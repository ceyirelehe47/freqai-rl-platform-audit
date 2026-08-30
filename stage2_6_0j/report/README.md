# stage2_6_0j:Builder 不可逆密封计算、内核动态状态、文件元数据与原生指令通道闭环

- 基线:db13c06fae2a425eba80f19e59abbdce4d801335(stage2_6_0i)
- 主报告:`report/route_c_stage2_6_0j_builder_sealed_compute_closure.md`
- artifacts:`artifacts/`(23 项,真实运行派生)
- 结论:**PASS**(仅依据 full-cold;数字见 artifacts/regression_test_summary.md)

## 目录

- `src/rl_builder_runtime/`:Worker 侧运行时(sealed_compute.py 为本阶段
  新增核心:final compute filter/MDWE/fd 隔离/顶层纯度 AST/依赖策略);
- `src/rl_curriculum/`:Supervisor 侧(profile v4/协议循环/二次实测/
  lock v4/evidence v4/承诺 v11/CLI v12);
- `tests/route_c_stage2_6_0j/`:新增测试目录(94 项,全部真实生产路径);
- `tests/route_c_stage2_6_0{b,c,d,e,f,g,h,i}/`:等强度语义适配的
  历史测试文件(版本断言升级/NumPy formal 拒绝/Compute 文件通道语义
  迁移;零删除);
- `runner/`:regression_runner(exit 5 修复 + 0j 接入)/选择规则/
  artifacts 生成脚本/回归入口。

## 核心语义(Prepare -> Seal -> Compute)

- Prepare(可信):v2 filter + vDSO 冻结 + PR_SET_TSC + native 预加载 +
  顶层纯度 AST + 导入闭包(全部在 build 前);
- Seal(ACK 后不可逆):PR_SET_MDWE(REFUSE_EXEC_GAIN) -> fd 隔离
  (stdin 关闭/1,2->/dev/null/RESULT_FD=87/ACK_FD=88) -> final compute
  filter(**default deny** + 最小 allowlist + write/mmap/mprotect/
  rt_sigaction 参数过滤);
- Compute:build_pack 纯计算;任何未列 syscall EPERM;prctl 被拒
  (TSC 无法重开);open/stat/statfs/sysinfo/getcpu/uname/getrandom/
  clock/PROT_EXEC/线程/进程全拒;Compute 内 import/open/exec/compile
  违规清单拒收;build 返回后 Runner 经 RESULT_FD 单向输出;
- Supervisor 二次实测(final 后 Worker 存活窗口,ACK2 释放):线程 1/
  后代 0/filter 叠加 >=2/exec 映射零增长。
