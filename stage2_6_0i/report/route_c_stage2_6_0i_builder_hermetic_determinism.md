# Route C 阶段 2.6.0i 审计报告:Builder 密闭确定性输入、真实运行时内容闭包与 seccomp 架构边界闭环

日期:2026-08-29
基线:stage2_6.0h(commit `11b22e8ebcb16c4bee78d3244d827e09e814fda6`,1340 项回归)
环境:Windows + WSL2(CryptoRL-Ubuntu-24.04)/ Ubuntu 24.04 / conda freqtrade-rl(Python 3.11.16)
Freqtrade 上游:固定 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`,工作树 clean(见 upstream_integrity.txt)

---

## 0. 结论

**PASS。** 2.6.0h 独立审查的三项阻塞(输入文件闭包、未承诺外部状态、
seccomp 架构边界)全部以**生产机制**(非记录性补丁)闭合:正式 Builder
Worker 的有效输入集合 = 内容寻址只读 bundle(rbm- manifest)+ 冻结请求
+ 冻结 seed namespace + 固定环境;真实时钟被 vDSO 冻结 stub 与 syscall
拒绝双层封死;真实熵不可观察(熵为受承诺确定性字节);seccomp v2 校验
arch、显式拒绝 x32、禁止一切线程;全量回归(full-cold,统一 runner,2 worker)1462 项零失败、
零跳过、零 xfail、零 error(1384 项历史测试协议等强度适配 + 78 项
新增攻击测试;wall 3282s)。

## 1. 生产保证(机制层)

### 1.1 内容寻址 runtime bundle(阻塞 A)
- Worker 的**整个根文件系统**在启动前由 Supervisor 组装为内容寻址
  staging(conda env 硬链接 + ELF DT_NEEDED 传递闭包解析的系统库 +
  Runner 运行时副本 + Builder 包副本 + 确定性熵文件),逐文件 manifest
  (rbm- 摘要)进入 evidence 与承诺;
- 三重验证:组装后复验、**Worker exec 前在挂载视图内全量复验**(对实际
  挂载内容的重新验证)、运行结束后 Supervisor 复验(检测硬链接别名
  就地改写);
- RECORD 降级为辅助元数据(归属映射):内容权威是 manifest;归属按
  **实际文件路径**(METADATA Name 归一),多义归属 fail closed。

### 1.2 导入/文件/native 闭包(阻塞 A)
- 每个实际导入模块:loader 白名单(SourceFile/ExtensionFile/
  Sourceless/zipimporter/Builtin/Frozen)、文件字节 sha256 与 manifest
  逐条绑定、by-path distribution 归属;bundle 外文件、scratch 动态
  加载、自定义 import hook、外部 zip、多义归属全部 fail closed(真实
  攻击路径实测);
- native 库由 Supervisor 在 quiesce 时刻从外部 /proc maps 实测,逐个
  绑定字节与 origin(全部 runtime-bundle);manifest 外 .so 拒绝;
- 可见只读文件全集 = manifest 全集(pivot 后宿主路径 ENOENT,实测
  探针矩阵);scratch 每次全新为空。

### 1.3 时钟闭包(阻塞 B)
- **vDSO 冻结虚拟化**:解析 vDSO ELF 符号表取得 __vdso_clock_
  gettime/time/gettimeofday/clock_getres/getcpu 偏移,munmap 原页后
  同基址重映射、整页回写原字节(ld.so 将 vDSO 视作链接映射对象,
  元数据必须完整)并仅在原偏移覆写返回冻结纪元 0 的 stub;glibc 在
  启动期解析的 vDSO 函数指针直接落入受控 stub;
- 行为证明(进入 EDIC 与锁 v3):time.time()/monotonic()/
  perf_counter() 恒 0.0,datetime.now()/utcnow() 恒 1970(跨双跑
  一致——不是"三次碰巧相同",而是恒定冻结值);
- syscall 层:clock_gettime/time/gettimeofday/times/getrusage/
  nanosleep/clock_nanosleep/adjtimex/clock_gettime64 全部 seccomp
  EPERM(raw syscall 实测矩阵);
- 指令层:prctl(PR_SET_TSC=PR_TSC_SIGSEGV)(实测选项号 26),
  rdtsc 执行即 SIGSEGV(真实攻击实测 Worker 信号死亡、构建失败);
- vDSO 证据:原始 vDSO 字节 sha256、符号偏移表、stub 摘要、冻结
  纪元常量全部进入 EDIC。

### 1.4 熵源闭包(阻塞 B)
- getrandom syscall seccomp EPERM;/dev 无真实 random/urandom 设备;
- /dev/urandom、/dev/random 是**受承诺确定性字节文件**(固定种子
  sha256 链生成,内容进 manifest)的只读 bind;
- 实测:os.urandom/secrets/SystemRandom/random 模块导入与 numpy
  未播种 RNG 全部取得确定性种子(两个全新 Worker 进程产出相同 pack;
  numpy 种子来自 CPython 对 /dev/urandom 文件的顺序读——跨进程读同
  一起始字节,确定性成立);getrandom raw syscall 攻击构建失败。

### 1.5 /proc 与环境观测(阻塞 B)
- /proc 完全不挂载(Worker 内 ENOENT、列表为空);Worker 证据字段
  (Seccomp/NoNewPrivs/NSpid/线程/子进程/maps)全部由 Supervisor 在
  quiesce 时刻外部实测合并——**运行时锁/证据不再依赖 Worker 自读
  /proc**;
- UTS namespace 固定 hostname=builder-worker;PID namespace(外部
  NSpid 实测 pidns pid=1);netns 仅 lo;环境身份(白名单 env、
  uname、cpu、cwd=/scratch)进 EDIC 且跨运行一致。

### 1.6 seccomp v2 与线程(阻塞 C)
- BPF 第 0/1 条读 seccomp_data.arch 并 JEQ AUDIT_ARCH_X86_64,
  不匹配跳 RET EPERM(结构断言 + 摘要对账);
- 第 2-5 条显式 AND/JEQ __X32_SYSCALL_BIT(0x40000000)置位即
  RET EPERM;raw syscall 实测:x32 fork/execve/clone/write 均
  EPERM;**本内核原生支持 x32 fork**(无 filter 基线实测真实创建
  孙进程)——证明该边界是必要防线而非冗余;结果矩阵明确区分
  "seccomp 拒绝(EPERM)"与"内核原生行为(ENOSYS/EBADF)";
- x86_64 fork/vfork/clone/clone3(ENOSYS 使 glibc 回退到被拒的
  clone)/execve/execveat/ptrace/mount/umount2/unshare/setns/
  process_vm_*/bpf/perf_event_open 全拒;
- **clone 全拒(0h 的 CLONE_THREAD 例外删除)**:线程创建即 EPERM
  (threading.Thread().start() 实测 RuntimeError);Builder 吞掉异常
  返回 pack 时 quiesce 外部实测 /proc task 恰为 1(线程从未存在,
  静止证明进锁 v3 与 EDIC);"Builder 返回后线程继续活动"的路径在
  机制上不存在。

### 1.7 执行顺序与 Candidate 隔离(工作包 D)
- 正式顺序全部完成于 Candidate checkpoint 可见之前(访问守卫 v2
  的 Builder 阶段子进程豁免收窄为:bootstrap launcher 与两个带
  身份标记的 Supervisor 组装/复验子进程——守卫现在检查完整 argv,
  且这些子进程只读取 staging,不触碰任何候选材料);
- EDIC(edi-)取代 esb-:绑定 bundle 摘要、挂载摘要、proc/dev/
  clock/entropy/seccomp/线程静止/环境身份与全部行为探针;
- 协议:lock v3 / evidence v3 / 承诺 v10 / CLI v11 / worker v3 /
  profile v3 / seccomp v2;旧材料(含"重签"v2 为 v3 形状)全部拒绝;
  请求/结果/attempt log 等语义未变者不升级。

## 2. 测试证明(工作包 E/F;tests/route_c_stage2_6_0i/,78 项)

| 文件 | 覆盖 |
|---|---|
| test_bundle_content_closure.py(17) | 摘要确定性、E1 组装前绑定/组装后拒绝、A4 RECORD csv 全矩阵、A5 symlink/FIFO/越界、E3 by-path 归属与多义、熵文件稳定、manifest 自洽、系统库闭包 |
| test_seccomp_arch_x32.py(16) | C1/C2 结构证明、x32/x86_64 raw syscall 全矩阵、无 filter 基线区分、x32 fork 真实泄漏基线与 filter 阻断对照 |
| test_clock_entropy_closure.py(8) | E5 冻结时钟可见/双跑一致/raw syscall 拒绝/rdtsc 死亡/vDSO 证据;E6 确定性熵双跑一致/getrandom 拒绝/numpy 未播种确定性 |
| test_host_visibility.py(5) | E7 宿主路径 ENOENT 矩阵、/proc 缺席、身份固定(pidns/uts/netns)、环境身份稳定、scratch 全新、/dev 节点与熵文件 |
| test_thread_quiescence.py(3) | E9 线程创建拒绝、吞错后静止证明、后台导入线程不可达 |
| test_import_file_closure.py(6) | 真实 numpy 闭包/归属/native、scratch 动态加载拒绝、自定义 hook 拒绝、zip 内外、namespace location、多义归属 |
| test_bundle_toctou.py(5) | E10 staging 篡改、硬链接别名就地写、EDIC bundle 摘要/线程数/seccomp 策略篡改拒绝 |
| test_protocol_upgrade.py(6) | 版本总表、v2 锁/evidence 拒绝、v3 缺字段逐项拒绝、重签拒绝、profile v3 语义 |
| test_full_private_pipeline_v10.py(12) | 工作包 F 完整链路(见 §3) |

## 3. 完整私有链路复验(工作包 F)

- 私有 Builder(自包含、stdlib-only)、非默认 pair_count_per_
  family=40、max_attempts=5、first_pass 真实 attempt log(编号连续/
  唯一 accept/前置全 reject/选中即终止);
- 两步 duration contract → precommit 双跑(七组一致性键:pack/
  attempt log/runtime lock/deterministic input/access summary/
  child/exec)→ evidence v3(edi-/rbm-)→ 承诺 v10 → CLI v11 正式
  考试第三次重放(replay edi-/rbm-/thread_policy 与 precommit 一致)
  → duration/power/pack validity(PACK_VALID)→ trusted training
  attestation → Candidate 沙箱 → 256-step PPO smoke → **正常 FAIL**
  (挂科不失效)→ sealed checks 全 True;
- 篡改矩阵(重签 bre- 后仍拒,rc=5 EXAM_INVALID):runtime_bundle_
  hash、import closure 注入、时钟策略(伪造真实时间)、熵策略
  (getrandom 伪造放行)、线程静止(伪造 4 线程)、seccomp arch
  策略(伪造不校验)、0h v2 evidence 重签;
- 访问守卫:violations==[],stat_coverage 含 namespace_unnameable。

## 4. 环境限制(如实声明,不构成 PASS 障碍)

1. **ASLR 残余**:vDSO 基址与堆地址随进程变化——vDSO 基址不进入
   任何哈希(仅 stub 摘要/冻结纪元等确定值进入);无合成模块外,
   Worker 内无依赖地址的输入路径(合成模块为无文件命名空间,已记入
   闭包)。
2. **TSC 封禁的进程级性**:PR_SET_TSC 为 per-thread 标志,由 Worker
   在 seccomp 安装后立即设置且禁止任何新线程/进程,故覆盖完整;
   rdtsc 探针以真实崩溃(独立进程)与攻击用例(Worker 信号死亡)
   双路径证明。
3. **bundle 复验的窗口语义**:exec 前挂载视图全量复验 + 运行后
   Supervisor 全量复验覆盖全部采信窗口;两窗口之间 Worker 对根文件
   系统无写权限(ro bind + Landlock + 只读 open)。
4. CPython 3.11 对 os.stat 无审计事件(沿 0h 结论):stat 级不可
   利用由 pivot 后 ENOENT 探针矩阵证明。

## 5. 与 2.6.0h 材料的互斥

承诺 v10 的加载器拒绝 v9(弃用列表,含逐版缺陷说明);evidence v3
哈希/加载拒绝 v2;lock v3 校验拒绝 v2;worker 协议 v3 拒绝 v2;
"重签"(改 format + 重算 bre-)不能绕过字段级语义校验(缺
deterministic_input_hash/runtime_bundle_hash/thread_policy 的材料
在验证器拒绝);实测见 legacy_2_6_0h_material_rejection.json 与
test_legacy_0h_evidence_reshaped_rejected。

## 6. 回归(工作包:全量)

- 2.6.0h 基线 1340 项全部保留(适配后 1384 项:0h/0g 等目录因
  参数化扩展净增 44 项):协议字面量按等强度语义映射适配
  (esb-→edi- + rbm- + thread_policy 等),无删减、无断言弱化、
  无 skip/xfail(多处断言强于 0h:降级矩阵 13→24 例、numpy
  绑定升级为 file+sha256+distribution 三重);
- 新增 78 项(§2);
- 统一 regression runner(quick/affected/
  full/full-cold;影响规则可审计;修改共享 env 的目录独占运行;
  full-cold 清缓存从零执行且为唯一 PASS 依据;性能:串行 full
  ≈62min 且存在跨目录 env 互扰 → full-cold 2-worker 3282s 全绿);
- 逐目录结果见 regression_test_summary.md,原始日志见
  regression_raw.log;vendor/freqtrade 见 upstream_integrity.txt
  (HEAD 与 clean 状态)。

## 7. 冻结边界确认

RouteCEnvCore-v1.0.0 / ObservationSpec-v1 / BinaryLongFlatAction-v1 /
NetLogEquityReward-v1 / MarketOpenCausalExecution-v1 /
TerminalLiquidation-v1 / LongFlatLedger / fee / slippage / tick
rounding / reward / terminal liquidation / Freqtrade 上游源码 /
Null qualification / friction 公式 / power-analysis-v2 / antithetic
pair / Candidate observation-action 合同 / training attestation
信任根——全部未修改。未开始 2.6.1、课程 generator、正式 PPO、模型
容量选择、Alpha 训练、Dry-run、真实交易。

---

### 附:PASS 判定对照(任务书第十三节)

| # | 判定 | 证据 |
|---|---|---|
| 1 | 可见只读全集进 bundle | rbm- manifest + 挂载视图复验 + ENOENT 探针 |
| 2 | RECORD 外新增导入不逃逸 | E1 矩阵(组装前绑定/组装后拒绝) |
| 3 | 模块-归属正确绑定 | by-path 归属 + 多义 fail closed |
| 4 | package data 在闭包内 | package_data_access_matrix |
| 5 | 真实 clock 不影响 pack | vDSO 冻结 + syscall 拒绝 + 双跑恒 0 |
| 6 | 真实 entropy 不影响 pack | getrandom EPERM + 确定性熵 + 双跑一致 |
| 7 | 不可读未承诺 /usr/conda/proc/data | ENOENT 矩阵 + /proc 不挂载 |
| 8 | seccomp 校验 architecture | BPF i0/i1 + 结构断言 |
| 9 | x32 bit 显式关闭 | BPF i2-i5 + x32 raw syscall EPERM 矩阵 |
| 10 | 不可创建后代/exec | fork/vfork/clone/clone3/execve/execveat 全拒矩阵 |
| 11 | 线程禁止 + 静止证明 | clone 全拒 + quiesce task==1 |
| 12 | 新语义进 evidence/承诺 | evidence v3 / 锁 v3 / EDIC / v10 / v11 |
| 13 | 旧 0h 材料拒绝 | §5 + legacy 矩阵 |
| 14 | 完整私有 pipeline 通过 | §3 |
| 15 | 零失败/跳过/xfail/error | regression_test_summary.md |
| 16 | 上游 clean + 固定 HEAD | upstream_integrity.txt |
| 17 | 冻结合同未修改 | §7 |
| 18 | 未开始下一阶段 | §7 |
