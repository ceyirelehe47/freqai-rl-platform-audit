"""工作包 A4/G7:fd 与协议通道攻击矩阵。

- Builder 无法读 stdin(Seal 时彻底关闭;final filter 的 read 白名单
  只有 RESULT_ACK_FD=88);
- fd1/2 已是 /dev/null(print/write 不可见且无害);
- RESULT_FD 是唯一真实通道:Compute 段注入的字节导致协议违规
  (Supervisor 期待恰好一行 final 帧,任何注入行 -> fail closed);
- 无 /proc/self/fd 可枚举(/proc 不存在;Compute 内列目录被拒)。
"""

from __future__ import annotations


def test_read_stdin_rejected(run_attack2j):
    """G7:os.read(0) 消耗协议字节——fd 0 已关闭且不在 final filter
    的 read 白名单(fd=88),syscall 层 EPERM;异常未捕获时构建
    fail closed。"""
    outcome = run_attack2j(
        "    import os\n"
        "    data = os.read(0, 64)\n"
        "    notes = {'stolen': data.hex()}\n",
        label="read-stdin")
    assert not isinstance(outcome, dict), \
        f"stdin 可读且取到协议字节: {outcome}"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError",
                          "BuilderUncertainError"), outcome


def test_write_stdout_stderr_harmless(run_attack2j):
    """G7:print(fd1) 无害;Builder 无合法途径获得 os/sys 引用。

    formal 语义下 Builder 拿不到 os(顶层 import 禁/Compute 内 import
    违规)——os.write(1/2) 攻击被依赖面合同前置阻断(纵深第一层);
    唯一无 import 的输出原语 print 落 fd1=/dev/null。判定:run 成功
    本身就是证明——行协议(恰好一行 quiesce + 一行 final)未被破坏。"""
    denied = run_attack2j(
        "    import os\n"
        "    os.write(1, b'FAKE')\n"
        "    notes = {'w': True}\n",
        label="oswrite-denied")
    assert not isinstance(denied, dict), \
        "Compute 内 import os 未被拒绝(os.write 攻击面)"
    assert denied[0] in ("BuilderRunnerError", "BuilderProvenanceError")

    outcome = run_attack2j(
        "    print('FAKE-STDOUT-LINE')\n"
        "    notes = {'p': True}\n",
        label="print-fd1")
    assert isinstance(outcome, dict), \
        f"print 到 fd1(/dev/null)被误判失败: {outcome}"


def test_write_result_fd_injection_fails(run_attack2j):
    """G7 核心:Builder 暴力发现 RESULT_FD 并注入伪造 final 行——
    Supervisor 状态机只接受恰好一行合法 final 帧,注入导致协议
    违规 fail closed(不产生可信 output)。"""
    outcome = run_attack2j(
        "    import os\n"
        "    for fd in range(80, 96):\n"
        "        try:\n"
        "            os.write(fd, b'{\"protocol\": \"x\", \"phase\": "
        "\"final\", \"status\": \"ok\"}\\n')\n"
        "        except OSError:\n"
        "            pass\n"
        "    notes = {'injected': True}\n",
        label="inject-result-fd")
    assert not isinstance(outcome, dict), \
        "RESULT_FD 注入形成了可信 output"
    assert outcome[0] in ("BuilderRunnerError", "BuilderProvenanceError",
                          "BuilderUncertainError"), outcome


def test_proc_self_fd_absent(run_attack2j):
    """G7:/proc/self/fd 不存在(/proc 完全未挂载;Compute 内列目录
    本身被 final filter 拒)。"""
    outcome = run_attack2j(
        "    import os\n"
        "    fds = os.listdir('/proc/self/fd')\n"
        "    notes = {'fds': fds}\n",
        label="proc-self-fd")
    assert not isinstance(outcome, dict), "/proc/self/fd 可访问"
    assert outcome[0] in ("BuilderRunnerError",
                          "BuilderProvenanceError"), outcome


def test_future_ack_unreadable(run_attack2j):
    """G7:读取未来 ACK——stdin 在 Seal 时已关闭且 read 仅允许
    fd=88;Compute 内读 stdin 被拒(fail closed)。"""
    outcome = run_attack2j(
        "    import os\n"
        "    chunks = []\n"
        "    data = os.read(0, 256)\n"
        "    chunks.append(data.hex() if data else 'EOF')\n"
        "    notes = {'chunks': chunks}\n",
        label="future-ack")
    assert not isinstance(outcome, dict), \
        "stdin 有协议字节可偷(未来 ACK 可读)"
    assert outcome[0] in ("BuilderRunnerError",
                          "BuilderProvenanceError"), outcome


def test_result_fd_closed_fds_reported(tmp_path, seed_pack_and_dc):
    """A4:真实链路的 fd 隔离状态进入 sealed_compute 证据。"""
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
        write_private_builder,
    )

    root = write_private_builder(tmp_path / "fdiso-builder")
    provider = private_provider_from_root(root)
    seed, dc = seed_pack_and_dc
    run = run_isolated_builder_run(
        provider.builder_identity(),
        provider.frozen_build_request(seed, dc),
        builder_root=root, profile=BuilderRunnerProfile())
    fd_iso = run["runtime_lock"]["sealed_compute"]["fd_isolation"]
    assert fd_iso["stdin"] == "closed"
    assert fd_iso["stdout"] == "redirected-devnull"
    assert fd_iso["stderr"] == "redirected-devnull"
    assert fd_iso["result_fd"] == 87
    assert fd_iso["result_ack_fd"] == 88
