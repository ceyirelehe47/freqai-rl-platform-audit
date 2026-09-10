# R17 V2 C1/C3 工程校准——诚实 FAIL 交付报告

**任务版本**：`R17V2C13EngineeringCalibration-v1`
**日期**：2026-09-10
**基线**：3e377add6f6b3ba68c24a50ccfffe7534983ca9b（父 5607876b…）
**结论**：**工程路径未完成（FAIL）**。主实验在第一个真实生成请求即因源码缺陷
fatal；按任务书 §3.3/§9 S3 与 README_AGENT 的硬合同（主实验开始后不自动修代码
重跑同一 profile、不 hotfix 续跑），本报告按真实失败状态交付。**未修码重跑、
未换 namespace、未扩备援、未补造证据。**

## 1. 三状态分立（任务书 §7）

| 状态 | 值 | 依据 |
|---|---|---|
| V2 C1/C3 工程路径与交付完成 | **false** | fit_main 第一请求 fatal（§2） |
| C1/C3 strict 工程统计结果 | **未产生** | 未到达任何评估阶段；不存在任何统计 PASS/FAIL |
| 正式资格签发 | **false** | 恒 false；无任何 formal 链接触 |

主 run 真实身份：`v2c13eng_20260910T140213_115963`
（监护 engineering kind，business_rc=3，run_record 完整落盘）。

## 2. 失败事实链（逐字可复核）

1. claim 于 14:03:10Z 消费（profile 级一次性；plan_sha256
   `bb539dfcaddab453a42b6597532a8995a29f11c9e14fc4448618130ae0be1a2a`）。
2. namespace 运行前核对：四个新 namespace 零命中（plan.json
   runtime.namespace_unused，原件在 main_run/monitored_run）。
3. fit_main 首个请求 `fit_main_c1_opportunity_D0_p0` 真实生成完成、
   envelope 证据完整落盘（requests/ + attempts/ 三层）。
4. validate_proof 分类阶段抛 `ProfileError: generator identity mismatch`
   → fatal → 全实验终止。result.json：status=generation_failed、
   rc=3、phase=fit_main_generation、fit_calls=[]（零次拟合——真实）、
   policy_evaluation_started=false（零策略评估——真实）。
5. **根因**：runtime['generator'] 仅记录 C3 generator 身份
   （cur261-c3-v4）；C1 的 call envelope 携带 cur261-c1-v5。
   v1 单族合同泛化到三族时该检查未按 family 分别对拍。
   （plan.json runtime.generator.family_version=cur261-c3-v4 vs
   request call_envelope.generator.family_version=cur261-c1-v5，
   见 main_run。）
6. 修复点明确且小（validate_proof 按 family 取 runtime['generators']
   [family] 对拍 + describe() 构造三族身份表 + 测试补三族 fixture），
   但属主实验后源码修复，**按合同留给下一轮任务书明确安排**。

## 3. 已真实完成的部分（全部有原件）

- **S1 实现**：不可变 profile（336/160/176/144/160/144 预算机器核对全过）、
  三族有限备援装配（C3 fit p6/p7、eval p10/p11；C1/C2 无备援权）、
  pipeline 编排、stdlib 冷读 verify、26 模块 source lock。
- **S1 局部测试**：24 passed（A01-A22 覆盖；local_tests/v2c13_local.log）。
  旧合同防回归 136 passed（reserve 69 + bridge 55 + R10 routing 12；
  local_tests/legacy_regression.log）。
- **S2 核对**：registry 93/4 对齐断言通过；routing v2c13 表安装；参数快照
  C3-D3=50.0/[0.20,0.36,0.44]、C1-D3 R4 继承、C2=historical control、
  R4 继承验证 pass（pack digest r6pk-6d73b07f…）。
- **S4 隔离（失败版）**：unshare --user --map-root-user --mount
  --propagation private；/mnt 与 /home/cryptorl/projects 双遮蔽成立
  （tmpfs 覆盖，原路径 FileNotFoundError 口径）；三负例全拒：
  healthy-fail 副本 rc=2（selection 缺失→不完整交付拒绝）、request 追加
  rc=2（evidence byte set mismatch）、result.json 翻绿 rc=2（同字节层拒绝）；
  原根 manifest c661c65e… 不变、result 保持 generation_failed/rc=3；
  源探针前后存在（isolation/WORK_DIR）。
- **S5 全量回归**：1937 tests / **1 failed** / 7 skipped / 1929 passed
  （attempt2_complete/monitored_run/junit.xml）。失败项
  `test_curriculum261_r17_governance_unit.test_registry_alignment`
  硬编码 `n_namespaces == 89`——本轮授权把 registry 扩到 93，该"精确
  预期测试"更新（§8.1 授权面）漏在 S1 完成；主实验后按 §9 S5
  （失败时保存原件，不能自动再跑第二次获取绿色）不再重跑。
  另有一次回归启动用法错误（相对路径 vs task-cwd）留档
  attempt1_usage_error（rc=4，无测试执行）。

## 4. 未执行部分（如实）

- 两个 fit bank 的 144/144 选定与两次 V2 拟合/重载/冻结：未到达。
- 160 对 C1/C3 eval 生成、scaled 评估、canonical 等价、R4/R5 strict
  统计：未到达（policy_evaluation_started=false）。
- C 阶段完整交付负例（缺 envelope/路由交换/统计翻绿/遥测追加）：交付件
  不存在，无法对其构造；已用失败版三负例覆盖可覆盖面。

## 5. 预算与消耗（真实）

- 计划 336 请求/1680 attempt；实际消耗 **1 个 pair 请求**
  （fit_main_c1_opportunity_D0_p0，A/B 两侧，内部 5 attempt 上限未耗尽
  即 accepted——attempt 证据在 main_run）。
- claim 已消费；四个新 namespace 已有 1 个坐标的真实生成记录
  （preplan_v2c13_fit_main_r17 的 c1/D0/p0）。**下一轮若安排新实验，
  须显式处置该 claim 与既有生成记录，不得静默复用。**

## 6. 归档与 Git

- 归档根：`stage2_6_1/artifacts/repair17/development/v2_c13_engineering_delivery/`
  （875 文件，24MB；task_pack/implementation/local_tests/namespace_check/
  main_run/verify_fail/isolation/full_regression）。
- 本轮普通提交并推送（不 amend、不 force-push）；提交内容=实现+测试+
  归档+失败证据原样。统计 FAIL 不存在（未产生），工程 FAIL 如实保留。
- 工作树中既有旧监护运行残留（T/M/未跟踪 runs/）不属于本轮，未混入提交。

## 7. 下一轮需要的明确安排

1. 是否授权修复 validate_proof 三族 generator 身份检查并处置已消费
   claim/既有单坐标生成记录后重开主实验（同 profile 或新版本号）。
2. 是否同步更新 governance 测试 89→93 预期（§8.1 授权面内）并重跑全量。
3. 旧 stage2_6_1/src 部署树（namespace 副本）与官方同步面（r17_sync.sh
   平铺到 $D/src/rl_curriculum）双结构并存的清理建议（本轮已确认真实
   import 面是后者；误用前者会被 regular/namespace 包解析规则遮蔽）。
