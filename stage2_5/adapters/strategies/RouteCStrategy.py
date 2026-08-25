"""阶段 2.5 路线 C:Freqtrade 策略薄适配层。

特征:少量因果特征(收益/滚动波动率/价格相对均值/原始 OHLC 供环境用),
全部只使用当前及过去数据;目标仓位列 &-target_position 由 RouteCModel
顺序推理填充。信号转换只做"目标状态变化 -> enter/exit",不加额外 shift,
成交时机完全交给 Freqtrade 回测引擎自身的 shift(1)(open[t+1])。
"""

import sys
from pathlib import Path

from pandas import DataFrame

from freqtrade.strategy import IStrategy

PROJ_ROOT = Path(__file__).resolve().parents[2]
SRC_DIR = PROJ_ROOT / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from rl_platform.signal_convert import target_to_signals  # noqa: E402


class RouteCStrategy(IStrategy):
    """
    阶段 2.5 路线 C 验证策略(非生产用途,不做收益评估)。
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

    def feature_engineering_expand_all(
        self, dataframe: DataFrame, period: int, metadata: dict, **kwargs
    ) -> DataFrame:
        # 阶段 2.5 不使用 period 展开特征(indicator_periods_candles 为空)
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
        # 环境价格来源(BaseReinforcementLearningModel.build_ohlc_price_dataframes 约定)
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
        dataframe = self.freqai.start(dataframe, metadata, self)
        return dataframe

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df = target_to_signals(df)
        df.loc[df["do_predict"] != 1, "enter_long"] = 0
        return df

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        df = target_to_signals(df)
        df.loc[df["do_predict"] != 1, "exit_long"] = 0
        return df
