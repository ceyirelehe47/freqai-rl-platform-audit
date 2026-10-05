# A2 失败交付复验收口报告 — dsv4.1f（RouteC_QAFv2_A2_OneShotExecution_v1，续线）
日期：2026-10-05（UTC+8）｜复验对象：commit a94fb2a0（parent c47028f6）修复面｜只读，未签发/未 launch/未重跑 prepare/未科学计算
承前任 ExGate1（c47028f6 验收：correct/0.88，F1-F3 P2、F4-F6 P3）修复后复验。

## 0. 方法
- 冷拷逐字节：脚本 `cold_verify.sh` 将 `d_side_originals/` 41 件与 D2 现场（/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2）对应原件的 live sha256 逐件比对 → 41/41 MATCH（`cold_verify_result.txt`）。
- 无回退：`cmp_prev.sh` 读前任 `hash_compare.txt` 记的 37 件 sha 与当前仓内冷拷比对 → 37/37 未变（`cmp_prev_result.txt`）。
- 现场只读探针：D2/P2/旧 P 自 abort（本地 18:32:13）后新增写入 = 0/0/0；旧 P admission `b465e5f1…` 未变、18:00 后 0 新文件。
- 提交纯度：a94fb2a0 = 8 新文件 + EXECUTION_REPORT 修改，全部落在 `qaf_v2_a2_execution_v1/`；c47028f6 同理（src/tests/runner 零改动）。HEAD= a94fb2a0，工作树无未跟踪/未提交的该目录文件。
- blob 与工作树字节一致（8 新文件逐一 git show 比对）。

## 1. F1–F6 逐项复验
- F1 ✅ d_side_originals 现 41 件；新增 4 件逐字节等于 D2 原位：
  environment.yml `e7a0850e…`、requirements-lock.txt `4e727d3d…`（均与旧 P 同字节）、r17_admission_issued.jsonl `c8e2954e…`、formal_root/gate_topology_reconciliation_digest.txt `cde2b72a…`。报告 §6 计数 41/50 与实物一致。
- F2 ✅ `e1_e2/prepare_output_20261005T1020Z.recovered.txt`（`f7cf76f6…`，与前目录 recov 件逐字节同）在场，内容=幂等 installed=false/idempotent_ok=true/actions=[]/same_source_verify ok rc=0/one_shot_writes=0；`e1_e2/install.json`（`a704eb65…`）在报告 §1 改标为 R3 安装点原始记录（同字节于 rc_closure/d2_installpoint）。
- F3 ✅ `user_approval_statement_20261005.recovered.txt` 在场，288B，sha256=`724d9fff…` = admission/perm 绑定 statement_digest；来源注记（§1603/omp 会话 user 消息/日期/会话 transcript）见报告 §1。
- F4 ✅ `e4_attempt2_refused_approval_source.recovered.log`（`d18a4b36…`）在场且注明来源=会话 transcript、非现场原字节；报告 §1 说明 take2 日志被 take3 覆盖。
- F5 ✅ EXECUTION_REPORT §3.5 绑定注记在场：authorization 内嵌 qfap-06b07282… 为 take2 被拒修订摘要，生效绑定=qfap-fb6a072a…（与批准原件/permit bound_approval_digest 一致）。
- F6 ✅ `e0_preflight/e0_prerun_snapshot.json`（`ffe0a371…`）填充（provenance=会话 E0 预检恢复件并注明）；空目录已无；全树无空目录。

## 2. 面无回退
- D2 原件未动（41/41 live MATCH；37/37 与前任记录一致）；abort 后 D2/P2/旧 P 零写。
- 两提交纯证据，无重跑/重签/换根/回写冻结面；一次性资源零再消费。
- 证据目录 51 文件（含本报告外的 50 件证据 + EXECUTION_REPORT.md）。

## 3. 结论
**correct / PASS**。前任 F1–F6 全部落地且证据可核，无新缺陷、无回退。EX10 可闭合，包可冷读/封 RETURN。
