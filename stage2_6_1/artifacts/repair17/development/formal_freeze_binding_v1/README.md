# formal_freeze_binding_v1 — RouteC_FormalFreeze_ApprovalBinding_v1 准备目录

任务包: `RouteC_FormalFreeze_ApprovalBinding_v1`(承接 FLP R4 CLOSED PASS,
候选 `04d1020800794df35bd1618f9b3ffb0d21d63adf`,证据树
`c3cba8b20ebd1633be05c9858c9db7ebeca7e6e9`)。

本目录是**非生产发布准备目录**。本轮只做:链外 provenance 来源证明、
真实 Commit A、非激活部署对拍、A1/A2/B_UNAPPROVED 计划快照刷新、
只读核验与待批交付。不签发许可、不启动正式研究/训练、不激活
formal_ready、不创建生产运行实例。

## 目录

| 路径 | 内容 | 进入 Commit A |
|---|---|---|
| `provenance/` | 链外 GateTopologyReconciliation-v2 来源证明(provenance-lock 一次锁定) | 是 |
| `protection_surface/before.json` | 开工生产保护面只读快照 | 是 |
| `FREEZE_RECORD.md` | 冻结记录(基线、冻结面清单、无自引用声明) | 是 |
| `plans/A1/` `plans/A2/` | 互斥候选 A1/A2 计划快照(同一 Commit A,构建器真实生成) | 否(evidence HEAD) |
| `plans/B_UNAPPROVED/` | B 草案机械刷新(B_NOT_APPROVED) | 否(evidence HEAD) |
| `evidence/` | 部署对拍、差分回归、只读核验、隔离正反例输出 | 否(evidence HEAD) |
| `protection_surface/after.json` | 结束保护面快照 | 否(evidence HEAD) |
| `scripts/` | 本目录证据采集脚本(可复算) | 是(快照脚本) |

## 身份分层(不得混用)

1. **Git Commit A / tree**:代码冻结对象(本目录 provenance 锁定后产生)。
2. **R17 admission `git_tree_digest`**:admission 侧代码树身份
   (`curriculum261_r17_admission_substance.git_tree_digest`)。
3. **A1/A2/B 的 `qbpl-…` research_plan_digest**:各自实验内容身份
   (`curriculum261_qprod_plan.research_plan_digest`)。
4. **qualification_plan_r17**:未来链内校准后 lock-plan 产生,当前不存在,
   不以旧件或假 hash 补位。

## 状态

FREEZE_READY_PENDING_USER_APPROVAL(全部工程面就绪、等待用户选择
A1/A2 与 B 批准);真实 Level A/B/教学 NOT_RUN。
