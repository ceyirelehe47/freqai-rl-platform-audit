#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R25 工程替身工作者探针(RouteC_R25_FinalClosure_TrainingReadiness_v1 版)。

明确边界:本脚本不 import 任何研究生成模块、不生成任何研究语料;
只做有界 CPU/内存活动 + 心跳 + 进程实例登记,用于验证 R25 启动链
(r25_batch_launcher_v2.sh 的 timeout --foreground 包装)下真实工作者
(含子/孙进程)进入 guest sampler 任务级遥测,以及受控短超时后
**已登记实例逐一退出**的核验。

v2 登记合同(本轮 F 出口收敛;旧版缺陷经 2026-09-28 独立审查在
真实进程反例中确认,并已在本机 WSL 复现):
  旧缺陷:
    1) writer 对自有实例 /proc stat 读取失败(PermissionError/
       FileNotFoundError)时把 start_ticks=-1 写入登记并照常发布;
    2) checker 只验 int 类型,-1/布尔/负数全部放行;
    3) created_descendants=true 但 child/grandchild 记录缺失的
       副本照样判 clean;
    4) 无效登记身份(-1)与实际存活实例 ticks 不匹配被解释成
       pid_reused_old_dead——把"从未取得可信身份"当"已知旧实例
       已退出回收"。
  本版行为:
    producer(身份确认,确认不了就拒绝,绝不发布 -1):
      - 身份来源优先级:子进程握手自报(子自读 /proc/self/stat 与
        自有孙 /proc/<孙>/stat,属已拥有实例的报告)优先;握手值
        无效时对**同一已拥有 pid** 做有界直读(次数/时长有限,只
        观测同一实例,失败事实保留);两来源冲突即拒绝;
      - 任何 root/child/grandchild 身份无法确认 → RegistrationError:
        不发布登记文件(原子写 tmp+os.replace,无半写)、以自有
        句柄收尾子/孙、退出码 6、失败事实写 <registry>.failed.json
        (目录不可写时仅打 stderr);
      - root 身份只来自自身 /proc 读取,失败即拒绝。
    consumer(完整性/关联性校验通过后才逐实例判定):
      - format=r25-worker-registry-v2(v1 为历史缺陷格式,一律 rc4);
      - created_roles 与 instances 角色多重集必须一致(声明已创建
        却缺 child/grandchild 记录=rc4;多余/重复同样 rc4);
      - 每实例 pid>0、start_ticks>=1,均严格 int(布尔/浮点/缺值/
        负数/占位全拒,原因指明身份字段);pid 全局唯一;恰一个
        root 且 root_pid 与之相等;grandchild 蕴含 child;
      - 无后代正例必须 created_roles=["root"] 且
        no_descendants_verified=true + 非空 basis;空清单不默认成功;
      - 身份全部有效后才做逐实例判定:/proc 消失=dead_gone;存活
        且 starttime 一致=alive(必非 clean);state Z=zombie_unreaped;
        starttime 不一致=pid_reused_old_dead(仅当登记身份有效才有
        此解释;旧实例必已结束,不向新实例发信号);无法读取=
        unobservable(不 clean)。
  清理与检测分离:checker 永不发信号;驱动器/launcher 只按
  (pid, start_ticks) 双重匹配的自有实例收尾;登记身份不可信时
  不得凭登记里的裸 PID 清理。

模式:
  burn  --seconds N:~30% 单核负载;--spawn-child 派生合作子进程
                     (子再派生孙,均带 SIGTERM 责任清理);
  sleep --seconds N:纯睡眠(供短超时杀伤正例);
  orphan --seconds N:工程负例夹具——派生**无清理**的子/孙,握手后
                     写登记并立即退出,留下存活孤儿供 checker 反例;
  --check-registry F:只读核验登记文件(上述 consumer 规则)。

退出码(check-registry):0=clean;2=存在僵尸(已终止未回收);
3=存在存活本任务实例;4=登记缺失/不完整/身份不合法;
5=无法观测。
工作者自身:0=正常结束;6=登记失败(登记文件未发布,自有实例已收尾)。
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

REGISTRY_FORMAT = "r25-worker-registry-v2"
_CHILD_PROC: subprocess.Popen | None = None

#: 对同一已拥有实例身份直读的有界重试(次数×间隔;只观测同一 pid,
#: 不拿后来的同 PID 未知实例替代)
_IDENTITY_RETRY_ATTEMPTS = 3
_IDENTITY_RETRY_DELAY_S = 0.05

_ROLES = ("root", "child", "grandchild")


class RegistrationError(RuntimeError):
    """登记身份无法确认/来源冲突/登记无法写出。

    语义:本任务不得进入长循环,不得发布任何可消费登记;调用方
    负责以自有句柄收尾已创建实例并退出码 6。
    """

    def __init__(self, reason: str, facts: dict | None = None):
        super().__init__(reason)
        self.facts: dict = facts or {}


_CHILD_CODE = r"""
import json, os, signal, subprocess, sys, time
def _ticks(pid):
    try:
        s = open(f"/proc/{pid}/stat").read()
        f = s[s.rindex(")") + 2:].split()
        return int(f[19])
    except Exception:
        return -1
g = subprocess.Popen([sys.executable, "-c",
                      "import time\nwhile True: time.sleep(3600)"])
print(json.dumps({"role": "child", "pid": os.getpid(),
                  "start_ticks": _ticks(os.getpid()),
                  "grandchild": g.pid,
                  "grandchild_start_ticks": _ticks(g.pid)}), flush=True)

def _term(signum, frame):
    g.terminate()
    try:
        g.wait(timeout=5)
    except subprocess.TimeoutExpired:
        g.kill(); g.wait()
    sys.exit(128 + signum)

signal.signal(signal.SIGTERM, _term)
try:
    time.sleep(float(sys.argv[1]))
finally:
    g.terminate()
    try:
        g.wait(timeout=5)
    except subprocess.TimeoutExpired:
        g.kill(); g.wait()
"""


# orphan 模式专用:子/孙均为无信号处理的纯睡眠者(负例需要"没被
# 谁清理"的存活后代;TTL 由驱动器参数限定,外部 finally 兜底回收)。
_ORPHAN_CHILD_CODE = r"""
import json, os, subprocess, sys, time
def _ticks(pid):
    try:
        s = open(f"/proc/{pid}/stat").read()
        f = s[s.rindex(")") + 2:].split()
        return int(f[19])
    except Exception:
        return -1
ttl = str(float(sys.argv[1]))
g = subprocess.Popen([sys.executable, "-c",
                      "import sys, time\ntime.sleep(float(sys.argv[1]))",
                      ttl])
print(json.dumps({"role": "orphan-child", "pid": os.getpid(),
                  "start_ticks": _ticks(os.getpid()),
                  "grandchild": g.pid,
                  "grandchild_start_ticks": _ticks(g.pid)}), flush=True)
time.sleep(float(ttl))
"""


def _utc() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _identity(label: str) -> dict:
    return {
        "label": label,
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "pgid": os.getpgid(0),
        "sid": os.getsid(0),
        "utc": _utc(),
    }


def _read_proc_stat(pid: int) -> str:
    """唯一 /proc stat 读取口(测试故障注入的观测边界)。"""
    with open(f"/proc/{pid}/stat", encoding="utf-8") as fh:
        return fh.read()


def _proc_instance(pid: int) -> tuple[bool, str, int] | None:
    """(exists, state, start_ticks);None=无法观测。"""
    try:
        text = _read_proc_stat(pid)
    except FileNotFoundError:
        return (False, "", -1)
    except OSError:
        return None
    try:
        rp = text.rindex(")")
        fields = text[rp + 2:].split()
        return (True, fields[0], int(fields[19]))  # state, starttime
    except (ValueError, IndexError):
        return None


def _valid_ticks(value) -> bool:
    """有效启动身份:/proc stat field22 实测正整数;严格 int(拒布尔)。"""
    return type(value) is int and value >= 1


def _confirm_identity(pid: int, handshake_ticks, role: str) -> int:
    """确认一个已拥有实例的启动身份;确认不了即抛 RegistrationError。

    来源优先级:握手自报(已拥有实例的报告)优先;握手无效时对同一
    pid 有界直读。两来源均有效而取值冲突 → 拒绝(身份混淆,宁可
    不登记)。直读 PermissionError/不存在等故障不冒充任何身份。
    """
    facts: dict = {"pid": pid, "role": role}
    obs = _proc_instance(pid)
    if obs is not None and obs[0]:
        facts["direct_observed_ticks"] = obs[2]
        if _valid_ticks(handshake_ticks) and handshake_ticks != obs[2]:
            raise RegistrationError(
                f"{role} 身份来源冲突: 握手 {handshake_ticks} vs 实测 "
                f"{obs[2]}(pid={pid})", {**facts, "handshake_ticks":
                                         handshake_ticks, "conflict": True})
    if _valid_ticks(handshake_ticks):
        facts["source"] = "handshake_self_report"
        return int(handshake_ticks)
    last = ("unobservable" if obs is None
            else ("proc_missing" if not obs[0] else "no_ticks"))
    for _ in range(_IDENTITY_RETRY_ATTEMPTS - 1):
        time.sleep(_IDENTITY_RETRY_DELAY_S)
        obs = _proc_instance(pid)
        if obs is not None and obs[0]:
            facts["source"] = "writer_direct_proc_read"
            facts["direct_observed_ticks"] = obs[2]
            return obs[2]
        last = ("unobservable" if obs is None
                else ("proc_missing" if not obs[0] else "no_ticks"))
    facts["last_observation"] = last
    facts["retry_attempts"] = _IDENTITY_RETRY_ATTEMPTS
    raise RegistrationError(
        f"{role} 启动身份无法确认({last};pid={pid};握手值="
        f"{handshake_ticks!r})——未观测身份不得写为已登记", facts)


def _spawn_child(seconds: float) -> tuple[subprocess.Popen, dict | None]:
    """合作子进程(孙由子派生,均带 SIGTERM 责任清理)。

    返回 (proc, handshake|None);握手含 child/grandchild 的 pid 与
    start_ticks(子自读 /proc,属已拥有实例报告)。握手不可用返回
    None,由登记环节显式失败。
    """
    proc = subprocess.Popen(
        [sys.executable, "-c", _CHILD_CODE, str(min(seconds, 3600.0))],
        stdout=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        info = json.loads(line)
        if int(info["pid"]) != proc.pid:
            raise ValueError("握手 pid 与句柄不一致")
        return proc, info
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return proc, None


def _spawn_orphan(seconds: float) -> tuple[subprocess.Popen, dict | None]:
    """orphan 负例夹具:无信号处理的纯睡眠子/孙(握手协议同上)。"""
    proc = subprocess.Popen(
        [sys.executable, "-c", _ORPHAN_CHILD_CODE,
         str(min(seconds, 300.0))],
        stdout=subprocess.PIPE, text=True)
    try:
        line = proc.stdout.readline()
        info = json.loads(line)
        if int(info["pid"]) != proc.pid:
            raise ValueError("握手 pid 与句柄不一致")
        return proc, info
    except (json.JSONDecodeError, KeyError, ValueError, OSError):
        return proc, None


def _write_registry(path: Path, *, label: str,
                    child_pid: int | None, grand_pid: int | None,
                    handshake: dict | None) -> None:
    """确认并原子发布登记;任何身份未确认/写不出即抛 RegistrationError。

    绝不发布含占位身份(-1/布尔等)或"已创建后代却缺记录"的登记;
    原子写(tmp+os.replace)保证不存在半写文件。
    """
    root_ticks = _confirm_identity(os.getpid(), None, "root")
    instances = [{"pid": os.getpid(), "start_ticks": root_ticks,
                  "role": "root"}]
    created_roles = ["root"]
    identity_sources = {"root": "writer_direct_proc_read"}
    hs = handshake or {}
    if child_pid is not None:
        child_ticks = _confirm_identity(
            child_pid, hs.get("start_ticks"), "child")
        instances.append({"pid": child_pid, "start_ticks": child_ticks,
                          "role": "child"})
        created_roles.append("child")
        identity_sources["child"] = (
            "handshake_self_report"
            if _valid_ticks(hs.get("start_ticks"))
            else "writer_direct_proc_read")
        if grand_pid is None:
            raise RegistrationError(
                "grandchild 身份来源缺失: 已创建后代但握手不可用,"
                "不得发布不完整登记",
                {"child_pid": child_pid, "handshake_keys":
                 sorted(hs.keys())})
        grand_ticks = _confirm_identity(
            grand_pid, hs.get("grandchild_start_ticks"), "grandchild")
        instances.append({"pid": grand_pid, "start_ticks": grand_ticks,
                          "role": "grandchild"})
        created_roles.append("grandchild")
        identity_sources["grandchild"] = (
            "handshake_self_report"
            if _valid_ticks(hs.get("grandchild_start_ticks"))
            else "writer_direct_proc_read")
    created = child_pid is not None
    registry = {
        "format": REGISTRY_FORMAT,
        "created_utc": _utc(),
        "driver_label": label,
        "root_pid": os.getpid(),
        "created_descendants": created,
        "created_roles": created_roles,
        "no_descendants_verified": (not created),
        # created_descendants=False 时:由创建者(本进程,未 spawn 任何
        # 子进程)显式声明并记录依据;空登记不默认成功。
        "no_descendants_basis": ("创建者未调用任何 spawn(--spawn-child "
                                 "未提供且非 orphan 模式)") if not created
                                else None,
        "identity_sources": identity_sources,
        "instances": instances,
    }
    payload = json.dumps(registry, indent=1, ensure_ascii=False) + "\n"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(payload, encoding="utf-8")
        os.replace(tmp, path)
    except OSError as exc:
        raise RegistrationError(
            f"登记写入失败({exc});不发布、不继续长任务",
            {"registry_path": str(path), "write_error": str(exc)}) from exc


def _emit_registration_failure(args, exc: RegistrationError,
                               spawned: dict) -> None:
    """登记失败事实:尽力落 <registry>.failed.json,不可写则 stderr。"""
    record = {"event": "registration_failed", "utc": _utc(),
              "label": args.label, "mode": args.mode,
              "reason": str(exc), "facts": exc.facts,
              "spawned": spawned,
              "published_registry": False}
    reg = getattr(args, "registry_out", None)
    dumped = json.dumps(record, ensure_ascii=False)
    if reg:
        try:
            fp = Path(reg + ".failed.json")
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(dumped + "\n", encoding="utf-8")
        except OSError as werr:
            print(json.dumps({**record,
                              "failed_facts_write_error": str(werr)},
                             ensure_ascii=False),
                  file=sys.stderr, flush=True)
        else:
            print(json.dumps({**record, "failed_facts_path": str(fp)},
                             ensure_ascii=False),
                  file=sys.stderr, flush=True)
    else:
        print(dumped, file=sys.stderr, flush=True)


def _signal_if_same_instance(pid: int, ticks, sig=signal.SIGTERM) -> bool:
    """仅当 (pid,start_ticks) 双匹配且可观测时发信号;否则不动。

    登记失败收尾用:身份不可确认的实例绝不凭裸 PID 清理,由有限
    TTL 与驱动器兜底。
    """
    if not _valid_ticks(ticks):
        return False
    obs = _proc_instance(pid)
    if obs is not None and obs[0] and obs[2] == ticks:
        try:
            os.kill(pid, sig)
            return True
        except OSError:
            return False
    return False


def _check_registry(path: Path) -> int:
    """只读核验(绝不禁令/杀进程);完整性与关联性通过后才逐实例判定。"""
    try:
        registry = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"verdict": "registry_invalid",
                          "rc": 4, "reason": str(exc)}, ensure_ascii=False))
        return 4
    if not isinstance(registry, dict) \
            or registry.get("format") != REGISTRY_FORMAT:
        print(json.dumps({"verdict": "registry_invalid", "rc": 4,
                          "reason": f"format 不符(要求 {REGISTRY_FORMAT};"
                                    "v1 为历史缺陷格式,一律拒绝)"},
                         ensure_ascii=False))
        return 4

    def _incomplete(reason: str) -> int:
        print(json.dumps({"verdict": "registry_incomplete", "rc": 4,
                          "reason": reason}, ensure_ascii=False))
        return 4

    created_roles = registry.get("created_roles")
    created_desc = registry.get("created_descendants")
    if not isinstance(created_roles, list) or not created_roles \
            or any(r not in _ROLES for r in created_roles) \
            or len(set(created_roles)) != len(created_roles):
        return _incomplete(f"created_roles 不合法: {created_roles!r}")
    if "root" not in created_roles:
        return _incomplete("created_roles 缺 root")
    if "grandchild" in created_roles and "child" not in created_roles:
        return _incomplete("created_roles 含 grandchild 却无 child,矛盾")
    if type(created_desc) is not bool:
        return _incomplete(
            f"created_descendants 不是布尔: {created_desc!r}")
    if created_desc != (created_roles != ["root"]):
        return _incomplete(
            f"created_descendants({created_desc}) 与 created_roles("
            f"{created_roles}) 矛盾")
    no_ver = registry.get("no_descendants_verified")
    basis = registry.get("no_descendants_basis")
    if not created_desc:
        if no_ver is not True or not isinstance(basis, str) \
                or not basis.strip():
            return _incomplete(
                "无后代声明缺可信依据(verified/basis);空清单或无依据"
                "材料不能自证成功")
    elif no_ver is not False or basis is not None:
        return _incomplete(
            f"已创建后代却带无后代声明(verified={no_ver!r},"
            f"basis={basis!r}),矛盾")

    instances = registry.get("instances")
    if not isinstance(instances, list) or not instances:
        return _incomplete("instances 缺失/为空(空登记不默认成功)")
    seen_pids: dict[int, str] = {}
    inst_roles: list[str] = []
    for inst in instances:
        if not isinstance(inst, dict):
            return _incomplete(f"实例条目不是对象: {inst!r}")
        role = inst.get("role")
        if role not in _ROLES:
            return _incomplete(f"实例角色不合法: {role!r}")
        pid = inst.get("pid")
        if type(pid) is not int or pid <= 0:
            return _incomplete(
                f"实例身份不合法(pid): {role} pid={pid!r}"
                "(须正整数;布尔/浮点/缺值均拒)")
        ticks = inst.get("start_ticks")
        if type(ticks) is not int or ticks < 1:
            return _incomplete(
                f"实例身份不合法(start_ticks): {role} pid={pid} "
                f"start_ticks={ticks!r}(未观测身份/占位值不得冒充已"
                "登记;须 /proc stat field22 实测正整数,布尔/负数/"
                "浮点/缺值均拒)")
        if pid in seen_pids:
            return _incomplete(
                f"重复/冲突实例 pid={pid}(role {seen_pids[pid]} 与 "
                f"{role})")
        seen_pids[pid] = role
        inst_roles.append(role)
    if sorted(inst_roles) != sorted(created_roles):
        return _incomplete(
            f"实例清单与已创建后代声明矛盾: created_roles="
            f"{created_roles}, 实列角色={inst_roles}(声明已创建却缺"
            " child/grandchild 记录,或多出/重复条目,均不 clean)")
    root_pid = registry.get("root_pid")
    if type(root_pid) is not int or root_pid <= 0:
        return _incomplete(f"root_pid 不合法: {root_pid!r}")
    root_insts = [i for i in instances if i["role"] == "root"]
    if len(root_insts) != 1 or root_insts[0]["pid"] != root_pid:
        return _incomplete(
            f"缺 root 关联: root_pid={root_pid!r} 与 root 实例不一致")

    results = []
    rc = 0
    for inst in instances:
        obs = _proc_instance(inst["pid"])
        if obs is None:
            status = "unobservable"
            rc = max(rc, 5)
        elif not obs[0]:
            status = "dead_gone"
        elif obs[2] != inst["start_ticks"]:
            # 登记身份已确证有效;同 PID 不同 starttime = 实例身份
            # 不匹配——旧实例必已退出回收(pid 才可能被复用);不向
            # 新实例发信号。
            status = "pid_reused_old_dead"
        elif obs[1] == "Z":
            status = "zombie_unreaped"
            rc = max(rc, 2)
        else:
            status = "alive"
            rc = max(rc, 3)
        results.append({**inst, "status": status})
    verdict = {0: "clean", 2: "zombie_unreaped", 3: "leaked_alive",
               5: "unobservable"}[rc]
    print(json.dumps({"verdict": verdict, "rc": rc,
                      "checked_utc": _utc(),
                      "instances": results}, ensure_ascii=False))
    return rc


def _burn(seconds: float, label: str, heartbeat: Path) -> None:
    deadline = time.monotonic() + seconds
    n = 0
    with open(heartbeat, "a", encoding="utf-8") as fh:
        while time.monotonic() < deadline:
            t0 = time.monotonic()
            while time.monotonic() - t0 < 0.03:  # ~30ms 计算脉冲
                n += 1
                _ = sum(i * i for i in range(2000))
            fh.write(json.dumps(
                {**_identity(label), "iter": n}, ensure_ascii=False)
                + "\n")
            fh.flush()
            time.sleep(0.07)  # ~30% 单核,轻负载


def _install_sigterm_cleanup(child_pid: int | None) -> None:
    def _handler(signum, frame):
        if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
            _CHILD_PROC.terminate()
            try:
                _CHILD_PROC.wait(timeout=5)
            except subprocess.TimeoutExpired:
                _CHILD_PROC.kill()
                _CHILD_PROC.wait()
        sys.exit(128 + signum)
    signal.signal(signal.SIGTERM, _handler)


def _terminate_child() -> None:
    if _CHILD_PROC is not None and _CHILD_PROC.poll() is None:
        _CHILD_PROC.terminate()
        try:
            _CHILD_PROC.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _CHILD_PROC.kill()
            _CHILD_PROC.wait()


def main(argv: list[str] | None = None) -> int:
    global _CHILD_PROC
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--label", default="worker")
    ap.add_argument("--mode",
                    choices=("burn", "sleep", "orphan"), default="burn")
    ap.add_argument("--seconds", type=float, default=30.0)
    ap.add_argument("--spawn-child", action="store_true")
    ap.add_argument("--heartbeat", default=None)
    ap.add_argument("--identity-out", default=None)
    ap.add_argument("--registry-out", default=None)
    ap.add_argument("--check-registry", action="store_true")
    ap.add_argument("--identity", default=None)
    args = ap.parse_args(argv)

    if args.check_registry:
        return _check_registry(Path(args.identity))

    ident = _identity(args.label)
    if args.identity_out:
        Path(args.identity_out).write_text(
            json.dumps(ident, indent=1) + "\n", encoding="utf-8")
    print(json.dumps({**ident, "mode": args.mode,
                      "seconds": args.seconds}), flush=True)
    _install_sigterm_cleanup(None)
    registry_path = Path(args.registry_out) if args.registry_out else None

    if args.mode == "orphan":
        # 工程负例:留下无清理的存活子/孙后立即退出(不调用
        # _terminate_child;TTL 有限,驱动器 finally 兜底回收)。
        proc, hs = _spawn_orphan(args.seconds)
        spawned = {"child": {"pid": proc.pid,
                             "start_ticks": (hs or {}).get(
                                 "start_ticks")},
                   "grandchild": {"pid": (hs or {}).get("grandchild"),
                                  "start_ticks": (hs or {}).get(
                                      "grandchild_start_ticks")}}
        print(json.dumps({"role": "orphan-root", "pid": os.getpid(),
                          "event": "spawned", "spawned": spawned,
                          "registry": str(registry_path)}), flush=True)
        try:
            if registry_path:
                _write_registry(
                    registry_path, label=args.label,
                    child_pid=proc.pid,
                    grand_pid=(hs or {}).get("grandchild"),
                    handshake=hs)
        except RegistrationError as exc:
            _emit_registration_failure(args, exc, spawned)
            # 收尾只动自有实例:orphan 子无信号处理器,terminate 即
            # 终止;孙仅在握手身份有效且当前可观测匹配时发信号,
            # 否则留给有限 TTL/驱动器兜底(绝不凭不可信身份清理)。
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
            _signal_if_same_instance(
                spawned["grandchild"]["pid"],
                spawned["grandchild"]["start_ticks"])
            return 6
        print(json.dumps({"role": "orphan-root", "pid": os.getpid(),
                          "child": spawned["child"]["pid"],
                          "grandchild": spawned["grandchild"]["pid"],
                          "registry": str(registry_path)}), flush=True)
        proc.stdout.close()
        return 0  # 立即退出,不等待不清理

    child_pid: int | None = None
    grand_pid: int | None = None
    hs: dict | None = None
    if args.spawn_child:
        _CHILD_PROC, hs = _spawn_child(args.seconds)
        child_pid = _CHILD_PROC.pid
        grand_pid = (hs or {}).get("grandchild")
    if child_pid is not None:
        print(json.dumps({"role": "root", "event": "spawned",
                          "spawned": {"child": {
                              "pid": child_pid,
                              "start_ticks": (hs or {}).get(
                                  "start_ticks")},
                              "grandchild": {
                                  "pid": grand_pid,
                                  "start_ticks": (hs or {}).get(
                                      "grandchild_start_ticks")}}}),
              flush=True)
    try:
        if registry_path:
            # 进入长循环/退出前完成登记;身份确认不了即显式失败,
            # 不发布任何可消费登记,也不开始长任务。
            _write_registry(registry_path, label=args.label,
                            child_pid=child_pid, grand_pid=grand_pid,
                            handshake=hs)
    except RegistrationError as exc:
        _emit_registration_failure(
            args, exc,
            {"child": {"pid": child_pid,
                       "start_ticks": (hs or {}).get("start_ticks")}
             if child_pid is not None else None,
             "grandchild": {"pid": grand_pid,
                            "start_ticks": (hs or {}).get(
                                "grandchild_start_ticks")}
             if grand_pid is not None else None})
        # 自有实例收尾:合作子进程的 SIGTERM 处理器会连带终止孙。
        _terminate_child()
        return 6
    if args.mode == "burn":
        _burn(args.seconds, args.label,
              Path(args.heartbeat or "/tmp/r25_worker_heartbeat.jsonl"))
    else:
        time.sleep(args.seconds)
    _terminate_child()
    print(json.dumps({**_identity(args.label), "ended": True}),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
