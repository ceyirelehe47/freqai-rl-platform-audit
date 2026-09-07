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
