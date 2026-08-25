# 上游测试结果(阶段二 §23)

- 日期:2026-08-25 UTC
- 命令:`python -m pytest tests/freqai/test_freqai_interface.py -k "ReinforcementLearner or get_state_info" -v --no-header`
- 工作目录:~/projects/crypto_rl/vendor/freqtrade(tag 2026.7)
- 结果:**8 passed, 0 failed, 0 skipped,154.84s**

| 测试 | 结果 | 覆盖的语义 |
|---|---|---|
| test_extract_data_and_train_model_Standard[ReinforcementLearner-…] | PASSED | 官方 5Ac 训练循环在 mock 数据上跑通并保存 zip;RL 守卫(SVM/DI 自动关闭、shuffle 强制 False)路径 |
| test_extract_data_and_train_model_Standard[ReinforcementLearner_multiproc-…] | PASSED | 多进程环境包装 |
| test_extract_data_and_train_model_Standard[ReinforcementLearner_test_3ac-…] ×2 | PASSED | 三动作环境训练(float32/非 float32、can_short 两种) |
| test_extract_data_and_train_model_Standard[ReinforcementLearner_test_4ac-…] | PASSED | 四动作环境训练 |
| test_start_backtesting[ReinforcementLearner-3-freqai_rl_test_strat] | PASSED | FreqAI RL 回测滑窗产出 3 个预测缓存文件 |
| test_get_state_info[False] / [True] | PASSED | live 模式读取 Trade 仓位/利润/时长;无 exchange 时错误日志分支 |

## 这些测试没有覆盖的语义(由本审计人工实验补齐)

- observation 窗口与执行 tick 的对齐(训练 gap=2 vs 推理 gap=1);
- 费用/PnL 公式数值验证(add_entry_fee/add_exit_fee/_update_total_profit);
- 训练环境与回测器成交语义一致性;
- episode 结束未平仓处理与回撤终止的数值行为;
- 奖励函数与净值的关系(刷分路径);
- add_state_info=true 在回测下的报错(上游无该负向测试)。

测试工具依赖(本任务新增,运行时依赖未动):pytest 9.1.1、pytest-mock、
pytest-xdist、pytest-asyncio、pytest-timeout。
