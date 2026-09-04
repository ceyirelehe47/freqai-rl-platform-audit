# -*- coding: utf-8 -*-
"""R14 治理测试:HistoricalEvidenceBinding(R14 版)/R12 abort binding/
freeze 治理/rt 路由合同/sealed preflight 证据文件名对齐/generation
evidence completeness(§四-2/§四-5)。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r14_generation_evidence import (
    BlockAttemptSummary,
    ExpectedCall,
    verify_generation_evidence_completeness,
)
from rl_curriculum.curriculum261_r14_historical import (
    R11_COMMIT_A,
    R11_COMMIT_A_PRIME,
    R12_COMMIT_A,
    R12_COMMIT_B,
    R14_EXPECTED_BASELINE,
    historical_evidence_binding, R13_COMMIT_A, R13_COMMIT_B)


def _release_repo() -> Path | None:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            return cand
    return None


# ------------------------------------------------ generation evidence
def _env(namespace="stress_r14", family="c3_cost", rung="D0", pair=0,
         attempt=0, accepted=True, digest=None, call_digest="cd-1"):
    return {
        "stage": "s", "iteration": "r14", "call_digest": call_digest,
        "envelope": {
            "iteration": "r14", "namespace": namespace,
            "family": family, "rung": rung, "pair_index": pair,
            "attempt_index": attempt, "outer_seed": 12345,
            "accepted": accepted,
            "digest": digest or "x" * 64,
        },
    }


EXPECTED = [ExpectedCall("stress_r14", "c3_cost", "D0", 0)]


def test_generation_evidence_complete_pass():
    rows = [_env(attempt=0, accepted=False), _env(attempt=1, accepted=True)]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert r["pass"], r["problems_sample"]
    assert r["observed_call_invocations"] == 1
    assert r["iteration"] == "r14"


def test_generation_evidence_missing_rejected():
    rows = [_env(namespace="other_r14")]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]
    assert r["missing_calls"] == 1


def test_generation_evidence_same_coordinate_two_legal_calls():
    calls = [ExpectedCall("calibration_r14", "c1_opportunity", "D0", 0),
             ExpectedCall("calibration_r14", "c1_opportunity", "D0", 0)]
    rows = [
        _env(namespace="calibration_r14", family="c1_opportunity",
             rung="D0", pair=0, attempt=0, accepted=True,
             call_digest="cd-eval"),
        _env(namespace="calibration_r14", family="c1_opportunity",
             rung="D0", pair=0, attempt=0, accepted=True,
             call_digest="cd-c13"),
    ]
    r = verify_generation_evidence_completeness(
        None, calls, stage_label="s", ledger_rows_override=rows)
    assert r["pass"], r["problems_sample"]
    assert r["observed_call_invocations"] == 2


def test_generation_evidence_iteration_mismatch_rejected():
    rows = [_env(attempt=0, accepted=False), _env(attempt=1, accepted=True)]
    rows[1]["envelope"]["iteration"] = "r12"
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]


# ------------------------------------------------ historical binding
@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestHistoricalEvidenceBindingR14:
    def test_ancestry_and_r13_clean_chain(self):
        repo = _release_repo()
        binding = historical_evidence_binding(repo)
        assert binding["expected_baseline"] == R14_EXPECTED_BASELINE
        assert R14_EXPECTED_BASELINE == (
            "b8e1de05cc3040ddc81634eb36d735a9fe3483da")
        assert R13_COMMIT_A == (
            "47d3f22f4df97855423ee748f3aa2df5497422a6")
        assert R13_COMMIT_B == R14_EXPECTED_BASELINE
        assert binding["checks"]["baseline_commit_exists"] is True
        assert binding["checks"]["r12_clean_two_commit_chain"] is True
        assert binding["checks"]["r13_clean_two_commit_chain"] is True
        assert binding["checks"]["r13_exposure_terminal_failed"] is True
        assert binding["checks"]["r13_failed_checks_only_c2_semantics"] is True
        assert binding["checks"]["r13_commit_b_contains_runner_py"] is True
        assert binding["checks"]["r13_raw_logs_incomplete"] is True
        assert binding["checks"]["r13_plan_digest_qp12_prefix"] is True
        assert binding["ok"] is True, binding["failed_checks"]
        gaps = binding["r13_governance_binding"]["r13_governance_gaps"]
        assert gaps["plan_digest_prefix"] == "qp12-"
        assert gaps["full_cold_reader_rehearsal_absent"] is True

    def test_r11_chain_anchors_retained(self):
        assert R11_COMMIT_A == (
            "df0292ac2208375cca478b037c4ba87c6808911e")
        assert R11_COMMIT_A_PRIME == (
            "572c509233fef560a39ea30cd497a34053d47ce0")
        repo = _release_repo()
        binding = historical_evidence_binding(repo)
        assert binding["checks"]["r11_a_ancestor_of_a_prime"] is True
        assert binding["checks"][
            "r11_clean_chain_invalidated_by_a_prime"] is True


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestR12AbortBinding:
    def test_binding_passes_against_real_repo(self, tmp_path):
        from rl_curriculum.curriculum261_r14_cli import _r12_abort_binding

        binding = _r12_abort_binding(tmp_path)
        assert binding["pass"] is True
        assert binding["qualification_plan_never_locked"] is True
        assert binding["qualification_exposure_absent"] is True
        assert (tmp_path / "r12_abort_binding.json").is_file()
        doc = json.loads(
            (tmp_path / "r12_abort_binding.json").read_text(
                encoding="utf-8"))
        assert doc["failure_classification"].startswith(
            "producer/consumer artifact interface inconsistency")

    def test_audit_writes_r12_failure_binding(self, tmp_path):
        """cmd_audit 的 r12_iteration_failure_binding.json 内容锁。"""
        src = Path(
            __file__).resolve().parents[2] / "src" / "rl_curriculum" / (
                "curriculum261_r14_cli.py")
        text = src.read_text(encoding="utf-8")
        assert "r12_iteration_failure_binding.json" in text
        assert "preprocessor_bundle_hash" in text
        assert "KeyError: 'bundle_hash'" in text


@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestR13FailureBinding:
    def test_binding_passes_against_real_repo(self, tmp_path):
        from rl_curriculum.curriculum261_r14_cli import _r13_failure_binding

        binding = _r13_failure_binding(tmp_path)
        assert binding["pass"] is True
        assert binding["failed_checks"] == ["c2_semantics_pass"]
        assert binding["exposure_terminal_failed"] is True
        assert binding["remains_permanent_fail"] is True
        assert len(binding["governance_gaps"]) == 7
        assert (tmp_path / "r13_iteration_failure_binding.json").is_file()

    def test_audit_writes_r13_failure_binding(self):
        src = Path(
            __file__).resolve().parents[2] / "src" / "rl_curriculum" / (
                "curriculum261_r14_cli.py")
        text = src.read_text(encoding="utf-8")
        assert "r13_iteration_failure_binding.json" in text
        assert "_r13_failure_binding(out)" in text
        # provenance 硬 gate 进 audit
        assert "verify_gate_topology_reconciliation(out)" in text


# ------------------------------------------------ freeze 治理
@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestFreezeGovernance:
    """R14 全 freeze surface(§六):完整行为(tmp dev/repo 场景)由
    test_curriculum261_r14_freeze.py 覆盖;此处锁定结构合同与
    fail closed 语义。"""

    def test_verify_fails_closed_without_freeze(self, tmp_path):
        from rl_curriculum.curriculum261_r14_dependencies import (
            verify_r14_code_freeze,
        )

        result = verify_r14_code_freeze(tmp_path)
        assert result["pass"] is False
        assert "error" in result

    def test_write_requires_commit_a_head_match(self, tmp_path):
        """code_freeze_sha 必须等于 repo HEAD(冻结绑定 Commit A)。"""
        from rl_curriculum.curriculum261_r14_dependencies import (
            write_r14_code_freeze,
        )

        with pytest.raises(RuntimeError) as excinfo:
            write_r14_code_freeze(tmp_path, code_freeze_sha="0" * 40)
        # 两种 fail closed 之一:repo 不可达(纯 tmp)或 sha 不匹配
        assert ("code_freeze_sha 与 repo HEAD 不一致"
                in str(excinfo.value)) or ("不可达" in str(excinfo.value))

    def test_freeze_surface_contract_declared(self):
        from rl_curriculum.curriculum261_r14_dependencies import (
            R14_FREEZE_DEV_DIRS,
            R14_FREEZE_DEV_FILES,
            R14_FREEZE_REPO_PATHS,
        )

        assert "src/rl_curriculum" in R14_FREEZE_DEV_DIRS
        assert "tests/route_c_stage2_6_1" in R14_FREEZE_DEV_DIRS
        assert "user_data/strategies/RouteCStrategy.py" in (
            R14_FREEZE_DEV_FILES)
        assert "requirements-lock.txt" in R14_FREEZE_DEV_FILES
        assert "stage2_6_1/runner" in R14_FREEZE_REPO_PATHS
        assert "stage2_6_1/src" in R14_FREEZE_REPO_PATHS
        assert "stage2_6_1/tests/route_c_stage2_6_1" in (
            R14_FREEZE_REPO_PATHS)


# ------------------------------------------------ rt 路由合同
class TestRtRoutingContract:
    def test_rt_table_and_mutual_exclusivity(self):
        from rl_curriculum.curriculum261_r14_routing import (
            R14_RT_ROLE_FIT_NAMESPACE,
            RoutingContractError,
            build_routing_r14,
        )

        assert R14_RT_ROLE_FIT_NAMESPACE["final"] == (
            "rt3_fit_qualification_r14")

        class _FakeV2:
            namespace = "rt3_fit_main_r14"
            bundle_hash = "r4pb-rt"
            parameter_state_hash = "p"
            manifest_multiset_hash = "m"

        routing = build_routing_r14("main", _FakeV2(), rt=True)
        assert routing.nonformal is True
        with pytest.raises(RoutingContractError):
            build_routing_r14("main", _FakeV2(), rt=True, shadow=True)

    def test_formal_routing_rejects_rt_namespace(self):
        from rl_curriculum.curriculum261_r14_routing import (
            RoutingContractError,
            build_routing_r14,
        )

        class _FakeV2:
            namespace = "rt3_fit_main_r14"
            bundle_hash = "r4pb-rt"
            parameter_state_hash = "p"
            manifest_multiset_hash = "m"

        with pytest.raises(RoutingContractError):
            build_routing_r14("main", _FakeV2())

    def test_rt_eval_namespaces_mapped(self):
        from rl_curriculum.curriculum261_r14_routing import (
            R14_EVAL_NAMESPACE_ROLE,
        )

        assert R14_EVAL_NAMESPACE_ROLE[
            "rt3_calibration_main_r14"] == "main"
        assert R14_EVAL_NAMESPACE_ROLE[
            "rt3_qualification_r14"] == "final"


# ------------------------------------------------ sealed preflight 证据文件名
class TestSealedPreflightEvidenceFilenames:
    def test_evidence_list_matches_real_producers(self):
        """§四-2:证据文件清单必须与 calibrate/preflight-static 真实
        产物名对齐(R12 潜伏缺陷的回归锁)。"""
        src = Path(
            __file__).resolve().parents[2] / "src" / "rl_curriculum" / (
                "curriculum261_r14_preflight.py")
        text = src.read_text(encoding="utf-8")
        for required in (
                "preprocessing_v2_requalification.json",
                "robustness_gate.json",
                "supervised_learnability_main.json",
                "supervised_learnability_holdout.json",
                "prelock_static_preflight.json"):
            assert f'"{required}"' in text, required
        for legacy in ('"preprocessing_robustness_gate.json"',
                       '"curriculum_robustness_gate.json"',
                       '"supervised_learnability.json"'):
            assert legacy not in text, legacy


# ------------------------------------------------ cleanliness 读取修复
class TestCleanlinessReads:
    def test_reads_real_calibration_artifacts(self):
        """§四-2:cleanliness writer 读取真实产物(修复 R12 的无
        producer 文件名缺陷)。"""
        src = Path(
            __file__).resolve().parents[2] / "src" / "rl_curriculum" / (
                "curriculum261_r14_cli.py")
        text = src.read_text(encoding="utf-8")
        assert "calibration_report_main.json" not in text
        assert "calibration_report_holdout.json" not in text


# ------------------------------------------------ 官方入口
class TestOfficialEntrypoint:
    def test_import_sweep_passes(self):
        from rl_curriculum.curriculum261_r14_cli import (
            _official_entrypoint_validation,
        )

        entry = _official_entrypoint_validation()
        assert entry["pass"] is True, entry["import_sweep_failed"]
        assert "real-artifact-rehearsal" in entry["subcommands"]

    def test_no_alternate_loader_passes(self):
        from rl_curriculum.curriculum261_r14_cli import (
            _no_alternate_loader_check,
        )

        nal = _no_alternate_loader_check()
        assert nal["pass"] is True, nal


# ------------------------------------------------ api namespace 注册
class TestR14NamespacesRegistered:
    def test_namespaces_in_whitelist_and_guarded(self):
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R14_NAMESPACES,
            CURRICULUM261_SEED_NAMESPACES,
        )

        ns_set = set(CURRICULUM261_R14_NAMESPACES)
        assert "qualification_r14" in ns_set
        assert "rt_qualification_r14" in ns_set
        assert "rt_cue_model_r14" in ns_set
        assert ns_set <= set(CURRICULUM261_SEED_NAMESPACES)
        # 与 R12 namespace 完全不相交
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R12_NAMESPACES,
        )

        assert not ns_set & set(CURRICULUM261_R12_NAMESPACES)

    def test_qualification_guard_blocks_before_unlock(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R14_LOCK_DIR", str(tmp_path))
        from rl_curriculum.curriculum261_api import (
            GeneratorError,
            derive261_seed,
        )

        with pytest.raises(GeneratorError, match="qualification_r14"):
            derive261_seed("qualification_r14", "c1_opportunity", "D0",
                           0, 0)


# ------------------------------------------------ rt profiles
class TestRtProfiles:
    def test_rt_profiles_full_generation_scale(self):
        from rl_curriculum.curriculum261_r14_orchestrator import (
            rt_holdout_profile_r14,
            rt_main_profile_r14,
        )

        main = rt_main_profile_r14()
        hold = rt_holdout_profile_r14()
        assert main.name == "rt_main" and hold.name == "rt_holdout"
        # c13 评估 60/rung(rehearsal-only 扩样;c3 margin 临界性;
        # 正式链保持 10 冻结);其余生成基数与正式同构
        assert main.c13_pairs_per_rung == 60
        assert main.semantic_blocks == 160
        assert main.c2_blocks == 20
        assert main.c2_independent_pairs_per_rung == 20
        assert main.supervised_pairs_per_rung == 10
        assert main.equivalence_pairs_per_rung == 3
        # supervised 全量训练(3 seeds + 正式配置;gate 语义要求)
        assert main.supervised_model_seeds == (20270132, 20270133,
                                               20270134)
        assert main.supervised_training_config is None
        # rehearsal-only namespace + 落盘
        assert main.c13_eval_namespace == "rt3_calibration_main_r14"
        assert main.write_artifacts is True
        assert hold.c13_eval_namespace == "rt3_calibration_holdout_r14"
        assert hold.write_artifacts is True


# ------------------------------------------------ GateTopologyReconciliation-v1(§五)
@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestGateTopologyProvenance:
    def test_build_provenance_passes(self):
        from rl_curriculum.curriculum261_r14_provenance import (
            build_gate_topology_reconciliation,
        )

        payload = build_gate_topology_reconciliation()
        assert payload["pass"] is True
        assert payload["digest"].startswith("r14gtrec-")
        # 双侧证据齐全
        ce = payload["contradiction_evidence"]
        for marker in ce["declaration_side"]["markers"].values():
            assert marker["present"] is True
        for marker in ce["implementation_side"]["markers"].values():
            assert marker["present"] is True
        assert ce["r6_root"]["marker_in_r6_rule"]["present"] is True
        assert ce["plan_side"]["c2_matched_contains_old_text"][
            "present"] is True

    def test_provenance_conclusions_locked(self):
        from rl_curriculum.curriculum261_r14_provenance import (
            build_gate_topology_reconciliation,
        )

        payload = build_gate_topology_reconciliation()
        concl = payload["conclusions"]
        assert concl["r13_remains_permanent_fail"] is True
        assert concl["r14_fixes_pre_exposure_contract_contradiction"] \
            is True
        assert concl["no_use_of_r13_observed_recall_for_rule_choice"] \
            is True
        assert concl["dedicated_thresholds_unchanged"] is True
        # R13 observed 数值不进入规则选择声明(证明靠源码 markers,
        # 不靠结果);数值只允许出现在 r13_binding 历史事实块
        concl_text = json.dumps(concl, ensure_ascii=False)
        assert "0.948571" not in concl_text
        assert "在查看任何 R13 final 数值前已成立" in (
            concl["rule_choice_basis"])

    def test_provenance_r13_binding(self):
        from rl_curriculum.curriculum261_r14_provenance import (
            build_gate_topology_reconciliation,
        )

        payload = build_gate_topology_reconciliation()
        rb = payload["r13_binding"]
        assert rb["commit_chain"] == [
            "960dbe19701901f9262614aadf8b7f97742fab4d",
            "47d3f22f4df97855423ee748f3aa2df5497422a6",
            "b8e1de05cc3040ddc81634eb36d735a9fe3483da"]
        assert rb["exposure_status"] == "failed"
        assert rb["c2_semantics_pass_observed"] is False

    def test_write_once_and_verify(self, tmp_path):
        from rl_curriculum.curriculum261_r14_provenance import (
            verify_gate_topology_reconciliation,
            write_gate_topology_reconciliation,
        )

        payload = write_gate_topology_reconciliation(tmp_path)
        assert payload["pass"] is True
        assert (tmp_path
                / "gate_topology_reconciliation.json").is_file()
        with pytest.raises(RuntimeError, match="一次且仅一次"):
            write_gate_topology_reconciliation(tmp_path)
        check = verify_gate_topology_reconciliation(tmp_path)
        assert check["pass"] is True, check
