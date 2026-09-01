# -*- coding: utf-8 -*-
"""R6 §38 测试:param pack(§17/§23)——R4 继承/键集/ladder 语义/
digest/selected_block_count 合同。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_r6_param_pack import (
    C2_LADDER_CANDIDATES,
    R4_PARAMETER_PACK_DIGEST,
    R5_DESIGN_PLAN_DIGEST,
    ladder_distance_from_historical,
    ladder_pack_payload,
    load_selected_pack,
    pack_digest,
    r6_candidate_grid,
    r6_family_rung_params,
    r6_override_for,
    validate_ladder_semantics,
    verify_r4_inheritance,
    write_selected_pack,
)
from rl_curriculum.curriculum261_r6_tape import (
    matched_ladder_contract_identity,
)


def test_grid_locked_eight_candidates():
    grid = r6_candidate_grid()
    assert len(grid) == 8
    assert "c2l_historical_control" in grid
    for cand in grid.values():
        assert not validate_ladder_semantics(cand)


def test_ladder_semantics_rejects_bad():
    bad = {r: dict(C2_RUNG_PARAMS[r]) for r in ("D0", "D1", "D2", "D3")}
    bad["D1"]["alpha_bps"] = 90.0  # 破坏单调
    assert validate_ladder_semantics(bad)
    bad2 = {r: dict(C2_RUNG_PARAMS[r]) for r in ("D0", "D1", "D2", "D3")}
    bad2["D2"]["vol_bps"] = 99.0  # 键集内但值变化(语义函数不查;结构由
    # _c2_ladder 构造器拒绝)
    assert not validate_ladder_semantics(bad2)


def test_c2_ladder_builder_rejects_structure_keys():
    from rl_curriculum.curriculum261_r6_param_pack import _c2_ladder

    with pytest.raises(RuntimeError, match="难度键"):
        _c2_ladder(D0={"vol_bps": 25.0})


def test_pack_keyset_matches_historical(tmp_path):
    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    for rung in ("D0", "D1", "D2", "D3"):
        assert set(ladder[rung]) == set(C2_RUNG_PARAMS[rung])
        # 结构参数逐位冻结
        for k in ("payoff_bars", "vol_bps", "cue_rate", "dir_len_range",
                  "width_len_range", "pulse_bps", "wick_base_bps",
                  "wide_wick_bps", "narrow_wick_bps"):
            assert ladder[rung][k] == C2_RUNG_PARAMS[rung][k]


def test_pack_payload_and_digest_roundtrip(tmp_path):
    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_balanced", c2_ladder=ladder,
        selected_block_count=15,
        design_plan_digest="r6dp-test",
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity="bi-test",
        candidate_evidence={"score": 3.2}, baseline_commit="40a0d9a")
    assert pack["selected_block_count"] == 15
    assert pack["r4_parameter_pack_digest"] == R4_PARAMETER_PACK_DIGEST
    assert pack["r5_design_plan_digest"] == R5_DESIGN_PLAN_DIGEST
    d1 = pack_digest(pack)
    assert d1.startswith("r6pk-")
    # digest 自排除(created_utc/digest 不影响)
    pack["created_utc"] = "2026-09-01T00:00:00+00:00"
    assert pack_digest(pack) == d1
    path = write_selected_pack(tmp_path, pack)
    loaded = load_selected_pack(tmp_path)
    assert loaded["digest"] == pack_digest(loaded)
    # 篡改拒绝
    loaded2 = json.loads(path.read_text(encoding="utf-8"))
    loaded2["c2_ladder"]["D3"]["alpha_bps"] = 99.0
    (tmp_path / "r6_parameter_pack.json").write_text(
        json.dumps(loaded2), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest"):
        load_selected_pack(tmp_path)


def test_selected_block_count_options_only():
    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    for n in (10, 15, 20):
        p = ladder_pack_payload(
            selected_c2_candidate="x", c2_ladder=ladder,
            selected_block_count=n, design_plan_digest="d",
            matched_contract_identity="m", block_integrity_identity="b")
        assert p["selected_block_count"] == n
    with pytest.raises(RuntimeError, match=r"\{10,15,20\}"):
        ladder_pack_payload(
            selected_c2_candidate="x", c2_ladder=ladder,
            selected_block_count=30, design_plan_digest="d",
            matched_contract_identity="m", block_integrity_identity="b")


def test_override_scope_and_family_params():
    ladder = C2_LADDER_CANDIDATES["c2l_conservative"]
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_conservative", c2_ladder=ladder,
        selected_block_count=10, design_plan_digest="d",
        matched_contract_identity="m", block_integrity_identity="b")
    c2 = r6_family_rung_params("c2_context", pack)
    for rung in ("D0", "D1", "D2", "D3"):
        assert c2[rung]["alpha_bps"] == ladder[rung]["alpha_bps"]
        assert c2[rung]["wick_kappa"] == ladder[rung]["wick_kappa"]
    # C1/C3:仅 D3 覆盖,D0-D2 历史
    from rl_curriculum.curriculum261_pairs import family_specs

    for family in ("c1_opportunity", "c3_cost"):
        params = r6_family_rung_params(family, pack)
        hist = family_specs()[family].rung_params
        for rung in ("D0", "D1", "D2"):
            assert params[rung] == dict(hist[rung])
        assert params["D3"] == pack["d3_overrides"][family]


def test_verify_r4_inheritance_full(pack=None):
    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_balanced", c2_ladder=ladder,
        selected_block_count=10, design_plan_digest="d",
        matched_contract_identity="m", block_integrity_identity="b")
    v = verify_r4_inheritance(pack)
    assert v["pass"], v


def test_distance_ladder():
    assert ladder_distance_from_historical(
        C2_LADDER_CANDIDATES["c2l_historical_control"]) == 0.0
    assert ladder_distance_from_historical(
        C2_LADDER_CANDIDATES["c2l_balanced"]) > 0.0
