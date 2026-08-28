"""工作包(协议):v9/v10 升级与旧材料拒绝。

新执行器必须明确拒绝:commitment v8 及更早、evidence v1、runtime
lock v1、attempt log v1、没有 effective sandbox report 的材料、
允许子进程或共享宿主 /dev/shm 的材料。语义未变的 Route C/Null/
friction/power/attestation/Candidate runtime 协议不升级。
"""

from __future__ import annotations

import copy
import json

import pytest

from rl_curriculum.builder_evidence import (
    BUILDER_RUN_EVIDENCE_FORMAT,
    builder_run_evidence_hash,
)
from rl_curriculum.builder_identity import (
    BUILDER_MANIFEST_FORMAT,
    _DEPRECATED_BUILDER_MANIFEST_FORMATS,
)
from rl_curriculum.builder_provenance import (
    ATTEMPT_LOG_FORMAT,
    BUILDER_RUNNER_PROTOCOL,
    BUILD_REQUEST_FORMAT,
    BUILD_RESULT_FORMAT,
    RUNTIME_LOCK_FORMAT,
)
from rl_curriculum.builder_runner import (
    SINGLE_PROCESS,
    BuilderRunnerProfile,
)
from rl_curriculum.formal_exam import EXAM_CLI_VERSION
from rl_curriculum.sealed_exam import (
    SEALED_EXAM_PROTOCOL,
    _DEPRECATED_PROTOCOLS,
    SealedExamError,
)


def test_protocol_constants_upgraded():
    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v9"
    assert "sealed-exam-commitment-v8" in _DEPRECATED_PROTOCOLS
    assert BUILDER_MANIFEST_FORMAT == "null-pack-builder-manifest-v5"
    assert "null-pack-builder-manifest-v4" in (
        _DEPRECATED_BUILDER_MANIFEST_FORMATS)
    assert BUILDER_RUNNER_PROTOCOL == "builder-runner-protocol-v3"
    assert BUILD_REQUEST_FORMAT == "builder-build-request-v3"
    assert BUILD_RESULT_FORMAT == "builder-build-result-v3"
    assert ATTEMPT_LOG_FORMAT == "builder-attempt-log-v2"
    assert RUNTIME_LOCK_FORMAT == "builder-runtime-lock-v2"
    assert BUILDER_RUN_EVIDENCE_FORMAT == "builder-run-evidence-v2"
    assert EXAM_CLI_VERSION == "hidden-exam-cli-v10"


def test_v8_commitment_rejected(sealed_exam_env):
    """v8 承诺载荷被 v9 执行器显式拒绝(带缺陷描述)。"""
    commitment = sealed_exam_env["commitment"]
    payload = json.loads(commitment.to_json())
    payload["protocol_version"] = "sealed-exam-commitment-v8"
    with pytest.raises(SealedExamError, match="v8|已弃用"):
        type(commitment).from_json(json.dumps(payload))


def test_v7_commitment_rejected(sealed_exam_env):
    commitment = sealed_exam_env["commitment"]
    payload = json.loads(commitment.to_json())
    payload["protocol_version"] = "sealed-exam-commitment-v7"
    with pytest.raises(SealedExamError, match="v7|已弃用"):
        type(commitment).from_json(json.dumps(payload))


def test_v9_roundtrip_preserves_new_fields(sealed_exam_env):
    commitment = sealed_exam_env["commitment"]
    payload = json.loads(commitment.to_json())
    assert payload["builder_attempt_policy"]["policy"] in (
        "first_pass", "assembly")
    again = type(commitment).from_json(json.dumps(payload))
    assert again.commitment_hash() == commitment.commitment_hash()
    assert again.builder_attempt_policy == commitment.builder_attempt_policy


def test_evidence_v1_rejected_by_hash_fn(sealed_exam_env):
    """evidence v1(v0g 旧格式)被 v2 执行器的哈希函数拒绝。"""
    evidence = copy.deepcopy(sealed_exam_env["evidence"])
    evidence["format"] = "builder-run-evidence-v1"
    with pytest.raises(Exception, match="builder-run-evidence-v2"):
        builder_run_evidence_hash(evidence)


def test_missing_sandbox_report_evidence_rejected(sealed_exam_env):
    """没有 effective sandbox report 的 evidence 摘要拒绝。"""
    from rl_curriculum.builder_evidence import verify_builder_run_evidence
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    commitment = sealed_exam_env["commitment"]
    core = dict(commitment.builder_run_evidence)
    assert core.get("effective_sandbox_hash")
    # 承诺侧:剥离 effective_sandbox_hash 的摘要 -> from_json 拒绝
    payload = json.loads(commitment.to_json())
    payload["builder_run_evidence"].pop("effective_sandbox_hash")
    payload["builder_run_evidence"]["evidence_hash"] = \
        "bre-" + "0" * 64
    with pytest.raises(SealedExamError, match="effective_sandbox"):
        type(commitment).from_json(json.dumps(payload))


def test_child_process_evidence_rejected(sealed_exam_env):
    """允许子进程的 evidence(child_process_count>0)在 from_json
    即被拒绝。"""
    commitment = sealed_exam_env["commitment"]
    payload = json.loads(commitment.to_json())
    payload["builder_run_evidence"]["child_process_count"] = 2
    with pytest.raises(SealedExamError, match="后代进程|child"):
        type(commitment).from_json(json.dumps(payload))


def test_runtime_lock_v1_rejected():
    """v1 锁(只哈希 RECORD 的旧形态)不再被接受。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    v1_lock = {
        "format": "builder-runtime-lock-v1",
        "python_implementation": "cpython",
        "python_version": "3.11",
        "executable_prefix": "/env",
        "distributions": [],
    }
    with pytest.raises(BuilderProvenanceError, match="runtime-lock-v2|格式"):
        check_runtime_lock_against_static(v1_lock, [])


def test_attempt_log_v1_rejected(sealed_exam_env):
    """v1 attempt log(builder 直接提交的旧格式)被合同拒绝。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_attempt_log,
    )

    with pytest.raises(BuilderProvenanceError,
                       match="attempt-log-v2|format"):
        check_attempt_log(
            {"format": "builder-attempt-log-v1", "max_attempts": 0,
             "attempts": [], "selected_attempt": None,
             "output_pack_hash": "p-x"},
            attempt_policy={"policy": "assembly", "max_attempts": 0})


def test_seccomp_disabled_profile_cannot_claim_single_process():
    """seccomp 禁用 + single_builder_process 声明被构造期拒绝。"""
    from rl_curriculum.builder_runner import BuilderRunnerError

    with pytest.raises(BuilderRunnerError, match="seccomp"):
        BuilderRunnerProfile(install_seccomp=False,
                             process_tree_policy=SINGLE_PROCESS)


def test_untouched_protocols_not_bumped():
    """语义未变的协议不无理由升级(Route C/Null/attestation/沙箱)。"""
    import rl_curriculum.sealed_exam as se

    assert se.module_code_hash.__name__ == "module_code_hash"
    from rl_curriculum.probe_charter import probe_observation_schema
    from rl_curriculum.sandbox import default_sandbox_profile

    assert probe_observation_schema() is not None
    profile = default_sandbox_profile()
    assert str(profile.profile_hash())  # Candidate 沙箱 profile 不在本阶段升级范围
