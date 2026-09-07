# A22 真实 Agent 告警接收回执（停读后恢复）

- **场景**：WARNING→冷却期内升级 CRITICAL；消费者（Agent 工具）暂停读取 14 秒后恢复，未决递交完整回放；保护不等读取。
- **运行**：`run_20260907T064420Z`（replay 输入 110 条样本：60 正常→keyvol WARNING free=10→8 正常→keyvol CRITICAL free=3→40 正常；业务 `bash -c 'sleep 45'`）。
- **接收方式（模式 B 等价）**：ZCode Bash 工具 `run_in_background` 启动 WSL 脚本（supervisor stdout 流入后台任务输出文件）；Agent 侧**不读取输出文件 14 秒**（真实消费者暂停：期间无任何 TaskOutput/Read 调用），随后单次 `Read` 恢复消费。
- **工具返回（逐字，完整行，未删节）**：
  - `R17ALERT {"action":"open","severity":"WARNING","incident":{"incident_id":"run-keyvol-2","kind":"keyvol","detail":"关键卷 F: 可用 10.0GiB < 20.0GiB",...,"delivered_count":1},...,"note":"当前任务继续","utc":"2026-09-07T06:44:24Z",...}`
  - `R17ALERT {"action":"escalate","severity":"CRITICAL","incident":{"incident_id":"run-keyvol-2",...,"severity":"CRITICAL","first_seen_mono":2.2,"last_seen_mono":2.5,"samples":2,...,"stopped_requested":true,"delivered_count":2},"metrics":{"vol":"F:","present":true,"free_gb":3.0,...},...,"note":"停止请求由本地策略执行,不等待模型回复","utc":"2026-09-07T06:44:24Z",...}`
  - `R17LOG {"event":"business_exited","rc":-15,...}`
  - `SUPERVISOR_RC=4`
  - 工具输出原始文件：`C:\Users\15027\.zcode\cli\exec\sess_0b71d385-4316-4d13-abbb-b9973adbadee\call_8ace9a4d22f04ee28109f73c-stdout.log`（13 行，全部于恢复读取后一次取得）
  - 说明：上文 `"..."` 处为本文档书写时的省略标记；逐字原文以该输出文件与本目录 `s.jsonl`/`run/` 落盘流为准（证据等级：工具原始输出文件 > 本回执转录）。
- **落盘交叉（run/alerts/alerts.jsonl，19 行）**：`open WARNING 06:44:24 run-keyvol-2 delivered_count=1`；`escalate CRITICAL 06:44:24 run-keyvol-2 delivered_count=2`；`stop_requested/sigterm_sent/business_exited(-15)` 同秒。递交计数与工具行一致。
- **停读窗口证明**：后台任务于 06:44:20Z 前后启动，Agent 侧 14 秒内零读取调用；恢复后首读即取得全部 5 条 R17ALERT/R17LOG 递交行——未决不被吞、不丢、按序回放。
- **保护不等读取**：WARNING（mono 2.2）→ escalate+停止请求（mono 2.5）→ TERM→business rc=-15→supervisor 退出码 4，全部发生在停读窗口内（读取恢复之前）。
- **IO 完成性（summary.io）**：`submitted=25 accepted=25 ok=25 failed=0 dropped=0 dropped_critical=0 rejected_after_seal=0 io_stuck=false`——停读期间递交动作排队等待而非丢弃，恢复后全部成功执行。
- **结论**：A22 PASS（同 incident 升级、停读回放、真实 rc=4、保护先于读取、递交计数分层一致）。
