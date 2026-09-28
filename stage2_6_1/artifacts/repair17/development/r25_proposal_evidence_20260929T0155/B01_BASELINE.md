# B01 基线与执行面记录 — RouteC_R25_ProposalEvidence_SelfAcceptance_v1

记录时间：2026-09-29T01:55+08:00（本地）；全部由实际命令输出支撑。

## 身份

- repo：ceyirelehe47/freqai-rl-platform-audit
- branch：route-c-stage2-6-1-repair17（本地与 origin 一致，`git rev-list --count` 双向为 0）
- 观察基线 HEAD：e0cdd5ea3ac6a1d7500e61e0759f72509fd46850（=发包基线，未前进）
- 原已测代码候选 C：7e9e5470889884bad296a2dbb4b3e55ca38bc151
- 提交链：75343094（上轮发包基线）→ 7e9e5470（C：r25_worker_probe.py + registry 测试）→ 30d856ab（证据 E）→ e0cdd5ea（回执定稿）

## 执行面判定

- `git diff --name-only C..HEAD` 全部落在：`stage2_6_1/artifacts`（120 文件）与 `stage2_6_1/report`（1 文件：训练提案原件）。
- 无 `stage2_6_1/src|runner|tests`、无 `stage2_6_2/src` 变更 → **执行面与 C 完全一致**。
- 工作树未提交状态（49 untracked / 1 deleted / 9 typechange）全部位于 `stage2_6_1/artifacts/repair17/development/` 下的历史证据路径（r24 尝试脚本、run_supervision 历史 run、r25_final_closure return_stage 等），不含任何 src/runner/tests 路径 → 不改变执行面。
- 工作树已知偏差（不触碰、不影响执行面）：
  - `D stage2_6_1/artifacts/.../r25_final_closure_20260928T160624/candidate_C_push_receipt.txt`（HEAD 中在册，工作树缺失；本轮一律以 `git show HEAD:<path>` 读取该文件，不改工作树）。
  - 9 个 typechange 均为 c3_entry_temp_ownership_closure / v2_c13 历史证据中 symlink 型成员的呈现差异。
- 结论：本轮为纯文档/只读核验/打包变化 → **复用 C=7e9e547 的既有 WSL 全量回归与集成原件**，不重跑；本轮不产生新代码候选。

## 本轮变更面（计划）

仅新增：修订提案 v2、本轮只读核验脚本/结果、交付说明（均在本目录或 report/ 下新路径）。不改旧原件、不改 runner/src/tests、不做正式注册/抽样/cue-audit/资格消费/训练。

## 工作区清理备注（2026-09-29，用户授权）

goal_incoming 旧轮残留 20 项 + rounds/r21 移入 `archive/goal_incoming_history_20260929/`（账目 `archive/REORG_MANIFEST_F_20260929.tsv`）；git 本地+远端删除 repair11–16（均为 HEAD 祖先，提交仍可达）。`trading/outgoing`、`trading/packs`、仓库在飞未提交变更原样保留；清理后实测 FinalClosure RETURN SHA 仍为声明值 87d7c88b…。
