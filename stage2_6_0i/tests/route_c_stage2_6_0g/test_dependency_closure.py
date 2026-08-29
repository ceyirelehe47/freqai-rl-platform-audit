"""阶段 2.6.0g 收尾:G1 静态 import 闭包降级为预检 + G3 运行时锁对账。

- 静态闭包仍是 allowlist 候选/诊断(gymnasium 等第三方覆盖);
- 实际运行时锁由隔离 Runner 派生;未注册/版本漂移/<missing> 拒绝。
"""

from __future__ import annotations

import pytest


def test_static_closure_covers_third_party():
    from rl_curriculum.builder_identity import (
        _static_import_closure,
        _rl_curriculum_root,
    )

    closure = _static_import_closure(
        [("rl_curriculum", _rl_curriculum_root())])
    for expected in ("numpy", "pandas", "gymnasium"):
        assert expected in closure, f"静态闭包遗漏 {expected}"


def test_static_manifest_marks_itself_precheck(mock_identity):
    deps = mock_identity.manifest.get("external_dependencies") or []
    modules = {d.get("module") for d in deps}
    assert "rl_platform" in modules
    assert "python" in modules
    assert "numpy" in modules


def _lock(extra_dists=None, versions=None):
    base = {
        "format": "builder-runtime-lock-v3",
        "python_implementation": "cpython",
        "python_version": "3.11.0",
        "executable_prefix": "/",
        "process_tree_policy": "single_builder_process",
        "thread_policy": "threads_forbidden_clone_denied",
        "child_process_count": 0,
        "child_process_attempts": 0,
        "exec_count": 0,
        "exec_attempts": 0,
        "worker_pidns_pid": 1,
        "runtime_bundle": {
            "manifest_digest": "rbm-" + "a" * 64,
            "file_count": 12, "syslib_sonames": [], 
            "hostname": "builder-worker",
        },
        "clock_policy": {
            "vdso": {"mode": "frozen-stub"},
            "pr_set_tsc_rc": 0,
            "raw_syscall": {"clock_gettime": "ERRNO1"},
            "behavior": {"time_time": 0.0, "datetime_now_year": 1970},
        },
        "entropy_policy": {
            "getrandom": "ERRNO1", "dev_urandom_deterministic": True,
            "deterministic_entropy_sha256_prefix": "0" * 16,
        },
        "seccomp_policy": {"format": "builder-seccomp-policy-v2"},
        "seccomp_filter_hash": "scp-" + "c" * 64,
        "environment_identity": {"environ": {}, "cwd": "/scratch"},
        "thread_state": {"policy": "threads_forbidden_clone_denied",
                         "thread_count_at_quiesce": 1,
                         "task_comms": ["python3.11"]},
        "distributions": [
            {"module": "numpy", "distribution": "numpy",
             "version": "9.9.9",
             "file": "/lib/python3.11/site-packages/numpy/__init__.py",
             "sha256": "d" * 64,
             "imported": ["numpy"]},
        ],
        "import_closure": [{
            "module": "numpy", "loader": "SourceFileLoader",
            "origin_kind": "file",
            "file": "/lib/python3.11/site-packages/numpy/__init__.py",
            "sha256": "d" * 64,
            "owner": "distribution", "distribution": "numpy",
        }],
        "native_libraries": [],
    }
    for d in (extra_dists or []):
        base["distributions"].append(d)
    if versions:
        for d in base["distributions"]:
            if d["module"] in versions:
                d["version"] = versions[d["module"]]
    return base


def test_lock_against_static_ok():
    from rl_curriculum.builder_provenance import (
        check_runtime_lock_against_static,
    )

    static = [{"module": "numpy", "kind": "package_version",
               "version": "9.9.9"},
              {"module": "pandas", "kind": "package_version",
               "version": "1.0.0"}]
    # 运行时只加载 numpy(allowlist 允许比实际宽:函数级 import 未触发)
    check_runtime_lock_against_static(
        _lock(), static, require_single_process=False,
        verify_content=False)


def test_unregistered_dependency_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    lock = _lock(extra_dists=[
        {"module": "requests", "distribution": "requests",
         "version": "2.0",
         "file": "/lib/python3.11/site-packages/requests/__init__.py",
         "sha256": "e" * 64,
         "imported": ["requests"]}])
    static = [{"module": "numpy", "kind": "package_version",
               "version": "9.9.9"}]
    with pytest.raises(BuilderProvenanceError, match="未注册|动态"):
        check_runtime_lock_against_static(
        lock, static, require_single_process=False,
        verify_content=False)


def test_version_drift_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    static = [{"module": "numpy", "kind": "package_version",
               "version": "1.2.3"}]
    with pytest.raises(BuilderProvenanceError, match="版本|漂移"):
        check_runtime_lock_against_static(
        _lock(), static, require_single_process=False,
        verify_content=False)


def test_missing_static_record_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    static = [{"module": "numpy", "kind": "package_version",
               "version": "<missing:numpy>"}]
    with pytest.raises(BuilderProvenanceError, match="missing"):
        check_runtime_lock_against_static(
        _lock(), static, require_single_process=False,
        verify_content=False)


def test_missing_runtime_record_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    lock = _lock(versions={"numpy": "<missing:numpy>"})
    with pytest.raises(BuilderProvenanceError, match="missing"):
        check_runtime_lock_against_static(
        lock, [], require_single_process=False,
        verify_content=False)


def test_bad_lock_format_rejected():
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
        check_runtime_lock_against_static,
    )

    with pytest.raises(BuilderProvenanceError, match="格式"):
        check_runtime_lock_against_static({"format": "wrong"}, [])


def test_isolated_runner_lock_for_selfcontained_builder(private_builder_a,
                                                        sealed_exam_env,
                                                        duration_contract,
                                                        mock_pack):
    """自包含 builder 的运行时锁:实际加载第三方为空(标准库之外),
    全部来自 staging 内部 -> 空 distributions 合法。"""
    from rl_curriculum.builder_evidence import precommit_builder_runs

    provider = private_builder_a
    req = provider.frozen_build_request(mock_pack, duration_contract)
    _ev, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    dists = runs[0]["runtime_lock"]["distributions"]
    for d in dists:
        assert not d["version"].startswith("<missing")
