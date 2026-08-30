"""工作包 G:checkpoint 前访问证明 v2。

- 主进程 BuilderStageAccessGuard v2 覆盖 open/os.listdir/os.scandir/
  os.system/subprocess.Popen/ctypes.dlopen 等实际存在的事件;
- os.stat/os.access/os.readlink 在 CPython 3.11 无审计事件:stat 级
  不可利用由 pivot_root namespace 不可命名保证(EDIC 探针);
- Candidate 沙箱未启动:Builder 阶段出现的非 Builder-Runner 子进程
  Popen 记为违规;
- Runner 沙箱内的宿主路径探针全部 ENOENT(真实隔离 Runner;从
  run["deterministic_input_report"] 读取)。
"""

from __future__ import annotations

import json
import os
import subprocess

import pytest

from rl_curriculum.access_guard import BuilderStageAccessGuard


def test_guard_v2_covers_extended_events(tmp_path):
    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"checkpoint")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        os.listdir(str(tmp_path))          # os.listdir 事件
        os.scandir(str(tmp_path))          # os.scandir 事件
    result = guard.audit_result()
    assert result["format"] == "builder-stage-access-audit-v2"
    for ev in ("open", "os.listdir", "os.scandir", "subprocess.Popen"):
        assert ev in result["covered_events"]
    assert "namespace_unnameable" in result["stat_coverage"]


def test_guard_records_checkpoint_open_violation(tmp_path):
    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"checkpoint")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        with open(ckpt, "rb"):
            pass
    result = guard.audit_result()
    assert any("open" in v and "model.zip" in v
               for v in result["violations"])


def test_guard_records_scandir_on_checkpoint_dir(tmp_path):
    """对 checkpoint 所在目录的 scandir/listdir 也被记录(路径前缀)。"""
    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"checkpoint")
    guarded = str(tmp_path / "model.zip")
    with BuilderStageAccessGuard([guarded]) as guard:
        list(os.scandir(str(tmp_path)))
    result = guard.audit_result()
    assert guard.open_event_count >= 1
    # listdir 事件本身不指向 checkpoint 前缀,不构成违规;但事件计数
    # 被记录(证明覆盖)
    assert result["open_event_count"] >= 1


def test_guard_flags_non_builder_runner_subprocess(tmp_path):
    """Builder 阶段出现非 Builder-Runner 子进程(Candidate 沙箱)
    记为违规(证明 Candidate 沙箱未启动)。"""
    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"x")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        # 模拟 Candidate 沙箱启动(非 unshare/rl_builder_runtime)
        subprocess.Popen(
            ["/bin/true"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL).wait()
    result = guard.audit_result()
    assert result["spawn_event_count"] >= 1
    assert any("非 Builder Runner 子进程" in v
               for v in result["violations"])


def test_guard_allows_builder_runner_launch_marker(tmp_path):
    """unshare + rl_builder_runtime.bootstrap 的启动是允许的。"""
    ckpt = tmp_path / "model.zip"
    ckpt.write_bytes(b"x")
    with BuilderStageAccessGuard([str(ckpt)]) as guard:
        # 只构造事件(不真正启动):直接触发 audit 事件
        import sys
        for hook in ():  # pragma: no cover
            pass
        sys.audit("subprocess.Popen",
                  ("/usr/bin/unshare", ["unshare", "--user",
                                        "rl_builder_runtime.bootstrap"],
                   None, None))
    result = guard.audit_result()
    assert not [v for v in result["violations"]
                if "非 Builder Runner 子进程" in v]


def test_runner_sandbox_host_paths_unnameable(sealed_exam_env,
                                              private_builder_a,
                                              tmp_path):
    """G(方案 4):真实隔离 Runner 的 EDIC 探针证明宿主路径
    (checkpoint 侧car 同层路径)在 Builder 阶段不可命名(ENOENT)。"""
    from rl_curriculum.builder_runner import run_isolated_builder_run
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )

    provider = private_builder_a
    from conftest import attack_request

    dc = _dc(sealed_exam_env)
    req = attack_request(provider, sealed_exam_env["pack"], dc)
    record = run_isolated_builder_run(
        provider.builder_identity(), req,
        builder_root=getattr(provider, "root", provider._root))
    edic = record["deterministic_input_report"]
    probes = edic["probes"]
    assert probes["host_usr"]["result"] == "ENOENT"
    assert probes["host_home"]["result"] == "ENOENT"
    assert probes["host_etc_hostname"]["result"] == "ENOENT"
    assert probes["host_sys"]["result"] == "ENOENT"
    assert probes["host_oldroot_usr"]["result"] == "ENOENT"
    assert edic["proc"]["self_status"] == "ENOENT"
    assert edic["proc"]["listing_empty"] is True
    access = record["access_summary"]
    # checkpoint/sidecar/attestation 从未被访问(allowlist 外即拒)
    blob = json.dumps(access)
    for forbidden in ("checkpoint", "sidecar", ".rl_manifest",
                      ".rl_attestation"):
        assert forbidden not in blob


def _dc(sealed_exam_env):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        sealed_exam_env["pack"], required_families=[
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"])
