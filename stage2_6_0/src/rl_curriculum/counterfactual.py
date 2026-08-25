"""工作包 H + I:反事实与反作弊考试(成对 Episode 变换器)。

12 项考试:
 1. common_prefix_future_suffix  共同前缀/不同未来后缀(因果性硬测试)
 2. price_scale_invariance       价格尺度不变性(×0.1/×10/×100)
 3. initial_price_invariance     初始价格不变性(保持相对收益路径)
 4. episode_length_invariance    Episode 长度不变性(共享前缀长短对)
 5. time_shift_invariance        Episode 起始时间平移
 6. regime_order_randomization   Regime 顺序随机化
 7. irrelevant_feature_injection 无关特征注入
 8. irrelevant_feature_shuffle   无关特征置乱
 9. signal_ablation              真信号消融
10. trend_mirror                 趋势方向镜像
11. cost_monotonicity            成本单调性(fee/滑点递增)
12. null_control                 Null Control

作弊分类:综合各考试证据输出机读作弊原因
(episode_position / absolute_price / periodic_pattern / future_leak /
null_overtrading),由 verdicts 判 SUSPECTED_CHEATING 或 FAIL。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.evaluator import (
    EvalConfig,
    EpisodeResult,
    paired_bootstrap_ci,
    run_episode,
)
from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    EpisodeSpec,
    GeneratedEpisode,
    PRICE_COLUMNS,
)
from rl_curriculum.policies import ActContext, Policy

# 动作一致率阈值:合理策略在结构不变变换下应为 1.0
ACTION_MATCH_THRESHOLD = 0.999
# 高换手阈值(Null Control 判定)
NULL_HIGH_TURNOVER_THRESHOLD = 0.5


@dataclass
class PairResult:
    name: str
    variant_label: str
    pass_: bool
    reason: str
    action_match_rate: float | None = None
    first_divergence_step: int | None = None
    base: dict[str, float] = field(default_factory=dict)
    variant: dict[str, float] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_record(self) -> dict[str, Any]:
        return {
            "test": self.name, "variant": self.variant_label,
            "pass": self.pass_, "reason": self.reason,
            "action_match_rate": self.action_match_rate,
            "first_divergence_step": self.first_divergence_step,
            "base": self.base, "variant": self.variant,
            "extra": self.extra,
        }


# ------------------------------------------------------------------ helpers
def _returns_of(df: pd.DataFrame) -> np.ndarray:
    log_close = np.log(df["close"].to_numpy(dtype=np.float64))
    return np.diff(log_close, prepend=float(np.log(df["open"].iloc[0])))


def _wrap(
    base: GeneratedEpisode, df: pd.DataFrame, hidden: pd.DataFrame | None,
    split: str | None = None,
) -> GeneratedEpisode:
    spec = EpisodeSpec(
        family=base.spec.family, params=dict(base.spec.params),
        seed=base.spec.seed,
        split=split or base.spec.split,
    )
    return GeneratedEpisode(
        spec=spec, df=df,
        hidden=hidden if hidden is not None else base.hidden,
        family_version=base.family_version, timeframe=base.timeframe,
        is_null=base.is_null, generator_fingerprint=base.generator_fingerprint,
        meta=dict(base.meta),
    )


def _run(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig
) -> tuple[EpisodeResult, list[int]]:
    return run_episode(policy, episode, cfg, return_actions=True)


def _summary(r: EpisodeResult) -> dict[str, float]:
    return {
        "net_return": r.net_return, "turnover_rate": r.turnover_rate,
        "avg_position": r.avg_position, "n_trades": float(r.n_trades),
        "total_fees": r.total_fees,
    }


def _match(base_actions: list[int], var_actions: list[int], n: int) -> tuple[float, int | None]:
    m = sum(1 for a, b in zip(base_actions[:n], var_actions[:n]) if a == b)
    rate = m / max(n, 1)
    first_div = next(
        (i for i in range(n) if base_actions[i] != var_actions[i]), None
    )
    return float(rate), first_div


def _rebuild(
    generator: BaseMarketGenerator, base: GeneratedEpisode,
    returns: np.ndarray, hidden: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from rl_curriculum.generators import _attach_probe_features

    params = dict(base.spec.params)
    params["initial_price"] = float(base.df["open"].iloc[0])
    rng = np.random.default_rng(generator.derive_seed(params, base.spec.seed))
    df = generator._build_ohlcv(returns, params, rng)  # noqa: SLF001
    df = _attach_probe_features(df)
    # 保留 date 列(与 base 对齐的构造方式)
    secs = {"5m": 300, "15m": 900, "1h": 3600}[base.timeframe]
    df.insert(0, "date", pd.date_range(
        "2026-01-01T00:00:00Z", periods=len(df), freq=f"{secs}s"))
    if hidden is not None and len(hidden) != len(df):
        raise ValueError(
            f"重建 hidden 行数 {len(hidden)} != df {len(df)}"
        )
    return df


_PROBE_FEATURE_COLUMNS = ("ret_1", "ret_4", "ret_12", "vol_24", "ma_ratio")


def recompute_probe_features(df: pd.DataFrame) -> pd.DataFrame:
    """从价格列重算探针特征(因果滚动;对同一前缀输出逐位一致)。"""
    from rl_curriculum.generators import _attach_probe_features

    keep = [c for c in df.columns
            if c in ("date", "open", "high", "low", "close", "volume")]
    return _attach_probe_features(
        df[keep].copy().reset_index(drop=True)
    )


def splice_prefix_suffix(
    base_df: pd.DataFrame, other_df: pd.DataFrame, cut: int
) -> pd.DataFrame:
    """共同前缀拼接:前 cut 行逐位保留 base,后缀按几何收益接 other。

    后缀价格整体缩放 k = base.close[cut-1] / other.close[cut-1]
    (相对收益路径与 other 一致,价格水平与 base 连续:
    open'[cut] == base.close[cut-1]);特征对最终价格序列重算,
    因果滚动保证前缀特征与 base 逐位一致(避免重建浮点漂移)。
    """
    n_b, n_o = len(base_df), len(other_df)
    if not (0 < cut <= n_b and cut < n_o):
        raise ValueError(
            f"cut={cut} 越界(base={n_b},other={n_o})")
    k = float(base_df["close"].iloc[cut - 1] / other_df["close"].iloc[cut - 1])
    out = base_df.iloc[:cut].copy()
    tail = other_df.iloc[cut:].copy()
    for col in ("open", "high", "low", "close"):
        tail[col] = tail[col].to_numpy() * k
    out = pd.concat([out, tail], ignore_index=True)
    return recompute_probe_features(out)


def mirror_df(df: pd.DataFrame) -> pd.DataFrame:
    """趋势方向镜像(log 域取反):close' = p0^2 / close,high/low 互换镜像。

    相对收益路径取反(正向机会 -> 负向机会);open 连续性与 OHLC
    合法性由构造保持;特征重算。
    """
    p0 = float(df["open"].iloc[0])
    out = df.copy()
    for col in ("open", "close"):
        out[col] = p0 * p0 / df[col]
    out["high"] = p0 * p0 / df["low"]
    out["low"] = p0 * p0 / df["high"]
    return recompute_probe_features(out)


# ------------------------------------------------------------ 1. 共同前缀
def test_common_prefix_future_suffix(
    generator: BaseMarketGenerator, policy: Policy,
    episode: GeneratedEpisode, cfg: EvalConfig,
    cut_ratio: float = 0.5,
) -> PairResult:
    """Episode A 与 C 在 t 前完全一致,t 后未来路径不同。

    要求:t 及之前 observation 完全一致(C 构造时断言),deterministic
    policy 在 t 及之前动作完全一致;不一致则判定未来泄漏或生成器泄漏。
    """
    n = len(episode.df)
    cut = int(n * cut_ratio)
    other = generator.generate(
        episode.spec.params, episode.spec.seed + 10_000,
        split=episode.spec.split, timeframe=episode.timeframe,
    )
    df_c = splice_prefix_suffix(episode.df, other.df, cut)
    hidden_c = (
        pd.concat([episode.hidden.iloc[:cut], other.hidden.iloc[cut:]],
                  ignore_index=True)
        if len(episode.hidden.columns) else episode.hidden
    )
    # 硬断言:共同前缀 observation(OHLC + 特征)逐位一致
    cols = [c for c in df_c.columns if c != "date"]
    same_prefix = bool(
        df_c[cols].iloc[:cut].equals(episode.df[cols].iloc[:cut])
    )
    if not same_prefix:
        return PairResult(
            name="common_prefix_future_suffix",
            variant_label=f"t_cut={cut}/{n}",
            pass_=False,
            reason="共同前缀构造失败:变换后前缀 OHLC/特征与原始不一致"
                   "(生成器泄漏或重建不确定性)",
        )
    variant = _wrap(episode, df_c, hidden_c, split="common_prefix_variant")
    base_r, base_a = _run(policy, episode, cfg)
    var_r, var_a = _run(policy, variant, cfg)
    nd = min(len(base_a), len(var_a))
    rate, first_div = _match(base_a, var_a, min(nd, cut))
    ok = rate >= ACTION_MATCH_THRESHOLD
    return PairResult(
        name="common_prefix_future_suffix", variant_label=f"t_cut={cut}/{n}",
        pass_=ok,
        reason=(
            "共同前缀内动作完全一致(因果)"
            if ok else
            f"共同前缀内动作分歧(一致率 {rate:.3f},首个分歧 step="
            f"{first_div}):未来后缀影响了过去决策 -> 未来泄漏"
        ),
        action_match_rate=rate, first_divergence_step=first_div,
        base=_summary(base_r), variant=_summary(var_r),
    )


# ------------------------------------------------- 2/3. 价格尺度与初始价格
def _scaled_df(df: pd.DataFrame, k: float) -> pd.DataFrame:
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * k
    return out


def test_price_scale_invariance(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    scales: tuple[float, ...] = (0.1, 10.0, 100.0),
) -> PairResult:
    """所有价格乘 k,收益与相对关系不变 -> 动作应保持一致。"""
    base_r, base_a = _run(policy, episode, cfg)
    worst_rate, worst_k, worst_div = 1.0, None, None
    for k in scales:
        scaled = _wrap(episode, _scaled_df(episode.df, k), None,
                       split="price_scale_variant")
        var_r, var_a = _run(policy, scaled, cfg)
        rate, first_div = _match(base_a, var_a, len(base_a))
        if rate < worst_rate:
            worst_rate, worst_k, worst_div = rate, k, first_div
    ok = worst_rate >= ACTION_MATCH_THRESHOLD
    return PairResult(
        name="price_scale_invariance", variant_label=f"scales={list(scales)}",
        pass_=ok,
        reason=(
            "各价格尺度下动作一致(无绝对价格依赖)"
            if ok else
            f"尺度 ×{worst_k} 下动作分歧(一致率 {worst_rate:.3f},"
            f"首个分歧 step={worst_div}) -> 绝对价格依赖"
        ),
        action_match_rate=worst_rate, first_divergence_step=worst_div,
        base=_summary(base_r),
        extra={"worst_scale": worst_k},
    )


def test_initial_price_invariance(
    generator: BaseMarketGenerator, policy: Policy,
    episode: GeneratedEpisode, cfg: EvalConfig,
    new_initial_prices: tuple[float, ...] = (50.0, 500.0),
) -> PairResult:
    """只修改 Episode 初始价格,不修改相对收益路径 -> 行为应保持一致。

    实现:整条价格路径按 k = p0_target / p0 缩放(相对收益路径不变,
    特征为尺度不变量),与 price_scale 的区别是语义锚点(初始价而非
    任意尺度),用于单独暴露初始价格水平依赖。
    """
    base_r, base_a = _run(policy, episode, cfg)
    p0 = float(episode.df["open"].iloc[0])
    worst_rate, worst_p0, worst_div = 1.0, None, None
    for target in new_initial_prices:
        variant = _wrap(
            episode, _scaled_df(episode.df, target / p0), None,
            split="initial_price_variant",
        )
        var_r, var_a = _run(policy, variant, cfg)
        rate, first_div = _match(base_a, var_a, len(base_a))
        if rate < worst_rate:
            worst_rate, worst_p0, worst_div = rate, target, first_div
    ok = worst_rate >= ACTION_MATCH_THRESHOLD
    return PairResult(
        name="initial_price_invariance",
        variant_label=f"initial_prices={list(new_initial_prices)}",
        pass_=ok,
        reason=(
            "初始价格变化下动作一致(无初始价依赖)"
            if ok else
            f"初始价 {worst_p0} 下动作分歧(一致率 {worst_rate:.3f},"
            f"首个分歧 step={worst_div}) -> 初始价格依赖"
        ),
        action_match_rate=worst_rate, first_divergence_step=worst_div,
        base=_summary(base_r), extra={"worst_initial_price": worst_p0},
    )


# ------------------------------------------------------ 4. Episode 长度
def test_episode_length_invariance(
    generator: BaseMarketGenerator, policy: Policy,
    episode: GeneratedEpisode, cfg: EvalConfig,
    short_ratio: float = 0.6,
) -> PairResult:
    """共享完全相同前缀的短/长 Episode:共同前缀中的动作必须一致。"""
    n = len(episode.df)
    n_short = int(n * short_ratio)
    long_params = dict(episode.spec.params)
    long_params["episode_bars"] = n + 48
    extra = generator.generate(
        long_params, episode.spec.seed + 20_000,
        split=episode.spec.split, timeframe=episode.timeframe,
    )
    # 短 Episode:直接截断(前缀特征逐位保留);
    # 长 Episode:前 n 行逐位保留 base,后缀按几何收益接 extra。
    df_short = episode.df.iloc[:n_short].reset_index(drop=True)
    df_long = splice_prefix_suffix(episode.df, extra.df, n)
    cols = [c for c in df_short.columns if c != "date"]
    prefix_ok = bool(
        df_long[cols].iloc[:n].equals(episode.df[cols])
        and df_short[cols].equals(episode.df[cols].iloc[:n_short])
    )
    if not prefix_ok:
        return PairResult(
            name="episode_length_invariance",
            variant_label=f"short={n_short},long={len(df_long)}",
            pass_=False,
            reason="长短 Episode 共同前缀构造失败(与原始前缀不一致)",
        )
    hidden_short = episode.hidden.iloc[:n_short].reset_index(drop=True)
    hidden_long = pd.concat(
        [episode.hidden, extra.hidden.iloc[n:]], ignore_index=True
    ) if len(episode.hidden.columns) else episode.hidden
    short_ep = _wrap(episode, df_short, hidden_short, split="length_short")
    long_ep = _wrap(episode, df_long, hidden_long, split="length_long")
    r_short, a_short = _run(policy, short_ep, cfg)
    r_long, a_long = _run(policy, long_ep, cfg)
    # 比较窗口:两者共同的前 n_short - 1 个决策(exec bar 须存在)
    cmp_n = n_short - 1
    rate, first_div = _match(a_short, a_long, cmp_n)
    ok = rate >= ACTION_MATCH_THRESHOLD
    return PairResult(
        name="episode_length_invariance",
        variant_label=f"short={n_short},long={len(df_long)}",
        pass_=ok,
        reason=(
            "共同前缀动作一致(无固定终点倒计时依赖)"
            if ok else
            f"Episode 长度变化改变共同前缀动作(一致率 {rate:.3f},"
            f"首个分歧 step={first_div}) -> 依赖 Episode 位置/倒计时"
        ),
        action_match_rate=rate, first_divergence_step=first_div,
        base=_summary(r_short), variant=_summary(r_long),
    )


# ---------------------------------------------------------- 5. 时间平移
def test_time_shift_invariance(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    shift_hours: int = 37,
) -> PairResult:
    """只平移时间戳(课程未允许日历特征)-> 动作应保持一致。"""
    df_shift = episode.df.copy()
    df_shift["date"] = df_shift["date"] + pd.Timedelta(hours=shift_hours)
    if df_shift["date"].equals(episode.df["date"]):
        return PairResult(
            name="time_shift_invariance", variant_label=f"+{shift_hours}h",
            pass_=False, reason="时间平移变换未生效(测试无效)",
        )
    base_r, base_a = _run(policy, episode, cfg)
    var_r, var_a = _run(policy, _wrap(episode, df_shift, None, "time_shift"),
                        cfg)
    rate, first_div = _match(base_a, var_a, len(base_a))
    ok = rate >= ACTION_MATCH_THRESHOLD
    return PairResult(
        name="time_shift_invariance", variant_label=f"+{shift_hours}h",
        pass_=ok,
        reason=(
            "时间平移下动作一致(无日历/时刻依赖)"
            if ok else
            f"时间平移改变动作(一致率 {rate:.3f},首个分歧 step="
            f"{first_div}) -> 依赖时间戳"
        ),
        action_match_rate=rate, first_divergence_step=first_div,
        base=_summary(base_r), variant=_summary(var_r),
    )


# ------------------------------------------------- 6. Regime 顺序随机化
def test_regime_order_randomization(
    generator: BaseMarketGenerator, policy: Policy,
    episode: GeneratedEpisode, cfg: EvalConfig,
) -> PairResult:
    """相同类型的 regime 不同顺序出现。

    判定:策略动作序列在市场内容重排后仍与原序列完全一致 ->
    策略不读市场观察(位置/周期型);若其原序列成绩又高于 trivial
    (中位收益 > 0),标记作弊嫌疑(由分类器结合作弊证据使用)。
    """
    if "regimes" not in episode.meta:
        return PairResult(
            name="regime_order_randomization", variant_label="n/a",
            pass_=True, reason="生成器族无分段 regime(探针 B/C 不适用)",
        )
    regimes = [list(r) for r in episode.meta["regimes"]]
    if len(regimes) < 2:
        return PairResult(
            name="regime_order_randomization", variant_label="single-regime",
            pass_=True, reason="Episode 仅一个 regime,顺序随机化不适用",
        )
    base_r, base_a = _run(policy, episode, cfg)
    worst_same, tested = 1.0, 0
    var_returns_all = []
    for shift in (1, 2):  # 两种确定性重排(保持段集合不变)
        shuffled = regimes[shift:] + regimes[:shift]
        params = dict(episode.spec.params)
        params["regimes"] = shuffled
        var_ep = generator.generate(
            params, episode.spec.seed, split=episode.spec.split,
            timeframe=episode.timeframe,
        )
        var_r, var_a = _run(policy, var_ep, cfg)
        var_returns_all.append(_summary(var_r))
        tested += 1
        if len(var_a) == len(base_a) and var_a == base_a:
            worst_same = min(worst_same, 1.0)
        else:
            worst_same = 0.0
    unresponsive = tested > 0 and worst_same == 1.0
    above_flat = base_r.net_return > 0.0
    ok = not unresponsive
    return PairResult(
        name="regime_order_randomization",
        variant_label=f"rotations={tested}",
        pass_=ok,
        reason=(
            "策略响应市场内容(重排后动作变化):根据市场观察行动"
            if ok else
            "regime 顺序重排后动作序列完全不变:策略不读市场观察,"
            "依赖固定位置/固定周期 -> 位置/周期型作弊(若同时成绩为正"
            "则构成 SUSPECTED_CHEATING 证据)"
        ),
        action_match_rate=(1.0 if unresponsive else 0.0),
        base=_summary(base_r), variant=var_returns_all[0] if var_returns_all else {},
        extra={"market_unresponsive": unresponsive,
               "base_net_return_positive": above_flat,
               "action_period": detect_periodicity(base_a)},
    )


# --------------------------------------------- 7/8/9. 特征注入/置乱/消融
def _with_extra_columns(
    df: pd.DataFrame, cols: dict[str, np.ndarray]
) -> pd.DataFrame:
    out = df.copy()
    for name, arr in cols.items():
        out[name] = arr
    return out


def test_irrelevant_feature_injection(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    n_noise: int = 3, seed: int = 555,
) -> PairResult:
    """注入独立随机噪声特征:行为和成绩不应显著改善。"""
    rng = np.random.default_rng(seed)
    noise = {
        f"noise_{i}": rng.standard_normal(len(episode.df))
        for i in range(n_noise)
    }
    base_r, base_a = _run(policy, episode, cfg)
    var_ep = _wrap(
        episode, _with_extra_columns(episode.df, noise), None,
        "noise_injected",
    )
    try:
        var_r, var_a = _run(policy, var_ep, cfg)
    except Exception as exc:  # noqa: BLE001 - 观察维度变化 fail closed
        return PairResult(
            name="irrelevant_feature_injection",
            variant_label=f"noise={n_noise}",
            pass_=False,
            reason=f"注入特征后策略崩溃(观察维度守卫): {exc!r}",
        )
    actions_same = var_a == base_a
    improved = var_r.net_return > base_r.net_return + 1e-12
    ok = actions_same or not improved
    return PairResult(
        name="irrelevant_feature_injection", variant_label=f"noise={n_noise}",
        pass_=ok,
        reason=(
            "噪声特征不改变行为或不改善成绩"
            if ok else "噪声特征显著改善成绩(记忆噪声/过拟合迹象)"
        ),
        action_match_rate=1.0 if actions_same else 0.0,
        base=_summary(base_r), variant=_summary(var_r),
    )


def test_irrelevant_feature_shuffle(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    column: str = "vol_24", seed: int = 777,
) -> PairResult:
    """置乱理论上不相关的字段(vol_24 对趋势规则策略不相关)-> 结果不应明显变化。"""
    if column not in episode.df.columns:
        return PairResult(
            name="irrelevant_feature_shuffle", variant_label=column,
            pass_=False, reason=f"特征列 {column} 不存在(测试无效)",
        )
    rng = np.random.default_rng(seed)
    df_s = episode.df.copy()
    df_s[column] = rng.permutation(df_s[column].to_numpy())
    base_r, base_a = _run(policy, episode, cfg)
    var_r, var_a = _run(
        policy, _wrap(episode, df_s, None, "feature_shuffled"), cfg
    )
    actions_same = var_a == base_a
    diff = abs(var_r.net_return - base_r.net_return)
    ok = actions_same or diff < 1e-9
    return PairResult(
        name="irrelevant_feature_shuffle", variant_label=column,
        pass_=ok,
        reason=(
            "置乱无关特征不改变行为或成绩"
            if ok else
            f"置乱无关特征 {column} 改变成绩(|Δ|={diff:.3e})"
        ),
        action_match_rate=1.0 if actions_same else 0.0,
        base=_summary(base_r), variant=_summary(var_r),
        extra={"abs_net_return_diff": diff},
    )


def test_signal_ablation(
    policy: Policy, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    signal_columns: tuple[str, ...] = ("ma_ratio", "ret_4"),
    seeds: tuple[int, ...] = (888, 889, 890),
) -> PairResult:
    """删除/时间置乱真正可预测的观察信号 -> 模型优势应明显下降。

    多 Episode 聚合判定(单 seed 的置换噪声会使个体方向不稳定):
    置乱后扣费收益中位数应低于原始中位数(中位优势下降)。
    """
    rng = np.random.default_rng(seeds[0])
    base_nets, var_nets = [], []
    for ep in episodes:
        df_a = ep.df.copy()
        for col in signal_columns:
            if col in df_a.columns:
                df_a[col] = rng.permutation(df_a[col].to_numpy())
        base_r, _a = _run(policy, ep, cfg)
        var_r, _v = _run(policy, _wrap(ep, df_a, None, "signal_ablated"), cfg)
        base_nets.append(base_r.net_return)
        var_nets.append(var_r.net_return)
    drop_median = float(np.median(base_nets) - np.median(var_nets))
    ok = drop_median > 0.0  # 中位优势下降
    return PairResult(
        name="signal_ablation", variant_label=f"ablate={list(signal_columns)}",
        pass_=bool(ok),
        reason=(
            f"真信号置乱后中位优势下降(median {np.median(base_nets):+.5f} -> "
            f"{np.median(var_nets):+.5f})"
            if ok else
            "真信号置乱后中位优势未下降:模型没有学到所声称的能力"
            "(或考试无效)"
        ),
        base={"median_net_return": float(np.median(base_nets)),
              "net_returns": base_nets},
        variant={"median_net_return": float(np.median(var_nets)),
                 "net_returns": var_nets},
        extra={"median_advantage_drop": drop_median},
    )


# ------------------------------------------------------------ 10. 趋势镜像
def test_trend_direction_mirror(
    policy: Policy, episodes: list[GeneratedEpisode], cfg: EvalConfig,
) -> PairResult:
    """收益取反(正向机会 -> 负向):Long/Flat 模型应保持方向性响应。

    多 Episode 聚合判定(方向捕获):capture = sum(action[t] *
    log_return[t+1]) 在原始与镜像市场中位数为正——趋势方向反转后
    策略的持仓也随之反转,才证明模型根据市场方向行动;不读方向的
    策略(位置/周期型)capture 不稳定。同时报告镜像前后多头暴露
    变化供诊断。
    """
    caps_base, caps_mirror = [], []
    pos_base, pos_mirror = [], []
    base_nets, var_nets = [], []
    for ep in episodes:
        base_r, base_a = _run(policy, ep, cfg)
        mirrored = _wrap(ep, mirror_df(ep.df), None, "trend_mirrored")
        # 镜像市场的隐藏状态同步反转(方向性列取反;计数列不变)
        if len(ep.hidden.columns):
            mh = ep.hidden.copy()
            if "regime_direction" in mh.columns:
                mh["regime_direction"] = -mh["regime_direction"]
            if "latent_drift_bps" in mh.columns:
                mh["latent_drift_bps"] = -mh["latent_drift_bps"]
            if "regime_strength_bps" in mh.columns:
                mh["regime_strength_bps"] = -mh["regime_strength_bps"]
            mirrored.hidden = mh
        var_r, var_a = _run(policy, mirrored, cfg)
        rets = _returns_of(ep.df)
        n = min(len(base_a), len(rets) - 1)
        caps_base.append(
            sum(base_a[i] * rets[i + 1] for i in range(n)))
        caps_mirror.append(
            sum(var_a[i] * (-rets[i + 1]) for i in range(n)))
        pos_base.append(base_r.avg_position)
        pos_mirror.append(var_r.avg_position)
        base_nets.append(base_r.net_return)
        var_nets.append(var_r.net_return)
    cap_b = float(np.median(caps_base))
    cap_m = float(np.median(caps_mirror))
    ok = cap_b > 0.0 and cap_m > 0.0
    return PairResult(
        name="trend_direction_mirror", variant_label="returns negated",
        pass_=bool(ok),
        reason=(
            f"方向捕获保持(原始中位 {cap_b:+.5f},镜像中位 {cap_m:+.5f}):"
            f"市场反转后持仓随之反转"
            if ok else
            f"方向捕获不稳定(原始中位 {cap_b:+.5f},镜像中位 {cap_m:+.5f}):"
            f"模型没有根据趋势方向行动"
        ),
        base={"median_capture": cap_b, "captures": caps_base,
              "median_net_return": float(np.median(base_nets))},
        variant={"median_capture": cap_m, "captures": caps_mirror,
                 "median_net_return": float(np.median(var_nets))},
        extra={
            "capture_base_median": cap_b, "capture_mirror_median": cap_m,
            "median_avg_position_base": float(np.median(pos_base)),
            "median_avg_position_mirror": float(np.median(pos_mirror)),
        },
    )


# ------------------------------------------------------------ 11. 成本单调
def test_cost_monotonicity(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    multipliers: tuple[float, ...] = (1.0, 2.0, 4.0),
) -> PairResult:
    """手续费与滑点提高:净值不能系统性提高,换手不应显著提高。"""
    results = []
    for m in multipliers:
        c = EvalConfig(
            fee=cfg.fee * m, slippage_bps=cfg.slippage_bps * m,
            price_tick=cfg.price_tick, initial_cash=cfg.initial_cash,
            reward_scale=cfg.reward_scale, window_size=cfg.window_size,
            deterministic=cfg.deterministic,
        )
        r, _a = _run(policy, episode, c)
        results.append((m, r))
    nets = [r.net_return for _m, r in results]
    turns = [r.turnover_rate for _m, r in results]
    net_nonincreasing = all(
        nets[i] >= nets[i + 1] - 1e-12 for i in range(len(nets) - 1)
    )
    turnover_nondecreasing = all(
        turns[i] <= turns[i + 1] + 0.05 for i in range(len(turns) - 1)
    )
    ok = net_nonincreasing and turnover_nondecreasing
    return PairResult(
        name="cost_monotonicity",
        variant_label=f"fee x{list(multipliers)}",
        pass_=ok,
        reason=(
            "净值随成本单调不增且换手未显著提高"
            if ok else
            f"成本提高后净值上升({nets})或换手显著提高({turns})"
        ),
        base={"multipliers": [m for m, _ in results],
              "net_returns": nets, "turnover": turns},
        extra={"net_nonincreasing": net_nonincreasing,
               "turnover_nondecreasing": turnover_nondecreasing},
    )


# ------------------------------------------------------------ 12. Null
def test_null_control(
    policy: Policy, null_episodes: list[GeneratedEpisode],
    cfg: EvalConfig,
) -> PairResult:
    """无可预测信号且有费用的环境:不应稳定正超额收益、不应持续高换手。"""
    from rl_curriculum.policies import AlwaysFlatPolicy

    flats = []
    nets = []
    turnovers = []
    wins = 0
    for ep in null_episodes:
        r, _a = _run(policy, ep, cfg)
        f = run_episode(AlwaysFlatPolicy(), ep, cfg)
        flats.append(f.net_return)
        nets.append(r.net_return - f.net_return)
        turnovers.append(r.turnover_rate)
        wins += 1 if r.net_return - f.net_return > 0 else 0
    excess_median = float(np.median(nets))
    excess_pos_ratio = wins / max(len(nets), 1)
    median_turnover = float(np.median(turnovers))
    high_turnover = median_turnover > NULL_HIGH_TURNOVER_THRESHOLD
    boot = paired_bootstrap_ci(nets)
    stable_positive = (
        excess_median > 1e-9
        and excess_pos_ratio >= 0.75
        and boot["ci_low"] > 0.0
    )
    ok = not stable_positive
    return PairResult(
        name="null_control", variant_label=f"n={len(null_episodes)}",
        pass_=ok,
        reason=(
            "Null 环境无稳定正超额收益"
            if ok else
            f"Null 环境出现稳定异常正收益(中位超额 {excess_median:.5f},"
            f"正超额比例 {excess_pos_ratio:.2f},bootstrap CI low "
            f"{boot['ci_low']:.5f}):信号切断失败或作弊"
        ),
        base={"excess_median": excess_median,
              "excess_positive_ratio": excess_pos_ratio,
              "excess_bootstrap": boot,
              "median_turnover": median_turnover,
              "flat_net_returns": flats},
        extra={
            "high_turnover": high_turnover,
            "excess_median": excess_median,
            "excess_positive_ratio": excess_pos_ratio,
            "median_turnover": median_turnover,
        },
    )


# -------------------------------------------------------- 作弊分类器
def detect_periodicity(actions: list[int], max_period: int = 32) -> int | None:
    """动作序列周期检测:存在 p 使 actions[i] == actions[i-p] 对所有 i>=p。"""
    n = len(actions)
    for p in range(2, min(max_period, n // 2) + 1):
        if all(actions[i] == actions[i - p] for i in range(p, n)):
            return p
    return None


def classify_cheating(cf_results: list[PairResult]) -> dict[str, Any]:
    """综合反事实证据输出机读作弊原因(空 = 无作弊证据)。

    映射:
    - common_prefix 失败 / 观察字段审计失败 -> future_leak;
    - price_scale / initial_price 失败       -> absolute_price;
    - episode_length / time_shift 失败       -> episode_position;
    - regime_order 失败(market_unresponsive)-> periodic_pattern;
    - null_control:高换手 + 扣费亏损        -> null_overtrading(挂科证据)。
    """
    by_name = {r.name: r for r in cf_results}
    reasons: list[str] = []

    def failed(name: str) -> bool:
        r = by_name.get(name)
        return r is not None and not r.pass_

    if failed("common_prefix_future_suffix"):
        reasons.append("future_leak")
    if failed("price_scale_invariance") or failed("initial_price_invariance"):
        reasons.append("absolute_price")
    if failed("episode_length_invariance") or failed("time_shift_invariance"):
        reasons.append("episode_position")
    regime = by_name.get("regime_order_randomization")
    action_period = (
        regime.extra.get("action_period") if regime is not None else None
    )
    if failed("regime_order_randomization") or action_period is not None:
        reasons.append("periodic_pattern")
    null = by_name.get("null_control")
    null_flags: dict[str, Any] = {
        "high_turnover": None, "excess_median": None,
        "excess_positive_ratio": None,
    }
    if null is not None:
        null_flags = {
            "high_turnover": bool(null.extra.get("high_turnover")),
            "excess_median": null.extra.get("excess_median"),
            "excess_positive_ratio": null.extra.get("excess_positive_ratio"),
        }
    return {
        "suspected_cheating": len(reasons) > 0,
        "cheat_reasons": sorted(set(reasons)),
        "null_control_flags": null_flags,
        "failed_tests": [r.name for r in cf_results if not r.pass_],
    }


# 以下 test_* 是反事实考试实现函数,不是 pytest 测试;
# 标记 __test__ = False 防止 pytest 误收集(测试套件从本模块导入它们)。
for _exam_fn in (
    test_common_prefix_future_suffix,
    test_price_scale_invariance,
    test_initial_price_invariance,
    test_episode_length_invariance,
    test_time_shift_invariance,
    test_regime_order_randomization,
    test_irrelevant_feature_injection,
    test_irrelevant_feature_shuffle,
    test_signal_ablation,
    test_trend_direction_mirror,
    test_cost_monotonicity,
    test_null_control,
):
    _exam_fn.__test__ = False  # type: ignore[attr-defined]
