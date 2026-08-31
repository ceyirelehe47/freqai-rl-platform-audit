"""阶段 2.6.2:面向 SB3 PPO 的 deterministic multi-episode 课程环境。

- 组合而非继承:每次 reset 按 manifest 顺序取下一个已生成 episode,
  按 evaluator._build_env 的同一构造逻辑重建冻结 AlignedLongFlatEnv
  (features=select_features_strict,prices=OHLCV,
   execution_mode="market_open_causal")——observation/action/reward
  语义与 2.6.1 qualification 完全一致;
- episode 切换时完整清空账户状态:内层 env 每次全新构造,ledger
  reset 即等价新实例(2.6.1 冻结合同),无 position/equity/隐藏
  元数据跨 episode 泄漏;
- 不将 episode ID / family / rung / seed / latent 暴露给 policy:
  observation 只来自内层 env(8 生产特征 + 仓位槽位);
- bank 消耗完毕确定性停止:reset 在耗尽时进入 exhausted 状态并
  确定性回到 manifest 起点(仅服务于 SB3 VecEnv 在最后一个 done 处
  的自动 reset;训练 runner 必须断言 steps_taken == 预算 且
  exhausted_cycles <= 1,任何真实越界都视为配置错误——不静默循环);
- 单环境(n_envs=1):episode 顺序即 manifest 顺序,清晰无歧义。
"""

from __future__ import annotations

from typing import Any

import gymnasium as gym
import numpy as np
import pandas as pd

from rl_curriculum.curriculum261_api import curriculum261_eval_config
from rl_curriculum.curriculum261_production_obs import (
    production_observation_schema,
)
from rl_curriculum.evaluator import EvalConfig, select_features_strict
from rl_curriculum.generator_api import PRICE_COLUMNS
from rl_curriculum.ppo262_banks import LoadedEpisode
from rl_platform.env import AlignedLongFlatEnv


class CurriculumMultiEpisodeEnv(gym.Env):
    """deterministic multi-episode curriculum environment(n_envs=1)。

    metadata 无渲染;确定性来源:episode 列表固定、内层 env 无内部
    随机性(数据固定 + 成交确定),reset(seed) 只喂给 gymnasium 基类
    与内层(不影响动力学)。
    """

    metadata = {"render_modes": []}

    def __init__(
        self, bank: list[LoadedEpisode], *,
        eval_config: EvalConfig | None = None,
        schema=None,
    ):
        super().__init__()
        if not bank:
            raise ValueError("bank 不能为空")
        self.bank = list(bank)
        self.eval_config = eval_config or curriculum261_eval_config()
        self.schema = schema or production_observation_schema()
        if self.eval_config.window_size != self.schema.window_size:
            raise ValueError(
                "EvalConfig.window_size 必须与 observation schema 一致")
        probe = self._build_inner(self.bank[0])
        self.action_space = probe.action_space
        self.observation_space = probe.observation_space
        self._probe = probe
        # 游标与审计计数
        self._cursor = 0            # 下一次 reset 应加载的 episode 下标
        self._inner: AlignedLongFlatEnv | None = None
        self._episode_done = False
        self.current_index: int | None = None
        self.episodes_consumed = 0   # 完成(而非仅加载)的 episode 数
        self.steps_taken = 0         # 本 env 生命周期内的总决策步
        self.exhausted_cycles = 0    # 耗尽后的边界 reset 次数
        self.episode_trace: list[dict[str, Any]] = []

    # ------------------------------------------------------------ 内层构造
    def _build_inner(self, loaded: LoadedEpisode) -> AlignedLongFlatEnv:
        ep = loaded.episode
        features = select_features_strict(ep.df, self.schema)
        return AlignedLongFlatEnv(
            features=features,
            prices=ep.df[list(PRICE_COLUMNS)],
            fee=self.eval_config.fee,
            slippage_bps=self.eval_config.slippage_bps,
            initial_cash=self.eval_config.initial_cash,
            reward_scale=self.eval_config.reward_scale,
            window_size=self.eval_config.window_size,
            price_tick=self.eval_config.price_tick,
            execution_mode="market_open_causal",
        )

    # ------------------------------------------------------------ gym API
    def reset(self, *, seed: int | None = None, options: dict | None = None):
        super().reset(seed=seed)
        if self._cursor >= len(self.bank):
            # 确定性停止语义:manifest 耗尽。回到起点服务 SB3 在最后
            # 一个 done 处的自动 reset(不产生任何训练数据);真实越界
            # 由 runner 的 exhausted_cycles 断言拦截,绝不静默循环。
            self.exhausted_cycles += 1
            self._cursor = 0
        loaded = self.bank[self._cursor]
        self.current_index = self._cursor
        self._inner = self._build_inner(loaded)
        self._episode_done = False
        self._cursor += 1
        obs, info = self._inner.reset(seed=seed)
        info = dict(info)
        info["episode_index"] = self.current_index
        info["episode_key"] = loaded.key.canonical()
        info["env_episodes_started"] = self.current_index + 1
        return obs, info

    def step(self, action):
        if self._inner is None:
            raise RuntimeError("step 前必须 reset")
        if self._episode_done:
            raise RuntimeError(
                "episode 已终止:done 后必须 reset(包装层不支持 done 后"
                "继续 step;SB3 VecEnv 会在 done 处自动 reset)")
        obs, reward, terminated, truncated, info = self._inner.step(action)
        self._episode_done = bool(terminated or truncated)
        self.steps_taken += 1
        info = dict(info)
        info["episode_index"] = self.current_index
        if terminated or truncated:
            self.episodes_consumed += 1
            loaded = self.bank[self.current_index]
            self.episode_trace.append({
                "episode_index": self.current_index,
                "key": loaded.key.canonical(),
                "family": loaded.key.family,
                "rung": loaded.key.rung,
                "variant": loaded.key.variant,
                "episode_reward": float(
                    info.get("episode_reward_raw", np.nan)),
                "steps": int(info.get("execution_tick", -1)),
            })
        return obs, reward, terminated, truncated, info

    # ------------------------------------------------------------ 审计接口
    def exposure_counts(self) -> dict[str, int]:
        """family/rung 曝光计数(学习曲线用;policy 不可见)。"""
        counts: dict[str, int] = {}
        for t in self.episode_trace:
            k = f"{t['family']}/{t['rung']}"
            counts[k] = counts.get(k, 0) + 1
        return counts

    def audit(self) -> dict[str, Any]:
        """环境审计快照(不重复/不跳过的证据)。"""
        seen = [t["episode_index"] for t in self.episode_trace]
        return {
            "episodes_consumed": self.episodes_consumed,
            "steps_taken": self.steps_taken,
            "exhausted_cycles": self.exhausted_cycles,
            "unique_episodes_started": len(
                {i for i in seen}),
            "first_pass_order_ok": seen == sorted(set(seen)),
            "duplicate_episode_completions": len(seen) - len(set(seen)),
            "exposure_counts": self.exposure_counts(),
        }
