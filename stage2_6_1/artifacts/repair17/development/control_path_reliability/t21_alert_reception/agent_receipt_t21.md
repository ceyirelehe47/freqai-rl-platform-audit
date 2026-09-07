# T21 真实 Agent 告警接收回执（模式 B / 2026-09-07）

## 接收通道事实
- 宿主：ZCode 模式 B——`run_in_background` 后台任务 + `TaskOutput` 有界周期读取（本轮实际读取间隔：场景A 即时读、场景B 故意停读 12 秒后一次读取；均 ≤15s 周期约束内的真实工具调用）。
- 受监护任务：真实 supervisor 子进程（r17_supervision.py，task_kind=fixture），业务 `bash -c "sleep 30"`；样本经显式测试输入源 `--samples-source file:`（keyvol WARNING 10GiB<20 → 冷却期内 CRITICAL 3GiB<5，单样本瞬时判定）。
- 保护不等回复：两场景 CRITICAL 递交与 SIGTERM 均在无任何工具读取发生的时间窗内完成（场景B 的 business_exited rc=-15 早于读取时刻 12 秒）。

## 场景A（run_a_A）：WARNING→冷却期内升级 CRITICAL
真实工具返回（TaskOutput，逐字）关键行：
1. `R17ALERT {"action":"open","severity":"WARNING",...,"kind":"keyvol","detail":"关键卷 F: 可用 10.0GiB < 20.0GiB",...,"delivered_count":1}` utc=2026-09-07T01:31:50Z
2. `R17ALERT {"action":"escalate","severity":"CRITICAL",...,"stopped_requested":true,"delivered_count":2,...,"note":"停止请求由本地策略执行,不等待模型回复"}` utc=2026-09-07T01:31:50Z（与 open 同秒=冷却期内升级，未被 60s 冷却吞掉）

落盘交叉（run 目录 alerts.jsonl 15 行）：`stop_requested` + `sigterm_sent` 均在场；summary business rc 未记录（None：TERM 后任务树确认消失先于主循环观察到业务退出码，无 business_exited 事件；外层为保护性中止语义 rc=4）；incident keyvol delivered=2；run_record evidence_complete=True。rc=-15 的落盘事实属场景B（run_b_B summary business rc=-15）。io 队列 submitted=19/executed=19/dropped=0。
注：启动命令内联的 `SUPERVISOR_RC=0` 为 wsl.exe 复合命令拆参假象（`$?` 被拆）；真实退出码以场景B 脚本文件方式确认。

## 场景B（run_b_B）：停读回放
- 12 秒零读取窗口（2026-09-07T01:32:23Z 保护完成 → 01:32:35Z 恢复读取）内：WARNING open → escalate CRITICAL → 业务 TERM（business_exited rc=-15）→ worker_event 全部发生。
- 恢复后一次 `TaskOutput` 调用**回放全部 6 条未决事件**（上述序列完整、顺序一致、无丢失/重复）。
- `REAL_SUPERVISOR_RC=4`（保护性中止；脚本文件方式取得真实退出码）。
- 落盘：alerts.jsonl 18 行含 stop_requested+sigterm_sent；io submitted=24/executed=23/pending=1（退出边界最后一条 stdout 递交未及执行——daemon 线程诚实记录，alerts 文件本身完整）。

## 去重/升级/工具关联
- 同一 incident_id（run_*-keyvol-0）跨 open→escalate 两次呈现：事件按 incident+action 去重语义成立（delivered_count 1→2，无重复 open）。
- 升级未被冷却吞掉（S4 顺序合同）；保护动作（sigterm_sent utc 01:32:23）早于 Agent 认知（读取时刻 01:32:35）= 告警迟于保护动作，如实记录。
- 工具句柄：后台任务 exec_de2a7e5e（B）/ exec_5ca12a1d（A）；输出文件在 ZCode exec 会话目录（本回执引用的 R17ALERT 行为 TaskOutput 返回的逐字内容）。

## 边界
- 本回执为真实工具接收证据（非本地脚本打印自证）；宿主原始记录以 ZCode 会话任务输出文件为准（call_*-stdout.log），未导出部分标注为传输侧证据。
- 两场景均为受限测试读数源触发，未制造真实资源危险。
