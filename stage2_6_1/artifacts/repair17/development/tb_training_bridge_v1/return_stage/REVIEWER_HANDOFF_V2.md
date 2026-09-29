# REVIEWER_HANDOFF_V2 — B1–B4 返修复验交接

你是 `RouteC_QualifiedInput_TrainingBridge_v1` 返修轮独立 reviewer（OMP agent=reviewer，配置模型 zhipu-coding-plan/glm-5.3-flash）。上轮内容验收曾 PASS，但 ChatGPT 独立终验 **NOT_CLOSED_ENGINEERING**（四阻塞 B1-B4 + §6 补件）。本轮对修复候选 C3 完整独立复验：不因过去 PASS 跳过任何项，不为找 FAIL 强行找错。

## 必读（按序，原任务与失败上下文优先）

1. ChatGPT 终审报告（本轮验收依据）：`F:/trading/trading/goal_incoming/RouteC_TrainingBridge_Review_c85eee4e_Evidence/RouteC_TrainingBridge_Review_c85eee4e/REVIEW.md`（§2-§6 阻塞定义、§7 接续方式；同目录 probes/ 有其 16 反例与 QUOTA_RESULT.json）
2. 原任务包：`F:/trading/trading/goal_incoming/RouteC_QualifiedInput_TrainingBridge_v1/`（NEXT_GOAL/SCOPE_AND_BUDGET/ACCEPTANCE_MATRIX/RETURN_REQUIREMENTS/REVIEWER_PROMPT/SUPPLEMENT_RemoveRoundTimeLimit_v1.txt）
3. 修复对账（主 Agent 写，待你核验）：`return_stage/B_FIXES.md`
4. 上轮你的内容报告（历史参考）：`return_stage/REVIEWER_CONTENT_REPORT.md`

路径前缀：仓库 `F:/trading/freqai-rl-audit`；TB=`stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1`；ENG=`stage2_6_2/artifacts/eng_training_bridge_v1`。

## 候选与证据身份

- 候选链：C `803fe66e` → C2 `e565298d` → **C3 `611966b28bc0d2baeff396e8f42e91ddb1729e4e`**（B1-B4 修复）→ 证据 HEAD `d599b7340dc393ca74a09e8cf22c6c0735f69658`（已 push；回执 `TB/git_receipts/push_receipt.txt`）
- 修改面：`ppo262_entry_specs.py`（新，六入口共享 prepare 管线）、`ppo262_qualified_input.py`（B2.1 装载交叉核验 + N01 fit namespace 隔离 + verify_integrity + profile 上下文）、`ppo262_eng_profile.py`（路由 v2 真实管线+哨兵、冷读全绑定、B4 配额预约）、`ppo262_cli.py`/`ppo262_smoke.py`（实调点接共享解析器）；20 项新反例测试 `test_ppo262e_review_fixes.py`
- 回归：C3 树 261 全收集 ok=true（run r21_20260929_134230，2541=2534+7skip，import surface 315 成员）+ 262 全套 224 passed（=204+20）
- C3 零配额运行原件：`ENG/c3_verification/`（lock rc=0 / route rc=0 / cold-read rc=0 / formal-reject rc=2）；既有 checkpoint 经 `eng_ppo_smoke_256.manifest.v2.json` 显式已核验迁移（candidate_commit=e565298d，blob 复算）通过冷读
- 复验环境：WSL 部署树 `/home/cryptorl/projects/crypto_rl`（已同步 C3；conda freqtrade-rl；PYTHONPATH=src；PYTHONDONTWRITEBYTECODE=1）

## 硬约束

- 配额不重置且已满：原生 bank 重放 2/2、成功 12/12 —— **禁止任何原生 episode 生成/fit**；optimizer 剩 6/8 但**本轮复验不得新增 smoke**（eng-run 会触发生成）；只读复用既有工件与合成夹具
- 组件反例零生成零优化；你的检查脚本写隔离目录 `F:/trading/tmp_reviewer_tb_v1_fix/`（已建），不改被审产物/候选
- 同时最多 1 个重型 WSL 任务；不必重复 261 全回归（C3 已有 ok=true 记录），可复跑 262 定向与你的独立反例
- 逐条复现 REVIEW.md §2-§5 反例语义（可用原包 probes 脚本或仓库公共实现），每条配合法对照；另覆盖其 8 类最低反例在 C3 上的行为
- 检查 §6 补件：`return_stage/reviewer_originals/` 是否为上轮 reviewer 工作区 `F:/trading/tmp_reviewer_tb_v1` 的原样复制（逐字节比对）
- 运行时后端模型元数据未提供时如实记录"未提供"

## 产出

`REVIEWER_CONTENT_REPORT_V2.md` 写入 `F:/trading/trading/outgoing/`（包外暂存，封包时原样入 RETURN；勿写 return_stage——主 Agent 已冻结该目录等待你的结论）。内容：逐项 B1/B2.1/B2.2/B3/B4/§6 + 原 ACCEPTANCE_MATRIX 必需 ID 复核 + 你实做的独立反例清单与结果 + 配额消耗声明（应为零生成零优化）+ 最终判定 PASS/FAIL/BLOCKED（FAIL 给最小复现与关闭条件）。
