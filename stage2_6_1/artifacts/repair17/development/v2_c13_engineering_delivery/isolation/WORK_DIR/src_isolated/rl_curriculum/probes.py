"""阶段 2.6.0a 工作包 A4:测试专用作弊探针(独立 harness,不入正式接口)。

阶段 2.6.0 的作弊策略(StepCounter / AbsolutePrice / Periodic /
FutureLeak / NullOvertrader)与正式候选共用 Policy+ActContext 接口,
意味着"作弊能力"在正式接口上是合法可达的。本模块把它们全部迁移到
独立的 TestOnlyProbePolicy 协议:

- act(observation, harness_ctx) 双参签名,与 CandidatePolicy.act(observation)
  不同,不能被正式评估器调用(签名不符 + 类型拒绝);
- harness_ctx 是 TestHarnessContext,由 rl_curriculum.test_harness 构造,
  仅存在于测试/审计路径,正式候选评估器中不构造 future_returns、不传递
  hidden、不传递完整 Episode df;
- 正式评估入口(assert_formal_candidate)对 TestOnlyProbePolicy 一律拒绝。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd

from rl_curriculum.policy_api import TestOnlyProbePolicy


@dataclass
class TestHarnessContext:
    """测试专用单步上下文(仅测试 harness 构造;正式评估器不创建)。"""

    tick: int                       # 当前决策 bar(观察末行)
    n_rows: int                     # df 总行数
    position: int                   # 当前目标仓位(0/1)
    df: pd.DataFrame                # 完整 Episode df(探针审计用)
    hidden: pd.DataFrame | None     # 完整隐藏状态(探针审计用)
    future_returns: np.ndarray | None  # 测试专用未来收益(仅泄漏探针)


class StepCounterCheaterProbe(TestOnlyProbePolicy):
    """依赖 Episode 步数:在中段固定窗口做多(Episode 结构固定时得分)。

    Episode 长度随机化 / regime 顺序随机化后必然崩溃;
    反作弊系统必须在"原始成绩达到作弊判定门槛 + 长度反事实优势崩溃 +
    多 Episode 重复"三条件齐备时才标记 SUSPECTED_CHEATING(episode_position)。
    """

    name = "cheater_step_counter"

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        frac = ctx.tick / max(ctx.n_rows - 1, 1)
        return int(0.35 < frac < 0.65)


class AbsolutePriceCheaterProbe(TestOnlyProbePolicy):
    """依赖绝对价格阈值(初始价格 ~100 的课程中"低价区做多")。"""

    name = "cheater_absolute_price"

    def __init__(self, buy_below: float = 100.0):
        self.buy_below = float(buy_below)

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        return int(float(ctx.df["open"].iloc[ctx.tick]) < self.buy_below)


class PeriodicCheaterProbe(TestOnlyProbePolicy):
    """按固定时间间隔切换仓位(与市场内容无关的固定周期)。"""

    name = "cheater_periodic"

    def __init__(self, period: int = 6):
        if period < 1:
            raise ValueError(f"period 必须 >= 1,收到 {period}")
        self.period = int(period)
        self._step = 0

    def reset_episode(self) -> None:
        self._step = 0

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        k = self._step
        self._step += 1
        return int((k // self.period) % 2)


class FutureLeakProbe(TestOnlyProbePolicy):
    """读取测试专用 future_returns(模拟"错误 observation 含未来收益")。

    共同前缀测试(修改未来后缀不得改变共同前缀动作)与 observation
    字段审计必须发现它;它只在测试 harness 中获得 future_returns,
    正式候选评估器从不构造该数组——接口层根本不存在这条泄漏路径。
    """

    name = "cheater_future_leak"

    def __init__(self, fee_threshold: float = 0.001):
        self.fee_threshold = float(fee_threshold)

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        if ctx.future_returns is None:
            raise RuntimeError("FutureLeakProbe 需要测试专用 future_returns")
        nxt = ctx.tick + 1
        if nxt >= len(ctx.future_returns):
            return 0
        return int(float(ctx.future_returns[nxt]) > self.fee_threshold)


class NullOvertraderProbe(TestOnlyProbePolicy):
    """无信号环境中高频切换(NullOvertrader 行为形态)。

    正确判定是普通挂科(FAIL:高换手、扣费亏损),不是作弊高分。
    """

    name = "cheater_null_overtrader"

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        return 1 - int(ctx.position)


class OracleLikeHiddenReaderProbe(TestOnlyProbePolicy):
    """读隐藏当前行的探针(证明测试 harness 保有 Oracle 级审计能力)。

    与正式 OraclePolicy 等价的行为,但只能通过 TestHarnessContext
    (ctx.hidden)获得隐藏数据;正式候选接口(assert_formal_candidate)
    对其拒绝。
    """

    name = "probe_hidden_reader"

    def __init__(self):
        self.reads: str | None = None

    def act(self, observation: np.ndarray, ctx: TestHarnessContext) -> int:
        if ctx.hidden is None:
            raise RuntimeError("hidden_reader 需要测试 harness 的 hidden")
        self.reads = "hidden-ok"
        return int(float(ctx.hidden["regime_direction"].iloc[ctx.tick]) > 0)


# 阶段 2.6.0 旧名称的兼容别名(指向新 Probe 类型;测试套件统一改用
# 新名称,别名仅为迁移期提示)。
LEGACY_PROBE_ALIASES: dict[str, type[TestOnlyProbePolicy]] = {
    "StepCounterCheaterPolicy": StepCounterCheaterProbe,
    "AbsolutePriceCheaterPolicy": AbsolutePriceCheaterProbe,
    "PeriodicCheaterPolicy": PeriodicCheaterProbe,
    "FutureLeakProbePolicy": FutureLeakProbe,
    "NullOvertraderPolicy": NullOvertraderProbe,
}


def __getattr__(name: str) -> Any:  # 兼容旧导入名(带弃用提示)
    if name in LEGACY_PROBE_ALIASES:
        return LEGACY_PROBE_ALIASES[name]
    raise AttributeError(name)
