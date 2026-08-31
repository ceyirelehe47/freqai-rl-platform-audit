"""阶段 2.6.1 工作包 C:C1 — Opportunity Recognition(机会识别)课程族。

C1 教的能力:**什么时候市场存在值得承担 Long 风险的机会,什么时候应该
保持 Flat。**

世界模型(variant A,真实机会):
- 分段 regime 链:{opp: 每 bar 漂移 +a, neut: 0, neg: 每 bar -b};
  opp 与 neg 段的漂移总量大致平衡 -> Always Long 在全 episode 上无
  净漂移可搭,只输摩擦;
- 机会的可识别性来自 regime 的持续性:趋势特征
  (%-price-ma-ratio,生产特征 close/MA24-1)在 opp 段内持续为正,
  预测"漂移将继续";
- distractor:独立调度的短脉冲串(5 bar、随机方向、幅值 0.6a)——
  视觉上像机会启动但不持续,产生 false positive 诱惑。

pair 机制(variant B,假机会孪生):
- 与 A 共享同一随机流 / regime 边界 / distractor 表 / wick / nuisance
  (pair_variant 不进入 seed 派生);
- 唯一差别:opp/neg 段漂移全部置 0 -> 特征看起来仍会因噪声与
  distractor 出现"机会样"形态,但动量不再预测任何后续漂移;
- 因果映射差异:A 中 E[后续收益 | 动量为正] > 0,B 中 = 0(结构性
  度量见 pair_integrity_metrics)。

难度阶梯(D0->D3):漂移 a/b 下降、段长缩短、噪声上升、distractor
率上升——机会更难识别、decision margin 更薄,但 E[每次交易的捕获
edge] 始终 > 2x 往返摩擦(保证 reference 在 pair 聚合上为正)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import (
    Curriculum261Base,
    GeneratorError,
    draw_segment_chain,
    forward_sum,
    paired_noise,
)
from rl_curriculum.policy_api import (
    ObservableBaselinePolicy,
    OracleActContext,
    OraclePolicy,
)

FAMILY_C1 = "c1_opportunity"

#: C1 rung 参数(候选;最终值由 calibration 固定并进入 qualification plan)
#: drift 单位 bps/bar;vol bps;distractor_rate 为每 bar 触发概率。
#: neg 漂移按挂载段总量精确平衡:draw 后 neg_drift_eff = opp_total/
#: neg_bars,可交易区间 [1, n) 净漂移恰为 0 -> Always Long 恒等于
#: -摩擦(构造级保证)。
#: repair R1:rung 重设计。旧参数把 vol_bps 也当难度 knob(26->32),
#: 使 D3 的 pmr 触发阈值贴近噪声 3-sigma 边缘——参考策略产生大量
#: 1-bar 噪声持仓段(每段 -摩擦-噪声),D3 corpus 度量为负。新设计:
#: vol 全 rung 统一 26bps(nuisance 不做难度 knob),难度只来自漂移
#: 强度(58->24bps/bar);ma_sigma_mult 校准在 4.0(阈值 =
#: 4 x 26 x sqrt(25/72) ≈ 61bps,pmr 稳态读数 667/483/345/276bps =
#: 阈值的 11/8/5.7/4.5 倍,触发稳定性递减即难度阶梯)。
#: repair R2:相邻 rung 的漂移差拉开为 14/12/9 bps(R1 的 42->30 差
#: 12 但 D1/D2 的 qualification 度量仅差 0.7%,calibration/holdout 排序
#: 不稳);段长统一缩短到 [24, 40](更多独立机会段,压低跨语料方差)。
#: repair R2 v3(第二轮 calibration 反馈):段长**固定 24**(len_range
#: [24,24])——v2 的 [20,26] 收窄实验证明段长方差是每集净值方差的
#: 主源之一且过短段破坏 D1 ordering;固定段长完全消除该方差项
#: (策略为 MLP window=1 无记忆,固定段周期不可利用),drift 相邻差
#: 18/8/13 保持结构梯度。state_weights 的 opp 权重 0.36。
C1_RUNG_PARAMS: dict[str, dict[str, Any]] = {
    "D0": {"opp_drift_bps": 60.0, "neg_drift_bps": 46.0, "vol_bps": 26.0,
           "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
           "distractor_rate": 0.000},
    "D1": {"opp_drift_bps": 42.0, "neg_drift_bps": 33.0, "vol_bps": 26.0,
           "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
           "distractor_rate": 0.000},
    "D2": {"opp_drift_bps": 34.0, "neg_drift_bps": 27.0, "vol_bps": 26.0,
           "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
           "distractor_rate": 0.000},
    "D3": {"opp_drift_bps": 21.0, "neg_drift_bps": 16.0, "vol_bps": 26.0,
           "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
           "distractor_rate": 0.000},
}

#: C1 参考策略阈值:%-price-ma-ratio > k x sigma(pmr)(sigma 按 rung 的
#: vol_bps x sqrt(25/72) 解析闭式给出;k 在 plan 中冻结)
C1_REFERENCE_DEFAULTS = {"ma_sigma_mult": 1.0}

#: C1 结构性拒绝原因词表(预注册;不得包含任何 PnL 语义)
C1_REJECT_VOCAB = (
    "too_few_opp_segments", "too_few_flat_segments", "opp_segment_too_short",
    "flat_segment_too_short", "missing_neg_segments",
    "no_mounted_opportunity", "no_mounted_neg",
)

#: 结构性最低要求(与难度无关的合同)
C1_MIN_OPP_SEGMENTS = 1
C1_MIN_FLAT_SEGMENTS = 2
C1_MIN_OPP_LEN = 12
C1_MIN_FLAT_LEN = 10
#: repair R2:实际挂载(进入可交易区间 [1, n) 且 drift 真实非零)的
#: 机会/负机会 bar 数下限——R1 的 pair integrity 0.90 根因是首段
#: (为水平归零不挂载)承担了全部 opp 标签,latent 有机会而实际无
#: 机会;统一合同要求"标签有机会"必须蕴含"收益机制有机会"。
C1_MIN_MOUNTED_OPP_BARS = 12
C1_MIN_MOUNTED_NEG_BARS = 8


class C1OpportunityGenerator(Curriculum261Base):
    """C1 生成器:分段机会世界 + 假机会孪生 variant。"""

    family = FAMILY_C1
    family_version = "cur261-c1-v5"
    hidden_columns = [
        "seg_state", "regime_drift_bps", "bars_to_seg_end", "seg_index",
    ]

    def _generate(self, params, seed, rng):
        n = int(params["episode_bars"])
        variant = str(params.get("pair_variant", "A"))
        if variant not in ("A", "B"):
            raise GeneratorError(f"非法 pair_variant {variant!r}")
        opp = float(params["opp_drift_bps"]) * 1e-4
        neg = float(params["neg_drift_bps"]) * 1e-4
        vol = float(params["vol_bps"]) * 1e-4
        lo_len, hi_len = params["seg_len_range"]
        weights = np.asarray(params["state_weights"], dtype=float)
        dis_rate = float(params.get("distractor_rate", 0.0))

        # repair R2 v5:固定段模式 [neut, opp, neut, neg] x 3
        # (段长 24,共 12 段 = 288 bar)——n_opp_bars / n_neg_bars
        # 逐集恒定(各 72 bar),消除 v4 中主导度量的段数抽样方差
        # (oracle D1/D2 重合的根因);首段 neut 天然满足水平合同的
        # 首段不挂载。weights/draw_segment_chain 参数保留在 rung
        # 参数中仅为 schema 兼容,不再参与生成。
        seg_len = int(lo_len)
        if seg_len != int(hi_len) or n != seg_len * 12:
            raise GeneratorError(
                f"C1 v5 段表合同:段长必须固定且 12 段 = episode_bars"
                f"(seg_len={seg_len}, n={n})")
        pattern = [1, 2, 1, 0]  # neut, opp, neut, neg
        states = np.tile(np.repeat(np.array(pattern), seg_len),
                         n // (seg_len * 4))
        to_end = np.empty(n, dtype=int)
        for i in range(n):
            to_end[i] = seg_len - 1 - (i % seg_len)
        # 0=neg, 1=neut, 2=opp;neg 漂移按总量精确平衡(净漂移恒 0)
        # repair R1 水平合同:含 t=0 的第一段不挂漂移(环境可交易区间
        # 是 [1, n),t=0 的漂移无法被任何策略捕获却计入水平);平衡只在
        # 挂载段([1, n))内成立 -> sum(drift[1:]) 恒为 0。
        # repair R2 结构修复:第一段直接**强制改写为 neut**——R1 把首段
        # 漂移清零但保留 opp/neg 标签,当全部机会段恰好落在首段时,
        # latent 有机会而收益机制无机会(final integrity 0.90 的根因)。
        # 首段恒为 neut 后,任何 opp/neg 段必然在挂载区内,标签与收益
        # 机制一致;首段自身 drift=0(neut 天然不挂),水平合同不变。
        first_end = seg_len  # 固定模式首段即 neut(挂载区 [1, n))
        first_seg_mask = np.zeros(n, dtype=bool)
        first_seg_mask[:first_end] = True
        mount = ~first_seg_mask
        n_opp = int(np.sum(mount & (states == 2)))
        n_neg = int(np.sum(mount & (states == 0)))
        opp_drift = opp
        neg_drift = (n_opp * opp_drift / n_neg) if n_neg > 0 else 0.0
        drift_map = {0: -neg_drift, 1: 0.0, 2: opp_drift}
        drift = np.array([drift_map[int(s)] for s in states], dtype=float)
        drift[first_seg_mask] = 0.0
        if variant == "B":
            drift = np.zeros(n)  # 假机会孪生:去除全部 regime 漂移

        # distractor 脉冲串(A/B 共享同一调度;短、不持续、随机方向)
        distractor = np.zeros(n)
        if dis_rate > 0:
            t = 8
            while t < n - 6:
                if rng.random() < dis_rate * 1.0:
                    length = 5
                    sign = 1.0 if rng.random() < 0.5 else -1.0
                    end = min(t + length, n)
                    distractor[t:end] = sign * 0.6 * opp
                    t += length + 4
                else:
                    t += 1
        noise_rng = np.random.default_rng(self.derive_seed(
            {**params, "_noise": "market"}, seed))
        noise = vol * paired_noise(
            noise_rng, n,
            mutate_from=params.get("noise_mutate_from"),
            mutate_salt=params.get("noise_mutate_salt"))
        # 漂移按段总量精确平衡 + 噪声配对抵消 -> 价格水平自然归零,
        # 无需 OU 回拉(回拉的 gap 拖拽反而破坏配对抵消)
        returns = drift + distractor + noise

        seg_idx = np.zeros(n, dtype=int)
        run = 0
        for i in range(n):
            seg_idx[i] = run
            if to_end[i] == 0 and i + 1 < n:
                run += 1
        hidden = pd.DataFrame({
            "seg_state": states.astype(int),
            "regime_drift_bps": drift / 1e-4,
            "bars_to_seg_end": to_end.astype(int),
            "seg_index": seg_idx,
        })
        meta = {
            "family": FAMILY_C1, "variant": variant,
            "n_opp_segments": len(_segment_lengths(states, 2)),
            "episode_bars": n,
        }
        return returns, hidden, meta

    # ------------------------------------------------ 结构性校验(词表内)
    @staticmethod
    def structural_validator(episode) -> list[str]:
        return c1_structural_issues(episode)


def c1_structural_issues(episode) -> list[str]:
    """C1 结构性拒绝原因(生成时可知;generator validator 与 pair
    统一合同共用同一函数——acceptance 与 final 的判定源唯一)。"""
    issues: list[str] = []
    h = episode.hidden
    states = h["seg_state"].to_numpy()
    opp_lens = _segment_lengths(states, 2)
    flat_lens = (_segment_lengths(states, 0)
                 + _segment_lengths(states, 1))
    if len(opp_lens) < C1_MIN_OPP_SEGMENTS:
        issues.append("too_few_opp_segments")
    if len(_segment_lengths(states, 0)) < 1:
        issues.append("missing_neg_segments")
    if len(flat_lens) < C1_MIN_FLAT_SEGMENTS:
        issues.append("too_few_flat_segments")
    if opp_lens and min(opp_lens) < C1_MIN_OPP_LEN:
        issues.append("opp_segment_too_short")
    if flat_lens and min(flat_lens) < C1_MIN_FLAT_LEN:
        issues.append("flat_segment_too_short")
    # repair R2:实际挂载的机会/负机会 bar 数——只对 variant A 生效
    # (B 是假机会孪生,drift 恒 0 是其合同;首段强制 neut 后 A 的
    # 标签机会必然伴随收益机制机会,此检查是统一合同的生成时闸门)
    variant = str(episode.spec.params.get("pair_variant", "A"))
    if variant == "A":
        drift_bps = h["regime_drift_bps"].to_numpy()
        if int(np.count_nonzero(
                drift_bps > 0)) < C1_MIN_MOUNTED_OPP_BARS:
            issues.append("no_mounted_opportunity")
        if int(np.count_nonzero(
                drift_bps < 0)) < C1_MIN_MOUNTED_NEG_BARS:
            issues.append("no_mounted_neg")
    return [i for i in issues if i in C1_REJECT_VOCAB]


def _segment_lengths(states: np.ndarray, state: int) -> list[int]:
    lens: list[int] = []
    run = 0
    for s in states:
        if int(s) == state:
            run += 1
        elif run:
            lens.append(run)
            run = 0
    if run:
        lens.append(run)
    return lens


# ---------------------------------------------------------------- 策略层
class C1ReferencePolicy(ObservableBaselinePolicy):
    """C1 因果观察参考:趋势偏离超噪声门限 + 动量确认。

    只读当前 observation 的 %-price-ma-ratio / %-ret-4 槽位;阈值 =
    ma_sigma_mult x vol_bps/sqrt(24)(rung 参数的闭式解析,
    calibration 固定倍数)。动量确认使退出更快(机会段结束即离场,
    减少横盘拖拽与噪声再入场)。无隐藏状态、无未来、无 episode 身份。
    """

    name = "c1_reference_trend_reader"

    def __init__(self, ma_dev_thr: float):
        super().__init__()
        self.ma_dev_thr = float(ma_dev_thr)

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(
            self.read(observation, "%-price-ma-ratio") > self.ma_dev_thr
            and self.read(observation, "%-ret-4") > 0.0
        )


def c1_reference_threshold(rung_params: dict[str, Any],
                           ma_sigma_mult: float) -> float:
    """k-sigma 门限闭式解析(repair R1,production 口径,已校正)。

    %-price-ma-ratio = close/MA24 - 1 ≈ (close - MA24)/MA24。
    i.i.d. 噪声(sigma = vol)下 close - MA24 = sum_i w_i r_{t-i},
    w_i = (23-i)/24(i=0..23,全部为正:close-MA = (1/24)sum_{j=1}^{23}
    sum_{i<j} r_{t-i} 的展开系数) -> sum w^2 = 4324/576 = 7.507
    -> pmr 噪声 sigma = vol x 2.740。
    (repair R1 初版误用 sqrt(25/72)=0.589 与带负号的 4853/576=2.902;
    repair R2 修正为全正权重闭式 2.740。)
    """
    vol = float(rung_params["vol_bps"]) * 1e-4
    return float(ma_sigma_mult * vol * np.sqrt(4324.0 / 576.0))


class C1ShortcutPolicy(ObservableBaselinePolicy):
    """C1 family-specific 简单基线:朴素动量(短窗口单特征)。"""

    name = "c1_shortcut_naive_momentum"

    def reset_episode(self) -> None:
        return None

    def act(self, observation: np.ndarray) -> int:
        return int(self.read(observation, "%-ret-4") > 0.0)


class C1OraclePolicy(OraclePolicy):
    """C1 latent oracle(诊断专用,绝不对候选可见)。

    读当前行 sidecar:处于 opp 段且距段尾 >= 2 bar -> Long。
    """

    name = "c1_oracle_segment"

    def reset_episode(self) -> None:
        return None

    def act(self, ctx: OracleActContext) -> int:
        return int(
            ctx.hidden_row.get("seg_state", 0) == 2
            and ctx.hidden_row.get("bars_to_seg_end", 0) >= 2
        )


# ---------------------------------------------------------------- pair 完整性
def c1_pair_integrity_metrics(episode) -> dict[str, Any]:
    """C1 pair 完整性度量(分析 sidecar + 价格,不进入 observation)。

    causal_signal:A 中动量特征对后续 16 bar 收益的预测性(相关性);
    variant B 必须显著为 0。由 pair 校验在 A/B 聚合上判定。
    """
    h = episode.hidden
    states = h["seg_state"].to_numpy()
    lc = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    rets = np.diff(lc, prepend=0.0)
    fwd = forward_sum(rets, 16)
    ma_dev = episode.df["%-price-ma-ratio"].to_numpy(dtype=np.float64)
    in_opp = states == 2
    n_opp = int(in_opp.sum())
    edge_in_opp = float(np.mean(fwd[in_opp])) if n_opp else float("nan")
    both = np.isfinite(fwd) & np.isfinite(ma_dev)
    if both.sum() > 2:
        corr = float(np.corrcoef(ma_dev[both], fwd[both])[0, 1])
    else:
        corr = float("nan")
    return {
        "variant": str(episode.spec.params.get("pair_variant", "A")),
        "n_opp_bars": n_opp,
        "n_opp_segments": len(_segment_lengths(states, 2)),
        "fwd16_mean_in_opp_bps": edge_in_opp * 1e4,
        "corr_pmr_fwd16": corr,
        "realized_vol_bps": float(np.std(rets[1:]) * 1e4),
    }
