# Stage 2.6.1 Repair R5 — C2 Ladder 功效修复与 Clean One-Shot Qualification(主报告)

- **verdict: FAIL(design 阶段诚实 FAIL,Tier A 0/6 + Tier B 0/3 合格,§17 停止;calibration/final 未执行)**
- 迭代:R5(iteration id `r5`;baseline `95bb927f3ba46fa18b98602ea05c37ed67df198b` = R4 诚实 FAIL checkpoint)
- vendor pin:`52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`(clean)
- design plan digest:`r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d`(生成任何 design data 前锁定)
- 本报告按任务书 §36 的 28 问逐项回答。

---

## 1. R4 为什么 FAIL?

R4 final qualification verdict FAIL(36 项检查 34 过):C2 fresh 语料
D2 难度 0.006998 < D3 0.008450 排序翻转(`difficulty_ordering_all` 与
`gaps_ge_kappa_se_all` 两项失败),即 C2-D2/D3 的设计间距相对 10-pair
抽样不确定性不足。R5 同时如实绑定 R4 的两起治理违约(见问 2)。

## 2. 为什么 R4 final 只能作为诊断证据?

R4 存在三个独立缺陷,使 final 语料失去独立资格证据地位:

1. **gate 规则中途改变 + holdout 参与规则选择**:第一次正式 strict
   口径下 C2 FAIL,随后改为 pooled 20-pair SE 并复用同一
   calibration/holdout 才得到 PASS——holdout 已参与规则选择;
2. **exposure marker 写入并 crash 后删除复用同一 namespace**:第一次
   final 写入 `qualification_r4 exposure=running` 后因 vendor 路径 bug
   崩溃,R4 硬合同写明"任何 crash 都结束 iteration",但仍删除 marker
   并复用 `qualification_r4`(协议违约);
3. **C2 ladder 实质失败**:D2<D3 翻转不是"偶然坏 seed",而是
   D2-D3 设计间距(~1.7×SE)相对跨语料方差的结构性不足。

R5 对这三点的结构性修复:唯一 strict per-corpus 口径在 design plan 与
qualification plan 中先于数据冻结(`r5sg-` identity);exposure marker
升级为硬合同(原子创建/单向状态机/append-only ledger 兜底删除检测/
无 delete API/文件锁互斥,§27);C2 功效经两级预注册 design 正面处理。

## 3. V2 哪些部分被保留?

`RouteCFeaturePreprocessing-v2` 候选实现**逐位复用**(R5 不改数值):
pinned vendor `VarianceThreshold(0)` + `MinMaxScaler(-1,1)`(经 R3
`RouteCPreprocessor` inner)、offline fit/freeze、feature 维 (-∞,+∞)、
position [0,1]、三层 identity(parameter state `r4ps-` / fit manifest
multiset `r4fm-` / bundle `r4pb-`)、inverse-reference wrapper、无 clip。
R5 正式状态未声明"V2 已通过 qualification"(qualification 未执行);
V2 的重新资格验证电池在 R5 calibration 阶段(未到达)。测试层面
(V2 复用面,55 项 R5 测试)全部通过。

## 4. C1/C3 候选为什么可以作为 R5 输入?

C1-D3(`opp_drift_bps=24.5/neg=16.0/vol=26.0/seg[24,24]/weights
[0.36,0.28,0.36]/distractor=0.0`)与 C3-D3(`alpha=50.0/payoff_bars=1/
vol=18.0/cue_rate=0.23/mixture[0.20,0.36,0.44]/distractor=0.06`)为
R4 选定值,经双重黄金绑定进入 R5:任务书 §6 常量逐位锁定 +
`verify_r4_inheritance` 对 R4 pack artifact(`r4pk-eca9ed55…`)的
digest 复算与逐位比对(测试通过)。R5 未重新搜索 C1/C3 参数。
C1/C3 未在本轮通过新语料资格验证(design 阶段即 FAIL,calibration/
final 未执行)。

## 5. C2 D2/D3 为什么功效不足?

R4 qualification 语料 D2-D3 设计间距 ~1.7×SE;R5 design 双语料
(各 40 pairs)进一步揭示分层结构:

- **D3 侧(授权可改)**:pair 难度 sd≈0.004-0.006,降噪(vol 下调)与
  降 α 的组合能把 D2-D3 gap ratio 提到 1.47-3.04(Tier A;多数
  1.7-3.0)、2.10-4.02(Tier B;c2b_3@main 2.10 未过 3.0 门槛),
  方向有效;
- **冻结侧(授权不可改)**:D0-D1 设计间距仅 0.0054-0.0061,而
  κ×SE(n=10)≈0.0063-0.0070 → 单条件 D0-D1 gap 通过概率仅
  **0.38-0.51**;D1-D2 为 0.43-0.89。P(全部 strict 条件) 被冻结的
  D0-D1 间距结构性封顶在 ~0.25 以下,与 D3 参数无关;
- Tier B(上调 D2)确实拉开 D2-D3 但等量压缩 D1-D2(0.34-0.64),
  净联合概率仍 ≤0.24。

结论:C2 在 n=10 正式规模下,整条 ladder 的相邻间距功效不足以支撑
预注册门槛,且绑定约束(D0-D1)在 R5 授权范围(仅 C2-D3 / C2-D2+D3)
之外。

## 6. Tier A 有哪些候选?

6 个 C2-D3-only 候选(键集与历史 D3 一致;仅动
alpha_bps/vol_bps/wick_kappa;α<40、κ≤0.38 保持 ladder 单调):

| candidate | alpha_bps | vol_bps | wick_kappa |
|---|---|---|---|
| c2_a_alpha26_vol16 | 26.0 | 16.0 | 0.25 |
| c2_b_alpha27_vol18 | 27.0 | 18.0 | 0.25 |
| c2_c_alpha24_vol16 | 24.0 | 16.0 | 0.25 |
| c2_d_alpha26_vol13 | 26.0 | 13.0 | 0.25 |
| c2_e_alpha27_kappa30_vol16 | 27.0 | 16.0 | 0.30 |
| c2_f_alpha25_vol20 | 25.0 | 20.0 | 0.25 |

## 7. Tier B 是否触发?

**是(机械触发)**。Tier A 0/6 满足全部硬门槛 → design decision
落盘 `tier_b_authorized=true`(此后 `design_r5_tier_b_*` namespace
才被 `derive261_seed` 守卫放行)→ Tier B 3 个联合候选执行 →
0/3 合格 → 按预注册规则 **R5 = FAIL,停止,不进入 calibration**。

## 8. C2 最终候选是什么?

无。无任何候选满足全部硬门槛,未生成 parameter pack
(无 `r5pk-` digest;`r5_parameter_pack.json` 不存在,calibration
fail closed)。

## 9. maximin 评分是什么?

score = min over {gap_D2_D3/SE_n10, d3_vs_flat/SE_n10, d3_vs_long/SE_n10,
d3_vs_local_only/SE_n10, min(median_trades/8, label_rate/0.015)} ×
min over 两个 design corpus(§16;预注册于 design plan)。参考排序
(全部不合格,评分仅供诊断):Tier A 最高 c2_e 1.475、c2_f 1.434;
Tier B 最高 c2b_3 1.50(c2b_1 1.423)。

## 10. n=10 formal gate pass probability 是多少?

Tier A:0.125-0.250(12 个 candidate-corpus 中最高 0.250,
c2_d@main;下界 0.125=c2_c@validation);Tier B:0.057-0.242。全部 << 0.90 门槛。绑定条件逐项
最低:D0-D1 gap 0.33-0.51(冻结)、d3_ge_kappa_se 0.44-0.88、
D1-D2 gap 0.34-0.89、D2-D3 gap 0.50-0.85。

## 11. C2 行为密度是否足够?

是(所有候选全部通过,未成为约束):median reference trades
众数 12.0(实测 10-14,双腿口径,门槛 8)、long label rate
2.0-2.4%(门槛 1.5%)——
下调 α/vol 不删机会,密度保持历史水平。

## 12. main 与 holdout 是否各自独立 PASS?

未到达 calibration(gate 概念未执行)。design 的 main/validation
双开发语料各 40 pairs 已执行:两者结论一致(0 合格),不存在
语料间的选择性读取。

## 13. 是否存在任何 pooled 救援?

**否**。R5 唯一 PASS 口径是 strict per-corpus(pooled 仅诊断字段,
`pooled_conditions_r5_diagnostic` 强制标注 `diagnostic_only=True`);
测试锁定"pooled PASS 不能覆盖 strict FAIL"。design 阶段不存在任何
pooled 判定。

## 14. 是否修改过 gate 规则?

**否**。strict per-corpus 规则(含全部 κ×SE 条件、密度门槛、
0.90 功效门槛、maximin 选择、Tier B 机械触发)在 design plan
(r5dp-0c1eb69f…,数据生成前锁定)与 `r5sg-` identity 中冻结;
digest 漂移/网格漂移/code identity 漂移均 fail closed(测试锁定)。

## 15. strict gate 何时锁定?

design plan 锁定于 **任何 design_r5_* episode 生成之前**
(`design-plan-lock` → `design` 两步;`load_locked_design_plan`
校验 plan digest + 候选网格 + code identity 三重不漂移)。

## 16. V2 在新 fit banks 上是否通过?

未到达(preprocess_fit_calibration_r5 / holdout_r5 / qualification_r5
均未生成;§35 FAIL 路径禁止后续伪 artifact)。V2 复用面在测试级
验证通过(三层哈希/envelope 重载/篡改拒绝/无界空间/对抗探针)。

## 17. C1/C3 在新语料上是否通过?

未到达(C1/C3 的重新资格验证在 calibration/final 阶段;design 只
授权 C2)。R4 继承值黄金绑定验证通过。

## 18. final preflight 是否完全未访问 final seeds?

是(设计+测试双重保证):sealed preflight 不调用 `derive261_seed`
(monkeypatch 测试断言零 final-namespace 调用);static preflight 仅用
`ppo_smoke_r5`(非 final)。本轮 preflight 子命令未在正式链上执行
(design FAIL 即停)。

## 19. exposure marker 何时写入?

**从未写入**(final 未执行)。marker/ledger 均不存在;
`qualification_r5_exposed()=False`;`qualification_r5` /
`preprocess_fit_qualification_r5` namespace 从未被派生
(`qualification_r5_locked_before_use=True`)。

## 20. final 是否只执行一次?

未执行(0 次)。exposure 硬合同(原子 O_EXCL/单向状态机/ledger
兜底/无 delete API/flock 互斥)已实现并被 55 项测试锁定,本轮未消耗。

## 21. 是否发生任何 crash?

正式链无 crash(audit/design/smoke 全部正常退出;
design_run.log 无 traceback)。测试与冒烟中亦无。

## 22. 120 pairs 结果是什么?

未执行(design FAIL,final 不启动)。

## 23. C1/C2/C3 各自结果?

- C1:R4 D3 候选值继承绑定通过黄金验证;新语料资格未执行;
- C2:Tier A 0/6 + Tier B 0/3 合格(design FAIL 的直接原因);
- C3:同 C1。

## 24. full-cold 结果?

**未运行**(§32:仅 final qualification PASS 后才允许;本轮 FAIL)。

## 25. C3 Branch D 是否仍开放?

**是**(`c3_ppo_branch_d_remains_open`;R5 不解决 C3 scratch PPO /
BC fine-tune 破坏 / critic-update dynamics)。

## 26. R5 最终 PASS/FAIL?

**FAIL**(design 阶段诚实 FAIL;禁止 conditional pass)。

## 27. Stage 2.6.2 正式状态?

**FAIL**(未变;R5 未触碰 2.6.2 corpus;input lock 对 api.py 的
R5 迭代登记使 2.6.2 测试套件 150 项全绿)。

## 28. 建议的下一步是什么?

R5 的失败把约束边界标定清楚了:**在 n=10 正式规模下,C2 ladder
相邻间距的功效不足是 ladder 全局性质(D0-D1 间距 0.0054-0.0061 vs
κ×SE≈0.0063-0.0070),任何仅动 D2/D3 的授权都无法达标**。建议
独立审查在以下方向中决策(需新任务书授权,本轮不自动开始):

1. **R6:ladder 全局重校准**(授权扩展到 C2-D0/D1 的 α/κ 轴,扩大
   全部相邻间距;须重新审视"同族四档同一能力"的课程语义);
2. **统计口径层**:重新预注册正式规模(n=10 → 更大 n)或难度/
   间距的统计定义(pair-cluster 方差缩减,如噪声配对结构)——注意
   这触碰 §19 的规则冻结边界,必须在新迭代开头完成;
3. **优先转 C3 PPO Optimization Repair**(Branch D),把 2.6.1 的
   课程资格问题挂起待审——C1/C3 的 V2 与 D3 候选证据链在 R4/R5
   中均已建立且未被污染,可复用。

---

## 附:治理与证据完整性

- 历史证据零覆盖:repair1-4 / report / stage2_6_2 全部只读;
  R2 plan digest、262 R2 diag digest、R4 pack digest、vendor pin
  开机核验一致(audit `digests_match=True`);
- namespace:`r5` 14 个 namespace 与全部历史(含 `_r4`)及 2.6.2
  namespace 零碰撞(3000 seeds/namespace 枚举);Tier B namespace
  仅在机械授权后访问;
- 种子纪律:design plan 锁定先于任何 design episode;
  calibration_r5 / qualification_r5 / preprocess_fit_*_r5 均零访问;
- 测试:R5 新增 7 文件 55 项;2.6.1 全套 251 项、2.6.2 全套 150 项、
  2.6.2 input-lock 10 项全部通过;PPO 256-step smoke PASS
  (基础设施验证,V2 outer 无界空间 + SB3 check_env);
- artifacts:`stage2_6_1/artifacts/repair5/`(16 个文件;
  FAIL 路径未制造 calibration/preflight/qualification 伪 artifact;
  `r5_power_analysis.json` 由分析脚本从 tier results 派生,
  provenance 已注明)。
