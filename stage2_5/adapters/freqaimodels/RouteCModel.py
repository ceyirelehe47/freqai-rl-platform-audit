"""阶段 2.5 路线 C:FreqAI 薄适配模型。

只覆盖官方支持的扩展点,把 FreqAI 的数据/窗口/模型生命周期接到
自定义对齐环境与顺序推理器上;不复制 FreqAI 内部源码。

覆盖的方法与理由(详见主报告 §5):
- set_train_and_eval_environments():默认实现构造 Base5ActionRLEnv 家族环境,
  其 step() 时间语义(open[t+2] 执行)与记账不符合本任务;替换为 AlignedLongFlatEnv。
- fit():默认 ReinforcementLearner.fit 会挂 MaskableEvalCallback(本环境无动作掩码),
  且 PPO device=auto 会选 GPU;改为显式 CPU + 固定 seed 的最小 PPO 训练。
- rl_model_predict():默认 rolling().apply() 逐行独立预测,无法传递当前目标仓位;
  替换为 SequentialPositionPredictor 顺序推理(跨 backtest 子窗口经实例属性延续状态)。

不覆盖 train()/predict():官方前处理(特征过滤/缩放/OHLC 提取/缓存)全部复用。
"""

import sys
from pathlib import Path
from typing import Any

import numpy as np  # noqa: F401  (保持与上游模型一致的导入面)
import torch as th
from pandas import DataFrame
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.utils import set_random_seed

from freqtrade.freqai.RL.BaseReinforcementLearningModel import BaseReinforcementLearningModel
from freqtrade.freqai.data_kitchen import FreqaiDataKitchen

PROJ_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJ_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rl_platform.env import AlignedLongFlatEnv  # noqa: E402
from rl_platform.inference import SequentialPositionPredictor  # noqa: E402

import logging  # noqa: E402

logger = logging.getLogger(__name__)


class RouteCModel(BaseReinforcementLearningModel):
    """路线 C 适配层:AlignedLongFlatEnv + 顺序推理 + 最小 PPO。"""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        rc = self.freqai_info.get("route_c", {})
        self.rc_config = {
            "slippage_bps": float(rc.get("slippage_bps", 0.0)),
            "initial_cash": float(rc.get("initial_cash", 100.0)),
            "reward_scale": float(rc.get("reward_scale", 1.0)),
            "seed": int(rc.get("seed", 42)),
            "device": str(rc.get("device", "cpu")),
        }
        # 跨 FreqAI backtest 子窗口的顺序推理状态:
        # freqai_interface.start_backtesting 在同一模型实例上按时间顺序调用
        # train()/predict(),实例属性可安全携带上一窗口最终目标仓位。
        # None 表示尚未初始化(live 下首次推理从 Trade 状态解析,回测下为 0)。
        self._last_target_position: int | None = None

    # ------------------------------------------------------------- 环境构造
    def set_train_and_eval_environments(
        self,
        data_dictionary: dict[str, DataFrame],
        prices_train: DataFrame,
        prices_test: DataFrame,
        dk: FreqaiDataKitchen,
    ) -> None:
        """默认实现构造 Base5ActionRLEnv(时间/记账/奖励语义均不符合本任务),
        这里替换为 AlignedLongFlatEnv:观察含当前目标仓位、open[t+1] 执行、
        净值 log 奖励、终端强制清算。"""
        fee = self.config.get("fee")
        if fee is None:
            raise RuntimeError(
                "路线 C 要求 config 显式设置 fee(与回测器 set_fee 的 config 优先口径一致)"
            )
        common = dict(
            fee=float(fee),
            slippage_bps=self.rc_config["slippage_bps"],
            initial_cash=self.rc_config["initial_cash"],
            reward_scale=self.rc_config["reward_scale"],
            window_size=self.CONV_WIDTH,
        )
        self.train_env = AlignedLongFlatEnv(
            features=data_dictionary["train_features"], prices=prices_train, **common
        )
        self.eval_env = Monitor(
            AlignedLongFlatEnv(
                features=data_dictionary["test_features"], prices=prices_test, **common
            )
        )
        # 不创建 MaskableEvalCallback:本环境没有非法动作,无需动作掩码;
        # fit() 也不再依赖 self.eval_callback。

    # ----------------------------------------------------------------- 训练
    def fit(self, data_dictionary: dict[str, Any], dk: FreqaiDataKitchen, **kwargs):
        """最小 PPO 烟雾训练:CPU、固定 seed、无 eval callback。

        total_timesteps = train_cycles * len(train_features)(与官方一致)。
        """
        train_df = data_dictionary["train_features"]
        total_timesteps = self.freqai_info["rl_config"]["train_cycles"] * len(train_df)
        policy_kwargs = dict(activation_fn=th.nn.ReLU, net_arch=self.net_arch)
        if self.activate_tensorboard:
            tb_path = Path(dk.full_path / "tensorboard" / dk.pair.split("/")[0])
        else:
            tb_path = None
        seed = self.rc_config["seed"]
        set_random_seed(seed)
        model = self.MODELCLASS(
            self.policy_type,
            self.train_env,
            policy_kwargs=policy_kwargs,
            tensorboard_log=tb_path,
            device=self.rc_config["device"],
            seed=seed,
            **self.freqai_info.get("model_training_parameters", {}),
        )
        model.learn(total_timesteps=int(total_timesteps))
        logger.info(
            "RouteC PPO 训练完成: timesteps=%s device=%s seed=%s",
            int(total_timesteps), self.rc_config["device"], seed,
        )
        return model

    # ----------------------------------------------------------------- 推理
    def rl_model_predict(
        self, dataframe: DataFrame, dk: FreqaiDataKitchen, model: Any
    ) -> DataFrame:
        """默认 rolling().apply() 逐行独立预测 -> 替换为顺序推理。

        每个预测窗口从 self._last_target_position(上一窗口末尾)开始;
        首次调用时:live(Dry-run/实盘)从 Trade 状态解析初始仓位,回测初始化为 0。
        """
        if self._last_target_position is None:
            if self.live:
                from rl_platform.dryrun_state import get_initial_position_live

                self._last_target_position = get_initial_position_live(dk.pair)
            else:
                self._last_target_position = 0
        predictor = SequentialPositionPredictor(model, window_size=self.CONV_WIDTH)
        predictor.current_position = int(self._last_target_position)
        actions = predictor.predict_frame(dataframe)
        self._last_target_position = int(predictor.current_position)
        logger.info(
            "RouteC 顺序推理: 窗口行数=%s, 窗口末目标仓位=%s",
            len(dataframe), self._last_target_position,
        )
        return DataFrame(actions, index=dataframe.index, columns=dk.label_list)
