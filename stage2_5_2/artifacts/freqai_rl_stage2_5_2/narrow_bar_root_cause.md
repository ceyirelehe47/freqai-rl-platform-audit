# 窄 K 线成交不一致根因诊断(阶段 2.5.2 工作包 D,更正阶段 2.5.1 结论)

## 现象

阶段 2.5.1 窄 K 线轮(±0.5bps 振幅,5bps 请求滑点)出现回测交易数少于环境
(bt=13 vs env=17),当时报告将其归因为「回测器对恰等边界的限价卖单不在
当根撮合(需价格严格穿越挂单价)」。

**该归因是错误的。** 固定 commit 52bc96f 的撮合判定是闭区间:

```python
# vendor/freqtrade/freqtrade/optimize/backtesting.py:788
def _get_order_filled(self, rate: float, row: tuple) -> bool:
    """Rate is within candle, therefore filled"""
    return row[LOW_IDX] <= rate <= row[HIGH_IDX]
```

恰等于 low/high 的订单价在当根即撮合。阶段 2.5.2 用受控零振幅数据
(每根 bar open=high=low=close)复现了同样的交易数缺口,逐笔定位到真实根因。

## 真实根因(两个叠加机制)

### 机制一:clamp 到边界后 price_to_precision 的十进制往返产生 1 ulp 漂移

窄 K 线下,策略的滑点请求价(如 101.11×0.9995=101.0594)低于当根 low,
回测器按规则 clamp 到边界:`close_rate = max(close_rate, row[LOW_IDX])`
(optimize/backtesting.py:_get_exit_for_signal),随后 `_exit_trade` 再执行
`close_rate = price_to_precision(close_rate, ...)`。

数据侧的边界浮点(合成数据 `k×0.01` 的算术浮点,如 101.10000000000001)
经 price_to_precision 的 Decimal 往返后得到的是另一枚浮点
(float("101.1") = 101.10000000000001… 的最短表示浮点),两者相差 1 ulp:

- 若订单价落在 bar 边界之下 1 ulp:`low <= rate` 不成立;
- 若落在边界之上 1 ulp:`rate <= high` 不成立;

两种情况闭区间判定都失败,订单在当根不成交而滞留。

### 机制二:滞留订单触发 unfilledtimeout 循环,占位吞掉后续入场

滞留的退出单在下一根 bar 被 `ft_check_timed_out`(默认 unfilledtimeout)
取消,trade 保持 open;之后每个出场信号重新挂单、再次因 1 ulp 漂移滞留。
期间该 pair 的每日入场信号被「每 pair 同时只能有一笔 open trade」规则
(backtest_loop 步骤 2:`len(LocalTrade.bt_trades_open_pp[pair]) == 0`)
全部吞掉。

受控复现(零振幅数据,本阶段探针):trade #9 的退出单自 2026-07-24 16:00
起连续 4 天按上述循环滞留/重挂,至 2026-07-28 16:00 才成交,期间
07-25/26/27/28 的 4 个入场信号全部丢失 —— 与 bt=13 vs env=17 的缺口
逐笔对应。

### 附:阶段 2.5.2 首轮实现中执行合同未生效的直接原因

执行合同(bar 内一 tick)初版通过 `dp.get_analyzed_dataframe` 定位当前
bar 的 high/low,但回测模式下该方法被防未来函数切片
(dataprovider.py:397-417,`__slice_index` 不含当前 bar),策略 custom
价格钩子永远查不到执行 bar,静默退回旧 bps 公式。修复:策略在
populate 阶段缓存每根 bar 的 OHLC 地图(仅执行模拟按 current_time 读
当前行,不向模型提供未来特征),custom 价格钩子优先查缓存。

## 执行合同如何消除该问题(本阶段验收结论)

`bar_executable_price`(rl_platform/price_clamp.py)两侧(环境与策略)
统一:

1. 请求滑点价触及边界时按 tick 整数格向 bar 内部移动一格
   (买入严格小于 high、卖出严格大于 low),订单价与边界之间至少隔
   一个完整 tick,1 ulp 漂移不可能跨越;
2. 所有输出价格规范化(round 10 位)到与 price_to_precision 十进制
   往返一致的同一浮点(数据侧价格同样规范到该网格);
3. bar 容纳不下内部价(单 tick/零振幅 bar)时 fallback 为当根 open:
   订单价与数据边界是同一浮点,闭区间判定按恒等成立,当根成交。

七轮 parity(含窄 K 线 ±0.5bps 两轮与零振幅一轮)信号数/交易数/
时间/价格/单笔收益逐笔一致,终值差完全由已知口径解释
(stake 递推费差 + amount 精度截断),详见 full_fill_parity.md。

## 验证命令

- 复现(legacy 语义):阶段 2.5.1 `test_route_c_slippage_live_strategy.py`
  窄轮(成交子集匹配,记录了当时的缺口);
- 修复(执行合同):阶段 2.5.2 `test_full_fill_parity.py::test_full_fill_parity_all_rounds`。
