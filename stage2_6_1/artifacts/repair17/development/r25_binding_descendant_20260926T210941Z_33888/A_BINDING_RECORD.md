# A 出口记录:执行绑定强制 + 当前计划锚

轮次:RouteC_R25_BindingAndDescendantClosure_v1;候选 721b314。
基线 4bbb31c;被修复反例 = 独立审查 §2.2(A-binding-1 缺绑定仍达
生成哨兵)与 §2.3(A-binding-2 甲计划绑定用于乙计划)。

## 实现(单一路径,直接 CLI 与 launcher 同规则)

1. **创建端锚必需**:`execution-binding --plan` 变为必填;绑定恒含
   `plan_digest`(当前计划经 `_load_plan` digest 复验后的锚)。
2. **运行端强制**:`run-coordinate` 的绑定核验从 `if args.execution_
   binding:`(可跳过)改为无条件执行 `_verify_execution_binding(path,
   measured, plan)`:
   - 缺参数/空值/文件不存在/不可读/不可解析 → 拒绝(rc=3,refusal
     日志含原因、实测身份、generation_boundary_calls=0),不创建
     坐标目录、不写 manifest/事件/seal;
   - 绑定自身 digest 合法但**缺 plan_digest 锚** → 拒绝("缺计划锚
     plan_digest(不能当完整许可)")——不退回无绑定路径;
   - 锚 ≠ 本次实际加载计划的 digest → 拒绝("计划锚不符…甲计划的
     绑定不能用于乙计划");计划文件移位但字节相同 → 锚相同,通过;
   - 既有入口/生成模块/启动器身份核验不变(错入口摘要继续零生成
     拒绝,rc=3);
   - `--allow-smoke`/`engineering_use` 不提供任何免检通道(A06)。
3. **无自动重签**:失败后不按当前环境重签绑定、不覆盖原绑定、生成
   后不补锚;launcher 前置一次性创建绑定(write-once)后全程复用,
   绑定文件已存在时 launcher 以 rc=3 退出且不覆盖(A07 实测)。

## 验收映射(真实 main/argparse;定向测试 51/51 绿,WSL 部署树)

| ID | 测试 | 关键断言 |
|---|---|---|
| A01 | test_a01_missing_binding_refused_pre_generation | 真旧研究计划只读副本+c01+省略绑定 → rc=3;refusal JSON boundary_calls.total=0;plan_digest=r25dp-54841c4f…;无 coord 目录/无 SEALED。空串/不存在路径/坏 JSON 三变体同拒 |
| A02 | test_a02_binding_of_plan_a_rejected_for_plan_b | 两份各自合法计划(摘要不同);A 的绑定原样用于 B → rc=3 "计划锚不符";零生成;无 coord_s1 |
| A03 | test_a03_selfconsistent_binding_without_anchor_rejected / …_creation_requires_plan | 重算 binding_sha256 的无锚绑定拒绝;创建端缺 --plan 为 CLI 错误且不落文件 |
| A04 | test_a04_existing_identity_guards_still_hold + 上轮既有入口/模块错配测试 | 错入口摘要下继续 rc=3 零生成 |
| A05 | test_a05_relocated_identical_plan_passes | 计划移位同字节 → 绑定通过;4-block smoke 完成;manifest execution.binding.verified_ok=true;cold-read valid 且无来源限制标注(v2 manifest) |
| A06 | test_a06_engineering_and_smoke_flags_grant_no_exemption | 无绑定时 --allow-smoke 与否一律 rc=3;engineering 计划 c01 守卫保持 |
| A07 | TestLauncherWiringA07(smoke 成功/预存绑定不覆盖不重签 rc=3/坏坐标 DONE fail=1 零生成且绑定保留) | launcher 传递并核验同一计划绑定;binding.plan_digest==plan digest |
| A08 | 既有 plan-create/重复目标/三角色测试 + A05 smoke 来源记录 | 全部保持(42 项入口测试全绿) |

进程内哨兵(上轮 test_refusal_zero_generation_boundary_sentinel)
继续证明拒绝路径不触生成叶函数。

## 与旧件关系

旧 plan 不重签、不改;旧 11 坐标不重跑;本出口零研究生成
(smoke 仅 s1/s3 既有工程 namespace,≤4 blocks/语料,新临时目录)。
