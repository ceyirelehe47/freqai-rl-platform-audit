# A2-R2 独立 reviewer 证据索引(封包引用;原件不可变存 local/)

验收线:用户指定 dsv4.1f(=task.agentModelOverrides reviewer→commandcode/deepseek/deepseek-v4.1-flash:max);三会话同线:
- ReviewerA2R2Gate1(首轮+复验,中断于上下文上限)
- ReviewerA2R2Gate1R2(收口会话;终审)

| 阶段 | 结论 | 关键证据(原件目录 /f/trading/local/a2r2_review/) |
|---|---|---|
| gate1 首轮 | incorrect(6 findings:3×P1+3×P2) | SUMMARY.md;outputs/probe_admission_bypass.txt、probe_launch_drift.txt、probe_paths.json、stale_pins_failures.txt |
| gate1 修复复验 | 5/6 实证过,余 N1(P1)+N2(P2) | outputs/probe2_*、reverify_* |
| gate1 收口(N1/N2 修复后) | **correct/0.88** | 同会话结论;仓库证据 evidence/w2_gate1_fixloop/post_fix_suites.txt(193 全绿) |
| gate2 终审(PG01–PG12) | incorrect(P0:陈旧 state 面) | GATE2_REVIEW.md;outputs/gate2_*(prepare_rerun/plan_reverify/protection_diff/substance_D2/three_way/operator_check_D2) |
| gate2 P0 修复复验 | **correct/0.92,零阻断** | outputs/gate2_fix_affected287.txt(11 文件 287/287)、gate2_fix_preissue.json、gate2_fix_substance.json、before_cleanup 独立对拍 |
| 终签措辞 | "本任务工程准备通过,A2_RETRY_READY_PENDING_USER_APPROVAL"(不代签 ChatGPT 终验/用户新 A2 批准) | IRC 终审记录 + 本索引 |

P3(计数措辞)已在 6a4ea870 修复(guard+7 既有=8 文件 222 全绿;reviewer 超集 11 文件 287/287)。
封包基线:HEAD=6a4ea870;src/tests/runner 相对候选 efb35552 零变化(git diff 空)。

## RC 轮(RouteC_QAFv2_ReviewClosure_v1;dsv4.1f 同线 RcClosureGate1)

| 阶段 | 结论 | 关键证据(local/rc_review/) |
|---|---|---|
| gate1 | incorrect(4:1×P1+2×P2+1×P3) | REVIEW_REPORT_RC.md;rc04_ab_report/init_natural_ab_report/mismatch_*/reentry_probe |
| gate1-R2(修复 9210cd24 后) | incorrect(2×P2+1×P3:F2 快速路径未闭/PREP 阻断/文档旧值) | REVIEW_REPORT_RC_GATE1_R2.md;fastpath_demo/prep_demo/mismatch_*_9210 |
| gate1-R3(修复 513e75e3 后) | **PASS(1 P3 文档 nit 已修)** | REVIEW_REPORT_RC_GATE1_R3.md;fastpath_demo_513e/init_natural_ab_513e(0 回溯)/positiveprep_513e(PREP 正例全链)/rc04_ab_513e/substance_*_rerun_513e/tests 套件 73/73 |

候选演进:efb35552(A2-R2)→8c160d0a(RC:authority O_EXCL+并发/前缀测试)→9210cd24(F1 绑定门+F2 部分+文档)→**513e75e3(F2 快速路径有界重读+PREP 迁移+文档 rebase;最终候选)**。

## RCF 有限修复轮(ChatGPT 终验 FAIL→FiniteRepair_Brief;dsv4.1f 同线 RcfRepairGate1)

| 阶段 | 结论 | 关键证据(local/rcf_review/→已归档 evidence/reviewer_rcf_archive/) |
|---|---|---|
| RCF R1 | incorrect(2×P2:签发日志幽灵路径漏检再签;leaf 旗标校验晚于三件一次性写) | REVIEWER_DSV41F_RCF_RECHECK.md;probe_B_state B5/B6/B8 |
| RCF R2/R3(修复 f4684c1e→cff3f5d2) | **PASS**(真实日志首写前 rc4 零写;旗标前移;生产根守卫恢复;report-out 硬化;85/85;生产等价性验证) | r2_probe_{A,C,C2,D}.json;r2_suites.log |
| R4(残余观察闭环 9d735c8c) | 手工 env 哨兵首写前拒(测试 19/19) | closure 测试套件 |

候选演进续:513e75e3→1ea6bba8(RCF 实现)→f4684c1e(真实日志+前移)→cff3f5d2(生产根守卫)→**9d735c8c(env 守卫;最终候选)**。
