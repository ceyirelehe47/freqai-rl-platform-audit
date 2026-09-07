# R17 控制路径可靠性收口报告（Stage 2.6.1 / Repair R17 续轮）

英文标识：R17 Control-Path Reliability Closure — Valid Readiness, Nonblocking Protection & Cancellation-Safe Delegation

- 日期：2026-09-07
- 性质：R17 冻结前开发续轮。不是 R18；不创建最终 Implementation Freeze Commit A / Results B；不授权任何真实正式运行。
- 任务书：《Stage2_6_1_R17_Control_Path_Reliability_Agent_Implementation.md》（2026-09-07）
- 本轮接手 SHA：`0d53be6e8101f9ccb34f3eae205f3fc195b157dc`（parent `45d073a`）
- 本轮交付 SHA：见 §9（提交链）

---

## 0. 分项结果

| 分项 | 结果 | 依据 |
|---|---|---|
| B1 有效就绪与持续监护 | **PASS** | T01-T04（真实模块+run 级）；start-only/坏样本零 spawn；启动资源准入独立判定 |
| B2 阻塞 I/O 下保护 | **PASS** | T05-T07（真实进程+真实满管道+真实业务）；控制路径零 I/O 等待 |
| B3 资格委派退出/取消/授权闭合 | **PASS** | T08-T15（真实协调者+真实委派+独立 worker 进程+真实 grant）；T14 含真实 supervisor→coordinator 全链 |
| B4 全任务收尾 | **PASS** | T16-T18；正常 leader 退出核验后代；未证实有界退出+rc 维度 |
| B5 角色与交付 | **PASS** | T19-T20；pytest JUnit 由类型必需；缺件不缩小；verify FAIL |
| B6/§9 真实 Agent 告警接收 | **PASS** | T21 两场景（含停读回放）；真实工具返回+落盘交叉；非零告警 |
| §10 T22 正式边界 | **PASS** | 无许可/假 SHA/root 重定向拒绝路径重跑 11/11；本轮零新增正式写入 |
| T23 输入等价性 | **PASS**（映射既有） | M24 确定性 + m01/m22 E2E；控制路径不触业务 RNG（§5） |
| T24 全量回归+冷读 | **PASS** | §8（串行全量受监护+交付锚+冷读回执） |
| 历史 fresh rt3 C3 结构拒绝 | **BLOCKED（继承）** | 原生成约束未解除；本轮不要求也不允许重跑完整 recipe |
| 历史正向回放素材 | **BLOCKED（继承）** | fixture eligibility 维持；不补生成课程素材 |

停点：`R17 开发候选交付，等待独立审查`（§10 固定停点全文见 §11）。

## 1. 执行身份与环境

- 仓库 `ceyirelehe47/freqai-rl-platform-audit`，分支 `route-c-stage2-6-1-repair17`；起点核验：HEAD=`0d53be6`、parent=`45d073a`、fetch 无新提交、工作树 clean（WP0 快照）。
- WSL `CryptoRL-Ubuntu-24.04`（F:\WSL，boot_id `4da5bf99-96aa-40e3-808c-3630d9698335`）/ 用户 cryptorl / conda freqtrade-rl / 项目 `~/projects/crypto_rl`。
- 策略身份：POLICY 新增 `startup_admission` 段（win_free≥8GiB、commit<90%、guest≥4GiB、keyvol≥20GiB、首样本年龄≤10s）与控制时限常量（资格握手 30s/16KiB）；其余数值沿用 R17-SUPERVISION-POLICY-v1 未放宽。新 policy_sha256 随 run_record/summary 记录（例：fe763145…final 轮）。
- 部署面同步：`r17_supervision.py`、`r17_control_fixture_worker.py`（新增）、`r17_verify_delivery.py`、`curriculum261_r17_{workflow,final}.py`、`tests/route_c_stage2_6_1/*.py` → `~/projects/crypto_rl` 对应面（sync_and_test.sh，本轮工具，位于工作区 F:\trading\r17_cpr\tools）。

## 2. WP0：隔离快照与本轮正式边界

见 `control_path_reliability/wp0_isolation/`（快照文档+原始记录）：

- 部署 state 根与上轮归档逐字一致（journal 5 行=REQ1 全零 SHA 会话的 started→failed(rc=2 PrerequisiteError)→aborted→released；aborted marker；6 个请求目录 18312…44919），全部 mtime=2026-09-06T16:00-16:51Z，**本轮开始时无新增正式活动**；`.r17_formal_admission.json`/`r17_admission_consumed.jsonl` 均不存在（无许可，正式入口全关）。
- **B4 活证据（处置并归档）**：WSL PID 402 = 上轮 M07 测试残留的 win 采样器 interop `/init` 桥，已运行 08:54:30 而 ps1 参数 `-MaxSeconds 300`；Windows 侧 powershell 早已退出，桥悬挂（fd0=pipe、父孤儿化）。机制：MaxSeconds 只约束 Windows 侧；父（Supervisor）正常退出后未核验/回收后代。身份确认属上轮测试自建任务，SIGTERM 终止（"(402 terminated)"）。
- 资源：/ 919G 可用、/mnt/f 1.2T 可用、guest 内存 38G 可用（300GiB 口径远未触顶）。
- 本轮全程未启动任何真实正式链/正式数据访问/许可签发；工程测试全部在沙箱 state root（CURRICULUM261_R17_STATE_ROOT=tmp）。

## 3. B1-B5 修复清单（位置 / 旧反例 / 新结果 / 验证层级）

### B1 有效就绪（r17_supervision.py）
- 新增 `validate_win_sample`/`validate_guest_sample`/`_finite_num`（身份+结构+数值范围；零可用内存=有效但危险）；`WinSampleReader` 增 `run_id/saw_valid/last_valid(_mono)/invalid_samples`（saw_any 保留为诊断层）；`_emit_guest` 无效样本落盘但不进有效快照；`_pump_win_lines` 无效行不刷新新鲜度、重复 sampler_start=来源重启事件；`_wait_observation_ready` 只认**有效首样本**+新鲜度（≤2 核心周期）；新增 `admission_check`（run() 在就绪后、spawn 前调用，不过→rc=94 零 spawn）。
- 旧反例（真实模块实测）：sampler_start/空 perf 行使 `saw_any=True`→旧行为放行就绪（T01 断言 `not ok` 在旧代码必失败）；无启动资源准入。
- 层级：真实模块（reader/屏障/准入全为生产代码路径）+ run 级（rc=93/94、business 文件不存在）；已知边缘：win 样本无 vols 字段时 keyvol 准入线不检查（validate 允许 vols=None；真实 ps1 采样总带 vols，回放输入可构造该形态——按跳过而非不可判定拒绝，如实披露）。

### B2 阻塞 I/O 保护（r17_supervision.py）
- 新增 `BoundedIOWriter`（有界队列 1024+单一守护写线程；submit 非阻塞、drain 有界、stats 分层 pending/executed/dropped/dropped_critical/io_stuck）；`Supervisor.log/stdout_line/deliver/emergency_write` 全部经队列（排队≠已持久化≠已递交）；`Protector._safe_log` 改内存 pending 列表（控制动作零 I/O），主循环节拍与 finalize 经 `flush_logs()` 递交；request_stop/poll 顺序=先信号后日志；关键事件队列满丢→主循环触发 `io_evidence_lost`(PROTECTION_UNAVAILABLE) 粘性保护；finalize 顺序合同保留（supervisor_end→drain(15)→summary→drain(5)→run_record 哈希）。
- 旧反例：T05 用 30s 不返回的日志回调——旧实现 request_stop 同步 `_safe_log` 卡 30s×2（实测 60.0s）且信号被延迟；修复后 <2s 内 SIGTERM 已发。T06 真实满管道（64KiB os.pipe 填满）+忽略 TERM 业务：控制递交即刻返回、TERM→KILL 升级不被饿死。
- 层级：真实进程+真实管道+真实业务组；旧反例经固定旧快照语义实测（同文件修复前运行记录于诊断脚本输出）。

### B3 资格委派（curriculum261_r17_workflow.py / curriculum261_r17_final.py）
- FD 所有权：Popen 成功后父进程立即 `_close_fd(w_reg/r_tok)`（幂等+引用置 None 防 FD 复用误关）——旧行为父持有 worker 写端，worker 死后 r_reg 永无 EOF，`readline` 无限阻塞（pipe(7)）；全结束路径（spawn 失败/握手异常/取消/正常）统一 finally 清理。
- 有界握手：`_read_pipe_line`/`_write_pipe_all`（selectors；spawn 起算 30s 总 deadline、16KiB、EOF/半行/坏 JSON/超长/短写/BrokenPipe 均有定义）；`_qualify_delegation_handshake` 身份核对=自报 PID==实际 spawn PID 且 starttime 与 /proc 实测一致且仍存活；namespace 只能请求 plan 导出范围（`qualify_grant_namespaces`，缺省正式集合）的子集；grant 前/响应前重查取消（stop_state）与存活。
- 取消语义：取消先被接受→不新建 grant/不发送 token；grant 建后取消/写失败→close 统一 revoke（不补发）；取消已接受时的协议失败归因取消（cancel_detail 保留）；worker 侧 `_worker_delegate`（final.py）同样 selectors 有界化（EOF/超时/超长 fail closed，不再无界 readline）。
- 阶段准确清理：`_qualify_delegation_close` revoke 失败保留 `revoke_error`（不再 except:pass 吞掉）；第一失败原因优先（代码判定序：cancelled>spawn_failed>protocol_error>worker rc；token_delivery_failed 无独立分支，以 protocol_error 形态进入该优先级；各失败类互斥故顺序无行为差异）；取消后 worker rc=0 不改判成功；terminal 幂等（`_terminal_committed`）；delegation summary（无 token 明文）入 manifest qualify 行。
- 旧反例：T10 四形态在旧实现=readline 永悬挂（half_line EOF 因父持 w_reg 不到来/no_msg 无期限）；T09 early_exit 旧实现悬挂（EOF 不来）。新结果全部有界失败+阶段记录。
- 层级：真实协调者（execute_workflow_chain_r17+R17ChainSession+真实 journal/grant 机制）+独立 worker 进程（r17_control_fixture_worker.py，CONTROL_FIXTURE_TEST；normal 路径复用真实 `_worker_delegate`）；T14 为真实 supervisor→协调者→委派全链。

### B4 正常退出核验后代（r17_supervision.py）
- run() 退出条件重写：biz_done 后仍 `_member_pids()` 核验登记组；残留→`residual_task_after_leader_exit` 事实+CRITICAL 事件+直接 `request_stop`（受控清理 TERM→合作窗→KILL）；**保护停止长期未证实（业务拒死/KILL 无效）时无条件有界退出**（coop+10+25 硬上界；旧实现 kill_ineffective 后无限 continue 到 max_s）；`residual_unconfirmed` 如实记录；业务流哈希在写入者未证实退出时标 `live_writers`（§7.2）。
- `control_outcome()`：外层 rc 维度=93 观测未就绪/94 准入不足/2 意图拒绝/5 完成未证实（优先）/4 保护性中止/6 证据不完整(io 丢关键或 evidence_complete=False)/业务 rc 透传（正值；负值（信号形态）转换为 128+|rc| POSIX 形态，如 -15→143）——leader rc=0+残留、业务 rc=7 等不再返回 0。
- 信号 handler 注册提前到 spawn 之前（M12 偶发根因：TERM 在注册前到达=默认死亡不收业务）；spawn 前已收到停止→拒绝启动（rc=4）。
- 旧反例：WP0 残留 interop 桥（8h54m）即"父正常退出+后代残留"的现成活证据；T17 旧实现 61s 无限循环（KILL 被拒后依赖 biz_done 永不满足）→ 新 41s 有界退出 rc=5。
- 层级：真实进程组（leader/子/孙/邻近无关进程）+run 级 rc。

### B5 角色登记（r17_supervision.py / r17_verify_delivery.py）
- `_resolve_junit`：元素级等号/分离（含空格路径）/bash-c 内等号三形态；bash-c 内**分离**形态返回 `ambiguous_bash_c`（不写万能 shell 解析器）。
- task_kind=pytest：JUnit 为类型必需角色——解析不出/与显式登记冲突→`_startup_reject`→run() 入口 rc=2 零 spawn（记录+封口照常，业务文件不存在=以运行前意图解释 not_expected）；`--expect-artifact junit_xml=…` 映射规范角色 `junit_xml`（不再是 declared: 前缀任意项）。
- verify_delivery build：`missing_roles` 计算结果落锚（`anchor.missing_roles`，清单反映现实）；verify 对 v2 缺件 FAIL evidence_incomplete（既有）。
- 旧反例：`--junitxml <path>` 分离参数形态旧正则不命中→静默无 junit 角色→evidence_complete 误真；新=启动前拒绝或显式登记。
- 层级：真实模块+run 级+真实 verify 子进程。

## 4. T01-T24 测试映射（全部真实仓库实现；计数见 §8）

新文件 `tests/route_c_stage2_6_1/test_curriculum261_r17_control_path_unit.py`（47 项收集）+ 既有文件更新（夹具补 MemTotal/utc、m10 准入兼容、C06/C09/C10 drain、C07 flush、M12 时序）。层级：PF=纯函数/方法、RM=真实模块、RP=真实进程、RC=真实协调者集成、RA=真实 Agent 工具。

| 编号 | 测试 | 层级 | 结果 |
|---|---|---|---|
| T01 | t01_start_only_and_empty_not_ready; t01_no_resource_lines_at_all | RM | PASS |
| T02 | t02_invalid_win_samples_rejected[6]+wrong_run_id+dangerous_zero+invalid_guest[5] | RM/PF | PASS |
| T03 | t03_admission_gate_values; t03_replay_run_denied_without_spawn(rc=94 零 spawn) | RM+run | PASS |
| T04 | t04_partial_line_and_no_refresh; invalid_guest_not_snapshot; sampler_restart_recorded | RM | PASS |
| T05 | t05_request_stop_not_blocked_by_log（30s 阻塞回调；信号<2s） | RP | PASS |
| T06 | t06_stdout_full_pipe_does_not_block_control（64KiB 真实满管道+忽略 TERM→KILL） | RP | PASS |
| T07 | t07_broken_streams_and_emergency_failure; t07_summary_write_failure_emergency | RM | PASS |
| T08 | t08_normal_handshake_grant_and_closure（grant 建立/撤销/completed/唯一 writer/无明文 token） | RC | PASS |
| T09 | t09_worker_exit_before_identity(rc=7+identity_pipe_eof); t09_spawn_failure_keeps_exposure(rc=98+exposure 不退回) | RC | PASS |
| T10 | t10_malformed_identity_bounded[half_line/no_msg/bad_json/oversized]（deadline=2s 注入） | RC | PASS |
| T11 | t11_fake_identity_and_extra_namespaces[wrong_identity/extra_ns]（grant 零） | RC | PASS |
| T12 | t12_cancel_before_grant_no_new_grant[cancel_read/cancel_grant]（真实 SIGTERM 路径+barrier 注入点；后续步骤零） | RC | PASS |
| T13 | t13_token_delivery_failure_revokes_grant（close_token_read；grant 建+撤销+无二次下发） | RC | PASS |
| T14 | t14_real_supervisor_stops_coordinator_after_grant（真实 supervisor 回放 keyvol CRITICAL→协调者取消→worker -15→唯一 writer 封口→二次准入拒；sup rc=4） | RC+RP | PASS |
| T15 | C12 既有（terminal 前缀逐字节不变）+ T14 内 terminal 后二次准入拒 | RC | PASS |
| T16 | t16_leader_rc0_with_children_not_overall_success（rc=0+残留→rc=4；邻居存活） | RP | PASS |
| T17 | t17_kill_denied_residual_unconfirmed_bounded（KILL 注入被拒→41s 有界→rc=5） | RP | PASS |
| T18 | t18_finalize_and_outcome_idempotent; t18_live_writers_mark_uncertain_hash | RM | PASS |
| T19 | t19 五项（分离形态空格路径/缺失 rc=2/bash-c 分离拒绝/冲突拒绝/显式登记映射规范角色） | RM+run | PASS |
| T20 | t20_required_set_not_shrunk_by_absence（必需集合不缩小+build 可组+verify rc=1 evidence_incomplete） | RM+子进程 | PASS |
| T21 | t21_alert_reception 两场景（回执 agent_receipt_t21.md） | RA | PASS |
| T22 | TestFormalAdmissionIsolation+Unit 重跑（沙箱镜像路径;无许可/假 SHA/WIP/root 重定向/一次性消费） | RM+入口 | PASS(11/11) |
| T23 | M24 诊断确定性（既有）+m01/m22 E2E+控制路径不触业务 RNG（本轮改动面=监护/协调者控制层，无业务数值路径） | RM | PASS |
| T24 | 全量受监护回归 final 轮+交付 build/verify+冷读 | RP+RA | PASS（§8/§9） |

## 5. 控制路径与业务输入隔离（T23）

- 本轮全部改动位于监护控制层（supervisor/Protector/委派协议/角色登记）与测试；不修改交易/统计/生成结构合同、C1/C3/C2 参数、namespace/seed 派生、`max_attempts`、正式语义 160 blocks、cue audit 500+500、κ=1.5。
- 监护不消费业务 RNG：replay/采样→判定→控制路径无任何数值 seed 访问；控制 fixture worker（r17_control_fixture_worker.py）无业务数据、不调用生成。
- 非故障业务输出等价：m01（echo ok rc=0 → supervisor rc=0）与 M24 诊断只读 DP 双跑逐字节一致（排除 written_utc）在本轮全量内复验。

## 6. 阻塞 I/O 时间线（T05/T06 关键证据）

- T05：`stuck_log=30s 不返回`；修复后 request_stop 返回 dt<2s、`term_sent_at` 已设、真实业务组 5s 内退出；旧实现实测 60.0s（两次同步 _safe_log）。
- T06：真实 64KiB 管道填满+消费者保持打开不读+业务 `trap "" TERM; sleep 60`：stdout_line 投递 <1s 返回；CRITICAL→TERM→1.0s 合作窗→KILL→组员全部终止、`_member_pids()` 空；io 线程单独承接阻塞（stats pending 如实）。阻塞全程未解除（由测试 finally 排空，非实现路径解除）。
- 通知失败不饿死控制：deliver/log 失败只计数（log_failures/stdout_failures）不抛出；关键事件队列满→dropped_critical→粘性 PROTECTION_UNAVAILABLE（主循环每轮检查）。

## 7. 资格握手结束原因矩阵（真实链实测）

| 结束原因 | 触发 | 观察结果（manifest delegation + journal） |
|---|---|---|
| 正常完成 | normal worker | identity_verified=True; grant_issued=1; revoked=1; terminal=completed; 唯一 writer；无明文 token |
| worker 注册前退出 | early_exit(rc=7) | identity_pipe_eof(worker_rc=7)；rc=7 透传；grant 零；terminal failed |
| spawn 失败 | 注入 OSError | rc=98; spawn_failed 记录；exposure 已持久化不退回；terminal failed(spawn_failed) |
| 半行后退出 | half_line | identity_pipe_eof（EOF 因父关 w_reg 如期到达——旧实现永悬挂） |
| 不发消息 | no_msg | handshake_deadline_exceeded(2s 注入)；worker signal=15；grant 零 |
| 坏 JSON / 超长 | bad_json/oversized(>16KiB) | identity_bad_json / identity_message_oversized；有界失败 |
| 假身份 | wrong_identity(pid=1/start=1) | identity_mismatch(自报 vs spawn_pid+/proc 实测)；grant 零 |
| 超范围 namespace | extra_ns(真实身份) | namespaces_out_of_scope；grant 零 |
| 注册前/发 grant 前取消 | 真实 SIGTERM+读管道注入点 | cancelled=True；grant 零；terminal failed(cancelled)；后续步骤零痕迹 |
| token 写失败 | close_token_read（worker 关读端存活） | identity_verified=True; grant 建→BrokenPipe→token_delivery_failed→revoke；terminal failed；无二次下发 |
| 授权后 CRITICAL 取消 | T14 真实 supervisor | sup rc=4；grant revoked；terminal failed/crashed(cancelled/signal)；aborted→released 唯一 writer；二次准入拒 |
| terminal 后监护故障 | C12/T15 | terminal 前缀逐字节不变；iteration 如实失败；不改 crashed |

## 8. 全量受监护回归（T24）

- run：`control_path_reliability/full_regression/runs/final_20260907T013347`；真实命令=monitored_entry（kind=pytest）→ supervisor → `bash -c "source activate && cd ~/projects/crypto_rl && python -m pytest tests/route_c_stage2_6_1 --junitxml=<run>/junit.xml -q"`；业务窗口 01:33:51Z-01:53:36Z（约 19m45s）。
- **MONITORED_RC=0**：业务 pytest rc=0 且 supervisor 整体 rc=0（新 rc 维度语义：无保护事件+证据完整+业务成功 → 0）。
- **JUnit：tests=1423 / failures=0 / errors=0 / skipped=7 / passed=1416**。相对上轮 final4（1376 收集）净增 47=本轮新增控制路径专项全部通过；7 skipped 为设计内（本机依赖缺置项，逐项理由随 JUnit）。
- summary 交叉：incidents=0、stop_requested=[]、admission ok、coverage 全零异常（win_parse_errors=0、win_invalid_samples=0、guest_invalid_samples=0、telemetry_capped=False、stdout/log_failures=0）；telemetry 536,012B（256MiB 预算的约 0.2%）。io submitted=16/executed=15/pending=0（1 条=drain 后 submit 的退出边界 stdout 递交未及执行——alerts 文件本身完整，如实记录）。
- run_record：evidence_complete=True、finalized=True、七角色全 present（含 junit_xml——B5 登记链在真实全量形态生效）。
- 资源复算（关闭原始流重算 vs 在线 summary，四项全部 match）：guest_memavail_min=34.188GiB、win_free_phys_min=31.143GiB、win_commit_max=56.98%、task_tree_rss_max=5.564GiB；采样器自身 RSS 峰值 23.4MB、CPU 峰值 2.0%（常驻目标 ≤256MiB/≤5% 满足）。

## 9. 交付与锚

- build：`full_regression/delivery_manifest_v2.jsonl`（8 行=七角色+record）；锚 `full_regression/anchors/final.anchor.json`（含 missing_roles=[]、双锚：manifest+run_record 哈希）；`final.anchor.blob.txt` **manifest_blob_id=a4af587679207c6151eed583d1c6e8119e5b6873**（git hash-object 独立登记）。
- 验证前篡改反例：guest_samples.jsonl 追加 1 字节 → verify rc≠0 检出 → 恢复后 sha256 与原值一致（H0==H1，verify 前后原件字节不变）。
- verify 正式：rc=0、rows=8、problems=0（回执 verify_receipts/verify_20260907T015420Z.json）。
- 冷读回执：交付集合复制到独立目录（/tmp，脱离开发绝对路径）后 verify rc=0、rows=8（verify_20260907T015435Z.json）。
- T21 真实接收回执：`t21_alert_reception/agent_receipt_t21.md`（两场景 R17ALERT 逐字内容+工具句柄+UTC+真实 rc）。
- WP0 隔离快照：`wp0_isolation/`；本轮全部执行工具脚本（同步/复现/探针/收集/收尾/冷读）：`tools/`。
- 旧证据（supervision_closure、run_supervision、blocker_diagnosis、误触归档、失败 run）原字节保留；本轮诊断 run 已移至 `diagnostics/`（repro_m12_*）不混入上轮交付区。`run_supervision/rejected/rejected.jsonl` 为 append-only 拒绝日志：本轮 M16/T22 重跑追加 7 行 rejected_concurrent（2026-09-07 时间戳，逐行含 run_id/task_kind），历史 17 行逐字节未动（0d53be6 基线实测 17 行，45d073a 同为 17 行；本轮追加 7 行后共 24 行）。
- 本轮 E2E 测试运行产物（run_supervision/runs/ 下 e2e_* 与 M12/M01 等 run 目录、launch_evidence）按既有传统一并入库（上轮同款）。
- 提交链：`0d53be6` → `43b70d2`（本轮；推送 origin/route-c-stage2-6-1-repair17；提交消息含固定标记 `R17 development / control-path reliability / pre-freeze / formal quarantined`）。

## 10. 正式边界（本轮）

- 本轮零新增正式写入/数据/许可/会话；历史已终结部署身份继续隔离（WP0 快照逐字一致）。
- 无许可拒绝路径重跑 11/11（T22）；未通过部署面 formal root 验证防线（沙箱镜像路径）。
- 不重置、不换 root、不恢复机会、不签发许可。

## 11. 停点（固定）

```text
本轮：R17开发候选交付，等待独立审查
最终 Implementation Freeze Commit A / Results B：本轮不创建
有效正式许可与真实正式运行：本轮不产生
历史已终结正式部署身份：继续隔离，不恢复机会
新增正式数据 / qualification exposure：本轮禁止（实际无冲突）
完整 fresh rt3：原C3生成约束未解除，继续BLOCKED
历史正向回放素材：来源不完整时继续fixture eligibility BLOCKED
Stage2.6.1：尚未通过
Stage2.6.2：不变；C3 PPO Branch D独立开放
```
