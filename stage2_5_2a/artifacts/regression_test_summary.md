# 阶段 2.5.2a 回归测试摘要

日期:2026-08-25/26(UTC)
上游:Freqtrade 2026.7 / 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5 / dirty 0

## 总量

| 阶段 | 测试数 | 结果 |
|---|---|---|
| 2.5(tests/freqai_rl_stage2_5) | 38 | 全部通过 |
| 2.5.1(tests/freqai_rl_stage2_5_1) | 74 | 全部通过 |
| 2.5.2(tests/freqai_rl_stage2_5_2) | 78 | 全部通过 |
| 2.5.2a(tests/freqai_rl_stage2_5_2a) | 81 | 全部通过 |
| **合计** | **271** | **全部通过** |

命令:
`python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ tests/freqai_rl_stage2_5_2/ tests/freqai_rl_stage2_5_2a/ -q`
→ `271 passed`

PPO 回归烟雾:`python tests/freqai_rl_stage2_5_2a/ppo_smoke.py` → 全部通过
(ppo_regression_smoke.json)。

## 按任务书第四节更新的旧断言(列出旧断言 / 泄漏原因 / 更严格替代)

### 1. tests/freqai_rl_stage2_5/test_ledger.py::test_liquidation_at_end

- 旧断言:`liquidate(raw_open=120.0)` 免滑点清算(exec_price==120.0、
  slippage_cost==0.0),对齐 Freqtrade handle_left_open。
- 问题:该断言编码了"持有到 Episode 结束可以免滑点退出"的奖励漏洞
  (终端免费退出),策略上鼓励拖到终点。
- 替代:清算走市场卖出公式(exec==floor(120×0.9995)=119.94)、
  slippage_cost>0、fee>0,并新增"与普通卖出 _sell_all 同价同费"断言。

### 2. tests/freqai_rl_stage2_5/test_ledger.py::test_reset_clears_everything

- 仅参数名适配(liquidate(reference_price) 位置传参),断言未放宽。

### 3. tests/freqai_rl_stage2_5_1/test_live_trade_state_resync.py::test_strategy_slippage_from_config

- 旧断言:策略 route_c_slippage_bps 属性 + custom_entry_price/custom_exit_price
  返回 open×(1±bps/10000)。
- 问题:custom price 钩子在 2.5.2 被 bar_executable_price 驱动(读取执行 K 线
  最终 high/low),属非因果合同;2.5.2a 市场订单合同下策略不定义价格钩子,
  simulated 滑点不得改变 live 订单价格。
- 替代:order_types entry/exit=="market"、策略类不覆盖 custom_entry_price/
  custom_exit_price(IStrategy 基类回调不提供)、route_c_amount_epsilon
  与模型同源读取(1e-12 默认,配置覆盖生效)。

### 4. tests/freqai_rl_stage2_5_1/test_route_c_slippage_live_strategy.py::test_route_c_slippage_parity_end_to_end

- 旧断言:五轮(含 5/10bps 与"窄 K 线"构造)env 与回测 custom price 恒等;
  其中窄 K 线构造 close 位于 high/low 之外,数据本身非法。
- 问题:非零滑点 parity 依赖 custom price 钩子(非因果),且测试数据不满足
  合法 OHLC。
- 替代:保留零滑点两轮(fee0_slip0 / fee001_slip0),配置补市场订单要求的
  entry_pricing.price_side="other";成交价语义为 open[t+1] 恒等;非零模拟
  滑点声明只属环境压力测试(不声称回测 parity)。

### 5. tests/freqai_rl_stage2_5_2/test_full_fill_parity.py::test_full_fill_parity_all_rounds

- 旧断言:七轮 bar 内一 tick 执行合同 parity(触及边界内移一 tick、
  fallback open、非法窄 K 线两轮、零振幅一轮,且要求触发边界分支)。
- 问题:整个合同依赖执行 K 线最终 high/low(未来信息),2.5.2a 已废弃。
- 替代:零滑点市场订单三轮(宽/零振幅/零费),env 默认 causal,成交价恒等
  open[t+1] 断言;函数级 bar_executable_price 性质测试保留并标注
  legacy_noncausal_not_for_training;narrow_bar_full_parity.json 记录
  废弃说明与零滑点轮结果。

## 未放宽的回归(全量原样通过)

订单生命周期(FreqtradeBot 12 场景)、缓存守卫双层、do_predict 状态机、
PPO 预算、执行状态七态解析、live 最新行信号矩阵、反转取消、
telescoping、指纹与 manifest 等其余 2.5/2.5.1/2.5.2 断言全部原样通过。

## 新增测试(tests/freqai_rl_stage2_5_2a,81 项)

- test_market_execution_causality.py(12):函数合同(签名无 high/low)、
  ceil/floor 方向、取整不改善、输入校验、环境只要求 open/close、
  调用图保护(causal 零调用 bar_executable_price / legacy 对照)、
  非法 execution_mode 拒绝、合法 OHLC 四类 × 固定目标序列、
  窄 bar 无调价(区间外成交合法)、info 诊断字段;
- test_future_high_low_invariance.py(10):A.4 硬性验收(两份不同合法
  high/low 全等 + 极端值 + 参数矩阵 + legacy 对照组);
- test_terminal_liquidation_cost.py(8):工作包 C 七项 + ledger 直查;
- test_terminal_reward_telescoping.py(16):五种动作模式 × 三组参数 +
  scaled + 20 次随机 episode;
- test_inconsistent_first_live_call.py(6):工作包 D 七项;
- test_amount_epsilon_consistency.py(5):三档 epsilon 四处同源;
- test_partial_fill_base_fee.py(6):safe_amount_after_fee 口径;
- test_market_order_freqtrade_parity.py(1×4 轮):零滑点市场订单完整 parity;
- test_simulated_slippage_monotonicity.py(3):公式 + 成本/净值单调;
- test_cache_manifest_failure_is_fatal.py(6):G 包五场景 + 不复用;
- test_real_freqai_start_live_chain.py(5):真实 self.freqai.start 完整链路。
