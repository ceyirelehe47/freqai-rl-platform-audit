# Stage 2.6.2 Repair R2 Diagnostics — Family-Aware Evaluation、三 Seed BC 与真实 PPO 梯度闭环

- iteration:`s262_diag_r2_1`(诊断轮,非 official PASS attempt)
- 基线:`af871ee9c9e449c541dfdb5c8412d4c69f85c55e`(R1 检查点,被独立审查判 FAIL)
- 计划锁:`dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60`
- verdict:**Repair R2 Diagnostics: PASS**(语义 validator 60 项检查零问题;C1/C2/C3 分支全部落入 A–E)
- **Stage 2.6.2 official 状态不变:仍为 FAIL**
- family branches:**C1 = B(仅 scaled scratch PPO 恢复)/ C2 = A(unscaled scratch PPO 恢复)/ C3 = D(BC 学会但被 PPO fine-tune 摧毁)**
- 推荐下一步:**Stage 2.6.1 Repair R3**(重新冻结 preprocessing contract 并重新 qualification;不得直接 official 2.6.2);C3 的 D 分支证据同时指向其后的 PPO Optimization Repair
- official final namespace:未解锁、未生成、未暴露(`ppo_final_eval_262` 零接触)

---

## 0. 迭代历史与诚实记录

本轮实际经历三次计划锁(前两次按任务书 §13 废止,全部记录于现行计划的 `supersedes` 字段):

| 锁 | iteration | 废止原因 | 废止时的证据状态 |
|---|---|---|---|
| `dp-0551c1a1…` | s262_diag_r2 | gradient-verify 的 clipping 单调检查用绝对容差比较两次独立浮点范数求和,未裁剪时因求和顺序噪声误报(post=0.24678431 > pre=0.24678429,差 1.5e-8) | 零:在任何正式 diag bank 生成前发现,repair2/ 清空重锁 |
| `dp-0a0c2e2c…` | s262_diag_r2 | `_checkpoint_diagnostics` 缺 `evaluate_family_cells` 导入,首个 scratch run 的 checkpoint 评估即 NameError 崩溃 | scratch/BC 零模型证据;该锁下生成过的 supervised 证据随迭代作废并以新 namespace/seed 重新执行 |
| `dp-ee6f8dc1…` | **s262_diag_r2_1** | (现行) | — |

重启合同:s262_diag_r2_1 使用全新 namespace 集合(`diag262r2_1_*`,16 个)与全新 model seeds(supervised 28401-28403 / scratch 28501-28503 / BC 28601-28603 / prob RNG 262311),与 official、diag_r1、被废止的 diag_r2、2.6.1 全部 seed 空间整数级枚举隔离(`cross_superseded_overlaps` 为空)。**本轮在真实大运行之前先以 mini 预算 + 临时目录对全部 11 个 CLI 命令做了全链路 dry-run(含用假 supervised 结果单独驱动 BC 执行分支),这是第三次锁一次通过的直接原因。**

历史证据保留(§2):`s262_r0` 与 `s262_diag_r1` 的 artifacts/models/report 全部只读;`historical_diagnostic_binding.json` 记录 R1 全部 21 个 artifact 文件的 sha256,语义 validator 逐文件重算核验(`r1_artifacts_unmodified`);`test_ppo262_r2_preservation.py` 亦做会话内基线哈希合同。

## 1. Repair R1 为什么被独立审查判为 FAIL?

独立审查结论 = **FAIL / Branch F(INCONCLUSIVE)**,七项缺陷(原文要点):

1. mixed-family evaluator 以 `bank[0].key.family` 的 reference 评估整个 bank;
2. BC 计划锁定 3 个 seeds,实际只执行了第一个;
3. Arm B 实际读取 diag 训练 bank 标准差(`10^round(log10(std_trainbank))`),不是 data-independent fixed scaling;
4. 预注册的 probability checkpoints 实际为空(`"probability_dynamics_checkpoints": {}`,saver 从未传入);
5. gradient probe 用行为模仿式 `-log_prob(action)`,不是 PPO clipped surrogate gradient;
6. C2 supervised MLP 没有控制 ~2.4% Long label 的类别不平衡;
7. diagnostics PASS validator 大量只检查文件存在,没有语义验证。

R1 的 artifacts 与自称 PASS 的报告**原样保留**作为诚实的诊断失败历史;本报告不修改任何旧 artifact 让旧报告"变正确"。

## 2. mixed-family evaluator 的根因与新 evaluator 的证明

**根因**:R1 `_eval_d0_capture()` 内 `fam = bank[0].key.family` —— mixed eval bank 按 staged 顺序以 C1 开头,于是 C2/C3 的全部 capture cells 用 C1 的 reference policy(在 C2/C3 episode 上运行)与 C1 的 required baselines 计算。C2/C3 旧 capture 因此无效:分子里的 "reference mean" 根本不是该族 reference 的收益,`c2_local_only`/`c3_cost_ignorant` 两个 required baseline 甚至从未在该 cell 上运行。

**新 evaluator**(`ppo262_r2_evaluator.py`):

- `evaluate_single_family_bank(...)`:收到 mixed bank 抛 `MixedFamilyBankError`(fail closed);
- `evaluate_mixed_family_bank(...)`:显式按 **family × rung** 分组,每个 cell 用该 family/rung 的正确 `build_261_policy_set` 构建 reference 与 required baselines;
- 每个 cell 记录 reference identity:`reference_class` / `reference_module` / threshold 解析值(rung_params + reference_thresholds)/ required baseline names / episode manifest sha256,可追溯证明 **C2/D1 用的是 `C2ReferencePolicy`、C3/D1 用的是 `C3ReferencePolicy`**(scratch 结果内全部 81 个 cell 的 identity 均与 family 合同匹配,语义 validator 复核);
- sentinel 回归(`family_evaluator_validation.json`,PASS):真实三族 D0/D1 bank 上 (a) mixed 评估与逐族 single 评估的 cell 数值完全一致;(b) 逐族 identity 正确;(c) 复现 R1 错误路径(用 C1 policy set 评估整个 bank)时 C2/C3 cells 的 reference_mean 与正确值**必然发散**(bug 可检测);(d) 单族评估器拒绝 mixed bank。对应的 `test_ppo262_r2_evaluator.py::test_bank0_family_shortcut_detected` 保证:若 evaluator 退回 bank[0] shortcut,测试失败。

**C2/C3 旧 capture 为什么无效**:如上,reference 与 baselines 全部张冠李戴;数值本身还叠加了 §4 的 first-N 概率偏差。本轮全部 capture 由 family-aware 路径重算。

## 3. Denominator sanity(R > B)

`capture = (P - B) / (R - B)` 要求 `R > B`。新 evaluator 对每个 cell 检查 `reference_mean > best_baseline_mean`;不满足的 cell 标记 `invalid_reference_gap`、`capture = None`、**从 branch 判定中排除**,绝不当作普通数值解释。`family_eval_capture` 进一步要求 D1 valid 且 ≥2 个 valid cell,否则该族 capture 证据无效。

本轮实测(`reference_gap_validity.json`):三族 eval bank 的全部 9 个 cell(3 族 × D0/D1/D2,各 4 pairs × A/B)denominator 全部为正 —— C1:0.206/0.123/0.084;C2:0.033/0.018/0.018;C3:0.0020/0.0036/0.0084。**C3 的 reference-vs-baseline 差距在新 corpus 上极小**,这解释了 C3 capture 动辄 100+:PPO 的长仓偏向越过的是一个非常窄的 reference-gap,属于真实测量而非计算错误;概率/行为判据(§7)正确地将其排除出"恢复"判定。

## 4. probability evaluation 如何避免 first-N bias

R1 多处 `eval_bank[:24]` —— staged 顺序以 C1 开头,等于只评估了 C1。R2 禁止一切 `[:N]` 切片:概率诊断在**每族自己的完整 eval bank**(24 episodes,D0/D1/D2 × 4 pairs × A/B)上运行 `probability_metrics_on_bank`,分别输出 C1/C2/C3 probability gap,并验证每族每 latent 类样本数非零(`sampling_sufficient`)。实测类计数:C1 {positive 1728, neutral 3456, negative 1704};C2 {aligned 618, anti_aligned 618};C3 {above_cost 374, below_cost 674} —— 全族非零。

## 5. Scaling arms:A 是否 bitwise、B 是否真正 data-independent、旧 B 的新名字

- **Arm A(unscaled)**:identity adapter,与 s262_r0/R2 observation bitwise 一致(测试断言 `apply` 恒等);
- **Arm B(fixed precommitted)**:常数 = `10^round(log10(std_i))` 逐特征作用于 **R1 已暴露的历史 artifact** `repair1/feature_scale_profile.json` 的 `config_dev_train` 统计(s262_r0 official corpus;来源 artifact sha256 记录于 `fixed_scaling_contract.json`),即 `[0.01, 0.1, 0.01, 0.01, 0.1, 0.1, 0.1, 0.1, 1.0]`,center=0,position slot 恒 identity。**在生成任何 diag262r2_1 episode 之前写入计划锁定;不读取任何 r2 train/eval bank;不在每 episode 拟合;不根据结果调整。** 构造器合同:`ObsAdapter.fixed(center, scale, *, source)` 不接受任何训练数据(测试断言签名);更换任何"训练数据"不可能改变常数(常数无数据入参);
- **Arm C(train-bank-fitted frozen)**:只 fit 该 family/seed 的训练 bank obs(mean/std z-score),fit 后冻结应用于训练与独立 eval;eval 不参与 fit(测试断言 fit 后常数不因 apply eval 而变);position slot 不缩放;
- **旧 R1 Arm B 重新命名**:`coarse_train_fitted`(它读取 diag 训练 bank 统计),记录于现行计划的 `arms.legacy_r1_arm_b_reclassified`,仅作历史对照,不得再称 fixed scaling。

三 arms 严格配对(`preprocessing_pairing_integrity.json`,PASS):同 family/seed 共享同一 train_bank 对象(manifest sha256 记录)、同 seed 初始权重(`initial_policy_state_sha256` 三 arm 逐组相等)、同 config、同 82,656 steps、同 eval bank、同 checkpoint schedule;唯一差异 = observation preprocessing。

## 6. Scratch PPO 结果(family 分开,3 arms × 3 seeds)

预算(计划锁定):每 run 16-episode 单族 bank(D0/D1 × 4 pairs × A/B)× 18 cycles = 82,656 steps;`cand_a_center` 配置;共 27 runs,总 2,231,712 env steps,2117 秒。

恢复判据(预注册,同族四条件):family eval capture > 0(valid reference gap)且该族 probability gap > 0.05 且该族 deterministic behavior gap > 0.02;≥2/3 seeds。

| family | Arm A(unscaled) | Arm B(fixed) | Arm C(fitted) |
|---|---|---|---|
| C1 | **未恢复**(cap -0.019/-0.019/0.00;pgap≈0;det=0;坍塌) | **恢复 3/3**(cap 0.758/0.968/0.785;pgap 0.19-0.35;det 0.18-0.35) | **恢复 3/3**(cap 1.42/1.45/1.51;pgap 0.24-0.41) |
| C2 | **恢复 2/3**(cap 12.27/11.47/-0.10;pgap 0.15-0.20;det 0.23-0.30) | 恢复 3/3(cap ≈11-12) | 恢复 3/3(cap ≈12.3) |
| C3 | 未恢复 1/3(cap 136-154 但 pgap≤0.059、det 多为负) | 未恢复 1/3 | 未恢复 1/3 |

要点:

- **C1 的 blocker 确认为 observation scaling**(与 R1 的特征尺度证据一致:raw OHLC 与 ret/vol 组 mean|scale| 比 82.9);unscaled 下三 seed 全坍塌,scaled 下三 seed 全恢复且概率分离真实存在;
- **C2 的 scratch PPO 在 unscaled 下即恢复**(2/3 seeds)——尽管 C2 的 reference 动作在 unscaled 下连类平衡监督都学不会(§7)。解释:PPO 学到的是**超过 reference 的策略**(capture ≈ 11-12,分母 0.018-0.033),其对齐/反齐概率分离(0.15-0.29)与门控行为差(0.23-0.30)是真实测量。监督克隆 reference 与 PPO 发现超参考策略是两个不同难度的任务;
- **C3 无 arm 恢复**:capture 大(135-233)全部来自极窄 denominator(§3)的长仓偏向;probability gap 与 deterministic behavior gap 基本不达标(如 B arm pgap -0.026/+0.100/-0.002)。C3 的 PPO 学到的是"无差别做多",不是成本选择性。

## 7. Supervised 对照(family 分开,U/W/B × 3 arms × 3 seeds,seeds 28401-28403)

label 来源:causal observation reference policy(逐族逐 rung 正确 reference;不读 latent oracle/future/episode id);train/eval 为不同 namespace 不同 pair 区间(held-out pairs 不进入训练)。

- **C1**:全 arm 可学(unscaled linear bal acc 0.897;三 arm 的 U/W/B MLP 均 ≥2/3 seeds learned);
- **C3**:全 arm 可学(unscaled linear 0.813;类平衡同过);
- **C2(Long label 率 2.16%)**:
  - unscaled:U 全 Flat(bal 0.5,long recall 0);**W 1/3、B 1/3**(bal 0.50/0.85/0.55 与 0.50/0.90/0.54)→ 未达 2/3;
  - fixed_precommitted:U 失败;**W 3/3(0.71/0.86/0.93,long recall 0.95-1.0)、B 3/3(0.71/0.86/0.94)**;
  - train_fitted:U 失败;**W 3/3(0.88/0.83/0.88)、B 3/3**;PR-AUC 0.15-0.38、ROC-AUC/校准/FPR/预测 Long 率全量记录于 `c2_class_imbalance_results.json`。

结论:**C2 的 representation 不是不可学——scaling + 类平衡控制下类平衡 MLP 三 seed 全部学会**;单一 unweighted seed 判定"C2 不可学"的 R1 结论被推翻;C2 不构成 Branch E。

BC arm 选择(预注册 A→B→C 顺序取第一个 learned):C1=unscaled,C3=unscaled,C2=fixed_precommitted。

## 8. BC:三 seed 全部真实执行(family 分开)

计划 3 seeds(28601/28602/28603)× 3 族 = 9 runs,**全部执行**(计划执行矩阵 `bc: {c1:True, c2:True, c3:True}`,不多不少);每族独立训练(不混族,数据收集遇异族 episode 即 fail closed);actor 克隆用 train-label 逆频率加权 CE(权重只来自 BC train 标签);critic 全程不动(前后哈希相等);BC 权重经 `bc_init_state` 载入 runner(`actor_import_verified` 9/9);held-out 为独立 namespace + 独立 pair 区间(256+slot×32)。

每 seed 记录 BC 前/后 actor 哈希、BC 训练曲线、BC 后与 fine-tune 后的 held-out balanced accuracy / long recall / precision / behavior gap / 概率 gap / family-aware capture / KL / entropy / value 诊断。

| family | BC 学会(bal acc) | fine-tune 后 | drop | retained/destroyed |
|---|---|---|---|---|
| C1(unscaled) | 3/3(0.896-0.898) | 0.898 / 0.500 / 0.500 | 0.000 / 0.396 / 0.396 | retained 1,destroyed 2 → **destroyed 2/3** |
| C2(fixed) | 3/3(0.844-0.894) | 0.502 / 0.425 / 0.437 | 0.356-0.457 | destroyed 3/3 |
| C3(unscaled) | 3/3(0.866-0.923) | 0.425 / 0.477 / 0.620 | 0.246-0.498 | destroyed 3/3 |

细节值得记录:C2 的 BC 克隆被 fine-tune 摧毁后,策略概率分离转为正(0.22-0.23)且 capture 8.8-13.0——即 fine-tune 离开 reference 克隆、转向 §6 的超参考行为,与 C2 scratch=A 自洽。C1 seed28601 是唯一 retained(drop 恰为 0.0),另两 seed 下降 0.396 → 按 ≥2/3 规则判 destroyed。

## 9. Probability dynamics checkpoints:全部真实存在且非空

计划 schedule(机械换算到 bank 边界,ceil 到 16/8 的倍数):scratch 每 run 6 个(ep0/ep16/ep32/ep80/ep144/ep288 = initial/5.6%/11%/28%/50%/100%),BC 每 run 6 个(after_bc_before_ppo/ep8/ep16/ep24/ep48/ep96)。

- 产出:**scratch 27×6 + BC 9×6 = 216 个 checkpoint 文件**(scratch 命令内的 162 个经 `checkpoint_integrity.json` 全量哈希重算验证;BC 的 54 个经 `bc_execution_integrity.json` 验证);每个记录 policy/actor/critic/optimizer sha256;
- **每个 checkpoint 可重新加载**(`load_r2_checkpoint` 载入后重算哈希一致)并完成评估:deterministic/stochastic action 率、P(Long)、logit gap、entropy、value prediction(逐 latent 类)、family behavior gap、family-aware capture —— `policy_probability_dynamics.json` 非空(pass=True),BC 的 after_bc checkpoint 存在(哈希等于 BC 载体模型);
- 任何 checkpoint 缺失即 FAIL:27+9 个 run 的 `verify_expected` 全部 PASS,零 extra tag。

**分离形成/失去的阶段**:

- C1-B(seed28501):pgap 从 ep0 的 -0.001 → **ep16 即 0.125** → ep32 0.184 → ep144 0.250 → ep288 0.192:分离在训练早期(约 1/18 预算)形成后保持;
- C1-C:同型(ep16 0.125 → ep80 0.266);
- C2-A(seed28501):ep0-ep32 恒 0,ep80 才 0.013,**ep288 升至 0.204**:晚期形成(探索期长);
- C3-C:全程 ±0.04 内震荡,从不形成;
- BC(unscaled C1/C3):after_bc 的 pgap ≈ 0.0003-0.0006,与 held-out 克隆精度 0.87-0.92 并存 —— 见 §12 已知限制。

## 10. PPO surrogate gradient:真实、可验证

**插桩**(`DiagnosedPPO2.train()`):SB3 2.9.0 `PPO.train()` 的忠实副本 + 在真实 `loss.backward()` 之后、`clip_grad_norm_`/`optimizer.step()` 之前记录参数 `.grad`:actor/critic 总范数、policy/value 第一层逐输入列平均 |grad|(采样)、action/value head 范数、pre-clip 总范数(clip 函数返回值)与 post-clip 总范数(重算);每个 minibatch 的 surrogate 分量(policy/value/entropy loss、ratio 统计、clip_fraction、approx_kl、归一化前后 advantage 分布)全部绑定 `{update_index, minibatch_index, epoch, minibatch_of_update, env_step}`。首个 minibatch 的张量与 pre-update 权重被克隆保存,供等价测试手工复算。

**等价验证**(`ppo_surrogate_gradient_validation.json`,12/12 checks PASS):同 seed 重建模型(初始权重逐位一致)→ 载入捕获的 pre-update 权重 → 按 SB3 语义(逐 minibatch advantage 归一化 / ratio / clipped surrogate / entropy / vf 系数)手工重建 loss 并 backward → 与插桩记录对比:policy_loss / value_loss / entropy_loss / total_loss / actor 梯度范数 / critic 梯度范数 / 第一层逐列全部数值一致(相对容差内);clip 语义(post ≤ pre×(1+1e-6)+1e-9)与 minibatch 总数 = updates × epochs × minibatches 全部吻合。`test_ppo262_r2_gradients.py` 在测试层重复该等价性,并断言 R1 的 `-log_prob(action)` 行为模仿式探针不得再现。

实测首 minibatch 数值:actor 范数 0.210、critic 0.247、pre=post=0.324(低于 max_grad_norm 0.5,初始对称策略 policy_loss≈0 符合预期);27 个 scratch run 的逐 run 梯度摘要(含第一层逐输入列)记录于 `ppo_update_diagnostics.json`,rollout 级 value/advantage 诊断(含 explained variance、逐 action advantage)记录于 `value_advantage_diagnostics.json`。

## 11. Branch 判定与全局路线(按 family,无跨族拼接)

单族 recovery 的四类证据(capture / probability gap / deterministic behavior gap / reference gap 有效性)由 `family_recovery_evidence` 强制同族(异族输入抛 `CrossFamilyEvidenceError`;测试覆盖"C1 capture + C3 probability gap"被拒)。分支判定顺序(预注册):A→B→E→C→D→F。

- **C1 = B**:Arm A 不满足(3/3 坍塌),Arm B 与 C 均 3/3 恢复;
- **C2 = A**:Arm A 2/3 seeds 满足四条件;
- **C3 = D**:scratch 全 arm 不满足(supervised 可学所以非 E;BC 3/3 学会且 3/3 被 fine-tune 摧毁);
- 无任何族落入 F → `family_branch_decision.pass = True`。

**全局路线**(§18 优先级):存在 B → **推荐 Stage 2.6.1 Repair R3:重新冻结 preprocessing contract(含 reference/baseline 适配、新 calibration/robustness/qualification/final qualification),不得直接 official 2.6.2**。同时 C3=D 的证据表明 preprocessing 修复后仍需面对 PPO update 层问题(advantage normalization / critic stabilization / smaller updates / KL control / actor-critic LR 分离 / cost transition dynamics),建议作为 R3 之后的 PPO Optimization Repair 议题;C2 的"超参考恢复"提示 R3 重审时也应复核 reference 在 C2 上的 gap 幅度(denominator 0.018-0.033 偏窄)。

- 哪些 family 需要 scaling:**C1(scratch 层必须)、C2(监督层必须;scratch 层非必须)**;C3 不需要 scaling(C3 的问题不在预处理);
- 哪些 family 需要 PPO optimization:**C3(D 分支)**;
- 仍然 inconclusive 的 family:无;
- official final namespace:未解锁/未生成/未暴露。

## 12. 语义 validator(非文件存在性检查)

`diagnostic_semantic_validation.json`:**60 项检查全部通过**。覆盖:计划执行矩阵(scratch/bc/supervised 的实际 seeds 与计划完全一致,不多不少;预算与计划一致;BC 对可学族全部执行)、R1 artifacts 哈希重算未改动、family evaluator 语义(scratch 结果内全部 cell 的 reference identity 正确、invalid denominator 无 capture)、arm 语义(B 记录为 fixed 且常数来自 plan;C 仅 fit 训练 bank 且 position identity;B 的 position slot identity)、概率分族采样充足、checkpoint 数量与哈希(逐 run)、BC 语义(critic 未动、actor 导入验证)、梯度语义(等价通过、identity 齐全)、C2 PR/ROC-AUC 存在、branch 单族证据、official final plan 未生成。`plan_execution_matrix.json` 单独落盘。

## 13. 测试与回归

新增 9 个测试文件(`test_ppo262_r2_*.py`,58 项):family-aware evaluator(sentinel/identity/single-rejects-mixed/negative-denominator/跨族拼接拒绝/required baselines)、namespace 隔离(含对被废止 diag262r2_* 的 seed 隔离)、scaling arms(B 构造器无数据入参/常数机械推导/A bitwise/C 只 fit 训练 bank)、checkpoints(schedule 覆盖/哈希可重算/可加载/probability 非空/after_bc 存在且非随机 ep0)、PPO 梯度(单 minibatch 等价/归一化语义/clip 语义/entropy 项/identity 齐全/模仿式探针禁用)、BC(三 seed 合同/fail-closed 分族/critic 不动/导入哈希往返/retention 规则)、C2 不平衡(W/B 学会稀有类/balanced minibatch 各半/权重只来自 train/PR-AUC 与 long recall 存在)、family branch(独立判定/跨族拒绝/任一 F 全局 FAIL/路线矩阵)、preservation(R1 哈希不变/input lock/final namespace 未消费)。

回归(非 official closure,未运行 full-cold):targeted(r2)→ `tests/route_c_stage2_6_2`(全)→ affected `tests/route_c_stage2_6_1` → Route C 代表(`route_c_stage2_6_0`、`route_c_stage2_6_0j`)全绿(计数见 §15)。本轮零修改 `stage2_6_1/`、`stage2_6_0/`、`rl_platform/`(input lock 内容寻址证明);本轮未触碰 reward/fee/action/执行时序。

## 14. Artifacts 清单(全部非空,`repair2/`)

baseline_integrity / historical_diagnostic_binding / route_c_integrity / stage261_readonly / diagnostic_plan(+digest)/ diagnostic_namespace_integrity / fixed_scaling_contract / family_evaluator_validation / reference_identity_matrix / reference_gap_validity / supervised_control_plan / supervised_control_results / c2_class_imbalance_results / scratch_ppo_plan / scratch_ppo_results / preprocessing_pairing_integrity / checkpoint_integrity / policy_probability_dynamics / ppo_surrogate_gradient_validation / ppo_update_diagnostics / value_advantage_diagnostics / cost_decomposition / bc_plan / bc_results_c1 / bc_results_c2 / bc_results_c3 / bc_execution_integrity / family_branch_decision / global_route_decision / plan_execution_matrix / diagnostic_semantic_validation / regression_summary。模型:`models/ppo262/repair2/` 36 个 run 目录、216 个 checkpoint(.pt + 哈希记录)。

## 15. 数字与验收状态

- targeted(r2,9 文件):53 passed
- `tests/route_c_stage2_6_2`(全套):149 passed(R1 期 96 + 本轮新增 53)
- `tests/route_c_stage2_6_1`(affected):106 passed
- Route C 代表(`route_c_stage2_6_0` + `route_c_stage2_6_0j`):276 passed
- 合计 584 项全绿;`diagnostic_semantic_validation.pass = True`(60 检查);`regression_summary.repair2_diagnostics_pass = True`
- **Stage 2.6.2 official 状态:FAIL(不变)**。本轮为诊断轮;只有未来使用全新 official iteration、全新 official seeds、完整 probes/core/final 才可能改变。

## 16. 已知限制(如实登记,不影响本轮判定)

1. capture > 1(C2 ≈ 11-12、C3 ≈ 130-230)来自窄 denominator(C2 0.018-0.033、C3 0.002-0.008);预注册规则只要求 capture > 0,数值解释需配合 denominator 幅度阅读。C2 的恢复证据由概率分离与门控行为差同时支撑,C3 则被这两个判据正确排除;
2. BC 后的概率分离(pgap ≈ 0.0003-0.0017)与 held-out 克隆精度(0.87-0.92)并存:克隆精度在 reference 轨迹观测(含仓位历史)上度量,概率探针在常平仓轨迹上度量;C1 reference 的 Long 决策本身并不与 latent seg_state 一一对应(reference 基于 ma-ratio 阈值)。两个口径都是真实测量,本轮不裁决孰是;
3. 诊断规模预算(82,656 steps/run)远小于 official core(183,680 steps/replicate × 结构化课程);结论限定在诊断语料;
4. gradient 等价验证在首个 minibatch 上做(权重未更新前);对训练中期 minibatch 的等价性由"忠实副本 + 同一代码路径"结构性保证;
5. WSL 环境的 systemd 用户会话失败导致 /tmp 按会话隔离:两轮废弃锁的中间日志未持久化(不影响任何 artifact;scratch/BC 正式日志已落 `logs/`)。

## 17. 结论

- **Repair R2 Diagnostics: PASS**(诊断基础设施闭合;全部预注册对照真实执行;每族得到可信分支)
- C1 = B / C2 = A / C3 = D;无 F;无跨族证据
- 推荐路线:**Stage 2.6.1 Repair R3**(重新冻结 preprocessing 并重新 qualification)→ 其后针对 C3 的 PPO Optimization Repair
- 不进入 Stage 2.6.2 s262_r1 / 2.6.3;official final namespace 未消费
