# Stage 2.6.2 — 小规模 PPO 教学实验报告(FAIL,如实报告)

- Stage:`stage2_6_2`,iteration `s262_r0`
- Git baseline:`1927faa647d34e4f45ed9c46d100f500081560b8`
- R2 curriculum 输入:plan digest `qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99`(verdict PASS,exposure completed)
- Vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 最终判定:**FAIL** — 三族 per-family probe 全部无法学习(§13),按 §10/§13 停止,core experiment 与 sealed final evaluation 未执行。

---

## 0. 结论摘要

在冻结的 PPO + MLP + Long/Flat + causal-unscaled 生产观察路线上,PPO 无法从 C1/C2/C3 curriculum 中学到任何预期能力:

| family | probe 预算 | 终态策略 | core capture | 行为 gap |
|---|---|---|---|---|
| C1 Opportunity | 45,920 steps | Always Long(短暂)→ Always Flat | **-0.026** | selectivity **0.0** |
| C2 Context | 68,880 steps | Always Flat | **0.0** | gating **0.0** |
| C3 Cost | 68,880 steps | Always Flat(曾有短暂正收益探索期) | **-8.36** | cost-selectivity **0.0** |

延长诊断证明这不是预算问题:C1-only 用 **4 倍 probe 预算**(640 episodes = 183,680 steps = core 全预算)训练,策略在 ep60 后即死锁于 Always Flat(long=0.00、changes=0、reward=0.0000)直至 ep639。

学习动力学本身是健康的(换手 128→0 的摩擦规避真实发生,reward 从 -0.11 改善到 0),但全部三个 candidate 配置、三个 family、45k–183k steps 的每个组合都坍塌到退化策略,**没有任何组合表现出对观察的选择性响应**。

---

## 1. 使用了哪个 R2 curriculum identity?

`qp-8f64a1b5…`(R2 final qualification plan digest),由输入锁逐项绑定并复算一致:

- C1 Opportunity Recognition(`cur261-c1-v5`)、C2 Context Gating(`cur261-c2-v9`)、C3 Cost-Aware Selectivity(`cur261-c3-v4`);
- rung 参数一律从**锁定的 R2 plan** 读取(不信任源码常量):C1 v5 固定段表/D0–D3 漂移梯度、C2 v9 wick 纹理门控(双 knob `wick_kappa`+`alpha_bps`)、C3 v4 强度档混合 + 摩擦 0.001998002;
- reference 阈值同源:`ma_sigma_mult=1.0`(C1)、`cue_thr=0.0105/wick_dir_thr=0/wick_width_thr=0.0120`(C2)、`margin=1.10/any_signal_s=0.22`(C3);
- 288 bars @ 15m、initial_price=1.0、causal unscaled curriculum adapter、真实 `RouteCStrategy.feature_engineering_standard`、冻结 `AlignedLongFlatEnv`、observation dim=9(8 生产特征 + 仓位槽)、window=1。

## 2. Stage 2.6.1 是否保持只读?

**是。** 输入锁 13 项检查全部通过:

- R2 verdict = PASS,result 与 exposure marker 绑定同一 plan digest,exposure status = completed(corpus 已消耗,2.6.2 从未触碰 `qualification_r2` seed);
- 2.6.1 十一个课程模块 + `RouteCStrategy.py` 双 sha256(文件级 + `feature_engineering_standard` 函数级)与 plan `code_identity` 逐文件一致——**零改动**;
- family versions 与 R2 `curriculum_family_summary` 逐族逐参数一致;
- rl_platform tree hash(`rp-8a61cd6…`,2.6.1 同款算法键=文件名)未漂移;六项冻结合同版本号一致;
- production observation identity 与 preprocessing boundary(causal unscaled)未漂移;vendor pin 未漂移且 clean。

## 3. 2.6.2 使用了哪些新 seed namespaces?

11 个(namespace payload 前缀 `stage2_6_2`,与 2.6.1 的 `stage2_6_1` 派生流天然不相交):

`ppo_config_dev_262`、`ppo_probe_train_262_c1/c2/c3`、`ppo_probe_eval_262`、`ppo_core_train_262_rep1/2/3`、`ppo_dev_eval_262`、`ppo_final_eval_262`、`ppo_smoke_262`。

派生函数 `derive262_seed` 是 2.6.2 自己的单一来源(2.6.1 的 namespace 列表属冻结合同,无权扩充);`ppo_final_eval_262` 有独立 lock marker 守卫,plan 锁定前对任何代码路径抛错封闭。

## 4. training/dev/final 是否完全隔离?

**是**,由 `seed_namespace_integrity.json` 全量枚举验证(比较派生 seed 整数,非 namespace 字符串):11 个 262 namespace 两两不相交;与 2.6.1 全部 11 个 namespace(含 `qualification_r2`)在 pair∈[0,20000)×attempt∈[0,5) 范围零重合;core 三 replicate 区间互斥。**final namespace 本轮从未解锁、从未生成**(regression_summary: `final_namespace_untouched=true`)。

## 5. PPO config 如何选择?

预注册 3 个 candidate(§9 上限内,`ppo_config_development_plan.json` 运行前锁定):

| candidate | lr | ent_coef | 其余 |
|---|---|---|---|
| cand_a_center(中心) | 3e-4 | 0.01 | MlpPolicy [128,128] Tanh、n_steps=574、batch=287、n_epochs=10、γ=0.99、GAE λ=0.95、clip 0.2、grad clip 0.5、CPU |
| cand_b_lowentropy | 1e-4 | 0.003 | 同上 |
| cand_c_highentropy | 3e-4 | 0.02 | 同上 |

rollout 对齐约束:n_steps=287×2(episode 决策步原子),bank 预算与 rollout 块边界对齐,训练后可断言不跳过/不重复/不越界。三 candidate 共用同一 `ppo_config_dev_262` 语料(C1/C2/C3 各 D1,70 episodes 训练 + 4-pair 评估集),每 candidate 总计 60,270 steps(≈60k 上限内)。

## 6. 是否存在 hyperparameter over-search?

**不存在。** 只有预注册的 3 个 candidate,无网格搜索/贝叶斯优化/final-eval 调参;三族与 staged/mixed 使用完全相同的超参数;reward scale 未改、无 reward normalization、无 VecNormalize、无任何 scaler。实测三 candidate 的 aggregate capture **全部无区分**(评估集上全部坍塌为退化策略,capture ≤ 0),按 fallback 规则选择中心候选 `cand_a_center`(digest `pc-27ab88…`)供 probe 使用;fallback 理由完整记录在 `selection_notes`(三个 candidate 延长诊断同样坍塌,选择不影响 FAIL 判定)。

## 7-9. C1/C2/C3-only probe 是否学会?

**全部没有。** 探针协议:selected config、model seed 26201、独立 `ppo_probe_train_262_{c1,c2,c3}` bank(C1 160 eps / C2、C3 240 eps,构成与 core 对应族部分一致)、独立 `ppo_probe_eval_262`(4 rung × 4 pairs × A/B)、相同 observation adapter、staged 内族 rung 顺序。

| 族 | 预算 | 训练审计 | core capture | gate(>0.10) | 行为 gap | gate(>0.10) | probe |
|---|---|---|---|---|---|---|---|
| C1 | 45,920 | pass | -0.026 | ✗ | 0.0 | ✗ | **FAIL** |
| C2 | 68,880 | pass | 0.0 | ✗ | 0.0 | ✗ | **FAIL** |
| C3 | 68,880 | pass | -8.36 | ✗ | 0.0 | ✗ | **FAIL** |

具体坍塌形态(逐 rung capture 见 probe artifacts):

- **C1**:终态 Always Long(ppo=-0.00200 = 精确摩擦),`long_rate_on_positive/neutral/negative = 1/1/1`(诊断态)或 0/0/0(延长态)——机会识别完全缺失;
- **C2**:终态 Always Flat,`long_rate_aligned = long_rate_anti_aligned = 0`,variant A/B 双侧均无门控行为;
- **C3**:终态 Always Flat,`long_rate_above_cost = long_rate_below_cost = 0`,churn=0(远低于 cost-ignorant,但也无任何收益);D0–D2 的 required baseline 是 `c3_cost_ignorant`(正收益),PPO 落后它 → capture 深负(-31.26/-4.82/-1.33)。

训练曲线提供机制证据:C1 的轨迹是「随机高换手(reward≈-0.11,changes 128)→ 学会降换手 → 短暂 Always Long(±摩擦)→ 翻转 Always Flat 并死锁」;C3 在 ep80 曾出现 reward=+0.088 的短暂正收益探索期(D0 strong 事件 +70bps 可捕获),但策略无法稳定保持该行为,随后坍塌。

## 10. staged 与 mixed 是否使用完全相同的 episode multiset?

**core 实验未执行**(见第 20 问)。配对机制已实现并被测试覆盖:`mixed_order` 对同一 multiset 做确定性 shuffle(shuffle seed 从 replicate model seed 哈希派生),`manifest_equality` 产出 `same_multiset=true / different_order=true`;三 replicate 的 bank 通过全局 pair_index 区间互斥。该设计只存在于代码与测试,本轮没有消费。

## 11. 三个 model seeds 分别表现如何?

**未执行。** core(26201/26202/26203)未开跑;唯一使用的 model seed 是 probe/config-dev 的 26201(§13 预注册)。

## 12-14. C1/C2/C3 是否学会对应能力?

全部否定(第 7-9 问):selectivity gap = 0、gating gap = 0、cost-selectivity gap = 0。PPO 不是「学会了一部分」,而是完全没有形成对观察的分化响应——`argmax` 策略在所有 latent 状态类别上行为一致(全 0 或全 1)。

## 15. PPO capture 了 reference gap 的多少?

**零或负。** probe 评估集上(reference/baseline 在同一 episode 上重新运行,非复用 R2 数字):C1 各 rung capture -0.62 ~ -0.01(分母为 reference 正 gap);C2 恰为 0(与 always_flat 重合);C3 为 -31.26 ~ 0(required baseline 是正收益的 cost-ignorant)。

## 16-17. D0/D1/D2 与 D3 的表现?

所有 rung 一致坍塌,没有难度梯度响应:D0(easiest,reference gap 最大)同样 0 学习——这本身是重要诊断:**失败与任务难度无关,而是机制性的**。D3 stretch 无单独结论(未进入 core 阶段)。

## 18. staged 是否发生 catastrophic forgetting?

**不适用**(staged core 未执行)。可报告的替代证据:C1-only 延长诊断显示的「Always Long → Always Flat」翻转是一种自我遗忘(先前学到的持仓偏置被丢弃),但这是单一任务内的坍塌,不是课程间的遗忘。

## 19-20. staged 与 mixed 哪个更好?是否有 schedule 满足 candidate PASS?

**均不适用——没有任何 schedule 接近 candidate PASS。** §23 的 A–F 条件在 probe 层面就已全灭(A:三族 mean core capture > 0.20——实际 ≤ 0;C:行为 gap > 0.15——实际 0.0)。按 §10「不要继续烧 core experiment 预算」与 §13「停止」,staged/mixed 的 6 个 core run 与 sealed final evaluation **均未执行**,顺序效应问题(§25)本轮无法回答。

## 21. final evaluation 是否只执行一次?

**零次。** final plan 从未锁定(lock marker 不存在),`ppo_final_eval_262` seed 从未派生过任何 episode(代码路径有 lock 守卫 + 测试覆盖),exposure marker 不存在。fail-closed 合同按设计保持未消耗状态。

## 22. production scaler domain gap 是否仍然存在?

**存在,且严重性升级。** 本阶段的因果结论之一:causal-unscaled 生产观察存在**特征尺度失衡**(`%-raw_*` ≈ 1.0 vs `%-ret-*`/`%-vol-*` ≈ 3e-3,约 300 倍),MLP 在该输入上无法从随机初始化发现选择性响应。这把 G5 domain gap 从「口径差异」升级为「可学习性差异」:同一任务、同一 reference 可解,但 PPO 在 unscaled 合同下不可学(当前预注册 config 空间内)。**不得将本阶段结果等价于真实行情上的 production PPO 表现**——production 的 MinMaxScaler 缩放可能正是可学习的前提(这本身是 2.6.1 登记的后续 domain gap)。

## 23. full-cold 是否全绿?

FAIL 路径下按 §30 不运行 full-cold(「不需要为了明确的 PPO 学习失败反复跑一小时以上 full-cold」)。已执行的回归:**2.6.2 测试套件 49 项全绿;2.6.1 相关测试 106 项全绿**(证明 2.6.2 未破坏任何上游合同)。

## 24. Stage 2.6.2 最终 PASS / FAIL?

**FAIL。** 判定链(全部 artifacts 佐证):

1. 输入锁 13 项全过(2.6.1 只读、Route C/observation/preprocessing/vendor 零漂移);
2. seed isolation 全过(11 namespace 互斥 + 与 2.6.1 零重合);
3. PPO smoke 14 项全过(环境/SB3 集成/save-load 复现/边界语义);
4. config development 受限且可审计(3 candidate、60k/candidate、选择与 fallback 理由完整记录);
5. **三族 probe 全部 FAIL**(core capture -0.026/0.0/-8.36,行为 gap 全 0)→ §13 停止;
6. 延长诊断(C1 4 倍预算)证明非预算不足;
7. core 与 final 未执行、final namespace 未触碰;
8. 测试 49+106 全绿。

按 §24:候选无基础学习 + probe 全灭 → **Stage 2.6.2 = FAIL,如实报告**。

---

## 附录 A:机制分析(供 2.6.3 之前的独立审查)

1. **水平抵消构造的双稳态陷阱**:C1/C2/C3 的 paired-noise/平衡漂移构造使 Always Flat = 0、Always Long = -摩擦,两者都是强局部最优;selective 策略的额外收益(opp 段正漂移)需要策略先「按观察分化」才能兑现,而分化路径上的中间态(随机部分持仓)期望收益 ≈ 0,没有梯度上的过渡带。
2. **advantage 信号 vs 探索预算**:单 bar 的选择性 advantage(D1 opp 段 +42bps vs 摩擦 20bps)真实存在且方向正确,但被 GAE 平滑、value 近似误差与熵坍塌稀释;策略在 ~20k steps 内先收敛到确定性退化态,ratio clipping 随后锁死探索。
3. **特征尺度失衡**:`%-ret-1` 的典型值 ~3e-3,对第一层权重的贡献与梯度比 `%-raw_close`(~1.0)小约 300 倍;MLP 的有效输入维度实质退化为 raw 价格水平 + pmr。causal-unscaled 是 R2 qualification 的合同(本阶段禁止修改),该合同对 handcrafted reference(直接阈值化 pmr)友好,对随机初始化的梯度学习不友好。
4. **证据边界**:以上是 FAIL 现象的机制假说,不是已证明的因果链;「PPO 在当前输入合同下不可学」的可证伪范围限于:预注册 3 config、MLP、60k–183k steps、single-env PPO(GAE)。任何外推(如「PPO 永远学不会」「换 config 也不行」)超出本阶段证据。

## 附录 B:已实现但未消费的资产

以下能力已实现、已测试、但因 probe FAIL 未消费(2.6.3 以后的迭代可直接复用):

- staged/mixed 严格配对训练(同 multiset 确定性 shuffle + manifest equality artifact);
- core 三 replicate bank 规划(640 eps 构成表 + checkpoint 计划 0/160/400/640);
- sealed final evaluation 协议(plan 锁定 → hash/code/config 守卫 → exposure marker → 一次性执行 → locked-threshold 判定);
- normalized reference-gap capture / 行为能力指标 / pair-cluster bootstrap / retention 计算的完整实现与测试。

## 附录 C:失败证据清单

- `probe_results_{c1_opportunity,c2_context,c3_cost}.json`:三族正式 probe(含逐 rung capture 表、行为指标、完整 episode 学习曲线);
- `extended_diagnostic_c1.json`:C1-only 640-eps(183,680 steps)坍塌轨迹与终态行为;
- `ppo_config_development_result.json`:三 candidate 全部无区分的原始记录;
- `models/ppo262/`:probe/config-dev/诊断模型 + sidecar manifest(config digest、seed、SB3 2.9.0/torch 2.13.0、observation identity、文件 sha256);
- `core_experiment_plan.json`:预注册设计 + NOT_EXECUTED 理由;
- `regression_summary.json`:最终 FAIL 判定与 checks。
