# C13 模式 B 真实接收回执（R17 监护接线闭合轮）

- 接收 Agent：ZCode（GLM-5.3），工具通道=宿主后台任务输出（`run_in_background` 任务句柄）+ `TaskOutput` 周期取回（模式 B；无运行中任意时刻消息注入）。
- 被监护运行：全量回归第一轮 `final_20260906T183450`（2026-09-06T18:34:51Z–18:53:56Z，19:17）与第二轮 `final2_*`（同日启动，见 §8）。
- 工具任务句柄：第一轮 `exec_ec8d6ff2-6d87-4514-9522-43bca240898d`（启动 18:34:50Z）；输出文件 `call_b96b6342ba524ecbb252b609-stdout.log`。

## 接收记录（已检测→已投递→已展示→已确认四级）

| UTC（接收时点） | 通道 | 事件 | 与告警流对照 | 确认 |
|---|---|---|---|---|
| 18:35:0x | TaskOutput（stdout 头 4 行） | `R17LOG supervisor_start`（run_dir/policy digest `b02a0194…`） | alerts.jsonl `supervisor_start` 同 run_id 同 policy | 已确认（本行） |
| 18:35:0x | 同上 | `R17LOG business_started`（pid=72563） | alerts.jsonl `business_started` argv 逐字一致 | 已确认 |
| 18:43:2x | TaskOutput（grep R17ALERT 计数） | 计数=0 | alerts.jsonl 无 CRITICAL/WARNING 事件（健康） | 已确认：运行健康、零告警 |
| 18:48:5x、18:53:5x | TaskOutput + 只读 alerts 流 | `stage_mark observation_ready ready_after=1.8s` 等阶段事件 | 遥测 107/162/227 行双侧增长 | 已确认 |
| 18:54:0x | 任务完成通知（原生 re-invoke） | 任务 exit 0（第一轮业务 rc=1 由 pytest 1 failed 传导） | `supervisor_end incidents=1 business_rc=1` | 已确认 |

- 语义分级：`alert_delivered`（alerts.jsonl+stdout 写入路径执行）≠ 已展示（TaskOutput 返回给 Agent）≠ 已确认（本回执落盘）。本轮全程零资源告警，接收面为 R17LOG 阶段事件与任务完成通知；`R17ALERT` 通道的接收语义在 C09/C10 单元回归与健康运行零告警事实下闭合（离线回放语义=M08 既有）。
- 无 grant token/凭证/无关用户进程命令行进入消息；读取/等待不触碰业务（保护由本地策略执行，M10/C07 回归）。
- 消费按 incident_id 去重；无消费者时事件保留在 alerts.jsonl/spool（stdout_failures=0）。
