# R17 stop-publication 轮：停止决策与结果发布、首次停止预算、采样写者关闭

**英文标识：** R17 Thread-Aware Stop Decision + Post-Decision Publication + First-Stop Budget + Sampler Quiescence
**日期：** 2026-09-08
**仓库：** `ceyirelehe47/freqai-rl-platform-audit`，分支 `route-c-stage2-6-1-repair17`
**接手 SHA：** `b79ebe939e30dd28cb4bc86c065f5f53cf5b0faa`（远端 HEAD 与本地一致，无后续提交；接手 supervisor Git blob=`9e1a207b02a50d817df2815c07e6dc093bac0915` 已核对）
**交付 SHA：** `6cea807`（主交付提交；本回填行随其后的勘误提交一并推送，提交链以 git log 为准）
**性质：** R17 冻结前开发续轮（pre-freeze）。不创建最终 Implementation Freeze A / Results B，未运行真实 formal，无正式数据访问。

---

## 0. 分项判定

| 工作包 | 判定 | 依据 |
|---|---|---|
| WP1 停止决策（真实多线程下的截止点 C） | **PASS** | 反例A复现+修复验证；S01/S02/S03 组合测试；受控线程掩码继承+/proc 逐线程 SigBlk 前提核验+前提失败保守复核 |
| WP1 发布（决定之后才公开完成件） | **PASS** | P01 三观察点独立 reader；P02 真实 I/O 故障（chmod/目录占用）；cutoff_pending_rewrite 覆写路径删除 |
| WP2-A 首次停止预算 | **PASS** | 反例B复现+修复验证（est 从 stop_accept: 起，delta=0.000）；B01/B02 纠正；I01 工程链同一预算 |
| WP2-B 采样写者关闭 | **PASS** | 反例C复现+修复验证（句柄保留/evidence=False/rc=6）；W01/W02/W03/W04；_evidence_ok/writers_live/verify 同源消费关闭事实 |
| 集成交付 | **PASS** | 全量 1513 passed / 7 skipped（JUnit 1520 项 0 失败，外层 rc=0，§5）；反例新旧行为证据导出；副本冷读五步全 OK（§6）；本报告 |

不创造"整体 PASS（受限口径）"；上轮全量（1502 passed / 7 skipped）是接手基线，不是本轮结果。

---

## 1. 修复的三个缺陷（接手独立审查 §4-§6）

三项反例均在**接手快照副本**（md5 与 git HEAD 一致：supervision=`d6a7abf9…`、guest_sampler=`e4d6d4ad…`）上、固定 Python 3.11.16（conda `freqtrade-rl`）+ 真实模块 + 真实信号/线程先行复现，再对修复后实现重跑同一脚本验证行为翻转。

### SFB-01 截止点 C 只屏蔽主线程；C 前已发布完成件

**旧行为（反例A，`counterexamples/old_behavior/probe_a/`）：**
- `PROBE_RR_BEFORE_C=exists=True,finalized=True`——`write_summary`/`finalize_run_record` 在 C **之前**已对外发布 finalized=true 的 run_record；
- C 时刻真实线程清单 `['MainThread','r17-io-writer']`，主线程掩码 `[SIGINT,SIGTERM]` 生效中，但 writer 线程（`_loop` 为 `while True`，永不退出）未屏蔽；
- 临界区（C 赋值语句处）发真实 TERM：信号经未屏蔽 writer 线程接收，CPython C handler tripped 后 Python handler 在主线程执行——`sig_count=1`（handler 已登记）但 `count_at_cutoff=0`、`consumed=False`、`rc=0`。"屏蔽中发送=C 后"的旧边界保证只是调度偶然（handler 恰落在赋值之后）；若落在最后判定之后、赋值之前，信号将完全无痕漏接（对外产物中不存在）。

**修复（三件事互相支撑）：**
1. **受控线程终身屏蔽**：`BoundedIOWriter.__init__` 与 `_start_guest_sampler_shielded()` 都采用"创建线程先 block{TERM,INT}→spawn/start（新线程继承掩码）→恢复创建线程掩码"——写线程/采样线程从第一条指令起屏蔽，进程级信号只能投递主线程（生产面线程全集受控）。
2. **写线程可验证结束路径**：`_loop` 增加 `_CLOSE_SENTINEL` 哨兵退出；`close(timeout)` 经持锁 `put(block=False)` 入哨兵（绕过 submit 的 sealed 拒绝与外部 put_nowait 动作观测挂钩）、`join` 后用 `is_alive()` 判真实退出（join 超时返回值不构成结束证据）。
3. **前提核验+保守复核**：临界区内在主线程 block 之后读 `/proc/self/task/*/status` 逐线程核验 SigBlk 含 TERM|INT（`_cutoff_thread_premise`）；前提成立→临界区内最后判定+挂起边界（解除后 handler 必然 C 后）；前提失败（存在未屏蔽线程/掩码能力不可用/proc 不可读）→**不在临界区内判定**（判定本身不可靠），解除屏蔽后经确定性窗口（sleep 0.05）保守复核：窗口内登记的信号无法证明为 C 后，按已登记停止参与结果（`cutoff_signal_conservatively_consumed`），基线更新到复核后——不降级为旧竞态，也不把无信号的正常运行一律拒绝。

### SFB-02 外部停止/CRITICAL 被接受时不建立总 deadline

**旧行为（反例B，`old_behavior/probe_b/`）：**TERM 在主循环被接受消费（t=56.057），业务合作退出 2s 后 finalize 才以 reason=`'finalize'` 建立 5s 窗口（t=58.113，delta=2.056s）——合作退出时间逃出预算；summary `remaining_at_write=4.98`（几乎满额）。

**修复：**`handle_triggers` 的 `needs_stop` 分支在 `request_stop`/`no_live_task` **之前**调用 `_ensure_finalize_budget(f"stop_accept:{kind}")`——第一次接受终止决定、准备请求停止时建立；`_external_stop_early_window`（早窗口外部停止）同样先建立。覆盖全部真实入口：外部 TERM/INT 消费、CRITICAL/PROTECTION_UNAVAILABLE（资源/遥测预算/io 丢关键/win 侧 CRITICAL）、run_timeout、leader 退出残留、主循环致命异常（_terminal_shutdown 原有）、正常 finalize、早拒绝辅助清理（stop_win_sampler 原有）。WARNING 不进入 needs_stop 分支，不建立预算。同一 run 重复进入任何收尾方法复用同一 deadline（幂等，L01/B02/I01 断言预算恰一条）。

**修复后（`fixed_behavior/probe_b/`）：**`est_reason='stop_accept:supervisor_external_stop'`、`delta=0.000`、`remaining_at_write=2.964`（合作退出 2s 真实计入）。

### SFB-03 采样写者未确认关闭即签完整证据

**旧行为（反例C，`old_behavior/probe_c/`，非 replay 真实采样器）：**guest 线程在 `_emit_guest`（真实文件写入路径）内被屏障暂停，`join(15s)` 超时后 `self.guest_sampler = None`（句柄丢弃）；run 返回后线程仍存活；`run_record` 照签 `finalized=true, evidence_complete=true`、`rc=0`；释放屏障后 guest 遥测文件继续增长（1056→1133 字节）——"封口"时流未静止。`stop_win_sampler` 同理：wait 超时后仍无条件记 `win_sampler_stopped`。

**修复（关闭事实与完整性同源）：**
- **guest**：join 后用 `is_alive()` 判真实退出；未确认退出**保留句柄与身份**（不置 None、不强杀、不改 daemon），`_guest_close_state={stop_requested, started, joined, alive_after_join, thread_ident}`；replay 未启动线程（`ident is None`）不 join、单独记录 started=False。
- **win**：wait 成功→`exited=True`+确认版 `win_sampler_stopped`；超时→`win_sampler_stop_unconfirmed`（不再记 stopped）。所等候句柄=interop 进程本身（ps1 由该进程 `-File` 直跑、`AppendAllText` 直写 OutFile、无子写进程），wait 返回即实际写者退出。
- **io writer**：哨兵关闭+join 确认进 `_io_close_state`。
- **完整性消费**：`_evidence_ok` 拒绝任一必要流写者未确认（guest alive_after_join / win unconfirmed / io alive_after）；`finalize_run_record` 按角色映射 `live_writers`（business_*→业务进程组、telemetry_guest→guest 线程、telemetry_win→win 进程、alerts→io 线程），`evidence_complete = _evidence_ok(missing) and not _any_live_writer()`；record 新增 `writers` 块承载三组关闭事实；summary `writers` 块同源。verify 无需改动：`live_writers→evidence_incomplete`、`evidence_complete!=true→FAIL` 原有路径自然消费新事实。

**修复后（`fixed_behavior/probe_c/`）：**句柄保留（`GuestSampler(…, started daemon …)`）、`evidence_complete=False`、`rc=6`、`guest_sampler_stop_unconfirmed` 事件、释放后文件增长不再能推翻判定。

### SFB-01 的发布顺序（P01/P02）

finalize 重排为**先关闭、后决定、再发布**：

```
检查点①(consume) → guest 关闭确认 → win 关闭确认 → supervisor_end/通知
→ 检查点②(consume) → seal → drain → 检查点③(consume_sealed)
→ io writer 哨兵关闭+join → 私有候选(必需角色哈希;summary 角色除外)
→ [临界区: block → 前提核验 → 最后判定(前提成立时) → C 两赋值 → 解除]
→ (前提失败:保守复核+消费+基线更新)
→ 发布: write_summary → finalize_run_record(消费候选+现算 summary 条目)
```

- **C 前不存在对外完成件**：summary/run_record 的唯一一次发布在 C 之后；`cutoff_pending_rewrite`"先公开成功再覆写"路径删除。
- **发布失败实际影响结果**：`write_summary` 的 OSError 不再被吞——`_summary_publish_failed=True`→`control_outcome→6`；summary 失败仍发布 run_record（summary 条目 missing→evidence=false，作为明确的非成功终结证据）；run_record replace 失败→`_run_record_publish_failed`+emergency 回执+raise→rc=3、无合法完成件。已发布完成件不覆写、不解封原始流。
- summary 是发布时点真实快照：C 后到达的信号如实记录（sig/consumed=False/count）但不参与结果，后置回执 `post_cutoff_signal.json` 承载（count>base）。

---

## 2. 逐项判定证据

### 停止：后台线程仍在时，handler/C 的顺序如何确定？

固定部署环境（WSL2/CPython 3.11.16）实测事实链：
1. pthread_sigmask 只作用于调用线程；进程级信号投递给任一未屏蔽线程；CPython C handler 在接收线程 tripped，Python handler 在主线程下一**字节码检查点**执行——与主线程掩码无关（反例A：writer 接收、临界区内登记；附最小实验：全屏蔽挂起→解除后 handler 执行）。
2. 顺序由**实际登记顺序**（handler 执行时刻）决定：临界区前登记→检查点/最后判定消费参与结果；前提成立时临界区内到达→挂起到解除后→必然 C 后（后置回执）；前提失败→保守复核消费（s01a：rc=4、无伪回执；s02a：登记落 C 后时 rc=0+回执承载，双分支皆不漏）。
3. 能力失败（pthread_sigmask 不可用/s03b、存在未屏蔽线程/s03a）：前提失败如实记录（summary.publication.cutoff_premise_ok=False+detail），无信号时正常成功不受影响、不误杀无关线程（s01a/s03a 断言 aux 线程存活）；有信号保守归因非成功。不返回"能力不足却普通成功"。

### 发布：C 前 reader 能否看到 finalized 记录？

不能（P01 独立观察者三观察点）：候选准备后（C 前）与 C 决定后发布前，权威路径上 run_record.json/summary.json 均不存在；发布完成后 finalized=true 且字节不再变化（静置后 sha256 不变；post_cutoff_signal.json 是独立回执，不属于完成件覆写）。真实写入失败（P02）：summary 写失败→rc=6、无 summary 文件、run_record evidence=false+missing 含 summary；run_record replace 失败→rc=3、目标无合法记录、summary 保留发布时点真实内容。

### 预算：第一次接受 TERM/CRITICAL 时 deadline 是多少？

120s（policy finalize_window_s）从**第一次接受终止决定**起算（reason=`stop_accept:<kind>`）；转 crash 后 deadline 不变（B02：TERM→crash→重复收尾，预算恰一条、不重开）；辅助关闭/发布只消费剩余（反例B修复后 remaining=2.964/5.0；B01/B03 各阶段钳制；I01 工程链注入诊断错误不重建预算）。工程缩窗演示（反例B：窗口 5s、合作退出 2s）。

### 关闭：guest/Windows 超时时的状态？record/verifier 为什么不能误认完整？

超时时句柄与身份保留（W01：`GuestSampler(started daemon)`、thread alive、`_guest_close_state.alive_after_join=True`）；`telemetry_guest` 条目标 `live_writers=True`、`evidence_complete=False`、rc=6——verify 的 `live_writers→evidence_incomplete` 与 `evidence_complete!=True→FAIL` 消费同一事实，误认通道关闭。产品确认的退出：guest join 后 is_alive=False（W02a）、win wait 返回+returncode（W02a：PROBE_WIN_RC 非 None）、io 哨兵 join（W02a：writers.io.joined=True）。测试父进程兜底 kill 仅针对测试自造的忽略 TERM 辅助进程（b01/b03 的 win_ignore、s 系列的 aux 线程），产品侧对真实采样器只有 TERM→有界 wait→如实记录（W03：超时记 unconfirmed、stopped 不出现）。

### 交付：本轮真实测试计数、外层 rc、原始证据在哪里？

见 §5（全量）、§6（冷读）、§7（证据清单）。关键原始故障证据：`counterexamples/{old_behavior,fixed_behavior}/probe_{a,b,c}/`（含完整 run 目录与 probe 日志）。

---

## 3. 测试面变化（含三处点名纠正）

| 文件 | 变化 |
|---|---|
| `test_curriculum261_r17_stop_publication_unit.py` | **新增**（10 项）：S01a/S02a/S03a/S03b/P01/P02a/P02b/W01/W02a+W04/W02b |
| `test_curriculum261_r17_shutdown_fault_budget_cutoff_unit.py` | **C01-in 纠正**：不再预设"屏蔽中发送=C 后"——修复后该前提经线程掩码继承+/proc 核验成立；summary 断言随发布时序迁移（C 后信号如实进快照、consumed=False）；补 premise_ok 断言。**B02 纠正**：预算起点从 terminal_shutdown 改为第一次停止实际起点（`stop_accept:` 前缀）。**B03 纠正**：不再只查 timeout 事件——断言 writers.win.unconfirmed、evidence_complete=False、rc 非零、stopped 事件不出现（W03）。**B01**：事件改名断言+writers 块。**C04 迁移**：重写发布失败场景随覆写路径删除，等价迁移为 C 后首次发布失败（断言无 run_record）。**C02-in**：首信号断言放宽为 TERM/INT 之一（同批挂起信号解除后投递顺序不保证，不作逐个排序断言）。**settrace 定位纠正**：C 赋值行取第一个匹配（保守分支同款文本在其后且仅失败路径执行） |
| `test_curriculum261_r17_unified_shutdown_unit.py` | **L02c 迁移**：pre_summary 屏障随发布时序移到 C 之后——从"C 前消费"参数化移出，新测试断言 C 后回执语义（l02a/l02b 保持 C 前消费） |
| `test_curriculum261_r17_control_path_unit.py` | **新增 I01**：工程链正常停止后注入 finalize 内诊断错误（pending_logs+flush_logs 抛）——同一预算（stop_accept 起恰一条）、_shutdown_step 隔离、rc=4、撤权/terminal/哨兵零启动/采样关闭一致、evidence_complete=True（隔离的诊断错误不破坏完整性） |

所有纠正均注明原因；未删除任何对应反例，未为绿色放宽正确性要求（C02-in 的放宽附 S1 依据：同类标准信号不保证逐个排队/同批挂起投递顺序不保证）。

---

## 4. 实现改动面

```
stage2_6_1/runner/r17_supervision.py   (+508/-73;验收后追加两处防御
  小修:close() 哨兵 queue.Full 容错、finalize_run_record 防御直调
  分支跳过 summary 角色防重复)
  BoundedIOWriter: 掩码继承构造/_loop 哨兵退出/close()
  Supervisor: __init__ 状态字段(guest/win/io close state, cutoff premise,
             publish failed, rr candidate); handle_triggers stop_accept 预算;
             _external_stop_early_window 预算; stop_win_sampler 关闭状态;
             _evidence_ok 消费三组关闭事实; _writer_live_for_role/
             _any_live_writer/_prepare_run_record_entries/finalize_run_record
             (候选+per-role live_writers+writers 块+发布失败事实);
             write_summary 拆分 _build_summary+发布失败标志;
             _start_guest_sampler_shielded; _cutoff_thread_premise;
             finalize 重排(关闭→候选→临界区(前提核验/保守复核)→发布);
             control_outcome 发布失败→6; run() 重置面
stage2_6_1/runner/r17_win_sampler.ps1   未改(写者=interop 进程本身,已核对)
stage2_6_1/runner/r17_verify_delivery.py 未改(live_writers/evidence_complete
                                          原有路径消费新事实)
stage2_6_1/src/rl_curriculum/curriculum261_r17_workflow.py 未改(工程链
                                          合同不受影响,I01 实测)
```

---

## 5. 稳定候选全量验收

一次稳定候选全量（串行，无 `-n`；执行面=同步后 `~/projects/crypto_rl`，Python 3.11.16）：

```
1513 passed, 7 skipped, 23 warnings in 1568.95s (0:26:08)
外层 pytest rc=0（/tmp/sp_full/rc.txt 原件:"PYTEST_RC=0"）
JUnit 汇总: testsuite tests=1520, failures=0, errors=0, skipped=7
基线对照: 接手上轮 1502 passed → 本轮 +11(新增 stop_publication 10 项
+ control_path I01 1 项),无测试删除(纠正均注明原因)
```

原始 stdout/JUnit/rc：`artifacts/repair17/development/stop_publication_sampler_closure/full_run/`。

## 6. 完整副本冷读

正常已关闭包（非 replay、真实 Windows 采样器、快速成功业务）物理复制到新根，仅新根只读验证；负例（缺件/篡改副本）只操作一次性副本：

```
正常 run: supervisor rc=0;run_record finalized=true、evidence_complete=true、
  三组写者确认关闭(guest joined/win exited/io joined)
build: 7 行(manifest+anchor;root=supervisor 祖父层)
新根只读 verify: rc=0, rows=7, problems=0(回执 receipts/verify_*.json)
负例a(删 summary.json 副本): verify 如实失败(rc=1)
负例b(篡改 guest_samples.jsonl 副本): verify 如实失败(rc=1)
原件: cold_read/{cold_read_sp.sh, cold_read.log, sup_stdout.log,
  manifest.jsonl, anchor.json, newroot/, receipts/}
```

## 7. 证据清单

| 证据 | 位置 |
|---|---|
| 三项反例脚本（可复跑） | `…/stop_publication_sampler_closure/tools/probe_{a,b,c}_*.py` |
| 旧行为复现（接手快照 md5 一致） | `…/counterexamples/old_behavior/probe_{a,b,c}/`（含 probe 日志与完整 run 目录） |
| 修复后行为翻转 | `…/counterexamples/fixed_behavior/probe_{a,b,c}/` |
| 全量原件 | `…/full_run/`（stdout/JUnit/rc） |
| 冷读包 | `…/cold_read/` |
| 测试 | `stage2_6_1/tests/route_c_stage2_6_1/`（3 文件修改+1 新文件） |

执行环境记录：WSL `CryptoRL-Ubuntu-24.04`（F 盘 USB SSD），用户 `cryptorl`，conda `freqtrade-rl`，Python 3.11.16；同步面 `r17_sync.sh`（src+tests+runner→`~/projects/crypto_rl`；ps1 不入同步面，测试经 `/mnt/f` 发布仓库路径消费）。

---

## 8. 边界与不变项

- 正式面隔离不变：无正式许可消费、无 formal、无新正式业务数据、无 qualification exposure；历史已终结正式身份继续隔离。
- 领域合同（§10 全表）不变：C1/C3 参数、pair-cluster、κ=1.5、C2 matched 候选表、Global K、rt3 BLOCKED（C3 结构拒绝未解除）、R16 C2 FAIL 保留、Stage 2.6.2 开放。
- 本轮新测试中的辅助进程/线程均为测试创建并登记的实例；watchdog 只做测试兜底。
- 资源纪律：串行单重任务、核心采样 5s/明细 30s、256MiB 遥测预算、300GiB 使用上限沿用。

## 9. 最终状态

```
本轮：R17 冻结前开发候选交付，等待独立审查
最终 Implementation Freeze A / Results B：本轮不创建
真实正式许可 / formal / 新正式业务数据：本轮禁止
完整 fresh rt3：原 C3 结构拒绝未解除，继续 BLOCKED
Stage 2.6.1：尚未通过
Stage 2.6.2：不变
```
