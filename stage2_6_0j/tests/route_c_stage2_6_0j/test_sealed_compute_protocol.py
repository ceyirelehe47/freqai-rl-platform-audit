"""工作包 A3/F1/F3:依赖 allowlist、sealed compute report 与协议升级。

- A3:正式 profile 拒绝第三方 native;compat 允许运行但
  formal_eligible=false 且 evidence 层拒绝其形成可信材料;
- F1:sealed compute report v2 绑定 Prepare/Seal/Compute 全部边界;
- F3:协议版本升级与 2.6.0i 旧材料显式拒绝(含重签攻击)。
"""

from __future__ import annotations

import json

import pytest


def test_dependency_policy_formal_and_compat():
    from rl_builder_runtime.sealed_compute import dependency_policy

    formal = dependency_policy(formal=True)
    assert formal["profile"] == "formal"
    assert formal["formal_eligible"] is True
    assert formal["third_party_native"] == "rejected"
    assert formal["numpy_formal_eligible"] is False
    assert "numpy" in formal["forbidden_modules"]
    assert "ctypes" in formal["forbidden_modules"]
    assert "math" in formal["pure_modules"] or \
        "math" in formal["native_modules"]

    compat = dependency_policy(formal=False)
    assert compat["profile"] == "compat"
    assert compat["formal_eligible"] is False
    assert compat["third_party_native"] == "allowed-without-formal-evidence"


def test_sealed_compute_report_v2_fields(tmp_path, seed_pack_and_dc):
    """F1:真实链路 sealed compute report v2 的完整字段绑定。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
        write_private_builder,
    )

    root = write_private_builder(tmp_path / "scr-builder")
    provider = private_provider_from_root(root)
    seed, dc = seed_pack_and_dc
    run = run_isolated_builder_run(
        provider.builder_identity(),
        provider.frozen_build_request(seed, dc),
        builder_root=root, profile=BuilderRunnerProfile())
    edic = run["deterministic_input_report"]
    assert edic["format"] == "sealed-compute-report-v2"
    sc = edic["sealed_compute"]
    # Prepare 承诺
    assert sc["phase_plan"] == "prepare->seal->compute"
    assert sc["dependency_policy"]["format"] == \
        "builder-dependency-policy-v1"
    assert sc["top_level_purity"]["digest"].startswith("pur-")
    assert sc["preloaded_modules"]  # native 预加载非空
    # Seal 承诺(final filter 策略与摘要)
    assert sc["final_seccomp"]["policy"]["default_action"] == "EPERM"
    assert sc["final_seccomp"]["filter_digest"].startswith("scf-")
    assert sc["result_fd"] == 87
    # Supervisor 合并的实际 Seal 状态与二次实测
    sup = edic["supervisor"]
    assert sup["seal_state"]["mdwe"]["enabled"] is True
    assert sup["seal_state"]["final_filter"]["installed"] is True
    assert sup["compute_after"]["thread_count"] == 1
    assert sup["compute_after"]["exec_mapping_growth"] == 0
    assert sup["compute_after"]["seccomp_filter_count"] >= 2
    # Compute 违规清单(access summary)
    assert run["access_summary"]["phase_violations"] == []


def test_compat_run_cannot_form_trusted_evidence(tmp_path,
                                                 seed_pack_and_dc):
    """A3 核心:evidence 核心字段进 bre- 哈希——compat 语义的字段值
    (scf-public-assembly/public-assembly)与 formal 不相等,且
    build_builder_run_evidence 对非 formal 依赖策略的私有 run 直接
    拒绝(手工构造被拒路径)。"""
    from rl_curriculum.builder_evidence import (
        BuilderProvenanceError,
        build_builder_run_evidence,
        precommit_builder_runs,
    )
    from rl_curriculum.builder_runner import BuilderRunnerProfile
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
        write_private_builder,
    )

    root = write_private_builder(tmp_path / "compat-ev-builder")
    provider = private_provider_from_root(root)
    identity = provider.builder_identity()
    seed, dc = seed_pack_and_dc
    request = provider.frozen_build_request(seed, dc)
    evidence, runs = precommit_builder_runs(
        provider, request, builder_root=root)
    # 正式链默认 formal:evidence 携带真实 scf-/formal
    assert evidence["dependency_profile"] == "formal"
    assert evidence["final_seccomp_filter_hash"].startswith("scf-")
    # compat 语义字段值无法冒充 formal(进 bre- 哈希的核心字段)
    import copy as _copy

    forged = _copy.deepcopy(evidence)
    forged["dependency_profile"] = "compat"
    from rl_curriculum.builder_evidence import builder_run_evidence_hash

    assert builder_run_evidence_hash(forged) != evidence["evidence_hash"]
    # 私有 run 的依赖策略非 formal -> build 阶段直接拒绝
    compat_runs = _copy.deepcopy(runs)
    for r in compat_runs:
        r["dependency_profile"] = "compat"
    with pytest.raises(BuilderProvenanceError, match="formal"):
        build_builder_run_evidence(
            identity=identity, request=request, runs=compat_runs,
            provider=provider)


def test_protocol_versions_and_legacy_rejection():
    """F3:0j 协议族版本 + 2.6.0i 材料显式拒绝。"""
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL
    from rl_builder_runtime.runner import EDIC_FORMAT
    from rl_builder_runtime.sealed_compute import (
        FINAL_COMPUTE_POLICY,
    )
    from rl_curriculum.builder_evidence import (
        BUILDER_RUN_EVIDENCE_FORMAT,
        builder_run_evidence_hash,
    )
    from rl_curriculum.builder_provenance import (
        RUNTIME_LOCK_FORMAT,
        BuilderProvenanceError,
    )
    from rl_curriculum.builder_runner import BuilderRunnerProfile
    from rl_curriculum.formal_exam import EXAM_CLI_VERSION
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS, SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v11"
    assert "sealed-exam-commitment-v10" in _DEPRECATED_PROTOCOLS
    assert EXAM_CLI_VERSION == "hidden-exam-cli-v12"
    assert BUILDER_WORKER_PROTOCOL == "builder-runner-worker-v4"
    assert RUNTIME_LOCK_FORMAT == "builder-runtime-lock-v4"
    assert BUILDER_RUN_EVIDENCE_FORMAT == "builder-run-evidence-v4"
    assert EDIC_FORMAT == "sealed-compute-report-v2"
    assert FINAL_COMPUTE_POLICY["format"] == "builder-seccomp-final-policy-v3"
    assert BuilderRunnerProfile().canonical_payload()[
        "format"] == "builder-runner-profile-v4"

    # 0i v3 evidence 即使补新字段重签也被哈希/校验拒绝
    legacy = {
        "format": "builder-run-evidence-v3",
        "mode": "builder_execution", "deterministic": True,
        "final_seccomp_filter_hash": "scf-" + "1" * 64,
        "dependency_profile": "formal",
        "runs": [{"run": 1}, {"run": 2}],
    }
    with pytest.raises(BuilderProvenanceError):
        builder_run_evidence_hash(legacy)


def test_legacy_0i_edic_rejected_in_check():
    """F3:0i 的 edic-v1 报告被 sealed-compute-report-v2 校验拒绝。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        BuilderRunnerProfile,
        check_effective_deterministic_input_report,
    )

    legacy = {"format": "builder-deterministic-input-report-v1",
              "pidns_self_pid": 1}
    with pytest.raises(BuilderRunnerError, match="sealed-compute-report"):
        check_effective_deterministic_input_report(
            legacy, BuilderRunnerProfile())


def test_default_allow_policy_cannot_impersonate():
    """十二/十五:final filter default_action 改成 allow 的载荷与
    期望策略不相等(策略载荷精确相等断言)。"""
    from rl_builder_runtime.sealed_compute import FINAL_COMPUTE_POLICY
    from rl_curriculum.builder_runner import BuilderRunnerProfile

    tampered = json.loads(json.dumps(FINAL_COMPUTE_POLICY))
    tampered["default_action"] = "allow"
    payload = BuilderRunnerProfile().canonical_payload()
    assert payload["sealed_compute"]["final_filter"]["policy"] == \
        FINAL_COMPUTE_POLICY
    assert payload["sealed_compute"]["final_filter"]["policy"] != \
        tampered
    # prctl deny 家族在策略载荷中显式声明
    assert "prctl" in payload["sealed_compute"]["final_filter"]["policy"][
        "deny_families"]["state_control"]


def test_seccomp_filter_digest_tamper_detected():
    """十五:伪造 final filter 摘要 -> 与 canonical 重算不一致。"""
    from rl_builder_runtime.sealed_compute import (
        canonical_final_filter,
        final_filter_digest,
    )

    prog = canonical_final_filter()
    prog[0]["k"] = 0x40000028  # 篡改 arch
    assert final_filter_digest(prog) != final_filter_digest()
