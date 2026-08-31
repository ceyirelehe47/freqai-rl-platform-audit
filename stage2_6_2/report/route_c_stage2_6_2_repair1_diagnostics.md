# Stage 2.6.2 Repair R1 — PPO 可学习性诊断与实验基础设施闭环(诊断报告)

- 阶段状态:**Stage 2.6.2 仍为 FAIL**(本轮为 Repair R1 诊断,不是 official PASS attempt,不改变阶段判定)
- 本轮判定:**Stage 2.6.2 Repair R1 Diagnostics: PASS**(诊断基础设施有效、全部对照完成、机械判定落入 Branch D)
- 诊断迭代:`s262_diag_r1`(与 s262_r0 的 11 个 official namespace 及全部 2.6.1 namespace 零 seed 重合,枚举证明见 `repair1/diagnostic_namespace_integrity.json`)
- 基线:`7481b39b3d141a21b845a111b9f48e036c5f98f5`(s262_r0 FAIL 检查点;父提交 `1927faa` = 2.6.1 R2 PASS);vendor freqtrade 固定 `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`,clean
- 诊断计划:`dp-eb37187b2b81b8bc37f15d896ea5d6e322d080e0dc124259859c666ae8f2733e`(运行前锁定;锁定后未改任何常数/seed/预算/判定规则)
- 产物:全部新写 `artifacts/route_c_stage2_6_2/repair1/`;**s262_r0 的全部 artifacts/models/report 一字未动**

---

## 0. 一页结论

1. **s262_r0 的 null-score 选择 bug 已修复且验证**:r0 的三个 candidate 在 D1-only 评估集上被错误套用 D0/D1/D2 加权公式 → score 全 null → fallback。新指标 `config_dev_D1_capture` 对 r0 历史数据重算出有限分数(三 candidate 均 -3.239),按预注册 all-fail 语义正确判定 all-FAIL、official 选择为空、probe/core/final 三层 fail closed。
2. **特征尺度失衡从假说升级为实测事实**:raw OHLC 组 mean|scale| = 1.009,ret/vol 组 = 0.0122(**82.9 倍**),price-ma-ratio 组 = 0.0171(59.1 倍);随机初始化 MLP 第一层的贡献占比 raw = **98.7%**、ret/vol = 0.91%、pmr = 0.40%。
3. **梯度确实到不了小尺度特征**:unscaled(Arm A)第一层逐列 |grad|:raw 列 ≈ 7.3e-6,ret/vol/pmr 列 1e-8 ~ 1.8e-7(低 40–7000 倍);fitted 缩放(Arm C)后全部列 0.002–0.012 同量级——梯度阻断被 scaling 解除。
4. **representation 本身可学**:linear 探针在 scaled 下三族 held-out balanced accuracy 0.91/0.91/0.98;MLP [128,128] unscaled 全坍塌(0.5),train-bank-fitted 缩放后 C1=0.821、C3=0.789(train≈eval,真实泛化);C2 连训练集都学不会(long 类仅 2.4%)。
5. **unscaled scratch PPO 不是"永远学不会"**:D0 小 bank 重复暴露 16 cycles 下,C3 有 2/3 seeds 形成真实选择性(train capture 133/405 + 概率分离 0.084/0.055),C1 有 1/3(capture 0.862),C2 0/3。
6. **混合课程 + 单遍暴露下 ablation**:Arm A 三 seeds 全坍塌(eval aggregate 0.0,与 r0 一致);Arm C(fitted)下 **C1 三 seeds train capture 全正(0.059/0.180/0.400),eval core capture 0.159/0.440/0.604——scaling 真实恢复了 C1 的学习并泛化**;但 C2/C3 在 scaled 下大量交易大幅亏损(core -1.2 ~ -3.6)。Arm B(10 的幂固定常数)不充分。
7. **BC warm-start(在 fitted arm)**:actor 成功克隆 reference(held-out bal acc **0.804**),PPO fine-tune 后摧毁到 **0.481**(retained=false)。
8. **机械判定 Branch D**(预注册规则,supervised 学会 + scratch 全不满足恢复规则 + BC 能学但 fine-tune 摧毁):主要 blocker 之一是 PPO update/value/advantage 或成本局部最优。同时如实记录:**证据呈复合结构**——scaling 解除梯度/表征阻断(C1 恢复)是确凿的 B 向证据,BC 摧毁与 C2/C3 scaled 大亏是确凿的 D 向证据;两者叠加。
9. **下一步(按 Branch D 路线)**:PPO optimization repair(advantage normalization / critic stabilization / smaller updates / KL control / actor-critic LR 分离 / cost transition dynamics),不进入 2.6.3。若未来要把 scaled 预处理升级为正式合同,必须先走 Stage 2.6.1 Repair R3(本轮 Arm B/C 仅为 diagnostic evidence,已按任务书禁止直接升级)。
10. **official final namespace 未解锁、未生成、未暴露**:`ppo_final_eval_262` 派生仍被 lock 拒绝;无 official final plan/exposure marker。

---

## 1. 本轮定位与边界

- 本轮 = **Stage 2.6.2 Repair R1 — PPO Learnability Diagnostics & Harness Closure**。不是新的 official attempt、不是 staged/mixed core experiment、不是 sealed final、不是 2.6.3、不是 2.6.1 R3。
- 冻结边界全部保持:2.6.1 generators/family versions/rung 参数/pair construction/reference policies/qualification artifacts/R2 plan digest(`qp-8f64a1b5…`)/R2 exposure marker 未动;RouteCEnvCore-v1.0.0 / ObservationSpec-v1 / BinaryLongFlatAction-v1 / NetLogEquityReward-v1 / MarketOpenCausalExecution-v1 / TerminalLiquidation-v1 未动;fee/slippage/tick rounding/reward/action/execution/ledger/terminal liquidation 未动;模型路线仍限 PPO + MLP + Long/Flat + single asset + spot + non-recurrent。
- 代码修改面:仅 2.6.2 自有文件(`ppo262_cli/env/train/metrics/banks` 5 个既有文件修改 + `ppo262_diag_train/diag_metrics/diag_namespaces/diagnose_cli` 4 个新诊断文件);`rl_platform/**` 树哈希与 `curriculum261_*` R2 code_identity 全部不变(input_lock 13 项全过,见 `repair1/baseline_integrity.json`)。

## 2. s262_r0 为什么 FAIL —— 实验事实 vs 机制假说

**实验事实(r0 保留证据,未覆盖)**:
- 三族 probe core capture = -0.026 / 0.0 / -8.36,intended behavior gap 全 0;最终 deterministic policy 全部 Always Flat(C1 延长 4 倍预算 183,680 steps 后仍死锁)。
- config-development harness 有指标错误:实际只评估 D1,却调用要求 D0/D1/D2 的 `family_core_capture()` → 三 candidate score 全 null → fallback 选出 `cand_a_center`——**它不是通过有效比较选出的**。
- callback 学习曲线 `episode_key=""`(terminal info 丢失 attribution);rollout 诊断数据来源不明(滞后一轮或为空)。

**本轮修复后确立的新事实(取代原机制假说)**:
- 特征尺度失衡(82.9 倍)与第一层贡献占比(raw 98.7%)是**实测**,不再是"约 300 倍"的口头估计。
- unscaled MLP 监督探针全坍塌 + unscaled 第一层小尺度特征列梯度低 40–7000 倍——**特征尺度是 representation/optimization blocker 的机制链闭合**。
- 但 C3/C1 在 D0 重复暴露下能学(overfit)、C1 在 fitted 缩放下能学(ablation)——**"PPO 永远学不会"不成立**;失败是尺度/课程结构/预算/优化的复合结果。
- BC 能学而 fine-tune 摧毁——**PPO update 本身在当前 advantage/cost 结构下会破坏选择性策略**。

## 3. Harness 修复(A/B/C/D)

### Repair A — config-development 指标(方案 B:独立 D1 指标)
- 新指标 `config_dev_D1_capture`(ppo262_metrics.py):只读 `{family}/D1` cells 的三族均值;**输入不足(缺 cell/capture=None)raise 而非返回 null**;与 `family_core_capture`(语义被测试锁死,未改)完全分离。
- 选择逻辑抽为纯函数 `select_config_from_scores`:score 全有限;all-fail(全部 ≤0 且无任何 family > 0.05)→ `selected=None`,**删除 fallback 语义**;`cmd_config_dev` 与 `cmd_config_dev_select` 单一来源同步修复(旧版 r0 result 兼容重算)。
- 在 r0 历史数据上的验证(`repair1/config_metric_repair.json`,r0 原文件零改动,sandbox 重选):重算分数 -3.239 × 3(有限)、all-fail 检出、重选命令退非零、不生成 selected config、gate 关闭,7/7 checks PASS。

### Repair B — 三层硬门禁
- **Config Gate**:`selected_ppo_config.json` 缺失/selected 为空/标记 all_fail → probe/core/final-lock 全部拒绝(实测 `repair-verify`)。all-fail 时**清除 stale selected 文件**防旧 artifact 绕过。
- **Probe Gate**:三族 `probe_results_*.json` 必须存在、schema 完整(D0–D3 capture cells + 非空 episode_curve + env_audit 关键字段)、内部一致(pass=True 必须与 gate 字段/审计一致)——**手工伪造的 `{"pass": true}` 空文件、缺 cell 文件、矛盾文件全部被拒**(9 个 gate 测试覆盖)。core 与 dev-eval 与 final-lock 入口全部接入。
- **Final Gate**:input lock + config gate + probe gate + 6 个 core `training_run_summary` 全 pass + 模型/manifest 哈希(原有)。
- **workflow 分离**:`diagnose-*` 命令族独立 CLI(`ppo262_diagnose_cli`),只写 `repair1/`;official gate 只读顶层 `probe_results_*.json`,**repair1 目录下的产物不被 official runner 接受**;诊断命令在 official gate 关闭后仍可显式执行。

### Repair C — episode attribution
- `CurriculumMultiEpisodeEnv.step()/reset()` 的 info 每 step(尤其 terminal step)携带 `episode_key/namespace/family/rung/pair_index/variant/manifest_index`(`_attribution()`);只进 info/日志/callback,不进 observation/reward/policy(obs 合同测试锁定 9 维 float32 不变)。
- callback episode 行扩为完整归因 + `cost_fees_paid/terminal_liquidation_fee/ledger_trades`(动作目标变化与真实 ledger trade 分开计);terminal 丢 attribution 直接 raise。
- 实测(`repair1/episode_attribution.json`):terminal identity 保留 ✓、曲线与 manifest 逐 episode 对齐(循环 bank 2 cycles 亦对齐)✓、staged/mixed 顺序可由日志重建 ✓。

### Repair D — PPO rollout/update 诊断绑定
- **根因实测**:SB3 2.9.0 的 learn 循环 = `collect_rollouts → train()(只 record 不 dump) → dump_logs()(dump 并清空)`;r0 的 callback 在 `on_rollout_end`(上一轮 dump 之后、本轮 train 之前)读 `name_to_value` 只能得到空 dict。且 2.9.0 的 PPO.train() **已不记录 `train/grad_norm`**。
- 修复:`DiagnosedPPO`(子类化 PPO,构造不消耗额外随机数——同 seed 初始权重与原生 PPO 逐位一致,测试锁定)在 `train()` 返回后直读 `name_to_value`(恰为本 update 的值),经 `clip_grad_norm_` 包装捕获 total grad norm;每条记录绑定 `{update_index, rollout_index, env_step}`,缺失 metric 显式进 `missing_metrics`(不静默填 0)。
- 实测(`repair1/update_metric_binding.json`):首个 update 即有 8/8 指标(KL/clip/policy loss/value loss/entropy/EV/loss/grad_norm)✓、index 单调且 rollout 1:1 ✓、重复运行数值逐位一致 ✓。

## 4. 特征尺度 profile(§26 Q8/Q9)

`repair1/feature_scale_profile.json`(4 个 bank:config-dev train/eval、probe train/eval;每特征 min/max/mean/std/median/1%/5%/95%/99% 分位、missing/inf、相关矩阵、reference-action 条件分布):

| 组 | 列 | mean\|scale\| |
|---|---|---|
| raw OHLC | raw_open/high/low/close | **1.009** |
| ret/vol | ret-1 / ret-4 / vol-24 | 0.0122 |
| price-ma-ratio | pmr | 0.0171 |
| position slot | position | 0.0(flat 轨迹口径恒 0) |

- 尺度比:raw : ret/vol = **82.9 倍**;raw : pmr = 59.1 倍(r0 报告的"约 300 倍"是以个别分位比较的过估,本轮以全 bank 分位数表为准修正)。
- **第一层激活分析**(`repair1/feature_activation_profile.json`,随机初始化 [128,128] Tanh,seed 26201,未训练):pre-activation 贡献占比 raw = **98.7%**、ret/vol = 0.91%、pmr = 0.40%——**raw OHLC 主导 pre-activation,小尺度特征被数量级淹没**;Tanh 饱和率(|tanh|>0.96)= 0%(未饱和——问题不是饱和而是淹没/梯度稀疏)。

## 5. 静态监督探针(§26 Q10/Q11)

`repair1/supervised_probe_results.json`(输入 = policy-visible observation 9 维,reference 自身轨迹;label = causal observation reference policy 动作;pair 级 train/eval 隔离,各 20664 bars × 3 族;linear = LogisticRegression,MLP = [128,128] Tanh Adam 3e-4 × 20ep):

| family(long 率) | arm | linear eval bal-acc | MLP train | MLP eval | MLP 学会(rule) |
|---|---|---|---|---|---|
| C1(24.8%) | unscaled / fixed / fitted | 0.894 / 0.929 / 0.931 | 0.500 / 0.500 / 0.830 | 0.500 / 0.500 / **0.821** | 否 / 否 / **是** |
| C2(2.4%) | unscaled / fixed / fitted | 0.500 / 0.734 / 0.907 | 0.500 / 0.500 / 0.502 | 0.500 / 0.500 / 0.500 | 否 / 否 / 否 |
| C3(5.1%) | unscaled / fixed / fitted | 0.786 / 0.979 / 0.976 | 0.500 / 0.500 / 0.794 | 0.500 / 0.500 / **0.789** | 否 / 否 / **是** |

- **unscaled 与 scaled 的差异**:unscaled MLP 三族全坍塌到 0.5(预测单类),而 linear 在 C1/C3 unscaled 上可达 0.89/0.79——尺度失衡对 MLP 类优化器是致命的,对特征级自适应的正则化线性器不是。
- fitted MLP 的 train≈eval(0.83/0.82、0.79/0.79)——**无过拟合 gap,真实跨 pair 泛化**。
- C2 即使 scaled 也学不会(连 train 都 0.50;linear fitted 却 0.907)——C2 的 long 类仅 2.4% + wick 交互,当前 MLP 训练设置(20ep)下优化困难,是需要单独审视的 representation/标签边界问题(指向 §13 解释规则的第三种情形)。

## 6. Tiny overfit(§26 Q12)

`repair1/ppo_overfit_results.json`(每族 D0 8-pair bank × 16 cycles = 73,472 steps/seed,3 model seeds 27101–27103,unscaled):

| family | seeds 形成非退化选择性 | 关键数字 |
|---|---|---|
| C1 | 1/3 | seed27102:train capture **0.862**,P(Long) 分离 0.251,det gap 0.360;其余 seeds 全 flat |
| C2 | 0/3 | 全部 Always Flat(capture 0 / -0.07) |
| C3 | 2/3 | seed27102:capture **133.7**、prob gap 0.084;seed27103:capture **404.6**、prob gap 0.055(在重复 bank 上超出 reference = 过拟合背题) |

- 结论:**unscaled scratch PPO 在最简单、重复暴露的任务上能够形成非退化选择性**——r0 的坍塌不是"表示不可学"或"预算永远不够",而是(尺度 + 课程结构 + 单遍预算 + 优化)的复合;C2 是最难族(与其 supervised 结果一致)。
- 这是诊断性过拟合证据,不是泛化证明(dev bank 上 C1/C3 未保持正 capture)。

## 7. Policy dynamics:概率层 vs deterministic(§26 Q13/Q14)

`probability_dynamics_checkpoints`(init/5%/10%/25%/50%/final 六检查点,`repair1/ppo_overfit_results.json` 与 `preprocessing_ablation_results.json` 内)+ `probability_final`:

- **坍塌 seed 的确定性 flat 并不总掩盖概率层进步**:C1 overfit seed27102 的 det gap 0.360 与 prob gap 0.251 同向出现;但 ablation Arm A 全 flat seeds 的 prob gap 恒 0——**Arm A 下连概率层也无状态区分**(网络输出本身完全没有条件分化),不存在"概率已分离但未过 0.5"的隐藏进展。
- Arm C(fitted)出现新形态:**deterministic/capture 恢复(C1 0.16–0.60)但 eval bank 的 P(Long) latent 分离为负(-0.09 ~ -0.22)**——模型学到的盈利策略与 seg_state 标签口径不同向(概率层口径以 flat 轨迹展开,登记为已知口径限制);机械恢复规则因此未把 Arm C 判为 recovered(如实记录,不改规则)。
- stochastic(固定诊断 RNG seed 262099)与 deterministic 一致率、每族 P(Long)/logit 差/熵/value 均已逐 checkpoint 记录。

## 8. Advantage / Value / 梯度 / 成本(§26 Q15/Q16/Q17)

`preprocessing_ablation_results.json` 内 `rollout_stats_final` / `update_records_summary` / `gradient_probes` / `cost_decomposition`(以及 overfit 同款):

- **advantage 对 selective action 无稳定正信号(unscaled 坍塌态)**:Arm A 末期 rollout 中 action_1 仅出现 1 次(574 步),其 advantage 无法形成分布;positive rate 65% 全部来自 flat 动作的自洽基线。Arm C 交易活跃后 advantage 双向(52%/48%),action_0 mean 0.018 vs action_1 mean 0.002——**flat 的 advantage 反而更高**,与 C2/C3 成本结构一致(入场付摩擦,期望优势为负 → 成本局部最优拉向 flat)。
- **critic 预测力弱**:Arm A SB3 EV=-0.07(value_loss≈0,塌缩到常数);Arm C EV=+0.21(有学习但不足;诊断口径 EV_vs_returns=-0.74)。critic 不是主要瓶颈但也不充分。
- **梯度到达性(本轮最硬的机制证据)**:第一层逐输入列平均 |grad|——Arm A:raw 列 ≈7.3e-6,ret/vol/pmr 列 **1e-8~1.8e-7(低 40–7000 倍)**,position 列 0;Arm C:全部列 0.002–0.012 同量级。actor/critic 分离范数同步记录(Arm A 0.0021/0.0014 vs Arm C 0.298/0.197)。
- **成本分解**:动作目标变化(position changes,含探索期)与真实 ledger trades/费用/终端清算费分开记录(例:Arm C seed27201 训练期 fees 总额与 12,794 笔 ledger trades 对照 Arm A 的 8,830 次 position changes 但 0 真实交易)。

## 9. Preprocessing ablation A/B/C(§26 Q18)

`repair1/preprocessing_ablation_results.json` + `paired_initialization_integrity.json` + `paired_manifest_integrity.json`(严格配对:同 train_bank 对象(同 seed 槽位 pair 区间)/同 model seed/同初始权重哈希(3 seeds × 3 arms 全一致,pairing_ok=true)/同 config(cand_a_center)/同 82,656 steps/同 eval bank;唯一差异 = obs adapter;48-ep 三族 D0+D1 混合 bank × 6 cycles;eval = 三族 D0–D2 各 4 pairs):

| arm | eval aggregate capture(3 seeds) | C1 eval core | C2 eval core | C3 eval core |
|---|---|---|---|---|
| A unscaled(=r0 逐位) | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 | 0.0 / 0.0 / 0.0 |
| B fixed causal(10^round 规则) | -1.26 / -0.02 / -0.67 | -0.67 / 0.0 / -0.04 | -1.11 / 0.0 / 0.01 | -2.01 / -0.05 / -1.99 |
| C train-bank fitted z-score | -1.26 / -1.07 / -1.13 | **0.159 / 0.440 / 0.604** | -1.18 / -1.41 / -1.20 | -2.76 / -2.24 / -2.80 |

- train bank capture(Arm C,C1):0.059 / 0.180 / 0.400(3/3 seeds > 0)。
- **解读**:scaled 确实解除了坍塌并恢复了 C1 的真实学习(eval 泛化 0.16–0.60);但 C2/C3 在 scaled 下开始大量交易(11k–13k ledger trades)并大幅亏损——**scaling 是必要非充分**:它修复了表征/梯度通道,但 C2/C3 的成本局部最优/优势结构问题暴露得更严重(C2 需要罕见 long 类的精确 gating,C3 的 above/below-cost 边界在正摩擦下天然惩罚交易)。
- 机械恢复规则(train capture>0.05 ∧ prob gap>0.05 ∧ det gap>0.02,≥2/3 seeds)下三 arm 均未 recovered(C arm 的 prob gap 为负,见 §7 口径说明)——规则预注册后未改动。

## 10. BC warm-start(§26 Q19/Q20)

`repair1/bc_warmstart_results.json`(条件满足:supervised fitted MLP 学会 C1/C3;BC 在 fitted arm 执行;label 只来自 causal reference;bc_train/bc_eval 独立 namespace + pair 区间;critic 不读 latent 且未被 BC 触碰(参数哈希验证);actor 导入验证 `bc_init_actor_state_sha256`):

- **BC 能学**:held-out balanced accuracy **0.8035**(actor 从随机初始化克隆 reference 成功;train 0.995)。
- **PPO fine-tune 摧毁**:41,328 steps(3 cycles)后 held-out bal acc **0.4810**(绝对下降 0.32 >> 阈值 0.15;rule retained=false)。fine-tune 后 eval capture 同步恶化(aggregate -1.71)。
- 结论:当前 PPO update/value/advantage 或成本局部最优会主动破坏已加载的选择性策略——与 §8 的 advantage 结构证据(C2/C3 中 flat 的 advantage 高于 long)互相印证。

## 11. 决策树分支(§26 Q21)

机械判定(预注册规则,`repair1/diagnostic_decision.json`):

> **Branch D — supervised 能学,但 PPO fine-tune 摧毁 BC policy**

证据矩阵:
- supervised 学会:fitted arm C1/C3(✓);unscaled 学会:否
- unscaled scratch 恢复(Arm A):否(0/3)
- scaled scratch 恢复(机械规则):否(0/3;C1 capture 恢复但 prob 口径反向,如实登记)
- BC:能学(0.804);fine-tune:摧毁(0.481)

**同时如实记录的复合证据(不勉强归因到单一根因)**:
1. scaling/梯度阻断是确凿 blocker(§4 激活占比、§8 梯度列、§5 unscaled MLP 坍塌、§9 C1 恢复)——B 向证据;
2. PPO update/成本局部最优是确凿 blocker(§10 BC 摧毁、§9 C2/C3 scaled 大亏、§8 advantage 结构)——D 向证据;
3. unscaled PPO 在 D0 重复暴露下部分可学(§6)——课程结构/budget 亦是变量。

## 12. 下一步路线(§26 Q22)

按 Branch D:**PPO optimization repair**(单独一轮治理:advantage normalization、critic stabilization、smaller updates、KL control、actor/critic learning-rate 分离、cost transition dynamics 的受控对照),**不进入 2.6.3**。

补充约束(本轮证据直接推出):
- 任何 optimization repair 的对照实验建议在 scaled 预处理下进行(unscaled 下梯度通道本身不通,会混淆优化器变量);
- **scaled 预处理若要成为正式合同,必须走 Stage 2.6.1 Repair R3**(冻结新 preprocessing contract → reference/baseline 适配 → 新 calibration → 新 robustness gate → 新 qualification seeds → 新 final qualification),本轮 Arm B/C 只是 diagnostic evidence,**不得**直接用于 official 2.6.2 rerun;
- C2 的可学习性(2.4% 稀疏 long 类 + wick 交互,scaled MLP 连 train 都学不会)应在 R3 中与 preprocessing 合同一并重审。

## 13. official final namespace(§26 Q23)

- unlocked:**否**(`final_evaluation_plan.json` 不存在;`derive262_seed("ppo_final_eval_262", …)` 仍被 lock 拒绝,测试覆盖)
- generated:**否**(无 final plan/final raw/summary)
- exposed:**否**(无 exposure marker;`final_eval_exposed()` = False,测试覆盖)
- s262_r0 的 11 个 official namespace 未消费任何新 seed;诊断走独立 `s262_diag_r1` 派生流(与 official/2.6.1 全量枚举零交集)。

## 14. Repair R1 判定(§26 Q24)

**Stage 2.6.2 Repair R1 Diagnostics: PASS** —— 依据(任务书 §22 逐项):
- r0 evidence 完整保留(文件清单快照见 `baseline_integrity.json`);2.6.1/Route C 只读(input_lock 13 项过)
- config 指标不再 null(r0 数据重算有限 + 沙盒重选 fail-closed 全过);config/probe/final 三层 gate fail closed(伪造 artifact 无法绕过,9 测试)
- diagnostic 与 official workflow 分离(独立命令族 + namespace + 目录)
- attribution 完整、update 绑定正确(8/8 指标含 grad_norm)
- deterministic/stochastic/probability 三层指标、advantage/value/gradient/cost 诊断、feature profile、supervised、overfit、A/B/C ablation、BC warm-start 全部完成
- 全部对照严格配对(同 episodes/seed/初始权重,3 seeds × 3 arms 哈希一致)
- 机械落入 Branch D(A–E 内),非"加 scaler 赚钱"式结论
- final namespace 未触碰;targeted + stage2_6_2 + 2.6.1 + Route C 代表回归全绿(见 §15)

**Stage 2.6.2 状态不变:FAIL**(直到未来全新 official iteration + 全新 sealed evaluation 完整通过)。

## 15. 测试与回归

- 新增 2 个测试文件 47 项:config scoring(5)/gate enforcement(10)/attribution(4)/update metrics(5)/probability(3)/scaling(7)/BC(3)/namespace(6)+ 杂项 4;连同既有共 **96 项全绿**(`tests/route_c_stage2_6_2/`)。
- 受影响回归:`tests/route_c_stage2_6_1/`(冻结面验证)与 Route C 代表(`route_c_stage2_6_0`、`route_c_stage2_6_0j`)全绿;本轮未修改 `rl_platform/**` 与 `curriculum261_*`(input_lock 内容寻址证明),未运行 full-cold(非 official PASS closure,任务书 §25)。

## 16. 禁止事项遵守声明

未:覆盖 r0 证据 / 修改 2.6.1 generator 或 Route C / 修改 reward/fee/action / 使用 qualification_r2 或 ppo_final_eval_262 / 生成 official final plan / 声称 scaled diagnostic 通过 2.6.2 / 进入 2.6.3 / 大规模 hyperparameter sweep / reward normalization / VecNormalize / recurrent / multi-asset / historical training / backtest / dry-run / real trading。

## 附录 A — repair1 artifacts 清单

`baseline_integrity / historical_fail_binding(并入 baseline 与 config_metric_repair 的 r0 重现)/ route_c_integrity(并入 baseline_integrity)/ stage261_readonly(并入 baseline_integrity)/ official_gate_repair / config_metric_repair / episode_attribution / update_metric_binding / diagnostic_plan + digest / diagnostic_namespace_integrity / feature_scale_profile / feature_activation_profile / supervised_probe_plan + results / ppo_overfit_plan + results / preprocessing_ablation_plan + results / paired_initialization_integrity / paired_manifest_integrity / policy_probability_dynamics(内嵌于 overfit/ablation 的 checkpoint 记录)/ value_advantage_diagnostics 与 gradient_diagnostics 与 reward_cost_decomposition(内嵌于 ablation/overfit 的 rollout_stats/gradient_probes/cost_decomposition)/ bc_warmstart_results / diagnostic_decision / regression_summary`

BC warm-start 已执行(条件触发),无空 artifact。

## 附录 B — 与 r0 的对照

| 维度 | s262_r0(FAIL) | Repair R1(诊断) |
|---|---|---|
| config 选择 | score null + fallback | D1 指标有限分 + all-fail STOP |
| episode 曲线 | episode_key="" | 完整归因 + 成本列 |
| rollout 诊断 | 空滞后数据 | 8 指标绑定 update/rollout |
| 尺度问题 | "约 300 倍"假说 | 82.9 倍实测 + 98.7% 激活占比 + 40–7000 倍梯度差 |
| PPO 能力 | "未观察到选择性学习" | D0 重复暴露下 C3 2/3、C1 1/3 可学;scaled 下 C1 恢复 0.16–0.60 |
| 根因 | 未知 | 机械 Branch D + 复合证据(scaling 阻断 + update/成本局部最优) |
