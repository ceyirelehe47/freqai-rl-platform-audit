# 阶段 2.6.0d 全量回归摘要(2.5 -> 2.6.0d)

| 目录 | passed | failed | error | skipped | xfailed | 耗时 |
|---|---|---|---|---|---|---|
| freqai_rl_platform_audit | —(无测试文件,历次相同) | 0 | 0 | 0 | 0 | ~1s |
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 | 15.2s |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 | 31.1s |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 | 51.0s |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 | 19.5s |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 | 326.2s |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 | 348.7s |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 | 138.0s |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 | 257.1s |
| route_c_stage2_6_0d | 57 | 0 | 0 | 0 | 0 | 230.6s |
| **合计** | **921** | **0** | **0** | **0** | **0** | **1392s** |

- 无删除测试、无 skip/xfail、无断言降级;
- pack 扩容(每族 32 antithetic pair)使 CLI 级测试变慢约 3-5 倍,全部真实执行;
- 冻结六合同未变;vendor/freqtrade 52bc96f clean。
