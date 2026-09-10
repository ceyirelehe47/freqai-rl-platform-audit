# R17 C3 校准统计消费端接线：最终报告

日期：2026-09-10。分支 `route-c-stage2-6-1-repair17`，接手基线 `5607876b213af825d618868ba89cb0705cfdc472`。
固定环境：CryptoRL-Ubuntu-24.04 / cryptorl / Python 3.11.16 / conda freqtrade-rl。

## 1. 执行接线结论

**engineering_consumer_complete = true；run 与 delivery rc 均为 0。**

- 监护 run：`c3calbridge_20260910T113010_107611`（task_kind=engineering，business_rc=0，incidents=0）。
- 输入为旧已验收批次 `c3reserve_v1_20260910T050655_93442`（manifest Git blob `0ef26c7edd2a3b41aac345a751304fb4df2b75bc` 校验通过，未替换批次）。
- 组合 verifier：9 项 required/native 文件前后两次检查全部精确字节一致（exact_bytes_ok=true，含 telemetry_win 7860 字节、native sampler 退出确认），control_failures 为空，overall_ok=true。
- 业务输出完整落位 `handoff_run/monitored_run/c3_calibration_bridge/`：input_batch 只读副本、plan、episodes、analysis、result、manifest。
- 零生成：new_pair_requests=0、new_evaluator_invocations=0、preprocessor_fit_performed=false；接口检查中生成器/policy evaluator 哨兵零触发。

## 2. 统计诊断（与工程结论分开记录）

**statistical_diagnostic_pass = false，verdict = FAIL；split_pass：main=false，validation=false。**

这是固定小样本（每分区×rung 2 pair、raw production observation）在既有 R5 strict 条件（κ=1.5）下的诊断结果，按合同**原样保留**：未换样本、未扩样、未改门槛、未调 κ、未使用 pooled rescue、未以 bootstrap CI 替代。接线不因此回退。
**calibration_qualified = false**（本轮所有路径恒为 false：raw 输入、无 V2 完整流程，即使统计恰好通过也不能升格）。
计数勘误见 `RETURN_COUNT_CORRECTION.md`（160 个策略收益值；负 64 / 正 48 / 零 48）。

## 3. 仍未执行的部分

- V2 preprocessor fit/transform、统一 fit bank、envelope routing。
- 全尺寸 calibration 语料（本轮未把 2 pair/rung 无声扩成更多 pair）。
- 正式 calibration 资格、正式 A/B、冻结。
- policy evaluator、PPO 训练、任何新 namespace/生成坐标。
- 旧终态全部保留不变：p52/rt3、r3 telemetry FAIL、R16 C2 统计 FAIL、C3 PPO Branch D 互不追认。

## 4. 测试与隔离

| 项 | 结果 |
|---|---|
| 任务包局部测试（包内） | 68 passed / rc=0（55 bridge + 13 应用器） |
| 部署联合（reserve 69 + bridge 55） | 124 passed / rc=0 |
| 常规全量回归（一次，R17-first，121 文件，无 grep -v/--ignore） | JUnit 1913 tests / 1906 passed / 7 skipped / 0 failures / 0 errors，entry rc=0（=1858 collected + 55 新增） |
| 组合隔离五例（unshare/user/mount） | healthy=0、bridge_missing=1、bridge_append=1、bridge_same_length=1、telemetry_append=1，全部 payload_unchanged，overall_ok=true |

- 全量回归含 reserve 与 bridge 两个测试文件（test_files.txt 可核），未删测试凑数。
- 隔离 WORK_DIR 原样副本在 `isolation/work_dir_copy/`（外层日志与 isolated_result.json 同目录）。

## 5. 失败与未保存历史证据的如实说明

- 本轮无工程失败。统计诊断 FAIL 是数据结论，不是执行失败，未触发重跑。
- 上一轮测试定位小修的部署侧 69 项日志已存在并归档于 `previous_path_fix/`（69 passed / rc=0）；本轮部署联合 124 项是新执行，不冒充旧执行。
- 旧 full_regression_run2 的陈旧 rc=96 历史既不覆盖也不追认；历史 launcher 未修改。
- 本轮执行备注：阶段1首次运行时校验命令因执行脚本把 `cd 任务包` 置于环境激活（激活脚本内部会改变工作目录）之前而失败一次（checksums.log 记录 SHA256SUMS 找不到）；属执行脚本顺序错误，非任务包缺陷，修正顺序后同包重跑全绿。失败尝试的空证据目录已删除重建，未产生任何仓库改动。

## 6. 提交范围

`stage2_6_1/runner/r17_c3_calibration_{bridge,authority,delivery,source_lock}.py`（4 新增，source_lock 为应用器生成）、`test_curriculum261_r17_c3_calibration_bridge.py`（新增）、`test_curriculum261_r17_c3_reserve_batch.py`（上一轮授权定位小修，blob 67dd02eb→97241f8f，本轮一并入库）、本归档目录。生产模块、src、registry（89/4）、旧 source_lock、参数、κ、历史产物与启动脚本零改动。
