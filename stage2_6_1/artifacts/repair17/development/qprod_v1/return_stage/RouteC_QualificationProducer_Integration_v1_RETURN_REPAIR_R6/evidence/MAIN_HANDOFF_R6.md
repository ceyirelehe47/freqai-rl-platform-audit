# QProd 返修轮6(R6)reviewer 交接(第六次 NOT_CLOSED,C15 后,Q1 同根)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: 内容 C15=1139887e + 封包 HEAD c9e28ce3(R5 内容 PASS+冷读 PASS, 保持; 本轮核现场 HEAD=remote=c9e28ce3 未前进)
- 本轮触发: ChatGPT 第六次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C16=f45958ad**(R6 修复;证据件随后)
- 输入原件: `REVIEWER_ADDENDUM (5).md`(用户指定 Downloads 18:56 版, 已归档 `.../qprod_v1/repair_round6_notclosed/REVIEWER_ADDENDUM_R6_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(5);REVIEW.md/(1).md 为 2026-09-29 R25 旧件(不属本轮, 未误用)。原 22 项矩阵: `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已接受面(addendum (5) "保留已验内容",不重开)
C15 三反例修复(recall 矛盾/tail 子条件 False/坏 replay 数值删 flag);Q2/Q3/R01+R25/TB 结项;C15 适用 r21 原件已独立核验完整——本轮只做 C16 新候选适用验证,C15/C14 记录不改签。65 用例中 1 未批早停观察不作否决;统计负结果保留。

## R6 修复映射(仅 Q1 同根一般规则;非 5 个编号特判)
**原则**: 无 fixture 纯判定路径缺必需子依据≠True(C14 语义回归);派生声明必须与来源+派生公式重算一致;各层判定不可矛盾。
- (a) **ova K 链完整对账**: k_mean_model/k_mean_validation(在场)必须等于 direct_generator.<corpus>.aggregate.k_mean(来源,生产端同源字段);k_abs_diff 必须等于 |k_m-k_v|(派生);重算差值>k_tolerance 拒;k_modes_consistent=True 与重算矛盾记 disc。来源 1/1 而派生 1/4、差值 0 → 拒。同规则补 recall abs_diff 对 |recall_model-recall_validation|
- (b) **无 fixture 缺件拒**(C14 语义回归,addendum 13 行): ova 必需子键(recall_model/recall_validation/abs_diff/tolerance/recall_modes_consistent/k_mean_model/k_mean_validation/k_abs_diff/k_tolerance/k_modes_consistent)+fpb.bitwise_ok 缺任一 → once_vs_attempts_consistent=False(显式 disc"缺必需子依据");bitwise_ok 回归 `is True` 判定(缺失≠True)。tail per_corpus 布尔子依据(exact_noise_replay_ok/bounds_ok_all_positions)缺失 → 该 corpus 拒(缺失≠True,不能只靠 ok=True)。fixture 双重态: 缺失键如实列入 fixture_delegated(标注非静默 True),在场键仍对账(委托不可掩盖在场矛盾数值——R5 原则保持并扩展到 K 链)
- (c) **gk 分层一致**(生产规则 r17_global_k `base["pass"] = verdict=="PASS"`): pass==(verdict=="PASS") 矛盾拒;final.verdict(在场)≠顶层 verdict 拒;无 fixture 缺 verdict/pass 拒;INDETERMINATE 拒保留(not_indeterminate 语义不变,"不是不决"≠"已经 PASS")
- r4 结构用例正例夹具升级为支撑完整形态(原夹具即 R6 语义下应拒的缺件形态;其 MC 漂移/CI/replay 变体断言不变——不是删测试求绿)

## 复现与修复证据(WSL 真实依赖,零生成/零 MC/零 fit/零 optimizer;直调 pure helper 记录 fixture_mode=False)
- 修前复现 5/5(C15 字节): `repair_round6_notclosed/REPRO_R6_PRE_FIX.py`
  — c1 K 来源 1/1/派生 1.25-1.0/差值 0: all_consistent=True(洞)
  — c2 fpb.bitwise_ok 删除: True(洞;C14 会拒=实测退化)
  — c3 ova 只余 mode 键: True(洞)
  — c4 tail 子依据删除+ok=True: True(洞)
  — c5 gk verdict=FAIL/pass=True/final PASS: True(洞)
  — ctl 合法对照(支撑完整+精确容差): True(正例保持)
  (首轮探针容差不精确曾被 R5 ova tolerance 漂移检查拒——夹具修正后上述为真实状态)
- 修后(C16 字节)同探针: c1-c5 全 all_consistent=False(逐门 False: ova×3/tail/gk),ctl 仍 True

## 验证(C16 字节)
- 钉 R6 11(合法对照/五反例/K 超容差/INDETERMINATE/fixture 委托标注/fixture 不掩盖在场 K 矛盾)+qprod 面 **167/167**;r8/r9/r10/r17 cue-contract 面仍 29/29
- r21 v6 C16 完整收集审计/生命周期流程(结果入 EVIDENCE_INDEX);262 v10 适用回归;**C15/C14 原记录保留不改签**
- E01 只读复算数值逐值一致(与 R5 版 coords 对拍 identical=True,含 stats_gate_failed 键);E02 R6 七步 rc=0(标注非 261 回归)
- 原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## reviewer 需独立回答
1. 五反例(K 来源/派生差值矛盾、bitwise_ok 缺失、ova 只余 mode 键、tail 子依据缺失、gk FAIL+pass=True)在 checks 全 True+digest 自洽+无 fixture 直调 helper 下是否真拒;各由真实子条件/分层规则拒
2. 是否只补 5 个编号——逐门对账(含 recall abs_diff 派生、gk final 层、fixture 委托边界);rehearsal 自动补 fixture 路径不冒称无 fixture 路径(addendum 19 行: 直调 helper+记录 fixture_mode)
3. 合法支撑完整对照经实际判定/导出/现有消费路径仍通过;纯 helper 无 fixture 路径明确 True/明确 False/缺件三控制
4. C14 拒而 C15 放行的两处(bitwise_ok 缺失/ova mode 键)是否恢复 C14 拒绝语义;R5 三反例+R4 四反例+合法对照不退化
5. 未新增统计门槛/未改停止政策/未跑新研究;早停观察不作否决
6. 全 22 项矩阵对账(C15 已验项验证身份/适用性后复用)

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;主 Agent 不自签;reviewer 模型 zhipu-coding-plan/glm-5.3-flash,平台未返回的后端元数据如实说明
- 内容 PASS 后才封包;增量引用不递归嵌套;回执包外绑定最终 ZIP SHA

## §0 本轮目标原文(逐字)
继续 RouteC_QualificationProducer_Integration_v1 当前任务，不开新研究，不恢复8小时时限。

读取本包 REVIEW.md、REVIEWER_ADDENDUM.md、reference/原目标及22项矩阵。当前收到的R5候选C15=1139887e，封包HEAD=c9e28ce3。基线若已前进，先读取实际差异，不回退已完成工作。Q2/Q3/R01、R25/TrainingBridge已接受成果保留。

本次只返修Q1原八门的同根问题：
1. K均值/来源/派生差值须一致；两侧来源1/1，派生1/4却差值0，不能PASS。
2. 无fixture标记的纯判定路径缺必需子依据不能视为True。特别是bitwise_ok缺失、once_vs_attempts只余mode键；这两项C14会拒、C15反而通过。tail子条件部分缺失同样需拒。不要把rehearsal自动补fixture的路径冒称无fixture路径。
3. Global-K的支撑层/最终verdict/顶层pass须一致，明确FAIL+pass=True不能通过。

先独立复现本包的真实原函数结果，再修同门一般规则，不按5个编号硬编码，不通过一律拒绝合法输入求绿。高成本叶可以隔离，公共判定、锁和来源校验不能替身。通过当前反例只是必要条件；按原22项矩阵对最终候选及受影响面核验，确认旧三个Q1拒绝与合法对照不退化。

把本包REVIEWER_ADDENDUM.md原文交给OMP已配置reviewer，预期zhipu-coding-plan/glm-5.3-flash，真实独立上下文提审。主Agent负责实现/基础自测/修复，不能代写reviewer结论。reviewer FAIL后自行修复再复验，不能偷偷换模型或自签完成。

优先零新增原生/研究MC/fit/optimizer/模型加载的组件复验。原生2/2已耗尽，不因其他配额余额增加第3次运行。正式研究/资格/K11/教学继续NOT_RUN，科学早停定义与阈值不在本次修复范围。

代码修复后形成新候选，按已有约定做适用r21完整收集/auditor/lifecycle/record及262回归，C15历史原件不改写。保留当前有效证据，不重新跑旧研究/旧模型。内容独立PASS之后才封包，reviewer从实际最终ZIP冷读并签包外回执；增量引用可用，不递归嵌套旧大包。

只有独立内容与最终产物验收均通过才报告本轮完成；真实硬限制/越权阻塞如实FAIL或BLOCKED，不能把未完成叫PASS。最终CLOSED仍待ChatGPT终验。
