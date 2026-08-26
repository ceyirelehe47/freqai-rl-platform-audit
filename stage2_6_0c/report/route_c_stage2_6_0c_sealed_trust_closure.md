# 阶段 2.6.0c 报告:密封信任根、候选运行时绑定与反作弊复制闭环

- 日期:2026-08-26
- 基线:阶段 2.6.0b(commit `1f729fbe066a676bdf77e71873b216ce214ca8fb`)
- 结论:**PASS**(详见第十五节判定对照)
- 本阶段不开始正式 PPO 课程训练;进入 2.6.1 由独立审查决定。

## 一、任务范围

只修复 2.6.0b 独立审查发现的四个剩余正式阻塞,使密封考试的信任链真正闭环:

1. 正式考试使用的 issuer 只能来自已预承诺的 sealed commitment(工作包 A);
2. 沙箱内实际执行的 `rl_candidate_runtime` 每一个文件被 commitment 内容绑定(工作包 B);
3. 每一种作弊原因真实执行足够数量的不同 seed,不存在永远达不到门槛的检查(工作包 C);
4. strict Null 资格必须由真实资格报告证明,不能退化为 `qualification_pass=true`(工作包 D);
5. 协议与密封承诺升级,旧协议不得被新执行器自动接受(工作包 E);
6. mock 正式全链路重新闭环(工作包 F)。

冻结合同(`RouteCEnvCore-v1.0.0` / `ObservationSpec-v1` /
`BinaryLongFlatAction-v1` / `NetLogEquityReward-v1` /
`MarketOpenCausalExecution-v1` / `TerminalLiquidation-v1`)与
`vendor/freqtrade`(tag 2026.7,commit
`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`)均未修改。

## 二、工作包 A:issuer 信任根收归承诺

### 问题(2.6.0b 漏洞链)

- `hidden_exam_cli.py` 从 context 读取 `trusted_issuer` 并作为运行时
  参数传入 `run_sealed_exam()`;
- 执行器仅在该参数为 `None` 时才从 commitment 构造信任根,且从不比对
  两者——保留原承诺、替换 context issuer、用自己私钥自签 checkpoint
  即可获得正式资格;
- `TrustedIssuerConfig.protocol` 字段在两处重建路径被静默丢弃。

### 修复

| 位置 | 修复 |
|---|---|
| `formal_exam.py::run_sealed_exam` | 删除 `trusted_issuer` 参数;新增 `context_issuer_payload`(默认 None,仅作展示副本与承诺的 canonical equality 检查输入) |
| `formal_exam.py` 步骤 5 | 信任根唯一经 `TrustedIssuerConfig.from_payload(commitment.trusted_issuer)` 构造,构造前强制自洽校验 |
| `hidden_exam_cli.py` | 不再传入 issuer;context 副本经 `context_issuer_payload=ctx.get("trusted_issuer_payload")` 交给执行器做 equality |
| `attestation.py` | 新增 `verify_issuer_payload_self_consistency`(键集合精确/protocol==v1/issuer_id 非空/公钥可加载为 Ed25519/重算指纹一致/runner hash 格式合法/allow_smoke 必须 bool)与 `TrustedIssuerConfig.from_payload`(显式读取 protocol,不再丢弃) |
| `mock_sealed_exam.py::load_exam_context` | 不再构造 `TrustedIssuerConfig` 对象;返回原始 canonical payload 作为展示副本 |

不存在"参数非空时优先使用参数"逻辑;context 副本与承诺任何字段不同
均 `EXAM_INVALID`。

### 关键测试(`tests/route_c_stage2_6_0c/test_issuer_trust_root_closure.py`)

- **端到端攻击**:承诺绑定 issuer A + context 换 issuer B + checkpoint
  由 B 自签(材料完全自洽,B 公钥/B runner hash/B 签名)→ exit 5
  EXAM_INVALID(artifacts: `issuer_context_override_attack.json`,
  `attack_blocked=true`);
- formal API 签名无 issuer override(inspect 断言;唯一 issuer 相关参数
  是 equality 输入 `context_issuer_payload`,默认 None);
- CLI 源码不再 `trusted_issuer=ctx` 传参;
- context issuer 缺失不影响执行器从承诺构造信任根(全链路正常执行);
- 公钥与 fingerprint 不一致 / protocol 错 / runner hash 空 / smoke 非
  bool / 多字段 / 缺字段 → 自洽校验全拒(7 例矩阵);
- runner hash 被改 → EXAM_INVALID;allow_smoke 被改 → 承诺哈希变化
  (原承诺失效)。

## 三、工作包 B:候选运行时内容绑定与 TOCTOU 防护

### 问题

- 2.6.0b 的 sandbox profile 只绑定隔离配置(路径/rlimits/超时),不
  绑定沙箱内实际执行的 `rl_candidate_runtime` 任何文件内容;
- staging 复制(sandbox.py:200)到 Popen(:242)之间无重验——
  source-check 与 execution 之间存在 TOCTOU 窗口;
- `sandbox.py` 注释声称"profile 哈希绑定运行时内容哈希,由承诺另行
  绑定"与实现不符。

### 修复

新增(`sandbox.py`):

- `CANDIDATE_RUNTIME_MANIFEST_FORMAT = "candidate-runtime-manifest-v1"`;
- `REQUIRED_RUNTIME_FILES`(`__init__/bootstrap/guard/versions/worker`
  五个安全关键文件,缺失即拒绝);
- `compute_runtime_manifest()`:扫描运行时目录全部真实文件(递归,
  排除 `__pycache__`/`*.pyc`;**不限 .py——额外文件同样进入
  manifest,不被静默忽略**),逐文件 sha256,绑定
  `runtime_package_version` 与 `worker_protocol`;symlink 任何一级
  都拒绝;
- `runtime_tree_hash()`:`rt-` 前缀 canonical hash;
- `verify_staged_runtime()`:对 staging 重算文件哈希并与期望 manifest
  精确比对(文件集合与逐文件哈希都不得有差;多/少/变/symlink 均
  fail closed);
- `launch_sandboxed(..., expected_runtime_manifest=...)`:staging
  组装完成后、unshare/bootstrap 启动之前强制重验(正式路径传承诺
  值;测试路径退化为"staging 与当前源一致"自洽校验);
- `SandboxedCandidate(..., expected_runtime_manifest=...)` 由
  `formal_exam._load_sandboxed_candidate` 从承诺传入;
- `assemble_runtime_staging` 改为复制全部真实文件(原实现只复制
  `*.py`,非 .py 辅助文件会被静默丢弃)。

承诺侧(`sealed_exam.py`):

- `SealedExamCommitment` 新增 `candidate_runtime_manifest`(完整
  manifest,含逐文件哈希)与 `candidate_runtime_hash`(`rt-` 前缀),
  进入 canonical payload → 承诺哈希;
- `from_json` 强制两字段必填(缺 = 拒绝,v2 承诺没有此字段);
- `verify_sealed_commitment` 新增 check:`candidate_runtime_manifest`
  (当前源运行时 manifest 与承诺逐字节一致——runtime 代码变化 = 旧
  承诺失效)与 `candidate_runtime_hash`(manifest 与 hash 自洽)。

profile hash(隔离配置)与 runtime tree hash(执行代码内容)含义
分离,二者同时进入承诺。

### 关键测试(`test_candidate_runtime_binding.py`,14 项)

- manifest 稳定 + 逐文件内容敏感(五个安全关键文件各单字节变化均
  改变 tree hash);
- 缺 `versions.py` / 缺 `guard.py` → 拒绝;
- symlink(文件/目录)→ 拒绝;
- 额外 `evil_helper.py` 进入 manifest,旧 manifest 验证"额外文件"
  fail closed;
- bootstrap 跳过 Landlock / worker 改 reset 协议(注入 seed token)/
  guard 短路 sidecar 检查 → manifest 变化,旧承诺失效;
- runtime 协议版本字段被改 → tree hash 变化;
- **staging TOCTOU**:monkeypatch `assemble_runtime_staging` 在复制
  完成后替换 `worker.py`(或删除 `guard.py`)→
  `launch_sandboxed(expected_runtime_manifest=承诺值)` 在 Popen 之前
  `CandidateSandboxError`,worker 永不加载;
- 正常 staging 副本与源逐字节一致(`verified_byte_identical`);
- 承诺缺 runtime manifest/hash → `from_json` 拒绝;
- 源运行时被篡改后旧承诺的 sealed 验证失败(EXAM_INVALID 路径)。

## 四、工作包 C:反作弊复制闭环

### 问题

- `formal_exam.py` 五处 `replication_eps[:2]` 硬编码:absolute_price /
  episode_position / periodic_pattern 各只用 2 个 seed,而冻结门槛
  `min_distinct_cheat_seeds=3`——`SUSPECTED_CHEATING` 对这三类
  永不可达;
- `build_replication_evidence` 的 `variant_nets/paired_diffs` 逐
  record 追加,common_prefix 同 seed 的 3 个 cut 被当作 3 个独立
  样本进 bootstrap;
- `tests/route_c_stage2_6_0b` 存在一处 `or True` 永真断言。

### 修复

**动态门槛(C1,`formal_exam.run_counterfactual_suite`)**:

```text
required_seed_count = max(min_distinct_cheat_seeds, min_failing_cheat_episodes)
```

- 从 split 的 episodes 按 seed 去重构造取样表;不同 seed 数低于门槛
  → `SealedExamError`(EXAM_INVALID)——不降门槛,也不把考试包总
  Episode 数填进复制统计;
- 四类原因的取样全部使用同一组 `replication_eps`(`[:2]` 全部删除);
- `REPLICATION_SAMPLE_EPISODES` 常量删除(取样数只来自冻结判定器)。

**按 seed 聚合(C3,`counterfactual.build_replication_evidence`)**:

- 预注册规则 `per-seed-worst-variant-v1`(冻结于
  `CourseVerdictSpec.seed_aggregation`,进入判定器哈希、承诺
  `anticheat_replication_spec` 双保险与 verdict/commitment 哈希):
  - 同一 seed 的多个 cut/variant 先在 seed 内聚合;
  - 变体净收益取该 seed 全部变体的**最小值**(最坏变体)——优势
    崩溃的问题是"是否存在变体使优势消失",取均值会被同原因下
    不敏感变体(如初始价平移后仍做多)稀释,最坏值是 fail-safe
    方向;
  - 配对差 = 最坏变体收益 − 该 seed 原始收益;
  - 动作分歧率取 seed 内均值(行为度量);
  - failing seed = 该 seed 内任一记录失败;
  - bootstrap(优势崩溃/配对差)独立抽样单位是 seed——3 个 cut
    只贡献 1 个 seed 级样本;
- evidence 输出新增 `per_seed` 逐 seed 明细、`n_records`、
  `seed_aggregation`(可审计);未注册聚合规则直接拒绝
  (`CourseVerdictSpec.__post_init__` + evidence 构造双重校验);
- probe 课程 `min_effective_net_return` 校准为 0.02(与
  tests/route_c_stage2_6_0 作弊场景一致):空仓变体净收益恰为 0
  构成优势崩溃(0 < 0.02);此前 0.0 阈值下空仓变体永不崩溃。

**保持 2.6.0b 正确原则(C4)**:缺 collapse 证据不默认 True;
required 原因证据缺失 → EXAM_INVALID;单 seed 失败不判作弊;
无有效原始成绩只普通 FAIL。

**永真断言(C5)**:`tests/route_c_stage2_6_0b/
test_counterfactual_actual_replication_count.py` 的
`assert ... or True` 删除并替换为真实断言
(`tested_episodes < len(episodes)`);新增静态扫描测试确保整个
tests/ 树无 `or True` / `assert True` 模式。

### 关键测试(`test_anticheat_replication_closure.py`)

- 正式套件四原因集成:每原因 `distinct_seeds == 3`、
  `n_records >= 3`、tested seeds 来自实际记录的
  `extra.episode_seed`、pack 总数不参与复制计算
  (artifacts: `anticheat_replication_coverage.json`,
  `all_reasons_meet_threshold=true`);
- 同一 seed 9 条 cut 记录:`distinct_seeds=1`、bootstrap 样本量
  `n=1`;
- 价格尺度多 scale 先 seed 内聚合(不产生独立样本);
- 2-seed 考试包 → `run_counterfactual_suite` 直接 EXAM_INVALID;
- **三类此前不可达状态真实触发**(固定结构场景 + TestOnly 探针,
  不进入正式 Candidate 接口):
  - `AbsolutePriceCheaterProbe(buy_below=150)` ×3 seed →
    SUSPECTED_CHEATING(base=+0.2968);
  - `StepCounterCheaterProbe` ×3 seed → SUSPECTED_CHEATING
    (base=+0.0875);
  - `PeriodicCheaterProbe(4)` ×3 seed → SUSPECTED_CHEATING
    (base=+0.1433);
  - 每项经 `run_counterfactual_suite`(正式执行器同一函数)+
    `classify_cheating` 四门 + 冻结判定器最终 status 断言;
- 3 seed 被测但仅 2 个失败 seed → 第四门不满足,不判作弊。

## 五、工作包 D:真实 Null 资格报告强制绑定

### 问题

- `build_mock_commitment` 在缺真实报告时可退化为
  `{f: {"qualification_pass": True}}` 占位;
- 正式验证只查 `bool(bound.get("qualification_pass"))`——不读报告、
  不重算 hash、不对账任何材料。

### 修复

**报告 v2(`null_qualification.py`)**:

- `NULL_QUALIFICATION_FORMAT = "null-qualification-v2"`;
- `qualify_null_family` 输出内嵌全部对账材料:
  `generator_implementation_hash` / `generator_manifest_hash`(族实现
  指纹,报告生成时计算)、`observation_schema_hash`、
  `eval_config_manifest`(含 fee)、`qualification_params`
  (episodes_per_seed / max_net_drift_per_bar /
  min_distinct_qualification_seeds)、`qualification_code_hash`、
  `timeframe`、`seeds`/`distinct_seeds`、五项 checks;
- `REQUIRED_NULL_CHECKS`(五项,键集合精确)与
  `NULL_REPORT_REQUIRED_KEYS`(报告键集合精确,缺失/未识别字段均拒)。

**binding v2**:

- `{family: {family_version, qualification_pass, report_hash,
  report_payload}}`——完整 canonical 报告 payload 进入承诺哈希
  (报告内容被承诺绑定,不依赖可覆盖的未绑定路径);
- `build_null_qualification_bindings` 校验报告键集合;bool-only
  结构在构建侧即失败;
- `build_mock_commitment` 的 bool fallback 删除:缺
  `null_qualification_bindings` 立即 ValueError。

**完整重验证(`verify_null_qualification_bindings` 新签名)**:

逐族对账:binding 键集合精确 → payload 存在且键集合精确 → 重算
`qualification_report_hash(payload)` == binding.report_hash →
family / family_version 与 binding 及当前 generator_bindings 对账 →
generator implementation/manifest hash 与当前密封生成器绑定对账
(Null 实现变化 = 旧报告失效)→ qualification_code_hash 与当前代码
哈希一致(代码变化 = 旧报告失效)→ Observation Schema hash /
EvalConfig(含 fee)/ timeframe 与本次考试对账 → seeds 去重数
≥ 3 且与 distinct_seeds 自洽 → checks 键集合精确且全真 → pass 为
真且与 binding 布尔一致。

`verify_sealed_commitment` 调用点传入承诺的 generator_bindings /
schema hash / eval_config / pack timeframe。

### 关键测试(`test_null_qualification_binding.py`,21 项篡改矩阵)

bool-only / 缺 payload / hash 改 / payload 篡改(fee)/ family 错 /
version 错 / 实现指纹陈旧 / 资格代码陈旧 / seed 不足 / distinct
矛盾 / fee 不一致 / schema 不一致 / timeframe 不一致 / check 缺失 /
check 为假 / 未识别字段 / 缺字段 / pass 假 / 缺族绑定——全部拒绝;
真实生成的报告含全部对账材料并通过验证
(artifacts: `null_qualification_report_bindings.json`、
`null_qualification_tamper_matrix.json`,
`all_negative_cases_rejected=true`)。

## 六、工作包 E:协议升级

| 协议 | 旧值 | 新值 |
|---|---|---|
| sealed exam commitment | sealed-exam-commitment-v2 | **sealed-exam-commitment-v3** |
| sealed exam context | sealed-exam-context-v2 | **sealed-exam-context-v3** |
| hidden exam CLI | hidden-exam-cli-v3(两文件重复定义) | **hidden-exam-cli-v4**(单一来源 `formal_exam.EXAM_CLI_VERSION`,CLI re-export) |
| course verdict spec | course-verdict-spec-v2 | **course-verdict-spec-v3**(新增 seed_aggregation 字段) |
| candidate runtime manifest | (不存在) | **candidate-runtime-manifest-v1**(新) |
| null qualification | null-qualification-v1 | **null-qualification-v2**(新) |
| runtime package | rl-candidate-runtime-stage2_6_0b-v1 | **rl-candidate-runtime-stage2_6_0c-v1** |
| curriculum infra | rl-curriculum-stage2_6_0b-v1 | **rl-curriculum-stage2_6_0c-v1** |
| checkpoint manifest | checkpoint-manifest-v3 | 不变(语义未变,不做无理由升级) |
| training attestation | training-attestation-v1 | 不变(同上) |
| worker 协议 | candidate-worker-v2 | 不变(协议本身未变) |

旧协议拒绝:

- v1/v2 承诺:`from_json` 显式弃用错误(说明 v2 缺运行时内容绑定/
  真实 Null 报告绑定,issuer 通道曾被覆盖);
- v2 context:`load_exam_context` 明确报错(issuer 信任根已收归承诺);
- 缺 runtime manifest/hash 的 v3 payload:拒绝;
- bool-only Null binding:构建与验证双侧拒绝;
- 不允许静默补默认字段(承诺新字段在 from_json 必填)。

## 七、工作包 F:mock 正式全链路(实验)

`experiments/route_c_stage2_6_0c/run_all.py`,全链路 38s:

```text
mock hidden pack → 真实 strict Null 报告(三族×3 seed,全 pass)
→ mock issuer(Ed25519,allow_smoke=true 仅限 mock)+ 受信 runner 配置
→ 受控 PPO smoke 训练(256 步,非课程训练)
→ checkpoint sidecar(v3)+ Ed25519 training attestation
→ v3 承诺(绑定 runtime manifest + tree hash + 真实 Null 报告)
→ 系统级沙箱加载(staging 重验)
→ 正式反事实套件(四原因 × 3 seed,seed 级 bootstrap)
→ 冻结判定:FAIL(smoke 模型正常挂科,预期)
→ 幂等重试:同结果(attempt 复用) → 详细披露:包退休
→ 篡改矩阵(issuer 覆盖/runtime/Null/协议,全拒)
```

- 256-step PPO 仅验证 provenance/sandbox/接口;不宣称完成课程训练;
- 三类作弊集成场景全部达到 SUSPECTED_CHEATING(见第四节)。

## 八、测试统计

新增 `tests/route_c_stage2_6_0c/`(6 个测试文件 + conftest):

| 套件 | 文件 | 覆盖 |
|---|---|---|
| A | test_issuer_trust_root_closure.py | 信任根收归/攻击矩阵/自洽 |
| B | test_candidate_runtime_binding.py | manifest/staging/TOCTOU/篡改 |
| C | test_anticheat_replication_closure.py | 动态门槛/seed 聚合/三类作弊触发 |
| D | test_null_qualification_binding.py | 真实报告绑定/21 例篡改矩阵 |
| E | test_protocol_upgrade.py | 协议升级/旧版拒绝/冻结合同未动 |
| F | test_mock_sealed_exam_v4.py | 全链路/幂等/退休/不受信签名 |

全量回归(逐目录,详见 `artifacts/route_c_stage2_6_0c/
regression_test_summary.md`):

| 目录 | passed | failed | error | skipped | xfailed | 耗时 |
|---|---|---|---|---|---|---|
| freqai_rl_stage2_5 | 38 | 0 | 0 | 0 | 0 | 36s |
| freqai_rl_stage2_5_1 | 74 | 0 | 0 | 0 | 0 | 40s |
| freqai_rl_stage2_5_2 | 78 | 0 | 0 | 0 | 0 | 52s |
| freqai_rl_stage2_5_2a | 81 | 0 | 0 | 0 | 0 | 21s |
| route_c_stage2_6_0 | 182 | 0 | 0 | 0 | 0 | 75s |
| route_c_stage2_6_0a | 169 | 0 | 0 | 0 | 0 | 51s |
| route_c_stage2_6_0b | 159 | 0 | 0 | 0 | 0 | 63s |
| route_c_stage2_6_0c | 83 | 0 | 0 | 0 | 0 | 77s |
| **合计** | **864** | **0** | **0** | **0** | **0** | ~7.6min |

旧测试适配说明(不删测试、不加 skip、不降断言强度):

- 2.6.0b `test_counterfactual_actual_replication_count.py`:导入改为
  动态门槛计算,并删除 `or True` 永真断言、替换为真实断言
  (强度提升);
- 2.6.0b `test_invalid_null_rejected.py` / `test_sandbox_profile_
  binding.py` / `test_mock_sealed_exam_v3.py`:适配新 API 签名
  (verify 新 kwargs / v3 协议常量 / v4 CLI 版本字符串),断言语义
  保持或增强(v1 拒绝测试扩展为 v1+v2 双拒绝);
- 2.6.0a `test_sealed_pack_commitment.py` / conftest、2.6.0
  `test_hidden_exam_redaction.py` / `test_exam_retirement.py`:
  commitment 构建补真实 Null 报告绑定(bool 占位已不可用);
  dev_seed_holdout 扩至 3 seed(C1 门槛的必然要求);
- 2.6.0a v1 拒绝测试补占位 runtime manifest 以通过 v3 roundtrip,
  并扩展为 v1+v2 双拒绝。

## 九、冻结环境与上游完整性

- `vendor/freqtrade`:工作树 clean;HEAD
  `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(tag 2026.7);
- `RouteCEnvCore-v1.0.0` 及全部冻结 spec 未修改
  (`rl_platform/versions.spec_versions()` 逐项验证;
  `test_protocol_upgrade.py::test_frozen_environment_contracts_
  untouched` 断言);
- 成交时序/fee/ledger/reward/terminal liquidation/Long-Flat 语义
  未触碰;
- 未引入 LSTM/RecurrentPPO/GRU/TCN/Transformer/sb3-contrib/多资产。

## 十、PASS 条件对照(任务书第十三节)

| # | 条件 | 证据 |
|---|---|---|
| 1 | 正式 issuer 唯一来自 commitment | run_sealed_exam 无 issuer 参数;from_payload(commitment) |
| 2 | context issuer 替换攻击被拒绝 | 端到端攻击测试 EXAM_INVALID;attack artifact |
| 3 | formal API 无 issuer override | inspect 断言测试 |
| 4 | issuer 公钥与 fingerprint 自洽 | verify_issuer_payload_self_consistency + check #13 |
| 5 | runtime 完整树被承诺绑定 | candidate_runtime_manifest/hash 进 canonical payload |
| 6 | staging 与承诺逐字节一致 | launch_sandboxed 启动前 verify_staged_runtime |
| 7 | 任一安全关键文件变化使旧承诺失效 | 逐文件篡改矩阵 all_tamper_invalidates=true |
| 8 | 四原因均执行冻结数量不同 seed | 集成测试 distinct_seeds==3;coverage artifact |
| 9 | 同 seed 多变体不算独立 seed | per-seed 聚合;9 cut → 1 seed 测试 |
| 10 | 三类不可达状态可触发 | 三个 3-seed 作弊集成 SUSPECTED_CHEATING |
| 11 | pack seed 不足考试无效 | 2-seed 包 EXAM_INVALID 测试 |
| 12 | strict Null 每族真实报告 | bool fallback 删除;binding 嵌 payload |
| 13 | bool-only binding 被拒绝 | 构建+验证双侧测试 |
| 14 | 报告内容/hash/版本/参数/实现对账 | verify 全量对账 + 21 例矩阵 |
| 15 | 旧 commitment/context 明确拒绝 | v1/v2 弃用错误测试 |
| 16 | mock 正式链路完整执行 | v4 summary artifact(FAIL 正常挂科+幂等+退休) |
| 17 | 全部新增攻击矩阵通过 | sealed/runtime/null/issuer 四个矩阵 artifact |
| 18 | 全量回归零失败 | 见第八节(完成后填) |
| 19 | 上游 clean | 第九节 |
| 20 | 未开始正式课程训练 | 256-step smoke 仅为接口验证 |

## 十一、已知限制

1. `sealed_exam_tamper_matrix_v3.json` 中"context_issuer_mismatch"
   条目在实验层以 API 语义记录(rejected=true),完整端到端路径由
   测试套件的攻击测试覆盖;
2. `SandboxedCandidate.close()` 沿用 2.6.0b 行为不清理 staging 目录
   (匿名 tmp 位置,由系统清理;未纳入本阶段范围);
3. runtime manifest 扫描排除 `__pycache__`/`*.pyc`(解释器产物);
   非入口 pyc 不会被 import 路径加载,`.py` 内容变化全部被绑定;
4. probe 课程阈值(min_effective=0.02)是 mock 校准值,正式趋势课程
   门槛仍按计划在 2.6.2 校准冻结;
5. 作弊策略集成使用 TestOnly 探针协议(固定结构场景),不进入正式
   Candidate 接口;正式课程的反作弊检出能力依赖真实模型在正式课程
   上的表现,由后续阶段验证;
6. mock issuer `allow_smoke=true` 仅为接口验证;正式 issuer 配置
   仍为 false(实验脚本内注释明确)。

## 十二、交付物

- 本地报告:`~/projects/crypto_rl/reports/
  route_c_stage2_6_0c_sealed_trust_closure.md`
- 证据目录:`~/projects/crypto_rl/artifacts/route_c_stage2_6_0c/`
  (issuer_context_override_attack / trusted_issuer_consistency /
  candidate_runtime_tree_manifest / candidate_runtime_tamper_matrix /
  staged_runtime_integrity / anticheat_replication_coverage /
  anticheat_seed_cluster_bootstrap / absolute_price_cheat_integration /
  episode_position_cheat_integration / periodic_pattern_cheat_integration /
  null_qualification_report_bindings / null_qualification_tamper_matrix /
  sealed_exam_tamper_matrix_v3 / mock_sealed_exam_v4_summary /
  regression_test_summary / upstream_integrity)
- 公开目录:`stage2_6_0c/`(README / report / src / experiments /
  tests / artifacts / logs)
- 不含:真实私钥、正式隐藏种子、正式私有生成器、模型二进制、真实
  行情、数据库、API Key、代理认证、私人路径;mock 私钥仅在临时目录
  即时生成。
