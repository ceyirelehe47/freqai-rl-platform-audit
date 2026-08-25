"""工作包 F + N:确定性 Episode 评估器与统计纪律。

同一 (checkpoint/policy, 考试包, 环境版本, 评估代码版本) 必须生成
完全一致的结果:Episode 顺序按规范化 spec 排序、逐 episode RNG 种子
派生固定、bootstrap 种子固定、结果不含文件遍历顺序依赖。

输出:净值/扣费收益/最大回撤/换手/交易次数/费用/平均仓位/持仓时长、
相对 Always Flat 与规则基线的差值、相对 Oracle 的 regret、分 family /
分参数区间 / 最差分位数 / 种子通过比例、paired bootstrap 95% 置信区间、
行为指纹(动作序列 SHA-256)。

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
    BaseMarketGenerator,
    EpisodeSpec,
    GeneratedEpisode,
)
from rl_curriculum.policies import (
    ActContext,
    AlwaysFlatPolicy,
    Policy,
)

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


@dataclass
class EpisodeResult:
    spec: EpisodeSpec
    net_return: float            # 扣费收益 = final_cash/initial_cash - 1
    final_cash: float
    max_drawdown: float          # 逐 bar 净值峰谷最大回撤
    n_trades: int                # buy+sell 成交次数
    turnover_rate: float         # 仓位切换次数 / 决策数
    total_fees: float
    avg_position: float          # 持仓决策占比
    avg_holding_bars: float      # 平均连续持仓段长度(bars)
    n_decisions: int
    actions_sha256: str          # 行为指纹
    actions_count: dict[str, int]
    family_version: str
    generator_fingerprint: str
    reward_consistency_ok: bool  # sum(reward_raw) == log(final/initial)
    reward_abs_error: float

    def to_record(self) -> dict[str, Any]:
        return {
            "family": self.spec.family, "seed": self.spec.seed,
            "split": self.spec.split, "params": self.spec.params,
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
        }


# ------------------------------------------------------------------ 单 Episode
def run_episode(
    policy: Policy, episode: GeneratedEpisode, cfg: EvalConfig,
    *, return_actions: bool = False,
):
    """在冻结的 AlignedLongFlatEnv(market_open_causal)上运行单个 Episode。"""
    feature_cols = [
        c for c in episode.df.columns
        if c not in PRICE_COLUMNS and c != "date"
    ]
    env = AlignedLongFlatEnv(
        features=episode.df[feature_cols],
        prices=episode.df[list(PRICE_COLUMNS)],
        fee=cfg.fee, slippage_bps=cfg.slippage_bps,
        initial_cash=cfg.initial_cash, reward_scale=cfg.reward_scale,
        window_size=cfg.window_size, price_tick=cfg.price_tick,
        execution_mode="market_open_causal",
    )
    # future_returns:仅作弊探针(FutureLeakProbe)读取的测试专用数据;
    # 正式策略与基线不读(纪律见 policies.py),泄漏由反作弊考试抓取。
    log_close = np.log(episode.df["close"].to_numpy(dtype=np.float64))
    future_returns = np.diff(log_close, prepend=log_close[0])

    obs, _ = env.reset(seed=episode.spec.seed)
    actions: list[int] = []
    equities: list[float] = []
    fees_total = 0.0
    trades = 0
    total_reward_raw = 0.0
    done = False
    while not done:
        ctx = ActContext(
            tick=env._current_tick, n_rows=env.n_rows,  # noqa: SLF001
            position=env._target_position,  # noqa: SLF001
            df=episode.df, hidden=episode.hidden,
            future_returns=future_returns,
        )
        action = int(policy.act(obs, ctx))
        obs, _reward, terminated, truncated, info = env.step(action)
        done = terminated or truncated
        actions.append(action)
        equities.append(float(info["equity_end"]))
        fees_total += float(info["fee_paid"])
        if info["trade_direction"] in ("buy", "sell"):
            trades += 1
        total_reward_raw += float(info["reward_raw"])

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
    result = EpisodeResult(
        spec=episode.spec,
        net_return=net_return,
        final_cash=final_cash,
        max_drawdown=max_dd,
        n_trades=trades,
        turnover_rate=switches / max(len(actions), 1),
        total_fees=fees_total,
        avg_position=n_long / max(len(actions), 1),
        avg_holding_bars=(
            float(np.mean(holding_segments)) if holding_segments else 0.0
        ),
        n_decisions=len(actions),
        actions_sha256=hashlib.sha256(actions_bytes).hexdigest(),
        actions_count={
            "0": len(actions) - n_long, "1": n_long,
        },
        family_version=episode.family_version,
        generator_fingerprint=episode.generator_fingerprint,
        reward_consistency_ok=reward_err < 1e-9,
        reward_abs_error=reward_err,
    )
    if return_actions:
        return result, actions
    return result


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
    policy: Policy,
    episodes: list[GeneratedEpisode],
    cfg: EvalConfig,
    *,
    baseline_policies: dict[str, Policy] | None = None,
    label: str | None = None,
) -> dict[str, Any]:
    """确定性评估一个策略;可选基线做逐 episode 配对差与 bootstrap。"""
    ordered = sorted(episodes, key=lambda e: e.spec.canonical())
    results = [run_episode(policy, e, cfg) for e in ordered]
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
        "eval_config": cfg.manifest(),
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
        },
        "episodes": [r.to_record() for r in results],
        "evaluator_code_hash": evaluator_code_hash(),
    }
    # 种子通过比例:逐 episode 优于 Always Flat
    flat_policy = AlwaysFlatPolicy()
    flat_results = {
        e.spec.canonical(): run_episode(flat_policy, e, cfg) for e in ordered
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
                e.spec.canonical(): run_episode(bpol, e, cfg) for e in ordered
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
