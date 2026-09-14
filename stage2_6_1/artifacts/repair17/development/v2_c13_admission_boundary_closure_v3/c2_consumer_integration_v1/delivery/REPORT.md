# R17C2SelectionCalibrationConsumerIntegration-v1 执行报告

## 1. 最终判定

**本轮报告消费工程：FAIL**（S4 完整回归 1 项失败；按 TASKBOOK §6 不给 conditional PASS、不重复运行追绿）。

- 合成报告的 fixture_gate_outcome：PASS（仅测试值，非业务统计）。
- 新业务统计：NOT_RUN；正式资格：NOT_ISSUED；launch_authorized=false（16 个生产入口哨兵全部零调用）。
- 旧 v2 工程 FAIL 保留原样；v3b：CLOSED PASS，未改写。
- 未实现（不因任何单项通过而省略）：真实 producer、episode/proof 来源重建、V2 fit/scaled evaluator 路由、正式参数包、生产运行授权。

## 2. 各阶段真实结果

| 阶段 | 结果 | 关键计数/证据 |
|---|---|---|
| S0 接手 | PASS | HEAD=远端=基线 3a8559ed2812b75b5b677fa6ce7395dd97998850；分支 route-c-stage2-6-1-repair17；暂存/源码面干净；工作树 192 行全部为已知 run_supervision 追加；保护区快照 OK；历史锁 SHA c9152b62…7c55 一致；包 SHA256SUMS 65/65 OK |
| S1 应用 | PASS | 包级测试 83 passed（R17_LOCAL_EXCERPT_TESTS 隔离环境，独立进程）；apply_patch check→--apply 两步 ok=true；四新增文件 SHA256 与 PACKAGE_INFO 完全一致；git diff --check 干净；r17_sync 完成 |
| S2 定向+CLI | PASS | 定向九文件 231 case（=178+53）零 fail/error/skip，new_c2_cases=53、zero_skip=true；CLI rehearse entry.rc=0；verify.rc=0，verify.json ok=true、scope=synthetic-report-reconsumption、16 哨兵全零、business_statistics=NOT_RUN、formal_qualification=NOT_ISSUED、launch_authorized=false；7 个负例全部 rejected=true 且 original_unchanged=true（missing_result/append_result/resign_wrong_decision/resign_promote_qualification/resign_swapped_candidate/replace_input_and_manifest/source_identity_changed） |
| S3 候选 C | PASS | C=749660f7501e4db70c962455387bfb5f5755cd8a，仅四新增文件（1137 行插入），父=基线，无 run_supervision 混入，提交后 sync 完成、源码面干净 |
| S4 全量回归 | **FAIL** | collect=2144 tests（=2091+53 精确一致）；monitored pytest 38m40s：**1 failed / 2136 passed / 7 skipped**；失败=既有测试 tests/route_c_stage2_6_1/test_curriculum261_r16_execgov.py::TestRealSubprocessCompetition::test_two_processes_one_winner；run_bound_regression 在 entry.rc=1 处按合同停止，new_c2_check/verify_C 未产生；全部原件保留于 full_regression/ |
| S5 归档 E | 见 EVIDENCE 段 | 失败证据如实归档；不伪装合格 E |
| S6 终验/推送 | 见回传包 | final_receipt 真实输出随回传包；远端 ref 如实记录 |

## 3. S4 失败详情与归因（全部原件已保留）

失败断言：`assert len(winners) == 1`，实际 results 仅一条 B 记录 `{'role': 'B', 'acquired': False, 'error': '另一个进程持有 R16 正式会话锁(竞争请求被拒绝;本请求对正式状态零写入)'}`；A 进程无任何 JSON 输出。

归因证据链（只读取证，未重跑、未改代码）：

1. B 的报错证明 A 已成功获得 flock（另一进程持锁）；A 应在持权生命周期结束后打印 `{"role":"A","acquired":true}`，实际 stdout 无任何 JSON 行 → A 在 acquire 之后、print 之前异常退出（exit 路径产生的 traceback 走 stderr，被测试的 `out_a, _ = pa.communicate(...)` 丢弃）。
2. 该测试文件两轮字节一致：本轮与 v3b 轮 test_files.sha256 中 test_curriculum261_r16_execgov.py 同为 20dcdb27d7e6535640322c5ecfdda2719907a0d45d534a608d9ad9d0d71c196a。
3. 基线→候选 C 的 git diff 不含 curriculum261_r16_execgov 模块（本轮仅新增 C2 consumer 四文件）。
4. v3b 轮（同一基线、同一测试文件）该测试通过，全量 2091 零失败零跳过异常。
5. 失败测试与本轮新增四文件无任何 import/行为依赖（grep 证据见 WORK）。
6. pytest 临时目录已被清理，journal 现场不可复得；失败时刻 monitored 记录 patterns=[]（无真实资源告警；stdout 中两条 CRITICAL R17ALERT 为其他测试自身的注入场景）。

结论：**既有 R16 双进程竞争测试在真实环境的一次不稳定失败（A 子进程中途异常），与本轮新增代码无因果**。但按 TASKBOOK §6"完整回归失败……不给 conditional PASS、不重复运行追绿"，本轮记 FAIL 并交回，不自行复跑或修复。建议后续：由助手决定是否授权对该既有测试单独复跑取证（例如补 stderr 捕获），或出下一包处置。

## 4. 身份与计数汇总

- 基线：3a8559ed2812b75b5b677fa6ce7395dd97998850（S0 时本地=远端）
- 候选 C：749660f7501e4db70c962455387bfb5f5755cd8a
- 证据 E：PENDING（S5 后更新）
- 定向：231/231（178+53），零 fail/error/skip
- 全量：collect 2144（=2091+53）；1 failed / 2136 passed / 7 skipped（7 为既有允许 skip，未增）
- CLI 零调用：16/16 哨兵全零；七负例全拒；冷读 verify ok
- 新生产实验/generator/V2 fit/scaled eval/claim/namespace 授权：0

## 5. 输入与源身份

- 输入包：R17_C2_Selection_Calibration_Consumer_v1_Code_and_Verification_Pack.zip（服务器 sha256 f600633e8ead87e8…，本地与包目录副本一致；副本见 WORK/input_pack.zip）
- 应用后四文件 SHA256 与 PACKAGE_INFO new_files 逐一相等（见 §2 S1 行）。
