# Route C Stage 2.6.1 R17 — 结果判定一致性、在途写入封口与资源准入（开发轮报告）

**英文标识**：R17 Result Propagation + In-Flight Evidence Sealing + Fail-Closed Resource Admission
**性质**：R17 冻结前开发续轮（不是 R18；不创建最终 Implementation Freeze A / Results B；不授权真实正式运行）
**接手锚点**：`28e8ec68d89a7d219faf6d16a82ac62e7b742ed5`（parent `2615485`）
**交付目录**：`stage2_6_1/artifacts/repair17/development/result_seal_admission_closure/`
**提交标记**：`R17 development / result-seal-admission closure / pre-freeze / formal quarantined`

---

## 1. 接手身份与隔离（WP0）

接手快照（只读）落盘于 `wp0_identity/wp0_snapshot.txt`：

- HEAD=`28e8ec6`、parent=`2615485`、分支 `route-c-stage2-6-1-repair17`、发布树工作树干净（Windows 侧）。
- WSL 同步树（`/mnt/f/trading/freqai-rl-audit`）同 HEAD；Linux 根卷用量 ≈37GiB（<300GiB 线）；无存活 r17/pytest 任务。
- 正式许可文件 `.r17_formal_admission.json` 不存在（隔离保持）；本轮零新增正式活动。
- 已知边缘：WSL 侧 git 对 5 个旧 artifact 文件显示 modified——实测为 /mnt/f 上 CRLF/LF 归一化伪差异（Windows 侧干净）；未触碰、未覆盖，本轮提交一律走 Windows 侧 git（与上轮一致）。
- 影响范围审查（subagent，只读）完成：四个修复面的全部调用方、既有测试断言、跨模块风险与陷阱清单驱动了下述实现与夹具适配（详见 §3–§6 各节"影响面"）。

## 2. 三个最小假成功反例（先红后绿）

新测试文件 `tests/route_c_stage2_6_1/test_curriculum261_r17_result_seal_unit.py`；修复前全部红（旧行为实证），修复后全部绿：

| 反例 | 旧行为（红） | 新行为（绿） |
|---|---|---|
| A01：worker 写半行身份后 exit 0 | raw rc=0 → `record_step_completed` → 链继续 fixture_never → `chain ok=true`（假成功） | `effective_result=failed`、链停、fixture_never 零启动、外层非零、raw rc=0 保留 |
| A09：唯一写动作已被写线程 get、持续阻塞、queue 为空 | `drain` 见 `queue.empty()` 返回 0（假完成）；回调抛错被 `except: pass` 后 `executed+=1`（错误计成功） | drain 等待 in-flight 并超时返回未确认（>0）；失败计入 `failed`，不宣称完成 |
| A14：vols 缺字段/空列表/只有 C:/存储查询 None | keyvol 检查整体跳过、storage None 跳过 → 准入 `ok=true` | `required_vol_missing:F:` / `storage_unknown` 拒绝，business spawn=0 |

## 3. WP1 结果传播（RCP-01）：失败真正传到步骤、整链与最外层

### 3.1 实现（`curriculum261_r17_workflow.py` + CLI 两处消费）

- **四语义层**（§4.1）：进程事实（`rc`/`signal` 原样保留，不改写）；协议/控制（delegation 的 cancelled/protocol_error/spawn_failed/worker_unconfirmed/revoke_error）；资格状态（terminal 三态 + journal 只读提取的 `qualification_terminal_status`）；步骤与链（`effective_result`/`effective_failure` + `ok/failed_step`）。
- **`_delegation_step_failure(summary)`**：raw rc=0 只是必要条件——cancelled / spawn_failed / protocol_error / worker_unconfirmed / revoke_error / terminal_state≠committed 任一未闭合 → 步骤有效失败（判定序与 close 第一失败原因一致；unknown 不默认 true）。
- **主循环**：`rc==0 and effective_failure is None` 才 `record_step_completed`；有效失败 → `record_step_failed(rc=0)`（journal 迁移合法）+ 链 break + `_fail_closure_for`；rec 增 `effective_result`/`effective_failure` 字段。
- **`effective_failure` 在任何 rc 下都计算**：rc≠0 时它是控制/协议层第一语义原因（如取消），与进程事实分层披露。
- **CLI 消费**：`cmd_verify_formal_logs`（原只看 rc 的盲区）与 `cmd_real_artifact_rehearsal` 的 step_ok 均按 `effective_result` 判定（旧记录无该字段时按 rc 兼容）。
- **`qualification_terminal_status` 死字段赋真值**：链尾从权威 journal 只读提取；reader 失败如实 `read_failed`，不覆盖链事实。

### 3.2 判定表实测（A01–A08；CF 真实链=真实 execute/coordinator/session/grant+独立 worker）

| 场景 | 实测结果 |
|---|---|
| A01 身份前 exit 0（silent_exit）/半行/坏 JSON 后 exit 0 | raw rc=0（bad_json 为 0 或 -15 时序竞争，两者均有效失败）；protocol_error（identity_pipe_eof 等）；grant=0；步骤 failed；链停；fixture_never 零启动；外层非零 |
| A02 normal+verify_grant | grant 建立/验证/撤销、terminal committed、`effective_result=completed`、链/外层成功、零数值 seed 访问（cf_ns_* 工程命名空间） |
| A03 撤权写入失败（注入 revoke 持久化错误） | revoke_error 保留；`effective_failure=grant_revoke_failed`；不走成功 completed；后续零启动。授权关闭未证实 → 按既有隔离与重任务阻断处置（不把"调用过 revoke"当"已生效"） |
| A04 terminal 写失败 / 写已落盘但报错 / 重复清理 | 写失败→terminal_state=unknown+terminal_error+步骤失败、journal 无 terminal；写落盘后报错→journal 只读核对为 committed（无重复 terminal、不强判）；幂等：close 三态+execgov 二次提交拒绝双保险 |
| A05 取消先接受、worker 捕获 TERM 后 exit 0 | cancelled 保持；新 grant 禁止；`effective_failure=delegation_cancelled`；外层非零 |
| A06 忽略 TERM/迟到半行/token 读端关闭 | 读写共用 spawn 起算 30s deadline（token 写不再重开 10s 窗口）；循环内消费取消（≤0.5s 节拍）；短写不重开；无无界等待 |
| A07 清理不能确认退出 / fail-closure 挂起 | 未确认→rc=92 哨兵（避开 2/3/4/5/6/7/93-99 与 -15）+worker_unconfirmed+有效失败；fail-closure 60s 有界超时（协调者不悬挂、不外抛，fail_closure.log 落 timeout 说明） |
| A08 身份字段错误/部分 spawn 失败 | wrong_identity/extra_ns 经真实核对拒绝；全路径统一 fd 清理（引用置 None 防 FD 复用误关）；无法证明项明示 |

## 4. WP1 有界取消（RCP-04 四点）

1. **身份读循环内轮询取消**：`_read_pipe_line`/`_write_pipe_all` 增 `cancel_fn`，每轮（≤0.5s select 分片）检查；取消观测间隔不超过既有 0.5s 节拍（A05 cancel_read 注入实测同轮响应）。
2. **token 写共用 deadline**：`time.monotonic()+10.0` 重开窗口 → 共用 spawn 起算的同一 `deadline`（§4.6）。
3. **`_terminate_and_wait` 返回确认态**（True=已确认退出/False=未确认）；`_run_step_subprocess` 清理路径不再无期限 `proc.wait()`——未确认 → rc=92 哨兵 + worker_unconfirmed（不填 0）；正常业务等待保持既有运行时长限制（不把业务全程限为握手 30s）。
4. **fail-closure 有界**：`subprocess.run` 加 60s timeout；TimeoutExpired 捕获后写明"未确认结束，收尾按未确认保留"，不外抛（保 execute"返回不 raise"合同，C11 兼容）。

## 5. WP2 在途写入封口（RCP-02）：完成不再依赖 queue.empty

### 5.1 BoundedIOWriter 生命周期（`r17_supervision.py`）

- **动作生命周期**：queued → in_flight → ok / failed；不变量 `accepted = queued + in_flight + ok + failed`（`rejected_after_seal` 单独计，在 accepted 之外）；put/task_done 严格配对。
- **回调抛错不是成功**：`_log_sync`/`_stdout_sync` 失败计数保留在 Supervisor 属性（C10/T07 断言兼容）同时**上抛**，writer 计 failed 并保留有界失败摘要（角色+critical+错误，≤32 条）。
- **drain 按边界**：等待已接受动作**全部成功完成**——队列空但仍有 in-flight 时必须等待（A09 barrier 实证）；失败同样算未完成（不能宣称封口完成）；超时如实返回未确认数，不无限 join、不清空队列。
- **seal()**：run_record 哈希之后拒绝一切新提交（计数 `rejected_after_seal`，不伪装成功处理）；封口后迟到写入不改动已发布文件（A11 哈希不变实测）。

### 5.2 finalize 分批封口顺序

```
producer 停止(samplers stop;protector.flush_logs)
→ supervisor_end 入队(alerts 批最后一条)
→ drain(15)：alerts 批全部成功完成(在途/失败/超时→_io_drain_unconfirmed)
→ write_summary(同步写+完成确认;异常→应急写兜底)
→ finalize_run_record(同步原子写;哈希在写入者退出后)
→ 退出通知 R17LOG(独立后置位置:stdout 非交付文件,不追加已封口流)
→ iow.seal()
```

- `evidence_complete = 必需角色全 present 且 drain 未确认=0 且 io 无 failed/io_stuck/queued/in_flight/dropped_critical 且 writers_live=False`（§5.4：文件存在≠证据完整；live_writers 与 evidence_complete 互斥）。
- summary/run_record 中的 io 快照为其各自**写入时点**的封口态（run_record 写于退出通知 R17LOG 提交与 seal() 之前，故封口终态比 run_record 内嵌值多 1——t22 实测 run_record io=25、seal 后终态 26；run_record 不追改，差异以 anchors 与冷读回执为准）。

### 5.3 验证器消费完成性（`r17_verify_delivery.py`）

verify 新增两条 FAIL 路径（build 仍允许生成诊断包）：逐项 `live_writers` → `evidence_incomplete: 写者未确认关闭`；`run_record.evidence_complete != true` → `evidence_incomplete(缺件/写动作失败/封口未确认/io 丢关键)`。既有 missing-role 路径不变（C14 兼容）。

### 5.4 A09–A13 实测

| 场景 | 结果 |
|---|---|
| A09 单动作 in-flight+queue 空（barrier 确认写线程已进入动作） | drain(0.5)>0（未确认）；解除后 drain=0 |
| A09b 回调抛错 | failed=1、ok=0、drain>0（旧实现吞错计 executed 的反例修复） |
| A10 写失败→evidence | run_record `evidence_complete=false`、`io.failed=1` → build 组包（诊断）+ verify rc=1 `evidence_incomplete` |
| A11 seal 后迟写 | submit 拒绝×2 计数；已发布文件哈希不变 |
| A12 stdout 停读/写线程卡住 | T05/T06/T07 既有真实形态保持（保护先于 IO）；A22 停读 14s 实测 25/25 写动作 ok、0 dropped |
| A13 live_writers | `evidence_complete=false` + required 条目 live_writers → verify rc=1 `live_writers` |

## 6. WP3 资源准入（RCP-03）：按必需依赖集合，unknown≠安全

### 6.1 必需依赖集合（POLICY.startup_admission）

- `keyvol_required=("F:",)`：从部署映射固定（F=活跃项目/WSL/swap/发布路径所在卷）；**不以样本里恰好出现哪些卷决定必需**。
- `keyvol_optional=("C:",)`：登记的应急备用——缺失/异常如实降级（`optional_degraded`），不擅自升级为阻断；E 不在集合时离线不产生任何阻断。
- 每个必需卷要求完整有效状态：present / free 有限数值（<20GiB 拒）/ `identity_match is True`（消费 ps1 既有 serial 核对，此前 admission 从未消费）/ 冲突记录（vol_duplicate）拒绝。
- 可写性（§6.1"运行用户对实际必要目录"）：win 侧消费 ps1 `telemetry_out_writable`（**改为首轮即探测**，首样本必带真实结果，unknown≠true）；Linux 侧 run_dir 写探针（写自己的已登记探针文件后删）。
- Linux 根卷用量：`_storage_used_gib` 返回 None/失败 → `storage_unknown` 拒绝（旧实现跳过）。

### 6.2 样本生成身份与读入身份分开（§6.3）

- `validate_win_sample` 增 `utc`（在场可解析）与 `seq`（非负整数）身份场——旧格式只能由历史只读 reader 解释，不作为 live 准入兼容后门。
- `WinSampleReader`：同 seq 重复消费不刷新 last_valid（`duplicate_seq` 计数）；序号回退（来源重启迹象）不刷新（`seq_regressions`）；**样本 utc 早于本 run 启动−300s 容差 → `stale_replayed` 拒收**（旧日志重放到新 run 不得通过；跨 OS UTC 墙钟比较容差 `source_utc_tolerance_s=300` 已声明，不建时间同步服务）；接收时刻（last_valid_mono）与源生成时刻（last_valid_src_utc）分开记录。
- `admission_check` 对 win/guest 样本做 predates 检查（旧时间戳拒绝）。
- GuestSampler 增 run_id+seq（live 样本绑定本次 run 与源序号）。
- ps1 采样器 sample 行增 `seq`（sampler_start 起单调）。
- 附带修复：ps1（无 BOM）中本轮新增/移动的中文注释行被 PowerShell 按 ANSI 误读后产生了解析敏感字符（手动探针实测 `ParserError: 245 行意外的 }`，见 tools/ps1_manual_probe.sh 输出记录于本节集成过程）；将探测段新增注释改为 ASCII 后 ps1 恢复出样（同一探针实测 seq=1/telemetry_out_writable=true 首样本即带）。既有其余中文注释行未破坏解析、字节未动（勘误修订：验收指出本句原表述与 diff 不符——diff 中探测段两行中文注释被 ASCII 版替换；063719Z 集成 run 的 win_no_lines 现场保留，逐字节根因未定位，归因以上述探针实测为限）。

### 6.3 A14–A18 实测

A14（4 形态拒绝+零 spawn）、A15（identity 不符/重复卷记录拒绝；C 缺失降级不阻断；E 不在集合无影响）、A16（旧行不进有效状态/重复 seq/序号回退/旧时间戳重放全部拒刷新）、A17（来源重启重新建立基线；运行中失联沿用既有每源独立 15/30s 规则）、A18（T01/T02 start-only 与危险零值不 spawn；**健康真实 live 输入经真实准入启动**——见 §7 集成）。

## 7. 集成验证

### 7.1 真实 live 全链（正常控制 run）

`integration/runs/normal_20260907T064316Z`：真实 ps1 win 采样（C:+F: identity_match=true、telemetry_out_writable=true 首样本即带）→ 有效就绪 → 真实准入通过（F: free≈1165GiB）→ supervisor 监护唯一协调者 → 真实 qualify 委派（normal worker）→ grant 发放/验证/撤销 → terminal committed → fixture_sentinel 真实启动并 completed → writer 封口 → run_record/manifest/anchor → 冷读副本 verify。

实测：`MONITORED_RC=0`、biz_rc=0、steps=`[('qualify',0,'completed'),('fixture_sentinel',0,'completed')]`、journal grant_issued+grant_revoked+唯一 qualification_terminal、`evidence_complete=True`、io 16/16 ok 0 failed 0 rejected、`BUILD_RC=0`、`VERIFY_RC=0`（冷读）。

### 7.2 A22 真实 Agent 告警接收（停读后恢复）

`tools/a22_alert_pause_resume.sh` + 回执 `t22_alert_pause/agent_receipt_a22.md`：真实后台任务输出（模式 B 等价）；keyvol WARNING（mono 2.2，"当前任务继续"）→ 同 incident 同秒 escalate CRITICAL（mono 2.5，"停止请求由本地策略执行，不等待模型回复"）→ TERM → business rc=-15 → `SUPERVISOR_RC=4`；**Agent 停读 14 秒**（零读取调用）期间全部保护动作完成，恢复后首读回放全部未决递交行（与落盘 alerts.jsonl 逐行交叉一致）；25/25 写动作 ok、0 dropped。

### 7.3 证据等级披露

- §7.1/§8 的 `MONITORED_RC=0`、§7.3 的 `14/14 稳定` 等控制台逐字输出未持久化为独立文件（结论由 run_record business rc=0、JUnit、alerts 流、tools 脚本与 rejected.jsonl 审计间接支撑；m10 竞态现场保留于 diagnostics/m10_flaky/run_1）。

### 7.4 顺带竞态修复（旧已知形态）

m10（联合负载下 ~2/9 失败）根因：TERM 后业务即死时，退出条件块的 poll 先于下一轮监控段看到退出 → break 时 `biz_rc` 丢失为 None（与上轮 T21 场景 A 勘误同根因）。修复：`_observe_business_exit()` 幂等统一退出观察（监控段与退出条件块两处调用，真实 rc 不因 break 时序丢失）——修复后 14/14 稳定。

## 8. 稳定候选全量回归

受监护串行全量：`1444 passed / 7 skipped / 0 failed`（JUnit 1451/0/0/7，较上轮 +28 项），`MONITORED_RC=0`；资源复算四项与在线 summary 一致；交付锚+篡改反例+正式 verify+冷读全部 rc=0。命令、回执路径、复算表与 blob 见附录 C。

## 9. 交付锚与冷读

交付目录 `result_seal_admission_closure/`：`wp0_identity/`（接手快照）、`t22_alert_pause/`（A22 原始件+回执）、`integration/`（正常链 runs/delivery/cold_read）、`full_regression/`、`diagnostics/`（m10 竞态现场）、`tools/`（全部脚本，本轮实际执行内容登记）。交付 manifest/anchor 与冷读回执见 `delivery_manifest/`（组包命令与哈希在 §9 附录）。

## 10. 正式边界

本轮零新增正式活动/许可/数据/qualification exposure；历史已终结正式身份保持隔离（WP0 只读核对；正式许可文件不存在）；全部测试与注入仅在隔离工程夹具（CONTROL_FIXTURE_TEST/工程命名空间/replay 文件通道），生产入口不因环境变量跳过验证（T22 既有 11 项继续全绿）。

## 11. 分项结论与固定停点

| 分项 | 结论 | 依据 |
|---|---|---|
| 结果判定一致性 | PASS | §3 判定表 A01–A08；r17 专项三文件合计 135 项全绿（=control_path 47+supervision 60+result_seal 28，新文件已含其中） |
| 有界取消与清理 | PASS | §4 四点；A05–A07 |
| 在途写入与封口 | PASS | §5；A09–A13 |
| 资源准入与新鲜度 | PASS | §6；A14–A18+集成真实准入 |
| 交付与告警 | PASS | §7+§9；A22 真实工具接收 |
| 正式边界 | PASS | §10 |

**固定停点**：

```
本轮：R17开发候选交付，等待独立审查
最终 Implementation Freeze A / Results B：本轮不创建
正式许可与真实正式运行：本轮不产生
历史已终结正式部署身份：继续隔离，不恢复机会
新增正式业务数据 / qualification exposure：本轮禁止
完整 fresh rt3：原C3结构拒绝未解除，继续BLOCKED
历史正向素材：仍按既有来源完整性判断，不能补造
Stage 2.6.1：尚未通过
Stage 2.6.2：不变，C3 PPO Branch D独立开放
```

---

## 附录 A：A01–A24 矩阵映射

| 编号 | 测试/证据 | 文件 |
|---|---|---|
| A01 | test_a01_half_line/silent_exit/bad_json | result_seal_unit（新） |
| A02 | test_a02_normal_worker_full_success_path + T08（verify_grant） | result_seal_unit + control_path_unit |
| A03 | test_a03_revoke_write_failure_blocks_success | result_seal_unit |
| A04 | test_a04_terminal_write_unknown / terminal_written_but_raised / a19 readonly | result_seal_unit |
| A05 | test_a05_cancel_propagates + 既有 T12 | result_seal_unit + control_path_unit |
| A06 | 既有 T10（deadline=2 有界）+T13（close_token_read）+cancel_fn 循环内 | control_path_unit + result_seal_unit |
| A07 | test_a07_unconfirmed_termination / fail_closure_timeout_bounded | result_seal_unit |
| A08 | 既有 T09/T11 + FD 复用防护 | control_path_unit |
| A09 | test_a09_single_inflight / failed_action | result_seal_unit |
| A10 | test_a10_write_failure_evidence_incomplete | result_seal_unit |
| A11 | test_a11_seal_rejects_late_submit | result_seal_unit |
| A12 | 既有 T05/T06/T07 + A22 停读 | control_path_unit + t22 |
| A13 | test_a13_live_writers_verify_fail | result_seal_unit |
| A14 | test_a14_required_vol_missing×3 + storage_unknown | result_seal_unit |
| A15 | test_a15 identity/duplicate/optional_C | result_seal_unit |
| A16 | test_a16 legacy/duplicate/regression/old_timestamp | result_seal_unit |
| A17 | test_a17_reader_restart + 既有 M 系失联 | result_seal_unit + supervision_unit |
| A18 | 既有 T01/T02 + 集成真实 live 准入 | control_path_unit + integration |
| A19 | test_a19_terminal_verify_readonly_fails_closed + 既有 C12/T15 | result_seal_unit + supervision_unit |
| A20 | 既有 T19/T20/C14 | control_path/supervision_unit |
| A21 | 既有 verify 篡改系列 + 新增 a10/a13 verify FAIL | 多文件 |
| A22 | t22_alert_pause 真实接收+回执 | t22_alert_pause/ |
| A23 | 既有 T22（TestFormalAdmissionIsolation+Unit 共 11 项） | supervision_unit（勘误修订：原误记 control_path_unit） |
| A24 | 集成正常链+全量回归+交付锚冷读 | integration/full_regression |

## 附录 B：变更文件清单

- `stage2_6_1/src/rl_curriculum/curriculum261_r17_workflow.py`（WP1+有界取消）
- `stage2_6_1/src/rl_curriculum/curriculum261_r17_cli.py`（两处 effective_result 消费）
- `stage2_6_1/runner/r17_supervision.py`（WP2+WP3+m10 竞态修复）
- `stage2_6_1/runner/r17_guest_sampler.py`（run_id/seq）
- `stage2_6_1/runner/r17_win_sampler.ps1`（seq+首轮探针+注释编码修复）
- `stage2_6_1/runner/r17_verify_delivery.py`（完成性消费）
- `stage2_6_1/runner/r17_control_fixture_worker.py`（silent_exit 行为）
- `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_result_seal_unit.py`（新增 28 项）
- `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_control_path_unit.py`（夹具身份适配）
- `stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_supervision_unit.py`（夹具身份适配+m10 诊断断言）
- 交付/报告/tools（本目录与本文件）

## 附录 C：§8/§9 数据（全量回归与交付锚）

### C.1 稳定候选全量回归（受监护）

- 命令：`r17_monitored_entry.sh pytest --max-seconds 3000 -- python3 -m pytest tests/route_c_stage2_6_1 -q --junitxml=<run>/junit.xml`（串行；R17_RUN_DIR 预指定；launch_evidence 登记实际执行内容）。
- Run：`full_regression/runs/final_20260907T064708`。
- stdout：`1444 passed, 7 skipped, 23 warnings in 1204.17s`；JUnit 汇总 `total=1451 failures=0 errors=0 skipped=7`（上轮 1423 → 本轮 +28 项新增测试）；`MONITORED_RC=0`；业务 rc=0。
- 7 项 skip 与上轮逐名一致（勘误修订构成：5 项 ancestry binding（非 repairNN 分支）+ 2 项 r16 governance 条件跳过；无 requires_linux 跳过——全部测试在 WSL 内执行）。

### C.2 资源复算（已关闭原始流重算 vs 在线 summary，`full_regression/resource_recompute.json`）

| 指标 | 复算（原始流） | summary 在线 | 一致性 |
|---|---|---|---|
| guest MemAvailable 最低 | 33.939 GiB | 33.9389 GiB | 一致 |
| win phys_avail 最低 | 32.923 GiB | 32.923 GiB | 一致 |
| win commit 峰值 | 54.77% | 54.77% | 一致 |
| 任务树 RSS 同刻求和峰值 | 6.069 GiB | 6.0688 GiB | 一致（诊断口径：同刻求和非去重物理占用） |
| 采样器自身 RSS（末样本） | 24.2 MB | — | 远低于 256MiB 预算 |

### C.3 交付锚与冷读

- build：8 行 manifest（`full_regression/delivery_manifest_v2.jsonl`）+ 锚 `anchors/final.anchor.json`。
- 篡改反例：向 `telemetry/guest_samples.jsonl` 追加 1 字节 → verify rc=1 检出 → 恢复后哈希一致。
- 正式 verify：`rc=0, rows=8, problems=0`（回执 `verify_receipts/verify_20260907T071128Z.json`）。
- 冷读（独立目录 `cold_read_final/`，脱离开发绝对路径）：`rc=0, rows=8, problems=0`（`verify_20260907T071129Z.json`）。
- git blob：`manifest_blob_id=6f007cbfe6a640e39661ed34aefb5b529b2208e7`（`anchors/final.anchor.blob.txt`）。

## 12. 续轮：独立审查否决与 RSA-01/02/03 修复闭环（R17 冻结前开发第二轮）

### 12.1 独立审查结论与本轮范围

独立审查（`R17_Result_Seal_Admission_Independent_Review.md`，2026-09-07，固定 `227374c`）否决了本轮 §11 的"全部 PASS"结论：**开发验收未通过，R17 冻结前开发继续**（不是新增正式统计 FAIL）。三个未闭合点与审查 §7 给定的修复范围：

- **RSA-01** writer 计数转移与 seal 竞态：queue.get 完成→in_flight 计数的空窗、submit 三段式与 seal 的空窗、finalize 缺事前封口边界；
- **RSA-02** reader 拒绝结果未传到真实消费者：被拒样本仍出现在 read_new 返回值、pump 重做弱校验后刷新失联计时；
- **RSA-03** 终态内容不一致：revoke_error 未闭合仍可写 completed、只读恢复只核对"存在"不核对"是什么状态"、授权后取消（worker 捕获 TERM exit 0）不归因为取消。

审查确认有效的部分保留不动：A01 协议失败阻断链、必需 F 卷准入、身份读写有界。审查 §6 的补充观察（正常业务 wait 依赖外层监护而非统一期限、rc=92 哨兵与"raw rc 原样保留"的表述差异）作为边界披露记入 12.7，不在本轮修改面内。

影响范围审查（subagent，按全局约定先行）结论：三项设计可行；采纳其调整点——退出通知保持入队（seal 前进入批次，避免同步 print 的无界阻塞）、emergency 用"submit 被拒且已 sealed"回退同步直写、guest 校验条件式闭合（live 在 `_emit_guest`，admission/回放保持历史宽容）、terminal 内容不符判定限定 worker_rc==0 窗口、terminate 信号实际送达才置取消标志。

### 12.2 RSA-01：writer 接受/交接/完成/封口原子边界（runner/r17_supervision.py）

- **drain 单一计数口径**：`pending = accepted - ok - failed` 取代 `qsize()+in_flight` 相加——与队列内部互斥、线程调度无关，get→计数空窗内的动作必然已被 accepted 覆盖；`_pending_locked()` 为唯一判定来源。
- **submit 全临界区**：sealed 检查→put_nowait→accepted 计数合入同一 writer 锁临界区（put_nowait 非阻塞；唯一锁序 writer→queue，无嵌套死锁）。通过 sealed 检查的动作立即计入待完成集合，并发的 seal/drain 必然看到它——不存在"未计入也未拒绝"的迟交。
- **finalize 事前封口**（§5.3 顺序修正）：producer 停→supervisor_end 日志+退出通知入队（通知只引用运行前即固定的确定路径，属本批待完成动作）→ **seal** → **drain(15)** → write_summary → finalize_run_record。哈希消费终态计数，**run_record 内嵌 io 即最终封口态**（同时闭合上轮勘误②"写入时点态"）。
- **emergency 回退**：seal 后 submit 被拒（rejected_after_seal 如实计数）→ `_emergency_sync` 同步直写（异常路径受控 I/O，不静默丢弃）；队列满仍走 dropped_critical 保护路径。
- **_evidence_ok 独立防线**：新增 `accepted == ok + failed` 一致性核验（queued/in_flight 保留为诊断维度）。

### 12.3 RSA-02：有效样本输出边界贯穿真实消费者（同文件）

- **reader 输出边界**：`WinSampleReader.new_valid` 每次 read_new 重置，只含通过 validate+seq 去重/回退+predates 全部闸门的样本；read_new 返回值仍含全部可解析 dict 行（诊断/事件面）。
- **pump 只消费边界**：`_pump_win_lines` 对 sample 行显式跳过（有效性唯一由 reader 决定），win_latest 与 `last_win_line_mono` 只从 new_valid 刷新——被拒的重复/回退/旧时间样本不再经弱校验"复活"为有效输入（审查 P3 两场景的正反例见 12.6）。
- **null 行根因修复**：合法 JSON 但非对象（null/标量/数组）计 parse_errors、不入返回（旧实现 reader 的 `obj.get` 抛 AttributeError）。
- **win run_id 严格化**：reader 绑定 run 身份时缺失 run_id 的旧格式拒绝（`run_id_missing`）——历史解释只在只读 reader（run_id=None）与回放输入源。
- **guest 条件闭合**：`validate_guest_sample(rec, run_id=...)` 在传 run_id 时要求 run_id 匹配+seq 非负整数；`_emit_guest`（live 唯一交接点）传 self.run_id 并维护 guest 侧 seq 去重/回退/predates 闸——重复 seq、序号回退、早于 run 启动的 utc 不刷新 `_guest_latest` 与 `last_guest_mono`。
- **replay 不启动生产采样器**：`--samples-source file:`（显式测试输入源）下不再调用 start_win_sampler、不创建 win_reader——与 `_declare_expected` 不登记 telemetry_win 的既有 replay 判定一致；live run 身份绑定不作用于回放输入。
- **摘要贯穿**：summary.coverage 新增 win_duplicate_seq/win_seq_regressions/win_stale_replayed/guest_duplicate_seq/guest_seq_regressions/guest_stale_replayed（同一 reader/emit 闸计数）。

### 12.4 RSA-03：资格终态内容一致（src/rl_curriculum/curriculum261_r17_workflow.py）

- **revoke_error 不入 completed**：close 的意图状态判定序（cancelled > spawn_failed > protocol_error > worker_unconfirmed > **revoke_error** > worker rc）重构为"先决定意图状态再统一提交"；撤权失败时提交 `failed`（note 携带 `grant_revoke_failed:<错误>;worker_rc=<rc>`）——`revoke_error != null && qualification_terminal=completed` 的矛盾态不再可能。
- **只读恢复核对内容与身份**：`_journal_terminal_verified`（存在性布尔）→ `_journal_terminal_lookup`（返回事件 dict）：核对 event/plan_digest/**owner==session.session_hash** 三重匹配；无会话身份属性=无法核对归属→fail-closed None。恢复出的真实 status 记入 `_terminal_status`，summary 新增 `terminal_status` 字段（正常路径也填提交的状态）。
- **步骤判定消费内容**：`_delegation_step_failure` 在 terminal_state==committed 后新增内容核验——`worker_rc==0 且 terminal_status 非 None 且非 completed` → `qualification_terminal_content_mismatch`（限定 rc=0 假成功窗口；crashed 记录的第一失败原因仍是进程事实，不贴内容不符标签）。
- **授权后取消归因**：stop_state 新增 `terminated` 标志（terminate 信号实际送达才置位）；`_run_step_subprocess` 正常 wait 返回后，委派步骤且未标记取消时若 `requested and terminated` → `delegation["cancelled"]=True`+`cancel_detail`（进入 summary）——worker 捕获 TERM 优雅 exit 0 不再写 completed；worker 自然退出后才到达的停止请求不置位（那是步骤边界停止）。

### 12.5 附带修复与夹具升级

- **worker 行为面**（r17_control_fixture_worker.py）：新增 `term_exit0`（先装 TERM 处理器消除安装竞态，再走真实注册/接收路径，token 后打印标记等待停止→优雅 exit 0）；CF 注入新增 `cancel_after_grant` 模式（token 写完成后向协调者自身注入 SIGTERM）。
- **delegation summary** 补 `cancel_detail` 字段（此前两处设置点均未暴露到 summary）。
- **t18 时序脆弱性修复**（test_curriculum261_r17_control_path_unit.py）：`sleep 60` 凑 `max_s=60` 贴线——旧实现 replay 路径 powershell interop 查询把 spawn 推迟约 0.8s 使 run_timeout 稳定先触发；本轮 replay 跳过该查询后 60s 贴线竞态翻向自然退出（stash 旧代码复跑确认归因）。改为 `sleep 90`（30s 余量），测试不再依赖启动耗时的偶然延时。
- **夹具升级**：control_path t04 三处 win 样本补 run_id（live reader 绑定后缺失即拒）；supervision_unit c03 两处内联 guest 样本补 run_id+seq+动态 utc（固定旧日期会被 predates 闸拒收）。
- **A19 更新**：`_journal_terminal_verified(...) is False` → `_journal_terminal_lookup(...) is None`，并补"无会话身份=fail-closed"断言。

### 12.6 续轮测试与交付数据

- **新增 10 项测试**（test_curriculum261_r17_result_seal_unit.py）：
  - TestRSA01WriterAtomicBoundary 3 项：get 交接空窗 drain 等待（手动重演写线程 get 后计数前的真实交错，旧实现 qsize+in_flight=0 假完成）；submit/seal 竞态（barrier 确定性交错：submit 持锁过 sealed 检查后暂停，seal/drain 线程化观测 `assert not result`——旧实现 drain 立即返回 0）；run_record io 终态一致+封口后应急如实计数（rejected_after_seal+1 且 accepted 不变）。
  - TestRSA02SampleBoundary 4 项：pump 拒绝样本不刷新失联计时（重复 seq=5 + 旧 utc 重放后 `last_win_line_mono` 不变、new_valid 空，seq=7 到达正常刷新——审查 P3 两场景的正反例）；null/标量行不炸且计 parse_errors；live reader 缺 run_id 拒绝；guest 身份/序号/新鲜度全闸（重复/回退/旧 utc/缺 run_id 不刷新快照，新样本正常）。
  - TestRSA03TerminalContent 3 项：授权后取消端到端（cancel_after_grant+term_exit0：raw rc=0 保留、cancelled=True、cancel_detail 含 supervision_stop_after_grant、effective_failure=delegation_cancelled、journal terminal=failed、后续零启动）；lookup 内容+会话身份核对（他人 terminal 不匹配）；内容不符判定限 rc=0（crashed 不贴标签、旧 summary 无字段宽容）。
  - 既有断言强化：a03 增加 journal `status=="failed"`+note 含 grant_revoke_failed+terminal_status 断言；a02/a04b 增加 terminal_status=="completed"。
- **专项稳定性**：三测试文件（control_path+supervision+result_seal）145 项连跑 2 轮全绿（157.30s/158.19s）；t18 单独复跑 2 次通过（62.39s/62.21s）。
- **候选全量回归**（monitored_entry 真实监护面，run `full_regression/runs/final_20260907T111521`）：`1454 passed, 7 skipped, 23 warnings in 1306.29s`；JUnit `total=1461 failures=0 errors=0 skipped=7`（上轮 1451 → +10 新增）；MONITORED 业务 rc=0；`evidence_complete=true`、`missing_roles=[]`、io `accepted=17 ok=17 failed=0 in_flight=0 queued=0`（accepted==ok+failed 终态一致核验通过）；无 stop 请求、无拒绝样本（真实 ps1 出样 seq 单调：duplicate/regression/stale 全 0）。
- **资源复算**（`rsa_closure/resource_recompute.json`，已关闭原始流 vs summary）：guest MemAvailable 最低 33.976 GiB、win phys_avail 最低 31.449 GiB、commit 峰值 56.24%、任务树 RSS 同刻求和峰值 6.066 GiB、采样器自身 RSS 24.4 MB——四项与 summary 在线值一致。
- **交付锚**（`rsa_closure/`，--root=full_regression 即 run_record 相对路径基准）：build 8 行；篡改反例（guest_samples.jsonl 追加 1 字节）verify rc≠0 检出、恢复后哈希一致；正式 verify `rc=0 rows=8 problems=0`；冷读（独立目录）`rc=0 rows=8 problems=0`；`manifest_blob_id=ca4418f4d440464be4defee35937b668bb36188c`。

### 12.7 剩余边界披露（审查 §6 对应项，本轮未修改）

- 正常授权后的 worker 等待仍是无 timeout 的 `proc.wait()`，由外层监护运行时长限制兜底（§4.6 的分层设计：握手 30s 有界、正常业务计算用运行时长限制）——这不是统一结束期限，长跑 worker 依赖监护停止链。
- `R17_RC_UNCONFIRMED=92` 是"退出未确认"哨兵而非进程真实退出码；"raw rc 原样保留"的准确表述为：**真实已知 rc 原样保留，未确认退出以 92 哨兵显式区分**（不与 2/3/4/5/6/7/93-99 及 -15 冲突）。
- `BoundedIOWriter.stats()` 的 `pending` 字段=queued（qsize，诊断快照），与 drain 的 pending（accepted-ok-failed，判定口径）同名不同义；schema 保持增量兼容未改名，消费方以 run_record io 的 accepted/ok/failed 三元组为准。
- 新鲜度判定口径：win 失联计时（last_win_line_mono）以**接收时刻**刷新，样本**生成时刻**（utc，跨 OS 墙钟容差 300s）只用于 predates 重放防护——本 run 内早期积压记录（生成后延迟到达）仍会刷新接收计时；该口径已如实记录（last_valid_src_utc 分开保存），未建立生成时刻新鲜度闸。
- MONITORED 控制台逐字输出（R17LOG 行）持久化于交付 run 的 supervisor stdout 通道与脚本日志，JUnit/summary/run_record 为权威佐证（与上轮 §7.3 披露同口径）。
- **验收勘误 E-02（边缘形态披露）**：`_on_supervision_stop` 的 `proc.poll() is None` 检查与 `proc.terminate()` 之间存在极小窗口——worker 恰在此窗口自然退出且未被 reap 时，terminate 对已退出进程成功返回 → `terminated=True` → rc=0 会被保守归因 cancelled（把自然成功误判为取消）。方向保守（不会把失败判成功），本轮以披露记录，未改变判定。
- **验收勘误 E-01（测试稳健性，已应用）**：`test_rsa01_get_handoff_gap_drain_waits` 的主线程手动 `get()` 已改为 `get(timeout=5)`+Empty 显式 fail——写线程抢先取走唯一动作时测试明确失败而非挂起。

### 12.8 续轮结论与停点（不变）

三个 RSA 未闭合点全部修复并有确定性回归覆盖；候选全量 1461 项零失败；交付锚/篡改反例/冷读全过。**R17 冻结前开发候选（第二轮）交付，等待独立审查**。固定停点与上轮 §11 一致，逐字保留：本轮不创建最终 Commit A/B、不签发正式许可、不启动真实 formal、不读取新的正式 design/calibration/holdout/final 数据、不清除或重置已终结正式身份、不换 root 恢复机会、不自动创建 R18；完整 fresh rt3 的 C3 结构拒绝、R16 C2 D3 统计 FAIL、C3 PPO Branch D 三者不因监护修复互相解除；Stage 2.6.1 尚未通过。

## 附录 D：续轮变更清单（相对 227374c）

| 文件 | 变更 |
|---|---|
| `stage2_6_1/runner/r17_supervision.py` | BoundedIOWriter（submit 全临界区/drain 单一口径/is_sealed）、_evidence_ok 一致性核验、emergency 回退、finalize 事前封口顺序；WinSampleReader.new_valid+null 行过滤；validate_win_sample run_id 严格化；validate_guest_sample 条件闭合；_emit_guest 全闸；_pump_win_lines 消费边界；replay 不启动生产采样器；summary.coverage 六字段 |
| `stage2_6_1/src/rl_curriculum/curriculum261_r17_workflow.py` | close 意图状态重构（revoke_error→failed）+_terminal_status；_journal_terminal_lookup（内容+owner）；_delegation_step_failure 内容核验（限 rc=0）；stop_state.terminated 与授权后取消归因；summary 增 cancel_detail/terminal_status |
| `stage2_6_1/runner/r17_control_fixture_worker.py` | term_exit0 行为（先装 handler 再真实 delegate） |
| `stage2_6_1/tests/.../test_curriculum261_r17_result_seal_unit.py` | CF 增 cancel_after_grant 模式；新增 3 测试类 10 项；a02/a03/a04b/A19 断言强化 |
| `stage2_6_1/tests/.../test_curriculum261_r17_control_path_unit.py` | t04 三处 run_id；t18 sleep 60→90（时序脆弱性） |
| `stage2_6_1/tests/.../test_curriculum261_r17_supervision_unit.py` | c03 两处内联样本补 run_id+seq+动态 utc |
| `stage2_6_1/artifacts/.../tools/rsa_closure_delivery.sh` | 新增：续轮交付锚脚本（build/篡改反例/verify/冷读/blob，--root=full_regression） |
| `stage2_6_1/artifacts/.../rsa_closure/` | 新增：续轮交付（manifest 8 行/anchors/verify 回执/冷读/资源复算/blob ca4418f4） |
