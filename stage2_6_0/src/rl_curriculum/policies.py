"""工作包 E + I:统一策略适配接口(基线策略库与故意作弊策略)。

评估器通过同一 act(obs, ctx) 接口运行:
- SB3 PPO checkpoint(SB3CheckpointPolicy,加载前执行版本守卫);
- Oracle(读取生成器隐藏状态;只用于课程可解性上限,永远不得作为
  模型训练输入);
- 可观察规则策略(只能使用模型同样可见的信息;验证题目是否给了
  学生足够信息);
- trivial / random 基线;
- 故意依赖捷径的作弊策略(StepCounter / AbsolutePrice / Periodic /
  FutureLeak / NullOvertrader)——用于证明反作弊系统有效。

合理的课程资格关系应为:
Oracle > 可观察规则策略 > trivial / random 策略。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd


@dataclass
class ActContext:
    """单步决策上下文(评估器提供;纪律由策略声明与审计保证)。"""

    tick: int                       # 当前决策 bar(观察末行)
    n_rows: int                     # df 总行数
    position: int                   # 当前目标仓位(0/1)
    df: pd.DataFrame                # 模型可见信息(价格 + 特征列)
    hidden: pd.DataFrame | None = None   # 生成器隐藏状态(仅 Oracle 读取)
    future_returns: np.ndarray | None = None  # 测试专用未来数据(仅作弊探针)


class Policy(ABC):
    """策略协议:deterministic act(obs, ctx) -> {0, 1}。"""

    name: str = "policy"
    reads_hidden: bool = False

    @abstractmethod
    def act(self, obs: np.ndarray, ctx: ActContext) -> int: ...


# ------------------------------------------------------------------ trivial
class AlwaysFlatPolicy(Policy):
    name = "always_flat"

    def act(self, obs, ctx):
        return 0


class AlwaysLongPolicy(Policy):
    name = "always_long"

    def act(self, obs, ctx):
        return 1


class RandomPolicy(Policy):
    name = "random"

    def __init__(self, seed: int = 0):
        self.rng = np.random.default_rng(seed)

    def act(self, obs, ctx):
        return int(self.rng.integers(0, 2))


class PeriodicTogglePolicy(Policy):
    name = "periodic_toggle"

    def __init__(self, period: int = 8):
        if period < 1:
            raise ValueError(f"period 必须 >= 1,收到 {period}")
        self.period = period

    def act(self, obs, ctx):
        return int((ctx.tick // self.period) % 2)


class OneStepGreedyPolicy(Policy):
    """上一根 bar 收益为正即做多(短视贪婪)。"""

    name = "one_step_greedy"

    def act(self, obs, ctx):
        return int(ctx.df["ret_1"].iloc[ctx.tick] > 0.0)


class HighTurnoverPolicy(Policy):
    """每步切换仓位(高频换手基线;亦是 NullOvertrader 的行为形态)。"""

    name = "high_turnover"

    def act(self, obs, ctx):
        return 1 - int(ctx.position)


# ------------------------------------------------------------- 规则 / Oracle
class RuleTrendPolicy(Policy):
    """可观察规则基线:只用模型同样可见的特征(无隐藏状态、无未来)。

    规则:ma_ratio > ma_threshold 且 ret_4 > ret_threshold 时做多。
    阈值在课程章程中冻结,不得依据 PPO 表现调整。
    """

    name = "rule_trend"

    def __init__(self, ma_threshold: float = 0.001, ret_threshold: float = 0.0):
        self.ma_threshold = float(ma_threshold)
        self.ret_threshold = float(ret_threshold)

    def act(self, obs, ctx):
        row = ctx.df.iloc[ctx.tick]
        return int(
            row["ma_ratio"] > self.ma_threshold and row["ret_4"] > self.ret_threshold
        )


class OracleSegmentedDriftPolicy(Policy):
    """探针 A 的 Oracle:读隐藏 regime 方向(仅课程可解性上限)。"""

    name = "oracle_segmented_drift"
    reads_hidden = True

    def act(self, obs, ctx):
        if ctx.hidden is None:
            raise RuntimeError("Oracle 需要生成器隐藏状态(评估器未提供)")
        return int(ctx.hidden["regime_direction"].iloc[ctx.tick] > 0)


class OracleSmoothLatentDriftPolicy(Policy):
    """探针 B 的 Oracle:读连续潜在漂移(仅课程可解性上限)。"""

    name = "oracle_smooth_latent_drift"
    reads_hidden = True

    def __init__(self, threshold_bps: float = 3.0):
        self.threshold_bps = float(threshold_bps)

    def act(self, obs, ctx):
        if ctx.hidden is None:
            raise RuntimeError("Oracle 需要生成器隐藏状态(评估器未提供)")
        return int(ctx.hidden["latent_drift_bps"].iloc[ctx.tick] > self.threshold_bps)


# ------------------------------------------------------------ 故意作弊策略
class StepCounterCheaterPolicy(Policy):
    """依赖 Episode 步数:在中段固定窗口做多(当 Episode 结构固定时得分)。

    Episode 长度随机化 / regime 顺序随机化后必然崩溃,
    审计器必须将其标记为 SUSPECTED_CHEATING(episode_position)。
    """

    name = "cheater_step_counter"

    def act(self, obs, ctx):
        frac = ctx.tick / max(ctx.n_rows - 1, 1)
        return int(0.35 < frac < 0.65)


class AbsolutePriceCheaterPolicy(Policy):
    """依赖绝对价格阈值(初始价格 ~100 的课程中"低价区做多")。

    价格尺度变化(×0.1/×10/×100)后行为完全改变,
    被价格尺度不变性测试发现 -> SUSPECTED_CHEATING(absolute_price)。
    """

    name = "cheater_absolute_price"

    def __init__(self, buy_below: float = 100.0):
        self.buy_below = float(buy_below)

    def act(self, obs, ctx):
        return int(ctx.df["open"].iloc[ctx.tick] < self.buy_below)


class PeriodicCheaterPolicy(Policy):
    """按固定时间间隔切换仓位(与 PeriodicToggle 同行为,作弊语义)。

    regime 顺序随机化 / 时间平移后失效 ->
    SUSPECTED_CHEATING(periodic_pattern)。
    """

    name = "cheater_periodic"

    def __init__(self, period: int = 6):
        self.period = int(period)

    def act(self, obs, ctx):
        return int((ctx.tick // self.period) % 2)


class FutureLeakProbePolicy(Policy):
    """读取 observation 中的未来字段(测试专用,绝不能进入正式训练代码)。

    模拟"错误 observation 含未来收益"的泄漏环境中的策略:
    下一步收益大于费用阈值即做多。共同前缀测试(修改未来后缀不得改变
    共同前缀动作)与 observation 字段审计必须发现它 ->
    SUSPECTED_CHEATING(future_leak)。
    """

    name = "cheater_future_leak"

    def __init__(self, fee_threshold: float = 0.001):
        self.fee_threshold = float(fee_threshold)

    def act(self, obs, ctx):
        if ctx.future_returns is None:
            raise RuntimeError("FutureLeakProbe 需要测试专用 future_returns")
        nxt = ctx.tick + 1
        if nxt >= len(ctx.future_returns):
            return 0
        return int(float(ctx.future_returns[nxt]) > self.fee_threshold)


class NullOvertraderPolicy(Policy):
    """无信号环境中高频切换(与 HighTurnover 同行为,作弊语义)。

    Null Control 审计必须判定其:高换手、扣费亏损、Null Control 挂科。
    """

    name = "cheater_null_overtrader"

    def act(self, obs, ctx):
        return 1 - int(ctx.position)


# ------------------------------------------------------------- SB3 checkpoint
class SB3CheckpointPolicy(Policy):
    """SB3 PPO checkpoint 适配(deterministic predict)。

    加载即执行 checkpoint 兼容守卫(rl_curriculum.checkpoints):
    sidecar manifest 必须存在且环境/观察/动作版本匹配;声明了
    charter_hash 时也必须匹配。不兼容 checkpoint 拒绝加载。
    """

    name = "sb3_checkpoint"

    def __init__(
        self,
        checkpoint_path,
        *,
        expected_charter_hash: str | None = None,
        device: str = "cpu",
    ):
        from rl_curriculum.checkpoints import load_guarded_checkpoint

        self.checkpoint_path = str(checkpoint_path)
        self.model, self.manifest = load_guarded_checkpoint(
            checkpoint_path, expected_charter_hash=expected_charter_hash
        )
        self.device = device
        self.name = f"sb3:{self.manifest.get('checkpoint_name', self.name)}"

    def act(self, obs, ctx):
        action, _ = self.model.predict(
            np.asarray(obs, dtype=np.float32).reshape(1, -1), deterministic=True
        )
        return int(np.asarray(action).reshape(-1)[0])
