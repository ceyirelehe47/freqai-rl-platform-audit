# R17 r3 必要字节与 Windows 采样封口：只读取证回传

- 日期：2026-09-09（UTC 时标为准）
- 审查固定提交：`6d98f5b77a8961f0c7918ca4a045bbeb2a35a87a`
- 候选 reader 未动：`7a5ccc19b4e3ade4dd0e6b64861ae425cdb631c181149458a51f4ccbb52141dd`
- 性质：只读取证。未修改任何生产代码/aggregate/锚/日志；未删除旧 run；未 kill 无关进程；未重跑 pytest/课程。

## 0. 辅助工具包状态

`README_AGENT_CHECK.md` 所指 `tools/audit_run_bytes.py` **未随文件交付**（Downloads 仅该 md；两个 zip 与 E 盘均无）。按任务书语义用等价只读实现替代：`E:\trading\r17_telemetry_audit\tools\r17_audit_run_bytes_equiv.py`（纯标准库、不导入项目、不写文件、stdout JSON、rc 0/1/2 语义一致），在固定环境 **Python 3.11.16**（WSL freqtrade-rl）执行。变换（CRLF↔LF）仅内存定位，不将变换后匹配当作原件匹配。

## 1. 三对象字节检查（stdout 已存 outputs/，真实 rc）

| 对象 | rc | 结果 |
| --- | --- | --- |
| 工作树 `runs/c3eto_full_20260909_r3/` | **1** | telemetry_win 不符；其余 6 项（telemetry_guest/alerts/business_stdout/business_stderr/junit_xml/summary）字节+摘要+读取稳定性全部匹配 |
| git blob 导出副本（6d98f5b → `E:\trading\r17_telemetry_audit\gitblob_r3\`，9 文件） | **1** | 同上：仅 telemetry_win 不符（309550≠264179） |
| 已有封口副本 | — | **未发现**（见 §4，缺口如实保留） |

**决定性 hint**：两对象的 telemetry_win **原字节前 264179 字节（登记长度前缀）的 sha256 均恰等于登记值 `f502a49f…`**（`prefix_matches_registered_sha=true`；CRLF→LF 形态同样成立说明前缀内无 CRLF 差异；LF→CRLF 不成立）。即登记值=seal 时刻文件内容，seal 后为**纯追加**（append-only），seal 前内容一字未动。这不是行尾归一化问题，不能用变换匹配替代原件事实。

## 2. r3 实际写者身份与时间线（最小事实）

- 事件链（alerts.jsonl）：`win_sampler_started`（interop_pid=71796，max_seconds=5580，12:30:11Z）→ `win_sampler_ready`（**windows_pid=135692**，12:30:13Z）→ `win_sampler_stopped`（12:59:10Z，mono=1748.0；走 exited=True 分支，**非** stop_unconfirmed）。
- 文件事实（`telemetry/win_samples.jsonl`，工作树）：共 **1069 行**；首行 12:30:13.011Z；**seal(12:59:10Z) 之后 735 行**；末行 `{"event":"sampler_end","reason":"max_seconds","utc":"2026-09-09T14:03:18.190Z"}`。
- 即：supervisor 记录 `win_sampler_stopped` 时，Windows 侧 powershell（135692）**并未退出**，继续追加 64 分 8 秒，直到自身 MaxSeconds（12:30:18+5580s=14:03:18）到期写 `sampler_end` 后自停。
- 当前进程核查：Windows 侧无任何 `r17_win_sampler` powershell 进程（`Get-CimInstance` 过滤 CommandLine 含 win_sampler → 无）；135692 已随 max_seconds 自停。**无残留实例需要处理。**

三态字节身份（各自保留，未混用）：

| 形态 | bytes | sha256 | 行数 |
| --- | --- | --- | --- |
| run_record 登记（seal 12:59:10Z） | 264179 | `f502a49f3dc8b785…` | —（登记时刻快照） |
| 提交版（git blob `327a99c5…`，6d98f5b；≈21:2x 本地 add 时刻截断） | 309550 | `9e1375c5d18b5f77…` | 391 |
| 工作树（采样器自停后终态） | 848948 | `e6dfd51ea5adf8b1…` | 1069 |

## 3. 登记 f502a49f/264179 完整副本搜索（结果：未找到，保留缺口）

已搜索：runs 树全部文件（size=264179c 精确匹配）→ 无；git 历史（525c2cf/1389351/6d98f5b 三提交的该路径 blob 均为 327a99c5/309550）→ 无；`C:\Users\15027\AppData\Local\r17_supervision_emergency\`（4 文件均旧轮次：111/996/446472/98 bytes）→ 无；WSL /tmp 与 /home/cryptorl 浅层 → 无。**登记摘要对应的 264179 字节完整对象当前不存在于任何已知位置**；仅可由现存文件前 264179 字节前缀复现（§1 hint）。r3 run 的 receipts/ 目录为空，supervisor 未在 seal 时另存封口副本。

## 4. 根因定位（只读代码审阅，未改任何实现）

- `stage2_6_1/runner/r17_supervision.py` `stop_win_sampler`（L1711-1746）：`os.kill(interop_pid, SIGTERM)` + `win_proc.wait(timeout)`——杀的是 **WSL interop `/init` 包装进程**；wait 返回即记 `win_sampler_stopped`。注释假设"ps1 由该进程 -File 直跑…wait 返回即实际写者退出"。**r3 实证该假设不成立**：/init 被 SIGTERM 后 Windows 侧 powershell 不随之退出。
- `stage2_6_1/runner/r17_win_sampler.ps1`：主循环 `while($true)`（L139-249）**没有任何外部停止机制**（无标志文件/管道轮询），仅 L244-249 `总时长>=MaxSeconds → sampler_end → break` 自停。
- 即：停止路径 = 杀 interop 包装器，而真实写者的唯一退出路径是自超时。

## 5. 短的 sampler 开始—停止—封口检查（原有工程入口，一次性新 run）

run `c3eto_sampler_probe_20260909b`（业务=部署树 54 项测试，2 秒，`--max-seconds 180`）：

- `win_sampler_started`(interop 75812) → `win_sampler_ready`(**windows_pid=117848**) → business_exit rc=0 → `win_sampler_stopped`(14:58:28Z，exited=True 分支)。
- 文件 2 行（sampler_start + seq=1），size 1089，mtime 14:58:27；seal 后 +45s/+90s/+300s **零增长**；`Get-Process 117848` → **进程不存在**。
- 与 r3 行为**相反**：本场景 SIGTERM→/init 退出后 Windows 采样器确实死了。结论：`win_sampler_stopped` 事件的可靠性**依赖场景**（r3：长 run+setsid 会话下 /init 死而 powershell 存活 64 分钟；探针：短 run+前台链下连带退出）。停止确认不能以 interop wait 为准——这是需要修复方（ChatGPT）决策的点。
- （首次尝试 `c3eto_sampler_probe_20260909` 被 startup 准入拒绝：pytest 类型缺 `--junitxml`，零 spawn 无采样器；目录保留为痕迹。）

## 6. 其他声明

- `aggregate_v6.py` 局限确认属实：仅核 stdout/junit 内容哈希与 run_record 登记一致性，未逐项核全部 required 字节（本轮 `evidence_complete=true` 下 telemetry_win 已漂移即为例证）。本轮未修改 aggregate 与生产监护实现。
- 既有证据保留：1716 passed/14 次 CLI/两个回执工作包证据不受影响；本轮未重跑完整 pytest。
- 正式 A/B、fresh rt3、新正式数据、qualification exposure、备援与条件采样均未触碰；既有隔离身份未恢复。

## 7. 工件位置

- 等价检查工具：`E:\trading\r17_telemetry_audit\tools\r17_audit_run_bytes_equiv.py`
- 三对象检查输出：`E:\trading\r17_telemetry_audit\outputs\check_worktree.json`（rc=1）、`check_gitblob.json`（rc=1）
- git blob 导出副本：`E:\trading\r17_telemetry_audit\gitblob_r3\`
- 探针脚本与 run：`E:\trading\r17_telemetry_audit\sampler_probe.sh`；`runs/c3eto_sampler_probe_20260909{,b}/`（仓库内，保留）
- 进程取证脚本：`E:\trading\r17_telemetry_audit\find_samplers.ps1`
