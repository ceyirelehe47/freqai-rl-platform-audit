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
