# -*- coding: utf-8 -*-
"""QProd(RouteC_QualificationProducer_Integration_v1)Level A/B 运行上下文。

本轮工程实现的生产侧公共上下文层:

1. **两层独立运行身份**:Level A(新迭代资格链)与 Level B(K 坐标确认性
   研究)各自持有独立的 artifact root/state root/许可身份/计划身份,
   互不复用对方的状态目录或一次性消费记录;共享的是被验证的核心函数。
2. **根解析与加固**:正式入口只接受受信任部署配置
   (deploy_root/qprod_deploy_config.json)中批准的 canonical 根,
   不从任意用户输入或环境变量接受绕过根;工程入口显式注入隔离 test
   root,但在正式部署配置 mode=formal_ready 时拒绝执行工程面。
   路径别名/symlink/相对路径逃逸以 realpath 规范化后检查,不做纯
   字符串 startswith。
3. **旧根零写**:任何 qprod 写入目标不得解析进部署树历史正式产物
   面(artifacts/route_c_stage2_6_1_repair1[7-9]/state 等冻结根)。
4. **会话治理**:QProdRunSession 复用 r17 execgov 的职责与
   create-only 规则(flock 互斥 + 单写者 journal + 一轮一次被接受
   运行 + owner 死亡不可接管 + 拒绝留证),但 journal/锁/身份属于
   新迭代上下文,不写 R17 固定 iteration id。

本模块不签发任何许可(签发只在隔离 test authority / 未来正式
admission 链);真实正式 Level A/B 运行保持 NOT_RUN。
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

QPROD_CONTEXT_FORMAT = "cur261-qprod-context-v1"

#: 任务层(NEXT_GOAL §1:Level A 资格链 / Level B 确认性研究)。
QPROD_LEVELS = ("level_a", "level_b")

#: 运行 profile:engineering=本轮工程排练/烟测;formal=正式(须受信任
#: 配置 + 正式许可链;本轮无真实正式许可,formal 入口 fail closed)。
QPROD_PROFILES = ("engineering", "formal")

#: 受信任部署配置文件名(正式 canonical 根的唯一来源)。
QPROD_DEPLOY_CONFIG_NAME = "qprod_deploy_config.json"
QPROD_DEPLOY_CONFIG_FORMAT = "cur261-qprod-deploy-config-v1"

#: 工程上下文禁止出现在 formal_ready 部署(测试入口不得在正式部署放行)。
QPROD_DEPLOY_MODES = ("sandbox", "formal_ready")

#: 正式面拒绝环境重定向的变量名(正式 root 不可 env 注入)。
QPROD_ROOT_ENV_VARS = (
    "CURRICULUM261_QPROD_ART_ROOT",
    "CURRICULUM261_QPROD_STATE_ROOT",
)

#: 会话 journal(单写者;append-only;终态后不可重入)。
QPROD_JOURNAL_NAME = "qprod_run_journal.jsonl"
QPROD_SESSION_LOCK_NAME = "qprod_session.lock"
QPROD_REJECTED_DIR = "rejected_requests"

#: journal 合法事件集(迁移合法性:见 _replay_ok)。
QPROD_JOURNAL_EVENTS = (
    "session_acquired", "session_released", "permit_consumed",
    "run_terminal_recorded", "interruption_recorded",
)
_QPROD_TERMINAL_EVENTS = ("run_terminal_recorded",)
_QPROD_PROTECTED_FIELDS = ("seq", "utc", "event", "iteration_id",
                           "level", "pid", "owner", "writer")


class QProdContextError(RuntimeError):
    """上下文/根/身份校验失败(fail closed;零状态副作用)。"""


class QProdOwnershipError(RuntimeError):
    """会话所有权/重入拒绝(附独立 request 证据)。"""


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _canonical_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _fsync_dir(path: Path) -> None:
    fd = os.open(str(path), os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _realpath(path: Path | str) -> Path:
    """规范化绝对真实路径(解析全部 symlink;不做字符串前缀比较)。"""
    return Path(os.path.realpath(str(path)))


def _is_within(child: Path, parent: Path) -> bool:
    """realpath 语义的包含判断(非字符串 startswith)。"""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def protected_old_roots() -> tuple[Path, ...]:
    """历史冻结正式产物面(qprod 写入必须零落在其内)。

    覆盖(按规范名保护,**无论目标当前是否存在**——不存在时写入
    该路径同样是在冒建冻结正式根,必须拒绝;F4 修复:旧实现仅在
    目录已存在时保护,部署树解析为空导致守卫空转):
    - 各候选基(包祖先 0..4,覆盖仓库树 stage2_6_1 与部署树两层
      布局)下 artifacts/route_c_stage2_6_1_repair{17,18,19};
    - 已发布交付包目录 <base>/trading/packs(存在时);
    - 环境声明的 R17 部署 state root(CURRICULUM261_R17_DEPLOYED_
      STATE_ROOT,存在与否都保护——它是正式绑定声明)。
    """
    pkg_dir = Path(__file__).resolve().parent
    roots: list[Path] = []
    bases = list(pkg_dir.parents[:5])
    for base in bases:
        art = base / "artifacts"
        for name in ("route_c_stage2_6_1_repair17",
                     "route_c_stage2_6_1_repair18",
                     "route_c_stage2_6_1_repair19"):
            roots.append(_realpath(art / name))
        packs = base / "trading" / "packs"
        if packs.is_dir():
            roots.append(_realpath(packs))
    env_root = os.environ.get("CURRICULUM261_R17_DEPLOYED_STATE_ROOT")
    if env_root:
        roots.append(_realpath(env_root))
    return tuple(dict.fromkeys(roots))


def harden_root(path: Path | str, *, label: str,
                create: bool = True) -> Path:
    """根目录加固:绝对路径、realpath 规范化、旧根零写、越界拒绝。

    返回规范化后的真实路径;调用方只使用返回值落盘。别名(大小写/
    symlink/相对段)解析后命中保护根即拒绝——不是字符串 startswith。
    """
    raw = Path(str(path))
    if not raw.is_absolute():
        raise QProdContextError(
            f"{label} 必须是绝对路径(拒绝相对路径逃逸): {raw}")
    if ".." in raw.parts:
        raise QProdContextError(
            f"{label} 含 '..' 路径段(拒绝): {raw}")
    real = _realpath(raw)
    for prot in protected_old_roots():
        if _is_within(real, prot) or real == prot:
            raise QProdContextError(
                f"{label} {raw}(真实路径 {real})落在受保护历史根 "
                f"{prot} 内(旧 R17/R18/R19 状态面零写)")
    if create:
        real.mkdir(parents=True, exist_ok=True)
    return real


def load_deploy_config(deploy_root: Path | str) -> dict[str, Any]:
    """读取受信任部署配置(正式 canonical 根的唯一来源)。

    缺失/不可解析/格式不符 => QProdContextError(fail closed;
    formal 入口不得回退到任何隐式默认根)。
    """
    cfg_path = Path(deploy_root) / QPROD_DEPLOY_CONFIG_NAME
    if not cfg_path.is_file():
        raise QProdContextError(
            f"受信任部署配置缺失: {cfg_path}(正式根不可从环境/参数"
            f"取得;fail closed)")
    try:
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise QProdContextError(f"部署配置不可解析: {exc}") from exc
    if cfg.get("format") != QPROD_DEPLOY_CONFIG_FORMAT:
        raise QProdContextError(
            f"部署配置 format {cfg.get('format')!r} != "
            f"{QPROD_DEPLOY_CONFIG_FORMAT!r}")
    if cfg.get("mode") not in QPROD_DEPLOY_MODES:
        raise QProdContextError(
            f"部署配置 mode {cfg.get('mode')!r} 非法")
    return cfg


def resolve_formal_roots(deploy_root: Path | str, *,
                         level: str, iteration_id: str) -> dict[str, Path]:
    """正式根解析:仅受信任配置;环境重定向一律拒绝。"""
    redirected = [v for v in QPROD_ROOT_ENV_VARS if os.environ.get(v)]
    if redirected:
        raise QProdContextError(
            f"正式入口拒绝环境重定向({redirected};canonical 根只"
            f"来自受信任部署配置)")
    if level not in QPROD_LEVELS:
        raise QProdContextError(f"未知任务层 {level!r}")
    cfg = load_deploy_config(deploy_root)
    if cfg.get("mode") != "formal_ready":
        raise QProdContextError(
            f"部署配置 mode={cfg.get('mode')!r} 未批准正式运行"
            f"(正式 Level A/B 运行保持 NOT_RUN;fail closed)")
    entry = (cfg.get("formal_roots") or {}).get(iteration_id) or {}
    art = entry.get("artifact_root")
    state = entry.get("state_root")
    if not art or not state:
        raise QProdContextError(
            f"部署配置未批准迭代 {iteration_id!r} 的 canonical 根")
    return {
        "artifact_root": harden_root(art, label="formal artifact root"),
        "state_root": harden_root(state, label="formal state root",
                                  create=False),
    }


@dataclass(frozen=True)
class QProdContext:
    """一次 QProd 运行的已验证上下文(全链唯一传递对象)。"""

    level: str                    # level_a | level_b
    iteration_id: str
    profile: str                  # engineering | formal
    artifact_root: Path
    state_root: Path
    code_freeze_sha: str          # 代码冻结身份(候选 commit)
    plan_identity: dict[str, str]  # 计划身份(研究计划/资格计划 digest)
    permit_path: Path             # 许可文件(authority 目录内)
    authority_dir: Path           # 工程 test authority 目录(隔离)
    namespaces_scope: tuple[str, ...] = ()
    created_utc: str = field(default_factory=lambda: _now_utc())

    def to_payload(self) -> dict[str, Any]:
        return {
            "format": QPROD_CONTEXT_FORMAT,
            "level": self.level,
            "iteration_id": self.iteration_id,
            "profile": self.profile,
            "artifact_root": str(self.artifact_root),
            "state_root": str(self.state_root),
            "code_freeze_sha": self.code_freeze_sha,
            "plan_identity": dict(self.plan_identity),
            "permit_path": str(self.permit_path),
            "authority_dir": str(self.authority_dir),
            "namespaces_scope": list(self.namespaces_scope),
            "created_utc": self.created_utc,
        }

    def ensure_same(self, other: "QProdContext", *, what: str) -> None:
        """消费者边界核对:真实消费者拿到的就是这一个上下文。

        created_utc 是构造时刻而非身份字段,不参与比对。
        """
        mine = self.to_payload()
        theirs = other.to_payload()
        drift = {k: (mine[k], theirs[k]) for k in mine
                 if k != "created_utc" and mine[k] != theirs.get(k)}
        if drift:
            raise QProdContextError(
                f"{what} 上下文漂移(全链必须同一已验证上下文): {drift}")


def build_engineering_context(
        *, level: str, iteration_id: str, base_dir: Path | str,
        code_freeze_sha: str, authority_dir: Path | str,
        namespaces_scope: tuple[str, ...] = (),
        deploy_root_for_guard: Path | str | None = None,
) -> QProdContext:
    """工程上下文(显式隔离 test root;正式部署拒绝工程入口)。

    - base_dir 必须是隔离目录(经 harden_root 加固;不在保护根内);
    - authority_dir 是隔离工程 test authority 目录(签发发生在
      被验包之外;不得位于 state/artifact root 内部);
    - 若附近部署配置 mode=formal_ready,则工程入口拒绝执行
      (测试注入不得在正式部署放行)。
    """
    if level not in QPROD_LEVELS:
        raise QProdContextError(f"未知任务层 {level!r}")
    base = harden_root(base_dir, label="engineering base dir")
    authority = harden_root(authority_dir, label="authority dir",
                            create=False)
    art = harden_root(base / f"qprod_{level}_{iteration_id}" / "artifacts",
                      label="engineering artifact root")
    state = harden_root(base / f"qprod_{level}_{iteration_id}" / "state",
                        label="engineering state root")
    if _is_within(authority, state) or _is_within(authority, art):
        raise QProdContextError(
            "authority 目录不得位于本上下文 state/artifact root 内部"
            "(自授权拒绝)")
    guard_root = deploy_root_for_guard
    if guard_root is None:
        pkg_dir = Path(__file__).resolve().parent
        guard_root = pkg_dir.parents[2]
    cfg_path = Path(guard_root) / QPROD_DEPLOY_CONFIG_NAME
    if cfg_path.is_file():
        cfg = load_deploy_config(guard_root)
        if cfg.get("mode") == "formal_ready":
            raise QProdContextError(
                "部署配置 mode=formal_ready:工程/test root 注入入口"
                "在正式部署拒绝执行(测试入口不得放行)")
    return QProdContext(
        level=level, iteration_id=iteration_id, profile="engineering",
        artifact_root=art, state_root=state,
        code_freeze_sha=code_freeze_sha, plan_identity={},
        permit_path=authority / f"qprod_permit_{level}_{iteration_id}.json",
        authority_dir=authority,
        namespaces_scope=tuple(namespaces_scope))


class QProdRunSession:
    """单写者会话 journal(复用 execgov 职责;新迭代身份)。

    规则(r17 execgov 同源语义):
    - acquire 前置 flock(LOCK_EX|LOCK_NB),竞争即拒(留证);
    - 锁内重查 journal:已有终态(run_terminal_recorded)或已有
      session_acquired(即使 owner 已死)一律拒绝——一轮只有一次
      被接受的运行,不得接管重跑;
    - journal append-only,写前重放校验,非法迁移拒绝;
    - 拒绝 = 独立 request 证据 + 零 journal 副作用。
    """

    def __init__(self, state_root: Path, *, level: str,
                 iteration_id: str):
        self.state_root = Path(state_root)
        self.level = level
        self.iteration_id = iteration_id
        self._owner = f"{os.getpid()}@{int(time.time())}"
        self._fh = None
        self._acquired = False

    # ------------------------------------------------ journal 基础
    @property
    def journal_path(self) -> Path:
        return self.state_root / QPROD_JOURNAL_NAME

    def entries(self, *, strict: bool = True) -> list[dict[str, Any]]:
        if not self.journal_path.is_file():
            return []
        out: list[dict[str, Any]] = []
        for ln, line in enumerate(
                self.journal_path.read_text(encoding="utf-8")
                .splitlines(), 1):
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as exc:
                if strict:
                    raise QProdContextError(
                        f"journal 第 {ln} 行损坏(fail closed): {exc}")
                continue
            out.append(rec)
        return out

    def _replay_ok(self, prefix: list[dict[str, Any]]) -> bool:
        events = [e["event"] for e in prefix]
        if "session_released" in events and any(
                e not in ("session_released",) for e in events[
                    events.index("session_released") + 1:]):
            return False
        for ev in _QPROD_TERMINAL_EVENTS:
            if events.count(ev) > 1:
                return False
        if events.count("session_acquired") > 1:
            return False
        return True

    def _append(self, event: str,
                payload: dict[str, Any] | None = None) -> int:
        if not self._acquired:
            raise QProdOwnershipError(
                f"journal_append({event}) 要求已取得会话所有权")
        if event not in QPROD_JOURNAL_EVENTS:
            raise QProdContextError(f"未知 journal 事件 {event!r}")
        prefix = self.entries()
        n = len(prefix)
        record = {
            "seq": n + 1, "utc": _now_utc(), "event": event,
            "iteration_id": self.iteration_id, "level": self.level,
            "pid": os.getpid(), "owner": self._owner,
            "writer": "qprod_session_owner",
        }
        if payload:
            for k in payload:
                if k in _QPROD_PROTECTED_FIELDS:
                    raise QProdOwnershipError(
                        f"payload 键 {k!r} 受保护,不可覆盖身份字段")
            record.update(payload)
        if not self._replay_ok(prefix + [record]):
            raise QProdContextError(
                f"拒绝写入非法迁移 {event!r}(当前前缀 {n} 条)")
        with open(self.journal_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False,
                                sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        _fsync_dir(self.state_root)
        return record["seq"]

    def _write_rejection(self, reason: str,
                         binding: dict[str, Any] | None) -> Path:
        rej_dir = self.state_root / QPROD_REJECTED_DIR
        rej_dir.mkdir(parents=True, exist_ok=True)
        path = rej_dir / (
            f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}_"
            f"{reason}.json")
        path.write_text(json.dumps({
            "format": "cur261-qprod-session-rejection-v1",
            "reason": reason, "binding": binding or {},
            "iteration_id": self.iteration_id, "level": self.level,
            "utc": _now_utc(),
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    # ------------------------------------------------ 获取/释放
    def acquire(self, binding: dict[str, Any] | None = None) -> None:
        self.state_root.mkdir(parents=True, exist_ok=True)
        lock_path = self.state_root / QPROD_SESSION_LOCK_NAME
        fh = open(lock_path, "a+", encoding="utf-8")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            self._write_rejection("lock_held_by_active_owner", binding)
            raise QProdOwnershipError(
                "另一进程持有本上下文会话锁(竞争请求被拒绝;"
                "零 journal 副作用)") from exc
        entries = self.entries()
        events = [e["event"] for e in entries]
        if any(e in _QPROD_TERMINAL_EVENTS for e in events):
            fh.close()
            self._write_rejection("terminal_state_no_reentry", binding)
            raise QProdOwnershipError(
                "本上下文已记录终态:终态不可重入(不得删除锁/换根/"
                "换坐标救活已消费运行)")
        if "session_acquired" in events:
            # 锁可拿到 ⇒ 登记的 owner 已死;已接受的运行不可接管
            fh.close()
            acquired = next(e for e in entries
                            if e["event"] == "session_acquired")
            self._write_rejection(
                "already_accepted_run_no_takeover", binding)
            raise QProdOwnershipError(
                f"已有被接受的运行(owner={acquired.get('owner')});"
                f"owner 崩溃也不可接管重跑(中断收尾走 interruption_"
                f"recorded + 新隔离目录)")
        self._fh = fh
        self._acquired = True
        self._append("session_acquired", {
            "binding": binding or {}, "owner_alive_note":
                "fork 继承 fd 不构成所有权;journal 迁移重放为权威"})

    def release(self) -> None:
        self._append("session_released")
        if self._fh is not None:
            try:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            finally:
                self._fh.close()
                self._fh = None
        self._acquired = False

    # ------------------------------------------------ 事件记录
    def record_permit_consumed(self, permit_id: str) -> None:
        self._append("permit_consumed", {"permit_id": permit_id})

    def record_terminal(self, *, status: str, verdict: str,
                        plan_digest: str | None = None,
                        detail: dict[str, Any] | None = None) -> None:
        if status not in ("completed", "failed", "crashed"):
            raise QProdContextError(f"非法终态 {status!r}")
        self._append("run_terminal_recorded", {
            "status": status, "verdict": verdict,
            "plan_digest": plan_digest, "detail": detail or {}})

    def record_interruption(self, reason: str,
                            attribution: dict[str, Any]) -> None:
        """中断/半成品可归属记录(不自动重抽;不冒称完整结果)。"""
        self._append("interruption_recorded", {
            "reason": reason, "attribution": attribution})


__all__ = [
    "QPROD_CONTEXT_FORMAT", "QPROD_LEVELS", "QPROD_PROFILES",
    "QPROD_JOURNAL_NAME", "QPROD_JOURNAL_EVENTS",
    "QProdContextError", "QProdOwnershipError", "QProdContext",
    "QProdRunSession", "protected_old_roots", "harden_root",
    "load_deploy_config", "resolve_formal_roots",
    "build_engineering_context",
]
