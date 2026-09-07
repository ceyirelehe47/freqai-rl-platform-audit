# -*- coding: utf-8 -*-
"""R17 控制路径测试 worker(CONTROL_FIXTURE_TEST;任务书 §6.5 批准)。

仅测试使用、无业务数据:不经受控 pipe 协议的**正常**路径复用
真实 worker 的注册/接收实现(rl_curriculum.curriculum261_r17_final.
_worker_delegate——同一份代码,不另写自动 PASS 的握手);故障
变体(半行/坏 JSON/超长/假身份/超范围)是协议故障注入,直接写
pipe。行为由 R17_CF_BEHAVIOR 选择(默认 normal):

  normal            注册→有界等 token→verify→exit 0
  verify_grant      同 normal+二次非生成式权限核验→exit 0
  sleep_cancel      token 后长睡眠(可被协调者取消)
  ignore_cancel     token 后忽略 TERM 长睡眠(升级路径)
  early_exit        注册前 rc=7 退出
  half_line         写半行(无换行)后退出
  no_msg            不发消息,长睡眠
  bad_json          写坏 JSON 行
  oversized         写 >16KiB 注册行
  wrong_identity    写假身份(pid=1/starttime=1;协调者 /proc 核对拒绝)
  extra_ns          请求超范围 namespace
  exit_before_token 注册后立即退出(不等 token)

协调者以 `python -m r17_control_fixture_worker --await-delegation
<w_reg> <r_tok>` 启动本模块(与真实 qualify worker 同一形态)。
不生成任何课程数据、不消费数值 seed、不触达正式 namespace。
"""
from __future__ import annotations

import json
import os
import sys
import time


def _real_delegate(write_fd: int, read_fd: int) -> None:
    from rl_curriculum.curriculum261_r17_final import _worker_delegate
    _worker_delegate(
        write_fd, read_fd,
        tuple(os.environ.get("R17_CF_NAMESPACES", "cf_ns_a").split(",")))


def _fake_register(write_fd: int, *, pid: int | None = None,
                   start: int | None = None,
                   namespaces: list[str] | None = None,
                   payload: bytes | None = None,
                   newline: bool = True) -> None:
    if payload is None:
        ident = {"pid": pid if pid is not None else os.getpid(),
                 "starttime": start if start is not None else 12345}
        msg = json.dumps({"kind": "executor_identity",
                          "identity": ident,
                          "namespaces": namespaces or ["cf_ns_a"]})
        payload = msg.encode("utf-8")
    data = payload + (b"\n" if newline else b"")
    view = memoryview(data)
    while view:
        n = os.write(write_fd, view)
        view = view[n:]


def main() -> int:
    argv = sys.argv[1:]
    behavior = os.environ.get("R17_CF_BEHAVIOR", "normal")
    if "fail-closure" in argv:
        # 双面:monkeypatch 的模块名同样命中协调者的 fail-closure
        # 子命令调用——立即成功(封口不是被测对象)
        return 0
    if "--await-delegation" in argv:
        i = argv.index("--await-delegation")
        write_fd, read_fd = int(argv[i + 1]), int(argv[i + 2])
    else:
        # 无委派 fd=链内普通步骤占位(如"后续不得开始"节点被
        # 正常执行时):直接成功
        return 0
    if behavior == "early_exit":
        return 7
    if behavior == "silent_exit":
        # A01 第一行形态:取得委派 fd 后不写任何身份、以 rc=0
        # 退出(协调者读到 EOF → identity_pipe_eof;worker 自然退出)
        return 0
    if behavior == "no_msg":
        time.sleep(90)
        return 0
    if behavior == "half_line":
        _fake_register(write_fd, payload=b'{"kind": "executor_ide',
                       newline=False)
        return 0
    if behavior == "bad_json":
        _fake_register(write_fd, payload=b'{"kind": "executor_identity" not json')
        return 0
    if behavior == "oversized":
        _fake_register(write_fd,
                       payload=b'{"kind":"executor_identity","pad":"' +
                               b"x" * (17 * 1024) + b'"}')
        return 0
    if behavior == "wrong_identity":
        _fake_register(write_fd, pid=1, start=1)
        time.sleep(30)  # 留给协调者核对窗口
        return 0
    if behavior == "extra_ns":
        # 真实实例身份+超范围 namespace 请求(隔离身份核对与范围核对)
        ident = {"pid": os.getpid(),
                 "starttime": _self_start_ticks()}
        msg = json.dumps({"kind": "executor_identity",
                          "identity": ident,
                          "namespaces": ["cf_ns_a",
                                         "qualification_r17_extra"]})
        os.write(write_fd, msg.encode("utf-8") + b"\n")
        time.sleep(30)
        return 0
    if behavior == "exit_before_token":
        ident = {"pid": os.getpid(),
                 "starttime": _self_start_ticks()}
        msg = json.dumps({"kind": "executor_identity", "identity": ident,
                          "namespaces": ["cf_ns_a"]})
        os.write(write_fd, msg.encode("utf-8") + b"\n")
        return 0
    if behavior == "close_token_read":
        # T13:注册(真实身份,保持进程存活供协调者核对)→关闭
        # token 读端但不退出→协调者 grant 已建,写响应必 BrokenPipe
        ident = {"pid": os.getpid(),
                 "starttime": _self_start_ticks()}
        msg = json.dumps({"kind": "executor_identity", "identity": ident,
                          "namespaces": ["cf_ns_a"]})
        os.write(write_fd, msg.encode("utf-8") + b"\n")
        try:
            os.close(read_fd)
        except OSError:
            pass
        time.sleep(30)  # 存活供核对;由协调者受控终止
        return 0
    # normal / verify_grant / sleep_cancel / ignore_cancel:
    # 真实 worker 注册+接收代码路径
    _real_delegate(write_fd, read_fd)
    if behavior == "verify_grant":
        from rl_curriculum.curriculum261_r17_execgov import (
            R17_EXECUTOR_TOKEN_ENV, verify_executor_token,
        )
        token = os.environ.get(R17_EXECUTOR_TOKEN_ENV, "")
        # 非生成式权限核验(不调用任何生成/seed 派生)
        verify_executor_token(token, "cf_ns_a")
    if behavior == "sleep_cancel":
        time.sleep(90)
        return 0
    if behavior == "ignore_cancel":
        import signal as _signal
        _signal.signal(_signal.SIGTERM, _signal.SIG_IGN)
        time.sleep(90)
        return 0
    return 0


def _self_start_ticks() -> int:
    with open("/proc/self/stat") as fh:
        text = fh.read()
    rp = text.rindex(")")
    return int(text[rp + 2:].split()[19])


if __name__ == "__main__":
    sys.exit(main())
