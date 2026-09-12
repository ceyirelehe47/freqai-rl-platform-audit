"""R5 测试:parameter pack(R4 继承黄金绑定/Tier 结构/override 范围/
冻结面/digest 自排除)(§34)。

- C1/C3 D3 继承值逐位等于任务书 §6 常量与 R4 pack artifact(若存在,
  含 r4pk-eca9... digest 复算);
- Tier A/B 候选键集与历史 D3/D2 完全一致,仅动授权键;
- r5_override_for 只影响 override 范围(C2-D0/D1 逐位不变);
- pack digest 排除 created_utc 与 digest 自身;
- frozen_parameter_identity_r5 的 tier 相关冻结面。
"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r5_param_pack import (
    C2_TIER_A_CANDIDATES,
    C2_TIER_B_CANDIDATES,
    R4_PARAMETER_PACK_DIGEST,
    R4_SELECTED_C1_D3,
    R4_SELECTED_C3_D3,
    apply_r5_override,
    frozen_parameter_identity_r5,
    ladder_pack_payload,
    pack_digest,
    param_distance_from_historical,
    r5_override_for,
    verify_r4_inheritance,
)


def test_r4_inherited_params_golden():
    """任务书 §6 常量逐位锁定(C1/C3 D3 继承值)。"""
    assert R4_SELECTED_C1_D3 == {
        "opp_drift_bps": 24.5, "neg_drift_bps": 16.0, "vol_bps": 26.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000,
    }
    assert R4_SELECTED_C3_D3 == {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.20, 0.36, 0.44],
        "distractor_rate": 0.060,
    }
    assert R4_PARAMETER_PACK_DIGEST == (
        "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722"
        "ac5aac8e6d764f99")


def test_tier_grid_key_sets_match_historical():
    hist_d3 = set(C2_RUNG_PARAMS["D3"])
    hist_d2 = set(C2_RUNG_PARAMS["D2"])
    assert set(hist_d3) == set(hist_d2)
    for cand in C2_TIER_A_CANDIDATES.values():
        assert set(cand) == hist_d3
        assert cand["alpha_bps"] < C2_RUNG_PARAMS["D2"]["alpha_bps"]
        assert cand["wick_kappa"] <= C2_RUNG_PARAMS["D2"]["wick_kappa"]
        assert cand["payoff_bars"] == 1
        assert cand["cue_rate"] == C2_RUNG_PARAMS["D3"]["cue_rate"]
    for cand in C2_TIER_B_CANDIDATES.values():
        assert set(cand["D3"]) == hist_d3
        assert set(cand["D2"]) == hist_d2
        assert cand["D2"]["alpha_bps"] < C2_RUNG_PARAMS["D1"]["alpha_bps"]
        assert cand["D2"]["wick_kappa"] < C2_RUNG_PARAMS["D1"][
            "wick_kappa"]


def _pack_tier_a():
    return ladder_pack_payload(
        tier="A", selected_c2_candidate="c2_a_alpha26_vol16",
        c2_d3_params=dict(C2_TIER_A_CANDIDATES["c2_a_alpha26_vol16"]),
        design_plan_digest="r5dp-test")


def _pack_tier_b():
    cand = C2_TIER_B_CANDIDATES["c2b_1_d2up42_d3down25"]
    return ladder_pack_payload(
        tier="B", selected_c2_candidate="c2b_1_d2up42_d3down25",
        c2_d3_params=dict(cand["D3"]), c2_d2_params=dict(cand["D2"]),
        design_plan_digest="r5dp-test")


def test_pack_digest_excludes_created_utc_and_self():
    pack = _pack_tier_a()
    d1 = pack_digest(pack)
    pack["created_utc"] = "2099-01-01T00:00:00+00:00"
    d2 = pack_digest(pack)
    assert d1 == d2 and d1.startswith("r5pk-")
    pack2 = dict(pack)
    pack2["digest"] = "r5pk-should-not-self-reference"
    assert pack_digest(pack2) == d1


def test_pack_override_scope():
    pack_a = _pack_tier_a()
    assert r5_override_for("c1_opportunity", pack_a) == {
        "D3": dict(R4_SELECTED_C1_D3)}
    assert r5_override_for("c3_cost", pack_a) == {
        "D3": dict(R4_SELECTED_C3_D3)}
    ov = r5_override_for("c2_context", pack_a)
    assert set(ov) == {"D3"}

    pack_b = _pack_tier_b()
    ov_b = r5_override_for("c2_context", pack_b)
    assert set(ov_b) == {"D2", "D3"}

    specs = family_specs()["c2_context"]
    base = {r: dict(specs.rung_params[r])
            for r in ("D0", "D1", "D2", "D3")}
    applied = apply_r5_override("c2_context", base, pack_a)
    assert applied["D0"] == base["D0"] and applied["D1"] == base["D1"]
    assert applied["D2"] == base["D2"]
    assert applied["D3"] == ov["D3"]


def test_override_does_not_touch_frozen_rungs():
    """override 范围之外的 rung episode 逐位不变(R5 namespace 内)。"""
    pack = _pack_tier_a()
    ov = r5_override_for("c2_context", pack)
    r_hist = generate_pair("c2_context", "D2", 3,
                           namespace="ppo_smoke_r5")
    r_ov = generate_pair("c2_context", "D2", 3, namespace="ppo_smoke_r5",
                         rung_params_override=ov)
    for side in ("A", "B"):
        assert r_hist.episodes[side].df.equals(r_ov.episodes[side].df)
        assert r_hist.episodes[side].hidden.equals(
            r_ov.episodes[side].hidden)


def test_frozen_identity_scope_by_tier():
    id_a = frozen_parameter_identity_r5("A")
    id_b = frozen_parameter_identity_r5("B")
    assert set(id_a["frozen"]["c2_context"]) == {"D0", "D1", "D2"}
    assert set(id_b["frozen"]["c2_context"]) == {"D0", "D1"}
    for fam in ("c1_opportunity", "c3_cost"):
        assert set(id_a["frozen"][fam]) == {"D0", "D1", "D2"}
        assert set(id_b["frozen"][fam]) == {"D0", "D1", "D2"}
    assert id_a["identity"] != id_b["identity"]
    assert id_a["identity"].startswith("r5fp-")


def test_verify_r4_inheritance(monkeypatch, tmp_path):
    """继承验证:常量一致 + (若 R4 artifact 存在)digest 复算一致。"""
    pack = _pack_tier_a()
    rep = verify_r4_inheritance(pack)
    assert rep["pass"] is True

    # 破坏继承值 -> 拒绝
    broken = json.loads(json.dumps(pack))
    broken["d3_overrides"]["c1_opportunity"]["opp_drift_bps"] = 99.0
    assert verify_r4_inheritance(broken)["pass"] is False


def test_param_distance_tiebreaker():
    hist = dict(C2_RUNG_PARAMS["D3"])
    near = dict(hist, alpha_bps=31.0)
    far = dict(hist, alpha_bps=25.0, vol_bps=15.0)
    assert param_distance_from_historical(near, hist) < \
        param_distance_from_historical(far, hist)
    assert param_distance_from_historical(hist, hist) == 0.0


def test_pack_payload_rejects_bad_keyset():
    bad = dict(C2_TIER_A_CANDIDATES["c2_a_alpha26_vol16"])
    bad.pop("pulse_bps")
    with pytest.raises(RuntimeError):
        ladder_pack_payload(
            tier="A", selected_c2_candidate="bad",
            c2_d3_params=bad, design_plan_digest="r5dp-test")
