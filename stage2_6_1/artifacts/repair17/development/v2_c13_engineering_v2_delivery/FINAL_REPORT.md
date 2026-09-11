# R17 V2 C1/C3 v2 修复与工程实验最终报告

任务 R17V2C13RepairAndPreclaimClosure-v2(2026-09-10/11)。
基线 HEAD 769b6d282b6e870491e31e92f96828543d23ab24(parent b3bb6087)。
合同 R17V2C13EngineeringCalibration-v2。

## 结论首屏(四格 family×分区 / 工程 / 统计 / 资格)

| 项 | 结果 |
|---|---|
| c1_opportunity × main strict | PASS |
| c1_opportunity × validation strict | PASS |
| c3_cost × main strict | PASS |
| c3_cost × validation strict | PASS |
| 工程路径(complete/delivered,rc=0) | 完成 |
| 工程统计 overall_strict_pass | PASS(四格全过) |
| canonical 等价 main/validation | PASS(unexplained=0;main legacy diffs=100 全部 float32 边界可解释) |
| 正式资格 | 未签发(engineering_only;不建正式 A/B,不开 qualification/exposure) |

## 执行链(S0-S7)

- S0 接手:任务包 SHA 8/8;HEAD/parent 一致;部署面 v2_c13 8 文件逐字节一致;
  132 个未提交项全为 run_supervision 历史遥测(范围外)。
- S1 四项修复:
  - B1 三族身份(describe generators 映射+validate_proof 按族;旧式单身份 runtime 拒绝);
  - B2 registry 97/4(api/registry 双表 +4 v2 namespace;governance 精确增量断言);
  - B3 strict 复算(SE 开平方根;REQUIRED_BASELINES 冷读白名单快照;always_flat 每
    rung 必查;与真实 rung_report_r4+corpus_conditions_r5 逐叶差分);
  - B4 实际对象(routing.bundle() 取用时重算三层身份;v2c13/v2c13v2 代际隔离;
    envelope 文件锚点;评估后复核;refit 守卫独立于 FIT_CALL_LOG);
  - WP4(phase 精确化/verify synthetic 语义/失败 run 冷读/fit manifest 交叉核对/
    read_episode_csv float_precision=round_trip)。
  局部测试:v2c13 42 项 + governance 32 项全绿(含 v1 首 proof 只读回归 V03)。
- S2 合成链(共享编排 core):E01-E05 + 失败演练(身份错配/备援耗尽/写失败/
  eval 中 refit/语义篡改)9 项全绿;生产生成调用为 0;synthetic 永不授予工程完成。
- S3 完整回归(claim 之前,合同前移):
  - attempt1 1942/11F/4E:torch CUDA driver probe 线程(SigBlk=0)污染直调 supervisor
    (attempt1_thread_attribution.md);
  - attempt2 同因(11F/4E);
  - attempt3 全绿 1957/7s/0F(测试基建修复:conftest CUDA 缓解 + attempts_plan PPO
    smoke/r10_preflight preflight+CLI/r10_rehearsal/r11_integration/r12_integration
    全部子进程隔离;生产代码零改动);
  - attempt4(namespace_unused regular-file 过滤后新完整候选)全绿 1957/7s/0F ENTRY_RC=0。
- S4 preclaim:三族真实 metadata(c1-v5/c2-v9/c3-v4)与 v1 proof 记录一致;
  v2 namespace 零消费;v1 claim 保留;计划落盘 preclaim/v2_plan.json
  (66cbf9f3...)+ 准入回执。claim 排他创建按合同在 S5 run() 流程内完成。
- S5 主实验(run_id v2c13eng2_20260911T005151_3574,受监护 engineering,
  max 21600s,实用时 4m25s):
  - claim 一次性消费:plan_sha256 4fbbb91a...(与 preclaim 计划差异=运行时
    namespace 扫描把 preclaim 计划文件如实分类为 planning-only,V09 语义);
  - 336 请求全部一次通过(160 fit + 176 eval;0 备援消耗;1680 attempts 预算
    实际 336 attempts);
  - 两次三课程统一 V2 fit(72 pair/144 entry/bank;save/reload/冻结/三层 hash);
  - 320 主要 scaled episode + 96 canonical episode(每分区 24 pair/48 ep);
  - 四格 strict 全 PASS;canonical 双分区 PASS;delivery/manifest 完整;
  - 业务 rc=0,supervisor 证据完整(run_record/summary/telemetry/告警 0)。
- S6 交付核验:
  - verify 冷读(修复 reader 对 reference writer Infinity 解释字段的读取缺陷后)
    rc=0:evidence_consistent=true,engineering_complete=true,四格复算=封存;
  - 实际隔离六例(unshare 遮蔽 /mnt 与 /home/cryptorl/projects,探针前后,
    mountinfo 留痕):健康 rc=0;缺件/追加/等长篡改/外层自洽路由错配/遥测追加
    全部 rc=2 拒绝;原件前后字节不变。
- S7 归档(本目录):main_run/monitored_run 2489 文件与 run_supervision 原件
  逐字节一致;preclaim/s3_full_regression(attempt1-4 全留)/s6_isolation/handover。

## 预算对账

计划 336 请求(fit160+eval176)/1680 attempt 上界;实际 336 请求全部 accepted
(C1/C2 零拒绝,C3 零结构拒绝),attempts=336(每请求 1 次),备援 p6/p7/p10/p11
全 not_needed;A/B 两侧 generator 调用 672 次(计划上界 3360)。

## reader 修复登记(S6 条款)

发现并修复 verify 的 reference_equivalence 读取缺陷:writer(_float32_explainable)
对解释性字段 decision_margin_to_threshold 写出 Infinity token,严格 JSON 读取
拒绝。修复=白名单式兼容(仅 decision_margin_to_threshold/float32_relative_quantum
允许非有限;gate/统计字段出现非有限仍拒绝)。主产物零改动;修复身份随本轮候选
源码(source_lock 重锁后)。

## 未运行项

无 NOT_RUN 的必经阶段。C2 仅参与 fit(工程控制),本轮未运行 C2 统计/训练;
正式链/qualification/exposure/新训练按任务书停止条款未启动。

## 关键路径

- 主 result: main_run/monitored_run/v2_c13_engineering_v2/result.json
- 主 claim: ../v2_c13_engineering_claim/R17V2C13EngineeringCalibration-v2.json
- envelope×2: main_run/monitored_run/v2_c13_engineering_v2/bundles/{main,validation}/envelope.json
- 四格条件: result.json statistical.*;复算 s6_verify_cold_read.json
- 完整回归: s3_full_regression/{junit.xml,stdout.log}(attempt3/4 全绿)
- 隔离: s6_isolation/(六例 out/err + mountinfo + probe)
