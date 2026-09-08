# R17 收尾二次错误隔离、共享剩余预算与停止决策截止点闭合(开发轮报告)

**英文标识：** R17 Secondary-Failure Isolation + Shared Shutdown Budget + Consistent Stop Decision
**日期：** 2026-09-08
**性质：** R17 冻结前开发续轮(pre-freeze)。不是 R18;不创建最终 Implementation Freeze A / Results B;不产生正式许可、真实正式运行、正式数据或 qualification exposure。

## 1. 身份与接手

| 项 | 值 |
|---|---|
| 接手 SHA | `56f4d0060a4f3960700b7b32c4b58e4d1cb96dfc`(=origin HEAD,无新提交,工作树干净) |
| 接手 supervisor blob | `383e573bd2918b3b2522ae9e07c4b0b536681dc2` |
| vendor pin | `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` |
| 交付 SHA | `c23b5f0b08fefe2ed322bf1d1b464a2ce2f4acde`(见 §9) |
| 环境 | WSL `CryptoRL-Ubuntu-24.04`/`cryptorl`;conda `freqtrade-rl`,Python 3.11.16;执行树 `~/projects/crypto_rl` |
| import 来源 | 接手验证:`stage2_6_1_runner/r17_supervision.py`(发布树快照与执行树逐字节一致) |
| 历史基线(不作本轮结果) | 上轮 `final_20260907T163430`:1486 passed/7 skipped/1408.57s |

## 2. WP0:接手快照上的三项最小复现(先定位,不先跑全量)

固定接手快照的临时工程副本(`~/r17u2_wpo/snapshot_handover_56f4d00/`,不切换活跃部署)。探针源码与原始输出归档于 `probes/wp0_repro_handover/`(每探针含 child_stdout.log 与 result.json 原件)。

| 探针 | 缺陷 | 原始数字(接手快照) |
|---|---|---|
| P1 二次错误 | `_terminal_shutdown` 循环内第一次退出观察抛错即跳出整个循环:TERM 已发(`sigterm_sent`)、KILL 从未发生,supervisor 返回 rc=3 时业务组(leader+真实后代,均忽略 TERM)仍活 | rc=3;alive=[408,409];sigkill_sent=false |
| P2 共享期限 | deadline 为 `_terminal_shutdown` 局部变量,未传入 finalize 各等待:停止阶段消耗后剩余 2.786s,`stop_win_sampler` 仍拿全额 wait(10)(真实等满 10.000s),`drain(15.0)` 请求 15s(剩余已 -7.214s),总链 12.235s | budget=5.0s;drain_requested=15.0 |
| P3 最后窗口 | 检查点④判定后、C 标记赋值前(handler 已实际登记,sig=15、count=1、consumed=False),run 返回 rc=0 成功、summary 无外部停止事实;`_record_post_cutoff_signal` 的"有信号且未消费就算 C 后"防御兜底把该 C 前登记伪称为 C 后事件写入回执(§6.4 点名禁止形态) | rc=0;consumed=False;回执 sig_count_at_cutoff=0/total=1 |

探针形态:真实 `main()`/进程内 run、真实 fork 后代忽略 TERM、`sys.settrace` 行级定位 finalize 内 C 标记赋值行(发布树 2929 行)前发送真实 SIGTERM,handler 在 C 赋值前完成登记(`PROBE_HANDLER_DONE=15` 实证)。测试自身 watchdog 兜底单独记录,不计产品保护成功。

## 3. 实现(最小修改;不新建平台)

执行面变更仅 `stage2_6_1/runner/r17_supervision.py`(git numstat +217/−41 行;主体提交消息误记 +219,以 numstat 为准)与新增测试文件;`curriculum261_r17_workflow.py` 零改动(src/rl_curriculum 无任何模块 import supervisor——影响面审查确认)。

### 3.1 WP1-A 二次错误隔离

- 新增 `_shutdown_step(name, fn, default)`:终止收尾循环内单步兜底——该步抛错被有界吸收(每步骤保留首错误/类型/首见时刻与计数,首条经 `emergency_write` 同步落盘 `terminal_shutdown_step_failure`),返回 default,不依赖该步的控制继续(§4.1)。
- `_terminal_shutdown` 循环体:`poll`/`flush_logs`/`_observe_business_exit`/`_terminal_state_confirmed` 每步独立兜底;终态核验失败=default False(不确认);退出观察一次失败=本轮未知而非已退出,预算内下轮重读;残留核验自身失败≠无残留(default True 保持未确认)。
- `finalize` 内 `protector.flush_logs()` 同样纳入 `_shutdown_step`(收尾内的日志递交属诊断依赖,非发布步骤):持续 flush 失败不再中断封口(seal/summary/run_record 继续)——f03 测试暴露的第三个真实缺陷位(旧代码在持续 flush 失败下 summary/run_record 完全缺失)。
- summary 新增 `shutdown_step_failures` 有界事实字段。

### 3.2 WP1-B 共享收尾预算(一次建立、一直复用)

- 新增 `_ensure_finalize_budget(reason)`(幂等建立绝对单调 deadline)/`_finalize_remaining()`/`_bounded_wait(cap, phase)`(=min(阶段上限,剩余);零剩余=0.0,不转 None/默认值/无期限)。
- 建立点:首次进入终止性处理(`_terminal_shutdown`,先于可能失败/阻塞的诊断)、正常收尾(`finalize` 开头)、早拒绝(`stop_win_sampler` 入口);重复进入任何收尾方法复用同一 deadline,不重新计时。`run()` 开头与 external stop 状态同面重置(每个 run() 一份)。
- 消费点:guest 采样线程 join(原 15s)、win sampler stop 的 wait(原 10s)、seal 后 drain(原 15s)全部改为 `_bounded_wait`;win 超时事件附 `budget_remaining_s`。主循环运行时长不受 120s 限制(预算只在收尾链生效);`start_win_sampler` 的 ps1 派生寿命不改;主循环既有保护硬上界(coop+10+25 等)不动(t17 公式保持)。
- summary 新增 `finalize_budget` 可核验事实(window_s/established_at_mono/establish_reason/remaining_at_write/notes[≤64]:每阶段 requested/remaining/allowed)。

### 3.3 WP2 停止决策边界 C(sigmask 临界区)

- `finalize` 尾部检查点④+C 标记合并进 `signal.pthread_sigmask(SIG_BLOCK, {TERM, INT})` 临界区:`[屏蔽]→最后判定(有意向未消费→结果层消费,纯内存赋值)→C 两赋值→[解除屏蔽]`,随后在剩余预算内发布(候选重写机制沿用)。
- 顺序论证:临界区在主线程(finalize 调用面)屏蔽 TERM/INT——Python handler 的登记要么已发生在临界区前(被最后判定看到,参与本 run 结果),要么只能在解除屏蔽后(必然在 C 之后,count>base,由独立后置回执承载);不存在"handler 在检查后、C 前登记却被 C 基线吞掉"的中间态。CPython 信号处理只在主解释器主线程执行(S1);临界区内零 I/O、零进程等待、零普通锁;`_consume_external_stop_sealed` 本身只做内存赋值。
- 平台降级:`pthread_sigmask` 不可用时如实记录 `cutoff_mask_unavailable`,退化为顺序判定→标记(窗口收窄为两赋值间隙);Linux 主路径已关闭窗口。
- 删除 `_record_post_cutoff_signal` 的"有信号且未消费就算 C 后"防御兜底(§6.4 点名禁止):只承载真正 C 后新到信号(count>base)。C 前登记必被临界区消费,不可能落到 C 后还保持未消费。
- 检查点①②③位置与语义不变(seal 前完整消费链/seal 后结果层消费)。

## 4. 闭合验证(修改后代码上的同探针)

`probes/wp0_closure_verified/`(修改后 supervisor 快照与原始输出):

| 探针 | 结果 |
|---|---|
| P1 | rc=3;KILL 发生(sigkill_sent=true);业务组在 supervisor 返回前结束 |
| P2 | budget=5.0s;停止后剩 2.786s→win join 实际 2.787s(≤剩余+节拍容差);drain 请求 0.0(剩余耗尽,零剩余不变无期限);总链 5.001s(≤预算+容差) |
| P3-pre(临界区进入行执行前发 TERM,等 handler 完成) | rc=4;consumed=True;count_at_cutoff=1;summary 重写承载 external_stop_sig=15;无伪 C 后回执 |
| P3-in(C 标记赋值行,屏蔽中发 TERM) | rc=0;consumed=False;count_at_cutoff=0;独立回执 sig_count_total=1>base=0;summary/封口件无改写 |

## 5. 验收矩阵(16 组;专项测试文件 16 项全绿)

新测试文件 `tests/route_c_stage2_6_1/test_curriculum261_r17_shutdown_fault_budget_cutoff_unit.py`(**16 passed in 82.30s**;真实模块+真实子进程+settrace 行级定位;生产入口无注入通道):

| 编号 | 用例 | 关键断言 |
|---|---|---|
| F01 | f01(真实 main(),真实 coop=30s,真实后代+独立邻居,升级前第一次 flush 抛错) | rc=3;KILL 仍发生;business rc=-9 真实取得;terminal_confirmed;二次错误有界登记;邻居存活;业务组已结束 |
| F02 | f02a(升级前退出观察抛错)/f02b(实际 rc 已读到后退出日志链抛错) | KILL 仍发生;真实 rc(-9/-15)保留;封口继续(supervisor_end);shutdown_step_failures 在 |
| F03 | f03(R17ALERT 持续阻塞+flush 持续抛) | KILL 由内存状态证实(kill_sent);flush 失败有界累计≥2;封口完成(summary/run_record 在);证据完整性按事实呈现 |
| F04 | f04(成员核验持续失败) | 不盲杀(无 sigkill);residual_unconfirmed=True(核验失败≠无残留);poll/residual_scan 步骤失败登记;登记组保持未处置 |
| B01 | b01(缩窗 5s) | win join≤剩余;drain 请求钳制(15→剩余);总链≤预算+容差;budget_established 恰一条;各阶段 notes 可核验 |
| B02 | b02(TERM→停止中 crash→重复调用收尾) | deadline 不变(REPEAT_DEADLINE_SAME);term_sent_at 不重发;预算恰一次建立(reason=terminal_shutdown:*);finalize 幂等(supervisor_end 恰 1);首因保留 |
| B03 | b03(缩窗 1.2s,等待耗尽) | win join≤低剩余(非全额 10s);总链≤预算+容差;remaining_at_write≤0.6;win_sampler_stop_timeout 如实记录 |
| C01 | c01_pre/c01_in(正反对照;settrace 定位临界区进入行/C 标记行) | 前:rc=4、消费、summary 重写、无伪回执;后:rc=0、独立回执 count_total=1>base=0、封口件不改 |
| C02 | c02_dual(临界区前 TERM+INT)/c02_in_repeat(临界区内 TERM+INT 两种信号)/c02_mask_restore | 双登记首因粘性(TERM)、count=2、同一决策消费;临界区内两信号解除后逐一登记(count≥2,回执承载,S1:同类标准信号不逐个排队,故用两种信号);掩码复原(SIGMASK_AFTER=empty)+handler 恢复 SIG_DFL |
| C03 | L02a/b/c/d(既有)+c01_in | ①②③屏障消费与 C 后回执语义保持;临界区内=C 后 |
| C04 | c04(临界区消费决定后发布失败) | 外层 rc=3(不因 cutoff 已建立返回成功);消费决定不撤销(PROBE_CONSUMED=True);无伪回执 |
| L01 | l01(正常成功/crash/93 早拒绝三出口) | 每 run 预算恰一条建立记录;crash 出口 reason=terminal_shutdown:*;早拒绝出口经同一预算面(stop_win_sampler) |
| I01 | i01(真实 supervisor→工程 coordinator→已授权无数据 worker,叠加收尾 flush 二次失败) | rc=3;真实 grant_revoked/qualification_terminal(failed|crashed)/chain_iteration_aborted/chain_released;哨兵零启动;同 run 的 shutdown_step_failures 与 finalize_budget 事实在 |
| R01 | 既有 reader/writer/权限/封口回归 | 见 §6(231 项全绿) |
| E01/E02 | 冷读与全量 | 见 §7/§8 |

F01 保留真实合作窗口 30 秒、业务先证明 TERM 忽略已安装(READY marker)、真实后代与独立邻居、持续通知阻塞;其余缩窗项在用例内标注。

## 6. 专项回归(既有 R17 测试零破坏)

修改后执行面上串行运行既有 8 个 R17 测试文件:`unified_shutdown`(12)/`read_signal`(15)/`result_seal`/`control_path`(含 t14/t14b)/`supervision_unit`(60)/`execgov`/`governance`/`cold_copy` = **231 passed in 550.79s,0 failed**。U02/U03/L02-L04/S05/S06/t16-t18 等直接锁定旧行为的用例全部保持绿。

## 7. 受监护全量

`runs/final_20260908T024944`(2026-09-08T02:49:46Z→03:14:21Z,约 24.6 分钟;monitored_entry 监护;R17_RUN_DIR 预指定;freqtrade-rl 解释器;串行):

- stdout 原文(business/stdout.log 尾部):**1502 passed, 7 skipped, 23 warnings in 1482.56s**
- JUnit 汇总:**1509 tests / 0 failures / 0 errors / 7 skipped**(上轮 1493+本轮新增 16 项验收矩阵=1509 精确吻合;计数不复用历史)
- summary:business rc=0;io 18 accepted/18 ok/0 failed/0 dropped_critical/io_stuck=false;external_stop_sig=null(sig_count=0);residual_unconfirmed=false;finalize_budget(正常路径 establish_reason=finalize;remaining_at_write=119.934;notes=4:established/guest_join/win_sampler_join/io_drain)
- run_record:finalized=true、evidence_complete=true、missing_roles=[](7 角色+manifest record 行=8 行清单)
- 外层 rc=0:父级显式落盘 `runs/full_outer_20260908T024944.rc`(0) + wsl 链 exit 0 + supervisor summary rc=0

同日第一次启动尝试 `runs/final_20260908T024858` 被入口拒绝(R17_PROJECT_ROOT 未指到执行树,activate 脚本不存在,rc=98)——按事实保留,不删除。

## 8. 交付与冷读

- 本轮位置:`stage2_6_1/artifacts/repair17/development/shutdown_fault_budget_cutoff/`(tools 复用上轮已验收版本,md5 见 tools_md5.txt;旧 unified_shutdown_cold_read 等目录原样保留)。
- 固定清单+锚+完整副本+独立冷读+缺件/篡改负例(`finalize_delivery.sh` 8 步,工具复用上轮已验收版本,md5 见 `tools/tools_md5.txt`):

- 资源复算(已关闭流重算,与 summary peaks 交叉一致):guest MemAvailable 最低 **34.394GiB**、任务树 RSS 同刻求和峰值 **5.558GiB**、win 最低可用 **29.615GiB**、win commit 峰值 **58.54%**、采样器自身 RSS 25.1MB
- build 固定清单+锚:8 行;原根复验(构建自校验,如实标注非独立冷读):8 行 0 问题
- 冷读副本:8 文件 **928558 字节** 物理复制+逐项哈希核对
- **独立冷读**:unshare user+mount namespace 内 tmpfs 遮蔽 /mnt → 原根不可见(original_root_visible="no")→ verify 只读新根 rc=0(8 行 0 问题)→ payload 前后快照不变 → 回执 rc=0
- 负例(一次性副本):缺件隔离 verify rc=1(失败原因=缺失文件检出,非脚本崩溃);篡改一字节隔离 verify rc=1;正副本与原件字节不变
- git blob 锚登记:两段式(先 commit manifest,后 `register_anchor.sh` 登记,见 §9 勘误/登记提交)

## 9. Git

- 提交标记:`R17 development / shutdown-fault-budget-cutoff / pre-freeze / formal quarantined`
- 接手 `56f4d006` → 交付 `c23b5f0b08fefe2ed322bf1d1b464a2ce2f4acde`(完整新增父链见 git log;不 amend/squash/force-push)。

## 10. 领域合同与正式状态保持

Route C 六项环境合同、fee/reward/action/execution/ledger、八个生产特征与 position slot、`RouteCFeaturePreprocessing-v2`、`PolicyVisibleReferenceCanonicalization-v1`、`PolicyVisibleSupervisedLabel-v1`、`C2MatchedLadderBlock-v1`、`GenerationInvocationEnvelope`、main/holdout routing、C1/C3 参数、pair-cluster 与 κ=1.5、`max_attempts=5`、C2 候选表、Global K joint-null 等全部不改。rt3_calibration_main_r17/c3_cost/D0/pair52 结构拒绝、R16 C2 matched D3 统计失败、C3 PPO Branch D 三项独立问题保持原状态(完整 fresh rt3 继续 BLOCKED)。本轮无新正式许可/运行/数据;历史误触、接受与终结事实原样保留;未清理任何历史失败 namespace 或 exposure;run_supervision/rejected 拒绝记录按既有规则追加(本轮测试与全量期间共 3 条 rejected_concurrent 为真实记录:02:02:19Z/02:42:09Z/03:07:11Z,均为既有单例测试固定形态)。

## 11. 结论

| 分项 | 结果 |
|---|---|
| WP1 二次错误隔离 | PASS:升级前 flush/观察失败不放弃仍安全可执行的控制(KILL/真实 rc/成员核验继续);持续不可确认时如实有界失败(F04) |
| WP1 共享预算 | PASS:每收尾入口复用同一 deadline;辅助停止与封口消费剩余预算;零剩余不变无期限;无全额续期(B01-B03) |
| WP2 决策边界 | PASS:最后检查后 C 前登记参与本 run 结果(C01-pre);临界区内登记归真 C 后独立回执(C01-in/C02);无伪 C 后兜底(已删除);发布失败仍非成功(C04) |
| 集成与交付 | PASS:专项 16+231 全绿;受监护全量见 §7;原始证据/锚/冷读见 §8 |
| 正式边界 | 保持:无新正式面;历史隔离不变 |

**本轮:R17 冻结前开发候选交付,等待独立审查。**

## 12. 独立验收结论(2026-09-08,验收 agent 只读核查)

**ACCEPT**(A 实现语义/B 测试有效性/C WP0 证据链/D 全量与外层 rc/E 冷读/F 报告如实性/G git 卫生七项全 PASS;复现与闭合探针快照 blob 分别核对为接手 383e573 与交付 9e1a207)。非阻断观察 4 条:(1) rejected.jsonl 计数 2→3(已勘误 §10);(2) P2 闭合 win join 2.776→2.787s 笔误(已勘误 §4);(3) 变更行数 +219→+217(numstat 口径,已勘误 §3;已推送提交消息不改);(4) `_terminal_shutdown`/`finalize` 内 `if prot.pending_logs:` 属性访问未包入 `_shutdown_step`(普通列表属性实际不抛错的理论缝隙,留待后续轮收窄,如实记录)。
