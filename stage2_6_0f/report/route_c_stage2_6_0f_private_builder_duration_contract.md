# 阶段 2.6.0f 报告:私有 Builder 身份与 Null 时长合同最终闭环

- 阶段:2.6.0f
- 日期:2026-08-27
- 基线提交:aa80c2d29082fa508202fef75ab0fdc600f24aba(阶段 2.6.0e)
- 结论:**PASS**(等待独立审查;未开始 2.6.1,未开始正式课程 PPO 训练)

## 一、修复的三个遗留问题

1. **formal verifier 无参数调用默认公开 mock builder**:阶段 2.6.0e 的
   `verify_sealed_commitment`(12c)/`validate_null_pack`(报告
   `builder_manifest_hash` 字段)/`pack_builder_code_hash` 包装在正式路径
   上无参调用 `pack_builder_manifest_hash()`,默认绑定公开 mock builder,
   没有正式的评估方私有 Builder Identity Provider。
2. **builder manifest 只绑定手工挑选的函数清单**:v1 manifest 通过
   `_fn_binding` 逐函数源码哈希挑选 assemble/attempt/seed/pair/validator
   等函数,遗漏实际决定 attempt 是否被接受的中间链路
   (`_validate_pack_ephemeral`、`build_spec_for_pack`、
   `_verify_pair_*` 子函数、salt 常量值、family 列表真源等)。
3. **duration 从第一个/最后一个 null_control Episode 推导**:
   `sealed_exam.py` 取第一个(break 语义)、`formal_exam.py` 取最后一个
   (循环覆盖)、多处 `.get("episode_bars", 96)` 静默回退;同一 sealed
   exam 中不同 strict Null family / pair 可以使用不同 resolved duration
   而不被发现。

## 二、工作包 A:正式 Builder Identity Provider(新增
`src/rl_curriculum/builder_identity.py`)

- **Provider 抽象**(`BuilderIdentityProvider` 协议):提供 canonical
  manifest、manifest hash(npb-)、builder protocol 版本、非敏感公开摘要
  (`BuilderIdentity.public_digest`);在评估环境中重新计算,不读取任何
  自报 hash。
- **信任源隔离**:Provider 是评估方可信主机输入;不从候选 checkpoint、
  sidecar、考试 pack、考试 context 获取信任;不进入 Candidate 沙箱
  (`SandboxedCandidate` 签名无 builder/provider 参数);sealed-exam-
  context-v3 **不新增**任何 builder provider 信任根字段。
- **formal API 显式接收**:`run_sealed_exam(builder_provider)`、
  `verify_sealed_commitment(builder_identity, duration_contract)`、
  `validate_null_pack(builder_identity, duration_contract)`、pack
  validity report 生成的 `provider_builder_manifest_hash(identity)`。
  缺失即 fail closed(EXAM_INVALID);**删除**了
  `pack_builder_manifest` / `pack_builder_manifest_hash` /
  `pack_builder_code_hash` 三个无参 mock 入口(源码级不存在)。
- **CLI(v7)**:`--builder-provider {mock,private}` 必填;private 需
  `--builder-provider-root`(评估方只读配置 `provider_config.json` 声明
  entrypoint/参数);缺 provider CLI exit 2 且执行器对 None fail closed。
- **Mock/Private 双实现**:公开 mock 流程显式传入
  `MockBuilderIdentityProvider`;测试私有流程用
  `PrivateBuilderIdentityProvider`(临时/私有目录,不进 Candidate
  runtime,不进公开承诺)。

## 三、工作包 B:builder 完整依赖闭包(null-pack-builder-manifest-v2)

- **package tree manifest**:受信 root 下全部文件(含资源)逐文件
  sha256,相对路径 posix 排序稳定;拒绝 symlink/缺失文件;额外文件不能
  被静默忽略(全部进入文件清单);路径必须位于受信 root 内;不扫描候选
  可写目录。mock Provider 的 root = rl_curriculum 包(37 个文件),实际
  attempt 选择链的中间依赖(assemble/attempt loop/
  `_validate_pack_ephemeral`/`build_spec_for_pack`/null materialization/
  seed 与 pair 推导/validator 子函数/BASE_PARAMS/family 真源)全部被
  tree 覆盖——不再依赖人工补函数名。
- **显式外部依赖 manifest**:rl_platform package tree hash + python/
  numpy/pandas 运行时版本(依赖模块身份明确绑定)。
- **语义字段**:params_spec(BASE_PARAMS)、families(与
  `FORMAL_NULL_FAMILIES` 真源一致)、pair_count、max_attempts、
  signature_policy(v1 的签名禁止参数动态检查在 Provider 侧保留:
  `check_builder_signature_policy`)。
- **三方一致**:承诺 npb-、pack validity 报告 `builder_manifest_hash`、
  formal verifier 全部来自同一 Provider 派生的 identity
  (`provider_builder_manifest_hash` 是唯一入口)。

## 四、工作包 C:全局 strict Null duration contract(新增
`src/rl_curriculum/null_duration_contract.py`)

- **唯一推导函数** `derive_global_null_duration_contract`:收集所有
  required strict Null family 的**全部** null_control Episode,逐条
  `resolve_duration`(fail closed),resolved 值集合大小必须为 1;合同
  含 timeframe / bar duration seconds / resolved bars / resolved
  duration seconds/hours / 解析规则版本(rps- 引用)。
- **比较 resolved 值而非原始参数文本**:`episode_bars=96` 与
  `duration_hours=24`(15m)解析为完全相同的合同,允许;原始声明自相
  矛盾仍由参数解析器拒绝。
- **删除语义**:verify/spec 构建不再取第一个 Episode;执行器 4b 不再取
  最后一个 Episode;`null_qualification.py` 与测试辅助不再 `.get(96)`
  静默回退;正式路径源码无 `episode_bars.*96` 默认值(测试断言)。
- **Commitment v6 绑定**:`null_duration_contract`(公开 payload)+
  `null_duration_contract_hash`(ndc-);from_json 校验 payload 与 hash
  自洽。
- **全链路对账**:qualification spec(nqs-)用合同 resolved bars 构建;
  family reports 经 nqs- 对账;power 重跑用合同 bars 重建 spec;pack
  validity 报告(v3)新增 `duration_contract_hash` + `duration_contract`
  字段进入 npv- hash;任一不一致 → EXAM_INVALID(不判候选 FAIL/作弊)。

## 五、工作包 D:协议升级与执行顺序

升级(语义变化):
- `sealed-exam-commitment-v5 → v6`(v5 进弃用列表;缺 ndc- 的旧承诺
  被拒绝)
- `null-pack-builder-manifest-v1 → v2`(v1 手工函数清单材料被拒绝)
- `null-pack-validity-v2 → v3`(v2 进弃用列表;v2 报告被构建层拒绝)
- `hidden-exam-cli-v6 → v7`

未升级(语义未变):null-friction-contract-v2、null-qualification-
spec-v2、null-power-analysis-v2、null-qualification-v4、checkpoint-
manifest-v3、training-attestation-v1、candidate-runtime-manifest-v1、
sealed-exam-context-v3(测试断言)。

**正式执行顺序(D1,全部 integrity gate 先于候选 checkpoint 加载与
沙箱启动;测试以沙箱 spy 断言)**:
1. 加载 commitment、pack、评估方 Provider;
2. 验证 pack 未退休;
3. 从全部 strict Null specs 派生全局 duration contract;
4. 重算实际(私有)builder identity;
5. 验证 sealed commitment v6(npb- 对账先于昂贵的 power 重跑);
6. 重跑完整 power-analysis-v2;
7. 物化 pack(从第 3 步后移,materialize 现在发生在验证之后);
8. 重算 null-pack-validity-v3;
9. 验证 training attestation 与 checkpoint;
10. 启动 Candidate 系统沙箱(checkpoint 在沙箱内加载);
11. 执行 G4 / Null / 反作弊考试。

## 六、测试(route_c_stage2_6_0f,64 项全部通过)

- `test_builder_identity_provider.py`:formal API 必填、无参 mock 入口
  源码级删除、mock 显式、context/checkpoint/pack 无 provider 声明通道、
  v1 manifest 拒绝、Provider/Candidate 隔离。
- `test_private_builder_formal_integration.py`:A4 四场景(A+A+A PASS;
  A+A+B EXAM_INVALID;修改 A 后旧承诺失效;Provider 缺失 EXAM_INVALID)
  + 完整 `run_sealed_exam`(CLI `--builder-provider private`)链路 +
  CLI 替换攻击。
- `test_builder_dependency_closure.py`:tree 全文件绑定、4 类真实文件
  篡改矩阵、语义字段(参数/family/attempt max)变化、外部依赖变化、
  中间 helper 篡改使旧承诺失效、pack validity 报告 Provider hash 三方
  一致。
- `test_global_null_duration_contract.py`:唯一合同、顺序无关、等价
  raw 声明、矛盾声明 fail closed、缺字段拒绝、无 first/last/96 源码
  断言、承诺绑定、spec/family/power/pack 全链路对账、verify 篡改拒绝。
- `test_mixed_null_duration_rejection.py`:任务书 12 场景矩阵(含
  首末 96 中间 192 绕过失败、全部拒绝先于 checkpoint 加载)。
- `test_protocol_v6_upgrade.py`:v6/v5 弃用、CLI v7、manifest v2、
  validity v3、v1/v2 旧材料拒绝、缺 ndc- 承诺拒绝、CLI 缺 provider
  拒绝、未变协议不升级、六项冻结合同与 vendor HEAD 校验。
- `test_mock_sealed_exam_v7.py`:v7 全链路(mock provider 显式 +
  256-step PPO smoke 正常 FAIL + 幂等 + --detailed 退休)、npb/ndc
  篡改在沙箱启动前拒绝。

旧阶段测试维护(断言语义不降级,仅签名/常量适配):2.6.0e 重写
`test_pack_builder_manifest.py` 为 provider/tree 语义(断言更强);
版本常量断言跟进(v6/v7/v3/v2);`null_qual_cache.py` 与各阶段 conftest
补 `validate_null_pack`/`verify_sealed_commitment`/CLI 的新必填参数
(经 `tests/compat_stage2_6_0f.py` 共享辅助);96 回退改为显式解析。

## 七、全量回归

见 `artifacts/route_c_stage2_6_0f/regression_test_summary.md`
(11 个测试目录,零失败/零跳过/零 xfail)。

## 八、不变量确认

- 六项冻结合同(RouteCEnvCore-v1.0.0 / ObservationSpec-v1 /
  BinaryLongFlatAction-v1 / NetLogEquityReward-v1 /
  MarketOpenCausalExecution-v1 / TerminalLiquidation-v1)未修改;
- vendor/freqtrade 工作树 clean,HEAD =
  52bc96f4480b1a0da6a9b455bd00b17fbb6786a5;
- 2.6.0e 的摩擦(margin=0.002/1.001)、功效(power-analysis-v2 重跑)、
  antithetic pair、issuer 信任根、runtime 绑定、反作弊守卫全部保留
  (回归通过);
- 未开始正式人工课程 C1/C2/C3 PPO 训练(256-step smoke 仅用于链路
  验证)。

## 九、已知限制

1. mock Provider 的 package tree 绑定整个 rl_curriculum 包:修改评估
   基础设施中与 builder 无关的模块(如 formal_exam 执行器本身)也会
   改变 npb- 并要求重建承诺——这是刻意的保守选择(额外文件不忽略),
   代价是承诺重建频率升高;正式私有 builder 只绑定私有目录,不受影响。
2. `PrivateBuilderIdentityProvider` 的签名政策静态声明于
   provider_config.json / manifest 字段;动态函数签名检查只在可导入
   的 mock Provider 上强制(私有 builder 不被评估环境 import)。
3. 外部依赖 manifest 绑定 python/numpy/pandas 版本与 rl_platform
   tree:跨环境重算 npb- 会不同(设计使然——同环境才应通过)。
4. duration contract 的"raw 参数不同但 resolved 相同"允许性依赖
   resolve_duration 的解析语义(rps- 哈希引用);解析规则本身变化仍会
   使旧承诺失效。
5. artifacts/duration_cross_binding_audit.json 的
   pack_validity_duration_contract_hash 字段未填充(生成脚本小缺陷);
   该对账由测试 test_spec_family_power_pack_cross_binding 与
   npv- hash 机制完整覆盖。formal_exam.py 中少量历史步骤注释编号
   (5/7)与 docstring 的 11 步编号不一致(仅注释)。
6. 阶段 2.6.1 未开始;本阶段结论已通过独立验收 subagent 审查
   (ACCEPT,22/22 PASS 条件满足、FAIL 条件无一成立、冻结目录
   rl_platform/rl_candidate_runtime 与 2.6.0e 逐字节一致)。
