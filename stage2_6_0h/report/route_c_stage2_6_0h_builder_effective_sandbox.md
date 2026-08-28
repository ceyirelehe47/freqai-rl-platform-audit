# 阶段 2.6.0h 收尾报告:Builder 后代执行、有效沙箱证明与 Attempt 选择策略闭环

- 基线提交:`6871d5e7b1b63477600435d9f3b30593a79a8d9a`(阶段 2.6.0g)
- 本阶段判定:**PASS**(全量回归 14 目录零失败;见第 12 节)
- Freqtrade 上游:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` clean 未修改
- 六项冻结交易合同未修改;未开始 2.6.1;未开始正式课程 PPO 训练

---

## 1. 阶段目标与修复清单

本阶段修复 2.6.0g 遗留的六项缺陷:

| # | 缺陷(任务书) | 修复 |
|---|---|---|
| 1 | Builder 可创建子进程,子进程 import 不进入父 Runner 的 runtime lock | seccomp 进程树策略(fork/vfork/clone3/execve/execveat/ptrace/process_vm_*/mount/umount2/unshare/setns/bpf/perf_event_open 全拒 EPERM;clone 仅允许 CLONE_THREAD 线程,clone3 返回 ENOSYS)+ 审计尝试计数(pidns 快照对已回收子进程不可见,`child_process_count = max(pidns 实测, 审计计数)`)+ RLIMIT_NPROC 附加防线 |
| 2 | Builder 可通过子进程、/dev/shm、/etc、/sys 使用未绑定外部状态 | pivot_root 最小 rootfs:宿主路径**不可命名**(stat 级 ENOENT);私有最小 /dev(null/zero/urandom/random/full + 独立 /dev/shm tmpfs + fd symlinks);空 /etc;/sys 不存在;全新 /proc 与私有 /tmp;Landlock /proc 最小文件集 |
| 3 | runtime lock 只哈希 RECORD,不验证实际安装文件 | lock v2 方案二:RECORD 作清单,对全部条目计算**实际文件内容** canonical digest(dcd-);修改 package 文件保持 RECORD 不变 -> digest 变化 -> 旧 evidence 失效;主进程 formal 期重算对账 |
| 4 | evidence 声称 first_pass 但未执行该选择规则 | attempt log v2 硬约束:编号 0 起严格连续唯一、选中前全 reject、选中是第一个且唯一 accept、选中后无条目、无 accept 构建必须失败;8 类违规负例全拒;策略进入请求/manifest/evidence/承诺 |
| 5 | evidence 只绑定期望 profile,未绑定实际生效沙箱 | Effective Sandbox Report(esb-):内核版本/namespace 身份/pidns 进程/netns 接口/mount 规范摘要/实际 rlimits/继承 fd/seccomp 模式与 filter 摘要(scp-)/行为探针(fork/exec 拒绝、宿主路径 ENOENT、/dev/shm 私有);进入 evidence 核心与承诺;13 项降级篡改矩阵全拒 |
| 6 | 主进程 checkpoint 前访问守卫只覆盖 open | 守卫 v2:覆盖 CPython 3.11 实际存在的全部事件(open/os.listdir/os.scandir/os.system/subprocess.Popen/ctypes.dlopen/os.exec 等);stat/access/readlink 无审计事件 -> 由 pivot_root 不可命名 + Runner 探针证明(方案 4);非 Builder-Runner 子进程违规(证明 Candidate 沙箱未启动) |

## 2. 工作包 A:后代执行禁止(A1/A2/A3)

- **A1 seccomp**(内核级,非 monkeypatch):Runner 在 import Builder 前经
  `prctl(PR_SET_NO_NEW_PRIVS)` + `seccomp(SECCOMP_SET_MODE_FILTER)` 安装
  确定性 BPF 过滤器。filter 由纯函数 `canonical_seccomp_filter()` 生成,
  摘要 `scp-d3e1689b…` 进入 profile(brp-)、沙箱报告(esb-)与 evidence;
  主进程重算摘要对账(代码被换即拒)。
  线程例外(`clone` 带 `CLONE_THREAD`)显式进入策略与 profile;线程与
  后代进程由测试区分(`test_thread_creation_allowed`)。
- **A2 native 加载**:audit hook 记录 `ctypes.dlopen` 全部目标;实际加载
  的 .so 从 `/proc/self/maps` 枚举并**内容绑定**(sha256),归属
  staging(npb- 绑定)/ distribution(RECORD)/ 系统前缀;其他位置
  (/dev/shm、/tmp、scratch)的 native library 一律拒绝。
- **A3 攻击矩阵**(真实隔离 Runner):子 Python import 未注册包(pytest)、
  /bin/sh、os.posix_spawn、fork+exec、ctypes.CDLL 自备 .so、外部可执行
  文件——全部在 pack 采信前失败(构建失败/锁拒绝 -> EXAM_INVALID 路径)。
- **任务书指定 PoC**(子进程 import 绕过):seccomp 关闭的演示 profile 下,
  子 Python import pytest 的版本输出进入 pack notes 且三次运行 hash 一致
  (输出确定性),但 pytest 不出现在父 Runner 锁内(v1 漏检证明);v2 语义下
  child_process_count/attempts>0 -> evidence 构造期拒绝;正常 profile 下
  seccomp 直接拒绝子进程创建。见 artifacts
  `child_process_import_bypass_rejection.json`。

## 3. 工作包 B:私有最小文件系统(B1/B2/B3)

bootstrap 在 mount namespace 内构造 newroot 并 `pivot_root` 切换:

- `/usr`(rbind,WSL 子挂载要求 rbind)+ conda env 按原路径只读挂载
  (exec_argv/sys.prefix 不变);
- staging(workdir)同路径 bind;runtime/builder_pkg 只读 remount(TOCTOU);
- 私有最小 `/dev`:tmpfs + 5 个设备节点 bind + **独立 /dev/shm tmpfs**
  (宿主 /dev 与 /dev/shm 整体不可见;每次运行全新挂载,precommit 双跑与
  exam replay 不共享可写状态);
- 全新 `/proc`(pidns 私有;Landlock 只授予 status/maps/mountinfo +
  /proc 与 /proc/self/fd 的 READ_DIR;`/proc/net/*` 因 Landlock 对 netns
  proc superblock 的规则不生效改为 `socket.if_nameindex()` syscall 级证明);
- 空 `/etc`;`/sys` 不存在(stat 级 ENOENT);私有 `/tmp` tmpfs。

B3 攻击:宿主 /dev/shm beacon 读取、跨运行 /dev/shm 通道、os.stat('/etc')、
os.listdir('/sys')、machine-id 读取、宿主临时目录、目录排序侧信道——
全部失败(ENOENT/Landlock/审计拒绝)。

## 4. 工作包 C:Effective Sandbox Report(C1/C2/C3)

报告由 Runner **实际运行**产生,含:kernel release;user/mount/pid/net
namespace 身份证明(userns root uid=0、pivot 应用、pidns=[1]、netns=[lo]);
Landlock ABI/handled rights/授权摘要(grt-,workdir 归一化);mount 规范
摘要(bootstrap 与 runner 两侧一致,workdir 占位);实际 rlimits
(getrlimit);继承 fd([0,1,2],稳定性过滤 listdir dup 噪声);seccomp 模式
(/proc/self/status 实测)+ filter 摘要;进程树策略与计数;**行为探针**
(fork/exec 尝试被拒 EPERM、宿主路径 ENOENT、/dev/shm 空)。

esb- 哈希进入 evidence 核心、承诺摘要,precommit 双跑一致、考试期第三次
重放一致。**降级矩阵**(13 项:seccomp 关、nnp=0、mount 摘要漂移、探针
泄漏、fd 越界、pidns 多进程、网络多接口、rlimit 未应用、filter 摘要不符、
允许 child、child/exec 计数>0、宿主可见)全部使校验拒绝。

## 5. 工作包 D:运行时依赖锁 v2(D1-D4)

- **D1**:锁记录 `process_tree_policy=single_builder_process`、
  `child_process_count`(聚合)、`child_process_attempts`(审计)、
  `exec_count`,进入 evidence。
- **D2**:distribution 内容摘要(dcd-)基于实际文件(方案二;conda-forge
  环境系统性改写安装文件,要求实文件==RECORD 声明的方案一在该环境不可行;
  方案二同样满足"改文件不改 RECORD 被发现":digest 变化 -> 旧 evidence
  失效);RECORD 缺失/无条目 fail closed;主进程 formal 期重算对账。
- **D3**:native .so 内容绑定与归属(staging/distribution/系统前缀),
  未绑定位置拒绝。
- **D4 攻击**:改 .py 保持 RECORD、替换 .so、同版本不同内容、动态 import
  未注册、子进程 import(PoC)——全部被发现或拒绝。

## 6. 工作包 E:first_pass attempt 策略(E1-E3)

attempt_policy `{policy: first_pass, max_attempts: N}` 显式进入冻结请求
(v3)、Builder manifest(v5)、Builder Run Evidence(nap-)、sealed
commitment(v9),verify 四方一致(`builder_attempt_policy_binding`)。
attempt log v2 硬约束与 8 类负例(两个 accept/重复编号/跳跃/超界/选中后
有条目/跳过首个合格/有 accept 未选中/输出 hash 不符)全部拒绝。

## 7. 工作包 F:evidence v2 对账

核心字段新增:effective_sandbox_hash(esb-)、access_summary_hash(acs-)、
process_tree_policy、child_process_count、exec_count、runner_isolation;
一致性从三组 hash 升级为**六组**(pack/attempt log/runtime lock/effective
sandbox/access summary + 进程树计数),双跑与重放按六组对账;detail 的
sandbox_report/access_summary/runtime_lock/attempt_log 全部重算哈希对账
(篡改 detail 绕过 bre- 的攻击被拒);公开组装通道使用确定性哨兵
(esb-public-assembly / in_process_public_assembly),私有通道必须真实 esb-
且哨兵冒充被拒。

## 8. 工作包 G:checkpoint 前访问证明

- 方案 4(主):pivot_root 使 checkpoint/sidecar/attestation 在 Builder
  沙箱内**不可命名**(Runner 报告探针 ENOENT 实证);
- 方案 3(辅):主进程 BuilderStageAccessGuard v2 覆盖实际存在的全部审计
  事件;`audit_result` 记录 covered_events 与 stat_coverage 说明;
- 非隔离-Runner 子进程(如 Candidate 沙箱启动)在 Builder 阶段出现即违规
  (Candidate 沙箱未启动证明);测试 monkeypatch 仅作测试。

## 9. 协议升级

| 协议 | 旧 | 新 |
|---|---|---|
| sealed commitment | v8 | **sealed-exam-commitment-v9**(v8 进弃用列表,from_json 带 0h 缺陷描述) |
| hidden exam CLI | v9 | **hidden-exam-cli-v10** |
| builder manifest | v4 | **null-pack-builder-manifest-v5**(attempt_policy 预注册) |
| builder runner | v2 | **builder-runner-protocol-v3** |
| build request | v2 | **builder-build-request-v3**(attempt_policy) |
| build result | v2 | **builder-build-result-v3** |
| attempt log | v1 | **builder-attempt-log-v2**(first_pass 合同) |
| runtime lock | v1 | **builder-runtime-lock-v2**(进程树+内容+native) |
| run evidence | v1 | **builder-run-evidence-v2**(新核心哈希) |
| runner worker | v1 | **builder-runner-worker-v2**(sandbox_report 字段) |
| runner profile | v1 | **builder-runner-profile-v2**(seccomp/私有 dev/proc 最小集) |

语义未变的 Route C 合同、Null qualification、friction、power、attestation、
Candidate runtime 协议未升级。拒绝 v8 及更早承诺、evidence v1、lock v1、
attempt log v1、无 effective sandbox report 材料、允许子进程材料。

## 10. 完整私有链路(工作包 I)

40 pair/5 attempts 私有 builder(两步 duration contract)→ precommit 双跑
(隔离 Runner:seccomp+pivot+私有 dev)→ evidence v2 → commitment v9 →
CLI v10 `--builder-evidence` 第三次重放(六组一致)→ duration/power/pack
validity 对账 → attestation + Candidate 沙箱 → **256-step PPO smoke 正常
FAIL**;篡改 esb- 的 evidence(重签)被 formal 拒绝。

## 11. 攻击矩阵汇总

| 攻击 | 结果 |
|---|---|
| 子 Python import 未注册包(3 次一致输出) | 正常 profile 拒绝(seccomp);演示 profile 证明 v1 锁漏检 + v2 计数暴露 |
| /bin/sh、posix_spawn、fork+exec、外部可执行 | 拒绝 |
| ctypes.CDLL 自备 .so(未绑定位置) | 锁拒绝 |
| 线程创建(CLONE_THREAD) | 允许(策略例外) |
| 宿主 /dev/shm beacon / 跨运行通道 | ENOENT/私有 tmpfs 拒绝 |
| stat/listdir /etc /sys / machine-id / 宿主 tmp / 目录排序 | ENOENT 或审计拒绝 |
| 13 项沙箱降级篡改 | 校验拒绝 |
| 改 .py 保 RECORD / 替换 .so / 同版本不同内容 | digest 变化+对账拒绝 |
| 8 类 attempt log 违规 | 合同拒绝 |
| v8 承诺 / v1 evidence / v1 lock / v1 log / 无 sandbox 材料 / 允许子进程材料 | 显式拒绝 |
| inspect.stack/argv/env 扫描(沿 0g) | 继续拒绝 |

## 12. 全量回归

| 目录 | passed | failed | skipped | xfailed | error |
|---|---|---|---|---|---|
| freqai_rl_platform_audit | 0 | 0 | 0 | 0 | 0 |
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0d | 57 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0e | 112 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0f | 64 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0g | 149 | 0 | 0 | 0 | 0 |
| route_c_stage2_6_0h | 94 | 0 | 0 | 0 | 0 |
| **合计** | **1340** | **0** | **0** | **0** | **0** |

要求与结果:failed=0、error=0、skipped=0、xfailed=0;0g 的 149 项与
0h 新增 94 项全部通过;未删除/弱化/跳过任何既有测试(历史目录仅按协议
升级同步断言与字面量)。

## 13. 冻结确认

- RouteCEnvCore-v1.0.0 / ObservationSpec-v1 / BinaryLongFlatAction-v1 /
  NetLogEquityReward-v1 / MarketOpenCausalExecution-v1 / TerminalLiquidation-v1 /
  LongFlatLedger / fee/slippage/tick rounding 未修改;
- Freqtrade 上游 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` clean 未修改;
- 仅使用 SB3 PPO + MLP Actor-Critic + 单资产现货 + Long/Flat;
- 未引入 LSTM/RecurrentPPO/GRU/TCN/Transformer/多资产;
- 未开始 2.6.1;未开始正式课程 PPO 训练。

## 14. 已知限制

1. conda-forge 环境的安装文件会被系统性改写(pyc 重编译/entry point 重写),
   D2 采用方案二(实际内容 digest)而非要求实文件==RECORD 声明;RECORD
   声明不一致计数进入 digest 输入(`.record_declared_mismatches`),但不
   fail closed。
2. CPython 3.11 对 os.stat/os.access/os.readlink 不发审计事件;stat 级
   不可利用由 pivot_root 不可命名保证(Runner 探针实证),主进程窗口依赖
   代码路径不含 checkpoint path + 守卫覆盖实际存在的事件。
3. seccomp filter 为 deny-list(默认 allow);syscall 编号为 x86_64 硬编码
   (策略载荷声明 arch=x86_64,跨架构需扩展)。
4. 已回收子进程在 pidns 快照不可见,进程树计数以
   max(pidns 实测, 审计尝试计数) 聚合;seccomp 的 EPERM 拒绝是最终防线。
5. `importlib.metadata` 的 `dist._path` 私有 API 沿用(0g 已记录),Python
   升级时需复核。

## 15. 交付物

- 本报告:`reports/route_c_stage2_6_0h_builder_effective_sandbox.md`
- artifacts:`artifacts/route_c_stage2_6_0h/`(17 项,见任务书清单)
- 测试:`tests/route_c_stage2_6_0h/`(9 文件 + conftest,94 项)
- 公开目录:`stage2_6_0h/`(报告/src/tests/artifacts/logs)
