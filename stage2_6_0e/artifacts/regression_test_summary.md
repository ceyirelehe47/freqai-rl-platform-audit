# 阶段 2.6.0e 全量回归测试摘要

- 日期:2026-08-27
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl(Python 3.11)
- 命令:`python -m pytest tests/<阶段目录> -q`(逐目录全量)
- 冻结确认:RouteCEnvCore-v1.0.0 / ObservationSpec-v1 /
  BinaryLongFlatAction-v1 / NetLogEquityReward-v1 /
  MarketOpenCausalExecution-v1 / TerminalLiquidation-v1 全部未修改;
  vendor/freqtrade clean @ 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5

| 测试目录 | passed | failed | error | skipped | xfailed | 耗时 |
|---|---:|---:|---:|---:|---:|---:|
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 | 7s |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 | 10s |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 | 50s |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 | 19s |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 | 311s |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 | 436s |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 | 227s |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 | 248s |
| route_c_stage2_6_0d | 57 | 0 | 0 | 0 | 0 | 271s |
| route_c_stage2_6_0e | 109 | 0 | 0 | 0 | 0 | 418s |
| **合计** | **1030** | **0** | **0** | **0** | **0** | **1997s** |

说明:

- 阶段 2.5 → 2.6.0e 全部 10 个测试目录零失败、零跳过、零 xfail;
- 总数 1030 = 阶段 2.6.0d 基线的 921 + 本阶段新增 109;
- 阶段 2.6.0e 期间对 2.6.0a/b/c/d 既有测试的修改仅为协议版本字符串
  与公式断言的同步(sealed v5 / nq v4 / cli v6 / 冻结账本公式),
  未删除测试、未降低断言强度;
- 首轮回归发现 3 个失败(2.6.0a 两处 v5 结构 fixture、2.6.0d 一处
  margin 篡改场景的重跑异常路径),修复(null_power_reverification
  将 power 重跑失败转为 fail-closed 拒绝 + fixture 补 v5 字段)后
  全量重跑通过,本表为修复后的最终记录。
