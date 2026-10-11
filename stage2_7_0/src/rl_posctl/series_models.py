# -*- coding: utf-8 -*-
"""时序候选:固定 16 根已完成 K 线窗口的展开 MLP 与小型 LSTM 编码
(RouteC_PositionControl W6,PosctlSeriesCandidates-v1)。

设计(事前固定,不做事后架构搜索):
- 窗口 W=16(只含已完成 bar;不含未来/跨 episode/身份信息);
- 窗口 MLP:环境 window_size=16,扁平观察直接进标准 MLP(与单步
  MLP 同一 policy 类,只是观察面不同);
- LSTM:每个有限窗口**独立编码**,初始 hidden/cell 置零重置(每步
  重算;不跨步递推、不跨 episode 携带)——它是短窗口编码器,不
  声称无限历史记忆,也不等价 RecurrentPPO;
- 两结构信息范围相同:同样 16×n_feat 窗口;账户状态(exposure/
  solvency)单独拼接在编码输出之后;
- LSTM 为单层、hidden=128(紧凑模型,固定);
- 无跨步递推 => 不需要 episode-start 掩码/序列切片重建;该简化
  已在报告声明,且可见历史恰为 16。
"""

from __future__ import annotations

import torch as th
import torch.nn as nn

from stable_baselines3.common.torch_layers import BaseFeaturesExtractor

LSTM_WINDOW = 16
LSTM_HIDDEN = 128


class WindowLstmFeaturesExtractor(BaseFeaturesExtractor):
    """obs = [window 特征平铺 (16·n_feat) | account(2)]。

    - 前 16·n_feat reshape 为 (16, n_feat) 序列,单层 LSTM(hidden
      128)从零初始状态编码,取末步 hidden;
    - account 2 维单独拼接(不进时间编码);
    - 输出 features = [lstm_h(128) | account(2)]。
    """

    def __init__(self, observation_space, n_features: int,
                 window: int = LSTM_WINDOW,
                 hidden: int = LSTM_HIDDEN) -> None:
        n_account = 2
        super().__init__(observation_space, hidden + n_account)
        self.n_features = int(n_features)
        self.window = int(window)
        self.hidden = int(hidden)
        self.lstm = nn.LSTM(self.n_features, self.hidden,
                            num_layers=1, batch_first=True)
        # 权重初始化(正交;PyTorch LSTM 默认 uniform,显式固定)
        for name, param in self.lstm.named_parameters():
            if "weight" in name:
                nn.init.orthogonal_(param)
            elif "bias" in name:
                nn.init.constant_(param, 0.0)

    def forward(self, obs: th.Tensor) -> th.Tensor:
        b = obs.shape[0]
        flat = obs[:, : self.window * self.n_features]
        account = obs[:, -2:]
        seq = flat.reshape(b, self.window, self.n_features)
        # 每窗口独立编码:零初始状态(不跨样本/跨步携带)
        h0 = obs.new_zeros(1, b, self.hidden)
        c0 = obs.new_zeros(1, b, self.hidden)
        out, _ = self.lstm(seq, (h0, c0))
        return th.cat([out[:, -1, :], account], dim=1)


def lstm_policy_kwargs(n_features: int) -> dict:
    """LSTM 候选的 policy_kwargs(编码器 + 紧凑头)。"""
    return dict(
        features_extractor_class=WindowLstmFeaturesExtractor,
        features_extractor_kwargs={
            "n_features": int(n_features)},
        net_arch=dict(pi=[64], vf=[64]),
    )


def mlp_policy_kwargs(width: int) -> dict:
    """MLP 候选(两隐层宽度 width;actor/critic 分支同宽)。"""
    return dict(net_arch=dict(pi=[int(width)] * 2,
                              vf=[int(width)] * 2))
