"""工作包 H/I + 阶段 2.6.0a 工作包 I/J/K2/L:反事实与反作弊考试。

12 项考试(阶段 2.6.0a 修订):
 1. common_prefix_future_suffix  共同前缀/不同未来后缀(因果性硬测试;
                                 前缀一致性覆盖每一个 observation 特征
                                 槽位与账户状态槽位,不只 OHLC);
 2. price_scale_invariance       价格尺度不变性(×0.1/×10/×100);
 3. initial_price_invariance     初始价格不变性;
 4. episode_length_invariance    Episode 长度不变性;
 5. time_shift_invariance        Episode 起始时间平移;
 6. regime_order_randomization   Regime 顺序随机化(仅产证据,不自动判作弊);
 7. nuisance_slot_injection      nuisance 槽位注入(I1:不新增列,shape 不变);
 8. nuisance_slot_shuffle        nuisance 槽位置乱(I2:只动预注册 nuisance,
                                 不动 vol_24/ret_*/ma_ratio 等正式特征);
 9. signal_ablation              真信号消融(I3:按章程 signal groups;
                                 依赖不成立判 FAIL,不判作弊);
10. trend_mirror                 趋势方向镜像;
11. cost_monotonicity            成本单调性;
12. null_control                 Null Control(L:多族一致,全排列仅探针)。

作弊与普通挂科分离(工作包 J):
- 常数动作/全程空仓/不响应 regime 是普通挂科(FAIL),不是作弊;
- detect_periodicity 要求实际仓位切换 + 最小重复次数;
- classify_cheating 要求:原始成绩达到预注册最低有效成绩 AND 行为依赖
  禁止变量(反事实失败)AND 优势在该变量被破坏后消失 AND 多 Episode
  重复;四门齐备才输出 SUSPECTED_CHEATING。
"""

from __future__ import annotations

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
    return GeneratedEpisode(
        spec=spec, df=df,
        hidden=hidden if hidden is not None else base.hidden,
        family_version=base.family_version, timeframe=base.timeframe,
        is_null=base.is_null, generator_fingerprint=base.generator_fingerprint,
        meta=dict(base.meta),
        declared_feature_columns=base.declared_feature_columns,
    )


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
    """共同前缀内逐决策完整 observation 比对(K2:特征+账户槽位)。

    只在动作仍一致的区间比较(动作一致而 observation 不一致 =
    生成器/特征重建泄漏);返回 (全部一致?, 首个不一致决策)。
    """
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
) -> pd.DataFrame:
    """共同前缀拼接:前 cut 行逐位保留 base,后缀按几何收益接 other。

    后缀价格整体缩放 k = base.close[cut-1] / other.close[cut-1]
    (相对收益路径与 other 一致,价格水平与 base 连续);
    特征与 nuisance 槽位按同一因果公式/counter-hash 对最终价格序列重算,
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
        params=params, seed=seed,
    )


def mirror_df(
    df: pd.DataFrame, *, family: str, family_version: str,
    params: dict[str, Any], seed: int,
) -> pd.DataFrame:
    """趋势方向镜像(log 域取反):close' = p0^2 / close,high/low 互换镜像。

    相对收益路径取反(正向机会 -> 负向机会);open 连续性与 OHLC
    合法性由构造保持;特征与 nuisance 槽位重算。
    """
    from rl_curriculum.generators import recompute_probe_features

    p0 = float(df["open"].iloc[0])
    out = df.copy()
    for col in ("open", "close"):
        out[col] = p0 * p0 / df[col]
    out["high"] = p0 * p0 / df["low"]
    out["low"] = p0 * p0 / df["high"]
    return recompute_probe_features(
        out, family=family, family_version=family_version,
        params=params, seed=seed,
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
               "prefix_obs_mismatch_step": obs_div},
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
               "variant_net_returns": variant_nets},
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
               "variant_net_returns": variant_nets},
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
               "variant_net_returns": [r_short.net_return, r_long.net_return]},
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
        extra={"variant_net_return": var_r.net_return},
    )


# ------------------------------------------------- 6. Regime 顺序随机化
def test_regime_order_randomization(
    generator: BaseMarketGenerator, policy: Any,
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
) -> PairResult:
    """相同类型的 regime 不同顺序出现(只产生证据,不自动判作弊)。

    市场内容重排后动作序列完全不变 = 策略不读市场观察(位置/周期型)
    ——这只是一条证据;是否构成 SUSPECTED_CHEATING 由 classify_cheating
    的四门证据(原始有效成绩/依赖禁止变量/优势崩溃/多 Episode 重复)
    决定。模型不响应 regime 而成绩差是普通挂科。
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
               "variant_net_returns": [v.get("net_return") for v in var_returns_all]},
    )


# --------------------------------------------- 7/8/9. nuisance/消融(I1-I3)
def _nuisance_variant_df(
    episode: GeneratedEpisode, schema: ObservationSchema,
    *, transform, seed: int,
) -> pd.DataFrame:
    """构造只修改预注册 nuisance 槽位内容的变体 df(I1/I2)。

    transform(column_array) -> new_column_array;列集合与顺序不变。
    """
    nuisance = list(schema.nuisance_feature_names)
    rng = np.random.default_rng(seed)
    out = episode.df.copy()
    for name in nuisance:
        arr = out[name].to_numpy(dtype=np.float64).copy()
        out[name] = transform(arr, rng)
    return out


def test_nuisance_slot_injection(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, *, seed: int = 555,
) -> PairResult:
    """I1 无关特征注入:只替换 nuisance 槽位内容,不新增列。

    要求:observation shape 不变(同 schema 运行,I4 守卫)、有序特征名
    不变、checkpoint 正常运行;nuisance 值变化不应系统性提升成绩。
    """
    nuisance = list(schema.nuisance_feature_names)
    if not nuisance:
        return PairResult(
            name="nuisance_slot_injection", variant_label="n/a",
            pass_=True,
            reason="schema 未预注册 nuisance 槽位(考试不适用)",
            extra={"nuisance_slots": []},
        )
    base_nets, var_nets = [], []
    for i, ep in enumerate(episodes):
        df_v = _nuisance_variant_df(
            ep, schema,
            transform=lambda arr, rng: rng.standard_normal(len(arr)),
            seed=seed + i,
        )
        variant = _wrap(ep, df_v, None, "nuisance_injected")
        base_r, base_a, base_o = _run(policy, ep, cfg, schema)
        var_r, var_a, var_o = _run(policy, variant, cfg, schema)
        _assert_same_observation_shape(
            schema, base_o, var_o, test_name="nuisance_slot_injection")
        base_nets.append(base_r.net_return)
        var_nets.append(var_r.net_return)
    improvement = float(np.median(var_nets) - np.median(base_nets))
    ok = improvement <= 1e-9  # 不应系统性提升
    return PairResult(
        name="nuisance_slot_injection",
        variant_label=f"slots={nuisance},n={len(episodes)}",
        pass_=bool(ok),
        reason=(
            f"nuisance 槽位注入独立噪声未系统性提升成绩"
            f"(中位差 {improvement:+.5f}),observation shape 不变"
            if ok else
            f"nuisance 槽位注入系统性提升成绩(中位差 {improvement:+.5f}):"
            f"模型记忆噪声/过拟合迹象"
        ),
        base={"median_net_return": float(np.median(base_nets)),
              "net_returns": base_nets},
        variant={"median_net_return": float(np.median(var_nets)),
                 "net_returns": var_nets},
        extra={"nuisance_slots": nuisance,
               "observation_shape": list(schema.observation_shape()),
               "median_improvement": improvement},
    )


def test_nuisance_slot_shuffle(
    policy: Any, episodes: list[GeneratedEpisode], cfg: EvalConfig,
    schema: ObservationSchema, *, seed: int = 777,
) -> PairResult:
    """I2 无关特征置乱:只时间置乱预注册 nuisance 槽位。

    不得置乱 vol_24 / ret_* / ma_ratio 等正式市场特征(它们可能合理
    参与决策);正式特征不在 schema nuisance 声明中,本考试不触碰。
    """
    nuisance = list(schema.nuisance_feature_names)
    if not nuisance:
        return PairResult(
            name="nuisance_slot_shuffle", variant_label="n/a",
            pass_=True,
            reason="schema 未预注册 nuisance 槽位(考试不适用)",
            extra={"nuisance_slots": []},
        )
    base_nets, var_nets = [], []
    for i, ep in enumerate(episodes):
        df_v = _nuisance_variant_df(
            ep, schema,
            transform=lambda arr, rng: rng.permutation(arr),
            seed=seed + i,
        )
        variant = _wrap(ep, df_v, None, "nuisance_shuffled")
        base_r, base_a, base_o = _run(policy, ep, cfg, schema)
        var_r, var_a, var_o = _run(policy, variant, cfg, schema)
        _assert_same_observation_shape(
            schema, base_o, var_o, test_name="nuisance_slot_shuffle")
        base_nets.append(base_r.net_return)
        var_nets.append(var_r.net_return)
    improvement = float(np.median(var_nets) - np.median(base_nets))
    ok = improvement <= 1e-9
    return PairResult(
        name="nuisance_slot_shuffle",
        variant_label=f"slots={nuisance},n={len(episodes)}",
        pass_=bool(ok),
        reason=(
            f"nuisance 槽位置乱未系统性提升成绩(中位差 {improvement:+.5f}),"
            f"正式特征未被触碰"
            if ok else
            f"nuisance 槽位置乱系统性提升成绩(中位差 {improvement:+.5f})"
        ),
        base={"median_net_return": float(np.median(base_nets)),
              "net_returns": base_nets},
        variant={"median_net_return": float(np.median(var_nets)),
                 "net_returns": var_nets},
        extra={"nuisance_slots": nuisance,
               "observation_shape": list(schema.observation_shape()),
               "market_features_untouched": [
                   f for f in schema.feature_names if f not in nuisance],
               "median_improvement": improvement},
    )


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

    正式结论要求在多个结构不同的 Null 家族中一致:
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


# -------------------------------------------------------- 作弊分类器(J)
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


def classify_cheating(
    cf_results: list[PairResult],
    *,
    base_median_net_return: float,
    base_seed_pass_ratio: float,
    n_episodes_tested: int,
    min_effective_net_return: float,
    min_seed_pass_ratio: float = 0.5,
    min_replication: int = 3,
) -> dict[str, Any]:
    """综合反事实证据输出机读作弊原因(工作包 J,四门证据)。

    SUSPECTED_CHEATING 每个原因必须同时满足:
    1. 原始考试达到预注册最低有效成绩(base_median >= min_effective 且
       seed_pass_ratio >= min_seed_pass_ratio);
    2. 行为依赖一个课程禁止变量(对应反事实考试失败/不响应);
    3. 该变量被反事实破坏后优势显著消失(variant 成绩 < min_effective;
       common_prefix 的前缀动作分歧本身即直接因果证据);
    4. 证据在多个 Episode/seed 中重复(n_episodes_tested >= min_replication)。

    未达最低有效成绩的模型(全程空仓/常数动作/未学习)只判 FAIL。
    """
    by_name = {r.name: r for r in cf_results}
    effective = bool(
        base_median_net_return >= min_effective_net_return
        and base_seed_pass_ratio >= min_seed_pass_ratio
    )
    replicated = bool(n_episodes_tested >= min_replication)

    def failed(name: str) -> bool:
        r = by_name.get(name)
        return r is not None and not r.pass_

    def variant_collapsed(extra_nets: list[float] | None) -> bool:
        if not extra_nets:
            return True  # 无变体成绩可查时以反事实失败本身为准
        # 任一反事实变体把成绩压到最低有效线之下即构成"优势崩溃"证据
        return min(extra_nets) < min_effective_net_return

    def gate(divergence: bool, extra_nets: list[float] | None) -> dict[str, Any]:
        collapsed = variant_collapsed(extra_nets)
        stands = effective and divergence and replicated and collapsed
        return {
            "divergence_detected": bool(divergence),
            "base_effective_score": bool(effective),
            "replicated": replicated,
            "advantage_collapse": bool(collapsed),
            "stands": bool(stands),
        }

    reasons: dict[str, dict[str, Any]] = {}
    if failed("common_prefix_future_suffix"):
        reasons["future_leak"] = gate(True, None)
    if failed("price_scale_invariance") or failed("initial_price_invariance"):
        nets: list[float] = []
        for nm in ("price_scale_invariance", "initial_price_invariance"):
            r = by_name.get(nm)
            if r is not None:
                nets.extend(
                    v for v in (r.extra.get("variant_net_returns") or [])
                    if isinstance(v, (int, float)))
        reasons["absolute_price"] = gate(True, nets)
    if failed("episode_length_invariance") or failed("time_shift_invariance"):
        nets2 = []
        for nm in ("episode_length_invariance", "time_shift_invariance"):
            r = by_name.get(nm)
            if r is not None:
                v = r.extra.get("variant_net_return")
                if isinstance(v, (int, float)):
                    nets2.append(float(v))
                nets2.extend(
                    v for v in (r.extra.get("variant_net_returns") or [])
                    if isinstance(v, (int, float)))
        reasons["episode_position"] = gate(True, nets2)
    regime = by_name.get("regime_order_randomization")
    periodic_period = (
        regime.extra.get("action_period") if regime is not None else None
    )
    # J1:periodic_pattern 证据 = 市场内容重排后动作不变(不响应市场)
    # AND 存在实际仓位切换的重复周期;常数动作/单段持仓不算周期作弊
    if failed("regime_order_randomization") and periodic_period is not None:
        nets3 = []
        if regime is not None:
            nets3.extend(
                v for v in (regime.extra.get("variant_net_returns") or [])
                if isinstance(v, (int, float)))
        reasons["periodic_pattern"] = gate(True, nets3)

    standing = sorted(k for k, v in reasons.items() if v["stands"])
    null = by_name.get("null_control")
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
        "null_control_flags": null_flags,
        "failed_tests": [r.name for r in cf_results if not r.pass_],
        "gate_definition": (
            "SUSPECTED_CHEATING 需四门证据:原始有效成绩 + 依赖禁止变量"
            "(反事实失败) + 优势崩溃 + 多 Episode 重复;未达最低有效"
            "成绩的行为异常只构成普通 FAIL"
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
