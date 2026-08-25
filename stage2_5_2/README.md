# 阶段 2.5.2:Route C 实时执行状态与完整成交语义修复

本目录为公开复现材料,对应本地主报告
`~/projects/crypto_rl/reports/freqai_rl_stage2_5_2_execution_fix.md`。
上一阶段材料见 [stage2_5_1/](../stage2_5_1/)(不覆盖)。

## 判定:PASS(允许进入阶段 2.6,本阶段未开始)

六个工作包与结果:

| 问题 | 结果 |
|---|---|
| Trade.is_open 被直接当作多头 | 七态执行状态解析器(FLAT/PENDING_ENTRY/PARTIAL_ENTRY/LONG/PENDING_EXIT/PARTIAL_EXIT/INCONSISTENT);实际暴露按源码从 Trade+Order 重推导;INCONSISTENT fail closed |
| Live 扫描整段历史目标生成信号 | 历史/回填行一律无信号;最新行 = 真实执行状态+最新目标+do_predict+活动订单;backtest/live 双路径;populate 幂等 |
| 零成交挂单/部分成交/待退出无法区分 | 全部区分并驱动信号规则:同方向挂单不重复下单;反转经官方 adjust_entry/exit_price 返回 None 取消 |
| 无完整 FreqtradeBot 级订单生命周期验证 | 12 场景全链路(rl_model_predict→策略→FreqtradeBot→Fake Exchange→Trade/Order 持久层→下一 heartbeat),含进程重启五状态恢复 |
| 窄 K 线环境与回测成交不一致(只比子集) | bar 内一 tick 执行合同(环境与策略同一价格函数);七轮 parity 逐笔一致(17==17==17);更正 2.5.1 根因诊断(1 ulp 漂移+超时循环) |
| 缓存 COMPLETE 只查名称行数 | 内容级校验(sha256/日期序列/目标与 do_predict 列哈希/指纹绑定),7 类损坏场景全部 fail closed |

测试:阶段 2.5(38)+ 2.5.1(74)+ 2.5.2 新增(78)= **190 项全部通过**;
PPO 回归烟雾三轮(全新/缓存复用/模型重载)全部通过
(5 窗预算 482→512→actual 512,720 动作无 NaN,复用复现交易路径,
重载 0 次训练动作逐字段一致)。上游 Freqtrade 2026.7 / commit 52bc96f
零修改(始/终 clean)。

## 目录结构

```text
stage2_5_2/
├── README.md
├── report/       主报告(判定/根因/复现命令/证据索引)
├── src/          rl_platform 全部模块(新增 execution_state.py、cache_content.py)
├── adapters/     RouteCModel.py(freqaimodels)/ RouteCStrategy.py(strategies)
├── experiments/  run_experiment.py + 配置模板(双层缓存守卫+执行合同配置)
├── tests/        8 个测试文件 + bot_harness + ppo_smoke(78 项)
├── artifacts/    20 个证据文件(状态矩阵/生命周期 trace/七轮 parity/缓存损坏矩阵/烟雾)
└── logs/         烟雾运行日志摘要
```

## 复现要点

```bash
# WSL CryptoRL-Ubuntu-24.04,conda freqtrade-rl
python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/ \
    tests/freqai_rl_stage2_5_2/ --ignore=tests/freqai_rl_stage2_5_2/ppo_smoke.py -q
python tests/freqai_rl_stage2_5_2/ppo_smoke.py   # PPO 回归烟雾(需代理脚本)
```

上游交互发现(记录):COMPLETE 缓存复用时上游
`check_if_feature_list_matches_strategy` 与 RL `drop_ohlc_from_features=true`
冲突(存盘特征列表不含 %-raw_*),2.5.2 模板改 `false` 规避,上游零修改。
详见主报告十六节。

本目录不含真实行情数据、模型二进制、数据库、API Key 或任何本机敏感路径;
所有 identifier/窗口数/行数均由脚本动态推导,无硬编码。
