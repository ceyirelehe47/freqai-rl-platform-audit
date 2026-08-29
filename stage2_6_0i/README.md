# 阶段 2.6.0i:Builder 密闭确定性输入、真实运行时内容闭包与 seccomp 架构边界闭环

基线:2.6.0h(commit `11b22e8ebcb16c4bee78d3244d827e09e814fda6`,
1340 项回归)。Freqtrade 上游固定 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。

## 一、解决的问题(2.6.0h 独立审查三项阻塞)

### 阻塞 A:runtime lock 未覆盖真实导入文件闭包
2.6.0h 的 distribution content digest 以 RECORD 为清单,不能发现
RECORD 外新增并被导入的文件、namespace 包第二 owner、package data
读取、loader 攻击等。

### 阻塞 B:Builder 仍能读取未承诺的外部状态
活 /usr、活 conda 环境、/proc、真实时钟(vDSO/syscall)、真实熵源
(/dev/urandom、getrandom)对 Builder 可见;"三次一致"无法证明输出
只由承诺材料决定。

### 阻塞 C:seccomp 缺架构/x32 边界证明;线程策略不闭合
BPF 未校验 seccomp_data.arch;x32 ABI 路径未显式关闭(本内核原生
支持 x32 fork,实测无 filter 时可创建进程);CLONE_THREAD 放行使
后台线程在 Builder 返回后继续活动成为可能。

## 二、架构(Supervisor → 密闭 Builder Worker)

```
Supervisor(评估主进程,rl_curriculum/builder_runner.py)
 ├─ RuntimeBundlePool:内容寻址 bundle 组装/复用(rbm- 摘要)
 ├─ fork-launcher(rl_builder_runtime/bootstrap.py,纯 syscall,
 │  无 unshare/mount/pivot_root 外部命令):
 │    userns(父写 uid_map/gid_map——WSL2 拒绝自写)→ mountns
 │    (private)→ netns → utsns(hostname=builder-worker)
 │    → bundle staging 挂载(bind self + tmpfs dev/tmp/scratch
 │      + null/zero/full 设备 bind + 确定性熵 ro bind + 根 ro
 │      remount)→ pidns → fork worker
 └─ Worker(pivot_root → 挂载摘要 → umount 旧根 → 挂载视图内
      manifest 全量复验 → Landlock → rlimits → exec)
      = bundle python(PYTHONHOME=/)在密闭 rootfs 内运行:
        seccomp v2 → vDSO 冻结 stub → PR_SET_TSC → EDIC 探针
        → 受控 import → 构建 → 导入闭包 → quiesce 握手
 Supervisor quiesce 外部实测(/proc:maps/task/status/NSpid)
 → ACK → final → 运行后 staging 全量复验
```

Worker 可见输入 = 且仅 = 受承诺材料:
1. 内容寻址只读 bundle 根(conda env 硬链接 + 系统库闭包 + Runner
   运行时 + Builder 包 + 确定性熵文件 + manifest);
2. 冻结请求(stdin);
3. 全新空 scratch tmpfs;
4. 最小 /dev(null/zero/full;urandom/random 为**受承诺确定性字节
   文件**的 ro bind);
5. 固定环境变量(UTS hostname/时区/locale/HASHSEED 均固定)。

不可见:宿主 /usr、活 conda 树、/proc(完全不挂载)、真实时钟、
真实熵、Candidate/checkpoint、网络(netns 仅 lo)、其他宿主路径
(pivot 后 ENOENT,实测探针矩阵)。

## 三、工作包落点

### A:runtime bundle 内容闭包
- `rl_builder_runtime/bundle.py`:组装(硬链接优先/跨设备复制/
  symlink 绑定目标且不得逃逸/特殊文件拒绝)、逐文件 manifest
  (rbm-)、ELF DT_NEEDED 系统库闭包解析(vaddr→offset)、RECORD
  标准 csv 解析(绝对路径拒绝、重复拒绝、URL-safe base64 校验、
  无哈希条目显式记录、../ 层级标记且最终解析必须在 bundle 内)、
  dist 归属映射(按实际文件路径;METADATA Name 归一;多义记录);
- 挂载视图复验(Worker exec 前,verify 实际挂载内容)+ 运行后
  Supervisor 复验(检测硬链接别名就地改写);
- 导入闭包(runner `_import_closure`):逐模块 loader 白名单/
  文件字节 sha256 绑定 manifest/by-path 归属/namespace 包 search
  location 校验/zip(bundled 允许、外部拒绝)/自定义 loader 与
  scratch 动态加载拒绝;native 库由 Supervisor quiesce 时刻外部
  /proc maps 实测并逐字节绑定。

### B:时钟/熵/动态状态闭包
- **vDSO 冻结虚拟化**(核心技术):解析 vDSO ELF 符号表,munmap
  原页后在同基址重映射、整页回写原字节(ld.so 把 vDSO 当链接映射
  对象遍历,元数据必须完整)、仅在原符号偏移覆写返回冻结纪元 0 的
  stub(clock_gettime/time/gettimeofday/clock_getres/getcpu);
  glibc 缓存的 vDSO 函数指针直接落入受控 stub——time.time() 恒
  0.0、datetime 恒 1970,跨运行跨机器确定;
- raw syscall 时钟族(clock_gettime/time/gettimeofday/times/
  getrusage/nanosleep 族/clock_gettime64)seccomp 全拒;
  RDTSC/RDTSCP 由 prctl(PR_SET_TSC=PR_TSC_SIGSEGV)(实测常量 26)
  封禁,rdtsc 执行即 SIGSEGV(fail closed);
- 熵:getrandom syscall 拒绝;/dev/urandom、/dev/random 为受承诺
  确定性字节文件(内容 sha256 进 manifest)——stdlib random/secrets
  /numpy 未播种 RNG 均取得确定性种子(双跑实测 pack 一致);
- /proc 完全不挂载(动态内核状态不可观察);Worker 证据字段由
  Supervisor 外部实测合并;
- UTS namespace 固定 hostname;PID namespace(外部 NSpid 实测
  pidns pid=1);环境身份(白名单 env/uname/cpu/cwd)进 EDIC。

### C:seccomp v2 与线程生命周期
- BPF 先校验 seccomp_data.arch == AUDIT_ARCH_X86_64(不匹配
  EPERM),显式拒绝 __X32_SYSCALL_BIT;raw syscall 实测矩阵:
  x32 fork/execve/clone/write 全 EPERM(并实测本内核原生支持
  x32 fork——无 filter 基线真实创建孙进程,证明该防线必要);
  x86_64 fork/vfork/clone/clone3/execve/execveat 全拒;
- **clone 全拒(删除 0h 的 CLONE_THREAD 例外)**:正式 Builder
  禁止一切线程;线程创建即 EPERM;quiesce 时刻 Supervisor 外部
  实测 /proc task 恰为 1(线程静止证明进锁 v3 与 EDIC)。

### D:执行顺序与证据升级
- 正式顺序:bundle 组装/验证 → identity → 冻结请求 → Worker 沙箱
  → 构建 → 导入/文件/环境闭包验证 → 时钟/熵策略验证 → 线程静止
  验证 → evidence 形成 → precommit 双跑 → 承诺 → 第三次重放 →
  对账;全部完成后 Candidate 才可见(访问守卫 v2 豁免清单收窄到
  bootstrap launcher 与两个带标记的 Supervisor 组装子进程,并检查
  完整 argv);
- **Effective Deterministic Input Report**(builder-deterministic-
  input-report-v1,edi-):取代 0h esb-;绑定 bundle 摘要/挂载/
  proc/dev/clock/entropy/seccomp/线程静止/环境身份/全部行为探针;
- 协议升级:runtime lock v2→**v3**、run evidence v2→**v3**(新增
  deterministic_input_hash/runtime_bundle_hash/thread_policy)、
  承诺 v9→**v10**(v9 入弃用列表)、CLI v10→**v11**、worker 协议
  v2→**v3**(两阶段 quiesce/final)、profile v2→**v3**、seccomp
  策略 v1→**v2**;旧材料(含"重签")全部拒绝。

### E/F:攻击与链路测试(见测试清单)

## 四、测试与基线

- 2.6.0h 基线 1340 项全部保留并适配到新协议(断言等强度映射,
  无删减/无弱化/无 skip);
- 新增 tests/route_c_stage2_6_0i/(78 项):bundle 内容闭包 17、
  seccomp arch/x32 16、时钟/熵 8、宿主可见性 5、线程静止 3、
  导入闭包 6、TOCTOU 5、协议升级 6、完整私有链路 12(40 pair/5
  attempts、precommit 双跑、承诺 v10、CLI v11 第三次重放、
  256-step PPO smoke 正常 FAIL、六类篡改 EXAM_INVALID、0h 材料
  重签拒绝);
- 全量回归(full-cold,统一 runner):**1462 passed / 0 failed /
  0 skipped / 0 xfailed / 0 error**(1384 项历史适配 + 78 项新增;
  见 regression_test_summary.md / regression_raw.log /
  upstream_integrity.txt / regression_fullcold_summary.json);
- 统一 regression runner(regression_runner.py + 影响规则
  regression_selection_rules.md):quick/affected/full/full-cold
  四模式;目录级受控并行(默认 2 worker,每 worker 独立中性
  TMPDIR/cache/日志,固定线程环境);修改共享 env 状态的目录
  (0h/0i)独占运行;full-cold 清缓存从零执行,全绿后刷新内容
  寻址基线——只有 full-cold 允许报告 PASS;
- 性能:首轮串行 full ≈62min(温缓存,且因共享 env 并发互扰出现
  0h 32 errors/0b 1 failed);full-cold(2 worker + 互斥调度 +
  中性 TMPDIR)= **3282s ≈ 54.7min 全绿**(冷缓存含 ~5min 组装/
  验证开销;沙箱挂载视图全量复验是主要固定成本,属安全语义);
- 测试结构:纯 validator 批量篡改用例复用 module 级可信基线
  夹具(private_chain/run_attack),完整考试链每会话仅跑一次;
  full 模式 --durations=50 热点清单随原始日志提交。

## 五、Artifacts(18 项)

见 report/ 与 artifacts 清单:runtime_environment_bundle_manifest
(+manifest.full.json.gz)、runtime_bundle_tree_digest、
actual_import_file_closure、namespace_package_owner_matrix、
package_data_access_matrix、record_extra_file_attack、
clock_attack_matrix、entropy_attack_matrix、
host_file_visibility_matrix、seccomp_arch_x32_matrix、
thread_quiescence_report、runtime_bundle_toctou_matrix、
builder_evidence_v3、legacy_2_6_0h_material_rejection、
full_private_pipeline_next_protocol、regression_test_summary、
regression_raw、upstream_integrity。

## 六、协议版本总表(2.6.0i)

| 组件 | 2.6.0h | 2.6.0i |
|---|---|---|
| sealed commitment | v9 | **v10** |
| hidden exam CLI | v10 | **v11** |
| builder run evidence | v2 | **v3** |
| runtime lock | v2 | **v3** |
| worker 协议 | builder-runner-worker-v2 | **v3** |
| runner profile | v2 | **v3** |
| seccomp 策略 | v1(无 arch/x32;放行 CLONE_THREAD) | **v2**(arch/x32/clone 全拒/clock/entropy) |
| 沙箱报告 | esb-(effective sandbox) | **edi-**(deterministic input) |
| bundle manifest | —(无 bundle) | **builder-runtime-bundle-manifest-v1(rbm-)** |
| 确定性输入报告 | — | **builder-deterministic-input-report-v1** |

请求/结果/attempt log/mock 通道语义未变,不作无理由升级
(builder-build-request-v3 / builder-build-result-v3 /
builder-attempt-log-v2 / ndc-/nqs-/npa-/npv- 等保持)。

## 七、冻结边界确认

RouteCEnvCore-v1.0.0、ObservationSpec-v1、BinaryLongFlatAction-v1、
NetLogEquityReward-v1、MarketOpenCausalExecution-v1、
TerminalLiquidation-v1、LongFlatLedger、fee/slippage/tick/
reward/清算、Freqtrade 上游源码、Null qualification、friction、
power-analysis-v2、antithetic、Candidate 合同、training
attestation 信任根全部未修改;未开始 2.6.1/课程 PPO/训练/Dry-run/
真实交易。
