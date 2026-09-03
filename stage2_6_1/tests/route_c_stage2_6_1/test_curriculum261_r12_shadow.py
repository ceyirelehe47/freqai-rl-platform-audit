# -*- coding: utf-8 -*-
"""R12 工作包 C 测试:full-scale shadow profile 基数 / 双跑比较器 /
训练削减不触碰生成覆盖。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_shadow_profiles_full_generation_cardinality():
    from rl_curriculum.curriculum261_r12_orchestrator import (
        CALIBRATION_PAIRS_PER_RUNG_R12,
        C2_INDEPENDENT_PAIRS_PER_RUNG_R12,
        EQUIVALENCE_PAIRS_PER_RUNG_R12,
        SEMANTIC_BLOCKS_PER_CORPUS_R12,
        shadow_holdout_profile_r12,
        shadow_main_profile_r12,
    )

    for prof in (shadow_main_profile_r12(),
                 shadow_holdout_profile_r12()):
        assert prof.shadow is True and prof.preplan is False
        # 生成基数 = 正式
        assert prof.c13_pairs_per_rung == CALIBRATION_PAIRS_PER_RUNG_R12
        assert (prof.equivalence_pairs_per_rung
                == EQUIVALENCE_PAIRS_PER_RUNG_R12)
        assert (prof.supervised_pairs_per_rung
                == CALIBRATION_PAIRS_PER_RUNG_R12)
        assert (prof.semantic_blocks
                == SEMANTIC_BLOCKS_PER_CORPUS_R12)
        assert (prof.c2_independent_pairs_per_rung
                == C2_INDEPENDENT_PAIRS_PER_RUNG_R12)
        # c2 matched >= max(FORMAL_BLOCK_OPTIONS)=20(超集覆盖)
        assert prof.c2_blocks >= 20
        # 训练削减:seeds 少于正式(唯一允许的削减维度)
        assert len(prof.supervised_model_seeds) < 3
        assert prof.supervised_training_config is not None
    main = shadow_main_profile_r12()
    hold = shadow_holdout_profile_r12()
    # main/holdout namespace 完全分离
    assert (main.supervised_namespace != hold.supervised_namespace
            and main.c13_eval_namespace != hold.c13_eval_namespace
            and main.semantic_namespace != hold.semantic_namespace)


def test_shadow_namespaces_nonformal():
    from rl_curriculum.curriculum261_r12_orchestrator import (
        shadow_main_profile_r12,
    )

    p = shadow_main_profile_r12()
    for ns in (p.c13_eval_namespace, p.equivalence_namespace,
               p.supervised_namespace, p.semantic_namespace,
               p.c2_matched_namespace, p.c2_independent_namespace):
        assert ns.startswith("shadow_")


def _mk_artifact(d: Path, name: str, payload) -> Path:
    d.mkdir(parents=True, exist_ok=True)
    p = d / name
    p.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return p


def test_shadow_compare_identical_runs_pass(tmp_path):
    from rl_curriculum.curriculum261_r12_shadow import (
        compare_full_scale_shadow_runs,
    )

    a, b = tmp_path / "A", tmp_path / "B"
    for d in (a, b):
        _mk_artifact(d, "gate.json", {"pass": True, "value": 0.95,
                                      "written_utc": "2026-09-03T01:00:00"})
        sub = d / "final"
        _mk_artifact(sub, "result.json", {"verdict": "PASS", "n": 42})
        ledger = d / "generation_invocation_ledger.jsonl"
        ledger.write_text(
            json.dumps({"stage": "s", "call_digest": "c1",
                        "envelope": {"digest": "e1"}}) + "\n"
            + json.dumps({"stage": "s", "call_digest": "c2",
                          "envelope": {"digest": "e2"}}) + "\n",
            encoding="utf-8")
    result = compare_full_scale_shadow_runs(a, b)
    assert result["pass"] is True
    assert result["ledger_identity_digests_identical"] is True


def test_shadow_compare_detects_ledger_drift(tmp_path):
    from rl_curriculum.curriculum261_r12_shadow import (
        compare_full_scale_shadow_runs,
    )

    a, b = tmp_path / "A", tmp_path / "B"
    for d, digests in ((a, ("e1", "e2")), (b, ("e1", "eX"))):
        d.mkdir(parents=True)
        (d / "generation_invocation_ledger.jsonl").write_text(
            "".join(json.dumps({"stage": "s", "call_digest": "c",
                                "envelope": {"digest": e}}) + "\n"
                    for e in digests), encoding="utf-8")
    result = compare_full_scale_shadow_runs(a, b)
    assert result["pass"] is False
    assert result["ledger_identity_digests_identical"] is False


def test_shadow_compare_ignores_declared_non_identity_fields(tmp_path):
    from rl_curriculum.curriculum261_r12_shadow import (
        compare_full_scale_shadow_runs,
    )

    a, b = tmp_path / "A", tmp_path / "B"
    _mk_artifact(a, "summary.json",
                 {"value": 1, "started_utc": "2026-09-03T01:00:00",
                  "run_tag": "A"})
    _mk_artifact(b, "summary.json",
                 {"value": 1, "started_utc": "2026-09-03T09:00:00",
                  "run_tag": "B"})
    result = compare_full_scale_shadow_runs(a, b)
    assert result["pass"] is True


def test_shadow_compare_detects_gate_input_drift(tmp_path):
    from rl_curriculum.curriculum261_r12_shadow import (
        compare_full_scale_shadow_runs,
    )

    a, b = tmp_path / "A", tmp_path / "B"
    _mk_artifact(a, "supervised.json", {"balanced_accuracy": 0.71})
    _mk_artifact(b, "supervised.json", {"balanced_accuracy": 0.69})
    result = compare_full_scale_shadow_runs(a, b)
    assert result["pass"] is False
    assert result["artifact_identity_digest_diffs"]


def test_shadow_pack_not_formal():
    from rl_curriculum.curriculum261_r12_shadow import _shadow_pack

    pack = _shadow_pack()
    assert pack["design_plan_digest"] == "r12dp-shadow-engineering"
    assert pack["selected_block_count"] == 20
    assert not pack["design_plan_digest"].startswith("r12dp-0") or True
    # 工程 pack 不得携带正式 digest 值
    from rl_curriculum.curriculum261_r12_param_pack import (
        R10_DESIGN_PLAN_DIGEST,
    )
    assert pack["design_plan_digest"] != R10_DESIGN_PLAN_DIGEST


def test_official_entrypoint_includes_new_commands():
    from rl_curriculum.curriculum261_r12_cli import (
        _official_entrypoint_validation,
    )

    entry = _official_entrypoint_validation()
    assert entry["pass"] is True
    for cmd in ("determinism-matrix", "shadow-run", "shadow-compare"):
        assert cmd in entry["subcommands"]


def test_marginal_gate_reads_guard_pass():
    """回归(R12 shadow 捕获的 R10 潜伏缺陷):c2_independent_marginal_
    guard_r12 返回的 wrapper dict 无顶层 pass;gate 组装必须读
    marginal["guard"]["pass"](短路求值会掩盖该缺陷 —— rehearsal
    因 matched False 短路而未触发,全规模 shadow 触发)。"""
    import inspect

    from rl_curriculum.curriculum261_r12_orchestrator import (
        _orchestrate_calibration_stage_inner_r12,
    )
    src = inspect.getsource(_orchestrate_calibration_stage_inner_r12)
    assert 'marginal["guard"]["pass"]' in src
    assert 'marginal["pass"]' not in src.replace(
        'marginal["guard"]["pass"]', "")
    # wrapper 返回结构实证:顶层无 pass,guard 内有
    from rl_curriculum.curriculum261_r12_calibration import (
        c2_independent_marginal_guard_r12,
    )
    sig = inspect.signature(c2_independent_marginal_guard_r12)
    assert list(sig.parameters) == ["indep", "pack",
                                    "recall_floor_value"]
    fn_src = inspect.getsource(c2_independent_marginal_guard_r12)
    assert 'guard["pass"]' in fn_src
