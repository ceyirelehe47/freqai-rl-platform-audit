# 阶段 2.6.1 Repair R10:Calibration 全链路闭环、Policy-Visible Reference 与 Clean Qualification(主报告)

- 结论:**FAIL(诚实 FAIL)**
- 启动基线:`ab260684df340f89443ce9827f8f733e3ede4320`(R9 诚实 FAIL checkpoint;父提交 `dfe646bb`(R8))
- Implementation freeze(Commit A):`e97c38d4f3ca4cf07d3acb2cc86b6aa161837f1b`
- Implementation freeze 修正(Commit A′,最终冻结点):`06e9b5beb4df564e51d27aae444f281843356809`
- 结果提交(Commit B):见仓库 log(本报告与 artifacts 所在提交)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / PYTHONPATH=src

## 0. 执行时间线(UTC)

| 时刻 | 事件 |
|---|---|
| 实现阶段 | 21 个 R10 模块 + 14 个测试文件;R10 测试 110 项全绿;R0-R9 回归 449 项全绿;262 回归 150 项全绿;preplan-smoke CLI 全链通过(工程 rehearsal `r10pr-23f9f15b`;full-pipeline rehearsal `r10rh-fd82ebfb`;§10 根因诊断 Branch B) |
| Commit A | `e97c38d4`(36 files,+13580) |
| audit 第一次 | 在 freeze 写入处 `NameError: write_r10_code_free`(拼写);零正式 namespace 访问、无 ledger、无 plan、freeze 未写成 → 治理判定见 §20.2;中断产物归档 `raw_logs/audit_interrupted/`(14 文件) |
| Commit A′ | `06e9b5b` 修复拼写 + freeze 写入前移至 cmd_audit 第一件事;新冻结点 |
| 正式 audit | PASS(freeze=06e9b5b;tree `r10src-9409ca07`;依赖 `r10dep-1cf0ea6a` 32 符号全过;delegation audit `r10sig-4b238b06` 全过;R9 abort 硬闸通过) |
| cue-audit | PASS(plan `r10ap-b57fa614`;p_contract=0.950429;MC 0.950369(diff 6.0e-5);once/attempts 零偏差、first_pass 50/50 逐位一致、500/500 attempt=0) |
| plan-roundtrip | 14/14 全过 |
| design plan 锁定 | `r10dp-e39575ba0cf66c5f229328ceefc4ef506ffbb3c191f15261f592ab5087dd6f9c` |
| design | PASS(semantic main/validation 双过;三候选唯 historical control 合格({15,20});机械选择 n=15;pack `r10pk-a475b997313b445ca25aa76f43e394bbe5bf493942942d39f7a6f6b75feb9314`) |
| calibrate | main/holdout fit 完成;robustness 电池 **PASS(reference equivalence main 修复确认:canonical 全等、98 个 legacy 差异全部 float32 边界解释、0 unexplained;routing 全过)**;随后 shared orchestration 的 supervised main 在 c3_cost/D0/pair1 抛 `PairGenerationError`(5 attempts 全部 too_few_distractors) |
| 17:29:54 | `r10_iteration_aborted.json` 写入(§21 硬规则);R10 永久结束;guard 生效;零 exposure |
| FAIL 路径 | cleanliness PASS;post_design(补录)+ post_abort 快照;回归 targeted 559 / 262 150 全绿;full-cold 未执行(final 未 PASS) |

## 1. R9 为什么 FAIL?

R9 CLI 调用 `supervised_learnability_run_r9(v2_main, pack)` 缺少必填位置参数 `namespace` → TypeError;按 R9 §18 硬规则(design plan 锁定后任何异常)诚实 FAIL。另外 R9 的 preprocessing_v2_requalification 已产生 `reference_equivalence_all=false`(只保存布尔值)。

## 2. R9 design 取得了哪些有效开发证据?

Cue Contract v2 全新 audit(p_contract=0.950435);160-block semantic main/validation 双 PASS;三候选完整评估;historical control 为唯一合格候选({10,15,20} 全合格);机械选择 n=10;independent marginal PASS;R9 parameter pack 生成(`r9pk-c3070b5b`)。R10 报告将其全部绑定于 `r9_abort_binding.json`(development evidence only)。

## 3. 为什么 R9 pack 不能直接成为正式输入?

规范 §2.1:R9 结果只能作为 development evidence;R10 必须在全新 namespace 重新完成同一 design。事实上 R10 重做结果不同(§24:R10 新语料下 historical control 的 n=10 gateP=0.8367 不合格,机械选出 n=15)——证明重做是实质要求而非形式。

## 4. supervised wrapper 的两个调用错误是什么?

① CLI 两参调用缺 `namespace`(TypeError 直接死因);② wrapper 内部 `_supervised_run(preproc_v2, pack, namespace, **kw)` 把 namespace 传进 R6 实现的第三位置参数——真实签名是 `(preproc_v2, pack, pairs_per_rung=10, namespace="calibration_r6", train_pair_limit=6)`,即 namespace 值被当作 pairs_per_rung 使用(即使补上调用参数也必然错传)。

## 5. R10 如何禁止位置参数错传?

`supervised_learnability_run_r10(preproc_v2, pack, *, namespace, pairs_per_rung, train_pair_limit, model_seeds, training_config)` —— 全部 keyword-only;签名层使第三位置参数不可能。所有 R6 委托显式关键字(`pairs_per_rung=`, `n_blocks=`, `parameter_pack_identity=` 等)。live signature audit(`r10sig-4b238b06`,覆盖 §7.3 全部九类 runner:wrapper/underlying 签名、keyword-only 集合、forwarded keywords、source sha256)+ AST 检查(禁止第三位置参数、CLI 必须显式 `namespace=`)在 audit 阶段全过;测试含负向(位置传 namespace 立即 TypeError、R9 形态被 AST 抓出)。

## 6. supervised labels 过去为什么不合法?

R6/R9 的 `_collect_supervised_dataset_r6` 把 raw reference policy 直接运行在 scaled episode 上(`run_policy_episode(ref, scaled_ep, ...)`)——raw threshold(按 raw feature 量级设计)直接作用于 MinMax-scaled 特征;标签既非合法 raw 语义也非合法 scaled 语义。

## 7. R10 label 如何从 causal reference 与 scaled input 对齐?

PolicyVisibleSupervisedLabel-v1(`r10_labels.py`):双 env 同步 replay —— canonical env(`canonical_episode`:特征列 = inverse(float32(transform(raw))),价格列原始数据)供 reference 决策;scaled env(生产 transform + env float32 投影)产出 dataset observation;同一 action 序列驱动两 env → position 逐位一致;labels = canonical reference 的逐步 causal action;§8.2 对齐验证(dataset obs==scaled replay obs、position 一致、label==canonical action、与正式评估器 action 序列一致)。pair-identity split(A/B 同 pair 同侧)。gate 用 W/B 控制、U 诊断。

## 8. main/holdout 过去如何错用 preprocessor?

R9 cmd_calibrate 三处 holdout 评估错传 v2_main:`run_calibration_corpus_c13_r9(v2_main, pack, "calibration_holdout_r9")`(L1021)、`run_c2_matched_corpus_r9(v2_main, ..., "calibration_holdout_r9", ...)`(L1048)、`run_c2_independent_corpus_r9(v2_main, ..., "c2_independent_holdout_r9")`(L1069);equiv 检查只用 v2_main。holdout bundle 从未真正服务任何评估。

## 9. R10 routing 如何 fail closed?

`R10BundleRouting`(frozen dataclass;role/fit namespace/三层 hash);权威映射 `calibration_r10→main`、`calibration_holdout_r10→holdout`、`qualification_r10→final`(preplan 表独立);`build_routing_r10` 拒绝 role↔namespace 交叉/未知 fit namespace/bundle hash 不符;`require_eval_routing_r10` 在返回 bundle 前完成校验(生成第一条评估结果前失败);routing matrix 全程落盘(`bundle_routing_validation.json`,calibrate 阶段 all_pass=True)。负向测试:swap、final 撞 main/holdout、hash mismatch、provenance mismatch 全部拒绝。

## 10. R9 reference-equivalence 具体有哪些 mismatch?

R9 只落盘了布尔值(72 episodes 全部记录丢失)。R10 在 `reference_diagnostic_main_r10` 诊断重现:legacy(wrapped-on-scaled vs raw)共 **98 个 action 差异**(诊断集 33 个;calibrate 正式 main 电池 98 个),每个带 §10.2 全字段(family/rung/pair/side/policy/timestep/raw_action/wrapped_action/net returns/raw_obs float32/scaled float64+float32/inverse obs/逐特征重建误差/position/policy conditions/decision margin/bundle hash/policy state)。

## 11. mismatch 属于哪些根因类别?

全部归类 `float32_projection_boundary`(决策边界 4×2⁻²⁴×max(|x|,0.1) 量化界内);**0 个 unexplained**;无 column/schema、routing、policy state/reset、tie 行为类。

## 12. float64 roundtrip 是否等价?

是。Float64 Mathematical Path(transform→inverse,全 float64)max_abs 重建误差 = 2.22e-16(容差 1e-14)→ pass。

## 13. float32 runtime roundtrip 是否导致动作翻转?

是——这正是 R9 `reference_equivalence_all=false` 的根因:生产 env 唯一投影点(`rl_platform/env.py::_observation` 的 `astype(float32)`)使 raw 路径读 `float32(raw_x)`、wrapped 路径读 `inverse(float32(transform(raw_x)))`,两者在阈值附近翻转(98 处,全部在量化界内)。

## 14. 是否引入 policy-visible canonicalization?

是。`PolicyVisibleReferenceCanonicalization-v1`:`canonical_raw_features = inverse(float32(transform(raw_features)))`;raw-side 用 canonical episode(价格列原始);scaled-side wrapper 逆变换产生 bitwise 相同 canonical raw;supervised labels 用 canonical reference;所有 observation-aware 基线同一合同;交易价格/reward/ledger 用原始市场数据。不修改 preprocessor/thresholds、无 raw side channel、无 latent、绑定 bundle(design plan 绑定静态 digest;calibrate/final 绑定 bundle 级 payload)。

## 15. 如引入,它是否改变 legacy action?

canonical 合同本身与 wrapped(生产)路径**逐位一致**(calibrate main 电池:72 episodes canonical_scaled_full_equality=True)。与 legacy float64-raw 相比的差异即 §10 的 98 处(全部 float32 边界内)。

## 16. 所有差异是否都可解释?

是:0 unexplained(诊断集与正式 main 电池均如此)。

## 17. 是否存在任何 unexplained mismatch?

无(equivalence 口径);注:calibrate 后续的**生成失败**属于另一类(§20),已按 §21 处置。

## 18. preplan full-pipeline rehearsal 覆盖了什么?

§12.2 全清单:main/holdout tiny fit、bundle verification、routing、production/reference equivalence、supervised dataset+训练+评估、C1/C3、C2 matched、semantic(4 blocks)、independent、strict gate assembly、artifact 序列化与 reload、临时目录 qualification plan lock/load、sealed preflight(零 final seed)、tiny final-like runner(临时 exposure 状态机)。digest `r10rh-fd82ebfb`。

## 19. rehearsal 是否使用正式相同 orchestrator?

是。`orchestrate_calibration_stage_r10`(calibrate 的唯一编排)与 `execute_final_core_r10`(final 的执行核心)被正式与 rehearsal 共同调用;唯一差异是 R10ExecutionProfile 的样本量与 namespace。禁 monkeypatch 被遵守(rehearsal 报告 `monkeypatch_used=false`)。

## 20. code freeze SHA 是什么?正式数据后是否发生源码变化?

### 20.1 冻结与 SHA
- Commit A `e97c38d4`;audit 第一次运行在写 freeze 处 NameError(见 §20.2);Commit A′ `06e9b5beb4df564e51d27aae444f281843356809`(拼写修复 + freeze 前移)为**最终冻结点**;audit 以其锚定 freeze artifact(tree `r10src-9409ca074d16`)。
- freeze 后零源码变化:`fail_path_cleanliness.json` 的 `source_changed_after_freeze=false`;calibrate/后续阶段的 freeze 复验(源码树 sha256 清单比对)从未失败;design/final plan 绑定 06e9b5b。

### 20.2 audit 中断的治理披露(完整事实)
第一次 audit 在 freeze 写入行抛 `NameError`(拼写 `write_r10_code_free`)。当时的精确状态:**零正式 R10 namespace 访问**(无 cue/design/calibration 语料生成;ledger 不存在;任何 plan 不存在;freeze artifact 未写成)。§21 硬规则的触发域明确为"从第一次正式 namespace 访问开始"的异常,且 abort 合同的执行对象("保留所有 plan")不存在 —— 判定:该异常位于触发域之外,不写 aborted marker。处置:中断产物 14 个文件完整归档 `raw_logs/audit_interrupted/`;修复(一行拼写 + freeze 前移至 audit 第一动作,消除"数据先于锚点"的时序缺陷);Commit A′ 成为新冻结点;全部治理 artifact 以新锚点重新生成。此判定与证据链提交独立审查复核。

### 20.3 calibrate 阶段异常(正式失败点)
design plan 锁定、pack 生成、大量正式 namespace 访问(cue-audit/design/fit bank/eval/equiv)之后,shared orchestration 的 supervised main 在生成 c3_cost/D0/pair1(supervised_main_r10)时抛 `PairGenerationError`(5 attempts 全部 too_few_distractors;A/B/pair 三段同文案)——明确处于 §21 触发域内。按合同:`r10_iteration_aborted.json` 写入(2026-09-02T17:29:54Z),R10 永久结束,guard 生效(aborted 后一切阶段入口拒绝),下一轮必须 R11。不修代码、不重锁 plan、不复用 namespace。

## 21. 正式数据后是否发生源码变化?

否(§20.1)。Commit A′ 之后 src/tests/vendor/config 零变化;仅新增 artifacts/raw_logs/报告。

## 22. R10 cue audit 结果?

plan `r10ap-b57fa6141cbb5411afd91d03ca9a552f4f723e728cdecd620c26a6a9c4734cca`(先锁后跑);p_contract=0.9504294240;MC(1e6 events)=0.950369(|diff|=6.0e-5 ≤ 0.001);model 经验 0.949514(CI [0.945910,0.953086] 含 analytic);validation(attempts-mode)0.953357(CI [0.949641,0.957052] 含 analytic);floor=0.930429;exact replay/per-event K/tail mirror 全过;once/attempts:recall 差 0.003844(tol 0.007920)、k_mean 差 0.002(tol 0.05)、first_pass 50/50 逐位一致、attempt histogram 500/500 attempt=0;audit digest `r10ca-4b98b06f04`。

## 23. semantic main/validation 结果?

design 阶段(dedicated,`cue_semantic_design_main_r10`/`_validation_r10`):main PASS(160 blocks、4147 unique cues、recall LCB **0.949952** ≥ floor 0.930429、non-cue FP UCB 0.000644 ≤ 0.01);validation PASS(160 blocks、4149 cues、LCB **0.946356**、FP UCB 0.000509)。calibration 阶段语义语料(cue_semantic_calibration/holdout)未执行(supervised main 先失败)。

## 24. 三个 candidate 结果?

恰好三候选(historical/conservative/midpoint;alpha 68/54/40/32、74/56/40/28、71/55/40/30;kappa 0.80/0.55/0.38/0.25、0.82/0.60/0.40/0.26、0.81/0.575/0.39/0.255,冻结合同逐位不变)。R10 新语料 40 matched blocks × 2 corpora 评估:historical_control 合格 {15, 20}(n=10 的 gate_pass_probability=**0.8367** < 0.90 → 不合格;n=15 → 0.9511;n=20 → 0.98575);conservative 与 midpoint 在 {10,15,20} 全部不合格。与 R9(n=10 全合格)的差异来自全新 seed 空间的独立语料——印证 §2.1 的 development-evidence 定位。

## 25. 选定 candidate 与 formal n?

机械选择(最小 n → maximin → 距离 → id):**c2l_historical_control,n=15**(maximin 0.109721;参数距离 0)。未预设(R9 曾选 n=10)。

## 26. independent marginal 结果?

`design_r10_independent_marginal`(20 pairs/rung):guard PASS(ordering/D3/基线 margin/integrity=1.0/oracle positive/密度/local cue independence/context observability/point recall ≥ 0.90)。

## 27. R10 pack digest?

`r10pk-a475b997313b445ca25aa76f43e394bbe5bf493942942d39f7a6f6b75feb9314`(CurriculumR10MatchedLadderPack-v1;绑定 R4 C1/C3-D3、选定 ladder、n=15、Cue Contract v2、matched-ladder、policy-visible reference 合同、R10 p_contract/floor、code freeze SHA(经 design plan)、cue audit plan、design plan、marginal 证据)。

## 28. V2 main/holdout bundles?

main:fit `preprocess_fit_calibration_r10`(4/rung×3 families;bundle hash 见 `preprocessor_bundle_calibration.json`);holdout:fit `preprocess_fit_holdout_r10`(独立)。`preprocessing_v2_requalification.json`:**电池 PASS**(survival 8/8×2、fit bank integrity、vendor 数值等价、envelope reload 位等、manifest/参数篡改拒绝、staged/mixed 同 multiset 同 bundle、顺序不变、observation space、adversarial、no NaN/Inf、position identity、bundle verify×2、provenance 完整、dual-fit 差异记录、R4 继承)——注:该电池以 main 侧完成全部检查;holdout 侧 reference equivalence 检查位于电池的 holdout 段(supervised 失败发生在电池之后,holdout 电池结果已含于同一 artifact:pass=True)。

## 29. supervised main/holdout 结果?

main:dataset 构造(c1 40 records → 22960 rows;c2 同)与 c1/c2 全部训练完成前的 **c3 records 生成失败**(§20.3)——supervised main 未完成,holdout 未开始。label alignment 主结果(失败前写盘):c1/c2 alignment 全过(`supervised_label_alignment_main.json` / `supervised_dataset_identity_main.json`)。

## 30. calibration 是否独立 PASS?holdout 是否独立 PASS?

均**未完成**(supervised main 失败即中止);已完成的 preprocessing robustness 电池 PASS(含 routing 与 reference equivalence main)。

## 31. 是否有 pooled rescue?

无(orchestrator 以 per-role 独立 gate 组装;`pooled_rescue_used=false`;失败后未做任何补救)。

## 32. final plan digest?

**未产生**(calibration 未 PASS → §22 前置不满足 → qp10- plan 从未构建/锁定;qualification namespace 从未解锁)。

## 33. sealed preflight 是否零 final seed?

未执行(无 final plan)。设计上 sealed preflight 的零 final-seed 合同在 preplan rehearsal 验证过(`write_rehearsal_sealed_preflight_r10`:0 preprocess_fit_qualification_r10 / 0 cue_semantic_qualification_r10 / 0 qualification_r10 / 0 c2_independent_qualification_r10 seed 调用)。

## 34. exposure 何时写入?final 执行几次?

**exposure 从未写入**(exposure marker 与 ledger 均不存在;`fail_path_cleanliness` 验证);final qualification 执行 0 次;final namespace 保持封存(seed 守卫在 post_abort 快照仍锁定)。

## 35. core/independent/semantic 数量?

design 阶段:semantic 160 blocks × 2(=1280 episodes 语料,各 4147/4149 unique positive cues);matched 40 blocks × 2 corpora × 3 候选;independent 20×4=80 pairs。calibration/final 阶段数量未产生(final 未执行;calibration 部分见 §28-30)。

## 36. final reference equivalence 结果?

未执行(final 未开始)。calibration main 电池的 reference equivalence(同一 canonical 合同)PASS:72 episodes、canonical vs scaled 全等、98 legacy 差异全解释、0 unexplained。

## 37. C1/C2/C3 结果?

design:C2 选出 historical control/n=15;marginal PASS。calibration:C1/C3 corpus、C2 matched、C2 independent、semantic 全部未执行(失败点在 supervised,位于其前);final 未执行。

## 38. full-cold 结果?

**未运行、未宣布**(final qualification 未 PASS;§26:FAIL 时不运行 full-cold)。FAIL 路径回归:targeted(stage2_6_1 全部)=**559 passed**;stage2_6_2=**150 passed**。

## 39. C3 Branch D 是否仍开放?

**开放**(R10 不解决 C3 scratch PPO / BC-actor 被 PPO 破坏 / critic-value-advantage 动力学)。

## 40. R10 最终 PASS/FAIL?

**FAIL**(禁止 conditional pass;失败点与治理见 §20.3;成果与未完成清单见 §0/§28-31)。

## 41. Stage 2.6.2 正式状态?

**FAIL**(不变;本轮 262 回归 150 项全绿;input lock 已登记 R10 api.py 变更,sha `d11ad20d…`)。

## 42. PPO smoke?

未执行(FAIL 路径;`ppo_smoke_r10` namespace 已注册未使用)。

## 43. 建议下一步(R11 处方)

1. **R11 全新 namespace 全链重做**(R10 全部 namespace 永久封存;含 abort/ledger/marker 保留)。
2. **生成失败根因追查(最高优先)**:本次 c3_cost/D0/pair1 的 5-attempt 全败在三种重放(单调用/纯生成序列/含 c1+c2 dataset+torch 训练的完整 supervised-main 序列)下**均不可复现**(详见 `raw_logs/generation_failure_replay_diagnostics.json`);c3 生成器路径无全局 RNG(grep 审计)。R11 应:(a) 重放扩展至包含 robustness 电池(eval/equiv 144 episodes × 3 runs)后再到 supervised,若重现则二分定位;(b) 把 PairGenerationError 的逐 attempt 结构明细纳入 supervised artifact(本次 traceback 有 5 条同文案,attempt log 未落盘);(c) 评估预注册 attempt-escalation 合同(生成失败时的预注册扩展 attempt 区间,须写入 R11 plan;不得修改生成器/C1-C3 参数)。
3. R10 已验证的修复直接继承(经 R11 的签名核对):keyword-only 委托、PolicyVisibleSupervisedLabel-v1、bundle routing、canonical reference 合同(Branch B)、共享 orchestrator、freeze-first audit。R10 的 cue audit/design/pack 全部结果作为 development evidence 绑定进 R11 报告。
4. 治理不变:两阶段 commit、§21 硬规则、aborted marker 不可删。

## 44. Known limitations

- post_design namespace 快照为 abort 后补录(时点披露于快照内 note;design 完成时点的内联快照未捕获——R9 由外部脚本拍摄,R10 遗漏,证据链由 ledger/artifact 时序补足)。
- supervised 失败的进程内根因未定位(unexplained runtime failure;不可复现);这是 R11 的第一优先事项。
- calibration 阶段的 holdout 侧 reference equivalence 电池结果包含在整体电池 artifact 内(supervised 失败在其后),但 holdout 侧的 supervised/matched/semantic 独立 gate 全部未执行。
- audit 第一次运行的 NameError 与治理判定(§20.2)提交独立审查复核。
