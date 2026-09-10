# 本轮改动面(相对基线 3e377add)

新增:
- stage2_6_1/runner/r17_v2_c13_profile.py   不可变工程 profile(计划/参数快照/claim/namespace 核对)
- stage2_6_1/runner/r17_v2_c13_batch.py     profile 驱动有限备援装配(三族;C3 fit p6/p7、eval p10/p11)
- stage2_6_1/runner/r17_v2_c13_pipeline.py  主实验编排 + stdlib 冷读 verify
- stage2_6_1/runner/r17_v2_c13_source_lock.py 26 模块执行来源闭包锁
- stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_r17_v2_c13_pipeline.py 24 项局部测试(A01-A22)

修改(最小增量):
- src/rl_curriculum/curriculum261_api.py        R17 namespace 89->93(+4 v2c13)
- src/rl_curriculum/curriculum261_r17_registry.py 同步对齐(断言强制)
- src/rl_curriculum/curriculum261_r17_routing.py 新 v2c13 路由类(R17_V2C13_ROLE_FIT_NAMESPACE
  + eval namespace 两项映射 + R17BundleRouting.v2c13 标志 + build/require 分支;旧四类路由合同不变)

固定基线核对:HEAD=3e377add=远端;vendor pin 52bc96f4 在位;发布/部署树同步(r17_sync.sh 官方面)。

已知未完成(按 §9 S5 合同在主实验后不可修+重跑):
- 旧 governance 测试 test_registry_alignment 硬编码 89,本轮授权面内的"精确预期测试"更新
  (89->93)漏在 S1 完成;全量回归因此 1 failed(1937/1/7)。
- validate_proof 的 generator 身份检查为单族(C3)泛化缺陷:runtime['generator'] 仅记录
  C3 generator 身份,C1/C2 的 call envelope 携带各自 family_version,逐位比对必然
  mismatch。主实验第一请求即 fatal(见 main_run)。修复需下一轮任务书明确安排。
