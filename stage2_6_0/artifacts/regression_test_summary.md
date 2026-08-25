# 阶段 2.6.0 回归测试摘要

- 时间(UTC): 2026-08-25/26
- 环境: WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 回归命令:
  python -m pytest tests/freqai_rl_stage2_5/ tests/freqai_rl_stage2_5_1/     tests/freqai_rl_stage2_5_2/ tests/freqai_rl_stage2_5_2a/     tests/route_c_stage2_6_0/ -q
- 结果: **438 passed**(0 failed / 0 skipped / 0 xfail)
- PPO 回归烟雾: python tests/freqai_rl_stage2_5_2a/ppo_smoke.py 全部通过
  (完整指纹含版本注入 -> FreqAI 滑窗 5 窗 -> PPO 预算准确 -> 市场订单
  回测逐笔==open[t+1] -> 缓存 COMPLETE -> env 重放 telescoping 5.6e-16;
  证明 route_c 新增规范版本键与终端观察修复不破坏 2.5.2a 全链路)

## 测试数量分阶段

| 阶段 | def test_ 静态数 | pytest 收集数(含参数化) |
|---|---|---|
| 2.5 | 33 | 38 |
| 2.5.1 | 64 | 74 |
| 2.5.2 | 58 | 78 |
| 2.5.2a | 60 | 81 |
| 2.6.0(新) | 140 | 167 |
| 合计 | 355 | 438 |

## 旧测试处理

未修改、未删除、未 skip、未 xfail 任何 2.5~2.5.2a 现有测试。
对既有代码的两处修改均为新增行为,旧测试全部通过:
1. env.py 终端观察仓位归零(terminated 时 obs 仓位字段=0,info 新增
   requested_target_position / actual_position_after_liquidation);
2. run_experiment.py 缺失预测目录致命化(freqtrade 退出码 0 且
   backtesting_predictions 不存在 -> invalid + 退出码 4 + manifest 记录
   原始异常 + 模型目录保留)。

## 新测试覆盖(22 个文件,167 项)

test_environment_freeze_version / test_terminal_observation_position /
test_missing_prediction_dir_is_fatal / test_timebase_conversion /
test_gamma_real_time_equivalence / test_course_charter_hash /
test_generator_determinism / test_hidden_state_not_in_observation /
test_common_prefix_invariance / test_price_scale_invariance /
test_episode_length_invariance / test_null_control / test_signal_ablation /
test_generator_family_holdout / test_baseline_ordering /
test_cheater_detection / test_exam_pack_hash / test_hidden_exam_redaction /
test_exam_retirement / test_evaluator_determinism /
test_checkpoint_compatibility_guard / test_generalization_grade

## fail-closed 验证清单(任务书第五节)

- checkpoint 环境版本不匹配 -> CheckpointCompatibilityError 拒绝加载
- 课程章程哈希不匹配 -> 拒绝(checkpoint 守卫与 charter 断言)
- 考试包 schema/内容错误 -> ExamPackError 拒绝
- 隐藏考试内容缺失(文件不存在)-> ExamPackError 拒绝
- 隐藏考试已退休 -> 拒绝 + EXAM_INVALID(退出码 5)
- observation 维度变化 -> 注入特征后 SB3 策略崩溃 fail closed(测试断言)
- 非法 OHLC / NaN 特征 -> GeneratorError(生成后立即校验)
- reward 与最终净值不一致 -> EvaluationError(逐 episode 校验)
- Episode 终端持仓非 0 -> 断言失败
- freqtrade 成功但预测目录缺失 -> 退出码 4 + invalid + 原始异常
- checkpoint 二进制被替换(SHA-256 不一致)-> 拒绝加载
