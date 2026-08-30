"""阶段 2.6.1 工作包 E:C3 — Cost-Aware Selectivity(成本敏感择时)课程族。

C3 教的能力:**有预测 edge 不代表应该交易;只有扣除真实 Route C 摩擦
以后仍值得承担仓位时才交易。**

世界模型:
- 信号事件(泊松 + 最小间隔):强度 s(三档混合:strong/marginal/weak)、
  方向 d=+-1 等概率;注入 2 bar 可见脉冲 d x s x k(策略通过 ret_2
  可读到的"信号强度"——强度可见性与收益耦合完全解耦);
- 收益注入(variant A):事件后 H bar 内每 bar 追加 drift = d x alpha x s,
  单次事件的总毛 edge G(s) = alpha x s x H(对数单位);
- 摩擦 F 只取自 null_friction.ledger_round_trip_retention(冻结账本
  的唯一可审计来源;fee=0.001/slip=0 时 F = 0.001998002);
- 可交易判据:G(s) > F。参考策略的强度阈值 s* = m x F / (alpha x H)
  (m 为安全边际),由冻结摩擦公式推导——不存在"课程专用成本模型";
- distractor 事件:可见脉冲、零收益(纯 churn 诱惑);
- weak/marginal 信号:毛 edge 为正但 G < F("gross signal 看似有利,
  但扣费后不值得改变仓位")。

pair 机制(variant B,收益解耦孪生):
- 与 A 共享同一事件表 / 强度 / 方向 / 脉冲 / 噪声流 / wick / nuisance;
- 唯一差别:收益注入改为与强度**无关**的常数 beta = 0.3F / H
  (方向仍与脉冲一致)——所有信号的毛 edge 都为正但都低于成本,
  且强度不再携带任何收益信息(因果映射从"单调升穿成本线"变为
  "与强度无关的亚成本常数")。

难度阶梯:强信号占比下降、marginal(跨在阈值两侧)占比上升、
distractor 率上升、噪声上升;强档 G 始终 > 2F(保证 pair 聚合上
cost-aware reference 为正,拒绝无信号化)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    Curriculum261Base,
    GeneratorError,
    paired_noise,
)
from rl_curriculum.null_friction import ledger_round_trip_retention
from rl_curriculum.policy_api import (
    ObservableBaselinePolicy,
    OracleActContext,
    OraclePolicy,
)

FAMILY_C3 = "c3_cost"

#: 冻结账本往返摩擦(单一来源;fee=0.001、slip=0、tick=0 -> ~0.001998)
FRICTION = 1.0 - ledger_round_trip_retention(fee=0.001, slippage=0.0)
FRICTION_BPS = FRICTION * 1e4

#: 脉冲可见度常数:每单位强度 s 的单 bar 脉冲幅值(bps)。
#: k=160:强档脉冲 248-296bps(~14-sigma @ vol 18bps),参考阈值 ~4-sigma,
#: 噪声假触发率 ~0;同时控制脉冲流的价格水平方差(配合事件配对)。
C3_PULSE_K_BPS = 160.0

#: 事件配对合同:每个事件(信号或 distractor)在 gap U[C3_PAIR_GAP]
#: 根 bar 后跟一个**同强度、反方向**的镜像事件(gap >= 4 保证在
#: close[t] 入场的阈值策略于镜像脉冲到达前已完成一轮退出)——两个事件都是真实的
#: 世界事件(各自携带 d x G(s) 的收益注入),脉冲与收益对价格水平的
#: 净影响成对抵消(无净漂移、无持续回吐漂移可搭乘),Always Long
#: 的净收益方差被结构性抑制。
C3_PAIR_GAP = (4, 6)

#: C3 专用价格水平回拉(抑制残余水平方差;0.02/bar 的回拉漂移
#: <= ~3.2bps/bar,远小于摩擦)
C3_LEVEL_PULL_THETA = 0.02

#: 强度档(全 rung 固定;难度只来自 mixture 与 distractor 率)
#: strong: G_eff = 79-94bps(4.0-4.7F);marginal: 9-24bps(跨在成本线
#: 与参考阈值两侧);weak: 2.5-6bps(纯亚成本纹理)
C3_STRENGTH_BINS: dict[str, tuple[float, float]] = {
    "strong": (1.55, 1.85), "marginal": (0.18, 0.48), "weak": (0.16, 0.24),
}
#: distractor 脉冲强度(51-72bps:高于 cost-ignorant 阈值、低于参考阈值)
C3_DISTRACTOR_S_RANGE = (0.24, 0.33)

#: C3 rung 参数(候选;最终值由 calibration 固定并进入 plan)。
#: 收益注入为单 bar(H=1):事件后 1 根 bar 内注入 d x alpha x s。
#: cue_rate 为"事件对"的每 bar 到达率(对内 gap 另行采样)。
C3_RUNG_PARAMS: dict[str, dict[str, Any]] = {
    "D0": {"alpha_bps": 64.0, "payoff_bars": 1, "vol_bps": 18.0,
           "cue_rate": 0.090, "mixture": [0.60, 0.25, 0.15],
           "distractor_rate": 0.015},
    "D1": {"alpha_bps": 62.0, "payoff_bars": 1, "vol_bps": 18.0,
           "cue_rate": 0.095, "mixture": [0.42, 0.33, 0.25],
           "distractor_rate": 0.025},
    "D2": {"alpha_bps": 57.0, "payoff_bars": 1, "vol_bps": 18.0,
           "cue_rate": 0.100, "mixture": [0.32, 0.36, 0.32],
           "distractor_rate": 0.035},
    "D3": {"alpha_bps": 54.0, "payoff_bars": 1, "vol_bps": 18.0,
           "cue_rate": 0.105, "mixture": [0.27, 0.38, 0.35],
           "distractor_rate": 0.045},
}
#: variant B:收益注入常数(与强度无关),可捕获毛 edge = 0.3 x F(亚成本)
C3_B_PAYOFF_FRACTION = 0.3

#: 参考策略安全边际(阈值推导:G(s*) = m x F);cost-ignorant 的
#: "任意可见信号"阈值(s=0.30 -> 48bps ~ 2.7-sigma,追一切可见信号)
C3_REFERENCE_DEFAULTS = {"margin": 1.15, "any_signal_s": 0.22}


def c3_capture_per_s(rung_params: dict[str, Any]) -> float:
    """每单位强度的可捕获毛 edge(bps):事件收益注入无回拉拖拽,
    open[t+1] 买、close[t+1] 卖恰好捕获 alpha x s。"""
    return float(rung_params["alpha_bps"])


C3_REJECT_VOCAB = (
    "too_few_signals", "too_few_above_cost_signals",
    "too_few_below_cost_signals", "missing_signal_directions",
    "too_few_distractors",
)
C3_MIN_SIGNALS = 6
C3_MIN_ABOVE_COST = 2
C3_MIN_BELOW_COST = 2
C3_MIN_DISTRACTORS = 1


class C3CostAwareGenerator(Curriculum261Base):
    """C3 生成器:脉冲可见 x 收益耦合世界 + 亚成本解耦 variant。"""

    family = FAMILY_C3
    family_version = "cur261-c3-v1"
    hidden_columns = [
        "sig_strength", "sig_dir", "sig_gross_bps", "above_cost",
        "distractor_flag", "payoff_active", "payoff_dir", "payoff_gross_bps",
    ]

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
        variant = str(params.get("pair_variant", "A"))
        if variant not in ("A", "B"):
            raise GeneratorError(f"非法 pair_variant {variant!r}")
        alpha = float(params["alpha_bps"])
        H = int(params["payoff_bars"])
        vol = float(params["vol_bps"]) * 1e-4
        cue_rate = float(params["cue_rate"])
        mixture = np.asarray(params["mixture"], dtype=float)
        dis_rate = float(params["distractor_rate"])
        k = C3_PULSE_K_BPS * 1e-4
        bins = [C3_STRENGTH_BINS[b] for b in ("strong", "marginal", "weak")]
        # 事件表(A/B 共享):事件以 "+- 配对"调度——首个事件方向 d、
        # 强度 s;gap U[2,4] bar 后跟镜像事件(-d, 同 s);distractor 同样
        # 配对(镜像事件也是 distractor)。脉冲与收益注入对价格水平的
        # 净影响成对抵消。
        events: list[tuple[int, float, int, bool]] = []

        def _emit(t: int, s: float, d: int, is_dis: bool):
            events.append((t, s, d, is_dis))

        t = 10
        while t < n - 8:
            roll = rng.random()
            if roll < cue_rate:
                b = int(rng.choice(3, p=mixture / mixture.sum()))
                s = float(rng.uniform(bins[b][0], bins[b][1]))
                d = 1 if rng.random() < 0.5 else -1
                gap = int(rng.integers(C3_PAIR_GAP[0], C3_PAIR_GAP[1] + 1))
                _emit(t, s, d, False)
                _emit(min(t + gap, n - 1), s, -d, False)
                t += gap + 6
            elif roll < cue_rate + dis_rate:
                s = float(rng.uniform(*C3_DISTRACTOR_S_RANGE))
                d = 1 if rng.random() < 0.5 else -1
                gap = int(rng.integers(C3_PAIR_GAP[0], C3_PAIR_GAP[1] + 1))
                _emit(t, s, d, True)
                _emit(min(t + gap, n - 1), s, -d, True)
                t += gap + 6
            else:
                t += 1

        sig_strength = np.zeros(n)
        sig_dir = np.zeros(n, dtype=int)
        sig_gross = np.zeros(n)
        above_cost = np.zeros(n, dtype=int)
        distractor = np.zeros(n, dtype=int)
        payoff_active = np.zeros(n, dtype=int)
        payoff_dir = np.zeros(n, dtype=int)
        payoff_gross = np.zeros(n)
        pulse = np.zeros(n)
        payoff = np.zeros(n)
        capture_per_s = c3_capture_per_s(
            {**params, "alpha_bps": alpha})
        beta_bps = C3_B_PAYOFF_FRACTION * FRICTION_BPS / H

        for t, s, d, is_dis in events:
            sig_strength[t] = s
            sig_dir[t] = d
            distractor[t] = int(is_dis)
            # 脉冲在事件 bar 单 bar 内完成:close[t] 观察到完整强度,
            # open[t+1] 成交无法免费捕获脉冲本身(与 C2 同款因果合同);
            # 事件后 J bar 内线性回吐 -> 事件对价格水平净影响为 0
            pulse[t] += d * s * k
            if is_dis:
                continue  # distractor:零收益(但脉冲+回吐照常,可见)
            if variant == "A":
                # 注入用原始 alpha;回吐/回拉拖拽在价格序列上自然发生。
                # 可捕获毛 edge(open[t+1] 买、close[t+1] 卖)记入 sidecar:
                # G(s) = capture_per_s x s = (alpha - k/J - theta*k) x s
                g_bps = capture_per_s * s
                per_bar = np.sign(d) * alpha * s / H * 1e-4
            else:
                g_bps = beta_bps * H  # 与强度无关的亚成本常数
                per_bar = np.sign(d) * beta_bps * 1e-4
            sig_gross[t] = g_bps
            above_cost[t] = int(g_bps > FRICTION_BPS)
            end = min(t + 1 + H, n)
            payoff[t + 1:end] += per_bar
            payoff_active[t + 1:end] = 1
            payoff_dir[t + 1:end] = np.sign(d)
            payoff_gross[t + 1:end] = g_bps

        noise_rng = np.random.default_rng(self.derive_seed(
            {**params, "_noise": "market"}, seed))
        noise = vol * paired_noise(
            noise_rng, n,
            mutate_from=params.get("noise_mutate_from"),
            mutate_salt=params.get("noise_mutate_salt"))
        # 事件配对(脉冲+收益)与噪声配对全部成对抵消 -> 水平自然归零
        returns = pulse + payoff + noise
        hidden = pd.DataFrame({
            "sig_strength": sig_strength,
            "sig_dir": sig_dir.astype(int),
            "sig_gross_bps": sig_gross,
            "above_cost": above_cost.astype(int),
            "distractor_flag": distractor.astype(int),
            "payoff_active": payoff_active.astype(int),
            "payoff_dir": payoff_dir.astype(int),
            "payoff_gross_bps": payoff_gross,
        })
        meta = {
            "family": FAMILY_C3, "variant": variant,
            "n_events": len(events),
            "n_signals": int(np.count_nonzero(sig_dir != 0) - distractor.sum()),
            "n_above_cost": int(np.count_nonzero(above_cost)),
            "n_distractors": int(distractor.sum()),
            "friction_bps": FRICTION_BPS, "episode_bars": n,
        }
        return returns, hidden, meta

    # ------------------------------------------------ 结构性校验(词表内)
    @staticmethod
    def structural_validator(episode) -> list[str]:
        issues: list[str] = []
        h = episode.hidden
        variant = str(episode.spec.params.get("pair_variant", "A"))
        is_signal = (h["sig_dir"].to_numpy() != 0) & \
                    (h["distractor_flag"].to_numpy() == 0)
        n_signals = int(is_signal.sum())
        if n_signals < C3_MIN_SIGNALS:
            issues.append("too_few_signals")
        dirs = h["sig_dir"].to_numpy()[is_signal]
        if not (np.any(dirs > 0) and np.any(dirs < 0)):
            issues.append("missing_signal_directions")
        above = h["above_cost"].to_numpy()
        n_above = int(np.count_nonzero(above))
        n_below = n_signals - n_above
        if variant == "A":
            if n_above < C3_MIN_ABOVE_COST:
                issues.append("too_few_above_cost_signals")
            if n_below < C3_MIN_BELOW_COST:
                issues.append("too_few_below_cost_signals")
        else:
            # variant B:全部信号必须亚成本(收益解耦合同)
            if n_above != 0:
                issues.append("too_few_above_cost_signals")
            if n_below < C3_MIN_BELOW_COST:
                issues.append("too_few_below_cost_signals")
        if int(h["distractor_flag"].sum()) < C3_MIN_DISTRACTORS:
            issues.append("too_few_distractors")
        return [i for i in issues if i in C3_REJECT_VOCAB]


# ---------------------------------------------------------------- 策略层
class C3ReferencePolicy(ObservableBaselinePolicy):
    """C3 因果观察参考(成本敏感):只有估计毛 edge 超过冻结摩擦才做多。

    阈值从公开课程参数推导:s* = margin x F / (alpha x H),
    对应观察阈值 ret_1 > k x s*(脉冲单 bar 全幅)。
    成本常数取自 null_friction(冻结账本),不是课程专用成本模型。
    """

    name = "c3_reference_cost_aware"

    def __init__(self, strength_thr: float):
        super().__init__()
        self.strength_thr = float(strength_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        thr = self.strength_thr * C3_PULSE_K_BPS * 1e-4
        return int(self.read(observation, "ret_1") > thr)


class C3CostIgnorantPolicy(ObservableBaselinePolicy):
    """C3 无视成本基线:任何可见正信号都追(gross-edge chaser)。"""

    name = "c3_cost_ignorant"

    def __init__(self, any_signal_s: float = 0.15):
        super().__init__()
        self.any_signal_s = float(any_signal_s)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        thr = self.any_signal_s * C3_PULSE_K_BPS * 1e-4
        return int(self.read(observation, "ret_1") > thr)


class C3OraclePolicy(OraclePolicy):
    """C3 latent oracle(诊断专用):信号 bar 上即知 G>F 且方向为正。

    在 close[t] 决策、open[t+1] 成交的时序下恰好完整捕获 G(s)-F。
    """

    name = "c3_oracle_above_cost"

    def reset_episode(self) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        return int(
            ctx.hidden_row.get("sig_dir", 0) > 0
            and ctx.hidden_row.get("sig_gross_bps", 0.0) > FRICTION_BPS
        )


def c3_strength_threshold(rung_params: dict[str, Any],
                          margin: float) -> float:
    """由冻结摩擦公式推导的参考强度阈值。

    s* = margin x F / capture_per_s(可捕获毛 edge 系数,
    见 c3_capture_per_s;回吐与回拉拖拽已计入)。
    """
    return float(margin * FRICTION_BPS / c3_capture_per_s(rung_params))


# ---------------------------------------------------------------- pair 完整性
def c3_pair_integrity_metrics(episode) -> dict[str, Any]:
    """C3 pair 完整性度量:强度-收益耦合在 A/B 间必须改变。"""
    h = episode.hidden
    is_signal = (h["sig_dir"].to_numpy() != 0) & \
                (h["distractor_flag"].to_numpy() == 0)
    s = h["sig_strength"].to_numpy()[is_signal]
    g = h["sig_gross_bps"].to_numpy()[is_signal]
    if len(s) > 2 and np.std(s) > 0 and np.std(g) > 0:
        corr = float(np.corrcoef(s, g)[0, 1])
    else:
        # 零方差(B 的常数毛 edge)即完全解耦,记 0
        corr = 0.0
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    rets = np.diff(lc, prepend=0.0)
    return {
        "variant": str(episode.spec.params.get("pair_variant", "A")),
        "n_signals": int(is_signal.sum()),
        "n_above_cost": int(np.count_nonzero(
            h["above_cost"].to_numpy())),
        "max_gross_bps": float(np.max(g)) if len(g) else float("nan"),
        "mean_gross_bps": float(np.mean(g)) if len(g) else float("nan"),
        "corr_strength_gross": corr,
        "n_distractors": int(h["distractor_flag"].sum()),
        "realized_vol_bps": float(np.std(rets[1:]) * 1e4),
    }
