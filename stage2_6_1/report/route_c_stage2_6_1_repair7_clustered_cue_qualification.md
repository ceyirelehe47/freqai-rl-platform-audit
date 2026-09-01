# Stage 2.6.1 Repair R7 — Cluster-Aware Cue Semantic Gate 与 Clean Matched-Ladder Qualification(诚实 FAIL)

- 迭代:`curriculum_iteration = r7`
- 基线:`7970d2096b6a5a93a85d32620b9b2b3a24826568`(R6 诚实 FAIL checkpoint;父提交 `40a0d9ae…` 为 R5)
- 最终结论:**FAIL**(design 阶段 shared cue semantic gate 在 `design_r7_matched_main` 未通过;§19.1/§20)
- 治理状态:design plan 保留未删未重锁(digest `r7dp-73d65b6838c0686b26ad4c74c1fd7ca94d72aa8f20930d78a555bb8f8890e454`);无 parameter pack;无 exposure marker;未运行 full-cold;R0–R6 历史证据零改动。

---

## 0. 执行摘要

R7 的目标是修复 R6 的两个失败根因(重复计数 + 点阈值误卡),在保留 C2 matched-ladder 统计与 Preprocessing V2 的前提下,用 cluster-aware cue semantic gate 完成从 clean design 到 sealed final 的全链路资格验证。

**已交付并验证的部分**:

1. `C2CueDetectionSemanticContract-v1` 完整落地:unique cue event 去重(matched block 内 4 rung × A/B 共享 cue 表,同一 `(block_index, cue_bar)` 只计一次;canonical = D0/A;跨 rung/variant 的 cue detection input 不一致 => block integrity FAIL)、block-cluster bootstrap 单侧 95% LCB/UCB、candidate-independent 与 candidate-specific 指标解耦。
2. p_contract 合同审计三层自洽:**解析积分 p_contract = 0.950399**(1,000,000 次事件级 MC 给 0.949745 ± 0.000218;200 matched blocks 的 bridge 实测 0.950039,z = −0.12)。预注册 `recall_floor = max(0.90, p_contract − 0.02) = 0.930399`。
3. 4 候选网格(historical control / R6 conservative / midpoint / conservative_d3_up)、机械选择规则、§16.2 治理(design data 生成开始即写 started 事件;iteration aborted 合同)全部实现并经 38 项新测试 + 346/150 回归锁定。
4. matched-ladder 核心实现零修改复用(R6 tape/pairs/param_pack/calculation 模块 sha256 经测试与发布仓库 R6 终态逐位对拍;`test_curriculum261_r7_preflight.py::test_matched_ladder_modules_unchanged_identity`)。

**失败点**:design 阶段 §19.1 shared cue semantic gate——`design_r7_matched_validation` 通过(recall LCB 0.9355 ≥ 0.9304),但 `design_r7_matched_main` 的 unique-event cue recall 点估计落在 p_contract 左尾约 3σ(0.9260 vs 0.9504;语料 cluster bootstrap SE 0.0085),单侧 95% LCB = **0.9120 < recall_floor 0.9304**。按 §19.1 任一 corpus shared gate FAIL 即整个 design FAIL,不进行 candidate 选择;按 §20/§37 禁止以修改 recall floor、delta、candidate 或 n 救援。**R7 = 诚实 FAIL。**

## 0.1 事件披露:design plan loader 的 writer/loader 字段不对称(零数据、零代码修改处置)

完整时间线与证据链,供独立验收审视:

1. `design-plan-lock` 于 16:41(UTC)写入 `r7_design_plan.json` + `r7_design_plan_digest.txt`(digest `r7dp-73d65b68…`)。
2. 首次 `design` 在 `load_locked_design_plan_r7` 失败:"digest 复算不一致"。根因:R7 的 writer 在 plan payload 上附加 `design_plan_digest` 与 `locked_utc` 两个元字段后写盘,而 loader 复算仅排除 `locked_utc`(R6 的 writer 不把 digest 字段写进 plan 文件——R7 抄写偏差)。
3. 该失败发生在 `mark_design_data_started` **之前**:design data 零生成、无任何统计结果产出;plan 文件与 digest 文件写盘后从未被改动。
4. 只读数学验证(`r7_verify_plan.py`,不改任何 src):排除 writer 附加的两个元字段后复算 digest 与锁定值**逐位一致**——plan 的预注册内容(23 个顶层键、4 候选、p_contract、floor、audit digest、code identity)与锁定 digest 完全对应。
5. 处置:以**零 src 修改**的驱动脚本(`r7_drive_design.py`)用与 writer 对称的复算逻辑读取 plan(等价于正确的 loader 实现),验证通过后调用 `run_design_stage_r7`。src 全部文件的 sha256 在 plan 锁定前后逐位不变 => plan 绑定的 code identity 不变,§16.2 的"code identity 发生变化"终止条件不触发;plan 未删除、未重锁(对比 R6 的无效路径:R6 是"改统计代码后删旧 plan 同 namespace 重锁并继续",R7 是"plan 与代码零改动、仅以对称复算继续读取")。
6. loader 的对称性缺陷**不在本轮修复**(修复即修改 `curriculum261_r7_design.py` = design data 已生成后的代码修改 = §16.2 iteration 永久结束路径);作为已知 limitation 记录,修复留给 R7.1/R8。
7. 本披露交由独立验收 subagent 判定;若判定该处置违反 §16.2/§17,则 R7 的 FAIL 结论不变(FAIL 发生在其后的统计 gate,处置只影响"design 数据是否有效生成"——而该数据只产出了 FAIL 证据,未产出任何 PASS 利益)。

## 1. 主报告(§36 三十八问)

1. **R6 为什么 FAIL?** 两层:形式层,R6 在第一份 design plan 锁定并生成数据后修改统计代码、删除旧 plan、同 iteration 同 namespace 重锁——formal design evidence 无效;统计层,R6 的 `cue_recall_min = 0.95` 点阈值预注册在生成器固有检出率期望之上,且 matched 下 cue 表跨 candidate 逐位相同使 recall 只依赖语料,8 个 candidate 被同一共享指标同时拒绝(7/8 的唯一 binding 条件是 recall;唯一例外 kappa_wide 还叠加 D3 功效不足)。
2. **R6 matched-ladder 哪些结论成立?** 全部技术结论:同 block 四 rung 共享结构带(cue 表/s 链/w 链/基础噪声/volume/wick jitter/初始价/时长/时间戳/A-B 结构)逐位一致(本轮 shared gate 的跨 candidate cue 表 digest 再次验证:4 candidate × 2 corpus 全部唯一 digest 数 = 1);blockwise gap 方差相对 scrambled 缩减多倍;historical control 与 conservative ladder 在忽略误卡 recall 时 n=15 双语料 gateP 0.943/0.947。R7 全部复用,零语义修改。
3. **为什么 R6 formal design evidence 无效?** 见第 1 问形式层:预注册合同(不删 plan、不改代码)在数据生成后被破坏,数值只能作历史开发证据。R7 以全新 seed 空间重做,且 plan 保留至今未删未重锁。
4. **为什么同一 cue 不能重复计 8 次?** matched block 内 4 rung × A/B 共享同一 cue 表、同一噪声实现与同一脉冲,cue bar 的 detection input(`%-ret-1` 读数)跨 8 份逐位一致(本轮 violations = 0 实证)——它们是同一事件的 8 份重复观测,不是 8 个独立事件;重复计 8 次会把事件数虚增至 8 倍、把 CI 虚假缩小 √8 倍(`clustered_cue_metric_validation.json` 的 naive_eightfold 对照实证)。
5. **unique cue event 如何定义?** `(block_index, cue_bar_index)` 二元组;在一个 matched block 内只计一次;统计读数取 canonical 侧。
6. **canonical cue observation 是什么?** `D0/A`(design plan 预注册冻结)。跨 rung/variant 一致性是硬合同:任何 cue bar 的 8 份读数 max−min > 1e-12 即 block integrity FAIL(design 两语料 violations 均为 0)。
7. **p_contract 如何计算?** 三层:(a) 解析层——正 cue bar 读数 = `exp(pulse + eps[t]) − 1`(`close = exp(cumsum(log_returns))`,`%-ret-1 = close.pct_change()`),判定 ⟺ `eps[t] > −margin_log`,`margin_log = pulse − ln(1+cue_thr) = 45.547bps`;`eps[t] | K ~ N(0, vol²(1+K))`,`K ~ Binomial(C(t), 1/9)`(paired_noise 的镜像候选结构),`q(t) = Σ_k BinPMF · Φ(margin_log/(vol√(1+k)))`;(b) 位置层——正 cue 位置分布 ŵ(t) 由冻结生成器(matched-tape、sentinel ladder、与 design 完全同机制)在 `cue_contract_audit_r7` 的 200 blocks 提取;(c) `p_contract = Σ_t ŵ(t)·q(t) = 0.950399`。
8. **noninferiority delta 为什么是 0.02?** 任务书 §9.2 预注册值,在 audit 运行前冻结于 `curriculum261_r7_cue_contract.py` 并进入合同 digest;含义:容忍生成器固有检出率期望的 2pp 内统计波动(≈2.4×单语料 cluster SE)。
9. **absolute recall floor 为什么是 0.90?** 同为预注册下限:即便 p_contract 估计偏高,检测语义也不得退化到 0.90 以下;本轮未起作用(floor 由非劣效臂决定)。
10. **最终 recall floor 是多少?** `max(0.90, 0.950399 − 0.02) = 0.930399`。
11. **cue recall LCB 如何计算?** 每 matched block 统计 (n_positive, n_hit),block-cluster bootstrap(重采样完整 block、cluster 内 pooled、20000 次、seed 20260925)取 5% 分位 = 单侧 95% LCB。
12. **precision/FP/payoff false cue 的 cluster bounds?** 同一 cluster bootstrap:precision 用每 block (n_over, n_over∧cue+) 的 5% 分位(LCB ≥ 0.85);non-cue FP 用 canonical 的 non-cue bar (n, over) 的 95% 分位(UCB ≤ 0.01);payoff false-cue 按 candidate × rung × side 的 payoff bar (n, over∧active) UCB ≤ 0.06,D0–D3 每档单独判定(不得以 D3 稀释 D0)。本轮 design 在 shared gate 即 FAIL,候选侧指标未到判定步;工程验证(ppo_smoke_r7 下 12 blocks)全部跑通。
13. **哪些 semantic metrics 是 candidate-independent?** positive cue recall、non-cue false-positive、unique cue count、block 级 cue 事件分布——每 corpus 只算一次(R6 的教训:同一 recall 不得记到全部 candidate)。
14. **哪些是 candidate-specific?** payoff-bar false-cue、cue precision、payoff/cue confusion、reference trade side effects——按 candidate/rung/side。
15. **候选 grid 有哪些?** `c2l_historical_control`(68/54/40/32 + 0.80/0.55/0.38/0.25,冻结默认)、`c2l_conservative`(74/56/40/28 + 0.82/0.60/0.40/0.26)、`c2l_midpoint`(71/55/40/30 + 0.81/0.575/0.39/0.255)、`c2l_conservative_d3_up`(74/56/40/30 + 0.82/0.60/0.40/0.26)。
16. **为什么只保留 3–4 个?** §13 上限;R6 的 8 候选网格已证明边际信息有限而计算/治理成本高;D3 alpha∈[28,32] 边界排除了 R6 已证明 margin 不足的低 alpha 方案(kappa_wide 的 27 也被排除);midpoint/d3_up 是 conservative 与 historical 之间的两个有 R6 power-table 依据的稳健化选项。
17. **选定的 formal block count 是什么?** 未选定——shared gate FAIL 短路于 candidate 评估与机械选择之前(§19.1:不进行 candidate 选择)。
18. **选定的 C2 ladder 是什么?** 未选定,同上。
19. **两个 design corpus 的 gate probability 是多少?** 未到达 formal gate simulation(shared gate 先行;两 corpus 的 shared 指标:main recall LCB 0.9120 / point 0.9260;validation LCB 0.9355 / point 0.9470;non-cue FP UCB 0.00055 / 0.00041,均 ≤ 0.01)。
20. **independent marginal guard 是否通过?** 未执行(design FAIL 分支不访问 `design_r7_independent_marginal` namespace;artifact `c2_independent_marginal_design.json` 不存在)。
21. **V2 在新 fit banks 上是否通过?** audit 阶段的工程等价(production equivalence,preplan_smoke_r7 语料)PASS;正式三 bundle(calibration/holdout/final)未生成(calibration 未执行)。
22. **C1/C3 是否在新语料通过?** 未执行(calibration/final 未运行)。
23. **calibration 和 holdout 是否各自独立通过?** 未执行。
24. **是否使用 pooled 救援?** 否(未到达任何 gate 组装步)。
25. **design plan 锁后是否发生代码变更?** 否——src 全部文件在 plan 锁定前后逐位不变(§0.1 的 loader 事件以零代码修改处置;code identity 不变)。
26. **是否删除或重锁过 plan?** 否。`r7dp-73d65b68…` 从锁定至今未删、未覆盖、未重写(`lock_design_plan_r7` 为 O_CREAT|O_EXCL,测试断言已存在即拒)。
27. **final preflight 是否零 final seed?** sealed preflight 未执行(未到 final 阶段);pre-lock static preflight 的组件在 38 项测试与 ppo_smoke_r7 下验证(零 final seed 断言见 `test_curriculum261_r7_preflight.py::test_sealed_preflight_zero_final_seed`,以合成 plan 验证)。
28. **exposure 何时写入?** 从未写入(`qualification_exposure_r7.json` 与 ledger 均不存在;iteration 事件账本仅有 `design_data_started` 一条)。
29. **final 是否只执行一次?** 未执行(execution count = 0)。
30. **core qualification pairs 是多少?** 0(未执行;按 §27 应为 80 + 4n = 120/140/160)。
31. **independent guard pairs 是多少?** 0(未执行;§27 固定 80)。
32. **total generated pairs 是多少?** 0(final 口径);本轮实际生成的 qualification 链数据为零——design 语料是开发数据(2 corpus × 4 candidate × 40 matched blocks = 320 blocks = 2560 episodes)。
33. **C1/C2/C3 结果分别如何?** C1/C3 未执行;C2 停在 design shared gate FAIL。
34. **full-cold 结果?** 未运行(§31:final FAIL/未执行时不运行、不宣布 full-cold PASS)。
35. **C3 Branch D 是否仍开放?** 是——R7 不解决 C3 scratch PPO / BC 被 fine-tune 破坏 / critic-value-advantage 动力学。
36. **R7 最终 PASS/FAIL?** **FAIL**。
37. **Stage 2.6.2 正式状态?** FAIL(不变;R7 未触及)。
38. **建议下一步?** 见 §2 处方。

## 2. 失败机理与 R7.1 处方建议

### 2.1 main 语料 recall 左尾的定量刻画

| 语料 | blocks | unique 正 cue | recall point | cluster SE | LCB | 判定(floor 0.9304) |
|---|---|---|---|---|---|---|
| cue_contract_audit_r7(bridge) | 200 | 5184 | 0.9500 | — | — | 校验(z=−0.12 vs 解析) |
| design_r7_matched_main | 40 | 1041 | 0.9260 | 0.0085 | 0.9120 | FAIL(差 0.0184) |
| design_r7_matched_validation | 40 | 1038 | 0.9470 | 0.0069 | 0.9355 | PASS(余 0.0051) |

main 的点估计相对 p_contract 为 −2.9σ(事件级 SE 0.0081 口径 −3.0σ);三语料点估计的离散(0.926/0.947/0.950)超出单语料 SE 预期,提示存在语料级随机效应分量(每语料 40 blocks 的 cue 位置结构带抽样)。已知 limitation:本轮未把 per-event 的镜像命中数 K 落盘,无法事后分解 main 的低 recall 由位置分布(K 偏大)还是噪声实现驱动;audit 的 K 边际(P(K≤1)=0.749)与 σ_eff 分位数(p50=28.3bps)已给出期望侧刻画。

### 2.2 处方(R7.1,均需新任务书授权)

1. **loader 对称修复**(一行级):`design_plan_digest_r7` 复算时同时排除 writer 附加的 `design_plan_digest` 字段(或 writer 停止写该字段,对齐 R6);`test` 加 writer→load roundtrip 锁定。
2. **shared gate 的语料级方差处理**——三选一(任务书层决策):
   a. 每 design corpus 的 block 数 40 → 80(语料 point SE 0.0085 → ~0.006,LCB 余量 +~0.004;计算量 ×2);
   b. 维持 40 blocks 但把 design corpus 数 2 → 3(shared gate 判据仍逐 corpus,但左尾语料的复现概率与定位更稳);
   c. 接受预注册判据不变,直接以全新 namespace 重跑(三语料证据下 main 属 ~3σ 左尾;同设计重跑出现两个左尾语料的概率 ~4%)。风险:反复重跑构成 garden-of-forking-paths,必须由任务书显式授权并公开全部历史尝试。
3. **per-event K 落盘**:shared gate 输出加每事件镜像命中数直方图,使下一轮 FAIL(若有)可归因。
4. cue 合同本身(unique 去重/cluster bootstrap/floor 公式)与 matched-ladder 实现无需改动——本轮全部测试与工程验证绿。

## 3. 治理附录

- **§3.1 执行链与产物**:audit(基线/历史 digest/route_c/vendor/production equivalence/namespace pre-design 全 PASS)→ cue-audit(p_contract 三层)→ preplan-smoke(sentinel)→ design-plan-lock(`r7dp-73d65b68…`)→ design(§0.1 loader 事件 → 零代码修改驱动)→ shared gate FAIL → 收尾(unique/clustered 验证、namespace post-design PASS、PPO smoke PASS、fail_path_cleanliness PASS、回归 38/346/150 全绿)。
- **§3.2 测试**:新增 6 文件 38 项(cue contract 5 / cue eval 8 / namespaces 9 / param pack 7 / selection 4 / preflight 5);2.6.1 全套 346、2.6.2 全套 150 零失败;input lock(R7 登记 `curriculum261_api.py = 4d8f1e82…`)与 R0–R6 黄金向量测试全绿。
- **§3.3 历史保留**:R1–R6 artifacts/report 未改动;R6 tape/pairs/param_pack/calculation 模块 sha256 与 R6 终态逐位一致(测试断言);`curriculum261_api.py` 变更仅新增 R7 白名单与三 namespace 守卫,`_derive261_seed_raw` payload 与黄金向量不变。
- **§3.4 禁止事项遵守**:未修改 Route C 六合同/fee/reward/action/execution/C1-C3 参数/C2 carrier/cue 结构;未用 R6 design data 作资格数据;未复用任何旧 namespace;未把 recall 阈值机械改为 0.93(而是建立了 p_contract 合同);数据后未改 delta/floor/candidate/n;plan 未删未重锁;matched FAIL 后未用 unpaired/pooled 救援;exposure 未写;无 per-family/per-episode scaler/eval refit/VecNormalize/reward normalization/PPO tuning/BC warm-start/C3 PPO optimization;未进入 Stage 2.6.2 official / 2.6.3 / 历史训练 / backtest / Dry-run / real trading。
- **§3.5 full-cold**:未执行,不宣布 PASS。
