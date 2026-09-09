#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 真实生成—评估工程切片 + 完整只读语义读回(engineering_only)。

本文件包含两条独立路径:

生成路径(与上轮合同一致,八坐标+p52 负例):
- 八个预声明坐标(namespace=preplan_calibration_main_r17, family=c3_cost,
  rung D0-D3 x pair_index 0/1)先冻结 recipe 再执行,结果保留不替换;
  接受 pair → 真实生产观测 + 冻结 Route C 评估;拒绝 pair → 完整失败
  记录 + evaluator 零启动哨兵;
- --p52-negative:原 rt3 p52 负例真实生成入口重放到 PairGenerationError。
  负例是本切片模式的必需控制:意外接受、证据不全、原因不符或未预期
  异常都会保存事实后使命令非零(rc=4),不得打印成功掩盖负例失败。

读回路径(v4:路径检查—使用一致 + 回执不覆盖 + 必要参数完整性,
纯标准库,不 import 生成/评估栈):
- 以模块内固定的授权声明(EXPECTED_SLICE)为依据,不靠输入自证完整性;
- recipe→索引→详情→attempt→evaluation 逐层身份绑定:必需负例、请求
  顺序、坐标、namespace、A/B 评估身份、attempt 条数/编号/接受语义、
  状态与 integrity 一致性全部进入统一 verdict;任何必需检查缺失/false/
  不可解析/矛盾 → FAIL 且 CLI 非零;
- 身份绑定(沿用 v3,按 cur261_generation_envelope 原合同):
  accepted 的 A/B 输出哈希四处闭合(selected envelope.event_table ==
  attempt_log.output_episode_hashes == 顶层 episode_hashes ==
  evaluation.episodes[].episode_hash);每条 attempt envelope 的内部
  digest 按 canonical 合同复算(_ENVELOPE_NON_IDENTITY_KEYS 只剔顶层
  digest/runtime,不递归);p52 负例五条 envelope 与固定原件身份体逐条
  canonical 对照(两侧各自先复算 digest);envelope.generator 与 recipe
  generator_identity 对照;
- 必要参数完整性(v4 新增):六个必要课程键(REQUIRED_CURRICULUM_KEYS,
  固定合同)先查 recipe.rung_params[rung] 完整性,再要求每条实际
  envelope 的 base_params.A/B 键存在且值与对应 rung 一致;缺键与
  值不一致分别记录,合并入统一 verdict;合法附加键不判;
- 只读与写隔离(沿用 v3 快照时序):读回前后对源目录做(集合,字节
  哈希,大小,mtime)快照,最终快照在读回操作与回执写入全部完成后
  拍摄;
- 路径检查与写入一致(v4 新增):回执目标按真实文件系统语义逐组件
  解析(不做"链接后再 .."的词法折叠,alias/.. 与 OS 打开同一位置),
  准入返回确认后的唯一写入目标,后续创建目录/临时件/发布/存在性
  检查与回执输出全部消费该确认结果 —— 检查目标与实际使用目标是
  同一对象;与只读输入重叠(真实父子关系判定)、经链接解析落入源内
  的新嵌套目标一律拒绝;
- 回执不覆盖(v4 新增):本次调用开始前已存在的最终目标一律拒绝
  (任何形态:有效/空/非 JSON 文件、目录、链接条目含悬空);回执
  以"只创建不替换"落地(唯一临时名 open 'x' + os.link 原子创建),
  最终检查后需要改判时仅允许更新本次独占创建的候选(文件身份
  所有权核对通过才替换);不跟随预置临时件链接,失败只清理本次
  创建的对象;
- --p52-envelope 必需:负例拒绝词表与原记录逐条对照(固定来源核对,
  不只信计数字段或保存的布尔)。

授权边界(不变):仅限本清单八坐标与 p52 负例确定性重放;不做
namespace/seed 搜索、不追加坐标、不替换失败请求、不依据 PnL 选择
样本。评估走原始生产观测路径,未验证训练侧归一化 fit(如实声明)。

用法:
  生成: r17_c3_engineering_slice.py --out-dir <dir> [--p52-negative <env.json>]
  读回: r17_c3_engineering_slice.py --readback <dir> \
            --p52-envelope <orig_env.json> --report <receipt.json>

rc 语义:
  0   = 生成完整 / 读回 PASS
  1   = 读回 FAIL(回执含逐项 problem)
  2   = 用法错误/输出目录非空/回执目标写前准入被拒(含本次调用前
        已存在的显式目标;零源写入)
  4   = p52 负例意外接受或证据缺陷(事实先落盘)
  5   = 读回内部异常
  6   = 读回回执写失败(准入已过,落盘仍失败)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

_HERE = Path(__file__).resolve()
#: runner 目录(诊断 recorder 复用)与发布树 src 提示;不在此 import
#: 任何业务包——读回路径必须纯标准库可执行。
_RUNNER_DIR = _HERE.parent
_SRC_HINT = _HERE.parent.parent / "src"
if str(_RUNNER_DIR) not in sys.path:
    sys.path.insert(0, str(_RUNNER_DIR))

SLICE_NAMESPACE = "preplan_calibration_main_r17"
SLICE_FAMILY = "c3_cost"
SLICE_RUNGS = ("D0", "D1", "D2", "D3")
SLICE_PAIR_INDICES = (0, 1)
#: 原 p52 负例坐标(rt3 namespace;只读重放,不改任何旧 run)
P52_NEGATIVE = {"namespace": "rt3_calibration_main_r17",
                "family": "c3_cost", "rung": "D0", "pair_index": 52}

#: 读回的固定授权声明(本次切片模式的合同;不由输入自证)。recipe 与
#: 索引都要与它精确匹配——同时改 recipe 不能授权第九个坐标。
EXPECTED_REQUESTS = tuple(
    (rung, idx) for rung in SLICE_RUNGS for idx in SLICE_PAIR_INDICES)
EXPECTED_MAX_ATTEMPTS = 5
#: 详情文件名必须逐字等于 {rung}_p{idx}.json(防逃逸/跨坐标引用)
_DETAIL_NAME_RE = "{rung}_p{idx}.json"

#: 评估 episode 必须提供的策略结果键(有限数值)
POLICY_KEYS = ("always_flat", "always_long", "c3_cost_ignorant",
               "reference", "oracle")

#: envelope 内部 digest 合同常量(与生产模块
#: curriculum261_generation_envelope 的权威实现逐字对应;reader 侧
#: 只对**已落盘纯 JSON** 做复算,权威语义由独立测试进程对照锁死)。
ENVELOPE_DIGEST_PREFIX = "r11env-"
CALL_ENVELOPE_DIGEST_PREFIX = "r11call-"
#: digest 计算体只剔除 envelope 顶层的 digest/runtime(非身份字段),
#: 不递归删除内层同名字段。
_ENVELOPE_NON_IDENTITY_KEYS = ("digest", "runtime")

# 必要课程键(固定合同的定位,非双方键交集):每条实际 envelope 的
# base_params.A/B 必须包含全部键且与 recipe.rung_params[rung] 一致;
# 缺一个键即读回 FAIL。合法展开的附加键(pair_variant/episode_bars/
# initial_price/cur261_rung 等)不在此列,继续允许。
REQUIRED_CURRICULUM_KEYS = ("alpha_bps", "payoff_bars", "vol_bps",
                            "cue_rate", "mixture", "distractor_rate")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


def _atomic_write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, path)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _ensure_src_path() -> None:
    """生成分支专用:保证 rl_curriculum 可 import(部署树已有路径或
    发布树 src 回退)。读回路径不调用本函数。"""
    try:
        import rl_curriculum.curriculum261_c3  # noqa: F401
    except ImportError:
        p = str(_SRC_HINT)
        if p not in sys.path:
            sys.path.insert(0, p)


class EvalSentinel:
    """evaluator 启动计数器(真实调用计数,证明负例零启动)。"""

    def __init__(self) -> None:
        self.invocations = 0
        self.evaluated_coordinates: list[str] = []

    def evaluate(self, records, family: str, rung_params: dict,
                 thresholds: dict) -> dict:
        from rl_curriculum.curriculum261_qualification import (
            evaluate_pair_corpus,
        )
        self.invocations += 1
        self.evaluated_coordinates.append(
            f"{records[0].rung}/p{records[0].pair_index}")
        return evaluate_pair_corpus(
            records, family, rung_params, thresholds)


def freeze_recipe(out_dir: Path) -> dict:
    """读取任何新生成结果之前,冻结全部八请求与参数摘要(§5.1)。"""
    _ensure_src_path()
    from rl_curriculum.curriculum261_generation_envelope import (
        generator_identity,
    )
    from rl_curriculum.curriculum261_pairs import family_specs
    spec = family_specs()[SLICE_FAMILY]
    requests = [{"namespace": SLICE_NAMESPACE, "family": SLICE_FAMILY,
                 "rung": rung, "pair_index": idx}
                for rung in SLICE_RUNGS
                for idx in SLICE_PAIR_INDICES]
    recipe = {
        "format": "r17-c3-engineering-slice-recipe-v1",
        "engineering_only": True,
        "purpose": ("engineering generation-to-evaluation slice; NOT a "
                    "formal workflow, NOT a calibration corpus, NOT "
                    "qualification evidence"),
        "namespace": SLICE_NAMESPACE,
        "family": SLICE_FAMILY,
        "requests": requests,
        "n_requests": len(requests),
        "max_attempts": 5,
        "attempts_policy": "existing first_pass, max 5 (API unchanged)",
        "rung_params": {r: dict(spec.rung_params[r])
                        for r in SLICE_RUNGS},
        "reference_defaults": dict(spec.reference_defaults),
        "generator_identity": generator_identity(spec.generator),
        "negative_control": dict(P52_NEGATIVE),
        "frozen_utc": utc_now(),
    }
    _atomic_write(out_dir / "recipe.json", recipe)
    return recipe


def run_slice(out_dir: Path) -> dict:
    """执行八个预声明坐标:生成→(接受)真实评估/(拒绝)完整失败记录。"""
    _ensure_src_path()
    from r17_c3_p52_diagnosis import make_checked_recorder_cls
    from rl_curriculum.curriculum261_api import PairGenerationError
    from rl_curriculum.curriculum261_generation_envelope import (
        envelope_sink,
    )
    from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
    recipe = freeze_recipe(out_dir)
    spec = family_specs()[SLICE_FAMILY]
    sentinel = EvalSentinel()
    results_path = out_dir / "slice_results.jsonl"
    assert not results_path.exists(), (
        "slice_results.jsonl 已存在:不覆盖旧结果(不重开旧 run)")
    holders: list = []

    def factory(**kw):
        rec = make_checked_recorder_cls()(**kw)
        holders.append(rec)
        return rec

    summary_rows: list[dict] = []
    with envelope_sink(factory):
        for req in recipe["requests"]:
            rung, idx = req["rung"], req["pair_index"]
            holders.clear()
            coord = f"{rung}/p{idx}"
            detail_path = out_dir / "pairs" / f"{rung}_p{idx}.json"
            assert not detail_path.exists(), f"{detail_path} 已存在"
            row: dict = {"coord": coord, **req}
            try:
                record = generate_pair(
                    SLICE_FAMILY, rung, idx, namespace=SLICE_NAMESPACE)
            except PairGenerationError as exc:
                rec = holders[-1] if holders else None
                envs = list(getattr(exc, "attempt_envelopes", None) or [])
                if not envs and rec is not None:
                    envs = list(rec.attempt_envelopes)
                detail = {
                    "format": "r17-c3-engineering-slice-pair-v1",
                    "engineering_only": True,
                    "status": "rejected",
                    "coord": coord,
                    "generation_error": str(exc)[:2000],
                    "selected_attempt": None,
                    "attempt_log": exc.attempt_log.canonical(),
                    "n_attempt_envelopes": len(envs),
                    "attempt_envelopes": envs,
                    "recorder_errors": list(rec.record_errors)
                    if rec is not None else ["recorder_not_attached"],
                    "eval_started": False,
                    "evaluator_invocations_total": 0,
                    "downstream_sentinel": {
                        "evaluator_started": False,
                        "fake_empty_episode": False,
                        "cached_output_used": False,
                        "note": "拒绝 pair 不进入评估;evaluator 计数"
                                "为进程内真实调用计数,非 mock"},
                }
                _atomic_write(detail_path, detail)
                row.update({"status": "rejected",
                            "n_attempt_envelopes": len(envs),
                            "selected_attempt": None,
                            "detail": str(detail_path.name),
                            "detail_sha256": _sha256_file(detail_path)})
                summary_rows.append(row)
                with results_path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                    fh.flush()
                    os.fsync(fh.fileno())
                continue
            # 接受:真实生产观测 + 冻结 Route C 评估(calibration 先例:
            # rung_params 用注册表原值,thresholds 用 reference_defaults)
            rec = holders[-1] if holders else None
            thresholds = dict(spec.reference_defaults)
            rung_params = dict(spec.rung_params[rung])
            ev = sentinel.evaluate([record], SLICE_FAMILY,
                                   rung_params, thresholds)
            detail = {
                "format": "r17-c3-engineering-slice-pair-v1",
                "engineering_only": True,
                "status": "accepted",
                "coord": coord,
                "pair_record": record.canonical(),
                "episode_hashes": dict(record.attempt_log.episode_hashes),
                "integrity": record.integrity,
                "integrity_ok": record.integrity_ok,
                "n_attempt_envelopes": len(rec.attempt_envelopes)
                if rec is not None else 0,
                "attempt_envelopes": list(rec.attempt_envelopes)
                if rec is not None else [],
                "recorder_errors": list(rec.record_errors)
                if rec is not None else ["recorder_not_attached"],
                "eval_started": True,
                "evaluation": ev,
                "evaluation_note": (
                    "run_policy_episode over production observation "
                    "schema + frozen Route C eval config; raw production "
                    "observation path does NOT validate training-side "
                    "normalization fit"),
            }
            _atomic_write(detail_path, detail)
            row.update({"status": "accepted",
                        "selected_attempt":
                            record.attempt_log.selected_attempt,
                        "integrity_ok": record.integrity_ok,
                        "detail": str(detail_path.name),
                        "detail_sha256": _sha256_file(detail_path)})
            summary_rows.append(row)
            with results_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
                os.fsync(fh.fileno())

    slice_summary = {
        "format": "r17-c3-engineering-slice-summary-v1",
        "engineering_only": True,
        "n_requests": recipe["n_requests"],
        "n_accepted": sum(1 for r in summary_rows
                          if r["status"] == "accepted"),
        "n_rejected": sum(1 for r in summary_rows
                          if r["status"] == "rejected"),
        "evaluator_invocations_total": sentinel.invocations,
        "evaluated_coordinates": sentinel.evaluated_coordinates,
        "replaced_or_dropped": False,
        "finished_utc": utc_now(),
    }
    _atomic_write(out_dir / "slice_summary.json", slice_summary)
    return slice_summary


def run_p52_negative(out_dir: Path, envelope_path: Path) -> dict:
    """原 p52 负例:真实生成入口→PairGenerationError→evaluator 零启动。

    只读重放固定坐标(rt3 namespace p52),不读写任何旧 run 目录;
    envelope_path 仅用于交叉核对拒绝词表与原记录一致。意外接受也是
    合法落盘的事实,但调用方(main/测试)必须以非零结束。
    """
    _ensure_src_path()
    from rl_curriculum.curriculum261_api import (
        PairGenerationError, generate_pair_with_attempts,
    )
    from rl_curriculum.curriculum261_pairs import (
        family_specs, pair_acceptance_contract,
    )
    from r17_c3_p52_diagnosis import make_checked_recorder_cls
    spec = family_specs()[SLICE_FAMILY]
    orig = json.loads(Path(envelope_path).read_text(encoding="utf-8"))
    call = orig["call_envelope"]
    assert (call["namespace"] == P52_NEGATIVE["namespace"]
            and call["pair_index"] == P52_NEGATIVE["pair_index"]), (
        "负例坐标与原记录不一致")
    rec = make_checked_recorder_cls()(
        iteration=call["iteration"], namespace=call["namespace"],
        family=call["family"], rung=call["rung"],
        pair_index=int(call["pair_index"]),
        rung_params=dict(call["rung_params"]))
    sentinel = EvalSentinel()
    error: str | None = None
    selected: int | None = None
    unexpected: dict | None = None
    try:
        generate_pair_with_attempts(
            spec.generator, dict(call["rung_params"]),
            namespace=call["namespace"], family=call["family"],
            rung=call["rung"], pair_index=int(call["pair_index"]),
            structural_validator=pair_acceptance_contract(
                call["family"]), recorder=rec)
        accepted = True
    except PairGenerationError as exc:
        accepted = False
        error = str(exc)
        selected = exc.attempt_log.selected_attempt
    except Exception as exc:  # noqa: BLE001 —— 事实先落盘,调用方定 rc
        accepted = False
        unexpected = {"error_type": type(exc).__name__,
                      "error": str(exc)[:500]}
        error = f"unexpected:{type(exc).__name__}:{str(exc)[:200]}"

    orig_reasons = [a.get("rejection_reasons")
                    for a in orig["attempt_envelopes"]]
    new_reasons = [e.get("rejection_reasons")
                   for e in rec.attempt_envelopes]
    detail_path = out_dir / "p52_negative.json"
    assert not detail_path.exists(), "p52_negative.json 已存在"
    report = {
        "format": "r17-c3-engineering-slice-p52-negative-v1",
        "engineering_only": True,
        "coordinates": dict(P52_NEGATIVE),
        "accepted": accepted,
        "generation_error": error,
        "selected_attempt": selected,
        "n_attempt_envelopes": len(rec.attempt_envelopes),
        "attempt_envelopes": rec.attempt_envelopes,
        "recorder_errors": rec.record_errors,
        "rejection_reasons_match_original": orig_reasons == new_reasons,
        "downstream_sentinel": {
            "evaluator_started": sentinel.invocations > 0,
            "evaluator_invocations": sentinel.invocations,
            "fake_empty_episode": False,
            "cached_output_used": False,
            "note": "负例经真实生成入口保持失败;评估器零启动为进程"
                    "内真实计数;输出文件为全新写入(无缓存当本次输出)"},
        "written_utc": utc_now(),
    }
    if unexpected is not None:
        report["unexpected_exception"] = unexpected
    _atomic_write(detail_path, report)
    return report


def p52_negative_evidence_ok(neg: dict) -> tuple[bool, list[str]]:
    """负例证据完备性判定(生成命令出口用;事实已由调用方落盘)。"""
    problems: list[str] = []
    if neg.get("accepted") is not False:
        problems.append("p52 负例意外接受(原合同应五连拒)")
    if neg.get("selected_attempt") is not None:
        problems.append("p52 负例 selected_attempt 非空")
    if neg.get("n_attempt_envelopes") != EXPECTED_MAX_ATTEMPTS:
        problems.append(
            f"p52 负例 envelope 条数 {neg.get('n_attempt_envelopes')}"
            f" != {EXPECTED_MAX_ATTEMPTS}")
    idx = [e.get("attempt_index") for e in neg.get("attempt_envelopes", [])]
    if sorted(x for x in idx if x is not None) != list(
            range(EXPECTED_MAX_ATTEMPTS)):
        problems.append(f"p52 负例 attempt 编号不齐全: {idx}")
    if neg.get("recorder_errors"):
        problems.append(f"p52 负例 recorder 错误: {neg['recorder_errors']}")
    if neg.get("rejection_reasons_match_original") is not True:
        problems.append("p52 负例拒绝词表与原记录不一致")
    ds = neg.get("downstream_sentinel", {})
    if ds.get("evaluator_started") is not False or ds.get(
            "evaluator_invocations") != 0:
        problems.append("p52 负例 evaluator 非零启动")
    return (not problems), problems


# ================================================= 读回路径(v2,纯标准库)
def _snapshot(root: Path) -> dict[str, tuple]:
    """源目录只读快照:相对路径→(sha256, size, mtime_ns)。"""
    snap: dict[str, tuple] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            st = p.stat()
            snap[str(p.relative_to(root)).replace(os.sep, "/")] = (
                _sha256_file(p), st.st_size, st.st_mtime_ns)
    return snap


def _finite_number(v) -> bool:
    return (isinstance(v, (int, float)) and not isinstance(v, bool)
            and math.isfinite(v))


# ---------------------------------------- canonical digest 薄适配(只读)
def _canon_float(v: float):
    """权威 _canonicalize 的 float 分支:NaN/Inf 走 __float__ 标记。"""
    if math.isnan(v) or math.isinf(v):
        return {"__float__": repr(float(v))}
    return float(v)


def _canonicalize_json_types(obj):
    """权威 _canonicalize 的已落盘 JSON 子集(纯标准库)。

    权威实现(curriculum261_generation_envelope._canonicalize)额外覆盖
    numpy/pandas/set/Path/bytes 等运行时类型;envelope 落盘为 JSON 后
    只剩 None/bool/int/str/float/dict/list,本函数即其语义子集。
    set/ndarray 等若意外出现(伪造输入)按 TypeError 拒绝,不静默近似。
    """
    if obj is None or isinstance(obj, (bool, int, str)):
        return obj
    if isinstance(obj, float):
        return _canon_float(obj)
    if isinstance(obj, dict):
        return {str(k): _canonicalize_json_types(v)
                for k, v in obj.items()}
    if isinstance(obj, list):
        return [_canonicalize_json_types(v) for v in obj]
    raise TypeError(
        f"canonical 薄适配不接受类型 {type(obj).__name__!r}"
        f"(值截断: {str(obj)[:80]!r})")


def _canonical_json_text(obj) -> str:
    """权威 canonical_json 的已落盘 JSON 形态(sort_keys+紧凑分隔符+
    ensure_ascii=False;与 CPython json 的 float 最短往返表示一致)。"""
    return json.dumps(_canonicalize_json_types(obj), sort_keys=True,
                      separators=(",", ":"), ensure_ascii=False)


def _digest_body(env: dict) -> dict:
    """digest 计算体:剔除顶层非身份键(digest/runtime),不递归。"""
    return {k: v for k, v in env.items()
            if k not in _ENVELOPE_NON_IDENTITY_KEYS}


def _recompute_envelope_digest(env) -> str:
    """按原合同复算 envelope/call digest(与权威 stable_digest 同式)。"""
    return ENVELOPE_DIGEST_PREFIX + hashlib.sha256(
        _canonical_json_text(_digest_body(env)).encode("utf-8")).hexdigest()


def _recompute_call_digest(env) -> str:
    return CALL_ENVELOPE_DIGEST_PREFIX + hashlib.sha256(
        _canonical_json_text(_digest_body(env)).encode("utf-8")).hexdigest()


def _identity_body_text(env) -> str | None:
    """envelope 身份体的 canonical 文本(异常时 None,调用方记 problem)。"""
    try:
        return _canonical_json_text(_digest_body(env))
    except (TypeError, ValueError) as exc:
        return f"<canonical-error:{type(exc).__name__}:{exc}>"


# ---------------------------------------- 回执写入隔离(WP2,写前准入)
class ReportTargetRejected(Exception):
    """回执/临时件目标与只读输入重叠(准入拒绝;零源写入)。"""


class ReceiptWriteError(Exception):
    """回执目标已通过准入但落盘失败(不输出完成 PASS)。"""


def _resolve_target_strict(p: Path) -> Path:
    """按真实文件系统语义解析目标(检查与写入共用的唯一语义)。

    - 相对路径以进程 cwd 一次采样为基准,工作目录差异不改变解析结果
      所指的实际位置;
    - realpath 逐组件解析已存在部分的符号链接,不对"链接后再 .."
      做词法折叠 —— alias/.. 与 OS 打开该路径时落在同一位置
      (abspath/normpath 会先消掉 alias/.. 得出另一个目录,禁止);
    - 不存在部分原样拼接在已解析祖先之后;
    - 解析失败(权限/循环等 OSError)按歧义拒绝,不静默改写到
      另一个位置后返回成功。
    """
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    try:
        return Path(os.path.realpath(p, strict=False))
    except OSError as exc:
        raise ReportTargetRejected(
            f"目标路径无法可靠解析(拒绝而非改写): {p} "
            f"({type(exc).__name__}: {exc})") from exc


def _assert_report_target_safe(report_path: Path,
                               protect_roots: list) -> Path:
    """写前准入:返回确认后的回执最终路径(本次调用的唯一写入目标)。

    后续创建目录/打开临时件/发布/存在性检查与回执输出全部消费该
    确认结果 —— 检查目标与实际使用目标是同一个对象。规则:

    1. 目标、目标父目录(临时件所在)与全部保护根按真实文件系统
       语义解析(见 _resolve_target_strict);确认目标或其父目录
       落在任何保护根之内即拒绝(真实父子关系,非字符串前缀;
       同名前缀兄弟目录不受影响);
    2. 本次调用开始前已存在的最终目标一律拒绝(任何形态:有效
       JSON/空文件/普通文件/目录/链接条目;lexists 判定)——
       已有显式目标不覆盖,新结果另存;
    3. 词法最终组件是符号链接条目(即使其目标不存在/在保护外)
       拒绝,不跟随写入;
    4. 固定名临时件链接指向只读输入时拒绝(fail closed)。

    无法安全确定时一律拒绝。本函数在任何创建目录/打开临时件/写入
    之前调用;目标可以不存在,但其可确认的祖先参与第 1 条判定
    (经链接解析落在源内的新嵌套目标同样在此被拒)。
    """
    target = _resolve_target_strict(report_path)
    target_dir = _resolve_target_strict(report_path.parent)
    for prot in protect_roots:
        prot_r = _resolve_target_strict(Path(prot))
        for t, label in ((target, "report"), (target_dir, "report_dir")):
            if t == prot_r or prot_r in t.parents:
                raise ReportTargetRejected(
                    f"{label} 目标位于只读输入之内: {t} ⊆ {prot_r}")
    # 本次调用前已存在的最终目标:一律拒绝,不覆盖已有结果
    if os.path.lexists(target):
        raise ReportTargetRejected(
            f"回执最终目标本次调用前已存在(已有显式目标不覆盖,"
            f"新结果请另存): {target}")
    # 词法最终组件是链接条目(含悬空):不跟随写入
    final_entry = (target.parent / report_path.name
                   if report_path.name else target)
    if final_entry != target and os.path.islink(final_entry):
        raise ReportTargetRejected(
            f"回执最终目标是符号链接条目(不跟随写入,悬空同样"
            f"拒绝): {final_entry}")
    # 预置的固定名临时件链接:安全写从不使用固定 .tmp 名,但仍明确
    # 拒绝"目标目录内已存在指向输入的固定名链接"(fail closed)。
    fixed_tmp = report_path.with_suffix(report_path.suffix + ".tmp")
    if fixed_tmp.is_symlink():
        link_real = Path(os.path.realpath(fixed_tmp))
        for prot in protect_roots:
            prot_r = _resolve_target_strict(Path(prot))
            if link_real == prot_r or prot_r in link_real.parents:
                raise ReportTargetRejected(
                    f"固定名临时件是指向只读输入的链接: "
                    f"{fixed_tmp} -> {link_real}")
    return target


def _atomic_write_receipt(path: Path, payload: dict,
                          owned_id: tuple | None = None) -> tuple:
    """回执专用安全写:只创建不替换;或仅更新本次独占的未完成候选。

    path 必须是 _assert_report_target_safe 返回的确认目标(所有
    mkdir/临时件/发布都作用在确认位置)。

    - owned_id=None(首次发布):在目标父目录写唯一临时名(open 'x',
      不跟随预置链接),以 os.link(tmp, path) 原子创建最终目标 ——
      目标已存在时 FileExistsError,绝不替换既有文件(与
      os.replace 的本质区别);发布后删除临时件,返回新目标的
      (st_dev, st_ino) 供本次调用后续更新做所有权核对。
    - owned_id=(dev, ino)(更新本次未完成候选):仅当目标当前文件
      身份与 owned_id 一致才 os.replace(tmp, path);不一致(目标被
      外部更换)抛 ReceiptWriteError,不覆盖 —— 不把"先检查过目标
      不存在"当作后续无条件覆盖任意新出现目标的保证。
    - 失败清理只删除本次确实创建并拥有的临时件,不触碰任何其他
      对象;不回退写入任何未准入位置。
    """
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")
        tmp = path.with_name(f".{path.name}.{os.getpid()}.{stamp}.tmp")
        try:
            with open(tmp, "x", encoding="utf-8") as fh:
                fh.write(json.dumps(payload, ensure_ascii=False, indent=1))
                fh.flush()
                os.fsync(fh.fileno())
            if owned_id is None:
                try:
                    os.link(tmp, path)
                except FileExistsError as exc:
                    raise ReceiptWriteError(
                        f"回执最终目标已存在(只创建不替换): {path}"
                    ) from exc
            else:
                st = os.stat(path)
                if (st.st_dev, st.st_ino) != tuple(owned_id):
                    raise ReceiptWriteError(
                        f"回执目标文件身份与本次候选不符(不覆盖): "
                        f"{path}")
                os.replace(tmp, path)
        finally:
            try:
                os.unlink(tmp)
            except FileNotFoundError:
                pass
        st = os.stat(path)
        return (st.st_dev, st.st_ino)
    except ReceiptWriteError:
        raise
    except OSError as exc:
        raise ReceiptWriteError(
            f"回执写失败: {type(exc).__name__}: {exc} "
            f"(目标: {path})") from exc


class _Problems:
    """读回问题收集器:同一必需条件只在本列表里判定一次。"""

    def __init__(self) -> None:
        self.items: list[dict] = []

    def add(self, check: str, where: str, expected, actual) -> None:
        self.items.append({"check": check, "where": where,
                           "expected": expected, "actual": actual})

    def __len__(self) -> int:
        return len(self.items)


def _load_json(problems: _Problems, path: Path, label: str):
    if not path.is_file():
        problems.add("file_present", label, "file exists", "missing")
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError, OSError) as exc:
        problems.add("json_parseable", label, "valid JSON", f"{type(exc).__name__}:{exc}"[:200])
        return None


def readback(out_dir: Path, report_path: Path,
             p52_envelope_path: Path,
             protect_roots: list | None = None) -> dict:
    """完整只读语义读回(不执行任何生成/评估;不写源目录)。

    结构:写前准入 → 加载与核对 → 收集问题 → 统一判定 → 独立回执
    → 最终只读快照。所有必需语义进入同一 verdict;回执写 report_path,
    该目标(含临时件)在写入前与全部只读输入(out_dir 树、p52 依据、
    额外 protect_roots)做路径准入,重叠即抛 ReportTargetRejected
    (零源写入)。protect_roots 供组包/冷读声明更大的只读 payload 根;
    缺省保护集为 out_dir 树 + p52_envelope_path 本身。
    """
    protect = [Path(out_dir), Path(p52_envelope_path)] + [
        Path(p) for p in (protect_roots or [])]
    # 写前准入:先于任何为回执创建目录/打开临时件/写入的操作;返回
    # 确认后的唯一写入目标(本次调用独占候选的所有权锚点),后续
    # 创建目录/临时件/发布/存在性检查与回执输出全部消费该确认
    # 结果 —— 检查目标与实际使用目标是同一个对象。
    confirmed = _assert_report_target_safe(report_path, protect)

    problems = _Problems()
    checks: dict = {"source_dir": str(out_dir)}
    before = _snapshot(out_dir) if out_dir.is_dir() else {}
    if not out_dir.is_dir():
        problems.add("file_present", "source_dir", "directory exists",
                     "missing")

    recipe = _load_json(problems, out_dir / "recipe.json", "recipe.json")
    summary = _load_json(problems, out_dir / "slice_summary.json",
                         "slice_summary.json")

    # L1 recipe 与固定授权声明
    if recipe is not None:
        got_reqs = recipe.get("requests")
        if not isinstance(got_reqs, list):
            problems.add("recipe_requests", "recipe.requests", "list",
                         type(got_reqs).__name__)
        else:
            got_coords = [(q.get("rung"), q.get("pair_index"))
                          if isinstance(q, dict) else (None, None)
                          for q in got_reqs]
            if got_coords != [tuple(x) for x in EXPECTED_REQUESTS]:
                problems.add(
                    "recipe_requests_match_authorization",
                    "recipe.requests",
                    [list(x) for x in EXPECTED_REQUESTS], got_coords)
            wrong_id = [q for q in got_reqs if isinstance(q, dict) and (
                q.get("namespace") != SLICE_NAMESPACE
                or q.get("family") != SLICE_FAMILY)]
            if wrong_id:
                problems.add("recipe_request_identity",
                             "recipe.requests[].namespace/family",
                             {"namespace": SLICE_NAMESPACE,
                              "family": SLICE_FAMILY},
                             wrong_id[0])
        if recipe.get("n_requests") != len(EXPECTED_REQUESTS):
            problems.add("recipe_n_requests", "recipe.n_requests",
                         len(EXPECTED_REQUESTS),
                         recipe.get("n_requests"))
        if recipe.get("max_attempts") != EXPECTED_MAX_ATTEMPTS:
            problems.add("recipe_max_attempts", "recipe.max_attempts",
                         EXPECTED_MAX_ATTEMPTS,
                         recipe.get("max_attempts"))
        if recipe.get("namespace") != SLICE_NAMESPACE:
            problems.add("recipe_namespace", "recipe.namespace",
                         SLICE_NAMESPACE, recipe.get("namespace"))
        if recipe.get("family") != SLICE_FAMILY:
            problems.add("recipe_family", "recipe.family",
                         SLICE_FAMILY, recipe.get("family"))
        if recipe.get("engineering_only") is not True:
            problems.add("recipe_engineering_only",
                         "recipe.engineering_only", True,
                         recipe.get("engineering_only"))
        if recipe.get("negative_control") != P52_NEGATIVE:
            # 本次模式:p52 负例是必需项,删除声明不能降级为"未请求"
            problems.add("recipe_negative_control_required",
                         "recipe.negative_control", P52_NEGATIVE,
                         recipe.get("negative_control"))
        for key in ("rung_params", "reference_defaults",
                    "generator_identity"):
            if not recipe.get(key):
                problems.add("recipe_param_identity_present",
                             f"recipe.{key}", "non-empty", "missing/empty")
        if isinstance(recipe.get("rung_params"), dict):
            missing = [r for r in SLICE_RUNGS
                       if not recipe["rung_params"].get(r)]
            if missing:
                problems.add("recipe_rung_params_complete",
                             "recipe.rung_params", list(SLICE_RUNGS),
                             f"missing {missing}")

    # L2 索引(slice_results.jsonl)
    rows: list[dict] = []
    results_path = out_dir / "slice_results.jsonl"
    if not results_path.is_file():
        problems.add("file_present", "slice_results.jsonl",
                     "file exists", "missing")
    else:
        try:
            for i, line in enumerate(results_path.read_text(
                    encoding="utf-8").splitlines()):
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError as exc:
                    problems.add("index_row_parseable",
                                 f"slice_results.jsonl:line{i + 1}",
                                 "valid JSON", f"{exc}"[:120])
                    continue
                if not isinstance(row, dict):
                    problems.add("index_row_is_object",
                                 f"slice_results.jsonl:line{i + 1}",
                                 "object", type(row).__name__)
                    continue
                row["_line"] = i + 1
                rows.append(row)
        except UnicodeDecodeError as exc:
            problems.add("index_decode", "slice_results.jsonl", "utf-8",
                         f"{exc}"[:120])
    checks["index_rows_n"] = len(rows)

    # L3 索引与声明(顺序精确;不排序、不只比集合)
    got_seq = [(r.get("rung"), r.get("pair_index")) for r in rows]
    want_seq = [tuple(x) for x in EXPECTED_REQUESTS]
    if got_seq != want_seq:
        problems.add("index_order_exact", "slice_results.jsonl",
                     [list(x) for x in want_seq],
                     [list(x) if isinstance(x, tuple) else x
                      for x in got_seq])
    seen: set = set()
    for r in rows:
        key = (r.get("rung"), r.get("pair_index"))
        if key in seen:
            problems.add("index_no_duplicate", f"row@line{r.get('_line')}",
                         "unique coordinates", f"duplicate {key}")
        seen.add(key)
        if r.get("namespace") != SLICE_NAMESPACE or r.get(
                "family") != SLICE_FAMILY:
            problems.add("index_row_identity",
                         f"row@line{r.get('_line')}",
                         {"namespace": SLICE_NAMESPACE,
                          "family": SLICE_FAMILY},
                         {"namespace": r.get("namespace"),
                          "family": r.get("family")})
        expect_coord = (f"{r.get('rung')}/p{r.get('pair_index')}"
                        if r.get("rung") is not None
                        and r.get("pair_index") is not None else None)
        if r.get("coord") != expect_coord:
            problems.add("index_coord_field",
                         f"row@line{r.get('_line')}", expect_coord,
                         r.get("coord"))
        if r.get("status") not in ("accepted", "rejected"):
            problems.add("index_status_known",
                         f"row@line{r.get('_line')}",
                         "accepted|rejected", r.get("status"))

    # L4-L7 逐行详情核对
    accepted_coords: list[str] = []
    rejected_coords: list[str] = []
    detail_files_seen: dict[str, str] = {}
    for r in rows:
        where = f"{r.get('coord')}@line{r.get('_line')}"
        rung, idx = r.get("rung"), r.get("pair_index")
        status = r.get("status")
        # 详情引用:路径安全 + 存在 + 哈希
        detail_name = r.get("detail")
        if not isinstance(detail_name, str) or not detail_name or (
                os.sep in detail_name or "/" in detail_name
                or ".." in detail_name):
            problems.add("detail_ref_safe", where,
                         "plain filename under pairs/", detail_name)
            continue
        expected_name = _DETAIL_NAME_RE.format(rung=rung, idx=idx)
        dpath = out_dir / "pairs" / detail_name
        present = dpath.is_file()
        digest_ok = (present and _sha256_file(dpath)
                     == r.get("detail_sha256"))
        checks.setdefault("detail_digest", {})[where] = bool(digest_ok)
        if not present:
            problems.add("detail_present", where,
                         f"pairs/{detail_name}", "missing")
            continue
        if not digest_ok:
            problems.add("detail_digest", where,
                         r.get("detail_sha256"),
                         "recomputed mismatch")
        if detail_name != expected_name:
            # 跨坐标引用(即使哈希正确):身份关系失败并指明两个坐标
            problems.add("detail_identity_cross_coord", where,
                         f"pairs/{expected_name}", f"pairs/{detail_name}")
        if detail_name in detail_files_seen:
            problems.add("detail_file_reused", where,
                         "one detail file per request",
                         f"also used by {detail_files_seen[detail_name]}")
        detail_files_seen[detail_name] = where
        doc = _load_json(problems, dpath, f"{where} detail")
        if doc is None:
            continue
        # 详情身份(与索引行/固定声明)
        for field, want in (("status", status),
                            ("coord", r.get("coord")),
                            ("engineering_only", True)):
            if doc.get(field) != want:
                problems.add("detail_field_identity",
                             f"{where}:{field}", want, doc.get(field))
        pr = doc.get("pair_record")
        if status == "accepted" and not isinstance(pr, dict):
            problems.add("detail_pair_record", where, "object",
                         type(pr).__name__)
        if isinstance(pr, dict):
            for field, want in (("family", SLICE_FAMILY),
                                ("rung", rung),
                                ("pair_index", idx)):
                if pr.get(field) != want:
                    problems.add(
                        "detail_pair_record_identity",
                        f"{where}:pair_record.{field}", want,
                        pr.get(field))
        # envelope 身份与 attempt 完备性(实际条目,不是计数字段)
        envs = doc.get("attempt_envelopes")
        n_env = doc.get("n_attempt_envelopes")
        log = (doc.get("attempt_log")
               if isinstance(doc.get("attempt_log"), dict)
               else (pr or {}).get("attempt_log"))
        log = log if isinstance(log, dict) else {}
        attempts = log.get("attempts")
        attempts = attempts if isinstance(attempts, list) else []
        selected = (log.get("selected_attempt")
                    if log.get("selected_attempt") is not None
                    else doc.get("selected_attempt"))
        if n_env != len(envs if isinstance(envs, list) else []):
            problems.add("detail_env_count_consistent", where,
                         "n_attempt_envelopes == len(attempt_envelopes)",
                         f"{n_env} vs "
                         f"{len(envs if isinstance(envs, list) else [])}")
        if log.get("max_attempts") not in (None, EXPECTED_MAX_ATTEMPTS):
            problems.add("detail_max_attempts", where,
                         EXPECTED_MAX_ATTEMPTS,
                         log.get("max_attempts"))
        if r.get("selected_attempt") != selected and status == "accepted":
            problems.add("index_selected_matches_detail", where,
                         selected, r.get("selected_attempt"))
        env_idx = ([e.get("attempt_index")
                    for e in envs] if isinstance(envs, list) else [])
        if status == "accepted":
            accepted_coords.append(r.get("coord"))
            if not isinstance(selected, int) or not (
                    0 <= selected < EXPECTED_MAX_ATTEMPTS):
                problems.add("accepted_selected_in_range", where,
                             f"0..{EXPECTED_MAX_ATTEMPTS - 1}", selected)
            else:
                if [a.get("index") for a in attempts] != list(
                        range(selected + 1)):
                    problems.add("accepted_attempts_sequence", where,
                                 list(range(selected + 1)),
                                 [a.get("index") for a in attempts])
                for i, a in enumerate(attempts):
                    want_acc = (i == selected)
                    if a.get("accepted") is not want_acc:
                        problems.add(
                            "accepted_attempt_gate", f"{where}:attempt{i}",
                            {"accepted": want_acc}, a)
                if env_idx != list(range(selected + 1)):
                    problems.add("accepted_env_sequence", where,
                                 list(range(selected + 1)), env_idx)
                if (isinstance(envs, list) and len(envs) > selected
                        and envs[selected].get("accepted") is not True):
                    problems.add("accepted_env_selected_true", where,
                                 True, envs[selected].get("accepted"))
            # selected envelope 的 A/B 输出哈希(生成证据之源;四处闭合
            # 的锚点)。selected 无效或字段缺失时按层报缺失,不跳过比较。
            sel_out_hashes: dict = {}
            if isinstance(envs, list) and isinstance(selected, int) and (
                    0 <= selected < len(envs)):
                et_sel = envs[selected].get("event_table")
                et_sel = et_sel if isinstance(et_sel, dict) else {}
                for side in ("A", "B"):
                    side_tbl = et_sel.get(side)
                    h = (side_tbl.get("episode_content_hash")
                         if isinstance(side_tbl, dict) else None)
                    sel_out_hashes[side] = (
                        h if isinstance(h, str) and h else None)
            # A/B 评估身份
            top_hashes = doc.get("episode_hashes")
            top_hashes = top_hashes if isinstance(
                top_hashes, dict) else {}
            out_hashes = log.get("output_episode_hashes")
            out_hashes = out_hashes if isinstance(
                out_hashes, dict) else {}
            ev = doc.get("evaluation")
            if not isinstance(ev, dict):
                problems.add("accepted_evaluation_present", where,
                             "evaluation object", "missing")
                # 评估层缺失:生成侧锚点仍必须存在且与已有两层一致
                for side in ("A", "B"):
                    sel_h = sel_out_hashes.get(side)
                    if not sel_h:
                        problems.add(
                            "selected_envelope_output_present",
                            f"{where}:{side}",
                            "selected envelope event_table."
                            "episode_content_hash non-empty", sel_h)
                    else:
                        for layer, layer_h in (
                                ("attempt_log", out_hashes.get(side)),
                                ("detail_top", top_hashes.get(side))):
                            if layer_h != sel_h:
                                problems.add(
                                    "selected_envelope_output_binding",
                                    f"{where}:{side}", sel_h,
                                    {"layer": layer, "hash": layer_h})
            else:
                eps = ev.get("episodes")
                eps = eps if isinstance(eps, list) else []
                sides = [e.get("side") for e in eps]
                if sorted(s for s in sides if s) != ["A", "B"] or len(
                        set(sides)) != len(sides):
                    problems.add("evaluation_sides_exact_AB", where,
                                 ["A", "B"], sides)
                for side in ("A", "B"):
                    if not top_hashes.get(side):
                        problems.add("episode_hash_present",
                                     f"{where}:{side}", "non-empty",
                                     top_hashes.get(side))
                    if out_hashes and top_hashes.get(
                            side) != out_hashes.get(side):
                        problems.add(
                            "episode_hash_matches_attempt_log",
                            f"{where}:{side}", out_hashes.get(side),
                            top_hashes.get(side))
                eval_h: dict = {}
                for e in eps:
                    side = e.get("side")
                    if side in ("A", "B"):
                        eval_h[side] = e.get("episode_hash")
                        if e.get("episode_hash") != top_hashes.get(side):
                            problems.add(
                                "evaluation_episode_hash_binding",
                                f"{where}:{side}", top_hashes.get(side),
                                e.get("episode_hash"))
                    if e.get("pair") != idx or e.get("rung") != rung:
                        problems.add(
                            "evaluation_episode_identity",
                            f"{where}:{side}",
                            {"rung": rung, "pair": idx},
                            {"rung": e.get("rung"), "pair": e.get("pair")})
                    for pol in POLICY_KEYS:
                        if not _finite_number(e.get(pol)):
                            problems.add(
                                "evaluation_policy_finite",
                                f"{where}:{side}:{pol}", "finite number",
                                e.get(pol))
                # 四处输出身份闭合(v3):selected envelope 是被评估对象
                # 的生成证据之源;三个下游(top/log/eval)互相一致不能
                # 替代与它的绑定(下游自证 / digest 正确重算均不够)。
                for side in ("A", "B"):
                    sel_h = sel_out_hashes.get(side)
                    if not sel_h:
                        problems.add(
                            "selected_envelope_output_present",
                            f"{where}:{side}",
                            "selected envelope event_table."
                            "episode_content_hash non-empty", sel_h)
                        continue
                    for layer, layer_h in (
                            ("attempt_log", out_hashes.get(side)),
                            ("detail_top", top_hashes.get(side)),
                            ("evaluation", eval_h.get(side))):
                        if layer_h != sel_h:
                            problems.add(
                                "selected_envelope_output_binding",
                                f"{where}:{side}", sel_h,
                                {"layer": layer, "hash": layer_h})
            if doc.get("eval_started") is not True:
                problems.add("accepted_eval_started_flag", where,
                             True, doc.get("eval_started"))
            integ = doc.get("integrity")
            if isinstance(integ, dict) and integ.get("pass") is not True:
                problems.add("accepted_integrity_pass_flag", where,
                             True, integ.get("pass"))
            if doc.get("integrity_ok") is not True or (
                    isinstance(pr, dict)
                    and pr.get("integrity_ok") is not True) or (
                    r.get("integrity_ok") is not True):
                problems.add("accepted_integrity_ok_consistent", where,
                             "True in detail/pair_record/index",
                             {"detail": doc.get("integrity_ok"),
                              "pair_record": (pr or {}).get(
                                  "integrity_ok"),
                              "index": r.get("integrity_ok")})
        elif status == "rejected":
            rejected_coords.append(r.get("coord"))
            if selected is not None:
                problems.add("rejected_selected_none", where, None,
                             selected)
            if [a.get("index") for a in attempts] != list(
                    range(EXPECTED_MAX_ATTEMPTS)):
                problems.add("rejected_attempts_sequence", where,
                             list(range(EXPECTED_MAX_ATTEMPTS)),
                             [a.get("index") for a in attempts])
            if any(a.get("accepted") for a in attempts):
                problems.add("rejected_attempts_all_rejected", where,
                             "all accepted=false",
                             [a.get("accepted") for a in attempts])
            if env_idx != list(range(EXPECTED_MAX_ATTEMPTS)):
                problems.add("rejected_env_sequence", where,
                             list(range(EXPECTED_MAX_ATTEMPTS)), env_idx)
            reasons = [e.get("rejection_reasons")
                       for e in (envs if isinstance(envs, list) else [])]
            if (len(reasons) != EXPECTED_MAX_ATTEMPTS
                    or not all(reasons)):
                problems.add("rejected_reasons_complete", where,
                             f"{EXPECTED_MAX_ATTEMPTS}x non-empty",
                             reasons)
            if "evaluation" in doc or doc.get("eval_started") is not False:
                problems.add("rejected_no_evaluation", where,
                             "no evaluation / eval_started=false",
                             {"has_evaluation": "evaluation" in doc,
                              "eval_started": doc.get("eval_started")})
            ds = doc.get("downstream_sentinel")
            if not isinstance(ds, dict) or ds.get(
                    "evaluator_started") is not False:
                problems.add("rejected_sentinel_zero_start", where,
                             "evaluator_started=false", ds)
        # recorder 事实(accepted/rejected 共同)
        if doc.get("recorder_errors"):
            problems.add("detail_recorder_errors_empty", where, [],
                         doc.get("recorder_errors"))
        # 内部 digest 按原合同复算(v3):每条实际条目,不只信保存字符串;
        # canonical 语义与生产权威实现由独立测试进程对照锁死。
        env_dig = checks.setdefault("envelope_digest", {})
        for i, e in enumerate(envs if isinstance(envs, list) else []):
            try:
                calc = _recompute_envelope_digest(e)
                ok = calc == e.get("digest")
                env_dig[f"{where}:env{i}"] = ok
                if not ok:
                    problems.add("envelope_digest_recompute",
                                 f"{where}:env{i}", calc, e.get("digest"))
            except (TypeError, ValueError) as exc:
                env_dig[f"{where}:env{i}"] = False
                problems.add("envelope_digest_recompute",
                             f"{where}:env{i}", "canonical recompute",
                             f"{type(exc).__name__}:{exc}"[:120])
        # 生成器身份与课程参数绑定(v3):不再只查非空
        if isinstance(recipe, dict):
            rgi = recipe.get("generator_identity")
            rgi_ok = isinstance(rgi, dict) and bool(rgi)
            for i, e in enumerate(envs if isinstance(envs, list) else []):
                eg = e.get("generator")
                if not rgi_ok:
                    problems.add("envelope_generator_recipe_source",
                                 f"{where}:env{i}",
                                 "recipe.generator_identity object",
                                 rgi)
                    break
                if not isinstance(eg, dict) or not eg:
                    problems.add("envelope_generator_present",
                                 f"{where}:env{i}",
                                 "generator identity object", eg)
                    continue
                if eg != rgi:
                    diff = sorted(k for k in set(eg) | set(rgi)
                                  if eg.get(k) != rgi.get(k))
                    problems.add("envelope_generator_matches_recipe",
                                 f"{where}:env{i}",
                                 "identical to recipe.generator_identity",
                                 {"diff_fields": diff})
            rp = (recipe.get("rung_params").get(rung)
                  if isinstance(recipe.get("rung_params"), dict)
                  else None)
            # 必要课程键完整性:先查 recipe 侧(既有来源不得缺键缩小
            # 预期),再查每条 envelope 两侧。必要集合来自固定合同
            # (REQUIRED_CURRICULUM_KEYS),不是双方键的交集 —— envelope
            # 与 recipe 同时删键仍会被 envelope 侧存在性检查拒绝。
            if not isinstance(rp, dict) or not rp:
                problems.add("recipe_rung_params_present",
                             f"recipe.rung_params[{rung}]",
                             "non-empty rung parameter object", rp)
            else:
                rp_missing = [k for k in REQUIRED_CURRICULUM_KEYS
                              if k not in rp]
                if rp_missing:
                    problems.add(
                        "recipe_rung_params_required_keys",
                        f"recipe.rung_params[{rung}]",
                        {"required": list(REQUIRED_CURRICULUM_KEYS)},
                        {"missing": rp_missing})
            for i, e in enumerate(envs if isinstance(envs, list)
                                  else []):
                bp = e.get("base_params")
                for side in ("A", "B"):
                    sp = bp.get(side) if isinstance(bp, dict) else None
                    if not isinstance(sp, dict) or not sp:
                        problems.add(
                            "envelope_base_params_present",
                            f"{where}:env{i}:{side}",
                            "base_params object", sp)
                        continue
                    missing = [k for k in REQUIRED_CURRICULUM_KEYS
                               if k not in sp]
                    if missing:
                        problems.add(
                            "envelope_base_params_required_keys",
                            f"{where}:env{i}:{side}",
                            {"required": list(REQUIRED_CURRICULUM_KEYS),
                             "note": "必要课程键必须存在(固定合同,"
                                     "与 recipe 是否缺键无关)"},
                            {"missing": missing})
                    if isinstance(rp, dict) and rp:
                        wrong = sorted(k for k, v in rp.items()
                                       if k in sp and sp.get(k) != v)
                        if wrong:
                            problems.add(
                                "envelope_base_params_matches_rung",
                                f"{where}:env{i}:{side}",
                                f"same-named keys equal to "
                                f"recipe.rung_params[{rung}]"
                                f"(合法展开的附加键不判)",
                                {"mismatched": wrong})
        # 每条 envelope 的 A/B 事件表两侧完整(实际条目)
        for i, e in enumerate(envs if isinstance(envs, list) else []):
            et = e.get("event_table")
            et = et if isinstance(et, dict) else {}
            for side in ("A", "B"):
                if ((et.get(side) or {}).get("counts")) is None:
                    problems.add(
                        "detail_env_event_table_sides",
                        f"{where}:env{i}:{side}",
                        "counts present on both sides", "missing")
        env_ns = {e.get("namespace") for e in (
            envs if isinstance(envs, list) else [])}
        wrong_ns = env_ns - {SLICE_NAMESPACE}
        if wrong_ns:
            problems.add("detail_env_namespace", where,
                         SLICE_NAMESPACE, sorted(str(n) for n in wrong_ns))
        env_ident = [f"{e.get('rung')}/p{e.get('pair_index')}"
                     for e in (envs if isinstance(envs, list) else [])
                     if e.get("rung") != rung
                     or e.get("pair_index") != idx]
        if env_ident:
            problems.add("detail_env_coordinate_identity", where,
                         f"{rung}/p{idx} in every envelope",
                         f"foreign: {env_ident[:3]}")

    # L8 p52 负例(本次模式必需;与固定来源逐条对照)
    p52 = _load_json(problems, out_dir / "p52_negative.json",
                     "p52_negative.json")
    if p52 is not None:
        if p52.get("coordinates") != P52_NEGATIVE:
            problems.add("p52_coordinates", "p52_negative.coordinates",
                         P52_NEGATIVE, p52.get("coordinates"))
        if p52.get("accepted") is not False:
            problems.add("p52_rejected", "p52_negative.accepted",
                         False, p52.get("accepted"))
        if p52.get("selected_attempt") is not None:
            problems.add("p52_selected_none",
                         "p52_negative.selected_attempt", None,
                         p52.get("selected_attempt"))
        penvs = p52.get("attempt_envelopes")
        penvs = penvs if isinstance(penvs, list) else []
        checks["p52_n_envelopes"] = len(penvs)
        if len(penvs) != EXPECTED_MAX_ATTEMPTS or [
                e.get("attempt_index") for e in penvs] != list(
                range(EXPECTED_MAX_ATTEMPTS)):
            problems.add("p52_envelopes_complete",
                         "p52_negative.attempt_envelopes",
                         list(range(EXPECTED_MAX_ATTEMPTS)),
                         [e.get("attempt_index") for e in penvs])
        if any(e.get("accepted") for e in penvs):
            problems.add("p52_all_envelopes_rejected",
                         "p52_negative.attempt_envelopes",
                         "all accepted=false",
                         [e.get("accepted") for e in penvs])
        if not all(e.get("rejection_reasons")
                   for e in penvs):
            problems.add("p52_reasons_nonempty",
                         "p52_negative.attempt_envelopes",
                         "non-empty reasons per envelope", "empty found")
        for i, e in enumerate(penvs):
            et = e.get("event_table")
            et = et if isinstance(et, dict) else {}
            for side in ("A", "B"):
                if ((et.get(side) or {}).get("counts")) is None:
                    problems.add(
                        "p52_env_event_table_sides",
                        f"p52_negative:env{i}:{side}",
                        "counts present on both sides", "missing")
        if p52.get("recorder_errors"):
            problems.add("p52_recorder_errors", "p52_negative", [],
                         p52.get("recorder_errors"))
        ds = p52.get("downstream_sentinel")
        if not isinstance(ds, dict) or (
                ds.get("evaluator_started") is not False
                or ds.get("evaluator_invocations") != 0):
            problems.add("p52_evaluator_zero", "p52_negative.sentinel",
                         {"evaluator_started": False,
                          "evaluator_invocations": 0}, ds)
        # 固定来源对照(不只用保存的布尔)
        orig = _load_json(problems, p52_envelope_path,
                          "p52_envelope(original)")
        if orig is not None:
            ocall = orig.get("call_envelope")
            if not isinstance(ocall, dict):
                problems.add("p52_orig_call_envelope",
                             "original.call_envelope", "object",
                             type(ocall).__name__)
                ocall = {}
            else:
                try:
                    ccalc = _recompute_call_digest(ocall)
                    checks["p52_orig_call_digest_recomputed"] = (
                        ccalc == ocall.get("digest"))
                    if ccalc != ocall.get("digest"):
                        problems.add(
                            "p52_orig_call_digest_recompute",
                            "original.call_envelope.digest",
                            ccalc, ocall.get("digest"))
                except (TypeError, ValueError) as exc:
                    problems.add(
                        "p52_orig_call_digest_recompute",
                        "original.call_envelope.digest",
                        "canonical recompute",
                        f"{type(exc).__name__}:{exc}"[:120])
            for field in ("namespace", "family", "rung", "pair_index"):
                if ocall.get(field) != P52_NEGATIVE[field]:
                    problems.add("p52_orig_call_identity",
                                 f"original.call_envelope.{field}",
                                 P52_NEGATIVE[field], ocall.get(field))
            if ocall.get("max_attempts") != EXPECTED_MAX_ATTEMPTS:
                problems.add("p52_orig_max_attempts",
                             "original.call_envelope.max_attempts",
                             EXPECTED_MAX_ATTEMPTS,
                             ocall.get("max_attempts"))
            orig_reasons = [a.get("rejection_reasons")
                            for a in orig.get("attempt_envelopes", [])]
            new_reasons = [e.get("rejection_reasons") for e in penvs]
            if orig_reasons != new_reasons:
                problems.add("p52_reasons_match_original",
                             "p52_negative vs original envelopes",
                             "identical per-attempt reasons",
                             {"original": orig_reasons,
                              "saved": new_reasons})
            if p52.get("rejection_reasons_match_original") is not True:
                problems.add("p52_match_flag_true",
                             "p52_negative.rejection_reasons_match_original",
                             True,
                             p52.get("rejection_reasons_match_original"))
            # 身份体逐条对照(v3):顶层坐标正确、拒绝词表相同、保存
            # digest 各自复算正确,都不能替代内层身份逐字段对应——
            # 换坐标/换 seed 的自洽负例在此拒绝(runtime 不参与)。
            oenvs = orig.get("attempt_envelopes")
            oenvs = oenvs if isinstance(oenvs, list) else []
            if len(oenvs) != len(penvs):
                problems.add("p52_orig_envelope_count",
                             "original.attempt_envelopes",
                             f"same count as saved ({len(penvs)})",
                             len(oenvs))
            else:
                body_checks = checks.setdefault("p52_identity_body", {})
                for i, (oe, ne) in enumerate(zip(oenvs, penvs)):
                    for side_tag, env in (("original", oe),
                                          ("saved", ne)):
                        try:
                            side_calc = _recompute_envelope_digest(env)
                            side_ok = side_calc == env.get("digest")
                        except (TypeError, ValueError):
                            side_ok = False
                        if not side_ok:
                            problems.add(
                                "p52_envelope_digest_recompute",
                                f"{side_tag}:env{i}",
                                "recompute == saved digest",
                                env.get("digest"))
                    otext = _identity_body_text(oe)
                    ntext = _identity_body_text(ne)
                    equal = (otext == ntext and not str(otext).startswith(
                        "<canonical-error"))
                    body_checks[f"env{i}"] = bool(equal)
                    if not equal:
                        obody = (_digest_body(oe)
                                 if isinstance(oe, dict) else {})
                        nbody = (_digest_body(ne)
                                 if isinstance(ne, dict) else {})
                        diff = sorted(k for k in set(obody) | set(nbody)
                                      if obody.get(k) != nbody.get(k))
                        problems.add(
                            "p52_identity_body_match_original",
                            f"p52_negative:env{i}",
                            "canonical identity body identical to "
                            "original (digest/runtime excluded)",
                            {"diff_fields": diff})

    # L9 汇总复核(从详情行重算,不直接相信 summary 字段)
    if summary is not None:
        if summary.get("n_accepted") != len(accepted_coords):
            problems.add("summary_n_accepted", "slice_summary",
                         len(accepted_coords), summary.get("n_accepted"))
        if summary.get("n_rejected") != len(rejected_coords):
            problems.add("summary_n_rejected", "slice_summary",
                         len(rejected_coords), summary.get("n_rejected"))
        if summary.get("n_requests") != len(rows):
            problems.add("summary_n_requests", "slice_summary",
                         len(rows), summary.get("n_requests"))
        if summary.get("evaluated_coordinates") != accepted_coords:
            problems.add("summary_evaluated_coords", "slice_summary",
                         accepted_coords,
                         summary.get("evaluated_coordinates"))
        if summary.get("evaluator_invocations_total") != len(
                accepted_coords):
            problems.add("summary_eval_invocations", "slice_summary",
                         len(accepted_coords),
                         summary.get("evaluator_invocations_total"))
        if summary.get("replaced_or_dropped") is not False:
            problems.add("summary_not_replaced", "slice_summary",
                         False, summary.get("replaced_or_dropped"))
        checks["accepted_coords"] = accepted_coords
        checks["rejected_coords"] = rejected_coords

    # 只读不变性(v3 时序):先在回执写入前核对检查过程未动源,写入回执
    # 后再拍最终快照——准入若有遗漏,写入源内的文件此时必被捕捉。
    after_mid = _snapshot(out_dir) if out_dir.is_dir() else {}
    source_identical = (before == after_mid)
    checks["source_snapshot_identical"] = source_identical
    if not source_identical:
        problems.add("source_readonly", "source_dir snapshot",
                     "identical before/after",
                     {"before_keys": len(before),
                      "after_keys": len(after_mid)})

    verdict = "PASS" if not problems else "FAIL"
    report = {
        "format": "r17-c3-engineering-slice-readback-v4",
        "engineering_only": True,
        "readback_verdict": verdict,
        "n_problems": len(problems),
        "problems": problems.items,
        "checks": checks,
        "expected_contract": {
            "namespace": SLICE_NAMESPACE, "family": SLICE_FAMILY,
            "requests": [list(x) for x in EXPECTED_REQUESTS],
            "max_attempts": EXPECTED_MAX_ATTEMPTS,
            "negative_control_required": True,
            "p52_envelope_source": str(p52_envelope_path)},
        "report_target_admission": {
            "report_path": str(report_path),
            "confirmed_target": str(confirmed),
            "protect_roots": [str(p) for p in protect],
            "admitted": True,
            "note": "写前准入已通过;确认目标(含临时件父目录)不与只读"
                    "输入重叠且本次调用前不存在;全部写入消费该确认"
                    "目标,发布只创建不替换"},
        "reader_sha256": _sha256_file(_HERE),
        "read_utc": utc_now(),
    }
    # 首次发布:只创建不替换;返回本次独占候选的文件身份(所有权)
    target_id = _atomic_write_receipt(confirmed, report)
    after_final = _snapshot(out_dir) if out_dir.is_dir() else {}
    if after_final != before:
        # 回执写入期间/之后源被污染:以最终事实改判 FAIL 并更新本次
        # 独占候选(所有权核对通过才替换;更新的是本次调用创建的
        # 同一文件,不是调用开始前的历史目标)。
        report["checks"]["source_snapshot_identical"] = False
        report["problems"].append({
            "check": "source_readonly_final",
            "where": "source_dir snapshot (after receipt write)",
            "expected": "identical before/after-final",
            "actual": {"before_keys": len(before),
                       "after_final_keys": len(after_final)}})
        report["n_problems"] = len(report["problems"])
        report["readback_verdict"] = "FAIL"
        _atomic_write_receipt(confirmed, report, owned_id=target_id)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out-dir", help="切片输出目录(须不存在或为空)")
    ap.add_argument("--p52-negative", metavar="ENV_JSON",
                    help="原 p52 失败证据 json(负例只读重放)")
    ap.add_argument("--readback", metavar="DIR",
                    help="只读加载模式:完整语义核对已执行切片")
    ap.add_argument("--p52-envelope", metavar="ENV_JSON",
                    help="读回用:原 p52 envelope(固定来源对照,必需)")
    ap.add_argument("--report", metavar="JSON",
                    help="读回回执输出路径(缺省写当前目录,当前目录"
                         "在只读输入内时拒绝并要求显式外部路径)")
    ap.add_argument("--protect-root", metavar="DIR", action="append",
                    default=[], help="额外只读根(组包/冷读声明更大"
                    " payload 根;可重复;写前准入一并保护)")
    args = ap.parse_args(argv)

    if args.readback:
        if not args.p52_envelope:
            ap.error("--readback 需要 --p52-envelope(负例固定来源对照)")
        report_path = (Path(args.report) if args.report else
                       Path.cwd() / f"readback_receipt_"
                       f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}.json")
        try:
            report = readback(Path(args.readback), report_path,
                              Path(args.p52_envelope),
                              protect_roots=[Path(p) for p in
                                             args.protect_root])
        except ReportTargetRejected as exc:
            # 写前准入拒绝:零源写入,错误位置与原因进 stderr,不写报告
            print(f"report target rejected (no source writes "
                  f"performed): {exc}", file=sys.stderr)
            return 2
        except ReceiptWriteError as exc:
            print(f"receipt write failed: {exc}", file=sys.stderr)
            return 6
        except Exception as exc:  # noqa: BLE001 —— 读回自身异常即 FAIL
            print(f"readback internal error: "
                  f"{type(exc).__name__}: {exc}", file=sys.stderr)
            return 5
        print(f"readback_verdict: {report['readback_verdict']}")
        print(f"n_problems: {report['n_problems']}")
        confirmed = Path(report["report_target_admission"][
            "confirmed_target"])
        print(f"report: {confirmed}")
        try:
            sys.stdout.flush()
        except OSError:
            pass
        # 回执写失败必须在 readback 内抛出;此处兜底复核确实落在
        # 准入确认的实际位置
        if not confirmed.is_file():
            print("FATAL: 回执未落盘", file=sys.stderr)
            return 6
        return 0 if report["readback_verdict"] == "PASS" else 1

    if not args.out_dir:
        ap.error("需要 --out-dir 或 --readback")
    out_dir = Path(args.out_dir)
    if out_dir.exists() and any(out_dir.iterdir()):
        print(f"refusing: {out_dir} 非空(不覆盖旧结果)",
              file=sys.stderr)
        return 2
    out_dir.mkdir(parents=True, exist_ok=True)

    summary = run_slice(out_dir)
    if args.p52_negative:
        neg = run_p52_negative(out_dir, Path(args.p52_negative))
        summary["p52_negative_accepted"] = neg["accepted"]
        ok, neg_problems = p52_negative_evidence_ok(neg)
        summary["p52_negative_evidence_ok"] = ok
        summary["p52_negative_problems"] = neg_problems
        _atomic_write(out_dir / "slice_summary.json", summary)
        if not ok:
            print("p52 negative control FAILED(事实已保存):",
                  file=sys.stderr)
            for p in neg_problems:
                print(f"  - {p}", file=sys.stderr)
            return 4
    print(f"slice: {summary['n_accepted']} accepted / "
          f"{summary['n_rejected']} rejected of "
          f"{summary['n_requests']}")
    print(f"out: {out_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
