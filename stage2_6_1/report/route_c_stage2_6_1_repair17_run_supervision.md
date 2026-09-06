# R17 运行监护与 Agent 告警——实现交付报告

**日期**：2026-09-06/07  
**性质**：R17 冻结前开发任务（运行监护接入 + Agent 告警 + 保护性中止 + 交付验证器修复 + C3 固定坐标诊断）。**不是 R18，不是正式 qualification 授权。**  
**接手开发 SHA**：`422df1c2bdda376272204d01dc152bf8c2ee156d`（parent `cd2fa3a6…`，远端一致，工作树干净——阶段 A 核验）  
**分支**：`route-c-stage2-6-1-repair17`

---

## 0. 分项结论（§16 判定标准逐项）

| 分项 | 状态 | 一句话依据 |
|---|---|---|
| 自动监护能力 | **PASS** | 监护入口自动启动/收尾在真实负载（全量 pytest/C3 诊断）验证；测量身份（页大小/starttime 实例/cgroup）与预算落地 |
| Agent 告警递交 | **PASS（模式 B）** | 有界工具等待（TaskOutput 15s）端到端真实验证；离线回放/去重语义正确；模式如实声明为周期接收非即时推送 |
| 保护执行 | **PASS** | CRITICAL 无 Agent 回复 1 秒内 SIGTERM 停止登记任务组（真实进程 rc=-15）；合作窗/升级/残留路径有界；无权限越界 |
| 交付验证 | **PASS** | build/verify 彻底分离+外部双锚（manifest/run_record sha256+可选 git blob id）；验证前删件/篡改/删清单行/改哈希/空清单/越界全部非零检出 |
| C3 固定坐标诊断 | **完成（结论=原合同允许的结构拒绝）** | 确定性重放逐字段一致+生成器源哈希匹配+解析 DP 单表零 distractor 概率 21.15%、五连零 1/2361 |
| 完整 R17 工程链 | **BLOCKED（不变）** | 固定 recipe 坐标 rt3_calibration_main_r17/c3_cost/D0/p52 在原合同内五连拒；不构成改 namespace/阈值/attempts 的授权 |
| R17 最终 A / Results B / 正式链 | **未创建/未启动（见 §1.3 误触发记录）** | — |

---

## 1. 身份与范围

### 1.1 实际交付物（新增/修改，全部 LF；.sh/.py 经 r17_sync.sh 同步入 WSL）

新增：`stage2_6_1/runner/r17_supervision.py`（监护核心：策略引擎 R17-SUPERVISION-POLICY-v1/incident 去重升级恢复/递交/保护/预算/收尾/run_record）、`r17_guest_sampler.py`（guest 采样：页大小 sysconf/starttime 实例身份/CPU 累计/IO/PSS 低频/cgroup 链解析）、`r17_win_sampler.ps1`（Windows 采样：GetPerformanceInfo SIZE_T 口径/关键卷空间+身份+可写探测/C 盘应急/MaxSeconds 必填）、`r17_verify_delivery.py`（交付验证器 build/verify 分离）、`r17_monitored_entry.sh`（受监护统一入口：flock 单例/排他 run 目录/env 零注入）、`r17_c3_p52_diagnosis.py`（WP7 诊断：envelope 只读+解析 DP+一次最小复现）；测试 `test_curriculum261_r17_supervision_unit.py`（35 项）。

修改：`r17_entry_common.sh`（追加 `r17_monitored_bootstrap/teardown`——formal 观测型接线）、`r17_formal_chain.sh`（state root 绑定后接线 `if ! …; then emit_launch …` 结构 + EXIT trap + `R17_ART_ROOT` 测试重定向支持；chain-run 调用与重定向行字节不动）、governance 测试 SHELLS 增补。

### 1.2 环境实测（阶段 A）

WSL 2.7.12/内核 6.18.33.2-2；MemTotal 41073264 kB(≈39.2GiB)/12 CPU/swap 8388608 kB；vendor 52bc96f；C 盘 101.5GiB 空闲（LOCALAPPDATA 在 C=应急保存独立故障域）；F 盘 1165GiB 空闲；WSL 根卷 used 38GiB（300GiB 上限口径：df -BK used KiB→GiB）。

### 1.3 正式面状态（含一次开发期误触发的如实记录）

- 最终 Implementation Freeze Commit A：未创建。正式 Results Commit B：未创建。正式 qualification exposure：未新增。R16 及更早永久 FAIL 不变。
- **误触发记录（不删除、不改写，按任务书 §1"不用删 marker 恢复假定的 NOT_STARTED"）**：本轮 D5 测试首版经真实 `r17_formal_chain.sh` 假 SHA 路径三次运行（2026-09-06T16:00:45Z/16:01:11Z/16:01:45Z，请求目录 `r17_formal_requests/20260906T160045Z_18312` 等），真实建立了 execgov 准入会话并写入部署状态根（`state/r17_execution_journal.jsonl`、`r17_bootstrap_accepted.json`、`r17_iteration_aborted.json`、abort_request 证据、顶层 `r17_workflow_plan_formal.json`/`r17_chain_result.json`——均 freeze_sha=40×0）。**每次均在第一步 provenance-verify 即失败（rc=2 前置产物缺失），零正式数据访问、零资格授权**；阶段 A 核验时该状态根为空，故无历史覆盖；三次请求三个独立目录（E1 请求隔离有效）。已修正 D5 测试以 `R17_STATE_ROOT`+`R17_ART_ROOT` 隔离（修正版通过，真实部署状态根字节不变），并据此给 formal_chain 增加 ART 测试重定向。正式链结论仍为 NOT_STARTED（无任何正式数据消费），但"零正式链请求"不再成立——以上述三份假 SHA 拒绝记录为准。

---

## 2. 自动监护能力（WP1/WP2/WP3）

### 2.1 接入面与生命周期

真实接入入口：`r17_monitored_entry.sh <kind> -- <cmd>`（pytest/rehearsal/c3diag/engineering/fixture；formal 拒绝——formal 走自身观测型接线避免双重监护）。生命周期：LF 自检→存储天花板→conda 激活→解释器验证→flock 单例（被拒者只写 `run_supervision/rejected/`，不触碰 execgov 证据区）→run 目录排他创建（`mkdir` 拒绝碰撞；RUN_ID=UTC 纳秒+PID，不进业务 RNG/namespace/env）→自动启动 Windows 采样器（interop powershell，`wslpath -w` 路径转换，双 PID 登记：interop/Windows）+ guest 采样线程→业务 spawn（独立进程组，stdout/stderr 直连文件无 PIPE，env 原样传递）→判定/递交/保护→有限收尾（停采样器按登记 PID→summary→run_record finalize 原子写）。

正式入口为**观测型**接线（`r17_monitored_bootstrap` 仅启动宿主采样器并登记，EXIT trap teardown）：判定/保护不作用于 formal 业务编排（其进程非监护启动，无登记进程组）——边界如实声明，M26 报告如实呈现。

### 2.2 三层测量与身份修正

| 层 | 实现 | 修正点 |
|---|---|---|
| Windows | GetPerformanceInfo（P/Invoke psapi；**cb=DWORD+其余 SIZE_T** 结构修正——初版全 DWORD 致 err=24 BAD_LENGTH）；关键卷空间+VolumeSerialNumber 身份核对+低频 1KB 可写探测 | 弃用语义不明的 CIM 虚拟内存字段；卷身份=预登记序列号（盘符可见≠卷正确） |
| Guest | /proc meminfo 全键/PSI(memory,cpu,io)/vmstat pswp；任务树=pgid 主口径（重托管稳定）+根 PID 后代 | 页大小 sysconf；starttime 实例身份（PID 复用不拼速率）；CPU 累计 jiffies；/proc/io 权限边界=unavailable 不填零；PSS 低频 smaps_rollup；cgroup 沿祖先链（not_limited=不适用非报错） |
| 任务树 | 逐进程 state/threads/rss/pss/cpu 累计与增量/io 增量/复用标记 | RSS 求和不冒充去重物理内存；峰值按同时刻记录不跨阶段混加 |
| 监护自身 | 每样本自记 RSS/CPU%/采样耗时/输出字节/parse_errors/coverage_gaps | 预算 256MiB/run，80% 降明细，超限采样停写保留前缀（alerts 继续，失联判定切心跳并如实标注） |

实测量级：supervisor 常驻 RSS≈14-18MiB（远低于 256MiB 目标）；win 采样器 WS≈98MiB（PS 5.1 基线）；采样耗时 guest≈30-80ms/次；全程零预算触发、零 parse_errors、零 coverage_gaps（见各 run summary）。

### 2.3 固定策略（运行前登记内容哈希；工程保护值非统计 gate）

`R17-SUPERVISION-POLICY-v1` 按任务书 §7 全表实现：win 物理内存 8/30s→W、4/15s×3 样本→C；commit 90%/30s→W、95%/15s×3→C；guest MemAvailable 4/30s→W、2/15s×3 且（同实例 pswpout 增量或 memory.full.avg10≥1%）→C，**PSI/换出同时失联=PROTECTION_UNAVAILABLE（不放行）**；cgroup 新增 oom/oom_kill→C、≥90%→W；存储 300GiB 上限 90%→W/达限→C；关键卷 <20GiB→W、<5GiB 或可写探测失败→C；观测失联 15s→W/30s→C；worker rc≠0/stderr 结构失败模式→WORKER 事件（与资源事件分类不混淆）；progress_stall 600s→仅 W（不推断死锁）；恢复迟滞（win≥10GiB+commit<85%+guest≥6GiB 保持 30s）只关 W 级 incident；CRITICAL 停止粘性。误报防护（M04）：CPU 满载/缓存高/磁盘忙/无 stdout 单现象不触发；持续窗要求有效样本计数，无数据不凑持续时间。

### 2.4 真实负载下发现并修复的监护缺陷（全部有对应回归测试）

1. `GuestSampler._stop` 属性遮蔽 `threading.Thread._stop` 方法（join 崩溃）→ 改名 `_stop_event`。
2. GetPerformanceInfo 结构字段为 SIZE_T（x64 8 字节）非 DWORD → err=24，全指针化+`.ToInt64()` 算术。
3. 卷匹配串冒号拼接错误（`"C:"+":"`="C::" 永不匹配）→ 直接 `DeviceID -eq $v`。
4. ps1 缺省路径指向 WSL 本地（.ps1 不入 r17_sync 同步面）→ 缺省改发布仓库 /mnt/f 路径+存在性检查。
5. replay 模式 join 未启动线程崩溃 → `is_alive()` 守卫。
6. **观测新鲜度竞态取模缺陷（真实全量回归暴露）**：主循环 mono 与 guest 线程 `last_guest_mono` 竞态产生微负差，`% 60` 把 -0.02 翻成 59.98 → 伪 CRITICAL → 全量 pytest 被保护性误停（rc=-15，事件链完整保留）。修复=`max(0.0, …)` clamp + 宽限期不用取模（`mono<60 → stale=None`）。该事故本身即"保护不依赖 Agent 回复"与"事件级摘要递交"的一次真实端到端演示（我在 TaskOutput 中收到该 CRITICAL 的完整事件）。
7. **可写探测位置错误（第二次全量回归暴露）**：探测写 `C:\` 卷根，非管理员进程无写权 → `writable:false` 伪 CRITICAL 再次停掉 pytest。修复=探测目标改为**必要证据实际位置**（遥测输出目录=OutFile 同目录；应急目录=EmergencyDir），语义从"卷可写"修正为"必要证据可写"；应急目录探测失败单独降级为 WARNING（独立故障域降级而核心遥测仍在）。
8. **任务树跟踪未联动（第二次全量回归期间发现）**：采样器在业务 spawn 前创建，登记进程组（pgid）从未注入 → 任务树测量空转（task_count=None）。修复=spawn 后注入 pgid+根 PID；不影响核心资源判定（该轮回归正常跑完）。修复后验证 run 确认 task_count=2、tree_rss 跟踪正常。
9. **finalize 顺序合同缺陷（交付打包阶段暴露）**：`supervisor_end` 日志在 run_record 哈希计算之后追加写 alerts.jsonl → 清单记录与文件矛盾（build 正确拒绝——验证器防线起效）。修复=全部 alerts 写入先于 run_record 哈希计算（顺序合同写入代码注释）。

---

## 3. Agent 告警递交（WP0/WP4）

### 3.1 宿主能力（WP0，已核实）

宿主=ZCode（Windows 侧）；核实能力：Bash `run_in_background` 返回稳定 task handle 且**任务退出时原生 re-invoke Agent**（仅覆盖退出事件）；`TaskOutput(block=true, timeout≤600000)` 有界等待取回输出+状态；无运行中任意时刻消息注入。⇒ **模式 B（有界工具等待/周期接收）**为主通道（默认 15s 周期），任务退出原生通知为附带边界事件。Agent 与 WSL 相互独立（WSL 崩溃时 Agent 存活可读 C 盘应急记录；会话结束时任务与事件保留）。

### 3.2 递交语义

supervisor stdout=宿主持久化任务输出文件（TaskOutput 读同一文件，全量返回）=递交面；每事件单行 `R17ALERT {json}`（事件级可行动摘要：run 身份/严重度/原因/指标/阈值/持续时间/已执行动作/证据位置），同时持久化 per-run spool `alerts/alerts.jsonl`。至少一次递交+消费端按 incident_id 去重；无活跃等待者时事件保留（stdout 文件+spool），重连回放=TaskOutput 全量返回；不声称 exactly-once，不声称"模型已处理"——只报告传输/工具展示层证据。递交身份：incident 去重（同因持续=单 incident，first/last/peak/持续时间），升级/恢复单独递交，重复提醒≥60s，异因 CRITICAL 不被 W 冷却吞掉。

### 3.3 真实会话接收证据（M07/M08，本会话内）

- **M07 真实接收**：2026-09-06T15:43:04Z 后台启动受监护 fixture 任务（样本注入模拟 keyvol WARNING），`TaskOutput(block=true, timeout=15000)` 真实返回 `R17ALERT {"action":"open","severity":"WARNING","incident_id":"m07_154304_299-keyvol-0","detail":"关键卷 F: 可用 18.0GiB < 20.0GiB",…}`。触发→保存（spool emitted 15:43:05Z）→递交（stdout 写同秒）→工具呈现（本会话 TaskOutput 结果）→**Agent 确认**：本会话确认收到该 incident，按策略语义处置为"任务继续、不新增重任务、无需控制动作"——确认与工具结果一并存档于 `receipts/` 与本报告。
- **M08 离线/回放**：M10 全程（告警产生于我无活跃等待期间）事件完整保留于任务输出文件与 spool；任务完成时宿主原生 re-invoke（task-notification），后续 Read/TaskOutput 全量回放旧事件且按 run_id/隔离目录不串新 run。
- 延迟实测：规则确立→本地保存/递交尝试 <1 个核心采样周期（同秒）；递交→工具呈现取决于等待周期发起时刻（本例约 5-10s，≤15s 周期上限）；符合模式 B 诚实声明（周期接收非即时推送）。

---

## 4. 自动保护（WP5）

- **告警与控制分离**：判定/停止全部本地确定性代码执行；CRITICAL 递交与停止请求同时发出，不等待模型回复。
- **M10 真实保护**（两次：会话级+测试级）：注入 keyvol CRITICAL（F: 3.0GiB<5GiB）→ `stop_requested`→`sigterm_sent`→业务 sleep 90 于 **1 秒内**被 SIGTERM（rc=-15）→`task_tree_gone`→收尾。事件链（alerts.jsonl）逐事件完整。
- 合作退出窗 30s→SIGKILL 升级（仅登记 pgid；M11 夹具验证）；kill 无效（不可中断 IO）→如实记录 survivors+"停止已请求、完成未证实"，不宣称 SIGKILL 必成。
- 停止只作用于登记进程组；不按名杀；不杀用户进程；伪造旧 marker/过期 PID 无效（按 pgid+实例）。supervisor 自身被停（M12）→收尾路径停业务，无残留、无伪终态。
- 粘性：CRITICAL 停止不因指标恢复自动取消；资源中止不改写业务 verdict（worker rc≠0=WORKER 事件独立分类）。

---

## 5. 业务与旧问题

### 5.1 C3 固定坐标诊断（WP7；结论=原合同允许的结构拒绝）

- 证据：run `20260906T134324Z_1475` 五次 attempt envelope——A/B **共享事件表**（`pair_variant` 不入 seed 派生，envelope 内 A/B n_signals 恒等可证）全部 `n_distractors=0`；五次 outer_seed 相互独立。
- **一次最小复现**（受监护工程运行 `runs/20260906T160935_1193_24448`，同 namespace/family/rung/pair_index/参数/5-attempt 上限）：`PairGenerationError` 再现，重放 envelope 与原 envelope **逐字段一致**（outer_seed/internal_derived_seed/digest/episode_content_hash/A.counts 全匹配）；生成器源 sha256 与 envelope 登记（77374242…）一致。
- **解析 DP**（纯数学，不调生成器）：对调度循环精确建模（t∈[10,280)，P(cue)=0.2/P(dis)=0.015/空 bar 0.785；pair 推进 gap+4∈{8,9,10} 均匀）——单事件表零 distractor 概率 **0.2115**，五连零 **4.24e-4（≈1/2361）**。这修正了上一轮"五连零≈1e-10"的量级误判（当时高估迭代数约一倍）。结论与 R16 rt2 同规模全绿自洽：rt2 D0 约 60 pair 撞上至少一个五连零的概率约 2.5%，通过属正常。
- 判定：`CONTRACT_LEGAL_STRUCTURAL_REJECTION`——C3_MIN_DISTRACTORS=1 结构合同在 D0 参数（distractor_rate=0.015）下的合同内小概率拒绝；非调用缺陷（重放一致+源哈希一致+参数/override 链与 envelope 记录一致）。**维持完整工程链 BLOCKED**；不构成改 attempts/跳 pair/改阈值/换 namespace 的授权。若未来需解锁：需独立授权的生成合同变更（如 D0 distractor_rate 调整）或工程 namespace 生成层预筛——均超出本轮范围，仅作建议记录。
- 诊断产物：`run_supervision/wp7_c3_p52_diagnosis.json`（受监护 run 的 business 产物）。

### 5.2 原统计结论未改

R16 C2 matched main D3 原值与 FAIL 判定保留；C1/C3 参数、κ=1.5、pair-cluster 口径、Global K 合同、17 步 authoritative workflow、六项环境合同、八特征、预处理/标签/阶梯合同全部未动（diff 可核）。

### 5.3 旧证据找回与剩余缺口（WP6/10.3）

- 找回：上轮未交付的 4 个 small 模式 rehearsal run（20260906T141402Z_3442/141512Z_4261/141621Z_5081/141621Z_5082）原始 `chain_run.log`/`launch_evidence.jsonl`/journal 共 13 文件，只读复制至 `run_supervision/recovered_evidence/`（原文件在 WSL 原位不动）+来源映射 `source_map.json`（原运行时间/原提交 422df1c2/此前未交付事实）。
- 剩余缺口（如实保留）：上轮全量回归（1307 passed）的完整 pytest stdout/stderr 未在 WSL 落盘，原始流不可找回；不以重跑冒充旧证据——本轮受监护全量回归为新工程运行独立保存完整 stdout/stderr/JUnit。

---

## 6. 完整交付（WP6）

### 6.1 交付验证器（替代 cold_read_check.py 缺陷路径；旧脚本原样保留为历史证据）

- `build`：显式组包，必需集合来自 `run_record.json`（schema r17-run-record-v1，finalized:true 才可消费；required 外文件不收；external 条目需 external_reason）；run_record 与实际文件哈希矛盾=build 失败。
- `verify`：只读已声明清单+外部锚点——锚文件在交付集合之外，含 manifest_sha256+run_record_sha256 **双锚**；可选 git 锚=记录在案 commit 的 **blob id**（`git cat-file`，非工作树字节摘要——autocrlf/unspecified eol 下工作树与 blob 字节不同）；清单行 schema 校验（旧方言拒绝）；重复路径/越界/空清单/引用不闭合/夹带全部非零；空 stderr（size=0+空哈希）合法、缺失检出；回执写独立输出区，manifest/原文件只读。
- 反例全绿（M19-M21，真实新验证入口）：验证前删件/篡改（非零+具体文件+manifest 前后哈希不变）；删清单行（撞锚）/改清单内哈希/缺清单（rc=2）/空清单；真实空 stderr vs 缺失区分；未标记 external 的绝对路径拒绝；旧 blocker_diagnosis 方言行拒绝；finalized=false 拒绝 build。

### 6.2 测试与回归

- 专项：`test_curriculum261_r17_supervision_unit.py` 35 项全绿（勘误:初稿误记 38/39;验收核验实测 35,JUnit 同数）（WSL 真实模块；含两个真实负载缺陷的回归测试：stale 竞态取模、M24 确定性对照）；governance 32 项全绿（SHELLS 增补 r17_monitored_entry.sh 后 LF+bash-n 全过；formal/rt 结构断言零破坏——rt 脚本零改动）。
- 全量回归（受监护执行，M02 真实接入，最终 run `runs/20260906T163902_6365_38444`）：**1351 tests / 0 errors / 0 failures / 7 skipped（1344 passed），19:09（1163s）**；JUnit 与完整 stdout/stderr 落 run 目录（stderr=真实空文件 0 字节）；任务树全程覆盖（225 个含任务树样本，任务树 RSS 同时峰值 6.07GiB）；该 run 已 build（7 行 manifest）+verify rc=0+验证前篡改反例（追加 1 字节→rc=1 检出→恢复→锚哈希不变→复验 rc=0）。7 项 skip 全部为历史轮次分支上下文跳过（R12-R16 binding 检查在各自 iteration 分支外无效——设计内，与上轮同类）。回归历程本身构成监护迭代证据：第一次被缺陷 6（stale 竞态）保护性误停、第二次被缺陷 7（卷根探测）保护性误停，第三次（全部修复后）完整跑通且任务树数据完整；两次误停 run 的完整事件链作为缺陷证据原样保留。
- 既有反例不回归：M23 断言 supervision/guest_sampler 源码无执行治理接口/资格面字样；execgov 既有反例（未委派/owner-death/撤销）由既有 governance 套件覆盖（32/32）。
- M24 前后对照：同输入 fixture 任务裸跑与受监护跑业务输出逐字节一致（"bare-fixture-output-42"，裸跑 sha256 `89ba7658…`）；诊断脚本只读部分（DP+envelope 分析）双运行逐字节等价（排除 written_utc）。

### 6.3 资源报告口径（验收勘误后）

- summary.json 当前实现记录：win 侧峰值（win_free_phys_min_gib/win_commit_max_pct）+ 覆盖区间（guest_last_mono/win_last_mono/win_parse_errors/coverage_gaps）+ incidents/stage_marks/telemetry_bytes/双 PID。
- guest/task 侧峰值**不在 summary 内**，按 §15 要求从已保存遥测原始流独立复算（§6.2 引用的任务树同时峰值 6.07GiB 即由 guest_samples.jsonl 225 个含任务树样本复算得出——验收核验已独立复证）。无测量的字段不写零；不同 run/阶段/进程峰值不混加。
- 监护自身开销见 §2.2。关键卷依赖：active VHDX 与 swap 在 F:、发布仓库在 F:、应急保存在 C:（LOCALAPPDATA，101.5GiB 空闲）；E 盘非依赖（仅附带记录）。

---

## 7. 最终停点（与任务书 §16 一致）

```text
R17 最终 Implementation Freeze Commit A:未创建
R17 正式 Results Commit B:未创建
R17 正式链:未启动(§1.3 三次假 SHA 拒绝记录除外——零数据消费)
R17 正式资格 exposure:未新增
Stage 2.6.1:尚未获得正式 PASS(R13-R16 永久 FAIL 不变)
Stage 2.6.2:不变;C3 PPO Branch D 独立开放
完整 R17 工程链:BLOCKED(固定坐标合同内结构拒绝;解锁需独立授权)
```

下一项最小未决工作：(1) 审查方对 §1.3 误触发记录的确认与处置；(2) 是否独立授权生成合同变更/工程 namespace 预筛以解锁 17 步链；(3) 未来 formal 启用时将观测接线升级为保护型（需把 chain-run 纳入登记进程组——另行设计，不属本轮）。

### 6.4 交付清单状态

- 新合同（finalize 顺序定型后）run `20260906T163902_6365_38444`：delivery_manifest_v2.jsonl（7 行）+ 外部锚 `anchors/…anchor.json`（manifest/run_record 双锚）+ verify 回执（rc=0）。
- 历史过程 run（m07/m10/wp7/finalverify/两次误停/冒烟等）：原始目录字节保留、不入 manifest（跑于清单合同定型前；WP7 诊断结论 JSON `wp7_c3_p52_diagnosis.json` 独立保存并在 §5.1 引用）。
- `.gitattributes` 增补 `stage2_6_1/artifacts/repair17/development/run_supervision/** -text`（交付区字节级稳定：jsonl 哈希锚定要求 checkout 后字节不变，不受 autocrlf 影响）。
