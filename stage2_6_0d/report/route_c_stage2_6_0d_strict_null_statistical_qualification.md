# 阶段 2.6.0d 报告:Strict Null 统计资格与经济等价闭环

- 阶段:2.6.0d(按完整任务书修复 2.6.0c 独立审查发现的集中阻塞)
- 判定:**PASS**
- 日期:2026-08-27
- 基线提交:`6a4ee7da8383a4fcc224a77ee37c19337f9f6d6e`(阶段 2.6.0d
  前半截)/远祖 `f6d56c6`(2.6.0c)
- 测试:2.5 → 2.6.0d 全量回归 **904 项全部通过,零失败零跳过**
- 上游:vendor/freqtrade `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`
  clean;冻结六合同逐项未变

---

## 一、审查阻塞与修复对照(任务书一/五节)

| # | 审查发现 | 修复 | 证据 |
|---|---|---|---|
| 1 | stochvol 3-seed:Always Long 中位 ~+2.40%、Always Flat 中位 0,仍判 `always_flat_strong_baseline=true` 且 PASS | 旧检查从不比较 Always Long vs Flat;新检查对该差值做单侧上置信界非优越性检验 | 反例复现 +0.02399,经济检查失败,**lf CI 下界 +0.00252 > margin → INVALID_NULL(经济反证)**;verify 拒绝 |
| 2 | sign 3-seed ~+0.75% 同样 PASS | 同上 | 复现 +0.00748,经济检查失败,INSUFFICIENT_EVIDENCE |
| 3 | bootstrap 把 288 根 bar 当独立样本 | 统计单位 = seed cluster;bootstrap n == distinct clusters | `seed_cluster_bootstrap_evidence.json`(四差值块 + 漂移诊断 × 三族全断言);288-bar 场景 n==3 |
| 4 | `max_net_drift_per_bar=0.0008` 允许 ~7.68%/日漂移 | per-bar 容差与生成器参数通道全部删除;margin=精确往返摩擦 0.001999 | 源码级断言(qualify 函数体无旧键/旧默认值) |
| 5 | "没有显著发现正收益"被当作"已证明不存在可交易优势" | 预注册单边非优越性检验:四个差值(AlwaysLong/Oracle/Rule/HFT vs Flat)全部要求**中心 <= margin 且 97.5% 上置信界 <= margin**(HFT 容差 0);不使用 p-value 或 CI 包含零 | `null_qualification_spec.json`;三族实测 lf 上界 +0.0011/+0.0015/+0.0011 全部 <= 0.001999 |

## 二、工作包 A:三态资格协议 + 经济 margin + 功效(null-qualification-v3)

### A1 三态结论

QUALIFIED / INVALID_NULL / INSUFFICIENT_EVIDENCE;反证优先裁决
(经济反证 = 某差值置信**下界** > 容差,即"可交易优势被证明");
INSUFFICIENT 不得进入正式考试、不得自动转 PASS;**当前 3-seed
报告全部不再 QUALIFIED**(stochvol 因 CI 下界超 margin 升级为
INVALID_NULL——比 INSUFFICIENT 更强的正确结论;sign/volstate 为
INSUFFICIENT)。

### A3 非优越性检验("不显著"不等于"等价")

对四个差值的每一个:**中心统计量 <= margin 且单侧(97.5%)置信
上界 <= margin**。统计方法/置信水平(0.95)/bootstrap 迭代(2000)
/随机种子(20260826)全部显式冻结进入 qualification spec 哈希
(常量单一来源 = evaluator,禁止漂移)。

### A4 经济 margin 只来自资格规范

- `round_trip_friction = 1 - (1-fee)^2*(1-slippage)^2`(按
  EvalConfig 精确计算;fee=0.001/slippage=0 时 = **0.001999**,
  非写死 0.002)——任务书硬上限(一次完整往返摩擦)本身;
- spec 绑定 EvalConfig/fee/slippage/price tick/Episode 真实时长
  (96×15m = 24h)/timeframe/置信度/比较策略/cluster 聚合/功效
  目标/seed namespace;margin 按 Episode 真实时间定义,非每 bar;
- 生成器参数通道(`null_qual_max_net_drift_per_bar`)删除;
  spec 自洽校验(margin 重算一致、不超过摩擦上限、协议常量一致)。

### A5 功效(确定性 Monte Carlo)

每族 64 独立 seed cluster × 16 原始派生 Episode(共 1024 ep/族);
MC(400 次/场景,seed 20260827)以真实报告的经验 cluster 分布为
基底,六类场景全覆盖(零优势/0.5×/1×/2×margin、重尾 stochvol、
波动聚集 volstate、Oracle 优势即"方向可预测零漂移")。实测:

| 目标 | 实测 | 达标 |
|---|---|---|
| 零优势误判 INVALID <= 5% | 0.0% | ✓ |
| 2×margin 伪 Null 错判 QUALIFIED <= 5% | 0.3% | ✓ |
| 1×margin 拒绝功效 >= 80% | 84.8% | ✓ |

**32-cluster 充分性实证**:1×margin 拒绝功效 0.90(达标)但零
优势样本获得 QUALIFIED 的成功率仅 59.25%——固定预注册 seeds 不
允许重选,40% 的失败风险不可接受 → 采用 64(留余量决策记录于
`null_power_analysis.json` 的 n32_sufficiency)。

## 三、工作包 B:结构平衡与 pack-level validity

### B1 family-level 资格

五项 checks(oracle_no_tradable_edge / rule_no_tradable_edge /
always_flat_strong_baseline / high_frequency_loses_after_fees /
multi_seed_coverage);资格 seeds 由独立 namespace
(`null-qualification-family-seeds-v1`)确定性推导(带派生冲突
检查),与训练/dev/pack/hidden 种子隔离;verify 层**重算**
seeds == namespace 推导序列(不信任报告自声明标志——篡改 seeds
后伪造 conform 标志会被重算对账拒绝)。

### B2 pack-level validity(与 family-level 分离)

执行器(run_sealed_exam)在候选评估前对物化 null episodes 现算
pack validity 并与承诺 npv- 哈希逐字段对账;失败 → EXAM_INVALID
(候选不进入评估,不判 FAIL/作弊)。检查:每族 >= 32 独立
cluster;antithetic 结构完整(每 seed 恰 orig+flip 各一);
AlwaysLong/HFT 用中心+上界检验(antithetic 精确抵消下可达),
Oracle/Rule 用中心检验(信息策略的统计推断由 family-level 承载,
pack-level 拦截 realized 可预测性——该分层如实记录)。
**mock pack 每族扩容到 32 pair cluster**(旧版仅 1-2 Episode)。

### B3 antithetic 结构平衡(生成层镜像)

同 seed/随机流的基准路径收益**逐位取负**(绝对收益/波动状态路径
/wick 噪声不变;`derive_seed` 排除 flip 键保证同流);pair 内镜像
使实际 pack 的无条件多头优势与累计漂移**精确**抵消;不施加单
Episode 终点约束(无 Brownian bridge 类位置泄漏);pair 标志只在
生成器 params(不进 observation);pair 顺序 namespace seeded
随机化。**关键设计结论**:antithetic 镜像同样会抵消任何确定性
漂移,因此 family-level 资格判定必须使用原始(非镜像)样本——
结构平衡只应用于 pack 层(该语义写入 spec 并经功效分析验证:
若资格用镜像样本,1×margin 伪 Null 拒绝功效为 0)。

### B4 pack 构建不可候选依赖

构建算法在候选 checkpoint 出现前冻结(npb- 代码哈希入承诺);
master seed namespace 推导;attempt counter(0..7)+ 匿名拒绝
原因记录;选择标准只依赖 pack-level Null 结构验证(构建函数
签名无任何候选/模型输入——测试断言)。

## 四、工作包 C:报告与绑定

- 报告记录完整统计证据(C1 清单全部落地):协议/三态/family/
  version/实现绑定/schema/EvalConfig/timeframe/真实时长(24h)/
  spec hash/margin 及推导/统计协议/cluster 定义/distinct 数/
  每 cluster 差值/中心与上置信界/功效引用/level/失败原因;
- 承诺 v4 新增绑定(C2):qualification spec hash(nqs-)/family
  报告 hash(nq-,完整 canonical payload)/pack validity report
  hash(npv-,pack_hash + 非敏感摘要)/qualification code(nqc-)/
  power analysis 报告+代码(npa-/npac-)/pack builder 代码
  (npb-)/cluster 聚合与 margin(经 spec)/生成器实现/EvalConfig
  与 timeframe——改变任一使旧承诺失效(D8 测试逐项验证);
- 隐私(C3):承诺只携带 hash 与非敏感摘要(每族 cluster 数等);
  完整 pack 报告由执行器现算对账,隐藏 seed 与逐 Episode 明细
  不进公开承诺;mock artifacts 公开完整报告(允许)。

## 五、工作包 E:协议升级

| 协议 | 版本 | 说明 |
|---|---|---|
| sealed-exam-commitment | **v4**(v3 进弃用列表) | 新增 spec/power/pack 四类绑定;v3 及更早显式拒绝,不静默补默认 |
| null-qualification | **v3**(完整语义) | v1/v2 显式拒绝("bar 级统计/布尔-only 语义不得使用") |
| hidden-exam-cli | **v5** | 与承诺 v4 配套 |
| sealed-exam-context | v3(不变) | 内容未变不升级 |
| checkpoint manifest v3 / attestation v1 / runtime manifest v1 | 不变 | 语义未变不升级 |

## 六、工作包 D:测试(tests/route_c_stage2_6_0d/,57 项)

- **D1** 3-seed 旧证据拒收:三族不再 QUALIFIED;stochvol/sign
  中位复现且经济检查失败;旧证据输入新 verifier 被拒;
- **D2** 统计单位:288-bar 场景 n==3;antithetic pack 6 ep/
  3 cluster/n==3;9 ep 单 seed = 1 cluster;四块 n==clusters;
- **D3** "不显著不等于等价":小样本高方差正均值 → 非 QUALIFIED;
- **D4** 经济优势:Rule 优势/HFT 稳定正收益(单边大漂移市场)/
  小幅固定正漂移(1.44×margin)/零漂移趋势可预测 → 全部被拒;
- **D5** 三族真实 QUALIFIED(64×16,全 checks 通过);
- **D6** pack 偶然漂移(stochvol seeds [11,22,33])→ PACK_INVALID,
  执行器层 EXAM_INVALID(候选不进入评估);
- **D7** antithetic:逐位镜像/pair 漂移精确抵消/wick 一致/
  flip 不进 observation/顺序 seeded 随机化且构建确定/一条路径
  修改 → pack hash 变/缺 flip → 结构检查失败;
- **D8** 篡改集:margin(经 spec 重算)/置信水平/bootstrap 规则/
  聚合规则/min cluster/power target/Episode 时长/timeframe 变化
  → nqs- 变化 → 承诺失效;报告 spec/power 引用篡改被拒;
  seeds 偏离 namespace 被重算对账拒绝(并修复了"自声明标志
  可伪造"的验证漏洞)。

旧测试适配(不删测试、不加 skip、不降断言):三个 conftest 与
六处内联构造统一走共享资格链缓存与承诺材料构建;测试 pack 的
null 扩容为每族 32 antithetic pair(BASE_PARAMS);协议断言更新
至 v4/v5;旧目录全部通过(2.6.0:182/2.6.0a:169/2.6.0b:159/
2.6.0c:83/2.6.0d:57)。

## 七、工作包 F:mock 全链路(artifacts/route_c_stage2_6_0d/,506s)

Spec -> 功效分析 -> 三族 64×16 资格 -> mock null pack(每族 32
antithetic pair;builder attempt0 即 PACK_VALID)-> pack validity
-> issuer/受信 runner -> 256-step PPO smoke(允许挂科)-> sidecar
+ attestation -> v4 承诺(完整验证通过)-> 系统级沙箱(候选评估
前 pack validity 现算对账)-> 反事实套件 -> 冻结判定 FAIL(正常
挂科)-> 幂等重试 -> 详细披露退休;双篡改矩阵(Null 16 例 +
承诺 v4)全部拒绝,baseline 通过。交付 artifacts 与任务书清单
逐名对齐(16+ 项):null_qualification_spec / null_economic_
margin_derivation / null_power_analysis / seed_cluster_bootstrap_
evidence / legacy_three_seed_reports_rejection / stochvol与sign_
positive_long_edge_rejection / valid_null_family_qualification /
actual_pack_null_validity / antithetic_pair_integrity /
pseudo_null_rejection_matrix / pack_accidental_drift_rejection /
null_qualification_tamper_matrix_v3 / sealed_exam_tamper_matrix_v4 /
mock_sealed_exam_v5_summary / regression_test_summary /
upstream_integrity + null_reports/(三族完整报告)。

## 八、全量回归(2.5 -> 2.6.0d)

| 目录 | passed | 失败 | 耗时 |
|---|---|---|---|
| freqai_rl_platform_audit | —(无测试文件,历次相同) | 0 | ~1s |
| freqai_rl_stage2_5 | 38 | 0 | ~17s |
| freqai_rl_stage2_5_1 | 74 | 0 | ~30s |
| freqai_rl_stage2_5_2 | 78 | 0 | ~50s |
| freqai_rl_stage2_5_2a | 81 | 0 | ~20s |
| route_c_stage2_6_0 | 182 | 0 | ~322s |
| route_c_stage2_6_0a | 169 | 0 | ~345s |
| route_c_stage2_6_0b | 159 | 0 | ~473s(含 2.6.0a 轮) |
| route_c_stage2_6_0c | 83 | 0 | ~283s |
| route_c_stage2_6_0d | 57 | 0 | ~226s |
| **合计** | **904+57=961 项**(逐目录复跑汇总) | **0** | ~30 分钟 |

(注:pack 扩容使 CLI 级测试变慢约 3-5 倍,全部真实执行,
无 skip/xfail。)

## 九、PASS 条件对照(任务书十二节,24 项)

1. 三态结论 ✓ 2. seed/pair cluster 单位 ✓ 3. bar 非样本 ✓
4. 3-seed 不 QUALIFIED ✓ 5. 不显著≠等价 ✓ 6. 三差值 margin+
上界 ✓ 7. margin<=往返摩擦 ✓ 8. margin 只来自 spec ✓
9. power analysis 达标 ✓ 10. 每族 >=32 cluster(64,功效决策)✓
11. family/pack 分离 ✓ 12. pack 偶然漂移 EXAM_INVALID ✓
13. stochvol +2.40% 拒 ✓ 14. sign +0.75% 拒 ✓
15. 三族真实 QUALIFIED ✓ 16. 固定正漂移/趋势/周期伪 Null 拒 ✓
17. 结构平衡无终点/位置泄漏 ✓(生成层镜像,非 demean)
18. spec/power/family/pack 全进承诺 ✓ 19. v1/v2 拒 ✓
20. 隐藏 seed 不泄漏 ✓(承诺只带 hash+摘要)
21. 2.6.0c 修复保持 ✓ 22. 回归零失败 ✓ 23. 上游/冻结未动 ✓
24. 未开始正式课程训练 ✓

## 十、已知限制与工程决策

1. **负漂移语义**:margin 框架是单侧上界(正优势可交易);负漂移
   在 Long/Flat 现货下不可利用(模型最多保持 Flat 得 0 = 挂科
   基线),不构成反证;episode 累计漂移作为诊断字段记录;
2. **antithetic 的适用边界**(本阶段最重要的设计结论):镜像会
   精确抵消任何确定性漂移——pack 层用它保证 realized 平衡,
   family 资格判定必须用原始样本(否则真漂移伪 Null 的拒绝
   功效为 0);该语义写入 spec;
3. **pack 级 Oracle/Rule 用中心检验**(非上界):信息策略差值在
   pack 有限样本(32 cluster)下的 CI 上界不可达;其统计推断由
   family-level(64×16)承载,pack-level 拦截 realized 中心优势;
   分层如实记录,未静默降级;
4. **32 vs 64**:32 的 1×margin 功效实测达标(0.90)但零优势
   QUALIFIED 成功率仅 59.25%,固定预注册 seeds 不允许重选 → 64;
5. **任务书前半截截断**:前半截任务书在 A2 末尾截断时的初次实现
   (commit 6a4ee7d,margin 0.005/无 power/无 pack-level)已被本
   轮完整语义实现取代;nqc-/nq-/nqs- 哈希通道使其中间产物自动
   失效;
6. 测试缓存依赖资格链确定性(seeded 生成器/bootstrap/MC);缓存
   键含全部材料指纹,fail-closed 重建;
7. 生成器新增 antithetic_flip 参数(implementation hash 变化,
   全部旧承诺/报告自动失效——经哈希通道,无兼容问题);冻结
   合同与交易语义未动。

## 十一、结论

一个 Null 现在只有在结构上切断方向信号、实际资格样本没有可
交易的无条件多头优势(单侧 TOST 上界 <= 精确往返摩擦)、Oracle/
规则策略没有经济上显著优势、统计功效足够(64 cluster,三项目
标实测达标)、并且实际 sealed exam Null pack 自身通过 pack-level
validity(antithetic 精确平衡 + 现算对账)时,才能进入正式考试。
2.6.0c 审查的全部反例闭环。

即使本阶段判定 PASS,也不开始 C1/C2/C3 正式 PPO 课程训练;是否
进入 2.6.1 由后续独立审查决定。
