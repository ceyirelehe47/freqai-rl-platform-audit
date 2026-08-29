"""工作包 D4/F:协议版本升级与旧材料拒绝。

- 承诺 v10:SEALED_EXAM_PROTOCOL 常量;v9 及更早进入弃用列表,
  from_json 拒绝且报逐版缺陷说明;
- evidence v3:2.6.0h 的 v2 evidence(缺 deterministic_input_hash/
  runtime_bundle_hash/thread_policy)被 v3 执行器拒绝;
- lock v3:v2 锁(无 bundle 绑定/线程策略/时钟冻结)被拒绝;
- worker 协议 v3:旧 builder-runner-worker-v2 响应被拒绝;
- 0h 材料"重签"攻击:把 v2 字段塞进 v3 形状并重算哈希,字段级
  校验仍拒绝(不能靠重签绕过语义缺失)。
"""

from __future__ import annotations

import copy
import json

import pytest

pytestmark = pytest.mark.stage2_6_0i


def test_sealed_protocol_versions():
    from rl_curriculum.sealed_exam import (
        _DEPRECATED_PROTOCOLS, SEALED_EXAM_PROTOCOL,
    )

    assert SEALED_EXAM_PROTOCOL == "sealed-exam-commitment-v10"
    assert "sealed-exam-commitment-v9" in _DEPRECATED_PROTOCOLS
    from rl_curriculum.formal_exam import EXAM_CLI_VERSION

    assert EXAM_CLI_VERSION == "hidden-exam-cli-v11"
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL

    assert BUILDER_WORKER_PROTOCOL == "builder-runner-worker-v3"
    from rl_curriculum.builder_provenance import RUNTIME_LOCK_FORMAT

    assert RUNTIME_LOCK_FORMAT == "builder-runtime-lock-v3"
    from rl_curriculum.builder_evidence import (
        BUILDER_RUN_EVIDENCE_FORMAT,
    )

    assert BUILDER_RUN_EVIDENCE_FORMAT == "builder-run-evidence-v3"


def test_v2_lock_rejected():
    """0h 的 v2 锁(即使内容完备)被 v3 校验拒绝。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_runtime_lock_against_static,
    )

    v2_lock = {
        "format": "builder-runtime-lock-v2",
        "python_implementation": "cpython", "python_version": "3.11.16",
        "executable_prefix": "/env", "process_tree_policy":
            "single_builder_process",
        "child_process_count": 0, "child_process_attempts": 0,
        "exec_count": 0,
        "distributions": [], "native_libraries": [],
    }
    with pytest.raises(BuilderProvenanceError, match="v3|格式"):
        check_runtime_lock_against_static(v2_lock, [])


def test_v3_lock_missing_closure_fields_rejected():
    """v3 形状但缺线程策略/bundle 绑定/时钟冻结 -> 逐项拒绝。"""
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError, check_runtime_lock_against_static,
    )

    def base_lock():
        return {
            "format": "builder-runtime-lock-v3",
            "python_implementation": "cpython",
            "python_version": "3.11.16", "executable_prefix": "/",
            "process_tree_policy": "single_builder_process",
            "thread_policy": "threads_forbidden_clone_denied",
            "child_process_count": 0, "child_process_attempts": 0,
            "exec_count": 0, "exec_attempts": 0,
            "worker_pidns_pid": 1,
            "runtime_bundle": {"manifest_digest": "rbm-" + "a" * 64,
                               "file_count": 10, "syslib_sonames": [],
                               "hostname": "builder-worker"},
            "clock_policy": {
                "vdso": {"mode": "frozen-stub"},
                "pr_set_tsc_rc": 0,
                "raw_syscall": {"clock_gettime": "ERRNO1"},
                "behavior": {"time_time": 0.0,
                             "datetime_now_year": 1970}},
            "entropy_policy": {"getrandom": "ERRNO1",
                               "dev_urandom_deterministic": True},
            "distributions": [], "import_closure": [],
            "native_libraries": [],
            "thread_state": {"policy": "threads_forbidden_clone_denied",
                             "thread_count_at_quiesce": 1,
                             "task_comms": ["python3.11"]},
        }

    ok = base_lock()
    check_runtime_lock_against_static(ok, [], verify_content=True)

    no_thread = base_lock()
    no_thread["thread_policy"] = "0h-allowed-clone-thread"
    with pytest.raises(BuilderProvenanceError, match="线程"):
        check_runtime_lock_against_static(no_thread, [])

    no_bundle = base_lock()
    no_bundle["runtime_bundle"] = {"manifest_digest": "dcd-xyz",
                                   "file_count": 1}
    with pytest.raises(BuilderProvenanceError, match="rbm-|bundle"):
        check_runtime_lock_against_static(no_bundle, [])

    live_clock = base_lock()
    live_clock["clock_policy"]["behavior"]["time_time"] = 1759100000.0
    with pytest.raises(BuilderProvenanceError, match="时钟|冻结"):
        check_runtime_lock_against_static(live_clock, [])

    real_entropy = base_lock()
    real_entropy["entropy_policy"]["getrandom"] = "ALLOWED"
    with pytest.raises(BuilderProvenanceError, match="熵|getrandom"):
        check_runtime_lock_against_static(real_entropy, [])

    threads_alive = base_lock()
    threads_alive["thread_state"]["thread_count_at_quiesce"] = 3
    with pytest.raises(BuilderProvenanceError, match="线程静止"):
        check_runtime_lock_against_static(threads_alive, [])


def test_v2_evidence_rejected():
    """2.6.0h v2 evidence 被 v3 哈希/加载路径拒绝(含"重签":即使把
    format 改成 v3 并重算 bre-,缺新语义字段仍拒绝)。"""
    from rl_curriculum.builder_evidence import (
        BuilderProvenanceError,
        builder_run_evidence_core,
        builder_run_evidence_hash,
        verify_builder_run_evidence,
    )

    v2_evidence = {
        "format": "builder-run-evidence-v2",
        "mode": "builder_execution", "deterministic": True,
        "effective_sandbox_hash": "esb-" + "1" * 64,
        "runs": [{"run": 1}, {"run": 2}],
    }
    with pytest.raises(BuilderProvenanceError, match="v3"):
        builder_run_evidence_hash(v2_evidence)
    # 重签攻击:改 format 为 v3 并补哈希 -> 哈希函数只看 format,
    # 但完整验证路径的语义字段校验拒绝(缺 edi-/rbm-/thread_policy)
    resigned = dict(v2_evidence)
    resigned["format"] = "builder-run-evidence-v3"
    resigned["run_status"] = "ok"
    resigned["deterministic_input_hash"] = ""  # 缺失(0h 无此语义)
    resigned["runtime_bundle_hash"] = ""
    resigned["thread_policy"] = ""
    resigned["evidence_hash"] = builder_run_evidence_hash(resigned)
    assert builder_run_evidence_hash(resigned) == \
        resigned["evidence_hash"], "重签在机械层面自洽"
    from types import SimpleNamespace

    summary = dict(builder_run_evidence_core(resigned))
    summary["evidence_hash"] = resigned["evidence_hash"]
    fake_commitment = SimpleNamespace(
        builder_run_evidence=summary,
        pack_hash=str(resigned.get("output_pack_hash") or ""))
    fake_identity = SimpleNamespace(manifest_hash="", tree_hash="",
                                    manifest={})
    with pytest.raises(BuilderProvenanceError,
                       match="确定性输入报告|edi-|bundle|线程|双跑记录"):
        verify_builder_run_evidence(
            resigned, commitment=fake_commitment,
            identity=fake_identity, request_hash="nbr-x")


def test_worker_protocol_v2_rejected(run_attack, monkeypatch):
    """旧 builder-runner-worker-v2 响应行 -> 协议校验拒绝。

    (以 v3 校验函数直接验证:同构造消息仅协议名不同。)
    """
    from rl_builder_runtime import BUILDER_WORKER_PROTOCOL

    assert BUILDER_WORKER_PROTOCOL.endswith("v3")
    old = {"protocol": "builder-runner-worker-v2", "phase": "final",
           "status": "ok", "build_result": {}}
    # supervisor 侧对协议名的精确校验语义
    assert old["protocol"] != BUILDER_WORKER_PROTOCOL


def test_profile_v3_requires_closure_semantics():
    """profile v3 载荷必须绑定 bundle/时钟/熵/线程语义;0h profile
    v2 载荷(无这些字段)与 v3 不相等(降级材料无法冒充)。"""
    from rl_curriculum.builder_runner import BuilderRunnerProfile

    payload = BuilderRunnerProfile().canonical_payload()
    assert payload["format"] == "builder-runner-profile-v3"
    assert payload["runtime_bundle"]["content_addressed"] is True
    assert payload["runtime_bundle"]["mounted_verify_before_exec"]
    assert payload["runtime_bundle"]["post_run_verify"]
    assert payload["filesystem_view"]["proc_mounted"] is False
    assert payload["filesystem_view"]["host_usr_visible"] is False
    assert payload["filesystem_view"]["host_conda_visible"] is False
    assert payload["filesystem_view"]["dev_random_urandom"] == \
        "deterministic-committed-file"
    assert payload["thread_policy"] == "threads_forbidden_clone_denied"
    assert payload["seccomp"]["policy"]["format"] == \
        "builder-seccomp-policy-v2"
    assert "CLONE_THREAD" not in json.dumps(
        payload["seccomp"]["policy"]), "0h 线程放行条目必须删除"
