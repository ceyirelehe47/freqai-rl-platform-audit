"""工作包 F:evidence v3 核心哈希与对账(2.6.0i 适配)。

- 新核心字段:deterministic_input_hash(edi-)/ runtime_bundle_hash
  (rbm-)/ thread_policy / access_summary_hash / process_tree_policy /
  child_process_count / exec_count / runner_isolation;
- verify 重算全部核心哈希;detail.deterministic_input_report 重算
  edi-;detail.access_summary 重算 acs-;
- 篡改 detail 的 deterministic_input_report/access 绕过 bre- 的攻击
  被拒绝;
- 隔离降级(seccomp 关/组装哨兵冒充)的 evidence 无法通过 verify。
"""

from __future__ import annotations

import copy

import pytest

from rl_curriculum.builder_evidence import (
    EVIDENCE_CORE_FIELDS,
    builder_run_evidence_hash,
    verify_builder_run_evidence,
)
from rl_curriculum.builder_provenance import (
    BuilderProvenanceError,
    access_summary_hash,
)


def test_core_fields_include_new_hashes():
    for field in ("deterministic_input_hash", "runtime_bundle_hash",
                  "thread_policy", "access_summary_hash",
                  "process_tree_policy", "child_process_count",
                  "exec_count", "runner_isolation"):
        assert field in EVIDENCE_CORE_FIELDS
    # 0h 的 esb- 通道已退役:核心字段不再包含 effective_sandbox_hash
    assert "effective_sandbox_hash" not in EVIDENCE_CORE_FIELDS


def test_mock_evidence_carries_new_fields(sealed_exam_env):
    ev = sealed_exam_env["evidence"]
    assert ev["format"] == "builder-run-evidence-v3"
    assert ev["deterministic_input_hash"] == "edi-public-assembly"
    assert ev["runtime_bundle_hash"] == "rbm-public-assembly"
    assert ev["access_summary_hash"].startswith("acs-")
    assert ev["process_tree_policy"] == "in_process_public_assembly"
    assert ev["thread_policy"] == "in_process_public_assembly"
    assert ev["child_process_count"] == 0
    assert ev["exec_count"] == 0
    assert ev["runner_isolation"] == "public_assembly_process"
    assert ev["runs"] and len(ev["runs"]) == 2
    for run in ev["runs"]:
        for key in ("pack_hash", "attempt_log_hash", "runtime_lock_hash",
                    "deterministic_input_hash", "access_summary_hash",
                    "child_process_count", "exec_count"):
            assert key in run


def test_verify_accepts_mock_evidence(sealed_exam_env):
    env = sealed_exam_env
    verify_builder_run_evidence(
        env["evidence"], commitment=env["commitment"],
        identity=env["provider"].builder_identity(),
        request_hash=env["commitment"].builder_build_request_hash)


def test_tamper_access_summary_detail_rejected(sealed_exam_env):
    """篡改 detail.access_summary(绕过核心 acs-)被拒绝。"""
    env = sealed_exam_env
    evidence = copy.deepcopy(env["evidence"])
    evidence["detail"]["access_summary"]["open_count"] = 999
    with pytest.raises(BuilderProvenanceError, match="access_summary"):
        verify_builder_run_evidence(
            evidence, commitment=env["commitment"],
            identity=env["provider"].builder_identity(),
            request_hash=env["commitment"].builder_build_request_hash)


def test_tamper_core_access_hash_rejected(sealed_exam_env):
    """核心 access_summary_hash 改动破坏 bre- 自洽。"""
    env = sealed_exam_env
    evidence = copy.deepcopy(env["evidence"])
    evidence["access_summary_hash"] = "acs-" + "0" * 64
    with pytest.raises(BuilderProvenanceError):
        verify_builder_run_evidence(
            evidence, commitment=env["commitment"],
            identity=env["provider"].builder_identity(),
            request_hash=env["commitment"].builder_build_request_hash)


def test_tamper_process_tree_rejected(sealed_exam_env):
    """核心 process_tree_policy 篡改 -> bre- 不自洽 -> verify 拒绝。"""
    env = sealed_exam_env
    evidence = copy.deepcopy(env["evidence"])
    evidence["process_tree_policy"] = "allow_descendants"
    assert builder_run_evidence_hash(evidence) != evidence["evidence_hash"]
    with pytest.raises(BuilderProvenanceError):
        verify_builder_run_evidence(
            evidence, commitment=env["commitment"],
            identity=env["provider"].builder_identity(),
            request_hash=env["commitment"].builder_build_request_hash)


def test_access_summary_hash_deterministic():
    access = {
        "format": "builder-access-summary-v2",
        "open_count": 3, "outside_allowlist": [],
        "covered_events": ["open"], "child_process_attempts": 0,
        "exec_attempts": 0, "dlopen_targets": []}
    h1 = access_summary_hash(copy.deepcopy(access))
    access["open_count"] = 4
    h2 = access_summary_hash(access)
    assert h1 != h2
    assert h1.startswith("acs-")


def test_private_evidence_requires_real_deterministic_input(
        sealed_exam_env):
    """私有通道 evidence 的 edi- 哨兵必须真实(不能是组装哨兵)。"""
    from rl_curriculum.builder_evidence import (
        MOCK_EDI_HASH,
        build_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    env = sealed_exam_env
    run = {
        "mode": "builder_execution",
        "status": "ok",
        "pack": env["pack"],
        "pack_hash": env["commitment"].pack_hash,
        "attempt_log": env["evidence"]["detail"]["attempt_log"],
        "runtime_lock": env["evidence"]["detail"]["runtime_lock"],
        "runner_code_hash": "rtb-x",
        "sandbox_profile_hash": "brp-x",
        "access_summary": {},
        "deterministic_input_hash": MOCK_EDI_HASH,  # 哨兵冒充
        "runtime_bundle_hash": "rbm-" + "1" * 64,
        "thread_policy": "threads_forbidden_clone_denied",
        "process_tree_policy": "single_builder_process",
    }
    with pytest.raises(BuilderProvenanceError, match="edi-"):
        build_builder_run_evidence(
            identity=env["provider"].builder_identity(),
            request=env["commitment"].builder_build_request,
            runs=[dict(run), dict(run)],
            provider=env["provider"])


def test_private_evidence_requires_real_bundle(sealed_exam_env):
    """私有通道 evidence 的 rbm- 哨兵冒充被拒绝(0h 活环境材料)。"""
    from rl_curriculum.builder_evidence import (
        MOCK_BUNDLE_HASH,
        build_builder_run_evidence,
    )
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    env = sealed_exam_env
    run = {
        "mode": "builder_execution",
        "status": "ok",
        "pack": env["pack"],
        "pack_hash": env["commitment"].pack_hash,
        "attempt_log": env["evidence"]["detail"]["attempt_log"],
        "runtime_lock": env["evidence"]["detail"]["runtime_lock"],
        "runner_code_hash": "rtb-x",
        "sandbox_profile_hash": "brp-x",
        "access_summary": {},
        "deterministic_input_hash": "edi-" + "5" * 64,
        "runtime_bundle_hash": MOCK_BUNDLE_HASH,  # 哨兵冒充
        "thread_policy": "threads_forbidden_clone_denied",
        "process_tree_policy": "single_builder_process",
    }
    with pytest.raises(BuilderProvenanceError, match="rbm-|bundle"):
        build_builder_run_evidence(
            identity=env["provider"].builder_identity(),
            request=env["commitment"].builder_build_request,
            runs=[dict(run), dict(run)],
            provider=env["provider"])


def test_descendant_run_rejected_in_evidence_build(sealed_exam_env):
    """child_process_count>0 的 run 无法组进 evidence。"""
    from rl_curriculum.builder_evidence import build_builder_run_evidence
    from rl_curriculum.builder_provenance import (
        PROCESS_TREE_SINGLE,
        BuilderProvenanceError,
    )

    env = sealed_exam_env
    run = {
        "mode": "builder_execution", "status": "ok",
        "pack": env["pack"], "pack_hash": env["commitment"].pack_hash,
        "attempt_log": env["evidence"]["detail"]["attempt_log"],
        "runtime_lock": env["evidence"]["detail"]["runtime_lock"],
        "runner_code_hash": "rtb-x", "sandbox_profile_hash": "brp-x",
        "access_summary": {},
        "deterministic_input_hash": "edi-" + "9" * 64,
        "runtime_bundle_hash": "rbm-" + "9" * 64,
        "thread_policy": "threads_forbidden_clone_denied",
        "child_process_count": 1,
        "exec_count": 0,
        "process_tree_policy": PROCESS_TREE_SINGLE,
    }
    with pytest.raises(BuilderProvenanceError,
                       match="edi-|后代|进程树"):
        build_builder_run_evidence(
            identity=env["provider"].builder_identity(),
            request=env["commitment"].builder_build_request,
            runs=[dict(run), dict(run)],
            provider=env["provider"])
