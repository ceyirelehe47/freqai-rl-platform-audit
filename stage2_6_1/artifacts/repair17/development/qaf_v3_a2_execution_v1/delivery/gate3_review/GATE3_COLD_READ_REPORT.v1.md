# GATE3 COLD READ REPORT — RouteC_QAFv3_A2_OneShotExecution_v1

- Reviewer 角色：独立 reviewer（第三关：真正最终 ZIP 冷读）
- 冷读时间：2026-10-11T11:13Z–11:21Z（+08:00 19:13–19:21）
- 对象：`/mnt/f/trading/local/RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT.zip`（193,217 B）
- 期望 SHA256：`0ce55a93196badbe919b37d03e5094b3452baca88e1ec7ea0e8ad67b06a24f10`
- 解压临时目录：`/mnt/f/trading/local/qafv3_gate3_review/unpack/`
- 对照源 A：`/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qaf_v3_a2_execution_v1/`
- 对照源 B（D3 现场）：`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3`
- 工具面：WSL `/usr/bin/unzip`、`zipinfo`、`sha256sum`、`cmp`、`diff -rq`；未执行任何链步、科学计算或模型操作

---

## 检查项结果

### 1. ZIP SHA256 与 sidecar — PASS
- 实算（WSL `sha256sum`）：`0ce55a93196badbe919b37d03e5094b3452baca88e1ec7ea0e8ad67b06a24f10` == 期望值。
- sidecar `RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT.zip.sha256.txt`：同一哈希，文件名指称一致。

### 2. 结构与清单安全 — PASS
- `unzip -t`：126 成员全部 `OK`，`No errors detected`。
- `zipinfo -1` 检查：成员 126；重复名 0；绝对路径（`^/`）0；`..` 成员 0；盘符（`^[A-Za-z]:`）0；非普通文件/目录成员（链接/设备/管道）0；成员名含反斜杠 0。
- 顶层目录唯一：`RouteC_QAFv3_A2_OneShotExecution_v1_RETURN_TO_CHATGPT/`。
- 构成：113 个文件 + 13 个目录项（含顶层自身）= 126 成员；解压后内容共 569,562 B；最大单件 200,214 B（`d3_snapshot/artifacts/formal_a_qaf_v3/r17_code_freeze.json`）。

### 3. SHA256SUMS.txt 复算 — PASS
- 包内 `SHA256SUMS.txt` 112 条；`sha256sum -c` rc=0，112/112 OK。
- 不含 `SHA256SUMS.txt` 自身（自引用 0）；条目路径形态干净（无 `^/`、无 `../`、无盘符前缀）。
- 条数==内容文件数：112 条 == 113 文件 − 1（SUMS 自身）。
- 隐藏件覆盖：`d3_snapshot/.r17_formal_admission.json` 在清单第 32 行（`5d144ed5…`），无遗漏。

### 4. 与对照源逐字节对拍 — 6/7 SAME，1 项 DIFF（发现 F-1）
对 `EXECUTION_REPORT.md`、`EX_SELF_CHECK.md`、`E0_READ_ONLY_CHECK_REPORT.md`、`commands/`、`d3_snapshot/`、`reviewer_gate1/`、`reviewer_gate2/` 以 `diff -rq` 对拍对照源 A：

| 对象 | 结果 |
|---|---|
| EXECUTION_REPORT.md | SAME |
| EX_SELF_CHECK.md | SAME |
| E0_READ_ONLY_CHECK_REPORT.md | SAME |
| commands/ | **DIFF：`commands/E4_watch.jsonl`**（见 F-1）；其余全部一致 |
| d3_snapshot/ | SAME（整目录，78 件） |
| reviewer_gate1/ | SAME |
| reviewer_gate2/ | SAME |

d3_snapshot 四件另与 D3 现场原件 `cmp` 对拍（D3 侧均唯一命中）：

| 包内件 | D3 原件 | 结果 | SHA256 |
|---|---|---|---|
| d3_snapshot/artifacts/formal_a_qaf_v3/r17_code_freeze.json | $D3/artifacts/formal_a_qaf_v3/r17_code_freeze.json | SAME | `d559d0d0e0194881643f81f3376f117ebee6274754890fc24b75215c1b8b642a` |
| d3_snapshot/artifacts/formal_a_qaf_v3/chain_budget_gate.json | $D3/artifacts/formal_a_qaf_v3/chain_budget_gate.json | SAME | `5d16063f6cf00d8a761ebe0d476fc02907b4bf85d4d05b730c90e4a4b0f4854f` |
| d3_snapshot/artifacts/formal_a_qaf_v3_chain_logs/cue-audit.err | $D3/artifacts/formal_a_qaf_v3_chain_logs/cue-audit.err | SAME | `5debf8b7ffac4b8bf6aa525b0aa17010bd9e57ed871377ed686572b551b3aa94` |
| d3_snapshot/state/r17_execution_journal.jsonl | $D3/artifacts/route_c_stage2_6_1_repair17/state/r17_execution_journal.jsonl | SAME | `52722ffdebbbaf463d6ae15129b9e64cff22f5641260c6ddb8931b7f58e6f36b` |

### 5. 关联抽查 — PASS
- `commands/E4_execute.argv.txt`：`--admission-id qaf-v3-c0fb6858-a2`；`--attempt qaf_v3`；`--stop-after verify-formal-logs`；`--code-freeze-sha c0fb685823eb4733bda9f5920601311228d55fde`。
- `d3_snapshot/state/r17_admission_consumed.jsonl`：`admission_id=qaf-v3-c0fb6858-a2`、`commit_a_sha=c0fb6858…55fde`、consumed 2026-10-11T10:49:34Z —— 与 argv 一致；并与 `d3_snapshot/r17_admission_issued.jsonl`、`d3_snapshot/.r17_formal_admission.json`（同 id、同 freeze SHA、substance `r17sub-84648fff…`）一致。
- authority permit 原件 `d3_snapshot/authority/qprod_permit_level_a_qprod_a_formal_v3.json`：`permit_id=qppm-formal-ed1e6a965ab55ab6`、`authorized_stop_after=verify-formal-logs`、`code_freeze_sha=c0fb6858…55fde`、`iteration_id=qprod_a_formal_v3` —— 与 argv 的 `--stop-after`/`--attempt`（qaf_v3 系标识）及 `d3_snapshot/state/qprod_permit_consumed.jsonl` 消费行（同 permit_id、consumed 10:48:14Z、pid 6306）一致；admission 的 issuer approval 关联 `qaf-v3-c0fb6858-a2-user-approval`。包内交叉命中面（E3/E4 日志、EXECUTION_REPORT、Gate2 报告、run journal）无冲突 ID。
- `SHA256SUMS.txt` 不含自身 ✓。
- 敏感串抽查：`grep -rIl 'password\|token\|private key'` 与大小写不敏感变体均 **无命中**。

### 6. 大件与路径形态 — PASS
- 本次无模型/语料大件：最大件为 200 KB 的 code-freeze JSON；无 `.pkl/.pt/.pth/.ckpt/.bin/.zip/.tar/.gz/.model/.onnx/.parquet/.csv` 后缀件（与交付回执"未达产生步"口径一致）。
- 成员名无 Windows 反斜杠（`zipinfo -1 | grep -c '\\'` = 0）。

---

## 发现

### F-1（P2）：`commands/E4_watch.jsonl` 封包竞态——ZIP 内为对照源的严格前缀，源文件封包后仍在增长
- 包内副本：32 行 / 4,130 B，SHA256 `d38b46af06ad93c6dfc171b1f780ebd9aa82b395e9dbd67ea1db3133c891952c`，zip 内时间戳 2026-10-11 19:13:06(+08)。
- 对照源 A 副本：冷读时 38 行 / 4,928 B（19:19），SHA256 `3e1fbef86bcde4cfab1c42df5c74a9daf3f2ebf5d9af17a846fc73a9e7a8f63c`，随后仍在增长（19:20 已 39 行 / 5,061 B）。
- `diff -u` 定性：差异**仅为尾部追加**（11:14Z–11:19Z 的 6 个 watch tick，`op_alive:0, rc:"1"`），包内 32 行与源文件前 32 行逐字节一致，无任何内容矛盾。
- 根因：watcher 进程（`bash /home/cryptorl/qafv3_e4_watch.sh`，pid 513，冷读时仍存活）以 ~59 s 周期续写该日志，主 Agent 在 19:13 打包时未先停止 watcher，打包进 ZIP 的是活动日志的中间切片；包外交付回执 19:15 出具后源文件仍继续变化。
- 影响：检查项 4"逐字节对拍"对该件不成立（当前时点）；ZIP 自身完整性（SUMS/CRC）不受影响，ZIP 内该件自洽且可复现。
- 处置建议（供主 Agent 执行）：停止 watcher 进程 → 以终态 `E4_watch.jsonl` 重对照源 A → 重封 ZIP（新 SHA）→ sidecar/交付回执同步改绑 → **重新执行第三关冷读**。备选：在封包前将 watcher 日志冻结为固定终态并记录冻结时点，再打包。

---

## 结论

**FAIL（针对当前 SHA `0ce55a93…24f10` 的本包）**——唯一不通过项为 F-1（`commands/E4_watch.jsonl` 封包竞态，检查项 4 逐字节对拍不等）；其余全部检查项（哈希/结构/SUMS/D3 四件对拍/关联 ID/敏感串/大件/路径形态）均 PASS。按验收约定：主 Agent 修复重封后须重新冷读，本报告随之失效并由新报告取代。

## 局限
- 冷读仅做产物与摘要核验：不重跑链、不重放科学计算、不训练/加载模型；不审计 D3 现场在冷读时点之后的变化。
- watcher 进程活性与源文件行数为冷读时点观察（19:20:24Z 时 pid 513 存活、39 行），非终态断言。
- 后端模型元数据不可观测；本报告结论只针对上述固定 SHA 的 ZIP 字节。
