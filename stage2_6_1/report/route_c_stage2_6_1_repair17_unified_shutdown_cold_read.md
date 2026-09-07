# R17 统一有界收尾、停止截止点与独立冷读——开发轮报告

**英文标识：** R17 Unified Bounded Shutdown + Stop-Acceptance Cutoff + Detached Evidence Verification
**日期：** 2026-09-07
**性质：** R17 冻结前开发续轮（非 R18；不创建最终 Implementation Freeze A / Results B；无真实正式运行）
**接手 SHA：** `501bf159948da14f951be21a8436323bf2561b53`
**交付 SHA：** `{{DELIVERY_SHA}}`
**独立审查结论引用：** `R17_Read_Failure_Signal_Safety_Independent_Review.md`（RSS-01/02/03）

---

## 0. 摘要

本轮修复三个已核对的缺口并以行为与证据闭合：

| 缺口 | 缺陷形态（接手版实测复现） | 本轮修复 | 翻绿证据 |
|---|---|---|---|
| RSS-01 异常收尾简化 | `main()` crash 分支只 request_stop→finalize→return 3：业务忽略 TERM 时无 KILL、无退出观察、无残留核验；`run()` finally 已恢复 handler，收尾期无保护 | 异常统一收尾进 `run()`（直调=CLI 同保证）：`_handle_fatal_exception`→`_terminal_shutdown` 驱动既有 Protector 到终态（合作窗满升级 KILL、真实 rc 观察、组成员核验、预算尽如实未确认）；handler 由最外层域（main token 嵌套）覆盖收尾全程 | probe rss01：修复前业务+子孙存活/无 KILL/biz_rc=None → 修复后 kill_sent+terminal_confirmed+biz_rc=-9+邻居存活 |
| RSS-02 late-stop 落 rc=0 | 三边界（finalize 开始/drain/结果提交前）信号只写 `external_stop_sig` 字段、未消费、outer rc=0；S05c 固化该行为 | finalize 内四个 C 检查点（①finalize 开始完整链 ②seal 前完整链 ③seal 后结果层消费 ④run_record 后最后判定+发布前候选重写）；C 在 run_record 原子写完成点越过；C 后信号→独立 `post_cutoff_signal.json` 回执 | probe rss02：三边界 rc 0→4（consumed=True、raw rc=0 保留）；s05c/l02a-c/l02d 测试 |
| RSS-03 冷读读原根 | 旧冷读只复制 manifest/anchor（副本零 run 字节）；verify `--root` 仍指原始 full_regression | `build_cold_copy`（固定清单→物理字节逐项复制+哈希核对）+`cold_read_isolated`（unshare user+mount namespace 内 tmpfs 遮蔽 /mnt，原根对验证进程不可访问）+负例（缺件/篡改只在一次性副本） | probe rss03 + 旧 run 补充冷读（隔离 verify rc=0/缺件 1/篡改 1）+C01-C04 |

三件事均先在接手快照（`~/r17u_snap_handover`，md5 `abac56f2` 与发布树一致）上建立真实反例（REPRODUCED），修复后翻绿（NOT_REPRODUCED）；未重写上轮已修好的 reader/writer/资格治理。

## 1. 接手现场（WP0）

- HEAD=`501bf15`、parent=`4a3c6a8`、远端同 SHA 无新提交、工作树干净；supervisor blob `b03afa20`、旧交付脚本 blob `305199a2` 与任务书 [R3][R4] 一致。
- 开发树同步（r17_sync：src/tests/runner 三面）；无存活登记任务；formal 目录只读确认为空（历史终结身份隔离保持，本轮零触碰）；F 盘可用 ~1.2T（300GiB 门槛余量充足）。
- 快照与反例的 import 来源：三个 probe 均 `sys.path` 指向接手冻结快照（见 `probes/results/wp0_snapshot.json`）。
- 上轮 `final_20260907T140907`（1469/7/0）仅作历史引用，不复用为本轮验收计数。

## 2. 三个真实反例（先证后修）

probe 脚本与结果 JSON 在 `artifacts/repair17/development/unified_shutdown_cold_read/probes/`：

| probe | 注入 | 接手版结果（REPRODUCED） | 修复后 |
|---|---|---|---|
| `probe_rss01_exception_shutdown.py` | 真实 main() 入口；业务装 SIG_IGN+真实子孙，READY 文件证明先于异常注入；pump 注入主循环异常；R17ALERT 通道持续阻塞；独立邻居 | main rc=3 返回时业务 leader+子孙存活、term_sent=true、kill_sent=false、biz_rc=None、terminal_confirmed=false；邻居存活（`rss01_result.json`） | kill_sent=true、terminal_confirmed=true、biz_rc=-9、业务组清零、邻居存活、无 watchdog 兜底（`rss01_fixed_result.json`） |
| `probe_rss02_late_stop.py` | 三个明确事件屏障（`finalize` 进入/seal 后 drain/`write_summary` 前）向自身发真实 TERM；业务 sleep 1 自然 rc=0 | 三边界全部 run_rc=0、sig=15 已登记、consumed=false（`rss02_result.json`） | 三边界 run_rc=4、consumed=true、raw rc=0 保留（`rss02_fixed_result.json`；含检查点④对"③与发布完成之间空窗"的关闭——pre_summary 屏障首轮曾漏，补④后翻绿） |
| `probe_rss03_cold_read.py` | 照旧脚本方式建冷副本（只复制 manifest+anchor）；verify A 传原始 full_regression、verify B 传副本 payload 根 | A rc=0（验收事实上读原根）+副本零 run 文件+B rc=1（`rss03_result.json`） | 由 WP3 工具链替代（见 §5） |

## 3. WP1 统一有界收尾

**一个责任主体，复用既有 Protector**（`r17_supervision.py`）：

- `run()` 重构：`try: _run_body() except Exception: _handle_fatal_exception(exc); return 3`——**直接调用 run() 与 CLI main() 获得同一任务清理保证**（任务书 §4.1）；`finally` 记录 C 后回执并恢复 handler。
- `_handle_fatal_exception`：crash 事实记录（log+emergency）→ 通知入队（异步，不阻塞保护）→ `_terminal_shutdown`；每段独立 try/except，第二失败记录不丢原失败、不递归再入收尾（§4.5）。
- `_terminal_shutdown(reason)`：保留首个失败（不重跑刚抛错的采样/策略/报告逻辑）；按已有身份范围 request_stop（幂等）；循环（0.2s 节拍）驱动 `protector.poll`（合作窗满自动升级 KILL——与主循环同一 Protector 规则）+`_observe_business_exit`（真实 rc）；`_terminal_state_confirmed`=**直接业务 rc 已取得 且 登记组无活成员**（leader 已退/TERM 已发/单次扫描空，任何单项不单独替代）；共享预算 `policy.finalize_window_s=120s`（自进入终止处理起算，不因重复异常/信号重开）；预算尽→`residual_unconfirmed` 如实保留+emergency 记录（不写成安全完成、不填 raw rc=0）。finally 分段兜底（flush_logs/finalize 各自独立 try）。
- handler 生命周期：`_install_signal_handlers`/`_restore_signal_handlers` 可重入 token（嵌套链正确）；main() 持最外层 token 覆盖 run 内部安装、异常统一收尾与 finalize 全程（修复"run() finally 先恢复 handler、main() 收尾期裸奔"）。
- main() 简化为最后防线（`supervisor_outer_crash` emergency+return 3）。

**U02 实测**（真实 coop=30s 身份保留）：忽略 TERM 业务+READY 证明+通知持续阻塞+真实子孙+邻居——supervisor 自己 KILL、确认退出（biz_rc=-9）、邻居存活、watchdog 零参与；t14b 证明 crash 路径同样驱动真实工程链（取消/撤权/terminal/哨兵零启动/二次准入拒）。

## 4. WP2 停止接受截止点 C

**三个边界分开**：业务 raw rc（`_observe_business_exit` 固定）/ writer seal（原始流关闭）/ run 取消接受截止点 C（新）。

C 的位置与前置：`finalize()` 内 `write_summary→finalize_run_record`（.replace 原子写完成）之后；此前任务树核验/producer 停止/seal+drain/原始证据固定已按序成立。四个检查点：

| 检查点 | 位置 | 动作 |
|---|---|---|
| ① | finalize 开始（原始流可写） | `_consume_external_stop()` 完整链（log+handle_triggers） |
| ② | seal 前（最后可写位置） | 同① |
| ③ | seal 后、write_summary 前 | `_consume_external_stop_sealed()` 结果层消费（不重开原始流；§5.3 收尾元数据承载） |
| ④ | run_record 完成后、C 紧前 | ③→发布完成期间到达的信号：消费+**发布前候选重写**（§5.2"候选可在发布前废弃"；哈希以最终件为准） |

空窗论证：④与 C 之间为纯属性赋值（无字节码级可插入屏障）；`_sig_external` 增加纯自增计数 `_external_stop_sig_count`，C 设点记录 `count_at_cutoff`——C 后新到（count>at_cutoff）由 `_record_post_cutoff_signal` 写独立回执 `post_cutoff_signal.json`（不改任何已哈希固定原件；含防御兜底分支）。确定性交错由 l02a-d 测试证明（事件屏障=实际方法边界，非 stdout 次数）。

**行为表落实**：业务未启动（u06：零 spawn+不伪造日志）；活跃/后代活跃（u04a：residual 实际清理 rc=4）；raw rc=0+C 前（l01/s05c：raw 保留+outer 4）；drain 中（l02b：handler 只登记+检查点消费，不重入 finalize 不解封）；候选准备（l02c：④捕获重写）；C 后（l02d：post_cutoff 回执+结果不变）；发布失败（l03：整体失败 rc!=0，不补造文件）。

## 5. WP3 真正独立冷读

工具（`tools/`，新交付目录；旧脚本/旧清单/旧回执原样保留）：

- **`build_cold_copy.py`**：从已固定 manifest/anchor 读必要集合（不扫描现存文件）；逐项**物理字节复制**（拒软链接）到 `<dest>/payload/<相对路径>`；复制即校验（重算 sha256 对清单行）；metadata（清单+锚原样）/verifier（绑定代码副本+sha）/copy_manifest（来源声明=历史 argv 身份、计数、verify argv 提示）。
- **`cold_read_isolated.sh`**：`unshare --user --map-root-user --mount` 内 `mount -t tmpfs tmpfs /mnt`——原开发证据根（/mnt/f）对验证进程**完全不可访问**（不动真实目录；namespace 私有）；verify 全部读取位置（root/manifest/anchor/run-record）只指新根；验证前后 payload 全树（mtime_ns,size,sha256）快照必须不变（只读性）；回执记录隔离事实/argv/cwd；verify 回执与隔离事实先落副本内（namespace 内 /mnt 不可达）再由外层搬运。
- **`cold_read_negative.sh`**：C03 缺件（原根仍有该文件）/C04 篡改一字节——均在一次性副本；隔离 verify 必须失败（无回退/无重算/无重建清单）。
- **旧脚本定位**：`read_failure_closure` 的 verify/冷读如实保留并说明为"原根复验"；本轮 `run_supplement_cold_read.sh` 对 `final_20260907T140907` 补交独立冷读（注明实际验证日期与代码身份）——8 文件 867438 字节复制、隔离 verify rc=0（原根不可见+8 行 0 问题+只读不变）、缺件 1/篡改 1，归档 `cold_copies/r17u_supplement_final_140907`+`receipts/r17u_supplement_final_140907`。
- 篡改反例不再修改原始运行文件（旧脚本的"改后恢复"做法不延续）。

## 6. 验收矩阵映射

| 编号 | 覆盖 | 结果 |
|---|---|---|
| U01 | `test_s06a`（强化断言：terminal_confirmed+biz_rc=-15） | PASS |
| U02 | `test_u02_...`（真实 coop 身份+READY+阻塞+子孙+邻居） | PASS |
| U03 | `test_u03a`（收尾窗口第二信号同链）+`test_u03b`（第二异常分段继续） | PASS |
| U04 | `test_u04a`（leader 退子孙活实际清理）+`test_u04b`（身份不明未确认+非零+evidence 不完整） | PASS |
| U05 | `test_t14`（保护停止形态+哨兵零启动断言）+`test_t14b`（crash 形态真实工程链：grant→取消→撤权→terminal→哨兵零启动→二次准入拒） | PASS |
| U06 | `test_u06`（pre-spawn 零启动+不伪造原始日志） | PASS |
| L01 | `test_s05c`（重写：C 前停止 raw=0/outer=4/consumed=True） | PASS |
| L02 | `test_l02a/b/c`（三屏障）+`test_l02d`（finalize 返回后=C 后） | PASS |
| L03 | `test_l02d`（C 后回执+成功件完整）+`test_l03`（发布失败整体失败） | PASS |
| L04 | `test_l04`（成功/拒绝/异常/收尾失败四出口恢复+重复调用不残留） | PASS |
| C01 | `test_c01`（固定清单→完整 payload 字节逐项一致） | PASS |
| C02 | `test_c02`（unshare 隔离+原根不可见+verify rc0+只读不变） | PASS |
| C03 | `test_c03`（缺件隔离失败；失败原因核实=缺失检出非脚本崩溃） | PASS |
| C04 | `test_c04`（篡改检出+正副本字节不变） | PASS |
| E01 | 既有 reader/writer/资格回归全保留（专项 177 含 r01-r05/s01-s06/rsa/a 系） | PASS |
| E02 | 受监护全量（1486/7/0，外层 rc=0，evidence_complete=true）+独立冷读（隔离 rc=0/负例全检出） | PASS |

## 7. 数据

### 7.1 专项（2026-09-07）

`run_focus.sh`：6 个 R17 测试文件串行 = **177 passed**（read_signal 15 / unified_shutdown 12 / cold_copy 4 / result_seal+supervision+control_path 146，含 t14/t14b）。

### 7.2 受监护全量

`run_full_regression.sh`（R17_RUN_DIR 预指定；freqtrade-rl 解释器；monitored_entry 监护；只建父目录）：

- run：`runs/final_20260907T163430`（2026-09-07T16:34:32Z→16:58:06Z，约 23.6 分钟）
- stdout 原文（business/stdout.log 尾部）：**1486 passed, 7 skipped, 23 warnings in 1408.57s**
- JUnit 汇总：1493 tests / 0 failures / 0 errors / 7 skipped（1476 基线+12 U/L+4 C+1 t14b=1493 精确吻合；本轮计数不复用上轮 1469）
- summary：business rc=0；io 18 accepted/18 ok/0 failed/queued 0/in_flight 0/dropped_critical 0/io_stuck false；external_stop_sig=null（sig_count=0）；residual_unconfirmed=false；coverage win_read_failures=6（last_op=stat，启动文件尚未创建的瞬时失败形态，与上轮同款；非运行中失联）、telemetry_capped=false、win/guest last_mono≈1411.9/1413.3（覆盖至结束）
- run_record：finalized=true、evidence_complete=true、missing_roles=[]（7 角色 + manifest 的 record 行=8 行清单）
- 外层 rc=0 证据链：wsl.exe 整链 exit 0（脚本 `set -euo pipefail` 语义下 monitored_entry 非 0 会使链非 0）+ supervisor summary rc=0 + evidence_complete=true

### 7.3 独立冷读与资源复算

**本轮 run 交付冷读**（`delivery_closure/`+`receipts/final_20260907T163430/`+`cold_copies/`，`finalize_delivery.sh` 8 步）：

- 资源复算（已关闭流重算，与 summary peaks 交叉一致）：guest MemAvailable 最低 **34.042GiB**、任务树 RSS 同刻求和峰值 **5.925GiB**（诊断口径非去重）、win 最低可用 **28.628GiB**、win commit 峰值 **60.32%**、采样器自身 RSS 24.9MB
- build 固定清单+锚：8 行（telemetry_guest/telemetry_win/alerts/business_stdout/business_stderr/summary/junit_xml/record）
- 原根复验（构建自校验，如实标注非独立冷读）：rc=0、8 行 0 问题
- 冷读副本：8 文件 **902976 字节**物理复制+逐项哈希核对
- **独立冷读**：unshare user+mount namespace 内 tmpfs 遮蔽 /mnt → 原根不可见（original_root_visible="no"）→ verify 只读新根 rc=0（8 行 0 问题）→ payload 前后全树快照不变（只读性）→ 回执 rc=0
- 负例（一次性副本）：C03 缺件隔离 verify rc=1（失败原因核实=「缺失: …/alerts.jsonl」检出，非脚本崩溃）；C04 篡改一字节隔离 verify rc=1；正副本与原件字节不变
- 篡改检出专项（finalize 第 7 步）：冷副本上改 1 字节 → 隔离 verify rc=1（原件未动）

**旧 run 补充冷读**（§6.5 授权；`run_supplement_cold_read.sh`）：对上轮 `final_20260907T140907` 补交独立冷读——8 文件 867438 字节、隔离 verify rc=0（原根不可见+8 行 0 问题+只读不变）、缺件 1/篡改 1；归档 `cold_copies/r17u_supplement_final_140907`+`receipts/r17u_supplement_final_140907`；实际验证日期 2026-09-07、verifier 代码哈希见 copy_manifest.json。旧 `read_failure_closure` 的 verify/冷读原件原样保留（其原根复验定位如实说明，不改写）。

### 7.4 证据等级披露

- 本轮 probe/测试的注入仅作用于测试自有文件、进程与隔离工程状态；生产入口无注入通道（t14b 的 crash 注入经测试 wrapper，非生产参数）。
- `test_u04b`/部分探针使用缩短工程预算（`finalize_window_s=4` 等，用例内标注）；至少一个组合测试（u02）保留真实策略身份（coop=30s+KILL 升级实测）。
- WSL unshare 隔离为进程级（user+mount namespace+tmpfs 遮蔽 /mnt）；不影响宿主文件系统；副本置于家目录（/mnt 之外）以保证隔离时可达。
- 全量计数为本轮实测，不复用上轮 1469。

## 8. 交付锚

```text
stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/
  probes/                3 反例 probe+结果(接手版 REPRODUCED/修复版翻绿)+wp0 快照
  tools/                 build_cold_copy/cold_read_isolated/cold_read_negative/
                         run_supplement_cold_read/finalize_delivery/register_anchor/
                         run_focus/run_full_regression/recompute_resources/inspect_receipts/verify_c03_repro
  runs/                  本轮受监护全量 run(final_*)
  cold_copies/           r17u_supplement_final_140907(旧 run 补充冷读)+本轮 run 副本
  receipts/              隔离冷读/负例/篡改回执(独立于封口原件)
  delivery_closure/      manifest/anchor/资源复算/verify 回执(本轮 run)
stage2_6_1/report/route_c_stage2_6_1_repair17_unified_shutdown_cold_read.md
```

旧 `read_failure_signal_safety/`、`read_failure_closure/`、更早 RSA 包与失败 run 原样保留；未编辑旧回执的 root/日期/rc。

## 9. 领域与正式边界（未改变）

Route C 六项环境合同、fee/reward/action/execution/ledger、八个生产特征与 position slot、`RouteCFeaturePreprocessing-v2`、`PolicyVisibleReferenceCanonicalization-v1`、`PolicyVisibleSupervisedLabel-v1`、`C2MatchedLadderBlock-v1`、`GenerationInvocationEnvelope`、main/holdout routing、C1/C3 参数、pair-cluster 与 κ=1.5、C2 三组候选与 formal matched 10/15/20、Global K joint-null 等全部不动。

| 既有问题 | 本轮状态 |
|---|---|
| rt3_calibration_main_r17 / c3_cost / D0 / pair52 结构拒绝 | 不增 attempts/不跳坐标/不换 namespace；完整 fresh rt3 继续 BLOCKED |
| R16 C2 matched main D3 统计失败 | 保留原数值与 FAIL |
| C3 PPO Branch D | 独立学习问题；本轮无 PPO 优化、不宣布 2.6.2 PASS |
| 历史已终结正式身份 | 继续隔离；本轮无新正式许可/活动/业务数据/qualification exposure |

## 10. 停点

```text
本轮：R17 冻结前开发候选交付，等待独立审查
最终 Implementation Freeze A / Results B：本轮不创建
正式许可与真实正式运行：本轮不产生
历史已终结正式部署身份：继续隔离，不恢复机会
新增正式业务数据 / 正式 qualification exposure：本轮禁止
完整 fresh rt3：原 C3 结构拒绝未解除，继续 BLOCKED
历史正向素材：依既有来源完整性判断，不补造
Stage 2.6.1：尚未通过
Stage 2.6.2：不变，C3 PPO Branch D 独立开放
```
