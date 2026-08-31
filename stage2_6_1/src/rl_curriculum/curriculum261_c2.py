# -*- coding: utf-8 -*-
"""R2 patch 3: curriculum261_c2.py 全量重写为 v9(wick 几何纹理上下文)。

repair R2 的结构性 redesign(R1 v6-v8 的死结:方向上下文若由价格
漂移承载,漂移强则 cue 读数分布随 regime 平移(local-only 隐式免费
读出门控),漂移弱则 pmr 判定仅 ~2σ 不稳):

v9 把上下文载体整体移出 close 收益路径,改为 **wick 几何纹理**:
- G1(方向纹理 regime):wick 偏斜方向 s∈{+1,-1} 等长成对交替块。
  s=+1 块内每 bar 上影长、下影短(E[high-close] > E[close-low]);
  s=-1 块反向。%-raw-high/%-raw-low/%-raw-close(生产特征)组合
  score = high+low-2*close 的期望 = ±2*kappa*wick_base。
- G2(wick 幅值 regime):wide/narrow 等长成对交替块;width =
  high-low 在两态差 ~3.5 倍。
- close 收益 = 间隔配对噪声(常数 vol)+ cue 脉冲(镜像)+ 收益注入
  (镜像):上下文载体完全不进入 close 收益 ->
  1) local cue(%-ret-1)分布在任何上下文态下按构造逐分布相同
     (local-cue context independence 是构造级性质,非统计凑合);
  2) 水平归零沿用 R1 已证合同(噪声/脉冲/注入全部按对抵消,
     sum(returns[1:]) 恒 0,Always Long 恒 = -摩擦);
  3) 上下文可观察性由 wick 特征承载,即时可读(无 24-bar 窗口
     冲刷,无体制切换读数滞后,无暖机假触发——R1 G2 的三类
     notcue 假触发根源一并消除)。

cue 事件(泊松 + span 检查 + 镜像配对):
- cue(t, d) 在 gap U[2,3] 后跟镜像 cue(-d);span 检查保证 s/w 在
  两个 cue 时刻恒定 -> 注入 d*gate*alpha 与 -d*gate*alpha 按对精确
  抵消(水平合同);放置后步进 gap+20(节奏控制,每集 ~12-13 对)。
- cue 脉冲单 bar 完成(pulse_bps=150):close[t] 读到完整脉冲,
  open[t+1] 成交无法免费捕获脉冲本身;payoff bar 读数
  |alpha*s| <= 60bps 与阈值 105bps(cue_thr)分离,注入 bar 不触发。

pair 机制(variant):
- A:gate = G1(方向纹理);B:gate = G2(wick 幅值);
- A/B 共享 s/w 链 / cue 表 / 噪声流 / wick 表,唯一差别是门控绑定
  对象。

策略层(production 特征名):
- local-only(%-ret-1 only):cue 分布与门控无关 -> E[payoff]=0,
  每笔只输摩擦,双语料稳定失败;
- 单上下文(wick score 或 width 只读其一):在绑定 variant 上对,
  在另一个 variant 上 E=0 只输摩擦 -> 聚合被对齐参考压过;
- 参考(正 cue ∧ score>0 ∧ wide):跨 variant 恒正确(每边放弃
  一半机会作为代价),只读当前 observation 的四个生产特征槽位。
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

#: C2 rung 参数(repair R2 v9;最终值由 calibration 固定并进入 plan)。
#: 难度双 knob:
#: - wick_kappa:wick 偏斜度 -> 上下文判定的 score SNR(D0 0.85 ->
#:   D3 0.30,判对率 ~99.99% -> ~90%);
#: - alpha_bps:注入幅值(60 -> 34);
#: 其余全 rung 固定(上下文结构与机会密度不是难度 knob,
#: D0-D3 教同一能力)。
C2_RUNG_PARAMS: dict[str, dict[str, Any]] = {
    "D0": {"alpha_bps": 68.0, "payoff_bars": 1, "vol_bps": 20.0,
           "cue_rate": 0.820, "wick_kappa": 0.80,
           "dir_len_range": [56, 80], "width_len_range": [96, 136],
           "pulse_bps": 150.0, "wick_base_bps": 80.0,
           "wide_wick_bps": 110.0, "narrow_wick_bps": 30.0},
    "D1": {"alpha_bps": 54.0, "payoff_bars": 1, "vol_bps": 20.0,
           "cue_rate": 0.820, "wick_kappa": 0.55,
           "dir_len_range": [56, 80], "width_len_range": [96, 136],
           "pulse_bps": 150.0, "wick_base_bps": 80.0,
           "wide_wick_bps": 110.0, "narrow_wick_bps": 30.0},
    "D2": {"alpha_bps": 40.0, "payoff_bars": 1, "vol_bps": 20.0,
           "cue_rate": 0.820, "wick_kappa": 0.38,
           "dir_len_range": [56, 80], "width_len_range": [96, 136],
           "pulse_bps": 150.0, "wick_base_bps": 80.0,
           "wide_wick_bps": 110.0, "narrow_wick_bps": 30.0},
    "D3": {"alpha_bps": 32.0, "payoff_bars": 1, "vol_bps": 20.0,
           "cue_rate": 0.820, "wick_kappa": 0.25,
           "dir_len_range": [56, 80], "width_len_range": [96, 136],
           "pulse_bps": 150.0, "wick_base_bps": 80.0,
           "wide_wick_bps": 110.0, "narrow_wick_bps": 30.0},
}

#: 参考阈值(production 特征口径,解析闭式):
#: - cue_thr = 105bps:cue bar 读数 = pulse 150 +- vol 20(触发率
#:   ~98.8%);payoff bar 读数 |alpha*s| <= 60 +- 20 与非 cue 噪声
#:   (3 sigma = 60)都低于阈值 -> 注入 bar 不被误判为 cue;
#: - wick_dir_thr = 0:score = raw_high + raw_low - 2*raw_close 的
#:   符号即方向纹理判定(期望 = ±2*kappa*wick_base,D3 最小
#:   ±24bps,判定噪声 sigma ~18bps);
#: - wick_width_thr = 120bps:wide 幅 ~240bps / narrow 幅 ~70bps
#:   (含 body ~20bps),分界清晰(bar 级判对率 ~99%)。
C2_REFERENCE_DEFAULTS = {"cue_thr": 0.0105, "wick_dir_thr": 0.0,
                         "wick_width_thr": 0.0120}

C2_REJECT_VOCAB = (
    "too_few_cues", "too_few_aligned_gate_windows",
    "context_polarity_missing",
)

C2_MIN_CUES = 10
C2_MIN_ALIGNED_WINDOWS = 2

#: wick 判定使用的 observation 槽位索引(PRODUCTION_FEATURE_COLUMNS
#: 固定列序;导入时断言,列序漂移立即失败)
_WICK_COL_INDEX: dict[str, int] = {"open": 4, "high": 5, "low": 6,
                                   "close": 7}


def _assert_wick_col_index() -> None:
    from rl_curriculum.curriculum261_production_obs import (
        PRODUCTION_FEATURE_COLUMNS,
    )

    cols = list(PRODUCTION_FEATURE_COLUMNS)
    expect = {4: "%-raw_open", 5: "%-raw_high", 6: "%-raw_low",
              7: "%-raw_close"}
    for idx, name in expect.items():
        if cols[idx] != name:
            raise GeneratorError(
                f"PRODUCTION_FEATURE_COLUMNS 列序漂移:index {idx} 应为 "
                f"{name},实际 {cols[idx]}(C2 wick 判定索引失效)")

#: cue 放置节奏:镜像 gap U[2,3],放置后步进 gap + 20
#: (每集期望 ~12-13 对,reference 只交易正 cue -> 每集 ~12 笔,
#: 与 R1 机会密度一致;方差由 corpus 规模控制)
C2_CUE_STEP_PAD = 8


def _alternating_chain(
    n: int, len_range: tuple[int, int], rng: np.random.Generator,
) -> np.ndarray:
    """等长成对交替链:每个状态对 (+L, -L) 共用同一长度 L。

    等长成对使 s/w 在 episode 内时间均衡(每态约一半 bar),且
    A/B 共享同一条链(pair nuisance 合同)。
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


def c2_wick_regime_chains(n: int, params: dict[str, Any],
                          seed: int, family: str = FAMILY_C2,
                          family_version: str = "cur261-c2-v9",
                          ) -> tuple[np.ndarray, np.ndarray]:
    """从确定性派生流重建 (s 链, w 链)——_generate 与 wick 重写共用。

    params 必须是与 _generate 相同的 effective params(含
    pair_variant 等被排除键也不影响:派生盐固定,不依赖 variant,
    保证 A/B 链逐位一致)。
    """
    import hashlib
    import json as _json

    payload = _json.dumps(
        [family, family_version,
         {k: v for k, v in params.items()
          if k not in ("pair_variant", "antithetic_flip",
                       "noise_mutate_from", "noise_mutate_salt")},
         int(seed), "_c2_wick_regimes"],
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    rng = np.random.default_rng(int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"))
    d_lo, d_hi = params["dir_len_range"]
    w_lo, w_hi = params["width_len_range"]
    s = _alternating_chain(n, (int(d_lo), int(d_hi)), rng)
    w = _alternating_chain(n, (int(w_lo), int(w_hi)), rng)
    return s, w


def _wick_log_plan(n: int, s: np.ndarray, w: np.ndarray,
                   params: dict[str, Any], seed: int,
                   family: str = FAMILY_C2,
                   family_version: str = "cur261-c2-v9",
                   ) -> tuple[np.ndarray, np.ndarray]:
    """每 bar 的 (上影, 下影) log 幅度(确定性派生流,带 ±25% jitter)。

    up = base*(1 + kappa*s)*(1+j_u);dn = base*(1 - kappa*s)*(1+j_d);
    base = w>0 ? wide : narrow。s=+1 -> 上影长/下影短。
    """
    import hashlib
    import json as _json

    kappa = float(params["wick_kappa"])
    base_wide = float(params["wide_wick_bps"]) * 1e-4
    base_narrow = float(params["narrow_wick_bps"]) * 1e-4
    payload = _json.dumps(
        [family, family_version, int(seed), "_c2_wick_jitter"],
        sort_keys=True, separators=(",", ":"))
    rng = np.random.default_rng(int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big"))
    base = np.where(w > 0, base_wide, base_narrow)
    j_u = rng.uniform(-0.25, 0.25, size=n)
    j_d = rng.uniform(-0.25, 0.25, size=n)
    up = base * (1.0 + kappa * s.astype(float)) * (1.0 + j_u)
    dn = base * (1.0 - kappa * s.astype(float)) * (1.0 + j_d)
    return np.clip(up, 1e-9, 0.05), np.clip(dn, 1e-9, 0.05)


class C2ContextGatingGenerator(Curriculum261Base):
    """C2 生成器 v9:wick 几何纹理上下文 + 幅值体制,A/B 换门控绑定。"""

    family = FAMILY_C2
    family_version = "cur261-c2-v9"
    hidden_columns = [
        "wick_dir_state", "wick_width_state", "cue_dir",
        "payoff_active", "payoff_dir", "active_gate_is_dir",
    ]
    #: _generate -> _build_ohlcv 的 wick 纹理计划(同一次 generate()
    #: 调用栈内传递;读取即清空,不跨调用持有)
    _wick_plan: tuple[np.ndarray, np.ndarray] | None = None

    def __init__(self) -> None:
        super().__init__()
        _assert_wick_col_index()

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
        variant = str(params.get("pair_variant", "A"))
        if variant not in ("A", "B"):
            raise GeneratorError(f"非法 pair_variant {variant!r}")
        alpha = float(params["alpha_bps"]) * 1e-4
        H = int(params["payoff_bars"])
        vol = float(params["vol_bps"]) * 1e-4
        cue_rate = float(params["cue_rate"])
        pulse = float(params["pulse_bps"]) * 1e-4

        # 上下文链:方向纹理 s / wick 幅值 w(等长成对交替,A/B 共享)
        s, w = c2_wick_regime_chains(
            n, params, seed, self.family, self.family_version)
        # s 链右移占位 bar 0 复制(链在 [0, n) 直接构造即可——
        # wick 不进入 close 收益,无水平合同约束;首 bar 复制无副作用)
        # (保持与 R1 相同的 [1, n) 语义:s/w 全程定义,bar 0 由链首覆盖)

        # 噪声:常数尺度间隔配对(水平按对抵消;R2 无 vol 体制切换)
        noise_rng = np.random.default_rng(self.derive_seed(
            {**params, "_noise": "market"}, seed))
        eps = paired_noise(
            noise_rng, n, scale=np.full(n, vol),
            mutate_from=params.get("noise_mutate_from"),
            mutate_salt=params.get("noise_mutate_salt"))

        # cue 事件:泊松尝试 + span 检查(两个 cue 时刻 s/w 恒定)+
        # 镜像配对 + 步进节奏控制
        cue_dir = np.zeros(n, dtype=int)
        t = 4
        while t < n - 8:
            if rng.random() < cue_rate:
                d = 1 if rng.random() < 0.5 else -1
                gap = int(rng.integers(2, 4))
                if t + gap + 1 >= n:
                    t += 1
                    continue
                span_s = bool(np.all(s[t:t + gap + 1] == s[t]))
                span_w = bool(np.all(w[t:t + gap + 1] == w[t]))
                if span_s and span_w:
                    cue_dir[t] = d
                    cue_dir[t + gap] = -d
                    t += gap + C2_CUE_STEP_PAD
                else:
                    t += 1
            else:
                t += 1

        # 收益注入(单 bar H=1):injected = d x gate x alpha,
        # gate_A = s(方向纹理), gate_B = w(wick 幅值);
        # span 保证镜像注入 = -d x gate x alpha -> 按对精确抵消
        gate = s if variant == "A" else w
        payoff = np.zeros(n)
        payoff_dir = np.zeros(n, dtype=int)
        active = np.zeros(n, dtype=int)
        for tt in range(n):
            if cue_dir[tt] == 0:
                continue
            d = int(cue_dir[tt])
            injected = alpha * float(gate[tt]) * d
            end = min(tt + 1 + H, n)
            payoff[tt + 1:end] += injected
            payoff_dir[tt + 1:end] = 1 if injected > 0 else -1
            active[tt + 1:end] = 1
        # 可见脉冲:cue 单 bar 全幅(close[t] 可读,open[t+1] 不可捕获)
        pulse_arr = np.zeros(n)
        for tt in range(n):
            if cue_dir[tt] != 0:
                pulse_arr[tt] = float(cue_dir[tt]) * pulse

        # wick 纹理计划(供 _build_ohlcv 重写 high/low)
        up, dn = _wick_log_plan(n, s, w, params, seed,
                                self.family, self.family_version)
        self._wick_plan = (up, dn)

        returns = eps + pulse_arr + payoff
        hidden = pd.DataFrame({
            "wick_dir_state": s.astype(int),
            "wick_width_state": w.astype(int),
            "cue_dir": cue_dir.astype(int),
            "payoff_active": active.astype(int),
            "payoff_dir": payoff_dir.astype(int),
            "active_gate_is_dir": np.full(
                n, 1 if variant == "A" else 0, dtype=int),
        })
        meta = {
            "family": FAMILY_C2, "variant": variant,
            "gate_binding": "wick_dir_texture" if variant == "A"
            else "wick_width_regime",
            "n_cues": int(np.count_nonzero(cue_dir)),
            "episode_bars": n,
        }
        return returns, hidden, meta

    def _build_ohlcv(self, log_returns, params, rng):
        """wick 几何纹理重写:上/下影分离偏斜(context carrier)。"""
        df = super()._build_ohlcv(log_returns, params, rng)
        plan = self._wick_plan
        self._wick_plan = None
        if plan is None:
            raise GeneratorError(
                "C2 v9 wick 纹理计划缺失(_generate 未先行执行;"
                "不得在课程外直接调用 _build_ohlcv)")
        up, dn = plan
        o = df["open"].to_numpy()
        c = df["close"].to_numpy()
        high = np.maximum(o, c) * np.exp(up)
        low = np.minimum(o, c) * np.exp(-dn)
        df["high"] = high
        df["low"] = low
        return df

    # ------------------------------------------------ 结构性校验(词表内)
    @staticmethod
    def structural_validator(episode) -> list[str]:
        return c2_structural_issues(episode)


def c2_structural_issues(episode) -> list[str]:
    """C2 结构性拒绝原因(生成时可知;generator validator 与 pair
    统一合同共用同一函数——acceptance 与 final 的判定源唯一)。"""
    issues: list[str] = []
    h = episode.hidden
    cue_dir = h["cue_dir"].to_numpy()
    s = h["wick_dir_state"].to_numpy()
    w = h["wick_width_state"].to_numpy()
    variant = str(episode.spec.params.get("pair_variant", "A"))
    gate = s if variant == "A" else w
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
def wick_score_of(observation: np.ndarray) -> float:
    """方向纹理判定特征(body-clean):high + low - open - close。

    恒等式 max(o,c)+min(o,c) = o+c 使
    score = (high - max(o,c)) - (min(o,c) - low) = 上影 - 下影,
    bar body(含 cue 脉冲的收盘收益)被精确消除——只保留 wick
    偏斜。score 期望 = ±2*kappa*wick_base(乘法价格水平的一阶
    修正被 o,c≈1 吸收)。
    """
    hi = float(observation[_WICK_COL_INDEX["high"]])
    lo = float(observation[_WICK_COL_INDEX["low"]])
    cl = float(observation[_WICK_COL_INDEX["close"]])
    op = float(observation[_WICK_COL_INDEX["open"]])
    return hi + lo - cl - op


def wick_width_of(observation: np.ndarray) -> float:
    """幅值体制判定特征(body-clean):(high - low) - |close - open|。

    wick_span = 上影 + 下影 = (high-low) - |c-o|——cue 脉冲进入
    close 收益(body)而非 wick,span 对脉冲免疫。wide/narrow 的
    span 期望 = 2 x base(wide 220bps / narrow 60bps,与 kappa 无关:
    (1+kappa*s)+(1-kappa*s) = 2)。
    """
    hi = float(observation[_WICK_COL_INDEX["high"]])
    lo = float(observation[_WICK_COL_INDEX["low"]])
    cl = float(observation[_WICK_COL_INDEX["close"]])
    op = float(observation[_WICK_COL_INDEX["open"]])
    return (hi - lo) - abs(cl - op)


class C2ReferencePolicy(ObservableBaselinePolicy):
    """C2 因果观察参考(production 特征):局部 cue 与两个正交上下文
    同时对齐(无状态)。

    入场条件(对齐立方:正 cue ∧ 方向纹理 score>0 ∧ wide 幅值):
      %-ret-1 > cue_thr 且 wick_score > wick_dir_thr 且
      wick_width > wick_width_thr。
    该子集在 variant A(门控方向纹理:需 s=+1)与 variant B(门控
    wick 幅值:需 w=+1)中门控均为对齐方向 -> 跨 variant 恒正确
    (每边各放弃一半机会作为代价)。收益注入为单 bar,无需持有。
    只读当前 observation 的四个生产特征槽位(%-ret-1 与 raw 三列)。
    """

    name = "c2_reference_context_align"

    def __init__(self, cue_thr: float, wick_dir_thr: float,
                 wick_width_thr: float):
        super().__init__()
        self.cue_thr = float(cue_thr)
        self.wick_dir_thr = float(wick_dir_thr)
        self.wick_width_thr = float(wick_width_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(
            self.read(observation, "%-ret-1") > self.cue_thr
            and wick_score_of(observation) > self.wick_dir_thr
            and wick_width_of(observation) > self.wick_width_thr)


class C2LocalOnlyPolicy(ObservableBaselinePolicy):
    """C2 local-only 基线:只看局部 15m cue(%-ret-1),完全忽略上下文。

    v9 下 cue 读数与门控按构造无关 -> 买每个正 cue 在两个 variant 上
    E[payoff] = 0,每次往返只输摩擦(双语料稳定失败)。
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

    feature 取 "%-raw-high/low/close 组合"(方向纹理)或
    "%-raw-high/low 组合"(wick 幅值),与参考读取的槽位一致——
    差异只在上下文数量,隔离"单上下文不足"。
    """

    def __init__(self, cue_thr: float, gate_thr: float, feature: str):
        super().__init__()
        if feature not in ("wick_dir", "wick_width"):
            raise ValueError(
                f"C2 单上下文基线的 feature 必须是 wick_dir/wick_width,"
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
        gate = (wick_score_of(observation) if self.feature == "wick_dir"
                else wick_width_of(observation))
        return int(r1 > self.cue_thr and gate > self.gate_thr)


class C2OraclePolicy(OraclePolicy):
    """C2 latent oracle(诊断专用):cue bar 上 d x 激活门控 > 0 即 Long。"""

    name = "c2_oracle_payoff"

    def reset_episode(self) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        gate = (ctx.hidden_row.get("wick_dir_state", 0.0)
                if ctx.hidden_row.get("active_gate_is_dir", 0) == 1
                else ctx.hidden_row.get("wick_width_state", 0.0))
        d = ctx.hidden_row.get("cue_dir", 0)
        return int(d != 0 and d * gate > 0)


# ---------------------------------------------------------------- pair 完整性
def c2_pair_integrity_metrics(episode) -> dict[str, Any]:
    """C2 pair 完整性度量(已实现统计;构造级判定见 pairs 模块)。"""
    h = episode.hidden
    cue_dir = h["cue_dir"].to_numpy()
    s = h["wick_dir_state"].to_numpy()
    w = h["wick_width_state"].to_numpy()
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    rets = np.diff(lc, prepend=0.0)
    nxt = np.concatenate([rets[1:], [np.nan]])  # cue 后一 bar(注入 bar)

    def _mean(mask: np.ndarray) -> float:
        m = mask & np.isfinite(nxt)
        return float(np.mean(nxt[m]) * 1e4) if m.sum() > 2 else float("nan")

    prev = np.concatenate([[0], cue_dir[:-1]])
    prev_s = np.concatenate([[0], s[:-1]])
    prev_w = np.concatenate([[0], w[:-1]])
    inj = prev != 0
    return {
        "variant": str(episode.spec.params.get("pair_variant", "A")),
        "n_cues": int(np.count_nonzero(cue_dir)),
        "next1_dir_aligned_bps": _mean(inj & (prev * prev_s > 0)),
        "next1_dir_anti_bps": _mean(inj & (prev * prev_s < 0)),
        "next1_width_aligned_bps": _mean(inj & (prev * prev_w > 0)),
        "next1_width_anti_bps": _mean(inj & (prev * prev_w < 0)),
        "realized_vol_bps": float(np.std(rets[1:]) * 1e4),
    }
