# -*- coding: utf-8 -*-
"""双向连续仓位 + HOLD 混合动作环境(RouteC_PositionControl W1)。

动作(HybridHoldRebalanceAction-v1):二元组 (branch, w)
- branch=0:HOLD(观望/继续持有),w 忽略(必须为 0 值占位,传非 0
  视为编码错误拒绝);
- branch=1:REBALANCE(w),w∈[-1,1] 为目标名义敞口比例(相对扣费后
  净值;正=多头,负=空头,0=清仓);
- 非法输入(branch∉{0,1}/w 非有限/越界/branch=1 时 w 缺失)显式
  ValueError 拒绝,绝不静默转 HOLD/0。

时间因果(PosctlEnvCore-v1):
  观察 = 截至 close[t] 的特征窗口 + 账户状态(敞口比例/偿付余量)
  -> 执行在 open[t+1](统一标记价 = 原始 open[t+1];
     成交价另按方向加不利滑点/tick 取整)
  -> 旧数量承担 close[t]->open[t+1] 跳空;新数量承担
     open[t+1]->close[t+1];
  -> 若 t+1 ∈ 资金费计划:在 close[t+1] 按标记结算(方向正确);
  -> 维持保证金风险检查(close[t+1]):|qty|*close>0 且
     equity < maintenance_margin*|qty|*close 时风险规则一次性全额
     平仓(risk action,区别于模型动作,同样支付全部摩擦);
  -> 终端(t+1 = 最后一根):清算以 close[last] 为参考价,与普通
     平仓完全相同的滑点/取整/费用;HOLD 不能阻止清算/费用/资金费。

奖励(NetLogEquityReward-v2):reward_raw = log(E_end/E_start),
E_start=equity(close[t]),E_end=equity(close[t+1])(含一切损益/费用/
资金费/清算)。无任何附加持仓/空仓/HOLD/回撤奖惩项。E_end<=0 时
log 未定义:显式经济失败终结(terminated=True,info.economic_failure,
info.reward_valid=False;reward 数值 0.0 仅作占位,训练 harness 必须
检测该标志并判运行无效,不得让该步参与学习)。

自融资 telescoping(无失败时):sum(reward_raw) == log(final_cash/E0)。

观察(PosctlObs-v1):window_size 行特征(平铺) + [exposure_ratio,
solvency_ratio](close[t] 口径;HOLD 漂移致 |exposure|>1 不截断;
空仓 solvency=+inf 以一个大常数有限值表示是为了 Box 观察的数值
稳定,info 内保留真实 inf 语义标注)。
"""

from __future__ import annotations

import math
from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd

from rl_posctl.ledger import TwoSidedLinearLedger
from rl_posctl.versions import (
    POSCTL_ACCOUNT_FEATURES,
    POSCTL_ACTION_SPEC_VERSION,
    POSCTL_ENV_CORE_VERSION,
    POSCTL_EXECUTION_SPEC_VERSION,
    POSCTL_LEDGER_VERSION,
    POSCTL_OBSERVATION_SPEC_VERSION,
    POSCTL_REWARD_SPEC_VERSION,
)

# 空仓偿付比例的有限表示(Box 观察);info 里同时保留 raw(=inf)。
FLAT_SOLVENCY_OBS = 1e6


class HybridPositionEnv(gym.Env):
    """HOLD/REBALANCE(w) 双向部分持仓环境(现金结算线性合约研究仿真)。

    参数:
        features: 已缩放特征矩阵(DataFrame/2D array),与 prices 对齐;
        prices:   至少含 open/close 列(high/low 不参与成交);
        fee:      单边手续费率(按实际成交名义量计);
        slippage_bps: 确定性模拟滑点(基点,方向不利);
        price_tick:  成交价方向不利取整 tick(0=不量化);
        initial_cash: 期初净值;
        reward_scale: 奖励缩放常数(info 保留原始值);
        window_size:  观察特征窗口行数;
        funding_schedule: {bar_index: rate} 预定资金费(None=无资金费,
            如实记录 funding_missing=True,不冒充真实零成本研究);
        maintenance_margin: 维持保证金比例(风险规则参数,profile 固定);
    """

    metadata: dict[str, Any] = {"render_modes": []}
    env_core_version = POSCTL_ENV_CORE_VERSION
    observation_spec_version = POSCTL_OBSERVATION_SPEC_VERSION
    action_spec_version = POSCTL_ACTION_SPEC_VERSION
    reward_spec_version = POSCTL_REWARD_SPEC_VERSION
    execution_spec_version = POSCTL_EXECUTION_SPEC_VERSION
    ledger_version = POSCTL_LEDGER_VERSION

    def __init__(
        self,
        features: pd.DataFrame | np.ndarray,
        prices: pd.DataFrame,
        fee: float = 0.001,
        slippage_bps: float = 0.0,
        initial_cash: float = 100.0,
        reward_scale: float = 1.0,
        window_size: int = 1,
        funding_schedule: dict[int, float] | None = None,
        maintenance_margin: float = 0.05,
        price_tick: float = 0.0,
        dates: pd.Timestamp | None = None,
    ) -> None:
        super().__init__()
        if isinstance(features, pd.DataFrame):
            self.feature_names = list(features.columns)
            self._features = features.to_numpy(dtype=np.float64)
        else:
            self.feature_names = [
                f"f{i}" for i in range(features.shape[1])]
            self._features = np.asarray(features, dtype=np.float64)
        missing = [c for c in ("open", "close") if c not in prices.columns]
        if missing:
            raise ValueError(f"prices 缺列 {missing}")
        self._open = prices["open"].to_numpy(dtype=np.float64)
        self._close = prices["close"].to_numpy(dtype=np.float64)
        n = len(self._open)
        if len(self._features) != n:
            raise ValueError("features/prices 行数不一致")
        if window_size < 1 or n < window_size + 1:
            raise ValueError("数据不足(window_size+1)")
        if maintenance_margin <= 0.0:
            raise ValueError("maintenance_margin 必须 >0")
        self.window_size = int(window_size)
        self.n_rows = n
        self.fee = float(fee)
        self.slippage_bps = float(slippage_bps)
        self.price_tick = float(price_tick)
        self.initial_cash = float(initial_cash)
        self.reward_scale = float(reward_scale)
        self.funding_schedule = {
            int(k): float(v) for k, v in (
                funding_schedule or {}).items()}
        self.funding_missing = funding_schedule is None
        self.maintenance_margin = float(maintenance_margin)
        self._dates = dates
        self.first_decision_tick = self.window_size - 1
        self.last_decision_tick = n - 2

        n_feat = self._features.shape[1]
        self.n_account_features = len(POSCTL_ACCOUNT_FEATURES)
        self.observation_space = gym.spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(n_feat * self.window_size + self.n_account_features,),
            dtype=np.float32)
        # 混合动作的扁平编码面:[branch, w](branch∈{0,1},w∈[-1,1]);
        # 本 Box 仅是缓冲编码容器,环境 step 对 branch 做精确 0/1 校验。
        self.action_space = gym.spaces.Box(
            low=np.array([0.0, -1.0]), high=np.array([1.0, 1.0]),
            dtype=np.float32)
        self.ledger = TwoSidedLinearLedger(
            initial_cash=self.initial_cash, fee_rate=self.fee,
            slippage_bps=self.slippage_bps, price_tick=self.price_tick)
        self._current_tick = self.first_decision_tick
        self._last_info: dict[str, Any] | None = None
        self.episode_reward_raw: float | None = 0.0
        self.episode_reward_scaled: float | None = 0.0
        self.episode_reset_count = 0
        self.step_records: list[dict[str, Any]] = []
        self.economic_failure: dict[str, Any] | None = None

    # ------------------------------------------------------------ utils
    def _account_features(self, price: float) -> list[float]:
        e = self.ledger.equity(price)
        if e > 0.0:
            exposure = self.ledger.exposure_ratio(price)
            solv = self.ledger.solvency_ratio(price)
        else:
            exposure, solv = 0.0, 0.0
        return [float(exposure),
                float(solv if math.isfinite(solv) else FLAT_SOLVENCY_OBS)]

    def _observation(self, tick: int) -> np.ndarray:
        window = self._features[tick - self.window_size + 1: tick + 1]
        parts = [window.ravel(),
                 np.asarray(self._account_features(self._close[tick]))]
        return np.concatenate(parts).astype(np.float32)

    def get_observation(self) -> np.ndarray:
        return self._observation(self._current_tick)

    # --------------------------------------------------- action decoding
    @staticmethod
    def decode_action(action) -> tuple[int, float]:
        """扁平 [branch, w] -> (branch, w)。非法显式拒绝。"""
        arr = np.asarray(action, dtype=np.float64).ravel()
        if arr.shape != (2,):
            raise ValueError(
                f"动作形状非法 {arr.shape}:必须为 (branch, w) 二元组")
        branch_raw, w = float(arr[0]), float(arr[1])
        if branch_raw == 0.0:
            if w != 0.0:
                raise ValueError(
                    f"HOLD 分支的 w 占位必须为 0,收到 {w!r}(编码错误"
                    "不得静默忽略)")
            return 0, 0.0
        if branch_raw == 1.0:
            if not (math.isfinite(w) and -1.0 <= w <= 1.0):
                raise ValueError(
                    f"非法目标比例 {w!r}:必须为 [-1,1] 内有限数")
            return 1, w
        raise ValueError(
            f"非法动作分支 {branch_raw!r}:必须精确为 0(HOLD)或"
            " 1(REBALANCE)")

    # ------------------------------------------------------ gymnasium API
    def reset(self, *, seed: int | None = None,
              options: dict | None = None):
        super().reset(seed=seed)
        self.episode_reset_count += 1
        self.ledger.reset()
        self._current_tick = self.first_decision_tick
        self.episode_reward_raw = 0.0
        self.episode_reward_scaled = 0.0
        self.step_records = []
        self.economic_failure = None
        self._last_info = {"decision_tick": self._current_tick,
                           "reset": True}
        return self.get_observation(), dict(self._last_info)

    def step(self, action):
        if self.economic_failure is not None:
            raise RuntimeError("经济失败后环境已终结,不得继续 step")
        branch, w = self.decode_action(action)
        t = self._current_tick
        exec_tick = t + 1
        raw_open = self._open[exec_tick]
        exec_close = self._close[exec_tick]
        equity_start = self.ledger.equity(self._close[t])

        # 1) 执行模型动作(open[t+1];HOLD 不交易)
        if branch == 1:
            fill = self.ledger.apply_target_ratio(w, raw_open)
        else:
            fill = self.ledger.hold(raw_open)

        # 2) 资金费(t+1 ∈ 计划,按 close[t+1] 标记)
        funding_payment = 0.0
        if exec_tick in self.funding_schedule:
            rate = self.funding_schedule[exec_tick]
            funding_payment = self.ledger.settle_funding(
                exec_close, rate)

        # 3) 风险规则 / 终端清算
        risk_action = None
        liquidation = None
        terminated = exec_tick == self.n_rows - 1
        notional_close = abs(self.ledger.qty) * exec_close
        if not terminated and notional_close > 0.0:
            e_at_close = self.ledger.equity(exec_close)
            if e_at_close < self.maintenance_margin * notional_close:
                risk_action = self.ledger.risk_flatten(exec_close)
        elif terminated:
            liquidation = self.ledger.liquidate(exec_close)

        equity_end = self.ledger.equity(exec_close)

        # 4) 奖励与失败判定
        reward_valid = True
        if equity_start <= 0.0 or equity_end <= 0.0:
            reason = (
                f"非正净值(E_start={equity_start!r},"
                f"E_end={equity_end!r}):log 奖励未定义;"
                f"tick={t}->{exec_tick}")
            self.economic_failure = {
                "reason": reason, "decision_tick": t,
                "execution_tick": exec_tick,
                "equity_start": equity_start, "equity_end": equity_end,
                "action": [branch, w]}
            reward_raw = None
            reward = 0.0
            reward_valid = False
            self.episode_reward_raw = None
            self.episode_reward_scaled = None
            terminated = True   # 显式经济失败终结(不 clamp、不续跑)
        else:
            reward_raw = float(np.log(equity_end / equity_start))
            reward = self.reward_scale * reward_raw
            self.episode_reward_raw += reward_raw
            self.episode_reward_scaled += reward

        self._current_tick = exec_tick
        info: dict[str, Any] = {
            "decision_tick": t, "execution_tick": exec_tick,
            "action_branch": branch, "action_w": w,
            "fill_kind": fill.kind, "exec_price": fill.exec_price,
            "raw_open": raw_open, "signed_qty": fill.signed_qty,
            "fee": fill.fee, "realized_pnl": fill.realized_pnl,
            "requested_ratio": fill.requested_ratio,
            "achieved_ratio": fill.achieved_ratio,
            "residual": fill.residual,
            "qty": self.ledger.qty,
            "avg_entry": self.ledger.avg_entry,
            "cash": self.ledger.cash,
            "funding_payment": funding_payment,
            "equity_start": equity_start, "equity_end": equity_end,
            "reward_raw": reward_raw, "reward_scaled": (
                reward if reward_valid else None),
            "reward_valid": reward_valid,
            "exposure_ratio_close": (
                self.ledger.exposure_ratio(exec_close)
                if equity_end > 0.0 else None),
            "terminated": terminated, "truncated": False,
            "funding_missing": self.funding_missing,
        }
        if risk_action is not None:
            info["risk_action"] = {
                "exec_price": risk_action.exec_price,
                "signed_qty": risk_action.signed_qty,
                "fee": risk_action.fee}
        if liquidation is not None and liquidation.kind == "liquidate":
            info["terminal_liquidation"] = {
                "reference_price": liquidation.raw_mark,
                "exec_price": liquidation.exec_price,
                "fee": liquidation.fee,
                "signed_qty": liquidation.signed_qty}
        if self.economic_failure is not None:
            info["economic_failure"] = dict(self.economic_failure)
        rec = {k: v for k, v in info.items()
               if isinstance(v, (int, float, str, bool, list, tuple,
                                 type(None)))}
        rec["ts_decision"] = (str(self._dates[t])
                              if self._dates is not None else None)
        self.step_records.append(rec)
        self._last_info = info
        obs = self._observation(exec_tick) if equity_end > 0.0 else (
            np.full(self.observation_space.shape, np.nan, np.float32))
        return obs, float(reward), terminated, False, info

    def render(self):  # pragma: no cover
        return None
