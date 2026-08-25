# FreqAI RL 平台审计报告(阶段一链路验收 + 阶段二交易语义审计)

对 **Freqtrade 2026.7**(tag `2026.7`,commit `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`)
原生 FreqAI Reinforcement Learning 的完整平台审计:

- **阶段一**:官方 RL 链路验收(数据下载 → FreqAI 特征 → RL 环境 → PPO GPU 训练
  → 模型保存 → 重载/预测缓存 → 历史推理 → 回测 → 结果导出 → TensorBoard)。
- **阶段二**:训练/推理/回测的交易语义审计(时间对齐、成交价格、手续费、
  奖励函数、episode/reset、state info),全部结论以"源码行号 + 可重复实验 +
  手算对照"三重证据支持。

## 核心结论

**推荐路线 B**:Freqtrade 保留数据管理 / 正式回测 / Dry-run / 实盘;
训练改用自定义 Gymnasium 环境。

五项最关键发现(详见报告):

1. **训练与回测存在一根 K 线的系统性执行错位**:同一信息集下,RL 训练环境
   做成 −11.29%,Freqtrade 回测器对同信号做成 +8.87%,方向相反
   (`artifacts/env_vs_backtester_comparison.md`)。
2. 官方 `ReinforcementLearner` 内嵌五动作环境且不检查 `can_short`,
   spot long-only 下训练出的 Short_enter 动作被回测静默丢弃。
3. 默认奖励与净值严重脱钩:开仓 +25 / 空仓 −1 / 平仓放大 100~300 倍;
   零收益价格上反复开平实测刷出 +350 奖励。
4. episode 结束不强制平仓,未实现盈亏不入账;回撤终止采用未实现口径。
5. `lookahead-analysis` / `recursive-analysis` 会对 freqai identifier 模型目录
   整目录 rmtree,与 FreqAI 组合具有破坏性。

## 目录结构

```text
report/       主报告(自包含,含全部结论与证据引用)
artifacts/    全部证据文件(源码地图/数据质检/首跑摘要/动作分布/重载三分支快照/
              4 序列×2 费率×7 动作脚本的 synthetic trace CSV/环境对比/
              TensorBoard tags/上游测试摘要/模型清单)
reproduction/ 复现材料(实验脚本 + freqtrade 配置 + 复现说明)
logs/         全部命令日志(00–13 号脚本)
```

不含:真实市场数据 feather(交易所数据再分发许可)、模型二进制。

## 复现环境

WSL2 Ubuntu 24.04 + conda(freqtrade-rl,Python 3.11)+ PyTorch cu130(RTX 3060)。
按上游 `requirements-freqai-rl.txt` 固定安装,`pip install -e .`。
复现步骤见 `reproduction/README.md`。

## 审计边界声明

本仓库仅为平台审计:无实盘、无交易所 API Key、无正式策略开发、无参数调优。
默认奖励函数的行为评价是针对上游自带 benchmark 实现(其源码自身标注
"not for live production"),非对 Freqtrade 项目本身的否定。
