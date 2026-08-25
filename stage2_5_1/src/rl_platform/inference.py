"""顺序状态推理器(阶段 2.5 路线 C 核心,阶段 2.5.1 工作包 B/F 加固)。

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

阶段 2.5.1 加固:
- window_size 仅支持 1(guards.assert_conv_width,见工作包 B);
- predict_frame 接收与行对齐的 do_predict mask:do_predict != 1 或观察
  含 NaN/Inf 的行不调用模型、输出当前目标仓位、不更新顺序状态,
  保证"无效预测行不能改变目标状态"(工作包 F 十九节)。
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from rl_platform.guards import assert_conv_width


class SequentialPositionPredictor:
    """逐行顺序推理器。跨调用方(窗口/进程重载)通过 current_position 传递状态。"""

    def __init__(self, model: Any, window_size: int = 1) -> None:
        self.window_size = assert_conv_width(window_size, source="SequentialPositionPredictor")
        self.model = model
        self.current_position = 0

    @staticmethod
    def build_observation_static(
        features: np.ndarray, row: int, position: int, window_size: int
    ) -> np.ndarray:
        """与 AlignedLongFlatEnv._observation 完全一致的观察构造(静态入口)。"""
        window = features[row - window_size + 1 : row + 1]
        return np.concatenate([window.ravel(), [float(position)]]).astype(np.float32)

    def build_observation(
        self, features: np.ndarray, row: int, position: int
    ) -> np.ndarray:
        """与 AlignedLongFlatEnv._observation 完全一致的观察构造。"""
        return self.build_observation_static(features, row, position, self.window_size)

    def predict_frame(
        self,
        features: pd.DataFrame | np.ndarray,
        do_predict: np.ndarray | list[int] | None = None,
    ) -> np.ndarray:
        """对一帧(一个 FreqAI 预测窗口)逐行顺序推理,返回目标仓位序列(int)。

        :param do_predict: 与 features 逐行对齐的有效性 mask
            (1=有效;0=NaN 行;2=模型过期/DI 异常)。None 表示全部有效。
        """
        arr = features.to_numpy(dtype=np.float64) if isinstance(features, pd.DataFrame) \
            else np.asarray(features, dtype=np.float64)
        if do_predict is not None and len(do_predict) != len(arr):
            raise ValueError(
                f"do_predict 长度 {len(do_predict)} 与特征行数 {len(arr)} 不一致"
            )
        out = np.zeros(len(arr), dtype=np.int64)
        for i in range(len(arr)):
            if i < self.window_size - 1:
                out[i] = self.current_position
                continue
            dp_ok = True if do_predict is None else int(do_predict[i]) == 1
            obs = self.build_observation(arr, i, self.current_position)
            if not dp_ok or not np.isfinite(obs).all():
                # 无效预测行(do_predict != 1 或特征不完整):
                # 保持当前目标仓位,不调用模型,不更新顺序状态
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
    提供 save(joblib)以兼容 FreqAI data_drawer 对 sb3 模型的
    model.save(path) 调用(测试级 scripted 适配用;非生产路径)。
    """

    def __init__(self, feature_index: int = 0, threshold: float = 0.0) -> None:
        self.feature_index = feature_index
        self.threshold = threshold

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        value = float(obs[self.feature_index])
        return (1 if value > self.threshold else 0), None

    def save(self, path):
        import joblib

        joblib.dump(self, path)

    def save(self, path):
        import joblib

        joblib.dump(self, path)


class FixedSequencePolicy:
    """确定性测试策略:按给定动作序列依次输出(用于固定目标序列回归)。"""

    def __init__(self, actions: list[int] | np.ndarray) -> None:
        self.actions = [int(a) for a in actions]
        self.cursor = 0

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        action = self.actions[min(self.cursor, len(self.actions) - 1)]
        self.cursor += 1
        return action, None


class ReadPositionPolicy:
    """确定性测试策略:直接返回观察末维的仓位分量。

    用于验证 live 推理确实用"真实仓位"构造了最新观察(工作包 G)。"""

    def predict(self, obs: np.ndarray, deterministic: bool = True):
        return int(obs[-1]), None
