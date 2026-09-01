# -*- coding: utf-8 -*-
"""R7 §34 测试:Candidate Grid(§13)与 Parameter Pack(§22)。

- grid:3-4 候选;historical control + R6 conservative 必在;
  非历史候选 D3 alpha∈[28,32];严格单调;只动 alpha/kappa;
  不含 R6 已证明 D3 margin 不足的 α<=26 方案;
- pack:payload/digest/roundtrip;R4 C1/C3-D3 继承;
  override 只影响指定 rung;历史键集冻结。
"""

from __future__ import annotations

import pytest

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_r7_param_pack import (
    C2_LADDER_CANDIDATES_R7,
    R6_DESIGN_PLAN_DIGEST,
    R4_PARAMETER_PACK_DIGEST,
    R4_SELECTED_C1_D3,
    R4_SELECTED_C3_D3,
    R7_PACK_VERSION,
    ladder_distance_from_historical_r7,
    ladder_pack_payload_r7,
    load_selected_pack,
    pack_digest_r7,
    r7_candidate_grid,
    r7_family_rung_params,
    validate_r7_grid_semantics,
    write_selected_pack_r7,
)


def test_grid_registration_and_bounds():
    assert validate_r7_grid_semantics() == []
    ids = list(C2_LADDER_CANDIDATES_R7)
    assert 3 <= len(ids) <= 4
    assert "c2l_historical_control" in ids
    assert "c2l_conservative" in ids
    for cid, ladder in C2_LADDER_CANDIDATES_R7.items():
        d3 = float(ladder["D3"]["alpha_bps"])
        if cid != "c2l_historical_control":
            assert 28.0 <= d3 <= 32.0, (cid, d3)
        # 只动 alpha/kappa:结构键与历史逐位一致
        for rung in ("D0", "D1", "D2", "D3"):
            hist = dict(C2_RUNG_PARAMS[rung])
            for k, v in ladder[rung].items():
                if k in ("alpha_bps", "wick_kappa"):
                    continue
                assert v == hist[k], (cid, rung, k)


def test_historical_control_is_frozen_default():
    cand = C2_LADDER_CANDIDATES_R7["c2l_historical_control"]
    for rung in ("D0", "D1", "D2", "D3"):
        assert cand[rung] == dict(C2_RUNG_PARAMS[rung])


def test_r4_frozen_candidates_match_spec():
    """C1-D3/C3-D3 继承值与任务书 §6 逐位一致。"""
    assert R4_SELECTED_C1_D3 == {
        "opp_drift_bps": 24.5, "neg_drift_bps": 16.0, "vol_bps": 26.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000}
    assert R4_SELECTED_C3_D3 == {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.20, 0.36, 0.44],
        "distractor_rate": 0.060}
    assert R4_PARAMETER_PACK_DIGEST.startswith("r4pk-")
    assert R6_DESIGN_PLAN_DIGEST.startswith("r6dp-")


def _pack_payload(**overrides):
    ladder = r7_candidate_grid()["c2l_conservative"]
    kwargs = dict(
        selected_c2_candidate="c2l_conservative",
        c2_ladder=ladder,
        selected_block_count=15,
        design_plan_digest="r7dp-" + "0" * 64,
        matched_contract_identity="r6ml-" + "0" * 64,
        block_integrity_identity="r6bt|n=15",
        cue_semantic_contract_digest="r7cue-" + "0" * 64,
        cue_semantic_rule_identity="r7csg-" + "0" * 64,
        cue_audit_digest="r7ca-" + "0" * 64,
        p_contract=0.937,
        recall_floor_value=0.917,
    )
    kwargs.update(overrides)
    return ladder_pack_payload_r7(**kwargs)


def test_pack_payload_digest_roundtrip(tmp_path):
    pack = _pack_payload()
    assert pack["pack_version"] == R7_PACK_VERSION
    assert pack["iteration"] == "r7"
    assert pack["p_contract"] == pytest.approx(0.937)
    assert pack["recall_floor"] == pytest.approx(0.917)
    d1 = pack_digest_r7(pack)
    assert d1.startswith("r7pk-")
    assert pack_digest_r7(pack) == d1
    tampered = dict(pack)
    tampered["c2_ladder"] = {
        **pack["c2_ladder"],
        "D3": {**pack["c2_ladder"]["D3"], "alpha_bps": 31.0}}
    assert pack_digest_r7(tampered) != d1
    path = write_selected_pack_r7(tmp_path, pack)
    assert path.is_file()
    loaded = load_selected_pack(tmp_path)
    assert loaded["digest"].startswith("r7pk-")
    # write 内部为副本补 digest 后落盘;重算与盘上一致(load 即验证)
    assert pack_digest_r7(loaded) == loaded["digest"]
    assert loaded["selected_block_count"] == 15


def test_pack_rejects_bad_block_count():
    with pytest.raises(RuntimeError):
        _pack_payload(selected_block_count=12)


def test_override_only_touches_expected_rungs():
    """override:C1/C3 只覆盖 D3;C2 四档;D0-D2 历史逐位不变。"""
    from rl_curriculum.curriculum261_r7_param_pack import (
        r7_override_for,
    )

    pack = _pack_payload()
    for family in ("c1_opportunity", "c3_cost"):
        ov = r7_override_for(family, pack)
        assert set(ov) == {"D3"}
    c2_ov = r7_override_for("c2_context", pack)
    assert set(c2_ov) == {"D0", "D1", "D2", "D3"}
    full = r7_family_rung_params("c1_opportunity", pack)
    for rung in ("D0", "D1", "D2"):
        assert rung in full
    ladder = r7_family_rung_params("c2_context", pack)
    for rung in ("D0", "D1", "D2", "D3"):
        assert ladder[rung] == pack["c2_ladder"][rung]


def test_ladder_distance_positive_for_modified():
    ladder = r7_candidate_grid()["c2l_conservative"]
    assert ladder_distance_from_historical_r7(ladder) > 0
    hist = r7_candidate_grid()["c2l_historical_control"]
    assert ladder_distance_from_historical_r7(hist) == pytest.approx(
        0.0)
