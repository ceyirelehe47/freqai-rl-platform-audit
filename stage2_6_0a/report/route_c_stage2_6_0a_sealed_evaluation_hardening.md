# 阶段 2.6.0a 报告:正式评估隔离、密封考试与 Observation 合同加固

- 日期:2026-08-26(UTC)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,工作树 clean(零修改)
- 基准:阶段 2.6.0 提交 915dd00(RouteCEnvCore-v1.0.0 未修改)
- 判定:**PASS**
- 测试:619 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81 /
  2.6.0 更新后 182 / 2.6.0a 新增 166;platform_audit 目录只含审计
  脚本无 pytest 用例,与阶段 2.6.0 口径一致);零 skip/xfail 删除
- 本阶段未训练任何正式课程模型;测试级固定维度 PPO(256 步)仅证明
  固定维度 SB3 模型能真实执行全部 G4 考试(允许挂科)
- 是否允许进入阶段 2.6.1:**允许**

---

## 1. 执行摘要

阶段 2.6.0 的全局 PASS 建立在不完整的评估边界上:普通候选策略通过
ActContext 可以读取完整 Episode DataFrame、Episode 总长度、完整隐藏
状态与完整未来收益;隐藏考试没有密封承诺,PASS 只看总体收益中位数,
考试条件可由命令行临时改写,脱敏输出泄漏生成器族与参数桶,无关特征
注入会改变固定维度模型的 observation shape,常数动作可能被误判周期
作弊。本阶段重建正式评估边界:

- 四类互不继承的策略接口(Candidate / ObservableBaseline / Oracle /
  TestOnlyLeakProbe),正式候选每步只收到固定 shape 的 observation,
  正式评估路径不构造 future_returns、不传递 hidden/df;
- 候选默认运行于独立子进程(JSON-lines 只传 observation 数组,环境
  清洗,异常脱敏);
- 课程级 observation schema(有序特征 whitelist / 维度 / window /
  dtype / 归一化 pipeline / 账户槽位 / 预注册 nuisance 槽位 / 因果
  可用时点声明)可哈希并绑定 checkpoint sidecar v2 与密封承诺;
- 密封考试承诺(sealed commitment)逐项绑定 pack 哈希(含 timeframe
  与 resolved durations)、章程、schema、规范版本、generator/
  evaluator/counterfactual/verdict 代码哈希与完整 EvalConfig;CLI
  必须提供 --sealed-manifest,不存在忽略哈希通道,--fee 等覆盖参数
  提供即拒绝;
- formal_eligible 守卫:v1 sidecar 与 legacy/smoke checkpoint 一律
  拒绝正式考试;
- 冻结判定器(CourseVerdictSpec)以 G4 硬门组合产生
  PASS/FAIL/SUSPECTED_CHEATING/EXAM_INVALID,overall median > 0 不再
  不足以 PASS;
- 默认隐藏输出最小化(硬门布尔 + 匿名化 split + 粗粒度分数带),
  attempt registry 幂等可审计,详细输出立即退休考试包;
- 无关特征考试改为固定维度 nuisance 槽位注入/置乱(vol_24 不再被
  当作无关特征),signal ablation 按章程 signal groups;
- 作弊与普通挂科分离:SUSPECTED_CHEATING 需要四门证据(原始有效
  成绩 + 依赖禁止变量 + 反事实优势崩溃 + 多 Episode 重复);全程
  空仓/常数动作/未学习模型判 FAIL;
- verify_episode 在 generate() 内自动执行精确 observation whitelist
  (命名无关,factor_x/signal_quality/state_7 一律拒绝)与特征因果
  前缀重算校验;
- EpisodeSpec 显式绑定 timeframe,真实时长与解析 bars 进入考试包
  哈希,materialize 绝无静默默认 15m;
- 多类 Null:符号随机化 / 分块重排 / 波动状态条件随机化三族结构
  不同、跨族一致(全排列保留为探针;Fourier 相位替身经验证保留线性
  自协方差被否决)。

所有 11 项正式阻塞均已修复并有对应测试与证据。

## 2. PASS / FAIL

**PASS**(第六节 42 项 PASS 条件逐项成立;FAIL 条件 18 项零命中)。

## 3. 阶段 2.6.0 PASS 被重新审查的原因

阶段 2.6.0 报告判定 PASS 时,以下事实未被其测试覆盖(本阶段逐条
在代码中确认并修复):

1. `ActContext` 把 df/n_rows/tick/hidden/future_returns 交给每一个
   策略(含普通候选)——接口层即存在泄漏通道;
2. 隐藏考试 CLI 无密封承诺:pack/章程/版本/代码/条件均无预承诺,
   `--fee` 可命令行改写;
3. PASS 条件为 `overall["median"] > 0`,未执行 G4/Null/生成器留出/
   参数外推/反作弊硬门;
4. 脱敏输出保留 by_family/by_split/by_param_bucket/q10/worst/best,
   泄漏生成器族、split 与参数桶;
5. 无关特征注入通过新增 DataFrame 列实现,固定维度 PPO 无法执行;
6. vol_24 被硬编码为"无关特征",但它是正式市场特征;
7. 常数动作序列满足任意周期,`detect_periodicity([0]*10)==2` 把
   全程空仓/满仓判成 periodic_pattern;
8. `verify_episode` 只查 OHLC/NaN/行数,不查 observation whitelist,
   依赖外部脚本"之后可能调用"audit;
9. checkpoint sidecar v1 不绑定有序特征/维度/窗口/dtype/归一化;
10. EpisodeSpec 无 timeframe,`materialize_pack` 静默使用默认 15m;
11. Null 只用收益全排列一种构造,破坏过多市场结构。

重新审查的结论:2.6.0 的"基础设施存在且可运行"仍然成立(保留),
但"正式评估边界可信"不成立(本阶段重建)。

## 4. Candidate / Baseline / Oracle 能力隔离(工作包 A)

接口(互不继承,`src/rl_curriculum/policy_api.py`):

- `CandidatePolicy`: `reset_episode(derived_seed)` / `act(observation)`
  / `close()`——只有 observation(含仓位槽位),无 ctx/df/tick/
  n_rows/seed/split/family/params/hidden/future_returns/OHLC/考试类型/
  剩余时间;
- `ObservableBaselinePolicy`: 同一冻结 observation + schema 名称->槽位
  映射(`slot("ma_ratio")`);规则特征从 observation 槽位读取,不读 df;
- `OraclePolicy`: 独立 `OracleActContext`(仅当前行隐藏状态 + 当前
  仓位,`__slots__` 封闭,无未来/无完整帧);
- `TestOnlyProbePolicy`: 独立测试 harness(`act(obs, harness_ctx)`
  双参签名),`is_test_only_harness` 标记;正式入口
  `assert_formal_candidate` 对探针/Oracle/非策略对象一律
  FormalPolicyRejected。

证据:`policy_capability_matrix.md`(接口签名与 15 个策略类归属矩阵)、
`candidate_isolation_trace.json`(Spy 候选逐步收到的 shape/dtype =
(9,)/float32;评估栈帧扫描 hidden/future_returns 均不存在;正式入口
对探针/Oracle/杂物的拒绝记录)。测试:
test_candidate_policy_observation_only / test_oracle_context_is_separate /
test_candidate_cannot_read_hidden / test_candidate_cannot_read_future_returns。

说明:进程内 Python 候选理论上可经 `sys._getframe` 观察评估器自身
局部(评估器帧持有 episode 属正常,它负责构造 observation);该通道
的进程级隔离由子进程候选提供(第 5 节),子进程内不存在 episode/
hidden/future_returns 对象。

## 5. 候选子进程(工作包 A5)

`src/rl_curriculum/candidate_worker.py`:评估主进程以
`python -m rl_curriculum.candidate_worker <checkpoint> <charter_hash>
<observation_schema_hash>` 启动候选,JSON-lines 协议只传
`{"op":"act","obs":[...]}` 数组;`SubprocessCandidate` 实现正式
CandidatePolicy 接口,评估器对其与进程内候选一视同仁。

隔离属性(测试 test_candidate_subprocess_redaction):

- worker 命令行只有 checkpoint 与两个绑定哈希,无 pack/seed/family/
  split/manifest 路径;
- 启动环境经 `scrub_environment` 清洗(命中 SEED/FAMILY/SPLIT/PACK/
  EXAM/CHARTER/HIDDEN/PARAMS/NULL/VERDICT 模式的变量一律删除);
- 候选异常只回 `{"error":"candidate-error-redacted","stage":...}`,
  不回传 traceback;stderr 由父进程捕获但不进入任何输出;
- 错误 shape 的 observation 触发脱敏错误(fail closed,不吞错给分)。

## 6. Observation Schema(工作包 B/K1)

`src/rl_curriculum/observation_schema.py` 定义课程级 schema:

- 有序 FeatureSpec 列表(名称/因果可用时点 close_of_bar_t/最大历史
  窗口/nuisance 旗标/信号组/归一化);
- window_size、dtype、账户槽位顺序(target_position)、成本上下文
  声明、归一化方法与 pipeline 哈希、nuisance 填充语义、schema 版本;
- `schema_hash()`(前缀 o-),canonical JSON 确定性;
- `assert_same_semantics` 拒绝:特征顺序/维度/window/dtype/归一化
  方法/pipeline 哈希/账户槽位/nuisance 数量任一不同——总维度相同也
  拒绝语义错位;
- `sidecar_binding()`/`assert_sidecar_binding` 与 checkpoint 逐项比对。

探针课程 schema(probe-course-obs-v2):8 特征
(ret_1/ret_4/ret_12/vol_24/ma_ratio + nuisance_0/1/2),window=1,
float32,identity 归一化;obs dim = 9。
schema hash = `o-4d9e7b4c3dae66db0592d1bf043cd4f985bca92900700eae8f7a8236682e94be`。

哈希敏感性(observation_schema_manifest.json):特征换序 / window=2 /
float64 / nuisance 减为 2 / pipeline 替换,五个变体哈希互不相同。

## 7. checkpoint observation 绑定(工作包 F)

sidecar v2(checkpoint-manifest-v2)新增
observation_schema_hash/feature_names/dim/window_size/dtype/
normalization_pipeline_hash 六字段;`save_checkpoint_manifest` 的
formal_eligible 要求 charter 与 observation schema 双绑定;
`is_formal_eligible` 强制:v1 schema(阶段 2.6.0)即使写着
formal_eligible=true 也判 False;legacy 标记一律 False。

`SB3CheckpointPolicy` 的 expected_charter_hash 与
expected_observation_schema_hash 均为必填 keyword(缺一即
TypeError,调用方无法"忘记传参"跳过校验);act 内 shape/dtype
assert(fail closed)。

测试:test_checkpoint_observation_binding / test_normalization_pipeline_guard /
test_formal_checkpoint_required / test_checkpoint_charter_binding;
证据:formal_checkpoint_guard.json(v1/legacy/仅 charter/SHA pin 四场景
全部拒绝正式资格)。

## 8. 策略 Episode 生命周期(工作包 C)

每 Episode 由评估器调用 `reset_episode(derived_episode_seed(spec))`
(种子由 EpisodeSpec 规范化哈希派生,与输入顺序无关);随机基线每
Episode 独立 RNG。证据:policy_reset_determinism.json——有状态候选
跨 Episode 计数器清零、同 spec 重放动作逐位一致;RandomPolicy 重复
评估与输入逆序完全一致。测试:test_policy_episode_reset /
test_random_baseline_determinism。前馈 PPO 无跨 Episode 状态;未来
RNN 候选必须在 reset_episode 显式清零(接口已固定该合同)。

## 9. 评估指标修正(工作包 D)

EpisodeResult 新增 policy_action_switches / policy_order_executions /
forced_terminal_executions / total_execution_fees /
terminal_liquidation_fee / round_trip_count。修正:

- 终端清算手续费计入 total_fees(2.6.0 漏记;现
  total_fees = total_execution_fees + terminal_liquidation_fee 恒成立);
- n_trades 只计模型成交;强制终端清算单列 forced_terminal_executions;
- 换手率分子只含模型目标切换,强制清算不算模型主动换手;
- round_trip_count 由模型开平与终端强制平仓共同闭合;
- sum(reward_raw) == log(final/initial) 覆含全部费用
  (reward_consistency_ok,误差 < 1e-9)。

证据:evaluation_metric_reconciliation.json(3 策略 × 2 Episode 全对账)。
测试:test_terminal_fee_metrics。

## 10. sealed exam commitment(工作包 E)

`src/rl_curriculum/sealed_exam.py`:独立评估方在考试前创建
SealedExamCommitment,绑定 pack hash / charter hash / observation
schema hash / 六项规范版本 / 逐族 generator 版本+代码哈希 / evaluator
包哈希 / counterfactual 模块哈希 / verdict 哈希 / 完整 EvalConfig /
checkpoint 要求 / attempt policy;commitment hash(前缀 sc-)。

`verify_sealed_commitment` 逐项验证;任一不匹配抛 SealedExamError
-> CLI 输出 EXAM_INVALID(退出码 5)。mock 承诺:
`sc-4990414c3e19e4d8c2e90d70d3bb6ec0fc05b0511e38b3b185f6dff2dd72b9c9`。

篡改矩阵(sealed_exam_tamper_matrix.json,11 项全部拒绝):
换 pack seed / 换 charter / 换 observation 顺序 / 换 spec version /
替换 generator 代码 / 替换 generator 版本 / 替换 evaluator / 替换
verdict 阈值 / 改写 fee / 改写 window / 运行时 EvalConfig 覆盖 /
判定器阈值真实变化——全部 REJECTED。不存在"忽略哈希/强制继续"参数
(源码级断言,--ignore-hash/--force/--skip-verify 不存在)。

## 11. EvalConfig 密封(工作包 E1)

正式考试条件(fee/滑点/初始资金/窗口/确定性)由考试上下文与 sealed
manifest 双重冻结:CLI 的 --fee/--slippage/--window-size/--initial-cash
在正式模式提供即退出码 2 并说明"由 sealed manifest 冻结";上下文或
承诺中的 EvalConfig 不一致 -> EXAM_INVALID。开发调参只能走 --dev
(仅 public pack,输出 formal_conclusion=false,不产生毕业结论)。
测试:test_eval_config_override_rejected。

## 12. checkpoint 正式资格(工作包 F)

正式 CLI 只接受 formal_eligible=true 的 checkpoint:is_formal_eligible
要求 v2 + 章程 + observation 绑定 + 版本逐项匹配;密封承诺的
checkpoint_requirements 再比对 SHA-256/章程/observation(可 pin 具体
SHA)。阶段 2.5/2.6.0 smoke checkpoint 可继续做接口验证
(allow_legacy),正式考试拒绝。测试:test_formal_checkpoint_required;
证据:formal_checkpoint_guard.json。

## 13. 冻结课程判定器(工作包 G)

`src/rl_curriculum/verdict_spec.py`:CourseVerdictSpec 可规范化、可
哈希(前缀 v-),阈值与硬门进入哈希;判定器哈希进入密封承诺。
探针课程 mock 判定器:`v-818f490c9504b6616aa42420b5c6f3d1922e3c4834f3b131df516d97699bb1b5`
(阈值仅为验证基础设施,非正式及格线)。

G4 硬门:三个 split 中位数>0(seed holdout/参数外推/族留出)、
vs Always Flat bootstrap CI low>0、vs 规则基线中位差>0、seed pass
ratio、换手上界、(可选)q10/回撤、12 项反事实全部通过、三族 Null
一致通过、无作弊证据。状态四态:PASS / FAIL / SUSPECTED_CHEATING /
EXAM_INVALID。

证据:frozen_verdict_probe.json——"仅 median=+0.5 无反事实证据"判
FAIL(不再足以 PASS);全门通过判 PASS;seed holdout 为负判 FAIL;
作弊证据判 SUSPECTED_CHEATING;密封失败判 EXAM_INVALID。
测试:test_hidden_verdict_uses_g4_gates。

## 14. 隐藏输出脱敏(工作包 H)

`minimal_hidden_output` 只返回:attempt id / checkpoint hash / pack
hash / 状态 / 等级 / 硬门布尔(split 名匿名化为 split_N)/ 粗粒度
分数带 / 完整性 / 建议。禁止并验证不出现:family/split/参数桶/各组
样本数/各组收益/q10/worst/best/动作指纹/seed/params。CLI 输出中的
sealed 验证检查键同样匿名化族名,pack_families 只给计数。
`redact_report` 对 mock_hidden 连聚合分组都不返回(public 开发考试
保留聚合)。证据:hidden_output_redaction_v2.json(禁止 token 扫描
零命中)、mock_sealed_hidden_exam_summary.json(default_output_clean
=true)。测试:test_hidden_output_minimal / test_hidden_exam_redaction。

## 15. attempt registry(工作包 H1)

`src/rl_curriculum/attempt_registry.py`:记录 attempt id/pack/checkpoint/
时间/状态/是否详细公开/是否退休;同 (checkpoint, pack) 幂等返回同一
结果(标记 idempotent_retry_of,不产生新可探测信息);可配置每对
(checkpoint, pack) 的提交上限(超限 AttemptLimitExceeded,策略明确
不静默)。--detailed 是终结性披露:跳过幂等缓存、完整重评、立即退休。
证据:attempt_registry_demo.json;mock 流程 4 次提交全部可审计。

## 16. 固定维度 nuisance 考试(工作包 I1/I2/I4)

schema 预注册 3 个 nuisance 槽位(nuisance_0/1/2,生成器以独立
counter-hash 噪声填充,前缀逐位稳定,声明"不应含预测信息");
vol_24/ret_*/ma_ratio 是正式市场特征,永不被当作 nuisance。

- 注入考试:只把 nuisance 槽位内容替换为独立噪声——列集合不变、
  observation shape 恒为 (9,)、checkpoint 正常运行、不系统性提升成绩;
- 置乱考试:只时间置乱 nuisance 槽位,正式特征逐位不动;
- I4 shape 守卫:`_assert_same_observation_shape` 对任何变体维度变化
  抛错(映射 EXAM_INVALID);旧式"加列注入"在 schema 严格特征选择下
  直接 fail closed,不产生模型成绩。

证据:fixed_shape_nuisance_test.json(SB3 候选双考试 shape 恒定)。
测试:test_fixed_shape_nuisance_slots。

## 17. signal ablation(工作包 I3)

按章程 signal_groups(trend: ma_ratio+ret_4 / momentum: ret_1+ret_12 /
volatility: vol_24)分组消融(fixed_value 或 time_shuffle),shape
不变,记录消融组与方向。规则基线消融 trend 组后优势下降(pass);
未学习 PPO 不依赖 -> FAIL(课程声称的特征依赖对该 checkpoint 不
成立),明确 is_cheat_evidence=False——不构成作弊证据。
证据:signal_ablation_fixed_shape.json。测试:test_signal_ablation
(2.6.0 更新版)。

## 18. 作弊与普通挂科分离(工作包 J)

`classify_cheating` 四门证据(每个原因独立闸门):

1. 原始考试达到预注册最低有效成绩(中位 >= min_effective 且
   seed_pass_ratio >= 阈值);
2. 行为依赖课程禁止变量(对应反事实考试失败);
3. 该变量被反事实破坏后优势显著消失(变体成绩 < 最低有效线);
4. 多 Episode/seed 重复(n >= min_replication)。

`detect_periodicity` 要求实际仓位切换(>=2)、稳定周期与最小重复
次数(>=3 个完整周期);常数序列返回 None。
NullOvertrader 判 FAIL(高换手、扣费亏损)。

证据:cheating_vs_failure_matrix.json——StepCounter(固定结构场景,
中位 +6.8%)=> SUSPECTED_CHEATING(episode_position);StepCounter
(普通参数,无优势)=> FAIL;AbsolutePrice(buy_below=150 上行市场)
=> SUSPECTED_CHEATING(absolute_price);Periodic(相位对齐)=> 
SUSPECTED_CHEATING(periodic_pattern);Periodic(普通参数)=> FAIL;
AlwaysFlat/AlwaysLong => FAIL。测试:
test_constant_policy_is_fail_not_cheating / test_periodic_cheating_requires_advantage /
test_cheater_detection(2.6.0 更新版)。

## 19. 自动 observation whitelist(工作包 K/K2)

`verify_episode` 在 generate() 内自动执行:OHLCV 合法 / NaN-Inf /
hidden 行数 / 精确 whitelist(declared_feature_columns 之外的列一律
GeneratorError,与命名无关)/ hidden 与 observation 无交集 / 特征
因果前缀重算一致(截断到 n/2 与 n 重算特征+nuisance,逐位相等,
中心化窗口等未来依赖特征被直接暴露)。命名黑名单
(FORBIDDEN_OBSERVATION_PATTERNS)降级为辅助报告。

共同前缀考试(K2)升级:除 df 前缀逐位一致外,逐步比对完整
observation 向量(特征+账户槽位)——prefix_obs_all_slots_match。
nuisance 槽位按 counter-hash 前缀稳定。

证据:generator_whitelist_audit.json(factor_x/signal_quality/state_7/
noise_9 四个"无害命名"额外列全部拒绝;六个注册族 whitelist 精确、
hidden 隔离)。测试:test_generator_exact_feature_whitelist /
test_feature_causal_availability。

## 20. timeframe 与真实时长(工作包 E2)

EpisodeSpec 必填 timeframe(缺失/未知/None 构造即失败);generate()
的 timeframe 为必填 keyword(无默认);canonical 含 timeframe;
resolve_duration 支持 episode_bars 直接给定或 duration_hours 按
ceil/floor/raise 解析,原始值与解析结果全部进入考试包哈希;
ExamPack 校验包级与 Episode 级 timeframe 一致(不一致即
ExamPackError);materialize_pack 使用 spec 自带 timeframe 物化。
证据:timeframe_duration_binding.json(5m/15m/1h 哈希互异;四组
时长解析)。测试:test_episode_spec_timeframe /
test_duration_resolution_in_hash。

## 21. 多类 Null(工作包 L)

正式三族(generators.py,每族 meta 记录保留/破坏/分布差异/局限):

1. probe_null_sign(符号随机化):保留 |收益| 逐位不变(波动聚集
   幅度结构)与非高斯边际形状;破坏一切方向预测关系;
2. probe_null_block(分块重排,默认 8 bars):保留块内局部结构与
   短程自相关;破坏跨块关系(局限:块内残存局部趋势);
3. probe_null_volstate(波动状态条件随机化,方向 1):按因果波动
   代理(|r| 滚动均值)三分位分档,档内置换后叠加独立符号翻转;
   保留槽位波动档位与 |收益| 边际;破坏跨槽方向(隐藏标签保留但
   Oracle 优势被切断)。

probe_null_control(全排列)保留为探针,不计入正式最小集。

**Fourier 相位替身的否决记录**:本阶段曾实现相位随机化 + AAFT 幅度
秩匹配替身,验证时发现规则趋势基线在其上仍有稳定正超额(+3.97%
中位,bootstrap CI low > 0,4/4 seed 为正)——相位随机化保留自协方差
函数,即保留线性可预测性,对自相关源不构成"无信号"Null。按任务书
对 surrogate 方法"必须说明保留和破坏哪些统计属性、经过验证"的要求,
该构造被否决并替换为 probe_null_volstate。另:volstate 仅做档内置换
时 Oracle 保留稳定正超额(桶与 regime 强度相关,置换非符号盲),
补符号随机化后切断——两次否决记录均写入生成器文档与代码注释。

正式结论要求跨族一致:规则基线/Oracle/NullOvertrader/AlwaysFlat/
Random 在三族上全部无稳定正超额(multi_null_control_report.json,
cross_family_consistent=true)。测试:test_multiple_null_families /
test_null_control(2.6.0 更新版)。

## 22. 固定维度 PPO G4 烟雾(工作包 N)

测试级 PPO(test_ppo_fixed_dim,256 步,obs dim 9,formal sidecar
v2,声明"仅验证基础设施,允许挂科")真实执行全部 G4 考试
(sb3_g4_fixed_shape_smoke.json):18 Episode mock 包(含 seed holdout/
参数外推/族留出/三族 Null),12 项反事实全部执行并产出明确判定
(all_exams_executed=true):尺度/初始价/长度/时间平移/regime 顺序/
共同前缀/成本单调/Null 通过;nuisance 注入与置乱/信号消融/趋势镜像
挂科(未学习模型依赖噪声、无方向捕获——符合预期,且 nuisance 考试
shape 恒定)。冻结判定器输出 FAIL/G0(作弊证据:无)。未为通过考试
修改任何阈值或考试。测试:test_sb3_fixed_shape_counterfactuals。

## 23. mock 正式 hidden 流程(工作包 O)

mock_sealed_hidden_exam_summary.json(候选运行于子进程):

1. 评估方创建 mock pack(18 Episode)+ sealed commitment +
   retirement registry;
2. 训练侧只提交 checkpoint + sidecar;
3. CLI 验证 checkpoint/pack/承诺/章程/schema/EvalConfig/代码哈希
   (sealed_checks_pass=true);
4. 候选在子进程受限接口运行(只收 observation);
5. 冻结判定器输出四态之一与 G0-G4(本例 FAIL/G0);
6. 默认输出严格脱敏(泄漏 token 扫描零命中);
7. --detailed:详细报告写出,考试包立即退休;
8. 再次评估:EXAM_INVALID(退出码 5);
9. 4 次 attempt 全部入 registry 可审计(幂等重试标记)。

另:修改 pack seed/fee/observation 顺序/generator 代码/verdict 阈值/
evaluator 代码/checkpoint/章程 中任一项,均使承诺校验失败
(第 10 节篡改矩阵 + CLI 级测试)。本阶段只使用公开 mock 内容,
未创建正式隐藏种子/生成器/承诺。

## 24. 旧测试更新说明(阶段 2.6.0 测试)

原则:只更新编码了错误正式隔离语义的断言,以更严格断言替代;
无删除/skip/xfail;历史报告与 artifacts 未触碰。逐文件:

| 文件 | 旧断言(为何不够) | 新断言 |
|---|---|---|
| test_cheater_detection.py | `detect_periodicity([0]*10)==2`(常数=周期);`classify_cheating(tests)` 单参(无原始成绩/崩溃/重复门槛,行为异常即作弊) | 常数序列 is None + 换手下限;classify_cheating 四门证据,固定结构场景构造原始优势,NullOvertrader 断 ordinary_failure_only |
| test_periodicity 部分 | 旧签名把 PeriodicCheaterPolicy 判 SUSPECTED 无需成绩 | 需 base_effective+collapse+replication 三闸门同时成立 |
| test_null_control.py | 单族全排列 `eps` 列表 + `extra["excess_median"]` 顶层(只验证一种 Null) | 按族字典 + per_family 断言;新增三族正式 Null 与 sign/volstate 边际保留测试 |
| test_signal_ablation.py | `test_irrelevant_feature_injection` 加列实现(改变 obs 维度);shuffle 默认 vol_24(正式特征被当无关) | 更名 nuisance_slot_injection/shuffle:只动预注册槽位、断言 shape 恒定与 market_features_untouched;signal_ablation 按 signal_group |
| test_hidden_state_not_in_observation.py | observation_fields == 5 市场特征(不含 nuisance);泄漏靠命名审计 | 完整 8 列 whitelist;新增 factor_x/signal_quality/state_7 额外列 verify_episode 拒绝(命名无关) |
| test_exam_pack_hash.py | EpisodeSpec 四参构造(无 timeframe);哈希不含时长 | timeframe 必填断言 + resolved_durations 入哈希断言 + 混合 timeframe 拒绝 |
| test_exam_retirement.py / test_hidden_exam_redaction.py | `--policy rule_trend` 直评 CLI(无密封/无 checkpoint);脱敏只查 episodes 不在 | 密封模式全链路(承诺/checkpoint/context);默认输出禁止 family/split/参数桶/q10 等全部 token;幂等/退休/EXAM_INVALID 断言 |
| test_checkpoint_compatibility_guard.py | v1 sidecar + charter 即 formal_eligible=true | v2 双绑定才 formal;v1 强制 False;SB3 适配器双哈希必填(TypeError);同维度特征换序 sidecar 拒绝 |
| test_evaluator_determinism.py | `run_episode(policy, ep, cfg)` 旧签名;`act(obs, ctx)` 覆写 | run_policy_episode + schema;act(observation) 单参 |
| test_baseline_ordering / family_holdout / generalization_grade / price_scale / episode_length / common_prefix / generator_determinism | generate() 默认 timeframe;evaluate_policy 无 schema | 显式 timeframe="15m" + schema 参数;前缀考试断言全槽位一致 |
| conftest.py | 无 schema/checkpoint 夹具 | 新增 session 级 schema 与 formal_checkpoint(v2 正式 sidecar) |

全部 22 个测试文件中 5 个与改动无关原样通过,其余 17 个按上表更新
(净增测试:167 -> 182)。

## 25. 新测试结果(阶段 2.6.0a)

33 个新文件,166 项全部通过(零 skip/xfail):

test_candidate_policy_observation_only(4)、test_oracle_context_is_separate(4)、
test_candidate_cannot_read_hidden(4)、test_candidate_cannot_read_future_returns(3)、
test_candidate_subprocess_redaction(5)、test_observation_schema_hash(8)、
test_ordered_feature_guard(5)、test_normalization_pipeline_guard(5)、
test_fixed_shape_nuisance_slots(6)、test_policy_episode_reset(4)、
test_random_baseline_determinism(4)、test_terminal_fee_metrics(6)、
test_sealed_pack_commitment(11)、test_pack_hash_mismatch_is_invalid(3)、
test_spec_version_mismatch_is_invalid(4)、test_eval_config_override_rejected(5)、
test_formal_checkpoint_required(4)、test_checkpoint_charter_binding(3)、
test_checkpoint_observation_binding(4)、test_hidden_verdict_uses_g4_gates(9)、
test_hidden_output_minimal(4)、test_attempt_registry(6)、
test_constant_policy_is_fail_not_cheating(4)、test_periodic_cheating_requires_advantage(3)、
test_generator_exact_feature_whitelist(5)、test_feature_causal_availability(5)、
test_episode_spec_timeframe(5)、test_duration_resolution_in_hash(7)、
test_multiple_null_families(7)、test_sb3_fixed_shape_counterfactuals(3)、
test_generator_code_hash_binding(5)、test_evaluator_code_hash_binding(4)、
test_verdict_hash_binding(5)。

任务书要求的故障 fail closed 清单全部有对应测试:候选读 hidden/未来
(栈帧扫描+接口签名)、formal_eligible=false、charter/observation 不符、
pack 哈希不符、EvalConfig 命令行改写、generator/evaluator/verdict 替换、
timeframe 不符、特征顺序变化、normalization 变化、nuisance 数量变化、
pack 已退休、额外观察字段、候选异常泄漏 traceback(子进程脱敏)。

## 26. 已知限制

1. 进程内 Python 候选理论上可经解释器内省观察评估器帧(评估器持有
   episode 属正常);该通道的完全隔离依赖子进程模式(默认开启),
   未来正式考试可升级到系统级 sandbox;
2. 子进程候选每步一次 JSON-lines 往返,大规模评估有通信开销
   (mock 演示可接受;正式考试吞吐非目标);
3. verdict 的 mock 阈值(如 min_effective_net_return=0.0、
   seed_pass_ratio_min=0.6)只用于验证基础设施,正式课程及格线在
   2.6.2 校准冻结;
4. block Null 的块内残存局部结构已声明(个别 seed 超额可为正但不
   稳定);volstate 的波动代理窗口(12 bars)存在估计误差;
5. 考试上下文(charter/schema/verdict/EvalConfig 的 JSON 载体)在
   文件系统中未加密——任何篡改都会被承诺哈希抓获,但机密性不是
   本阶段目标(mock 内容全部公开);
6. attempt registry 为单文件 JSON,无并发锁(单评估方串行使用);
7. Fourier 相位替身与"仅档内置换的 volstate"两次否决记录保留在
   代码注释与本报告,未保留其实现(避免误用)。

## 27. 是否允许进入阶段 2.6.1

**允许**。前置条件(第 10 节 FAIL 清单)全部未命中;正式评估边界
已建立:候选只能获得 observation、考试密封绑定代码与条件、判定器
冻结、输出最小化、作弊与挂科分离、多 Null 一致。

## 28. 复现命令

```bash
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
# 全部证据
python experiments/route_c_stage2_6_0a/run_all.py
# 全量回归(2.5 -> 2.6.0a)
bash   experiments/route_c_stage2_6_0a/run_regression.sh
# 单独运行密封 mock 流程(子进程候选)
python - <<'PY'
from rl_curriculum.mock_sealed_exam import *
# 见 experiments/route_c_stage2_6_0a/run_all.py::mock_sealed_flow
PY
# 测试
python -m pytest tests/route_c_stage2_6_0 tests/route_c_stage2_6_0a -q
```

## 29. 证据索引

artifacts/route_c_stage2_6_0a/(与公开仓库 stage2_6_0a/artifacts/ 同):

| 文件 | 内容 |
|---|---|
| policy_capability_matrix.md | 四接口签名与 15 策略归属矩阵 |
| candidate_isolation_trace.json | 候选逐步输入 shape/dtype、栈帧扫描、入口拒绝 |
| observation_schema_manifest.json | schema 载荷/哈希/绑定字段/哈希敏感性 |
| observation_order_mismatch_test.json | 同维换序等四场景拒绝 |
| normalization_guard.json | pipeline 替换拒绝 |
| policy_reset_determinism.json | 生命周期清零与 Random 确定性 |
| evaluation_metric_reconciliation.json | 终端费用/换手/往返全对账 |
| sealed_exam_commitment.json | mock 承诺 + 验证报告(sc-4990414c...) |
| sealed_exam_tamper_matrix.json | 11 项篡改全拒绝 |
| formal_checkpoint_guard.json | v1/legacy/仅 charter/SHA pin 场景 |
| frozen_verdict_probe.json | 判定器五场景(median>0 不足以 PASS) |
| hidden_output_redaction_v2.json | 最小输出与泄漏扫描 |
| attempt_registry_demo.json | 幂等/上限/审计字段 |
| fixed_shape_nuisance_test.json | SB3 固定维度 nuisance 双考试 |
| signal_ablation_fixed_shape.json | 消融(规则 pass/PPO FAIL) |
| cheating_vs_failure_matrix.json | 作弊 vs 挂科七场景 |
| generator_whitelist_audit.json | 无害命名额外列拒绝 + 六族审计 |
| timeframe_duration_binding.json | timeframe/时长入哈希 |
| multi_null_control_report.json | 三族文档与跨族一致 |
| sb3_g4_fixed_shape_smoke.json | 固定维度 PPO 全 G4 执行 |
| mock_sealed_hidden_exam_summary.json | 密封流程八步闭环 |
| regression_test_summary.md | 全量回归(619 项) |
| upstream_integrity.txt | 上游 clean 证明 |

关键哈希:

- charter: c-2ade551fc6c98e09e8f8f81942a18a615a9a4b3d7d29dc6b8bf80dc5ec9ac843
- observation schema: o-4d9e7b4c3dae66db0592d1bf043cd4f985bca92900700eae8f7a8236682e94be
- verdict spec: v-818f490c9504b6616aa42420b5c6f3d1922e3c4834f3b131df516d97699bb1b5
- mock sealed commitment: sc-4990414c3e19e4d8c2e90d70d3bb6ec0fc05b0511e38b3b185f6dff2dd72b9c9
- evaluator_code_hash: e-(运行时计算,覆盖 rl_curriculum 全包)
