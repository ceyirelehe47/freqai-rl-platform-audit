# -*- coding: utf-8 -*-
"""R10 §36 测试:parameter pack(§17/§27)——恰好 3 候选、digest
roundtrip、160 语义块绑定、R7 历史 digest 绑定。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_r10_param_pack import (
    C2_LADDER_CANDIDATES_R10,
    R7_DESIGN_PLAN_DIGEST,
    R10_PACK_VERSION,
    ladder_pack_payload_r10,
    ladder_distance_from_historical_r10,
    load_selected_pack,
    pack_digest_r10,
    r10_candidate_grid,
    validate_r10_grid_semantics,
    write_selected_pack_r10,
)


def test_grid_exactly_three_candidates():
    assert len(C2_LADDER_CANDIDATES_R10) == 3
    assert validate_r10_grid_semantics() == []
    ids = set(C2_LADDER_CANDIDATES_R10)
    assert ids == {"c2l_historical_control", "c2l_conservative",
                   "c2l_midpoint"}
    # D3 alpha 覆盖 28/30/32
    d3 = {float(v["D3"]["alpha_bps"]) for v in
          C2_LADDER_CANDIDATES_R10.values()}
    assert d3 == {28.0, 30.0, 32.0}
    # 网格深拷贝(修改副本不影响预注册网格)
    grid = r10_candidate_grid()
    grid.pop("c2l_midpoint")
    assert len(C2_LADDER_CANDIDATES_R10) == 3


def test_grid_forbidden_fourth_candidate_rejected():
    import rl_curriculum.curriculum261_r10_param_pack as mod

    original = dict(mod.C2_LADDER_CANDIDATES_R10)
    try:
        mod.C2_LADDER_CANDIDATES_R10["c2l_extra"] = dict(
            original["c2l_midpoint"])
        problems = validate_r10_grid_semantics()
        assert any("恰好 3" in p for p in problems)
    finally:
        mod.C2_LADDER_CANDIDATES_R10.clear()
        mod.C2_LADDER_CANDIDATES_R10.update(original)


def test_pack_digest_roundtrip_and_write(tmp_path):
    ladder = r10_candidate_grid()["c2l_midpoint"]
    pack = ladder_pack_payload_r10(
        selected_c2_candidate="c2l_midpoint",
        c2_ladder=ladder,
        selected_block_count=15,
        design_plan_digest="r10dp-" + "a" * 64,
        matched_contract_identity="r6ml-x",
        block_integrity_identity="bt-x",
        cue_semantic_contract_digest="r10cue-x",
        cue_semantic_rule_identity="r10csg-x",
        cue_audit_digest="r10ca-x",
        p_contract=0.9509,
        recall_floor_value=0.9309,
        noninferiority_delta=0.02,
        semantic_blocks_per_corpus=160,
        baseline_commit="11951f6d",
    )
    assert pack["pack_version"] == R10_PACK_VERSION
    assert pack["r7_design_plan_digest"] == R7_DESIGN_PLAN_DIGEST
    assert R7_DESIGN_PLAN_DIGEST.startswith("r7dp-73d65b68")
    # §R10:R8 失败证据链绑定(R8 ImportError → §8.4 永久结束)
    from rl_curriculum.curriculum261_r10_param_pack import (
        R8_DESIGN_PLAN_DIGEST as R8DP,
    )

    assert pack["r8_design_plan_digest"] == R8DP
    assert R8DP.startswith("r8dp-60bb85d5")
    # R10:R9 诚实 FAIL 证据链绑定(design 证据仅 development evidence)
    from rl_curriculum.curriculum261_r10_param_pack import (
        R9_DESIGN_PLAN_DIGEST as R9DP,
        R9_PARAMETER_PACK_DIGEST as R9PK,
    )

    assert pack["r9_design_plan_digest"] == R9DP
    assert R9DP.startswith("r9dp-83d4d3b7")
    assert R9PK.startswith("r9pk-c3070b5b")
    assert pack["semantic_blocks_per_corpus"] == 160
    d1 = pack_digest_r10(pack)
    pack["digest"] = d1
    assert pack_digest_r10(pack) == d1  # digest 不自引用
    write_selected_pack_r10(tmp_path, pack)
    loaded = load_selected_pack(tmp_path)
    assert loaded["digest"] == d1
    assert loaded["selected_block_count"] == 15
    # 篡改 payload → 复算失败
    tampered = json.loads(
        (tmp_path / "r10_parameter_pack.json").read_text(encoding="utf-8"))
    tampered["selected_block_count"] = 20
    (tmp_path / "r10_parameter_pack.json").write_text(
        json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="digest 复算不一致"):
        load_selected_pack(tmp_path)


def test_pack_enforces_160_semantic_blocks():
    ladder = r10_candidate_grid()["c2l_conservative"]
    with pytest.raises(RuntimeError, match="160"):
        ladder_pack_payload_r10(
            selected_c2_candidate="c2l_conservative",
            c2_ladder=ladder,
            selected_block_count=10,
            design_plan_digest="r10dp-x",
            matched_contract_identity="m",
            block_integrity_identity="b",
            cue_semantic_contract_digest="c",
            cue_semantic_rule_identity="r",
            cue_audit_digest="a",
            p_contract=0.95, recall_floor_value=0.93,
            noninferiority_delta=0.02,
            semantic_blocks_per_corpus=240)  # 禁止扩样


def test_distance_from_historical_zero_for_control():
    hist = r10_candidate_grid()["c2l_historical_control"]
    assert ladder_distance_from_historical_r10(hist) == 0.0
    cons = r10_candidate_grid()["c2l_conservative"]
    assert ladder_distance_from_historical_r10(cons) > 0.0
