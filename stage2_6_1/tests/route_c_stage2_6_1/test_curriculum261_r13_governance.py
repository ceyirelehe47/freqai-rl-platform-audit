# -*- coding: utf-8 -*-
"""R13 治理测试:HistoricalEvidenceBinding(R13 版)/R12 abort binding/
freeze 治理/rt 路由合同/sealed preflight 证据文件名对齐/generation
evidence completeness(§四-2/§四-5)。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_r13_generation_evidence import (
    BlockAttemptSummary,
    ExpectedCall,
    verify_generation_evidence_completeness,
)
from rl_curriculum.curriculum261_r13_historical import (
    R11_COMMIT_A,
    R11_COMMIT_A_PRIME,
    R12_COMMIT_A,
    R12_COMMIT_B,
    R13_EXPECTED_BASELINE,
    historical_evidence_binding,
)


def _release_repo() -> Path | None:
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            return cand
    return None


# ------------------------------------------------ generation evidence
def _env(namespace="stress_r13", family="c3_cost", rung="D0", pair=0,
         attempt=0, accepted=True, digest=None, call_digest="cd-1"):
    return {
        "stage": "s", "iteration": "r13", "call_digest": call_digest,
        "envelope": {
            "iteration": "r13", "namespace": namespace,
            "family": family, "rung": rung, "pair_index": pair,
            "attempt_index": attempt, "outer_seed": 12345,
            "accepted": accepted,
            "digest": digest or "x" * 64,
        },
    }


EXPECTED = [ExpectedCall("stress_r13", "c3_cost", "D0", 0)]


def test_generation_evidence_complete_pass():
    rows = [_env(attempt=0, accepted=False), _env(attempt=1, accepted=True)]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert r["pass"], r["problems_sample"]
    assert r["observed_call_invocations"] == 1
    assert r["iteration"] == "r13"


def test_generation_evidence_missing_rejected():
    rows = [_env(namespace="other_r13")]
    r = verify_generation_evidence_completeness(
        None, EXPECTED, stage_label="s", ledger_rows_override=rows)
    assert not r["pass"]
    assert r["missing_calls"] == 1


def test_generation_evidence_same_coordinate_two_legal_calls():
    calls = [ExpectedCall("calibration_r13", "c1_opportunity", "D0", 0),
             ExpectedCall("calibration_r13", "c1_opportunity", "D0", 0)]
    rows = [
        _env(namespace="calibration_r13", family="c1_opportunity",
             rung="D0", pair=0, attempt=0, accepted=True,
             call_digest="cd-eval"),
        _env(namespace="calibration_r13", family="c1_opportunity",
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
class TestHistoricalEvidenceBindingR13:
    def test_ancestry_and_r12_clean_chain(self):
        repo = _release_repo()
        binding = historical_evidence_binding(repo)
        assert binding["expected_baseline"] == R13_EXPECTED_BASELINE
        assert R13_EXPECTED_BASELINE == (
            "960dbe19701901f9262614aadf8b7f97742fab4d")
        assert R12_COMMIT_A == (
            "75a66dde368c6f7c8ccc1a70e19445a6f86165fe")
        assert R12_COMMIT_B == R13_EXPECTED_BASELINE
        assert binding["checks"]["baseline_commit_exists"] is True
        assert binding["checks"]["r12_clean_two_commit_chain"] is True
        assert binding["checks"]["r12_qualification_plan_never_locked"] \
            is True
        assert binding["checks"]["r12_final_qualification_not_executed"] \
            is True
        assert binding["ok"] is True, binding["failed_checks"]

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
        from rl_curriculum.curriculum261_r13_cli import _r12_abort_binding

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
                "curriculum261_r13_cli.py")
        text = src.read_text(encoding="utf-8")
        assert "r12_iteration_failure_binding.json" in text
        assert "preprocessor_bundle_hash" in text
        assert "KeyError: 'bundle_hash'" in text


# ------------------------------------------------ freeze 治理
@pytest.mark.skipif(_release_repo() is None,
                    reason="release repo 不可达(仅 WSL/开发机)")
class TestFreezeGovernance:
    def test_roundtrip_and_duplicate_rejection(self, tmp_path):
        from rl_curriculum.curriculum261_r13_dependencies import (
            verify_r13_code_freeze,
            write_r13_code_freeze,
        )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_release_repo()),
            capture_output=True, text=True).stdout.strip()
        payload = write_r13_code_freeze(tmp_path, code_freeze_sha=head)
        assert payload["iteration"] == "r13"
        assert verify_r13_code_freeze(tmp_path)["pass"] is True
        with pytest.raises(RuntimeError, match="一次且仅一次"):
            write_r13_code_freeze(tmp_path, code_freeze_sha=head)

    def test_drift_rejected(self, tmp_path, monkeypatch):
        import rl_curriculum

        from rl_curriculum.curriculum261_r13_dependencies import (
            verify_r13_code_freeze,
            write_r13_code_freeze,
        )

        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(_release_repo()),
            capture_output=True, text=True).stdout.strip()
        write_r13_code_freeze(tmp_path, code_freeze_sha=head)
        # 篡改冻结清单中的一个模块哈希 → 漂移被检出
        doc = json.loads(
            (tmp_path / "r13_code_freeze.json").read_text(
                encoding="utf-8"))
        first = sorted(doc["modules"])[0]
        doc["modules"][first] = "0" * 64
        (tmp_path / "r13_code_freeze.json").write_text(
            json.dumps(doc), encoding="utf-8")
        result = verify_r13_code_freeze(tmp_path)
        assert result["pass"] is False
        assert first in result["drifted_modules"]


# ------------------------------------------------ rt 路由合同
class TestRtRoutingContract:
    def test_rt_table_and_mutual_exclusivity(self):
        from rl_curriculum.curriculum261_r13_routing import (
            R13_RT_ROLE_FIT_NAMESPACE,
            RoutingContractError,
            build_routing_r13,
        )

        assert R13_RT_ROLE_FIT_NAMESPACE["final"] == (
            "rt2_fit_qualification_r13")

        class _FakeV2:
            namespace = "rt2_fit_main_r13"
            bundle_hash = "r4pb-rt"
            parameter_state_hash = "p"
            manifest_multiset_hash = "m"

        routing = build_routing_r13("main", _FakeV2(), rt=True)
        assert routing.nonformal is True
        with pytest.raises(RoutingContractError):
            build_routing_r13("main", _FakeV2(), rt=True, shadow=True)

    def test_formal_routing_rejects_rt_namespace(self):
        from rl_curriculum.curriculum261_r13_routing import (
            RoutingContractError,
            build_routing_r13,
        )

        class _FakeV2:
            namespace = "rt2_fit_main_r13"
            bundle_hash = "r4pb-rt"
            parameter_state_hash = "p"
            manifest_multiset_hash = "m"

        with pytest.raises(RoutingContractError):
            build_routing_r13("main", _FakeV2())

    def test_rt_eval_namespaces_mapped(self):
        from rl_curriculum.curriculum261_r13_routing import (
            R13_EVAL_NAMESPACE_ROLE,
        )

        assert R13_EVAL_NAMESPACE_ROLE[
            "rt2_calibration_main_r13"] == "main"
        assert R13_EVAL_NAMESPACE_ROLE[
            "rt2_qualification_r13"] == "final"


# ------------------------------------------------ sealed preflight 证据文件名
class TestSealedPreflightEvidenceFilenames:
    def test_evidence_list_matches_real_producers(self):
        """§四-2:证据文件清单必须与 calibrate/preflight-static 真实
        产物名对齐(R12 潜伏缺陷的回归锁)。"""
        src = Path(
            __file__).resolve().parents[2] / "src" / "rl_curriculum" / (
                "curriculum261_r13_preflight.py")
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
                "curriculum261_r13_cli.py")
        text = src.read_text(encoding="utf-8")
        assert "calibration_report_main.json" not in text
        assert "calibration_report_holdout.json" not in text


# ------------------------------------------------ 官方入口
class TestOfficialEntrypoint:
    def test_import_sweep_passes(self):
        from rl_curriculum.curriculum261_r13_cli import (
            _official_entrypoint_validation,
        )

        entry = _official_entrypoint_validation()
        assert entry["pass"] is True, entry["import_sweep_failed"]
        assert "real-artifact-rehearsal" in entry["subcommands"]

    def test_no_alternate_loader_passes(self):
        from rl_curriculum.curriculum261_r13_cli import (
            _no_alternate_loader_check,
        )

        nal = _no_alternate_loader_check()
        assert nal["pass"] is True, nal


# ------------------------------------------------ api namespace 注册
class TestR13NamespacesRegistered:
    def test_namespaces_in_whitelist_and_guarded(self):
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R13_NAMESPACES,
            CURRICULUM261_SEED_NAMESPACES,
        )

        ns_set = set(CURRICULUM261_R13_NAMESPACES)
        assert "qualification_r13" in ns_set
        assert "rt_qualification_r13" in ns_set
        assert "rt_cue_model_r13" in ns_set
        assert ns_set <= set(CURRICULUM261_SEED_NAMESPACES)
        # 与 R12 namespace 完全不相交
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R12_NAMESPACES,
        )

        assert not ns_set & set(CURRICULUM261_R12_NAMESPACES)

    def test_qualification_guard_blocks_before_unlock(self, tmp_path,
                                                      monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R13_LOCK_DIR", str(tmp_path))
        from rl_curriculum.curriculum261_api import (
            GeneratorError,
            derive261_seed,
        )

        with pytest.raises(GeneratorError, match="qualification_r13"):
            derive261_seed("qualification_r13", "c1_opportunity", "D0",
                           0, 0)


# ------------------------------------------------ rt profiles
class TestRtProfiles:
    def test_rt_profiles_full_generation_scale(self):
        from rl_curriculum.curriculum261_r13_orchestrator import (
            rt_holdout_profile_r13,
            rt_main_profile_r13,
        )

        main = rt_main_profile_r13()
        hold = rt_holdout_profile_r13()
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
        assert main.c13_eval_namespace == "rt2_calibration_main_r13"
        assert main.write_artifacts is True
        assert hold.c13_eval_namespace == "rt2_calibration_holdout_r13"
        assert hold.write_artifacts is True
