"""R4 测试:parameter pack(版本化 D3-only)+ 历史保留(§6/§33)。

- pack 只允许覆盖 C1/C3 的 D3;C2 与全部 D0-D2 逐位等于历史值;
- R0-R3 namespace 的 episode 生成不受 pack 影响(黄金哈希不变);
- pack digest 稳定且对参数敏感;
- override 只影响显式传入的生成调用(D3 档);D2 档不受影响。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r4_param_pack import (
    C1_D3_CANDIDATES,
    C3_D3_CANDIDATES,
    R4_OVERRIDE_RUNG,
    apply_r4_override,
    frozen_parameter_identity,
    pack_digest,
    pack_payload,
    r4_candidate_grid,
    r4_family_rung_params,
)

ARTIFACTS = Path(__file__).resolve().parents[2] / "artifacts"
R3_DIR = ARTIFACTS / "route_c_stage2_6_1_repair3"


def _pack():
    return pack_payload({
        "c1_opportunity": {"candidate": "c1_b_edge_up2",
                           "params": C1_D3_CANDIDATES["c1_b_edge_up2"]},
        "c3_cost": {"candidate": "c3_c_alpha_strong",
                    "params": C3_D3_CANDIDATES["c3_c_alpha_strong"]},
    })


# ------------------------------------------------------------- pack 结构
def test_pack_scope_d3_only():
    with pytest.raises(RuntimeError):
        pack_payload({"c2_context": {
            "candidate": "x", "params": dict(
                family_specs()["c2_context"].rung_params["D3"])}})


def test_pack_keys_must_match_history():
    bad = dict(C1_D3_CANDIDATES["c1_b_edge_up2"])
    bad.pop("distractor_rate")
    with pytest.raises(RuntimeError):
        pack_payload({"c1_opportunity": {"candidate": "bad",
                                         "params": bad}})


def test_pack_digest_stable_and_param_sensitive():
    p1, p2 = _pack(), _pack()
    assert pack_digest(p1) == pack_digest(p2)
    p3 = pack_payload({
        "c1_opportunity": {"candidate": "c1_a_edge_up",
                           "params": C1_D3_CANDIDATES["c1_a_edge_up"]},
        "c3_cost": {"candidate": "c3_c_alpha_strong",
                    "params": C3_D3_CANDIDATES["c3_c_alpha_strong"]}})
    assert pack_digest(p3) != pack_digest(p1)


def test_candidate_grid_preregistered_bounds():
    grid = r4_candidate_grid()
    assert 3 <= len(grid["c1_opportunity"]) <= 8
    assert 3 <= len(grid["c3_cost"]) <= 8
    # 候选必须仍来自 generator 已支持的参数集合(键集与历史一致)
    specs = family_specs()
    for fam, cands in grid.items():
        hist_keys = set(specs[fam].rung_params[R4_OVERRIDE_RUNG])
        for cid, params in cands.items():
            assert set(params) == hist_keys, (fam, cid)
    # 阶梯约束:opp/alpha 与 strong 份额必须低于 D2(保持 D3 更难)
    for cid, p in grid["c1_opportunity"].items():
        assert p["opp_drift_bps"] < specs["c1_opportunity"].rung_params[
            "D2"]["opp_drift_bps"], cid
    for cid, p in grid["c3_cost"].items():
        assert p["alpha_bps"] < specs["c3_cost"].rung_params["D2"][
            "alpha_bps"], cid
        assert p["mixture"][0] < specs["c3_cost"].rung_params["D2"][
            "mixture"][0], cid


# --------------------------------------------------------- 冻结参数面
def test_frozen_params_c2_and_d0_d2_unchanged_by_pack():
    pack = _pack()
    specs = family_specs()
    for family in ("c1_opportunity", "c2_context", "c3_cost"):
        merged = r4_family_rung_params(family, pack)
        for rung in CURRICULUM261_RUNGS:
            if family == "c2_context" or rung != R4_OVERRIDE_RUNG:
                assert merged[rung] == specs[family].rung_params[rung]
    # C1/C3 的 D3 被覆盖
    assert r4_family_rung_params("c1_opportunity", pack)["D3"] == \
        C1_D3_CANDIDATES["c1_b_edge_up2"]
    assert r4_family_rung_params("c3_cost", pack)["D3"] == \
        C3_D3_CANDIDATES["c3_c_alpha_strong"]
    # 冻结 identity 不含任何被覆盖面
    frozen = frozen_parameter_identity()["frozen"]
    assert "D3" not in frozen["c1_opportunity"]
    assert "D3" not in frozen["c3_cost"]
    assert set(frozen["c2_context"]) == set(CURRICULUM261_RUNGS)


def test_apply_override_returns_new_dict():
    pack = _pack()
    specs = family_specs()
    base = {r: dict(specs["c1_opportunity"].rung_params[r])
            for r in CURRICULUM261_RUNGS}
    merged = apply_r4_override("c1_opportunity", base, pack)
    assert base["D3"] == specs["c1_opportunity"].rung_params["D3"]
    assert merged["D3"] == pack["d3_overrides"]["c1_opportunity"]


# ------------------------------------------------------------ 历史保留
def test_r3_namespace_golden_episode_hash_unchanged():
    """calibration_r3 C1-D3 pair0 的 episode hash 与 R3 artifact 一致。"""
    summary_path = R3_DIR / "calibration_summary.json"
    if not summary_path.is_file():
        pytest.skip("R3 calibration artifact 不存在")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    rec = generate_pair("c1_opportunity", "D3", 0,
                        namespace="calibration_r3")
    for side in ("A", "B"):
        rows = [e for e in summary["families"]["c1_opportunity"]
                ["by_rung"]["D3"]["episodes"]
                if e["pair"] == 0 and e["side"] == side]
        assert rows, side
        assert rows[0]["episode_hash"] == \
            rec.attempt_log.episode_hashes[side]


def test_override_only_changes_d3_not_d2():
    ov = {"D3": dict(C1_D3_CANDIDATES["c1_b_edge_up2"])}
    with_ov = generate_pair("c1_opportunity", "D2", 0,
                            namespace="design_r4",
                            rung_params_override=ov)
    without = generate_pair("c1_opportunity", "D2", 0,
                            namespace="design_r4")
    d3_ov = generate_pair("c1_opportunity", "D3", 0,
                          namespace="design_r4",
                          rung_params_override=ov)
    d3_plain = generate_pair("c1_opportunity", "D3", 0,
                             namespace="design_r4")
    assert with_ov.attempt_log.episode_hashes["A"] == \
        without.attempt_log.episode_hashes["A"]
    assert d3_ov.attempt_log.episode_hashes["A"] != \
        d3_plain.attempt_log.episode_hashes["A"]
    assert with_ov.integrity_ok and d3_ov.integrity_ok


def test_r2_qualification_golden_hash_unchanged():
    """qualification_r2 C3-D3 pair0 与 R2 final raw 记录一致
    (pack/R4 代码不影响 R2 namespace 派生)。"""
    raw_path = (ARTIFACTS / "route_c_stage2_6_1_repair2"
                / "qualification_raw.json")
    if not raw_path.is_file():
        pytest.skip("R2 qualification raw 不存在")
    raw = json.loads(raw_path.read_text(encoding="utf-8"))
    recs = [r for r in raw.get("c3_cost", [])
            if r.get("rung") == "D3" and r.get("pair_index") == 0]
    if not recs:
        pytest.skip("R2 raw 无 c3 D3 pair0 记录")
    hashes = recs[0]["attempt_log"]["output_episode_hashes"]
    rec = generate_pair("c3_cost", "D3", 0,
                        namespace="qualification_r2")
    assert rec.attempt_log.episode_hashes == hashes
