# Stage 2.6.1 Repair R17 — 开发阻塞定位与最小修复(诊断报告)

**英文标识：** R17 Development Blocker Diagnosis & Minimal Repair
**日期：** 2026-09-06
**性质：** 冻结前、仅工程诊断与修复;不是 R18,不是正式资格执行。
**开发基线：** `3a153a08…`(中期冻结) → 本轮开发提交(见 §1;非最终
Implementation Freeze Commit A,非 Results Commit B)
**正式状态：** R17 正式链 NOT_STARTED;正式 namespace 零访问;
Stage 2.6.1 尚未通过;Stage 2.6.2 不变。

---

## 1. 起点与环境(§12-1)

- 分支 `route-c-stage2-6-1-repair17`;接手 HEAD =
  `3a153a08c0e3b1ec22050064bea2b28d19156ddf`,父链
  `d2ee974(→177c0a0→3a153a0` 与任务书一致;工作树干净、与远端同步。
- **本轮新增开发提交**(fast-forward,均含 "R17 development
  diagnosis / pre-freeze / formal not started"):
  1. `a9e8b67` — E1/E2 修复 + 环境迁 F + bash -n/D06/D07 测试
  2. `ce6c0ca` — dependencies/provenance 的 release repo 解析迁 F
  3. `2d67848` — rt small supervised_train_pair_limit 同步缩小
  4. `cd2fa3a` — rt rehearsal 缺省回归 R16 预登记规模
  (候选执行 digest = 最终提交 SHA,见 §7)
- WSL:`CryptoRL-Ubuntu-24.04` @ `F:\WSL`(2.7.12;WSLg 1.0.73;
  kernel 6.18.33);`.wslconfig` 生效值核验(VM 内实测):
  MemTotal 41GB(配额 40GB)/12 CPU/swap 8GB(@F:)。
  `autoMemoryReclaim` 键缺省 → 官方默认 `dropCache`(非禁用);
  `vmIdleTimeout` 缺省 → 60000ms。
- **环境迁移(用户指示)**:发布仓库 `E:\trading` → `F:\trading`
  (robocopy 5912 文件/385MB/0 失败;`git fsck` 干净;HEAD 校验);
  **F 侧为唯一工作树,E 侧只读备份**。WSL/swap 本就在 F。
  代码路径引用同步迁移(r17_sync/assemble_r17_b/cli×12+
  dependencies/provenance)。
- 300GB 存储上限保留;口径 = WSL 根文件系统已用(launcher +
  chain-run 双防线,现值 ~36GB)。

## 2. 故障归因(§12-2;四类结论制)

### 2.1 本轮开场 ENOENT 全阻塞 — CONFIRMED
- 现象:会话开始所有命令 `spawn bash.exe ENOENT`。
- 证据链:Read 探测 bash.exe 存在(C 盘)/E 卷不可见/F 在线;
  System 事件日志 disk Id=157 "磁盘 5 已被意外移除" 于当日
  07:56/10:19/11:44/12:00Z 共 4 次,Ntfs Id=98 E: 恢复 12:35:36Z;
  用户确认移除/重接为手动操作。
- 机制:工具进程 cwd=`E:\trading`;卷离线 → CreateProcess
  (lpCurrentDirectory 无效)失败 → ENOENT。bash 本体无恙。
- 上轮"宿主 shell 短暂 ENOENT + E: 瞬断自行恢复"同机制。
- **教训:可移除卷上的 cwd = shell 全死锁;工作目录已迁 F。**

### 2.2 上轮 E 盘时代 WSL 崩溃(15-17 轮) — CONFIRMED(既有证据)
- Windows 事件 disk Id=157 ×4 + 时刻与 design/calibrate 高 IO 段
  对应(迁移前已取证);USB 机械盘高负载掉线。本轮不重复触发。

### 2.3 上轮"nohup 脱离进程被杀" — MITIGATED(机制明确+对照)
- vmIdleTimeout 缺省 60000ms(官方文档核实):无客户端 60s → VM
  关闭 → 脱离进程全灭(不是"崩溃")。
- 修复:工具级 run_in_background 保活 wsl.exe 客户端。本轮全部
  长跑(≥90 分钟链)经此路径零中断(见 §4/§5)。
- 边界:keep-alive 缓解 ≠ 证明历史全部退出皆此因;工具退出/任务
  退出/VM 重启的区分本轮以"保活后现象消失+机制文档"为证。

### 2.4 内存"被吃 30G" — 机制分解 + 实测曲线(§12-2)
- vmmem = VM 内 Linux 总占用(进程匿名 + page cache),上限=
  memory 配额;Linux 不主动归还 cache(缺省 dropCache 回收有
  时机)。64GB 物理 − vmmem(→48GB 旧配额) − 宿主应用 ≈ 0.1GB
  可用的那次观测与该机制一致。
- **当时无进程级采样,30G 的逐项占比无直接证据(不编造)。**
- 本轮双侧采样(5s)实测:rt small 全链业务任务树 RSS 峰值
  ~1.2GB、AnonPages ≤0.7GB,而 page cache 数分钟即 2.9GB——
  缓存增长远快于业务进程;若该比例外推,历史 30G 大头应为
  page cache(可回收,无泄漏嫌疑)。大模式曲线见 §4。
- swap(8GB)在 vhdx 上,不占宿主 RAM。

### 2.5 rt rehearsal 22 次未走通 — 分解归因
- 工程迭代缺陷(参数名/状态机时序/产物根/别名/探针方法名):
  逐项已修复(上轮);本轮 17 步前 7 步 + design 全部稳定复跑 ✓。
- 环境中断:E 盘掉线(2.2)+ idle timeout(2.3)。
- **本轮新增发现的工程缺陷与修复(见 §3)。**

## 3. 最小修复(§12-3)

| # | 缺陷(源码可见/实测复现) | 修复 | 提交 |
|---|---|---|---|
| E1 | formal launcher 会话准入前 `>` 截断固定 chain_run.log(第二请求拒锁前已毁首请求日志;bash 重定向先于命令打开) | 全部请求期输出 → `r17_formal_requests/<RUN_ID>/` 独立目录;`>` 仅作用于本请求文件 | a9e8b67 |
| E2 | rehearsal 仅 state 随机,ART/LOGD 固定 → 跨次覆盖 provenance_lock/chain_run/plan/manifest,历史失败证据丢失 | state/artifacts/logs/chain 产物/manifest 全进 `r17_rt_runs/<RUN_ID>/`(含 chain-run 派生 `<name>_chain_logs`,落在 run 内);旧目录保留 | a9e8b67 |
| 双脚本漂移 | formal/rt launcher 重复维护 LF 自检/emit/激活/验证 | 提取 `r17_entry_common.sh` 共享(同源消除漂移);两 launcher 各自保留含 common 的 LF 自检 | a9e8b67 |
| 路径迁移残留 | dependencies/provenance 内嵌 release repo 解析仍指 /mnt/e → audit 读 E 盘旧 HEAD 拒绝 | 迁 /mnt/f(实测复现:audit rc=1 报 HEAD=3a153a0≠freeze) | ce6c0ca |
| rt small 配置缺陷 | small pairs=4 但 train_pair_limit=6 未同步 → test_rows 恒空,np.stack 崩溃(实测复现) | limit=(3 if small else 6)(正式 10:6 不变) | 2d67848 |
| rt 规模口径 | 上轮为绕开 c3 生成失败临时硬编码 small=True(缩小语料统计排序不保证;实测 curriculum gate False) | 缺省回归 R16 rt 预登记规模(RT_* 常量,R15/R16 rehearsal 17 步全绿先例);`CURRICULUM261_R17_RT_SMALL=1` 留作诊断逃生门 | cd2fa3a |

**不改变领域语义声明**:以上全部为工程层(路径/目录/规模开关/
日志落点);统计阈值、κ、max_attempts、seed 派生、正式样本量、
C2 候选表、global K 合同零触碰(§10 原文保持)。

## 4. 观测与 design 定位(§12-2;D02/D04)

- 双侧采样器(Windows PowerShell + WSL guest python,5s,JSONL,
  UTC;开销:win ~118MB RSS / guest ~20MB;保护线 B4 内建,
  全程未触发——全轮 WSL MemAvailable ≥37GB,Windows 可用
  ≥40GB,commit ≤45%,无 swap 换入)。
- **design 步定位结论(可检验)**:rt 链 design 步(rt3 工程
  namespace)= 稳定 ~5 分钟 CPU 计算(三次实测 5.5/5.1/5.1
  分钟),任务树 RSS 峰值 ~1.2GB,无 IO 停滞、无内存爬升、
  无等待点。**上轮 22 次"design 进行中"被杀 = 环境中断
  (§2.2/§2.3),非 design 本身缺陷。本轮在工具级保活下
  design 三次全部稳定完成。**
- 步骤时长基线(rt 链,实测):provenance-verify 2s;
  determinism-matrix 69s;audit 53s;cue-audit 4m54s;
  preplan-smoke 1m41s;plan-roundtrip 3s;design-plan-lock 13s;
  design ~5m;calibrate 见 §5。

## 5. 工程链验证(§12-5;D12)— 最终判定:BLOCKED

### 5.1 已真实验证的链段
- 前 7 步:四次完整复跑全绿(时长见 §4;E1/E2 修复后每次
  run 目录完全隔离,D07 断言通过)。
- design:三次 completed(journal 事件 + 产物在 run 目录)。
- calibrate 内部接口(small 模式,`CURRICULUM261_R17_RT_SMALL=1`):
  preprocessing robustness ✓ / supervised main+holdout ✓(2d67848
  修复后)/ routing 全矩阵 ✓ / conditioning+stress ✓ / frozen
  identity ✓——**接口层全部真实执行且通过**;唯一 False =
  curriculum 统计 gate(缩小语料排序不保证,非缺陷,不可放宽)。
- 每次失败的 raw log/journal/failure envelope 完整保存在各自
  run 目录(`r17_rt_runs/20260906T12*`~`T13*`,跨次零覆盖)。

### 5.2 rt 大模式全链 17 步 — 不可行(确定性,双证据)
1. **生成层(决定性)**:rt 大模式(=R16 预登记 RT_* 常量,
   60/rung、c2 20 blocks、semantic 160、indep 20)calibrate 在
   `c3_cost/D0/pair_index=52` 确定性 PairGenerationError:
   5 次生成尝试(冻结 max_attempts=5)均 distractor 不足,
   failure envelope ×5 落盘(run `20260906T134324Z_1475`,
   `generation_failure_envelopes_calibrate_c3_cost_D0_p52.json`)。
   生成器为 **R16 冻结原件**(`rl_curriculum.curriculum261_c3`,
   source_sha256=77374242… 绑定于 call envelope)——排除 R17
   转换引入生成缺陷。对照:R16 的 rt2 namespace 在同一规模
   (RT_C13_PAIRS_PER_RUNG=60,R16 实测同值)17 步全绿。
   ⇒ **rt3 namespace 的坐标级生成约束**(seed 派生自
   namespace+坐标,确定性;small 模式 2/rung 下 pair52 不生成,
   故 small 可过生成层——坐标敏感性确证)。上轮"5 连败
   seed 运气"记录即此,本轮以 envelope+生成器身份证据闭环。
2. **统计层(补充)**:small 模式唯一 False 项 = curriculum
   统计 gate;按任务书 §10/§D5 禁止放宽 gate 或换 seed/namespace
   抽到通过(换新工程 namespace = 事后挑选坐标,滑坡,不做)。

### 5.3 后半链接口的替代验证(§D5 允许口径)
qualify(pipe 委派)/grant 撤销/owner-death/smoke/full-cold/
report-read 的接口真实性由 execgov/governance 单元测试覆盖
(真实不同进程的委派握手、fork/spawn 反例、owner 真实退出后
拒绝、并发拒绝零 journal 副作用等 22+30 项)——**局部接口
验证完成,不等价于完整工程链**(任务书 §D5 原文边界)。

### 5.4 判定
**最终完整工程链(17 节点,rt 预登记规模)= BLOCKED**。
最小未决问题 = rt3 坐标系 c3_cost/D0/pair52(以及潜在其他
坐标)在冻结生成器+冻结 max_attempts 下的生成不可行;已有
证据 = 本 §5.2;下一项可区分假设的动作 = 在独立授权下
预登记一个新的工程 namespace 并先做全坐标生成可行性探针
(生成层,不触统计),或维持 small 口径并显式改预登记
rt 工程差异声明(需审查方批准——本报告不建议未经审查
自行选择)。

## 6. 回归与交付复验(§12-4/§12-6)

- 治理单元测试:30/30 passed(含新增 bash -n×5、E1 机制反例、
  D06 真实并发、D07 跨次隔离;真实 launcher 运行)。
- **全量回归(真实计数)**:`tests/route_c_stage2_6_1` 全目录,
  `pytest -q --junitxml=…`(WSL freqtrade-rl/Python 3.11.16,
  PYTHONPATH=src):**1307 passed, 7 skipped, 0 failed,
  1099.87s(18:19),rc=0**。JUnit 归档于本目录
  `full_regression_junit.xml`。
  7 个 skip 全部为设计内分支上下文条件跳过("非 repair12/13/
  14/15/16 分支"——R12-R16 binding 的分支检查仅在各轮迭代
  分支上执行,当前分支 route-c-stage2-6-1-repair17 按设计跳过,
  由各轮 governance 迭代内测试承担);无 R17 新增 skip。
  (计数与上轮报告口径差异来源:R17 转换+新增测试,不凑任何
  预设总数。)
- **交付冷读**:本目录(`artifacts/repair17/development/
  blocker_diagnosis/`)38 文件 + `delivery_manifest.jsonl`
  (sha256/bytes;manifest 自排除防自引用);隔离副本逐文件
  重算全过;篡改反例与缺件反例均被检出
  (`observers/cold_read_check.py`,可复跑)。
- 采样数据完整性:windows_samples.jsonl(13:38-诊断结束,
  5s 间隔,含 vol_missing 事件零条——E 盘重接后未再离线)、
  guest_samples.jsonl(链运行全程)归档于 `samples/`;
  4 个 rt run 的 journal/calibrate 日志/failure envelope/
  chain_result/launch_evidence 归档于 `runs/`(WSL 原始 run
  目录 `~/projects/crypto_rl/r17_rt_runs/` 保留全量字节,
  不删除)。

## 7. 状态结论(§13)

- **Diagnosis:CONFIRMED**(全部现象有直接证据或可信反例+机制:
  ENOENT=cwd 卷失效;上轮崩溃=E 盘掉线;脱离进程死=vmIdleTimeout;
  内存=配额+cache 机制,占比无历史进程级证据不编造;design=无缺陷,
  环境中断;rt 大模式不可行=rt3 坐标生成约束[确定性,envelope
  证据,生成器冻结原件,R16 rt2 同规模对照])。
- **Engineering Validation:PASS(受限口径)**——已验证环境与
  工作负载内:前 7 步+design+calibrate 接口层四次真实执行;
  E1/E2 修复经真实并发/跨次反例;全量回归 1307/0 失败;资源
  开销全程在诊断保护预算内(未触发任何保护线)。**不承诺**
  所有机器/并发组合;rt 大模式 17 步全链因 §5.2 不可行。
- **Delivery Evidence:PASS**(38 文件 manifest+隔离冷读+双反例;
  JUnit/原始日志/run 证据在库;缺件=无[归档范围外的 WSL 原始
  run 目录已声明路径与保留策略])。
- **Formal Authorization/Execution:NOT_STARTED**(R17 正式
  namespace 零访问;本轮全部工作在 rt3 工程 namespace 与
  工具/测试目录)。
- **最终完整工程链(rt 预登记规模 17 节点):BLOCKED**
  (§5.2;最小未决问题与下一步可区分假设动作已列)。
- **Stage 2.6.1:尚未通过;Stage 2.6.2:不变(C3 PPO Branch D
  仍开放)。**

**候选执行内容** = 本报告 §1 提交链的最终提交 SHA(见 git log;
不含报告本体的提交=前一提交;含报告的最终提交在推送后即本轮
候选 digest——两者均为开发提交,非 Commit A/B)。

```text
R17 最终 Implementation Freeze Commit A:本次不创建
R17 正式链:本次不启动
R17 正式资格 exposure:本次无新增
R17 iteration:尚未获得正式 PASS
```

## 8. Agent 回报要点索引(§14 对应)

1. 分支/接手/最终 SHA/父链/候选 digest → §1
2. 内存定位(命令/阶段/峰值/余量/commit/swap/缓存/采样覆盖)
   → §2.4 + §4(采样曲线原始数据在库)
3. 中断分类(应用错误/工具退出/生命周期/资源保护/OOM/存储/
   VM 重启/未知,各带时间与证据)→ §2.1-§2.3、§2.5
4. design 耗时分解+已执行/未开始路径 → §4、§5
5. 最小修复位置与真实测试(会话前日志覆盖/跨次隔离/授权握手/
   子进程收尾)→ §3、§5.1、§6
6. 全量测试真实数量/rc/JUnit/原始输出;最终 rehearsal 实际
   入口/前缀/冷读 → §5、§6
7. E 盘残留依赖/资源保护触发/日志缺件/历史证据缺口/
   已知不确定性 → §1(路径全迁 F;E 只读备份)、§2.4(历史
   内存占比无进程级证据)、§5.2(坐标级约束的不可判定外推)
8. 六类状态 → §7
