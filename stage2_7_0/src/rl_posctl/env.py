# -*- coding: utf-8 -*-
"""双向连续仓位 + HOLD 混合动作环境(RouteC_PositionControl W1)。

动作(HybridHoldRebalanceAction-v1):二元组 (branch, w)
- branch=0:HOLD(观望/继续持有),w 忽略(必须为 0 值占位,传非 0
  视为编码错误拒绝);
- branch=1:REBALANCE(w),w∈[-1,1] 为目标名义敞口比例(相对扣费后
  净值;正=多头,负=空头,0=清仓);
- 非法输入(branch∉{0,1}/w 非有限/越界/branch=1 时 w 缺失)显式
  ValueError 拒绝,绝不静默转 HOLD/0。

时间因果(PosctlEnvCore-v2,R1 修复开盘时序):
  观察 = 截至 close[t] 的特征窗口 + 账户状态(敞口/偿付的数值变换)
  -> **开盘检查(open[t+1],先于模型动作;HOLD 与 REBALANCE 对
     同经济状态一致)**:
     · equity(open) <= 0:显式经济失败终结(动作不执行、不收费;
       失败信息完整进 info/step_records,不抛无记录异常);
     · equity(open) > 0 且 < maintenance_margin*|qty|*open:
       开盘风险平仓(risk action,支付全部摩擦),随后模型动作
       在平仓后的账户上照常执行;
  -> 执行在 open[t+1](统一标记价 = 原始 open[t+1];
     成交价另按方向加不利滑点/tick 取整)
  -> 旧数量承担 close[t]->open[t+1] 跳空;新数量承担
     open[t+1]->close[t+1];
  -> 若 t+1 ∈ 资金费计划:在 close[t+1] 按标记结算(方向正确);
  -> 收盘维持保证金风险检查(close[t+1]):与开盘同一规则;
  -> 终端(t+1 = 最后一根):清算以 close[last] 为参考价,与普通
     平仓完全相同的滑点/取整/费用;HOLD 不能阻止清算/费用/资金费。

奖励(NetLogEquityReward-v2):reward_raw = log(E_end/E_start),
E_start=equity(close[t]),E_end=equity(close[t+1])(含一切损益/费用/
资金费/清算)。无任何附加持仓/空仓/HOLD/回撤奖惩项。E_open<=0 或
E_end<=0 时 log 未定义:显式经济失败终结(terminated=True,
info.economic_failure,info.reward_valid=False;reward 数值 0.0 仅作
占位,训练 harness 必须检测该标志并判运行无效,不得让该步参与学习)。

自融资 telescoping(无失败时):sum(reward_raw) == log(final_cash/E0)。

观察(PosctlObs-v2):window_size 行特征(平铺) + 账户特征数值变换
[asinh(exposure)/4, asinh(min(solvency,40))/4](close[t] 口径)。
HOLD 漂移致 |exposure|>1 不截断(asinh 单调保留);原始经济值
(equity/exposure/solvency/inf)逐保留在 info["account_state"]。
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

# 账户观察数值变换(PosctlObs-v2;事前固定,不看评估结果调参):
# - exposure: asinh(x)/4。单调、对称、无截断——HOLD 漂移 |x|>1 照实
#   可见(不 clip 隐藏越界);|x|→∞ 缓慢增长,MLP 首层不再全饱和。
# - solvency: asinh(min(s, 40))/4。CAP=40 远高于任何经济上可区分的
#   偿付余量(维护线 0.05;>40 全部等价"绝对安全"),cap 只作用于
#   我们自造的 inf 占位语义,不是隐藏真实敞口。
# 原始经济值(exposure/solvency/inf)逐保留在 info["account_state"]。
OBS_SCALE = 4.0
SOLVENCY_CAP = 40.0

# 全进程环境交互步计数(R1 计量:无梯度评估面实际步数的如实口径;
# 运行器读数后按次记入预约账本,测试不隐式免计)
ENV_STEP_COUNT = 0


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
        return [
            float(math.asinh(exposure) / OBS_SCALE),
            float(math.asinh(
                min(solv, SOLVENCY_CAP)) / OBS_SCALE)]

    def _account_state_raw(self, price: float) -> dict[str, Any]:
        """原始(未变换)账户经济值,进 info 日志供审计。"""
        return {
            "equity": self.ledger.equity(price),
            "exposure_ratio": self.ledger.exposure_ratio(price),
            "solvency_ratio": self.ledger.solvency_ratio(price),
            "maintenance_margin": self.maintenance_margin,
        }

    def _observation(self, tick: int) -> np.ndarray:
        window = self._features[tick - self.window_size + 1: tick + 1]
        parts = [window.ravel(),
                 np.asarray(self._account_features(self._close[tick]))]
        return np.concatenate(parts).astype(np.float32)

    def _feature_row(self, tick: int) -> dict:
        """决策 bar 的特征行(名称->值;供课程参考/基线只读当前
        可观察状态,不含未来)。"""
        return {name: float(v) for name, v in zip(
            self.feature_names, self._features[tick])}

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
        self._extra_risk_fills = []
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
        global ENV_STEP_COUNT
        ENV_STEP_COUNT += 1
        t = self._current_tick
        exec_tick = t + 1
        raw_open = self._open[exec_tick]
        exec_close = self._close[exec_tick]
        equity_start = self.ledger.equity(self._close[t])

        # ------------------------------------------------------------------
        # 0) 开盘偿付/维护检查(PosctlEnvCore-v2;先于模型动作)。
        # 旧仓位承担 close[t]->open[t+1] 跳空;账户在模型可行动作时点
        # 已不可偿付的,不允许 HOLD 穿过破产等收盘恢复(REBALANCE 与
        # HOLD 对同经济状态一致):
        # - equity(open) <= 0:显式经济失败终结(不 clamp、不执行任何
        #   动作;失败可追踪到 info.economic_failure 与运行记录);
        # - equity(open) > 0 但低于维护线:开盘风险平仓(risk action,
        #   支付全部摩擦),随后模型动作在平仓后的账户上照常执行
        #   (REBALANCE 可重新建仓;HOLD 保持空仓——一致性来自同一
        #   风险处置,而非给某分支豁免)。
        # ------------------------------------------------------------------
        open_risk_action = None
        equity_at_open = self.ledger.equity(raw_open)
        if equity_at_open <= 0.0:
            reason = (
                f"开盘净值非正(equity_open={equity_at_open!r},"
                f"E_start={equity_start!r}):账户在动作可执行时点已"
                f"不可偿付;tick={t}->{exec_tick},"
                f"请求动作=[{branch},{w}]未执行")
            self.economic_failure = {
                "phase": "open", "reason": reason,
                "decision_tick": t, "execution_tick": exec_tick,
                "equity_start": equity_start,
                "equity_at_open": equity_at_open,
                "action": [branch, w], "executed": False}
            self._current_tick = exec_tick
            self.episode_reward_raw = None
            self.episode_reward_scaled = None
            info = {
                "decision_tick": t, "execution_tick": exec_tick,
                "action_branch": branch, "action_w": w,
                "fill_kind": None, "exec_price": None,
                "raw_open": raw_open, "signed_qty": 0.0,
                "fee": 0.0, "realized_pnl": 0.0,
                "requested_ratio": (w if branch == 1 else None),
                "achieved_ratio": None, "residual": None,
                "qty": self.ledger.qty,
                "avg_entry": self.ledger.avg_entry,
                "cash": self.ledger.cash,
                "funding_payment": 0.0,
                "equity_start": equity_start,
                "equity_end": equity_at_open,
                "reward_raw": None, "reward_scaled": None,
                "reward_valid": False,
                "exposure_ratio_close": None,
                "terminated": True, "truncated": False,
                "funding_missing": self.funding_missing,
                "open_equity": equity_at_open,
                "risk_action": None, "terminal_liquidation": None,
                "fees_cum": self.ledger.fees_total,
                "funding_cum": self.ledger.funding_total,
                "economic_failure": dict(self.economic_failure),
                "account_state": self._account_state_raw(raw_open),
            }
            self._record(info, t)
            obs = np.full(self.observation_space.shape, np.nan,
                          np.float32)
            return obs, 0.0, True, False, info
        notional_open = abs(self.ledger.qty) * raw_open
        if notional_open > 0.0 and equity_at_open < (
                self.maintenance_margin * notional_open):
            open_risk_action = self.ledger.risk_flatten(raw_open)

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

        # 3) 收盘风险规则 / 终端清算(维持原语义;开盘风险平仓后若
        #    模型重新建仓,同样适用)
        risk_action = open_risk_action
        liquidation = None
        terminated = exec_tick == self.n_rows - 1
        notional_close = abs(self.ledger.qty) * exec_close
        if not terminated and notional_close > 0.0:
            e_at_close = self.ledger.equity(exec_close)
            if e_at_close < self.maintenance_margin * notional_close:
                close_flatten = self.ledger.risk_flatten(exec_close)
                if risk_action is None:
                    risk_action = close_flatten
                else:   # 同 bar 开盘+收盘两次风险事件的罕见叠加
                    self._extra_risk_fills = getattr(
                        self, "_extra_risk_fills", [])
                    self._extra_risk_fills.append(close_flatten)
        elif terminated:
            liquidation = self.ledger.liquidate(exec_close)

        equity_end = self.ledger.equity(exec_close)

        # 4) 奖励与失败判定
        reward_valid = True
        if equity_start <= 0.0 or equity_end <= 0.0:
            phase = ("open_risk_flatten"
                     if open_risk_action is not None and
                     equity_end <= 0.0 else "post_execution")
            reason = (
                f"非正净值(E_start={equity_start!r},"
                f"E_end={equity_end!r},phase={phase}):log 奖励未定义;"
                f"tick={t}->{exec_tick}")
            self.economic_failure = {
                "phase": phase, "reason": reason,
                "decision_tick": t, "execution_tick": exec_tick,
                "equity_start": equity_start,
                "equity_at_open": equity_at_open,
                "equity_end": equity_end,
                "action": [branch, w], "executed": True}
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
            "open_equity": equity_at_open,
            "open_risk_triggered": open_risk_action is not None,
            "fees_cum": self.ledger.fees_total,
            "funding_cum": self.ledger.funding_total,
            "account_state": self._account_state_raw(exec_close),
        }
        if risk_action is not None:
            info["risk_action"] = {
                "phase": "open" if open_risk_action is not None
                else "close",
                "exec_price": risk_action.exec_price,
                "signed_qty": risk_action.signed_qty,
                "fee": risk_action.fee}
        else:
            info["risk_action"] = None
        if liquidation is not None and liquidation.kind == "liquidate":
            info["terminal_liquidation"] = {
                "reference_price": liquidation.raw_mark,
                "exec_price": liquidation.exec_price,
                "fee": liquidation.fee,
                "signed_qty": liquidation.signed_qty}
        else:
            info["terminal_liquidation"] = None
        extras = getattr(self, "_extra_risk_fills", None)
        if extras:
            info["extra_risk_fills"] = [
                {"phase": "close", "exec_price": f.exec_price,
                 "signed_qty": f.signed_qty, "fee": f.fee}
                for f in extras]
            self._extra_risk_fills = []
        if self.economic_failure is not None:
            info["economic_failure"] = dict(self.economic_failure)
        self._record(info, t)
        obs = self._observation(exec_tick) if equity_end > 0.0 else (
            np.full(self.observation_space.shape, np.nan, np.float32))
        return obs, float(reward), terminated, False, info

    def _record(self, info: dict[str, Any], t: int) -> None:
        """把 info 精简为可序列化记录并登记(公共路径)。"""
        rec: dict[str, Any] = {}
        for k, v in info.items():
            if isinstance(v, (int, float, str, bool, list, tuple,
                              type(None))):
                rec[k] = v
            elif isinstance(v, dict):
                rec[k] = {k2: v2 for k2, v2 in v.items()
                          if isinstance(v2, (int, float, str, bool,
                                             list, tuple, type(None)))}
        rec["ts_decision"] = (str(self._dates[t])
                              if self._dates is not None else None)
        self.step_records.append(rec)
        self._last_info = info

    def render(self):  # pragma: no cover
        return None
