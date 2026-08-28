"""工作包 A:Builder 后代执行禁止(真实隔离 Runner 攻击)。

- A1:fork/vfork/clone3/execve/execveat/ptrace/process_vm_*/mount/
  umount2/unshare/setns 全拒;clone 仅允许 CLONE_THREAD 线程;
- A3 攻击:subprocess 启动子 Python import 未注册第三方包、/bin/sh、
  os.posix_spawn、fork+exec、ctypes.CDLL、外部可执行文件——全部
  在 pack 采信前失败;
- PoC(修复前漏检证明):seccomp 关闭的演示 profile 下子进程 import
  不进入父 Runner 锁(v1 缺陷),输出三次一致;v2 语义下此类 run
  的 child_process_count>0/evidence 被拒。
"""

from __future__ import annotations

import json

import pytest

from conftest import attack_request, write_attack_builder
from tests.route_c_stage2_6_0f.conftest import private_provider_from_root


def _dc(sealed_exam_env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        sealed_exam_env["pack"], required_families=list(
            ("probe_null_sign", "probe_null_volstate",
             "probe_null_stochvol")))


def _run(provider, env, body, *, profile=None, root=None):
    from rl_curriculum.builder_provenance import BuilderProvenanceError
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    req = attack_request(provider, env["pack"], _dc(env))
    try:
        return run_isolated_builder_run(
            provider.builder_identity(), req,
            builder_root=root or getattr(provider, "root", None),
            profile=profile)
    except (BuilderRunnerError, BuilderProvenanceError) as exc:
        return exc


def test_subprocess_child_import_rejected(sealed_exam_env, tmp_path):
    """子 Python import 未注册包(pytest)构造 pack -> 拒绝。"""
    body = (
        "    import subprocess, sys\n"
        "    out = subprocess.run(\n"
        "        [sys.executable, '-c',\n"
        "         'import pytest; print(pytest.__version__)'],\n"
        "        capture_output=True, text=True, check=True)\n"
        "    version = out.stdout.strip()\n"
        "    assert version\n"
    )
    root = write_attack_builder(tmp_path / "sub_attack", body,
                                label="sub-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception), "子进程攻击必须被拒绝"
    assert "子进程" in str(result) or "process" in str(result) \
        or "seccomp" in str(result) or "执行" in str(result)


def test_bin_sh_execution_rejected(sealed_exam_env, tmp_path):
    body = (
        "    import subprocess\n"
        "    out = subprocess.run(['/bin/sh', '-c', 'echo ok'],\n"
        "        capture_output=True, text=True, check=True)\n"
        "    assert out.stdout.strip() == 'ok'\n"
    )
    root = write_attack_builder(tmp_path / "sh_attack", body,
                                label="sh-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception)


def test_os_posix_spawn_rejected(sealed_exam_env, tmp_path):
    body = (
        "    import os\n"
        "    pid = os.posix_spawn(\n"
        "        '/usr/bin/true', ['/usr/bin/true'], os.environ)\n"
        "    os.waitpid(pid, 0)\n"
    )
    root = write_attack_builder(tmp_path / "spawn_attack", body,
                                label="spawn-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception)


def test_fork_then_exec_rejected(sealed_exam_env, tmp_path):
    body = (
        "    import os, sys\n"
        "    pid = os.fork()\n"
        "    if pid == 0:\n"
        "        os.execv(sys.executable,\n"
        "                 [sys.executable, '-c', 'import json'])\n"
        "    os.waitpid(pid, 0)\n"
    )
    root = write_attack_builder(tmp_path / "fork_attack", body,
                                label="fork-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception)


def test_ctypes_cdll_unbound_rejected(sealed_exam_env, tmp_path):
    """ctypes.CDLL 加载 scratch 内自备 .so(未绑定位置)被锁拒绝。"""
    import shutil

    src_so = None
    for candidate in (
            "/usr/lib/x86_64-linux-gnu/libz.so.1",
            "/lib/x86_64-linux-gnu/libz.so.1"):
        try:
            src_so = candidate
            break
        except OSError:
            continue
    if src_so is None:
        pytest.skip("系统 libz 不可用")
    body = (
        "    import ctypes\n"
        "    lib = ctypes.CDLL('./evil_native.so')\n"
        "    assert lib is not None\n"
    )
    extra = {"evil_native.so": shutil.copy(src_so, tmp_path / "z.so")
             and (tmp_path / "z.so").read_bytes()}
    # 注:write_attack_builder 写 root/evil_native.so;builder 的 cwd
    # 是 scratch,所以用绝对 staging 相对不可行——直接在 builder 内
    # 用相对路径会失败;改为用 __file__ 定位
    body = (
        "    import ctypes, os\n"
        "    here = os.path.dirname(os.path.dirname(__file__))\n"
        "    lib = ctypes.CDLL(os.path.join(here, 'evil_native.so'))\n"
        "    assert lib is not None\n"
    )
    root = write_attack_builder(
        tmp_path / "cdll_attack", body, extra_files=extra,
        label="cdll-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception)


def test_external_executable_rejected(sealed_exam_env, tmp_path):
    body = (
        "    import subprocess\n"
        "    out = subprocess.run(\n"
        "        ['/usr/bin/python3', '-c', 'print(1)'],\n"
        "        capture_output=True, text=True, check=True)\n"
        "    assert out.stdout.strip() == '1'\n"
    )
    root = write_attack_builder(tmp_path / "ext_attack", body,
                                label="ext-attacker")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert isinstance(result, Exception)


def test_thread_creation_allowed(sealed_exam_env, tmp_path):
    """A1 线程例外:CLONE_THREAD 线程创建被允许(与后代进程区分)。"""
    body = (
        "    import threading\n"
        "    box = []\n"
        "    t = threading.Thread(target=lambda: box.append(1))\n"
        "    t.start()\n"
        "    t.join()\n"
        "    assert box == [1]\n"
    )
    root = write_attack_builder(tmp_path / "thread_ok", body,
                                label="thread-ok")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, body, root=root)
    assert not isinstance(result, Exception), str(result)
    assert result["child_process_count"] == 0
    assert result["exec_count"] == 0


def test_poc_descendant_import_bypasses_v1_lock(sealed_exam_env,
                                                tmp_path,
                                                descendant_demo_profile):
    """任务书要求的 PoC:修复前 v1 锁漏检子进程 import 的证明。

    seccomp 关闭 + allow_descendants(仅供演示):子 Python import
    pytest(未注册第三方)并把版本写进 pack notes,三次运行输出
    一致(确定性);但运行时锁的 distributions 不含 pytest——证明
    v1 锁(只审计父进程 sys.modules)漏检子进程依赖。
    """
    body = (
        "    import subprocess, sys\n"
        "    out = subprocess.run(\n"
        "        [sys.executable, '-c',\n"
        "         'import pytest; print(pytest.__version__)'],\n"
        "        capture_output=True, text=True, check=True)\n"
        "    version = out.stdout.strip()\n"
    )
    root = write_attack_builder(
        tmp_path / "poc_descendant", body, label="poc-descendant")
    # notes 记录子进程输出(三次一致的确定性输出)
    src = (root / "builder_attack.py").read_text(encoding="utf-8")
    src = src.replace("'notes': {},", "'notes': {'child': version},")
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    provider = private_provider_from_root(root)
    hashes = []
    notes = []
    for _ in range(3):
        record = _run(provider, sealed_exam_env, body,
                     profile=descendant_demo_profile, root=root)
        assert not isinstance(record, Exception), str(record)
        hashes.append(record["pack_hash"])
        notes.append(record["pack"].notes.get("child"))
        # 漏检证明:子进程 import 的 pytest 不在父 Runner 锁内
        modules = [d["module"]
                   for d in record["runtime_lock"]["distributions"]]
        assert "pytest" not in modules
        # 但进程树计数暴露了后代进程(v2 新语义)
        assert record["child_process_count"] >= 1
    assert len(set(hashes)) == 1  # 三次输出一致
    assert len(set(notes)) == 1 and notes[0]


def test_descendant_run_cannot_formal_evidence(sealed_exam_env, tmp_path,
                                               descendant_demo_profile):
    """v2 语义:child_process_count>0 的 run 无法通过 evidence 校验。"""
    body = (
        "    import subprocess, sys\n"
        "    subprocess.run(\n"
        "        [sys.executable, '-c', 'import pytest'],\n"
        "        capture_output=True, check=True)\n"
    )
    root = write_attack_builder(tmp_path / "desc_evil", body,
                                label="desc-evil")
    provider = private_provider_from_root(root)
    record = _run(provider, sealed_exam_env, body,
                  profile=descendant_demo_profile, root=root)
    assert not isinstance(record, Exception), str(record)
    from rl_curriculum.builder_evidence import build_builder_run_evidence
    from rl_curriculum.builder_provenance import (
        BuilderProvenanceError,
    )

    req = attack_request(provider, sealed_exam_env["pack"], _dc(sealed_exam_env))
    with pytest.raises(BuilderProvenanceError,
                       match="后代|进程树|esb-"):
        build_builder_run_evidence(
            identity=provider.builder_identity(), request=req,
            runs=[record, dict(record)], provider=provider)
