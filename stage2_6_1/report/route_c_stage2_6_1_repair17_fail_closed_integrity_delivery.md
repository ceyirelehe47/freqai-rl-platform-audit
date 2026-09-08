# R17 fail-closed-integrity-delivery 轮主报告

英文标识：R17 Capability Fail-Closed + Integrity Bypass Closure + Full Delivery Revalidation
日期：2026-09-08
仓库：`ceyirelehe47/freqai-rl-platform-audit`，分支 `route-c-stage2-6-1-repair17`
接手 SHA：`029f1ff6d0ec90ec6cebac458431b8326989142f`（parent `6cea807c…`，ancestry 核对通过）
交付 SHA：`{{DELIVERY_SHA}}`
性质：R17 冻结前开发续轮（非 R18；不创建最终 A/B；真实正式许可/formal/新正式业务数据/
qualification exposure 全程禁止；历史已终结正式身份继续隔离）

## 0. 接手核对与执行环境

- HEAD=`029f1ff`、origin 同 SHA；supervisor Git blob `a6e58f95…`、上轮
  stop_publication 测试 blob `0f2c1184…`、上轮 cold_read_sp.sh blob
  `a2077b5d…`（实际路径 `…/stop_publication_sampler_closure/cold_read/
  cold_read_sp.sh`）全部核对吻合；工作树仅历史遗留 CRLF 行尾差异
  （r15 系文件/artifacts 采样件，非本轮修改面，原样保留不触碰）。
- 执行环境：WSL `CryptoRL-Ubuntu-24.04`（F 盘 USB SSD），用户 cryptorl，
  conda `freqtrade-rl`，Python 3.11.16；无遗留重任务；磁盘 / 919G 可用、
  F 1.2T 可用。
- 执行面：`r17_sync.sh` 布局（stage2_6_1/src→`~/projects/crypto_rl/src/
  rl_curriculum`、tests→`~/projects/crypto_rl/tests/route_c_stage2_6_1`、
  runner→`~/projects/crypto_rl/stage2_6_1_runner`），每轮修改后经
  `tr -d '\r' < …/r17_sync.sh | bash` 同步再测试。
- 发布树外依赖登记（任务书 §1.2 要求）：`generator_api.py`
  （sha256 `a403e070…c42`）、`param_resolution.py`（`6eb77911…20d`）、
  `timebase.py`（`a0bcd3e1…7cf`）、`observation_schema.py`（`2c90b881…
  dee`）——存在于执行树顶层 src（2.6.0 遗留布局共享文件），发布树
  `stage2_6_1/src/rl_curriculum/` 不含；本轮不假称干净发布树复现全部
  测试，依赖身份如上登记。证据 verifier（r17_verify_delivery.py）
  不依赖课程生成模块。

## 1. WP0：四项最小真实反例（全部成立）

工具：`tools/counterexamples/probe_fc{1,2,3}*.py`（真实
Supervisor/真实信号/真实线程/真实文件边界；预算值仅测试进程内注入）。

| 反例 | 缺陷 | 旧行为证据 | 归档 |
|---|---|---|---|
| FC-1a | SPSC-01：前提失败无信号仍成功 | 未屏蔽辅助线程在场→`premise_ok=False`→**rc=0**、evidence_complete=True | old_behavior/run_fc1a |
| FC-1b | SPSC-01 排序面：50ms 复核窗口 | 复核窗口内真实 TERM 被保守消费（本次落在窗口内=调度运气，无机制保证） | old_behavior/run_fc1b |
| FC-2 | SPSC-02A：budget_check 活写者旁路 | 真实 budget_check 触发→`guest_sampler=None`、close_state=None、线程存活、evidence_complete=True、**build rc=0+verify rc=0 接受活写者包**、释放后文件 1056→1133B 继续增长 | old_behavior/run_fc2 |
| FC-3 | SPSC-02B：summary 残片抵消 | 真实文件边界写 1 字节 `{` 后 OSError→残片留在最终路径、run_record 登记 present+残片哈希、evidence_complete=True、**verify rc=0 接受残片包** | old_behavior/run_fc3 |
| FC-4 | SPSC-03：交付缺口（只读核对） | 上轮 cold_read 对象=快速 fixture run（src_pkg/run…），full_run/ 仅三件无监护原件，冷读与全量无绑定；verifier 从开发树加载 | wp0_summary.md |

## 2. WP1：能力失效不能成功降级

代码（r17_supervision.py）：

- **删除**前提失败保守复核分支（`time.sleep(0.05)`+复核消费+基线移动
  ——整段物理删除；FC-1b 修复版复跑"定位 time.sleep(0.05) 失败"
  =分支不存在的直接证据，归档 fixed_behavior/run_fix1b）。
- 前提失败（掩码取得失败/线程前提核验失败）→ 登记控制失败事实
  （`_control_failures` 粘性列表），**run 必须非成功**：新增外层码
  **rc=7**（控制能力失效；现有 0/2/3/4/5/6/93/94 语义不变，模块头
  退出码表同步登记）；可以继续安全有界清理与诊断保存。
- **不伪造成功 C**：前提失败时不建立已认证 C（`_cutoff_certified`
  保持 False；C 两赋值只在前提成立分支执行；post_cutoff 回执只在
  C 建立后生成）——停止归属如实记为"无法认证"，已登记信号如实进
  summary/record（sig/consumed 状态），不消费、不追认时序。
- 掩码还原失败不再静默吞（旧 `except: pass`）→ 登记控制失败
  （`cutoff_mask_restore_failed`）。
- 同一事实进全部读取路径：summary.publication.control_failures、
  run_record.control_failures（顶层）、control_outcome→7、
  verifier 第 6 步（control_failures 非空 → FAIL"控制能力失效的
  失败记录，不得按完整运行交付验收"）。
- **控制失败与 evidence_complete 正交**（§4.3 表）：失败经过与文件
  完整固定时 evidence_complete 可为 True（失败证据完整≠运行成功，
  verify 仍拒绝）。
- 前提成立的正常路径不变（c01/c02 组回归通过）；正常成功仍可达。

测试：S03a/S03b 预期按任务书 §4.4 纠正（rc=7+控制失败进记录面+实际
verifier 拒绝+辅助线程不误杀；docstring 注明旧 rc=0 断言被 FC-1a
推翻）；S01a 观察点迁移到前提失败登记行（仍处 sigmask 临界区内），
断言 rc=7+信号如实登记（双分支）+无伪 C 后回执；新增 C02a（线程
查询失败）/C02b（掩码还原失败，含掩码面恢复的测试责任域）/C03
（INT 变体）。

## 3. WP2-A：预算耗尽也必须经过同一写者关闭事实

代码：

- `budget_check()` 只 `stop()` **不清引用**（旧 stop 后立即
  `guest_sampler=None` 删除）——句柄保留，关闭事实由共享收尾
  （finalize join 段）确认；stop 幂等（Event.set），budget+finalize
  双 stop 无副作用。
- 三态生命周期：`_guest_ever_started`（start 时置 True；run 重置面/
  __init__ 同步）——never_started(False)/started_unconfirmed(True 且
  无确认关闭记录)/confirmed_exited(True 且 close_state.joined)。
  **None 引用不再同时代表"没有写者"与"曾有写者、引用丢了"**。
- `_writer_live_for_role("telemetry_guest")`：close_state 记录时消费
  `alive_after_join`；无记录但 ever_started → True（未知=仍可能写）；
  从未启动 → False（replay/零启动不误拒）。`declared:<role>` 前缀
  继承同名角色映射（登记通道不改变写者事实——本轮发现的缝隙）。
- `_evidence_ok` 同源；writers 块：guest=None 仅代表从未启动，
  曾启动无记录记 `{"ever_started": true}`（未知不被 None 掩盖）。
- 现有键名（started/joined/alive_after_join/thread_ident/
  stop_requested）全部保留（w01/w02 系既有断言不破坏）。

测试：W01 完整组合（真实 emit 屏障→emit2 后由采样线程调用真实
budget_check→保护停止→正常收尾→**屏障未释放时**句柄保留/close_state
真实未知/live_writers/evidence_complete=False/实际 build rc=0+verify
rc=1 拒绝→释放后写者退出不回写）；W02c（已启动未知不被 None 掩盖+
verify 拒绝）/W02d（从未启动对照，None 语义唯一）；W03（budget 停止
后 finalize join 段真实执行、无线障时确认退出）。

## 4. WP2-B：必要发布失败不能被"文件存在"覆盖

代码：

- `write_summary()` 原子化：同目录私有临时文件 `.summary.json.tmp`
  完整写入+flush+close → `os.replace` 发布（S3：成功替换=原子可见
  性，不扩大为掉电持久化证明）；**发布目标已有文件=运行唯一性冲突
  →拒绝覆盖**（target_exists 失败面）；失败临时件保留为明确诊断
  残片（私有名，不在 required 角色中冒充成品）。
- 失败粘性：`_summary_publish_failed`/`_summary_publish_failure`
  （阶段+首因）进 `_evidence_ok`（即使最终路径有字节/哈希可算也
  不再完整）与 run_record summary 角色状态
  （`status="publish_failed"`+failure 细节；missing_roles 含 summary）
  ——**残片/旧件不能抵消已知发布失败**；目标非文件仍记 missing
  （两形态区分）。
- verifier（r17_verify_delivery.py）三处扩展：
  build 清单行跳过 `status in (missing, publish_failed, unreadable)`
  （残片不入清单）；verify 第 6 步对 `publish_failed`（必要结果证据
  无效）与 `unreadable`（无哈希身份）显式 FAIL；顶层
  `control_failures` 非空 FAIL（WP1 消费端）。build 的
  missing_roles 自动含新状态（语义=必要角色未有效交付）。

测试：P 矩阵五格——写前失败（t07 目标占位形态）、tmp 1 字节后失败
（P01）、可解析内容写完后 flush 失败（P02a）、tmp 完整但 replace 失败
（P02b）、正常成功（P03 对照，无残留+verify rc=0）。每个负例断言：
最终路径干净/残片只在 tmp、publish_failed、evidence False、rc=6、
**实际 build/verify 拒绝**。P02a 明确"残片内容可解析仍不构成有效
发布"。注入只在真实文件操作边界（Path.open/Path.replace wrapper），
不替换 write_summary 函数体。

## 5. 测试面适配（非生产行为变化）

- **conftest BLAS 线程约束**：pytest 进程内 BLAS/OpenMP 线程池是
  未屏蔽 TERM/INT 的 C 层线程（/proc 可见、threading.enumerate 不可
  见——本轮诊断实锤 8 连号 tid），直调形态 supervisor 的前提核验
  如实失败。生产 supervisor 独立进程不导入 numpy 无此线程面。
  conftest 在 numpy 首次 import 前设 OPENBLAS/OMP/MKL/NUMEXPR_
  NUM_THREADS=1（仅测试进程的第三方数值库行为；不 patch 前提函数、
  不改生产开关；residual/保护/发布语义照常执行）。
- t07（目录占位→publish_failed 语义升级）、t18（不再预置占位
  summary.json——预置=发布目标被占）、S01a 观察点迁移、S03a/b 预期
  纠正（任务书 §4.4 点名）。
- 直调/子进程/监视 run 的 root 基准统一（run_dir.parent.parent 同式
  ——修复本轮发现的差一层误用）。

## 6. 稳定候选受监护全量（E03）

- 入口：`r17_monitored_entry.sh pytest --max-seconds 3600 -- …`（执行
  编排：r17 supervisor 系 11 文件先跑、curriculum 系后跑——curriculum
  生成生态在 pytest 进程内产生 C 层线程池（实测 r12_integration 后
  残留 4 tid，threading.enumerate 不可见），会使**直调形态** supervisor
  run 的截止点前提核验如实失败（rc=7）；生产 supervisor 为独立进程
  不混入此类线程面，排序恢复直调测试的设计前提，断言与测试内容
  零修改、每项测试仍真实执行）。
- 监护 run：`fcid_full_20260908`（run_supervision/runs/ 下原件：
  business stdout/stderr、telemetry 双流、alerts、summary、
  run_record、launch_evidence、junit.xml——junit 经 R17_RUN_DIR
  预指定物理落 run 目录内，必需集合 7 角色全相对路径）。
- 结果：**1524 passed / 7 skipped / 23 warnings / 1696.90s（0 failed
  0 errors）**；JUnit testsuite tests=1531 / failures=0 / errors=0 /
  skipped=7；supervisor 外层 **OUTER_RC=0**（outer_rc.txt 直捕：无管道
  `> file; echo $?` 形态；business rc=0；各层 rc 分列，无 pipeline/
  `|| true` 覆盖）。
- 同 run 绑定：junit=run_record 必需集合内 junit_xml 角色；stdout=
  run 目录 business 原件；entry stdout（R17LOG 通道）→ `full_run/
  entry_stdout.log`；run_record finalized=true、evidence_complete=
  true、control_failures=[]、cutoff_certified=true、三组写者确认。
- **过程事实（如实登记，三轮）**：第一轮字母序全量 1509 passed/
  11 failed/4 errors——失败全部为 rc=7 语义在"进程被 curriculum C
  线程污染"下的直调测试（t16/t17/t18、P 矩阵、l01、w02b、l04、
  cold_copy 4 error），定位到 r12_integration 后残留 4 个 C 层线程
  （pytest.main 同进程实测 NTHREADS 1→5）；r17 系 11 文件单进程
  269 passed 全绿后改执行编排。第二轮业务 argv 包装脚本吞掉
  junitxml 参数（supervisor startup 拒绝/内联展开被 wsl.exe 参数层
  吞）→rc=3 提前退出；过程 run（20260908T125233/131204/134036/
  134238/134330/134712——后两个为启动即止/提前退出的编排试错，
  保留为事实不删除）一并保留。第三轮（本轮稳定候选）如上全绿；
  稳定候选后无生产代码变更。
- 独立验收（subagent）结论：A 代码核对/B 测试抽验/C 交付证据/
  D 报告一致性全 PASS；E 项曾 FAIL（old_behavior 归档在首次拷贝时
  静默失败为空目录），已从执行树原件补齐（run_fc1a/1b/2/3 四份
  含 run 目录全件）并补录 run_fix1b 的 probe stdout（"定位
  time.sleep(0.05) 失败"=保守复核分支物理删除的直接输出证据）。

## 7. WP3：完整交付独立冷读（E01/E02）

- 工具：本轮 `tools/fc_cold_read_pipeline.sh`+`cold_read_isolated_fc.sh`
  +`cold_read_negative_fc.sh`（复用 unified_shutdown_cold_read 的
  `build_cold_copy.py` 原件不改；隔离机制按本轮实际源路径适配：
  **同时遮蔽 /mnt（发行证据根）与 /home/cryptorl/projects（开发项目
  根/执行树）**，不机械只遮 /mnt）。
- 对象：全量 run `fcid_full_20260908` 的已关闭原件固定集合
  （run_record 必需角色+record+manifest+anchor；不从现存文件重建
  清单）；一次性新根（排他创建，不 rm -rf 复用路径）。
- 结果：正例——副本 verifier 只读新根 **verify rc=0**、双原根不可
  访问（mnt_f=no/proj=no）、payload 前后快照不变；
  负例——缺件 N1 **rc=1**（内容错误，不补读原根）、篡改 N2
  **rc=1**（哈希矛盾）、故障包 N3（控制失败 run
  run_fix1a 的副本）**rc=1**（verify 因 control_failures 拒绝，
  明确是失败证据不是完整运行通过）。
- 归档：cold_read/（脚本副本/日志/回执/副本身份）。

## 8. 证据索引

| 证据 | 位置 |
|---|---|
| 反例旧行为（4 run+probe 日志） | artifacts/.../fail_closed_integrity_delivery/tools/counterexamples/old_behavior/ |
| 反例修复后行为（5 run） | …/tools/counterexamples/fixed_behavior/ |
| WP0 总结 | …/tools/counterexamples/wp0_summary.md |
| 新增测试 | tests/route_c_stage2_6_1/test_curriculum261_r17_fail_closed_integrity_unit.py（11 项） |
| 全量原件 | run_supervision/runs/fcid_full_20260908/ |
| 全量导出 | …/fail_closed_integrity_delivery/full_run/（junit/entry_stdout/outer_rc） |
| 冷读 | …/fail_closed_integrity_delivery/cold_read/ |

## 9. 不变项与边界

- 领域合同（Route C 六项/fee/reward/特征/预处理/候选表/Global K/
  formal blocks/机械选择）全部未动；C1/C3 参数、κ=1.5、
  max_attempts=5、C2 matched 口径不变。
- 完整 fresh rt3 继续 BLOCKED（C3 结构拒绝未解除）；R16 C2 统计
  FAIL 原样保留；C3 PPO Branch D 独立开放。
- 历史已终结正式身份继续隔离；本轮零正式面操作（rejected 记录/
  正式前缀无新增）。
- 旧行为只在接手快照副本验证；未删除任何旧 run/失败计划/abort/
  exposure/原始日志；公共拒绝审计无新增（本轮无 formal 误触）。
- 存储与资源纪律：串行单重任务；核心采样/明细间隔、256MiB 遥测
  预算（生产值）、300GiB 上限、失联规则未改。

## 10. 分项结论

| 工作包 | 结论 |
|---|---|
| WP1 能力失效失败关闭 | **PASS**（FC-1a rc=0→7；50ms 分支物理删除；四形态 C02/C03 非成功；正常路径回归通过） |
| WP2-A 预算出口同一关闭事实 | **PASS**（FC-2 verify rc=0→1；三态；W01 组合全链） |
| WP2-B 发布失败不被残片抵消 | **PASS**（FC-3 verify rc=0→1；P 矩阵五格；原子发布+防覆盖） |
| WP3 完整交付独立冷读 | **PASS** |
| 集成回归 | **PASS**（1524 passed / 7 skipped / 23 warnings / 1696.90s(0 failed 0 errors)） |

最终停点：本轮=R17 冻结前开发候选交付，等待独立审查；不进入
R18；不创建最终 Implementation Freeze A / Results B；真实正式许可/
formal/新正式业务数据/qualification exposure 禁止；Stage 2.6.1 尚未
通过。
