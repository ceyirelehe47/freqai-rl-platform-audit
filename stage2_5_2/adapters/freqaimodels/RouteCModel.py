"""阶段 2.5.2 路线 C:FreqAI 薄适配模型(阶段 2.5/2.5.1 基础上加固)。

只覆盖官方支持的扩展点,把 FreqAI 的数据/窗口/模型生命周期接到
自定义对齐环境与顺序推理器上;不复制 FreqAI 内部源码。

覆盖的方法与理由:
- set_train_and_eval_environments():默认实现构造 Base5ActionRLEnv 家族环境,
  其 step() 时间语义(open[t+2] 执行)与记账不符合本任务;替换为 AlignedLongFlatEnv
  (阶段 2.5.2 起传入 price_tick 执行合同)。
- fit():默认 ReinforcementLearner.fit 挂 MaskableEvalCallback(本环境无动作掩码),
  且 PPO device=auto 会选 GPU;改为 run_ppo_fit:显式 resolved PPO 参数、
  rounded rollout 预算、num_timesteps 硬校验、预算记录落盘(2.5.1 工作包 A)。
- rl_model_predict():默认 rolling().apply() 逐行独立预测,无法传递当前目标仓位;
  替换为 SequentialPositionPredictor 顺序推理:
  * backtest:跨子窗口经实例属性延续状态(targets_to_signals 回测路径);
  * live:live_predict_frame 历史回填与实时决策分离,每个 heartbeat 从
    Trade/Order 解析真实执行状态(阶段 2.5.2 工作包 A:get_model_position_live
    七态映射;INCONSISTENT 时 fail closed,不调用模型、不静默选择);
  * 接收 dk.do_predict mask,无效行不更新目标状态(2.5.1 工作包 F)。

不覆盖 train()/predict():官方前处理(特征过滤/缩放/OHLC 提取/缓存)全部复用。

dk.do_predict 生成时机(源码确认,2.5.1 工作包 F 十九节调查):
BaseReinforcementLearningModel.predict 在调用 rl_model_predict 之前执行
dk.filter_features(training_filter=False),其中把含 NaN 的预测行标记为 0
(data_kitchen.py:285),长度与预测 dataframe 完全对齐;datasieve transform
的 outlier 数组被上游 RL 分支丢弃,但本阶段配置禁用 SVM/DI
(use_SVM_to_remove_outliers=false、DI_threshold=0),NaN 检查即完整语义。
"""

import sys
from pathlib import Path
from typing import Any

from pandas import DataFrame
from stable_baselines3.common.monitor import Monitor

from freqtrade.freqai.RL.BaseReinforcementLearningModel import BaseReinforcementLearningModel
from freqtrade.freqai.data_kitchen import FreqaiDataKitchen

PROJ_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJ_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rl_platform.env import AlignedLongFlatEnv  # noqa: E402
from rl_platform.guards import assert_conv_width  # noqa: E402
from rl_platform.inference import SequentialPositionPredictor  # noqa: E402
from rl_platform.live_inference import live_predict_frame  # noqa: E402
from rl_platform.ppo_params import resolve_ppo_params, run_ppo_fit  # noqa: E402

import logging  # noqa: E402

logger = logging.getLogger(__name__)


class RouteCModel(BaseReinforcementLearningModel):
    """路线 C 适配层:AlignedLongFlatEnv + 顺序推理 + 显式预算 PPO。"""

    def __init__(self, **kwargs) -> None:
        # 检查点 2/4:RouteCModel 构造(在父类规范化配置前后各检查一次)
        assert_conv_width(
            (kwargs.get("config") or {}).get("freqai", {}).get("conv_width", 1),
            source="RouteCModel.__init__(config)",
        )
        super().__init__(**kwargs)
        rc = self.freqai_info.get("route_c", {})
        self.rc_config = {
            "slippage_bps": float(rc.get("slippage_bps", 0.0)),
            "initial_cash": float(rc.get("initial_cash", 100.0)),
            "reward_scale": float(rc.get("reward_scale", 1.0)),
            "seed": int(rc.get("seed", 42)),
            "device": str(rc.get("device", "cpu")),
            # 阶段 2.5.2 工作包 D:执行合同价格 tick(0 = 旧边界 clamp 语义)
            "price_tick": float(rc.get("price_tick", 0.0)),
            # 阶段 2.5.2 工作包 A:实际成交数量判定 epsilon
            "amount_epsilon": float(rc.get("amount_epsilon", 1e-12)),
        }
        # 唯一 PPO 参数来源:freqai.route_c.ppo(冲突即报错,2.5.1 工作包 A)
        self.resolved_ppo = resolve_ppo_params(self.freqai_info)
        assert_conv_width(self.CONV_WIDTH, source="RouteCModel.__init__(CONV_WIDTH)")
        # 跨 FreqAI backtest 子窗口的顺序推理状态:
        # freqai_interface.start_backtesting 在同一模型实例上按时间顺序调用
        # train()/predict(),实例属性可安全携带上一窗口最终目标仓位。
        # 语义限定(阶段 2.5.2 工作包 F):仅用于 backtest 跨窗口延续;
        # live 下只是展示目标的延续值,绝不能当作 live 实际仓位——live 的
        # 实际仓位每个 heartbeat 都从 Trade/Order 重新解析(execution_state)。
        self._last_target_position: int | None = None
        # 每窗 PPO 预算记录(2.5.1 工作包 A;证据脚本从模型目录 json 与此列表双路读取)
        self.ppo_budget_records: list[dict[str, Any]] = []
        # live heartbeat trace(2.5.1 工作包 G;测试与证据脚本读取)
        self.live_trace: list[dict[str, Any]] = []
        # live 最新执行状态快照(工作包 A/B;测试与证据脚本读取)
        self.live_execution_trace: list[dict[str, Any]] = []

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
        净值 log 奖励、终端强制清算、bar 内一 tick 执行合同(2.5.2 工作包 D)。"""
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
            price_tick=self.rc_config["price_tick"],
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
        """显式 PPO 训练(2.5.1 工作包 A):

        - 参数唯一来源 resolved_ppo_params(冲突/重复配置在 __init__ 即报错);
        - rounded rollout 预算 = ceil(base/n_steps)*n_steps;
        - 训练后硬校验 model.num_timesteps == rounded_budget;
        - 预算记录写入模型目录 ppo_budget.json 并汇入实例列表。
        """
        train_df = data_dictionary["train_features"]
        train_cycles = int(self.freqai_info["rl_config"]["train_cycles"])
        if self.activate_tensorboard:
            tb_path = Path(dk.full_path / "tensorboard" / dk.pair.split("/")[0])
        else:
            tb_path = None
        # dk.full_path 是模型根目录(每窗相同,写入会互相覆盖);
        # dk.data_path 才是每窗 sub-train 目录,预算记录按窗落盘。
        record_path = Path(dk.data_path) / "ppo_budget.json"
        model, record = run_ppo_fit(
            env=self.train_env,
            resolved=self.resolved_ppo,
            train_cycles=train_cycles,
            n_train_rows=len(train_df),
            tensorboard_log=tb_path,
            record_path=record_path,
        )
        self.ppo_budget_records.append({**record, "pair": dk.pair, "model_dir": str(dk.full_path)})
        logger.info(
            "RouteC PPO 训练完成: base=%s rounded=%s actual=%s rollouts=%s "
            "episode_resets=%s device=%s seed=%s",
            record["base_budget"], record["rounded_budget"], record["actual_num_timesteps"],
            record["n_rollouts"], record["episode_resets"],
            record["device"], record["seed"],
        )
        return model

    # ----------------------------------------------------------------- 推理
    def rl_model_predict(
        self, dataframe: DataFrame, dk: FreqaiDataKitchen, model: Any
    ) -> DataFrame:
        """默认 rolling().apply() 逐行独立预测 -> 替换为顺序推理。

        backtest:每窗从 self._last_target_position(上一窗口末尾,首次 0)开始,
        targets_to_signals 回测路径顺序扫描。
        live:live_predict_frame 历史回填(隔离状态)与实时决策分离;
        每个 heartbeat 通过 execution_state.get_model_position_live 从
        Trade/Order 重新解析真实仓位(阶段 2.5.2 工作包 A:七态映射,
        INCONSISTENT 时 fail closed 不调用模型)。
        两分支都接收 dk.do_predict mask:无效行不更新目标状态(2.5.1 工作包 F)。
        """
        dp = getattr(dk, "do_predict", None)
        if dp is not None and len(dp) != len(dataframe):
            raise RuntimeError(
                f"dk.do_predict 长度 {len(dp)} 与预测 dataframe 行数 {len(dataframe)} "
                "不一致,拒绝推理(2.5.1 工作包 F 对齐前提被破坏)"
            )

        if self.live:
            from rl_platform.execution_state import (
                get_live_execution_snapshot,
                get_model_position_live,
            )

            eps = self.rc_config["amount_epsilon"]
            actions, trace = live_predict_frame(
                model=model,
                dataframe=dataframe,
                pair=dk.pair,
                window_size=self.CONV_WIDTH,
                read_position_fn=lambda p: get_model_position_live(p, amount_epsilon=eps),
                do_predict=dp,
                fallback_target=self._last_target_position,
            )
            self._last_target_position = int(trace["latest_target"])
            self.live_trace.append(trace)
            # 记录同刻执行状态快照(工作包 A/B 证据:仓位映射可核对)
            snap = get_live_execution_snapshot(dk.pair, amount_epsilon=eps)
            self.live_execution_trace.append({
                "heartbeat": len(self.live_execution_trace),
                "mode": trace["mode"],
                "execution_state": snap.state,
                "filled_amount": snap.filled_amount,
                "model_position": snap.model_position,
                "latest_target": trace["latest_target"],
                "do_predict": trace["do_predict_latest"],
                "fail_closed": trace["fail_closed"],
            })
        else:
            if self._last_target_position is None:
                self._last_target_position = 0
            predictor = SequentialPositionPredictor(model, window_size=self.CONV_WIDTH)
            predictor.current_position = int(self._last_target_position)
            actions = predictor.predict_frame(dataframe, do_predict=dp)
            self._last_target_position = int(predictor.current_position)
            logger.info(
                "RouteC 顺序推理: 窗口行数=%s, 窗口末目标仓位=%s",
                len(dataframe), self._last_target_position,
            )
        return DataFrame(actions, index=dataframe.index, columns=dk.label_list)
