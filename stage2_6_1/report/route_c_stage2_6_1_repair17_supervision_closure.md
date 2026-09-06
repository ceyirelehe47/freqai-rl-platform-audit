# Route C Stage 2.6.1 Repair 17 —— 监护接线闭合、正式入口隔离与证据完整性

- 轮次性质：R17 续轮（非 R18）。受限开发实现与工程回归；不创建最终 Implementation Freeze Commit A / Results Commit B，不启动正式链。
- 本轮接手 SHA：`aae6d6acad564a53a42773b9851a3716777c8813`（parent `82de3b5260df3176cf5cb078e88f96522393ba56`）；起点核查：HEAD=origin、工作树干净、vendor pin `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`（发布仓库与 WSL 部署面双侧一致）、WSL `CryptoRL-Ubuntu-24.04`/`cryptorl` 部署路径 `~/projects/crypto_rl` 正常。
- 任务书：《Stage2_6_1_R17_Monitor_Integration_Closure_Agent_Implementation.md》（2026-09-06）。

## 0. 分项结论（§13.2）

| 分项 | 结论 | 依据（详节） |
|---|---|---|
| 正式入口安全 | **PASS** | 本轮零新增真实正式面活动；准入前拒绝闸门（无许可 rc=96 零正式写入）；历史误触证据保全无重置（§2） |
| 真实遥测判定 | **PASS** | live 快照进入策略/峰值/摘要（S1）；就绪屏障+双源独立判活（S2）；C03/C04/C05/C06 全绿（§3） |
| 告警递交 | **PASS** | 升级不被冷却吞（S4/C09）；IO 失败不挡保护（C10）；模式 B 真实接收+确认（C13，§5） |
| 保护/协调者联动 | **PASS** | 组信号+同基准时钟+实例身份（S3/C07/C08）；工程链优雅封口唯一 writer（C11）；terminal 不改写（C12）（§4） |
| 证据完整性 | **PASS** | required 运行前登记、缺件保留为缺件（S5/C14）；verify 缺件 FAIL；锚+git blob（§6） |
| 工程正向回放 | **fixture eligibility BLOCKED（如实）** | 无完整来源闭环的历史正向链 run 素材；不制造正向素材（§7） |
| 原 fresh rt3 全链 | **BLOCKED（不变）** | rt_runs 全部 ok=False（C3/p52 结构拒绝既有定论）；本轮修复不改变生成约束（§7） |

## 1. 实际开发身份

- 开发 HEAD（本轮交付提交）：见 §9 提交记录（提交后填入）。
- 改动范围（全部为未冻结 R17 面）：
  - `stage2_6_1/runner/r17_formal_chain.sh`：准入许可闸门前置（任何正式 artifact/会话/步骤写入之前）；撤销 `R17_ART_ROOT/R17_STATE_ROOT` 对正式 root 的重定向通道（检测到即拒绝 `env_redirect_forbidden`）；新增 `R17_RUNNER_DIR`（工程测试指向真实部署 runner 面调用真实入口）。
  - `stage2_6_1/src/rl_curriculum/curriculum261_r17_admission.py`（新增，自包含仅标准库）：许可文件 `.r17_formal_admission.json` 的双侧一致校验（shell 侧系统 python3 在 conda 激活前执行；CLI 侧 `cmd_chain_run` formal 分支 import `enforce_formal_admission` 于任何文件创建之前）。规则：存在/格式/40hex 非 40 零/freeze_sha 匹配/state root 绑定/release 仓库 git commit 对象存在/一次性消费（`r17_admission_consumed.jsonl`）。**本轮不实现许可生成端，部署面不存在任何有效许可，正式入口保持关闭**；40 零/WIP SHA/--freeze-sha 均只是被拒输入。
  - `stage2_6_1/runner/r17_supervision.py`：S1–S5 修复（详 §3）；run_record schema v2（evidence_complete/missing_roles/status）；`--expect-artifact`/`--obs-ready-deadline` CLI 参数。
  - `stage2_6_1/runner/r17_verify_delivery.py`：v1/v2 双 schema；v2 缺件=build 可组包（清单反映现实）+verify FAIL（`evidence_incomplete`）。
  - `stage2_6_1/runner/r17_monitored_entry.sh`：可选 `R17_RUN_DIR`（工程调用方预指定 run 目录使 JUnit 路径先验可知；缺省自动生成行为不变；排他/碰撞拒绝同款）。
  - `stage2_6_1/src/rl_curriculum/curriculum261_r17_workflow.py`：协调者 SIGTERM/SIGINT 优雅停止（§5.2/C11；详 §4）；`_run_step_subprocess` 登记 worker proc；fail-closure 提取复用。
  - 测试：`test_curriculum261_r17_supervision_unit.py`（D5 重写+`TestFormalAdmissionIsolation`+`TestFormalAdmissionUnit`+`TestWiringClosure`+`TestChainCoordinatorSupervisionStop`+M13/S2 更新）；`test_curriculum261_r17_governance_unit.py`（formal 结构断言补闸门/重定向撤销）。
- 未建立 A/B；未运行真实 formal；未新增正式 qualification exposure；未新开 R18/新 namespace；统计阈值/seed/缓存/marker 未动。

## 2. WP0：误触证据保全、真相分解与正式隔离

### 2.1 误触真相（实际 6 次部署面请求，上轮报告只记载 3 次）

只读核查（`wp0_formal_incident/incident_timeline.md`+34 文件副本归档，副本与原位逐文件 sha256 一致；原位置原字节保留；boot_id 与 journal owner 一致 `4da5bf99-…`，同一内核实例）：

| 维度 | 计数 | 证据 |
|---|---|---|
| 部署面正式入口请求 | **6** | `r17_formal_requests/` 6 目录 |
| 会话接受 | **1**（REQ1 16:00:47Z） | journal seq1 `chain_session_acquired` |
| workflow 执行前缀 | 1 次，前缀长度 0 | fail_closure: `stopped_at_index=0`、`executed_prefix=[]`（provenance-verify rc=2 前置产物缺失） |
| 正式数据消费 / exposure / Commit A | **0 / 0 / 不存在** | `exposure_state=not_exposed`、`r17_code_freeze.json 不存在` |
| 覆盖已有文件 | **0** | 顶层/state 哈希与 mtime 自 REQ1 后逐字节未变 |
| 守卫拒绝 | **2**（REQ2/3） | `R17OwnershipError: iteration 已 aborted`（in_lock_recheck_failed）+rejected_requests 2 文件 |
| 测试通道残留 | **3**（REQ4/5/6） | 上轮 D5 修正版三次执行：state/ART 已重定向 tmp，但 `R17_PROJECT_ROOT` 指向部署面 → 仍真实创建请求目录/obs/采样器/激活日志 |

上轮报告 §1.3"三次"计数不完整、"每次均建立准入会话"表述仅对 REQ1 成立——本轮如实更正，不改写上轮报告原文。

### 2.2 状态分开表达与处置

正式入口请求（6）≠ 会话接受（1）≠ workflow 前缀（长度 0）≠ 数据消费（0）≠ exposure（0）≠ Commit A（不存在）。正式部署身份处置为**隔离待处置，不允许继续准入**（journal 已有终结记录，一次性合同不可重置续跑；本轮不授权恢复机会）。

### 2.3 拒绝前置与测试隔离（C01/C02）

- 准入闸门在创建 `$ART`、激活环境、启动观测、写 journal/plan/abort **全部之前**（拒绝只写请求目录内一条 `admission_rejected.jsonl`，rc=96）。
- 工程测试改沙箱 `R17_PROJECT_ROOT`+部署面真实 runner（`R17_RUNNER_DIR`）；D5 重写后断言真实部署面（请求根+状态根+ART 顶层）逐字节不变。
- 全部测试隔离核查：execgov 测试全 tmp；governance D06/D07 为受支持工程入口（rt rehearsal run 级隔离）；supervision E2E 写发布仓库监护区；唯一直接执行 formal 入口的 D5 已沙箱化。
- C01 矩阵全绿：无许可/假许可（sha 非仓库对象）/env 重定向/直接 CLI 四路全拒且零文件副作用。

## 3. S1–S5 修复（位置/回归/静态 vs 实际执行）

任务书静态结论 S1–S6 全部核实成立（无反证）；全部转化为真实模块回归（监护专项文件 final4 实测 **60 项全过、0 skip**；其中本轮新增 TestWiringClosure/TestFormalAdmissionIsolation/TestFormalAdmissionUnit/TestChainCoordinatorSupervisionStop 合计 24 项）。

| 项 | 缺陷（核实） | 修复位置 | 回归测试 |
|---|---|---|---|
| S1 | `run()` 非 replay 分支 `guest_rec=None`——采样线程数据从未进策略/峰值/摘要 | `_emit_guest` 写盘后存线程锁保护快照 `_guest_latest`；主循环 `_guest_snapshot()` 取最近有效快照喂 evaluate/`_task_aggregate`/`_update_peaks` | `test_c03_guest_snapshot_reaches_engine_and_peaks`（快照→引擎 CRITICAL 组合条件→峰值进 summary 口径） |
| S1b | 同一样本重复消费会增加窗口样本计数 | `SustainWindow.update(new_sample)`+`PolicyEngine._is_new`（按样本 utc 身份） | `test_c03_same_sample_not_counted_twice`（沿用快照计数不涨；新 utc 才 +1） |
| S2a | 固定 `sleep 3.0` 后必 spawn；guest 无首样本只打日志 | `_wait_observation_ready`（win 首有效行+guest 首样本，有界 30s 可调；失败=拒绝本请求 rc=93、不 spawn、只关自身采样器）；`_pump_win_lines` 供主循环/就绪共用 | `test_c04_not_ready_rejects_without_spawn`（真实 `run()` 路径 rc=93、business 零文件、run_record 封口）；全量回归真实就绪 2 秒通过（§8） |
| S2b | 失联判定 `max(两侧时间)` 掩盖单侧失联；预算耗尽 `stale=None` 掩盖失明 | 双源独立 `stale_map{"win","guest"}`→`observation_stale_win/_guest`（15s W/30s C 各自独立）；预算耗尽改**粘性保护性中止**（PROTECTION_UNAVAILABLE，不停采样后宣称有效；缺测区间如实记录） | `test_s2_independent_source_liveness`（C05 单元：一侧活跃不掩盖另一侧）；`test_c06_budget_cap_is_sticky_protection`（C06） |
| S3 | `os.kill(pgid,…)` 非组信号且可能命中无关进程；绝对 monotonic 与 run-relative poll 混算（长运行机器上升级永不触发）；leader 退出≠树消失 | `os.killpg` 组信号+守卫（pgid>1 且非自身组）；`mono_fn` 统一 run-relative 基准；leader `starttime` 实例身份核验（PID 复用不发信号，`identity_mismatch`/completion_unconfirmed）；`_member_pids` 扫描探活（zombie 不计存活） | `test_c07_group_escalation_and_neighbor_survival`（真实 leader+child+grandchild 忽略 TERM→TERM→合作窗→killpg 升级→组空；无关进程存活；无 tree_gone 误报）；`test_c08_*`（高单调起点 1e6 下升级按差值判定；身份不符零信号） |
| S4 | 先覆盖 `inc.severity="CRITICAL"` 再 `should_deliver`——escalate 永不返回，升级告警被冷却吞掉；deliver 的 IO 异常会跳过保护停止 | 升级判定移到覆盖之前；**粘性停止意图先于任何通知 IO 调度**；deliver/stdout/log 全部尽力而为（BrokenPipe/OSError/ValueError 计数不抛） | `test_c09_escalation_survives_cooldown`（W 首发后立即升 C：`action=escalate` 立即产生+停止调度；独立新 CRITICAL 不受别 incident 冷却影响）；`test_c10_alert_io_failure_does_not_block_protection`（alerts 目录占位+stdout 关闭：不抛、停止意图成立、失败计数） |
| S5 | `finalize_run_record` 缺文件 `continue`——required 随现存文件缩小；固定角色不含 JUnit/诊断输出 | 运行前 `_declare_expected`（核心六件+pytest `--junitxml` argv 解析+c3diag `--out` 解析+`--expect-artifact` 显式登记）；finalize 逐角色 `status ∈ {present,missing,unreadable}`；run_record v2 `evidence_complete/missing_roles` | `test_c14_missing_required_stays_missing`（缺 junit+summary：required 不缩小、v2 字段、build 可组包、verify FAIL `evidence_incomplete`）；全量回归 run 的 required 含真实 JUnit（§8） |
| S6 | formal 重定向通道/测试触达部署面 | §2.3（闸门+沙箱+通道撤销） | C01/D5/governance 结构断言 |

另修复（任务书 §5.3 点名）：`emergency_write` 的 `if d.is_dir() or True` 恒真放开——改为只写启动时解析验证的当前用户 LOCALAPPDATA 目录（wslpath 双形态），未知/不可写时如实缺失（stderr R17EMERG 尽力），不遍历 `C:\Users` 逐用户试写。

## 4. 保护与协调者联动（C11/C12）

`execute_workflow_chain_r17`（formal 与 rehearsal 共用代码路径）：
- SIGTERM/SIGINT handler=停止旗标+terminate 当前 worker（`_run_step_subprocess` 登记实时 proc；qualify 委派走既有 revoke→terminal 持权提交路径）；
- 步骤边界不再启动新步骤；按真实 rc/signal 走 fail-closure→`record_iteration_aborted`→`release`（协调者=唯一 journal writer；监护器不写 journal/abort/terminal、不发 grant）。

- `test_c11_supervision_stop_graceful_closure`：真实 `R17ChainSession.acquire`+真实执行器+无业务数据夹具步骤（长睡眠可被终止）；TERM 后协调者 **rc=0 优雅退出**；journal 序列 acquired→step_started→step_failed(rc=-15)→iteration_aborted(reason 含 supervision stop)→released；无双重 acquire；第二步零痕迹；全部事件 writer=chain_session_owner。
- `test_c12_terminal_survives_supervision_abort`：预置 qualification terminal（真实 open_window→commit completed）后停止——原 terminal 前缀逐字节不变（append-only）、尾部新增 aborted、terminal 行唯一且仍 completed；同 state root 二次准入被 journal 拒绝（无重开机会）。

## 5. 告警递交与真实接收（C09/C10/C13）

- 升级/冷却/独立 incident：C09（§3 表）。
- IO 失败：C10（§3 表）；全量回归期间真实 stdout 通道=模式 B（下）。
- **C13 真实接收（模式 B）**：全量回归以后台任务启动（任务输出通道），Agent 以 TaskOutput 周期取回增量 stdout。接收记录的详细程度如实限定：**轮 1 逐时点记录（启动/健康计数/阶段事件/完成通知四级）、轮 2 记录启动确认，轮 3/轮 4 由任务完成通知接收、未逐事件读取**；确认回执落 `receipts/`（含 run_id、run_dir、工具任务 id；UTC 记到十秒位掩码级；本轮全程零资源告警故无 incident_id/接收延迟字段可记——该两字段仅在存在资源告警事件时适用）。已检测（采样/判定）→已投递（stdout 写入）→已展示（工具输出返回 Agent）→已确认（本回执）四级分明；`alert_delivered` 仅代表本地持久化+stdout 写入路径执行，不自动等于接收成功。pending/重连语义：消费按 incident_id 去重；无消费者不影响保护（C10）。

## 6. 证据完整性与交付锚（C14/C15/C18）

- 运行意图决定必需集合（§3 S5）；缺件在 finalize 前后均检出（finalize 前=C14 missing 保留；finalize 后=M19-M21 篡改/缺件既有反例+本轮 verify `evidence_incomplete`）。
- 交付：`supervision_closure/full_regression/`——run_record v2+manifest+锚（manifest_sha256+run_record_sha256 双锚+git blob id 登记于在案 commit）；锚在交付集合之外；`.gitattributes -text` 保 jsonl 字节。
- 冷读：从发布副本（无开发绝对路径依赖）只读验收；真实部署面在回归前后逐字节不变（D5/C01 断言面）。
- 历史缺口不回写：上轮 1307 passed 的 stdout/stderr 缺失保持历史缺失；`run_supervision`/`blocker_diagnosis`/R16 区原字节。

## 7. §9 正向工程回放评估：fixture eligibility BLOCKED（如实）

- `r17_rt_runs` 全部 15+ run `chain_result.ok=False`（rt rehearsal 链从未完整成功；C3/p52 结构拒绝为既有定论）。
- R16 B `stage2_6_1/artifacts/repair16/real_artifact_rehearsal/`（5912 文件/396MB）为 R15/R16 工程工具与工作区大杂烩（dbg/patch/assemble 脚本），无干净正向链 run 的独立 manifest/哈希闭环。
- 结论：不存在"已经存在、有完整来源且可验证的历史工程正向链证据"→ 按任务书 §9.3 交付 **fixture eligibility BLOCKED**，不制造正向素材、不扩大生成范围。本轮以工程控制夹具（C11/C12：真实协调者+session+journal writer+无业务数据步骤模块）覆盖停止/撤销/终态后 reader 接口回归；命名区分 `CONTROL_FIXTURE_TEST`（C11/C12 夹具性质），不冒充 `HISTORICAL_ENGINEERING_REPLAY_TEST`，不消除原 fresh rt3 BLOCKED。

## 8. 全量受监护回归（C18）

三轮受监护串行回归（同一入口 `r17_monitored_entry.sh pytest`，`--junitxml` 指向预登记 run 目录路径；资源/测试/监护策略每次变更后重跑）：

| 轮 | run | 结果 | 性质 |
|---|---|---|---|
| 1 | `final_20260906T183450`（18:34:51Z–18:53:56Z，19:17） | **1 failed / 1367 passed / 7 skipped** | 缺陷暴露轮：新增 `R17_RUN_DIR` 经业务环境泄漏，嵌套受监护的 M16 撞已存在 run 目录（rc=96≠95）——受监护全量真实暴露接线缺陷；run 与事件链原样保留 |
| 2 | `final2_20260906T185600`（18:56–19:15，19:01） | **0 failed / 1368 passed / 7 skipped** | M16 修复（entry 用后 `unset R17_RUN_DIR`+测试防御清理）验证轮 |
| 3 | `final3_20260906T191713`（19:17–19:36，18:38） | **1 failed / 1368 passed / 7 skipped** | junit 登记验证轮：run_record v2 首次含 `junit_xml present`（219,416B）——S5 登记闭环在真实全量验证；失败项=M01 的测试自身 flaky（E2E run 目录名同秒+同测试进程 pid 碰撞，final2 同代码通过=时序性；已修：目录名加纳秒尾段） |
| 4 | `final4_20260906T193909`（19:39–19:57，18:24） | **0 failed / 1369 passed / 7 skipped** | 最终交付轮：全绿；build 8 行 manifest（7 角色+record，junit_xml present）→验证前篡改反例（追加 1 字节→verify rc=1 `哈希不符` 检出→恢复逐字节一致）→正式 verify **rc=0/8 行/0 问题**；manifest git blob `1ddfa868…`（独立登记文件，锚不回写）；资源复算与 summary 四项一致（guest 最低 33.951GiB / win 最低 34.483GiB / commit 峰 52.94% / 任务树 RSS 峰 6.064GiB；guest 215/win 210 样本、213 含任务树；监护开销：guest 侧采样线程 RSS 峰 22.3MiB、CPU 峰 1.6%，win 侧 powershell 采样器工作集峰 186.8MB（final 轮 201MB；双侧合计仍低于 256MiB 预算，结论不变）；零资源告警；stdout/log failures=0） |

- 修复链：轮1 暴露 → entry `unset R17_RUN_DIR`（run 目录只作用于入口自身，不泄入 supervisor→业务环境）→ 轮2 全绿；轮2 的 run_record 仍缺 junit 角色（时序：junit 正则修复在轮2 启动后同步）→ 轮3 验证登记闭环。
- 7 项 skipped 全部为历史轮次分支上下文跳过（R12–R16 binding 检查在各自 iteration 分支外无效——设计内，与上轮同类；逐项见 JUnit）。
- **就绪屏障真实数据**：轮1 `observation_ready ready_after=1.8s`、轮2 同量级（双侧首样本齐备后才 spawn 业务；对拍上轮固定 sleep 3.0 语义）。
- **S1 真实证据（summary 与原始流复算交叉核对，逐项一致）**：

| 指标 | 轮1（summary/复算） | 轮2（summary/复算） |
|---|---|---|
| guest MemAvailable 最低 | 34.330 / 34.330 GiB | 33.943 / 33.943 GiB |
| win 可用物理内存最低 | 32.659 / 32.659 GiB | 34.229 / 34.229 GiB |
| win commit 峰值 | 54.85% / 54.85% | 52.81% / 52.81% |
| 任务树 RSS 峰值（同刻求和，非去重物理占用） | 5.479 / 5.479 GiB | 6.067 / 6.067 GiB |
| 采样覆盖 | guest 225 / win 220 样本；224 含任务树；parse_errors=0 | guest 222 / win 218；221 含任务树 |
| 监护自身开销（guest 侧采样线程；MiB 口径） | RSS 峰值 22.2MiB、CPU 峰值 2.0%（目标 ≤256MiB/≤单核 5%） | 23.5MiB / 1.8% |
| 递交面健康 | stdout_failures=0、log_failures=0、遥测总量 526KB；win 侧采样器工作集峰 201MB | 同左（win 侧 156.5MB） |
| 资源告警 | 0（全程 WARNING/CRITICAL 零事件） | 0 |

- 口径说明：监护开销 RSS 均为 MiB（1024²KB）口径；guest 侧=采样线程自记，win 侧=powershell 采样器工作集（sampler_self_ws_mb 字段）。5 秒采样峰值为采样时刻峰值（非严格峰值）；任务树 RSS 为 pgid+后代同刻 RSS 求和（含共享页重复计数，不称去重物理占用）；win 侧为 GetPerformanceInfo 口径。
- 轮3 的 build+verify+锚+git blob 与验证前缺件反例：见 §6 与 `full_regression/verify_receipts/`。（轮3 数据完成后补录。）

## 9. 停点

- 开发候选交付，等待独立审查。未来正式身份处置、A/B 整理、真正资格运行、D0 生成合同变更或 namespace 预筛解锁均未授权，不自动推进。
