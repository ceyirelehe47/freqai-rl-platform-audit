# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:Generation Invocation Envelope(工作包 A)。

R10 确认输入(calibrate/supervised main 的 c3_cost/D0/pair1 五连败
too_few_distractors,三种重放不可复现,attempt 明细未落盘):
PairGenerationError 只保留字符串化 reasons,正式失败后无法复原每个
attempt 的真实生成输入 —— 任何未解释异常永远无法定位根因。

R11 修复(A1/A2/A3):
- GenerationInvocationEnvelope-v1:每次 pair attempt 的完整、稳定、
  可序列化、可哈希、可重放的调用证据。覆盖:调用坐标(namespace/
  family/rung/pair/attempt)、outer seed、canonical rung params、
  A/B 最终 base params、generator 源码身份、family_specs 注册项
  身份、generator 实例状态摘要(逐 attempt pre/post)、内部派生
  seed、split/timeframe、运行时版本(Python/NumPy/pandas/Torch)、
  PYTHONHASHSEED、线程环境变量、事件表摘要、结构计数、A/B episode
  内容哈希、structural validator 逐项结果、拒绝原因、接受状态。
- 全部规范化表示:canonical JSON(sort_keys + separators),不依赖
  repr、dict 插入顺序或进程随机 hash;set 一律 sorted。
- PairGenerationError 携带逐 attempt envelopes(见 api.py);
  supervise/calibration/final 任何生成失败路径在 abort 前落盘。
- replay 入口:envelope -> 重建调用 -> 逐字段对比(不读 PnL 或
  qualification 结果决定重放行为)。

合同边界:envelope 构建是**纯观察** —— 不改变 seed、生成顺序或
接受条件(recorder 异常被 api._recorder_record 吞掉并登记)。
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_TIMEFRAME,
    PairGenerationError,
    derive261_seed,
    episode_content_hash,
)
from rl_curriculum.curriculum261_pairs import family_specs

ENVELOPE_FORMAT = "cur261-generation-invocation-envelope-v1"
#: envelope 内容哈希前缀(区别于其他 r11 摘要命名空间)
ENVELOPE_DIGEST_PREFIX = "r11env-"
#: 调用级静态身份哈希前缀
CALL_ENVELOPE_DIGEST_PREFIX = "r11call-"

#: 结构计数的 hidden 列(c3: signals/distractors/above/below;
#: c1/c2 列不存在时计 None —— 列存在性本身进入摘要)
_COUNT_COLUMNS = (
    "sig_dir", "distractor_flag", "above_cost", "cue_dir",
    "payoff_active",
)

#: 会被记录的线程/BLAS 环境变量(确定性矩阵的场景维度)
THREAD_ENV_KEYS = (
    "OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS",
    "NUMEXPR_NUM_THREADS", "VECLIB_MAXIMUM_THREADS",
)


# ------------------------------------------------ 规范化与稳定哈希
def canonical_json(obj: Any) -> str:
    """规范化 JSON 串(sort_keys;不依赖 dict 插入顺序)。

    非法类型直接 TypeError(fail closed —— 宁可拒绝也不退回 repr)。
    """
    return json.dumps(
        _canonicalize(obj), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False)


def _canonicalize(obj: Any) -> Any:
    """递归规范化:set 排序、tuple->list、ndarray->嵌套 list、
    Path->str、numpy 标量->Python 标量。"""
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        if np.isnan(obj) or np.isinf(obj):
            return {"__float__": repr(float(obj))}
        return float(obj)
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return _canonicalize(float(obj))
    if isinstance(obj, np.ndarray):
        return _canonicalize(obj.tolist())
    if isinstance(obj, dict):
        return {str(k): _canonicalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_canonicalize(v) for v in obj]
    if isinstance(obj, (set, frozenset)):
        return {"__sorted_set__": sorted(
            _canonicalize(v) if isinstance(v, (str, int, float, bool))
            else str(v) for v in obj)}
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, pd.DataFrame):
        return {"__dataframe__": dataframe_digest(obj)}
    if isinstance(obj, (pd.Series,)):
        return _canonicalize(obj.tolist())
    if isinstance(obj, bytes):
        return {"__bytes_sha256__": hashlib.sha256(obj).hexdigest()}
    raise TypeError(
        f"envelope 规范化不接受类型 {type(obj).__name__!r}"
        f"(值截断: {str(obj)[:80]!r})")


def stable_digest(obj: Any, prefix: str) -> str:
    """稳定内容哈希:prefix + sha256(canonical JSON)。"""
    return prefix + hashlib.sha256(
        canonical_json(obj).encode("utf-8")).hexdigest()


def dataframe_digest(df: pd.DataFrame) -> str:
    """DataFrame 内容摘要(float64 规范化 CSV 与 episode_content_hash
    同口径;列顺序按排序后规范化,不受插入顺序影响)。"""
    cols = sorted(c for c in df.columns)
    h = hashlib.sha256()
    for c in cols:
        h.update(c.encode("utf-8"))
        h.update(b"|")
    h.update(b"||")
    h.update(
        df[cols].astype("float64").to_csv(
            index=False, float_format="%.17g").encode("utf-8"))
    return "df-" + h.hexdigest()


# ------------------------------------------------ 身份捕获
def _module_source_identity(obj: Any) -> dict[str, Any]:
    """对象定义模块的源码身份(文件 sha256 + 模块名)。"""
    mod = inspect.getmodule(obj)
    src_file = inspect.getsourcefile(obj)
    sha = ""
    if src_file and Path(src_file).is_file():
        sha = hashlib.sha256(
            Path(src_file).read_bytes()).hexdigest()
    return {
        "module": getattr(mod, "__name__", "") if mod else "",
        "source_file_stem": Path(src_file).stem if src_file else "",
        "source_sha256": sha,
    }


def generator_identity(generator: Any) -> dict[str, Any]:
    """生成器源码身份:class 全名 + 定义文件 sha256 + family 版本。"""
    cls = type(generator)
    ident = _module_source_identity(cls)
    ident.update({
        "class": f"{cls.__module__}.{cls.__qualname__}",
        "family": getattr(generator, "family", ""),
        "family_version": getattr(generator, "family_version", ""),
        "fingerprint": generator.fingerprint(),
    })
    return ident


def _value_state_digest(v: Any) -> str:
    """实例属性值的稳定摘要(规范递归;ndarray/DataFrame 走字节)。"""
    if isinstance(v, np.ndarray):
        return "arr-" + hashlib.sha256(
            np.ascontiguousarray(v).tobytes()
            + str(v.dtype).encode() + str(v.shape).encode()).hexdigest()
    if isinstance(v, pd.DataFrame):
        return dataframe_digest(v)
    return stable_digest({"v": _canonicalize(v)}, "val-")


def generator_state_digest(generator: Any) -> str:
    """生成器实例状态摘要(实例 __dict__ 逐键;键集排序)。

    覆盖:C2 的 _matched_tape_excludes(实例属性)、任何运行中被
    setattr 的字段。值为 None 的实例属性从摘要中剔除 —— None 与
    "属性不存在"语义等价(C2 的 _wick_plan 逐调用交接槽在调用后
    显式清空为 None,与类默认 None 等价;真正影响行为的污染
    (如 _matched_tape_excludes 被设为非空 tuple)仍然可检出)。
    类级常量不在此(不可变约定由 family_spec_identity 的源码 sha
    覆盖)。
    """
    state = {}
    for k in sorted(vars(generator)):
        v = vars(generator)[k]
        if v is None:
            continue
        state[k] = _value_state_digest(v)
    return stable_digest(state, "gstate-")


def family_spec_identity() -> dict[str, Any]:
    """family_specs() 注册项身份:generator 身份 + rung_params 内容
    摘要 + 各函数源码 sha(逐项)。"""
    out: dict[str, Any] = {}
    for fam, spec in sorted(family_specs().items()):
        out[fam] = {
            "generator": generator_identity(spec.generator),
            "generator_state_digest": generator_state_digest(
                spec.generator),
            "rung_params_digest": stable_digest(
                spec.rung_params, "rungparams-"),
            "reference_defaults_digest": stable_digest(
                spec.reference_defaults, "refdef-"),
            "integrity_metrics_source": _module_source_identity(
                spec.integrity_metrics)["source_sha256"],
            "construction_check_source": _module_source_identity(
                spec.construction_check)["source_sha256"],
        }
    return out


def runtime_identity() -> dict[str, Any]:
    """关键运行时版本 + PYTHONHASHSEED + 线程环境变量。"""
    ident: dict[str, Any] = {
        "python": sys.version,
        "python_executable_stem": Path(sys.executable).name,
        "numpy": np.__version__,
        "pandas": pd.__version__,
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "<unset>"),
        "thread_env": {k: os.environ.get(k, "<unset>")
                       for k in THREAD_ENV_KEYS},
    }
    for name in ("torch",):
        try:
            mod = sys.modules.get(name)
            if mod is None:
                ident[name] = "<not-imported>"
            else:
                ident[name] = getattr(mod, "__version__", "<imported>")
        except Exception:  # noqa: BLE001
            ident[name] = "<error>"
    return ident


def event_table_summary(episodes: dict[str, Any]) -> dict[str, Any]:
    """事件表摘要:hidden 内容 digest + 逐侧结构计数。

    GeneratorError 部分 episode:存在侧照常摘要;missing 侧记录
    null。计数列缺失 -> None(列存在性进摘要)。
    """
    out: dict[str, Any] = {}
    for side in ("A", "B"):
        ep = episodes.get(side)
        if ep is None:
            out[side] = None
            continue
        hidden = ep.hidden
        counts: dict[str, Any] = {}
        for col in _COUNT_COLUMNS:
            if col in hidden.columns:
                arr = hidden[col].to_numpy()
                counts[col + "_nonzero"] = int(np.count_nonzero(arr))
            else:
                counts[col + "_nonzero"] = None
        if "sig_dir" in hidden.columns and "distractor_flag" in (
                hidden.columns):
            sig = (hidden["sig_dir"].to_numpy() != 0) & (
                hidden["distractor_flag"].to_numpy() == 0)
            counts["n_signals"] = int(sig.sum())
            above = (hidden["above_cost"].to_numpy()
                     if "above_cost" in hidden.columns
                     else np.zeros(len(hidden)))
            counts["n_above_cost"] = int(np.count_nonzero(above[sig]))
            counts["n_below_cost"] = int(
                sig.sum() - counts["n_above_cost"])
            counts["n_distractors"] = int(np.count_nonzero(
                hidden["distractor_flag"].to_numpy()))
        out[side] = {
            "hidden_digest": dataframe_digest(hidden),
            "counts": counts,
            "episode_content_hash": episode_content_hash(ep),
            "bars": int(len(ep.df)),
        }
    return out


#: envelope digest 的非身份字段:runtime 是环境上下文元数据
#: (Python/NumPy/Torch 版本、PYTHONHASHSEED、线程环境变量),不参与
#: 生成身份 —— 否则"import torch 前后"或"不同 PYTHONHASHSEED"的
#: 合法环境差异会污染 envelope digest,掩盖真正的生成输入漂移。
_ENVELOPE_NON_IDENTITY_KEYS = ("digest", "runtime")


def _digest_body(env: dict[str, Any]) -> dict[str, Any]:
    """envelope/call envelope 的 digest 计算体(剔除非身份字段)。"""
    return {k: v for k, v in env.items()
            if k not in _ENVELOPE_NON_IDENTITY_KEYS}


# ------------------------------------------------ recorder(A1 核心)
class EnvelopeRecorder:
    """被动 attempt recorder:构建逐 attempt 完整调用证据。

    用法(r11 生成路径专用 wrapper):
        rec = EnvelopeRecorder(iteration="r11", namespace=...,
                               family=..., rung=..., pair_index=...,
                               rung_params=rung_params)
        episodes, log = generate_pair_with_attempts(..., recorder=rec)
    每个 attempt 结束后 api.generate_pair_with_attempts 调用
    rec.record("attempt", payload);envelope 立即物化(不保留
    episode 引用),可 JSONL 追加落盘(crash 持久)。
    """

    def __init__(self, *, iteration: str, namespace: str, family: str,
                 rung: str, pair_index: int,
                 rung_params: dict[str, Any],
                 rung_params_override: dict | None = None) -> None:
        spec = family_specs()[family]
        self.iteration = str(iteration)
        self.namespace = str(namespace)
        self.family = str(family)
        self.rung = str(rung)
        self.pair_index = int(pair_index)
        self.rung_params_snapshot = json.loads(canonical_json(
            {"params": _canonicalize(rung_params)}))["params"]
        self.attempt_envelopes: list[dict[str, Any]] = []
        self._generator = spec.generator
        self._state_digest = generator_state_digest(spec.generator)
        self._first_state_digest = self._state_digest
        #: 调用级静态身份(构造时定格;进入 PairGenerationError)
        self.call_envelope: dict[str, Any] = {
            "format": ENVELOPE_FORMAT + "-call",
            "iteration": self.iteration,
            "namespace": self.namespace,
            "family": self.family,
            "rung": self.rung,
            "pair_index": self.pair_index,
            "max_attempts": 5,
            "rung_params": self.rung_params_snapshot,
            "rung_params_override_keys": sorted(
                (rung_params_override or {}).keys()),
            "split": f"curriculum261_{self.namespace}",
            "timeframe": CURRICULUM261_TIMEFRAME,
            "generator": generator_identity(spec.generator),
            "generator_initial_state_digest": self._first_state_digest,
            "family_spec_identity": family_spec_identity(),
            "runtime": runtime_identity(),
        }
        self.call_envelope["digest"] = stable_digest(
            _digest_body(self.call_envelope),
            CALL_ENVELOPE_DIGEST_PREFIX)

    # -- api.generate_pair_with_attempts 的被动钩子 --
    def record(self, event: str, payload: dict[str, Any]) -> None:
        if event != "attempt":
            return
        attempt = int(payload["attempt"])
        seed = int(payload["seed"])
        episodes = payload.get("episodes") or {}
        pre_state = self._state_digest
        post_state = generator_state_digest(self._generator)
        self._state_digest = post_state
        # 内部派生 seed 的确定性重算(resolve->derive;纯观察)
        internal_seed = self._recompute_internal_seed(
            payload["params"], seed)
        env: dict[str, Any] = {
            "format": ENVELOPE_FORMAT,
            "iteration": self.iteration,
            "namespace": self.namespace,
            "family": self.family,
            "rung": self.rung,
            "pair_index": self.pair_index,
            "attempt_index": attempt,
            "outer_seed": seed,
            "seed_derivation_fields": {
                "namespace": self.namespace, "family": self.family,
                "rung": self.rung, "pair_index": self.pair_index,
                "attempt": attempt,
                "stage_id": "stage2_6_1",
            },
            "split": self.call_envelope["split"],
            "timeframe": CURRICULUM261_TIMEFRAME,
            "base_params": {
                side: json.loads(canonical_json(
                    {"p": _canonicalize(
                        payload["params"].get(side, {}))}))["p"]
                for side in ("A", "B")},
            "generator": self.call_envelope["generator"],
            "generator_state_digest_pre": pre_state,
            "generator_state_digest_post": post_state,
            "generator_state_changed": pre_state != post_state,
            "generator_state_changed_since_call_start":
                post_state != self._first_state_digest,
            "internal_derived_seed": internal_seed,
            "runtime": self.call_envelope["runtime"],
            "event_table": event_table_summary(episodes),
            "structural_validator_results": list(
                payload.get("issues") or []),
            "rejection_reasons": list(payload.get("issues") or []),
            "accepted": bool(payload.get("accepted")),
            "exception": payload.get("exception"),
        }
        env["digest"] = stable_digest(
            _digest_body(env), ENVELOPE_DIGEST_PREFIX)
        self.attempt_envelopes.append(env)

    def _recompute_internal_seed(self, params: dict, seed: int) -> int | None:
        try:
            from rl_curriculum.generator_api import (
                resolve_generator_params,
            )
            resolved = resolve_generator_params(
                params.get("A") or {}, CURRICULUM261_TIMEFRAME)
            return int(self._generator.derive_seed(
                resolved.effective_params, seed))
        except Exception:  # noqa: BLE001 —— 重算失败记 None(诊断)
            return None


def write_attempt_envelopes(path: Path,
                            call_envelope: dict[str, Any],
                            envelopes: list[dict[str, Any]],
                            error_note: str = "") -> dict[str, Any]:
    """PairGenerationError 证据落盘(原子;A2)。

    返回 manifest(供 abort artifact 引用);文件本身是完整 JSON
    (call envelope + 全部 attempt envelopes + error note)。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "format": "cur261-generation-failure-evidence-v1",
        "call_envelope": call_envelope,
        "attempt_envelopes": envelopes,
        "n_attempt_envelopes": len(envelopes),
        "error_note": error_note,
        "written_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(
            timespec="seconds"),
    }
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)
    return {
        "path": str(path),
        "n_attempt_envelopes": len(envelopes),
        "call_envelope_digest": call_envelope.get("digest", ""),
        "attempt_digests": [e.get("digest", "")
                            for e in envelopes],
        "sha256": hashlib.sha256(
            path.read_bytes()).hexdigest(),
    }


def dump_failure_evidence(exc: PairGenerationError, out_dir: Path,
                          stage_label: str) -> dict[str, Any] | None:
    """从 PairGenerationError 提取并落盘全部 attempt envelopes。

    供 calibrate/supervised/final 的异常处置路径在 abort marker 之前
    调用;异常对象没有 envelopes(历史路径)时返回 None。
    """
    envelopes = list(getattr(exc, "attempt_envelopes", None) or [])
    call_env = getattr(exc, "call_envelope", None)
    if not envelopes and call_env is None:
        return None
    fam = (call_env or {}).get("family", "unknown")
    rung = (call_env or {}).get("rung", "unknown")
    pair = (call_env or {}).get("pair_index", -1)
    name = f"generation_failure_envelopes_{stage_label}_{fam}_{rung}_p{pair}.json"
    return write_attempt_envelopes(
        Path(out_dir) / name, call_env or {}, envelopes,
        error_note=str(exc)[:2000])


# ------------------------------------------------ envelope ledger(A1)
class EnvelopeLedger:
    """JSONL 追加式 envelope 台账(逐 attempt flush;crash 持久)。

    正式 R11 生成路径(supervised/corpus/equiv/independent)每完成
    一个 pair 就把该 pair 的全部 attempt envelopes 追加进台账。
    """

    def __init__(self, path: Path, *, stage_label: str,
                 iteration: str = "r11") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.stage_label = str(stage_label)
        self.iteration = str(iteration)
        self._fh = open(self.path, "a", encoding="utf-8")

    def append_pair(self, recorder: EnvelopeRecorder) -> None:
        for env in recorder.attempt_envelopes:
            row = {
                "stage": self.stage_label,
                "iteration": self.iteration,
                "call_digest": recorder.call_envelope["digest"],
                "envelope": env,
            }
            self._fh.write(json.dumps(
                row, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def close(self) -> None:
        self._fh.close()

    def __enter__(self) -> "EnvelopeLedger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def read_envelope_ledger(path: Path) -> list[dict[str, Any]]:
    """读回台账行(坏行以占位保留,不抛错)。"""
    rows: list[dict[str, Any]] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"unparseable_line": line[:200]})
    return rows


def ledger_rows_digest(rows: list[dict[str, Any]]) -> str:
    """台账身份摘要:stage + call_digest + attempt envelope digests。

    时间戳等非身份字段不进入(两 cold run 台账一致性的比较口径)。
    """
    idents = [
        [r.get("stage", ""), r.get("call_digest", ""),
         (r.get("envelope") or {}).get("digest", "")]
        for r in rows if "unparseable_line" not in r]
    return stable_digest(idents, "r11ledger-")


# ------------------------------------------------ 全局 sink(A1 覆盖层)
_ACTIVE_SINK_FACTORY = None


def active_recorder(iteration: str, namespace: str, family: str,
                    rung: str, pair_index: int,
                    rung_params: dict[str, Any]):
    """api._default_recorder 的查询入口(sink 未打开返回 None)。

    R11 正式阶段通过 envelope_sink 打开 sink 后,所有
    generate_pair_with_attempts 调用(含 R6 冻结 runner 内部的
    generate_pair)自动获得 recorder;sink 关闭 = 历史路径零影响。
    """
    if _ACTIVE_SINK_FACTORY is None:
        return None
    try:
        return _ACTIVE_SINK_FACTORY(
            iteration=iteration, namespace=namespace, family=family,
            rung=rung, pair_index=pair_index, rung_params=rung_params)
    except Exception:  # noqa: BLE001 —— 证据路径 fail-open
        return None


class _ContextManager:
    def __init__(self, enter_fn, exit_fn):
        self._enter_fn = enter_fn
        self._exit_fn = exit_fn

    def __enter__(self):
        self._enter_fn()
        return self

    def __exit__(self, *exc):
        self._exit_fn()


def envelope_sink(factory):
    """打开全局 recorder 工厂(上下文管理器;禁止嵌套)。

    factory(*, iteration, namespace, family, rung, pair_index,
            rung_params) -> recorder 或 None。
    """
    global _ACTIVE_SINK_FACTORY
    if _ACTIVE_SINK_FACTORY is not None:
        raise RuntimeError("envelope sink 已打开(禁止嵌套)")

    def _set():
        global _ACTIVE_SINK_FACTORY
        _ACTIVE_SINK_FACTORY = factory

    def _clear():
        global _ACTIVE_SINK_FACTORY
        _ACTIVE_SINK_FACTORY = None

    return _ContextManager(_set, _clear)


def ledger_sink_factory(ledger_path: Path, *, stage_label: str,
                        iteration: str = "r11"):
    """逐 attempt 即时落盘的 sink 工厂(append + fsync;crash 持久)。

    生成的 recorder 继承 EnvelopeRecorder:每个 attempt envelope
    构建后立即追加写入台账文件(单线程顺序追加;文件按 attempt
    打开-写入-关闭,进程异常终止时已完成 attempt 均已持久)。
    """
    ledger_path = Path(ledger_path)
    ledger_path.parent.mkdir(parents=True, exist_ok=True)

    class _LedgerRecorder(EnvelopeRecorder):
        def record(self, event: str, payload: dict[str, Any]) -> None:
            n_before = len(self.attempt_envelopes)
            super().record(event, payload)
            if event != "attempt":
                return
            with open(ledger_path, "a", encoding="utf-8") as fh:
                for env in self.attempt_envelopes[n_before:]:
                    fh.write(json.dumps({
                        "stage": stage_label,
                        "iteration": iteration,
                        "call_digest": self.call_envelope["digest"],
                        "envelope": env,
                    }, ensure_ascii=False, separators=(",", ":")) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    def factory(*, iteration: str, namespace: str, family: str,
                rung: str, pair_index: int,
                rung_params: dict[str, Any]):
        return _LedgerRecorder(
            iteration=iteration, namespace=namespace, family=family,
            rung=rung, pair_index=pair_index, rung_params=rung_params)

    return factory


# ------------------------------------------------ replay 入口(A3)
def replay_call(call: dict[str, Any], *,
                recorder_cls=EnvelopeRecorder) -> dict[str, Any]:
    """按保存的调用身份重建生成调用并逐字段对比(同进程)。

    输入:call envelope(iteration/namespace/family/rung/pair_index/
    rung_params);从 rung_params 原样重建 generate_pair 的参数解析,
    重放全部 attempts,输出 envelope 级逐字段差异。不读取任何 PnL
    或 qualification 结果。
    """
    from rl_curriculum.curriculum261_pairs import (
        pair_acceptance_contract,
    )
    from rl_curriculum.curriculum261_api import (
        generate_pair_with_attempts,
    )
    spec = family_specs()[call["family"]]
    rung_params = dict(call["rung_params"])
    rec = recorder_cls(
        iteration=call["iteration"], namespace=call["namespace"],
        family=call["family"], rung=call["rung"],
        pair_index=int(call["pair_index"]), rung_params=rung_params)
    error: str | None = None
    try:
        generate_pair_with_attempts(
            spec.generator, rung_params,
            namespace=call["namespace"], family=call["family"],
            rung=call["rung"], pair_index=int(call["pair_index"]),
            structural_validator=pair_acceptance_contract(
                call["family"]),
            recorder=rec)
    except PairGenerationError as exc:
        error = str(exc)
    return {
        "format": "cur261-envelope-replay-v1",
        "call_namespace": call["namespace"],
        "call_digest_recomputed": rec.call_envelope["digest"],
        "call_digest_recorded": call.get("digest", ""),
        "attempt_envelopes": rec.attempt_envelopes,
        "generation_error": error,
    }


def compare_envelopes(recorded: dict[str, Any],
                      replayed: dict[str, Any]) -> dict[str, Any]:
    """逐字段对比两个 attempt envelope(身份字段 vs 结果字段分组)。

    身份字段不同 = 生成输入漂移(参数/seed/源码/状态);
    结果字段不同 = 确定性破坏(事件表/哈希/计数/接受状态)。
    """
    identity_keys = (
        "outer_seed", "internal_derived_seed", "base_params",
        "generator_state_digest_pre", "generator_state_digest_post",
        "split", "timeframe",
        "structural_validator_results", "accepted")
    result_keys = ("event_table",)
    drift_identity = {
        k: {"recorded": recorded.get(k), "replayed": replayed.get(k)}
        for k in identity_keys
        if not _json_eq(recorded.get(k), replayed.get(k))}
    drift_results = {
        k: {"recorded": _summary_of(recorded.get(k)),
            "replayed": _summary_of(replayed.get(k))}
        for k in result_keys
        if not _json_eq(recorded.get(k), replayed.get(k))}
    return {
        "format": "cur261-envelope-compare-v1",
        "envelope_digest_recorded": recorded.get("digest"),
        "envelope_digest_replayed": replayed.get("digest"),
        "bitwise_identical": recorded.get("digest") == replayed.get(
            "digest"),
        "identity_drift": drift_identity,
        "result_drift": drift_results,
        "generator_state_changed_in_replay": replayed.get(
            "generator_state_changed"),
        "consistent": (
            recorded.get("digest") == replayed.get("digest")
            or (not drift_identity and not drift_results)),
    }


def _json_eq(a: Any, b: Any) -> bool:
    try:
        return canonical_json(a) == canonical_json(b)
    except TypeError:
        return False


def _summary_of(v: Any) -> Any:
    try:
        s = json.dumps(_canonicalize(v), ensure_ascii=False)
        return s[:300]
    except TypeError:
        return str(v)[:300]


__all__ = [
    "ENVELOPE_FORMAT", "ENVELOPE_DIGEST_PREFIX",
    "CALL_ENVELOPE_DIGEST_PREFIX",
    "canonical_json", "stable_digest", "dataframe_digest",
    "generator_identity", "generator_state_digest",
    "family_spec_identity", "runtime_identity", "event_table_summary",
    "EnvelopeRecorder", "EnvelopeLedger", "read_envelope_ledger",
    "ledger_rows_digest", "write_attempt_envelopes",
    "dump_failure_evidence", "replay_call", "compare_envelopes",
    "active_recorder", "envelope_sink", "ledger_sink_factory",
]
