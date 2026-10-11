# GATE3 COLD READ REPORT — RouteC_QAFv3_A2_OneShotExecution_v1（v2 复验终版）

- Reviewer 角色：独立 reviewer（第三关：真正最终 ZIP 冷读；本文件为 v2 复验终版，v1 报告存档为同目录 `GATE3_COLD_READ_REPORT.v1.md`）
- v2 冷读时间：2026-10-11T11:28Z–11:33Z（+08:00 19:28–19:33）
- 对象：`/mnt/f/trading/local/RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT.zip`（194,079 B）
- 期望 SHA256（v2）：`9235bb693c48509730addd1ccd522e2326ef68366291e66d06178d2c125b2d06`
- 解压临时目录：`/mnt/f/trading/local/qafv3_gate3_review/unpack_v2/`（v1 解压树保留于 `unpack/` 供全量对拍）
- 对照源 A：`/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qaf_v3_a2_execution_v1/`
- 对照源 B（D3 现场）：`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3`
- 工具面：WSL `/usr/bin/unzip`、`zipinfo`、`sha256sum`、`cmp`、`diff -rq`；未执行任何链步、科学计算或模型操作

---

## 沿革（v1 FAIL → 处置 → v2 复验）
- v1（SHA `0ce55a93…24f10`，193,217 B）第三关冷读 **FAIL**：唯一发现 F-1——`commands/E4_watch.jsonl` 封包竞态（ZIP 内 32 行为对照源严格前缀，watcher pid 513 封包后仍续写）。v1 终签回执 FAIL 已出具，现归档 `local/qafv3_return_archive/REVIEWER_FINAL_RECEIPT_RouteC_QAFv3_A2_OneShotExecution_v1.md.v1_FAIL_coldread`；v1 包/sidecar/旧交付回执同目录归档（`.v1*` 后缀），未覆盖。
- 处置（主 Agent）：停止观察器（`commands/E4_watch_stop.txt` 处置记录：stop 2026-10-11T11:26:07Z、pid 513、根因=观察器 snap() 内 `rc_alive` 局部变量缺陷致终止条件永不 break、终态 45 行、SHA `12537627…df4b`）；冻结 `E4_watch.jsonl`；重封 v2 并同步重写 sidecar/交付回执。

## 检查项结果（v2）

### 1. ZIP SHA256 与 sidecar — PASS
- 实算：`9235bb693c48509730addd1ccd522e2326ef68366291e66d06178d2c125b2d06` == 期望值；大小 194,079 B。
- sidecar 同值、文件名指称一致（19:27 重写）。

### 2. 结构与清单安全 — PASS
- `unzip -t`：127 成员全部 `OK`，`No errors detected`。
- `zipinfo -1`：重复名 0；绝对路径 0；`..` 0；盘符 0；非普通文件/目录成员 0；成员名含反斜杠 0；顶层目录唯一 `RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT/`。
- 构成：114 文件 + 13 目录项（含顶层）= 127 成员。

### 3. SHA256SUMS.txt 复算 — PASS
- 113 条；`sha256sum -c` rc=0，113/113 OK；不含自身；路径形态干净（无 `^/`/`../`/盘符）。
- 条数==内容文件数：113 == 114 − 1（SUMS 自身）。
- 隐藏件 `d3_snapshot/.r17_formal_admission.json` 仍在清单；新增件 `commands/E4_watch_stop.txt` 在清单（`c36124629f96700e627cda6be6a56eceea248bf043bdb40e337840fbe63bc69e`，与包内实算一致）。

### 4. 与对照源逐字节对拍 — 全 SAME（v1 FAIL 项已闭环）
- 七项（EXECUTION_REPORT.md / EX_SELF_CHECK.md / E0_READ_ONLY_CHECK_REPORT.md / commands / d3_snapshot / reviewer_gate1 / reviewer_gate2）`diff -rq` 全部 SAME——含 `commands/E4_watch.jsonl`（现为冻结终态）与新增 `E4_watch_stop.txt`。
- d3_snapshot 四件与 D3 现场原件 `cmp` 全 SAME：r17_code_freeze.json（`d559d0d0…b642a`）、chain_budget_gate.json（`5d16063f…f4854f`）、cue-audit.err（`5debf8b7…b3aa94`）、r17_execution_journal.jsonl（`52722ffd…e6f36b`）。

### 4b. v1→v2 变更集核验（超出抽查的全树对拍）— PASS
- 对 v1/v2 两个完整解压树 `diff -rq`：差异**恰好**为声明变更集三条——
  1. `SHA256SUMS.txt` 重算（112→113 条）；
  2. `commands/E4_watch.jsonl` 32 行→冻结终态 45 行（包内 SHA `125376276280a03de026915de72d001fb07aa4b7b626d112973beba7f716df4b`，与对照源及处置记录一致）；
  3. 新增 `commands/E4_watch_stop.txt`（处置记录，合法新增件）。
- 其余全部内容与 v1 逐字节一致（覆盖 EXECUTION_REPORT/EX_SELF_CHECK/E0 报告、全部 commands、d3_snapshot 78 件、reviewer_gate1/2）。

### 5. 关联抽查 — PASS
- argv/consumed/issued/formal_admission/permit 五面 ID 链与 v1 逐字节相同（由 4b 全树对拍保证），v1 已核：admission `qaf-v3-c0fb6858-a2`、permit `qppm-formal-ed1e6a965ab55ab6`、`--attempt qaf_v3`、`--stop-after verify-formal-logs`==permit `authorized_stop_after`、`--code-freeze-sha`==admission `commit_a_sha`==permit `code_freeze_sha`。
- 新增处置记录 `E4_watch_stop.txt`：`watcher_stop_utc=2026-10-11T11:26:07Z`、`watcher_pid=513`、`final_lines=45`、`final_sha256=12537627…` 与现场实况一致；`SUMS.txt` 不含自身。

### 5b. 观察器冻结态独立复核 — PASS
- 冷读时 `ps` 无 `qafv3_e4_watch` 进程；`E4_watch.jsonl` 45 行/5,859 B/SHA `12537627…`，mtime 19:25:54(+08) 早于封包 19:27。
- 65 秒窗口复测（11:29:14Z→11:30:18Z）：行数与 SHA 完全不变——确认不再增长。

### 6. 大件与路径形态 / 敏感串 — PASS
- 无模型/语料大件，无可疑后缀件；成员名无反斜杠。
- `grep -rIl 'password\|token\|private key'` 及大小写不敏感变体对 v2 全树均无命中（新增处置记录为无害运维文本）。

---

## 发现
- 无新增发现。F-1（v1 封包竞态）已按处置闭环：观察器停止且经 65s 复测确认冻结、冻结终态入包、变更集之外零差异。

## 结论
**PASS（针对 v2 SHA `9235bb69…b2d06`）**——检查项 1–6 全部通过；v1 FAIL 项闭环；包外终签回执 `/mnt/f/trading/local/REVIEWER_FINAL_RECEIPT_RouteC_QAFv3_A2_OneShotExecution_v1.md` 已绑定该 SHA 出具（含 v1→v2 沿革与失效声明）。

## 局限
- 冷读仅做产物与摘要核验：不重跑链、不重放科学计算、不训练/加载模型；不审计冷读时点之后 D3 现场与对照源的变化。
- 冻结态结论基于冷读时点进程 absence + mtime + 65s 复测窗口，非永久性断言。
- 后端模型元数据不可观测；结论只针对上述固定 SHA 的 ZIP 字节。
