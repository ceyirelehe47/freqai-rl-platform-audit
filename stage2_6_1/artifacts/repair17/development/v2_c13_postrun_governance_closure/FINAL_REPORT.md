# R17 V2 C1/C3 事后治理封口与 C2 启动准备 — 最终报告

任务 `R17V2C13PostRunGovernanceAndC2LaunchPrep-v1`（2026-09-11）。
基线 d3cdf3d1bd4b40ba91013c31b14fc03eccb5ae11（parent 769b6d28）。
本轮真实生成 / fit / eval / canonical / policy / claim / exposure
计数全部为 **0**。

## 结论首屏（任务书 §11.2 四段 + 三状态）

### 旧 v2（R17V2C13EngineeringCalibration-v2）四层结论

| 层 | 结论 | 证据 |
|---|---|---|
| 数值路径 | **complete**（数值链真实走完；320 scaled episode、两 bundle、canonical 双分区） | independent_verdict/verify_stdout.json |
| 工程合同 | **FAIL**（独立审查六项缺口成立，不可追认） | INDEPENDENT_REVIEW.md + 本轮四态复算 |
| stored-table 统计诊断 | **PASS**（四格 C1/C3 × main/validation strict；诊断口径，不是正式校准证据） | 同上 statistical_strict_pass 全 True |
| 正式资格 | **NOT ISSUED** | 同上 formal_qualification_issued=false |

### 本轮状态

| 项 | 结果 |
|---|---|
| governance_closure_ready | **true**（G01-G12 / P01-P04 / E01-E10 / S01-S02 / R01-R04 见 coverage_index） |
| c2_launch_preparation_complete | **true**（C01-C06 全过；差分 11/11；草案 NOT_AUTHORIZED） |
| 本轮生成/fit/eval/canonical/policy/claim/exposure | 全部 0 |

## 新生产 verify 的四态 verdict（对旧 v2 归档，CLI 实测）

```text
numerical_path_complete          = true
stored_table_strict_diagnostic   = PASS
governance_contract_pass         = false
formal_qualification_issued      = false
engineering_complete             = false   ← 不再因字节自洽自动为真
governance_flags:
  claim_bound_to_plan              = true
  plan_format_layered              = false  (runtime 内嵌扫描;66cb→4fbbb 根因)
  routing_matrix_binds_frozen_hash = false  (6/6 行 expected_bundle_hash="(unbound)")
  episode_identity_fully_rebuildable = false (608/608 旧格式无 hidden → partial)
verify CLI rc = 1（不可签工程 PASS）
```

## 治理修复面（G/P/E 对应实现）

1. **WP1 协议（G03-G12）**：`r17_v2_c13_profile.py` 删除
   `R17_V2C13_REPO_ROOT` 环境旁路（生产根固定常量 + 显式
   set_test_authority fixture 接口 + claim 根内路径守卫）；新增
   create-only 权威三元组持久化（plan fsync+重读 / evidence /
   receipt）；claim 只能从持久化 plan 文件取得（O_EXCL，payload 绑定
   plan 文件字节 sha）；`r17_v2_c13_pipeline.py` 新增
   `prepare_authoritative_plan()`（preclaim 流程）并重构 `run()`：
   消费同一权威 plan（runtime/evidence 双对拍，漂移即拒）→ 复验
   receipt（同 plan digest + 同 source closure）→ 从文件 claim →
   首次生成。计划身份分层：namespace 扫描等易变观察写独立 evidence
   （含 planning-only 自引用规范化），plan digest 不再因扫描时序分叉。
2. **WP2 双闭包（P01-P04）**：全盘搜索执行闭包 `591b1f35...`
   （部署/run_supervision/git 8408 blob/隔离副本）零命中 →
   `execution_source_bytes_available=false`（诚实不可用，不重构）；
   事后 reader 闭包 `93f2d59a...` 与本轮治理闭包分层记录于
   source_provenance/provenance_dual_closure.json。
3. **WP3 冷读封口（E01-E10）**：verify 全面扩充 —— episode_artifacts
   键集精确=selected（E01）；v2 持久化格式补 hidden CSV+完整 spec，
   生产 reader 对实际重载对象重算权威 `episode_content_hash`（E02/E03，
   旧 608 文件按 partial_legacy 诚实登记）；fit manifest 逐成员绑定
   selected proof episode hash + stdlib multiset 重算（E04）；eval
   selection→episode→pair row→report 逐成员链（E05）；result/delivery
   统计必须从已复核 conditions 派生（E06）；canonical 固定前 3/stratum
   成员精确核对（E07）；routing ledger 携带真实 expected/actual 三层
   身份、verify 与 frozen checkpoint 交叉验证（E08，含
   require_eval_routing_r17 透传与 reference 死参数修复）；四态
   verdict 替代单一 engineering_complete（S02）；对旧 v2 只读副本五类
   语义负例全部拒绝（E10，ep_map/fit_src/routing/canonical/stat_flip；
   控制组通过）。
4. **WP4 合成链**：synthetic_chain 全部走新协议（fixture 经生产
   prepare_authoritative_plan 持久化权威三元组后 run 消费），健康+
   失败演练 9 项全绿；协议单元 15 项（含并发 O_EXCL 恰一胜、崩溃保留、
   tamper 拒绝、环境旁路删除断言）。
5. **WP5 C2 prep**：固定设计差分 11/11（见
   c2_calibration_launch_preparation/）；midpoint 候选以白名单字面
   覆盖新增（仅供下一份授权任务书审阅）；零调用哨兵实测。

## R17-first 完整回归（R01/R02）

- 定向组：claim_protocol+pipeline 57 passed；reader_binding+
  synthetic_chain+c2_prep+governance 54 passed（原件 stdout 留档于
  claim_protocol_tests/ 与 reader_positive_negative/）。
- 全量：full_regression/（junit.xml + stdout.log + run_meta.txt，
  ENTRY_RC 以后附行为准；候选=本轮最终 source lock）。
- 部署面与发布库同步（r17_sync），source lock 重锁（26 成员集合
  不变，5+1 文件值更新；部署导入面与锁逐位一致）。

## 原件不变性（G02/R03）

WP0 前置 byte snapshot 5968 文件（original_byte_snapshots/
snapshot_before.tsv，0 错误）；收尾对拍见 snapshot_after.tsv 与
diff 报告（本轮只读访问旧树；run_supervision 活动遥测除外说明见
snapshot_diff_report.txt）。

## 未运行项 / 停止边界

- 未重跑 v2、未创建任何 C2 namespace/claim/正式 plan、未开
  qualification/exposure/BC/PPO（任务书 §12）。
- 下一轮真实实验（含 C2）需独立任务 ID + 全新 namespace/claim +
  最终 plan + 明确授权（NEXT_EXPERIMENT_TASKBOOK_DRAFT.md，
  NOT_AUTHORIZED）。
