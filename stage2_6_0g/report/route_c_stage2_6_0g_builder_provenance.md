# 阶段 2.6.0g 报告:Builder 产物来源证明与私有 EntryPoint 验证闭环

- 日期:2026-08-28
- 基线提交:`2a07811cfa847c3ba02deb7ac67224634314a43b`(阶段 2.6.0f)
- Freqtrade 上游冻结:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 判定:PASS(详见第六节;等待独立审查,不自动进入 2.6.1)

## 一、阶段目标与遗留问题

阶段 2.6.0f 建立了 Builder Identity Provider 体系(npb- 绑定 builder
package tree + 显式外部依赖),但留下七个问题:

| # | 问题 | 修复 |
|---|------|------|
| P1 | Builder Identity 只证明评估环境中存在一组被哈希的文件,没有证明这组文件中的 Builder 实际生成了 commitment.pack_hash 绑定的 pack | 工作包 B:产物来源证明(冻结输入下实际执行 builder 并比对产物 hash) |
| P2 | 测试 private builder 的入口返回 None,仍能与公开 mock pack 组合后通过 formal verification | D1 步骤 4b 在候选加载前实际执行 builder,None 即 EXAM_INVALID |
| P3 | Private Provider 没有真实验证 entrypoint 和 attempt-loop 的存在、callable 类型、函数签名和返回值 | 工作包 A1:AST 静态解析 + 受控 import 双重验证 |
| P4 | 禁止 candidate/checkpoint/model/policy 参数规则只是 manifest 自我声明 | A1 验证链对私有侧动态强制 inspect.signature |
| P5 | commitment 创建端与 CLI 使用不同的 Provider 配置解析逻辑,CLI 遗漏 pair_count、max_attempts、external dependencies | 统一 load_builder_provider_config / private_provider_from_config |
| P6 | Builder 运行依赖只手工绑定少数包,未覆盖实际 import 的 Gymnasium 等 | AST import 闭包自动发现 |
| P7 | mock 构建辅助函数保留内部隐式 Mock Provider fallback | 两处 fallback 源码级删除,必填显式传入 |

核心目标:

> 不仅证明"Builder A 的文件身份正确",还要证明"Builder A 在冻结输入
> 和运行环境下实际产生的 pack,正是 commitment.pack_hash 所绑定的
> pack"。

## 二、实现内容

### 工作包 A1:EntryPoint 真实存在性验证(src/rl_curriculum/builder_identity.py)

`PrivateBuilderIdentityProvider.__init__` 构造期执行完整验证链
(任何失败即 `BuilderIdentityError`,fail closed,不存在"只接受字符串
声明"的回退):

1. module 源文件定位:支持私有形态(`builder_a`)与包内绝对形态
   (`rl_curriculum.mock_sealed_exam`),路径必须位于受信 root 内
   (拒绝拼写错误/入口文件缺失/路径逃逸);
2. AST 静态解析 qualname(最多 `Class.method` 两级):只有真实的
   `FunctionDef`/`AsyncFunctionDef` 定义节点能通过——注释、字符串
   字面量、变量赋值、不存在的符号在 AST 中都不是函数定义,天然被
   拒绝(不以字符串搜索判定);
3. 入口类型属于预注册允许范围
   `ALLOWED_ENTRYPOINT_KINDS = ("function", "staticfunction",
   "classfunction")`:类构造器与协程函数被拒绝;
4. 受控 import:root 临时加入 `sys.path`,同名 module 的陈旧缓存
   (源文件不在本 root)先弹出;import 后按 qualname 逐段 getattr
   解析真实对象;
5. 运行时类型复核(callable、非 type、属于
   FunctionType/MethodType/BuiltinFunctionType);
6. 签名可解析(P4:私有侧动态强制
   `check_builder_signature_policy`,禁止参数
   candidate/checkpoint/model/policy 不再是 manifest 自我声明);
7. build 入口必须接受冻结构建请求参数
   (builder-runner-protocol-v1 的单 request 位置参数形态)。

attempt-loop 声明非空时走同一验证链(参数形态放宽)。mock Provider
的入口(`mock_build_pack`)与 attempt-loop(`build_mock_hidden_pack`)
同样通过 A1 验证。

验证报告(含源文件 sha256、kind、签名参数)进入 manifest v3 的
`entrypoints_validated` 字段。

### 工作包 A2:统一 Builder Runner 调用协议(src/rl_curriculum/builder_provenance.py,新建)

- `builder-runner-protocol-v1` / `builder-build-request-v1` /
  `builder-build-result-v1` 三个版本化格式;
- 冻结构建请求由评估方代码统一派生
  (`build_frozen_build_request(identity, pack, duration_contract)`):
  内容 = builder 身份(npb-/协议/params_spec/families/pair 数/
  attempt 上限)+ pack 公开自由度(name/version/timeframe)+
  duration contract(timeframe/resolved_bars/ndc-);
- 黑名单 `BUILD_REQUEST_FORBIDDEN_FIELDS`(candidate/checkpoint/
  model/policy/score/scores/verdict/outcome/ranking/result/
  prediction)递归扫描键名,前缀派生字段(candidate_score 等)一并
  拒绝;请求哈希 `nbr-`(canonical JSON 排序稳定)进入 v7 承诺;
- `run_builder_entrypoint(entrypoint_fn, request)` 统一执行入口
  `build_pack(frozen_build_request) -> build_result`:返回 None、
  抛异常、返回非 dict、结果含未知字段、自报失败、pack 缺失或
  不可解析(必须 ExamPack 实例或可解析 dict/JSON)一律 failed;
- pack 解析后 `pack_hash()` 必须可计算。

**双通道重放形态**(实现中发现并解决的语义边界):公开 mock 流程
中存在评估方直接组装的合成 pack(混合 train/dev/null episodes 的
测试 pack),它们不是 mock 构建循环的产物——2.6.0g 的产物来源证明
正确地暴露了 2.6.0f 时代"mock provider 签了它并未构建的 pack"这一
松散点。修复为按通道分流:

- **私有通道(真实构建)**:请求永不携带 pack 内容,重放必须由
  builder 从自身冻结的 seed namespace 真实构建,产物 hash 对账;
- **公开 mock 组装通道**:mock builder 是公开验证基础设施的
  "组装器",其冻结构建输入就是 pack 的公开规范——请求携带
  `mock_pack_payload`(pack 的规范化 JSON),`mock_build_pack` 按
  载荷确定性重建 ExamPack(to_json→from_json roundtrip 的
  pack_hash 稳定性已验证);载荷内容在 verify 12d 从 pack 现算
  对账(注入与 pack 不符的载荷会因 nbr 对账失败被拒);
- **硬闸**:`verify_builder_provenance` 的
  `allow_mock_pack_payload` 只在 formal D1 4b 对
  `MockBuilderIdentityProvider` 为真——私有 builder 的请求携带
  载荷一律拒绝(私有重放不得照抄 pack 内容)。

### 工作包 B:产物来源证明(P1/P2)

- Provider 协议扩展:`builder_entrypoint()`(可执行入口)与
  `frozen_build_request(pack, duration_contract)`;Mock/Private 双
  实现;
- `verify_builder_provenance(provider, commitment, pack,
  duration_contract)`:请求哈希对账(重放输入不可被替换)→ 实际执行
  builder → 重放产物 pack_hash 必须等于 commitment.pack_hash;
- formal D1 顺序插入步骤 4b(候选 checkpoint 加载与沙箱启动之前,
  verify/power 重跑之前):失败即 EXAM_INVALID,输出
  `builder_provenance` 报告进入考试 evidence(非敏感:哈希与
  attempt 数,不含隐藏 seed 与私有源码内容)。

### P5:统一 Provider 配置解析(builder_identity.py)

`load_builder_provider_config(root)` +
`private_provider_from_config(root, config)`:单一字段清单
(必填 entrypoint_module/entrypoint_qualname;可选
attempt_loop_*/params_spec/families/pair_count_per_family/
max_attempts/external_dependencies/root_label)。CLI
(`--builder-provider private`)与承诺创建端/测试 conftest 共用;
未知字段拒绝(拼写错误不得静默失效),JSON 破损/必填缺失
fail closed。

### P6:完整依赖闭包(builder_identity.py)

`shared_external_dependency_manifest` 从手工清单(python/numpy/
pandas)升级为 AST 静态 import 闭包:扫描 rl_curriculum +
rl_platform + builder root 内全部 .py 的 import 语句(模块级与
函数级一视同仁),排除 stdlib 与内部源码包(rl_curriculum 在
package tree 内、rl_platform 用 tree hash、rl_candidate_runtime 由
candidate runtime manifest 独立绑定)。实际闭包覆盖:
ccxt/cryptography/freqtrade/gymnasium/joblib/numpy/pandas/sklearn/
stable_baselines3/torch + rl_platform tree hash + python 运行时。
import 名与发行名不一致的包按别名表查询版本(sklearn→scikit-learn)。

### P7:删除隐式 fallback(mock_sealed_exam.py)

- `build_mock_commitment(builder_provider=None)` → 显式
  ValueError(公开 mock 流程必须显式传入
  MockBuilderIdentityProvider);
- `_validate_pack_ephemeral(builder_identity=None)` → 显式失败;
  `build_mock_hidden_pack` 内部显式构造(mock 构建流程自身)。

### 协议版本升级

| 常量 | 2.6.0f | 2.6.0g |
|------|--------|--------|
| SEALED_EXAM_PROTOCOL | sealed-exam-commitment-v6 | sealed-exam-commitment-v7 |
| EXAM_CLI_VERSION | hidden-exam-cli-v7 | hidden-exam-cli-v8 |
| BUILDER_MANIFEST_FORMAT | null-pack-builder-manifest-v2 | null-pack-builder-manifest-v3 |
| BUILDER_PROTOCOL | null-pack-builder-protocol-v2 | null-pack-builder-protocol-v3 |
| (新增)BUILDER_RUNNER_PROTOCOL | — | builder-runner-protocol-v1 |
| (新增)BUILD_REQUEST/RESULT_FORMAT | — | builder-build-request/result-v1 |
| PACK_VALIDITY_FORMAT | null-pack-validity-v3 | 不变(v3) |

v7 承诺新增字段 `builder_build_request`(完整冻结构建请求)与
`builder_build_request_hash`(nbr-);from_json 校验前缀、payload 与
哈希一致、黑名单;verify 新增 check 12d(Provider 重新派生请求并对
账)。v6 材料的弃用消息详述其缺陷(npb- 只证文件存在、None 入口
组合攻击、入口无验证、配置解析分叉、手工依赖清单)。

## 三、测试

- 新增 `tests/route_c_stage2_6_0g/`(9 文件,71 项):
  - test_entrypoint_validation.py(A1 攻击矩阵:module 缺失/逃逸/
    qualname 不存在/字符串变量/注释/类构造器/协程/禁止参数×4/
    无 request 参数/陈旧缓存隔离;Class.method 正例);
  - test_builder_runner_protocol.py(A2:格式/必填/黑名单×6 递归×3
    层/哈希稳定性/None/异常/非 dict/自报失败/缺 pack/不可解析/
    未知字段/不可调用/mock 真实 ok/请求派生);
  - test_builder_provenance.py(P1/P2:mock 与私有重放通过、None
    入口攻击拒绝、产物不同拒绝、请求哈希不匹配拒绝、Provider 缺
    方法拒绝、承诺携带请求);
  - test_formal_provenance_integration.py(D1 4b formal 闭环:
    None builder 完整承诺→EXAM_INVALID+沙箱 spy 断言+结构性证据
    (4b 在 verify 前失败→checks 为空)、wrong-pack 拒绝、真实私有
    builder 链路推进、mock CLI v8 全链(256 步 PPO smoke 正常
    FAIL,builder_provenance 报告进入输出)、CLI None 拒绝);
  - test_unified_provider_config.py(P5)、
    test_dependency_closure.py(P6)、
    test_mock_no_implicit_fallback.py(P7 源码级)、
    test_protocol_v7_upgrade.py(v7 常量/v6 拒绝/缺请求/篡改/
    注入候选字段/12d 对账/roundtrip);
- 旧测试兼容更新(不降低断言):
  - 14 处 `build_mock_commitment` 无 provider 调用补显式
    MockBuilderIdentityProvider(P7 联动);
  - 版本常量断言升级(v6→v7、CLI v7→v8、manifest/protocol v2→v3,
    共 11 文件);
  - 2_6_0a 占位承诺补自洽 build_request/nbr-;
  - 2_6_0e 直构 Provider 的假入口签名升级为协议合规形态;
  - 2_6_0f 私有 builder 测试资产真实化(入口 `build_pack(request)`
    真实构造 pack;None 入口独立为攻击资产 PRIVATE_BUILDER_NONE_
    FILES;篡改矩阵改锚新签名);
  - 2_6_0f conftest 的 private_provider_from_root 改用 src 统一
    解析(与 CLI 同源)。

## 四、回归结果

13 目录全量回归(零跳过/零 xfail;freqai_rl_platform_audit 目录本无
测试文件,不计入):

| 目录 | 结果 |
|------|------|
| freqai_rl_stage2_5 | 38 passed |
| freqai_rl_stage2_5_1 | 74 passed |
| freqai_rl_stage2_5_2 | 78 passed |
| freqai_rl_stage2_5_2a | 81 passed |
| route_c_stage2_6_0 | 182 passed(含本阶段修复的 6 项合成 pack 重放) |
| route_c_stage2_6_0a | 169 passed |
| route_c_stage2_6_0b | 159 passed |
| route_c_stage2_6_0c | 83 passed |
| route_c_stage2_6_0d | 57 passed |
| route_c_stage2_6_0e | 111 passed + 1 failed(见下) |
| route_c_stage2_6_0f | 64 passed |
| route_c_stage2_6_0g | 73 passed |
| 合计 | **1169 passed / 1 failed** |

待复验项:`test_pack_builder_manifest.py::test_modifying_builder_
package_file_changes_npb`。根因已定位并修复:`_module_source_within`
的包名剥前缀逻辑误伤了"root 目录名与 module 同名"的私有形态
(测试的 root 为 `tmp/builder_a`、module 为 `builder_a`,前缀被
误剥后源文件定位失败);修复改为优先按原始 module 路径直接定位、
失败再剥前缀。修复已落盘,但按用户指示复跑推迟,与下一份任务书
的工作一并验证——本阶段判定相应记为有条件(见第六节)。

## 五、冻结确认

- RouteCEnvCore-v1.0.0、ObservationSpec-v1、
  BinaryLongFlatAction-v1、NetLogEquityReward-v1、
  MarketOpenCausalExecution-v1、TerminalLiquidation-v1 未修改;
- LongFlatLedger、fee/slippage/tick rounding、reward、terminal
  liquidation、动作含义、Observation、Freqtrade 上游未修改
  (vendor 52bc96f clean);
- 模型路线不变(SB3 PPO、普通 MLP Actor-Critic、单资产现货、
  Long/Flat;无 LSTM/RecurrentPPO/GRU/TCN/Transformer/多资产);
- 未开始正式课程 PPO 训练(测试中的 256 步 smoke 仅验证链路,
  正常 FAIL 不构成课程训练);
- rl_platform 与 rl_candidate_runtime 源码零改动(与 2.6.0f 基线
  逐字节一致,见验收记录)。

## 六、判定

- 工作包 A1/A2/B(核心)与 P1-P7 全部落地并有源码级证据;
- 新测试 73/73 通过;全量回归 1169 passed / 1 failed(该 1 项
  根因已定位、修复已落盘、复跑按用户指示推迟至下一阶段一并
  验证,见第四节);
- 七个问题的攻击面全部闭环(见 artifacts):
  - A1 攻击矩阵 12/12 拒绝;
  - P2 None 入口 + mock pack 组合在 formal 4b 被拒(沙箱未启动);
  - P1 产物不同 builder 被拒;mock 组装通道载荷与私有通道硬闸
    分流(私有请求携带载荷一律拒绝);
  - P5 CLI/承诺同源,全字段生效;
  - P6 gymnasium 等第三方进入依赖闭包;
  - P7 源码级无 fallback;
- 判定:**PASS(附 1 项待复验)**——2_6_0e 的同名 root 定位修复
  已落盘但未经复跑确认,与下一阶段工作一并验证后转无条件 PASS。
  **不自动进入 2.6.1,等待独立审查与下一份任务书。**

## 七、已知限制

1. 产物来源证明依赖 builder 的确定性重放:私有 builder 在冻结输入
   下可精确重产 pack;若真实私有 builder 使用外部不可复现状态
   (如网络、时钟),重放将失败并 EXAM_INVALID——这是 fail closed
   的预期行为,但要求正式 builder 满足确定性构建合同;
2. 公开 mock 通道的重放形态是"pack 规范载荷确定性重组装"
   (mock builder 是公开组装器,验证的是请求-产物一致性与通道
   自洽,而非"隐藏构建逻辑的真实执行");私有通道不受此影响
   (请求永不携带 pack 内容,重放必须真实构建,硬闸 fail closed);
3. A1 的入口类型白名单不含 callable 实例(仅函数/静态方法/类
   方法):需要实例入口的 builder 必须以模块级工厂函数适配;
4. 依赖闭包按 import 名绑定版本(torch/stable_baselines3 等大包
   版本变化会改变 npb-):评估方与承诺方必须同环境,这是依赖身份
   绑定的本意,但使 npb- 对环境升级更敏感;
5. verify 的 12d 是重放输入的静态对账;builder 实际执行只在
   formal D1 4b(每场考试一次)——单独调用 verify_sealed_commitment
   不执行 builder(与 power 重跑只在 formal 全链执行的既有分层
   一致);
6. 攻击矩阵中的"产物不同 builder"以 timeframe 差异构造;更隐蔽的
   微小差异(如单个 seed)同样会被 pack_hash 对账拒绝(同一机制),
   未逐一枚举;
7. freqai_rl_platform_audit 目录无测试文件,回归统计不含该目录。

## 八、发布

- 发布目录:`stage2_6_0g/`(src/experiments/tests/artifacts/logs/
  report/README);
- GitHub:ceyirelehe47/freqai-rl-platform-audit(本阶段提交见
  commit message);
- 不含私有 builder 真实源码、master seed、隐藏 Episode seed、
  issuer 私钥、模型二进制、真实行情或任何凭证(敏感扫描记录见
  发布说明)。
