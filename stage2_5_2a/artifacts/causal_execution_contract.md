# 阶段 2.5.2a 因果市场执行合同(execution_mode = market_open_causal)

## 冻结的执行合同

时间语义(任务书第一节):

```
K 线 t 完整收盘
→ 模型观察所有截至 t 的信息
→ 模型输出目标仓位
→ 在 open[t+1] 形成市场成交
→ 新仓位承担 open[t+1] 到 close[t+1] 的价格变化
→ 得到 close[t+1] 时的净值与奖励
```

执行价格白名单(唯一允许的依赖):

- open[t+1];
- 交易方向;
- 执行前已固定的 simulated_slippage_bps;
- 执行前已固定的价格 tick;
- 手续费配置。

禁止依赖:high[t+1]、low[t+1]、close[t+1]、后续任意 K 线、
某笔订单最终是否会被 K 线覆盖。

## 有效成交价公式(方向不利 tick 取整)

```
买入: effective_price = ceil_to_tick(open[t+1] × (1 + simulated_slippage_bps / 10000))
卖出: effective_price = floor_to_tick(open[t+1] × (1 − simulated_slippage_bps / 10000))
```

- 买入向上取整、卖出向下取整(Decimal 整数格往返,禁止 round-half-even);
- 取整只可能让成交价对交易者更不利(market_execution 内部硬校验,fail closed);
- price_tick=0 表示不量化(纯模拟环境);
- tick_rounding_version = side_aware_ceil_floor_v1。

## simulated_slippage_bps 语义边界

预先设定的有效市场冲击/滑点压力参数,只属于训练与离线压力环境;
不是历史 K 线中的真实限价成交价格,不要求位于该根 K 线 high/low 内。
Freqtrade live 使用交易所真实回报价格,simulated_slippage_bps 不改变
live 市场订单价格。非零滑点不声称被 Freqtrade 历史回测精确复现
(见 simulated_slippage_monotonicity.json)。

## 终端清算(工作包 C)

最后一个执行周期结束于 close[last]:

- 最后一根 K 线内的持仓先承担 open → close 收益;
- 清算发生在 close 后,基准价 = close[last];
- 清算使用与普通市场卖出完全相同的 simulated_slippage_bps、
  floor_to_tick 取整、卖出手续费:
  `floor_to_tick(close[last] × (1 − simulated_slippage_bps/10000))`;
- 最终全部为现金;reward telescoping:
  sum(unscaled_log_rewards) == log(final_cash / initial_cash)
  (20 次随机 episode 实测最大绝对误差 < 1e-12,烟雾实测 5.6e-16);
- 不存在"持有到 Episode 结束可以免滑点退出"的奖励漏洞。

## 与 Freqtrade 2026.7 的对齐(源码依据,commit 52bc96f)

- backtesting.py:551-567:信号列 shift(1)——信号 t 移到执行行 t+1;
- backtesting.py:1039-1057:custom_entry_price 仅 order_type=="limit"
  分支被调用;市场订单 propose_rate 保持 row[OPEN_IDX];
- backtesting.py:596:exit_signal 的 close_rate = row[OPEN_IDX];
- backtesting.py:788-789:_get_order_filled 闭区间 low<=rate<=high,
  合法 OHLC 下 open 恒在区间内 → 下单当根成交;
- exchange.py:1042:price_to_precision(ROUND):出场侧价格精度往返,
  数据价格 snap 到 tick 网格后不变;
- 隔离实验(纯 vendor MinimalMarketStrategy + CLI 回测真实 BTC 数据):
  入场成交价全部精确等于执行 bar 的 open。
- 精确 parity 只在 simulated_slippage_bps = 0 时要求:
  四轮(宽/合法窄/零振幅/零费)信号数/交易数/时间/价格(1e-12)/
  单笔收益/终值递推全部逐笔一致(zero_slippage_freqtrade_parity.md)。

## 旧合同的废弃(legacy_noncausal_not_for_training)

阶段 2.5.2 的 bar 内一 tick 执行合同(price_clamp.bar_executable_price):

- 请求滑点价触及执行 bar 最终 high/low 边界时向 bar 内移动一格,
  bar 容纳不下时 fallback open;
- 依赖执行 K 线最终 high/low 反向修改成交价——**未来信息泄漏**
  (成交决策使用了 t+1 收盘后才知道的区间端点),且"保证当根成交"
  依赖订单会被 K 线覆盖这一未来事实;
- 已从生产调用路径移除(ledger 市场路径、RouteCStrategy 价格钩子、
  实验入口),保留在 price_clamp.py 仅供历史回归测试显式选择;
- 调用图保护:tests/freqai_rl_stage2_5_2a/test_market_execution_causality.py
  monkeypatch bar_executable_price 为"调用即失败",causal 路径零调用,
  legacy 路径确实调用(区分能力证明);
- 2.5.2 的窄 K 线根因报告(narrow_bar_root_cause.md)保留为历史研究记录。

## 生产调用图(阶段 2.5.2a)

```
AlignedLongFlatEnv.step(action)
  → ledger.apply_target(action, open[t+1])        # 不接收 high/low
    → market_execution.buy_market_price / sell_market_price
  → terminated: ledger.liquidate(close[last])      # 与普通卖出同成本
RouteCStrategy: order_types entry/exit = market
  (不定义 custom_entry_price / custom_exit_price /
   不缓存执行 K 线 high/low)
RouteCModel: execution_mode 强制 market_open_causal(配置 legacy 即报错)
experiments/freqai_rl_stage2_5_2a: 唯一执行模式,指纹含执行合同
```
