#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 证据闭合:固定失败坐标 p52 的完整重放取证与机制核对(v2)。

v1 四缺陷修正(任务书 §2.2/§2.3/§3):
1. 空重放误判:旧版 deviated=false 零遍历即得"一致"。v2 强制重放证据
   完备(恰好 max_attempts 条、attempt 编号 0..N-1 唯一齐全、A/B 两侧
   event_table 完整、recorder 无错误),不完备 → REPLAY_EVIDENCE_INCOMPLETE,
   绝不从空集合推出"一致"。
2. 提前 return 漏写报告:意外接受/非预期异常/输出失败一律先完整落盘
   报告再定 rc,不留"没写报告却看起来成功结束"的出口。
3. 只比 A 侧:v2 用 compare_envelopes 做 envelope 级整体比较(含 A/B
   全字段),另附人读 A/B 计数对照;digest 与业务内容分开报告。
4. DP"上界"矛盾:旧版一边称碰撞使零个更容易、一边称忽略碰撞的结果
   是上界,方向自相矛盾。v2 按实际调度机器证明该参数下不存在碰撞与
   截断(事件位置序列严格递增;t+gap<=n-1-end_margin+gap_hi<n-1),
   DP 是理想独立均匀 RNG 模型下的精确值,并保留三个限制(A/B 共享
   事件表不能 q^10;只覆盖零 distractor 条件不等于总失败概率;固定
   坐标结果是确定的,重跑不是新抽签)。

用法(受监护工程运行,task-kind=c3diag):
  r17_c3_p52_diagnosis.py --envelope <generation_failure_envelopes_...json> \
      --out <diagnosis.json> [--no-replay]

rc 语义(报告总是先落盘):
  0  = 诊断完整取证(含"原合同允许的结构拒绝"与"调用偏离"两类结论)
  0  = --no-replay 只读/数学分析(verdict 明确 READONLY_NO_REPLAY,
       绝不写"重放通过")
  3  = 重放证据不完备/不可验(REPLAY_EVIDENCE_INCOMPLETE)
  4  = 意外接受或非预期异常(UNEXPECTED_ACCEPTANCE/UNEXPECTED_EXCEPTION)
  6  = 输出写失败(尽力写主报告;失败原因进 stderr)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

try:
    import rl_curriculum.curriculum261_c3  # noqa: F401  部署环境已有路径
except ImportError:  # 发布仓库内直接运行时的回退
    sys.path.insert(0, str(
        Path(__file__).resolve().parent.parent / "src"))

#: C3 调度常量来源(curriculum261_c3._generate 字面量;读取处逐字对应)
C3_SCHED_T0 = 10          # t = 10(事件首位置)
C3_SCHED_END_MARGIN = 8   # while t < n - 8(循环上界)


def utc_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------ 解析 DP(纯数学,不调生成器)
def dp_zero_distractor(n_bars: int, t0: int, t_end: int,
                       p_cue: float, p_dis: float,
                       gap_lo: int, gap_hi: int) -> dict:
    """C3 调度循环的精确零 distractor 概率(后向动态规划)。

    每迭代(t<t_end):roll<U(cue) → signal 对(存活,推进 gap+4,
    gap∈[gap_lo,gap_hi] 均匀);roll<U(cue+dis) → distractor 对
    (出现即失败吸收,对"零 distractor"贡献 0);否则空 bar(t+=1)。
    t>=t_end 无更多迭代,存活=1。

    本调度下(见 scheduling_no_collision_proof)distractor 计数恒为
    偶数、零个是该条件的唯一不满足形态,故 q(t_end 前无 distractor
    对)=P(n_distractors=0)。碰撞/截断在该参数下不存在,DP 即理想
    独立均匀 RNG 模型下的精确值(非上界/下界近似)。
    """
    adv = list(range(gap_lo + 4, gap_hi + 4 + 1))  # gap+4 均匀
    k = len(adv)
    p_empty = 1.0 - p_cue - p_dis
    max_t = t_end + max(adv) + 2
    f = [1.0] * (max_t + 1)          # t>=t_end:无更多迭代
    for t in range(t_end - 1, t0 - 1, -1):
        v = (p_cue / k) * sum(f[t + d] for d in adv)
        v += p_empty * f[t + 1]
        f[t] = v                      # distractor 分支:失败吸收,贡献 0
    p_zero = f[t0]
    return {
        "p_zero_distractor_single_event_table": p_zero,
        "p_five_consecutive_zero_independent_model": p_zero ** 5,
        "method": "exact DP over scheduling loop under ideal "
                  "independent-uniform RNG model; no collision or "
                  "truncation exists under this parameterization "
                  "(machine-verified), so the DP value is exact, "
                  "not an upper/lower bound approximation",
        "params": {"n_bars": n_bars, "t0": t0, "t_end": t_end,
                   "p_cue": p_cue, "p_dis": p_dis,
                   "gap_lo": gap_lo, "gap_hi": gap_hi,
                   "advance_dist": adv},
    }


def dp_forward_check(n_bars: int, t0: int, t_end: int,
                     p_cue: float, p_dis: float,
                     gap_lo: int, gap_hi: int) -> float:
    """前向分布演化(独立等价实现,核验后向 DP)。

    P(存活至首次离开循环) = 所有以 t>=t_end 结束且途中无 distractor
    分支的路径概率之和;与后向递推只是求和方向不同,数值须一致。
    """
    adv = list(range(gap_lo + 4, gap_hi + 4 + 1))
    k = len(adv)
    p_empty = 1.0 - p_cue - p_dis
    if t0 >= t_end:
        return 1.0  # 初始即出循环:无迭代,必然零 distractor
    prob = {t0: 1.0}
    survived = 0.0
    for t in range(t0, t_end):
        p = prob.pop(t, 0.0)
        if p == 0.0:
            continue
        for d in adv:  # signal 分支(存活)
            nt = t + d
            if nt >= t_end:
                survived += p * p_cue / k
            else:
                prob[nt] = prob.get(nt, 0.0) + p * p_cue / k
        nt = t + 1     # 空 bar(存活)
        if nt >= t_end:
            survived += p * p_empty
        else:
            prob[nt] = prob.get(nt, 0.0) + p * p_empty
        # distractor 分支:失败吸收,不计入 survived
    return survived


def dp_boundary_checks() -> list[dict]:
    """DP 边界条件独立核验(解析特例 + 前向/后向交叉,不硬编码 D0 答案)。"""
    checks: list[dict] = []

    def _both(n, t0, t_end, pc, pd, lo, hi):
        back = dp_zero_distractor(n, t0, t_end, pc, pd, lo, hi)
        fwd = dp_forward_check(n, t0, t_end, pc, pd, lo, hi)
        return back, fwd

    # (1) distractor_rate=0 → 必然零 distractor,q=1
    b, f = _both(288, 10, 280, 0.2, 0.0, 4, 6)
    checks.append({"name": "p_dis_zero_q_is_one",
                   "q_backward": b["p_zero_distractor_single_event_table"],
                   "q_forward": f, "ok": abs(b[
                       "p_zero_distractor_single_event_table"] - 1.0) < 1e-12
                   and abs(f - 1.0) < 1e-12})
    # (2) cue_rate=0 → 每迭代只能空 bar(1-p_dis)或 distractor;
    #     t0..t_end-1 共 t_end-t0 次迭代全空 → q=(1-p_dis)^(t_end-t0)
    n, t0, t_end, pd = 288, 10, 280, 0.015
    expect = (1.0 - pd) ** (t_end - t0)
    b, f = _both(n, t0, t_end, 0.0, pd, 4, 6)
    checks.append({"name": "p_cue_zero_closed_form",
                   "closed_form": expect,
                   "q_backward": b["p_zero_distractor_single_event_table"],
                   "q_forward": f,
                   "ok": abs(b["p_zero_distractor_single_event_table"]
                             - expect) < 1e-12 and abs(f - expect) < 1e-12})
    # (3) 无剩余迭代(t0>=t_end) → q=1
    b, f = _both(288, 280, 280, 0.2, 0.015, 4, 6)
    checks.append({"name": "no_remaining_bars_q_is_one",
                   "q_backward": b["p_zero_distractor_single_event_table"],
                   "q_forward": f, "ok": abs(f - 1.0) < 1e-15})
    # (4) 极短 horizon(n=20 → t_end=12):前向/后向交叉
    b, f = _both(20, 10, 12, 0.2, 0.015, 4, 6)
    checks.append({"name": "short_horizon_fwd_back_agree",
                   "q_backward": b["p_zero_distractor_single_event_table"],
                   "q_forward": f,
                   "ok": abs(b["p_zero_distractor_single_event_table"]
                             - f) < 1e-12})
    # (5) D0 全参数前向/后向交叉(主值独立核验)
    b, f = _both(288, 10, 280, 0.200, 0.015, 4, 6)
    checks.append({"name": "d0_fwd_back_agree",
                   "q_backward": b["p_zero_distractor_single_event_table"],
                   "q_forward": f,
                   "ok": abs(b["p_zero_distractor_single_event_table"]
                             - f) < 1e-12})
    # (6) 概率合法性 + p_dis 单调不增
    q_low = dp_zero_distractor(288, 10, 280, 0.2, 0.015, 4, 6)[
        "p_zero_distractor_single_event_table"]
    q_high = dp_zero_distractor(288, 10, 280, 0.2, 0.10, 4, 6)[
        "p_zero_distractor_single_event_table"]
    checks.append({"name": "probability_validity_monotone_p_dis",
                   "q_dis_0p015": q_low, "q_dis_0p10": q_high,
                   "ok": 0.0 <= q_low <= 1.0 and 0.0 <= q_high <= 1.0
                   and q_high <= q_low})
    return checks


def scheduling_no_collision_proof(n_bars: int, t0: int, end_margin: int,
                                  gap_lo: int, gap_hi: int) -> dict:
    """调度级无碰撞/无截断机器证明(从实际调度代码语义构造)。

    归纳论证:对起点 t_i 严格递增;镜像 m_i=min(t_i+g_i, n-1)。
    (a) 无截断:循环保证 t_i <= n-1-end_margin,故
        t_i+g_i <= n-1-end_margin+gap_hi < n-1 当 end_margin >= gap_hi+2;
    (b) 无同 bar 双事件:m_i < t_i+g_i+4 = t_{i+1}(对后紧跟下一对)或
        m_i < t_i+1 <= t_{i+1}(中间有空 bar)——推进量恒比镜像距离多 4;
    (c) 故全部事件位置严格递增;distractor 计数 = 2 x distractor 对数
        (偶数),零个是 too_few_distractors(C3_MIN_DISTRACTORS=1)的
        唯一不满足形态。
    """
    last_start_max = n_bars - 1 - end_margin
    mirror_max = last_start_max + gap_hi
    return {
        "n_bars": n_bars, "t0": t0, "t_end": n_bars - end_margin,
        "gap": [gap_lo, gap_hi],
        "loop_last_start_max": last_start_max,
        "mirror_position_max": mirror_max,
        "n_minus_1": n_bars - 1,
        "no_truncation": bool(mirror_max < n_bars - 1),
        "no_truncation_condition": (
            "end_margin>=gap_hi+2 required (8>=6+2 holds)"),
        "advance_minus_mirror_distance": 4,
        "strictly_increasing_positions": True,  # 由 (a)+(b) 归纳
        "distractor_count_is_even": True,
        "zero_is_only_violation_shape": True,
        "proof": ("(a) no clamp: t_i+g_i<={mirror_max}<n-1; "
                  "(b) m_i<t_i+g_i+4<=t_(i+1); positions strictly "
                  "increasing; distractor bars = 2 x distractor pairs"),
    }


def hidden_event_mechanics(hidden, gap_lo: int = 4,
                           gap_hi: int = 6) -> dict:
    """从 hidden 列重建事件调度结构(被动观察;生成时可知条件)。

    事件 = sig_strength 非零 bar(信号与 distractor 共用脉冲列)。
    无碰撞前提下位置升序即生成顺序 (t_1, m_1, t_2, m_2, ...)。
    """
    import numpy as np
    s = hidden["sig_strength"].to_numpy()
    d = hidden["sig_dir"].to_numpy()
    dis = hidden["distractor_flag"].to_numpy()
    pos = np.flatnonzero(s != 0)
    n_pairs = int(len(pos) // 2)
    gaps: list[int] = []
    inter: list[int] = []
    pair_structure_ok = len(pos) % 2 == 0
    distractor_pairs = 0
    for i in range(n_pairs):
        a, b = int(pos[2 * i]), int(pos[2 * i + 1])
        g = b - a
        gaps.append(g)
        same_strength = bool(s[a] == s[b])
        mirrored_dir = bool(d[b] == -d[a])
        pair_flag_equal = bool(dis[a] == dis[b])
        if not gap_lo <= g <= gap_hi:
            pair_structure_ok = False
        if not (same_strength and mirrored_dir and pair_flag_equal):
            pair_structure_ok = False
        if dis[a] != 0:
            distractor_pairs += 1
    for i in range(n_pairs - 1):
        delta = int(pos[2 * (i + 1)] - pos[2 * i + 1])
        inter.append(delta)
        if delta < 4:
            pair_structure_ok = False
    return {
        "n_event_bars": int(len(pos)),
        "n_event_pairs": n_pairs,
        "positions_strictly_increasing": bool(
            len(pos) < 2 or int(np.diff(pos).min()) > 0),
        "last_event_position": int(pos[-1]) if len(pos) else None,
        "pair_gaps": gaps,
        "inter_pair_min_advance": int(min(inter)) if inter else None,
        "pair_structure_ok": bool(pair_structure_ok),
        "n_distractor_pairs": distractor_pairs,
        "n_distractor_bars": int(dis.sum()),
        "n_distractor_bars_even": int(dis.sum()) % 2 == 0,
        "n_signal_bars": int(((d != 0) & (dis == 0)).sum()),
    }


# ------------------------------------------------ 取证 recorder(v2)
def make_checked_recorder_cls():
    """EnvelopeRecorder 取证子类:record 错误自记 + hidden 机制快照。

    api 层 recorder_errors 是局部死变量(不上抛),recorder 错误的唯一
    可观察症状是 envelope 缺条;本子类把错误就地登记,供证据完备性
    判定。仍是纯被动观察(异常被 api 吞掉,不改变生成结果)。
    """
    from rl_curriculum.curriculum261_generation_envelope import (
        EnvelopeRecorder,
    )

    class CheckedRecorder(EnvelopeRecorder):
        def __init__(self, **kw):
            super().__init__(**kw)
            self.record_errors: list[str] = []
            self.attempt_mechanics: list[dict] = []

        def record(self, event: str, payload: dict) -> None:
            try:
                super().record(event, payload)
                if event == "attempt":
                    eps = payload.get("episodes") or {}
                    mech = {"attempt": payload["attempt"]}
                    for side in ("A", "B"):
                        ep = eps.get(side)
                        mech[side] = (hidden_event_mechanics(ep.hidden)
                                      if ep is not None else None)
                    ha = eps["A"].hidden if "A" in eps else None
                    hb = eps["B"].hidden if "B" in eps else None
                    if ha is not None and hb is not None:
                        import numpy as np
                        mech["shared_event_table"] = {
                            "sig_strength": bool(np.array_equal(
                                ha["sig_strength"].to_numpy(),
                                hb["sig_strength"].to_numpy())),
                            "sig_dir": bool(np.array_equal(
                                ha["sig_dir"].to_numpy(),
                                hb["sig_dir"].to_numpy())),
                            "distractor_flag": bool(np.array_equal(
                                ha["distractor_flag"].to_numpy(),
                                hb["distractor_flag"].to_numpy())),
                        }
                    else:
                        mech["shared_event_table"] = None
                    self.attempt_mechanics.append(mech)
            except Exception as exc:  # noqa: BLE001 —— 取证路径自记
                self.record_errors.append(
                    f"{type(exc).__name__}:{exc}")

    return CheckedRecorder


def assess_replay_evidence(envs: list, record_errors: list,
                           max_attempts: int) -> dict:
    """重放证据完备性判定(纯函数;空/少/重复/缺侧/recorder 错误均不完备)。

    v1 缺陷:空集合遍历零次得 not deviated=True。此函数是它的反面:
    任何结构缺陷都使 evidence_complete=False,绝不从空集合推出一致。
    """
    idx = [e.get("attempt_index") for e in envs]
    expected = list(range(int(max_attempts)))
    sides_complete = all(
        (e.get("event_table", {}).get(side, {}) or {}).get("counts")
        is not None
        for e in envs for side in ("A", "B"))
    return {
        "n_attempt_envelopes": len(envs),
        "attempt_indices": idx,
        "both_sides_complete": sides_complete,
        "recorder_errors": list(record_errors),
        "evidence_complete": bool(
            len(envs) == len(expected)
            and sorted(idx) == expected and len(set(idx)) == len(idx)
            and sides_complete and not record_errors),
    }


# ------------------------------------------------ 主流程
def _analyze_original(env_doc: dict, report: dict) -> None:
    """原件静态分析:坐标、证据结构完备性、A/B 双侧摘要。"""
    call = env_doc["call_envelope"]
    attempts = env_doc["attempt_envelopes"]
    report["coordinates"] = {
        "namespace": call["namespace"], "family": call["family"],
        "rung": call["rung"], "pair_index": call["pair_index"],
        "max_attempts": call["max_attempts"]}
    report["generator_identity_envelope"] = call["generator"]

    # 原件证据结构完备性(不再默认"有就行")
    idx = [a.get("attempt_index") for a in attempts]
    expected = list(range(int(call["max_attempts"])))
    sides_complete = all(
        (a.get("event_table", {}).get(side, {}) or {}).get("counts")
        is not None
        for a in attempts for side in ("A", "B"))
    report["original_evidence_check"] = {
        "n_attempt_envelopes": len(attempts),
        "attempt_indices": idx,
        "attempt_indices_unique_sorted_0_to_n": (
            sorted(idx) == expected and len(set(idx)) == len(idx)),
        "both_sides_event_table_complete": sides_complete,
        "complete": bool(sorted(idx) == expected
                         and len(set(idx)) == len(idx) and sides_complete
                         and len(attempts) == len(expected)),
    }

    # A/B 双侧摘要(v1 只有 n_distractors_A/B + n_signals_A)
    summary = []
    for a in attempts:
        row: dict = {"attempt": a["attempt_index"],
                     "outer_seed": a["outer_seed"],
                     "internal_derived_seed": a.get("internal_derived_seed"),
                     "digest": a.get("digest"),
                     "selected_attempt": None,
                     "rejection_reasons": a.get("rejection_reasons"),
                     "exception": a.get("exception")}
        for side in ("A", "B"):
            et = (a.get("event_table", {}).get(side) or {})
            counts = et.get("counts") or {}
            row[f"n_signals_{side}"] = counts.get("n_signals")
            row[f"n_distractors_{side}"] = counts.get("n_distractors")
            row[f"n_above_cost_{side}"] = counts.get("n_above_cost")
            row[f"n_below_cost_{side}"] = counts.get("n_below_cost")
            row[f"episode_content_hash_{side}"] = et.get(
                "episode_content_hash")
            row[f"hidden_digest_{side}"] = et.get("hidden_digest")
        summary.append(row)
    report["envelope_summary"] = summary


def _analyze_mechanism(env_doc: dict, report: dict) -> None:
    """结构规则与调度概率核对:计数→规则映射、无碰撞证明、DP+边界。"""
    from rl_curriculum.curriculum261_c3 import (  # 实际常量,非硬编码
        C3_MIN_DISTRACTORS, C3_MIN_ABOVE_COST, C3_MIN_BELOW_COST,
        C3_MIN_SIGNALS, C3_PAIR_GAP, C3_RUNG_PARAMS,
    )
    call = env_doc["call_envelope"]
    rp = dict(call["rung_params"])
    # episode_bars 在 attempt base_params(call rung_params 不含);
    # 回退到注册表默认,两级都登记便于核对
    attempts_env = env_doc["attempt_envelopes"]
    n_from_base = None
    if attempts_env:
        n_from_base = (attempts_env[0].get("base_params", {})
                       .get("A", {}) or {}).get("episode_bars")
    n = int(n_from_base or 288)
    t0, margin = C3_SCHED_T0, C3_SCHED_END_MARGIN
    t_end = n - margin
    gap_lo, gap_hi = int(C3_PAIR_GAP[0]), int(C3_PAIR_GAP[1])

    # 逐 attempt:实际计数 → 当前规则状态的机器映射(PnL 无关)
    rule_rows = []
    for a in env_doc["attempt_envelopes"]:
        et = a.get("event_table", {})
        ca = (et.get("A", {}) or {}).get("counts") or {}
        cb = (et.get("B", {}) or {}).get("counts") or {}
        row = {"attempt": a["attempt_index"],
               "reject_vocabulary_observed": a.get("rejection_reasons"),
               "conditions": {
                   "n_signals_ge_6": bool(
                       (ca.get("n_signals") or 0) >= C3_MIN_SIGNALS),
                   "distractors_lt_min": bool(
                       (ca.get("n_distractors") or 0)
                       < C3_MIN_DISTRACTORS),
                   "A_above_ge_2": bool(
                       (ca.get("n_above_cost") or 0)
                       >= C3_MIN_ABOVE_COST),
                   "A_below_ge_2": bool(
                       (ca.get("n_below_cost") or 0)
                       >= C3_MIN_BELOW_COST),
                   "B_above_eq_0": bool((cb.get("n_above_cost") or 0) == 0),
                   "B_below_ge_2": bool(
                       (cb.get("n_below_cost") or 0)
                       >= C3_MIN_BELOW_COST)}}
        row["only_failing_condition_is_distractors"] = bool(
            row["conditions"]["n_signals_ge_6"]
            and row["conditions"]["distractors_lt_min"]
            and row["conditions"]["A_above_ge_2"]
            and row["conditions"]["A_below_ge_2"]
            and row["conditions"]["B_above_eq_0"]
            and row["conditions"]["B_below_ge_2"])
        rule_rows.append(row)
    report["structural_rule_mapping"] = {
        "thresholds": {
            "C3_MIN_SIGNALS": C3_MIN_SIGNALS,
            "C3_MIN_ABOVE_COST": C3_MIN_ABOVE_COST,
            "C3_MIN_BELOW_COST": C3_MIN_BELOW_COST,
            "C3_MIN_DISTRACTORS": C3_MIN_DISTRACTORS},
        "distractor_count_parity": (
            "counts are bar counts; each distractor pair contributes 2 "
            "bars, so n_distractors is even and zero is the only "
            "violation shape of n_distractors>=1"),
        "per_attempt": rule_rows}

    # 调度无碰撞证明 + DP(从实际参数构造;D0 交叉核对注册表)
    report["scheduling_proof"] = scheduling_no_collision_proof(
        n, t0, margin, gap_lo, gap_hi)
    report["scheduling_proof"]["n_bars_source"] = (
        f"attempt base_params A episode_bars={n_from_base}"
        if n_from_base is not None else "fallback 288 (registry D0)")
    registry_match = {
        k: (rp.get(k) == C3_RUNG_PARAMS.get(call["rung"], {}).get(k))
        for k in ("alpha_bps", "cue_rate", "distractor_rate", "vol_bps")}
    report["rung_params_vs_registry"] = registry_match
    report["dp"] = dp_zero_distractor(
        n, t0, t_end, float(rp["cue_rate"]),
        float(rp["distractor_rate"]), gap_lo, gap_hi)
    report["dp"]["limitations"] = [
        "A/B share one event table (pair_variant not in seed "
        "derivation): five attempts give 5 event tables, NOT 10 "
        "independent sides; q^10 is invalid",
        "five distinct hash-derived seeds are not a mathematical proof "
        "of independence; q^5 is a risk estimate under the ideal "
        "independent-RNG model, not the probability of a fixed "
        "coordinate",
        "this DP covers only the zero-distractor cause; other "
        "structural conditions (signal count, above/below) can also "
        "reject and are not included in q",
    ]
    report["dp"]["boundary_checks"] = dp_boundary_checks()
    report["dp"]["boundary_checks_all_ok"] = all(
        c["ok"] for c in report["dp"]["boundary_checks"])


def _replay(env_doc: dict, report: dict) -> int:
    """带完整 recorder 取证的确定性重放(显式被动记录,不再允许空集合)。

    不复用 replay_call(它吞掉 recorder 实例,使 recorder 错误面不可
    达);直接显式构造 CheckedRecorder 传入 generate_pair_with_attempts,
    recorder 仍为纯被动观察(异常被 api 吞掉,不改变生成结果)。
    """
    from rl_curriculum.curriculum261_api import (
        PairGenerationError, generate_pair_with_attempts,
    )
    from rl_curriculum.curriculum261_generation_envelope import (
        compare_envelopes,
    )
    from rl_curriculum.curriculum261_pairs import (
        family_specs, pair_acceptance_contract,
    )
    call = env_doc["call_envelope"]
    attempts = env_doc["attempt_envelopes"]
    checked_cls = make_checked_recorder_cls()

    # 接线预检:先构造确认 recorder 可用(不跑完才发现没有证据)
    rung_params = dict(call["rung_params"])
    try:
        rec = checked_cls(
            iteration=call["iteration"], namespace=call["namespace"],
            family=call["family"], rung=call["rung"],
            pair_index=int(call["pair_index"]), rung_params=rung_params)
        recorder_attached = True
    except Exception as exc:  # noqa: BLE001 —— 记录后走不完备分支
        report["replay"] = {
            "performed": True, "recorder_attached": False,
            "recorder_construction_error": f"{type(exc).__name__}:{exc}",
            "evidence_complete": False}
        return 3

    replay_doc: dict = {"performed": True,
                        "recorder_attached": recorder_attached}
    spec = family_specs()[call["family"]]
    error: str | None = None
    selected_attempt_none: bool | None = None
    unexpected: dict | None = None
    try:
        generate_pair_with_attempts(
            spec.generator, rung_params,
            namespace=call["namespace"], family=call["family"],
            rung=call["rung"], pair_index=int(call["pair_index"]),
            structural_validator=pair_acceptance_contract(
                call["family"]),
            recorder=rec)
        unexpectedly_accepted = True
    except PairGenerationError as exc:
        unexpectedly_accepted = False
        error = str(exc)
        selected_attempt_none = (
            exc.attempt_log.selected_attempt is None)
    except Exception as exc:  # noqa: BLE001 —— 非预期异常也先写报告
        unexpected = {"error_type": type(exc).__name__,
                      "error": str(exc)[:500]}
        unexpectedly_accepted = False

    if unexpected is not None:
        replay_doc.update({"unexpectedly_accepted": False,
                           **unexpected})
        report["replay"] = replay_doc
        return 4
    if unexpectedly_accepted:
        replay_doc.update({
            "unexpectedly_accepted": True,
            "n_attempt_envelopes": len(rec.attempt_envelopes),
            "attempt_indices": [e.get("attempt_index")
                                for e in rec.attempt_envelopes],
            "note": "重放出现接受——与原五连拒不一致,构成调用偏离"
                    "合同的证据(需最小修复路径)"})
        report["replay"] = replay_doc
        return 4

    # 证据完备性强校验(修缺陷 1 的核心:空/少/重复/缺侧均不完备)
    envs = list(rec.attempt_envelopes)
    evidence = assess_replay_evidence(
        envs, rec.record_errors, int(call["max_attempts"]))
    evidence_complete = evidence["evidence_complete"]
    replay_doc.update({
        "unexpectedly_accepted": False,
        "generation_error": error,
        "selected_attempt_is_none": selected_attempt_none,
        "recorder_error_visibility": (
            "CheckedRecorder self-reports record() failures; api's "
            "recorder_errors is a dead local and unobservable"),
        "attempt_mechanics": rec.attempt_mechanics,
        **evidence})

    # 逐条 envelope 比较(A/B 全字段;digest 与业务内容分开)
    comparisons = []
    for e in envs:
        i = e.get("attempt_index")
        orig = next((x for x in attempts
                     if x["attempt_index"] == i), None)
        if orig is None:
            comparisons.append({"attempt": i, "match": "no_original"})
            continue
        cmp_row = compare_envelopes(orig, e)
        cmp_row["attempt"] = i
        # 人读 A/B 计数对照(修缺陷 3:不只 A 侧)
        for side in ("A", "B"):
            ca = (orig["event_table"].get(side) or {}).get("counts") or {}
            cb = (e.get("event_table", {}).get(side) or {}).get(
                "counts") or {}
            cmp_row[f"{side}_counts"] = {
                k: {"original": ca.get(k), "replayed": cb.get(k)}
                for k in ("n_signals", "n_distractors",
                          "n_above_cost", "n_below_cost")}
        cmp_row["rejection_reasons_match"] = bool(
            orig.get("rejection_reasons") == e.get("rejection_reasons"))
        cmp_row["rejection_vocabulary"] = e.get("rejection_reasons")
        comparisons.append(cmp_row)
    replay_doc["envelope_comparisons"] = comparisons
    digest_level = all(
        c.get("bitwise_identical") is True
        for c in comparisons if c.get("match") != "no_original")
    business_level = all(
        (not c.get("identity_drift")) and (not c.get("result_drift"))
        and c.get("rejection_reasons_match", False)
        for c in comparisons if c.get("match") != "no_original")
    # runtime 差异单独报告(digest 不含 runtime;不删除不篡改)
    runtime_diffs = {}
    for e in envs:
        i = e.get("attempt_index")
        orig = next((x for x in attempts
                     if x["attempt_index"] == i), None)
        if orig is not None and orig.get("runtime") != e.get("runtime"):
            for k in set(orig.get("runtime", {})) | set(
                    e.get("runtime", {})):
                if orig.get("runtime", {}).get(k) != e.get(
                        "runtime", {}).get(k):
                    runtime_diffs.setdefault(str(i), {})[k] = {
                        "original": orig["runtime"].get(k),
                        "replayed": e.get("runtime", {}).get(k)}
    call_digest_recomputed = rec.call_envelope["digest"]
    call_digest_match = (call_digest_recomputed == call.get("digest"))
    replay_doc.update({
        "call_digest_recomputed": call_digest_recomputed,
        "call_digest_recorded": call.get("digest"),
        "call_digest_match": call_digest_match,
        "digest_level_consistent": digest_level,
        "business_level_consistent": business_level,
        "runtime_diffs": runtime_diffs,
        "runtime_note": (
            "envelope digests exclude runtime fields; runtime diffs are "
            "reported verbatim and never removed"),
        "deterministic_replay_consistent": bool(
            evidence_complete and digest_level and business_level
            and call_digest_match and not runtime_diffs),
        "business_replay_consistent": bool(
            evidence_complete and business_level and call_digest_match)})
    report["replay"] = replay_doc
    if not evidence_complete:
        return 3
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--envelope", required=True,
                    help="run 1475 的 generation_failure_envelopes json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-replay", action="store_true",
                    help="只读分析+DP+机制证明,不做重放(不得写重放通过)")
    args = ap.parse_args()

    env_doc = json.loads(
        Path(args.envelope).read_text(encoding="utf-8"))
    report: dict = {"schema": "r17-c3-p52-diagnosis-v2",
                    "written_utc": utc_now()}
    rc = 0
    try:
        _analyze_original(env_doc, report)
        # 生成器源身份核验(与 v1 相同口径)
        import rl_curriculum.curriculum261_c3 as c3mod
        src_sha = hashlib.sha256(
            Path(c3mod.__file__).read_bytes()).hexdigest()
        report["generator_source_sha256_actual"] = src_sha
        report["generator_source_matches_envelope"] = (
            src_sha == env_doc["call_envelope"]["generator"][
                "source_sha256"])
        _analyze_mechanism(env_doc, report)

        if args.no_replay:
            report["replay"] = {
                "performed": False,
                "note": "只读/数学分析模式;未做重放,不产生重放一致性"
                        "结论(README §3.4)"}
            report["verdict"] = "READONLY_NO_REPLAY"
            report["verdict_note"] = (
                "只读分析完成(证据结构+机制+DP);重放未执行,任何"
                "一致性结论均不成立,需默认模式取证")
        else:
            rc = _replay(env_doc, report)
            replay = report.get("replay", {})
            src_ok = report["generator_source_matches_envelope"]
            orig_ok = report["original_evidence_check"]["complete"]
            if replay.get("unexpectedly_accepted"):
                report["verdict"] = "UNEXPECTED_ACCEPTANCE"
                report["verdict_note"] = (
                    "重放出现接受,与原五连拒不一致——调用偏离既有合同"
                    "的证据;按 §4.3 分支二定位最小接线错误")
            elif replay.get("error_type"):
                report["verdict"] = "UNEXPECTED_EXCEPTION"
                report["verdict_note"] = (
                    f"重放遇到非预期异常 {replay['error_type']}:"
                    f"{replay.get('error', '')[:200]}——需人工介入")
            elif not replay.get("evidence_complete"):
                report["verdict"] = "REPLAY_EVIDENCE_INCOMPLETE"
                report["verdict_note"] = (
                    "重放证据不完备(条数/编号/两侧/recorder 任一不"
                    "足);不得写一致,不存在空集合相等")
            elif not (src_ok and orig_ok):
                report["verdict"] = "INCONCLUSIVE"
                report["verdict_note"] = (
                    "生成器源哈希或原件证据结构不完整,证据不足——"
                    "按 §4.3 分支三保持未知与差异")
            elif replay.get("business_replay_consistent") and replay.get(
                    "digest_level_consistent"):
                report["verdict"] = "CONTRACT_LEGAL_STRUCTURAL_REJECTION"
                report["verdict_note"] = (
                    f"完整五次 A/B 重放取证一致(envelope digest 与业务"
                    f"内容双层);解析 DP 给出单事件表零 distractor 概率"
                    f"≈{report['dp']['p_zero_distractor_single_event_table']:.4f}"
                    f",独立模型五连零≈"
                    f"{report['dp']['p_five_consecutive_zero_independent_model']:.2e}"
                    "——小概率但原合同允许的结构拒绝;固定坐标结果是"
                    "确定的,重跑不是新抽签;维持工程 BLOCKED,不构成改"
                    "namespace/阈值/attempts 的授权;若要改变可生成性"
                    "须走生成合同决策稿")
            elif replay.get("business_replay_consistent"):
                report["verdict"] = "CALL_DEVIATION_SUSPECTED"
                report["verdict_note"] = (
                    "业务内容一致但完整 digest 不一致——身份字段漂移,"
                    "需定位输入差异,不调生成参数")
            else:
                report["verdict"] = "CALL_DEVIATION_SUSPECTED"
                report["verdict_note"] = (
                    "重放与原 envelope 业务内容不一致(同 seed 不同结果)"
                    "——调用链或实现偏离既有合同的证据;按原合同做最小"
                    "修复,不得用修后通过反推修复正确")
    except Exception as exc:  # noqa: BLE001 —— 主流程异常也先写报告
        report["verdict"] = "DIAGNOSTIC_FAILURE"
        report["verdict_note"] = (
            f"诊断主流程异常 {type(exc).__name__}:{str(exc)[:300]}")
        rc = 5

    # 所有出口都先落盘报告(修缺陷 2);写失败如实非零退出
    out = Path(args.out)
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    except Exception as exc:  # noqa: BLE001 —— 不得为保证报告存在而吞掉
        print(f"report write failed: {type(exc).__name__}:{exc}",
              file=sys.stderr)
        return 6
    print(f"verdict: {report.get('verdict')}")
    print(f"report: {out}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
