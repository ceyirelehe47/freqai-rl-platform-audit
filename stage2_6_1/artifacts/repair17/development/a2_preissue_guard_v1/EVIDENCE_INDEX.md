# RC 轮证据索引(仓库不可变路径;归档不入包)

最终候选 513e75e35f05ed18a5ebd9db76834de938e44113 | 证据 HEAD 见 DELIVERY_RECEIPT

| 证据 | 仓库路径(stage2_6_1/artifacts/repair17/development/a2_preissue_guard_v1/ 下) | 首次提交 |
|---|---|---|
| 最终 261 record a102f967(run r21_20261005_054959,commit 9d735c8c) | evidence/regress261_d2/ | 本轮(见 git log --follow) |
| RCF 前 record 864cc48e(commit 513e75e3) | evidence/regress261_d2_rcf_513e75e3/ | e5191881 系 |
| RC 首轮 record 7b4b2be2(commit 8c160d0a) | evidence/regress261_d2_rc_gate1_8c160d0a/ | 9a8d95f0 |
| gate1-R2 record 0e106730(commit 9210cd24) | evidence/regress261_d2_r2fix_9210cd24/ | fc165e16 |
| A2-R2 v3 record 8436a1a7(commit efb35552) | evidence/regress261_d2_a2r2_efb35552/ | 8ffece2b |
| 早期尝试 1-5 原件 | evidence/regress261_d2_attempt{1_refused,2_no_dep_modules,3_partial_env,5_remaining_faces}/ | 98fc371a |
| 部署对拍/保护面 | evidence/deploy/(three_way_compare 625 all_equal;protection_before/after) | 98fc371a+ |
| P0 修复(陈旧 state 面) | evidence/p0_stateface_fix/ | cb4cc8c2 |
| reviewer 工作原件 | /f/trading/local/rc_review/(gate1 三轮)+/f/trading/local/a2r2_review/(A2-R2) | 包外不可变;结论摘录见 REVIEW_INDEX.md |
