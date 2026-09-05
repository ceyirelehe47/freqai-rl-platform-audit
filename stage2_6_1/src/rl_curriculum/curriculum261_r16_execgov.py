# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R16 执行治理内核(Execution Governance Kernel)。

R16 设计文档 §4/§6/§7/§8 的唯一实现:所有能够改变正式状态的路径都
经过本模块。它负责权限、生命周期、状态提交与证据边界,不修改生成
分布、统计规则或领域计算。

三条责任边界(§4.1):
- 领域计算层(generator/preprocess/reference/评估/统计)接收本模块
  授权的运行上下文,不决定 iteration 能否重新开始;
- 本模块 = 唯一正式会话 + 冻结身份 + 有效执行授权 + exposure +
  权限撤销 + 终态 + 运行事实;
- 证据 reader/report 只读已发布证据,读取失败不隐式生成数据。

权威状态源(§8.2):`r16_execution_journal.jsonl` 是唯一权威生命周期
记录;exposure marker 等 JSON 是其派生投影。记录损坏、截断、矛盾
或缺失时授权 fail closed(R16JournalCorruption),不得静默跳过解析
失败的事件后认为"从未 exposure"。

与 R15 的本质区别(§2.3 缺口修复):
- R15 终态 writer 只校验 plan digest,任何进程在 running 窗口内都
  能翻转终态;R16 终态提交要求持有当前会话的所有权凭证;
- R15 抢锁失败被 except Exception 捕获后写 crashed marker(跨进程
  污染);R16 会话获取失败只记录自己的拒绝事件,对正式 exposure/
  abort/traceback/manifest 零写入(§6.2);
- R15 终态写在锁释放之后;R16 终态在会话控制权有效时提交(§6.3);
- R15 derive261_seed 对正式 namespace 只查静态资格+终态封闭,
  running 窗口对任意进程开放;R16 受保护请求必须出示有效执行授权
  (§7.1)。

授权模型(§6.5/[S8]):flock 与 open file description 关联,fork/dup
可能共享同一锁,因此"拿到一个 fd"不构成授权。有效授权 = 出示
256-bit 随机 token 且 journal 重放确认:(a)该 token 被当前会话显式
委派;(b)会话未释放;(c)iteration 未 abort;(d)exposure 处于
running;(e)grant 未撤销;(f)namespace 属于授予范围。token 仅存
在于持有者内存或显式传递的环境变量,不写入任何磁盘文件(磁盘只存
token 的 sha256)。

信号策略(§6.4):KeyboardInterrupt/SystemExit 由会话拥有者的异常
处置路径处理;不可捕获 kill 不伪造"当时已写入 crashed",后续只能
依据留下的 journal 作事后失败封口(post-hoc orphan closure)。终态
已提交后,smoke/full-cold/日志失败可以使 iteration FAIL,但不覆写
已完成的资格终态。

信任边界(§4.3):本模块针对已冻结受信任代码中的误调用、并发、异常
和状态漂移,不是抵抗 root 或同权限恶意进程的安全沙箱。正式状态限
定单机 WSL/Linux 本地文件系统。
"""

from __future__ import annotations

import errno
import hashlib
import json
import os
import secrets
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

#: iteration 标识。
CURRICULUM261_ITERATION_ID_R16 = "r16"

#: 状态根目录环境变量(冻结部署身份解析;§6.1 out_dir 不得重定义
#: "同一 iteration 是否运行过")。
R16_STATE_ROOT_ENV = "CURRICULUM261_R16_STATE_ROOT"

#: 受委派执行者 token 的唯一合法传递通道(§7.2:不得借复制 marker/
#: JSON/环境变量自行取得授权;本变量由会话拥有者显式设置)。
R16_EXECUTOR_TOKEN_ENV = "CURRICULUM261_R16_EXECUTOR_TOKEN"

#: 权威 journal 与投影文件名。
R16_JOURNAL_NAME = "r16_execution_journal.jsonl"
R16_EXPOSURE_MARKER_NAME = "qualification_exposure_r16.json"
R16_ABORTED_MARKER_NAME = "r16_iteration_aborted.json"
R16_SESSION_LOCK_NAME = "r16_session.lock"

#: R16 正式 seed namespace(白名单定义在 curriculum261_api.py;
#: 此处为授权范围判定使用)。
R16_FORMAL_QUALIFICATION_NAMESPACES = (
    "qualification_r16",
    "preprocess_fit_qualification_r16",
    "c2_independent_qualification_r16",
    "cue_semantic_qualification_r16",
)

#: exposure 终态(单向一次)。
R16_EXPOSURE_TERMINAL_STATUSES = ("completed", "failed", "crashed")

#: journal 事件类型(闭合清单;未知事件在 strict 重放中被拒绝)。
R16_JOURNAL_EVENTS = (
    "session_acquired",        # 会话取得所有权(锁内)
    "session_superseded",      # 孤儿会话被新会话接管(exposure 前)
    "session_rejected",        # 竞争请求被拒绝(只记录自身,零正式副作用)
    "session_released",        # 会话正常释放(迭代总结提交后)
    "design_data_started",     # §16.2 design episode 首次生成(不可撤销)
    "iteration_aborted",       # §16.2 iteration 终止
    "exposure_started",        # 不可逆 exposure(先于任何正式数据访问)
    "grant_issued",            # 生成授权发放(exposure 持久化之后)
    "executor_delegated",      # 受委派执行者登记
    "grant_revoked",           # 生成授权撤销(final core 结束后)
    "qualification_terminal",  # 资格终态提交(持权内)
    "orphan_closure",          # 孤儿 running 的事后失败封口(§6.5)
)


class R16JournalCorruption(RuntimeError):
    """权威 journal 损坏/截断/矛盾:一切授权 fail closed。"""


class R16AuthorizationError(RuntimeError):
    """受保护请求缺少有效执行授权(§7.1 强制行为表)。"""


class R16OwnershipError(RuntimeError):
    """会话所有权缺失或已失效(终态提交/状态变更被拒绝)。"""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _default_state_root() -> Path:
    return (Path(__file__).resolve().parents[2] / "artifacts"
            / "route_c_stage2_6_1_repair16")


def r16_state_root() -> Path:
    """正式状态根目录(冻结解析:环境变量或部署缺省,二者必居其一)。"""
    env_val = os.environ.get(R16_STATE_ROOT_ENV)
    return Path(env_val).resolve() if env_val else _default_state_root()


def r16_journal_path() -> Path:
    return r16_state_root() / R16_JOURNAL_NAME


def r16_exposure_marker_path() -> Path:
    return r16_state_root() / R16_EXPOSURE_MARKER_NAME


def r16_aborted_marker_path() -> Path:
    return r16_state_root() / R16_ABORTED_MARKER_NAME


# ------------------------------------------------- journal(权威状态源)
def _fsync_dir(directory: Path) -> None:
    fd = os.open(directory, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def journal_append(event: str, payload: dict[str, Any] | None = None,
                   *, durable: bool = True) -> int:
    """追加一条权威事件并返回其 seq。

    durable=True(默认,全部关键事件)执行 write→flush→fsync(file)→
    fsync(dir) 完整持久化协议(§8.2);一次 os.replace 不为多个
    artifact 提供共同事务,journal 因此只在单文件内追加。
    """
    if event not in R16_JOURNAL_EVENTS:
        raise RuntimeError(f"未知 journal 事件类型 {event!r}")
    path = r16_journal_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    entries = _journal_entries_lenient(path)
    seq = entries + 1
    record = {
        "seq": seq,
        "utc": _now_utc(),
        "event": event,
        "iteration": CURRICULUM261_ITERATION_ID_R16,
        "pid": os.getpid(),
    }
    if payload:
        record.update(payload)
    line = json.dumps(record, ensure_ascii=False, sort_keys=True)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(line + "\n")
        fh.flush()
        if durable:
            os.fsync(fh.fileno())
    if durable:
        _fsync_dir(path.parent)
    return seq


def _journal_entries_lenient(path: Path) -> int:
    """计数既有行(仅用于 seq 分配;损坏行保留原样)。"""
    if not path.is_file():
        return 0
    count = 0
    with open(path, "rb") as fh:
        for _raw in fh:
            if _raw.strip():
                count += 1
    return count


def journal_entries(*, strict: bool = True) -> list[dict[str, Any]]:
    """重放权威 journal。

    strict=True(授权判定路径):任何一行无法解析、seq 不连续或事件
    类型未知都 raise R16JournalCorruption——不得静默跳过解析失败的
    事件后认为"从未 exposure"(§8.2)。
    """
    path = r16_journal_path()
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    expected_seq = 1
    corrupt: list[str] = []
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            text = raw.decode("utf-8", errors="replace").strip()
            try:
                rec = json.loads(text)
            except json.JSONDecodeError:
                corrupt.append(text[:200])
                continue
            if (not isinstance(rec, dict)
                    or rec.get("seq") != expected_seq
                    or rec.get("event") not in R16_JOURNAL_EVENTS):
                corrupt.append(text[:200])
                continue
            out.append(rec)
            expected_seq += 1
    if corrupt and strict:
        raise R16JournalCorruption(
            f"权威 journal 损坏({len(corrupt)} 行不可解析/seq 断裂/"
            f"未知事件;fail closed):{r16_journal_path()}")
    return out


def _entry(record: dict[str, Any], **match: Any) -> bool:
    return all(record.get(k) == v for k, v in match.items())


# ------------------------------------------------- 只读状态查询
def exposure_state() -> dict[str, Any]:
    """从权威 journal 重放 exposure 状态(marker 只是投影)。

    返回 {exposed, status, plan_digest, terminal, source}。journal
    损坏时 raise R16JournalCorruption(授权路径必须 fail closed)。
    只读报告路径可用 strict=False 获得降级事实。
    """
    entries = journal_entries()
    started = [e for e in entries if e["event"] == "exposure_started"]
    if not started:
        return {"exposed": False, "status": None, "plan_digest": None,
                "terminal": False, "source": "journal"}
    first = started[0]
    plan_digest = first.get("plan_digest")
    status = "running"
    terminal = None
    for e in entries:
        if e["event"] == "qualification_terminal":
            status = e.get("status", "crashed")
            terminal = status
        elif e["event"] == "orphan_closure":
            status = e.get("status", "crashed")
            terminal = status
    return {"exposed": True, "status": status, "plan_digest": plan_digest,
            "terminal": terminal is not None
            and status in R16_EXPOSURE_TERMINAL_STATUSES,
            "source": "journal"}


def iteration_aborted(strict: bool = True) -> bool:
    entries = journal_entries(strict=strict)
    return any(e["event"] == "iteration_aborted" for e in entries)


def _active_session_record(
        entries: list[dict[str, Any]]) -> dict[str, Any] | None:
    """最后一个会话记录(acquired/superseded),若未 released 则 active。"""
    last: dict[str, Any] | None = None
    for e in entries:
        if e["event"] in ("session_acquired", "session_superseded"):
            last = e
        elif e["event"] == "session_released":
            last = None
    return last


def _project_exposure_marker(entries: list[dict[str, Any]]) -> None:
    """把 journal 事实投影为 marker 文件(§8.2 派生视图)。

    只在会话持有者进程内调用;投影失败不影响权威状态,但会话记录
    journal 一条 note(marker 不可用时以 journal 为准)。
    """
    state = exposure_state()
    path = r16_exposure_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "iteration": CURRICULUM261_ITERATION_ID_R16,
        "contract": "R16 exposure 投影(权威源=r16_execution_journal."
                    "jsonl;marker 损坏/缺失不影响 journal 判定;"
                    "不可删除/覆盖/恢复为未暴露)",
        "written_utc": _now_utc(),
    }
    if state["exposed"]:
        payload["status"] = state["status"]
        payload["plan_digest"] = state["plan_digest"]
        if state["terminal"]:
            payload["updated_utc"] = _now_utc()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                   encoding="utf-8")
    os.replace(tmp, path)


# ------------------------------------------------- 正式会话
class R16FormalSession:
    """iteration 级正式会话:唯一所有权持有者(§6)。

    生命周期:acquire(锁内重查)→ 可选 exposure_started →
    issue_grant → (委派执行者) → revoke_grant →
    qualification_terminal → release。

    acquire 失败(竞争/状态不允许)只写 session_rejected 自身事件,
    对 exposure/abort/traceback/manifest 零正式副作用(§6.2)。
    """

    def __init__(self, *, binding: dict[str, Any],
                 lock_fh: Any, token: str) -> None:
        self._binding = dict(binding)
        self._lock_fh = lock_fh
        self._token = token
        self._session_hash = _token_hash(token)
        self._released = False
        self._grant: R16GenerationGrant | None = None

    # -- 属性 ------------------------------------------------------
    @property
    def session_hash(self) -> str:
        return self._session_hash

    @property
    def binding(self) -> dict[str, Any]:
        return dict(self._binding)

    def owns(self) -> bool:
        """当前进程仍持有该会话(未释放且锁 fd 开着)。"""
        return (not self._released and self._lock_fh is not None)

    def _require_owned(self, what: str) -> None:
        if not self.owns():
            raise R16OwnershipError(
                f"{what} 要求当前进程持有有效会话所有权(已释放或锁 "
                "fd 失效);终态不得在控制权失效后提交(§6.3)")

    # -- 获取 ------------------------------------------------------
    @classmethod
    def acquire(cls, binding: dict[str, Any]) -> "R16FormalSession":
        """取得唯一正式会话(flock 非阻塞 + 锁内重查,§6.1/§6.3)。

        锁内重查(全部基于权威 journal):
        - iteration_aborted 或 exposure terminal → 拒绝(只能事后
          封口/只读,不得新会话);
        - exposure running 且无终态 → 拒绝(机会已消耗;孤儿场景走
          orphan closure,不接管重跑,§6.5);
        - 存在未释放的旧会话(锁却能拿到 ⇒ 其持有进程已消失):
          * 旧会话未 exposure 且未发授权 → 记 session_superseded
            后允许接管(正式数据从未被访问,机会未消耗);
          * 否则 → 拒绝(只能 orphan closure)。
        """
        import fcntl

        root = r16_state_root()
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / R16_SESSION_LOCK_NAME
        fh = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            cls._record_rejection(binding, "lock_held_by_active_owner",
                                  exc)
            raise R16OwnershipError(
                "另一个进程持有 R16 正式会话锁(竞争请求被拒绝;本"
                "请求对正式状态零写入)") from exc
        # -- 锁内重查 ------------------------------------------------
        try:
            entries = journal_entries()
            if any(e["event"] == "iteration_aborted" for e in entries):
                raise R16OwnershipError(
                    "iteration 已 aborted;journal 权威记录拒绝新会话")
            state = exposure_state()
            if state["exposed"]:
                if state["terminal"]:
                    raise R16OwnershipError(
                        "exposure 已处于终态 "
                        f"{state['status']!r};正式机会已消耗并封口")
                raise R16OwnershipError(
                    "exposure 处于 running 且无终态(孤儿 running);"
                    "按 §6.5 只允许显式 orphan closure 失败封口,"
                    "不接管重跑")
            orphan = _active_session_record(entries)
            if orphan is not None:
                granted = any(
                    e["event"] in ("grant_issued",
                                   "executor_delegated")
                    for e in entries)
                if granted:
                    raise R16OwnershipError(
                        "孤儿会话曾发放生成授权(可能已访问正式数据);"
                        "只能 orphan closure,不得接管")
                journal_append("session_superseded", {
                    "superseded_session": orphan.get("session"),
                    "reason": "lock_released_without_release_event;"
                              "no_exposure_no_grant",
                })
        except Exception:
            import fcntl as _f

            _f.flock(fh.fileno(), _f.LOCK_UN)
            fh.close()
            cls._record_rejection(binding, "in_lock_recheck_failed", None)
            raise
        token = secrets.token_hex(32)
        payload: dict[str, Any] = {
            "session": _token_hash(token),
            "binding": binding,
        }
        journal_append("session_acquired", payload)
        return cls(binding=binding, lock_fh=fh, token=token)

    @classmethod
    def _record_rejection(cls, binding: dict[str, Any], reason: str,
                          exc: BaseException | None) -> None:
        """竞争请求只记录自身拒绝(§6.2:零正式副作用)。

        写入失败(例如状态根目录不可写)不再上抛——拒绝记录是尽力
        而为的证据,不得因记录失败把拒绝请求变成崩溃路径。
        """
        try:
            journal_append("session_rejected", {
                "reason": reason,
                "binding_summary": {
                    k: binding.get(k) for k in sorted(binding)[:6]},
                "error": f"{type(exc).__name__}: {exc}" if exc else None,
            }, durable=False)
        except Exception:  # noqa: BLE001 —— 拒绝证据尽力而为
            pass

    # -- exposure(§8.1:不可逆事件先于正式数据访问) ----------------
    def record_exposure_started(self, plan_digest: str,
                                *, note: str = "") -> None:
        self._require_owned("exposure_started")
        state = exposure_state()
        if state["exposed"]:
            raise R16OwnershipError(
                f"exposure 已记录(status={state['status']!r});一次"
                "性资格已消耗,禁止二次 exposure")
        journal_append("exposure_started", {
            "session": self._session_hash,
            "plan_digest": plan_digest,
            "note": note,
        })
        _project_exposure_marker(journal_entries())

    # -- 生成授权(§7) ---------------------------------------------
    def issue_generation_grant(
            self, *, namespaces: tuple[str, ...] = (
                R16_FORMAL_QUALIFICATION_NAMESPACES),
            delegate_to_env: bool = True) -> "R16GenerationGrant":
        """exposure 持久化之后激活有限生成授权(§6.3 顺序)。

        命名空间范围固定为 R16 正式四件套;授权窗口 = 发放至撤销。
        """
        self._require_owned("issue_generation_grant")
        state = exposure_state()
        if not (state["exposed"] and state["status"] == "running"):
            raise R16AuthorizationError(
                "生成授权要求 exposure 已持久化且处于 running 窗口"
                f"(当前 exposed={state['exposed']},"
                f"status={state['status']!r};§7.1)")
        grant = R16GenerationGrant(
            token=secrets.token_hex(32),
            namespaces=tuple(namespaces),
            session_hash=self._session_hash)
        journal_append("grant_issued", {
            "session": self._session_hash,
            "grant": grant.grant_hash,
            "namespaces": list(grant.namespaces),
        })
        journal_append("executor_delegated", {
            "session": self._session_hash,
            "grant": grant.grant_hash,
            "executor_pid": os.getpid(),
            "channel": R16_EXECUTOR_TOKEN_ENV if delegate_to_env
            else "in_process",
        })
        if delegate_to_env:
            os.environ[R16_EXECUTOR_TOKEN_ENV] = grant._token
        self._grant = grant
        _activate_grant(grant)
        return grant

    def revoke_generation_grant(self) -> None:
        """final core 结束后撤销生成授权(§6.3:停止新请求后撤销)。"""
        grant = self._grant
        if grant is None:
            return
        journal_append("grant_revoked", {
            "session": self._session_hash,
            "grant": grant.grant_hash,
        })
        os.environ.pop(R16_EXECUTOR_TOKEN_ENV, None)
        _deactivate_grant()
        self._grant = None

    # -- 资格终态(§6.3:持权内提交) --------------------------------
    def commit_qualification_terminal(self, status: str,
                                      plan_digest: str,
                                      *, note: str = "") -> None:
        if status not in R16_EXPOSURE_TERMINAL_STATUSES:
            raise RuntimeError(f"非法资格终态 {status!r}")
        self._require_owned("commit_qualification_terminal")
        state = exposure_state()
        if not (state["exposed"] and state["status"] == "running"):
            raise R16OwnershipError(
                f"资格终态要求 exposure running(当前 status="
                f"{state['status']!r});不得凭空或二次提交终态")
        if state["plan_digest"] != plan_digest:
            raise R16OwnershipError(
                "终态 plan digest 与 exposure 记录不符"
                f"({plan_digest!r} vs {state['plan_digest']!r})")
        journal_append("qualification_terminal", {
            "session": self._session_hash,
            "status": status,
            "plan_digest": plan_digest,
            "note": note,
        })
        _project_exposure_marker(journal_entries())

    # -- iteration 事件 ---------------------------------------------
    def record_iteration_aborted(self, reason: str) -> None:
        """§16.2 iteration 终止(会话持有者;smoke/full-cold 失败等)。"""
        self._require_owned("record_iteration_aborted")
        journal_append("iteration_aborted", {"reason": reason[:2000]})
        self._project_aborted_marker(reason)

    def _project_aborted_marker(self, reason: str) -> None:
        path = r16_aborted_marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "iteration": CURRICULUM261_ITERATION_ID_R16,
            "reason": reason,
            "utc": _now_utc(),
            "source": "journal projection",
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)

    # -- 释放 ------------------------------------------------------
    def release(self, *, summary: str = "") -> None:
        """提交迭代总结并释放正式会话所有权(最后一步,§6.3)。"""
        import fcntl

        if self._released:
            return
        self._require_owned("release")
        if self._grant is not None:
            self.revoke_generation_grant()
        journal_append("session_released", {
            "session": self._session_hash,
            "summary": summary[:2000],
        })
        fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
        self._lock_fh.close()
        self._lock_fh = None
        self._released = True


# ------------------------------------------------- 生成授权
class R16GenerationGrant:
    """有限期、有限 namespace 范围的正式生成授权(§7.1)。

    token 仅存在于持有者内存;跨进程委派通过受控环境变量并由
    verify_executor_token 重放 journal 验证。
    """

    def __init__(self, *, token: str, namespaces: tuple[str, ...],
                 session_hash: str) -> None:
        self._token = token
        self.namespaces = tuple(namespaces)
        self.session_hash = session_hash
        self.grant_hash = _token_hash(token)

    @property
    def token(self) -> str:
        return self._token


#: 进程内活动授权(同进程 final core 直接使用;子进程走 env token)。
_ACTIVE_GRANT: R16GenerationGrant | None = None


def _activate_grant(grant: R16GenerationGrant) -> None:
    global _ACTIVE_GRANT
    _ACTIVE_GRANT = grant


def _deactivate_grant() -> None:
    global _ACTIVE_GRANT
    _ACTIVE_GRANT = None


def active_grant() -> R16GenerationGrant | None:
    return _ACTIVE_GRANT


def _session_mutex_alive() -> bool:
    """探测会话互斥锁是否仍被持有(共享锁探测)。

    以 LOCK_SH|LOCK_NB 试探:失败 ⇒ 排他锁仍在(会话 owner 或其
    fd 继承者存活);成功 ⇒ 互斥已消失(owner 已死且无继承者),
    立即释放。fork/dup 共享 open file description([S8]),因此委派
    执行者若显式继承了锁 fd,在途计算窗口内探测仍为"存活"——
    符合 §6.5"在途计算不撤销"。owner 消失且无人继承时,残留
    token 因互斥消失而被拒绝(孤儿封口的前置事实)。
    """
    import fcntl

    lock_path = r16_state_root() / R16_SESSION_LOCK_NAME
    if not lock_path.is_file():
        return False
    fh = open(lock_path, "r", encoding="utf-8")
    try:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_SH | fcntl.LOCK_NB)
        except OSError:
            return True
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        return False
    finally:
        fh.close()


def verify_executor_token(token: str, namespace: str) -> dict[str, Any]:
    """验证出示的执行者 token 并返回授权事实(§7.1 强制行为)。

    全部条件:journal 无损坏;token 的 sha256 匹配某次 grant_issued
    且未被 grant_revoked/session_released/iteration_aborted 撤销;
    会话互斥锁仍被持有(owner 消失后的残留 token 失效);exposure
    处于 running;namespace 属于该授权范围。
    """
    if not token:
        raise R16AuthorizationError("缺少执行者 token(空凭证)")
    entries = journal_entries()  # strict:损坏即 R16JournalCorruption
    token_hash = _token_hash(token)
    grant_event = None
    delegated = False
    for e in entries:
        if e["event"] == "grant_issued" and e.get("grant") == token_hash:
            grant_event = e
            delegated = False
        elif (e["event"] == "executor_delegated"
                and e.get("grant") == token_hash):
            delegated = True
        elif e["event"] == "grant_revoked" and e.get("grant") == token_hash:
            raise R16AuthorizationError(
                "该生成授权已被撤销(final core 结束后)")
        elif e["event"] == "session_released":
            grant_event = None
            delegated = False
        elif e["event"] == "iteration_aborted":
            raise R16AuthorizationError("iteration 已 aborted")
    if grant_event is None or not delegated:
        raise R16AuthorizationError(
            "出示的 token 不对应任何有效委派(未被委派/会话已释放)")
    if not _session_mutex_alive():
        raise R16AuthorizationError(
            "会话互斥已消失(owner 进程消失且无锁继承者);残留 "
            "token 失效,不再受理新的受保护请求(§6.5)")
    if namespace not in grant_event.get("namespaces", ()):
        raise R16AuthorizationError(
            f"namespace {namespace!r} 不在授予范围 "
            f"{grant_event.get('namespaces')!r} 内")
    state = exposure_state()
    if not (state["exposed"] and state["status"] == "running"):
        raise R16AuthorizationError(
            "exposure 不在 running 窗口"
            f"(exposed={state['exposed']},status={state['status']!r})")
    return {"grant": token_hash, "namespace": namespace,
            "session": grant_event.get("session")}


def require_r16_generation_authorization(namespace: str) -> dict[str, Any]:
    """derive261_seed 对 R16 正式 namespace 的唯一守卫入口。

    进程内活动 grant 优先(同进程 final core);否则读受控环境变量
    (受委派子进程)。两者都要求通过 journal 重放验证。
    """
    if namespace not in R16_FORMAL_QUALIFICATION_NAMESPACES:
        raise R16AuthorizationError(
            f"namespace {namespace!r} 不是 R16 正式 namespace;"
            f"守卫仅覆盖 {R16_FORMAL_QUALIFICATION_NAMESPACES!r}")
    grant = _ACTIVE_GRANT
    if grant is not None:
        if namespace not in grant.namespaces:
            raise R16AuthorizationError(
                f"namespace {namespace!r} 不在活动授权范围内")
        return verify_executor_token(grant._token, namespace)
    env_token = os.environ.get(R16_EXECUTOR_TOKEN_ENV)
    if env_token:
        return verify_executor_token(env_token, namespace)
    raise R16AuthorizationError(
        f"对正式 namespace {namespace!r} 的 seed 派生缺少有效执行授权"
        "(无进程内活动 grant,亦无受委派执行者 token;静态资格不构"
        "成动态执行权,§7.1)")


# ------------------------------------------------- 孤儿封口(§6.5/§8.5)
def record_iteration_aborted_standalone(reason: str) -> None:
    """失败封口路径的 iteration 终止(不要求会话所有权;§6.4)。

    使用场景:workflow 步骤失败后由已冻结 fail-closure 命令调用
    (此时无活动会话——qualify 已正确封口释放,或从未创建)。
    取锁成功(无活动会话)才允许追加 iteration_aborted;锁被持有
    说明存在活动会话,拒绝以 abort 干扰正在运行的正式执行。
    """
    import fcntl

    root = r16_state_root()
    lock_path = root / R16_SESSION_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise R16OwnershipError(
            "存在活动 R16 正式会话;iteration aborted 封口被拒绝"
            "(不得干扰正在运行的正式执行)") from exc
    try:
        if iteration_aborted(strict=False):
            return  # 幂等:已终止
        journal_append("iteration_aborted", {"reason": reason[:2000]})
        path = r16_aborted_marker_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "iteration": CURRICULUM261_ITERATION_ID_R16,
            "reason": reason,
            "utc": _now_utc(),
            "source": "journal projection",
        }
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                       encoding="utf-8")
        os.replace(tmp, path)
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def orphan_running_closure(*, note: str) -> dict[str, Any]:
    """显式受限的事后失败封口(与只读 reader 分开,§8.5)。

    前提(全部验证):journal 无损坏;exposure running 无终态;会话
    锁可获取(无仍有效的会话);不存在未撤销的 grant/委派。只追加
    orphan_closure 终态事件 + 投影,不修原文件、不继续正式链、不重
    新授予数据权限。
    """
    import fcntl

    root = r16_state_root()
    lock_path = root / R16_SESSION_LOCK_NAME
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(lock_path, "a+", encoding="utf-8")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        fh.close()
        raise R16OwnershipError(
            "会话锁仍被持有(可能存在仍有效的会话或受委派执行者);"
            "无法确认孤儿状态,拒绝恢复/封口(§6.5)") from exc
    try:
        entries = journal_entries()
        if any(e["event"] == "iteration_aborted" for e in entries):
            raise R16OwnershipError("iteration 已 aborted;无需封口")
        state = exposure_state()
        if not (state["exposed"] and state["status"] == "running"):
            raise R16OwnershipError(
                f"exposure 状态 {state['status']!r} 不是孤儿 running")
        unrevoked_grants = [
            e.get("grant") for e in entries
            if e["event"] == "grant_issued"
            and not any(r["event"] == "grant_revoked"
                        and r.get("grant") == e.get("grant")
                        for r in entries)]
        # 锁可获取 ⇒ owner 已消失 ⇒ 互斥探测令全部残留 token 失效;
        # 未撤销的 grant 说明在途计算可能已发生,如实记录,不声称
        # "从未发生",也不授予新权限(§6.5)。
        journal_append("orphan_closure", {
            "status": "crashed",
            "plan_digest": state["plan_digest"],
            "unrevoked_grants": unrevoked_grants,
            "note": f"post-hoc orphan closure; {note[:1500]}",
        })
        _project_exposure_marker(journal_entries())
        return {"closure": "orphan_running", "status": "crashed",
                "unrevoked_grants": unrevoked_grants}
    finally:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        fh.close()


def bootstrap_failure_evidence(command: str, reason: str) -> dict[str, Any]:
    """workflow 之前的启动失败事实(§5.4)。

    不依赖 workflow 成功导入;描述:失败发生在 bootstrap;已执行
    workflow 前缀为空;首个未执行节点是 provenance-verify。
    """
    return {
        "failure_boundary": "bootstrap",
        "started_command": command,
        "reason": reason[:4000],
        "workflow_started": False,
        "executed_prefix": [],
        "first_unexecuted_node": "provenance-verify",
        "qualification_authorized": False,
        "exposure": exposure_state(),
    }
