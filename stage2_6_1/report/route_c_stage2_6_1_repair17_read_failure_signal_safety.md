# R17 续轮：读取失败隔离与信号安全停止（read-failure-signal-safety）

**日期：** 2026-09-07
**接手锚点：** `4a3c6a87872774c6cdc80c3168378b211a119eca`（parent `227374c5`）
**性质：** R17 冻结前开发续轮。不是 R18，不创建最终 Implementation Freeze A / Results B，不授权真实正式运行。
**任务书：** 《Stage2_6_1_R17_Read_Failure_Signal_Safety_Agent_Implementation.md》（2026-09-07）

---

## 0. 摘要

本轮只完成两项代码修复与一项测试稳健性修正，不重做上轮已修复的主体（writer 原子边界/正常拒收贯穿/终态内容一致性全部保留）：

| 工作包 | 结论 |
|---|---|
| WP1 读取失败隔离（RCF-01） | PASS——`read_new` 所有 stat/open/read 失败出口本次有效批次为空；读取失败有界诊断；恢复按原身份闸拒收重放旧行；15/30s 失联经真实非 replay 集成可达保护（R05 实测 rc=4） |
| WP2 信号安全停止（RCF-02） | PASS——TERM/INT handler 纯化为属性赋值（零 log/零锁/零 I/O）；注册提前到 run() 最开头并 finally 恢复；停止意图由四类正常控制路径消费（启动拒绝/就绪屏障/准入/spawn 前检查+spawn 衔接+主循环每轮）；持 writer 锁时真实 TERM/INT handler 确认返回且业务真实收到 TERM（S01/S02 实测）；main() crash 分支同步 print 移除 |
| T01 测试确定性 | PASS——get 交接测试改为真实写线程唯一消费者+队列适配注入屏障（不竞争抢元素） |

两个缺陷都在接手快照（`4a3c6a8` 真实模块、隔离副本）上先建立失败证据（REPRODUCED），修复后同一探针翻绿（NOT_REPRODUCED）。

**最终停点见 §10（与任务书 §11 逐字一致）。**

---

## 1. 接手身份与现场（WP0）

| 项目 | 实际核对值 |
|---|---|
| 接手 HEAD | `4a3c6a87872774c6cdc80c3168378b211a119eca`（git fetch 后远端一致，无新提交） |
| 工作树 | 干净（未提交内容为零），分支 `route-c-stage2-6-1-repair17` |
| `r17_supervision.py` blob | `51cd4e78e9ff4808305914d1fc16d87ff6a0fea0`（与任务书 [R3] 一致） |
| 残留任务 | WSL 内无 pytest/r17_/supervisor/coordinator 残留进程（ps 核对） |
| 正式隔离 | 保持：无正式许可签发/消费，已终结正式部署身份未触碰；本轮只读检查，未用真实部署根验证 |
| 快照副本 | `git archive HEAD` 导出一次性副本（家目录），反例在其上执行，不覆盖活跃部署 |

执行面：WSL 开发树 `~/projects/crypto_rl`（`r17_sync.sh` 同步发布仓库 src/tests/runner，含开发树独有 `generator_api` 模块——发布仓库直跑缺少该模块的 2 个测试项属既有状态，本轮与上轮同样在开发树执行面跑）。

一次启动失败痕迹如实保留：`run_supervision/runs/20260907T133822_1978_1969/`（仅 launch_evidence.jsonl——nohup 后台化被 wsl.exe 会话终止连带杀死，未产生业务数据；后续改用会话保持方式重跑）。

---

## 2. 两个真实反例（先证后修）

探针脚本与结果 JSON 随交付（`read_failure_signal_safety/probes/`）。

### 2.1 RCF-01：读取失败后旧批次仍被 pump 消费（`probe_read_failure.py`）

接手实现 `read_new()` 的 stat OSError（`r17_supervision.py:657-660`）与 open/read OSError（`:664-669`）提前 `return []`，**未清空 `self.new_valid`**——上轮批次残留；`_pump_win_lines` 每轮遍历 `win_reader.new_valid` 刷新 `last_win_line_mono`。

快照实测（`rcf01_result.json`，REPRODUCED）：

| 形态 | 实测 |
|---|---|
| 健康基线（seq=1,2） | new_valid=2，last_win_line_mono=10 ✓ |
| 文件消失（stat FileNotFoundError） | read_new 返回旧批次样本，new_valid 残留 2 条，mono 被刷新到 20 |
| 路径变目录（open IsADirectoryError） | new_valid 残留 1 条，mono 被刷新到 30 |
| stale 掩盖演示（连续 5 轮失败读取） | mono 序列 30→40→50→60→70→80，**max_stale=0.0**——15/30s 失联判定永不触发，host 保护被掩盖 |

修复后同一探针（`rcf01_fixed_result.json`，NOT_REPRODUCED）：失败后 new_valid 恒空、mono 不前进、max_stale=58.0（可达 30s CRITICAL 门槛）。

### 2.2 RCF-02：持 writer 锁时信号 handler 重入死锁（`probe_signal_deadlock.py`）

接手实现 `_sig` handler（`:1936-1941`）先 `self.log(...)`（→`BoundedIOWriter.submit`→`with self._lock`，`threading.Lock` 普通，`:971`）再 `request_stop`。主线程持锁时信号打断 → handler 在主线程执行 → 同线程第二次 acquire → 死锁。

快照实测（`rcf02_result.json`，REPRODUCED）：子进程真实 `Supervisor.run`（replay 输入+业务 sleep 30），测试挂钩把 business_started 的 stdout 提交暂停在 submit 持锁区间，父进程发真实 SIGTERM——**50 秒子进程未退出，被 probe watchdog SIGKILL 兜底**（`handler_returned: false`）。

首轮探针顺带证实的附带事实：handler 注册点在就绪屏障/准入之后，注册前窗口（supervisor_start 日志期）的 TERM 以默认行为直接杀死进程（实测 exit=-15），受控收尾/finalize 永不执行。

修复后同一探针（`rcf02_fixed_result.json`，NOT_REPRODUCED）：handler 返回，挂钩释放后 run() 推进，正常控制路径消费停止意图（`supervisor_external_stop` PROTECTION_UNAVAILABLE 告警），业务收真实 TERM（rc=-15），`PROBE_RUN_RC=4`，子进程 ~9 秒有界退出。

---

## 3. WP1：本次有效批次与历史快照彻底分开（§4 全项）

### 3.1 批次生命周期（§4.1）

`read_new()` 方法第一行 `self.new_valid = []`——本次有效批次在任何可能失败的 stat/open/read 之前重建；两个提前返回出口与正常出口语义统一："本轮没有接受新样本，就不向 pump 交付任何新样本"。`_pump_win_lines` 不改（其消费面本就只读 `new_valid`，出口语义由 reader 保证）。`last_valid`/`last_valid_mono`/`last_valid_src_utc` 保留为历史快照（展示/诊断），不是本次输入。

### 3.2 读取失败有界诊断（§4.2）

新增 reader 诊断属性（`WinSampleReader.__init__` 初始化——不经 run 的直构路径安全）：`read_failures`（累计）、`read_failure_consecutive`（连续）、`read_failure_last_op`（"stat"/"read"）、`read_failure_last_utc`、`read_failure_last_err`（异常类名，有界不携路径文本）。诊断不刷新任何有效性/身份/失联计时。正常 EOF 无新行与读取失败是不同事实：EOF 走正常路径（清零 consecutive、批次为空），不产生失败诊断；截断重置分支（size<offset）归类为成功。诊断字段进 `write_summary` coverage（replay 守卫 None）。`_pump_win_lines` 末尾对**首次**读取失败发一次有界 safe_log（`win_read_failure` 事件，正常控制上下文，非 handler）。

### 3.3 cursor、半行缓冲与恢复（§4.3）

读取失败出口同时重置 `offset=0`、`_buf=b""`：文件消失/重建后不把旧半行拼接到另一个来源的内容；恢复读取从头重建，重放旧行由既有 seq 身份闸拒收（不因"故障恢复"获得新有效性——R04 实测：重建文件中 seq=1 重放拒收、seq=2 新行恢复观测，duplicate_seq 如实计数）。R04 测试先红（暴露拼接边界）后绿，属本轮测试驱动发现并修复的真实边界。

### 3.4 失联真正传到保护（§4.4）

失联链路既有且修复后自动贯穿：读取失败 → new_valid 空 → `last_win_line_mono` 不刷新 → `stale_map["win"]` 从最后真实有效样本继续累计（不因错误重置，不重获宽限窗口）→ 15s WARNING/30s CRITICAL（`observation_stale_win`，每必要来源独立）→ `handle_triggers` PROTECTION 链 → `request_stop` → 收尾。host 失联不被 guest 正常更新掩盖（独立判活）；CRITICAL 触发保护后文件恢复不撤回停止；WARNING 后合法恢复按原有迟滞（既有行为）。

**非 replay 真实集成（R05，任务书 §4.4 要求）：** 真实 CLI supervisor（默认真实 ps1 采样，live 模式，无 `--samples-source file:`）+ 业务 sleep 60；就绪后把 `win_samples.jsonl` 替换为目录（ps1 的 `AppendAllText` 对目录持续失败=持续读取失败）→ 失联事实经实际 stale 规则形成告警 → 30s CRITICAL → Protector TERM 业务 → **rc=4 实测**；alerts 含 `observation_stale_win`（实际规则产生，非直接注入）与 `win_read_failure`；summary coverage 记录 `win_read_failures>=1`、`win_read_failure_last_op="read"`；`win_last_mono` 停在注入前、`guest_last_mono` 独立在場。"首样本始终不可读→业务零启动"映射既有 `test_c04_not_ready_rejects_without_spawn`（rc=93 零 spawn）。

---

## 4. WP2：信号处理器只留意图，正常控制路径负责停止（§5 全项）

### 4.1 handler 边界（§5.1-5.2）

`_sig_external` 为实例方法，函数体唯一动作：`if self._external_stop_sig is None: self._external_stop_sig = sig`（纯属性赋值，保留首次信号=粘性原因）。无 log/print/序列化/submit/queue.put/文件 I/O/进程等待/复杂遍历/Event.set。不抛异常跳临界区；不屏蔽 TERM/INT；不引入 RLock/线程池（`BoundedIOWriter._lock` 保持普通 `threading.Lock`，原子边界不动）。

### 4.2 注册与恢复（§5.4）

注册从就绪屏障之后提前到 **run() 最开头**（supervisor_start 日志之前）——注册前窗口（首条日志/就绪等待/准入）的 TERM/INT 不再以默认行为绕过受控收尾（§2.2 附带事实的修复）。`run()` 重构为 wrapper：注册（`try/except ValueError` 降级——非主线程调用形态）→ `try: return self._run_body()` → `finally` 恢复两个旧 handler（5 个返回点全覆盖，不留 handler 给下一次调用/测试）。重复调用 run() 重置意图状态。

### 4.3 意图消费者（§5.3 表逐行）

| 时机 | 实现 | 测试 |
|---|---|---|
| 业务 spawn 之前 | `_run_body` 在 startup_reject/就绪屏障 not-ready/准入拒绝三个早窗口分支检查意图（`_external_stop_early_window`：零业务启动已保证，exit_code=4 优先于 2/93/94）+ 准入后专门 pre-spawn 检查（零 spawn+rc=4） | S05a（零业务文件断言）+ c04 映射 |
| spawn 已发生、衔接窗口 | `spawn_business()` 返回后立即消费检查；主循环每轮开头消费（`_consume_external_stop`） | S05b（真实 spawn 完成后立即自信号→登记后补停） |
| 正常业务执行中 | 主循环每轮（节拍 1s；PEP 475 sleep 中断恢复不影响本轮消费） | S01/S02/S03 |
| leader 退出但子孙活跃 | 主循环 residual 分支持续运行期间消费点仍在 | 既有 residual 测试 |
| drain/finalize 进行中 | handler 只登记（不重入 finalize；`_finalize_done` 守卫既有）；事实进 summary | S05c（supervisor_end 窗口停止：不重入、alerts 单条 supervisor_end、external_stop_consumed=false 只留痕） |
| 成功终态确认后 | coordinator 面既有守卫（不回写 terminal）保持 | 既有 qualification 测试 |

`_consume_external_stop` 走既有 `handle_triggers(PROTECTION_UNAVAILABLE)` 链：`stop_requested_reasons` + `request_stop`（业务活跃）或 `stop_requested_no_live_task`（阻止后续步骤）；业务不活跃时补 `exit_code=4`（修补"业务自然退出后外部停止落到 rc=0"的既有洞——审查第 3 点）。

**重复信号（§5.4）：** 首次原因粘性（S03 实测 TERM→INT 序列 `external_stop_sig=15`）；incident/stop 理由各一条（不新建第二条停止链）；`request_stop` 幂等（合作窗不重开）；不重复 grant/terminal（coordinator 面既有）。

### 4.4 supervisor 异常路径（§5.3 末段）

`main()` crash 分支的同步 `print(R17ALERT, flush=True)` 移除，改为 `sup.stdout_line("R17ALERT", ...)`（异步写线程，必须在 `finalize()` seal 之前入队——已在原位置）。取舍如文档化：stdout 通道尽力而为（写线程阻塞只被 finalize 的 drain 有界等待，超时如实计未确认），stderr/emergency 同步兜底既有，信息不丢。异常退出保留 rc=3 与业务原始 rc 的区分。

### 4.5 审查修正采纳记录

影响审查（实现前 subagent，§全局约定）7 点全部采纳：`__init__` 初始化意图状态（防不经 run 的 finalize/write_summary AttributeError）；早窗口消费缺口补齐（三分支 exit_code=4 优先）；业务退出后 rc=0 既有洞修补；`signal.signal` ValueError 降级；T01 注入点纠正为标准库 `queue.Queue` 属性（`r17_supervision` 内是局部 import，patch 模块对象生效）；`except OSError as exc` 绑定+截断分支归类成功；crash R17ALERT 顺序合同。

---

## 5. T01：writer 交接测试确定性交错（§6）

`test_rsa01_get_handoff_gap_drain_waits` 重写：测试经 `monkeypatch.setattr(queue, "Queue", _PausingQueue)`（标准库模块属性；`BoundedIOWriter.__init__` 局部 `import queue` 解析到同一模块对象）注入队列适配——**真实写线程**调用 `get()` 取走动作后、返回前在屏障暂停（gate.wait(10) 有界）。测试线程只观察（taken 事件→stats 断言 queued=0/accepted=1/ok=0）与 drain（观测线程 0.3s 未返回断言）并释放屏障，**不竞争队列所有权、不手工改计数、不消费再入队**。断言集完整保留（交接空窗 drain 等待；释放后 drain=0+文件已写）。`submit/seal` 竞态测试（屏障确定性）保留；生产 writer 原子设计未动。

---

## 6. 验收矩阵映射（任务书 §7）

| 编号 | 测试/证据 | 结果 |
|---|---|---|
| R01 | `test_r01_file_gone_empty_batch_no_refresh` | PASS |
| R02 | `test_r02_stat_open_read_failure_paths`（stat/open/read 三态+恢复后控制循环继续） | PASS |
| R03 | `test_r03_bad_lines_do_not_advance_liveness`（无新行/半行/坏 JSON/非对象/重复 seq/旧 utc+新合法推进） | PASS |
| R04 | `test_r04_recover_same_source_rejects_replayed_old_lines`+`test_r04_read_failure_alert_bounded_once`（重放旧行拒收/告警一次） | PASS |
| R05 | `test_r05_live_host_read_failure_escalates_to_protection`（真实 CLI+真实 ps1，非 replay，实际 stale 规则→30s CRITICAL→TERM→rc=4）+首样本不可读映射既有 c04（rc=93 零启动） | PASS |
| S01 | `test_s01_sigterm_while_holding_writer_lock`（真实 SIGTERM@持锁：handler 返回+业务 rc=-15+rc=4） | PASS |
| S02 | `test_s02_sigint_while_holding_writer_lock`（SIGINT 同窗口） | PASS |
| S03 | `test_s03_repeated_signals_single_sticky_chain`（TERM+INT：粘性首因/单链/无重复 incident） | PASS |
| S04 | `test_s04_ignore_term_blocked_alert_kill_escalation`（trap "" TERM+R17ALERT 写线程阻塞：KILL 升级+退出核验在阻塞未解除时完成；evidence_complete=false 不假签） | PASS |
| S05 | `test_s05a/b/c`（spawn 前零业务/spawn 衔接补停/finalize 窗口不重入） | PASS |
| S06 | `test_s06a/b`（真实 main() crash：rc=3/TERM 已发；告警通道阻塞仍有界+不完整如实） | PASS |
| S07 | 映射既有：`cancel_after_grant_worker_exit0_not_completed`（真实 CF 链：取消/撤权/terminal/后续哨兵零启动/终态不改写）+ m12（supervisor 真实 TERM→业务停止）+ 本轮 S01/S05 supervisor 层真信号链；无正式数据访问 | PASS（映射） |
| T01 | 重写后 `test_rsa01_get_handoff_gap_drain_waits`+保留 `test_rsa01_submit_seal_race_counts_pending` | PASS |
| T02 | 全量回归（§7 数据）+既有健康路径测试全绿（相同输入输出不因补丁改变） | PASS |
| E01 | 故障 run 证据在测试产物内（alerts/summary/run_record 如实记录失败与缺件；本轮不重建清单掩盖缺失——证据等级披露见 §7.3） | PASS |
| E02 | 受监护全量+交付 build/篡改反例/verify/冷读/blob（§8） | PASS（见 §8 实测） |

R05 未直接调用 `handle_triggers`（实测经真实 stale 规则）；S01/S02 未只 assert 停止标志（实测 handler 返回+业务停止）；S04 未等 finally 解除阻塞才记录保护成功（KILL/核验在阻塞期完成）。

---

## 7. 测试与执行数据

### 7.1 专项（开发树执行面）

- `test_curriculum261_r17_read_signal_unit.py`（新增 15 项）：R01-R04×5+S01-S06×9+R05 live×1 全绿。
- `test_curriculum261_r17_result_seal_unit.py`：38 项全绿（含 T01 重写）。
- `test_curriculum261_r17_supervision_unit.py`+`test_curriculum261_r17_control_path_unit.py`：107 项全绿（既有无回归）。

### 7.2 受监护全量回归（T02/E02）

正式 run：`final_20260907T140907`（`r17_monitored_entry.sh` 起，真实 ps1 采样 live 模式）：

| 项 | 值 |
|---|---|
| 业务命令 | freqtrade-rl conda python -m pytest tests/route_c_stage2_6_1（--junitxml 预登记） |
| 结果 | **1469 passed / 7 skipped / 23 warnings in 1419.53s**（上轮 1454+15=1469 精确吻合本轮新增；0 失败） |
| 外层 | `MONITORED_RC=0`、`business_rc=0`、incidents=0、residual=0 |
| 证据 | `evidence_complete=true`、io 18 accepted/18 ok/0 failed、run_record 内嵌 io 即最终封口态 |
| 资源复算（关闭流重算 vs summary，四项一致） | guest 最低可用 33.96GiB / 任务树 RSS 同刻求和采样峰值 6.066GiB / win 最低可用 31.365GiB / win commit 峰值 56.06%（采样器自身 RSS 24.6MB） |
| 新诊断字段真实捕获 | `win_read_failures=6`（全量 23 分钟内 win 遥测的 6 次瞬时读取失败被 WP1 诊断如实记录——旧行为完全静默；未达 30s 失联线，保护未触发，健康行为） |

启动失败痕迹（如实保留）：`runs/20260907T133822_*`（nohup 后台化被会话终止连带杀死，仅 launch_evidence）；`runs/final_20260907T134710`（错误环境 crypto-rl 跑出 285 个 `No module named 'freqtrade'`——环境归因明确，非代码缺陷；正确环境 freqtrade-rl 重跑）；`run_supervision/runs/20260907T134239_*`（缺 junitxml 登记被启动前拒绝 rc=0 零 spawn，监护正确行为）；一次 run 目录碰撞拒绝（脚本预建目录，入口排他拒绝 exit 96）。上述均在启动阶段或环境层，未产生正式业务数据。

### 7.3 证据等级披露

- 探针/子进程测试的 stdout 由父进程 PIPE 行读取持久化在测试过程；控制台逐字输出未另存文件的部分以 alerts/summary/run_record/JUnit 交叉支撑（与上轮同等级披露）。
- 发布仓库缺开发树独有 `generator_api` 模块的 2 个测试项（a19/rsa03-lookup）只在开发树执行面有效——既有状态（上轮同），非本轮引入；发布仓库直跑该 2 项会 ImportError，如实说明。
- 一次 monitored_entry 启动失败痕迹（§1）保留未删。
- 独立验收（ACCEPT，A-E 全 PASS）5 条非阻断观察项如实记录：N-1 final run 的 utc 标记窗口（1345s）比 monotonic 业务窗口（1422.9s）短约 75s（mono/junit/pytest 三方自洽，应为运行中系统时钟同步回拨；该 run 的 utc 时间戳不可直接换算时长）；N-2 probes `*.json` 尾部混入 `*_exit=` 非 JSON 行（自动化解析需去尾）；N-3 `final.anchor.json` 内 `manifest_blob_id=null`（anchor 构建早于 blob 注册 3 秒未回填，blob id 以 blob.txt 与本报告为准，与上轮同构）；N-4 `test_r04_read_failure_alert_bounded_once` 对日志面为间接覆盖（粘性标志直断言，alerts 落盘由 iow 异步——测试注释已披露）；N-5 停点逐字一致性为报告自述（任务书原文不在仓库，独立逐字核验以验收指令要点交叉一致代替）。

---

## 8. 交付与锚

交付目录：`stage2_6_1/artifacts/repair17/development/read_failure_signal_safety/`

| 内容 | 位置 |
|---|---|
| 反例探针（源+结果） | `probes/`（rcf01/rcf02 各含修复前 REPRODUCED 与修复后 NOT_REPRODUCED 两份） |
| 全量 run | `full_regression/runs/<RUN_ID>/`（junit/summary/run_record/telemetry/alerts） |
| 交付包 | `read_failure_closure/`（manifest/anchors/verify_receipts/cold_read/resource_recompute） |
| 收尾脚本 | `tools/finalize_delivery.sh`+`tools/recompute_resources.py`（自上轮复制，未改上轮脚本）+`tools/run_full_regression.sh` |

交付锚实测（`finalize_delivery.sh` 输出）：

| 步骤 | 结果 |
|---|---|
| build | 8 行 manifest |
| 验证前篡改反例（guest_samples.jsonl 追加 1 字节） | 检出 rc≠0 ✓，恢复后 sha256 与篡改前一致 ✓ |
| verify（正式） | rc=0，rows=8，problems=0（回执 verify_20260907T143900Z.json） |
| 冷读（独立目录） | rc=0，rows=8，problems=0（verify_20260907T143901Z.json） |
| git blob | `manifest_blob_id=3826a2cfc56b40cef59dc3a1903eb130ca352b5a` |

上轮交付（`result_seal_admission_closure/rsa_closure/`）与历史失败 run 原样保留，未原地修改。

---

## 9. 领域边界与正式状态不变（任务书 §10）

Route C 六项环境合同、fee/reward/action/execution/ledger、八个生产特征与 position slot、预处理及 reference 合同全部保留。`RouteCFeaturePreprocessing-v2`、`PolicyVisibleReferenceCanonicalization-v1`、`PolicyVisibleSupervisedLabel-v1`、`C2MatchedLadderBlock-v1`、`GenerationInvocationEnvelope`、main/holdout routing、C1/C3 参数、pair-cluster 与 κ=1.5、C2 matched blockwise 差值 SE、`max_attempts=5`、dedicated semantic 160 blocks、cue audit 500+500、三个 C2 candidates、matched blocks 10/15/20、Global K joint-null、50k/200k、99% CP、INDETERMINATE=FAIL、true tail=t≥264 全部未触碰。无新训练框架、无 WSL 迁移、无依赖版本变更、无压测/拔盘、无用户进程干预。测试内写工程 grant/journal 与真实部署身份从入口到路径隔离。

三件事分列不变：

| 问题 | 本轮处理 |
|---|---|
| 工程 `rt3_calibration_main_r17 / c3_cost / D0 / pair52` 结构拒绝 | 不增 attempts、不跳坐标、不换 seed；保持既有 BLOCKED |
| R16 C2 matched main D3 统计门槛失败 | 保留原始 FAIL，不重解释 |
| C3 PPO Branch D | 独立学习问题，本轮无训练修复，不推出 Stage 2.6.2 PASS |

无业务数据控制夹具的成功不证明课程资格；测试步骤图不是第二份正式流程。

---

## 10. 结论与停点

| 分项 | 结论 |
|---|---|
| WP1 读取失败隔离 | PASS（先成功后各类读取失败均不复用旧批次；实际失联告警与保护可达——R05 真实非 replay 实测；恢复不绕过身份闸） |
| WP2 信号安全停止 | PASS（持锁时真实 TERM/INT 不重入 logger——S01/S02 实测；正常消费者实际停止本任务；阻塞通知不妨碍升级与收尾——S04/S06b 实测） |
| 测试稳健性 | PASS（确定屏障控制真实 writer/handler 路径，无竞争抢元素，无无限 wait） |
| 集成与交付 | PASS（专项+全量+冷读原始证据；外层 rc/业务事实/证据状态一致） |
| 正式边界 | PASS（本轮无真实正式许可/活动/新业务数据；历史隔离与失败记录保持） |

```text
本轮：R17 开发候选交付，等待独立审查
最终 Implementation Freeze A / Results B：本轮不创建
正式许可与真实正式运行：本轮不产生
历史已终结正式部署身份：继续隔离，不恢复机会
新增正式业务数据 / qualification exposure：本轮禁止
完整 fresh rt3：原 C3 结构拒绝未解除，继续 BLOCKED
历史正向素材：依既有来源完整性判断，不补造
Stage 2.6.1：尚未通过
Stage 2.6.2：不变，C3 PPO Branch D 独立开放
```
