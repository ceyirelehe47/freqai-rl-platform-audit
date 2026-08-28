"""工作包 B:私有最小文件系统视图与外部状态攻击(B1/B3)。

- 宿主 /dev/shm 对 Builder 不可见(私有 tmpfs);跨运行不共享;
- 预先写入宿主 /dev/shm 的 beacon 读不到;
- /etc /sys 与宿主临时目录 stat 级 ENOENT(pivot_root 不可命名);
- machine-id / 宿主 tmp 文件读取失败;
- 目录排序无法影响 pack(宿主目录不可列举)。
"""

from __future__ import annotations

import os

import pytest

from conftest import attack_request, write_attack_builder
from tests.route_c_stage2_6_0f.conftest import private_provider_from_root

FAMS = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _dc(env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        env["pack"], required_families=list(FAMS))


def _run(provider, env, root, *, profile=None):
    from rl_curriculum.builder_provenance import BuilderProvenanceError
    from rl_curriculum.builder_runner import (
        BuilderRunnerError,
        run_isolated_builder_run,
    )

    req = attack_request(provider, env["pack"], _dc(env))
    try:
        return run_isolated_builder_run(
            provider.builder_identity(), req, builder_root=root,
            profile=profile)
    except (BuilderRunnerError, BuilderProvenanceError) as exc:
        return exc


def test_host_dev_shm_beacon_unreadable(sealed_exam_env, tmp_path):
    """宿主预先写入 /dev/shm 的 beacon 在 Builder 沙箱内不可见。"""
    beacon = "/dev/shm/0h_beacon_host"
    with open(beacon, "w") as fh:
        fh.write("host-secret")
    try:
        body = (
            "    with open('/dev/shm/0h_beacon_host') as fh:\n"
            "        secret = fh.read()\n"
            "    assert secret\n"
        )
        root = write_attack_builder(tmp_path / "shm_read", body,
                                    label="shm-read")
        provider = private_provider_from_root(root)
        result = _run(provider, sealed_exam_env, root)
        assert isinstance(result, Exception), "宿主 /dev/shm 读取必须失败"
    finally:
        os.unlink(beacon)


def test_dev_shm_not_shared_across_runs(sealed_exam_env, tmp_path):
    """run1 写 /dev/shm/leak,run2 读不到(每次运行全新私有 tmpfs)。"""
    write_body = (
        "    with open('/dev/shm/leak', 'w') as fh:\n"
        "        fh.write('leaked')\n"
    )
    read_body = (
        "    with open('/dev/shm/leak') as fh:\n"
        "        data = fh.read()\n"
        "    assert data == 'leaked'\n"
    )
    root = write_attack_builder(tmp_path / "shm_w", write_body,
                                label="shm-w")
    provider = private_provider_from_root(root)
    r1 = _run(provider, sealed_exam_env, root)
    assert not isinstance(r1, Exception), str(r1)
    root2 = write_attack_builder(tmp_path / "shm_r", read_body,
                                 label="shm-r")
    provider2 = private_provider_from_root(root2)
    r2 = _run(provider2, sealed_exam_env, root2)
    assert isinstance(r2, Exception), "跨运行的 /dev/shm 通道必须不存在"


def test_stat_etc_returns_enoent(sealed_exam_env, tmp_path):
    """os.stat('/etc/...') 在 pivot 后 ENOENT(不可利用;stat 无审计
    事件,由 namespace 不可命名保证)。"""
    body = (
        "    import os\n"
        "    os.stat('/etc/machine-id')\n"
    )
    root = write_attack_builder(tmp_path / "stat_etc", body,
                                label="stat-etc")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, root)
    assert isinstance(result, Exception)


def test_listdir_sys_enoent(sealed_exam_env, tmp_path):
    body = (
        "    import os\n"
        "    entries = os.listdir('/sys')\n"
        "    assert entries\n"
    )
    root = write_attack_builder(tmp_path / "ls_sys", body,
                                label="ls-sys")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, root)
    assert isinstance(result, Exception)


def test_machine_id_read_fails(sealed_exam_env, tmp_path):
    body = (
        "    with open('/etc/machine-id') as fh:\n"
        "        mid = fh.read().strip()\n"
        "    assert len(mid) > 8\n"
    )
    root = write_attack_builder(tmp_path / "mid_read", body,
                                label="mid-read")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, root)
    assert isinstance(result, Exception)


def test_host_tmp_unreachable(sealed_exam_env, tmp_path):
    """宿主临时目录文件在私有 /tmp(tmpfs)内不可见。"""
    host_tmp = "/tmp/0h_host_beacon.txt"
    with open(host_tmp, "w") as fh:
        fh.write("host-tmp-secret")
    try:
        body = (
            "    with open('/tmp/0h_host_beacon.txt') as fh:\n"
            "        s = fh.read()\n"
            "    assert s\n"
        )
        root = write_attack_builder(tmp_path / "tmp_read", body,
                                    label="tmp-read")
        provider = private_provider_from_root(root)
        result = _run(provider, sealed_exam_env, root)
        assert isinstance(result, Exception)
    finally:
        os.unlink(host_tmp)


def test_directory_order_cannot_influence_pack(sealed_exam_env, tmp_path):
    """宿主目录列举(排序侧信道)不可用;staging 内列举确定性。"""
    body = (
        "    import os\n"
        "    entries = sorted(os.listdir('/etc'))\n"
        "    assert entries\n"
    )
    root = write_attack_builder(tmp_path / "order_leak", body,
                                label="order-leak")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, root)
    assert isinstance(result, Exception)


def test_private_dev_nodes_present(sealed_exam_env, private_builder_a):
    """私有 /dev 只含最小设备节点;宿主设备不可见。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run

    provider = private_builder_a
    req = attack_request(provider, sealed_exam_env["pack"], _dc(sealed_exam_env))
    record = run_isolated_builder_run(
        provider.builder_identity(), req, builder_root=provider.root)
    sb = record["effective_sandbox"]
    assert set(sb["private_dev_nodes"]) <= {
        "null", "zero", "urandom", "random", "full"}
    assert sb["probes"]["dev_shm_private"]["listing"] == []


def test_seccomp_disabled_profile_reports_degradation(sealed_exam_env,
                                                      tmp_path):
    """C3 真实降级:seccomp 关闭的 run 无法通过主进程沙箱校验。"""
    from rl_curriculum.builder_runner import (
        ALLOW_DESCENDANTS,
        BuilderRunnerProfile,
        BuilderRunnerError,
    )

    profile = BuilderRunnerProfile(
        install_seccomp=False, process_tree_policy=ALLOW_DESCENDANTS)
    body = (
        "    import subprocess, sys\n"
        "    subprocess.run([sys.executable, '-c', 'pass'],\n"
        "                   capture_output=True, check=True)\n"
    )
    root = write_attack_builder(tmp_path / "plain", body, label="plain")
    provider = private_provider_from_root(root)
    result = _run(provider, sealed_exam_env, root, profile=profile)
    # allow_descendants 的 run 本身可执行,但 evidence/verify 拒绝;
    # 若误用 single+seccomp off -> 构造期已拒
    assert not isinstance(result, Exception), str(result)
    # 行为证明(WSL 环境基线 Seccomp 字段恒为 2,不能作为未装证明):
    # seccomp 未安装时 exec 探针跳过、fork 探针泄漏、后代进程计数>0
    assert result["effective_sandbox"]["probes"]["exec_denied"][
        "result"] == "SKIPPED-NO-SECCOMP"
    assert result["effective_sandbox"]["probes"]["fork_denied"][
        "result"] == "LEAKED"
    assert result["child_process_count"] >= 1
    assert result["child_process_attempts"] >= 1
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile as P,
        check_effective_sandbox_report,
    )
    with pytest.raises(BuilderRunnerError):
        check_effective_sandbox_report(
            result["effective_sandbox"], P())
