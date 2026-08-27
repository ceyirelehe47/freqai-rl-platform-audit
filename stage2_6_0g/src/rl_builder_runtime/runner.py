"""Builder Runner worker:沙箱内执行私有 Builder(阶段 2.6.0g 收尾)。

启动形态(由 rl_builder_runtime.bootstrap exec):

    python -m rl_builder_runtime.runner <builder_pkg_staging> \
        <entrypoint_module> <entrypoint_qualname>

协议(builder-runner-worker-v1;每行一个 JSON):
- stdin:  单行冻结构建请求(builder-build-request-v2)
- stdout: 单行 Runner 响应
  {"protocol": "builder-runner-worker-v1", "status": "ok"|"failed",
   "build_result": {...v2 result...},
   "runtime_lock": {...实际 import 审计...},
   "access_summary": {"open_count": N, "outside_allowlist": [...]},
   "error": null | "..."}

职责边界:
- 私有 Builder 的 import 与执行**只发生在本沙箱进程**(主评估进程
  不 import 私有代码,顶层副作用不进入评估主进程;工作包 B1/C3);
- 运行时动态验证 entrypoint:callable、非类构造器、精确单 request
  位置参数(拒绝 *args/**kwargs/keyword-only/额外参数/候选别名参数;
  工作包 C1);
- build result v2 精确字段校验 + attempt log 规范化结构校验(D3/D4);
- sys.modules 快照差集 -> 实际加载的第三方模块 -> distribution
  映射运行时依赖锁(版本 + RECORD 哈希;无法映射 fail closed;
  工作包 G2);
- audit hook 记录 Builder 阶段全部 open 路径(allowlist 之外的访问
  上报;Landlock deny-by-default 兜底;工作包 B4/H);
- pack 以规范化 dict 透传(ExamPack 解析与 pack hash 在主进程做,
  本运行时不依赖评估方评估代码);
- 任何错误只回脱敏短消息,不回传 traceback/环境/文件内容。
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import sys
import types
from pathlib import Path

from rl_builder_runtime import BUILDER_WORKER_PROTOCOL

#: 单行请求/响应上限(私有请求很小;pack JSON 产物可达数 MB)
MAX_LINE_BYTES = 32 * 1024 * 1024

#: build 入口签名的候选别名黑名单(C1:参数名本身即拒绝)
FORBIDDEN_PARAM_NAMES = (
    "candidate", "candidate_path", "checkpoint", "checkpoint_path",
    "model", "policy", "score", "scores", "result", "exam_result",
    "verdict", "outcome", "prediction", "ranking",
)

#: builder build result v2 的精确字段集合(D3)
RESULT_FIELDS = frozenset({
    "format", "runner_protocol", "status", "pack", "attempt_log", "error",
})
#: attempt log 条目的精确字段集合(D4)
ATTEMPT_ENTRY_FIELDS = frozenset({"attempt", "verdict", "reject_reasons"})


class _RunnerFailure(Exception):
    """Runner 侧 fail closed 异常(消息必须可脱敏回传)。"""


def _emit(payload: dict) -> None:
    line = json.dumps(payload, ensure_ascii=False,
                      separators=(",", ":"))
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        sys.stdout.write(json.dumps({
            "protocol": BUILDER_WORKER_PROTOCOL,
            "status": "failed",
            "build_result": None, "runtime_lock": None,
            "access_summary": None,
            "error": "builder-runner-response-limit",
            "stage": "response-limit",
        }) + "\n")
        sys.stdout.flush()
        raise SystemExit(7)
    sys.stdout.write(line + "\n")
    sys.stdout.flush()


def _fail(error: str, stage: str, *, access_summary=None) -> int:
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "failed",
        "build_result": None,
        "runtime_lock": None,
        "access_summary": access_summary,
        "error": str(error)[:500],
        "stage": str(stage),
    })
    return 2


# ------------------------------------------------------------ 访问审计
class _AccessRecorder:
    """audit hook:记录 Builder 进程内全部 open 路径(H/B4)。

    只记录,不拒绝(拒绝交给 Landlock);allowlist 之外的 open 事件
    上报主进程。hook 内部吞掉一切异常,绝不因审计影响执行语义。
    """

    def __init__(self, allowlist_prefixes: list[str]):
        self._prefixes = [str(p) for p in allowlist_prefixes]
        self.open_events: list[str] = []
        self.outside: list[str] = []

    def hook(self, event: str, args) -> None:
        try:
            if event != "open":
                return
            path = args[0] if args else None
            if not isinstance(path, (str, bytes, int)):
                return
            path = str(path)
            self.open_events.append(path)
            if not any(path.startswith(p) for p in self._prefixes):
                if len(self.outside) < 64:
                    self.outside.append(path)
        except Exception:  # noqa: BLE001 - 审计绝不影响执行
            pass

    def summary(self) -> dict:
        # 只保留实际可 stat 到的违规路径:import 系统的 finder 探测
        # (如 editable 安装的 path hook)会对 sys.path 全部条目尝试
        # open,Landlock 拒绝的探测(ENoENT/EACCES,文件系统上 stat
        # 不可达)不构成信息泄露;读得到的 outside 才是真实违规
        import os

        reachable = [p for p in self.outside if os.path.exists(p)]
        return {
            "open_count": len(self.open_events),
            "outside_allowlist": reachable,
        }


# ------------------------------------------------------------ 入口验证
def _validate_entrypoint_signature(fn) -> list[str]:
    """C1:build 入口必须是精确的 ``build_pack(request)``。

    允许恰好一个位置参数(POSITIONAL_ONLY 或 POSITIONAL_OR_KEYWORD),
    除此之外不得有其他参数。返回违规原因列表(空 = 通过)。
    """
    problems: list[str] = []
    try:
        sig = inspect.signature(fn)
    except (TypeError, ValueError) as exc:
        return [f"签名无法解析: {exc}"]
    params = list(sig.parameters.values())
    if len(params) != 1:
        problems.append(
            f"入口必须恰好接受一个 request 参数(收到 {len(params)} 个)")
    for p in params:
        if p.kind == inspect.Parameter.VAR_POSITIONAL:
            problems.append(f"入口不接受 *args(参数 {p.name!r})")
        elif p.kind == inspect.Parameter.VAR_KEYWORD:
            problems.append(f"入口不接受 **kwargs(参数 {p.name!r})")
        elif p.kind == inspect.Parameter.KEYWORD_ONLY:
            problems.append(f"入口不接受 keyword-only 参数(参数 {p.name!r})")
        elif p.default is not inspect.Parameter.empty:
            problems.append(f"入口参数 {p.name!r} 不得有默认值(可选参数被拒绝)")
        if p.name in FORBIDDEN_PARAM_NAMES:
            problems.append(f"入口参数名 {p.name!r} 是候选相关禁止参数")
    return problems


def _validate_build_result(raw) -> dict:
    """D3:builder 返回值的精确字段与结构校验(沙箱侧第一道)。"""
    if raw is None:
        raise _RunnerFailure("build 入口返回 None(必须返回规范化 result)")
    if not isinstance(raw, dict):
        raise _RunnerFailure(
            f"build 入口返回类型 {type(raw).__name__} 不是 dict")
    unknown = sorted(set(raw) - RESULT_FIELDS)
    if unknown:
        raise _RunnerFailure(f"build 结果含未知字段 {unknown}")
    missing = sorted(RESULT_FIELDS - set(raw) - {"error"})
    if missing:
        raise _RunnerFailure(f"build 结果缺少字段 {missing}")
    if raw.get("format") != "builder-build-result-v2":
        raise _RunnerFailure(
            f"build 结果 format 必须是 'builder-build-result-v2'(收到 "
            f"{raw.get('format')!r})")
    if raw.get("runner_protocol") != "builder-runner-protocol-v2":
        raise _RunnerFailure(
            f"build 结果 runner 协议必须是 "
            f"'builder-runner-protocol-v2'(收到 "
            f"{raw.get('runner_protocol')!r})")
    if raw.get("status") != "ok":
        raise _RunnerFailure(
            f"build 自报失败 status={raw.get('status')!r}: "
            f"{str(raw.get('error'))[:200]}")
    if raw.get("error") not in (None, ""):
        raise _RunnerFailure("status=ok 但 error 非空(不自洽)")
    if not isinstance(raw.get("pack"), dict):
        raise _RunnerFailure(
            "build 结果的 pack 必须是规范化 pack JSON dict"
            "(ExamPack 规范由主进程解析)")
    _check_attempt_log_structure(raw.get("attempt_log"))
    return raw


def _check_attempt_log_structure(log) -> None:
    """D4:attempt log 的规范化结构合同(值级合同由主进程补全)。"""
    if not isinstance(log, dict):
        raise _RunnerFailure(
            f"attempt_log 必须是规范化 dict(收到 {type(log).__name__})")
    if log.get("format") != "builder-attempt-log-v1":
        raise _RunnerFailure(
            f"attempt_log.format 必须是 'builder-attempt-log-v1'(收到 "
            f"{log.get('format')!r})")
    ma = log.get("max_attempts")
    if not isinstance(ma, int) or isinstance(ma, bool) or ma < 0:
        raise _RunnerFailure("attempt_log.max_attempts 必须是非负 int")
    attempts = log.get("attempts")
    if not isinstance(attempts, list):
        raise _RunnerFailure("attempt_log.attempts 必须是 list")
    for entry in attempts:
        if not isinstance(entry, dict) or set(entry) != ATTEMPT_ENTRY_FIELDS:
            raise _RunnerFailure(
                "attempt_log 条目字段必须恰好是 "
                f"{sorted(ATTEMPT_ENTRY_FIELDS)}")
        if not isinstance(entry.get("attempt"), int) \
                or isinstance(entry.get("attempt"), bool):
            raise _RunnerFailure("attempt 条目的 attempt 必须是 int")
        if entry.get("verdict") not in ("accept", "reject"):
            raise _RunnerFailure(
                f"attempt 条目的 verdict 必须是 accept|reject(收到 "
                f"{entry.get('verdict')!r})")
        reasons = entry.get("reject_reasons")
        if not isinstance(reasons, list) or \
                not all(isinstance(r, str) for r in reasons):
            raise _RunnerFailure(
                "attempt 条目的 reject_reasons 必须是字符串列表")
    sel = log.get("selected_attempt")
    if sel is not None and (not isinstance(sel, int)
                            or isinstance(sel, bool)):
        raise _RunnerFailure("attempt_log.selected_attempt 必须是 int 或 null")
    if ma == 0 and attempts:
        raise _RunnerFailure(
            "max_attempts=0(组装模式)不得携带 attempt 条目")
    if sel is not None and not any(
            e.get("attempt") == sel and e.get("verdict") == "accept"
            for e in attempts):
        raise _RunnerFailure(
            "selected_attempt 必须指向一个 verdict=accept 的条目")


# ------------------------------------------------------------ 运行时依赖锁
def _runtime_import_lock(
    baseline: frozenset, after: frozenset, staging_root: str,
) -> tuple[dict, str]:
    """G2:实际 import 审计 -> 第三方 distribution 运行时锁。

    返回 (lock, error):error 非空表示 fail closed(无法映射/版本缺失/
    RECORD 缺失)。lock 绑定 distribution 名、版本、RECORD 哈希、
    实际 import 的顶级模块与 Python 运行时身份。
    """
    import importlib.metadata as md

    new_modules = sorted(after - baseline)
    top_level: dict[str, list[str]] = {}
    for full in new_modules:
        top = full.split(".")[0]
        top_level.setdefault(top, []).append(full)
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    entries: list[dict] = []
    for top in sorted(top_level):
        if top in stdlib or top == "rl_builder_runtime":
            continue
        mod = sys.modules.get(top)
        origin = str(getattr(mod, "__file__", "") or "")
        if origin.startswith(str(staging_root)):
            # builder package 自身模块(staging 内,已被 npb- tree manifest
            # 绑定,不属于外部依赖)
            continue
        if not origin:
            # 无源文件的命名空间/动态模块:无法绑定内容,fail closed
            return {}, f"module {top!r} 无源文件,无法验证内容身份"
        dist_names = md.packages_distributions().get(top)
        if not dist_names:
            return {}, (
                f"实际加载的第三方模块 {top!r} 无法映射到任何已安装 "
                f"distribution(未注册依赖 fail closed)")
        dist_name = sorted(dist_names)[0]
        try:
            dist = md.distribution(dist_name)
            version = str(dist.version)
        except Exception as exc:  # noqa: BLE001 - 元数据缺失 fail closed
            return {}, f"distribution {dist_name!r} 元数据不可读: {exc}"
        record_path = None
        try:
            for f in dist.files or []:
                if f.name == "RECORD" and len(f.parts) >= 1 \
                        and f.parts[-1] == "RECORD":
                    record_path = \
                        Path(dist._path) / "RECORD"  # noqa: SLF001
                    break
        except Exception:  # noqa: BLE001
            record_path = None
        record_sha = "<missing-record>"
        if record_path is None:
            record_path = Path(getattr(dist, "_path", "")) / "RECORD"
        if record_path and record_path.is_file():
            record_sha = hashlib.sha256(
                record_path.read_bytes()).hexdigest()
        if record_sha == "<missing-record>":
            return {}, (
                f"distribution {dist_name!r} 缺少安装元数据 RECORD,"
                f"内容无法验证(fail closed)")
        entries.append({
            "module": top,
            "distribution": dist_name,
            "version": version,
            "record_sha256": record_sha,
            "imported": sorted(top_level[top]),
        })
    lock = {
        "format": "builder-runtime-lock-v1",
        "python_implementation": sys.implementation.name,
        "python_version": sys.version.split()[0],
        "executable_prefix": str(getattr(sys, "prefix", "")),
        "distributions": entries,
    }
    return lock, ""


# ------------------------------------------------------------ 主流程
def main(argv: list[str]) -> int:
    if len(argv) != 4:
        return _fail(
            "usage: python -m rl_builder_runtime.runner <staging> "
            "<module> <qualname>", "usage")
    staging_root = str(Path(argv[1]).resolve())
    entrypoint_module = str(argv[2])
    entrypoint_qualname = str(argv[3])
    if not entrypoint_module or not entrypoint_qualname:
        return _fail("entrypoint module/qualname 为空", "usage")
    # stdin:冻结构建请求(单行 JSON)
    line = sys.stdin.readline()
    if not line.strip():
        return _fail("未收到冻结构建请求(stdin 为空)", "request")
    if len(line.encode("utf-8")) > MAX_LINE_BYTES:
        return _fail("请求超过字节上限", "request-limit")
    try:
        request = json.loads(line)
    except json.JSONDecodeError:
        return _fail("请求不是合法 JSON", "request")
    if not isinstance(request, dict):
        return _fail("请求必须是 JSON 对象", "request")

    # 审计 allowlist:staging + python 运行时前缀(其余路径的 open 事件
    # 上报;Landlock 已在 deny-by-default 层面拒绝候选材料/评估工作区)
    prefixes = [staging_root, str(Path(sys.prefix).resolve())]
    recorder = _AccessRecorder(prefixes)
    baseline = frozenset(sys.modules)
    sys.addaudithook(recorder.hook)
    try:
        # 受控 import:staging 优先;陈旧缓存(源文件不在本 staging 内)
        # 先弹出,保证执行的是刚验证过的 staging 副本(B3:不依赖主进程
        # sys.modules 缓存;源码 A / 缓存 B 攻击在隔离进程内无缓存可污染)
        cached = sys.modules.get(entrypoint_module)
        if cached is not None:
            cached_file = str(getattr(cached, "__file__", "") or "")
            if cached_file and not cached_file.startswith(staging_root):
                sys.modules.pop(entrypoint_module, None)
        sys.path.insert(0, staging_root)
        mod = importlib.import_module(entrypoint_module)
        obj: object = mod
        for part in entrypoint_qualname.split("."):
            if not hasattr(obj, part):
                raise _RunnerFailure(
                    f"qualname {entrypoint_qualname!r} 在 import 后不存在"
                    f"(属性 {part!r} 缺失)")
            obj = getattr(obj, part)
        # 运行时动态验证(C1/C3:发生在隔离 Runner,不在主评估进程)
        if not callable(obj):
            raise _RunnerFailure(
                f"入口 {entrypoint_qualname!r} 不是 callable")
        if isinstance(obj, type):
            raise _RunnerFailure(
                f"入口 {entrypoint_qualname!r} 是类构造器,被拒绝")
        if not isinstance(obj, (types.FunctionType, types.MethodType,
                                types.BuiltinFunctionType)):
            raise _RunnerFailure(
                f"入口运行时类型 {type(obj).__name__!r} 不在允许范围")
        problems = _validate_entrypoint_signature(obj)
        if problems:
            raise _RunnerFailure(
                "build 入口签名违规: " + "; ".join(problems))
        raw = obj(dict(request))
        result = _validate_build_result(raw)
    except _RunnerFailure as exc:
        return _fail(str(exc), "entrypoint-or-build",
                     access_summary=recorder.summary())
    except ImportError as exc:
        return _fail(f"builder module import 失败: {exc}", "import",
                     access_summary=recorder.summary())
    except Exception as exc:  # noqa: BLE001 - builder 异常一律 fail closed
        return _fail(
            f"builder 执行抛出 {type(exc).__name__}(脱敏)",
            "execution", access_summary=recorder.summary())
    # 运行时依赖锁(G2):实际加载的第三方模块必须全部可映射验证
    try:
        lock, lock_error = _runtime_import_lock(
            baseline, frozenset(sys.modules), staging_root)
    except Exception as exc:  # noqa: BLE001
        return _fail(f"运行时 import 审计失败: {exc}", "runtime-lock",
                     access_summary=recorder.summary())
    if lock_error:
        return _fail(f"运行时依赖锁 fail closed: {lock_error}",
                     "runtime-lock", access_summary=recorder.summary())
    access = recorder.summary()
    if access["outside_allowlist"]:
        import os

        names = sorted({os.path.basename(p)
                        for p in access["outside_allowlist"]})[:8]
        return _fail(
            "Builder 访问了 allowlist 之外的路径(已记录并拒绝采信):"
            + ",".join(names), "access", access_summary=access)
    _emit({
        "protocol": BUILDER_WORKER_PROTOCOL,
        "status": "ok",
        "build_result": result,
        "runtime_lock": lock,
        "access_summary": access,
        "error": None,
    })
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
