# R17 v3a：V10 夹具兼容修复与 v3 验收续接

任务：`R17V2C13V10FixtureRepairAndVerificationResume-v3a`

仓库：`ceyirelehe47/freqai-rl-platform-audit`  
分支：`route-c-stage2-6-1-repair17`  
固定应用 HEAD：`1ea193c0f1eb710e37aa23aa89f261617eb93c43`  
直接父提交：`04b2978a1e2c375bd347168f2a9eeded790b393e`

这是已经实现的**单测试文件补丁＋实机验收续接包**。不要再次应用旧 v3 的九文件应用器，不回退到 `04b2978…`。

读取顺序：本文件 → `TASKBOOK.md` → `RUNBOOK.md` → `SOURCE_MAP.md` → `ACCEPTANCE_MATRIX.md`。

## 本次修复

旧 `_claim_fixture` 复制了不再合法的成功前提：synthetic authority 配生产合同、空 source identity、没有实际回归包却写假摘要。生产守卫拒绝它是正确行为。

本包让 pipeline 夹具在函数内延迟导入并复用现有 claim_protocol 的 `_persist_plan_and_receipt`。后者已在失败轮 WSL 的 20 个协议测试中通过：它创建 synthetic 合同、非空 fixture source identity、真实临时回归包和实际摘要。

原 `test_v10_one_shot_claim`、损坏 claim 测试及其他既有测试体逐字保持不变。另加一个健康实包检查与四个参数化拒绝场景。没有改生产源码、守卫、source lock 或统计定义。

## 接续范围

应用修复 → 同步 → 八文件定向重验 → 新候选 C → 尚未执行的完整 R17-first 回归 → 健康包/副本负例 → E → 提交后 full 冷验。

八文件预计从 152 增至 157 个 case，以实际 collection/JUnit 为准；不能跳过原 v10 或删减测试来符合数字。上一轮没有执行完整回归，本轮通过定向后执行一次，不为 E 再跑 pytest。

## 证据位置

唯一新子目录：

`stage2_6_1/artifacts/repair17/development/v2_c13_admission_boundary_closure_v3/continuation_v3a/`

使用现有 v3 根下的新子目录，是为了符合已安装 guard 的 evidence-only 白名单。**不得改 v3 根中已经存在的 REPORT.md、日志、SHA256SUMS 或任何旧文件。** 不新增平级 v3a artifact 根，也不修改 guard 白名单迁就新目录。

## 停止与提交

Agent 只应用、同步、测试、采集原件、普通 commit/push。任何应用/定向/全量/采集/冷验失败，保留输出、按失败交付，不自行调整边界或删除 case。

成功：普通候选 C 与 evidence-only E，必要时 E2；失败：可审查的失败提交，明确不得用于准入。禁止 reset/rebase/amend/force-push 或清理未知工作。活动 run_supervision 变更单独记账，不混入提交。
