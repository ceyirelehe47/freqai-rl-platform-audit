# -*- coding: utf-8 -*-
"""PSC_P0_v1 有限期限时间观察环境与 bank 轮转环境。

P0FiniteTimeEnv(PosctlObsP0Time-v1):旧 6 维观察尾部追加 2 时间维:
  remaining_decisions/128(n_rows−1−tick;初始=H,最后一次行动前=1,
  终止步的终态观察为 0,此后环境终结不再 step)、
  original_horizon/128(=n_rows−1)。
时间维在构造、reset、step、VecEnv 自动 reset、eval、save/load 与
新进程全部经同一 _observation 路径(无 only-info 假接入,无 critic
特权信息)。经济语义/账本/失败分支逐位沿用 HybridPositionEnv(零改动)。
"""
from __future__ import annotations

import numpy as np
from gymnasium import spaces

from rl_posctl.env import HybridPositionEnv
from rl_posctl.experiments import EpisodeBankEnv
from rl_posctl.skill_p0.p0spec import (
    C1_FEE, FUNDING_SCHEDULE, INITIAL_CASH, MAINTENANCE_MARGIN,
    OBS_SPEC_VERSION, REWARD_SCALE)

_TIME_SCALE = 128.0


class P0FiniteTimeEnv(HybridPositionEnv):
    """有限期限已知的时间增广环境(观察 8 维 float32)。"""

    observation_spec_version = OBS_SPEC_VERSION
    p0_time_features = ("remaining_decisions_frac128",
                        "original_horizon_frac128")

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        base = self.observation_space.shape[0]
        self.observation_space = spaces.Box(
            low=-np.inf, high=np.inf,
            shape=(base + len(self.p0_time_features),),
            dtype=np.float32)

    def _time_features(self, tick: int) -> list:
        horizon = self.n_rows - 1
        remaining = self.last_decision_tick - tick + 1
        return [remaining / _TIME_SCALE, horizon / _TIME_SCALE]

    def _observation(self, tick: int) -> np.ndarray:
        base = super()._observation(tick)
        t = np.asarray(self._time_features(tick), dtype=np.float32)
        return np.concatenate([base, t]).astype(np.float32)


class P0EpisodeBankEnv(EpisodeBankEnv):
    """P0 bank 轮转环境(确定性同序;P0 时间观察;公开空资金费计划)。"""

    def __init__(self, bank, fee: float = C1_FEE,
                 window_size: int = 1):
        super().__init__(bank, fee=fee, window_size=window_size)

    def _make(self, item) -> P0FiniteTimeEnv:
        prices, feats, _ = item
        return P0FiniteTimeEnv(
            features=feats, prices=prices, fee=self.fee,
            window_size=self.window_size,
            funding_schedule=dict(FUNDING_SCHEDULE),
            maintenance_margin=MAINTENANCE_MARGIN,
            initial_cash=INITIAL_CASH,
            reward_scale=REWARD_SCALE,
            slippage_bps=0.0, price_tick=0.0)

    @property
    def observation_spec_version(self):
        return self._inner.observation_spec_version
