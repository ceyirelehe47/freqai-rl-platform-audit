"""顺序状态推理器(阶段 2.5 路线 C 核心)。

默认 FreqAI RL 的历史推理对每一行独立调用 model.predict(rolling().apply()),
无法把"当前目标仓位"作为观察状态传递。本模块按时间从早到晚逐行展开:

    初始目标仓位(0,或上一窗口末尾/重载/Dry-run 状态)
    -> 每行:观察 = 特征窗口(含当前行) + 当前目标仓位
    -> model.predict 输出新的目标仓位
    -> 保存动作并更新当前目标仓位
    -> 处理下一行

训练环境 AlignedLongFlatEnv 与本推理器使用完全相同的观察构造
(_observation(tick, position):特征窗口 ravel 后追加一位 0/1),
保证训练与历史推理观察形状一致。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd


class SequentialPositionPredictor:
    """逐行顺序推理器。跨调用方(窗口/进程重载)通过 current_position 传递状态。"""

    def __init__(self, model: Any, window_size: int = 1) -> None:
        self.model = model
        self.window_size = int(window_size)
        self.current_position = 0

    def build_observation(
        self, features: np.ndarray, row: int, position: int
    ) -> np.ndarray:
        """与 AlignedLongFlatEnv._observation 完全一致的观察构造。"""
        window = features[row - self.window_size + 1 : row + 1]
        return np.concatenate([window.ravel(), [float(position)]]).astype(np.float32)

    def predict_frame(self, features: pd.DataFrame | np.ndarray) -> np.ndarray:
        """对一帧(一个 FreqAI 预测窗口)逐行顺序推理,返回目标仓位序列(int)。"""
        arr = features.to_numpy(dtype=np.float64) if isinstance(features, pd.DataFrame) \
            else np.asarray(features, dtype=np.float64)
        out = np.zeros(len(arr), dtype=np.int64)
        for i in range(len(arr)):
            if i < self.window_size - 1:
                out[i] = self.current_position
                continue
            obs = self.build_observation(arr, i, self.current_position)
            if not np.isfinite(obs).all():
                # 特征不完整(预热期):保持当前目标仓位,不调用模型
                out[i] = self.current_position
                continue
            action, _ = self.model.predict(obs, deterministic=True)
            action = int(action)
            if action not in (0, 1):
                raise ValueError(f"模型输出了非法目标仓位 {action}")
            out[i] = action
            self.current_position = action
        return out


class ScriptedPolicy:
    """确定性测试策略:按指定特征列与阈值输出目标仓位。

    测试中用一个特征列(如第一列)驱动:col > threshold -> 1,否则 0。
    不含任何随机性,用于在启动 PPO 之前验证顺序推理的正确性。
    """

    def __init__(self, feature_index: int = 0, threshold: float = 0.0) -> None:
        self.feature_index = feature_index
        self.threshold = threshold

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        value = float(obs[self.feature_index])
        return (1 if value > self.threshold else 0), None


class FixedSequencePolicy:
    """确定性测试策略:按给定动作序列依次输出(用于固定目标序列回归)。"""

    def __init__(self, actions: list[int] | np.ndarray) -> None:
        self.actions = [int(a) for a in actions]
        self.cursor = 0

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        action = self.actions[min(self.cursor, len(self.actions) - 1)]
        self.cursor += 1
        return action, None
