"""工作包 H/I + 阶段 2.6.0a 工作包 I/J/K2/L + 阶段 2.6.0b 工作包 D/E:
反事实与反作弊考试。

12 项考试(阶段 2.6.0b 修订):
 1. common_prefix_future_suffix  共同前缀/不同未来后缀(多 Episode ×
                                 多切割点;因果性硬测试);
 2. price_scale_invariance       价格尺度不变性(×0.1/×10/×100);
 3. initial_price_invariance     初始价格不变性;
 4. episode_length_invariance    Episode 长度不变性;
 5. time_shift_invariance        Episode 起始时间平移;
 6. regime_order_randomization   Regime 顺序随机化(证据,不自动判作弊);
 7. nuisance_slot_injection      nuisance 槽位注入——双边等价检验
                                 (D:显著改善/显著恶化/依赖均 FAIL);
 8. nuisance_slot_shuffle        nuisance 槽位置乱——双边等价检验;
 9. signal_ablation              真信号消融(按章程 signal groups);
10. trend_mirror                 趋势方向镜像;
11. cost_monotonicity            成本单调性;
12. null_control                 Null Control(严格三族一致;
                                 block shuffle 已降级为诊断,不属硬门)。

阶段 2.6.0b 工作包 D(nuisance 双边等价):
- NuisanceEquivalenceSpec 预注册等价区间(δ/action match/换手/仓位
  容差/变换 seed 数),进入 verdict spec 与 sealed commitment;
- 注入与置乱同时检查行为稳定与收益稳定:paired bootstrap CI 完全位于
  [-δ, +δ] 才算等价;显著改善 -> FAIL;显著恶化 -> FAIL;
  无法证明等价 -> FAIL(证据不足)。

阶段 2.6.0b 工作包 E(真实多 seed 反作弊证据):
- 每种作弊原因独立聚合实际测试 Episode 数/不同 seed 数/失败数/
  动作分歧分布/配对收益差/优势崩溃 bootstrap;
- 不再使用整个考试包 Episode 总数冒充某项反事实的重复次数;
- 缺少变体收益证据时优势崩溃不得默认成立(旧版
  `if not extra_nets: return True` 已删除):required 反作弊考试
  -> EXAM_INVALID,非 required 诊断 -> insufficient_evidence;
- 作弊四门证据:原始有效成绩 + 依赖禁止变量 + 优势稳定崩溃 +
  多 seed 重复;单 seed 失败不判作弊。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.evaluator import (
    EvalConfig,
    EpisodeResult,
    paired_bootstrap_ci,
    run_policy_episode,
)
from rl_curriculum.generator_api import (
    BaseMarketGenerator,
    EpisodeSpec,
    GeneratedEpisode,
)
from rl_curriculum.observation_schema import ObservationSchema

# 动作一致率阈值:合理策略在结构不变变换下应为 1.0
ACTION_MATCH_THRESHOLD = 0.999
# 高换手阈值(Null Control 判定)
NULL_HIGH_TURNOVER_THRESHOLD = 0.5
# 周期检测参数(J1)
PERIODIC_MIN_SWITCHES = 2
PERIODIC_MIN_REPETITIONS = 3


class PairResult:
    """成对反事实考试结果(名称/变体/判定/证据)。"""

    def __init__(
        self, name: str, variant_label: str, pass_: bool, reason: str,
        action_match_rate: float | None = None,
        first_divergence_step: int | None = None,
        base: dict[str, float] | None = None,
        variant: dict[str, float] | None = None,
        extra: dict[str, Any] | None = None,
    ):
        self.name = name
        self.variant_label = variant_label
        self.pass_ = pass_
        self.reason = reason
        self.action_match_rate = action_match_rate
        self.first_divergence_step = first_divergence_step
        self.base = base or {}
        self.variant = variant or {}
        self.extra = extra or {}

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
        timeframe=base.spec.timeframe,
    )
    wrapped = GeneratedEpisode(
        spec=spec, df=df,
        hidden=hidden if hidden is not None else base.hidden,
        family_version=base.family_version, timeframe=base.timeframe,
        is_null=base.is_null, generator_fingerprint=base.generator_fingerprint,
        meta=dict(base.meta),
        declared_feature_columns=base.declared_feature_columns,
    )
    return wrapped


def _run(
    policy: Any, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema,
) -> tuple[EpisodeResult, list[int], list[np.ndarray] | None]:
    return run_policy_episode(
        policy, episode, cfg, schema,
        return_actions=True, return_observations=True,
    )


def _summary(r: EpisodeResult) -> dict[str, float]:
    return {
        "net_return": r.net_return, "turnover_rate": r.turnover_rate,
        "avg_position": r.avg_position, "n_trades": float(r.n_trades),
        "total_fees": r.total_fees,
        "policy_action_switches": float(r.policy_action_switches),
        "policy_order_executions": float(r.policy_order_executions),
        "forced_terminal_executions": float(r.forced_terminal_executions),
        "round_trip_count": float(r.round_trip_count),
    }


def _match(base_actions: list[int], var_actions: list[int], n: int) -> tuple[float, int | None]:
    m = sum(1 for a, b in zip(base_actions[:n], var_actions[:n]) if a == b)
    rate = m / max(n, 1)
    first_div = next(
        (i for i in range(n) if base_actions[i] != var_actions[i]), None
    )
    return float(rate), first_div


def _obs_prefix_match(
    base_obs: list[np.ndarray] | None, var_obs: list[np.ndarray] | None,
    n: int,
) -> tuple[bool, int | None]:
    """共同前缀内逐决策完整 observation 比对(K2:特征+账户槽位)。"""
    if base_obs is None or var_obs is None:
        return True, None
    for i in range(min(n, len(base_obs), len(var_obs))):
        if not np.array_equal(base_obs[i], var_obs[i]):
            return False, i
    return True, None


def _assert_same_observation_shape(
    schema: ObservationSchema, base_obs: list[np.ndarray] | None,
    var_obs: list[np.ndarray] | None, *, test_name: str,
) -> None:
    """I4 shape 守卫:变体与原始的每步 observation shape 必须一致。"""
    if base_obs is None or var_obs is None:
        return
    expected = schema.observation_shape()
    for tag, seq in (("base", base_obs), ("variant", var_obs)):
        for i, o in enumerate(seq):
            if tuple(np.asarray(o).shape) != expected:
                raise ValueError(
                    f"{test_name}: {tag} 第 {i} 步 observation shape "
                    f"{np.asarray(o).shape} != schema {expected}"
                    f"(维度变化是 EXAM_INVALID,不是模型挂科)")


def _rebuild(
    generator: BaseMarketGenerator, base: GeneratedEpisode,
    returns: np.ndarray, hidden: pd.DataFrame | None = None,
) -> pd.DataFrame:
    from rl_curriculum.generators import rebuild_episode_with_returns
    from rl_curriculum.timebase import timeframe_to_seconds

    df = rebuild_episode_with_returns(generator, base, returns, hidden)
    df.insert(0, "date", pd.date_range(
        "2026-01-01T00:00:00Z", periods=len(df),
        freq=f"{timeframe_to_seconds(base.timeframe)}s"))
    if hidden is not None and len(hidden) != len(df):
        raise ValueError(
            f"重建 hidden 行数 {len(hidden)} != df {len(df)}"
        )
    return df


def splice_prefix_suffix(
    base_df: pd.DataFrame, other_df: pd.DataFrame, cut: int,
    *, family: str, family_version: str, params: dict[str, Any], seed: int,
    timeframe: str,
) -> pd.DataFrame:
    """共同前缀拼接:前 cut 行逐位保留 base,后缀按几何收益接 other。

    后缀价格整体缩放 k = base.close[cut-1] / other.close[cut-1]
    (相对收益路径与 other 一致,价格水平与 base 连续);
    特征与 nuisance 槽位按同一因果公式/counter-hash 对最终价格序列重算
    (阶段 2.6.0b:解析与 generate() 相同的 effective params),
    保证前缀 observation(含 nuisance)与 base 逐位一致。
    """
    from rl_curriculum.generators import recompute_probe_features

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
    return recompute_probe_features(
        out, family=family, family_version=family_version,
        params=params, seed=seed, timeframe=timeframe,
    )


def mirror_df(
    df: pd.DataFrame, *, family: str, family_version: str,
    params: dict[str, Any], seed: int, timeframe: str,
) -> pd.DataFrame:
    """趋势方向镜像(log 域取反):close' = p0^2 / close,high/low 互换镜像。"""
    from rl_curriculum.generators import recompute_probe_features

    p0 = float(df["open"].iloc[0])
    out = df.copy()
    for col in ("open", "close"):
        out[col] = p0 * p0 / df[col]
    out["high"] = p0 * p0 / df["low"]
    out["low"] = p0 * p0 / df["high"]
    return recompute_probe_features(
        out, family=family, family_version=family_version,
        params=params, seed=seed, timeframe=timeframe,
    )


# ------------------------------------------------------------ 1. 共同前缀
def test_common_prefix_future_suffix(
    generator: BaseMarketGenerator, policy: Any,
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
    cut_ratio: float = 0.5,
) -> PairResult:
    """Episode A 与 C 在 t 前完全一致,t 后未来路径不同。

    要求:t 及之前每一个 observation 特征槽位与账户状态槽位完全一致
    (K2,不只 OHLC),deterministic policy 在 t 及之前动作完全一致;
    不一致则判定未来泄漏或生成器泄漏。

    工作包 E:多 Episode/多切割点由调用方(formal_exam
    run_counterfactual_suite)循环执行并聚合复制证据。
    """
    n = len(episode.df)
    cut = int(n * cut_ratio)
    other = generator.generate(
        episode.spec.params, episode.spec.seed + 10_000,
        split=episode.spec.split, timeframe=episode.spec.timeframe,
    )
    df_c = splice_prefix_suffix(
        episode.df, other.df, cut,
        family=episode.spec.family, family_version=episode.family_version,
        params=episode.spec.params, seed=episode.spec.seed,
        timeframe=episode.spec.timeframe,
    )
    hidden_c = (
        pd.concat([episode.hidden.iloc[:cut], other.hidden.iloc[cut:]],
                  ignore_index=True)
        if len(episode.hidden.columns) else episode.hidden
    )
    # 硬断言:共同前缀 observation df(全部特征列,含 nuisance)逐位一致
    cols = [c for c in df_c.columns if c != "date"]
    same_prefix = bool(
        df_c[cols].iloc[:cut].equals(episode.df[cols].iloc[:cut])
    )
    if not same_prefix:
        return PairResult(
            name="common_prefix_future_suffix",
            variant_label=f"t_cut={cut}/{n}",
            pass_=False,
            reason="共同前缀构造失败:变换后前缀 observation(特征+nuisance)"
                   "与原始不一致(生成器泄漏或重建不确定性)",
        )
    variant = _wrap(episode, df_c, hidden_c, split="common_prefix_variant")
    base_r, base_a, base_o = _run(policy, episode, cfg, schema)
    var_r, var_a, var_o = _run(policy, variant, cfg, schema)
    _assert_same_observation_shape(
        schema, base_o, var_o, test_name="common_prefix_future_suffix")
    nd = min(len(base_a), len(var_a))
    rate, first_div = _match(base_a, var_a, min(nd, cut))
    obs_ok, obs_div = _obs_prefix_match(base_o, var_o, min(nd, cut))
    ok = rate >= ACTION_MATCH_THRESHOLD and obs_ok
    return PairResult(
        name="common_prefix_future_suffix", variant_label=f"t_cut={cut}/{n}",
        pass_=ok,
        reason=(
            "共同前缀内动作与全部 observation 槽位(特征+账户)完全一致(因果)"
            if ok else
            (f"共同前缀内动作分歧(一致率 {rate:.3f},首个分歧 step="
             f"{first_div}):未来后缀影响了过去决策 -> 未来泄漏"
             if not obs_ok or first_div is not None else
             f"共同前缀内 observation 槽位不一致(首个不一致 step="
             f"{obs_div}):生成器/特征重建泄漏")
        ),
        action_match_rate=rate, first_divergence_step=first_div,
        base=_summary(base_r), variant=_summary(var_r),
        extra={"prefix_obs_all_slots_match": obs_ok,
               "prefix_obs_mismatch_step": obs_div,
               "cut_ratio": cut_ratio,
               "episode_seed": episode.spec.seed},
    )


# ------------------------------------------------- 2/3. 价格尺度与初始价格
def _scaled_df(df: pd.DataFrame, k: float) -> pd.DataFrame:
    out = df.copy()
    for col in ("open", "high", "low", "close"):
        out[col] = out[col] * k
    return out


def test_price_scale_invariance(
    policy: Any, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema,
    scales: tuple[float, ...] = (0.1, 10.0, 100.0),
) -> PairResult:
    """所有价格乘 k,收益与相对关系不变 -> 动作应保持一致。"""
    base_r, base_a, base_o = _run(policy, episode, cfg, schema)
    worst_rate, worst_k, worst_div = 1.0, None, None
    variant_nets: list[float] = []
    for k in scales:
        scaled = _wrap(episode, _scaled_df(episode.df, k), None,
                       split="price_scale_variant")
        var_r, var_a, var_o = _run(policy, scaled, cfg, schema)
        _assert_same_observation_shape(
            schema, base_o, var_o, test_name="price_scale_invariance")
        variant_nets.append(var_r.net_return)
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
        variant={"worst_variant_net_return": (
            float(min(variant_nets)) if variant_nets else None)},
        extra={"worst_scale": worst_k,
               "variant_net_returns": variant_nets,
               "episode_seed": episode.spec.seed},
    )


def test_initial_price_invariance(
    generator: BaseMarketGenerator, policy: Any,
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
    new_initial_prices: tuple[float, ...] = (50.0, 500.0),
) -> PairResult:
    """只修改 Episode 初始价格,不修改相对收益路径 -> 行为应保持一致。"""
    base_r, base_a, base_o = _run(policy, episode, cfg, schema)
    p0 = float(episode.df["open"].iloc[0])
    worst_rate, worst_p0, worst_div = 1.0, None, None
    variant_nets: list[float] = []
    for target in new_initial_prices:
        variant = _wrap(
            episode, _scaled_df(episode.df, target / p0), None,
            split="initial_price_variant",
        )
        var_r, var_a, var_o = _run(policy, variant, cfg, schema)
        _assert_same_observation_shape(
            schema, base_o, var_o, test_name="initial_price_invariance")
        variant_nets.append(var_r.net_return)
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
        base=_summary(base_r),
        variant={"worst_variant_net_return": (
            float(min(variant_nets)) if variant_nets else None)},
        extra={"worst_initial_price": worst_p0,
               "variant_net_returns": variant_nets,
               "episode_seed": episode.spec.seed},
    )


# ------------------------------------------------------ 4. Episode 长度
def test_episode_length_invariance(
    generator: BaseMarketGenerator, policy: Any,
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
    short_ratio: float = 0.6,
) -> PairResult:
    """共享完全相同前缀的短/长 Episode:共同前缀中的动作必须一致。"""
    n = len(episode.df)
    n_short = int(n * short_ratio)
    long_params = dict(episode.spec.params)
    long_params["episode_bars"] = n + 48
    extra = generator.generate(
        long_params, episode.spec.seed + 20_000,
        split=episode.spec.split, timeframe=episode.spec.timeframe,
    )
    # 短 Episode:直接截断(前缀特征逐位保留);
    # 长 Episode:前 n 行逐位保留 base,后缀按几何收益接 extra。
    df_short = episode.df.iloc[:n_short].reset_index(drop=True)
    df_long = splice_prefix_suffix(
        episode.df, extra.df, n,
        family=episode.spec.family, family_version=episode.family_version,
        params=episode.spec.params, seed=episode.spec.seed,
        timeframe=episode.spec.timeframe,
    )
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
    r_short, a_short, o_short = _run(policy, short_ep, cfg, schema)
    r_long, a_long, o_long = _run(policy, long_ep, cfg, schema)
    _assert_same_observation_shape(
        schema, o_short, o_long, test_name="episode_length_invariance")
    # 比较窗口:两者共同的前 n_short - 1 个决策(exec bar 须存在)
    cmp_n = n_short - 1
    rate, first_div = _match(a_short, a_long, cmp_n)
    obs_ok, obs_div = _obs_prefix_match(o_short, o_long, cmp_n)
    ok = rate >= ACTION_MATCH_THRESHOLD and obs_ok
    return PairResult(
        name="episode_length_invariance",
        variant_label=f"short={n_short},long={len(df_long)}",
        pass_=ok,
        reason=(
            "共同前缀动作与 observation 槽位一致(无固定终点倒计时依赖)"
            if ok else
            f"Episode 长度变化改变共同前缀动作(一致率 {rate:.3f},"
            f"首个分歧 step={first_div}) -> 依赖 Episode 位置/倒计时"
        ),
        action_match_rate=rate, first_divergence_step=first_div,
        base=_summary(r_short), variant=_summary(r_long),
        extra={"prefix_obs_all_slots_match": obs_ok,
               "prefix_obs_mismatch_step": obs_div,
               "variant_net_return": r_long.net_return,
               "variant_net_returns": [r_short.net_return, r_long.net_return],
               "episode_seed": episode.spec.seed},
    )


# ---------------------------------------------------------- 5. 时间平移
def test_time_shift_invariance(
    policy: Any, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema,
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
    base_r, base_a, base_o = _run(policy, episode, cfg, schema)
    var_r, var_a, var_o = _run(
        policy, _wrap(episode, df_shift, None, "time_shift"), cfg, schema)
    _assert_same_observation_shape(
        schema, base_o, var_o, test_name="time_shift_invariance")
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
        extra={"variant_net_return": var_r.net_return,
               "episode_seed": episode.spec.seed},
    )


# ------------------------------------------------- 6. Regime 顺序随机化
def test_regime_order_randomization(
    generator: BaseMarketGenerator, policy: Any,
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
) -> PairResult:
    """相同类型的 regime 不同顺序出现(只产生证据,不自动判作弊)。

    市场内容重排后动作序列完全不变 = 策略不读市场观察(位置/周期型)
    ——这只是一条证据;是否构成 SUSPECTED_CHEATING 由 classify_cheating
    的四门证据(原始有效成绩/依赖禁止变量/优势崩溃/多 seed 重复)
    决定。模型不响应 regime 而成绩差是普通挂科。
    """
    if "regimes" not in episode.meta:
        return PairResult(
            name="regime_order_randomization", variant_label="n/a",
            pass_=True, reason="生成器族无分段 regime(不适用)",
        )
    regimes = [list(r) for r in episode.meta["regimes"]]
    if len(regimes) < 2:
        return PairResult(
            name="regime_order_randomization", variant_label="single-regime",
            pass_=True, reason="Episode 仅一个 regime,顺序随机化不适用",
        )
    base_r, base_a, _o = _run(policy, episode, cfg, schema)
    worst_same, tested = 1.0, 0
    var_returns_all = []
    for shift in (1, 2):  # 两种确定性重排(保持段集合不变)
        shuffled = regimes[shift:] + regimes[:shift]
        params = dict(episode.spec.params)
        params["regimes"] = shuffled
        var_ep = generator.generate(
            params, episode.spec.seed, split=episode.spec.split,
            timeframe=episode.spec.timeframe,
        )
        var_r, var_a, _vo = _run(policy, var_ep, cfg, schema)
        var_returns_all.append(_summary(var_r))
        tested += 1
        if len(var_a) == len(base_a) and var_a == base_a:
            worst_same = min(worst_same, 1.0)
        else:
            worst_same = 0.0
    unresponsive = tested > 0 and worst_same == 1.0
    above_min = base_r.net_return > 0.0
    ok = not unresponsive
    return PairResult(
        name="regime_order_randomization",
        variant_label=f"rotations={tested}",
        pass_=ok,
        reason=(
            "策略响应市场内容(重排后动作变化):根据市场观察行动"
            if ok else
            "regime 顺序重排后动作序列完全不变:策略不读市场观察,"
            "依赖固定位置/固定周期(仅是证据;是否作弊由 classify_cheating "
            "结合原始有效成绩与优势崩溃判定)"
        ),
        action_match_rate=(1.0 if unresponsive else 0.0),
        base=_summary(base_r), variant=var_returns_all[0] if var_returns_all else {},
        extra={"market_unresponsive": unresponsive,
               "base_net_return_positive": above_min,
               "action_period": detect_periodicity(base_a),
               "variant_net_returns": [v.get("net_return") for v in var_returns_all],
               "episode_seed": episode.spec.seed},
    )


# --------------------------------------------- 7/8/9. nuisance/消融(I1-I3)
@dataclass(frozen=True)
class NuisanceEquivalenceSpec:
    """阶段 2.6.0b 工作包 D:预注册的 nuisance 双边等价判定规则。

    进入 CourseVerdictSpec(canonical payload)与 sealed commitment;
    考试后不得调整。
    """

    delta_return: float = 0.002        # 收益等价半区间(配对差 CI 全含于 [-δ,+δ])
    action_match_min: float = 0.98     # 逐 Episode 动作一致率下限
    turnover_abs_tol: float = 0.02     # 中位换手差绝对容差
    position_abs_tol: float = 0.02     # 中位仓位差绝对容差
    n_transform_seeds: int = 3         # 独立 nuisance 变换 seed 数
    bootstrap_iters: int = 2000
    bootstrap_alpha: float = 0.05

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "delta_return": float(self.delta_return),
            "action_match_min": float(self.action_match_min),
            "turnover_abs_tol": float(self.turnover_abs_tol),
            "position_abs_tol": float(self.position_abs_tol),
            "n_transform_seeds": int(self.n_transform_seeds),
            "bootstrap_iters": int(self.bootstrap_iters),
            "bootstrap_alpha": float(self.bootstrap_alpha),
        }

    def spec_hash(self) -> str:
        import hashlib
        import json

        return "ne-" + hashlib.sha256(
            json.dumps(self.canonical_payload(), sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()


def _nuisance_variant_df(
    episode: GeneratedEpisode, schema: ObservationSchema,
    *, transform, seed: int,
) -> pd.DataFrame:
    """构造只修改预注册 nuisance 槽位内容的变体 df(I1/I2)。"""
    nuisance = list(schema.nuisance_feature_names)
    rng = np.random.default_rng(seed)
    out = episode.df.copy()
    for name in nuisance:
        arr = out[name].to_numpy(dtype=np.float64).copy()
        out[name] = transform(arr, rng)
    return out


def evaluate_nuisance_equivalence(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, spec: NuisanceEquivalenceSpec,
    *, mode: str, seed_base: int = 555,
) -> PairResult:
    """工作包 D:nuisance 双边等价检验(mode=injection/shuffle)。

    同时检查(D1):
    1. 行为稳定(逐 Episode 动作一致率 >= action_match_min);
    2. 收益稳定(paired bootstrap CI 完全位于 [-δ, +δ]);
    3. 换手稳定(|中位差| <= turnover_abs_tol);
    4. 仓位稳定(|中位差| <= position_abs_tol);
    5. 不出现系统性改善(CI high > δ -> FAIL);
       不出现系统性恶化(CI low < -δ -> FAIL)。
    证据不足以证明等价(CI 过宽但未出界)-> FAIL(insufficient)。
    """
    nuisance = list(schema.nuisance_feature_names)
    name = (f"nuisance_slot_{mode}")
    if not nuisance:
        return PairResult(
            name=name, variant_label="n/a", pass_=True,
            reason="schema 未预注册 nuisance 槽位(考试不适用)",
            extra={"nuisance_slots": []},
        )
    if mode not in ("injection", "shuffle"):
        raise ValueError(f"未知 nuisance 模式 {mode!r}")
    if spec.n_transform_seeds < 2:
        raise ValueError("n_transform_seeds 必须 >= 2(双边等价需要多变换 seed)")

    base_cache: dict[int, tuple[EpisodeResult, list[int]]] = {}
    match_rates: list[float] = []
    first_divs: list[int | None] = []
    diffs_net, diffs_turn, diffs_pos = [], [], []
    base_nets, var_nets = [], []
    base_results_by_ep: dict[int, EpisodeResult] = {}
    var_results: list[EpisodeResult] = []

    for i, ep in enumerate(episodes):
        base_r, base_a, _o = _run(policy, ep, cfg, schema)
        base_cache[i] = (base_r, base_a)
        base_results_by_ep[i] = base_r
        base_nets.append(base_r.net_return)
        for t in range(spec.n_transform_seeds):
            tseed = seed_base + 1000 * t + i
            if mode == "injection":
                transform = (lambda arr, rng:
                             rng.standard_normal(len(arr)))
            else:
                transform = (lambda arr, rng: rng.permutation(arr))
            df_v = _nuisance_variant_df(ep, schema, transform=transform,
                                        seed=tseed)
            variant = _wrap(ep, df_v, None, f"nuisance_{mode}")
            var_r, var_a, var_o = _run(policy, variant, cfg, schema)
            _assert_same_observation_shape(
                schema, _o, var_o, test_name=name)
            rate, first_div = _match(base_a, var_a, len(base_a))
            match_rates.append(rate)
            if first_div is not None:
                first_divs.append(first_div)
            diffs_net.append(var_r.net_return - base_r.net_return)
            diffs_turn.append(var_r.turnover_rate - base_r.turnover_rate)
            diffs_pos.append(var_r.avg_position - base_r.avg_position)
            var_nets.append(var_r.net_return)
            var_results.append(var_r)

    action_match = float(np.mean(match_rates)) if match_rates else 0.0
    boot = paired_bootstrap_ci(
        diffs_net, n_boot=spec.bootstrap_iters,
        alpha=spec.bootstrap_alpha)
    med_turn_diff = float(np.median(diffs_turn))
    med_pos_diff = float(np.median(diffs_pos))
    n_pairs = len(diffs_net)

    reasons: list[str] = []
    behavior_ok = action_match >= spec.action_match_min
    ci_low, ci_high = float(boot["ci_low"]), float(boot["ci_high"])
    within = (ci_low >= -spec.delta_return and ci_high <= spec.delta_return)
    turnover_ok = abs(med_turn_diff) <= spec.turnover_abs_tol
    position_ok = abs(med_pos_diff) <= spec.position_abs_tol
    if not behavior_ok:
        reasons.append(
            f"行为不稳定:动作一致率 {action_match:.3f} < "
            f"{spec.action_match_min}(模型依赖 nuisance 槽位)")
    if ci_high > spec.delta_return:
        reasons.append(
            f"系统性改善:配对收益差 CI high {ci_high:+.5f} > "
            f"+δ={spec.delta_return}(模型从 nuisance 中'获利')")
    if ci_low < -spec.delta_return:
        reasons.append(
            f"系统性恶化:配对收益差 CI low {ci_low:+.5f} < "
            f"-δ=-{spec.delta_return}(模型因 nuisance 变化大幅崩溃)")
    if behavior_ok and ci_low >= -spec.delta_return and \
            ci_high <= spec.delta_return and n_pairs > 0 and \
            not within:
        reasons.append("内部一致性问题")
    if behavior_ok and not (ci_high > spec.delta_return
                            or ci_low < -spec.delta_return) and \
            not within:
        reasons.append(
            f"证据不足:CI [{ci_low:+.5f}, {ci_high:+.5f}] 未完全落入"
            f" [-δ,+δ],无法证明等价(insufficient evidence)")
    if not turnover_ok:
        reasons.append(
            f"换手不稳定:中位差 {med_turn_diff:+.5f} 超容差 "
            f"{spec.turnover_abs_tol}")
    if not position_ok:
        reasons.append(
            f"仓位不稳定:中位差 {med_pos_diff:+.5f} 超容差 "
            f"{spec.position_abs_tol}")
    ok = (behavior_ok and within and turnover_ok and position_ok
          and n_pairs > 0)
    return PairResult(
        name=name,
        variant_label=(f"slots={nuisance},eps={len(episodes)},"
                       f"tseeds={spec.n_transform_seeds}"),
        pass_=bool(ok),
        reason=(
            f"nuisance {mode} 双边等价成立:动作一致率 {action_match:.3f},"
            f"收益差 CI [{ci_low:+.5f},{ci_high:+.5f}] ⊂ "
            f"[-{spec.delta_return},+{spec.delta_return}],"
            f"换手差 {med_turn_diff:+.5f},仓位差 {med_pos_diff:+.5f}"
            if ok else "; ".join(reasons)
        ),
        action_match_rate=action_match,
        first_divergence_step=(min(first_divs) if first_divs else None),
        base={"median_net_return": float(np.median(base_nets)),
              "net_returns": base_nets},
        variant={"median_net_return": float(np.median(var_nets)),
                 "net_returns": var_nets},
        extra={
            "nuisance_slots": nuisance,
            "mode": mode,
            "observation_shape": list(schema.observation_shape()),
            "market_features_untouched": [
                f for f in schema.feature_names if f not in nuisance],
            "equivalence_spec": spec.canonical_payload(),
            "paired_bootstrap": boot,
            "n_pairs": n_pairs,
            "n_transform_seeds": spec.n_transform_seeds,
            "episodes_tested": len(episodes),
            "distinct_episode_seeds": len({e.spec.seed for e in episodes}),
            "action_match_rates": match_rates,
            "median_turnover_diff": med_turn_diff,
            "median_position_diff": med_pos_diff,
            "failure_modes": (
                [] if ok else
                ([m for m in (
                    ("improvement" if ci_high > spec.delta_return else None),
                    ("degradation" if ci_low < -spec.delta_return else None),
                    ("dependency" if not behavior_ok else None),
                    ("turnover" if not turnover_ok else None),
                    ("position" if not position_ok else None),
                    ("insufficient"
                     if (behavior_ok and ci_low >= -spec.delta_return
                         and ci_high <= spec.delta_return and n_pairs > 0
                         and not within) else None),
                ) if m])),
            "is_cheat_evidence": False,
        },
    )


def test_nuisance_slot_injection(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, *,
    spec: NuisanceEquivalenceSpec | None = None,
    seed: int = 555,
) -> PairResult:
    """I1 无关特征注入:只替换 nuisance 槽位内容,双边等价检验(D)。"""
    return evaluate_nuisance_equivalence(
        policy, episodes, cfg, schema,
        spec or NuisanceEquivalenceSpec(), mode="injection",
        seed_base=seed)


def test_nuisance_slot_shuffle(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, *,
    spec: NuisanceEquivalenceSpec | None = None,
    seed: int = 777,
) -> PairResult:
    """I2 无关特征置乱:只时间置乱预注册 nuisance 槽位,双边等价检验。"""
    return evaluate_nuisance_equivalence(
        policy, episodes, cfg, schema,
        spec or NuisanceEquivalenceSpec(), mode="shuffle",
        seed_base=seed)


def test_signal_ablation(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, *,
    signal_group: str = "trend",
    mode: str = "fixed_value",
    replacement: float = 0.0,
    seed: int = 888,
) -> PairResult:
    """I3 真信号消融:按章程预注册 signal groups 消融,shape 不变。

    - fixed_value:组内特征替换为固定值;
    - time_shuffle:组内特征时间置乱。
    判定:消融后模型优势应按预注册方向(中位数)下降。若不下降,
    结论是 FAIL(模型没有学到课程声称的能力/特征依赖不成立),
    不是 SUSPECTED_CHEATING。
    """
    groups = schema.signal_groups()
    if signal_group not in groups or not groups[signal_group]:
        return PairResult(
            name="signal_ablation", variant_label=f"group={signal_group}",
            pass_=False,
            reason=f"signal group {signal_group!r} 未在 schema 预注册"
                   f"(可用: {sorted(groups)})——考试无效",
        )
    features = list(groups[signal_group])
    rng = np.random.default_rng(seed)
    base_nets, var_nets = [], []
    for ep in episodes:
        df_a = ep.df.copy()
        for col in features:
            if mode == "fixed_value":
                df_a[col] = float(replacement)
            elif mode == "time_shuffle":
                df_a[col] = rng.permutation(df_a[col].to_numpy())
            else:
                raise ValueError(f"未知消融模式 {mode!r}(fixed_value/time_shuffle)")
        base_r, _a, _o = _run(policy, ep, cfg, schema)
        var_r, _v, _vo = _run(
            policy, _wrap(ep, df_a, None, "signal_ablated"), cfg, schema)
        base_nets.append(base_r.net_return)
        var_nets.append(var_r.net_return)
    drop_median = float(np.median(base_nets) - np.median(var_nets))
    ok = drop_median > 0.0  # 中位优势下降(预注册方向)
    return PairResult(
        name="signal_ablation",
        variant_label=f"group={signal_group},mode={mode}",
        pass_=bool(ok),
        reason=(
            f"消融 {signal_group} 组后中位优势下降"
            f"({np.median(base_nets):+.5f} -> {np.median(var_nets):+.5f})"
            if ok else
            f"消融 {signal_group} 组后中位优势未下降"
            f"({np.median(base_nets):+.5f} -> {np.median(var_nets):+.5f}):"
            f"模型未依赖课程声称的特征 -> FAIL(非作弊)"
        ),
        base={"median_net_return": float(np.median(base_nets)),
              "net_returns": base_nets},
        variant={"median_net_return": float(np.median(var_nets)),
                 "net_returns": var_nets},
        extra={"signal_group": signal_group, "features": features,
               "mode": mode, "median_advantage_drop": drop_median,
               "is_cheat_evidence": False},
    )


# ------------------------------------------------------------ 10. 趋势镜像
def test_trend_direction_mirror(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema,
) -> PairResult:
    """收益取反(正向机会 -> 负向):Long/Flat 模型应保持方向性响应。

    多 Episode 聚合判定(方向捕获):capture = sum(action[t] *
    log_return[t+1]) 在原始与镜像市场中位数为正。
    """
    caps_base, caps_mirror = [], []
    pos_base, pos_mirror = [], []
    base_nets, var_nets = [], []
    for ep in episodes:
        base_r, base_a, _o = _run(policy, ep, cfg, schema)
        mirrored = _wrap(
            ep,
            mirror_df(
                ep.df, family=ep.spec.family,
                family_version=ep.family_version,
                params=ep.spec.params, seed=ep.spec.seed,
                timeframe=ep.spec.timeframe,
            ),
            None, "trend_mirrored",
        )
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
        var_r, var_a, _vo = _run(policy, mirrored, cfg, schema)
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
    policy: Any, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema,
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
        r, _a, _o = _run(policy, episode, c, schema)
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
    policy: Any, null_episodes_by_family: dict[str, list[GeneratedEpisode]],
    cfg: EvalConfig, schema: ObservationSchema,
) -> PairResult:
    """L 多族 Null Control:无可预测信号且有费用的环境。

    正式结论要求在多个结构不同的严格 Null 家族中一致:
    - 无稳定正超额收益(中位数/正超额比例/bootstrap CI);
    - 记录高换手(NullOvertrader 的行为形态 -> 普通挂科证据,非作弊)。
    每族单独判定,任一族出现稳定正超额即 fail。
    """
    flats = []
    per_family: dict[str, dict[str, Any]] = {}
    all_nets: list[float] = []
    all_turnovers: list[float] = []
    for family, eps in sorted(null_episodes_by_family.items()):
        nets = []
        turnovers = []
        wins = 0
        for ep in eps:
            r, _a, _o = _run(policy, ep, cfg, schema)
            from rl_curriculum.policies import AlwaysFlatPolicy

            f = run_policy_episode(AlwaysFlatPolicy(), ep, cfg, schema)
            flats.append(f.net_return)
            nets.append(r.net_return - f.net_return)
            turnovers.append(r.turnover_rate)
            wins += 1 if r.net_return - f.net_return > 0 else 0
        excess_median = float(np.median(nets))
        excess_pos_ratio = wins / max(len(nets), 1)
        boot = paired_bootstrap_ci(nets)
        stable_positive = (
            excess_median > 1e-9
            and excess_pos_ratio >= 0.75
            and boot["ci_low"] > 0.0
        )
        per_family[family] = {
            "n_episodes": len(eps),
            "distinct_seeds": len({e.spec.seed for e in eps}),
            "excess_median": excess_median,
            "excess_positive_ratio": excess_pos_ratio,
            "excess_bootstrap": boot,
            "median_turnover": float(np.median(turnovers)),
            "stable_positive_excess": bool(stable_positive),
        }
        all_nets.extend(nets)
        all_turnovers.extend(turnovers)
    ok = all(not v["stable_positive_excess"] for v in per_family.values())
    n_families = len(per_family)
    return PairResult(
        name="null_control",
        variant_label=f"families={n_families}",
        pass_=bool(ok),
        reason=(
            f"{n_families} 个 Null 家族一致:无稳定正超额收益"
            if ok else
            "至少一个 Null 家族出现稳定异常正收益:信号切断失败或作弊"
        ),
        base={"excess_median": float(np.median(all_nets)) if all_nets else None,
              "flat_net_returns": flats},
        extra={"per_family": per_family,
               "n_families": n_families,
               "median_turnover": (
                   float(np.median(all_turnovers)) if all_turnovers else None),
               "high_turnover": bool(all_turnovers) and float(
                   np.median(all_turnovers)) > NULL_HIGH_TURNOVER_THRESHOLD},
    )


# -------------------------------------------------------- 作弊分类器(J/E)
def detect_periodicity(
    actions: list[int], *, max_period: int = 32,
    min_switches: int = PERIODIC_MIN_SWITCHES,
    min_repetitions: int = PERIODIC_MIN_REPETITIONS,
) -> int | None:
    """动作序列周期检测(J1)。

    常数动作序列不是周期作弊(无实际仓位切换);要求:
    - 存在实际仓位切换(switches >= min_switches);
    - 周期 p 使 actions[i] == actions[i-p] 对所有 i >= p 成立;
    - 完整周期重复 >= min_repetitions 次(n // p >= min_repetitions)。
    """
    n = len(actions)
    switches = sum(
        1 for i in range(1, n) if actions[i] != actions[i - 1])
    if switches < min_switches:
        return None  # 常数/近常数序列:普通挂科,不是周期作弊
    for p in range(2, min(max_period, n // 2) + 1):
        if n // p < min_repetitions:
            break
        if all(actions[i] == actions[i - p] for i in range(p, n)):
            return p
    return None


#: 每种作弊原因对应的反事实考试(工作包 E:逐原因独立聚合证据)
CHEAT_REASON_EXAMS: dict[str, tuple[str, ...]] = {
    "future_leakage": ("common_prefix_future_suffix",),
    "absolute_price": ("price_scale_invariance",
                       "initial_price_invariance"),
    "episode_position": ("episode_length_invariance",
                         "time_shift_invariance"),
    "periodic_pattern": ("regime_order_randomization",),
}


def build_replication_evidence(
    records: list[dict[str, Any]],
    *,
    base_net_by_episode: dict[int, float],
    min_effective_net_return: float,
    min_distinct_seeds: int,
    min_failing_episodes: int,
    bootstrap_iters: int = 2000,
    seed_aggregation: str = "per-seed-worst-variant-v1",
) -> dict[str, Any]:
    """工作包 E + 阶段 2.6.0c 工作包 C3:按 seed 聚合复制证据。

    输入 records 为该原因下每 Episode(或多切割点/多变换 variant)的
    PairResult.to_record();base_net_by_episode 为 {episode_seed: 原始
    收益}。

    聚合规则(per-seed-worst-variant-v1,预注册于 CourseVerdictSpec):
    - 同一 seed 的多个 cut/variant 不是独立样本:先在 seed 内聚合;
    - 变体净收益取该 seed 全部变体的最小值(最坏变体)——优势崩溃
      的问题是"是否存在变体使优势消失",均值会被同原因下不敏感
      变体(如初始价平移后仍做多)稀释,取最坏情况是 fail-safe 方向;
    - 配对差 = 最坏变体收益 - 该 seed 原始收益(审计量);
    - 动作分歧率取 seed 内均值(行为度量,非崩溃判定);
    - failing seed = 该 seed 内任一记录失败(依赖暴露按 seed 计);
    - bootstrap(优势崩溃/配对差)的独立抽样单位是 seed——
      3 个 cut 不产生 3 个独立样本,只贡献 1 个 seed 级样本。

    记录:实际记录数/不同 seed 数/失败 seed 数/失败比例/每 seed 聚合
    明细(可审计)/动作分歧/配对收益差/优势崩溃 bootstrap/首个分歧
    位置聚合/是否达到预注册复制门槛。
    """
    if seed_aggregation != "per-seed-worst-variant-v1":
        raise ValueError(
            f"未注册的 seed 聚合规则 {seed_aggregation!r}"
            f"(只支持 per-seed-worst-variant-v1;规则必须考试前冻结)")
    by_seed: dict[int, dict[str, Any]] = {}
    n_records = 0
    for rec in records:
        seed = rec.get("extra", {}).get("episode_seed")
        if seed is None:
            continue
        n_records += 1
        s = int(seed)
        slot = by_seed.setdefault(s, {
            "variant_nets": [], "action_divergences": [],
            "first_divs": [], "any_fail": False, "n_records": 0,
        })
        slot["n_records"] += 1
        if not rec.get("pass"):
            slot["any_fail"] = True
        if rec.get("action_match_rate") is not None:
            slot["action_divergences"].append(
                1.0 - float(rec["action_match_rate"]))
        if rec.get("first_divergence_step") is not None:
            slot["first_divs"].append(int(rec["first_divergence_step"]))
        vn = rec.get("variant", {}).get("net_return")
        if isinstance(vn, (int, float)):
            slot["variant_nets"].append(float(vn))
        for v in (rec.get("extra", {}).get("variant_net_returns") or []):
            if isinstance(v, (int, float)):
                slot["variant_nets"].append(float(v))
    if not by_seed:
        return {
            "tested_episodes": 0, "distinct_seeds": 0,
            "failing_episodes": 0, "failure_ratio": 0.0,
            "failing_seed_list": [], "seed_aggregation": seed_aggregation,
            "n_records": 0, "per_seed": {},
            "action_divergence_rates": [],
            "first_divergence_positions": [],
            "paired_return_diffs": [],
            "paired_return_bootstrap": {
                "n": 0, "stat": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan")},
            "variant_net_returns": [],
            "collapse_bootstrap": {
                "n": 0, "stat": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan")},
            "collapse_evidence_available": False,
            "advantage_collapse": False,
            "replication_met": False,
        }

    def _mean(xs: list[float]) -> float | None:
        return (sum(xs) / len(xs)) if xs else None

    tested_seeds = sorted(by_seed)
    per_seed: dict[int, dict[str, Any]] = {}
    variant_nets: list[float] = []       # seed 级聚合值(bootstrap 单位=seed)
    paired_diffs: list[float] = []
    action_divergences: list[float] = []
    first_divs_all: set[int] = set()
    failing_seeds: set[int] = set()
    for s in tested_seeds:
        slot = by_seed[s]
        # 最坏变体:seed 内全部变体净收益的最小值(均值会被不敏感
        # 变体稀释;崩溃问题是"存在变体使优势消失",取最坏情况)
        v_worst = min(slot["variant_nets"]) if slot["variant_nets"] else None
        d_mean = _mean(slot["action_divergences"])
        base = base_net_by_episode.get(s)
        paired = ((v_worst - float(base))
                  if (v_worst is not None and base is not None) else None)
        per_seed[s] = {
            "n_records": slot["n_records"],
            "any_fail": slot["any_fail"],
            "variant_net_worst": v_worst,
            "variant_net_mean": _mean(slot["variant_nets"]),
            "paired_diff_worst": paired,
            "action_divergence_mean": d_mean,
            "first_divergence_positions": sorted(set(slot["first_divs"])),
        }
        if slot["any_fail"]:
            failing_seeds.add(s)
        if v_worst is not None:
            variant_nets.append(v_worst)
        if paired is not None:
            paired_diffs.append(paired)
        if d_mean is not None:
            action_divergences.append(d_mean)
        first_divs_all.update(slot["first_divs"])
    n_distinct = len(tested_seeds)
    n_failing = len(failing_seeds)
    # 优势崩溃:seed 级变体收益的 bootstrap 上界低于最低有效线(稳定崩溃)
    if variant_nets:
        collapse_boot = paired_bootstrap_ci(
            variant_nets, n_boot=bootstrap_iters)
        collapsed = bool(
            collapse_boot["ci_high"] < min_effective_net_return)
        collapse_available = True
    else:
        collapse_boot = {"n": 0, "stat": float("nan"),
                         "ci_low": float("nan"), "ci_high": float("nan")}
        collapsed = False
        collapse_available = False
    paired_boot = (paired_bootstrap_ci(paired_diffs,
                                       n_boot=bootstrap_iters)
                   if paired_diffs else
                   {"n": 0, "stat": float("nan"), "ci_low": float("nan"),
                    "ci_high": float("nan")})
    return {
        "tested_episodes": n_distinct,
        "distinct_seeds": n_distinct,
        "failing_episodes": n_failing,
        "failure_ratio": (n_failing / n_distinct) if n_distinct else 0.0,
        "failing_seed_list": sorted(failing_seeds),
        "seed_aggregation": seed_aggregation,
        "n_records": n_records,
        "per_seed": per_seed,
        "action_divergence_rates": action_divergences,
        "first_divergence_positions": sorted(first_divs_all),
        "paired_return_diffs": paired_diffs,
        "paired_return_bootstrap": paired_boot,
        "variant_net_returns": variant_nets,
        "collapse_bootstrap": collapse_boot,
        "collapse_evidence_available": collapse_available,
        "advantage_collapse": collapsed,
        "replication_met": bool(
            n_distinct >= min_distinct_seeds
            and n_failing >= min_failing_episodes),
    }


def classify_cheating(
    cf_results: list[PairResult],
    *,
    base_median_net_return: float,
    base_seed_pass_ratio: float,
    replication_evidence: dict[str, dict[str, Any]] | None = None,
    min_effective_net_return: float,
    min_seed_pass_ratio: float = 0.5,
    min_distinct_seeds: int = 3,
    min_failing_episodes: int = 3,
) -> dict[str, Any]:
    """综合反作弊证据输出机读作弊原因(工作包 J + 阶段 2.6.0b E)。

    SUSPECTED_CHEATING 每个原因必须同时满足四门证据:
    1. 原始考试达到预注册最低有效成绩(中位 >= min_effective 且
       seed_pass_ratio >= min_seed_pass_ratio);
    2. 行为依赖一个课程禁止变量(对应反事实考试失败);
    3. 优势崩溃有真实变体收益证据支撑(collapse_evidence_available,
       且 bootstrap 上界 < 最低有效线)——缺少证据时崩溃不得默认成立;
    4. 多 seed 真实重复(distinct_seeds >= min_distinct_seeds 且
       failing_episodes >= min_failing_episodes,按该原因实际测试的
       Episode 计算,不用考试包总数冒充)。

    未达最低有效成绩的模型(全程空仓/常数动作/未学习)只判 FAIL;
    单 seed 失败不判作弊;缺少崩溃证据的原因记入
    missing_collapse_evidence(required 反作弊考试 -> 调用方 EXAM_INVALID)。
    """
    replication_evidence = replication_evidence or {}
    # 工作包 E:同名考试存在多条记录(多 Episode/多切割点);
    # 依赖检测 = 任意一条记录失败(不得被最后一条通过记录覆盖)
    records_by_name: dict[str, list[PairResult]] = {}
    for r in cf_results:
        records_by_name.setdefault(r.name, []).append(r)
    effective = bool(
        base_median_net_return >= min_effective_net_return
        and base_seed_pass_ratio >= min_seed_pass_ratio
    )

    def failed(name: str) -> bool:
        return any(not r.pass_ for r in records_by_name.get(name, []))

    reasons: dict[str, dict[str, Any]] = {}
    missing_collapse: list[str] = []
    insufficient: list[str] = []
    for reason, exam_names in CHEAT_REASON_EXAMS.items():
        dependency = any(failed(n) for n in exam_names
                         if n in records_by_name)
        if not any(n in records_by_name for n in exam_names):
            continue  # 该原因的考试未运行(判定器硬门另行处理缺考)
        evidence = replication_evidence.get(reason) or {}
        collapse_available = bool(evidence.get("collapse_evidence_available"))
        collapsed = bool(evidence.get("advantage_collapse"))
        replicated = bool(evidence.get("replication_met"))
        gate = {
            "divergence_detected": bool(dependency),
            "base_effective_score": bool(effective),
            "advantage_collapse": bool(collapsed),
            "collapse_evidence_available": collapse_available,
            "replicated": replicated,
            "tested_episodes": evidence.get("tested_episodes", 0),
            "distinct_seeds": evidence.get("distinct_seeds", 0),
            "failing_episodes": evidence.get("failing_episodes", 0),
            "collapse_bootstrap": evidence.get("collapse_bootstrap"),
            "stands": bool(effective and dependency and collapsed
                           and replicated),
        }
        reasons[reason] = gate
        # E3:依赖被检出但缺少崩溃证据 -> 不默认成立
        if dependency and effective and not collapse_available:
            missing_collapse.append(reason)
        elif dependency and effective and collapse_available \
                and not collapsed and not replicated \
                and evidence.get("distinct_seeds", 0) < min_distinct_seeds:
            insufficient.append(reason)

    standing = sorted(k for k, v in reasons.items() if v["stands"])
    null_records = records_by_name.get("null_control") or []
    null = null_records[-1] if null_records else None
    null_flags: dict[str, Any] = {
        "high_turnover": None, "stable_positive_excess_any_family": None,
    }
    if null is not None:
        null_flags = {
            "high_turnover": bool(null.extra.get("high_turnover")),
            "stable_positive_excess_any_family": any(
                v.get("stable_positive_excess")
                for v in (null.extra.get("per_family") or {}).values()
            ),
        }
    return {
        "suspected_cheating": len(standing) > 0,
        "cheat_reasons": standing,
        "reason_gates": reasons,
        "ordinary_failure_only": len(standing) == 0,
        "missing_collapse_evidence": missing_collapse,
        "insufficient_evidence_reasons": insufficient,
        "null_control_flags": null_flags,
        "failed_tests": [r.name for r in cf_results if not r.pass_],
        "gate_definition": (
            "SUSPECTED_CHEATING 需四门证据:原始有效成绩 + 依赖禁止变量"
            "(反事实失败) + 优势崩溃(真实变体收益 bootstrap,缺证据不"
            "默认成立) + 多 seed 真实重复(逐原因实际测试 Episode/"
            "seed 计数);未达最低有效成绩的行为异常只构成普通 FAIL"
        ),
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
    test_nuisance_slot_injection,
    test_nuisance_slot_shuffle,
    test_signal_ablation,
    test_trend_direction_mirror,
    test_cost_monotonicity,
    test_null_control,
):
    _exam_fn.__test__ = False  # type: ignore[attr-defined]
