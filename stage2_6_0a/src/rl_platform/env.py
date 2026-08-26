"""对齐的 Long/Flat Gymnasium 环境(阶段 2.5 路线 C 核心,2.5.1/2.5.2/2.5.2a 加固)。

时间语义(阶段 2.5.2a 任务书第一节冻结的 market_open_causal):
    K 线 t 已收盘
    -> 模型观察含行 t 的特征窗口 [t-w+1, t] + 当前目标仓位
    -> 输出目标仓位 action ∈ {0, 1}
    -> 在 open[t+1] 以因果市场成交价执行仓位变化
       (买入 ceil_to_tick、卖出 floor_to_tick;只依赖 open[t+1]、方向、
        simulated_slippage_bps、price_tick、fee;不依赖 high/low)
    -> 新仓位承担 open[t+1] -> close[t+1]
    -> 期末净值 E[t+1],奖励 r = reward_scale * log(E[t+1] / E[t])

Episode 终端(阶段 2.5.2a 工作包 C):
- 最后一个执行周期结束于 close[last]:先以 close[last] 计净清算价值,
  再使用与普通市场卖出完全相同的 simulated_slippage_bps、tick 取整、
  卖出手续费完成清算,最终全部为现金;
- 清算发生在最后一根 K 线收盘后,最后一根 K 线内的持仓仍承担
  open -> close 收益;不存在"持有到 Episode 结束可以免滑点"的漏洞;
- reward telescoping:sum(reward_raw) == log(final_cash / initial_cash)。

数据共 N 根时,决策 t 最大到 N-2(执行/清算发生在 bar N-1),
观察末行永远不含 bar N-1。

阶段 2.5.2a 起 market_open_causal 是默认且唯一的生产执行模式;
legacy_noncausal_not_for_training(阶段 2.5.2 bar 内调价合同,依赖
执行 K 线最终 high/low,非因果)仅供历史回归测试显式选择。

不继承 Freqtrade 的 BaseEnvironment/Base3ActionRLEnv:
step 时间推进、观察区间、记账、奖励、终端逻辑全部按上述语义重新实现。

阶段 2.6.0 工作包 0 冻结:RouteCEnvCore-v1.0.0(ObservationSpec-v1 /
BinaryLongFlatAction-v1 / NetLogEquityReward-v1 /
MarketOpenCausalExecution-v1 / TerminalLiquidation-v1);
终端清算后 observation 仓位字段 = 0,info 保留 requested_target_position /
actual_position_after_liquidation / terminal_liquidation。
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd

from rl_platform.market_execution import (
    EXECUTION_MODE,
    LEGACY_EXECUTION_MODE,
    VALID_EXECUTION_MODES,
)
from rl_platform.versions import (  # 阶段 2.6.0 工作包 0:冻结版本
    ACTION_SPEC_VERSION,
    ENV_CORE_VERSION,
    OBSERVATION_SPEC_VERSION,
    REWARD_SPEC_VERSION,
)


class AlignedLongFlatEnv(gym.Env):
    """观察含当前目标仓位的目标仓位环境(Discrete(2),Long/Flat 现货)。

    参数:
        features: 已缩放特征矩阵(DataFrame 或 2D array),行与 prices 逐行对齐;
        prices:   价格 DataFrame;market_open_causal 只要求 open/close 列
                  (high/low 不参与成交,可省略);legacy 模式要求四列;
        fee:      单边手续费率;
        slippage_bps: 确定性模拟滑点(基点,模拟环境专用,
                  = 配置键 freqai.route_c.simulated_slippage_bps);
        initial_cash: 期初现金;
        reward_scale: 奖励固定缩放常数(写入配置;info 同时保留原始值);
        window_size:  观察特征窗口行数(含当前行;阶段 2.5.1 仅验证 1);
        dates:     可选时间戳序列(仅用于 info 诊断,不参与计算);
        price_tick:  价格精度 tick(方向不利取整用;0 = 不量化);
        execution_mode: market_open_causal(默认)或
                  legacy_noncausal_not_for_training(仅历史测试)。
    """

    metadata: dict[str, Any] = {"render_modes": []}
    # 冻结规范版本(阶段 2.6.0 工作包 0);供 checkpoint 守卫与 manifest 校验
    env_core_version = ENV_CORE_VERSION
    observation_spec_version = OBSERVATION_SPEC_VERSION
    action_spec_version = ACTION_SPEC_VERSION
    reward_spec_version = REWARD_SPEC_VERSION
    # 上游 TensorboardCallback 会读取 env.unwrapped.tensorboard_metrics(字典套字典);
    # 阶段 2.5 不依赖它,保持空字典以防 AttributeError。
    tensorboard_metrics: dict[str, dict[str, float]] = {}

    def __init__(
        self,
        features: pd.DataFrame | np.ndarray,
        prices: pd.DataFrame,
        fee: float = 0.001,
        slippage_bps: float = 0.0,
        initial_cash: float = 100.0,
        reward_scale: float = 1.0,
        window_size: int = 1,
        dates: pd.Timestamp | None = None,
        price_tick: float = 0.0,
        execution_mode: str = EXECUTION_MODE,
    ) -> None:
        super().__init__()
        from rl_platform.ledger import LongFlatLedger

        if execution_mode not in VALID_EXECUTION_MODES:
            raise ValueError(
                f"execution_mode 必须是 {VALID_EXECUTION_MODES} 之一,收到 {execution_mode!r}"
            )
        self.execution_mode = execution_mode
        if isinstance(features, pd.DataFrame):
            self.feature_names = list(features.columns)
            self._features = features.to_numpy(dtype=np.float64)
        else:
            self.feature_names = [f"f{i}" for i in range(features.shape[1])]
            self._features = np.asarray(features, dtype=np.float64)
        # market_open_causal:high/low 不参与成交(因果),仅 open/close 必需;
        # legacy 模式保留阶段 2.5.1 的四列要求(bar 内调价合同)。
        required = ["open", "close"] if execution_mode == EXECUTION_MODE else \
            ["open", "high", "low", "close"]
        missing_cols = [c for c in required if c not in prices.columns]
        if missing_cols:
            raise ValueError(
                f"prices 缺少列 {missing_cols}:execution_mode={execution_mode}"
            )
        self._open = prices["open"].to_numpy(dtype=np.float64)
        self._close = prices["close"].to_numpy(dtype=np.float64)
        self._high = (
            prices["high"].to_numpy(dtype=np.float64) if "high" in prices.columns else None
        )
        self._low = (
            prices["low"].to_numpy(dtype=np.float64) if "low" in prices.columns else None
        )
        n = len(self._open)
        if len(self._features) != n:
            raise ValueError(f"features 行数 {len(self._features)} 与 prices 行数 {n} 不一致")
        if window_size < 1:
            raise ValueError("window_size 必须 >= 1")
        # 至少需要:window_size 行观察 + 1 根最终执行 bar
        if n < window_size + 1:
            raise ValueError(f"数据行数 {n} 不足以支撑 window_size={window_size} 的决策与执行")
        self.window_size = window_size
        self.n_rows = n
        self.fee = float(fee)
        self.slippage_bps = float(slippage_bps)
        self.price_tick = float(price_tick)
        self.initial_cash = float(initial_cash)
        self.reward_scale = float(reward_scale)
        self._dates = dates
        # 决策 bar: t ∈ [window_size-1, n-2];执行 bar: t+1 ∈ [window_size, n-1]
        self.first_decision_tick = window_size - 1
        self.last_decision_tick = n - 2

        n_feat = self._features.shape[1]
        self.observation_space = gym.spaces.Box(
            low=-10.0, high=10.0, shape=(n_feat * window_size + 1,), dtype=np.float32
        )
        self.action_space = gym.spaces.Discrete(2)

        self.ledger = LongFlatLedger(
            initial_cash=self.initial_cash, fee=self.fee,
            slippage_bps=self.slippage_bps, price_tick=self.price_tick,
            execution_mode=self.execution_mode,
        )
        self._current_tick = self.first_decision_tick
        self._target_position = 0
        self._last_info: dict[str, Any] | None = None
        self.episode_reward_raw = 0.0
        self.episode_reward_scaled = 0.0
        # PPO 训练预算审计用:episode reset 计数(工作包 A)
        self.episode_reset_count = 0

    # ------------------------------------------------------------------ utils
    def _date_of(self, tick: int) -> pd.Timestamp | None:
        if self._dates is not None:
            return self._dates[tick]
        return None

    def _observation(self, tick: int, position: int) -> np.ndarray:
        window = self._features[tick - self.window_size + 1 : tick + 1]
        obs = np.concatenate([window.ravel(), [float(position)]]).astype(np.float32)
        return obs

    def get_observation(self) -> np.ndarray:
        """供顺序推理与外部脚本使用的当前观察(含当前目标仓位)。"""
        return self._observation(self._current_tick, self._target_position)

    # ------------------------------------------------------------ gymnasium API
    def reset(
        self, *, seed: int | None = None, options: dict | None = None
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self.episode_reset_count += 1
        self.ledger.reset()
        self._current_tick = self.first_decision_tick
        self._target_position = 0
        self.episode_reward_raw = 0.0
        self.episode_reward_scaled = 0.0
        self._last_info = {
            "decision_tick": self._current_tick, "reset": True,
        }
        return self.get_observation(), dict(self._last_info)

    def step(
        self, action: int
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        action = int(action)
        if action not in (0, 1):
            raise ValueError(f"非法动作 {action}:目标仓位环境只有 0/1")

        t = self._current_tick
        exec_tick = t + 1
        raw_open = self._open[exec_tick]
        exec_close = self._close[exec_tick]

        prev_target = self._target_position
        equity_start = self.ledger.equity(self._close[t])

        if self.execution_mode == EXECUTION_MODE:
            # market_open_causal:成交不接触执行 bar 的 high/low(因果)
            trade = self.ledger.apply_target(action, raw_open)
        else:
            # legacy_noncausal_not_for_training:仅供历史回归测试
            exec_high = None if self._high is None else self._high[exec_tick]
            exec_low = None if self._low is None else self._low[exec_tick]
            trade = self.ledger.apply_target_legacy(
                action, raw_open, high=exec_high, low=exec_low
            )

        terminated = exec_tick == self.n_rows - 1
        liquidation = None
        if terminated:
            # 阶段 2.5.2a 工作包 C:清算基准价 = close[last],清算发生在
            # 最后一根 K 线收盘后,支付与普通市场卖出完全相同的成本;
            # 清算后全部为现金 -> equity_end = final_cash(telescoping 闭环)。
            if self.execution_mode == EXECUTION_MODE:
                liquidation = self.ledger.liquidate(exec_close)
            else:
                liquidation = self.ledger.liquidate_legacy(raw_open)

        equity_end = self.ledger.equity(exec_close)
        if equity_start <= 0 or equity_end <= 0:
            raise FloatingPointError(
                f"净值非正(E_start={equity_start}, E_end={equity_end}),log 奖励未定义"
            )
        reward_raw = float(np.log(equity_end / equity_start))
        reward = self.reward_scale * reward_raw
        self.episode_reward_raw += reward_raw
        self.episode_reward_scaled += reward

        self._target_position = action
        self._current_tick = exec_tick
        # 阶段 2.6.0 工作包 0:终端强制清算后账本实际仓位 = 0,
        # 终端 observation 的仓位字段必须为 0,不得继续显示已不存在的
        # 多头仓位;模型最后请求的目标保留在 info.requested_target_position。
        actual_position = action
        if terminated:
            actual_position = 0
            self._target_position = 0

        info: dict[str, Any] = {
            "decision_tick": t,
            "execution_tick": exec_tick,
            "decision_time": self._date_of(t),
            "execution_time": self._date_of(exec_tick),
            "action": action,
            "prev_target_position": prev_target,
            "new_target_position": action,
            "actual_position": actual_position,
            "execution_mode": self.execution_mode,
            "trade_direction": trade.direction,
            "raw_open": raw_open,
            "exec_price": trade.exec_price,
            "requested_price": trade.requested_price,
            "requested_slippage_bps": self.slippage_bps,
            "actual_effective_slippage_bps": trade.actual_effective_slippage_bps,
            "tick_rounding": trade.tick_rounding,
            "fee": self.fee,
            "price_clamped": trade.price_clamped,
            "price_moved_inside": trade.price_moved_inside,
            "price_fallback": trade.price_fallback,
            "fee_paid": trade.fee_paid,
            "notional": trade.notional,
            "qty": trade.qty,
            "slippage_cost": trade.slippage_cost,
            "cash": self.ledger.cash,
            "btc": self.ledger.btc,
            "equity_start": equity_start,
            "equity_end": equity_end,
            "unrealized_pnl": self.ledger.unrealized_pnl(exec_close),
            "realized_pnl": self.ledger.realized_pnl,
            "reward_raw": reward_raw,
            "reward_scaled": reward,
            "episode_reward_raw": self.episode_reward_raw,
            "terminated": terminated,
            "truncated": False,
        }
        if terminated:
            # 阶段 2.6.0 工作包 0:终端 info 分别保留模型最后请求的目标、
            # 清算后的实际仓位(恒 0)与完整清算诊断 terminal_liquidation。
            info["requested_target_position"] = action
            info["actual_position_after_liquidation"] = int(self.ledger.btc > 0)
        if liquidation is not None and liquidation.direction == "liquidate":
            info["terminal_liquidation"] = {
                "direction": "liquidate",
                "reference_price": liquidation.raw_open,
                "raw_open": liquidation.raw_open,
                "exec_price": liquidation.exec_price,
                "requested_price": liquidation.requested_price,
                "fee_paid": liquidation.fee_paid,
                "qty": liquidation.qty,
                "notional": liquidation.notional,
                "slippage_cost": liquidation.slippage_cost,
                "tick_rounding": liquidation.tick_rounding,
                "actual_effective_slippage_bps": liquidation.actual_effective_slippage_bps,
            }
        self._last_info = info
        obs = self._observation(exec_tick, self._target_position)
        return obs, float(reward), terminated, False, info

    def render(self):  # pragma: no cover - 阶段 2.5 不使用
        return None
