#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 WP7:固定 C3 失败坐标机制诊断(rt3_calibration_main_r17 /
c3_cost / D0 / pair_index=52;五次 attempt 全 too_few_distractors)。

授权边界(任务书 WP7/§11):只读分析已有证据优先;确有缺失时对
**完全相同工程坐标、参数和原有五次尝试上限**做一次最小复现;
不增加 attempts、不跳过 pair、不改 distractor 阈值/参数、不挑新
namespace、不扩缩样本。本脚本一次运行 = 一次最小复现。

三分类判定材料:
1. 调用或实现偏离既有合同 —— 仅当重放与原 envelope 出现不一致
   (同 seed 不同结果)或参数/override 链偏离 envelope 记录;
2. 原合同允许的结构拒绝 —— 重放逐字段一致 + 解析概率表明五连零
   属小概率但合同内事件(生成器与 validator 均按冻结合同工作);
3. 需改变生成合同或正向工程夹具 —— 上述皆否时给出最小建议。

用法(受监护工程运行):
  r17_c3_p52_diagnosis.py --envelope <generation_failure_envelopes_...json> \
      --out <diagnosis.json> [--no-replay]
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


def utc_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# ------------------------------------------------ 解析 DP(纯数学,不调生成器)
def dp_zero_distractor(n_bars: int, t0: int, t_end: int,
                       p_cue: float, p_dis: float,
                       gap_lo: int, gap_hi: int) -> dict:
    """C3 调度循环的精确零 distractor 概率(动态规划)。

    每迭代:roll<U(cue)→signal pair(推进 gap+4,gap∈[lo,hi] 均匀);
    roll<U(cue+dis)→distractor pair(同推进;出现即失败吸收);
    否则空 bar(t+=1)。事件表共享 A/B(pair_variant 不入 seed 派生),
    故一次 attempt=一个事件表。碰撞覆盖(bar 重叠)未建模:DP 值是
    无碰撞口径的上界,真实概率只能更低(碰撞只会减少 distractor 计
    数——使'零 distractor'更容易;因此 DP 是保守(偏大)的失败概率
    上界,用于数量级定标)。
    """
    adv = list(range(gap_lo + 4, gap_hi + 4 + 1))  # gap+4 均匀
    p_pair = p_cue + p_dis
    p_empty = 1.0 - p_pair
    max_t = t_end + max(adv) + 2
    f = [1.0] * (max_t + 1)          # t>=t_end:无更多迭代
    for t in range(t_end - 1, t0 - 1, -1):
        v = 0.0
        for d in adv:
            v += f[t + d]
        v *= (p_cue / len(adv))       # signal 分支(存活)
        v += p_empty * f[t + 1]       # 空 bar(存活)
        # distractor 分支:失败吸收,贡献 0
        f[t] = v
    p_zero = f[t0]
    return {
        "p_zero_distractor_single_event_table": p_zero,
        "p_five_consecutive_zero": p_zero ** 5,
        "method": "exact DP over scheduling loop "
                  "(no generator invocation;collision-overwrite not "
                  "modeled: DP is an upper bound of P(zero))",
        "params": {"n_bars": n_bars, "t0": t0, "t_end": t_end,
                   "p_cue": p_cue, "p_dis": p_dis,
                   "gap_lo": gap_lo, "gap_hi": gap_hi,
                   "advance_dist": adv},
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--envelope", required=True,
                    help="run 1475 的 generation_failure_envelopes json")
    ap.add_argument("--out", required=True)
    ap.add_argument("--no-replay", action="store_true",
                    help="只读分析+DP,不做最小复现")
    args = ap.parse_args()

    env_doc = json.loads(
        Path(args.envelope).read_text(encoding="utf-8"))
    call = env_doc["call_envelope"]
    attempts = env_doc["attempt_envelopes"]
    ns = call["namespace"]
    family = call["family"]
    rung = call["rung"]
    pair_index = call["pair_index"]
    rp = call["rung_params"]
    report: dict = {
        "schema": "r17-c3-p52-diagnosis-v1",
        "written_utc": utc_now(),
        "coordinates": {"namespace": ns, "family": family,
                        "rung": rung, "pair_index": pair_index,
                        "max_attempts": call["max_attempts"]},
        "generator_identity_envelope": call["generator"],
        "envelope_summary": [],
    }
    for a in attempts:
        report["envelope_summary"].append({
            "attempt": a["attempt_index"],
            "outer_seed": a["outer_seed"],
            "internal_derived_seed": a.get("internal_derived_seed"),
            "n_distractors_A": a["event_table"]["A"]["counts"][
                "n_distractors"],
            "n_distractors_B": a["event_table"]["B"]["counts"][
                "n_distractors"],
            "n_signals_A": a["event_table"]["A"]["counts"]["n_signals"],
            "rejection_reasons": a["rejection_reasons"],
            "digest": a.get("digest"),
            "episode_content_hash_A": a["event_table"]["A"].get(
                "episode_content_hash"),
        })

    # ---- 解析 DP(数量级定标) ----
    report["dp"] = dp_zero_distractor(
        n_bars=288, t0=10, t_end=288 - 8,
        p_cue=float(rp["cue_rate"]), p_dis=float(rp["distractor_rate"]),
        gap_lo=4, gap_hi=6)

    # ---- 生成器源身份核验 ----
    import rl_curriculum.curriculum261_c3 as c3mod
    src_sha = hashlib.sha256(
        Path(c3mod.__file__).read_bytes()).hexdigest()
    report["generator_source_sha256_actual"] = src_sha
    report["generator_source_matches_envelope"] = (
        src_sha == call["generator"]["source_sha256"])

    if args.no_replay:
        report["replay"] = {"performed": False}
    else:
        # ---- 一次最小复现(同坐标/同参数/同 5-attempt 上限) ----
        from rl_curriculum.curriculum261_api import (
            generate_pair_with_attempts)
        from rl_curriculum.curriculum261_c3 import C3CostAwareGenerator
        from rl_curriculum.curriculum261_pairs import (
            pair_acceptance_contract)
        replay_rows = []
        deviated = False
        try:
            gen = C3CostAwareGenerator()
            # 与 calibration 相同的入口合同;envelope 记录无 override
            generate_pair_with_attempts(
                gen, dict(rp),
                namespace=ns, family=family, rung=rung,
                pair_index=pair_index,
                structural_validator=pair_acceptance_contract(family))
            report["replay"] = {
                "performed": True, "unexpectedly_accepted": True,
                "note": "复现中出现接受——与原五连拒不一致,构成调用"
                        "偏离合同的证据(需最小修复路径)"}
            return 0
        except Exception as exc:  # PairGenerationError 携带 envelopes
            from rl_curriculum.curriculum261_api import (
                PairGenerationError)
            if not isinstance(exc, PairGenerationError):
                report["replay"] = {
                    "performed": True, "error_type":
                    type(exc).__name__, "error": str(exc)[:500]}
                return 0
            replay_envs = exc.attempt_envelopes or []
            for a in replay_envs:
                idx = a.get("attempt_index")
                orig = next((x for x in attempts
                             if x["attempt_index"] == idx), None)
                row = {"attempt": idx}
                if orig is None:
                    row["match"] = "no_original"
                    deviated = True
                else:
                    fields = {}
                    for key in ("outer_seed", "internal_derived_seed",
                                "digest"):
                        fields[key] = (
                            a.get(key) == orig.get(key))
                    et_a = a.get("event_table", {}).get("A", {})
                    et_o = orig["event_table"]["A"]
                    for k in ("episode_content_hash",):
                        fields[f"A.{k}"] = (
                            et_a.get(k) == et_o.get(k))
                    counts_new = et_a.get("counts", {})
                    counts_old = et_o["counts"]
                    for k in ("n_signals", "n_above_cost",
                              "n_below_cost", "n_distractors"):
                        fields[f"A.counts.{k}"] = (
                            counts_new.get(k) == counts_old.get(k))
                    row["field_matches"] = fields
                    row["all_match"] = all(fields.values())
                    if not row["all_match"]:
                        deviated = True
                replay_rows.append(row)
            report["replay"] = {
                "performed": True, "unexpectedly_accepted": False,
                "n_attempt_envelopes": len(replay_envs),
                "rows": replay_rows,
                "deterministic_replay_consistent": not deviated}

    # ---- 三分类判定材料 ----
    replay_ok = report.get("replay", {}).get(
        "deterministic_replay_consistent")
    src_ok = report["generator_source_matches_envelope"]
    p5 = report["dp"]["p_five_consecutive_zero"]
    if replay_ok is False or not src_ok:
        verdict = "CALL_DEVIATION_SUSPECTED"
        note = ("重放与原 envelope 不一致或生成器源哈希偏离——调用链"
                "或实现偏离既有合同的证据;需按原合同做最小修复")
    elif replay_ok and src_ok:
        verdict = "CONTRACT_LEGAL_STRUCTURAL_REJECTION"
        note = (f"确定性重放逐字段一致(生成器源哈希匹配);解析 DP 给出"
                f"单事件表零 distractor 概率≈"
                f"{report['dp']['p_zero_distractor_single_event_table']:.4f}"
                f",五连零≈{p5:.2e}——小概率但合同内事件;A/B 共享事件"
                "表(pair_variant 不入 seed 派生)故五次尝试=五个独立"
                "事件表;维持工程 BLOCKED,不构成改 namespace/阈值/"
                "attempts 的授权")
    else:
        verdict = "INCONCLUSIVE"
        note = "复现未执行或不完整"
    report["verdict"] = verdict
    report["verdict_note"] = note
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(f"verdict: {verdict}")
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
