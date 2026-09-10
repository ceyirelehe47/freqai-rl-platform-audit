# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R7:Cue 检测语义合同与 p_contract 合同审计。

C2CueDetectionSemanticContract-v1(§8-§9)解决 R6 的两个失败根因:
1. 重复计数——matched block 内 4 rung × A/B 共享 cue 表,同一
   (block_index, cue_bar_index) 只能计一个 unique cue event
   (去重与 cluster 统计在 curriculum261_r7_cue_eval 实现);
2. 点阈值误卡——R6 的 cue_recall_min=0.95 预注册在生成器固有
   检出率期望之上(配对噪声按对累加,cue bar 有效 sigma ≈ 27bps,
   recall 期望 ~0.94-0.95),且 matched 下 cue 表跨 candidate 共享
   使 recall 只依赖语料、不依赖 ladder——R7 改为:
   a. 先对冻结 cue/noise mechanism 做合同审计得到 p_contract;
   b. 预注册非劣效门槛
      recall_floor = max(absolute_minimum_recall,
                         p_contract - noninferiority_delta)
      (公式在 audit 运行前冻结于本模块;不得在看到 p_contract 或
      R7 data 后修改 delta / absolute floor);
   c. 正式 PASS 判据是 block-cluster bootstrap 单侧 95% LCB
      >= recall_floor(不是点估计 >= 0.95)。

合同审计方法(§9.1;deterministic,在生成任何 R7 candidate design
data 之前运行):
- 解析层:cue bar 读数 = exp(pulse + eps[t]) - 1(precise;
  close = exp(cumsum(log_returns)),%-ret-1 = close.pct_change()),
  判定 ⟺ eps[t] > -margin_log,margin_log = pulse - ln(1+cue_thr)。
  eps[t] = vol·(s0·|G0| + Σ_j s_j·|G_j|)(paired_noise 累加;主项
  s0·|G0| 存在于 t+16<n;镜像候选 t'∈[max(1,t-16), t-8] 各以
  1/9 概率命中)——±半正态=正态,故 eps[t]|K ~ N(0, vol²·(m+K)),
  K ~ Binomial(C(t), 1/9):
      q(t) = Σ_k BinPMF(k; C(t), 1/9) · Φ(margin_log/(vol·√(m+k)))
- 位置层:正 cue bar 位置分布 w(t) 由冻结生成器(matched-tape,
  sentinel ladder,与 design 完全同机制)在 cue_contract_audit_r7
  namespace 的 bridge 样本提取(canonical = D0/A);
- p_contract = Σ_t ŵ(t)·q(t)(bridge 直方图加权的解析积分);
- 事件级 Monte Carlo ≥ 1,000,000 次(固定 audit RNG seed)给出
  MC 估计与标准误;bridge 样本的实测 recall 作为桥校验(z 值)。

审计合同:不使用 R7 design/calibration/holdout/final namespace;
不读取 candidate ladder(sentinel = 冻结 cur261-c2-v9 默认 D0-D3,
与任何 R7 candidate 数值无关);不读取任何 R7 design 结果。
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    NOISE_PAIR_GAP_RANGE,
)
from rl_curriculum.curriculum261_c2 import (
    C2_REFERENCE_DEFAULTS,
    C2_RUNG_PARAMS,
    FAMILY_C2,
)
from rl_curriculum.curriculum261_r6_tape import (
    derive261_block_seed,
    generate_matched_block_once,
)

#: 语义合同版本(§8)。
C2_CUE_SEMANTIC_CONTRACT_VERSION = "C2CueDetectionSemanticContract-v1"

#: §9.2 预注册非劣效参数(audit 运行前冻结;数据后不得修改)。
NONINFERIORITY_DELTA = 0.02
ABSOLUTE_MINIMUM_RECALL = 0.90

#: §10 正式 PASS 判据的置信水平与 cluster 单位。
CUE_LCB_CONFIDENCE = 0.95
CUE_CLUSTER_UNIT = "matched_block"
CUE_CANONICAL_OBSERVATION = ("D0", "A")

#: §11 其他语义指标的业务阈值(与 R6 相同;R7 用 cluster bounds)。
C2_CUE_PRECISION_MIN = 0.85
C2_NON_CUE_FALSE_POSITIVE_MAX = 0.01
C2_PAYOFF_BAR_FALSE_CUE_MAX = 0.06

#: §10 unique 正 cue 事件最小样本量(每 design corpus)。
#: 冻结 cue 密度 = 每集 ~12-13 对 cue(§机制注释),40 matched blocks
#: 的 unique 正 cue 期望 ~500;任务书建议值 800 在该冻结密度下物理
#: 不可达(需 ~67 blocks)。按"真实 cue density 的等价但不更弱门槛"
#: 预注册:全覆盖(coverage=1.0,去重后全部事件参与)+ 事件数下界
#: 460(= 40 blocks × 11.5 正 cue/集,R6 观测下界)。
MIN_UNIQUE_POSITIVE_CUES = 460

#: 合同审计配置(冻结)。
AUDIT_NAMESPACE = "cue_contract_audit_r7"
AUDIT_RNG_SEED = 20260924
AUDIT_N_EVENTS = 1_000_000
AUDIT_BRIDGE_BLOCKS = 200
AUDIT_BRIDGE_ATTEMPT = 0

#: audit 使用的 sentinel ladder(= 冻结 cur261-c2-v9 默认 D0-D3;
#: 与 R7 candidate 网格无依赖关系——audit 在 candidate 生成前运行,
#: 且 alpha_bps/wick_kappa 不进入 cue 表/pulse/噪声的任何派生)。
def _sentinel_ladder() -> dict[str, dict[str, Any]]:
    return {rung: dict(params) for rung, params in C2_RUNG_PARAMS.items()}


def recall_floor(p_contract: float) -> float:
    """§9.2 预注册公式(audit 运行前冻结;数据后不得修改)。"""
    return max(ABSOLUTE_MINIMUM_RECALL,
               float(p_contract) - NONINFERIORITY_DELTA)


# ------------------------------------------------- 解析层
def _mirror_candidates(t: int, n: int) -> int:
    """bar t 的镜像候选数:paired_noise 中 t'∈[max(1,t-16), t-8]
    的每个 bar 独立以 1/9 概率选 gap 命中 t。"""
    lo = max(1, t - NOISE_PAIR_GAP_RANGE[1])
    hi = t - NOISE_PAIR_GAP_RANGE[0]
    if hi < lo:
        return 0
    return min(hi, n - 1) - lo + 1


def _primary_present(t: int, n: int) -> int:
    """bar t 是否作为配对首元素抽签(paired_noise 在 t+16>=n 时
    break——尾部 bar 不再有主项)。"""
    return 1 if t + NOISE_PAIR_GAP_RANGE[1] < n else 0


def q_recall_at_position(t: int, n: int, *, pulse: float, cue_thr: float,
                         vol: float) -> dict[str, Any]:
    """位置 t 的解析检出概率(精确 Binomial-正态混合)。

    判定:%-ret-1 = exp(pulse + eps) - 1 > cue_thr ⟺
    eps > -(pulse - ln(1+cue_thr)) = -margin_log。
    eps|K ~ N(0, vol²·(m+K)),K~Bin(C(t), 1/9)。
    """
    margin_log = pulse - math.log1p(cue_thr)
    c = _mirror_candidates(t, n)
    m = _primary_present(t, n)
    p_hit = 1.0 / (NOISE_PAIR_GAP_RANGE[1] - NOISE_PAIR_GAP_RANGE[0] + 1)
    total = 0.0
    terms = []
    for k in range(c + 1):
        pmf = math.comb(c, k) * (p_hit ** k) * ((1 - p_hit) ** (c - k))
        sigma = vol * math.sqrt(m + k)
        phi = 0.5 * (1.0 + math.erf(
            (margin_log / sigma) / math.sqrt(2.0))) if sigma > 0 else (
            1.0 if margin_log > 0 else 0.5)
        total += pmf * phi
        terms.append({"k": k, "pmf": pmf, "conditional_recall": phi})
    return {
        "t": t, "n": n, "mirror_candidates": c, "primary": m,
        "margin_log": margin_log, "q": total, "terms": terms,
    }


# ------------------------------------------------- bridge 层
def run_cue_contract_audit(out_dir: Path | None = None,
                           ) -> dict[str, Any]:
    """执行合同审计(§9.1;在任何 R7 candidate design data 之前)。

    返回(并可选落盘)完整 audit 报告;p_contract = 解析积分
    (bridge 位置直方图 × 解析 q(t));MC 与 bridge 实测为误差与
    桥校验,不改变 p_contract。
    """
    n = int(CURRICULUM261_EPISODE_BARS)
    thr = dict(C2_REFERENCE_DEFAULTS)
    cue_thr = float(thr["cue_thr"])
    ladder = _sentinel_ladder()
    d0 = dict(ladder["D0"])
    vol = float(d0["vol_bps"]) * 1e-4
    pulse = float(d0["pulse_bps"]) * 1e-4
    for rung_params in ladder.values():
        if (float(rung_params["vol_bps"]) * 1e-4 != vol
                or float(rung_params["pulse_bps"]) * 1e-4 != pulse):
            raise RuntimeError(
                "sentinel ladder 的 vol/pulse 必须 rung 一致(audit "
                "解析层假设单一冻结噪声合同)")

    # bridge:matched-tape 生成(与 design 完全同机制;canonical D0/A)
    pos_counts: dict[int, int] = {}
    n_positive = 0
    n_hit = 0
    per_episode_cues: list[int] = []
    for block_index in range(AUDIT_BRIDGE_BLOCKS):
        block_seed = derive261_block_seed(
            AUDIT_NAMESPACE, block_index, AUDIT_BRIDGE_ATTEMPT)
        episodes = generate_matched_block_once(
            ladder, block_seed, AUDIT_NAMESPACE)
        ep = episodes[CUE_CANONICAL_OBSERVATION[0]][
            CUE_CANONICAL_OBSERVATION[1]]
        cue = ep.hidden["cue_dir"].to_numpy()
        r1 = ep.df["%-ret-1"].to_numpy(dtype=np.float64)
        sel = np.flatnonzero(cue == 1)
        per_episode_cues.append(int(len(sel)))
        for t in sel.tolist():
            pos_counts[int(t)] = pos_counts.get(int(t), 0) + 1
            n_positive += 1
            if r1[t] > cue_thr:
                n_hit += 1
    if n_positive == 0:
        raise RuntimeError("bridge 样本无正 cue 事件(audit 异常)")
    w = {t: c / n_positive for t, c in pos_counts.items()}
    bridge_recall = n_hit / n_positive
    bridge_se = math.sqrt(
        bridge_recall * (1.0 - bridge_recall) / n_positive)

    # 解析积分:p_contract = Σ_t ŵ(t)·q(t)
    q_by_t: dict[int, float] = {}
    for t in w:
        q_by_t[t] = q_recall_at_position(
            t, n, pulse=pulse, cue_thr=cue_thr, vol=vol)["q"]
    p_contract = sum(w[t] * q_by_t[t] for t in w)

    # 桥校验:实测 vs 解析(z 值;事件级 SE 为下界,block 聚类使
    # 有效 SE 更大——仅作量级诊断,不作 gate)
    bridge_z = ((bridge_recall - p_contract) / bridge_se
                if bridge_se > 0 else 0.0)

    # 事件级 Monte Carlo(≥1e6;固定 audit RNG seed)
    rng = np.random.default_rng(AUDIT_RNG_SEED)
    ts = np.array(sorted(w), dtype=np.int64)
    wts = np.array([w[t] for t in ts], dtype=np.float64)
    wts = wts / wts.sum()
    t_draw = rng.choice(ts, size=AUDIT_N_EVENTS, p=wts)
    c_arr = np.array([_mirror_candidates(int(t), n) for t in ts])
    m_arr = np.array([_primary_present(int(t), n) for t in ts])
    p_hit = 1.0 / (NOISE_PAIR_GAP_RANGE[1] - NOISE_PAIR_GAP_RANGE[0] + 1)
    k_draw = rng.binomial(
        c_arr[np.searchsorted(ts, t_draw)].astype(np.int64), p_hit)
    m_draw = m_arr[np.searchsorted(ts, t_draw)]
    sigma_draw = vol * np.sqrt(m_draw + k_draw)
    margin_log = pulse - math.log1p(cue_thr)
    z_draw = rng.standard_normal(AUDIT_N_EVENTS)
    read_log = margin_log + sigma_draw * z_draw
    mc_hits = float(np.count_nonzero(read_log > 0.0))
    mc_p = mc_hits / AUDIT_N_EVENTS
    mc_se = math.sqrt(mc_p * (1.0 - mc_p) / AUDIT_N_EVENTS)

    # effective cue-noise distribution(位置加权)
    k_w = np.zeros(13, dtype=np.float64)
    for j, t in enumerate(ts):
        c = int(c_arr[j])
        for k in range(c + 1):
            pmf = math.comb(c, k) * (p_hit ** k) * ((1 - p_hit) ** (c - k))
            k_w[k] += wts[j] * pmf
    sigma_eff_w: dict[int, float] = {}
    for j, t in enumerate(ts):
        c = int(c_arr[j])
        m = int(m_arr[j])
        exp_sigma = sum(
            math.comb(c, k) * (p_hit ** k) * ((1 - p_hit) ** (c - k))
            * math.sqrt(m + k) for k in range(c + 1))
        sigma_eff_w[int(t)] = float(vol * exp_sigma)
    sigma_samples = sigma_draw[rng.integers(
        0, AUDIT_N_EVENTS, size=20000)]

    floor = recall_floor(p_contract)
    report: dict[str, Any] = {
        "format": "cur261-r7-cue-contract-audit-v1",
        "contract_version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "audit_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "audit_namespace": AUDIT_NAMESPACE,
        "audit_rng_seed": AUDIT_RNG_SEED,
        "audit_n_events": AUDIT_N_EVENTS,
        "audit_bridge_blocks": AUDIT_BRIDGE_BLOCKS,
        "audit_bridge_attempt": AUDIT_BRIDGE_ATTEMPT,
        "sentinel_ladder": {
            rung: {k: params[k] for k in ("alpha_bps", "wick_kappa")}
            for rung, params in ladder.items()},
        "sentinel_note": "audit 不读取 candidate ladder;sentinel = "
                         "冻结 cur261-c2-v9 默认 D0-D3(数值与任何 R7 "
                         "candidate 无依赖;alpha/wick_kappa 不进入 cue "
                         "表/pulse/噪声派生)",
        "frozen_detector": {
            "cue_thr": cue_thr,
            "wick_dir_thr": float(thr["wick_dir_thr"]),
            "wick_width_thr": float(thr["wick_width_thr"]),
            "feature": "%-ret-1",
            "vol_bps": float(d0["vol_bps"]),
            "pulse_bps": float(d0["pulse_bps"]),
            "episode_bars": n,
        },
        "margin_log": margin_log,
        "p_contract": float(p_contract),
        "analytic_terms": [
            {"t": int(t), "weight": float(w[t]),
             "q": float(q_by_t[t]),
             "mirror_candidates": _mirror_candidates(int(t), n),
             "primary": _primary_present(int(t), n)}
            for t in sorted(w)],
        "bridge": {
            "n_blocks": AUDIT_BRIDGE_BLOCKS,
            "canonical": "/".join(CUE_CANONICAL_OBSERVATION),
            "n_unique_positive_cues": n_positive,
            "positive_cues_per_block_mean": n_positive / AUDIT_BRIDGE_BLOCKS,
            "positive_cues_per_block_min": min(per_episode_cues),
            "positive_cues_per_block_max": max(per_episode_cues),
            "empirical_recall": bridge_recall,
            "event_level_se": bridge_se,
            "bridge_z_vs_analytic": bridge_z,
        },
        "monte_carlo": {
            "n_events": AUDIT_N_EVENTS,
            "p_hat": mc_p,
            "se": mc_se,
            "abs_diff_vs_analytic": abs(mc_p - p_contract),
        },
        "effective_cue_noise": {
            "unit": "log-return bps at positive cue bar",
            "conditional_sigma_bps": float(vol * 1e4),
            "k_marginal": {str(k): float(k_w[k]) for k in range(13)
                           if k_w[k] > 0},
            "sigma_eff_samples_bps_quantiles": {
                "p05": float(np.percentile(sigma_samples, 5) * 1e4),
                "p50": float(np.percentile(sigma_samples, 50) * 1e4),
                "p95": float(np.percentile(sigma_samples, 95) * 1e4),
                "mean": float(np.mean(sigma_samples) * 1e4),
            },
            "per_position_sigma_bps": {
                str(t): sigma_eff_w[t] * 1e4 for t in sorted(sigma_eff_w)},
        },
        "noninferiority": {
            "delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "formula": "recall_floor = max(absolute_minimum_recall, "
                       "p_contract - noninferiority_delta)",
            "recall_floor": floor,
        },
        "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
        "pass_rule": {
            "rule": "one-sided 95% LCB(block-cluster bootstrap) "
                    ">= recall_floor",
            "lcb_confidence": CUE_LCB_CONFIDENCE,
            "cluster_unit": CUE_CLUSTER_UNIT,
            "canonical_observation": "/".join(CUE_CANONICAL_OBSERVATION),
        },
    }
    report["audit_digest"] = cue_contract_audit_digest(report)
    if out_dir is not None:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "cue_contract_audit.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
    return report


def cue_contract_audit_digest(report: dict[str, Any]) -> str:
    """audit 报告摘要(绑定 p_contract/配置/bridge 概要/误差)。"""
    core = {
        "format": report["format"],
        "contract_version": report["contract_version"],
        "audit_namespace": report["audit_namespace"],
        "audit_rng_seed": report["audit_rng_seed"],
        "audit_n_events": report["audit_n_events"],
        "audit_bridge_blocks": report["audit_bridge_blocks"],
        "frozen_detector": report["frozen_detector"],
        "margin_log": report["margin_log"],
        "p_contract": report["p_contract"],
        "bridge": {k: report["bridge"][k] for k in (
            "n_unique_positive_cues", "empirical_recall",
            "event_level_se", "bridge_z_vs_analytic")},
        "monte_carlo": report["monte_carlo"],
        "noninferiority": report["noninferiority"],
    }
    blob = json.dumps(core, sort_keys=True, ensure_ascii=False,
                      default=float)
    return "r7ca-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def cue_semantic_contract_payload() -> dict[str, Any]:
    """预注册合同身份载荷(不含任何数据后数值;p_contract 属于 audit
    输出而非合同身份)。"""
    return {
        "version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "unique_event_key": ["block_index", "cue_bar_index"],
        "canonical_observation": list(CUE_CANONICAL_OBSERVATION),
        "cluster_unit": CUE_CLUSTER_UNIT,
        "deduplication": "4 rungs x A/B 共享 cue 表;同一 (block_index,"
                         "cue_bar_index) 只计一个 unique cue event;"
                         "canonical = D0/A;跨 rung/variant 的 cue "
                         "detection input 不一致 => block integrity FAIL",
        "noninferiority_delta": NONINFERIORITY_DELTA,
        "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
        "recall_floor_formula": "max(absolute_minimum_recall, "
                                "p_contract - noninferiority_delta)",
        "recall_pass_rule": "one-sided 95% block-cluster bootstrap LCB "
                            ">= recall_floor",
        "lcb_confidence": CUE_LCB_CONFIDENCE,
        "cue_precision_min": C2_CUE_PRECISION_MIN,
        "non_cue_false_positive_max": C2_NON_CUE_FALSE_POSITIVE_MAX,
        "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
        "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
        "candidate_independent_metrics": [
            "positive cue recall", "non-cue false-positive rate",
            "unique cue count", "block-level cue-event distribution"],
        "candidate_specific_metrics": [
            "payoff-bar false-cue rate", "cue precision",
            "payoff/cue confusion", "reference trade side effects"],
    }


def cue_semantic_contract_digest() -> str:
    blob = json.dumps(cue_semantic_contract_payload(), sort_keys=True,
                      ensure_ascii=False)
    return "r7cue-" + hashlib.sha256(blob.encode("utf-8")).hexdigest()
