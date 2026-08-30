"""阶段 2.6.1 工作包 D:C2 — Context Gating(上下文门控)课程族。

C2 教的能力:**同一个局部 15m 信号,在不同高周期上下文下是否仍然成立。**

正交双上下文设计(串扰消除是本设计的核心约束):
- G1(方向上下文,1h 尺度):等长成对交替链(±L1,L1 ∈ [40,64]),每段
  开始注入 24 bar 的 banner 漂移(水平影响成对抵消);由 htf_1h_mom
  (24 bar = 6 个 1h bar 的因果窗口动量)读取;
- G2(波动率体制,4h 尺度):等长成对交替的 calm/turbulent 持久链
  (L2 ∈ [144,208],即 36-52h),每 bar 噪声 vol 在低/高档之间切换;
  由 vol_24(24 bar 滚动 std,方向无关)读取——与 G1 的方向性印记
  完全正交,不存在窗口串扰;
- cue 事件(泊松 + 最小间隔,门控翻转后 5 bar 内不接受 cue):以
  "+- 配对"调度——cue(t, d) 在 gap U[4,6] 后跟镜像 cue(-d),
  脉冲与收益注入对价格水平的净影响成对抵消;
- cue 脉冲单 bar 完成(160bps):close[t] 观察到完整 cue、open[t+1]
  成交无法免费捕获脉冲本身;160 < 门控阈值(h1=250bps),脉冲无法
  单独翻转门控特征的读数;
- 收益注入(单 bar H=1):injected = d x gate x alpha——局部 cue 与
  门控上下文同号(d x gate > 0)时下一 bar 有正漂移(Long 有正
  edge);异号时为负漂移(buy 会亏,Flat 合理)。

pair 机制(variant):
- A:gate = G1(方向上下文门控);B:gate = G2(波动率体制门控);
- A/B 共享同一 banner 表 / 波动率体制表 / cue 表 / 噪声流 / wick /
  nuisance,唯一差别是门控绑定对象(方向 vs 波动率体制)。

策略层论证(见主报告):
- local-only(只看 ret_1):E[payoff] = 0 - F < 0(两个 variant 都是);
- 单上下文(只看 G1 或只看 G2):在绑定 variant 上全对,在另一个
  variant 上 E[payoff]=0 只输摩擦 -> 聚合被对齐参考压过;
- 参考策略(局部 cue 与两个上下文同时对齐:正 cue 需 h1>θ 且 calm;
  负 cue 需 h1<-θ 且 turbulent):对齐象限在两个 variant 中门控均为
  对齐方向,跨 variant 恒正确,聚合严格优于上述所有捷径;
- 当前 observation 足够(无 recurrent 依赖):决策所需上下文全部在
  当前 observation 的 htf_1h_mom / vol_24 行内。
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
from rl_curriculum.policy_api import (
    ObservableBaselinePolicy,
    OracleActContext,
    OraclePolicy,
)

FAMILY_C2 = "c2_context"

#: C2 rung 参数(候选;最终值由 calibration 固定并进入 plan)。
#: alpha=单 bar 收益注入幅值(bps),须低于 cue_thr(110bps)以免
#: 收益注入 bar 自身再次触发入场;难度来自 alpha 下降与 cue 率上升。
C2_RUNG_PARAMS: dict[str, dict[str, Any]] = {
    "D0": {"alpha_bps": 110.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 100.0, "cue_rate": 0.150,
           "banner1": [24, 26.0], "g1_len_range": [40, 64],
           "g2_len_range": [144, 208], "pulse_bps": 200.0},
    "D1": {"alpha_bps": 80.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 100.0, "cue_rate": 0.160,
           "banner1": [24, 26.0], "g1_len_range": [40, 64],
           "g2_len_range": [144, 208], "pulse_bps": 200.0},
    "D2": {"alpha_bps": 55.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 100.0, "cue_rate": 0.170,
           "banner1": [24, 26.0], "g1_len_range": [40, 64],
           "g2_len_range": [144, 208], "pulse_bps": 200.0},
    "D3": {"alpha_bps": 34.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 100.0, "cue_rate": 0.180,
           "banner1": [24, 26.0], "g1_len_range": [40, 64],
           "g2_len_range": [144, 208], "pulse_bps": 200.0},
}
C2_LEVEL_PULL_THETA = 0.006

#: 参考阈值(bps -> 小数):cue 110 = ~3.8-sigma(噪声假触发 ~0);
#: h1 门控 250(banner1 信号 ~460-528,噪声 sigma ~110-200);
#: vol 门控 50bps(calm 12 / turbulent 60;cue 脉冲对 vol_24 的
#: 抬升在两个体制中等量,分离保持)
C2_REFERENCE_DEFAULTS = {"cue_thr": 0.017, "htf1_thr": 0.0030,
                         "vol_thr": 0.0095}

C2_REJECT_VOCAB = (
    "too_few_cues", "too_few_aligned_gate_windows",
    "context_polarity_missing",
)

C2_MIN_CUES = 6
C2_MIN_ALIGNED_WINDOWS = 2


def _alternating_chain(
    n: int, len_range: tuple[int, int], rng: np.random.Generator,
) -> np.ndarray:
    """等长成对交替链:+L bar 后接 -L bar(同一 L)。"""
    lo, hi = int(len_range[0]), int(len_range[1])
    states = np.empty(n, dtype=int)
    t = 0
    sign = 1 if rng.random() < 0.5 else -1
    while t < n:
        ln = int(rng.integers(lo, hi + 1))
        end = min(t + ln, n)
        states[t:end] = sign
        sign = -sign
        t = end
    return states


def _monotone_banner(n: int, states: np.ndarray, w_up: int,
                     bps: float) -> np.ndarray:
    """单调上坡 banner:状态开始后 w_up 根 bar 注入 sign x bps 漂移。

    水平抵消由**等长成对状态链**保证:链以 (+L, -L) 成对构造,每个
    完整"状态对"的两个 banner 相互抵消;奇偶规则:仅当状态对的
    第二个状态也能容纳完整 banner 时,该对两个状态才都挂 banner
    (末尾放不下的状态对/落单状态一律不挂)——episode 末尾不残留
    水平漂移,Always Long 净收益收敛到 -摩擦。

    h1(htf_1h_mom)读数:上坡期间持续 ~bps x 24;上坡结束后窗口
    滑出,读数在本状态尾部逐渐衰减(同号,无害);状态翻转后新
    banner 立即驱动读数换向,过渡窗口 ~24 bar 由 cue 缓冲覆盖。
    """
    drift = np.zeros(n)
    # 状态分段:[(start, end, sign), ...]
    segs: list[tuple[int, int, int]] = []
    t = 0
    while t < n:
        st = int(states[t])
        start = t
        while t < n and int(states[t]) == st:
            t += 1
        segs.append((start, t, st))
    # 状态对 (2m, 2m+1):两者都挂或都不挂
    offset = min(12, max(0, w_up // 2))
    for m in range(0, len(segs) - 1, 2):
        s1, e1, sign1 = segs[m]
        s2, e2, _sign2 = segs[m + 1]
        # banner 置于状态中部:与前后两次翻转都保持缓冲,
        # h1 滞留读数窗口落在状态尾部的 deferral 区内
        if s2 + offset + w_up <= n and e1 - (s1 + offset) >= w_up:
            drift[s1 + offset:s1 + offset + w_up] =                 float(sign1) * bps * 1e-4
            drift[s2 + offset:s2 + offset + w_up] =                 float(states[s2]) * bps * 1e-4
    return drift


def _last_flip_bars(states: np.ndarray) -> np.ndarray:
    """每 bar 距最近一次状态翻转的 bar 数(episode 起点视为翻转)。"""
    n = len(states)
    out = np.empty(n, dtype=int)
    last = 0
    for t in range(n):
        if t > 0 and states[t] != states[t - 1]:
            last = t
        out[t] = t - last
    return out


class C2ContextGatingGenerator(Curriculum261Base):
    """C2 生成器:方向 banner + 波动率体制双上下文,A/B 换门控绑定。"""

    family = FAMILY_C2
    family_version = "cur261-c2-v2"
    hidden_columns = [
        "gate_g1", "vol_state", "cue_dir", "payoff_active", "payoff_dir",
        "active_gate_is_g1",
    ]

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
        variant = str(params.get("pair_variant", "A"))
        if variant not in ("A", "B"):
            raise GeneratorError(f"非法 pair_variant {variant!r}")
        alpha = float(params["alpha_bps"]) * 1e-4
        H = int(params["payoff_bars"])
        vol_low = float(params["vol_low_bps"]) * 1e-4
        vol_high = float(params["vol_high_bps"]) * 1e-4
        cue_rate = float(params["cue_rate"])
        w1, b1 = params["banner1"]
        g1_lo, g1_hi = params["g1_len_range"]
        g2_lo, g2_hi = params["g2_len_range"]
        pulse = float(params["pulse_bps"]) * 1e-4

        # G1:方向上下文链 + 单调上坡 banner(等长成对状态 -> 抵消)
        g1_state = _alternating_chain(n, (int(g1_lo), int(g1_hi)), rng)
        base = _monotone_banner(n, g1_state, int(w1), float(b1))
        # G2:波动率体制链(calm=+1 -> vol_low;turbulent=-1 -> vol_high)
        vol_state = _alternating_chain(n, (int(g2_lo), int(g2_hi)), rng)
        vol_bar = np.where(vol_state > 0, vol_low, vol_high)

        # cue 事件:泊松 + 门控翻转后 20 bar 缓冲(h1 滞后窗口)+ 镜像配对
        flip_g1 = _last_flip_bars(g1_state)
        flip_g2 = _last_flip_bars(vol_state)
        cue_dir = np.zeros(n, dtype=int)
        t = 10
        while t < n - 8:
            if rng.random() < cue_rate:
                if flip_g1[t] >= 26 and flip_g2[t] >= 26:
                    d = 1 if rng.random() < 0.5 else -1
                    gap = int(rng.integers(4, 7))
                    # 镜像仅在门控与体制在整个配对区间内保持一致时放置
                    # (否则 cue 与镜像的收益注入不抵消,破坏水平归零)
                    span_g1 = np.all(g1_state[t:t + gap + 1] == g1_state[t])
                    span_vs = np.all(vol_state[t:t + gap + 1] == vol_state[t])
                    if t + gap < n and span_g1 and span_vs:
                        cue_dir[t] = d
                        cue_dir[t + gap] = -d
                        t += gap + 5
                    else:
                        t += 1
                else:
                    t += 1
            else:
                t += 1

        # 收益注入(双向 cue,单 bar):injected = d x gate x alpha
        gate = g1_state if variant == "A" else vol_state
        payoff = np.zeros(n)
        payoff_dir = np.zeros(n, dtype=int)
        active = np.zeros(n, dtype=int)
        for t in range(n):
            if cue_dir[t] == 0:
                continue
            d = int(cue_dir[t])
            injected = alpha * float(gate[t]) * d
            end = min(t + 1 + H, n)
            payoff[t + 1:end] += injected
            payoff_dir[t + 1:end] = 1 if injected > 0 else -1
            active[t + 1:end] = 1
        # 可见脉冲:cue 单 bar 全幅(close[t] 可读,open[t+1] 不可捕获)
        pulse_arr = np.zeros(n)
        for t in range(n):
            if cue_dir[t] != 0:
                pulse_arr[t] = float(cue_dir[t]) * pulse

        # 噪声配对使用体制内统一尺度(配对首元素的 vol),跨体制边界
        # 的镜像不产生未抵消的水平漂移;噪声用独立派生流(支持未来变异)
        noise_rng = np.random.default_rng(self.derive_seed(
            {**params, "_noise": "market"}, seed))
        noise = paired_noise(
            noise_rng, n, scale=vol_bar,
            mutate_from=params.get("noise_mutate_from"),
            mutate_salt=params.get("noise_mutate_salt"))
        # banner(状态对)/cue 脉冲与收益(镜像对)/噪声(间隔对)全部成对
        # 抵消 -> 价格水平自然归零,无需 OU 回拉
        returns = base + pulse_arr + payoff + noise
        hidden = pd.DataFrame({
            "gate_g1": g1_state.astype(int),
            "vol_state": vol_state.astype(int),
            "cue_dir": cue_dir.astype(int),
            "payoff_active": active.astype(int),
            "payoff_dir": payoff_dir.astype(int),
            "active_gate_is_g1": np.full(
                n, 1 if variant == "A" else 0, dtype=int),
        })
        meta = {
            "family": FAMILY_C2, "variant": variant,
            "gate_binding": "g1_direction" if variant == "A"
            else "vol_regime",
            "n_cues": int(np.count_nonzero(cue_dir)),
            "episode_bars": n,
        }
        return returns, hidden, meta

    # ------------------------------------------------ 结构性校验(词表内)
    @staticmethod
    def structural_validator(episode) -> list[str]:
        issues: list[str] = []
        h = episode.hidden
        cue_dir = h["cue_dir"].to_numpy()
        g1 = h["gate_g1"].to_numpy()
        vs = h["vol_state"].to_numpy()
        variant = str(episode.spec.params.get("pair_variant", "A"))
        gate = g1 if variant == "A" else vs
        if int(np.count_nonzero(cue_dir)) < C2_MIN_CUES:
            issues.append("too_few_cues")
        if int(np.count_nonzero(cue_dir > 0)) < 4 or \
                int(np.count_nonzero(cue_dir < 0)) < 4:
            issues.append("too_few_cues")
        # 门控上下文两种极性都必须与足量 cue 共存(任务对比性的前提)
        for dd in (1, -1):
            sel = cue_dir == dd
            if int(np.sum(sel & (gate > 0))) < 1 or \
                    int(np.sum(sel & (gate < 0))) < 1:
                issues.append("context_polarity_missing")
        # 对齐象限(d x gate > 0)的连续窗口必须存在
        aligned = (cue_dir != 0) & (cue_dir * gate > 0)
        windows = 0
        run = 0
        for t in range(len(gate)):
            if aligned[t]:
                run += 1
            else:
                if run:
                    windows += 1
                run = 0
        if run:
            windows += 1
        if windows < C2_MIN_ALIGNED_WINDOWS:
            issues.append("too_few_aligned_gate_windows")
        return [i for i in issues if i in C2_REJECT_VOCAB]


# ---------------------------------------------------------------- 策略层
class C2ReferencePolicy(ObservableBaselinePolicy):
    """C2 因果观察参考:局部 cue 与两个正交上下文同时对齐(无状态)。

    入场条件(对齐立方:正 cue ∧ 1h 趋势向上 ∧ calm 体制):
      ret_1 > cue_thr 且 htf_1h_mom > htf1_thr 且 vol_24 < vol_thr。
    该子集在 variant A(门控 G1 方向:需 g1+)与 variant B(门控波动率
    体制:需 v+)中门控均为对齐方向 -> 跨 variant 恒正确(每边各放弃
    一半机会作为代价)。收益注入为单 bar,无需持有。只读当前
    observation(ret_1 / htf_1h_mom / vol_24)。
    """

    name = "c2_reference_context_align"

    def __init__(self, cue_thr: float, htf1_thr: float, vol_thr: float):
        super().__init__()
        self.cue_thr = float(cue_thr)
        self.htf1_thr = float(htf1_thr)
        self.vol_thr = float(vol_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(
            self.read(observation, "ret_1") > self.cue_thr
            and self.read(observation, "htf_1h_mom") > self.htf1_thr
            and self.read(observation, "vol_24") < self.vol_thr
        )


class C2LocalOnlyPolicy(ObservableBaselinePolicy):
    """C2 local-only 基线:只看局部 15m cue,完全忽略上下文。

    买每个正 cue(单 bar 进出):两个 variant 上 E[payoff] = 0,
    每次往返只输摩擦。
    """

    name = "c2_local_only"

    def __init__(self, cue_thr: float):
        super().__init__()
        self.cue_thr = float(cue_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(self.read(observation, "ret_1") > self.cue_thr)


class C2SingleContextPolicy(ObservableBaselinePolicy):
    """C2 单上下文基线:与参考同构的对齐规则,但只看一个上下文。

    feature 取 "htf_1h_mom"(方向上下文)或 "vol_24"(波动率体制),
    与参考读取的槽位一致——差异只在上下文数量,隔离"单上下文不足"。
    """

    def __init__(self, cue_thr: float, htf_thr: float, feature: str):
        super().__init__()
        self.cue_thr = float(cue_thr)
        self.htf_thr = float(htf_thr)
        self.feature = str(feature)

    @property
    def name(self) -> str:
        return f"c2_single_context_{self.feature}"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        r1 = self.read(observation, "ret_1")
        gate = self.read(observation, self.feature)
        if self.feature == "vol_24":
            return int(r1 > self.cue_thr and gate < self.htf_thr)
        return int(r1 > self.cue_thr and gate > self.htf_thr)


class C2OraclePolicy(OraclePolicy):
    """C2 latent oracle(诊断专用):cue bar 上 d x 激活门控 > 0 即 Long。"""

    name = "c2_oracle_payoff"

    def reset_episode(self) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        gate = (ctx.hidden_row.get("gate_g1", 0.0)
                if ctx.hidden_row.get("active_gate_is_g1", 0) == 1
                else ctx.hidden_row.get("vol_state", 0.0))
        d = ctx.hidden_row.get("cue_dir", 0)
        return int(d != 0 and d * gate > 0)


# ---------------------------------------------------------------- pair 完整性
def c2_pair_integrity_metrics(episode) -> dict[str, Any]:
    """C2 pair 完整性度量(已实现统计;构造级判定见 pairs 模块)。"""
    h = episode.hidden
    cue_dir = h["cue_dir"].to_numpy()
    g1 = h["gate_g1"].to_numpy()
    vs = h["vol_state"].to_numpy()
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    rets = np.diff(lc, prepend=0.0)
    nxt = np.concatenate([rets[1:], [np.nan]])  # cue 后一 bar(注入 bar)

    def _mean(mask: np.ndarray) -> float:
        m = mask & np.isfinite(nxt)
        return float(np.mean(nxt[m]) * 1e4) if m.sum() > 2 else float("nan")

    prev = np.concatenate([[0], cue_dir[:-1]])
    prev_g1 = np.concatenate([[0], g1[:-1]])
    prev_vs = np.concatenate([[0], vs[:-1]])
    # 仅在"前一 bar 是 cue"的注入 bar 上统计(按该 cue 的门控对齐性分组)
    inj = prev != 0
    return {
        "variant": str(episode.spec.params.get("pair_variant", "A")),
        "n_cues": int(np.count_nonzero(cue_dir)),
        "next1_g1_aligned_bps": _mean(inj & (prev * prev_g1 > 0)),
        "next1_g1_anti_bps": _mean(inj & (prev * prev_g1 < 0)),
        "next1_vol_aligned_bps": _mean(inj & (prev * prev_vs > 0)),
        "next1_vol_anti_bps": _mean(inj & (prev * prev_vs < 0)),
        "realized_vol_bps": float(np.std(rets[1:]) * 1e4),
    }
