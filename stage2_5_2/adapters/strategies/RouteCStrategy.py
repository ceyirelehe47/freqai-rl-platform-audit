"""阶段 2.5.2 路线 C:Freqtrade 策略薄适配层(阶段 2.5/2.5.1 基础上加固)。

特征:少量因果特征(收益/滚动波动率/价格相对均值/原始 OHLC 供环境用),
全部只使用当前及过去数据;目标仓位列 &-target_position 由 RouteCModel
顺序推理填充。

阶段 2.5.1 加固:
- 工作包 C:custom_entry_price / custom_exit_price 从渲染后的 Route C 配置
  (freqai.route_c.slippage_bps)读取确定性滑点;order_types 显式 limit。

阶段 2.5.2 加固:
- 工作包 B(live 只处理最新一行):dry-run/live 下 populate_* 整表清零后
  只在最新一行生成信号(signal_convert.latest_row_signals),输入为
  真实执行状态(execution_state 七态)+ 最新目标 + 最新 do_predict;
  历史/回填行一律无信号。backtest 走 targets_to_signals 顺序扫描,
  两条路径分开实现,不靠同一循环兼容。
- 工作包 B(目标反转取消):adjust_entry_price / adjust_exit_price 官方
  扩展点(freqtradebot.manage_open_orders -> replace_order ->
  strategy.adjust_order_price):挂单期间目标反转时返回 None = 官方语义
  「取消且不替换」;do_predict != 1 时保持 current_order_rate(不因无效
  预测取消订单);零成交 entry 取消后上游删除 trade,部分成交则保留
  已成交暴露,下一 heartbeat 按实际暴露重新决策。
- 工作包 D(执行合同):freqai.route_c.price_tick > 0 时,custom 价格由
  price_clamp.bar_executable_price 决定(请求滑点价触及当根 high/low 时
  按 tick 向 bar 内部移动,bar 容纳不下时 fallback open),与环境
  (AlignedLongFlatEnv -> LongFlatLedger)使用同一公共执行价格函数。
  当前 bar 的 high/low 从 dp.get_analyzed_dataframe 按 current_time 定位;
  定位不到(dry-run 实时 ticker 价)或未配置 tick 时退回旧 bps 公式。

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
    阶段 2.5.2 路线 C 验证策略(非生产用途,不做收益评估)。
    """

    timeframe = "1h"
    can_short = False
    # 执行 bar OHLC 缓存(pair -> {date: (high, low, open)});populate 时重建
    _route_c_bars: dict = {}

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
        # 执行合同支撑数据(工作包 D):缓存每根 bar 的 OHLC 供 custom 价格钩子
        # 定位「执行 bar」。回测模式的 dp.get_analyzed_dataframe 按防未来函数
        # 切片、不含当前 bar,不能用于此目的;populate 阶段拿到的 df 是全量数据,
        # 此缓存只在执行模拟(custom_entry/exit_price 按当前 bar 求 bar 内价)
        # 中按 current_time 读取当前行,不向模型提供任何未来特征。
        self._route_c_bars[metadata.get("pair", "")] = {
            ts: (h, lo, o)
            for ts, h, lo, o in zip(
                dataframe["date"], dataframe["high"],
                dataframe["low"], dataframe["open"], strict=True,
            )
        }
        return dataframe

    # ------------------------------------------------------------- 信号生成
    @property
    def _is_live_runmode(self) -> bool:
        return self.dp is not None and self.dp.runmode in LIVE_RUNMODES

    def _apply_signals(self, df: DataFrame, metadata: dict) -> DataFrame:
        """双路径信号生成(工作包 B):live 只处理最新一行,backtest 顺序扫描。"""
        if self._is_live_runmode:
            from rl_platform.execution_state import get_live_execution_snapshot

            pair = metadata.get("pair", "")
            snap = get_live_execution_snapshot(pair)
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
                "RouteC live 信号: state=%s intent=%s 暴露=%s",
                snap.state, intent, snap.filled_amount,
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

    # ------------------------------------- 目标反转取消(工作包 B 官方扩展点)
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

        - 目标 1:维持现有挂单(current_order_rate);
        - 目标 0:返回 None -> freqtradebot.handle_replace_order 取消剩余入场,
          零成交且无成交单时上游删除 trade;部分成交则保留实际暴露,
          下一 heartbeat 按实际暴露(PARTIAL_ENTRY/LONG)重新决策;
        - do_predict != 1 或无目标数据:维持挂单(不因无效预测取消订单)。
        - 仅 DRY_RUN/LIVE 生效:backtest 的 dp.get_analyzed_dataframe 返回
          整段已处理 dataframe(无逐行语义),反转取消是 live 循环行为,
          回测路径保持基类默认(维持 current_order_rate)。
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
        do_predict != 1 时维持挂单。仅 DRY_RUN/LIVE 生效(理由同
        adjust_entry_price)。
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

    # ------------------------------------------------- 确定性滑点(工作包 C/D)
    @property
    def route_c_slippage_bps(self) -> float:
        """滑点从渲染后的 Route C 配置读取,不在策略中写死。"""
        freqai_conf = (self.config or {}).get("freqai", {})
        return float((freqai_conf.get("route_c") or {}).get("slippage_bps", 0.0))

    @property
    def route_c_price_tick(self) -> float:
        """执行合同价格 tick(0 = 未配置,退回旧边界 clamp 语义)。"""
        freqai_conf = (self.config or {}).get("freqai", {})
        return float((freqai_conf.get("route_c") or {}).get("price_tick", 0.0))

    def _bar_hl(self, pair: str, current_time) -> tuple[float | None, float | None]:
        """定位 current_time 所在 bar 的 (high, low);定位失败返回 (None, None)。

        优先使用 populate 阶段缓存的 OHLC 地图(回测可用;回测的
        dp.get_analyzed_dataframe 被防未来切片,永远查不到当前 bar),
        缓存未命中(dry-run 实时)时退回 dp。
        """
        bar = self._route_c_bars.get(pair, {}).get(current_time)
        if bar is not None:
            return float(bar[0]), float(bar[1])
        df, _ = self.dp.get_analyzed_dataframe(pair, self.timeframe)
        if df is None or len(df) == 0 or "date" not in df.columns:
            return None, None
        try:
            row = df.loc[df["date"] == current_time]
        except (TypeError, ValueError):
            return None, None
        if len(row) == 0:
            return None, None
        return float(row["high"].iloc[0]), float(row["low"].iloc[0])

    def _executable_price(self, side: str, pair: str, current_time,
                          proposed_rate: float) -> float:
        """工作包 D 执行合同:与环境同一公共执行价格函数。"""
        from rl_platform.price_clamp import bar_executable_price

        bps = self.route_c_slippage_bps
        tick = self.route_c_price_tick
        if tick <= 0.0 or bps == 0.0:
            # 未配置执行合同或零滑点:0bps 与回测器恒等路径一致,直接原价
            return proposed_rate if bps == 0.0 else proposed_rate * (
                1.0 + (bps / 10000.0 if side == "buy" else -bps / 10000.0)
            )
        high, low = self._bar_hl(pair, current_time)
        if high is None or low is None:
            # 定位不到当根 bar(如 dry-run 实时 ticker 价):退回旧 bps 请求价
            return proposed_rate * (
                1.0 + (bps / 10000.0 if side == "buy" else -bps / 10000.0)
            )
        exec_price, _requested, _moved, _fb = bar_executable_price(
            side, proposed_rate, high, low, bps, tick
        )
        return exec_price

    def custom_entry_price(
        self, pair: str, trade, current_time, proposed_rate: float,
        entry_tag, side, **kwargs,
    ):
        """买入请求价:执行合同(tick>0)或 open*(1+bps/10000)(旧语义)。"""
        return self._executable_price("buy", pair, current_time, proposed_rate)

    def custom_exit_price(
        self, pair: str, trade, current_time, proposed_rate: float,
        current_profit, exit_tag, **kwargs,
    ):
        """卖出请求价:执行合同(tick>0)或 open*(1-bps/10000)(旧语义)。"""
        return self._executable_price("sell", pair, current_time, proposed_rate)
