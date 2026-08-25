# 阶段 2.5.2a:因果执行、终端奖励与完整 FreqAI Live 编排修复

> **阶段 2.5.2 的全局 PASS 已被阶段 2.5.2a 重新审查。**
> 原因:原执行合同使用执行 K 线最终 high/low 修改成交价格(bar 内一 tick
> 调价,属未来信息泄漏);阶段 2.5.2a 以因果市场成交合同
> (execution_mode = market_open_causal)取代。

- 判定:PASS(27 项 PASS 条件全部成立,10 项 FAIL 条件零命中)
- 测试:271 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81)
- PPO 回归烟雾:通过(预算准确/动作无 NaN/缓存 COMPLETE/复用与重载一致/
  指纹随执行合同变化)
- 是否允许进入阶段 2.6:允许(本阶段到此停止,未开始 2.6)

## 本阶段修复

1. **因果市场成交合同**:成交价只依赖 open[t+1]、方向、执行前固定的
   simulated_slippage_bps 与 price_tick(买入 ceil_to_tick 向上取整、
   卖出 floor_to_tick 向下取整,取整不得改善价格);high/low/close[t+1]
   与后续 K 线全部移出成交决策。改变未来 high/low(含极端值)不影响
   成交方向/价格/手续费/reward/最终净值(硬性验收)。
2. **Freqtrade 市场订单路径**:策略 entry/exit 均市场订单,移除 custom
   price 钩子与执行 K 线 high/low 缓存;源码+实验确认市场单回测在
   open[t+1] 成交(信号 shift(1)、custom price 仅 limit、闭区间撮合);
   零滑点四轮完整 parity(含合法窄 K 线与零振幅轮)逐笔一致;
   非零模拟滑点只属环境压力测试,不声称回测精确复现。
3. **终端清算**:与普通市场卖出完全相同的滑点、tick 取整与手续费
   (基准价 close[last],清算发生在收盘后);reward telescoping
   sum(log r) == log(final_cash/initial) 精确成立;免费退出漏洞消除。
4. **INCONSISTENT 首次启动**:不再 int(None);完全不调用模型(含历史
   展示重放)、展示目标安全值 0、不生成订单、不取消订单。
5. **amount_epsilon 统一**:模型/策略/live 执行状态/manifest 四处同源;
   base 币手续费部分成交按上游 safe_amount_after_fee 口径扣除。
6. **合法 OHLC**:公共验证器 + 四类合法生成器(宽/窄/零振幅/跳空),
   不再构造 close 越界的"窄 K 线"作为证据。
7. **缓存 manifest 失败致命化**:生成/自检失败 → 退出码 4、预测缓存
   quarantine、模型保留、manifest invalid、后续不复用。
8. **真实 self.freqai.start() live 集成测试**:Dry-run FreqtradeBot +
   完整 freqai 段 + 磁盘加载正式训练的极小 PPO 模型;populate_indicators
   → freqai.start → 特征处理/缩放/do_predict → 模型加载 → rl_model_predict
   → 目标列 → 信号 → process → Fake Exchange → Trade/Order;
   live 全程零训练;INCONSISTENT fail-closed 经真实链路复现。

## 目录

- `report/` 主报告(24 节,PASS 条件对表、复现命令、证据索引)
- `src/` rl_platform 本阶段新增/修改模块(market_execution 等)
- `adapters/` RouteCModel.py / RouteCStrategy.py
- `experiments/` 阶段 2.5.2a 实验入口与配置模板
- `tests/` 11 个测试文件(81 项)+ harness + PPO 烟雾
- `artifacts/` 19 个证据文件
- `logs/` 最终回归与烟雾输出摘要

## 复现(WSL CryptoRL-Ubuntu-24.04,conda freqtrade-rl)

```bash
source ~/projects/crypto_rl/activate-freqtrade.sh
source ~/projects/crypto_rl/scripts/proxy-on.sh   # CLI 回测需访问 exchange markets
cd ~/projects/crypto_rl
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/   tests/freqai_rl_stage2_5_2/ tests/freqai_rl_stage2_5_2a/ -q   # 271 passed
python tests/freqai_rl_stage2_5_2a/ppo_smoke.py                  # 烟雾三轮
```

上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,
零修改。本目录不含模型二进制/真实行情数据/SQLite/API Key/代理认证/本机路径。
