"""阶段 2.5.1 路线 C:Freqtrade 策略薄适配层(在阶段 2.5 基础上加固)。

特征:少量因果特征(收益/滚动波动率/价格相对均值/原始 OHLC 供环境用),
全部只使用当前及过去数据;目标仓位列 &-target_position 由 RouteCModel
顺序推理填充。

阶段 2.5.1 加固:
- 工作包 C:正式接入确定性滑点 —— custom_entry_price / custom_exit_price
  从渲染后的 Route C 配置(freqai.route_c.slippage_bps)读取,入场退出同值,
  slippage_bps=0 时返回原始 proposed rate,不影响手续费计算;
  order_types 显式设置 limit(自定义价格钩子仅对 limit 单生效)。
- 工作包 F:信号生成改为"有效目标 -> 信号"状态机(targets_to_signals):
  回测顺序扫描模拟仓位;dry-run/live 每个 heartbeat 从 Freqtrade Trade
  持久层读取真实仓位作为扫描起点,不依赖上一根预测目标判断订单是否成交。
  populate_entry_trend / populate_exit_trend 重复调用结果一致(幂等)。

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

from rl_platform.signal_convert import targets_to_signals  # noqa: E402

LIVE_RUNMODES = {RunMode.DRY_RUN, RunMode.LIVE}


class RouteCStrategy(IStrategy):
    """
    阶段 2.5.1 路线 C 验证策略(非生产用途,不做收益评估)。
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
    # 自定义价格钩子(custom_entry_price/custom_exit_price)仅对 limit 单生效
    order_types = {
        "entry": "limit",
        "exit": "limit",
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

    # ------------------------------------------------------------- 信号生成
    def _current_position_for_signals(self, metadata: dict) -> int:
        """信号状态机的仓位起点:回测 0;dry-run/live 从 Trade 表读取真实仓位。"""
        pair = metadata.get("pair", "")
        if self.dp is not None and self.dp.runmode in LIVE_RUNMODES:
            from rl_platform.dryrun_state import get_initial_position_live

            return int(get_initial_position_live(pair))
        return 0

    def _rebuild_signals(self, df: DataFrame, metadata: dict) -> DataFrame:
        """幂等信号重建:先清零 enter/exit 列再统一生成(工作包 F 二十一节)。"""
        return targets_to_signals(
            df, initial_position=self._current_position_for_signals(metadata)
        )

    def populate_entry_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return self._rebuild_signals(df, metadata)

    def populate_exit_trend(self, df: DataFrame, metadata: dict) -> DataFrame:
        return self._rebuild_signals(df, metadata)

    # ------------------------------------------------- 确定性滑点(工作包 C)
    @property
    def route_c_slippage_bps(self) -> float:
        """滑点从渲染后的 Route C 配置读取,不在策略中写死。"""
        freqai_conf = (self.config or {}).get("freqai", {})
        return float((freqai_conf.get("route_c") or {}).get("slippage_bps", 0.0))

    def custom_entry_price(
        self, pair: str, trade, current_time, proposed_rate: float,
        entry_tag, side, **kwargs,
    ):
        """买入请求价 = open[t+1] * (1 + bps/10000);0 bps 时返回原始 rate。"""
        bps = self.route_c_slippage_bps
        if bps == 0.0:
            return proposed_rate
        return proposed_rate * (1.0 + bps / 10000.0)

    def custom_exit_price(
        self, pair: str, trade, current_time, proposed_rate: float,
        current_profit, exit_tag, **kwargs,
    ):
        """卖出请求价 = open[t+1] * (1 - bps/10000);0 bps 时返回原始 rate。"""
        bps = self.route_c_slippage_bps
        if bps == 0.0:
            return proposed_rate
        return proposed_rate * (1.0 - bps / 10000.0)
