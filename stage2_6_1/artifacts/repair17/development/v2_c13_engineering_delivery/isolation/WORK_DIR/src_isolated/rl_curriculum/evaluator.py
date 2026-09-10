"""工作包 F/N + 阶段 2.6.0a 工作包 A/D + 阶段 2.6.0b 工作包 B:确定性 Episode 评估器与统计纪律。

阶段 2.6.0a 关键变化(保留):
- 评估严格按 observation schema 的有序 feature whitelist 选择输入:
  Episode 出现额外特征列即 EvaluationError(fail closed),绝不按
  DataFrame 原始列序决定输入;
- 评估路径按策略能力拆分:
  * run_observation_episode:候选/基线只收到 observation(reset_episode
    -> act(obs) -> ...;不构造 future_returns,不传递 hidden/df);
  * run_oracle_episode:Oracle 独立上下文(当前行隐藏状态 + 仓位);
  * run_test_probe_episode:测试专用探针 harness(df/hidden/
    future_returns 仅在此构造,正式评估器中不存在这些对象);
- 指标完整性(工作包 D):终端清算手续费计入 total_fees 与
    total_execution_fees;policy_order_executions 与
  forced_terminal_executions 分离;policy_action_switches 只统计模型
  目标切换;round_trip_count 统计完整买卖往返。

阶段 2.6.0b 工作包 B:
- reset_episode() 无参数(候选不接收任何 Episode 身份 token);
- ObservableBaselinePolicy 经 episode_instance(episode_seed) 获得
  每 Episode 实例(RandomPolicy 确定性由该工厂承载);episode_seed
  只进入基线通道,正式候选评估路径对其不可达。

统计纪律:中位数、均值、10% 分位数、最差 Episode、seed 通过比例、
generator family 分组、参数区间分组、paired bootstrap 95% 区间;
不只报告最佳 seed、不只报告总平均收益。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from rl_platform.env import AlignedLongFlatEnv
from rl_curriculum.generator_api import (
    PRICE_COLUMNS,
    GeneratedEpisode,
)
from rl_curriculum.observation_schema import ObservationSchema
from rl_curriculum.policy_api import (
    ObservableBaselinePolicy,
    ObservationOnlyPolicy,
    OraclePolicy,
    TestOnlyProbePolicy,
)
from rl_curriculum.probes import TestHarnessContext

BOOTSTRAP_SEED = 20260826
BOOTSTRAP_DEFAULT_ITERS = 2000


class EvaluationError(RuntimeError):
    """评估过程出现错误 -> EXAM_INVALID(fail closed,不产出部分成绩)。"""


@dataclass(frozen=True)
class EvalConfig:
    fee: float = 0.001
    slippage_bps: float = 0.0
    price_tick: float = 0.0
    initial_cash: float = 100.0
    reward_scale: float = 1.0  # 仅记录,不影响指标
    window_size: int = 1
    deterministic: bool = True  # 正式评估默认 True

    def manifest(self) -> dict[str, Any]:
        return {
            "fee": self.fee, "slippage_bps": self.slippage_bps,
            "price_tick": self.price_tick, "initial_cash": self.initial_cash,
            "reward_scale": self.reward_scale, "window_size": self.window_size,
            "deterministic": self.deterministic,
        }

    def config_hash(self) -> str:
        return "ec-" + hashlib.sha256(
            json.dumps(self.manifest(), sort_keys=True,
                       separators=(",", ":")).encode("utf-8")
        ).hexdigest()


@dataclass
class EpisodeResult:
    spec: Any                     # EpisodeSpec
    net_return: float             # 扣费收益 = final_cash/initial_cash - 1
    final_cash: float
    max_drawdown: float           # 逐 bar 净值峰谷最大回撤
    n_trades: int                 # buy+sell 成交次数(模型执行,不含强制清算)
    turnover_rate: float          # 模型目标切换次数 / 决策数
    total_fees: float             # 全部费用(含终端清算手续费)
    avg_position: float           # 持仓决策占比
    avg_holding_bars: float       # 平均连续持仓段长度(bars)
    n_decisions: int
    actions_sha256: str           # 行为指纹
    actions_count: dict[str, int]
    family_version: str
    generator_fingerprint: str
    reward_consistency_ok: bool   # sum(reward_raw) == log(final/initial)
    reward_abs_error: float
    # ------------------------------------------------ 阶段 2.6.0a 指标分离(工作包 D)
    policy_action_switches: int = 0       # 模型目标仓位切换次数
    policy_order_executions: int = 0      # 模型请求的成交次数(buy/sell)
    forced_terminal_executions: int = 0   # 终端强制清算次数(非模型主动)
    total_execution_fees: float = 0.0     # 模型成交手续费(不含强制清算)
    terminal_liquidation_fee: float = 0.0 # 终端清算手续费
    round_trip_count: int = 0             # 完整买入->卖出/清算往返数

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.spec.family, "seed": self.spec.seed,
            "split": self.spec.split, "params": self.spec.params,
            "timeframe": self.spec.timeframe,
            "net_return": self.net_return, "final_cash": self.final_cash,
            "max_drawdown": self.max_drawdown, "n_trades": self.n_trades,
            "turnover_rate": self.turnover_rate, "total_fees": self.total_fees,
            "avg_position": self.avg_position,
            "avg_holding_bars": self.avg_holding_bars,
            "n_decisions": self.n_decisions,
            "actions_sha256": self.actions_sha256,
            "actions_count": self.actions_count,
            "family_version": self.family_version,
            "generator_fingerprint": self.generator_fingerprint,
            "reward_consistency_ok": self.reward_consistency_ok,
            "reward_abs_error": self.reward_abs_error,
            "policy_action_switches": self.policy_action_switches,
            "policy_order_executions": self.policy_order_executions,
            "forced_terminal_executions": self.forced_terminal_executions,
            "total_execution_fees": self.total_execution_fees,
            "terminal_liquidation_fee": self.terminal_liquidation_fee,
            "round_trip_count": self.round_trip_count,
        }


# ------------------------------------------------------------- schema 绑定
def derive_episode_seed(spec: Any) -> int:
    """从 EpisodeSpec 规范化哈希派生每 Episode 独立种子(顺序无关)。

    工作包 B:该种子只用于 ObservableBaselinePolicy.episode_instance
    (随机基线确定性)与环境 reset;不得传给正式 CandidatePolicy。
    """
    return int.from_bytes(
        hashlib.sha256(spec.canonical().encode("utf-8")).digest()[:8], "big"
    )


def select_features_strict(
    df: pd.DataFrame, schema: ObservationSchema, *,
    context: str = "episode",
) -> pd.DataFrame:
    """严格按 schema 有序 whitelist 选择 observation 特征(B1)。

    - df 特征列集合必须与 whitelist 精确一致:额外列 fail closed
      (命名无关,vol 之外任何字段不在 whitelist 即拒绝);
    - 输入顺序由 schema 决定,不由 DataFrame 列序决定。
    """
    obs_cols = [
        c for c in df.columns
        if c not in PRICE_COLUMNS and c != "date"
    ]
    schema.assert_column_whitelist(obs_cols, context=context)
    return df[list(schema.feature_names)]


def _build_env(
    episode: GeneratedEpisode, cfg: EvalConfig, schema: ObservationSchema,
) -> AlignedLongFlatEnv:
    if cfg.window_size != schema.window_size:
        raise EvaluationError(
            f"EvalConfig.window_size={cfg.window_size} 与 observation schema "
            f"window_size={schema.window_size} 不一致(考试条件与 schema "
            f"必须一致,不得错位)")
    features = select_features_strict(
        episode.df, schema, context=f"{episode.spec.family}"
        f"/seed={episode.spec.seed}",
    )
    return AlignedLongFlatEnv(
        features=features,
        prices=episode.df[list(PRICE_COLUMNS)],
        fee=cfg.fee, slippage_bps=cfg.slippage_bps,
        initial_cash=cfg.initial_cash, reward_scale=cfg.reward_scale,
        window_size=cfg.window_size, price_tick=cfg.price_tick,
        execution_mode="market_open_causal",
    )


def _collect_metrics(
    episode: GeneratedEpisode, cfg: EvalConfig, env: AlignedLongFlatEnv,
    actions: list[int], equities: list[float], fee_events: list[dict[str, Any]],
    total_reward_raw: float,
) -> EpisodeResult:
    final_cash = float(env.ledger.cash)
    if env.ledger.btc != 0.0:
        raise EvaluationError(
            f"{episode.spec.family} seed={episode.spec.seed}:Episode 结束后"
            f"账本仍有持仓 {env.ledger.btc}(终端清算合同被违反)"
        )
    net_return = final_cash / cfg.initial_cash - 1.0
    eq = np.asarray([cfg.initial_cash] + equities)
    cummax = np.maximum.accumulate(eq)
    max_dd = float(np.max(1.0 - eq / cummax))
    switches = sum(1 for i in range(1, len(actions)) if actions[i] != actions[i - 1])
    holding_segments: list[int] = []
    run = 0
    for a in actions:
        if a == 1:
            run += 1
        elif run:
            holding_segments.append(run)
            run = 0
    if run:
        holding_segments.append(run)
    n_long = sum(actions)
    reward_target = float(np.log(final_cash / cfg.initial_cash))
    reward_err = abs(total_reward_raw - reward_target)
    actions_bytes = np.asarray(actions, dtype=np.int64).tobytes()

    # ------------------------------------------------ 工作包 D:费用/执行分离
    policy_order_executions = sum(
        1 for e in fee_events if e["kind"] == "policy_order")
    forced_terminal_executions = sum(
        1 for e in fee_events if e["kind"] == "forced_terminal")
    total_execution_fees = float(sum(
        e["fee"] for e in fee_events if e["kind"] == "policy_order"))
    terminal_liquidation_fee = float(sum(
        e["fee"] for e in fee_events if e["kind"] == "forced_terminal"))
    total_fees = total_execution_fees + terminal_liquidation_fee
    # 完整往返:0->1 开仓后经历 1->0(模型)或终端清算(强制)平仓
    round_trips = 0
    open_ = False
    for a in actions:
        if a == 1 and not open_:
            open_ = True
        elif a == 0 and open_:
            open_ = False
            round_trips += 1
    if open_:  # 终端强制平仓也闭合一次往返
        round_trips += 1

    return EpisodeResult(
        spec=episode.spec,
        net_return=net_return,
        final_cash=final_cash,
        max_drawdown=max_dd,
        n_trades=policy_order_executions,
        turnover_rate=switches / max(len(actions), 1),
        total_fees=total_fees,
        avg_position=n_long / max(len(actions), 1),
        avg_holding_bars=(
            float(np.mean(holding_segments)) if holding_segments else 0.0
        ),
        n_decisions=len(actions),
        actions_sha256=hashlib.sha256(actions_bytes).hexdigest(),
        actions_count={"0": len(actions) - n_long, "1": n_long},
        family_version=episode.family_version,
        generator_fingerprint=episode.generator_fingerprint,
        reward_consistency_ok=reward_err < 1e-9,
        reward_abs_error=reward_err,
        policy_action_switches=switches,
        policy_order_executions=policy_order_executions,
        forced_terminal_executions=forced_terminal_executions,
        total_execution_fees=total_execution_fees,
        terminal_liquidation_fee=terminal_liquidation_fee,
        round_trip_count=round_trips,
    )


# ------------------------------------------------------ obs-only(候选/基线)
def run_observation_episode(
    policy: ObservationOnlyPolicy, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema, *,
    return_actions: bool = False, return_observations: bool = False,
):
    """正式评估路径:候选/基线每步只收到 observation。

    本函数不构造 future_returns、不读取 hidden、不把 df 交给策略;
    当前仓位已在 observation 账户槽位内。

    工作包 B:reset_episode() 无参数。基线经 episode_instance(seed)
    获得每 Episode 独立实例(随机基线确定性);候选直接 reset(),
    不接收任何身份 token。
    """
    if isinstance(policy, ObservableBaselinePolicy):
        policy.bind_observation_schema(schema)
        episode_policy = policy.episode_instance(
            derive_episode_seed(episode.spec))
        if episode_policy is not policy and isinstance(
                episode_policy, ObservableBaselinePolicy):
            episode_policy.bind_observation_schema(schema)
    else:
        episode_policy = policy
    env = _build_env(episode, cfg, schema)
    obs, _ = env.reset(seed=episode.spec.seed)
    schema.assert_observation_array(
        obs, context=f"{episode.spec.family}/seed={episode.spec.seed} 首步")
    episode_policy.reset_episode()  # 无参数:无 seed/无 Episode 身份 token
    actions: list[int] = []
    equities: list[float] = []
    fee_events: list[dict[str, Any]] = []
    total_reward_raw = 0.0
    observations: list[np.ndarray] | None = [] if return_observations else None
    done = False
    while not done:
        if observations is not None:
            observations.append(np.array(obs))
        action = int(episode_policy.act(obs))  # 只有 observation
        obs, _reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        actions.append(action)
        equities.append(float(info["equity_end"]))
        if info["trade_direction"] in ("buy", "sell"):
            fee_events.append(
                {"kind": "policy_order", "fee": float(info["fee_paid"])})
        liq = info.get("terminal_liquidation")
        if liq is not None and float(liq.get("qty", 0.0)) > 0.0:
            fee_events.append(
                {"kind": "forced_terminal", "fee": float(liq["fee_paid"])})
        total_reward_raw += float(info["reward_raw"])

    result = _collect_metrics(
        episode, cfg, env, actions, equities, fee_events, total_reward_raw)
    if return_actions or return_observations:
        return result, actions, observations
    return result


# ------------------------------------------------------------------ Oracle
def run_oracle_episode(
    policy: OraclePolicy, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema, *,
    return_actions: bool = False,
):
    """Oracle 路径:独立上下文 = 当前行隐藏状态 + 当前仓位。

    不得访问未来隐藏状态或完整未来收益(hidden_row 仅当前行)。
    """
    from rl_curriculum.policy_api import OracleActContext

    env = _build_env(episode, cfg, schema)
    obs, _ = env.reset(seed=episode.spec.seed)
    policy.reset_episode()
    actions: list[int] = []
    equities: list[float] = []
    fee_events: list[dict[str, Any]] = []
    total_reward_raw = 0.0
    done = False
    while not done:
        row = episode.hidden.iloc[env._current_tick]  # noqa: SLF001
        ctx = OracleActContext(
            tick=int(env._current_tick),           # noqa: SLF001
            position=int(env._target_position),    # noqa: SLF001
            hidden_row={k: float(row[k]) for k in episode.hidden.columns},
        )
        action = int(policy.act(ctx))
        obs, _reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        actions.append(action)
        equities.append(float(info["equity_end"]))
        if info["trade_direction"] in ("buy", "sell"):
            fee_events.append(
                {"kind": "policy_order", "fee": float(info["fee_paid"])})
        liq = info.get("terminal_liquidation")
        if liq is not None and float(liq.get("qty", 0.0)) > 0.0:
            fee_events.append(
                {"kind": "forced_terminal", "fee": float(liq["fee_paid"])})
        total_reward_raw += float(info["reward_raw"])

    result = _collect_metrics(
        episode, cfg, env, actions, equities, fee_events, total_reward_raw)
    if return_actions:
        return result, actions
    return result


# ------------------------------------------------------------- 测试探针 harness
def run_test_probe_episode(
    probe: TestOnlyProbePolicy, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema, *,
    return_actions: bool = False, return_observations: bool = False,
):
    """测试专用探针评估(独立 harness;正式候选评估器绝不调用本函数)。

    只有此路径构造 future_returns 与完整 df/hidden 上下文,用于证明
    反作弊考试能抓到故意作弊;探针不能进入正式接口(接口签名 +
    is_test_only_harness 双重隔离)。
    """
    env = _build_env(episode, cfg, schema)
    obs, _ = env.reset(seed=episode.spec.seed)
    probe.reset_episode()
    log_close = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    future_returns = np.diff(log_close, prepend=log_close[0])
    actions: list[int] = []
    equities: list[float] = []
    fee_events: list[dict[str, Any]] = []
    total_reward_raw = 0.0
    observations: list[np.ndarray] | None = [] if return_observations else None
    done = False
    while not done:
        if observations is not None:
            observations.append(np.array(obs))
        ctx = TestHarnessContext(
            tick=int(env._current_tick),        # noqa: SLF001
            n_rows=int(env.n_rows),
            position=int(env._target_position),  # noqa: SLF001
            df=episode.df, hidden=episode.hidden,
            future_returns=future_returns,
        )
        action = int(probe.act(obs, ctx))
        obs, _reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        actions.append(action)
        equities.append(float(info["equity_end"]))
        if info["trade_direction"] in ("buy", "sell"):
            fee_events.append(
                {"kind": "policy_order", "fee": float(info["fee_paid"])})
        liq = info.get("terminal_liquidation")
        if liq is not None and float(liq.get("qty", 0.0)) > 0.0:
            fee_events.append(
                {"kind": "forced_terminal", "fee": float(liq["fee_paid"])})
        total_reward_raw += float(info["reward_raw"])

    result = _collect_metrics(
        episode, cfg, env, actions, equities, fee_events, total_reward_raw)
    if return_actions or return_observations:
        return result, actions, observations
    return result


# ------------------------------------------------------------------ 调度器
def run_policy_episode(
    policy: Any, episode: GeneratedEpisode, cfg: EvalConfig,
    schema: ObservationSchema, *,
    return_actions: bool = False, return_observations: bool = False,
):
    """按策略类型分发到对应评估路径(能力隔离的运行时边界)。

    return_actions/return_observations 为 True 时返回
    (result, actions, observations_or_None) 三元组(探针/Oracle 路径
    observations 恒为 None);两者均 False 时只返回 result。
    """
    if getattr(policy, "is_test_only_harness", False) or \
            isinstance(policy, TestOnlyProbePolicy):
        r, a, o = run_test_probe_episode(
            policy, episode, cfg, schema,
            return_actions=True, return_observations=return_observations)
        if return_actions or return_observations:
            return r, a, o
        return r
    if isinstance(policy, OraclePolicy):
        r, a = run_oracle_episode(
            policy, episode, cfg, schema, return_actions=True)
        return (r, a, None) if return_actions else r
    if isinstance(policy, ObservationOnlyPolicy):
        r, a, o = run_observation_episode(
            policy, episode, cfg, schema,
            return_actions=True, return_observations=return_observations,
        )
        if return_actions or return_observations:
            return r, a, o
        return r
    raise EvaluationError(
        f"未知策略类型 {type(policy).__name__}:正式评估只接受 "
        f"CandidatePolicy/ObservableBaselinePolicy(obs-only)、"
        f"OraclePolicy(独立上下文)或 TestOnlyProbePolicy(测试 harness)")


# ---------------------------------------------------------------------- 统计
def paired_bootstrap_ci(
    diffs: list[float],
    *,
    n_boot: int = BOOTSTRAP_DEFAULT_ITERS,
    seed: int = BOOTSTRAP_SEED,
    stat: str = "median",
    alpha: float = 0.05,
) -> dict[str, float]:
    """配对 bootstrap 95% 区间(同一考试包内逐 episode 差值)。"""
    arr = np.asarray(diffs, dtype=np.float64)
    if len(arr) == 0:
        return {"n": 0, "stat": float("nan"), "ci_low": float("nan"),
                "ci_high": float("nan")}
    rng = np.random.default_rng(seed)
    stats = np.empty(n_boot)
    for b in range(n_boot):
        sample = arr[rng.integers(0, len(arr), size=len(arr))]
        stats[b] = float(np.median(sample)) if stat == "median" else float(np.mean(sample))
    lo, hi = np.quantile(stats, [alpha / 2, 1 - alpha / 2])
    point = float(np.median(arr)) if stat == "median" else float(np.mean(arr))
    return {
        "n": int(len(arr)), "stat": point,
        "ci_low": float(lo), "ci_high": float(hi),
    }


def summarize_returns(values: list[float]) -> dict[str, float]:
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) == 0:
        return {"n": 0}
    return {
        "n": int(len(arr)),
        "median": float(np.median(arr)),
        "mean": float(np.mean(arr)),
        "q10": float(np.quantile(arr, 0.10)),
        "worst": float(np.min(arr)),
        "best": float(np.max(arr)),
    }


def group_results(
    results: list[EpisodeResult], key_fn
) -> dict[str, dict[str, float]]:
    groups: dict[str, list[float]] = {}
    for r in results:
        groups.setdefault(key_fn(r), []).append(r.net_return)
    return {k: summarize_returns(v) for k, v in sorted(groups.items())}


def param_bucket(result: EpisodeResult) -> str:
    """参数区间分组:探针参数以离散桶表达(强度/波动率分档)。"""
    p = result.spec.params
    drift = p.get("drift_bps_range", p.get("drift_bps"))
    if isinstance(drift, (list, tuple)) and len(drift) == 2:
        mid = (float(drift[0]) + float(drift[1])) / 2.0
        bucket = "weak" if mid < 10 else ("medium" if mid < 16 else "strong")
    else:
        bucket = "default"
    return f"{result.spec.family}:{bucket}"


# ---------------------------------------------------------------------- 主入口
def evaluator_code_hash(package_dir: Path | None = None) -> str:
    """评估代码版本:rl_curriculum 目录内容哈希(排序遍历,顺序无关)。"""
    import rl_curriculum

    root = Path(package_dir) if package_dir else Path(rl_curriculum.__file__).parent
    entries = []
    for f in sorted(root.rglob("*.py")):
        entries.append(
            [str(f.relative_to(root)), hashlib.sha256(f.read_bytes()).hexdigest()]
        )
    tree = hashlib.sha256(
        json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return "e-" + tree


def evaluate_policy(
    policy: Any,
    episodes: list[GeneratedEpisode],
    cfg: EvalConfig,
    schema: ObservationSchema,
    *,
    baseline_policies: dict[str, Any] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """确定性评估一个策略;可选基线做逐 episode 配对差与 bootstrap。"""
    ordered = sorted(episodes, key=lambda e: e.spec.canonical())
    results = [
        run_policy_episode(policy, e, cfg, schema) for e in ordered
    ]
    for r in results:
        if not np.isfinite(r.net_return):
            raise EvaluationError(
                f"Episode 指标出现 NaN/inf({r.spec.family} seed={r.spec.seed})"
            )
        if not r.reward_consistency_ok:
            raise EvaluationError(
                f"reward 与最终净值不一致({r.spec.family} "
                f"seed={r.spec.seed},误差 {r.reward_abs_error})"
            )
    report: dict[str, Any] = {
        "policy": policy.name if label is None else label,
        "reads_hidden": bool(getattr(policy, "reads_hidden", False)),
        "policy_kind": (
            "test_only_probe" if getattr(policy, "is_test_only_harness", False)
            else ("oracle" if isinstance(policy, OraclePolicy) else "obs_only")
        ),
        "eval_config": cfg.manifest(),
        "eval_config_hash": cfg.config_hash(),
        "observation_schema_hash": schema.schema_hash(),
        "n_episodes": len(results),
        "overall": summarize_returns([r.net_return for r in results]),
        "by_split": group_results(results, lambda r: r.spec.split),
        "by_family": group_results(results, lambda r: r.spec.family),
        "by_param_bucket": group_results(results, param_bucket),
        "behavior": {
            "median_turnover": float(np.median([r.turnover_rate for r in results])),
            "median_trades": float(np.median([r.n_trades for r in results])),
            "median_avg_position": float(
                np.median([r.avg_position for r in results])),
            "median_max_drawdown": float(
                np.median([r.max_drawdown for r in results])),
            "median_round_trips": float(
                np.median([r.round_trip_count for r in results])),
            "median_policy_order_executions": float(np.median(
                [r.policy_order_executions for r in results])),
            "median_forced_terminal_executions": float(np.median(
                [r.forced_terminal_executions for r in results])),
        },
        "fees": {
            "median_total_fees": float(np.median([r.total_fees for r in results])),
            "median_total_execution_fees": float(np.median(
                [r.total_execution_fees for r in results])),
            "median_terminal_liquidation_fee": float(np.median(
                [r.terminal_liquidation_fee for r in results])),
        },
        "episodes": [r.to_record() for r in results],
        "evaluator_code_hash": evaluator_code_hash(),
    }
    # 种子通过比例:逐 episode 优于 Always Flat
    from rl_curriculum.policies import AlwaysFlatPolicy

    flat_policy = AlwaysFlatPolicy()
    flat_results = {
        e.spec.canonical(): run_policy_episode(flat_policy, e, cfg, schema)
        for e in ordered
    }
    passes = [
        1 if r.net_return > flat_results[r.spec.canonical()].net_return else 0
        for r in results
    ]
    report["seed_pass_ratio_vs_always_flat"] = float(np.mean(passes)) if passes else 0.0

    if baseline_policies:
        comparisons: dict[str, Any] = {}
        for bname, bpol in baseline_policies.items():
            bl = {
                e.spec.canonical(): run_policy_episode(bpol, e, cfg, schema)
                for e in ordered
            }
            diffs = [
                r.net_return - bl[r.spec.canonical()].net_return for r in results
            ]
            comparisons[bname] = {
                "paired_diff_bootstrap": paired_bootstrap_ci(diffs),
                "mean_diff": float(np.mean(diffs)),
                "median_diff": float(np.median(diffs)),
                "regret_median": (
                    float(np.median([-d for d in diffs])) if bname.startswith("oracle")
                    else None
                ),
            }
        report["vs_baselines"] = comparisons
    return report
