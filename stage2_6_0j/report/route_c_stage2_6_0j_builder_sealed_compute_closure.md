# 阶段 2.6.0j:Builder 不可逆密封计算、内核动态状态、文件元数据与原生指令通道闭环

- 阶段:stage2_6_0j
- 基线:db13c06fae2a425eba80f19e59abbdce4d801335(stage2_6_0i)
- Freqtrade 上游固定:52bc96f4480b1a0da6a9b455bd00b17fbb6786a5(未漂移,工作树 clean)
- 环境:WSL2 CryptoRL-Ubuntu-24.04(内核 6.18.33.2-microsoft-standard-WSL2)/ conda freqtrade-rl / CPython 3.11
- 结论:**PASS**(判定对照见 §8;全部依据 full-cold)

## 0. 结论摘要

2.6.0i 的独立审查阻塞项(TSC 重开/default allow/硬件指令/文件元数据)全部以**机制收缩**方式闭环:

| 阻塞 | 2.6.0i 状态 | 2.6.0j 机制 |
|---|---|---|
| A:TSC 重开 | seccomp default allow,prctl 可用 | final filter **default deny**(prctl 未列即 EPERM);PR_TSC_ENABLE 攻击在 prctl 步骤失败 |
| B:内核动态状态 | sysinfo/getcpu/statfs 可调用 | default deny + 显式 deny 家族;sysinfo/getcpu/uname/sched_getaffinity/statfs/statvfs/xattr 全拒 |
| C:硬件原生指令 | RWX mmap 可执行 RDRAND 等 | PR_SET_MDWE(REFUSE_EXEC_GAIN,内核原生)+ final filter 拒一切 PROT_EXEC 映射;机器码页无法构造 |
| D:文件元数据 | bundle 内 stat 可读 | Compute 阶段 open/stat/statx/statfs/xattr/getdents 家族全拒;manifest 保持内容寻址(不纳入未承诺元数据) |
| (新)输入通道 | stdin/stdout 协议直通 | Seal 时 fd 隔离:stdin 关闭(EBADF)、fd1/2→/dev/null、唯一 RESULT_FD=87 单向输出、RESULT_ACK_FD=88 二次实测同步 |

结构升级为显式三阶段:**Prepare(可信)→ Seal(不可逆)→ Compute(纯计算)**。

## 1. 生产保证(机制层)

### 1.1 Prepare→Seal→Compute 阶段结构

```
Supervisor(评估主进程)
  └─ bootstrap launcher(userns/mountns/netns/utsns/pidns ->
     内容寻址 bundle rootfs -> pivot_root -> 挂载复验 -> Landlock ->
     rlimits -> exec Worker)
       └─ Worker Prepare(可信):
            v2 filter(arch/x32/进程/时钟/熵 deny-list)
            + vDSO 冻结 stub + PR_SET_TSC=SIGSEGV
            + native allowlist 预加载(Seal 前完成全部 dlopen)
            + builder 包逐模块顶层纯度 AST 验证
            + 受控 import(allowlist/闭包/逐文件哈希,全部在 build 前)
            + sealed compute report v2(report 阶段探针)
          quiesce 行 -> Supervisor 外部 /proc 实测(线程/映射/filter)
          ACK
       └─ Worker Seal(不可逆):
            PR_SET_MDWE=REFUSE_EXEC_GAIN(Linux>=6.14;本机原生支持)
            + fd 隔离(close(0);1/2→/dev/null;dup2 真实管道→87;
              dup stdin 读端→88;关闭其余 fd)
            + final compute filter 叠加安装(default deny + 参数过滤)
       └─ Worker Compute(build_pack 纯计算):
            pack = F(代码, 冻结请求, 提交运行时)——近似纯函数
          Runner 序列化 result -> RESULT_FD final 帧
          Supervisor 二次外部实测(存活窗口,经 ACK2 释放)-> 采信
```

结构约束(为什么必须三阶段):Seal 阶段自身需要的 prctl/seccomp/fd 操作
正是 Compute 要禁的 syscall;最终边界只能在 Prepare 完成、Compute 开始
之前安装。Worker 在 ACK 后进入不可逆状态,此后任何回退路径都是失败。

### 1.2 final compute filter(C1/C2/C3)

- default action:**EPERM**(未列 syscall 一律拒绝;错误处理合同统一);
- allowlist 由 strace 实测 CPython 3.11 纯计算段(brk/mmap/munmap/
  mremap/write)加运行时安全网(futex/signal/调度/退出)确定,共 19 项;
- 参数过滤(BPF 级,经典 BPF,seccomp_data 32 位高/低字均校验):
  - write:fd ∈ {1, 2, 87}(高位非零拒绝——防 64 位绕过 32 位比较);
  - read:fd = 88(RESULT_ACK_FD;Supervisor 在 final 帧之前不写入任何
    字节,Build 在 Compute 内读只会阻塞至超时自毁,无输入可泄漏);
  - mmap/mprotect:(prot & PROT_EXEC) == 0 且高位为零;
  - rt_sigaction:signal ∉ {SIGILL, SIGBUS, SIGFPE, SIGSEGV, SIGSYS}
    (禁止接管崩溃信号——含 PR_TSC_SIGSEGV 路径的边信道);
- 显式 deny 家族(未列即拒,载荷中逐族声明):进程/线程(fork/vfork/
  clone/clone3/execve/execveat)、状态控制(prctl/seccomp/arch_prctl/
  personality/ptrace/process_vm_*/setns/unshare)、时钟、熵(getrandom)、
  内核动态状态(sysinfo/getcpu/sched_getaffinity/uname/perf_event_open/
  bpf)、文件与元数据(open 族/read(参数外)/stat 族/statfs 族/xattr 族/
  getdents/lseek)、执行内存(mmap/mprotect/pkey_mprotect 含 EXEC/
  memfd_create/userfaultfd)、网络;
- BPF 程序 118 条指令,scf- 摘要进入 profile/lock/evidence/commitment;
- 内核级验证:真实安装后 18 类 syscall 探针(含 prctl(PR_TSC_ENABLE)/
  sysinfo/getcpu/uname/stat/statfs/openat/getrandom/clock_gettime/
  mmap RWX/mmap RX/memfd/clone/fork/socket/write 高位绕过/
  rt_sigaction sig11)全部 EPERM,mmap RW/brk/write(fd1)正常。

### 1.3 TSC 重开阻断(B1/G1)

时序:vDSO 冻结 → PR_SET_TSC=SIGSEGV → 可信初始化(含预加载)→
**final filter 安装** → build_pack。防线分两层(真实链路实测):

- 第一层(零 import 合同):攻击 Builder 以 `import ctypes` 获取
  prctl 句柄——该步在 Compute 违规清单即被拒(artifact
  prctl_tsc_reenable_attack.json 记录的失败点),构建 fail closed;
- 第二层(final filter,内核级直接证明):独立内核探针安装 filter
  后 raw `prctl(PR_SET_TSC, PR_TSC_ENABLE)` 实测返回 EPERM
  (prctl 未列入 allowlist,default deny),mmap RWX 同样 EPERM——
  即便攻击者经已加载句柄(CDLL(None))发起,prctl 也无法执行。

整个链路 fail closed,pack 不可能形成。RDTSC/RDTSCP 的另一层防线
(PR_SET_TSC_SIGSEGV 崩溃信号 handler 接管被 rt_sigaction 参数过滤
拒绝)同样生效。

### 1.4 不可逆 W^X / MDWE(B2)

- PR_SET_MDWE=REFUSE_EXEC_GAIN 在 Seal 首步设置(Linux >= 6.14;
  本机 6.18.33.2 原生支持,evidence 记录 supported/enabled/mode);
- 即使内核不支持,evidence 记录 supported=false 且 final filter 的
  PROT_EXEC 参数过滤是**同等级内核级后端**(不可卸载的叠加 filter),
  正式链不依赖单一机制;
- 攻击矩阵:mmap RWX / mmap RX / mmap RW→mprotect RX / memfd_create /
  pkey_mprotect / MAP_FIXED RWX / 已映射地址构造 callable 再调
  mmap RWX——全部失败;
- **开发期实测教训进入设计**:Seal 段自身曾因 `import fcntl` 触发
  lazy dlopen(fcntl.cpython-311 .so)导致 exec 映射增长;修复后
  Seal/Compute 段零 lazy import(fd 探测改用 os.close 的 EBADF 语义)。

### 1.5 native 调用能力(B3)

- 正式 Builder 依赖面(A3):纯 Python allowlist(abc/cmath/
  collections/dataclasses/datetime/decimal/enum/fractions/functools/
  hashlib/itertools/json/math/numbers/operator/re/statistics/string/
  time/typing/unicodedata)+ 受审计 native allowlist(math/cmath/
  hashlib 及 CPython 内建加速器);**第三方 native(NumPy 等)默认拒绝,
  NumPy 不具 formal eligibility**;
- compat profile 放开第三方 native(顶层 import 于 Prepare 完成并
  预热 lazy 子模块),formal_eligible=false,evidence 层拒绝其形成
  可信材料;0i 的 NumPy 闭包/native 绑定测试升级为 formal 拒绝 +
  compat 双跑一致双断言,未删除;
- Worker 在 Prepare 显式预加载全部 allowlist 模块,Seal 后零 dlopen;
- 即便 Builder 经 sys.modules 取得已加载 ctypes,CDLL(None) 的 raw
  syscall 与 mmap RWX 同样被 final filter 管辖(实测拒绝)。

### 1.6 文件与元数据通道(D1/D2/D3)

- Compute 阶段零文件访问:open/openat/creat/read(参数外 fd)/
  pread64/getdents64/lseek/stat/lstat/newfstatat/statx/statfs/fstatfs/
  access/faccessat/readlink/xattr 族全部未列入 allowlist(default
  deny);包内数据需求必须在 Seal 前读为已承诺不可变输入;
- 元数据攻击矩阵(真实链路):os.stat 的 st_ino/st_dev/st_nlink/
  st_mtime/st_ctime、raw statx、raw statfs、os.statvfs(f_bfree/
  f_files)、getxattr、目录项顺序——全部被拒;
- bundle manifest 保持内容寻址(path/type/size/mode/sha256),**不**
  纳入 inode/mtime 等未承诺元数据(那会摧毁内容寻址与双跑一致性:
  staging 每次组装 inode 必变);未承诺元数据的正确处理是**拒绝读取**
  而非承诺;
- 模块顶层元数据攻击(顶层 os.stat):资格阶段(纯度验证)拒绝。

### 1.7 硬件指令与原生执行通道(E1/E2/E3)

- 宿主能力探测(无沙箱真实执行,artifact 如实记录):CPUID/RDTSC/
  RDTSCP 真实可执行;RDRAND 的 **CPUID 位被 hypervisor 隐藏但指令
  真实可执行**(0x06100800 无 bit30,执行返回随机值)——证明"只看
  CPUID 位"会把 CPU 支持误报为不支持;RDSEED 可执行;RDPID 亦真实
  可执行(返回非零值;早期探测的 #UD 是机器码编码错误所致,最终
  探测修正后按真实执行记录);
- 沙箱内攻击(RWX 页执行 RDRAND/RDSEED/RDPID/CPUID/RDTSC/RDTSCP
  机器码):全部因 PROT_EXEC 映射被拒而失败——**无论 CPU 是否支持
  该指令,机器码页本身无法构造**;
- 执行路径矩阵:ctypes CDLL(文件)/CDLL(None)+raw syscall/cffi/
  mmap 模块/ExtensionFileLoader/SourceFileLoader/zipimport/scratch
  .so/bundle 内未声明 .so/预加载函数指针再 mmap RWX——全部失败。

### 1.8 fd 与协议通道(A4/G7)

- Seal 时:close(0)(stdin 彻底关闭,read→EBADF);fd1/2 重定向
  /dev/null(print/os.write 全部无害丢弃,Supervisor 不可见);
  真实 stdout dup2 到 RESULT_FD=87;原 stdin 读端 dup2 到
  RESULT_ACK_FD=88;关闭 3..65535 中其余 fd;
- RESULT_FD 是唯一真实通道,且只由 Runner 在 build_pack 返回后写入
  (同进程内 Builder 代码在 build 返回后不再执行;build 内注入行会
  破坏"恰好一行 final 帧"的协议状态机 → Supervisor fail closed,
  实测注入攻击全部失败);result 的一致性另由 Supervisor 侧
  ExamPack/attempt log/lock 全量校验锚定;
- Supervisor 在 final 帧后、Worker 退出前(Worker 阻塞在
  RESULT_ACK_FD)做**第二次外部 /proc 实测**:线程仍 1、后代仍 0、
  seccomp filter 数 ≥2(叠加被证明)、exec 映射零增长;完成后写
  ACK2 释放 Worker。

### 1.9 顶层纯度与动态 import(A1/A2/G6/G8)

- AST 静态:顶层仅允许 allowlist import / def / class(类体同规则)/
  字面量赋值 / docstring;G8 全形态(顶层 time/random/os.stat/
  sysinfo/getcpu/ctypes/thread/open/comprehension 调用)被拒;
- 运行时(toplevel 阶段):audit hook 只禁 import 机制自身不会产生的
  事件(os.system/subprocess/ctypes.dlopen/os.fork/os.exec/builtins.
  input)——importlib 的 open/compile/exec 与受审计库初始化
  (OpenBLAS 的 os.putenv)是合法足迹;模块身份由导入闭包逐文件
  绑定 bundle manifest 管辖;
- Compute 阶段零容忍:import/open/os.listdir/exec/compile/ctypes.
  dlopen 等任何一次出现即拒绝采信(实测 `import math`/`__import__`
  缓存命中同样违规——允许缓存命中等价于允许 sys 等危险模块);
- 动态加载矩阵:importlib/reload/marshal code object/pickle callable/
  sys.modules 篡改/meta_path hook/zipimport/SourceFileLoader/
  ExtensionFileLoader——机制层(open 被拒)+语义层(违规清单)双拒。

## 2. 测试证明(full-cold#4:全部 15 目录 1556 passed / 0 failed / 0 skipped / 0 xfailed / 0 error,all_green=True;其中 0j 目录 94 项)

测试文件与覆盖(全部真实生产路径:完整沙箱、真实 syscall、无 mock
降级):

| 文件 | 覆盖 |
|---|---|
| test_final_seccomp_default_deny.py | C1/C2/G9:default EPERM/allowlist 精确集/参数限制声明/BPF 模拟器 24 例(含高位绕过)/未知 syscall 编号统一 EPERM/sysinfo 链路攻击 |
| test_tsc_reenable_and_wx.py | B1/B2/G1/E2:PR_TSC_ENABLE 攻击(prctl 包装与 raw)/mmap RWX/mprotect W→X/memfd/pkey_mprotect/预存地址 callable;MDWE 真实链路生效证明 |
| test_fs_metadata_attack.py | D/G3:st_ino/st_dev/nlink/mtime/raw statx/statfs/statvfs/xattr/目录序/Compute 读写/顶层 stat 资格拒绝 |
| test_hardware_instruction.py | E1/G4:宿主真实执行能力矩阵(区分 CPU 支持与生产阻断)/RDRAND/RDSEED/RDPID/CPUID/RDTSC/RDTSCP 沙箱攻击/AST 顶层 ctypes/time/random 拒绝 |
| test_native_ffi_attack.py | B3/G5:CDLL 文件/CDLL(None) raw syscall/cffi/mmap 模块/ExtensionFileLoader/scratch .so/bundle 未声明 .so/函数指针升级 |
| test_dynamic_import_attack.py | A2/G6:import/`__import__`/importlib/reload/eval/exec/compile/marshal/pickle/sys.modules/meta_path/zipimport/SourceFileLoader |
| test_protocol_fd_attack.py | A4/G7:读 stdin(EBADF 证明)/fd1/2 无害写/RESULT_FD 注入 fail closed//proc/self/fd 不存在/未来 ACK 不可读/fd 隔离证据 |
| test_top_level_purity.py | A1/G8:10 类顶层攻击 AST+真实链路双拒/合法顶层字面量通过/类体同规则 |
| test_sealed_compute_protocol.py | A3/F1/F3:依赖策略 formal/compat/报告 v2 全字段/协议版本/0i 旧材料拒绝(edic-v1/v3 evidence 重签)/default allow 载荷冒充/filter 摘要篡改 |
| test_full_private_pipeline_v11.py | 十二:完整链路(40 pair/5 attempts/两步 duration contract/precommit 双跑/承诺 v11/CLI v12 第三次重放/256-step smoke FAIL/17 类篡改全 EXAM_INVALID) |

0i 目录适配(等强度语义映射,零删除):协议版本断言升级(v4/v11/v12
+final policy v3/scf-)、scratch/proc 可写可见性语义迁移(EDIC 实测
证明 + Compute 拒绝强断言)、NumPy 升级为 formal 拒绝 + compat 顶层
import 双跑一致 + formal_eligible=false、replay 对比键组扩展(scf-/
依赖策略)。0f conftest 的 helpers 模板 json.loads 顶层调用升级为
字面量(测试资产升级,非断言弱化)。

## 3. 完整私有链路复验(十二)

链路(全部通过):stdlib-only 私有 Builder(pair_count_per_family=
40, max_attempts=5, first_pass)→ 两步 duration contract → 内容寻址
runtime bundle → Prepare(纯度/闭包/EDIC v2)→ quiesce 外部实测 →
ACK → Seal(MDWE/fd 隔离/final filter)→ Compute → final(RESULT_FD)
→ 二次实测 → precommit 双跑(九组键全一致)→ evidence v4 → 承诺
v11 → hidden CLI v12 第三次重放(九组一致)→ duration/power/pack
validity → trusted attestation → Candidate 沙箱 → 256-step PPO
smoke → 正常 FAIL;全部 15 类篡改 EXAM_INVALID(沿用 0i 的 6 类
(含 final filter 哈希)+ 任务书十二新增的 9 类);
Candidate/checkpoint
在整个 sealed-compute 链闭合后才可见。

## 4. 环境与能力记录(如实,不伪装)

- PR_SET_MDWE:内核 6.18.33.2 原生支持(rc=0),evidence 记录
  enabled=true;不支持的内核上 evidence 记录 supported=false 且
  final filter 参数过滤作为同级后端(不 fail,因为后端充分);
- RDRAND:CPUID 位被 hypervisor 隐藏但指令真实可执行——本阶段如实
  记录并按"CPU 支持"处理(生产阻断不依赖 CPUID 位);
- RDPID:宿主真实可执行(artifact 如实记录);沙箱内攻击因
  exec 页无法构造被拒(与 CPU 支持无关);
- audit 事件可用性实测:open/os.listdir/compile/exec/import/
  ctypes.dlopen 存在;os.stat 无 audit 事件(由 AST+syscall 两层
  覆盖)。

## 5. 与 2.6.0i 材料的互斥(F3)

- 承诺 v10 进入弃用列表(v11 校验拒绝);
- edic-v1 报告被 sealed-compute-report-v2 校验拒绝;
- v3 evidence / v3 lock / v3 worker 协议被 v4 执行器拒绝(重签
  攻击:补 format 与哈希仍缺 sealed_compute 语义字段);
- 2.6.0i 目录的审计材料与 artifacts 保留不动(历史证据),但不再
  能进入任何新承诺。

## 6. 回归(十三)

- full-cold#4(20260830-082406):wall 5049s,totals {passed:1556, failed:0, skipped:0, xfailed:0, error:0},all_green=True;
- regression_runner 修复:tests/freqai_rl_platform_audit 从 pytest
  test-target manifest 移除(方案 1,诊断目录单列
  DIAGNOSTIC_DIRS);exit 5 特判删除——全部 test targets 必须
  exit 0;
- 0j 目录接入 ALL_DIRS/EXCLUSIVE_DIRS(攻击矩阵与 0h/0i 同性质
  独占)/RULES/COMMITMENT_CHAIN/CONFTEST_IMPORTERS;
- quick=0j 目录;affected 按 RULES(builder runtime/builder_* 触发
  0f..0j;承诺链触发全部);full-cold 全部目录零失败零 skipped
  零 xfailed 零 error(数字见 regression_test_summary.md 与
  regression_fullcold_summary.json)。

## 7. 冻结边界确认(十四)

未修改:RouteCEnvCore-v1.0.0/ObservationSpec-v1/
BinaryLongFlatAction-v1/NetLogEquityReward-v1/
MarketOpenCausalExecution-v1/TerminalLiquidation-v1/LongFlatLedger/
fee/slippage/tick rounding/reward/terminal liquidation/Freqtrade
上游源码/Null qualification/friction 公式/power-analysis-v2/
antithetic pair/Candidate observation-action contract/training
attestation 信任根。

Builder native 收紧不影响 Candidate/PPO/SB3/PyTorch/Freqtrade/
FreqAI/训练环境 NumPy。

未开始:2.6.1、C1/C2/C3 generator、正式课程 PPO、容量选择、历史
Alpha 训练、Dry-run、真实交易。

## 8. PASS 判定对照(十五;全部依据 full-cold#4)

| # | 条件 | 结果 |
|---|---|---|
| 1 | Builder 无法重开 TSC | ✓(prctl 未列 allowlist,EPERM) |
| 2 | PR_TSC_ENABLE→RDTSC 真实失败 | ✓(test_tsc_reenable,含 raw prctl 变体) |
| 3 | Compute filter default deny | ✓(EPERM;载荷/BPF/实测三重) |
| 4 | unknown syscall 真实被拒 | ✓(G9:未列编号统一 EPERM) |
| 5 | sysinfo/getcpu 不能影响 pack | ✓(链路攻击 fail closed) |
| 6 | 元数据不能影响 pack | ✓(stat/statx/statfs/statvfs/xattr 矩阵) |
| 7 | Compute 无文件访问 | ✓(open/read(参数外)/getdents/lseek 全拒) |
| 8 | Compute 无动态 import | ✓(违规清单+syscall 双层,缓存命中同样违规) |
| 9 | Compute 无追加输入 | ✓(stdin 关闭/read 仅 ACK fd 且无字节) |
| 10 | 无法创建 executable memory | ✓(MDWE+参数过滤;7 类路径矩阵) |
| 11 | 无法调用 ctypes/cffi/任意地址 | ✓(native 矩阵;CDLL(None) 同拒) |
| 12 | RDRAND 等被生产机制关闭 | ✓(exec 页不可构造;能力矩阵如实记录) |
| 13 | 线程/进程为零 | ✓(quiesce+二次实测均 1 线程/0 后代) |
| 14 | sealed compute 进 evidence/commitment | ✓(v4 字段+scf-+v11 承诺) |
| 15 | 0i 材料显式拒绝 | ✓(§5) |
| 16 | 完整 private pipeline 校验通过 | ✓(§3) |
| 17 | 全部 test targets exit 0 | ✓(full-cold,exit5 特判已删) |
| 18 | 零失败/零 skipped/零 xfailed/零 error | ✓(1556/0/0/0/0) |
| 19 | Freqtrade 固定且 clean | ✓(52bc96f) |
| 20 | 冻结合同未修改 | ✓(§7) |
| 21 | 未开始下一阶段 | ✓ |
