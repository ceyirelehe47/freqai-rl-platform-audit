# QProd 返修轮8(R8)reviewer 交接(第七次 NOT_CLOSED,R6/R7 合并包终验后 Q1 限定返修)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: C17b=079713cd(V3 PASS)+证据 b3397972+封包 044a0307(R6 ZIP ad48db11 冷读 PASS 保持);核现场 HEAD=remote=044a0307 未前进,无回退
- 本轮触发: ChatGPT 第七次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C18=cec19ae5**(R8 修复)+证据 e4553c88(已推)
- 输入原件: `REVIEWER_ADDENDUM (6).md`(已归档 `.../qprod_v1/repair_round8_notclosed/REVIEWER_ADDENDUM_R8_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(6);REVIEW.md/(1).md 为 2026-09-29 R25 旧件(不属本轮,未误用)。原 22 项矩阵: `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`。目标提到的 RESULT/README_REPLAY 在 Downloads 无对应新件(如实说明)

## 已验面(addendum (6) "已验成果",不重开)
五旧反例 C15→C17b 由接受变拒绝保持;R6 发现的 K 来源缺失/容限漂移修复保留;Q2/Q3+C17b r21 归档保持;历史环境/t09 失败如实保留;E01 不重新生成(只读复算);1 未批早停观察不作否决

## R8 修复映射(仅 Q1 同根收口;digest 域/黄金向量/研究政策不变)
- **K 输入闭合**(addendum §11): histogram 在场时频数须非负整数、Σ频数==aggregate.n_events(生产端 r17_noise_replay k_counts 每 unique event 恰计一次: `k_counts[e["k_actual"]] += 1` 遍历 events,n_events=len(events))、加权均值 Σ(k·c)/Σc==aggregate.k_mean(均值与方差共用同一已验支撑——R7 的 pooled se 同一直方图)。{4:110} 声明均值 1/ova 1/1/差 0/容限 .05 拒;{1:109} 对 n_events 110 拒;{1:110,2:-1} 负频数拒;键序重排天然无关(dict 遍历)
- **在场非法≠未提供**(§13): {"not-a-number":110} 无 fixture 拒(既有)+fixture 在场同样拒——R7b 的 k_tolerance_frozen_malformed 委托撤销,改为在场非法数值任何模式 k_ok=False(缺高成本叶≠坏支撑);缺件(直方图整块缺失)fixture 仍如实委托;合法手工输入(双键直方图+冻结容差精确同步+键序重排)fixture 与无 fixture 均通过(不一律拒绝 fixture)
- **gk 子门支撑**(§15): graph_integrity_ok=False 与 verdict=PASS/pass=True/final PASS 并存拒(生产规则 r17_global_k: `if not all(g.integrity["ok"]): base.update({"graph_integrity_ok": False, "pass": False, "verdict": "FAIL"...}); return`——完整性失败即 FAIL 早退);无 fixture PASS 缺 final 必需依据拒(生产端 PASS 必经 tier1/tier2,final 恒在场);FAIL 早退无 final 不加拒(与生产一致);fixture 缺失如实委托(global_k_audit.final)
- **tail 语料覆盖**(§15): 预期语料集合=direct_generator 上下文语料,不由 per_corpus 自身键集合自列;报告两语料而 per_corpus 仅 model → 无 fixture"缺整份 validation 支撑"拒;fixture 委托(tail_mirror_bound_integrity.per_corpus[validation]);在场语料坏子依据拒保持(R5/R6)

## 复现与修复证据(WSL 真实依赖,零生成/零 MC/零 fit/零 optimizer;直调 pure helper 记录 fixture_mode)
- 修前复现 7/7 洞(C17b 字节): `repair_round8_notclosed/REPRO_R8_PRE_FIX.py`
  — h1 validation 直方图 {4:110} 声明 k_mean 1/总量 110/ova 1/1/差0/容限.05: all_consistent=True(洞)
  — h2 {1:109} 对 n_events 110: True(洞)
  — h3 {1:110, 2:-1}: True(洞)
  — h4 gk graph_integrity_ok=False+PASS/pass/final PASS: True(洞)
  — h5 gk PASS 缺 final: True(洞)
  — h6 tail per_corpus 仅 model(dg 两语料): True(洞)
  — h7 fixture+{"not-a-number":110}: True(洞,R7b 委托放行)
  — ctl 合法(无 fixture)/ctl 合法(fixture)/ctl3 双键键序重排+冻结容差同步: 全 True(正控制)
- 修后(C18 字节)同探针: h1-h7 全拒(逐门: ova×3/gk×2/tail×1/ova-fixture×1),三正控制保持 True

## 验证(C18 字节)
- 钉 R8 12(七反例+三正控制+FAIL 早退无 final 不加拒+fixture 委托标注+在场坏子依据不退化);qprod 面 **182/182**;r8/r9/r10/r17 cue-contract 面 **29/29**
- r21 v6 C18 完整收集审计/生命周期: run 20261002_013343 **rc=0, 2711/0F/7skip, record f9e44621, verify 2711/2225/161(一次通过)** — evidence/regress_v6/full_regression_v6_c18/
- 262 v13 C18: 240 RC=0 — evidence/regress262/regress262_v13_c18
- E01 只读复算: E01_RECOMPUTE_C18.json(coords 与 R5-R7 逐值 identical)
- E02 R8 七步 rc=0(标注非 261 回归)— evidence/e02/
- C17b/C17/C16/C15 记录全部不改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## reviewer 需独立回答
1. addendum (6) §11 三反例(validation {4:110} 声明均值 1/{1:109} 总量不符/负频数)是否真拒,且由 histogram 频数/总量/均值闭合规则拒(非编号特判);顺序重排不拒
2. §13 同一非法 {"not-a-number":110} 无 fixture 拒后,fixture(rehearsal 自动补标记)是否同样拒在场非法;合法手工输入 fixture 是否仍通过(两种证明区分: rehearsal 加 fixture 的路径不被冒称无 fixture 路径,直调 helper 记录 fixture_mode)
3. §15 gk integrity False+PASS 并存拒、无 fixture PASS 缺 final 拒、tail 两语料缺 validation 拒——预期集合是否来自有效上下文(direct_generator)而非待验字典自列;是否有"遍历给出的 key"冒充覆盖
4. 旧 R5/R6/R7 反例与合法对照不退化;digest 域/黄金向量未动;P3 未被借来延期内部矛盾(新检查在旧 digest 不变下按内容正确性实现)
5. 全 22 项矩阵对账(C15-C17b 已验项核对身份/适用性后复用)
6. r21/262/E01/E02 身份与适用性;C17b 历史记录未改写

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;主 Agent 不自签;reviewer 模型 zhipu-coding-plan/glm-5.3-flash,平台未返回的后端元数据如实说明
- 内容 PASS 后才封包(增量引用基包 R5/R6 链,不递归嵌套);回执包外绑定最终 ZIP SHA

## §0 本轮目标原文(逐字)
继续 RouteC_QualificationProducer_Integration_v1 当前任务；这是 R6/R7 合并包独立终验后的 Q1 限定返修，不是新科研任务。

先读 REVIEW.md、原QProd NEXT_GOAL/22项 ACCEPTANCE_MATRIX、本次原始 RESULT 与 README_REPLAY。保留已修的五个旧Q1反例、Q2/Q3、适用r21回归原件、R25/TB结项。当前候选C17b=079713cdc043237da4e6b0402fb7f818a818876f，远端封包044a0307；出现后续提交先核对真实diff，不回退或覆盖它。

仅修：
1. K histogram 的结构/频数/总量/均值与原report及ova来源一致，均值差及方差容限共用同一已验支撑。直方图validation全4却声明均值1、总量不符或负频数不能通过。
2. fixture不能把已经提供的非法histogram委托为True。缺高成本叶与坏支撑不是一件事；合法手工输入仍可通过。
3. Global-K在场graph_integrity_ok=False不得与PASS并存；无fixture的PASS缺final依据、tail缺整份validation支撑必须拒绝。依据集合由有效上下文/原合同决定，不由待验字典自列。

本次不要求改变旧audit digest域或黄金向量，不以已登记的全自洽K字段hash覆盖P3单独否决。上述都可在旧digest不变下按内容正确性修复。

把 REVIEWER_ADDENDUM.md 原文交给实际配置的 OMP reviewer(zhipu-coding-plan/glm-5.3-flash)。你负责修复，独立reviewer根据原要求和原件判定；FAIL在原任务内自行修复再复验，不能代签、换标准或只验自己缩选的清单。指定reviewer无法调用则BLOCKED，不退回自验收。

不恢复8小时限制，不重置原生2/2额度；零新增原生/研究MC/fit/optimizer/模型加载。全回归按既有授权范围与资源保护执行，新语义候选使用既有r21完整证据流程和262适用回归；不把旧记录改签。正式资格/研究/K11/教学不授权。

独立内容PASS后封包，reviewer从实际最终ZIP冷读核验，绑定最终SHA的回执置于包外。确认最新源码、真实输入/输出、回归与reviewer原件齐备才能报告完成，最后仍待ChatGPT独立终验。
