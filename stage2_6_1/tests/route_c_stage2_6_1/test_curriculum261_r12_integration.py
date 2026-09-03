# -*- coding: utf-8 -*-
"""R12 集成测试:tiny supervised 全链(R12 runner + 修复后的两个
gate 真实接线;§12 类别 26/28 的 R12 侧)。"""

from __future__ import annotations

import numpy as np
import pytest


@pytest.fixture(scope="module")
def tiny_supervised():
    from rl_curriculum.curriculum261_pairs import generate_pair
    from rl_curriculum.curriculum261_r12_calibration import (
        fit_preprocessor_v2_from_bank_r12,
        generate_fit_bank_r12,
        supervised_learnability_run_r12,
    )
    from rl_curriculum.curriculum261_r12_shadow import _shadow_pack

    pack = _shadow_pack()
    bank = generate_fit_bank_r12("preplan_fit_main_r12", pack,
                                 pairs_per_rung=1)
    v2, _ = fit_preprocessor_v2_from_bank_r12(
        "preplan_fit_main_r12", pack, records=bank, pairs_per_rung=1,
        parameter_pack_identity=pack["digest"])
    result = supervised_learnability_run_r12(
        v2, pack,
        namespace="preplan_supervised_main_r12",
        pairs_per_rung=2,
        train_pair_limit=1,
        model_seeds=(20261131, 20261132, 20261133),
        training_config={"epochs": 2})
    return result, pack


def test_tiny_supervised_runs_all_three_families(tiny_supervised):
    result, _ = tiny_supervised
    assert set(result["families"]) == {
        "c1_opportunity", "c2_context", "c3_cost"}


def test_alignment_aggregation_wired(tiny_supervised):
    result, _ = tiny_supervised
    for fam, block in result["families"].items():
        assert "alignment_ok" in result["label_alignment"][fam]
        assert fam in result["dataset_identity"]
    assert result["alignment_all_ok"] is True


def test_distinct_seed_gate_wired_and_recomputed(tiny_supervised):
    """独立复算 distinct-seed gate(不信任自报 pass)。"""
    result, _ = tiny_supervised
    from rl_curriculum.curriculum261_r12_orchestrator import (
        R12_SUPERVISED_GATE,
    )
    for fam, block in result["families"].items():
        gate = block["distinct_seed_gate"]
        # 逐 seed W/B 结果重放机械计算
        per_seed = gate["per_seed_wb_results"]
        for control in ("W", "B"):
            ids = {int(s) for s, wb in per_seed.items()
                   if wb.get(control)}
            assert set(gate["passing_seed_ids_by_control"][
                control]) == ids
            expect = len(ids) >= R12_SUPERVISED_GATE["min_seeds_passing"]
            assert gate["control_pass"][control] == expect
        recomputed = all(gate["control_pass"].values())
        assert block["pass"] == recomputed
        # U 不进入计数:passing_seed_ids_by_control 只含 W/B
        assert set(gate["passing_seed_ids_by_control"]) == {"W", "B"}


def test_supervised_runner_keyword_only():
    import inspect

    from rl_curriculum.curriculum261_r12_calibration import (
        supervised_learnability_run_r12,
    )
    sig = inspect.signature(supervised_learnability_run_r12)
    for name in ("namespace", "pairs_per_rung", "train_pair_limit",
                 "model_seeds", "training_config"):
        assert sig.parameters[name].kind is inspect.Parameter.KEYWORD_ONLY


def test_recorder_sink_active_during_orchestration():
    """orchestrate 打开 envelope sink(AST/源码级;不实跑)。"""
    import inspect

    from rl_curriculum.curriculum261_r12_orchestrator import (
        orchestrate_calibration_stage_r12,
    )
    src = inspect.getsource(orchestrate_calibration_stage_r12)
    assert "envelope_sink" in src and "ledger_sink_factory" in src
    from rl_curriculum.curriculum261_r12_final import (
        execute_final_core_r12,
    )
    src2 = inspect.getsource(execute_final_core_r12)
    assert "envelope_sink" in src2
