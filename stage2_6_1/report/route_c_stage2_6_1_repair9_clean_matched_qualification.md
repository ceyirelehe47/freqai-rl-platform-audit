# Stage 2.6.1 Repair R9 — Candidate Evaluator 全链路闭环与 Clean One-Shot Matched Qualification(诚实 FAIL)

- 结论:**Stage 2.6.1 Repair R9 = FAIL(诚实;§18 一次性硬规则)**
- Baseline:`dfe646bbdd53d6053d483343c62088f45e92fb34`(R8 诚实 FAIL checkpoint;父提交 `11951f6d9b2f5fa63b17e3857aba92b330da029e` = R7 FAIL checkpoint)
- Commit:见仓库 main 分支(标题:"阶段 2.6.1 Repair R9:Clean Matched Qualification失败(诚实FAIL)")
- 正式状态:Stage 2.6.1 Repair R9 = FAIL;Stage 2.6.2 = FAIL;Stage 2.6.3 = 未开始;C3 PPO Branch D = 继续开放

## 0. 执行摘要

R9 修复了 R8 的两个正式工程缺陷(candidate evaluator 的 `c2_density_summary` 错误导入、semantic artifact writer 的 `endswith("main")` 后缀模糊匹配),并按规范补齐了模块级依赖闭环、真实(非 monkeypatch)evaluator 集成 smoke、cue audit plan 锁定、once/attempts 双模式审计、qp9- 前缀与"下一轮必须 R10"文案。前半程全部通过:audit → cue-audit(三路闭合,p_contract=0.950435)→ preplan rehearsal → plan-roundtrip(14/14)→ design plan 锁定(`r9dp-83d4d3b7…`)→ **design 阶段完整 PASS**(R8 爆雷点;semantic 160×2 双 artifact 独立保留、三候选完整评估、机械选择 n=10 + historical_control、marginal guard、pack `r9pk-c3070b5b…`)。

但 calibrate 阶段(design plan 锁定后)在 supervised learnability 第一步抛出 `TypeError: supervised_learnability_run_r9() missing 1 required positional argument: 'namespace'`。根因是 **R8 源码中的第三个潜伏缺陷**:`curriculum261_r8_cli.py:825` 的调用 `supervised_learnability_run_r8(v2_main, pack)` 缺第三参数(签名为 preproc_v2/pack/namespace);R8 永久结束于 design 阶段、从未执行 calibrate,故该缺陷从未暴露;R9 blind-rename 继承后在首次执行时爆发。这与 R8 的失败完全同构:上一轮从未执行的代码路径中的潜伏缺陷在本轮首次执行处爆发。

按 §18 一次性硬规则(plan 锁后任何异常 ⇒ 永久结束,不再允许 R9.1 恢复)与 §34(禁止 plan 锁后修复代码并继续),R9 已写 aborted marker 并永久结束。此外如实披露:崩溃前已写盘的 `preprocessing_v2_requalification.json` 中 24 项检查有 23 项 True、唯 `reference_equivalence_all=False`(72 个 fit-bank episode 的逐 episode reference 等价未全部通过)——这是独立于 TypeError 的第二个未通过项,意味着即使修复 TypeError,calibration 亦会 FAIL。

## 1. 治理与历史保全

- R0-R8 全部 artifacts/报告零修改;R8 aborted marker 完整保留(`r8_abort_binding.json` 于 audit 阶段绑定:iteration=r8、reason 含 ImportError、aborted_utc=2026-09-01T19:49:58+00:00)。
- R8 namespaces 永久封存:R9 全部 27 个 namespace 与 R0-R8 Stage 2.6.1 及 Stage 2.6.2 namespaces 零重合(`seed_namespace_integrity*.json`:`r9_vs_historical_overlap=0`);seed 层 r9 vs r7/r8 qualification namespace 零碰撞(测试断言)。
- R8 design plan digest 保留:`r8dp-60bb85d5481054b619188fb5a97209acd054e9e110da26710458ecaf2ef0db9d`;R9 matched-ladder 核心身份对拍源从 R7 plan 升级为 R8 plan(`verify_matched_core_identity_r8`:c2/r6_tape/r6_pairs 三模块 SHA256 与 R8 plan 记录值一致)。
- R9 design plan 已锁定且保留:`r9dp-83d4d3b71942604db1bbe895cedcdf083151b835c962f8f9da20b432ef4843f4`;未删除、未重锁;plan 锁后代码零修改(回归 450/59/150 全绿证实)。
- R9 aborted marker:`r9_iteration_aborted.json`(2026-09-02T07:36:25+00:00,经正式 API `write_r9_iteration_aborted` 写入;ledger 同步 append `iteration_aborted` 事件);文案"下一轮必须 R10"。
- exposure marker:从未写入;`qualification_r9_unlocked()` 恒 False(六要素解锁从未发生),qualification 四 namespace 在 api 层被守卫结构性封闭(final seed 派生数为 0)。
- fail-path 清洁:`fail_path_cleanliness.json` 全过——27 项禁入产物(qualification_*/sealed_*/robustness_gate/calibration_summary/supervised_learnability/ppo smoke 等)全部不存在;无临时 driver(全程 `python -m rl_curriculum.curriculum261_r9_cli` 正式子命令)。

## 2. §33 四十二问

1. **R8 为什么 FAIL?** design plan 锁定后第一个 candidate 真实评估时 ImportError:`from rl_curriculum.curriculum261_r6_pairs import c2_density_summary`——该函数实际定义于 `rl_curriculum.curriculum261_r5_pairs`(r6_pairs 只 re-export `density_gate_r5` 等四符号,无 c2_density_summary)。
2. **R8 aborted marker 是否保留?** 是,完整保留并绑定进 R9 plan(`r8_abort_evidence` 字段 + `r8_abort_binding.json`)。
3. **R8 namespaces 是否永久封存?** 是,零访问、零 seed 派生(隔离快照 overlap=0)。
4. **c2_density_summary 正确来源是什么?** `rl_curriculum.curriculum261_r5_pairs`(r5_pairs.py:290)。
5. **为什么 R8 测试没有发现错误导入?** 三重叠加:(a) 函数体内延迟 import,模块导入期不触发;(b) R8 测试 monkeypatch 了 `_evaluate_candidate_matched_r8`(shared-gate-FAIL 短路测试使 evaluator 从未被真实调用);(c) 不存在非 monkeypatch 的 evaluator 集成测试。
6. **R9 real evaluator smoke 如何覆盖完整路径?** `preplan_candidate_eval_r9` 下 4 个真实 matched blocks 完整执行 generate_matched_block_with_attempts → evaluate_pair_corpus_r4 → build_c2_block_evidence_table → c2_density_summary(r5_pairs)→ density_gate_r5 → candidate_cue_semantics → local cue independence → context observability → formal block 计算(10/15/20)→ scrambled diagnostic → 序列化 → 重载;三重覆盖(rehearsal、preflight 静态探针、集成测试),全程零 monkeypatch(artifact `candidate_evaluator_integration_smoke.json` 记录 `monkeypatch_used=false`)。
7. **是否还有任何关键动态 import?** evaluator 与 marginal guard 无函数内 import(结构性回归测试 `test_r9_design_has_no_function_body_import_of_density`);19 个声明依赖全部模块级解析(`dependency_resolution.json`,digest `r9dep-bbb853a33fae58d3e5c1a1c40d007d73a8d26e72f5633bdc67092cfc363aaa6c`,含 c2_density_summary.__module__ == r5_pairs 硬断言)。
8. **semantic main/validation 如何显式映射?** `SEMANTIC_ARTIFACT_MAP_R9`(design 两 namespace)与 `SEMANTIC_STAGE_ARTIFACT_MAP_R9`(calibration/holdout/qualification 三阶段)穷尽字典;`semantic_artifact_filename_r9` 对未知 namespace 立即 RuntimeError。
9. **是否存在覆盖或后缀判断?** 否——映射与 writer 实现中无 `.endswith(` 调用(结构性测试);writer 用 O_CREAT|O_EXCL 独占创建、写后 reload 校验内嵌 namespace/corpus_role/design_plan_digest;design 主流程在生成 candidate blocks 前强制"双文件同时存在且 SHA256 不同"。
10. **plan lock 前 rehearsal 包含哪些真实路径?** mini cue audit(8 blocks×2、50k 事件 MC、once+attempts 双模式)、semantic writer 机制验证(exclusive/reload/双文件/覆盖拒绝/未知 ns 拒绝)、真实 evaluator 4 blocks、semantic mini corpora(4+4)、parameter-pack builder dry、qp9- 前缀检查、sealed/final runner 静态导入、exposure marker 临时目录状态机(running 原子→单向 terminal)、依赖解析;digest `r9pr-2a7f362af4fb7bd78bb57126cb6b9167ae1baf3afa6dc7998cd8735725b1558e` 并入 design plan。
11. **R9 cue audit plan 何时锁定?** cue-audit 子命令在生成任何正式 audit data 之前(`cue_audit_plan.json` + `r9ap-9cd438876c632d645f3f4cc4b1d0fc7629a26341115ee29bd6052d43723ef918`);绑定 namespaces/500×2/once-attempts/exact replay/mirror bound/1e6 MC/bootstrap seeds/delta/floor/trace schema/code identity;重锁被拒、加载时对当前代码漂移 fail-closed。
12. **once-mode 与 attempts-mode 结果如何?** model(once)0.949981 vs validation(attempts)0.951368,|diff|=0.001387 ≤ tol 0.008200;k_mean 0.9435 vs 0.9666,|diff|=0.023054 ≤ tol 0.050;first_pass 逐位一致 50/50 块(df+hidden 全等);attempt histogram:500 blocks 全部 attempt=0(first_pass_rate=1.0、零结构拒绝)——sentinel ladder 下 structural retries 未条件化 cue recall。
13. **R9 corrected p_contract?** 0.9504348917802892(全新 audit namespaces 重算,未复制 R8 的 0.9504755)。
14. **R9 recall floor?** 0.9304348917802892 = max(0.90, 0.9504348918 − 0.02)。
15. **160-block semantic main 结果?** PASS:point 0.948218,LCB 0.943023 ≥ floor 0.930435;4152 unique positive cues(≥3600);non-cue FP UCB 0.000679(≤0.01);8/8 检查过。
16. **160-block semantic validation 结果?** PASS:point 0.955566,LCB 0.950423;4141 cues;FP UCB 0.000880;8/8。
17. **两个 semantic artifacts 是否都保留?** 是——`semantic_design_main.json`(sha256 92201593…)与 `semantic_design_validation.json`(ac730b1d…)哈希不同、各自独立落盘(R8 丢失 main 的缺陷已修复);jsonl 事件流分别 4152/4141 行。
18. **三个 candidates 结果如何?** c2l_historical_control:qualified {10,15,20} 全 True;c2l_conservative:全 False;c2l_midpoint:全 False(唯一合格者为冻结历史对照)。
19. **选定 formal block count?** 10(最小 n 机械产生;不得根据历史预指定)。
20. **选定 ladder?** c2l_historical_control:D0 68/0.80、D1 54/0.55、D2 40/0.38、D3 32/0.25;maximin@10 = 0.111757;param distance = 0.0。
21. **independent marginal 是否通过?** design 阶段 PASS(`c2_independent_marginal_design.json`:20 pairs/rung、namespace design_r9_independent_marginal、guard pass=True);calibration/holdout/final 的 marginal 未执行。
22. **R9 parameter-pack digest?** `r9pk-c3070b5bc114b77d0ca314a033ff14181aeac5fe7a916f4f5a6269624b6b26b9`(CurriculumR9MatchedLadderPack-v1;绑定 R4 pack/R5-R8 digest 链/选定 ladder/n=10/合同身份/候选与 marginal 证据)。
23. **V2 新 fit bundles 是否通过?** **否(独立第二未通过项,如实披露)**:calibrate 在崩溃前完成的 `preprocessing_v2_requalification.json` 24 项检查中 23 项 True(数值等价、8/8 特征存活、无 clip、无界空间、position 身份、bundle reload、manifest/tamper 拒绝、双 fit 独立性等),唯 `reference_equivalence_all=False`(72 个 fit-bank episode 的逐 episode reference 等价未全部通过)⇒ robustness gate 整体 FAIL。失败明细未落盘(每 episode 细节不在 artifact 内);R9 已永久结束,禁止为诊断再访问 R9 namespace,深入诊断移交 R10。main/holdout bundles 已生成并 verify(state r4ps-b35e94d2…,multiset r4fm-bdf029d7…/r4fm-b2bf5e03…)。
24. **C1/C3 新语料是否通过?** 未执行(calibrate 崩溃于 supervised,早于 C1/C3 corpus 生成)。
25. **calibration 是否独立通过?** 未完成(执行至 supervised 崩溃;fit/V2 重审完成、其余未达)。
26. **holdout 是否独立通过?** 未执行。
27. **是否使用 pooled rescue?** 否。
28. **plan 锁后是否出现异常?** 是——calibrate 阶段 `TypeError: supervised_learnability_run_r9() missing 1 required positional argument: 'namespace'`(curriculum261_r9_cli.py:1015;R8 潜伏缺陷 r8_cli.py:825)。
29. **是否删除或重锁 plan?** 否。
30. **是否使用临时 driver?** 否(aborted marker 亦经正式 API 写入)。
31. **sealed preflight 是否零 final seed?** sealed preflight 未执行(未到该阶段);结构性保证:qualification 未解锁 ⇒ api 守卫拒绝一切 final namespace seed。
32. **exposure 何时写入?** 从未。
33. **final 执行次数?** 0。
34. **core pairs 数量?** 未产生(final 未执行;按 §26 计划为 80+4×10=120)。
35. **independent pairs 数量?** 未产生(计划 80)。
36. **semantic blocks/episodes 数量?** design 阶段 320 blocks / 2560 episodes(160×2);final 阶段未执行。
37. **C1/C2/C3 结果?** final 结果未产生;design 阶段 C2 完整(三候选/选择/marginal/pack)。
38. **full-cold 结果?** 未执行(§28:final FAIL ⇒ 不运行、不宣布)。
39. **C3 Branch D 是否仍开放?** 是。
40. **R9 最终 PASS/FAIL?** **FAIL**(§18 一次性硬规则;无 conditional pass)。
41. **Stage 2.6.2 正式状态?** FAIL。
42. **建议下一步?** R10(必须;禁止 R9.1):(a) 修复 calibrate CLI supervised 调用缺 `namespace` 参数,并对 calibrate 子命令全链(含 supervised/C1/C3/semantic/marginal/汇总)补一个真实小规模集成 smoke,纳入 preplan rehearsal 硬前置——本轮再次证明"从未执行过的路径就是未验证的路径";(b) 诊断并修复 V2 `reference_equivalence_all=False`(R4 之后该检查首次重新执行;需在 R10 的 plan 锁前定位 72 episodes 中的失败明细);(c) 全部统计合同/候选网格/{10,15,20}/160-block 规模保持冻结;(d) 全新 r10 namespace。

## 3. 工程闭环明细(§5-§9)

- **依赖闭环(§6)**:`curriculum261_r9_dependencies.py` 声明 19 个 (symbol, 定义模块) 依赖;`resolve_dependency_identity_r9` 逐符号解析 resolved module/source file sha256/callable,硬断言 `c2_density_summary.__module__ == "rl_curriculum.curriculum261_r5_pairs"`;digest `r9dep-bbb853a3…` 进入 design plan。Import sweep(compileall + 14 模块 import + 符号解析)在 plan lock 前由 `_official_entrypoint_validation`(audit 阶段)与 preflight 双重执行。
- **真实 evaluator 集成 smoke(§7)**:`candidate_evaluator_integration_smoke.json` PASS(4 blocks、全链、序列化/重载、schema/finiteness 检查)。
- **artifact writer 显式映射(§8)**:`semantic_artifact_writer_validation.json` PASS(穷尽映射/exclusive-create/reload 一致/双文件哈希不同/覆盖拒绝/未知 namespace 拒绝)。
- **preplan rehearsal(§9)**:`preplan_end_to_end_rehearsal.json` PASS(8 个 section 全过)。

## 4. Cue Contract v2 重审(§10-§11)

audit plan 先锁(`r9ap-9cd4388…`);三路闭合:analytic p_contract=0.9504348918;MC(1,000,000 事件,seed 20261101)=0.950271(|diff|=0.000164 ≤ 0.001);直接生成器:model(once-mode)0.949981 CI[0.946065, 0.953812]、validation(attempts-mode)0.951368 CI[0.947555, 0.955064]——analytic 均在双语料双侧 95% cluster CI 内;|emp−analytic| ≤ max(3×SE, 0.005) 双语料过;tail 专项/K 位置检查(z=4.0 Bonferroni)/噪声重放(≤1e-12)/aggregate 复算全过;once_vs_attempts 对照一致(见 §2 第 12 问)。非劣效:delta=0.02、绝对下限 0.90 冻结;floor 未因 dedicated semantic 结果修改。

## 5. 治理执行时间线(UTC)

| 时间 | 事件 |
|---|---|
| 07:20 | audit 全绿(baseline/historical/r8_binding/dep/entrypoint) |
| 07:25 | cue audit plan 锁定(r9ap-9cd4388…)+ 三路闭合 audit PASS |
| 07:26 | preplan-smoke + rehearsal PASS(r9pr-2a7f362a…) |
| 07:26 | plan-roundtrip 14/14 PASS |
| 07:27 | **design plan 锁定 r9dp-83d4d3b7…(§18 硬规则生效)** |
| 07:28 | design_data_started |
| 07:29-07:33 | semantic 160×2 PASS → 三候选 × 2 语料 × 40 blocks 评估 → 选择(n=10, historical_control)→ marginal PASS → pack r9pk-c3070b5b |
| 07:33-07:34 | calibrate:V2 fit banks/bundles/重审(robustness FAIL:reference_equivalence_all=False)写盘 |
| 07:34 | **calibrate 于 supervised 第一步 TypeError(§18)→ R9 永久结束** |
| 07:36 | aborted marker + ledger(正式 API) |
| 之后 | fail-path 清洁检查全过;namespace 快照;回归 59/450/150 全绿 |

## 6. 回归与测试

- 新增 8 个测试文件 59 项全过(7 个 R8 适配 + `test_curriculum261_r9_integration.py` 14 项,含非 monkeypatch evaluator 全链集成、writer 显式映射、once/attempts、audit plan 锁定 roundtrip、qp9- 前缀、R10 文案、namespace 封闭)。
- Stage 2.6.1 全量:450 passed / 0 failed;Stage 2.6.2 全量:150 passed / 0 failed(api.py 变更已按 R3-R8 模式登记进 `R9_REGISTERED_CODE_CHANGES`,sha256 2abacd03…)。
- full-cold 未执行(§28)。raw logs 见 `raw_logs/`。

## 7. 已知限制

1. V2 `reference_equivalence_all=False` 的逐 episode 失败明细未落盘(该检查只落 all-bool 与计数);R9 namespace 已封存,无法回放诊断;R10 需在新 namespace 上定位。
2. calibrate 崩溃点的修复方案已在 §2 第 42 问记录,但按 §18/§34 本轮不修不复跑。
3. attempt histogram 显示 sentinel ladder 下 500/500 全部 first-pass(零结构拒绝),once vs attempts 的"重试条件化"维度在该 ladder 上未被实质 exercised(仍是有效的零偏差证据,但区分度有限)。
4. R9 继承了 R8 全部既有代码,blind-rename 无法发现"从未执行过的路径"中的潜伏缺陷——本轮 calibrate CLI 即此类;该结构性风险只能靠"每条正式路径都有真实集成 smoke"消除(R10 处方)。

## 8. C3 PPO Branch D

仍然开放(R9 不解决 C3 scratch PPO / BC actor 被 PPO fine-tune 破坏 / critic-value-advantage-update dynamics)。R9 PASS 后亦不得自动启动 Stage 2.6.2(本轮 FAIL 同样不启动)。
