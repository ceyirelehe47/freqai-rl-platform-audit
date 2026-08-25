"""阶段 2.5.2a 路线 C:Freqtrade 策略薄适配层(execution_mode=market_open_causal)。

特征:少量因果特征(收益/滚动波动率/价格相对均值/原始 OHLC 供环境用),
全部只使用当前及过去数据;目标仓位列 &-target_position 由 RouteCModel
顺序推理填充。

阶段 2.5.2a 改造(工作包 B):
- 订单类型改为 market(入场/退出均市场订单):成交价由回测器/交易所决定,
  回测中市场单以执行 bar 的 open 成交(backtesting.py:1039-1057 仅 limit
  分支调用 custom_entry_price;:596 exit_signal 的 close_rate=row[OPEN_IDX];
  :551-567 信号 shift(1)),与环境 market_open_causal 合同在
  simulated_slippage_bps=0 时逐笔对齐;
- 移除 custom_entry_price / custom_exit_price / _route_c_bars 执行 K 线
  high/low 缓存(阶段 2.5.2 bar 内调价合同依赖执行 K 线最终 high/low,
  属未来信息,已废弃为 legacy_noncausal_not_for_training);
- simulated_slippage_bps 只属于训练与离线压力环境,不得改变 live 市场订单
  价格;Freqtrade live 使用交易所真实回报价格;
- amount_epsilon 与 RouteCModel 从同一最终配置 freqai.route_c.amount_epsilon
  读取(工作包 E),所有执行状态读取都通过 route_c_amount_epsilon 传参。

保留(阶段 2.5.2 工作包 B):
- live 只处理最新一行(signal_convert.latest_row_signals);
- adjust_entry_price / adjust_exit_price 官方扩展点的目标反转取消
  (None = 取消且不替换);do_predict != 1 时维持挂单。

成交时机完全交给 Freqtrade 回测引擎自身的 shift(1)(open[t+1]),
本层不加额外 shift。
"""

import sys
from pathlib import Path

from pandas import DataFrame

from freqtrade.enums import RunMode
from freqtrade.strategy import IStrategy

PROJ_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJ_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rl_platform.execution_state import DEFAULT_AMOUNT_EPSILON  # noqa: E402
from rl_platform.signal_convert import (  # noqa: E402
    DO_PREDICT_COL,
    TARGET_COL,
    latest_row_signals,
    targets_to_signals,
)

import logging  # noqa: E402

logger = logging.getLogger(__name__)

LIVE_RUNMODES = {RunMode.DRY_RUN, RunMode.LIVE}


class RouteCStrategy(IStrategy):
    """
    阶段 2.5.2a 路线 C 验证策略(market_open_causal 市场订单,非生产用途,
    不做收益评估)。
    """

    timeframe = "1h"
    can_short = False
    minimal_roi = {"0": 100}
    stoploss = -0.99
    use_exit_signal = True
    exit_profit_only = False
    ignore_roi_if_entry_signal = False
    startup_candle_count = 99
    process_only_new_candles = True
    position_adjustment_enable = False
    # 阶段 2.5.2a 工作包 B:市场订单抽象。custom_entry_price /
    # custom_exit_price 仅对 limit 单生效,本策略不再定义它们;
    # simulated_slippage_bps 不改变 live 市场订单价格。
    order_types = {
        "entry": "market",
        "exit": "market",
        "stoploss": "market",
        "stoploss_on_exchange": False,
    }

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        # 阶段 2.5 不使用 period 展开特征(indicator_periods_candles=[10] 仅绕过
        # 上游 dataprovider 空列表边界缺陷,expand_all 不产生新特征)
        return dataframe

    def feature_engineering_expand_basic(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        return dataframe

    def feature_engineering_standard(
        self, dataframe: DataFrame, metadata: dict, **kwargs
    ) -> DataFrame:
        ret1 = dataframe["close"].pct_change()
        dataframe["%-ret-1"] = ret1
        dataframe["%-ret-4"] = dataframe["close"].pct_change(4)
        dataframe["%-vol-24"] = ret1.rolling(24).std()
        dataframe["%-price-ma-ratio"] = (
            dataframe["close"] / dataframe["close"].rolling(24).mean() - 1
        )
        # 环境价格来源(BaseReinforcementLearningModel.build_ohlc_price_dataframes 约定);
        # high/low 仅用于已收盘 bar 的特征与环境数据,不参与成交价格
        dataframe["%-raw_open"] = dataframe["open"]
        dataframe["%-raw_high"] = dataframe["high"]
        dataframe["%-raw_low"] = dataframe["low"]
        dataframe["%-raw_close"] = dataframe["close"]
        return dataframe

    def set_freqai_targets(self, dataframe: DataFrame, metadata: dict, **kwargs) -> DataFrame:
        # 占位标签:真实值由 RouteCModel 顺序推理覆盖写入
        dataframe["&-target_position"] = 0
        return dataframe

    def populate_indicators(self, dataframe: DataFrame, metadata: dict) -> DataFrame:
        # 阶段 2.5.2a:不再缓存执行 K 线 high/low(bar 内调价合同已废弃)
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    # ------------------------------------------------------------- 信号生成
    @property
    def _is_live_runmode(self) -> bool:
        return self.dp is not None and self.dp.runmode in LIVE_RUNMODES

    @property
    def route_c_amount_epsilon(self) -> float:
        """实际成交数量判定 epsilon:与 RouteCModel 同一配置来源
        (freqai.route_c.amount_epsilon,工作包 E),不允许策略静默使用默认值。"""
        freqai_conf = (self.config or {}).get("freqai", {})
        return float((freqai_conf.get("route_c") or {}).get(
            "amount_epsilon", DEFAULT_AMOUNT_EPSILON
        ))

    def _apply_signals(self, df: DataFrame, metadata: dict) -> DataFrame:
        """双路径信号生成:live 只处理最新一行,backtest 顺序扫描。"""
        if self._is_live_runmode:
            from rl_platform.execution_state import get_live_execution_snapshot

            pair = metadata.get("pair", "")
            snap = get_live_execution_snapshot(
                pair, amount_epsilon=self.route_c_amount_epsilon
            )
            if TARGET_COL in df.columns and len(df) > 0:
                target = int(df[TARGET_COL].iloc[-1])
                dp = int(df[DO_PREDICT_COL].iloc[-1]) \
                    if DO_PREDICT_COL in df.columns else 1
                df, intent = latest_row_signals(df, snap.state, target, dp)
            else:
                # 模型目标尚未就绪:整表清零,不生成任何信号
                df["enter_long"] = 0
                df["enter_tag"] = None
                df["exit_long"] = 0
                intent = "no_target_column"
            logger.info(
                "RouteC live 信号: state=%s intent=%s 暴露=%s amount_epsilon=%s",
                snap.state, intent, snap.filled_amount, self.route_c_amount_epsilon,
            )
            if snap.is_fail_closed:
                logger.error(
                    "执行状态 INCONSISTENT,本 heartbeat 不生成任何订单:\n%s",
                    snap.describe(),
                )
            return df
        # backtest 路径:顺序扫描模拟仓位(初始 0,跨窗状态由模型层延续)
        return targets_to_signals(df, initial_position=0)

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return self._apply_signals(df, metadata)

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return self._apply_signals(df, metadata)

    # ------------------------------------- 目标反转取消(官方扩展点)
    def _latest_route_c_target(self, pair: str) -> tuple[int | None, int | None]:
        """读取本 heartbeat 已分析 dataframe 最新行的 (目标仓位, do_predict)。

        adjust_* 回调在 manage_open_orders 阶段调用,晚于 strategy.analyze,
        dp.get_analyzed_dataframe 返回的就是本 heartbeat 的分析结果。
        """
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) == 0 or TARGET_COL not in df.columns:
            return None, None
        target = int(df[TARGET_COL].iloc[-1])
        dp = int(df[DO_PREDICT_COL].iloc[-1]) if DO_PREDICT_COL in df.columns else 1
        return target, dp

    def adjust_entry_price(
        self, trade, order, pair: str, current_time, proposed_rate: float,
        current_order_rate: float, entry_tag, side, **kwargs,
    ):
        """挂单期间的目标反转取消(官方语义:None = 取消且不替换)。

        阶段 2.5.2a:市场订单路径下本回调不调整价格(无 bar 内调价),
        仅承载「取消 / 维持」语义:
        - 目标 1:维持现有挂单(current_order_rate);
        - 目标 0:返回 None -> freqtradebot.handle_replace_order 取消剩余入场,
          零成交且无成交单时上游删除 trade;部分成交则保留实际暴露,
          下一 heartbeat 按实际暴露(PARTIAL_ENTRY/LONG)重新决策;
        - do_predict != 1 或无目标数据:维持挂单(不因无效预测取消订单);
        - 仅 DRY_RUN/LIVE 生效(回测 dp 无逐行语义,保持基类默认)。
        """
        if not self._is_live_runmode:
            return current_order_rate
        target, dp = self._latest_route_c_target(pair)
        if dp is not None and dp != 1:
            return current_order_rate
        if target == 0:
            logger.info(
                "RouteC 目标反转:请求取消 %s 剩余入场挂单 %s",
                pair, order.order_id if order else "?",
            )
            return None
        return current_order_rate

    def adjust_exit_price(
        self, trade, order, pair: str, current_time, proposed_rate: float,
        current_order_rate: float, entry_tag, side, **kwargs,
    ):
        """退出挂单期间目标反转回多头:返回 None 取消剩余退出,不替换。

        取消后仍有暴露 -> 下一 heartbeat 状态回到 LONG;本 heartbeat
        不生成新 entry(latest_row_signals 已保证)。
        do_predict != 1 时维持挂单。仅 DRY_RUN/LIVE 生效。
        """
        if not self._is_live_runmode:
            return current_order_rate
        target, dp = self._latest_route_c_target(pair)
        if dp is not None and dp != 1:
            return current_order_rate
        if target == 1:
            logger.info(
                "RouteC 目标反转:请求取消 %s 剩余退出挂单 %s",
                pair, order.order_id if order else "?",
            )
            return None
        return current_order_rate
