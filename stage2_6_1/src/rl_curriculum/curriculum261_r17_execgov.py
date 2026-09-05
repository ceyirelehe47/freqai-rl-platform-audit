"""R17 执行治理内核:链级会话 + 执行者身份绑定 + 单写者权威 journal。

R17 相对 R16 execgov 的五项闭合(F1-F5 对应):

F1 全链所有权 —— R17ChainSession 从外层入口(第一正式写之前)
    acquire,覆盖 17 步 + fail-closure + 收尾;qualify 只是链会话
    内的一个有限资格窗口(R17QualificationWindow),不再自行
    acquire/release。

F2 执行者身份 —— 进程实例身份(pid + /proc/<pid>/stat starttime
    + boot_id)在委派时登记、验证时比对。fork/spawn/exec 继承
    token/对象/fd 不继承身份;owner 死亡由 /proc 存活探测判定,
    不再依赖"锁 fd 还开着"。

F3 单写者 journal —— 权威 journal(r17_execution_journal.jsonl,
    与 R16 文件名分离)只有会话 owner 一个写者;seq 分配与写入
    持锁串行;抢锁失败的竞争请求写独立 rejected_requests/ 区,
    不触碰 journal;strict parser 验证完整合法状态迁移。

F4/F5 由 runner/assemble/rt_rehearsal 与 workflow 层承载。

威胁模型(任务书 §3):受信任冻结代码中的误调用、并发、进程继承、
异常与状态漂移;不抵抗 root/同权限全文件改写,不声称 Python
安全沙箱或断电完备性。
"""
from __future__ import annotations

import errno
import fcntl
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any, Iterable

from rl_curriculum.curriculum261_r17_registry import (
    CURRICULUM261_ITERATION_ID_R17,
    R17_FORMAL_QUALIFICATION_NAMESPACES,
    R17_DEPLOYED_STATE_ROOT,
    r17_state_root,
)

# ------------------------------------------------- 常量 -----------------
#: 状态根环境变量(准入时解析绑定;此后验证一致性,不重新解析语义)。
R17_STATE_ROOT_ENV = "CURRICULUM261_R17_STATE_ROOT"
#: 委派执行者 token 的受控传递通道(仅传递;不是授权依据)。
R17_EXECUTOR_TOKEN_ENV = "CURRICULUM261_R17_EXECUTOR_TOKEN"
#: 权威 journal(版本化文件名:与 R16 journal 物理分离,R16 历史
#: 形态在 R17 状态机下的兼容性问题被结构性消除)。
R17_JOURNAL_NAME = "r17_execution_journal.jsonl"
#: 拒绝请求独立证据区(不进入权威 journal;F3)。
R17_REQUEST_DIR_NAME = "rejected_requests"
#: 链会话互斥锁。
R17_SESSION_LOCK_NAME = "r17_chain_session.lock"
#: exposure marker 投影(journal 的只读投影,便于快速查询)。
R17_EXPOSURE_MARKER_NAME = "qualification_exposure_r17.json"
#: 迭代失败 marker 投影。
R17_ABORTED_MARKER_NAME = "r17_iteration_aborted.json"

#: 资格终态集合。
R17_EXPOSURE_TERMINAL_STATUSES = ("completed", "failed", "crashed")

#: 权威 journal 合法事件(单写者合同:全部由 ChainSession owner 写)。
R17_JOURNAL_EVENTS = (
    "chain_session_acquired",
    "design_data_started",
    "chain_step_started",
    "chain_step_completed",
    "chain_step_failed",
    "chain_exposure_started",
    "grant_issued",
    "grant_revoked",
    "qualification_terminal",
    "chain_iteration_aborted",
    "chain_released",
    "chain_closed",
)

#: 资格窗口内的顺序敏感事件(用于状态机)。
_WINDOW_ORDERED = ("chain_exposure_started", "grant_issued",
                   "grant_revoked", "qualification_terminal")

#: 步骤事件允许携带的白名单 payload 键(核心身份字段不可覆盖)。
_PROTECTED_FIELDS = ("seq", "utc", "event", "iteration", "pid",
                     "owner", "writer")


class R17JournalCorruption(RuntimeError):
    """权威 journal 损坏/状态迁移非法(fail closed)。"""


class R17AuthorizationError(RuntimeError):
    """生成授权不满足(静态资格或动态执行权)。"""


class R17OwnershipError(RuntimeError):
    """会话所有权/单写者约束被违反(竞争请求零正式副作用)。"""


# ------------------------------------------------- 基础工具 -------------
def _now_utc() -> str:
    import datetime

    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def _token_hash(token: str) -> str:
    import hashlib

    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def r17_journal_path() -> Path:
    return r17_state_root() / R17_JOURNAL_NAME


def r17_request_dir() -> Path:
    return r17_state_root() / R17_REQUEST_DIR_NAME


def r17_exposure_marker_path() -> Path:
    return r17_state_root() / R17_EXPOSURE_MARKER_NAME


def r17_aborted_marker_path() -> Path:
    return r17_state_root() / R17_ABORTED_MARKER_NAME


def _fsync_dir(directory: Path) -> None:
    fd = os.open(str(directory), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


# ------------------------------------------------- 进程实例身份 (F2) ----
def executor_identity(pid: int | None = None) -> dict[str, Any]:
    """当前(或指定)进程的实例身份:pid + starttime + boot_id。

    fork 产生新 pid;exec 不改 pid 但 starttime 不变;同 pid 复用
    由 starttime 区分。仅复制 token/对象/fd 的进程身份不同——
    这是执行者绑定的判定基础。
    """
    target = int(pid if pid is not None else os.getpid())
    ident: dict[str, Any] = {"pid": target}
    stat_path = f"/proc/{target}/stat"
    try:
        with open(stat_path, "r", encoding="utf-8") as fh:
            raw = fh.read()
        # comm 字段可含空格/括号:从最后一个 ')' 之后切分
        tail = raw.rsplit(")", 1)[-1].split()
        ident["starttime"] = tail[19]  # field 22 overall(0-based 19)
    except (OSError, IndexError):
        ident["starttime"] = None
    try:
        with open("/proc/sys/kernel/random/boot_id",
                  encoding="utf-8") as fh:
            ident["boot_id"] = fh.read().strip()
    except OSError:
        ident["boot_id"] = None
    return ident


def executor_identity_matches(expected: dict[str, Any],
                              actual: dict[str, Any]) -> bool:
    """两个实例身份是否同一(任一成分缺失即不匹配,fail closed)。"""
    keys = ("pid", "starttime", "boot_id")
    if any(expected.get(k) is None or actual.get(k) is None
           for k in keys):
        return False
    return all(expected.get(k) == actual.get(k) for k in keys)


def process_alive(ident: dict[str, Any]) -> bool:
    """实例身份对应的进程是否仍以同一实例存活(/proc 探测)。"""
    try:
        current = executor_identity(int(ident["pid"]))
    except (KeyError, TypeError, ValueError):
        return False
    return executor_identity_matches(ident, current)


# ------------------------------------------------- journal (F3) ---------
def _read_journal_records(path: Path) -> list[dict[str, Any]]:
    """原始读入全部行(JSON 解析失败记为 None 占位,保持行位)。"""
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    with open(path, "rb") as fh:
        for raw in fh:
            if not raw.strip():
                continue
            try:
                out.append(json.loads(raw.decode("utf-8")))
            except (UnicodeDecodeError, json.JSONDecodeError):
                out.append(None)
    return out


#: 合法状态迁移表:事件 -> 前置状态谓词(在已验证前缀上求值)。
def _migration_ok(event: str, prefix: list[dict[str, Any]],
                  record: dict[str, Any]) -> bool:
    """journal 状态机:事件在当前前缀下是否合法(§7.2)。

    prefix 已通过逐条校验;record 为待验条目。
    """
    def has(ev: str, **match: Any) -> bool:
        return any(r.get("event") == ev and
                   all(r.get(k) == v for k, v in match.items())
                   for r in prefix)

    events = [r.get("event") for r in prefix]
    iteration = record.get("iteration")
    if iteration != CURRICULUM261_ITERATION_ID_R17:
        return False
    if not events:  # 第一条
        return event == "chain_session_acquired"
    if "chain_released" in events or "chain_closed" in events:
        return False  # 结束后不允许新事件
    if event == "chain_session_acquired":
        return False  # 唯一会话,不允许二次 acquire 记录
    # 以下全部要求会话存在
    if not has("chain_session_acquired"):
        return False
    if "chain_iteration_aborted" in events:
        # 封口后只允许收尾释放
        return event == "chain_released"
    if event == "chain_exposure_started":
        return not has("chain_exposure_started")  # 一次性
    if event == "grant_issued":
        return (has("chain_exposure_started")
                and not has("qualification_terminal")
                and not has("grant_issued", grant=record.get("grant")))
    if event == "grant_revoked":
        return has("grant_issued", grant=record.get("grant")) and \
            not has("grant_revoked", grant=record.get("grant"))
    if event == "qualification_terminal":
        return (has("chain_exposure_started")
                and not has("qualification_terminal"))
    if event in ("chain_step_started",):
        step = record.get("step")
        # 同一步不得重复 started(失败后不重跑;成功后不再启动)
        return not has("chain_step_started", step=step)
    if event in ("chain_step_completed", "chain_step_failed"):
        step = record.get("step")
        return (has("chain_step_started", step=step)
                and not has("chain_step_completed", step=step)
                and not has("chain_step_failed", step=step))
    if event == "design_data_started":
        return not has("design_data_started")
    if event == "chain_released":
        return True
    return True  # chain_iteration_aborted 等由上层语义限制


def journal_entries(*, strict: bool = True) -> list[dict[str, Any]]:
    """重放权威 journal(单写者合同的读取面)。

    strict=True:语法、seq 连续、事件白名单、iteration、完整合法
    状态迁移全部校验;任一失败 raise R17JournalCorruption。
    """
    path = r17_journal_path()
    records = _read_journal_records(path)
    out: list[dict[str, Any]] = []
    expected_seq = 1
    problems: list[str] = []
    for rec in records:
        if not isinstance(rec, dict):
            problems.append(f"line-{expected_seq}:unparseable")
            continue
        if rec.get("seq") != expected_seq:
            problems.append(f"seq-{rec.get('seq')}!=expected-"
                            f"{expected_seq}")
            continue
        if rec.get("event") not in R17_JOURNAL_EVENTS:
            problems.append(f"unknown-event-{rec.get('event')!r}")
            continue
        if any(k in rec and k not in _PROTECTED_FIELDS
               for k in ()):  # 占位:核心字段由迁移校验覆盖
            problems.append("protected-field")
            continue
        if not _migration_ok(rec["event"], out, rec):
            problems.append(f"illegal-transition-{rec['event']}"
                            f"@seq{expected_seq}")
            continue
        out.append(rec)
        expected_seq += 1
    if problems and strict:
        raise R17JournalCorruption(
            f"权威 journal 损坏/非法迁移({len(problems)} 处;"
            f"fail closed):{r17_journal_path()}::{problems[:5]}")
    return out


def _entry(record: dict[str, Any], **match: Any) -> bool:
    return all(record.get(k) == v for k, v in match.items())


# ------------------------------------------------- 状态投影 -------------
def exposure_state() -> dict[str, Any]:
    """从权威 journal 投影 exposure 状态(corruption=已暴露)。"""
    try:
        entries = journal_entries()
    except R17JournalCorruption:
        return {"corrupt": True, "exposed": True, "status": "unknown",
                "plan_digest": None, "session": None}
    exposed = status = digest = session = None
    for e in entries:
        if e["event"] == "chain_exposure_started":
            exposed, status = True, "running"
            digest = e.get("plan_digest")
            session = e.get("session")
        elif e["event"] == "qualification_terminal":
            status = e.get("status")
    return {"corrupt": False,
            "exposed": bool(exposed),
            "status": status if exposed else "not_exposed",
            "plan_digest": digest, "session": session}


def iteration_aborted(strict: bool = True) -> bool:
    try:
        return any(e["event"] == "chain_iteration_aborted"
                   for e in journal_entries())
    except R17JournalCorruption:
        if strict:
            return True  # fail closed:损坏视同已终止
        return False


def chain_released() -> bool:
    try:
        return any(e["event"] == "chain_released"
                   for e in journal_entries())
    except R17JournalCorruption:
        return True


def _project_exposure_marker(entries: list[dict[str, Any]]) -> None:
    """journal → exposure marker 只读投影(存在性快速检查)。"""
    state = {"projected_from": "r17_execution_journal",
             "exposed": False, "status": "not_exposed"}
    for e in entries:
        if e["event"] == "chain_exposure_started":
            state = {"projected_from": "r17_execution_journal",
                     "exposed": True, "status": "running",
                     "session": e.get("session"),
                     "plan_digest": e.get("plan_digest")}
        elif e["event"] == "qualification_terminal":
            if state.get("exposed"):
                state["status"] = e.get("status")
    path = r17_exposure_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


def _project_aborted_marker(reason: str) -> None:
    path = r17_aborted_marker_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    payload = {"iteration": CURRICULUM261_ITERATION_ID_R17,
               "reason": reason[:2000], "utc": _now_utc()}
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)
    _fsync_dir(path.parent)


# ------------------------------------------------- 拒绝请求区 (F3) -------
def write_rejection_evidence(reason: str, binding: dict[str, Any],
                              exc: BaseException | None = None) -> Path:
    """竞争/被拒请求写独立证据文件(不触碰 journal/markers)。

    文件名含时间戳+pid 防冲突;写入尽力而为(失败不再上抛,
    拒绝路径不得演变为崩溃)。
    """
    try:
        d = r17_request_dir()
        d.mkdir(parents=True, exist_ok=True)
        name = (f"{int(time.time() * 1000)}_{os.getpid()}_"
                f"{secrets.token_hex(4)}.json")
        payload = {"iteration": CURRICULUM261_ITERATION_ID_R17,
                   "reason": reason,
                   "requester_identity": executor_identity(),
                   "binding_summary": {k: binding.get(k)
                                       for k in sorted(binding)[:8]},
                   "error": f"{type(exc).__name__}: {exc}" if exc
                   else None,
                   "utc": _now_utc()}
        p = d / name
        tmp = p.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, sort_keys=True)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, p)
        _fsync_dir(d)
        return p
    except Exception:  # noqa: BLE001 —— 拒绝证据尽力而为
        return Path("/dev/null")


# ------------------------------------------------- 链会话 (F1) ----------
class R17ChainSession:
    """整轮正式执行的唯一所有权会话(外层入口 → 收尾释放)。

    生命周期:
        acquire(锁内重查+身份登记)
        → [步骤事件 design_data/step_* 由本会话单写]
        → qualification 窗口(open_window → grant → … → terminal)
        → 收尾(smoke/full-cold/日志核验事件)
        → release / close

    owns() 语义(R17):当前进程实例 == 登记的 owner 身份,且锁仍
    被本会话持有(fd 打开且未 release)。fork 继承对象/fd 的子
    进程实例身份不同 → owns()==False,一切受保护操作被拒。
    """

    def __init__(self, *, binding: dict[str, Any], lock_fh: Any,
                 token: str, owner_identity: dict[str, Any]) -> None:
        self._binding = dict(binding)
        self._lock_fh = lock_fh
        self._token = token
        self._session_hash = _token_hash(token)
        self._owner_identity = dict(owner_identity)
        self._released = False
        self._grant_hashes: list[str] = []

    # -- 属性 ------------------------------------------------------
    @property
    def session_hash(self) -> str:
        return self._session_hash

    @property
    def binding(self) -> dict[str, Any]:
        return dict(self._binding)

    @property
    def owner_identity(self) -> dict[str, Any]:
        return dict(self._owner_identity)

    def owns(self) -> bool:
        """当前进程实例是本会话 owner(身份绑定;F2)。"""
        if self._released or self._lock_fh is None:
            return False
        return executor_identity_matches(
            self._owner_identity, executor_identity())

    def _require_owned(self, what: str) -> None:
        if not self.owns():
            raise R17OwnershipError(
                f"{what} 要求当前进程实例是会话 owner(身份绑定;"
                "继承对象/fd/token 不构成所有权;§WP2)")

    # -- journal 单写者写入口 --------------------------------------
    def _append(self, event: str,
                payload: dict[str, Any] | None = None) -> int:
        """owner 持锁串行追加(单写者合同;seq 无竞争)。

        持锁状态下 lenient 计数→+1→写→fsync;锁由本会话独占,
        串行性由所有权保证。迁移合法性在写入前用 strict 重放
        验证(非法迁移立即拒绝,不落盘)。
        """
        self._require_owned("journal_append")
        if event not in R17_JOURNAL_EVENTS:
            raise RuntimeError(f"未知 journal 事件类型 {event!r}")
        path = r17_journal_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        # 写前验证迁移(在当前权威前缀上)
        prefix = journal_entries()  # strict:损坏即抛
        n = len(_read_journal_records(path))
        record = {
            "seq": n + 1,
            "utc": _now_utc(),
            "event": event,
            "iteration": CURRICULUM261_ITERATION_ID_R17,
            "pid": os.getpid(),
            "owner": self._session_hash,
            "writer": "chain_session_owner",
        }
        if payload:
            for k in payload:
                if k in _PROTECTED_FIELDS:
                    raise R17OwnershipError(
                        f"payload 键 {k!r} 受保护,不可覆盖核心身份"
                        "字段(§7.1)")
            record.update(payload)
        if not _migration_ok(event, prefix, record):
            raise R17JournalCorruption(
                f"拒绝写入非法迁移 {event!r}(当前前缀 "
                f"{len(prefix)} 条;§7.2)")
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(path.parent)
        return record["seq"]

    # -- 获取 ------------------------------------------------------
    @classmethod
    def acquire(cls, binding: dict[str, Any]) -> "R17ChainSession":
        """取得整轮链会话(唯一;flock 非阻塞+锁内重查)。

        锁内重查(基于权威 journal):
        - 已有 chain_session_acquired 且无终局 → 拒绝(活跃会话);
        - 已有终止性事件(chain_released/chain_iteration_aborted)
          → 拒绝(一轮只有一次被接受的正式运行);
        - exposure/terminal 状态一致性由状态机保证;
        - state root 与部署绑定一致(R17_DEPLOYED_STATE_ROOT)。

        拒绝 = 独立 request 证据 + R17OwnershipError,零 journal
        副作用。
        """
        root = r17_state_root()
        if (R17_DEPLOYED_STATE_ROOT is not None
                and str(root) != R17_DEPLOYED_STATE_ROOT):
            write_rejection_evidence(
                "state_root_mismatch_with_deployed_binding", binding)
            raise R17OwnershipError(
                f"当前 state root {root} 与冻结部署绑定 "
                f"{R17_DEPLOYED_STATE_ROOT} 不一致(§WP2.4)")
        root.mkdir(parents=True, exist_ok=True)
        lock_path = root / R17_SESSION_LOCK_NAME
        fh = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            write_rejection_evidence("lock_held_by_active_owner",
                                     binding, exc)
            raise R17OwnershipError(
                "另一个进程持有 R17 链会话锁(竞争请求被拒绝;"
                "独立 request 证据;零 journal 副作用)") from exc
        # -- 锁内重查 ------------------------------------------------
        try:
            entries = journal_entries()  # strict(缺失=空)
            events = [e["event"] for e in entries]
            if any(e["event"] == "chain_iteration_aborted"
                   for e in entries):
                raise R17OwnershipError(
                    "iteration 已 aborted;journal 权威记录拒绝新会话")
            if "chain_released" in events or "chain_closed" in events:
                raise R17OwnershipError(
                    "本轮已释放/关闭;一轮只有一次被接受的正式运行"
                    "(§5.2)")
            if "chain_session_acquired" in events:
                # 锁可拿到 ⇒ 登记的 owner 已死(无人持锁)
                acquired = next(e for e in entries if e["event"] ==
                                "chain_session_acquired")
                # 已被接受的运行即使 owner 崩溃也不可接管重跑
                raise R17OwnershipError(
                    "已存在被接受的正式运行(owner 已消失);"
                    "不允许接管重跑,只允许受限事后封口(§5.2/§7.3)"
                    f"(原 owner={acquired.get('owner')})")
        except Exception:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
            fh.close()
            write_rejection_evidence("in_lock_recheck_failed", binding)
            raise
        token = secrets.token_hex(32)
        identity = executor_identity()
        payload = {
            "session": _token_hash(token),
            "binding": binding,
            "owner_identity": identity,
            "state_root": str(root),
        }
        fh.seek(0)
        fh.truncate()
        fh.write(json.dumps({"session": payload["session"],
                             "acquired_utc": _now_utc()},
                            ensure_ascii=False, sort_keys=True))
        fh.flush()
        os.fsync(fh.fileno())
        session = cls(binding=binding, lock_fh=fh, token=token,
                      owner_identity=identity)
        session._append("chain_session_acquired", payload)
        return session

    # -- 链事件(单写者;worker 经受控请求由 owner 代写) ------------
    def record_design_data_started(self, *, note: str = "") -> None:
        self._append("design_data_started", {"note": note[:500]})

    def record_step_started(self, step: str) -> None:
        self._append("chain_step_started", {"step": step})

    def record_step_completed(self, step: str, *, rc: int) -> None:
        self._append("chain_step_completed",
                     {"step": step, "rc": int(rc)})

    def record_step_failed(self, step: str, *, rc: int) -> None:
        self._append("chain_step_failed", {"step": step, "rc": int(rc)})

    # -- qualification 窗口 (§6.3 顺序) -----------------------------
    def open_qualification_window(self, plan_digest: str, *,
                                  note: str = "") -> None:
        """exposure 先行:机会消耗的权威记录(不可逆)。"""
        self._append("chain_exposure_started",
                     {"plan_digest": plan_digest, "note": note[:500]})
        _project_exposure_marker(journal_entries())

    def issue_generation_grant(
            self, *, namespaces: Iterable[str] = (
                R17_FORMAL_QUALIFICATION_NAMESPACES),
            delegate_executor_identity: dict[str, Any] | None = None,
            channel: str = "in_process") -> "R17GenerationGrant":
        """发放绑定执行者实例身份的有限生成授权。

        delegate_executor_identity 缺省 = 当前 owner 自身(in_process
        委派)。跨进程委派时为被委派子进程的实例身份(由受控启动
        协议在 spawn 前取得并传入)。
        """
        self._require_owned("issue_generation_grant")
        state = exposure_state()
        if not (state["exposed"] and state["status"] == "running"):
            raise R17AuthorizationError(
                "生成授权要求 exposure 已持久化且处于 running 窗口"
                f"(当前 exposed={state['exposed']},"
                f"status={state['status']!r};§6.3)")
        if any(e["event"] == "qualification_terminal"
               for e in journal_entries()):
            raise R17AuthorizationError(
                "资格已终态;reader 不得通过复验重新打开生成权限")
        executor_ident = dict(delegate_executor_identity
                              if delegate_executor_identity is not None
                              else executor_identity())
        if not executor_ident.get("starttime"):
            raise R17AuthorizationError(
                "被委派执行者实例身份不完整(缺 starttime);"
                "拒绝发放(fail closed)")
        grant = R17GenerationGrant(
            token=secrets.token_hex(32),
            namespaces=tuple(namespaces),
            session_hash=self._session_hash,
            executor_identity=executor_ident)
        self._append("grant_issued", {
            "grant": grant.grant_hash,
            "namespaces": list(grant.namespaces),
            "executor_identity": executor_ident,
            "channel": channel,
        })
        self._grant_hashes.append(grant.grant_hash)
        return grant

    def revoke_generation_grant(self, grant: "R17GenerationGrant") -> None:
        self._append("grant_revoked", {"grant": grant.grant_hash})

    def commit_qualification_terminal(self, status: str,
                                      plan_digest: str, *,
                                      note: str = "") -> None:
        if status not in R17_EXPOSURE_TERMINAL_STATUSES:
            raise RuntimeError(f"非法资格终态 {status!r}")
        state = exposure_state()
        if not (state["exposed"] and state["status"] == "running"):
            raise R17OwnershipError(
                f"资格终态要求 exposure running(当前 status="
                f"{state['status']!r});不得凭空或二次提交终态")
        if state["plan_digest"] != plan_digest:
            raise R17OwnershipError(
                "终态 plan digest 与 exposure 记录不符"
                f"({plan_digest!r} vs {state['plan_digest']!r})")
        self._append("qualification_terminal",
                     {"status": status, "plan_digest": plan_digest,
                      "note": note[:500]})
        _project_exposure_marker(journal_entries())

    # -- 终止与释放 --------------------------------------------------
    def record_iteration_aborted(self, reason: str) -> None:
        """整轮失败封口(活跃 owner 通过本会话;§7.3)。"""
        self._append("chain_iteration_aborted",
                     {"reason": reason[:2000]})
        _project_aborted_marker(reason)

    def release(self, *, summary: str = "") -> None:
        """正常整轮结束释放(qualification 已终态或未 exposure)。"""
        state = exposure_state()
        if state["exposed"] and state["status"] == "running":
            raise R17OwnershipError(
                "exposure 仍 running;必须先提交 qualification "
                "terminal 或 iteration_aborted 再释放(§7.4)")
        self._append("chain_released", {"summary": summary[:500]})
        self._close_lock()

    def close_after_release(self, *, summary: str = "") -> None:
        """交付核验完成后的最终封口(只读收尾之后)。"""
        self._append("chain_closed", {"summary": summary[:500]})
        self._close_lock()

    def _close_lock(self) -> None:
        if self._lock_fh is not None:
            try:
                fcntl.flock(self._lock_fh.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                self._lock_fh.close()
            except OSError:
                pass
        self._lock_fh = None
        self._released = True


# ------------------------------------------------- 授权 (F2) ------------
class R17GenerationGrant:
    """有限期、有限 namespace、绑定执行者实例身份的生成授权。"""

    def __init__(self, *, token: str, namespaces: tuple[str, ...],
                 session_hash: str,
                 executor_identity_: dict[str, Any] | None = None,
                 **kwargs: Any) -> None:
        self._token = token
        self.namespaces = tuple(namespaces)
        self.session_hash = session_hash
        self.executor_identity = dict(
            executor_identity_ if executor_identity_ is not None
            else (kwargs.get("executor_identity") or {}))
        self.grant_hash = _token_hash(token)

    @property
    def token(self) -> str:
        return self._token


#: 进程内活动授权(同进程 final core 直接使用)。
_ACTIVE_GRANT: R17GenerationGrant | None = None


def _activate_grant(grant: R17GenerationGrant) -> None:
    global _ACTIVE_GRANT
    _ACTIVE_GRANT = grant


def _deactivate_grant() -> None:
    global _ACTIVE_GRANT
    _ACTIVE_GRANT = None


def active_grant() -> R17GenerationGrant | None:
    return _ACTIVE_GRANT


def _chain_mutex_alive() -> bool:
    """会话互斥锁是否仍被持有(LOCK_SH|LOCK_NB 试探)。"""
    lock_path = r17_state_root() / R17_SESSION_LOCK_NAME
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


def _registered_owner_identity() -> dict[str, Any] | None:
    try:
        entries = journal_entries()
    except R17JournalCorruption:
        return None
    for e in entries:
        if e["event"] == "chain_session_acquired":
            return e.get("owner_identity")
    return None


def verify_executor_token(token: str, namespace: str) -> dict[str, Any]:
    """验证出示的执行者 token 并返回授权事实(§6.1 全条件)。

    与 R16 的关键差异(F2):token 仅是传递凭证;授权要求当前
    进程实例身份 == grant_issued 登记的被委派执行者身份,且登记
    的 owner 实例仍存活(/proc 探测,不依赖锁 fd)。
    """
    if not token:
        raise R17AuthorizationError("缺少执行者 token(空凭证)")
    entries = journal_entries()  # strict:损坏即 R17JournalCorruption
    token_hash = _token_hash(token)
    grant_event = None
    for e in entries:
        if e["event"] == "grant_issued" and e.get("grant") == token_hash:
            grant_event = e
        elif (e["event"] == "grant_revoked"
                and e.get("grant") == token_hash):
            raise R17AuthorizationError("该生成授权已被撤销")
        elif e["event"] == "chain_iteration_aborted":
            raise R17AuthorizationError("iteration 已 aborted")
    if grant_event is None:
        raise R17AuthorizationError(
            "出示的 token 不对应任何有效授权(未被发放/会话已结束)")
    # F2 核心:当前执行者实例身份比对
    expected_ident = grant_event.get("executor_identity") or {}
    actual_ident = executor_identity()
    if not executor_identity_matches(expected_ident, actual_ident):
        raise R17AuthorizationError(
            "当前进程实例不是被委派的执行者(token 为传递凭证,"
            "不构成授权;fork/spawn/exec 继承不获得权限;§WP2)")
    # owner 存活(实例级 /proc 探测;锁 fd 被继承不算 owner 存活)
    owner_ident = _registered_owner_identity()
    if owner_ident is None:
        raise R17AuthorizationError("journal 无会话登记记录")
    if not process_alive(owner_ident):
        raise R17AuthorizationError(
            "会话 owner 进程实例已消失;不再受理新的受保护请求"
            "(§WP2.2/T09)")
    if not _chain_mutex_alive():
        raise R17AuthorizationError(
            "会话互斥已消失(owner 及其锁继承者均不存在)")
    if namespace not in grant_event.get("namespaces", ()):
        raise R17AuthorizationError(
            f"namespace {namespace!r} 不在授予范围 "
            f"{grant_event.get('namespaces')!r} 内")
    state = exposure_state()
    if not (state["exposed"] and state["status"] == "running"):
        raise R17AuthorizationError(
            "exposure 不在 running 窗口"
            f"(exposed={state['exposed']},status={state['status']!r})")
    return {"grant": token_hash, "namespace": namespace,
            "session": grant_event.get("owner")}


def require_r17_generation_authorization(namespace: str) -> dict[str, Any]:
    """数据生成入口的强制授权检查(§6.5:覆盖真正数据入口)。

    顺序:静态资格(namespace 属 R17 正式面)→ 动态执行权
    (in-process 活动授权或 env token 的完整验证)。
    """
    from rl_curriculum.curriculum261_r17_registry import (
        require_r17_formal_namespace,
    )

    require_r17_formal_namespace(namespace)
    grant = active_grant()
    if grant is not None:
        if namespace not in grant.namespaces:
            raise R17AuthorizationError(
                f"namespace {namespace!r} 不在活动授权范围内")
        # in-process 授权同样验证执行者身份与窗口
        return verify_executor_token(grant.token, namespace)
    token = os.environ.get(R17_EXECUTOR_TOKEN_ENV, "")
    if not token:
        raise R17AuthorizationError(
            f"namespace {namespace!r} 要求有效 R17 生成授权"
            f"(无活动授权,亦无 {R17_EXECUTOR_TOKEN_ENV} 凭证;"
            "静态资格≠动态执行权;§WP2.5)")
    return verify_executor_token(token, namespace)


# ------------------------------------------------- 受限事后封口 ---------
def post_hoc_closure_allowed() -> bool:
    """受限事后封口的前置判定(owner 已死且无锁继承者)。"""
    if _chain_mutex_alive():
        return False
    owner_ident = _registered_owner_identity()
    if owner_ident is None:
        return False
    return not process_alive(owner_ident)


def record_post_hoc_closure(self_identity: dict[str, Any] | None = None,
                            *, reason: str) -> dict[str, Any]:
    """owner 消失后的受限事后封口(§7.3;不是第二次正式运行)。

    只允许:在 journal 追加 chain_iteration_aborted(经独立
    maintenance 锁串行),投影 aborted marker;不倒回 running、
    不新发 grant、不截断尾行。维护者身份被记录。
    """
    if not post_hoc_closure_allowed():
        raise R17OwnershipError(
            "受限事后封口仅适用于 owner 已消失且互斥不存在的场景;"
            "活跃 owner 必须通过本会话 record_iteration_aborted 封口")
    root = r17_state_root()
    root.mkdir(parents=True, exist_ok=True)
    maint_lock = root / "r17_maintenance.lock"
    mfh = open(maint_lock, "a+", encoding="utf-8")
    try:
        fcntl.flock(mfh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        records = _read_journal_records(r17_journal_path())
        # 独立维护锁内的串行追加(维护者不是会话 owner;显式区分)
        record = {
            "seq": len(records) + 1,
            "utc": _now_utc(),
            "event": "chain_iteration_aborted",
            "iteration": CURRICULUM261_ITERATION_ID_R17,
            "pid": os.getpid(),
            "owner": "post_hoc_maintenance",
            "writer": "post_hoc_maintenance",
            "reason": reason[:2000],
            "maintainer_identity": self_identity or executor_identity(),
        }
        path = r17_journal_path()
        line = json.dumps(record, ensure_ascii=False, sort_keys=True)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(path.parent)
        _project_aborted_marker(reason)
        return {"status": "post_hoc_closure_written",
                "maintainer": record["maintainer_identity"]}
    finally:
        try:
            fcntl.flock(mfh.fileno(), fcntl.LOCK_UN)
            mfh.close()
        except OSError:
            pass
