# -*- coding: utf-8 -*-
"""teach_env v3 — 经济时序修正(审查方 3999 组1)。

时序(决策 close[t]→执行 open[t+1]→结算 close[t+1];
线性无跳空 ⇒ open[t+1]=price):
  1) eq_start=equity(price)(close[t]);
  2) 开盘风险(=上一收盘点,PosctlEnvCore-v2):equity≤0=经济失败
     终结;低于维持线=风险平仓后动作照常;
  3) 动作在 open=price 执行(HOLD 占位/REBAL 扣费后精确求解);
     扣费后复查 equity(open)>0 否则失败;
  4) 抽 r;close=open*(1+r);
  5) 末步(rem==1):close 清算恰一次;清算后权益≤0=
     reward_valid=False;否则 reward=log(eq_final/eq_start);
     非末步:reward=log(eq_close/eq_start)(下一开盘风险即本收盘
     风险),rem-=1(终态 rem=0)。
基准(审查方):flat,w=.5,fee=.001,r=.01,rem1 →
eq_final/eq_start=1.0039930034982512(测试断言)。
"""
import math
import os
import random
import sys

import numpy as np

try:
    import gymnasium as gym
    from gymnasium import spaces
    _HAS_GYM = True
except Exception:
    gym = None
    spaces = None
    _HAS_GYM = False


def repo_src_path():
    """显式源码根:PILOT_REPO_SRC 优先(快照),回退本仓相对。"""
    env = os.environ.get("PILOT_REPO_SRC")
    if env and os.path.isdir(env):
        return env
    _here = os.path.dirname(os.path.abspath(__file__))
    return os.path.abspath(os.path.join(
        _here, "..", "freqai-rl-audit",
        "stage2_7_0", "src"))


_REPO_SRC = repo_src_path()
for _p in (_REPO_SRC,
           os.path.join(_REPO_SRC,
                        "rl_posctl", "skill_p0")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

from rl_posctl.ledger import (  # noqa: E402
    TwoSidedLinearLedger)
from rl_posctl.env import (  # noqa: E402
    HybridPositionEnv)

H = 32
MU = 0.0012
SIGMA = {0: 0.03, 1: 0.06}
FEE = 0.001
CASH0 = 100.0
MAINT = 0.05
OBS_DIM = 8

KERNEL = {
    "s": ([-1, 0, 1], 0.78, 0.22, None),
    "c": ([0, 1], 0.75, 0.25, None),
    "q": ([0.0, 0.25, 0.5, 0.75, 1.0], 0.80, None,
          [0.125, 0.25, 0.25, 0.25, 0.125]),
    "g": ([0, 1], 0.80, 0.20, None)}


def _asinh_acc(x):
    return math.asinh(x) / 4.0


class UnifiedPilotEnv(
        gym.Env if _HAS_GYM else object):
    """Gymnasium 兼容;SB3 reset() 走 4×25% 混额采样。"""

    metadata = {"render_modes": []}

    def __init__(self, rng=None):
        if _HAS_GYM:
            self.observation_space = spaces.Box(
                -np.inf, np.inf, (OBS_DIM,),
                dtype=np.float64)
            self.action_space = spaces.Box(
                -1.0, 1.0, (2,), dtype=np.float32)
        self.rng = rng or random.Random(0)
        self.led = TwoSidedLinearLedger()
        self.n_steps_env = 0
        self.price = 1.0
        self.rem = H
        self.total = H
        self.s = 1
        self.c = 1
        self.q = 1.0
        self.g = 0
        self.failed = None
        self._terminated = False

    def seed(self, s):
        self.rng = random.Random(s)

    # ---------------- reset ----------------
    def reset(self, *, seed=None, remaining=None,
              s=None, options=None):
        if seed is not None:
            self.rng = random.Random(seed)
        if remaining is None or s is None:
            kw = episode_reset_sampler(self.rng)
            remaining = kw["remaining"]
            s = kw["s"]
        self.led = TwoSidedLinearLedger()
        self.s = int(s)
        self.c = 1
        self.q = 1.0
        self.g = 0
        self.rem = int(remaining)
        self.total = H
        self.price = 1.0
        self.failed = None
        self._terminated = False
        return self._obs(), {"reset": True}

    def _obs(self):
        e = self.led.exposure_ratio(self.price)
        if not math.isfinite(e):
            e = math.copysign(1e9, e if e else 1.0)
        sol = self.led.solvency_ratio(self.price)
        if not math.isfinite(sol):
            sol = 40.0 if sol > 0 else 0.0
        return np.array(
            [float(self.c), float(self.g),
             float(self.q), float(self.s),
             _asinh_acc(e),
             _asinh_acc(min(sol, 40.0)),
             self.rem / 128.0,
             self.total / 128.0],
            dtype=np.float64)

    def _draw_r(self):
        mu_eff = self.s * self.c * self.q * MU
        u = self.rng.random() * 2.0 - 1.0
        return mu_eff + math.sqrt(3.0) * SIGMA[self.g] * u

    def _evolve(self, comp, v):
        vals, hold, res, fresh = KERNEL[comp]
        if fresh is not None:
            if self.rng.random() < hold:
                return v
            x = self.rng.random()
            acc = 0.0
            for fv, fp in zip(vals, fresh):
                acc += fp
                if x < acc:
                    return fv
            return vals[-1]
        if self.rng.random() < hold:
            return v
        return vals[self.rng.randrange(len(vals))]

    @staticmethod
    def _decode(action):
        """直接复用原 HybridPositionEnv.decode_action
        (精确 branch 0/1、HOLD 占位必须 0、w 域校验)。"""
        return HybridPositionEnv.decode_action(action)

    def _fail(self, phase, reason,
              branch, w, executed):
        self.failed = {
            "phase": phase,
            "reward_valid": False,
            "reason": reason,
            "action": [branch, w],
            "executed": executed}
        self._terminated = True
        return (self._obs(), 0.0, True, False,
                self._info(None, None, None,
                           reward_valid=False))

    def step(self, action):
        if self._terminated or self.failed:
            raise RuntimeError(
                "经济失败/终结后不得继续 step")
        branch, w = self._decode(action)
        self.n_steps_env += 1
        open_p = self.price             # open[t+1]=close[t]
        eq_start = self.led.equity(open_p)

        # 1) 开盘风险(先于动作)
        eq_open = self.led.equity(open_p)
        if eq_open <= 0.0:
            return self._fail(
                "open",
                "equity_open<=0 (%r)" % eq_open,
                branch, w, False)
        risk_action = None
        if (self.led.qty != 0.0
                and eq_open < MAINT * abs(
                    self.led.qty) * open_p):
            self.led.risk_flatten(open_p)
            risk_action = "open_risk_flatten"
            if self.led.equity(open_p) <= 0.0:
                return self._fail(
                    "open_post_flatten",
                    "equity after open risk-"
                    "flatten <=0 (%r)"
                    % self.led.equity(open_p),
                    branch, w, False)

        # 2) 动作在 open 执行 + 扣费后复查
        if branch == 0:
            self.led.hold(open_p)
            fill_kind = "hold"
        else:
            rec = self.led.apply_target_ratio(
                w, open_p)
            fill_kind = rec.kind
        eq_after = self.led.equity(open_p)
        if eq_after <= 0.0:
            return self._fail(
                "post_action",
                "equity_after_fee<=0 (%r)"
                % eq_after,
                branch, w, True)

        # 3) 抽 r;close=open*(1+r)
        r = self._draw_r()
        close_p = open_p * (1.0 + r)

        # 4) 末步清算恰一次 / 非末步收盘结算
        if self.rem <= 1:
            self.led.liquidate(close_p)
            eq_final = self.led.equity(close_p)
            self.price = close_p
            self.rem = 0
            self._terminated = True
            if eq_final <= 0.0:
                return self._fail(
                    "terminal",
                    "equity_final<=0 (%r)"
                    % eq_final,
                    branch, w, True)
            reward = math.log(
                eq_final / eq_start)
            return (self._obs(), reward,
                    True, False,
                    self._info(fill_kind, risk_action,
                               "terminal",
                               reward_valid=True,
                               r=r))
        eq_close = self.led.equity(close_p)
        if eq_close <= 0.0:
            return self._fail(
                "settle",
                "equity_close<=0 (%r)"
                % eq_close,
                branch, w, True)
        # 本 bar 收盘风险(不延至下一开盘):同 bar 强平+
        # 扣费复查;失败→同 bar 经济失败;成功→flat 状态
        if (self.led.qty != 0.0
                and eq_close < MAINT * abs(
                    self.led.qty) * close_p):
            self.led.risk_flatten(close_p)
            risk_action = (
                risk_action
                or "close_risk_flatten")
            eq_flat = self.led.equity(close_p)
            if eq_flat <= 0.0:
                return self._fail(
                    "close_flatten",
                    "equity after close "
                    "risk-flatten <=0 (%r)"
                    % eq_flat,
                    branch, w, True)
        reward = math.log(
            self.led.equity(close_p)
            / eq_start)
        self.price = close_p
        self.rem -= 1
        self.s = self._evolve("s", self.s)
        self.c = self._evolve("c", self.c)
        self.q = self._evolve("q", self.q)
        self.g = self._evolve("g", self.g)
        return (self._obs(), reward,
                False, False,
                self._info(fill_kind, risk_action,
                           None,
                           reward_valid=True,
                           r=r))

    def _info(self, fill_kind, risk_action,
              terminal, reward_valid, r=None):
        return {
            "fill_kind": fill_kind,
            "risk_action": risk_action,
            "terminal_liquidation": terminal,
            "reward_valid": reward_valid,
            "r": r,
            "economic_failure": (
                dict(self.failed)
                if self.failed is not None
                else None),
            "equity": self.led.equity(
                self.price),
            "exposure": (
                self.led.exposure_ratio(
                    self.price))}


def episode_reset_sampler(rng):
    k = rng.randrange(4)
    return [
        {"remaining": 32, "s": 1},
        {"remaining": 32, "s": -1},
        {"remaining": 1, "s": 1},
        {"remaining": 1, "s": -1},
    ][k]
