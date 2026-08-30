"""阶段 2.6.1 工作包 D + repair R1(v4):C2 — Context Gating 课程族。

C2 教的能力:**同一个局部 15m 信号,在不同持久上下文下是否仍然成立。**

repair R1 重设计历程(production observation 版):
- 上一轮的 G1 方向上下文由 htf_1h_mom(curriculum 自制特征)读取,
  该特征不在生产 observation 中 -> Blocker A;
- v3 曾用"方向 regime 漂移段"(每 bar ±35bps 漂移)承载 G1,由
  生产特征 %-price-ma-ratio 读取——校准暴露致命缺陷:regime 漂移
  进入每根 bar 的收益,cue 脉冲在 %-ret-1 上的读数分布随 regime
  方向平移(±70bps),阈值触发率的选择效应使 local-only 基线
  "免费"读出门控(g1+ 段触发率 ~100%、g1- 段 ~0),上下文门控被
  局部信号隐式解决,族不再教 gating;
- v5 的 G1 改为 **dev 平台价格**:log 价格 = 基线随机游走(间隔
  配对噪声,水平精确归零)+ dev 平台 P_t(ramp 升至 ±dev0、
  平台保持、ramp 回 0,按完整状态对对称)。平台保持段中部
  24-bar 窗口完全覆盖平台 -> 生产特征 %-price-ma-ratio ≈ ±dev0
  恒定可见;保持段 bar 收益 = 纯噪声(平台斜率为 0),ramp 期
  的方向性收益(±25bps/bar)与 cue 隔离(翻转后 >= 26 bar 才
  放 cue > ramp 16)——cue 读数与门控状态的相关被构造性断开,
  选择效应消除。

G2(波动率体制)不变:等长成对交替的 calm/turbulent 持久链,由
生产特征 %-vol-24 读取(与 G1 的位置印记正交,无窗口串扰)。

cue 事件(泊松 + 门控翻转后 26 bar 缓冲 = 过渡 16 + MA 冲刷):
"+- 配对"调度——cue(t, d) 在 gap U[4,6] 后跟镜像 cue(-d),且仅在
门控与体制整个配对区间内恒定且处于完整 dev 状态对内时放置(span
检查);cue 脉冲与收益注入不进入锚定递推(作为显示层收益叠加)。
cue 脉冲单 bar 完成(pulse_bps):close[t] 观察到完整 cue,
open[t+1] 成交无法免费捕获脉冲本身。
收益注入(单 bar H=1):injected = d x gate x alpha——局部 cue 与
门控上下文同号(d x gate > 0)时下一 bar 有正漂移(Long 有正
edge);异号时为负漂移(buy 会亏,Flat 合理)。

pair 机制(variant):
- A:gate = G1(方向上下文门控);B:gate = G2(波动率体制门控);
- A/B 共享同一方向状态表 / dev 表 / 波动率体制表 / cue 表 / 噪声
  流 / wick,唯一差别是门控绑定对象(方向 vs 波动率体制)。

水平归零(Always Long 只输摩擦)的构造保证:
- dev 只在完整状态对(反号等长段)上挂载:每对 dev 从 0 过渡到
  +dev0 再回 0、再到 -dev0 再回 0 -> dev 的水平贡献按对抵消,
  落单/截断段 dev 恒 0(dev_final 恒 0,无末端水平残留);
- 锚定噪声为间隔配对(体制内同尺度);dev 锚定的非线性残差为
  O(dev x eps) 二阶小量;
- cue 脉冲镜像 + span 恒定检查下的收益注入镜像 -> 每对净和为 0。

策略层论证(production 特征名):
- local-only(只看 %-ret-1):v4 下 cue 读数与门控无关 -> 两侧
  E[payoff] = 0,每次往返只输摩擦;
- 单上下文(只看 %-price-ma-ratio 或只看 %-vol-24):在绑定
  variant 上全对,在另一个 variant 上 E[payoff] = 0 只输摩擦 ->
  聚合被对齐参考压过;
- 参考策略(局部 cue 与两个上下文同时对齐:正 cue 需 pmr>0 且
  calm):对齐子集在两个 variant 中门控均为对齐方向,跨 variant
  恒正确,聚合严格优于所有捷径;
- 决策所需上下文全部在当前 observation 的 %-price-ma-ratio /
  %-vol-24 行内(无 recurrent 依赖)。
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

#: C2 rung 参数(repair R1 v4;最终值由 calibration 固定并进入 plan)。
#: alpha = 单 bar 收益注入幅值(bps);难度主 knob = alpha 下降,
#: 辅 knob = cue_rate 上升(机会密度补偿,压低跨语料方差);
#: g1_dev / ramp / 段长 / 体制 / 脉冲幅值全 rung 固定(上下文结构
#: 不是难度 knob,D0-D3 教同一能力)。
C2_RUNG_PARAMS: dict[str, dict[str, Any]] = {
    "D0": {"alpha_bps": 60.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 130.0, "cue_rate": 0.820,
           "g1_drift_bps": 12.0,
           "g1_len_range": [56, 80], "g2_len_range": [96, 136],
           "pulse_bps": 90.0},
    "D1": {"alpha_bps": 50.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 130.0, "cue_rate": 0.820,
           "g1_drift_bps": 12.0,
           "g1_len_range": [56, 80], "g2_len_range": [96, 136],
           "pulse_bps": 90.0},
    "D2": {"alpha_bps": 40.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 130.0, "cue_rate": 0.820,
           "g1_drift_bps": 12.0,
           "g1_len_range": [56, 80], "g2_len_range": [96, 136],
           "pulse_bps": 90.0},
    "D3": {"alpha_bps": 34.0, "payoff_bars": 1, "vol_low_bps": 12.0,
           "vol_high_bps": 130.0, "cue_rate": 0.820,
           "g1_drift_bps": 12.0,
           "g1_len_range": [56, 80], "g2_len_range": [96, 136],
           "pulse_bps": 90.0},
}

#: 参考阈值(production 特征口径):cue_thr = %-ret-1 门限。
#: cue bar 读数 = pulse 130 + 锚定噪声(calm ~12bps)≈ 150±15;
#: payoff bar 读数 = alpha + 锚定噪声(D0 最陡 90 -> 110±15)。
#: cue_thr=130bps:cue bar 通过率 ~90%,payoff bar 假触发率
#: D0 ~2%、D3 ~0——阈值把"信号 bar"与"收益注入 bar"在观察上分开
#: (收益注入不可被 open[t+1] 免费捕获,追逐注入 bar 只输摩擦)。
#: pmr_thr = 0(方向判定,pmr 精确 = ±dev0 = ±400bps);vol_thr =
#: calm/turbulent 分界(cue bar 的 vol-24 p50 ≈ 45bps << 95bps <<
#: turbulent ≈ 111bps)。
C2_REFERENCE_DEFAULTS = {"cue_thr": 0.0088, "pmr_thr": 0.0,
                         "vol_thr": 0.0085}

C2_REJECT_VOCAB = (
    "too_few_cues", "too_few_aligned_gate_windows",
    "context_polarity_missing",
)

C2_MIN_CUES = 10
C2_MIN_ALIGNED_WINDOWS = 2


def _alternating_chain(
    n: int, len_range: tuple[int, int], rng: np.random.Generator,
) -> np.ndarray:
    """等长成对交替链:每个状态对 (+L, -L) 共用同一长度 L。

    成对等长保证状态对的 dev 水平贡献抵消(dev 路径对称)。落单/
    截断的尾段照常占位,由 dev 挂载的段对完整性判定跳过。
    """
    lo, hi = int(len_range[0]), int(len_range[1])
    states = np.zeros(n, dtype=int)
    t = 0
    sign = 1 if rng.random() < 0.5 else -1
    while t < n:
        ln = int(rng.integers(lo, hi + 1))
        end = min(t + ln, n)
        states[t:end] = sign
        if end < n:
            end2 = min(end + ln, n)
            states[end:end2] = -sign
            t = end2
        else:
            t = end
    return states


def _paired_mount(n: int, states: np.ndarray) -> np.ndarray:
    """完整状态对的挂载掩码:段两两配对,反号且等长的对两段都挂。

    落单/截断段不挂(dev 恒 0)——dev_final 恒为 0,episode 不残留
    末端水平偏移,Always Long 的 dev 贡献按对精确抵消。
    """
    mount = np.zeros(n, dtype=bool)
    segs: list[tuple[int, int, int]] = []
    t = 0
    while t < n:
        st = int(states[t])
        start = t
        while t < n and int(states[t]) == st:
            t += 1
        segs.append((start, t, st))
    for m in range(0, len(segs) - 1, 2):
        s1, e1, sign1 = segs[m]
        s2, e2, sign2 = segs[m + 1]
        if sign1 == -sign2 and (e1 - s1) == (e2 - s2):
            mount[s1:e2] = True
    return mount


def _paired_drift(n: int, states: np.ndarray, mount: np.ndarray,
                  bps: float) -> np.ndarray:
    """微漂移:完整状态对(mount)内每 bar +-bps,水平按对抵消。

    v6 的关键标定(repair R1):漂移幅值 mu 的两难——
    - pmr 符号判定需要 11.5 x mu >> pmr 噪声(2.9 x vol,calm);
    - cue 读数的选择效应需要 mu << cue 脉冲幅值。
    mu=6bps(平台稳态 69bps,calm pmr 噪声 ~35bps,cue bar 上符号
    误判 ~2%)同时满足两者:cue 读数 = pulse + mu +- sigma 在
    g1+/- 段的触发率 ~62%/38%,local-only 的条件期望为负,无法
    隐式解决门控;对齐参考在 calm 段的 pmr 符号可靠。
    状态对等长 -> 每对漂移和精确为 0;落单/截断段(mount 外)
    漂移恒 0 -> 水平精确归零。
    """
    drift = np.zeros(n)
    drift[1:] = np.where(
        mount[1:], states[1:].astype(float) * bps * 1e-4, 0.0)
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
    """C2 生成器 v4:dev 锚定方向上下文 + 波动率体制,A/B 换门控绑定。"""

    family = FAMILY_C2
    family_version = "cur261-c2-v6"
    hidden_columns = [
        "gate_g1", "vol_state", "cue_dir", "payoff_active", "payoff_dir",
        "active_gate_is_g1", "g1_mount",
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
        g1_drift = float(params["g1_drift_bps"])
        g1_lo, g1_hi = params["g1_len_range"]
        g2_lo, g2_hi = params["g2_len_range"]
        pulse = float(params["pulse_bps"]) * 1e-4
        p0 = float(params.get("initial_price", 1.0))

        # G1:等长成对方向状态链(在 [1, n) 上构造,bar 0 复制占位无
        # dev)——水平合同:dev 生命周期全部落在 [1, n) 内
        g1_chain = _alternating_chain(n - 1, (int(g1_lo), int(g1_hi)), rng)
        g1_state = np.concatenate([g1_chain[:1], g1_chain])
        mount_chain = _paired_mount(n - 1, g1_chain)
        mount = np.concatenate([[False], mount_chain])
        base = _paired_drift(n, g1_state, mount, g1_drift)
        # G2:波动率体制链(calm=+1 -> vol_low;turbulent=-1 -> vol_high)
        vol_state = _alternating_chain(n, (int(g2_lo), int(g2_hi)), rng)
        # v7:噪声尺度 = 体制的 24-bar 线性平滑(切换边界与 vol-24
        # 读数同步,消除"读数 calm、实际 turbulent"的假触发窗口);
        # 暖机(t < 24)强制 calm(vol-24 读数为 fillna(0),若暖机
        # 起始即 turbulent,130bps 噪声会被 ref 当作 calm 期信号)。
        raw_scale = np.where(vol_state > 0, vol_low, vol_high)
        # 暖机(t < 24)强制 calm:必须在进入过渡状态机之前改写目标
        # (事后覆盖数组会让状态机从 turbulent 起步,第 24 根 bar 的
        # 实际 sigma 直接跳到全幅,而 vol-24 读数仍显示 calm)
        raw_scale[:24] = vol_low
        vol_bar = np.empty(n)
        cur = vol_low
        t2 = 0
        while t2 < n:
            tgt = float(raw_scale[t2])
            if abs(cur - tgt) < 1e-15:
                vol_bar[t2] = cur
                t2 += 1
                continue
            prev = cur
            end = min(t2 + 24, n)
            steps = end - t2
            for k in range(steps):
                vol_bar[t2 + k] = prev + (tgt - prev) * (k + 1) / steps
            cur = vol_bar[end - 1]
            t2 = end

        # 锚定噪声(间隔配对,体制内同尺度,独立派生流支持未来变异)
        noise_rng = np.random.default_rng(self.derive_seed(
            {**params, "_noise": "market"}, seed))
        eps = paired_noise(
            noise_rng, n, scale=vol_bar,
            mutate_from=params.get("noise_mutate_from"),
            mutate_salt=params.get("noise_mutate_salt"))
        del p0  # 水平基准不进入收益序列(初始价由 _build_ohlcv 处理)

        # cue 事件:泊松 + 门控翻转后 26 bar 缓冲(过渡 16 + MA 冲刷)
        # + 镜像配对(镜像仅在门控与体制整个配对区间内恒定、且处于
        # 完整 dev 状态对内部时放置)
        flip_g1 = _last_flip_bars(g1_state)
        flip_g2 = _last_flip_bars(vol_state)
        cue_dir = np.zeros(n, dtype=int)
        t = 10
        while t < n - 8:
            if rng.random() < cue_rate:
                if flip_g1[t] >= 26 and flip_g2[t] >= 26 and mount[t] \
                        and mount[min(t + 6, n - 1)]:
                    d = 1 if rng.random() < 0.5 else -1
                    # v7c:镜像 gap 2-3——两个脉冲几乎总在
                    # 同一 24-bar 窗口内成对出现,对 pmr/vol-24
                    # 的净扰动按对抵消(pmr 判定通过率回升);
                    # long-only 环境中负脉冲不可交易,短 gap 的
                    # 反转规律无策略价值
                    gap = int(rng.integers(2, 4))
                    span_g1 = np.all(g1_state[t:t + gap + 1] == g1_state[t])
                    span_vs = np.all(vol_state[t:t + gap + 1] == vol_state[t])
                    if t + gap < n and span_g1 and span_vs:
                        cue_dir[t] = d
                        cue_dir[t + gap] = -d
                        # 步进含镜像后缓冲:24-bar vol 窗口内最多
                        # 一对脉冲(vol-24 污染下限)
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

        # 显示层叠加:dev 锚定(水平按对抵消)+ 脉冲镜像 + 收益镜像
        returns = base + eps + pulse_arr + payoff
        hidden = pd.DataFrame({
            "gate_g1": g1_state.astype(int),
            "vol_state": vol_state.astype(int),
            "cue_dir": cue_dir.astype(int),
            "payoff_active": active.astype(int),
            "payoff_dir": payoff_dir.astype(int),
            "active_gate_is_g1": np.full(
                n, 1 if variant == "A" else 0, dtype=int),
            "g1_mount": mount.astype(int),
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
    """C2 因果观察参考(production 特征):局部 cue 与两个正交上下文
    同时对齐(无状态)。

    入场条件(对齐立方:正 cue ∧ 方向 regime 向上 ∧ calm 体制):
      %-ret-1 > cue_thr 且 %-price-ma-ratio > pmr_thr 且
      %-vol-24 < vol_thr。
    该子集在 variant A(门控 G1 方向:需 g1+)与 variant B(门控波动率
    体制:需 v+)中门控均为对齐方向 -> 跨 variant 恒正确(每边各放弃
    一半机会作为代价)。收益注入为单 bar,无需持有。只读当前
    observation 的三个生产特征槽位。
    """

    name = "c2_reference_context_align"

    def __init__(self, cue_thr: float, pmr_thr: float, vol_thr: float):
        super().__init__()
        self.cue_thr = float(cue_thr)
        self.pmr_thr = float(pmr_thr)
        self.vol_thr = float(vol_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(
            self.read(observation, "%-ret-1") > self.cue_thr
            and self.read(observation, "%-price-ma-ratio") > self.pmr_thr
            and self.read(observation, "%-vol-24") < self.vol_thr
        )


class C2LocalOnlyPolicy(ObservableBaselinePolicy):
    """C2 local-only 基线:只看局部 15m cue(%-ret-1),完全忽略上下文。

    v4 下 cue 读数与门控无关 -> 买每个正 cue 在两个 variant 上
    E[payoff] = 0,每次往返只输摩擦。
    """

    name = "c2_local_only"

    def __init__(self, cue_thr: float):
        super().__init__()
        self.cue_thr = float(cue_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(self.read(observation, "%-ret-1") > self.cue_thr)


class C2SingleContextPolicy(ObservableBaselinePolicy):
    """C2 单上下文基线:与参考同构的对齐规则,但只看一个上下文。

    feature 取 "%-price-ma-ratio"(方向上下文)或 "%-vol-24"
    (波动率体制),与参考读取的槽位一致——差异只在上下文数量,
    隔离"单上下文不足"。
    """

    def __init__(self, cue_thr: float, gate_thr: float, feature: str):
        super().__init__()
        if feature not in ("%-price-ma-ratio", "%-vol-24"):
            raise ValueError(
                f"C2 单上下文基线的 feature 必须是生产上下文特征,"
                f"收到 {feature!r}")
        self.cue_thr = float(cue_thr)
        self.gate_thr = float(gate_thr)
        self.feature = str(feature)

    @property
    def name(self) -> str:
        return f"c2_single_context_{self.feature}"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        r1 = self.read(observation, "%-ret-1")
        gate = self.read(observation, self.feature)
        if self.feature == "%-vol-24":
            return int(r1 > self.cue_thr and gate < self.gate_thr)
        return int(r1 > self.cue_thr and gate > self.gate_thr)


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
