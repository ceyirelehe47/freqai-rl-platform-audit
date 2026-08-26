# 阶段 2.6.0b 报告:密封执行、可信训练来源与评估统计最终修复

- 日期:2026-08-26(UTC)
- 环境:WSL CryptoRL-Ubuntu-24.04(内核 6.18.33.2-microsoft-standard-WSL2)/
  conda freqtrade-rl / Python 3.11.16
- 上游:Freqtrade 2026.7,commit 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5,
  工作树 clean(零修改)
- 基准:阶段 2.6.0a 提交 5f13f49(RouteCEnvCore-v1.0.0 未修改,
  本阶段再次确认)
- 判定:**PASS**
- 测试:781 项全部通过(2.5 38 / 2.5.1 74 / 2.5.2 78 / 2.5.2a 81 / 2.6.0 更新后 182 / 2.6.0a 更新后 169 / 2.6.0b 新增 159;platform_audit 目录只含审计脚本无 pytest 用例,与阶段 2.6.0/2.6.0a 口径一致);零 skip/xfail 删除
- 本阶段未开始任何正式 C1/C2/C3 课程训练;测试级 PPO(256 步,
  mock attestation 签发)仅证明 provenance 与执行链路(允许挂科)
- 是否允许进入阶段 2.6.1:**允许**

---

## 1. 执行摘要

阶段 2.6.0a 的全局 PASS 建立在六个未被发现(或被误判为已解决)
的正式阻塞上:真实时长只进哈希不进行数、正式候选只有 API 级
JSON-lines 隔离、nuisance 检验单边、反作弊重复证据不真实、
formal_eligible 可由训练侧自行声明、block shuffle 被当作完全无信号
Null。本阶段完成最终评估基建修复:

- 工作包 A:统一参数解析通道(resolve_generator_params):任何
  生成器 `_generate` 之前,课程声明的真实时间字段(duration_hours /
  regime 时长范围 / 特征窗口 / 决策间隔 / 延迟收益阶段 / 回撤阶段)
  全部解析为 bars 并注入 effective params;生成器不再有静默默认
  (`params.get("episode_bars", 96)` 全部删除);实际行数必须等于
  resolved bars,不一致即 GeneratorError(EXAM_INVALID 路径);
- 工作包 B:reset_episode() 无参数:候选不再收到由隐藏 EpisodeSpec
  派生的 derived_seed 身份 token;worker 协议 reset 消息逐字节
  `{"op": "reset"}`(携带任何额外字段 = 协议违规);随机基线确定性
  迁移到 ObservableBaselinePolicy.episode_instance 工厂(seed 只进入
  基线通道);
- 工作包 C:系统级密封沙箱:unshare(user+mount+pid+proc+net
  namespace)+ Landlock(ABI v4,deny-by-default)+ 只读 bind mount
  中性 checkpoint 路径 + rlimits(CPU/AS/FSIZE/NOFILE/NPROC)+ 父进程
  侧单步超时与 stdout 行长上限;--no-subprocess 与 use_subprocess
  参数删除(源码级);最小候选运行时 rl_candidate_runtime(worker +
  守卫 + bootstrap,共 5 个文件)是沙箱内唯一项目代码;十类攻击
  探针(读工作区/隐藏包/父进程/网络/写 checkpoint/超长输出/失控
  子进程/内存/文件大小/fd)全部失败;
- 工作包 D:nuisance 双边等价检验(NuisanceEquivalenceSpec 预注册
  等价区间 [-δ,+δ]/动作一致率/换手与仓位容差/变换 seed 数):
  显著改善 FAIL、显著恶化 FAIL、依赖 FAIL、无法证明等价 FAIL;
- 工作包 E:每种作弊原因独立聚合真实多 Episode/多 seed 证据
  (build_replication_evidence):实际测试数/失败数/动作分歧分布/
  配对收益差/优势崩溃 bootstrap;共同前缀 3 Episode × 3 切割点;
  删除"缺少变体收益即默认崩溃"的旧逻辑——缺证据的 required 原因
  → EXAM_INVALID,非 required 诊断 → insufficient_evidence;
- 工作包 F:生成器实现指纹(generator_binding):逐族绑定实际类
  源码/定义模块/MRO 基类模块/声明依赖/资源文件/family_version
  (不再是共享 generators.py 哈希);修改任何成分 → 该族承诺失效;
  修改无关生成器不影响目标族绑定;
- 工作包 G:可信训练 attestation(Ed25519):sidecar 只证明
  format_compatible;formal_eligible 唯一来源是受信签发方签名的
  attestation(绑定 checkpoint/sidecar/训练 manifest/章程/schema/
  环境/runner hash/PPO 参数/预算/种子/smoke 标志);十项篡改矩阵
  全部拒绝;
- 工作包 H:Null 家族重新资格审查:block shuffle 重新分类为
  partial_dependency_destruction 诊断族(保留块内方向关系,退出
  required_null_families);新增第三种机制 probe_null_stochvol
  (独立实现的马尔可夫随机波动率零漂移市场);三族全部通过五项
  资格审查(Oracle 无方向优势/规则无超额/净漂移近零/高频扣费亏损/
  多 seed 覆盖);资格绑定(逐族 report hash + 审查代码 hash)进入
  sealed commitment;漂移伪 Null 被拒绝(INVALID_NULL);
- 工作包 I:版本全面升级:candidate-worker-v2 / checkpoint-manifest-v3
  / training-attestation-v1 / sealed-exam-commitment-v2 /
  course-verdict-spec-v2 / hidden-exam-cli-v3;v1 承诺被 v2 执行器
  显式拒绝(版本不兼容);v2 sidecar 不再产生 formal_eligible;
- 工作包 J:mock 正式全链路 v3 闭环 + 完整篡改矩阵(十四项全部
  EXAM_INVALID 或需要新承诺)。

RouteCEnvCore-v1.0.0 未修改(env.py/ledger/market_execution/reward
零触碰);上游 Freqtrade clean。

## 2. PASS / FAIL

**PASS**(第六节 40 项 PASS 条件逐项成立;FAIL 条件 19 项零命中)。

## 3. 阶段 2.6.0a PASS 被重新审查的原因

2.6.0a 报告判定 PASS 时,以下事实未被其测试覆盖(本阶段逐条在
代码中确认并修复):

1. `resolve_duration` 解析出 resolved_bars 并进入考试包哈希,但每个
   生成器 `_generate` 仍执行 `params.get("episode_bars", 96)`——
   48h@15m 声明 192 bars,实际生成 96 行,manifest 与真实内容背离;
2. 候选只是 JSON-lines 子进程:共享文件系统(可读评估工作区/隐藏包
   生成器源码)、共享 PID/proc(可读父进程 cmdline/environ)、共享
   网络、共享当前用户权限;--no-subprocess 可退回进程内执行;
3. `reset_episode(derived_seed)` 把由隐藏 EpisodeSpec 规范化哈希派生
   的稳定 token 交给候选:候选可凭它识别/区分隐藏试题(身份侧信道);
4. nuisance 考试只检查 `variant - base <= 0`:模型因 nuisance 变化
   大幅崩溃时仍然通过(单边检验);
5. 反作弊"多 Episode 重复"实际把 `report["n_episodes"]`(整个考试包
   总数)当作某项反事实的重复次数;共同前缀只测 seed_eps[0] 一个
   Episode、一个 50% 切点;
6. `variant_collapsed` 在缺少变体收益证据时返回 True(默认优势崩溃
   成立);
7. generator binding 哈希公共 generators.py:私有隐藏生成器被替换
   只要注册表模块整体哈希不变就不会被发现(逐族绑定缺失);
8. `formal_eligible=true` 由训练侧在 sidecar 里自行填写即生效
   (v2 双绑定只证明格式兼容,不证明训练来源可信);
9. block shuffle 保留块内趋势与短周期方向关系,却被列为
   required_null_families 的"完全无信号 Null"硬门。

重新审查结论:2.6.0a 的"接口拆分/observation schema/密封承诺框架/
判定器四态"保留且被 v2/v3 版本继承;但"正式考试边界可信"在上述
九点上不成立(本阶段重建)。

## 4. resolved duration 实际物化(工作包 A)

统一参数解析通道(param_resolution.py):

```
原始课程参数 + timeframe
  -> resolve_generator_params()          # 唯一入口
     ├─ resolve_duration()               # episode 总时长 -> episode_bars
     └─ resolve_time_field() × N         # 其余时间字段 -> 各自 bar 参数
  -> effective params(已含解析后的 bars)
  -> 生成器 _generate(直接 params["episode_bars"],无默认值)
  -> len(df) == resolved_bars 强校验(不一致即 GeneratorError)
```

证据(actual_duration_materialization.json):

| timeframe | duration_hours | resolved_bars | 实际行数 | pack hash |
|---|---|---|---|---|
| 15m | 48 | 192 | 192 | 互异(3 组) |
| 5m | 48 | 576 | 576 | 互异 |
| 1h | 48 | 48 | 48 | 互异 |

不存在回退到 96 行默认值的路径:所有 `params.get("episode_bars", 96)`
已从生成器删除(直接键访问,缺键即 KeyError);实际行数与 resolved
bars 不一致时 generate() 抛 GeneratorError(测试用故意截断的生成器
验证)。同时给出真实时长与显式 bars 不一致 -> 解析即失败;date 轴
间隔与 timeframe 逐组一致(resolved_parameter_trace.json 含逐字段
trace 与解析语义哈希 rps-)。

## 5. 真实时间字段解析机制(工作包 A3)

TIME_FIELD_BINDINGS 预注册注册表(可扩展,进入 sealed commitment
的 resolved_parameter_semantics_hash):

| 真实时间字段 | 目标 bar 参数 | 类别 |
|---|---|---|
| duration_hours | episode_bars | episode_total |
| regime_duration_hours_range | regime_len_range | regime_duration_range |
| feature_window_hours | feature_window_bars | feature_window |
| decision_interval_minutes | (校验=timeframe) | decision_interval |
| delayed_reward_phase_hours | delayed_reward_phase_bars | delayed_reward_phase |
| drawdown_phase_hours | drawdown_phase_bars | drawdown_phase |

- 范围字段解析为 [bars_lo, bars_hi],逐字段 trace 记录原始值/取整
  规则/解析结果/实际生效值;
- 声明了字段但目标参数已显式存在且不一致 -> 直接失败(禁止静默取
  其一);decision_interval 与 timeframe 不一致 -> 失败;
- 生成器侧配合修复:`_random_regimes` 不再产生"一大段兜底"——段长
  一律取自解析范围,余量(< lo_len)并入上一段并记录(probe-A-v2)。

## 6. Candidate reset 身份 token 移除(工作包 B)

- 接口:`reset_episode(self) -> None`(源码级断言参数列表 == ["self"]);
- worker 协议(candidate-worker-v2):reset 消息逐字节 `{"op": "reset"}`;
  携带任何额外字段(derived_seed/episode_id/seed/spec_hash/...)→
  stage=reset-identity-token 协议违规(fail closed);
- 随机基线:RandomPolicy(seed) 构造 + episode_instance(episode_seed)
  工厂——episode_seed 只存在于 ObservableBaselinePolicy 通道,候选
  评估路径对其不可达;重复评估与输入逆序完全一致(测试);
- 有状态候选跨 Episode 清空;两个 observation 前缀完全相同但
  EpisodeSpec 不同的题目,候选前缀决策逐位一致(候选无任何身份
  通道可用于区分);前馈 PPO 与 RNN 风格候选都能用无参数 reset
  (RNN 状态在 reset 内清零)。

## 7. 正式沙箱技术选择(工作包 C)

WSL2 内核 6.18 提供完整组合(实测,sandbox_capability_matrix.md):

| 能力 | 状态 |
|---|---|
| unshare user+mount+pid+proc+net 组合 | 可用 |
| tmpfs 挂载(mount ns 内) | 可用 |
| bind mount + remount 只读 | 可用 |
| 空 network namespace(仅 down lo) | 可用 |
| Landlock | ABI v4 |
| PR_SET_NO_NEW_PRIVS | 可用 |
| bubblewrap | 未安装(未使用;unshare+Landlock 已满足全部要求) |

最终隔离栈:unshare(user+mount+pid+mount-proc+fork+net)→
bootstrap(rl_candidate_runtime.bootstrap:中性只读 checkpoint 路径
/tmp staging 内 model/ → Landlock deny-by-default → rlimits → 关闭
3+ fd → execve worker)。Landlock 规则:read+exec 授予系统运行时
(conda env/usr/lib/bin/sbin/opt)与最小运行时 staging;read-only
授予 /etc /proc /sys 与 model 目录;rw 授予 /dev 与 scratch
(tmpfs)。其余一切(评估工作区/隐藏包/项目目录/用户 home 其余
部分/真实 /tmp 其余内容)读/写/执行全部拒绝。

## 8. WSL namespace/sandbox 能力验证

见第 7 节矩阵;全部为实际执行结果(不是方案描述)。沙箱能力不足时
sandbox_capability_report()["system_level_sandbox_available"]=False,
正式考试拒绝执行(FAIL 条款:不得把普通子进程再次称为正式密封执行)。

## 9. 文件系统隔离(工作包 C3/C8)

sandbox_denial_trace.json:评估工作区 sentinel/隐藏包/sealed
manifest/退休注册表/私有生成器源码/项目根/用户 home 的
read/list/write 全部 PermissionError;all_denied=true。
mountinfo 不泄漏 home/项目路径(checkpoint 先复制到 staging 再
bind mount,源路径只在中性临时目录内)。唯一可写目录是沙箱
scratch(tmpfs)。

## 10. PID/proc 隔离(工作包 C4)

sandbox_proc_isolation.json:沙箱内 /proc 数字条目 = ["1"](仅自身);
评估主进程 pid 的 /proc/<pid>/cmdline、environ、fd 不可读(pid 在
新 PID namespace 中不存在);3+ 继承 fd 全部关闭;worker 环境无
SEED/FAMILY/SPLIT/PACK/EXAM/CHARTER/HIDDEN/PARAMS/NULL/VERDICT
模式变量。

## 11. 网络隔离(工作包 C5)

sandbox_network_test.json:loopback 连接 OSError、外部 IP 连接
OSError、DNS 解析 gaierror;/proc/net/route 无外部路由(空 netns)。

## 12. 最小候选运行时(工作包 C6)

src/rl_candidate_runtime(5 个文件,公开仓库包含全部源码):
- worker.py:JSON-lines 协议(candidate-worker-v2;reset 无 token;
  输出行长上限;非法 obs/op fail closed);
- guard.py:sidecar v3 验证(SHA-256/冻结版本/章程/observation 绑定;
  只证明 format_compatible);
- bootstrap.py:mount/Landlock/rlimit/fd/执行布置(先隔离后加载
  checkpoint);
- versions.py:冻结环境版本常量的自包含副本(测试断言与
  rl_platform.versions 逐项相等)。

沙箱内不存在 generators/exam_pack/formal_exam/sealed_exam/
verdict_spec/evaluator 等评估代码(rl_curriculum 包不挂载)。

## 13. 资源限制(工作包 C7)

sandbox_resource_limits.json:RLIMIT_CPU=1800s、RLIMIT_AS=6144MB、
RLIMIT_FSIZE=64MB、RLIMIT_NOFILE=256、RLIMIT_NPROC=512(按真实 uid
全系统计数,容纳 torch/libgomp 线程池);自定义 profile 逐项生效。
父进程侧:单步响应超时(step_timeout)与 stdout 单行 4096 字节上限
(worker 侧与父进程侧一致);超时/超限/协议违规 ->
CandidateSandboxError → EXAM_INVALID,不产出部分成绩(测试覆盖:
超长行/超时/非 JSON 回复/非法 op)。

## 14. nuisance 双边等价检验(工作包 D)

NuisanceEquivalenceSpec(预注册,进入 verdict spec 与承诺):
δ=0.002(收益等价半区间)/action_match_min=0.98/turnover_abs_tol=
0.02/position_abs_tol=0.02/n_transform_seeds=3/bootstrap 2000@α=0.05。

判定(evaluate_nuisance_equivalence,注入与置乱共用):
- 行为稳定:逐 Episode 动作一致率 >= 阈值;
- 收益稳定:配对差 bootstrap CI 完全位于 [-δ, +δ];
- 换手/仓位稳定:|中位差| <= 容差;
- CI high > δ → improvement FAIL;CI low < -δ → degradation FAIL;
  行为不稳 → dependency FAIL;CI 未出界但不入区间 → insufficient
  FAIL。failure_modes 列出全部命中模式。

证据(nuisance_equivalence_report.json):RuleTrend(忽略 nuisance)
注入/置乱双 PASS(动作一致率 1.0);nuisance_dependency_failure.json:
故意读取 nuisance_0 的策略 FAIL(dependency);测试覆盖 improvement
(尾部阈值策略在上行外推市场从注入的正态尾部获利)与 degradation
(变体触发逆势持仓)。正式市场特征逐位不变、observation shape
恒定。

## 15. 多 seed 反作弊证据(工作包 E)

- run_counterfactual_suite:共同前缀 3 Episode × 3 切割点(0.25/0.5/
  0.75);价格尺度/初始价/长度/时间平移/regime 重排各 2+ Episode;
  逐作弊原因 build_replication_evidence 聚合:实际测试 Episode 数/
  不同 seed 数/失败数/失败比例/动作分歧率分布/首个分歧位置聚合/
  配对收益差与 bootstrap/变体收益 bootstrap/复制门槛达成;
- 复制计数来自实际记录(records 携带 episode_seed),与考试包总
  Episode 数无关(集成测试断言 tested != 包总数);
- classify_cheating 修复:同名考试多条记录不再被 by_name 字典折叠
  (旧实现最后一条通过记录会覆盖前面的失败记录)。

## 16. 优势崩溃统计(工作包 E3)

- 变体收益 bootstrap 上界 < 最低有效线 = 崩溃(逐原因);
- 缺少变体收益证据:collapse_evidence_available=False,崩溃不默认
  成立——SUSPECTED_CHEATING 不输出;required 原因进入
  missing_collapse_evidence → 判定器 EXAM_INVALID;诊断原因 →
  insufficient_evidence(replicated_cheating_evidence.json 与
  single_seed_not_cheating.json 记录五门 gate 全字段);
- 旧 `if not extra_nets: return True` 与 variant_collapsed 已从源码
  删除(测试源码级断言)。

## 17. 实际生成器实现绑定(工作包 F)

generator_binding.py:逐族指纹 = sha256(canonical{实际类源码,
定义模块文件,MRO 基类模块,协议模块,声明依赖文件哈希,资源文件
哈希,feature_columns,family_version})(前缀 gi-)。

- generator_implementation_binding.json:注册表全族指纹互异;
  sample manifest 展示逐成分绑定;
- private_generator_tamper_test.json:两个独立模块的私有生成器,
  类实现/特征依赖/family_version 篡改各自改变指纹;无关族不受
  影响;声明依赖/资源缺失直接失败;
- sealed commitment v2 的 generator_bindings 为逐族三元组
  (family_version, implementation_hash, manifest_hash);verify 逐族
  重算比对(篡改矩阵:替换实现哈希 → 拒绝)。

## 18. 可信训练 attestation(工作包 G)

training-attestation-v1(Ed25519):

- 载荷:checkpoint/sidecar/训练 manifest 的 SHA-256、章程与
  observation schema hash、RouteC 环境版本、训练生成器与训练包
  hash、训练代码 hash、PPO 完整参数、网络架构与参数量、训练预算、
  训练种子、is_smoke、allow_formal_evaluation、issuer_id、
  training_runner_hash、签发时间;canonical JSON 签名;
- G3 私钥隔离:mock 私钥只存在于评估方临时目录;不进入仓库/训练
  Agent 工作区/环境变量/checkpoint/候选沙箱;评估方只在承诺中绑定
  公钥指纹与 runner hash;
- sidecar v3:format_compatible(绑定齐全即 true)+ 训练 manifest
  引用;formal_eligible 字段恒 false 且声明
  formal_eligibility_source=training_attestation_only(训练侧自填
  boolean 被明确忽略);
- trusted_training_attestation_demo.json:受控训练 runner(测试级
  PPO 256 步)→ 不可变训练 manifest → mock trusted issuer 签发 →
  验证签名与逐项绑定 → formal_eligible=true。

## 19. issuer 与 runner 信任链(工作包 G6)

TrustedIssuerConfig(issuer_id/公钥/指纹/必需 training_runner_hash/
allow_smoke)进入 sealed commitment;attestation 协议版本
(training-attestation-v1)与 allow_smoke 策略一并绑定。篡改矩阵
(attestation_tamper_matrix.json):自签名/未受信公钥/checkpoint 替换/
sidecar 修改/训练 manifest 修改/章程变化/schema 变化/smoke 伪装/
runner hash 不符/绑定其他 checkpoint —— 全部拒绝;唯一通过的是
合法 mock attestation。

## 20. strict Null 资格审查(工作包 H3)

null_qualification.py(代码哈希 nqc- 进入承诺):五项检查:
1. Oracle 无稳定方向优势(读隐藏状态也不盈利,bootstrap CI);
2. 可观察规则无稳定超额(RuleTrend vs Always Flat);
3. 净漂移近零(汇集全部 bar 的每 bar 平均对数收益 bootstrap CI ⊂
   ±8e-4;策略级 Always Long vs Flat 的每 Episode 比较统计功效
   不足,已在实现中说明);
4. 高频策略扣费亏损(HighTurnover 中位 < 0);
5. 多 seed 覆盖(>= 3 个不同 seed)。

strict_null_qualification.json:三族全部通过(8 seed × 96 bar);
每族资格绑定 {family_version, qualification_pass, report_hash}
进入 sealed commitment;漂移伪 Null(direction_weights [0,0.85,0.15])
被拒绝(INVALID_NULL);修改 Null 实现 → implementation hash 变化 →
原资格证明对实现失效(测试)。

## 21. block shuffle 重新分类(工作包 H1)

probe_null_block → partial_dependency_destruction / local-structure
robustness test(block_shuffle_reclassification.md):
- 保留:块内局部结构/短程方向关系(测试:块均值漂移显著大于 iid
  噪声尺度);
- 破坏:跨块关系;
- is_null_family=False(诊断族);不在 FORMAL_NULL_FAMILIES /
  verdict required_null_families / 章程 formal_null_families 中;
- mock 包不再包含该族 Episode;其上获利的短周期规则不触发 Null
  作弊(测试)。

## 22. sealed commitment v2(工作包 I)

sealed-exam-commitment-v2 绑定:pack/charter/observation schema/
六项规范版本/逐族生成器实现三元组/evaluator/counterfactual/
verdict(含 nuisance 等价区间与复制门槛)/完整 EvalConfig/
sandbox profile 哈希(sp-)/严格 Null 资格绑定与审查代码哈希/
受信 issuer(公钥/指纹/runner hash/smoke 策略)/resolved parameter
semantics 哈希(rps-)/checkpoint 要求(require_trusted_attestation)/
attempt policy。v1 承诺被显式拒绝(版本不兼容,测试);
sandbox profile 缺失或不匹配 → EXAM_INVALID(verify 强制)。

版本升级总表:

| 组件 | 旧 | 新 |
|---|---|---|
| candidate worker 协议 | v1(带 derived_seed) | candidate-worker-v2(无 token) |
| checkpoint sidecar | checkpoint-manifest-v2 | checkpoint-manifest-v3(attestation 语义) |
| training attestation | (无) | training-attestation-v1 |
| sealed exam commitment | v1 | sealed-exam-commitment-v2 |
| verdict spec | course-verdict-spec-v1 | course-verdict-spec-v2 |
| hidden exam CLI | hidden-exam-cli-v2 | hidden-exam-cli-v3 |
| 课程基础设施 | rl-curriculum-stage2_6_0a-v1 | rl-curriculum-stage2_6_0b-v1 |

## 23. mock 正式考试(工作包 J)

mock_sealed_exam_v2_summary.json:评估方准备(mock pack v3/承诺
v2/issuer 公钥/沙箱 profile)→ 受控训练来源(测试级 PPO 256 步 +
不可变 manifest + mock issuer 签发)→ CLI 正式模式(32 项密封检查
全过)→ 候选沙箱执行(reset 无 token;无隐藏包挂载;无网络;无父
进程信息)→ 冻结判定器输出 FAIL/G0(测试级模型允许挂科,未为通过
修改任何考试)→ 幂等重试返回同一 attempt。全程 12.1 秒。

## 24. 篡改矩阵(工作包 J5)

sealed_exam_tamper_matrix_v2.json(raw duration/生成器实现/Null 资格/
沙箱 profile/EvalConfig/nuisance 阈值/复制门槛/pack/resolved bars/
checkpoint/attestation 缺失/训练 manifest/issuer 公钥)+ 
attestation_tamper_matrix.json:全部 EXAM_INVALID 或验证失败
(需要新承诺);合法路径唯一。

## 25. 旧测试更新说明

规则:只更新编码了 2.6.0a 错误正式语义的断言,以更严格断言替换;
无删除/skip/xfail;历史报告与 artifacts 未触碰。逐文件清单见
公开仓库 stage2_6_0b/tests/ 内各文件顶部"阶段 2.6.0b 更新"说明
与 
逐文件摘要(2.6.0a 目录 6 个 + 2.6.0 目录 7 个 + conftest):

| 文件 | 旧断言(为何不可信) | 新断言 |
|---|---|---|
| 2_6_0a/test_sealed_pack_commitment.py | 承诺构造缺 trusted_issuer/verify 缺 sandbox_profile 也能过;code_hash 篡改共享模块哈希 | 双侧必给参数;逐族 implementation_hash/manifest_hash 篡改被拒;无 attestation 拒绝;新增 v1 承诺拒绝/缺 issuer/缺 profile 三个更严测试(12→15 项) |
| 2_6_0a/test_eval_config_override_rejected.py | 携带已删除的 --no-subprocess | 移除旗标;"无强制继续参数"改为 argparse 定义集实证 |
| 2_6_0a/test_evaluator_code_hash_binding.py | verify 不给 sandbox_profile 也通过 | 必给 profile 且沙箱哈希检查通过 |
| 2_6_0a/test_verdict_hash_binding.py | 同上 | 同上 |
| 2_6_0a/test_generator_code_hash_binding.py | sealed_exam.generator_bindings 共享 m- 哈希 | generator_binding 逐族 gi- 三元组;CLI 级篡改键为 implementation_hash |
| 2_6_0a/test_candidate_subprocess_redaction.py | SubprocessCandidate(已删)/reset 带 seed | SandboxedCandidate;reset 无参;argv 中性占位符且无原始提交路径 |
| 2_6_0/conftest.py | formal_checkpoint 断言 formal_eligible=True(v3 下恒 False,9 个 fixture error) | attested checkpoint(sidecar v3+manifest+Ed25519);断言 formal_eligible=False + is_format_compatible=True |
| 2_6_0/test_hidden_exam_redaction.py | 无 attestation/无 issuer/v1 上下文/--no-subprocess/probe_null_block | attested + context v2 + 承诺 v2 真实沙箱全链路;严格三族 |
| 2_6_0/test_exam_retirement.py | 同上 | 退休/复用拒绝走真实 EXAM_INVALID(退出码 5) |
| 2_6_0/test_cheater_detection.py | classify_cheating 旧签名(n_episodes_tested 冒充复制数) | build_replication_evidence 逐 seed 真实证据;四门逐门断言;作弊场景显式 regimes 使变体崩溃可测 |
| 2_6_0/test_checkpoint_compatibility_guard.py | formal_eligible=True | formal_eligible=False + format_compatible=True + 自声明无效 |
| 2_6_0/test_common_prefix_invariance.py | splice_prefix_suffix 缺 timeframe(TypeError) | 显式 timeframe |
| 2_6_0/test_episode_length_invariance.py | 随机 regimes 恰好全非正(不确定性) | 显式混合方向 regimes(确定性场景) |
。

## 26. 新测试结果(阶段 2.6.0b)

32 个新文件,159 项全部通过(零 skip/xfail):

test_duration_hours_materializes_rows(7)、test_resolved_params_reach_generator(7)、
test_regime_duration_resolution(8)、test_candidate_reset_has_no_identity_token(6)、
test_formal_cli_has_no_inprocess_bypass(6)、test_sandbox_filesystem_denial(4)、
test_sandbox_hidden_pack_denial(3)、test_sandbox_parent_proc_denial(4)、
test_sandbox_network_denial(4)、test_sandbox_readonly_checkpoint(3)、
test_sandbox_resource_limits(5)、test_sandbox_output_protocol_limit(5)、
test_sandbox_profile_binding(5,含 v1 承诺版本拒绝)、
test_nuisance_bidirectional_equivalence(4)、test_nuisance_dependency_fails(2)、
test_nuisance_improvement_fails(2)、test_nuisance_degradation_fails(2)、
test_counterfactual_actual_replication_count(5)、test_single_seed_failure_not_cheating(7)、
test_multi_seed_cheating_evidence(6)、test_missing_collapse_evidence_is_invalid(3)、
test_generator_actual_implementation_hash(6)、test_private_generator_module_tamper(4)、
test_training_attestation_signature(10)、test_untrusted_issuer_rejected(3)、
test_self_declared_formal_eligible_rejected(4)、test_training_manifest_tamper(4)、
test_smoke_checkpoint_attestation_rejected(3)、test_block_shuffle_not_strict_null(6)、
test_strict_null_qualification(6)、test_invalid_null_rejected(6)、
test_mock_sealed_exam_v3(6)。


fail-closed 清单逐项对应:duration 与行数不一致(test_resolved_
params_reach_generator::test_generator_row_mismatch_is_generator_error)
/候选收到 token(接口签名+worker 逐字节+行为区分)/正式进程内
(--no-subprocess 不存在+argparse 拒绝+run_sealed_exam 无参)/隐藏包
与工作区可读(sandbox_denial)/父进程可读(proc 隔离)/网络可用
(netns)/checkpoint 可写(三层只读)/nuisance 改善与恶化(双边等价)
/单 seed 冒充多 seed(replication 计数)/缺崩溃证据默认成立
(missing_collapse → EXAM_INVALID)/生成器实现变化(gi- 绑定)/
sidecar 自声明(is_formal_eligible 恒 False)/attestation 无效与
issuer 不受信/smoke 伪装/block shuffle 误当严格 Null/未资格审查的
Null 进入考试(verify_null_qualification_bindings)。

## 27. 已知限制

1. Landlock 不约束 io_uring/部分 ioctl;网络 TCP 连接限制(ABI v5
   scoped sockets)未启用——本阶段以独立 network namespace 提供网络
   隔离(更强);
2. RLIMIT_NPROC 按真实 uid 全系统计数:上界必须容纳系统内该 uid
   的其他进程(取 512;失控子进程爆炸仍被约束,与 cpu_seconds
   一起封顶);
3. 沙箱候选每步一次 JSON-lines 往返(实测 ~0.5ms/步):正式考试
   吞吐非本阶段目标;
4. mock 判定器阈值与 nuisance 等价区间(δ=0.002 等)只用于验证
   基础设施;正式课程阈值在 2.6.2 校准冻结;
5. attestation 的信任锚是 issuer 私钥持有者:私钥方可以对新载荷
   重新签发(验证层无法区分)——这是设计边界(信任链的终点),
   依赖签发工具与私钥保管流程;评估方只能绑定公钥与 runner hash;
6. stochvol 的波动状态本身可预测(这是保留的结构):若未来课程
   能力是"波动率择时",需要补充波动择时维度的 Null(与方向 Null
   联合覆盖);
7. 净漂移资格审查阈值 ±8e-4/bar 基于 768 bar 汇总检验的功效
   (SE ~1bp):介于零漂移与 16.8bps 伪漂移之间;更弱的漂移(<5bps)
   可能漏检——但此类漂移同时会被 Oracle/规则检查在策略层捕获。

## 28. 是否允许进入阶段 2.6.1

**允许**。FAIL 清单 19 项零命中;正式评估边界已重建:真实时长物化、
无身份 token、系统级沙箱(文件/PID/网络/资源/协议五维隔离)、
attestation 信任链、双边等价检验、真实多 seed 复制证据、逐族实现
绑定、严格 Null 资格审查。

## 29. 完整复现命令

```bash
source ~/projects/crypto_rl/activate-freqtrade.sh
cd ~/projects/crypto_rl
git -C vendor/freqtrade describe --tags --exact-match   # 2026.7
git -C vendor/freqtrade rev-parse HEAD                  # 52bc96f...
# 全部证据(24 项 artifacts)
python experiments/route_c_stage2_6_0b/run_all.py
# 全量回归(2.5 -> 2.6.0b)
bash experiments/route_c_stage2_6_0b/run_regression.sh
# 新增测试
python -m pytest tests/route_c_stage2_6_0b -q -p no:cacheprovider
```

## 30. 证据索引

artifacts/route_c_stage2_6_0b/(与公开仓库 stage2_6_0b/artifacts/ 同):

| 文件 | 内容 |
|---|---|
| actual_duration_materialization.json | 48h×3 timeframe 实际行数与 pack hash |
| resolved_parameter_trace.json | 逐字段解析 trace 与语义哈希 |
| candidate_reset_protocol.json | 无 token reset 协议与源码证据 |
| sandbox_capability_matrix.md | WSL 内核沙箱能力矩阵 |
| sandbox_profile_manifest.json | 沙箱 profile 载荷与哈希 |
| sandbox_denial_trace.json | 文件系统拒绝 + mountinfo 无泄漏 |
| sandbox_network_test.json | loopback/外部/DNS 全拒 |
| sandbox_proc_isolation.json | /proc 仅自身 + 父进程不可达 |
| sandbox_resource_limits.json | 五类 rlimit 实测 |
| nuisance_equivalence_report.json | 双边等价(注入+置乱) |
| nuisance_dependency_failure.json | 依赖 nuisance 策略 FAIL |
| replicated_cheating_evidence.json | 多 seed 四门证据(成立) |
| single_seed_not_cheating.json | 单 seed 不判作弊 + 缺证据演示 |
| generator_implementation_binding.json | 逐族实现指纹与 verify |
| private_generator_tamper_test.json | 私有生成器篡改矩阵 |
| trusted_training_attestation_demo.json | 受控训练→签发→验证链路 |
| attestation_tamper_matrix.json | attestation 篡改矩阵 |
| strict_null_qualification.json | 三族资格审查 + 伪 Null 拒绝 |
| block_shuffle_reclassification.md | block shuffle 降级说明 |
| sealed_commitment_v2.json | mock 承诺 v2 与绑定覆盖 |
| sealed_exam_tamper_matrix_v2.json | 十四项考试篡改矩阵 |
| mock_sealed_exam_v2_summary.json | mock 全链路八步闭环 |
| regression_test_summary.md | 全量回归 |
| upstream_integrity.txt | 上游 clean 证明 |

