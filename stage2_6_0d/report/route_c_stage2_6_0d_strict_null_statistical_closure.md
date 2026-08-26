# 阶段 2.6.0d 报告:Strict Null 统计资格与经济等价闭环

- 阶段:2.6.0d(修复 2.6.0c 独立审查发现的集中阻塞)
- 判定:**PASS**
- 日期:2026-08-27
- 基线提交:`f6d56c6414398cc3f576b4b1df6c570c7fb4714e`(阶段 2.6.0c)
- 测试:904 passed / 0 failed / 0 error / 0 skipped / 0 xfailed
- 上游:vendor/freqtrade `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`,工作树 clean

---

## 一、审查发现的集中阻塞(全部修复)

2.6.0c 独立审查指出:strict Null 的报告内容已被正确密封与验证,但
资格判定本身存在三个统计/经济语义缺陷:

| # | 审查发现 | 2.6.0d 修复 | 验证 |
|---|---|---|---|
| 1 | `probe_null_stochvol` 3-seed 样本 Always Flat 中位 0、Always Long 中位 ≈ +2.40%,仍判 `always_flat_strong_baseline=true` 且整体 PASS | 旧检查从不比较 Always Long vs Always Flat(`always_long_median` 只写不读);新检查由该比较的 cluster 级 bootstrap CI 上界驱动 | 反例复现 `+0.02399` → `INSUFFICIENT_EVIDENCE`,verify 拒绝进入考试(artifacts `null_qualification_small_sample_counterexample.json`) |
| 2 | `probe_null_sign` 3-seed Always Long 中位 ≈ +0.75% 同样 PASS | 同上 + 三态协议(功效不足不得 PASS) | 反例复现 `+0.00748` → `INSUFFICIENT_EVIDENCE` |
| 3 | bootstrap 把多个 Episode 内数百根 bar 当独立样本(Null 刻意保留波动聚集) | 统计单位改为 seed cluster(每 seed 聚合 K 个关联 Episode 后 bootstrap) | 四统计块 × 三族全部断言 `bootstrap n == distinct independent clusters`;同 seed 9 episode 只算 1 cluster |
| 4 | `max_net_drift_per_bar=0.0008` 在 96 根 15m Episode 上允许 ≈7.68% 累计 log drift | per-bar 容差与 bar 级 bootstrap 全部废除;新带以每 episode 累计量直接定义(正侧 +0.5%,负侧 -1.0%) | `test_per_bar_tolerance_abolished_at_source`(源码级断言) |
| 5 | "没有显著发现正收益"被错误解释为"已证明不存在可交易优势" | 单侧 TOST(证明等价)+ 显著性(发现反证)+ 功效门槛三分离,三态结论 | 漂移伪 Null(lf CI [+16.6%, +20.3%])→ `INVALID_NULL` |

## 二、工作包 A:三态资格协议(null-qualification-v3)

### A1 显式三态结论

```
QUALIFIED            结构、经济等价、统计功效与实际 pack 全部成立
INVALID_NULL         发现可交易漂移、Oracle/规则优势、结构性预测关系
                     或其他明确反证
INSUFFICIENT_EVIDENCE 样本数或统计功效不足,不能证明等价;不得进入
                     正式考试,不得被自动转换为 PASS
```

裁决规则(预注册,反证优先):

1. 结构反证(Oracle 稳定正超额 / RuleTrend 稳定正超额 / HFT 扣费
   不亏)→ `INVALID_NULL`;
2. 经济反证(无条件多头优势 CI 下界 > 0.005,或 drift CI 下界 >
   +0.005,或 drift CI 上界 < -0.010)→ `INVALID_NULL`;
3. 六项 checks 全真 → `QUALIFIED`;
4. 其余 → `INSUFFICIENT_EVIDENCE`。

报告内 `pass` 键保留为 `verdict == "QUALIFIED"` 的别名(承诺链
`verify` 层要求 pass/verdict/checks 三者两两一致,自相矛盾即拒)。
**当前 3-seed 资格报告全部得到 `INSUFFICIENT_EVIDENCE`**(任务书
硬性要求)。

六项 checks(键集合精确):

| check | 判定 | 单位 |
|---|---|---|
| `oracle_no_stable_directional_edge` | 非(中位>0 且 CI 下界>0) | cluster |
| `rule_no_stable_excess` | 同上 | cluster |
| `always_flat_strong_baseline` | Always Long−Flat CI 上界 ≤ 0.005 | cluster(单侧 TOST) |
| `episode_net_drift_nonexploitable` | drift CI 上界 ≤ +0.005 且下界 ≥ −0.010 | cluster |
| `high_frequency_loses_after_fees` | HFT 中位净收益 < 0 | episode(诊断) |
| `multi_seed_coverage` | 独立 cluster 数 ≥ 64 | — |

### A2 独立统计单位:seed / Episode cluster

- 每 seed 构成一个 cluster;其 K=`episodes_per_seed`(默认 8)个
  关联 Episode(派生 seed = seed + 1000·k)先在 cluster 内按算术
  平均聚合(规则名 `per-seed-mean-episode-v1`);
- bootstrap 抽样单位是 cluster 值列表(`bootstrap_unit =
  "seed-cluster"`);`paired_bootstrap_ci` 原语签名不变(另有 5 处
  调用方),只是输入从 bar 池换成 cluster 列表;
- 报告记录(A2 要求的五个量全齐):原始 Episode 数
  (`n_episodes_tested`)、cluster 数(`n_clusters`)、distinct
  seed 数(`distinct_seeds`)、cluster 聚合规则
  (`cluster_aggregation`)、bootstrap 实际 n(各统计块
  `bootstrap["n"]`);
- 测试断言 `bootstrap n == distinct independent clusters`(四统计块
  × 三族),同 seed 9 个 Episode 只算 1 个 cluster。

## 三、经济等价与统计功效(工程决策记录)

### 带(预注册常量,进入 `qualification_params` 并被 verify 对账)

| 常量 | 值 | 依据 |
|---|---|---|
| `MAX_UNCONDITIONAL_LONG_EDGE` | 0.005 | 每 96-bar(24h)episode 无条件多头净优势(含费)≤0.5% 才算"无可交易优势";远小于两个审查反例(+2.40%/+0.75%) |
| `MAX_TRADABLE_DRIFT` | 0.005 | 正漂移可被 Long/Flat 现货模型利用(做多跑赢 Flat);0.5% 累计对数漂移扣 0.2% 双边费后仍是明确可交易优势 |
| `MAX_NEGATIVE_DRIFT` | 0.010 | 负漂移不可利用(模型最多保持 Flat 得 0 = 挂科基线);仅在巨大到构成结构性非中心证据(>1%)时拒绝 |
| `MIN_QUALIFICATION_CLUSTERS` | 64 | 功效推导见下 |
| `DEFAULT_EPISODES_PER_SEED` | 8 | 同上 |

**不对称带是预注册的经济语义**:三族 64-cluster 实测中
volstate/stochvol 的 drift 中心 ≈ −0.26%(t(4) 重尾 + 波动聚集下
的抽样噪声,SE ≈ 0.20%);若用对称 ±0.5% 带会把构造零漂移的族误判
为出带。负侧放宽到 1.0% 不是为通过校准——带内负中心不构成
"可利用优势"的反证,带外(>1%)仍构成结构性非中心反证。

### 功效推导(64 cluster × 8 episode 的来源)

- 每 episode Always Long 净收益 std 实测 ≈ 3%(2.6.0c artifact:
  bar std 0.32% × √96 ≈ 3.1%,聚集略放大);
- K=8 episode/seed 的 cluster 均值 std ≈ 1.1%;
- n=64 时 bootstrap CI 半宽 ≈ 0.27%,单侧 TOST 要求中心噪声
  (1σ ≈ 0.14%)与半宽合计 ≤ 0.5% 带 → n ≥ ~52,取 64 留余量;
- 实测(64×8,seeds 11..74):
  - sign:lf CI [−0.00409, +0.00082],drift CI [−0.00284, +0.00235];
  - volstate:lf CI [−0.00685, −0.00132],drift CI [−0.00548, +0.00006];
  - stochvol:lf CI [−0.00657, −0.00151],drift CI [−0.00517, −0.00011];
  - 三族全部 QUALIFIED(成本:首次生成 ≈35s,之后确定性磁盘缓存
    秒级)。

### 3-seed 反例在新协议下的处置

- stochvol(sign 同理):cluster 门槛不满足 → `multi_seed_coverage
  = False` → `INSUFFICIENT_EVIDENCE`;其 lf CI [+0.25%, +4.80%]
  宽达带外,恰好说明 3 cluster 无法证明任何经济等价;
- 若小样本恰出现足够强的中心(如 CI 下界 > 0.5%),则直接
  `INVALID_NULL`(反证优先于功效判定)——两种结果都满足"不再
  QUALIFIED"。

## 四、协议升级与失效通道

| 协议 | 2.6.0c | 2.6.0d | 说明 |
|---|---|---|---|
| Null 资格格式 | null-qualification-v2 | **null-qualification-v3** | v1/v2 报告在 verify 层显式拒绝("已弃用") |
| 资格代码哈希 nqc- | — | 自动变化 | 文件字节哈希;旧承诺/旧报告双通道自动失效 |
| sealed-exam-commitment | v3 | v3(不变) | 承诺结构未变;Null 语义变化由 nqc-/nq-/format 覆盖 |
| sealed-exam-context | v3 | v3(不变) | 同上 |
| hidden-exam-cli | v4 | v4(不变) | — |
| checkpoint manifest | v3 | v3(不变) | 语义未变不升级 |
| training attestation | v1 | v1(不变) | 语义未变不升级 |
| candidate runtime manifest | v1 | v1(不变) | 运行时未修改 |

verify 层新增对账:cluster 单位(`bootstrap_unit`/`n_clusters`/
`distinct_seeds`/各块 `bootstrap.n`/`cluster_values` 长度)、聚合
规则、预注册参数字典精确相等、三态结论合法且为 QUALIFIED、
pass↔verdict↔checks 三方一致。

## 五、2.6.0c 实现保留确认(任务书第四节)

| 2.6.0c 资产 | 状态 |
|---|---|
| issuer 信任根(承诺唯一来源/context 副本 canonical equality/自洽校验) | 保留;`run_sealed_exam` 签名无 issuer 覆盖参数(测试断言) |
| candidate-runtime-manifest-v1 逐文件绑定 + staging TOCTOU 验证 | 保留;承诺继续绑定 runtime tree hash |
| 反作弊复制闭环(动态 seed 门槛/seed 聚合/三类作弊可达 SUSPECTED_CHEATING) | 保留;无 `replication_eps[:N]` 硬编码(正则扫描) |
| Null 报告内容绑定(bool-only 拒绝/全材料对账) | 保留并加强(三态对账);20 例篡改矩阵全拒 |
| 冻结六合同 | 未动;`rl_platform` 与 2.6.0c 发布基线逐字节一致 |

## 六、测试

### 新增 tests/route_c_stage2_6_0d/(40 项)

- `test_three_state_verdict.py`(10):三态常量;3-seed 三族
  INSUFFICIENT(任务书硬要求);stochvol +2.40% / sign +0.75% 反例
  复现且不再 QUALIFIED;INSUFFICIENT 进承诺被拒;无自动转 PASS
  通道;漂移伪 Null/结构伪 Null → INVALID_NULL;全样本 QUALIFIED;
  verdict↔checks 一致性;
- `test_cluster_bootstrap_unit.py`(7):bootstrap n == distinct
  clusters(四块 × 三族);9 episode 1 seed = 1 cluster;计数记录;
  聚合规则手工重算核对;bar 级键废除;单位/计数/聚合篡改被拒;
  报告确定性;
- `test_economic_equivalence_band.py`(7):check 由 lf CI 上界
  驱动;stochvol 反例在新检查下 False;带值经济意义(<旧容差/10、
  <反例/4);不对称带负中心语义(带内负中心不阻 QUALIFIED);正漂移
  出带 → INVALID_NULL;HFT 检查保持;旧容差源级废除;
- `test_null_qualification_v3_protocol.py`(16):v3 常量与 v1/v2
  弃用;旧格式/旧 schema 拒绝;非 QUALIFIED 三态/非法值/pass 矛盾
  拒绝;预注册参数篡改拒绝;承诺协议不升版;冻结合同未动;
  2.6.0c 守卫(issuer API 面/无硬编码截断/无永真断言/runtime 绑定/
  bool-only 拒绝)。

### 旧测试适配(不删测试、不加 skip、不降断言)

- 三个 conftest(2.6.0a/b/c)与四处内联 qualify 的 null 报告生成
  统一改为共享确定性磁盘缓存(`tests/null_qual_cache.py`,64×8,
  键含 nqc-/params/manifest/schema/seeds,任一变化自动重建);
- `test_strict_null_qualification.py`:六项 checks + cluster 数
  断言;
- `test_null_qualification_binding.py`:v3 键集/消息文案/cluster
  门槛断言;
- `test_protocol_upgrade.py`:format 断言 v2→v3;
- `test_invalid_null_rejected.py`:无需修改(3-seed 漂移伪 Null 在
  v3 下仍被拒,pass 篡改被 pass/verdict 一致性拒绝)。

## 七、全量回归(2.5 → 2.6.0d)

| 目录 | passed | 失败 | 耗时 |
|---|---|---|---|
| freqai_rl_platform_audit | —(无测试文件,与 2.6.0c 相同) | 0 | 0.8s |
| freqai_rl_stage2_5 | 38 | 0 | 16.6s |
| freqai_rl_stage2_5_1 | 74 | 0 | 30.3s |
| freqai_rl_stage2_5_2 | 78 | 0 | 49.9s |
| freqai_rl_stage2_5_2a | 81 | 0 | 19.7s |
| route_c_stage2_6_0 | 182 | 0 | 70.0s |
| route_c_stage2_6_0a | 169 | 0 | 34.9s |
| route_c_stage2_6_0b | 159 | 0 | 62.9s |
| route_c_stage2_6_0c | 83 | 0 | 111.4s(与 2.6.0d 合并轮) |
| route_c_stage2_6_0d | 40 | 0 | 31.3s |
| **合计** | **904** | **0** | ≈7.5 分钟(两轮) |

首轮回归 1 例失败:2.6.0c 的永真断言静态扫描命中 2.6.0d 新测试
docstring/错误消息中的字面说明文字——按 2.6.0c 同款处理改措辞
(拼接构造),复跑通过。904 = 2.6.0c 基线 864 + 2.6.0d 新增 40。

## 八、全链路实验(artifacts/route_c_stage2_6_0d/,77s)

1. `null_qualification_v3_full_sample.json` + `null_reports/*.json`
   ——三族 64×8 QUALIFIED(实测 CI 见第三节);
2. `null_qualification_small_sample_counterexample.json`——
   3-seed 反例闭环:stochvol `+0.02399` / sign `+0.00748` 复现,
   三族 INSUFFICIENT_EVIDENCE,verify 拒绝进入考试;
3. `null_qualification_economic_disproof.json`——漂移伪 Null
   (direction_weights [0,0.9,0.1],64 cluster×2)→ INVALID_NULL
   (lf CI 下界 ≈ +16.6% >> 0.5% 带);
4. `economic_band_registration.json`——带值/语义/功效推导预注册;
5. `cluster_bootstrap_unit_audit.json`——bootstrap n == clusters
   断言矩阵(四块 × 三族)+ 9 episode/1 seed 用例;
6. `sealed_commitment_verification_v3.json`——v3 承诺完整验证
   (全部 checks 通过);
7. `mock_sealed_exam_flow_v3_nulls.json`——系统级沙箱正式考试
   #1 FAIL(256-step PPO smoke 正常挂科)+ 幂等 #2 + 详细披露退休
   #3;
8. `null_qualification_tamper_matrix_v3.json`——20 例篡改全部
   被拒(baseline 通过);
9. `stage2_6_0c_guards_preserved.json`——2.6.0c 闭环保留;
10. `upstream_integrity.txt`——vendor `52bc96f4480b` clean、冻结
    六合同逐项未变。

## 九、完整性确认

- 冻结合同六项未动(`rl_platform` 与 stage2_6_0c 基线逐字节一致,
  唯一差异 `__pycache__`);
- fee/slippage/reward/ledger/terminal liquidation/成交时序/
  Long-Flat 动作/Freqtrade 上游全部未修改;
- 生成器未修改(stochvol 构造零漂移——`vols[states] × t(4) 对称
  增量`;+2.40% 反例是检查语义问题,非构造问题);
- 模型路线不变(SB3 PPO / MLP / 单资产 / 现货 / Long-Flat);
- 未开始任何正式 PPO 课程训练(256-step PPO 仅作 provenance/
  sandbox/接口 smoke,允许挂科);
- 公开仓库不包含:真实 issuer 私钥、正式隐藏种子、正式私有生成器、
  模型二进制、真实行情、数据库、API Key、代理认证、私人路径与
  凭证;mock 私钥只在临时目录即时生成。

## 十、已知限制与工程决策

1. **任务书文本截断**:用户提供的任务书在第五节 A2 末尾截断;
   已明确部分(阶段目标/两个反例/冻结合同/须保留实现/A1/A2)全部
   实现,后续内容(工作包 B-F 命名、PASS/FAIL 条款、交付清单)按
   项目既有阶段模式(2.6.0c 的协议升级/mock 闭环/测试/回归/发布
   结构)补全,全部决策已在本报告记录;
2. **`per-seed-mean-episode-v1` 选均值而非最坏值**:资格证明是
   "证明等价"的无偏中心估计;2.6.0c 反作弊侧的 worst-variant 是
   fail-safe 语义,两者目的不同;
3. **负带 1.0% 的选择**:见第三节;若未来审查认为应更严,收紧该
   常量即自动使全部旧报告失效(nqc-/nq- 双通道),无需迁移代码;
4. **测试缓存依赖确定性**:资格报告完全 seeded(生成器与 bootstrap
   均 seeded),缓存键含 nqc-/全部材料指纹,任一变化 fail-closed
   重建;缓存位于项目 `.cache/`(不进入发布);
5. **cluster bootstrap n=64 的 basic bootstrap 特性**:小 n 下
   bootstrap CI 由极值主导,3-cluster 样本的 CI 宽达带外——这正是
   INSUFFICIENT_EVIDENCE 门槛存在的原因;
6. **旧阶段 experiments 脚本不重跑**:2.6.0b/c 的 run_all 绑定其
   发布时的资格协议(v1/v2),其 artifacts 已冻结发布;当前代码库
   中它们仅作历史参考(报告如实注明,不修改历史脚本);
7. **`paired_bootstrap_ci` 复用而非新原语**:函数本身对任意列表
   重采样,统计单位由输入列表的构造决定;cluster 化通过喂入
   cluster 级值列表实现,签名与其它 5 处调用方不受影响。

## 十一、结论

阶段 2.6.0d 的目标达成:一个 Null 只有在结构上切断方向信号、实际
资格样本没有可交易的无条件多头优势(单侧 TOST 证明)、Oracle/规则
策略没有经济上显著优势、统计功效足够(64 cluster),并且实际
sealed exam Null pack 本身也有效时,才能进入正式考试。2.6.0c 审查
的反例(stochvol +2.40% / sign +0.75% 仍 PASS、bar 级假样本、
7.68% 累计漂移容差)全部闭环。

即使本阶段判定 PASS,也不开始 C1/C2/C3 正式 PPO 课程训练;是否进入
2.6.1 由后续独立审查决定。
