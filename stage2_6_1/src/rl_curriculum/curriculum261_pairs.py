"""阶段 2.6.1 工作包 F:C1/C2/C3 pair 构造与 pair integrity 自动验证。

Pair 合同(每个 family x rung x pair_index):
- A/B 两个 episode 由同一 seed 派生(seed 公式不含 side;pair_variant 不
  进入生成器 seed 派生),因此共享:收益噪声流 / OHLCV wick 噪声 /
  nuisance 槽位 / 段与事件时间表 / episode 长度 / 初始价格——nuisance
  相似按构造成立,并被本模块逐 pair 自动复验;
- 唯一差别是因果映射(C1 漂移有无 / C2 门控绑定 / C3 强度-收益耦合);
- pair 级尝试策略:每次 attempt 同 seed 同时生成 A/B,两端都通过结构
  性校验才算该 attempt 通过(max_attempts=5 / first_pass)。

Pair integrity 两层验证:
1. 逐 pair 确定性构造审计(主判定):共享表逐位一致 + 因果映射的
   构造级差异(从 sidecar 断言,不受实现噪声影响,只在实现出错时失败);
2. 已实现统计度量(报告证据):nuisance 波动率(vol_24 中位数,漂移不
   敏感)比值容差、A/B 已实现因果指标——进入 causality / integrity
   矩阵,在 rung/family 聚合层(20 episode 样本)检验。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_MAX_ATTEMPTS,
    CURRICULUM261_RUNGS,
    EpisodeAttemptLog,
    GeneratedEpisode,
    GeneratorError,
    PairGenerationError,
    check_attempt_log,
    generate_pair_with_attempts,
)
from rl_curriculum.curriculum261_c1 import (
    C1OpportunityGenerator,
    C1_REFERENCE_DEFAULTS,
    C1_RUNG_PARAMS,
    c1_pair_integrity_metrics,
)
from rl_curriculum.curriculum261_c2 import (
    C2ContextGatingGenerator,
    C2_REFERENCE_DEFAULTS,
    C2_RUNG_PARAMS,
    c2_pair_integrity_metrics,
)
from rl_curriculum.curriculum261_c3 import (
    C3CostAwareGenerator,
    C3_REFERENCE_DEFAULTS,
    C3_RUNG_PARAMS,
    c3_pair_integrity_metrics,
)

#: nuisance 相似容差:vol_24 中位数比值(A/B)必须落在该区间
#: (vol_24 是滚动局部 std,对常数漂移不敏感;A/B 共享噪声流 -> 应接近 1)
NUISANCE_VOL24_RATIO_RANGE = (0.75, 1.35)


@dataclass
class FamilySpec:
    """family 注册项:生成器 / rung 参数 / 参考阈值默认 / 完整性度量。"""

    family: str
    generator: Any
    rung_params: dict[str, dict[str, Any]]
    reference_defaults: dict[str, float]
    integrity_metrics: Callable[[GeneratedEpisode], dict[str, Any]]
    construction_check: Callable[
        [GeneratedEpisode, GeneratedEpisode], dict[str, Any]]


@dataclass
class PairRecord:
    """一个 qualification pair(A/B 两 episode + 尝试日志 + 完整性判定)。"""

    family: str
    rung: str
    pair_index: int
    episodes: dict[str, GeneratedEpisode]
    attempt_log: EpisodeAttemptLog
    integrity: dict[str, Any] = field(default_factory=dict)
    integrity_ok: bool = False

    def canonical(self) -> dict[str, Any]:
        return {
            "family": self.family, "rung": self.rung,
            "pair_index": int(self.pair_index),
            "attempt_log": self.attempt_log.canonical(),
            "integrity": self.integrity,
            "integrity_ok": bool(self.integrity_ok),
        }


def generate_pair(
    family: str, rung: str, pair_index: int, *,
    namespace: str,
    rung_params_override: dict[str, dict[str, Any]] | None = None,
) -> PairRecord:
    """生成一个 pair(A/B 同 seed 同 attempt)+ 自动完整性验证。"""
    if family not in family_specs():
        raise GeneratorError(f"未知 family {family!r}")
    if rung not in CURRICULUM261_RUNGS:
        raise GeneratorError(f"未知 rung {rung!r}")
    spec = family_specs()[family]
    rung_params = dict(
        (rung_params_override or {}).get(rung)
        or spec.rung_params[rung])
    # C3 的强度档按 rung 解析;rung 显式进入 params(进入 seed 派生的
    # 参数集,但同一 (family,rung) 内 A/B 与各 pair 的流一致性不受影响)
    rung_params = dict(rung_params)
    rung_params["cur261_rung"] = rung
    episodes, log = generate_pair_with_attempts(
        spec.generator, rung_params,
        namespace=namespace, family=family, rung=rung,
        pair_index=pair_index,
        structural_validator=type(spec.generator).structural_validator,
    )
    problems = check_attempt_log(log)
    if problems:
        raise GeneratorError(
            f"{family}/{rung}/p{pair_index} 尝试日志非法: {problems}")
    record = PairRecord(family=family, rung=rung, pair_index=pair_index,
                        episodes=episodes, attempt_log=log)
    record.integrity = compute_pair_integrity(record)
    record.integrity_ok = record.integrity["pass"]
    return record


# ------------------------------------------------------------ 完整性验证
def _nuisance_checks(a: GeneratedEpisode, b: GeneratedEpisode) -> dict[str, Any]:
    """nuisance 相似:长度/初始价/volume+nuisance 逐位一致/vol_24 容差。"""
    checks: dict[str, Any] = {}
    checks["same_length"] = len(a.df) == len(b.df)
    checks["same_initial_price"] = bool(
        a.df["open"].iloc[0] == b.df["open"].iloc[0])
    checks["volume_identical"] = bool(
        np.array_equal(a.df["volume"].to_numpy(),
                       b.df["volume"].to_numpy()))
    # vol_24 中位数:滚动局部 std,对 A 的漂移不敏感 -> 应接近一致
    va = float(np.median(a.df["vol_24"].to_numpy(dtype=np.float64)))
    vb = float(np.median(b.df["vol_24"].to_numpy(dtype=np.float64)))
    ratio = (va / vb) if vb > 0 else float("inf")
    checks["vol24_median_A"] = va
    checks["vol24_median_B"] = vb
    checks["vol24_ratio_in_range"] = bool(
        NUISANCE_VOL24_RATIO_RANGE[0] <= ratio <= NUISANCE_VOL24_RATIO_RANGE[1])
    checks["vol24_ratio"] = ratio
    nuisance_cols = ["nuis_0", "nuis_1", "nuis_2"]
    checks["nuisance_slots_identical"] = bool(all(
        np.array_equal(a.df[c].to_numpy(), b.df[c].to_numpy())
        for c in nuisance_cols))
    return checks


def _c1_construction_check(a: GeneratedEpisode,
                           b: GeneratedEpisode) -> dict[str, Any]:
    """C1 构造审计:A 的 opp/neg 段有真实漂移;B 的 regime 漂移恒 0。"""
    ha, hb = a.hidden, b.hidden
    states_a = ha["seg_state"].to_numpy()
    drift_a = ha["regime_drift_bps"].to_numpy()
    drift_b = hb["regime_drift_bps"].to_numpy()
    opp_drift_pos = bool(np.all(drift_a[states_a == 2] > 0))
    neg_drift_neg = bool(np.all(drift_a[states_a == 0] < 0))
    b_drift_zero = bool(np.all(np.abs(drift_b) < 1e-9))
    shared_seg = bool(np.array_equal(
        ha["seg_index"].to_numpy(), hb["seg_index"].to_numpy())
        and np.array_equal(states_a, hb["seg_state"].to_numpy()))
    return {
        "A_opp_drift_positive": opp_drift_pos,
        "A_neg_drift_negative": neg_drift_neg,
        "B_regime_drift_zero": b_drift_zero,
        "shared_segment_table": shared_seg,
        "causal_diff_ok": bool(
            opp_drift_pos and neg_drift_neg and b_drift_zero),
    }


def _c2_construction_check(a: GeneratedEpisode,
                           b: GeneratedEpisode) -> dict[str, Any]:
    """C2 构造审计:A 的收益注入符号由 G1(方向)决定;B 由波动率体制决定。

    判定:对每个 cue t,注入窗口内的 payoff_dir 与
    sign(gate[t]) x sign(cue[t]) 逐点一致;共享 banner/体制/cue 表。
    """
    ha, hb = a.hidden, b.hidden
    cue = ha["cue_dir"].to_numpy()
    g1a = ha["gate_g1"].to_numpy()
    vsa = ha["vol_state"].to_numpy()
    payoff_dir_a = ha["payoff_dir"].to_numpy()
    active_a = ha["payoff_active"].to_numpy()
    payoff_dir_b = hb["payoff_dir"].to_numpy()
    g1b = hb["gate_g1"].to_numpy()
    vsb = hb["vol_state"].to_numpy()
    H = int(a.spec.params["payoff_bars"])
    n = len(cue)

    def _binding_ok(gate: np.ndarray, payoff_dir: np.ndarray) -> bool:
        for t in range(n):
            if cue[t] == 0:
                continue
            end = min(t + 1 + H, n)
            window = slice(t + 1, end)
            if not np.any(active_a[window]):
                continue
            expect = np.sign(gate[t]) * np.sign(cue[t])
            mask = active_a[window].astype(bool)
            got = payoff_dir[window][mask]
            if not np.all(got == expect):
                return False
        return True

    a_gate_is_g1 = bool(np.all(ha["active_gate_is_g1"].to_numpy() == 1))
    b_gate_is_g2 = bool(np.all(hb["active_gate_is_g1"].to_numpy() == 0))
    shared_tables = bool(
        np.array_equal(cue, hb["cue_dir"].to_numpy())
        and np.array_equal(g1a, g1b) and np.array_equal(vsa, vsb))
    return {
        "A_gate_is_g1": a_gate_is_g1,
        "B_gate_is_vol_regime": b_gate_is_g2,
        "A_payoff_bound_to_g1": bool(_binding_ok(g1a, payoff_dir_a)),
        "B_payoff_bound_to_vol": bool(_binding_ok(vsb, payoff_dir_b)),
        "A_payoff_not_bound_to_vol": bool(
            not _binding_ok(vsa, payoff_dir_a)),
        "B_payoff_not_bound_to_g1": bool(
            not _binding_ok(g1b, payoff_dir_b)),
        "shared_cue_banner_vol_table": shared_tables,
        "causal_diff_ok": bool(
            a_gate_is_g1 and b_gate_is_g2
            and _binding_ok(g1a, payoff_dir_a)
            and _binding_ok(vsb, payoff_dir_b)
            and not _binding_ok(vsa, payoff_dir_a)
            and not _binding_ok(g1b, payoff_dir_b)
            and shared_tables),
    }


def _c3_construction_check(a: GeneratedEpisode,
                           b: GeneratedEpisode) -> dict[str, Any]:
    """C3 构造审计:A 的毛 edge 随强度严格单调且存在超成本;
    B 的毛 edge 为亚成本常数且与强度解耦;共享事件表。"""
    ha, hb = a.hidden, b.hidden
    is_sig_a = (ha["sig_dir"].to_numpy() != 0) & \
               (ha["distractor_flag"].to_numpy() == 0)
    s = ha["sig_strength"].to_numpy()[is_sig_a]
    g_a = ha["sig_gross_bps"].to_numpy()[is_sig_a]
    g_b = hb["sig_gross_bps"].to_numpy()[is_sig_a]
    # 单调:按强度排序后毛 edge 非降(构造上 G=alpha*s*H)
    order = np.argsort(s)
    monotone_a = bool(np.all(np.diff(g_a[order]) >= -1e-9))
    above_a = bool(np.count_nonzero(ha["above_cost"].to_numpy()) >= 2)
    # B:常数亚成本(方差为 0 且 < F)
    const_b = bool(np.std(g_b) < 1e-9 and np.all(g_b > 0))
    sub_cost_b = bool(np.count_nonzero(hb["above_cost"].to_numpy()) == 0)
    shared_events = bool(
        np.array_equal(ha["sig_strength"].to_numpy(),
                       hb["sig_strength"].to_numpy())
        and np.array_equal(ha["sig_dir"].to_numpy(),
                           hb["sig_dir"].to_numpy())
        and np.array_equal(ha["distractor_flag"].to_numpy(),
                           hb["distractor_flag"].to_numpy()))
    return {
        "A_gross_monotone_in_strength": monotone_a,
        "A_has_above_cost": above_a,
        "B_gross_constant": const_b,
        "B_all_below_cost": sub_cost_b,
        "shared_event_table": shared_events,
        "causal_diff_ok": bool(
            monotone_a and above_a and const_b and sub_cost_b
            and shared_events),
    }


_FAMILY_SPECS: dict[str, FamilySpec] | None = None


def family_specs() -> dict[str, FamilySpec]:
    """family 注册表(懒构造:依赖下方构造检查函数先定义)。"""
    global _FAMILY_SPECS
    if _FAMILY_SPECS is None:
        _FAMILY_SPECS = {
            spec.family: spec for spec in (
                FamilySpec("c1_opportunity", C1OpportunityGenerator(),
                           C1_RUNG_PARAMS, C1_REFERENCE_DEFAULTS,
                           c1_pair_integrity_metrics,
                           _c1_construction_check),
                FamilySpec("c2_context", C2ContextGatingGenerator(),
                           C2_RUNG_PARAMS, C2_REFERENCE_DEFAULTS,
                           c2_pair_integrity_metrics,
                           _c2_construction_check),
                FamilySpec("c3_cost", C3CostAwareGenerator(),
                           C3_RUNG_PARAMS, C3_REFERENCE_DEFAULTS,
                           c3_pair_integrity_metrics,
                           _c3_construction_check),
            )
        }
    return _FAMILY_SPECS


def compute_pair_integrity(record: PairRecord) -> dict[str, Any]:
    """逐 pair 完整性判定(确定性构造审计 + nuisance + 已实现统计)。"""
    FAMILY_SPECS_LOCAL = family_specs()
    a, b = record.episodes["A"], record.episodes["B"]
    spec = FAMILY_SPECS_LOCAL[record.family]
    nuisance = _nuisance_checks(a, b)
    construction = spec.construction_check(a, b)
    realized = {
        "A": spec.integrity_metrics(a),
        "B": spec.integrity_metrics(b),
    }
    nuisance_ok = all(
        nuisance[k] for k in
        ("same_length", "same_initial_price", "volume_identical",
         "vol24_ratio_in_range", "nuisance_slots_identical"))
    causal_ok = construction.get("causal_diff_ok", False)
    shared_ok = all(v for k, v in construction.items()
                    if k.startswith("shared_"))
    return {
        "family": record.family, "rung": record.rung,
        "pair_index": record.pair_index,
        "nuisance": nuisance,
        "construction": construction,
        "realized": realized,
        "nuisance_ok": nuisance_ok,
        "causal_diff_ok": causal_ok,
        "shared_construction_ok": shared_ok,
        "pass": bool(nuisance_ok and causal_ok and shared_ok),
    }


def generate_family_corpus(
    family: str, *, namespace: str, pairs_per_rung: int,
    rung_params_override: dict[str, dict[str, Any]] | None = None,
    rungs: tuple[str, ...] = CURRICULUM261_RUNGS,
) -> list[PairRecord]:
    """一个 family 的全部 pair(qualification:40;calibration:可缩小)。"""
    records: list[PairRecord] = []
    for rung in rungs:
        for idx in range(pairs_per_rung):
            records.append(generate_pair(
                family, rung, idx, namespace=namespace,
                rung_params_override=rung_params_override))
    return records


def attempt_statistics(records: list[PairRecord]) -> dict[str, Any]:
    """first-pass rate / attempts 分布 / 拒绝原因分布(pair 级)。"""
    logs = [r.attempt_log for r in records]
    n = len(logs)
    if n == 0:
        return {"n_pairs": 0}
    attempts_used = [
        (log.selected_attempt if log.selected_attempt is not None
         else log.max_attempts) for log in logs]
    reasons: dict[str, int] = {}
    for log in logs:
        for att in log.attempts:
            if not att.accepted and att.reason:
                for part in att.reason.split("; "):
                    key = part.strip()[:60]
                    reasons[key] = reasons.get(key, 0) + 1
    return {
        "n_pairs": n,
        "first_pass_rate": float(
            sum(1 for u in attempts_used if u == 0) / n),
        "attempts_histogram": {
            str(k): int(sum(1 for u in attempts_used if u == k))
            for k in range(CURRICULUM261_MAX_ATTEMPTS + 1)},
        "mean_attempts": float(np.mean(attempts_used)),
        "max_attempts_used": int(max(attempts_used)),
        "rejection_reasons": dict(sorted(
            reasons.items(), key=lambda kv: -kv[1])),
    }
