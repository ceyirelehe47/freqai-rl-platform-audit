# -*- coding: utf-8 -*-
"""R9 §31 集成测试:candidate evaluator 全链路闭环与 artifact 显式映射。

R8 测试盲区的直接封堵(R8 的测试 monkeypatch 了
_evaluate_candidate_matched_r8,使函数体内的错误 import
c2_density_summary(r6_pairs)从未在测试中执行——直到正式 design
阶段 ImportError 爆发)。本文件的 evaluator 测试禁止任何 monkeypatch:
真实生成 matched blocks → 真实评估器全链 → 序列化/重载。
"""

from __future__ import annotations

import hashlib
import json

import pytest

from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS, FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r6_tape import (
    generate_matched_block_with_attempts,
)


# ------------------------------------------------ §6 依赖闭环
def test_c2_density_summary_symbol_origin_is_r5_pairs():
    """§6.2 硬断言:c2_density_summary 定义于 r5_pairs(R8 错误导入
    r6_pairs 的正式失败原因)。"""
    from rl_curriculum.curriculum261_r5_pairs import c2_density_summary
    # r6_pairs 根本没有该符号——这正是 R8 ImportError 的机制
    import rl_curriculum.curriculum261_r6_pairs as r6pairs

    assert not hasattr(r6pairs, "c2_density_summary")
    with pytest.raises(ImportError):
        from rl_curriculum.curriculum261_r6_pairs import (  # noqa: F401
            c2_density_summary as _broken,)


def test_dependency_resolution_table_full_pass():
    from rl_curriculum.curriculum261_r9_dependencies import (
        C2_DENSITY_SUMMARY_DEFINITION_MODULE,
        DEPENDENCY_TABLE_R9,
        resolve_dependency_identity_r9,
    )

    rep = resolve_dependency_identity_r9()
    assert rep["pass"], rep["problems"]
    assert rep["n_declared"] == len(DEPENDENCY_TABLE_R9)
    assert (rep["dependencies"]["c2_density_summary"]["resolved_module"]
            == C2_DENSITY_SUMMARY_DEFINITION_MODULE)
    for symbol, row in rep["dependencies"].items():
        assert row["resolved"] and row["callable"], symbol
        assert row["module_matches_declaration"], symbol
        assert row["source_file_sha256"], symbol
    assert rep["digest"].startswith("r9dep-")
    # 每个声明的 symbol 在 import 期可从声明模块取到
    import importlib

    for symbol, module in DEPENDENCY_TABLE_R9:
        assert hasattr(importlib.import_module(module), symbol), symbol


def test_r9_design_has_no_function_body_import_of_density():
    """§6.2:r9_design 的 evaluator 路径无函数内延迟 import(模块级
    解析;R8 缺陷的结构性回归测试)。"""
    import inspect

    import rl_curriculum.curriculum261_r9_design as r9design

    src = inspect.getsource(r9design)
    assert ("from rl_curriculum.curriculum261_r6_pairs import "
            "c2_density_summary") not in src
    for fn_name in ("_evaluate_candidate_matched_r9",
                    "_run_independent_marginal_guard"):
        body = inspect.getsource(getattr(r9design, fn_name))
        assert "import rl_curriculum" not in body, fn_name


# ------------------------------------------------ §7 真实 evaluator 集成
def test_real_candidate_evaluator_full_chain_no_monkeypatch(tmp_path):
    """§7/§31:不 monkeypatch 的完整 candidate 评估集成测试(plan lock
    的硬前置;R8 ImportError 的爆发路径)。"""
    from rl_curriculum.curriculum261_r9_design import (
        _evaluate_candidate_matched_r9,
    )

    ladder = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}
    thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
    blocks = [generate_matched_block_with_attempts(
        ladder, namespace="preplan_candidate_eval_r9", block_index=i)
        for i in range(2)]
    result = _evaluate_candidate_matched_r9(
        "integration_sentinel", ladder, "preplan_candidate_eval_r9",
        thresholds, blocks=blocks, n_blocks=2)
    assert result["n_blocks"] == 2
    assert set(result["difficulty_means"]) == {"D0", "D1", "D2", "D3"}
    assert set(result["per_formal_block_count"]) == {"10", "15", "20"}
    assert set(result["density_gates"]) == {"D0", "D1", "D2", "D3"}
    cue_sem = result["semantics"][
        "candidate_cue_semantics_r9_cluster_aware"]
    assert set(cue_sem["per_rung"]) == {"D0", "D1", "D2", "D3"}
    assert result["block_corpus_summary"]["n_blocks"] == 2
    assert result["block_attempt_stats"]
    # JSON 序列化 + 重载等价(canonical)
    blob = json.dumps(result, default=float, sort_keys=True)
    reloaded = json.loads(blob)
    assert reloaded["difficulty_means"] == result["difficulty_means"]


def test_preplan_evaluator_smoke_artifact(tmp_path):
    """§7:candidate_evaluator_integration_smoke 真实 artifact。"""
    from rl_curriculum.curriculum261_r9_preplan import (
        run_candidate_evaluator_integration_smoke_r9,
    )

    report = run_candidate_evaluator_integration_smoke_r9(
        tmp_path, n_blocks=2)
    assert report["pass"], report["checks"]
    assert report["monkeypatch_used"] is False
    on_disk = json.loads(
        (tmp_path / "candidate_evaluator_integration_smoke.json")
        .read_text(encoding="utf-8"))
    assert on_disk["pass"] is True
    assert on_disk["namespace"] == "preplan_candidate_eval_r9"


# ------------------------------------------------ §8 artifact 显式映射
def test_semantic_writer_explicit_mapping_no_suffix_heuristic(tmp_path):
    from rl_curriculum.curriculum261_r9_design import (
        SEMANTIC_ARTIFACT_MAP_R9,
        SEMANTIC_STAGE_ARTIFACT_MAP_R9,
        semantic_artifact_filename_r9,
        write_semantic_artifact_r9,
    )

    assert (semantic_artifact_filename_r9("cue_semantic_design_main_r9")
            == "semantic_design_main.json")
    assert (semantic_artifact_filename_r9(
        "cue_semantic_design_validation_r9")
        == "semantic_design_validation.json")
    # main/validation 永不写入同一个 path
    names = set(SEMANTIC_ARTIFACT_MAP_R9.values())
    assert len(names) == len(SEMANTIC_ARTIFACT_MAP_R9)
    # 三阶段映射同样穷尽且互不冲突
    all_names = names | set(SEMANTIC_STAGE_ARTIFACT_MAP_R9.values())
    assert len(all_names) == (len(SEMANTIC_ARTIFACT_MAP_R9)
                              + len(SEMANTIC_STAGE_ARTIFACT_MAP_R9))
    # 后缀启发式在 R9 的映射/writer 实现代码中不复存在(结构性回归
    # 测试;模块 docstring 保留对 R8 缺陷的历史说明属正常)
    import inspect

    from rl_curriculum.curriculum261_r9_design import (
        semantic_artifact_filename_r9 as _saf,
        write_semantic_artifact_r9 as _wsa,
    )

    assert ".endswith(" not in inspect.getsource(_saf)
    assert ".endswith(" not in inspect.getsource(_wsa)
    # 未知 namespace 立即报错
    with pytest.raises(RuntimeError, match="不在显式映射表"):
        semantic_artifact_filename_r9("cue_semantic_design_main")
    # exclusive create + embedded namespace + 双文件哈希不同
    p_main = write_semantic_artifact_r9(
        tmp_path, "cue_semantic_design_main_r9", {"marker": "m"},
        "r9dp-test", event_rows=[{"cue_bar": 1}])
    p_valid = write_semantic_artifact_r9(
        tmp_path, "cue_semantic_design_validation_r9",
        {"marker": "v"}, "r9dp-test", event_rows=[{"cue_bar": 1}])
    assert p_main.name == "semantic_design_main.json"
    assert p_valid.name == "semantic_design_validation.json"
    assert p_main.is_file() and p_valid.is_file()
    h1 = hashlib.sha256(p_main.read_bytes()).hexdigest()
    h2 = hashlib.sha256(p_valid.read_bytes()).hexdigest()
    assert h1 != h2
    back = json.loads(p_main.read_text(encoding="utf-8"))
    assert back["namespace"] == "cue_semantic_design_main_r9"
    assert back["corpus_role"] == "main"
    assert back["design_plan_digest"] == "r9dp-test"
    assert back["event_count"] == 1
    assert (tmp_path / "semantic_design_main.jsonl").is_file()
    # 覆盖尝试必须失败
    with pytest.raises((OSError, FileExistsError)):
        write_semantic_artifact_r9(
            tmp_path, "cue_semantic_design_main_r9", {"marker": "x"},
            "r9dp-test")


def test_semantic_writer_validation_artifact(tmp_path):
    from rl_curriculum.curriculum261_r9_preplan import (
        run_semantic_writer_validation_r9,
    )

    report = run_semantic_writer_validation_r9(tmp_path)
    assert report["pass"], report["checks"]
    on_disk = json.loads(
        (tmp_path / "semantic_artifact_writer_validation.json")
        .read_text(encoding="utf-8"))
    assert on_disk["pass"] is True


# ------------------------------------------------ §10 cue audit plan
def test_cue_audit_plan_lock_roundtrip_and_no_relock(tmp_path):
    from rl_curriculum.curriculum261_r9_cue_contract import (
        cue_audit_plan_digest_r9,
        cue_audit_plan_payload_r9,
        load_locked_cue_audit_plan_r9,
        lock_cue_audit_plan_r9,
    )

    path, digest = lock_cue_audit_plan_r9(tmp_path)
    assert digest.startswith("r9ap-")
    assert path.is_file()
    payload = load_locked_cue_audit_plan_r9(tmp_path)
    assert payload["cue_audit_plan_digest"] == digest
    assert payload["generation_mode"] == {"model": "once",
                                          "validation": "attempts"}
    assert payload["blocks_per_corpus"] == 500
    assert payload["monte_carlo"]["n_events"] == 1_000_000
    assert payload["noninferiority_delta"] == 0.02
    assert payload["absolute_minimum_recall"] == 0.90
    # digest 不自引用
    assert cue_audit_plan_digest_r9(payload) == digest
    # 重锁拒绝
    with pytest.raises(RuntimeError, match="禁止修改/重锁"):
        lock_cue_audit_plan_r9(tmp_path)
    # 篡改 → 复算失败
    tampered = dict(payload)
    tampered["blocks_per_corpus"] = 400
    (tmp_path / "cue_audit_plan.json").write_text(
        json.dumps(tampered, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(RuntimeError, match="复算不一致"):
        load_locked_cue_audit_plan_r9(tmp_path)


def test_cue_audit_requires_locked_plan_only_when_formal(tmp_path):
    from rl_curriculum.curriculum261_r9_cue_contract import (
        run_cue_contract_audit,
    )

    # 非正式(小规模)audit 不要求锁定 plan,且与锁定要求互斥
    with pytest.raises(RuntimeError,
                       match="非正式.*audit 不得要求锁定"):
        run_cue_contract_audit(
            tmp_path, blocks_per_corpus=2, mc_events=1000,
            model_namespace="preplan_smoke_r9",
            validation_namespace="preplan_candidate_eval_r9",
            require_locked_plan=True)


# ------------------------------------------------ §23 plan 前缀
def test_qualification_plan_digest_uses_qp9_prefix():
    from rl_curriculum.curriculum261_r9_plan import plan_digest_r9

    digest = plan_digest_r9({"probe": True})
    assert digest.startswith("qp9-") and len(digest) == 4 + 64
    assert not digest.startswith("qp7-")
    assert not digest.startswith("qp8-")


# ------------------------------------------------ §18/§34 治理文案
def test_next_round_wording_is_r10():
    """§23/§34:错误文案必须写"下一轮必须 R10",不得出现 R9.1。"""
    import inspect

    import rl_curriculum.curriculum261_r9_design as r9design
    import rl_curriculum.curriculum261_r9_namespaces as r9namespaces
    import rl_curriculum.curriculum261_r9_plan as r9plan

    for mod in (r9design, r9namespaces, r9plan):
        src = inspect.getsource(mod)
        assert "R9.1" not in src, mod.__name__
        assert "R9.1/R9" not in src, mod.__name__


def test_r8_namespaces_and_markers_not_referenced_by_r9_design_data():
    """§17:R9 全部 namespace 与 R8 零重合(字符串层与 seed 层)。"""
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_R8_NAMESPACES,
        CURRICULUM261_R9_NAMESPACES,
    )

    r8_set = set(CURRICULUM261_R8_NAMESPACES)
    r9_set = set(CURRICULUM261_R9_NAMESPACES)
    assert not (r8_set & r9_set)
    assert len(r9_set) == len(CURRICULUM261_R9_NAMESPACES) == 27
    for required in ("cue_contract_model_r9", "cue_contract_validation_r9",
                     "preplan_smoke_r9", "preplan_candidate_eval_r9",
                     "preplan_semantic_main_r9",
                     "preplan_semantic_validation_r9",
                     "cue_semantic_design_main_r9",
                     "cue_semantic_design_validation_r9",
                     "design_r9_matched_main", "design_r9_matched_validation",
                     "design_r9_independent_marginal",
                     "preprocess_fit_calibration_r9",
                     "preprocess_fit_holdout_r9",
                     "preprocess_fit_qualification_r9",
                     "cue_semantic_calibration_r9",
                     "cue_semantic_holdout_r9",
                     "cue_semantic_qualification_r9",
                     "calibration_r9", "calibration_holdout_r9",
                     "qualification_r9",
                     "c2_independent_calibration_r9",
                     "c2_independent_holdout_r9",
                     "c2_independent_qualification_r9",
                     "stress_r9", "fresh_holdout_r9", "training_r9",
                     "ppo_smoke_r9"):
        assert required in r9_set, required


def test_qualification_r9_seeds_locked_before_unlock(tmp_path,
                                                     monkeypatch):
    """§17/§24:qualification_r9 namespace 在六要素解锁前封闭。"""
    from rl_curriculum.curriculum261_api import derive261_seed

    monkeypatch.setenv("CURRICULUM261_R9_LOCK_DIR", str(tmp_path))
    for ns in ("qualification_r9", "preprocess_fit_qualification_r9",
               "c2_independent_qualification_r9",
               "cue_semantic_qualification_r9"):
        with pytest.raises(Exception, match="不可访问"):
            derive261_seed(ns, "c2_context", "D0", 0, 0)


# ------------------------------------------------ §9 rehearsal
def test_preplan_rehearsal_end_to_end(tmp_path):
    """§9:完整工程 rehearsal(真实 evaluator/writer/mini audit/
    marker;全部非正式 namespace)。"""
    from rl_curriculum.curriculum261_r9_preplan import (
        run_preplan_rehearsal_r9,
    )

    report = run_preplan_rehearsal_r9(tmp_path)
    assert report["pass"], json.dumps(
        {k: v for k, v in report["sections"].items() if not v},
        ensure_ascii=False)
    assert report["monkeypatch_used"] is False
    assert report["formal_namespaces_used"] is False
    assert report["rehearsal_digest"].startswith("r9pr-")
    assert (tmp_path / "preplan_end_to_end_rehearsal.json").is_file()
    assert (tmp_path / "candidate_evaluator_integration_smoke.json"
            ).is_file()
    assert (tmp_path / "semantic_artifact_writer_validation.json"
            ).is_file()
    det = report["detail"]["cue_audit_mini"]
    assert det["once_vs_attempts"]["first_pass_bitwise_check"][
        "bitwise_ok"]
