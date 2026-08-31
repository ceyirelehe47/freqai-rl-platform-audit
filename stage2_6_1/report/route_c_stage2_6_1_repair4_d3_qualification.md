# 阶段 2.6.1 Repair R4:正式预处理合同 V2、D3 统计功效与重新 Qualification

- **判定:FAIL(诚实 FAIL)**
- 失败层级:final qualification 的 curriculum 排序条件——**C2(frozen,本轮无修改授权)在一次性 qualification_r4 语料上 D2 < D3 排序翻转**;本轮授权修复的 C1-D3 / C3-D3 在同一语料上**全部条件通过**
- preprocessing V2 合同:**全部资格证据 PASS**(数值等价、无界 outer observation space、三层 identity、fit manifest provenance、bundle verification、staged/mixed、reference 全 240 episode 逐 bar 等价、conditioning、supervised、PPO smoke)
- calibration 双 robustness gate:**PASS**(preprocessing gate + curriculum gate + supervised 全过)
- final qualification:**执行并 FAIL**(34/36;语料已暴露,证据完整保留)
- Baseline:`d105405e5ddd989d6faf0601e912907746ad8980`(Stage 2.6.1 Repair R3 诚实 FAIL checkpoint)
- Vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean,未动)
- 迭代身份:`r4`;产物写入 `stage2_6_1/artifacts/repair4/`
- 两次 governance waiver 登记(gate 口径对齐 + final 崩溃恢复,见 §16)

---

## 1. R3 为什么 FAIL?

R3 的 curriculum robustness gate FAIL:C1-D3 余量(pair-cluster 口径 0.00265 < κ×SE 0.00694)、C3 holdout D3 翻负(−0.00165)。根因是 **C1/C3 的 D3 设计余量与 10-pair 抽样不确定性同量级**——R2 的 PASS 建立在 episode 假独立 SE 低估上,诚实口径下余量并不稳健。

## 2. R3 preprocessing 哪些部分成立?

数值实现全部成立并经 R4 复验:vendor `IFreqaiModel.define_data_pipeline` 直接复用(VarianceThreshold(0)+MinMaxScaler(-1,1)),train/eval/reload/shuffled 逐位等价,统一 offline fit/freeze,8/8 特征存活,position 不缩放,reference 逐 bar 等价,conditioning/supervised/PPO smoke PASS。

## 3. 为什么 R3 正式合同仍未闭合?

独立审查确认四项:production scaler 不 clip 但正式空间仍声明 Box(-10,10);state hash 只绑 scaler 参数不绑 fit 来源;reference margin 用了 episode 事后切换 required baseline 的 hindsight 口径;difficulty metric 在 evaluator(corpus 级常数)与 gate(episode 级 hindsight max)两处定义不一致。

## 4. V2 observation space 如何定义?

外层 preprocessing-aware Gymnasium wrapper(`RouteCPreprocessingEnvV2`,继承 `gym.Wrapper`):

```
low  = [-inf × 8, 0]
high = [+inf × 8, 1]
dtype = float32
```

reset/step 透传并校验(dim/float32/finite/position∈{0,1}),**值逐位不变**。PPO、SB3 `check_env`、PPO model 构建看到的都是该 outer space(实测 `model.observation_space.low[:8]` 全 -inf)。内层 `AlignedLongFlatEnv` 冻结声明不变(Route C 六项合同零修改)。

## 5. 为什么不能继续用 Box(-10,10)?

production MinMaxScaler 不 clip,eval 越界值线性外推,R3 实测越界率 0.043% 全在 ±10 内是**经验事实**而非合同保证;把无限外推空间声明为有限界是在文档里撒谎。V2 用真无界声明消除该矛盾(任务书 §8 明确禁止"不能仅在文档里写无界,运行时仍暴露 Box(-10,10)")。

## 6. 是否存在任何 clip?

**没有。** 全链路验证:wrapper 输出与 bare inner 逐位相等(`wrapper_pass_through_bitwise=True`);对抗探针把 raw 特征推到 fit range 外 6 个 range,transformed 值 ±13.0 被 outer space 接受(`observation_space.contains == True`)且不截断;calibration/holdout/final 全 corpus containment PASS。SB3 对无界 Box 完全兼容(check_env + PPO 学习 + save/load 决定性全过),无 blocker。

## 7. fit manifest 如何进入 bundle identity?

三层 identity(§9):
- **A. Parameter State Hash**(`r4ps-`):只绑 transform 参数(retained mask / data min/max / scale/min / 列 / dtype / pipeline 版本;刻意不含 `n_samples_seen_`);
- **B. Fit Manifest Multiset Hash**(`r4fm-`):每 fit bank episode 一条 entry(namespace/family/rung/pair/side/episode hash/feature-matrix hash/generator+parameter-pack identity),排序后逐 entry 哈希再总哈希——行序不敏感、multiset 内容敏感;
- **C. Preprocessor Bundle Hash**(`r4pb-`):A + B + fit protocol digest + production pipeline identity + runtime config identity + feature construction identity 的联合绑定。

final 的三层哈希:`r4ps-22a27dfa…` / `r4fm-4203ace3…` / `r4pb-406dfcec…`(全 64 位见 artifacts)。

## 8. staged/mixed 为何得到同 bundle?

fit 对 manifest 行序不敏感(MinMax/VT 为置换不变统计):shuffled rows 重拟合 → 同 param hash;manifest(episode multiset)不变 → 同 multiset hash → 同 bundle(校准与 final 语料上各重验一次)。对偶测试:重复一个 episode(min/max 不变 → 同 param hash、multiset 改变)→ **不同 bundle**。全部进 `staged_mixed_fit_equivalence.json` / `serialization_reproducibility.json`。

## 9. difficulty metric 如何统一?

`difficulty_pair[p] = reference_pair[p] − always_flat_pair[p]`(唯一口径;Always Flat 恒 0 但保留显式 baseline 语义)。rung mean / pair-cluster SE / D3 正性 / 相邻 gap / bootstrap / final 排序**全部从同一张 pair 证据表派生**(`r4pt-` schema identity 进 plan),evaluator 与 gate 数字由构造同源(测试锁定)。

## 10. 为什么禁止 episode-level hindsight baseline switch?

逐 episode 选"表现最好的 baseline"再统计,等价于给 margin 注入每集最优对手:R3 的 C3 margin(main −0.0097)正是该伪影——逐基线口径下同一数据 margin 为正(测试构造了符号翻转场景证明两种口径可给出相反判定)。hindsight 选择与"reference 是否稳定胜过每个固定基线"是不同命题,后者才是课程资格问题。

## 11. fixed baselines 如何逐个比较?

对每个 required baseline(C1: always_flat/always_long;C2: +c2_local_only;C3: +c3_cost_ignorant)分别计算 `margin[p,b] = reference_pair[p] − b_pair[p]` 的 mean / pair-cluster SE / κ 检验 / bootstrap CI,全部 rung 逐 corpus 判定。R4 校准与 final 的全部逐基线 margin 均 PASS(C3-D3 对 cost_ignorant 的 margin 在 final 上 mean +0.0171 ≥ κ×SE)。

## 12. pair-cluster 统计如何实现?

一个 A/B pair = 一个 cluster:pair 表行键 =(rung, pair_index)(跨 rung 同编号 pair 不合并——实现期测试抓到并修复了一个键控 bug),pair 值 = A/B 均值;SE = sd(pair)/√n;相邻 gap 的 SE 用两 rung SE 的二次合成。gate 的量级条件按 R2/R3 预注册口径用双语料 pooled(20 pair/档)判定,严格逐 corpus 口径作为诊断字段保留(见 §16 waiver)。

## 13. bootstrap 如何实现?

percentile bootstrap:按 pair 重采样(不拆散 A/B)、固定 seed 20260901、5000 次(功效模拟 20000 次、seed 20260902);CI 作为辅助证据记录在 pair 表/ladder/margin 中,不替代预注册 κ gate,不事后选择有利口径。

## 14-16. C1/C3-D3 候选与 power analysis 如何选择?

预注册 6+6 候选(design plan 锁定后才生成 episodes;重跑校验网格未变):C1 调 opp_drift/vol,C3 调 alpha/mixture/distractor/cue_rate(全部来自 generator 已支持参数;seg_len 固定合同/结构休眠参数不动)。配对设计:共享 seed schedule/episode 数/评估代码/D2 冻结语料;**噪声流共享结构性不可达**(冻结 generator 的 derive_seed payload 含 rung 参数)——如实登记,以 antithetic A/B + 30 pair + bootstrap 缓解。功效规则(预注册):`mean ≥ 2.5×SE(n=10)` AND `bootstrap P(formal-gate PASS) ≥ 0.80`;选择规则:合格者中 gate-pass probability 最高。

design_r4 语料(30 pairs/rung/candidate)结果:

| C1 candidate | D3 mean | effect(n=10) | gate P | 合格 |
|---|---|---|---|---|
| c1_a_edge_up (opp 24.5) | 0.0295 | 4.58 | **1.000** | ✅ **选定** |
| c1_b_edge_up2 (opp 28) | 0.0421 | 6.64 | 0.993 | ✅ |
| c1_c_vol_down (vol 21) | 0.0157 | 2.49 | 0.852 | ❌ |
| c1_d_edge_vol (24.5/22) | 0.0399 | 6.47 | 0.999 | ✅ |
| c1_e_edge_vol2 (28/21) | 0.0546 | 10.80 | 0.907 | ✅ |
| c1_f_edge_vol3 (31/20) | 0.0769 | 14.72 | 0.056 | ❌(逼近 D2,gap FAIL) |

| C3 candidate | D3 mean | effect | gate P | 合格 |
|---|---|---|---|---|
| c3_a_alpha_up (α 50) | 0.0051 | 1.82 | 0.662 | ❌ |
| c3_b_strong_up (0.22) | 0.0098 | 3.60 | 0.980 | ✅ |
| c3_c_alpha_strong (50/0.20) | 0.0097 | 4.70 | **1.000** | ✅ **选定** |
| c3_d_alpha_strong2 (52/0.24) | 0.0107 | 3.55 | 0.975 | ✅ |
| c3_e_mild_dis_down | 0.0064 | 2.49 | 0.862 | ❌ |
| c3_f_density_up | 0.0078 | 3.11 | 0.935 | ✅ |

结论与机制一致:C1 靠漂移上调(单纯降噪不够),C3 靠 α 与 strong 份额双管齐下(单纯 α 上调不够);过激参数(C1 opp 31)会侵蚀 D2>D3 间隙被规则拒绝。

## 17-18. C1/C3-D3 最终参数

- **C1-D3(R4 pack)**:`opp_drift_bps 24.5, neg_drift_bps 16.0, vol_bps 26.0, seg_len_range [24,24], state_weights [0.36,0.28,0.36], distractor_rate 0.000`(历史 D3 为 opp 21.0;唯一实质量变是机会段漂移 +3.5bps/bar)
- **C3-D3(R4 pack)**:`alpha_bps 50.0, payoff_bars 1, vol_bps 18.0, cue_rate 0.230, mixture [0.20,0.36,0.44], distractor_rate 0.060`(历史为 α 46 / strong 0.14)
- pack digest:`r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99`

## 19. C2 及 D0-D2 是否完全未漂移?

是。pack 只允许 C1/C3 的 D3(键集校验 + pack 构造拒绝其他);C2 全部与 C1/C3 的 D0-D2 逐位等于 family_specs 历史值(冻结参数 identity `r4fp-…` 进 plan 并在 final 复核一致);R2/R3 namespace 黄金 episode 哈希不变(calibration_r3 C1-D3 pair0 与 qualification_r2 C3-D3 pair0 逐位复现,测试锁定);设计期 D2 语料全部 candidate 共享。

## 20-21. 两个 gate 的结果

**preprocessing robustness gate:PASS**——production 数值等价(vendor 对拍逐位)、V2 无界空间合同、全 corpus containment、对抗探针、8/8 存活、position identity、envelope 序列化/重载、manifest 篡改/参数篡改拒绝、staged/mixed 同 bundle、不同 multiset 不同 bundle、no NaN/Inf、reference 等价(72 episode:每 family×rung×3 pair×A/B)、conditioning(raw OHLC 份额 0.505 ≤ 0.60、饱和 0、越界率 ≤0.10)、fit/eval 隔离。

**curriculum robustness gate:PASS**——

| family | 难度梯(calibration / holdout) | D3 pooled vs κ×SE | 判定 |
|---|---|---|---|
| C1 | 0.205/0.194 > 0.111/0.111 > 0.068/0.069 > **0.020/0.029** | 0.0249 ≥ 0.0072 ✅ | PASS |
| C2 | 0.031/0.035 > 0.024/0.017 > 0.012/0.012 > 0.006/0.005 | 0.0055 ≥ 0.0024 ✅ | PASS |
| C3 | 0.047/0.050 > 0.033/0.033 > 0.017/0.023 > **0.006/0.008** | 0.0074 ≥ 0.0025 ✅ | PASS |

C1-D3 从 R3 的 0.0030/0.0023 提升到 0.0203/0.0294;C3-D3 holdout 从 −0.0017 翻正到 +0.0084。C1/C3 在更严的逐 corpus 口径下也全过;C2 的两个边缘 gap 只在预注册 pooled 口径下通过(见 §16)。supervised gate:三族 6/6 W/B gated runs 达标(bacc 0.76-0.86)。

## 22. calibration/holdout 是否一次性执行?

是。candidate pack 锁定后一次性:fit bank(calibration)→ calibration_r4 → fit bank(holdout)→ calibration_holdout_r4 → 双 gate。两次实现层修正(见 §16)均发生在 plan lock 前、不改任何参数/κ/seed/语料规模,corpus 由确定性生成保持逐位相同。

## 23. final plan 是否在两 gate PASS 后锁定?

是。`build_plan_r4` 拒绝任一 gate 非 PASS;plan 绑定 §26 全部 22 类身份(R4 iteration、pack digest 与正式 D3 参数、冻结参数 identity、V2 contract digest、vendor pipeline/runtime config/feature construction identity、observation-space identity、fit protocol、fit manifest derivation、pair table schema identity、difficulty/margin identity、pair-cluster+bootstrap 方法、κ=1.5、qualification seed schedule、final fit bank schedule、metrics/thresholds、code identity(21 模块+RouteCStrategy 双哈希)、baseline SHA d105405、vendor SHA、Route C 六项、R2 plan digest qp-8f64a1b5…、262 诊断 digest dp-ee6f8dc1…、R3 baseline 1b47db4)。锁定 digest:`qp4-72b3a7e835f0a40b05198a8d0008ef1d7dac66f0b2eef3751cecdcc8396c10de`(首锁 qp4-a9024ae4… 因 §16 事件 2 的路径修复重锁,seed 派生不含 plan digest,corpus 身份不变)。

## 24-26. final fit manifest / bundle hash

- final fit bank:`preprocess_fit_qualification_r4`(plan lock 后首次访问,3×4×4 pairs×A/B = 96 episodes);
- fit manifest multiset hash:`r4fm-4203ace3938740bca1d356ec26bb0cf5ab1b291236e9dcabe2808c0f59bf303b`;
- preprocessor bundle hash:`r4pb-406dfcecf6f0dbe1d2a5fbc8c29d4e583f91d3fd88dd6d36827b9503db8beee8`(parameter state `r4ps-22a27dfaf0035f8d1f72e104fa26b850ce0b7b23cdf82f21eaf112f53bed752a`)。

## 27-29. final 120 pairs 结果

qualification_r4 一次性执行(3×4×10×A/B = 120 pairs,exposure marker 完整):

| family | D0 | D1 | D2 | D3 | D3 vs κ×SE | 排序 | 判定 |
|---|---|---|---|---|---|---|---|
| C1 | 0.2119 | 0.0987 | 0.0763 | **0.0244** | 0.0244 ≥ 0.0104 ✅ | ✅ | **PASS** |
| C2 | 0.0293 | 0.0199 | **0.0070** | 0.0085 | 0.0085 ≥ 0.0034 ✅ | ❌ D2<D3 | **FAIL** |
| C3 | 0.0512 | 0.0356 | 0.0198 | **0.0084** | 0.0084 ≥ 0.0037 ✅ | ✅ | **PASS** |

34/36 检查通过;唯二失败(`difficulty_ordering_all` / `gaps_ge_kappa_se_all`)均来自 **C2 的 D2-D3 翻转(−0.00145)**。C2 参数本轮冻结无修改授权:校准双语料中其 D2-D3 间距 ~0.0055 ≈ 1.7×SE,本就功效不足;fresh 10-pair 抽样 D2 偏低(~2σ)+ D3 偏高(~1.3σ)导致翻转。这正是 R4 用功效设计为 C1/C3 修复、但 C2 无权触碰的同族问题在 final 语料上的显形。reference 逐 bar 等价覆盖全部 240 episodes(全策略对)PASS;pair integrity 1.0;复现(含 pack-D3 override)/fresh seed/latent/因果全过;conditioning/supervised 重跑 PASS;无界空间/对抗探针/staged-mixed/envelope 重载全过。

## 30. C3 PPO Branch D 是否仍开放?

**是。** R4 未触碰 PPO optimization;即使 R4 将来 PASS 也不能声称 C3 PPO 已解决(BC 可学但 fine-tune 摧毁的 critic/advantage/update dynamics 问题原样保留)。

## 31. Stage 2.6.1 Repair R4 最终判定

**FAIL(诚实 FAIL)。** 授权范围(C1-D3/C3-D3 课程资格 + preprocessing V2 正式合同 + 统计统一 + 功效设计)全部达成并在 final 语料上通过;FAIL 来自无授权修改的冻结 family C2 的难度排序在一次性 fresh 语料上翻转。按 §29,qualification_r4 语料已暴露,不得修代码后复用;下一轮必须 R4.1/R5 + 全新 seed space(并需要新的设计授权处理 C2 的 D2-D3 功效,或调整 final 排序检查的统计定义)。

## 32. Stage 2.6.2 正式状态

**FAIL(未变)。** R4 不重跑 2.6.2;C3 Branch D 开放;不得自动进入 2.6.2 official。

## 16(补). 两次 governance waiver(全文见 governance_waiver.json)

1. **gate 口径对齐(calibration 阶段内、plan lock 前)**:R4 初版 gate 把相邻 gap 与 D3≥κ×SE 实现为逐 corpus(10-pair)独立判定,比 R2/R3 预注册规则(pooled 20-pair)更严;首跑 C2 两个边缘 gap FAIL(证据存档 `curriculum_robustness_gate_strict_variant_diagnostic.json` 等)。修正对齐预注册口径;**授权范围 C1/C3 在两种口径下判定相同(均 PASS)**;严格口径结果作为诊断字段永久保留;未改任何参数/κ/seed。
2. **final 崩溃恢复(corpus 生成前)**:首次 qualify 在第 1 步身份复核因 vendor 路径解析 bug 崩溃(自 R3 复制的潜伏 bug,R3 final 从未执行故未暴露)。崩溃点在**任何 qualification seed 派生之前**——corpus 从未生成、零观察零泄漏(qualification seed 不含 plan digest,corpus 身份与重锁无关)。处理:证据存档(`*_crashed_run` / `qualification_crash_traceback.log`)、清除 stale marker、一行路径修复、重锁 plan、重跑。重跑的 FAIL 为最终判定。

## 回归

- targeted(tests/route_c_stage2_6_1,含 43 项新 R4 测试):**196 passed / 0 failed**;
- affected(按规则命中全部 route_c 目录,含 Stage 2.6.2 输入锁):exit 0;
- Stage 2.6.2 目录:**150 passed / 0 failed**(输入锁登记 R4 变更后全绿);
- **full-cold:未执行**(§36 前置条件"final qualification PASS"不满足;FAIL 轮不宣布 full-cold PASS)。

## Route C / generator / vendor 未修改

六项冻结合同、fee/slippage/tick/reward/ledger/action/execution、RouteCStrategy.feature_engineering_standard、C1/C2/C3 generator 算法结构与历史参数、reference threshold 全部未动;rl_platform 冻结核心零改动(无界空间由课程层外层 wrapper 声明);vendor pin clean;历史 artifacts 零覆盖(repair1/2/3 与 2.6.2 目录只读)。

## 已知局限

1. C2 的 D2-D3 设计间距 ~1.7×SE(n=10 下排序翻转概率 ~4-5%),修复需要 C2 参数的设计授权(本轮明令冻结);
2. design 阶段无法跨 candidate 共享噪声流(冻结 generator 的 seed 派生含参数),以配对 seed schedule + antithetic + 30-pair 缓解并预注册登记;
3. qualification 的排序检查是点估计判定(无 SE 容差)——这是 R2 以来一致的预注册语义,R4 未擅自放宽;
4. final corpus 已暴露,任何后续迭代需全新 seed space。

## 下一步建议(不自行执行)

- **R5(或 R4.1)需要的新授权**:C2 的 D2-D3 功效重校准(与本次 C1/C3 同方法:design stage + power analysis + 版本化 pack),以及是否将 final 排序检查改为"逐 corpus 排序 + gap ≥ κ×SE"的合成口径(预注册,不得看本轮结果后追认);
- preprocessing V2 合同的全部资格证据与 C1/C3-D3 课程资格证据与本轮 FAIL 无关,可整体复用于下一轮(换 corpus 即可);
- C3 PPO Optimization Repair(Branch D)仍需单独决策。
