# 阶段 2.6.1 Repair R11:Generation Determinism Closure, Supervised Gate Correctness and Clean Qualification(主报告)

- 结论:**FAIL(诚实 FAIL)**
- 启动基线:`b31ad39bbce040e4fe93a58b864d144bd12dca4f`(R10 诚实 FAIL checkpoint)
- Implementation Freeze(Commit A):`df0292ac2208375cca478b037c4ba87c6808911e`
- Implementation Freeze 修正(Commit A′,最终冻结点):`572c509233fef560a39ea30cd497a34053d47ce0`
- 结果提交(Commit B):见仓库 log(本报告与 artifacts 所在提交)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- 环境:WSL CryptoRL-Ubuntu-24.04 / conda freqtrade-rl / PYTHONPATH=src
- 分支:`route-c-stage2-6-1-repair11`

## 0. 执行时间线(UTC,2026-09-03)

| 时刻 | 事件 |
|---|---|
| 实现阶段 | 22 个 R11 模块(20 个 r10→r11 适配 + generation_envelope + r11_determinism + r11_shadow 共 24 文件含新模块)+ 8 个测试文件;R11 测试 72 项全绿;R0-R10+R11 targeted 回归 **629 passed**;262 回归 **150 passed** |
| 工作包 A 验证 | mutable state 审计 PASS(family_specs 单例无跨调用污染);14 场景跨进程确定性矩阵**全绿**(全部 identical);R10 五 attempt seeds 前缀逐位一致;R10 失败在所有重放环境**不可复现**;generation determinism gate PASS |
| 工作包 C 验证 | 两次独立冷进程 full-scale shadow:逐 attempt envelope digest 与 33 个 gate artifact(剥离声明非身份字段)完全一致;shadow 捕获并修复 R10 潜伏缺陷(marginal gate 组装读 wrapper 不存在的顶层 pass;短路求值在 tiny rehearsal 掩盖) |
| preplan-smoke | 全链 PASS(工程 smoke r11smoke;§9 端到端 rehearsal `r11pr-386a8a06…`;§10 根因诊断 Branch B、36 legacy 差异全解释、0 unexplained;§12 full-pipeline rehearsal `r11rh-32cbd3b4…`) |
| Commit A | `df0292a`(48 files) |
| 第一次 audit | 在 r9_abort_binding 处中断:`PRIOR_R9_PARAMETER_PACK_DIGEST` 手工转录 typo(多一个字符);零正式 R11 namespace 访问(audit 治理检查段);16 个中断产物归档 `raw_logs/audit_interrupted/` |
| Commit A′ | typo 修复并与 repair9 digest 文件逐位核验;`572c509` 成为最终冻结点 |
| 正式 audit | **PASS**(freeze=572c509;tree `r11src-565b26b`;equivalence/ns/historical digests/vendor/dep/entrypoint/determinism 合同绑定全过;R8/R9/R10 abort 绑定全过) |
| cue-audit | plan 先锁(`r11ap-6879f609…`);**三路闭合 FAIL** —— K 位置检查越界(§2);按"不得锁 design plan"立即停止 |
| FAIL 处置 | `r11_iteration_aborted.json` 写入(10:28:26Z);fail_path_cleanliness PASS;post-fail namespace 快照;FAIL 路径回归 targeted 630 / 262 150 全绿;full-cold 未运行 |

## 1. R10 正式生成失败与重放矛盾的根因是否定位?

**没有唯一确定**,且按合同明确定性为
**"historically underdetermined due to missing invocation-state evidence"**。
R10 当时的 `PairGenerationError` 只保留字符串化 reasons,attempt log 未落盘,生成器实例状态/params 快照/内部派生 seed 均未记录 —— 任何假设(单例污染/params 别名原地修改/torch 引入的共享状态/进程内一次性状态)都无法被证据排除或确认。R11 的 A4/A5 系统排查(见 §4/§5)在 14 个环境场景、进程内五阶段负载序列下均未复现任何确定性破坏,也未发现任何 mutable state 污染 —— 与"证据缺失导致不可判定"一致。

## 2. 若未唯一定位,为什么历史证据不足?

R10 失败时:(a) 异常只携带 5 条同文案字符串;(b) 逐 attempt 的调用 envelope 不存在;(c) 生成器单例状态在失败时刻的摘要不可知;(d) 失败发生的进程已终止。重放(新进程、新状态)与正式运行(原进程、原状态)之间至少存在一项未记录的差异 —— 这正是 R11 工作包 A 要永久消除的缺口。

## 3. R11 如何保证未来同类异常可完整重放?

GenerationInvocationEnvelope-v1(`curriculum261_generation_envelope.py`):每次 pair attempt 的完整、稳定、可序列化、可哈希、可重放调用证据,覆盖任务书 A1 全部字段(调用坐标/outer seed/canonical rung params/A-B base params/generator 源码身份/family_specs 注册项身份/逐 attempt pre-post 实例状态摘要/内部派生 seed/split/timeframe/运行时版本/PYTHONHASHSEED/线程环境变量/事件表摘要/结构计数/A-B episode 内容哈希/structural validator 逐项结果/拒绝原因/接受状态/状态变化标记)。recorder 是纯观察钩子(异常 fail-open,不改变 seed/顺序/接受条件);R11 全部正式阶段经 envelope sink 逐 attempt 即时落盘(JSONL append+fsync);生成失败时 `PairGenerationError` 自带全部 attempt envelopes,calibrate/final 的异常处置在 abort marker 之前先落盘证据。replay 入口(`replay_call`/`compare_envelopes`)从保存的 envelope 重建调用并逐字段对比,不读任何 PnL/qualification 结果。

## 4. generator 是否存在 mutable singleton/global state?

A4 审计结论:**不存在影响行为的跨调用 mutable state**。
- C2 实例属性 `_wick_plan`(逐调用交接槽)调用后清为 None —— 与类默认 None 语义等价(状态摘要归一),不携带跨调用信息;
- `_matched_tape_excludes`(若被污染为非空 tuple)会立即可检出(状态摘要+call envelope 的 initial state digest 三处可见),实测全阶段无漂移;
- C1/C2/C3_RUNG_PARAMS 模块常量、api/c1/c2/c3 模块公共 globals 在五阶段负载(pair 生成/matched tape/fit bank+V2 fit/torch MLP 训练/预处理电池)前后摘要全部不变;
- 输入 params 对象调用前后逐位不变(shallow-copy 别名无原地修改)。

## 5. 相同 invocation envelope 跨进程是否 bitwise 一致?

**是**。14 场景矩阵(单 R10 失败调用重放/不同 PYTHONHASHSEED/import 顺序/预 import torch/预跑 C1/预跑 C2/预构造 C1+C2 supervised dataset/预训练 U-W-B MLP/预处理 robustness+reference-equivalence 电池/main+holdout 双 bundle 流程/同进程两次/双独立冷进程/OMP=MKL=1/R10 五 seeds 整体重放)全部:attempt envelope digest 逐位一致(内部 seed/canonical params/event digest/计数/episode hash/structural 结果/接受状态)。合同要点:envelope digest 剔除 runtime 上下文元数据(版本/PYTHONHASHSEED/线程环境)—— 环境差异是合法的非身份字段,混入会掩盖真正的生成输入漂移。

## 6. R10 五个 attempt seeds 在 R11 诊断中分别产生什么结果?

派生层面:五个记录 seeds 与 `derive261_seed("supervised_main_r10","c3_cost","D0",1,attempt)` 逐位一致(前缀验证)。生成层面:重放在 attempt 0(seed=4610631957848990728,即 R10 正式 attempt 0)**立即通过**(too_few_distractors 不出现);即与 R10 诊断一致 —— 同 seed 同参数在重放下不产生零 distractor 结果,失败不可复现。

## 7. 是否修改了 generator 语义或参数?

**没有**。C1/C2/C3 生成器、RUNG_PARAMS、paired_noise、`_derive261_seed_raw` payload 逐字未动(R0-R10 黄金向量回归锁定,629 项含全部历史 golden hash 测试)。api.py 变更(262 input lock 登记 sha `542f356d…`→ typo 修复后不变)仅:(a) R11 namespace 白名单追加;(b) R11 六要素解锁守卫;(c) 被动 recorder 钩子(默认 None = 历史行为逐位不变);(d) PairGenerationError 可选证据属性。max_attempts=5 未变。

## 8. 为什么没有直接增加 max_attempts?

因为 R10 的失败不是"重试不够"而是"确定性矛盾 + 证据缺失"。增加 attempts 会:(a) 违反任务书三.5(生成确定性闭合前禁止扩大重试);b) 在根因未明时把未解释异常埋进更多采样。R11 选择把每个 attempt 变成完全可重放的证据,而不是增加 attempt 数量。

## 9. supervised alignment 聚合 bug 如何修复?

R10 `collect_policy_visible_dataset_r10` 返回的 `alignment_ok` 取自循环最后一个 episode 的 `ep_alignment_ok`。R11 `collect_policy_visible_dataset_r11` 全量聚合:`alignment_ok = 所有 episode 均对齐 AND alignment_failures 为空 AND 逐 episode steps==labels AND 行数账目一致(n_rows == n_steps_total == n_rows_expected_total)`;逐 episode 对齐记录(含 n_steps/n_label_actions)全量进入 artifact。负向测试四例全部验证:首 episode position 失败+末尾正常→FAIL;中间 replay mismatch→FAIL;failures 非空+末尾正常→FAIL;行数账目错→FAIL。

## 10. distinct model-seed gate 如何定义?

gated controls = W、B;对每个 gated control 分别统计通过的 **distinct model seeds**(集合语义);W 至少 2/3 distinct seeds 且 B 至少 2/3 distinct seeds;family pass = W AND B;U 仅诊断不计数;重复记录同一 seed 不增加计数。artifact 落盘每 control 的 passing seed IDs、distinct 计数、逐 seed W/B 结果与机械计算过程。负向测试五例全过(单 seed W+B 双通过→FAIL;W=2/B=1→FAIL;W=B=2→PASS;U 全过但 W/B 不足→FAIL;重复 seed 不增量)。

## 11. 负向测试是否证明单个 seed 不能冒充两个 seeds?

是(§10 负向测试 1:只有 seed1 的 W/B 都通过,R10 缺陷逻辑 n_passing=2 会误 PASS,R11 distinct W=1/B=1 → FAIL;测试独立复算,不信任自报 pass 字段)。

## 12. full-scale shadow 覆盖了哪些正式坐标?

与正式完全相同的 orchestrator 与 final 核心(禁 monkeypatch;AST+测试锁定):supervised 三 family × 全 rung × 全 pair index(10/rung,含 C3 D0-D3)、equiv 3/rung、c13 eval 10/rung、semantic 160 blocks × main/validation/final 三 namespace、C2 matched 20 blocks(为 {10,15,20} 的超集)、C2 independent 20/rung、main 与 holdout 双路径、preprocessing robustness/reference-equivalence 电池先于 supervised 的正式顺序、fit→bundle reload→routing、canonical reference、临时 exposure 状态机、final-like 全规模。唯一削减 = supervised 纯训练(1 model seed、epochs=2;不改变生成调用路径覆盖)。

## 13. 两次 cold shadow 是否一致?

**是**:invocation ledger(逐 attempt envelope digest 序列,2 个台账文件)身份 digest 完全一致;33 个 JSON gate/证据 artifact 在剥离声明非身份字段(时间戳/run_tag/各自摘要文件)后 canonical digest 零差异(`shadow_two_cold_runs_comparison.json`:pass=True)。shadow final-like verdict=FAIL 的三项全部可解释且与接线无关:block_contract_identity(工程 pack 无正式合同绑定)、supervised_gate(1 seed 达不到 2/3 distinct seeds —— 正是 B2 修复的预期行为)、c2_independent_marginal_pass(工程语料真实统计边缘结果)。

## 14. code freeze SHA 是什么?

最终冻结点 = Commit A′ `572c509233fef560a39ea30cd497a34053d47ce0`(Commit A `df0292a` 因第一次 audit 中断的 typo 修复被取代;中断治理披露见 §15)。

## 15. 正式 namespace 访问后是否发生源码变化?

**没有**。第一次 audit 中断发生在 freeze 写入后的治理检查段(r9_abort_binding 的常量 typo),当时**零正式 R11 namespace 访问**(equivalence 仅用 preplan_smoke_r11;无 cue/design/calibration 语料、无 ledger、无 plan)—— 与 R10 §20.2 先例同型,位于 §21 触发域之外。处置:typo 修复并与 repair9 digest 文件逐位核验;16 个中断产物完整归档;Commit A′ 新冻结点;全部治理 artifact 以新锚点重新生成。此后(audit/cue-audit 直至 FAIL)`fail_path_cleanliness.source_changed_after_freeze=false`,freeze 复验从未失败。

## 16. Cue Contract v2 结果是什么?

**FAIL**(本轮正式失败点)。audit plan 先锁(`r11ap-6879f609c2db77e7c8ec2f9dc03115ebbb6465c2eb3dc14903bd6a2544b58da2`)。结果:p_contract=0.950435;MC(1e6 events)=0.950516(|diff|=8.1e-5 ≤ 0.001);model 经验=0.952678(CI [0.949198,0.956090] 含 analytic);validation(attempts 模式)=0.951385(CI [0.947681,0.955033] 含 analytic);floor=0.930435;once/attempts:recall 差 0.001293(tol 0.007699)、k_mean 差 0.019(tol 0.050)、first_pass 50/50 逐位一致。**唯一失败项**:direct-generator model corpus(cue_contract_model_r11,500 matched blocks once 模式)的 K 位置检查在尾位置 t=226 越界:n_events=31、C(t)=9、k_mean=1.6774 vs Binomial(9,1/9) 期望 1.0、se=0.16933、**z=4.0006 > Bonferroni 阈值 4.0**(AUDIT_K_Z_THRESHOLD,R8-R10 冻结合同参数)。同实现同参数下 R10 的 max_z=2.431 —— R11 全新 seed 空间的单点边缘翻线,属真实统计判定,非代码缺陷(检查逻辑为 R8 冻结实现,R11 未修改)。

## 17-19. 三 candidate、机械选择、independent marginal

**未执行** —— cue audit FAIL 后按"不得锁 design plan"立即停止;design namespace(cue_semantic_design_*/design_r11_matched_*/design_r11_independent_marginal)从未被访问;无 candidate 评估、无 n∈{10,15,20} 功效判定、无 pack。R10 的 design 结果(historical control、机械 n=15)按 §2 仅作 development evidence 绑定于 r10_abort_binding,未进入任何 R11 metric。

## 20. main bundle 与 holdout bundle 是否独立?

calibrate 未执行。设计层面(继承 R10 并经 shadow 全规模验证):main/holdout 各自独立 fit(shadow_fit_* 双 namespace)、独立 bundle hash、显式 routing(preplan/shadow/正式三路由类;非正式 routing 不得服务正式 namespace 的 fail-closed 测试锁定)。

## 21-22. canonical vs scaled 等价、legacy 差异

正式 calibrate 电池未执行。开发证据:preplan §10 根因诊断(Branch B:float64 数学路径通过、canonical 与 scaled 全等、36 legacy 差异全部 float32_projection_boundary 解释、0 unexplained);shadow 双跑的 reference equivalence main/holdout 全过(artifact 一致性比较的一部分)。

## 23-25. supervised/calibration 与 pooled rescue

均未执行(cue-audit FAIL 在前)。pooled_rescue_used=false(从未有任何补救;fail_path_cleanliness 记录)。

## 26-29. final plan、sealed preflight、exposure、final 执行

**全部未发生**:无 final plan、无 sealed preflight、**exposure marker 从未写入**、final qualification 执行 0 次;qualification_r11/c2_independent_qualification_r11/cue_semantic_qualification_r11/preprocess_fit_qualification_r11 全程锁定(post-fail namespace 快照:qualification_r11_locked_before_use、零 exposure)。

## 30. R11 最终 PASS/FAIL?

**FAIL**(禁止 conditional pass)。失败点:正式 cue-audit 的 K 位置检查(§16);处置见 §0/§31。

## 31. Stage 2.6.2 正式状态?

**FAIL(不变)**。本轮 262 回归 150 项全绿(FAIL 路径重跑亦 150 全绿);api.py 变更已按 R11 登记于 ppo262_input_lock(input lock 语义维持)。

## 32. PPO smoke 与 full-cold 是否执行?

均**未执行**(FAIL 路径;ppo_smoke_r11 namespace 已注册未使用;full-cold 未运行未宣布)。FAIL 路径回归:targeted(stage2_6_1 全部)= 630 passed;stage2_6_2 = 150 passed。

## 33. Known limitations / 下一步(R12 处方)

1. **R12 全新 namespace 全链重做**(R11 全部 namespace 永久封存;abort marker/ledger 保留)。
2. **Cue Contract v2 的尾位置 K 检查是本轮唯一阻断点**:z=4.0006 vs 4.0 的单点翻线在 500-block 语料上属 5% 名义水平下的边缘事件;R12 不得修改阈值/语料规模来"救结果"(合同参数冻结)。若 R12 复现同类单点翻线,应把该现象本身作为 Cue Contract v2 方差的正式研究对象(预注册,进入 R12 plan),而非视为异常。
3. R11 已验证的确定性/gate 修复直接继承(经 R12 签名核对):envelope 合同、矩阵、B1/B2、shadow 基建、abort 包装;R11 的 determinism/shadow/preplan 全部产物作为 development evidence 绑定。
4. 治理不变:两阶段 commit、§21 硬规则、aborted marker 不可删、fail-path cleanliness。
5. 其余已知限制:shadow 的训练削减(1 seed/2 epochs)意味着 supervised gate 的数值面在冻结前只被 tiny(3 seeds)与集成测试覆盖;audit 第一次中断的治理判定(§15)提交独立审查复核。

## 34. 测试与证据索引

- R11 新增测试 8 文件 72 项(envelope/determinism/labels/namespaces/governance/shadow/integration/marginal 回归)全部通过;targeted 630 / 262 150。
- 关键 artifacts(stage2_6_1/artifacts/repair11/):`determinism/generator_state_mutation_audit.json`、`determinism/cross_process_determinism_matrix.json`、`determinism/generation_determinism_contract.json`、`shadow/shadow_two_cold_runs_comparison.json`(含 A/B 双跑全量产物)、`preplan_full_pipeline_rehearsal.json`、`r11_code_freeze.json`、`cue_contract_audit.json`、`r11_iteration_aborted.json`、`r11_iteration_events.jsonl`、`fail_path_cleanliness.json`、`seed_namespace_integrity_post_fail.json`、`r10_abort_binding.json`、`generation_determinism_binding.json`、`raw_logs/`(audit/cue-audit 运行日志、回归原始日志、audit_interrupted/ 16 文件)。
