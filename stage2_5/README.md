# 阶段 2.5:路线 C 可行性验证(FreqAI 编排层 + 自定义对齐环境)

上一阶段(阶段一/二)审计结论:原生 FreqAI RL 训练环境与 Freqtrade 回测器
存在一根 K 线的系统性执行错位等 9 项问题,推荐路线 B。本阶段验证**路线 C**:
不修改 Freqtrade 核心、不维护 fork,保留 FreqAI 的特征流水线/滑动窗口/
模型生命周期/回测编排,替换交易语义核心(对齐 Gymnasium 环境、Long/Flat
净值账本、净值 log 奖励、目标仓位动作、顺序状态推理、实验指纹缓存隔离)。

**判定:CONDITIONAL PASS**(17 项通过条件全部成立,7 项非核心限制均不阻塞
下一阶段,见报告 §2/§21)。

关键结果:

- 时间对齐:自定义环境与真实 `Backtesting.start()` 在同数据同信号下
  entry/exit 时间与价格完全一致(信息截至 t → open[t+1] 成交),
  上一阶段的 gap=2 vs gap=1 错位消除;
- 单笔收益率与 Freqtrade 回测器公式一致(≤5e-9);复利终值差有闭式
  W·f·(1−R)(stake 语义差异,f=0.001 时每笔 ≤1e-4 相对);
- 累计 log reward 与净值比一致(<1e-12,24 组人工序列);
- 模型重载确定性:删预测缓存重跑成交逐字段一致;独立进程加载保存模型
  重推理 720 行零差异;
- 跨 FreqAI 子窗口目标仓位状态延续(窗 1-4 末多头 → 窗 5 继续);
- 实验指纹:seed 42/43 → 两个 identifier,零旧缓存命中;
- PPO 烟雾全链路(5 窗 CPU 训练、无 NaN、回测成交在 open[t+1])。

## 目录结构

```text
stage2_5/
├── report/freqai_rl_stage2_5_route_c_validation.md   主报告(25 节)
├── src/rl_platform/           核心包(账本/对齐环境/顺序推理/信号转换/指纹/dry-run 状态)
├── adapters/
│   ├── freqaimodels/RouteCModel.py    FreqAI 薄适配层(3 个官方扩展点)
│   └── strategies/RouteCStrategy.py   策略薄适配层(特征+目标仓位转信号)
├── experiments/               run_experiment.py(指纹→config→回测入口)+配置模板
├── tests/                     38 项确定性测试 + 证据生成脚本
├── artifacts/                 全部证据文件(见报告 §25 索引)
└── logs/                      预检查/PPO 烟雾/重载/缓存隔离日志
```

## 复现环境

- Freqtrade 2026.7(commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,vendor 零修改)
- Python 3.11 + gymnasium + stable-baselines3 + torch(CPU 训练)
- BTC/USDT spot 1h(Binance US)公开数据,自行下载:
  `freqtrade download-data --exchange binanceus --pairs BTC/USDT --timeframes 1h --timerange 20260401-20260701`

源码布局:核心包放 `src/rl_platform`,适配层放 `user_data/freqaimodels` 与
`user_data/strategies`(路径约定见各文件头部 `PROJ_ROOT` 注释)。

## 复现命令

```bash
# 1. 确定性测试(38 项)
python -m pytest tests/freqai_rl_stage2_5/ -v

# 2. PPO 烟雾(指纹渲染 config → freqtrade backtesting 全链路)
python experiments/freqai_rl_stage2_5/run_experiment.py \
  --timerange 20260601-20260701 --seed 42 --suffix ppo_base --extract-actions

# 3. 模型重载分支 + 证据
rm -rf user_data/models/stage25-rc-<id>/backtesting_predictions
python experiments/freqai_rl_stage2_5/run_experiment.py \
  --timerange 20260601-20260701 --seed 42 --suffix ppo_reload --extract-actions
python tests/freqai_rl_stage2_5/ppo_evidence.py <run1.zip> <run2.zip>
python tests/freqai_rl_stage2_5/make_evidence.py
```

## 边界声明

本目录为架构验证材料,非生产系统:特征与奖励仅为链路验证用的最小因果集,
未做超参搜索与收益评估;PPO 动作分布高度集中(672/720)如实记录,不代表
架构失败;Dry-run 订单拒绝/断线重同步未实现(报告 §21)。不包含真实市场
数据、模型二进制与任何凭据。
