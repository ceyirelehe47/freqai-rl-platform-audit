# 阶段 2.6.0h:Builder 后代执行、有效沙箱证明与 Attempt 选择策略闭环

- 基线:阶段 2.6.0g(commit `6871d5e`)
- 判定:**PASS**(独立验收 ACCEPT,25/25)
- 全量回归:**1340 passed / 0 failed / 0 skipped / 0 xfailed / 0 error**
  (14 目录;2.6.0g 基线 1246 项全部保留,本阶段新增 94 项)
- Freqtrade 上游 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5` clean 未修改;
  六项冻结交易合同未修改;未开始 2.6.1 与正式课程 PPO 训练

## 本阶段修复(相对 2.6.0g)

1. **A|后代执行禁止**:Runner 在 import Builder 前安装 seccomp 进程树
   策略(fork/vfork/clone3/execve/execveat/ptrace/process_vm_*/mount/
   umount2/unshare/setns/bpf/perf_event_open 全拒 EPERM;clone 仅允许
   CLONE_THREAD 线程;RLIMIT_NPROC 附加防线)。filter 为确定性 BPF 纯函数,
   摘要(scp-)进入 profile/evidence 并被主进程重算对账。
2. **B|私有最小文件系统**:bootstrap 以 pivot_root 切换到最小 rootfs——
   宿主路径不可命名(stat 级 ENOENT);私有最小 /dev(5 节点 + 独立
   /dev/shm tmpfs,宿主整体不可见,跨运行无共享);空 /etc;/sys 不存在;
   全新 /proc(pidns)与私有 /tmp;Landlock /proc 最小文件集。
3. **C|Effective Sandbox Report(esb-)**:Runner 实际运行产生——内核/
   namespace 身份/pidns 进程/netns 接口/mount 规范摘要(bootstrap 与
   runner 双侧一致)/实际 rlimits/继承 fd/seccomp 实测/fork-exec-宿主路径
   行为探针;进入 evidence 核心与承诺;13 项降级篡改矩阵全拒。
4. **D|运行时依赖锁 v2**:进程树字段(single_builder_process/计数);
   distribution **实际文件内容** canonical digest(dcd-,RECORD 作清单;
   改文件不改 RECORD -> 旧 evidence 失效;主进程 formal 期重算对账);
   native .so 内容绑定与归属(未绑定位置拒绝)。
5. **E|first_pass attempt 策略**:策略显式进入冻结请求/manifest/evidence/
   承诺(四方一致);attempt log v2 硬约束(编号 0 起连续唯一、选中前全
   reject、选中是第一个且唯一 accept、选中后无条目、无 accept 不得产出
   pack);8 类违规负例全拒。
6. **F|evidence v2**:核心新增 esb-/acs-/process_tree/child/exec 计数/
   isolation;一致性从三组 hash 升级为六组;detail 全量重算对账防篡改;
   组装通道哨兵与私有通道真实 esb- 区分。
7. **G|checkpoint 前访问证明**:方案 4(pivot 不可命名 + Runner 探针)
   + 方案 3(守卫 v2 覆盖 CPython 3.11 实际存在的全部审计事件;非
   Builder-Runner 子进程违规即 Candidate 沙箱未启动证明)。
8. **协议升级**:sealed-exam-commitment-v9 / hidden-exam-cli-v10 /
   null-pack-builder-manifest-v5 / builder-runner-protocol-v3 /
   builder-build-request-v3 / builder-build-result-v3 /
   builder-attempt-log-v2 / builder-runtime-lock-v2 /
   builder-run-evidence-v2 / builder-runner-worker-v2 /
   builder-runner-profile-v2。v8 承诺、v1 evidence/lock/attempt log、
   无 effective sandbox report、允许子进程的材料全部显式拒绝。

## 任务书指定 PoC

Builder 父进程 -> subprocess 子 Python -> 子 Python import 未注册第三方
(pytest) -> 确定性输出:修复前(演示 profile)v1 锁漏检子进程 import
(三次输出一致而 pytest 不在锁内);修复后 seccomp 拒绝子进程创建,
正常 profile 下构建失败被拒。见
`artifacts/child_process_import_bypass_rejection.json`。

## 目录

- `report/` 最终报告(工作包 A-I、协议表、攻击矩阵、回归表、已知限制)
- `src/` 本阶段触及源码(rl_builder_runtime 全部 + rl_curriculum 九个文件)
- `tests/route_c_stage2_6_0h/` 9 个测试文件(94 项;真实隔离 Runner 攻击)
- `artifacts/` 17 项(进程树/私有 dev/降级矩阵/内容锁/tamper/策略矩阵/
  evidence v2/预访问/PoC/管线/旧材料拒绝/回归汇总/原始日志/上游完整性)
- `logs/` 全量回归原始日志

## 复现

```bash
# WSL(CryptoRL-Ubuntu-24.04)+ conda freqtrade-rl
source ~/miniforge3/etc/profile.d/conda.sh && conda activate freqtrade-rl
cd ~/projects/crypto_rl
python -m pytest tests/route_c_stage2_6_0h -q          # 94 passed
# 全量回归逐目录执行(见 artifacts/regression_test_summary.md)
```

## 限制

见报告第 14 节(conda 环境采用方案二内容摘要、CPython 3.11 无 stat 审计
事件由 namespace 不可命名兜底、seccomp deny-list x86_64、已回收子进程以
审计计数聚合、dist._path 私有 API)。
