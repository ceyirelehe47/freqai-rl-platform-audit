# Stage 2.6.1 Repair R6 — C2 全局 Ladder 重构、Matched-Ladder 统计设计与 Clean Qualification(诚实 FAIL)

- **仓库**: ceyirelehe47/freqai-rl-audit,分支 `main`
- **本轮基线**: `40a0d9ae4ac8fcfa6f643f584a8fb63ec5579afc`(R5 诚实 FAIL checkpoint;父提交 `95bb927f` = R4 诚实 FAIL checkpoint,§0 开机核验一致)
- **最终 verdict**: **FAIL**(design 阶段:8 个完整 ladder candidate × formal block count {10,15,20} 的合格组合数为 0;§19/§26 机械规则)
- **R6 交付快照**: matched-ladder block 基础设施全量落地并测试锁定;matched 统计修复本身被验证有效(R5 的冻结 D0-D1 瓶颈在新口径下消失);FAIL 根因是预注册语义阈值的校准失误 + 4 个激进候选的真实功效不足,均为下一迭代可机械修正的输入。

---

## 1. 执行摘要

R6 的两项授权目标一成一败:

**成功的部分——matched-ladder 统计设计(§9-§15)全量落地并验证有效**:
- 同 block 的四个 rung 逐位共享 cue 时间/方向表、wick 方向纹理链 s、wick 幅值体制链 w、基础噪声创新 eps(反解验证 max|diff| = 3.3e-16)、volume 路径、wick jitter、初始价格、episode 时长与时间戳;唯一差异是 alpha_bps 对 payoff 注入的确定性缩放与 wick_kappa 对 wick 纹理的确定性变换(§10 随机带合同,实现于 `curriculum261_c2.py` 的 opt-in matched-tape 模式——默认关闭,历史 namespace 行为逐位不变,由 2.6.1 全套 251 项历史测试 + `_derive261_seed_raw` 黄金向量回归锁定);
- blockwise 配对差分把 rung 间比较从"独立路径差分"升级为"同路径差分":相邻 rung 的 block 相关 0.83-0.94,scrambled control 实测方差缩减 main 语料 3.5×-11.4×(全语料 3.1×-24.3×;§15 诊断);
- **R5 的核心瓶颈被解决**:R5 中历史 ladder 的冻结 D0-D1 间距(独立 gap 0.0054-0.0061 < κ×SE(n=10) 0.0063-0.0070,联合通过概率封顶 ≤0.25)在 matched 口径下,同一历史 ladder 的 D0-D1 gap/SE 达 5.5-7.7(main 口径),三段 gap ratio 4.4-9.2(双语料全口径),formal gate 通过概率(main@n=15: 0.977;validation@n=15: 0.985;双语料 n=20: 0.993/0.997)——若非语义 gate 误伤,`c2l_historical_control` 在 n=15 即满足全部功效条件(§19"不达标不得被选中"的 control 条款恰好证明统计修复成立)。

**失败的部分——design 阶段 0/8×3 合格(§26)**,两条独立根因:
1. **主根因(预注册阈值校准失误,与候选参数无关)**:§18 新增的 cue/payoff separation gate 中 `cue_recall_min = 0.95` 被预注册在生成器固有检出率的期望上——配对噪声按对累加使 cue bar 有效噪声 σ≈27bps,固有 recall = Φ(45bps/27bps) ≈ 0.951,每语料抽样 SE≈0.005。matched 设计下 cue 表跨候选共享,recall 只依赖语料:main 语料 8/8 候选 = 0.9519(过),validation 语料 8/8 候选 = 0.9490(差 0.001 FAIL)——阈值恰好卡在期望值,左右各半概率。历史 control ladder 同样被此 gate 拒绝,证明这是 gate 校准问题而非 ladder 设计问题。
2. **次根因(4 个激进候选的真实功效不足)**:`c2l_balanced/alpha_wide/alpha_edge/d0_high` 的 D3 α∈[22,26] 使 D3-vs-flat 均值(~3-6bps/笔 × ~6 笔对齐交易)相对 blockwise SE 不足 2.5×,D2/D3 逐基线 margin 同因——这是真实的设计信息:即使 matched 缩方差 3.5-5×,D3 α 过低的 edge 仍太薄。

**治理合规**:规则先锁(design plan digest `r6dp-db74ed10…` 锁定于任何 design episode 生成前;一次实现层勘误重锁发生在任何统计结果产出之前,零语义变化,见 §32 勘误记录);数据后未改任何阈值/网格/block 选项;无 pooled;final namespace 零访问;exposure marker 零写入;R0-R5 全部 namespace 与历史 golden hash 逐位不变(2.6.1 全套 308 passed、2.6.2 全套 150 passed 含 input lock R6 登记与 seed 黄金向量)。

---

## 2. §40 主报告 33 问

**1. R5 为什么 FAIL?**
R5 在 design 阶段诚实停止:Tier A(仅 C2-D3)0/6 与 Tier B(D2+D3 joint)0/3 候选满足全部硬门槛。数值根因:冻结 D0-D1 独立 gap 0.0054-0.0061 < κ×SE(n=10)=0.0063-0.0070,单条件通过概率 0.38-0.51,联合 formal-gate 概率封顶 ≤0.25 << 0.90。

**2. 为什么继续调 D2/D3 没有意义?**
R5 已证明:下调 D3 扩大 D2-D3 的同时压低 D3 绝对 margin;上调 D2 压缩 D1-D2;D0-D1 冻结间距不足是主要瓶颈且在独立采样口径下不可救——40 pairs 的路径噪声(σ_pair≈0.02-0.03)决定的 SE 下限不随 D2/D3 微调改变。

**3. matched-ladder 解决的是什么统计问题?**
把 rung 间比较的统计单位从独立 rung pair 升级为 block 内配对差分:四个 rung 共享同一结构随机带后,gap 的 block 方差只含参数效应,路径噪声逐位抵消。实测方差缩减 3.5-11.4×,使历史间距(ladder 完全不动)的 formal gate 通过概率从 ≤0.25 提升到 0.92-0.99(n=10-20)。

**4. matched block 中哪些随机内容共享?**
cue 时间表与方向表(hidden.cue_dir 逐位相等)、wick 方向纹理链 s、wick 幅值体制链 w、基础噪声创新 eps(从 returns−pulse−payoff 反解,跨 rung×variant 最大绝对差 3.3e-16)、volume 路径、wick jitter(payload 不含参数,天然共享)、初始价格(常数 100)、episode 时长(288 bar)与 bar 时间戳(epoch 递增)。block seed = `derive261_seed(ns, c2_context, "matched_block", block_index, attempt)`,派生不含难度参数——不同 candidate 的同 block_index 结构带逐位一致(§20"相同 block-index schedule"由构造满足,测试锁定)。

**5. 哪些内容随 rung 变化?**
只有两个难度轴(§7 授权):alpha_bps(payoff 注入幅值的确定性缩放)与 wick_kappa(wick 上/下影 `base·(1±κ·s)·(1+jitter)` 的确定性变换,jitter 共享)。其余 9 个结构参数(payoff_bars/vol_bps/cue_rate/dir_len_range/width_len_range/pulse_bps/wick_base_bps/wide_wick_bps/narrow_wick_bps)全 rung 逐位冻结,cross-rung matching 合同逐键校验(`params_scope` 检查,非法键差异整 block 拒绝)。

**6. block-level attempt 如何工作?**
一个 attempt = 完整四-rung block(8 episodes):生成 → 每 rung 的 A/B 结构词表校验 + pair 统一合同 → 跨 rung matching 校验 → per-rung 构造级 pair integrity;任一失败整 block 拒绝并 attempt+1(拒绝原因全部来自预注册结构词表,无 PnL 参与);max_attempts=5;first_pass 选择(绝不挑最好看的 block);日志 `MatchedBlockAttemptLog` 与 `check_block_attempt_log` 结构校验(编号连续/选中前全拒/选中后无拒)。

**7. matched 信息为何不会泄漏给 policy?**
block ID 与 rung ID 不进入 observation——episode 的 df 列与生产 schema 完全一致(8 生产特征 + OHLCV/date,测试 `test_block_id_not_in_observation` 锁定);matched 只是采样/统计合同,policy observation 合同(RouteCEnvCore/ObservationSpec)与 reward/execution 合同全部冻结未动。

**8. candidate grid 有哪些?**
8 个完整 ladder(§17 预注册,生成任何 design episode 前锁定):
| candidate | α(D0/D1/D2/D3) | κ(D0/D1/D2/D3) |
|---|---|---|
| c2l_balanced | 78/50/35/23 | 0.88/0.58/0.34/0.22 |
| c2l_alpha_wide | 80/52/36/24 | 0.85/0.60/0.38/0.24 |
| c2l_kappa_wide | 76/54/40/27 | 0.92/0.62/0.36/0.21 |
| c2l_conservative | 74/56/40/28 | 0.82/0.60/0.40/0.26 |
| c2l_alpha_edge | 82/48/34/22 | 0.85/0.55/0.36/0.24 |
| c2l_mid_flat | 78/48/38/26 | 0.86/0.55/0.38/0.23 |
| c2l_d0_high | 80/54/38/23 | 0.90/0.62/0.40/0.22 |
| c2l_historical_control | 68/54/40/32(R5 原值) | 0.80/0.55/0.38/0.25 |

**9. formal block options 为什么是 10/15/20?**
任务书 §19 预注册:对应 final C2 规模 120/140/160 pairs(80 + 4n),覆盖 R5 历史规模(10)与 1.5×/2× 扩档;锁定后禁止增删(测试 `test_formal_block_options_locked` + plan 网格守卫)。

**10. 选定的最小 block 数是什么?**
**无**——0 个合格组合,选择规则在第一层(最小 n)即空转。若仅看功效条件(剔除误伤的 recall gate),最小可行 n=15(c2l_historical_control 与 c2l_conservative 的 main/valid 双语料 formal gate P 均 ≥0.94);kappa_wide 仅 n=20 达标(0.901/0.949)。

**11. 选定的 C2 ladder 参数是什么?**
**无选定候选**(§19:无合格组合 → 不生成 parameter pack)。

**12. maximin score 是什么?**
预注册 §22:min over {gap_D0-D1/SE, gap_D1-D2/SE, gap_D2-D3/SE, D3-vs-flat/SE, D3-vs-long/SE, D3-vs-local-only/SE, 最弱 positive-gap rate/0.65, 密度比 min(trades/8, label/0.015), separation 余量 min(1−fc/0.06, recall/0.95)} × min over 两个 design corpus,SE 取该 n 的 expected block SE。选择顺序:最小 n → score 最大 → 参数距离最小 → id 排序(测试锁定含 tie-break)。

**13. 两个 design corpus 的 formal pass probability 是多少?**
逐候选见 `r6_candidate_results.json`/`r6_power_analysis.json`。代表性数字(n=15/n=20):
- c2l_historical_control: main 0.977/0.993, validation 0.985/0.997
- c2l_conservative: main 0.943/0.983, validation 0.947/0.981
- c2l_kappa_wide: main 0.817/0.901, validation 0.885/0.949
- c2l_balanced(激进组代表): main 0.359/0.423, validation 0.566/0.649
全部 8 候选因 validation 语义 gate(recall 0.9490<0.95)不合格,故 0 组合进入选择。

**14. matched gap SE 相比 scrambled SE 降低多少?**
scrambled(打乱 block 对应重估 unpaired SE,§15 仅诊断):方差缩减比(se_scrambled/se_matched)² 在 main 语料为 3.5×(c2l_alpha_edge 的 D0-D1)至 11.4×(c2l_historical_control 的 D0-D1),双语料全口径 3.1×-24.3×;相邻 rung block 相关 main 0.83-0.94、全口径 0.74-0.97。完整表在 `r6_power_analysis.json` 的 `scrambled_vs_matched_se`。

**15. positive-gap block rate 是多少?**
全部 8 候选 × 两语料 × 三段 gap 的 rate ∈ [0.90, 1.00](门槛 0.65,全过)。代表性:historical_control 三段 0.95;balanced main 0.95-0.975。

**16. cue/payoff separation 是否成立?**
参数化分离本身成立:payoff-bar false-cue 率 0.0172-0.0276(阈值 0.06,全过,且随 α 单调上升的机制可见:α_edge(82) 0.0276 > historical(68) 0.0172);non-cue 假阳性 ~0.0005(阈值 0.01);precision 0.9415-0.9613(阈值 0.85)。**唯 cue recall 阈值(0.95)误伤**:main 0.9519/validation 0.9490——阈值预注册在固有检出率期望上(详见 §1 主根因),与候选参数无关。

**17. C2 行为密度是否足够?**
是。全部候选双语料:median reference trades 10-14(双腿口径,64 个 rung×语料值的中位数 11.5;阈值 8)、reference long label rate 1.89%-2.77%(中位数 2.28%;阈值 1.5%)、mean n_cues ~24-25/ep。

**18. independent marginal guard 是否通过?**
**未执行**(§16:guard 在选定 candidate 后、pack 锁定前运行;无选定候选 → 不运行,`design_r6_independent_diagnostic` namespace 零访问)。

**19. V2 在新 fit banks 上是否通过?**
**qualification/calibration/holdout fit bank 未生成**(§39:design FAIL 后不得制造后续伪 artifact)。已执行的等价证据:audit 阶段 production preprocessing audit + numerical equivalence(production_equivalence.json pass=true,V2 数值实现与 R4 逐位同源,vendor pin 52bc96f4 clean);PPO smoke 内 V2 fit(ppo_smoke_r6)serialize/reload/outer 无界空间/check_env 全过。

**20. C1/C3 在新语料上是否通过?**
**未执行**(C1/C3 的 calibration/holdout/qualification 在 design PASS 后才运行;FAIL 在 design 阶段即停止)。C1-D3/C3-D3 的 R4 继承绑定在 pack 合同层完成验证(`verify_r4_inheritance`:常量 + R4 artifact digest 复算 + 逐位比对,测试锁定)。

**21. calibration 与 holdout 是否各自独立通过?**
未执行(design FAIL;§26 禁止进入 calibration)。

**22. 是否有 pooled 救援?**
否。R6 的统计合同里 pooled 只是诊断角色(§19 沿 R5);本轮连 calibration 都未进入,pooled 概念未被动用。

**23. final preflight 是否零 final seed 访问?**
final preflight **未执行**(design FAIL 前置阻断)。守卫已就位并被测试锁定:sealed preflight 的零 final seed 由 monkeypatch 记录器验证(test_sealed_preflight_no_final_seed_access);静态 preflight 只触碰 ppo_smoke_r6(test_static_preflight_touches_only_smoke_ns);`qualification_r6` seed 在六要素解锁前被 derive261_seed 拒绝(test_qualification_r6_seed_guarded_before_unlock)。

**24. exposure 何时写入?**
从未写入。marker 与 ledger 均不存在(`fail_path_cleanliness.json`:marker_exists=false, ledger_exists=false, qualification_r6_exposed=false)。

**25. final 是否只执行一次?**
final **零执行**(execution count = 0;qualification_r6 namespace 零 seed 派生)。

**26. final 总 pair 数是多少?**
不适用(未执行)。预注册规模:80 + 4×selected_block_count(120/140/160 随 n=10/15/20),绑定进 plan 模板(`final_sample_counts`)。

**27. C1/C2/C3 结果分别如何?**
不适用(未到 qualification)。C2 design 结果:8 候选全部评估完毕,逐 candidate×n×corpus 的 gap ratios/positive rates/gate probability/margins/密度/语义在 `r6_candidate_results.json`(原始 block 证据表全量保留,§26)。

**28. matched 与 independent 诊断有什么差异?**
independent-rung 诊断语料未生成;已完成的对照是 matched vs scrambled(§14)。design 阶段的 D3 功效不足结论建立在 matched 口径上,与 R5 独立口径的结论(整条 ladder 功效不足)形成分层:matched 解决了间距功效,剩下的 D3 绝对 margin 功效是 α 参数本身的属性。

**29. full-cold 结果是什么?**
**未运行**(§35:仅 final qualification PASS 后运行;FAIL 后不宣布)。

**30. C3 Branch D 是否仍开放?**
是。R6 不解决 C3 scratch PPO/BC 被 fine-tune 破坏/value dynamics(§37);Stage 2.6.2 official 状态保持 FAIL。

**31. R6 最终 PASS/FAIL?**
**FAIL**(诚实)。§36 的 PASS 条件在"C2 全局 candidate 合格 + selected formal block count 机械选出"处断裂;无 waiver、无 conditional pass。

**32. Stage 2.6.2 正式状态是什么?**
FAIL(不变;本轮不触及 2.6.2 official)。

**33. 建议下一步是什么?**
**R6.1(同一 matched 基础设施上的阈值+网格修正重预注册)**,三件事:
1. `cue_recall_min` 从 0.95 校准为生成器固有检出率 − 抽样容差(建议 0.93:固有 0.951 − 3×SE_语料≈0.009;或直接以 Φ(45bps/σ_eff) 的实测期望 0.951 为中心下移)。其余语义阈值(precision 0.85/fc 0.06/non-cue 0.01)本轮全部通过且有余量,不动。
2. ladder grid 修正:D3 α 下限上移至 ≥27(本轮 α∈[22,26] 的 4 候选 D3-vs-flat 与 D2/D3 margin 的 2.5×SE 不达是真实功效不足);保留本轮已证明功效充分的 conservative(74/56/40/28, 0.82/0.60/0.40/0.26)与 kappa_wide(76/54/40/27)为锚,周边重设 4-6 个候选。
3. 全新 R6.1 namespaces/design plan(block tape 机制零改动,`curriculum261_r6_tape.py`/`r6_pairs.py` 直接复用)。
备选:若审查方认为应优先处理 C3 PPO(C3 Branch D),C1/C3 的 V2 与 D3 候选证据链未被本轮污染,可先行。

---

## 3. 治理附录

### 3.1 勘误记录(design plan 重锁,零语义变化)
第一次 design 执行在第一个 candidate 第一个 corpus 的 margin 统计计算处崩溃:`build_c2_block_evidence_table` 的 margins 键集误排除 `always_flat`(与 REQUIRED_BASELINES 口径不一致,KeyError)。此时**没有任何 candidate 的任何统计结果产出**(无结果可见、无数据浪费:design namespace 的 episodes 完全确定于 seed+generator+参数,生成路径未修改,重跑逐位重现)。修复(margins 恢复包含全部 required 基线;oracle 不入 margins)不改变任何预注册语义(网格/阈值/统计公式/block 选项/seed 全部未动)。旧 plan `r6dp-09832f6d…` 删除,新 plan `r6dp-db74ed10…` 重锁,勘误全文见 `design_plan_erratum.json`。测试 `test_se_is_blockwise_not_composite`/`test_two_level_tables_same_source` 在修复后代码上锁定新口径。

### 3.2 禁止事项合规自查(§41)
- Route C 六项合同/fee/reward/action/execution:未动(route_c_integrity + 2.6.1 input lock 全绿)。
- C1/C3 参数:未改(R4 继承常量+artifact 双绑定,verify_r4_inheritance pass)。
- C2 context carrier/reference thresholds/cue 机制/A-B variant/observation 字段:未改(仅 opt-in 随机带键剔除,默认路径逐位不变)。
- R5 design corpus 未用作 R6 资格数据(全新 design_r6_* namespace)。
- qualification_r4/r5 未复用;block 数选项/candidate grid 数据后未改;无 unpaired 救援(scrambled 仅诊断);无 pooled;exposure 未删(从未写入);无 per-family/episode scaler/eval refit/VecNormalize/reward normalization/PPO tuning/BC warm-start/C3 PPO/2.6.2 official/2.6.3/historical training/backtest/Dry-run/real trading。
- matched-tape 修改(curriculum261_c2.py/api.py)已按 R3-R5 同款白名单机制登记进 `ppo262_input_lock.py` 的 `R6_REGISTERED_CODE_CHANGES`(api=81d0d4a3…,c2=196ac7b2…;c2 为首次登记),2.6.2 input lock 测试(20 passed)与 `_derive261_seed_raw` 黄金向量不变性全部通过。

### 3.3 回归证据
| 套件 | 结果 | raw 日志 |
|---|---|---|
| targeted(R6 六测试文件) | 57 passed / 0 failed | regression_targeted_raw.log |
| affected(2.6.1 全套:历史 251 + R6 57) | 308 passed / 0 failed | regression_affected_261.log |
| affected(2.6.2 全套,含 input lock/namespace) | 150 passed / 0 failed | regression_affected_262.log |
| full-cold | 未执行(§35) | — |

历史保留:R5 artifacts/report 原样保留;R4/R5 marker 未触碰;R2 plan digest `qp-8f64a1b5…`、diag262r2 `dp-ee6f8dc1…`、R4 pack `r4pk-eca9ed55…`、R5 design plan `r5dp-0c1eb69f…` 开机核验一致(historical_binding.json)。

### 3.4 R6 交付清单
- src(13 模块):curriculum261_r6_{tape,param_pack,namespaces,pairs,design,calibration,preflight,plan,final,smoke,cli}.py + 修改的 curriculum261_{api,c2}.py + 登记的 ppo262_input_lock.py
- tests(6 文件,57 项):tape/param_pack/namespaces/statistics/selection/preflight——覆盖 §38 全部七类(历史保留/Matched Block/Statistics/Candidate Selection/Marginal Guard/Governance/Regression)
- artifacts(repair6/,22 文件):baseline_integrity/historical_binding/route_c_integrity/preprocessing_v2_contract(+digest)/production_equivalence/production_preprocessing_audit/seed_namespace_integrity_{pre,post}_design/r6_design_plan(+digest)/design_plan_erratum/r6_candidate_results/r6_sample_size_selection/r6_power_analysis/fail_path_cleanliness/ppo_256step_smoke/regression_summary(+3 raw logs)
- FAIL 后未生成:parameter pack/全部 calibration/holdout/qualification/final 类 artifact(§39)

### 3.5 关键 digest/身份
| 项 | 值 |
|---|---|
| R6 design plan(现行) | r6dp-db74ed109a7bf7a955c74f1bd248213002d3c08f79512abf0faf93f8941e03c7 |
| R6 design plan(勘误前,已废弃) | r6dp-09832f6d27c5183805…(全文见 design_plan_erratum.json) |
| matched-ladder 合同 | C2MatchedLadderBlock-v1(identity r6ml-…,进 design plan 绑定) |
| block 表 schema | r6bt-…(r6_pairs.py BLOCK_TABLE_SCHEMA) |
| R6 parameter pack | 未生成(FAIL) |
| qualification plan | 未生成(FAIL) |
| exposure | 未写入(marker+ledger 均不存在) |
| baseline | 40a0d9ae4ac8fcfa6f643f584a8fb63ec5579afc |
| vendor pin | 52bc96f4480b1a0da6a9b455bd00b17fbb6786a5(clean) |
