# 阶段 2.6.0c 全量回归测试摘要

- 日期:2026-08-26
- 命令:`python -m pytest tests/<目录>/ -q --timeout=560 -p no:cacheprovider`
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl
- 结论:**8 个目录共 864 项全部通过,0 failed / 0 error / 0 skipped / 0 xfailed**

| 目录 | passed | failed | error | skipped | xfailed | 耗时 |
|---|---|---|---|---|---|---|
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 | 36s |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 | 40s |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 | 52s |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 | 21s |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 | 75s |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 | 51s |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 | 63s |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 | 77s |
| **合计** | **864** | **0** | **0** | **0** | **0** | ~7.6min |

说明:

- 另有四次"全仓库收集"运行(2.5 系列目录路径展开异常时触发,
  每次均收集全部 864 项)全部通过,与逐目录统计一致;
- 阶段 2.6.0c 新增 83 项(6 个测试文件),无 skip/xfail;
- 旧阶段目录中 5 个测试文件做了 API 适配(协议 v3/新 verify 签名/
  动态 seed 门槛/mock 承诺必带真实 Null 报告),断言语义保持或
  增强(2.6.0b 的 `or True` 永真断言删除并替换为真实断言);
  未删除任何旧测试,未降低任何断言强度;
- 冻结环境校验:RouteCEnvCore-v1.0.0 等六项 spec 逐项验证未变
  (见 upstream_integrity.txt);vendor/freqtrade clean,
  HEAD 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5。
