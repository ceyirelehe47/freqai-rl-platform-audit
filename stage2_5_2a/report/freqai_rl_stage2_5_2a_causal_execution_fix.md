# 阶段 2.5.2a 报告:因果执行、终端奖励与完整 FreqAI Live 编排修复

- 日期:2026-08-25/26(UTC)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,工作树 clean(零修改)
- 判定:**PASS**
- 测试:271 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81);PPO 回归烟雾通过
- 是否允许进入阶段 2.6:**允许**(本任务结束即停,未开始 2.6)

---

## 1. 执行摘要

阶段 2.5.2 的全局 PASS 被本阶段重新审查:其 bar 内一 tick 执行合同
(bar_executable_price)在成交价决策中读取执行 K 线的**最终 high/low**,
属未来信息泄漏;Episode 终端清算免滑点构成免费退出;live 集成测试
绕过了 self.freqai.start()。本阶段以
**execution_mode = market_open_causal** 因果市场成交合同整体取代旧合同:
成交价只依赖 open[t+1]、方向、执行前固定的 simulated_slippage_bps 与
price_tick(买入 ceil_to_tick、卖出 floor_to_tick),环境与策略全部
切换到市场订单;终端清算与普通卖出完全同成本;live 推理 INCONSISTENT
完全 fail-closed;amount_epsilon 四处同源;base fee 部分成交按上游
safe_amount_after_fee 口径;全部 synthetic 数据满足合法 OHLC;缓存
manifest 后处理失败致命化(退出码 4 + quarantine);新增真正经过
self.freqai.start() 的 Dry-run FreqtradeBot 完整链路集成测试。
零滑点市场订单四轮完整 parity(含合法窄 K 线与零振幅轮)逐笔一致。

## 2. PASS / FAIL

**PASS**(27 项 PASS 条件逐项对表见第 22 节;10 项 FAIL 条件零命中)。

## 3. 阶段 2.5.2 PASS 被重新审查的原因

2.5.2 的七轮 parity 建立在"请求滑点价触及当根 high/low 边界时向 bar
内移动一格、bar 容纳不下时 fallback open"的执行合同上。该合同:

1. 成交价是执行 K 线**最终**区间端点的函数——决策时(t+1 开盘前)不可知;
2. "保证当根成交"依赖"订单会被该 K 线覆盖"这一未来事实;
3. 为对齐该合同,策略层缓存了执行 K 线 high/low 供 custom price 钩子使用,
   把未来数据接入了订单价格路径。

违反因果成交语义。2.5.2 的窄 K 线根因报告(1 ulp 漂移)是真实工程发现,
但其修复方向(向 bar 内调价)本身不合法。本阶段废弃该合同(保留为
legacy_noncausal_not_for_training 仅供历史回归),根因报告作为历史研究
记录保留,不篡改。

## 4. 旧 bar 内执行合同的未来信息问题

见上节与 `artifacts/freqai_rl_stage2_5_2a/causal_execution_contract.md`。
区分能力证明:`test_future_high_low_invariance.py::test_legacy_mode_is_high_low_sensitive`
在窄 K 线场景下,legacy 模式的成交价确实随 high/low 改变(对照组),
而 causal 模式完全不变——不变性测试不是恒等空测试。

## 5. 新 market_open_causal 合同

时间语义、价格白名单、禁止依赖清单与公式见
`causal_execution_contract.md`。核心实现:

- `src/rl_platform/market_execution.py`(新):buy_market_price /
  sell_market_price / ceil_to_tick / floor_to_tick;函数签名与实现均不
  接收 high/low;取整改善即 RuntimeError(fail closed);输入校验
  (正价格、非负滑点/tick、有限性);诊断含 requested/effective/
  actual_effective_slippage_bps/tick_rounding。
- `ledger.py`:execution_mode 字段(默认 market_open_causal);
  apply_target(target, open) 市场路径不接收 high/low;
  apply_target_legacy / liquidate_legacy 仅供历史测试。
- `env.py`:execution_mode 参数;causal 模式 prices 只要求 open/close;
  step 不把执行 bar high/low 传入记账。

## 6. tick 取整

Decimal 整数格往返(`ceil/floor(price/tick)×tick`),买 ceil 卖 floor,
禁 round-half-even;性质测试(500 组随机)取整后永不优于请求价;
恰在网格上的价恒等(63620.51→63620.51),零滑点下 effective==open。
`market_price_rounding.json` 记录样本。

## 7. high/low 不变性(硬性验收)

两份同 open/close/动作/fee/滑点/tick 数据,high/low 换成不同合法值
(含 high=1e9 / low=1e-6 极端):每步成交方向、成交价格、手续费、reward、
最终净值**逐位全等**;参数矩阵 bps{0,5}×tick{0,0.01}。
`future_high_low_invariance.json`。

## 8. Freqtrade 市场订单时间对齐(源码 + 实验)

源码(commit 52bc96f):
- backtesting.py:551-567 信号 shift(1);
- :1039-1057 custom_entry_price 仅 limit 分支,市场单 propose_rate=row[OPEN_IDX];
- :596 exit_signal close_rate=row[OPEN_IDX];
- :788-789 闭区间撮合,合法 OHLC 下 open 恒成交于当根;
- exchange.py:1042 出场 price_to_precision(ROUND),tick 网格数据往返不变。

实验:纯 vendor MinimalMarketStrategy(无本项目代码)CLI 回测真实 BTC
数据,入场价全部精确==执行 bar open。结论:**市场订单回测为 open[t+1]
对齐**,无额外 shift,entry/exit 时间与环境一致。B.5 的 FAIL 分支未触发。

(过程中排除的一次误报:btanalysis 曾读到 2.5.2 时代的旧回测结果文件
(--export none 不写新文件),其 63634.26 等价格是旧 limit+调价合同的产物;
修正为 --export trades 后按本次结果验证,零滑点断言全过。)

## 9. simulated slippage 与真实 exchange fill 的边界

simulated_slippage_bps=0/fee>0 是 2.6 默认。非零滑点只做环境压力测试
(`simulated_slippage_monotonicity.json`:公式 + 逐笔成本单调不减 +
终值 0>5>10bps 严格下降),**不声称 Freqtrade 已精确复现该模拟滑点**;
Freqtrade live 使用交易所真实回报价格,simulated_slippage_bps 不改变
live 市场订单价格(策略无任何价格钩子)。零滑点精确 parity 四轮
(`zero_slippage_freqtrade_parity.md`:宽/合法窄/零振幅/零费,
信号数==交易数==环境成交数、时间/价格 1e-12、单笔收益、终值递推
闭式 + 5e-6/笔精度预算,无成交子集比较)。

## 10. 终端清算(工作包 C)

最后一个执行周期结束于 close[last]:持仓先承担 open→close 收益,收盘后
以 floor_to_tick(close[last]×(1−bps/1e4)) 清算,支付与普通市场卖出
完全相同的滑点、tick 取整、手续费,最终全现金。七项测试全过:恒定价格
普通退出与终端退出同成本 / 倒数第二步退出 / 持有强制退出 / 同价单位成本
一致 / 终值随 0→5→10bps 单调下降 / 最后一步开多头支付双边成本 /
随机 episode 长度无免费套利。`terminal_liquidation_parity.json`。

## 11. reward telescoping

sum(unscaled_log_rewards) == log(final_cash/initial_cash):
5 种动作模式 × {0bps,5bps}×{tick 0,0.01} + scaled(reward_scale=2.5)
+ 20 次随机长度/随机价格 episode,绝对误差全部 < 1e-12;
PPO 烟雾真实数据重放实测 5.6e-16。`reward_telescoping.json`。

## 12. INCONSISTENT 首次启动(工作包 D)

live_inference 重写:read_position_fn 抛 InconsistentExecutionStateError 且
fallback_target=None 时,不再执行 int(None)(旧代码唯一崩溃点,
live_inference.py:88)。冻结语义:完全不调用模型(含历史展示重放)、
全部展示目标安全值 0(不解释为真实目标空仓)、最新行不生成 entry/exit、
不取消订单;trace 记录 fail_closed/execution_state=INCONSISTENT/
model_called=false/latest_target_valid=false/完整诊断。七项测试 + 真实
FreqAI 链路集成复现(双 open trade → process() → 零模型调用、零订单、
零取消)。`inconsistent_live_start_trace.json`。

## 13. amount_epsilon 统一(工作包 E)

模型(RouteCModel.rc_config)、策略(RouteCStrategy.route_c_amount_epsilon
property)、get_live_execution_snapshot、get_model_position_live 四处全部
从同一 freqai.route_c.amount_epsilon 读取;manifest execution_contract 与
指纹均含该值。三档(1e-3/1e-8/1e-12)边界暴露 5e-4 判定一致切换
(PENDING_ENTRY/观察0 ↔ PARTIAL_ENTRY/观察1)。`amount_epsilon_consistency.json`。

## 14. base fee 部分成交

上游源码:Order.safe_amount_after_fee = safe_filled − safe_fee_base
(trade_model.py:164-166),recalc_trade_from_orders 累计已关闭订单即用此
口径。execution_state 的活动订单累计从裸 filled 修正为 filled_after_fee:
base 币手续费存在时不再高估暴露;quote 费率(ft_fee_base=None)场景数值
不变(回归)。与上游 recalc 一致性验证:同一订单 open 状态解析暴露 ==
关闭后 recalc 写入的 trade.amount。`partial_fill_base_fee.json`。

## 15. 合法 OHLC 测试(工作包 F)

公共验证器 legal_ohlc.validate_ohlc(high≥max(o,c)、low≤min(o,c)、
high≥low、正价格、非负 volume)在生成后立即校验。生成器提供合法宽/
窄(bar 区间恰为 body,1 tick 宽)/零振幅/跳空四类,tick 网格 snap。
固定目标序列 0,1,1,1,0,0,1,1,0 重放:零滑点市场执行只依赖 open,
high/low 不改变成交结果,窄/doji 无特殊调价,零振幅按同一市场合同处理,
不再维护"向 bar 内移动一 tick 保证成交"语义(窄 bar + 5bps 允许区间外
成交并有测试固化)。`legal_ohlc_validation.json`。2.5.2 的非法窄 K 线
构造随旧合同废弃(见第 18 节)。

## 16. 缓存后处理失败(工作包 G)

runner(post_backtest_cache_pipeline):回测成功 → 生成缓存内容 manifest →
立即自检,只有 self_check==COMPLETE 整轮实验才成功;生成或自检失败 →
写入原始错误、backtesting_predictions 整体 quarantine(原子 rename,
不删除)、模型目录保留、本轮 manifest 标记 invalid、退出码 4
(CACHE_PIPELINE_EXIT_CODE);Freqtrade 的退出码 0 不覆盖后处理失败;
被隔离缓存后续运行按 NONE 全窗重推理(不复用)。六场景测试(构造异常/
写失败/自检 INCONSISTENT/写出后被改/正常成功幂等/quarantine 后不复用)。
`cache_manifest_failure_tests.json`。

## 17. 真实 self.freqai.start() live 链路(工作包 H)

- 测试准备阶段:正式 RouteCModel 在小型合成数据上真实训练极小 PPO
  (完整 train/predict/save),保留模型目录与 pair_dictionary.json;
- Dry-run FreqtradeBot 携带完整 freqai 段,真实调用链:
  populate_indicators → self.freqai.start → start_live(真实特征处理/
  缩放/do_predict)→ data_drawer.load_data(磁盘加载模型 zip+pipeline)
  → RouteCModel.predict → rl_model_predict(live)→ build_strategy_
  return_arrays → populate_entry/exit → FreqtradeBot.process →
  Fake Exchange(仅外部交易所)→ 真实 Trade/Order 持久层;
- 13 项确认全部通过:freqai.start 计数、磁盘模型加载(zip+metadata
  实存 + model_return_values 建立)、live 零训练(ppo_budget_records 空、
  无新增 sub-train)、真实 do_predict、目标列由 FreqAI 返回、首次全历史
  回填无历史信号(FreqAI 官方占位语义:首次 return_values 为占位、不产生
  订单;最新真实预测由下一次 heartbeat 的 append_model_predictions 写入,
  与本阶段 live 合同完全契合)、最新行可产生订单(市场单)、下一 heartbeat
  从 Trade/Order 恢复(PENDING_ENTRY→成交→LONG,七态映射经真实链路)、
  进程重建后仍加载、INCONSISTENT fail-closed、无 API Key、无外部网络
  (download_all_data_for_training 测试级 no-op,数据已在磁盘)、
  Fake Exchange 只替换外部交易所;
- `real_freqai_start_live_trace.csv` + `real_freqai_start_live_summary.md`。

## 18. 旧测试更新说明

按任务书第四节列出五处更新(旧断言/泄漏原因/更严格替代),全文见
`artifacts/freqai_rl_stage2_5_2a/regression_test_summary.md`:
2.5 免滑点清算断言 → 因果成本断言;2.5.1 策略滑点钩子断言 → 市场订单+
无价格钩子+epsilon 同源;2.5.1 五轮 parity → 零滑点两轮;2.5.2 七轮
parity → 零滑点三轮 + legacy 函数测试保留标注。未删除、未 skip、
未 xfail 任何测试;历史报告与 artifacts 未篡改(2.5.2 的
full_fill_parity.md/narrow_bar_full_parity.json 由本轮运行按更新后
测试重写,旧版本在 backups/stage252a_20260825/ 与阶段 2.5.2 公开仓库
快照中保留)。

## 19. 新测试结果

tests/freqai_rl_stage2_5_2a 共 11 个测试文件 81 项全部通过
(清单见 regression_test_summary.md)。

## 20. PPO 烟雾

`tests/freqai_rl_stage2_5_2a/ppo_smoke.py` 全部通过:完整指纹(含执行
合同)→ FreqAI 滑窗 5 窗 → 因果市场环境 → PPO(预算准确,actual==
rounded 全窗)→ 保存/加载 → 顺序推理(动作 508:212,无 NaN)→ 市场订单
策略 → Freqtrade 零滑点回测(逐笔成交价==执行 bar open)→ 缓存内容
manifest COMPLETE(失败致命化生效)→ 缓存复用(交易路径逐字段一致、
零新训练)→ 模型重载(零重训、动作逐字段一致)。指纹敏感性:
simulated_slippage_bps 或 price_tick 变化 → 新指纹 → 新 identifier。
env 重放 telescoping 5.6e-16。`ppo_regression_smoke.json`。
滑点压力 0/5/10bps 单调性见第 9 节。

## 21. 已知限制

1. 非零 simulated_slippage_bps 无 Freqtrade parity(声明的边界,非缺陷);
2. 环境市场成交仍是模拟抽象(不含订单簿深度/部分成交动力学),
   live 成交以交易所真实回报为准;
3. FreqAI live 首次全历史回填的 return_values 为官方占位语义
   (do_predict 列非 1,不产生订单),第二个 heartbeat 起才有驱动订单的
   最新预测——这是上游行为,已在测试中固化为断言;
4. 市场订单在 Dry-run Fake Exchange 中的成交由脚本控制;真实 dry-run
   的市场单即时成交语义由上游 exchange 层保证;
5. 单交易对(BTC/USDT 1h)单时段;阶段范围限制,非目标;
6. G 包 quarantine 在写 manifest 失败(父目录不可写)场景下仍保证退出码
   4,但 quarantine 本身失败时记录 quarantine_error 不中断(不删除任何数据)。

## 22. 是否允许进入阶段 2.6 / PASS 条件对表

27 项 PASS 条件:全部成立(1 上游零修改✓ 2 生产成交函数不收 high/low✓
3 不变性✓ 4 不再用 bar_executable_price✓ 5 不再缓存 high/low 改价✓
6 买 ceil✓ 7 卖 floor✓ 8 市场单 open[t+1] 对齐✓ 9 非零滑点不声称 parity✓
10 终端同成本✓ 11 telescoping✓ 12 无免费退出✓ 13 无 int(None)✓
14 不调模型不下单不取消✓ 15 epsilon 统一✓ 16 base fee✓ 17 合法 OHLC✓
18 宽/窄/doji 因果✓ 19 manifest 失败致命✓ 20 隔离+非零✓ 21 真实
freqai.start✓ 22 真实加载模型✓ 23 未绕过(无测试壳替代)✓ 24 生命周期
回归✓ 25 旧测试全过✓ 26 烟雾✓ 27 上游 clean✓)。
10 项 FAIL 条件零命中。**允许进入阶段 2.6**;按任务书要求本任务到此停止。

## 23. 完整复现命令

```bash
# WSL: CryptoRL-Ubuntu-24.04
source ~/projects/crypto_rl/activate-freqtrade.sh
source ~/projects/crypto_rl/scripts/proxy-on.sh   # CLI 回测需访问 exchange markets
cd ~/projects/crypto_rl

# 全量回归(271 项)
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ \
  tests/freqai_rl_stage2_5_2/ tests/freqai_rl_stage2_5_2a/ -q

# PPO 回归烟雾(三轮 + 指纹敏感性 + env 重放)
python tests/freqai_rl_stage2_5_2a/ppo_smoke.py

# 阶段 2.5.2a 实验入口
python experiments/freqai_rl_stage2_5_2a/run_experiment.py \
    --timerange 20260601-20260701 --seed 42 --fee 0.001 \
    --simulated-slippage-bps 0 --price-tick 0.01 --suffix base

# 上游完整性
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
git -C vendor/freqtrade status --short                  # 空
```

## 24. 证据索引

`artifacts/freqai_rl_stage2_5_2a/`(19 个文件,无空文件):

| 文件 | 内容 |
|---|---|
| causal_execution_contract.md | 冻结合同 + 源码依据 + 调用图 |
| future_high_low_invariance.json | 不变性矩阵 + legacy 对照 |
| market_price_rounding.json | ceil/floor 取整样本 |
| terminal_liquidation_parity.json | 终端成本一致 + 单调性 |
| reward_telescoping.json | telescoping 随机 episode |
| inconsistent_live_start_trace.json | INCONSISTENT 首启 fail-closed |
| amount_epsilon_consistency.json | epsilon 四处同源 |
| partial_fill_base_fee.json | safe_amount_after_fee 口径 |
| legal_ohlc_validation.json | 四类合法 K 线 + 固定目标序列 |
| zero_slippage_freqtrade_parity.md | 零滑点四轮完整 parity |
| market_order_parity_summary.json | 四轮数值汇总 |
| simulated_slippage_monotonicity.json | 滑点压力单调性 + 边界声明 |
| cache_manifest_failure_tests.json | G 包场景矩阵 |
| cache_content_manifest.json | 烟雾缓存内容清单(副本) |
| real_freqai_start_live_trace.csv | 真实 freqai.start 心跳 trace |
| real_freqai_start_live_summary.md | 调用证据汇总 |
| regression_test_summary.md | 旧断言更新 + 新旧测试数量 |
| ppo_regression_smoke.json | 烟雾全量记录 |
| upstream_integrity.txt | 上游版本/commit/clean 记录 |

公开仓库:https://github.com/ceyirelehe47/freqai-rl-platform-audit 的
`stage2_5_2a/`(不覆盖 stage2_5 / stage2_5_1 / stage2_5_2)。
