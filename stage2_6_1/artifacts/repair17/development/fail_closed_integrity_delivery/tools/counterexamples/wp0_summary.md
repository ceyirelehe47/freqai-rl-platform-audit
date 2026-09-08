# WP0 最小真实反例总结（fail-closed-integrity-delivery 轮）

日期：2026-09-08；接手 SHA：`029f1ff6d0ec90ec6cebac458431b8326989142f`
快照：执行树 `/home/cryptorl/projects/crypto_rl/stage2_6_1/runner`（与发行树
`stage2_6_1/runner/r17_supervision.py` md5=911d05a8… 一致；supervisor Git
blob `a6e58f95…` 核对吻合）；Python 3.11.16（freqtrade-rl conda）；
win sampler ps1 为仓库内真实原件。预算值注入仅在测试进程内修改
`sup.policy`（生产策略未改）。

## FC-1a：线程前提失败 + 无信号 → 仍普通成功（SPSC-01）

`run_fc1a/`：未屏蔽辅助线程（`fc1-unshielded-aux`）全程存活跨越
finalize；replay 模式；无信号。

- `_cutoff_premise_ok=False`（`unshielded_threads:415`，
  `cutoff_thread_premise_failed` 事件在案）
- **run rc=0（普通成功）**、`evidence_complete=True`、`finalized=True`
- 辅助线程存活未被误杀

结论：能力失效后仅经 50ms 保守复核即可成功降级——前提不能证明时
run 仍可成功，缺陷坐实。

## FC-1b：50ms 保守复核窗口内真实 TERM（SPSC-01 排序面）

`run_fc1b/`：settrace 定位 `time.sleep(0.05)` 行（快照 L3536），
进入该行时发送真实 SIGTERM。

- 信号登记 count=1，被保守分支消费（`cutoff_signal_conservatively_
  consumed`），rc=4，`count_at_cutoff=1`
- 该次时序落在消费窗口内；但该窗口的"保证"完全依赖调度运气
  （CPython 3.11 eval 检查点稀疏），无任何机制性质——正是
  [S1] 所指"不能用固定延时替代停止排序保证"

## FC-2：budget_check 停止后活写者被 None 掩盖（SPSC-02A）

`run_fc2/`：真实 ps1 + 真实 guest 线程；emit1 正常（供就绪）；
emit2 真实文件写完成后由该线程调用真实 `budget_check()`（预算
注入 1B；`telemetry_bytes` 真实统计 1927B≥1B），随后挂事件屏障。

- `telemetry_capped=True`、incident `telemetry_budget`、
  `stop_requested_reasons` 在案（`PROTECTION_UNAVAILABLE` 真实触发）
- `budget_check` 内 `guest_sampler.stop()` 后**立即置 None**：
  `PROBE_GUEST_HANDLE=None`
- `_guest_close_state=None`（已启动写者的未知关闭状态被掩盖）；
  run_record `writers.guest=None`，`telemetry_guest` 条目无
  `live_writers` 标记
- guest 线程在 run 返回后**仍存活**，文件挂住时 1056B
- `evidence_complete=True`、`finalized=True`
- **实际 build rc=0 + verify rc=0（problems=0）——活写者包被
  接受为完整交付**
- 释放屏障后文件继续增长 1056→1133B（流从未冻结；verify 通过的
  哈希在验证后即失效）
- 附带观察：budget 触发时业务尚未启动（win 首样本就绪在 emit2
  之后），走 `stop_requested_no_live_task`；业务随后仍被启动并
  正常退出 rc=0——保护原因未转化为外层非零（与句柄掩盖同源的
  结果面缺口，本轮 WP2-A 一并修复验证）

## FC-3：summary 部分写入残片被 present/哈希抵消（SPSC-02B）

`run_fc3/`：真实文件边界注入——summary.json 目标路径真实
open+write+flush 写出首字节 `{` 后抛 OSError(5)；不替换
write_summary 函数体。

- 最终路径残留 1 字节 `{`
- `_summary_publish_failed=True` 仅进 `control_outcome`（rc=6），
  **不进 `_evidence_ok`**
- run_record summary 条目 `status="present"` + 残片 sha256（1 字节
  哈希 021fb596…）、`missing_roles=[]`、`evidence_complete=True`
- **实际 build rc=0 + verify rc=0（problems=0）——必要发布失败的
  残片包被接受为完整交付**

## FC-4：上轮交付缺口（SPSC-03，只读核对）

上轮 `stop_publication_sampler_closure/`：

- `full_run/` 仅 pytest_stdout.log / junit.xml / outer_rc.txt 三件，
  **无监护 run 原件**（telemetry/alerts/run_record/summary/监护
  原始流）
- `cold_read/manifest.jsonl` 对象为 `src_pkg/run/…`（run_id="run"
  的快速 fixture supervisor run），**不是** full_run 的全量 pytest
  监护 run——冷读对象与全量交付无绑定
- verifier 代码从开发树加载，未隔离原项目根（复用
  `unified_shutdown_cold_read/tools/` 的隔离机制未用于上轮冷读）

## 复现命令形态

```
python probe_fc1_premise_fail.py <snap_dir> <base> [--signal-in-review]
python probe_fc2_budget_bypass.py <snap_dir> <base>
python probe_fc3_summary_fragment.py <snap_dir> <base>
```

反例日志原件：本目录 `run_fc1a/ run_fc1b/ run_fc2/ run_fc3/`
（PROBE_* 输出见各 run 目录上级 console 记录与 events/alerts 流）。
