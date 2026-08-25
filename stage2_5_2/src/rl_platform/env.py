"""对齐的 Long/Flat Gymnasium 环境(阶段 2.5 路线 C 核心,2.5.1/2.5.2 加固)。

时间语义(任务书第五节,与 Freqtrade 回测"信息截至 t -> open[t+1] 成交"一致):

    K 线 t 已收盘
    -> 模型观察含行 t 的特征窗口 [t-w+1, t] + 当前目标仓位
    -> 输出目标仓位 action ∈ {0, 1}
    -> 在 open[t+1] 执行仓位变化(含滑点/手续费)
    -> 新仓位承担 open[t+1] -> close[t+1]
    -> 期末净值 E[t+1],奖励 r = reward_scale * log(E[t+1] / E[t])

Episode 终端(任务书第九节):预留最后一根 bar 作为"不进入模型观察的最终执行 bar"。
数据共 N 根时,决策 t 最大到 N-2(执行/清算发生在 open[N-1]),观察末行永远不含
bar N-1。terminated 时若仍持多头,在 open[N-1] 强制清仓(无滑点、扣手续费,
与 Freqtrade 回测器 handle_left_open 同口径,阶段 2.5.1 修正)。

阶段 2.5.1 加固(工作包 C):
- prices 必须提供执行 bar 的 open/high/low/close;成交价被限制在当根
  high/low 内(镜像 Freqtrade 对 custom price 的 clamp)。

阶段 2.5.2 加固(工作包 D 执行合同):
- price_tick > 0 时,成交价由 price_clamp.bar_executable_price 决定:
  请求滑点价触及当根边界时按 tick 向 bar 内部移动,保证与回测器
  闭区间撮合语义下「下单当根成交」完全一致;bar 容纳不下时 fallback open。
  info 记录 price_moved_inside / price_fallback 供证据核对。

不继承 Freqtrade 的 BaseEnvironment/Base3ActionRLEnv:
step 时间推进、观察区间、记账、奖励、终端逻辑全部按上述语义重新实现。
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd


class AlignedLongFlatEnv(gym.Env):
    """观察含当前目标仓位的目标仓位环境(Discrete(2),Long/Flat 现货)。

    参数:
        features: 已缩放特征矩阵(DataFrame 或 2D array),行与 prices 逐行对齐;
        prices:   含 open/high/low/close 四列的 DataFrame(原始价格,未缩放);
        fee:      单边手续费率;
        slippage_bps: 确定性滑点(基点);
        price_tick:  价格精度 tick(阶段 2.5.2 执行合同;0 = 旧边界 clamp 语义);
        initial_cash: 期初现金;
        reward_scale: 奖励固定缩放常数(写入配置;info 同时保留原始值);
        window_size:  观察特征窗口行数(含当前行;阶段 2.5.1 仅验证 1);
        dates:     可选时间戳序列(仅用于 info 诊断,不参与计算)。
    """

    metadata: dict[str, Any] = {"render_modes": []}
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
    ) -> None:
        super().__init__()
        from rl_platform.ledger import LongFlatLedger

        if isinstance(features, pd.DataFrame):
            self.feature_names = list(features.columns)
            self._features = features.to_numpy(dtype=np.float64)
        else:
            self.feature_names = [f"f{i}" for i in range(features.shape[1])]
            self._features = np.asarray(features, dtype=np.float64)
        missing_cols = [c for c in ("open", "high", "low", "close") if c not in prices.columns]
        if missing_cols:
            raise ValueError(
                f"prices 缺少列 {missing_cols}:工作包 C 要求执行 bar 的 high/low "
                "参与价格限制,生产路径必须提供四列"
            )
        self._open = prices["open"].to_numpy(dtype=np.float64)
        self._high = prices["high"].to_numpy(dtype=np.float64)
        self._low = prices["low"].to_numpy(dtype=np.float64)
        self._close = prices["close"].to_numpy(dtype=np.float64)
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
        exec_high = self._high[exec_tick]
        exec_low = self._low[exec_tick]

        prev_target = self._target_position
        equity_start = self.ledger.equity(self._close[t])

        trade = self.ledger.apply_target(action, raw_open, high=exec_high, low=exec_low)

        terminated = exec_tick == self.n_rows - 1
        liquidation = None
        if terminated:
            liquidation = self.ledger.liquidate(raw_open)

        equity_end = self.ledger.equity(self._close[exec_tick])
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

        info: dict[str, Any] = {
            "decision_tick": t,
            "execution_tick": exec_tick,
            "decision_time": self._date_of(t),
            "execution_time": self._date_of(exec_tick),
            "action": action,
            "prev_target_position": prev_target,
            "new_target_position": action,
            "trade_direction": trade.direction,
            "raw_open": raw_open,
            "exec_price": trade.exec_price,
            "requested_price": trade.requested_price,
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
            "unrealized_pnl": self.ledger.unrealized_pnl(self._close[exec_tick]),
            "realized_pnl": self.ledger.realized_pnl,
            "reward_raw": reward_raw,
            "reward_scaled": reward,
            "episode_reward_raw": self.episode_reward_raw,
            "terminated": terminated,
            "truncated": False,
        }
        if liquidation is not None and liquidation.direction == "liquidate":
            info["terminal_liquidation"] = {
                "direction": "liquidate",
                "raw_open": liquidation.raw_open,
                "exec_price": liquidation.exec_price,
                "fee_paid": liquidation.fee_paid,
                "qty": liquidation.qty,
                "notional": liquidation.notional,
            }
        self._last_info = info
        obs = self._observation(exec_tick, self._target_position)
        return obs, float(reward), terminated, False, info

    def render(self):  # pragma: no cover - 阶段 2.5 不使用
        return None
