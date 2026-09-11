# S3 attempt1 的 11 failed / 4 errors 归因:torch 未屏蔽线程面

## 失败形态
全部失败/错误集中在 supervisor 直调形态测试:
- cold_copy ×4 (fixture ERROR: Supervisor rc=7)
- control_path ×2, fail_closed_integrity ×5, shutdown_budget ×1,
  stop_publication ×1, unified_shutdown ×1 (FAILED: rc=7)

run_record 的 control_failures:
  {"kind":"cutoff_capability_unavailable",
   "detail":"unshielded_threads:125468,125470,125471"}

## 根因链
1. r17_supervision._cutoff_thread_premise 全量扫描 /proc/self/task,
   任何未屏蔽 TERM/INT 的存活线程 → 前提失败 → rc=7(设计如此,
   与 v1 已有的 conftest BLAS 缓解注释所描述的问题同族)。
2. attempts_plan 的 TestPpoSmoke 在 pytest 进程内调用
   run_ppo_smoke → import torch → 创建未屏蔽 C 层线程。
3. 实测(zzz_thread_probe):attempts_plan 之后 pytest 进程含
   cuda0000240000a / pt_autograd_0 / cuda-EvtHandlr(3 个,
   与 run_record 的 unshielded 计数一致)。
4. v1 attempt2(同调用形态)当时通过:torch 在 GPU 直通不可用状态
   下不建 CUDA 线程;本轮宿主 GPU 状态不同触发懒初始化——环境
   漂移,非 v2 代码缺陷。
5. 顺序二分定位:attempts_plan(字母序第一) + cold_copy 即复现;
   单独 cold_copy 通过;c3_* 前缀组合通过。

## 修复(候选2)
- conftest: CUDA_VISIBLE_DEVICES='' setdefault(消除 pt_autograd_0
  与 cuda-EvtHandlr;与既有 BLAS 缓解同性质,只约束测试进程)。
- TestPpoSmoke 改子进程执行 run_ppo_smoke(torch 线程面留在子进程;
  断言语义不变,新增父进程线程数守卫)。
- 实测验证:attempts_plan+cold_copy 14 passed;
  attempts_plan+stop_publication 20 passed;
  r10_integration 后线程面仅 main+jemalloc(不触发)。
