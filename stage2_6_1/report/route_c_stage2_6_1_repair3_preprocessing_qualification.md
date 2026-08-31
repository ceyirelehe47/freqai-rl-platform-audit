# 阶段 2.6.1 Repair R3:Production 预处理合同与课程重新 Qualification

- **判定:FAIL(诚实 FAIL)**
- 失败层级:curriculum robustness gate(C1/C3 的 D3 余量在 pair-cluster 口径下不足)
- preprocessing 合同本身:**全部资格证据 PASS**(production 数值等价、统一 fit/freeze、特征存活、observation 合同、reference 逐 bar 等价、conditioning、supervised、PPO smoke)
- final qualification:**未执行**(§22 停止规则;qualification_r3 / preprocess_fit_qualification_r3 从未被访问)
- Baseline:`1b47db474461a82b07c6b863894b7f9c4b4dce98`(Stage 2.6.2 Repair R2 Diagnostics PASS checkpoint)
- Vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean,未动)
- 迭代身份:`r3`;全部产物写入 `stage2_6_1/artifacts/repair3/`

---

## 1. 为什么需要 R3?

Stage 2.6.2 Repair R2 诊断确认:C1 = Branch B —— **unscaled scratch PPO 三 seed 全部失败**(坍塌 Always Flat),而 fixed precommitted scaling 与 train-fitted scaling 均恢复;C2 = Branch A(unscaled 2/3 seeds 恢复);C3 = Branch D(BC actor 可学,但 PPO fine-tune 在 3/3 seeds 摧毁该能力)。结论:scaling 是 C1 的正式合同 blocker,但不是 C3 的充分解法。

R2 时代的课程 observation 是 causal-unscaled(`curriculum_preprocessing_boundary` 登记的 domain gap)。R3 的任务:把 preprocessing 从 2.6.2 diagnostic arm 升级为阶段 2.6.1 正式、版本化、可序列化、可资格审查的输入合同(`RouteCFeaturePreprocessing-v1`),在该合同下重新完成 C1/C2/C3 calibration、robustness gate 与 120-pair final qualification。

## 2. C1 Branch B / C2 Branch A / C3 Branch D 意味着什么?

- **C1 Branch B**:输入尺度支配(82.9 倍特征尺度失衡)使 PPO 优化在 unscaled 输入上不可学——这是**表示问题**(输入合同),R3 的直接目标;
- **C2 Branch A**:unscaled 下 PPO 大部分可恢复——C2 对 scaling 不敏感,是对照;
- **C3 Branch D**:监督/BC 可学但 PPO fine-tune 摧毁能力——这是**优化问题**(critic/advantage/update dynamics),R3 不解决、仍开放。

## 3. pinned FreqAI 真实 preprocessing 是什么?(WP-A 审计)

从 pinned vendor 源码与当前正式 Route C runtime config(`experiments/freqai_rl_stage2_5_2a/runtime/config_stage252a-rc-e9b373b3c9_smoke-reload.json`,sha256 记录于 `production_preprocessing_audit.json`)重新确认,**不依赖 R2 报告的转述**:

- **pipeline 构建**:`IFreqaiModel.define_data_pipeline`(freqai_interface.py:558-587)= `datasieve.Pipeline([("const", ds.VarianceThreshold(threshold=0)), ("scaler", SKLearnWrapper(MinMaxScaler(feature_range=(-1, 1))))])`;
- config 中 PCA=false、SVM=false、DI_threshold=0、无 DBSCAN、noise=0 → pipeline **恰好两步**,无额外步骤;
- `drop_ohlc_from_features = false`(rl_config);`add_state_info = false`;`conv_width = 1`;
- **fit 时机**:`BaseReinforcementLearningModel.train`(:125-138):`feature_pipeline.fit_transform(dd["train_features"])` —— fit 于训练窗 train_features(8 列,列序=策略赋值序);
- **env 收到 transform 后数据**(`set_train_and_eval_environments(df=scaled)`);eval/test 走 `feature_pipeline.transform`;
- **VarianceThreshold**:sklearn 语义 threshold=0 只删常数列;`get_support()` mask,retained 列保持原列序;行为探测确认删常数列、保留非常数列;
- **MinMaxScaler 不 clip**:超出 train min/max 的 eval 值线性外推(探测:fit range [0,3] 的列,eval=10 → 输出 5.67);
- **dtype**:pandas → numpy float64 → transform → float64 DataFrame;
- **position slot**:不在 pipeline 内;由 `AlignedLongFlatEnv._observation` 在 preprocessing 之后追加为第 9 维(0/1 原值,不缩放)。

## 4. R3 是否直接复用了 production pipeline?如何证明等价?

**直接复用**。`build_vendor_feature_pipeline()` 以未绑定方式调用 vendor `IFreqaiModel.define_data_pipeline` 代码本体(shim 只提供来自真实 config 的 freqai_info)——R3 没有重实现任何 scaler。

`numerical_equivalence_report`(fit 于正式 fit bank 13,824 行)对拍独立构造的 vendor pipeline,全部逐位一致:

| 检查 | 结果 |
|---|---|
| train transform 逐位 | ✅ |
| 独立 eval transform 逐位 | ✅ |
| retained mask / 列序 | ✅ |
| zero-variance 行为(vendor 删常数列;正式 fit 无常数列) | ✅ |
| out-of-range 线性外推(不 clip) | ✅ |
| float64 dtype | ✅ |
| serialize → reload → transform 逐位(state hash 相等) | ✅ |
| shuffled rows → 同 state hash / 同 transform | ✅ |

## 5. 正式合同 RouteCFeaturePreprocessing-v1(§4/§7/§8/§9/§10/§11/§12)

- **版本**:`RouteCFeaturePreprocessing-v1`;state 格式 `r3-route-c-feature-preprocessing-state-v1`;合同 digest `r3pc-…`(实现身份,进 plan);
- **fit scope**:offline training-corpus fit → frozen deployment transform。一个训练 run → 一个完整 training episode multiset → **一个统一 preprocessor**,C1/C2/C3 全部共享;fit 于 multiset 全部 policy-visible feature rows;**禁止** episode 内/family 切换/eval 时 refit/online normalization;
- **feature input / retained**:8 个 production 列(`%-ret-1`…`%-raw_close`),**8/8 全部存活**(VarianceThreshold 在两个 fit bank + final 预检上零删除);observation dim 恒 9;
- **position handling**:不参与 fit、不缩放、不 center、不 clip,env 追加第 9 维原值(自动测试验证 0/1 identity);
- **observation space**:Box(-10, 10) float32(生产 env 冻结 layout);production 不 clip → 允许越界语义;containment 在 fit bank/calibration/holdout 全 corpus 实测(最大越界率 0.043%,全部 |obs| < 10,dim=9,finite,position 0/1);
- **serialization**:纯参数 JSON(mask、data_min/max、scale、min 等,无 pickle 对象);reload 后 transform 逐位一致;`state_hash` = canonical JSON sha256(qualification preprocessor state hash 进 plan 与 PPO model manifest 绑定接口);
- **统一 fit 防泄漏边界**:允许读完整训练 manifest;禁止读 dev/final/qualification corpus、latent truth、未来数据——fit bank namespace(`preprocess_fit_*_r3`)与 evaluation namespace 完全隔离,且 fit bank 只用于拟合、不进入任何 qualification metric。

**staged/mixed 共享同一 state**:fit 对 manifest 行序不敏感(MinMax/VT 为置换不变统计);shuffled rows → 同 state hash(回归测试);staged 与 mixed 相同 multiset 必得相同 fitted state——这是未来课程顺序比较的必要条件,R3 已冻结并测试。

## 6. fit bank 具体是什么?为什么不构成 eval leakage?

- 每个 fit bank = 3 family × 4 rung × 4 pairs × A/B = 96 episodes(约 27,648 feature rows),namespace 分别为 `preprocess_fit_calibration_r3` / `preprocess_fit_holdout_r3`(`preprocess_fit_qualification_r3` 本轮因 gate FAIL 从未访问);
- 覆盖 §17 要求的 C1/C2/C3 × D0-D3 × A/B × 每 family/rung 4 pairs;
- **不构成 leakage 的理由**:fit 允许使用完整训练 manifest(offline corpus fit 协议);evaluation corpus(calibration_r3/holdout_r3)与 fit bank 的 seed namespace 不相交(namespace integrity artifact 数值验证:22 个 namespace × 3 family × 4 rung × 50 pair × 5 attempt 枚举,零碰撞);fit bank 不参与任何 metric 计算。

## 7. 为什么不能 per-family fit?

未来 staged/mixed PPO 必须在**同一个 policy** 中处理 C1/C2/C3——三个 family 各自一个 scaler 会让 policy 输入分布随课程阶段漂移,课程顺序比较失效。R3 冻结统一 preprocessor(单 fit state 覆盖三族),并以 `test_single_preprocessor_shared_across_families` / `test_staged_mixed_same_multiset_same_state` 强制。

## 8. Reference 语义(§13/§14,方式 B inverse-transform wrapper)

`PreprocessingAwarePolicy`:reference/baseline 只接收 transformed policy-visible observation + frozen preprocessor state;先把前 8 维仿射逆变换回 raw 特征语义再运行原 policy。不访问 raw env side channel / latent / future / episode 元数据。

**强制等价验证**(fit bank 12 episode 全策略对,进 final 也将复验):

- raw reference action == preprocessing-aware reference action **逐 bar** ✅(C1/C2/C3 全部策略:c1_reference、c1_shortcut、c2_reference、c2_local_only、c2_single_context×2、c3_reference、c3_cost_ignorant)
- raw net return == preprocessed net return(逐位相等)✅

Always Flat / Always Long 不读 observation,不受影响;oracle 走 sidecar(仅 world diagnostic)。affine inverse 精度 < 1e-12(测试验证)。

## 9. Conditioning(§19,§36-16)

| 指标 | unscaled | R3 scaled | gate |
|---|---|---|---|
| raw OHLC 随机第一层贡献份额 | 0.636 | **0.505**(均匀=0.5) | ≤0.60 ✅ |
| Tanh 饱和率(随机第一层) | 0.0000 | 0.0000 | ≤0.05 ✅ |
| eval out-of-fit-range rate(逐列最大) | — | 0.00043 | ≤0.10 ✅ |
| 近零方差(scaled) | — | 无 | 禁止 ✅ |

(注:unscaled 份额 0.636 是课程语料上的实测;2.6.2 诊断的 ~98% 出自 82.9 倍尺度失衡的 probe 语料。R3 合同下尺度支配已消除——小尺度特征不再被数量级淹没。)

## 10. Supervised learnability(§20,§36-17)

三族 × 3 model seeds × pair-level split(每 rung 前 6 pair 训练 / 后 4 pair held-out,无 pair 跨集泄漏);MLP [128,128] Tanh(与 PPO actor 同量级);C1/C3 的 Long 率 7-8%、C2 4.7%,三族统一 W(class-weighted CE)/B(balanced minibatch)为 gate 控制(262 R2 family-aware 先例),U(unweighted)仅诊断:

| family | W/B gated | held-out balanced acc | behavior gap(TPR−FPR) |
|---|---|---|---|
| C1 | 6/6 | 0.868-0.877 | 0.736-0.755 |
| C2 | 6/6 | 0.850-0.954 | 0.700-0.908 |
| C3 | 6/6 | 0.798-0.831 | 0.597-0.662 |

**全部 ≥2/3 seeds: bacc ≥ 0.60 且 gap ≥ 0.20** ✅。U 控制三族全坍塌(bacc 0.500)——纯类不平衡训练控制现象,非表示不可学(ROC-AUC 0.73-0.96 显示排序完全可学)。

诚实记录(calibration 阶段内、plan lock 前的两处 gate 实现修正,governance_waiver.json 全文登记):(a) behavior_gap 初版误用 accuracy−majority 定义(类不平衡下结构性不可达),对齐 262 R2 预注册先例 TPR−FPR;阈值 0.60/0.20 全程未调;(b) C1/C3 初版只跑 U 控制,补齐 W/B(与 C2 同级)。(c) curriculum gate 的 margin 条件统计单元由跨 rung 混合改为 (rung, pair) 分层(跨 rung 同 index pair 是不同 episode);**两版实现下 C1/C3 的 FAIL 判定相同**。

## 11. Pair-cluster statistical contract(§23,§36-18)

一个 A/B pair = 一个 cluster。全部 mean/SE/adjacent-rung gap/D3 margin/reference-vs-baseline margin 使用 pair 级聚合(A/B 均值为单一 cluster 样本)。episode 假独立被测试显式拒绝(构造 pair 内高相关数据,假独立口径低估 SE ≥1.3 倍,实测 ~1.41=√2)。§24 的 margin 报告:R−B、pair-cluster SE、gap/SE。

## 12. Calibration 与两个 gate 的结果(§22,§36-19)

语料:calibration_r3 / calibration_holdout_r3 各 3 family × 4 rung × 10 pairs × A/B;stress_r3 12 pairs/rung;C2 双诊断(calibration_r3+holdout)PASS。

难度梯子(pair-cluster 口径,reference − max(0, always_long)):

| family | corpus | D0 | D1 | D2 | D3 | integrity |
|---|---|---|---|---|---|---|
| C1 | main | 0.1962 | 0.0992 | 0.0796 | **0.0030** | 1.0 |
| C1 | holdout | 0.2035 | 0.1052 | 0.0778 | **0.0023** | 1.0 |
| C2 | main | 0.0285 | 0.0200 | 0.0133 | 0.0050 | 1.0 |
| C2 | holdout | 0.0310 | 0.0209 | 0.0126 | 0.0055 | 1.0 |
| C3 | main | 0.0597 | 0.0373 | 0.0208 | 0.0072 | 1.0 |
| C3 | holdout | 0.0544 | 0.0428 | 0.0222 | **−0.0017** | 1.0 |

- **preprocessing robustness gate:PASS**(等价 + robustness checks + conditioning 全过);
- **curriculum robustness gate:FAIL**:
  - **C1**:排序 D0>D1>D2>D3 ✅、gaps 全部 ≥ κ×pair-SE ✅、D3>0 ✅,但 **D3 余量不足**:双语料合并 D3 mean = 0.00265 < κ×SE = 0.00694;D3 的 reference margin(main 0.00295 / holdout 0.00234)同样 < κ×SE(0.0096/0.0105);
  - **C2:全过**(D3 mean 0.00527 ≥ κ×SE 0.00174);
  - **C3**:main 全过,但 **holdout D3 翻负**(reference −0.00165 < always_flat 0,reference 未压过必胜基线)且 D3 双语料合并 mean 0.00279 < κ×SE 0.00320;D3 reference margin main −0.0097 / holdout −0.0131(负)。

**根因分析**(诚实归属):reference 逐 bar 等价已证——R3 下 reference/基线/oracle 的行为与收益和 raw 合同完全一致;generator/rung 参数/评估配置未动。因此该 FAIL **不是 preprocessing 合同造成的**,而是 §23 pair-cluster 统计口径修复(去掉 R2 的 episode 假独立 SE 低估)+ 全新 R3 seed 语料的共同结果。与 R2 语料对比:C1 D3 在 calibration_r2 上为 0.0136/0.0179(R2 gate PASS,但其 SE 用 episode 假独立口径),R3 语料上仅 0.0030/0.0023——同分布新抽样的波动幅度(差 ~0.013 ≈ 1.3×pair-SE)表明 **C1/C3 的 D3 设计余量本就与采样不确定性同量级**;R2 的 PASS 在诚实口径下余量并不稳健。这正是任务书 §24 要求修复口径后必须显式检验的条件。

## 13. §22 停止规则的执行

curriculum robustness gate FAIL 后:

- **未生成** final qualification plan 与 plan digest;
- **未访问** `preprocess_fit_qualification_r3` 与 `qualification_r3`(完整 guard:plan+digest 重算+gate 四要素,锁前派生被拒,有测试);
- 未调整任何参数/kappa/阈值后重跑(禁止"调整参数后继续称为同一次 R3");
- 证据完整保存于 `stage2_6_1/artifacts/repair3/`。

## 14. PPO smoke(§29)

256-step PPO plumbing smoke(`ppo_smoke_r3` namespace,calibration preprocessor):fit state 加载 ✅、transformed obs shape(9,)/float32 ✅、declared space contains ✅、model save/load deterministic ✅、reset/step/action 路径 ✅、reward 有限/无 NaN/无 crash ✅。未用于任何选择决策。

## 15. 历史技术债修复(§32)

- **seed guard**:qualification_r3 守卫完整验证 plan 存在 + digest 文件存在 + digest 重算一致 + robustness gate=true(四要素测试:缺 plan/缺 digest/gate=false/digest 篡改各自拒绝);
- **目录统一**:CLI output 目录与 lock-marker 目录统一(默认同为 `artifacts/route_c_stage2_6_1_repair3`),默认命令自包含;
- **iteration 字段**:R3 产物全部 `r3`,无 r2/diag262r2 残留(测试);
- **重复 seed derivation 删除**:`_derive261_seed_raw` 的双重定义(第一个为递归死代码)已合并为单一实现(测试强制 count==1);
- **pair uncertainty**:全部改 cluster 口径(见 §11)。

以上修复均有回归测试。

## 16. 回归

- targeted(quick):tests/route_c_stage2_6_1 **153 passed / 0 failed**(含 R2 协议 19 项无回归);
- affected:改动文件(curriculum261_api.py + 新增 curriculum261_r3_*)按规则命中 route_c_stage2_6_1(+ 2.6.2 adapter integration)——affected 运行 exit 0;
- **full-cold:未执行**(§37 前置条件"两个 gate PASS + final qualification PASS"不满足;FAIL 轮按停止规则不宣布 full-cold PASS)。

## 17. Route C / generator / vendor 未修改

六项冻结合同(RouteCEnvCore-v1.0.0 / ObservationSpec-v1 / BinaryLongFlatAction-v1 / NetLogEquityReward-v1 / MarketOpenCausalExecution-v1 / TerminalLiquidation-v1)、fee/slippage/tick/reward/ledger/action/execution、RouteCStrategy.feature_engineering_standard、C1/C2/C3 generator 与 rung 参数、pair construction 全部未动;vendor pin clean。新增的 preprocessing 是 RouteCStrategy 输出与 env/policy 输入之间的独立合同,ObservationSpec-v1 的名称与含义未变。

## 18. §36 逐问速答(未在上文展开的)

- **11.所有 8 features 是否存活?** 是,两个 fit bank 8/8 全存活,retained 序=输入序,observation dim 恒 9;
- **position 如何处理?** 见 §5;**observation space 如何定义?** Box(-10,10) float32 + 不 clip 语义 + 实测 containment;
- **eval 超出 train min/max 时怎么处理?** 与 production 完全一致:线性外推(实测越界率 ≤0.043%,无截断);
- **raw/transformed reference 是否逐 bar 一致?** 是(§8);**C1/C2/C3 supervised 是否都可学?** 是(§10);**C2 类别失衡如何控制?** W+B 双控制(§10);
- **pair-cluster uncertainty 如何计算?** (rung,pair) 分层 pair 聚合 + κ×pair-SE + bootstrap 接口;
- **final fit bank 是否在 lock 后首次生成?** 本轮未到该步骤(gate FAIL 先停止);
- **final 120 pairs 结果?** 未执行(§13);
- **preprocessing state hash?** calibration main `r3pre-914ab89ea2c4ac…`(全 64 位见 artifacts),holdout `r3pre-4b11ce31971776…`(两 fit bank state 不同,transform 列级最大差 0.037,稳定性检查通过);
- **qualification plan digest?** 未生成(合法:禁止);
- **C3 Branch D 是否仍开放?** **是**——R3 未触碰 PPO optimization;即使 R3 将来 PASS 也不能声称 C3 PPO 已解决;
- **Stage 2.6.2 正式状态?** 仍为 **FAIL**(未变);
- **Stage 2.6.1 R2 旧结论?** 保留为 causal-unscaled observation 合同下的历史 PASS。

## 19. 已知局限

1. C1/C3 D3 余量不足的结论基于 10 pairs/rung/corpus 的抽样;是否为结构性(需要 rung 参数设计调整)需要新设计决策,不在本轮擅自处理(§38 禁止修改 generator/rung 参数);
2. R3 的 C1 ladder D0-D2 与 gaps 全部健康,唯一缺口在 D3 绝对余量——说明问题特定于最细难度档,不是合同层面的全面失效;
3. supervised gate 的 W/B 控制与 behavior_gap 定义修正在 calibration 阶段内完成(plan lock 前),已如实登记于 governance_waiver;若未来轮次引用本轮 supervised 数字需注意该语境。

## 20. 下一步建议(不自行执行)

R3 FAIL 的直接原因是**统计口径修复暴露的课程 D3 余量问题**,而非 preprocessing 合同缺陷。建议下一步任选其一(需要新任务书决策):

- **路线 a(课程资格 repair)**:Stage 2.6.1 R4——先做 D3 rung 参数的统计功效分析(设计层面:要么增大 D3 margin 的构造性余量,要么以 pair-cluster 口径重新校准 rung 参数并预注册),再重跑 R3 式 qualification。注意这是 generator/rung 设计变更,按任务书属于"更大的设计 blocker",须显式授权;
- **路线 b(先利用已 PASS 的合同)**:preprocessing 合同的全部资格证据(等价/统一 fit/存活/reference 等价/conditioning/supervised/smoke)已经 PASS 且与课程 rung 参数无关——可先在新任务书中授权把 `RouteCFeaturePreprocessing-v1` 作为 2.6.2 的 preprocessing candidate(按 R2 报告"R3 若 PASS 则成为 2.6.2 candidate"的原意,此处需明确:合同资格已证,课程 D3 资格未过),再决定 C3 Branch D 的优化 repair 顺序;
- 无论哪条路线,**C3 PPO Branch D 仍开放**,不得自动进入 Stage 2.6.2 official。

## 21. 结论

**Stage 2.6.1 Repair R3 = FAIL(诚实 FAIL)。**

- Production preprocessing 合同资格:全部证据 PASS;
- Curriculum D3 资格(C1/C3):pair-cluster 口径下余量不足 → curriculum robustness gate FAIL → 按停止规则未执行 final qualification;
- Stage 2.6.2 official 状态:FAIL(未变);
- C3 PPO Branch D:仍开放。
