"""工作包 D:运行时内容绑定(2.6.0i:bundle manifest 语义)。

- content digest 通道(RECORD/dcd-)已废除:内容权威是内容寻址
  runtime bundle manifest(rbm-);
- 修改 conda env 中已安装 package 文件(.py/.so)后组装 bundle ->
  bundle manifest digest 变化(旧 evidence 失效);
- 版本号相同但内容不同 -> digest 不同;
- E1:env 中新增未登记文件在组装**前** -> 文件进入 manifest(被
  绑定,committed);组装**后**再改 staging 文件 -> verify_runtime_
  bundle 抛 BundleError(TOCTOU);
- check_runtime_lock_against_static:v3 结构校验(thread_policy/
  worker_pidns_pid/runtime_bundle rbm-/clock 冻结/熵确定性/
  import_closure 文件绑定/distributions file+sha256)——手工构造
  违规锁逐一断言拒绝;
- 真实 Runner:锁内 import_closure 非空且 file 条目 sha256 为 64 位
  hex;numpy distribution 条目有 file+sha256;
- 子进程 import 的 PoC(引用 A 包)证明 v1 漏检、v3 进程树计数暴露。
"""

from __future__ import annotations

import hashlib
import importlib.metadata as md
import json
import os
import shutil
import sys
from pathlib import Path

import pytest

from conftest import attack_request, write_attack_builder
from rl_curriculum.builder_provenance import (
    BuilderProvenanceError,
    check_runtime_lock_against_static,
)
from tests.route_c_stage2_6_0f.conftest import private_provider_from_root

FAMS = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _dc(env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        env["pack"], required_families=list(FAMS))


def _env_root() -> Path:
    py = Path(sys.executable).resolve()
    env_root = py.parent.parent
    if not (env_root / "lib" / "python3.11").is_dir():
        pytest.skip("python 不在 conda env 布局内")
    return env_root


def _runtime_src() -> Path:
    import rl_builder_runtime

    return Path(rl_builder_runtime.__file__).resolve().parent


def _builder_pkg(root: Path) -> Path:
    write_attack_builder(root / "bp", "    pass\n", label="bundle-bp")
    return root / "bp"


def _assemble(staging_root: Path):
    """组装一个 bundle(小 builder 包;env 真实)。"""
    from rl_builder_runtime.bundle import assemble_runtime_bundle

    return assemble_runtime_bundle(
        env_root=_env_root(), staging_root=staging_root,
        runtime_src=_runtime_src(),
        builder_pkg_root=_builder_pkg(staging_root.parent),
        hostname="builder-worker", jobs=4)


def _manifest_files(info) -> dict[str, str]:
    return {e["path"]: e["sha256"] for e in info["manifest"]["entries"]
            if e.get("type") == "file"}


@pytest.fixture(scope="module")
def bundle_base(tmp_path_factory):
    """干净 env 的一次组装(对照基准;staging 与 env 同文件系统以
    支持硬链接——/tmp 与 $HOME 在同一设备)。"""
    base = tmp_path_factory.mktemp("rbm-base")
    staging = base / "bundle_a"
    info = _assemble(staging)
    return {"base": base, "staging": staging, "info": info}


def test_bundle_digest_self_consistent(bundle_base):
    """manifest digest 与 bundle_manifest_digest 重算一致(rbm-)。"""
    from rl_builder_runtime.bundle import bundle_manifest_digest

    info = bundle_base["info"]
    assert info["digest"].startswith("rbm-")
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    assert bundle_manifest_digest(core) == info["digest"]
    assert bundle_manifest_digest(core) == \
        info["manifest"]["manifest_digest"]


def test_untampered_bundle_verifies(bundle_base):
    from rl_builder_runtime.bundle import verify_runtime_bundle

    info = bundle_base["info"]
    core = {k: v for k, v in info["manifest"].items()
            if k != "manifest_digest"}
    result = verify_runtime_bundle(
        bundle_base["staging"], core, jobs=4, expect_digest=info["digest"])
    assert result["digest"] == info["digest"]
    assert result["verified_files"] >= 1


def test_env_py_tamper_changes_bundle_digest(tmp_path, bundle_base):
    """D4 攻击(2.6.0i):改 conda env 已安装 package 的 .py 内容
    (版本号不变)后组装 bundle -> rbm- digest 变化(旧 evidence
    失效;RECORD 是否变化无关)。"""
    from rl_builder_runtime.bundle import bundle_manifest_digest

    sp = _env_root() / "lib" / "python3.11" / "site-packages"
    target = sp / "numpy" / "__init__.py"
    if not target.is_file():
        pytest.skip("numpy 未安装")
    original = target.read_bytes()
    version_before = md.distribution("numpy").version
    try:
        # os.replace 换新 inode:不影响既有 bundle staging(无别名)
        tmp_new = target.with_name("__init__.py.tamper_tmp")
        tmp_new.write_bytes(original + b"\n# tamper-probe\n")
        os.replace(tmp_new, target)
        staging = tmp_path / "bundle_tamper_py"
        info = _assemble(staging)
        assert info["digest"] != bundle_base["info"]["digest"]
        core = {k: v for k, v in info["manifest"].items()
                if k != "manifest_digest"}
        assert bundle_manifest_digest(core) == info["digest"]
        # 同一文件条目的 sha256 变化(RECORD 语义下 dcd- 的等价物)
        key = "lib/python3.11/site-packages/numpy/__init__.py"
        assert _manifest_files(info)[key] != \
            _manifest_files(bundle_base["info"])[key]
        # 版本号相同(numpy==numpy),内容不同被区分
        assert md.distribution("numpy").version == version_before
    finally:
        tmp_new = target.with_name("__init__.py.tamper_tmp")
        if tmp_new.exists():
            os.replace(tmp_new, target)
        else:
            target.write_bytes(original)


def test_env_so_tamper_changes_bundle_digest(tmp_path, bundle_base):
    """D4:.so 替换(内容变)同样被 bundle manifest digest 发现。"""
    sp = _env_root() / "lib" / "python3.11" / "site-packages"
    candidates = sorted(sp.rglob("*.so"))
    if not candidates:
        pytest.skip("site-packages 无 .so")
    target = candidates[0]
    original = target.read_bytes()
    try:
        tmp_new = target.with_name(target.name + ".tamper_tmp")
        tmp_new.write_bytes(original[:-1] + bytes([original[-1] ^ 0xFF]))
        os.replace(tmp_new, target)
        staging = tmp_path / "bundle_tamper_so"
        info = _assemble(staging)
        assert info["digest"] != bundle_base["info"]["digest"]
        rel = target.relative_to(_env_root()).as_posix()
        assert _manifest_files(info)[rel] != \
            _manifest_files(bundle_base["info"])[rel]
    finally:
        tmp_new = target.with_name(target.name + ".tamper_tmp")
        if tmp_new.exists():
            os.replace(tmp_new, target)
        else:
            target.write_bytes(original)


def test_e1_env_file_committed_and_staging_tamper_detected(
        tmp_path, bundle_base):
    """E1:组装前新增未登记文件 -> 进入 manifest(被绑定);
    组装后改 staging 文件 -> verify_runtime_bundle 抛 BundleError。"""
    from rl_builder_runtime.bundle import BundleError, verify_runtime_bundle

    sp = _env_root() / "lib" / "python3.11" / "site-packages"
    hidden = sp / "numpy" / "_hidden_test.py"
    assert "lib/python3.11/site-packages/numpy/_hidden_test.py" not in \
        _manifest_files(bundle_base["info"])
    staging = tmp_path / "bundle_e1"
    try:
        hidden.write_text("VALUE = 'committed'\n", encoding="utf-8")
        info = _assemble(staging)
        # 组装前进入 env 的文件被 manifest 绑定(committed)
        assert "lib/python3.11/site-packages/numpy/_hidden_test.py" in \
            _manifest_files(info)
        core = {k: v for k, v in info["manifest"].items()
                if k != "manifest_digest"}
        # 组装后再篡改 staging 内容(复制通道文件:builder_pkg 是
        # copy 不硬链接,改写不污染 env)-> 全量复验 fail closed
        victim = staging / "builder_pkg" / "params.json"
        assert victim.is_file()
        victim.write_text("{}  # tampered", encoding="utf-8")
        with pytest.raises(BundleError):
            verify_runtime_bundle(
                staging, core, jobs=4, expect_digest=info["digest"])
    finally:
        if hidden.exists():
            hidden.unlink()


# --------------------------------------- check_runtime_lock_against_static v3
def _valid_v3_lock() -> dict:
    """手工构造的合法 v3 锁(结构完备;通过静态对账)。"""
    from rl_builder_runtime.runner import SECCOMP_PROCESS_POLICY

    return {
        "format": "builder-runtime-lock-v3",
        "python_implementation": "cpython",
        "python_version": "3.11",
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
            "file_count": 12,
            "syslib_sonames": ["libc.so.6"],
            "hostname": "builder-worker",
        },
        "clock_policy": {
            "vdso": {"mode": "frozen-stub"},
            "pr_set_tsc_rc": 0,
            "raw_syscall": {"clock_gettime": "ERRNO1",
                            "time": "ERRNO1",
                            "gettimeofday": "ERRNO1",
                            "clock_gettime64": "ERRNO1"},
            "behavior": {"time_time": 0.0, "time_monotonic": 0.0,
                         "time_perf_counter": 0.0,
                         "datetime_now_year": 1970,
                         "datetime_utcnow_year": 1970},
        },
        "entropy_policy": {
            "getrandom": "ERRNO1",
            "dev_urandom_deterministic": True,
            "deterministic_entropy_sha256_prefix": "0" * 16,
        },
        "seccomp_policy": SECCOMP_PROCESS_POLICY,
        "seccomp_filter_hash": "scp-" + "c" * 64,
        "environment_identity": {"environ": {}, "cwd": "/scratch"},
        "thread_state": {
            "policy": "threads_forbidden_clone_denied",
            "thread_count_at_quiesce": 1,
            "task_comms": ["python3.11"],
        },
        "distributions": [{
            "module": "evilpkg", "distribution": "evilpkg",
            "version": "1.0", "imported": ["evilpkg"],
            "file": "/lib/python3.11/site-packages/evilpkg/__init__.py",
            "sha256": "d" * 64,
        }],
        "import_closure": [{
            "module": "evilpkg", "loader": "SourceFileLoader",
            "origin_kind": "file",
            "file": "/lib/python3.11/site-packages/evilpkg/__init__.py",
            "sha256": "d" * 64,
            "owner": "distribution", "distribution": "evilpkg",
        }],
        "native_libraries": [{
            "path": "/lib/x86_64-linux-gnu/libz.so.1",
            "sha256": "e" * 64, "origin": "runtime-bundle",
        }],
    }


DIST_ENTRY = [{"module": "evilpkg", "version": "1.0"}]


def test_valid_v3_lock_accepted():
    check_runtime_lock_against_static(_valid_v3_lock(), DIST_ENTRY)


def _mutated(mutate) -> dict:
    import copy

    lock = _valid_v3_lock()
    mutate(lock)
    return lock


@pytest.mark.parametrize("mutate,match", [
    (lambda l: l.__setitem__("format", "builder-runtime-lock-v2"),
     "runtime-lock-v3|格式"),
    (lambda l: l.__setitem__("process_tree_policy", "allow_descendants"),
     "进程树策略"),
    (lambda l: l.__setitem__("child_process_count", 1), "进程树违规"),
    (lambda l: l.__setitem__("exec_count", 2), "进程树违规"),
    (lambda l: l.pop("thread_policy"), "线程禁止策略"),
    (lambda l: l.__setitem__("thread_policy", "threads_allowed"),
     "线程禁止策略"),
    (lambda l: l["thread_state"].__setitem__("thread_count_at_quiesce", 2),
     "线程静止实测失败"),
    (lambda l: l.pop("worker_pidns_pid"), "pidns 内 pid 1"),
    (lambda l: l["runtime_bundle"].__setitem__(
        "manifest_digest", "dcd-" + "0" * 64), "runtime bundle 绑定"),
    (lambda l: l.pop("runtime_bundle"), "runtime bundle 绑定"),
    (lambda l: l["clock_policy"]["vdso"].__setitem__("mode", "live"),
     "vDSO 冻结策略"),
    (lambda l: l["clock_policy"]["behavior"].__setitem__(
        "time_time", 123.5), "冻结纪元"),
    (lambda l: l["clock_policy"]["behavior"].__setitem__(
        "datetime_now_year", 2026), "冻结纪元"),
    (lambda l: l["clock_policy"]["raw_syscall"].__setitem__(
        "time", "ERRNO0"), "未被拒绝"),
    (lambda l: l["entropy_policy"].__setitem__("getrandom", "ERRNO0"),
     "确定性熵策略"),
    (lambda l: l["entropy_policy"].__setitem__(
        "dev_urandom_deterministic", False), "确定性熵策略"),
    (lambda l: l.pop("import_closure"), "import_closure"),
    (lambda l: l["import_closure"][0].__setitem__("sha256", "short"),
     "未绑定 bundle 字节"),
    (lambda l: l["import_closure"][0].__setitem__("file", "evil.py"),
     "未绑定 bundle 字节"),
    (lambda l: l.pop("native_libraries"), "native_libraries"),
    (lambda l: l["native_libraries"][0].__setitem__("sha256", "x"),
     "native_libraries 条目缺少内容绑定"),
    (lambda l: l["distributions"][0].__setitem__(
        "version", "<missing:evilpkg>"), "缺失依赖"),
    (lambda l: l["distributions"][0].pop("file"),
     "文件字节绑定"),
    (lambda l: l["distributions"][0].__setitem__("sha256", "short"),
     "文件字节绑定"),
])
def test_v3_lock_violation_matrix_rejected(mutate, match):
    with pytest.raises(BuilderProvenanceError, match=match):
        check_runtime_lock_against_static(_mutated(mutate), DIST_ENTRY)


def test_unregistered_dependency_rejected():
    """实际加载未注册第三方依赖(静态闭包外)拒绝。"""
    lock = _valid_v3_lock()
    with pytest.raises(BuilderProvenanceError, match="未注册"):
        check_runtime_lock_against_static(lock, [])


def test_version_drift_rejected():
    """运行时版本与静态预检不一致拒绝(依赖环境漂移)。"""
    lock = _valid_v3_lock()
    with pytest.raises(BuilderProvenanceError, match="不一致"):
        check_runtime_lock_against_static(
            lock, [{"module": "evilpkg", "version": "1.1"}])


def test_runner_lock_records_closure_and_bundle(sealed_exam_env, tmp_path):
    """真实 Runner 锁:import_closure 逐文件 64-hex 绑定;numpy
    distribution 有 file+sha256;native 绑定齐全;bundle rbm-。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run

    body = "    import numpy\n    assert numpy.__version__\n"
    root = write_attack_builder(
        tmp_path / "np_ok", body,
        external_dependencies=[{"module": "numpy", "version": "2.4.6"}],
        label="np-ok")
    provider = private_provider_from_root(root)
    req = attack_request(provider, sealed_exam_env["pack"],
                         _dc(sealed_exam_env))
    record = run_isolated_builder_run(
        provider.builder_identity(), req, builder_root=root)
    lock = record["runtime_lock"]
    assert lock["format"] == "builder-runtime-lock-v3"
    assert lock["process_tree_policy"] == "single_builder_process"
    assert lock["thread_policy"] == "threads_forbidden_clone_denied"
    assert lock["worker_pidns_pid"] == 1
    assert lock["thread_state"]["thread_count_at_quiesce"] == 1
    assert lock["child_process_count"] == 0
    assert lock["exec_count"] == 0
    assert lock["runtime_bundle"]["manifest_digest"].startswith("rbm-")
    assert lock["runtime_bundle"]["manifest_digest"] == \
        record["runtime_bundle_hash"]
    # 导入闭包:非空且每条 file 条目绑定 64 位 hex sha256
    assert lock["import_closure"], "import_closure 必须非空"
    file_entries = [e for e in lock["import_closure"]
                    if e.get("origin_kind") == "file"]
    assert file_entries
    for e in file_entries:
        assert e["file"].startswith("/")
        assert len(e["sha256"]) == 64
        int(e["sha256"], 16)  # hex
    # numpy distribution 条目:file + sha256(按实际文件归属绑定)
    dists = {d["module"]: d for d in lock["distributions"]}
    assert "numpy" in dists
    np_entry = dists["numpy"]
    assert np_entry["file"].startswith("/")
    assert len(np_entry["sha256"]) == 64
    assert np_entry["version"] == "2.4.6"
    assert lock["native_libraries"], "native .so 必须被绑定"
    for n in lock["native_libraries"]:
        assert len(n["sha256"]) == 64
        assert n["origin"] == "runtime-bundle"
    # 锁与 EDIC 的 bundle/native 一致
    edic = record["deterministic_input_report"]
    assert lock["runtime_bundle"] == edic["runtime_bundle"]
    assert lock["native_libraries"] == \
        edic["supervisor"]["native_libraries"]


def test_poc_descendant_import_absent_from_lock(sealed_exam_env, tmp_path,
                                                descendant_demo_profile):
    """PoC(与 A 包联动):子进程 import pytest 不出现在锁内——v1
    漏检;v3 进程树计数(child>=1)暴露,evidence 拒绝。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run

    body = (
        "    import subprocess, sys\n"
        "    subprocess.run(\n"
        "        [sys.executable, '-c', 'import pytest'],\n"
        "        capture_output=True, check=True)\n"
    )
    root = write_attack_builder(
        tmp_path / "poc2", body,
        external_dependencies=[{"module": "numpy", "version": "2.4.6"}],
        label="poc2")
    provider = private_provider_from_root(root)
    req = attack_request(provider, sealed_exam_env["pack"],
                         _dc(sealed_exam_env))
    record = run_isolated_builder_run(
        provider.builder_identity(), req, builder_root=root,
        profile=descendant_demo_profile)
    mods = {d["module"] for d in record["runtime_lock"]["distributions"]}
    assert "pytest" not in mods  # 漏检证明(v1 缺陷)
    assert record["child_process_count"] >= 1  # v3 暴露
