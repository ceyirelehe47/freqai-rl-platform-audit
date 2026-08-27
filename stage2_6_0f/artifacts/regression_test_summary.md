# 阶段 2.6.0f 全量回归汇总

- 日期:2026-08-27
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11
- 基线:aa80c2d(2.6.0e)→ 2.6.0f 工作树
- 结论:**11 个测试目录共 1097 项全部通过;0 failed / 0 skipped / 0 xfailed / 0 error**

| 目录 | passed | failed | error | skipped | xfailed | 耗时 |
|---|---|---|---|---|---|---|
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 | 8s |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 | 12s |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 | 51s |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 | 24s |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 | 384s |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 | 497s |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 | 251s |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 | 260s |
| route_c_stage2_6_0d | 57 | 0 | 0 | 0 | 0 | 294s |
| route_c_stage2_6_0e | 112 | 0 | 0 | 0 | 0 | 448s |
| route_c_stage2_6_0f(本阶段新增) | 64 | 0 | 0 | 0 | 0 | 179s |
| **合计** | **1097** | **0** | **0** | **0** | **0** | **~41 分钟** |

说明:
- route_c_stage2_6_0c 在首轮回归中出现 1 项失败(test_mock_sealed_exam_v4
  的 CLI 版本常量断言仍为 v6);该断言更新为 hidden-exam-cli-v7 后复跑
  全目录 83 项全部通过(见 regression_raw.log 末尾 re-verify 记录)。
- 旧阶段测试维护仅限三类:①v6/v7/v3/v2 协议常量断言跟进;②
  validate_null_pack / verify_sealed_commitment / CLI 新必填参数的
  显式适配(经 tests/compat_stage2_6_0f.py 共享辅助);③修复 2.6.0b
  测试对 param_resolution 全局注册表的真实污染(注册后未恢复,会改变
  rps-/duration 合同哈希)。未删除任何旧测试、未添加 skip/xfail、
  未降低旧断言。
- 重新确认:六项冻结合同未修改;vendor/freqtrade clean 且 HEAD 为
  52bc96f4480b1a0da6a9b455bd00b17fbb6786a5;未开始正式课程 PPO 训练
  (256-step smoke 仅用于链路验证,正常 FAIL)。
