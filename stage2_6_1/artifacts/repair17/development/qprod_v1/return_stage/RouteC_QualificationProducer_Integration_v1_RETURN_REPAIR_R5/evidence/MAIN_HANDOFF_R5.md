# QProd 返修轮5(R5)reviewer 交接(第五次 NOT_CLOSED,C14 后,Q1 限定)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: 封包 HEAD 3d56f5c0 + 内容候选 C14=3d2193e2(R4 内容 PASS+冷读 PASS, 保持)
- 本轮触发: ChatGPT 第五次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C15=1139887e**(R5 修复单提交;证据件随后)
- 输入原件: `REVIEWER_ADDENDUM (4).md`(用户指定 `C:\Users\15027\Downloads\REVIEWER_ADDENDUM (4).md` 06:16 版, 已归档 `.../qprod_v1/repair_round5_notclosed/REVIEWER_ADDENDUM_R5_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(4), **无 REVIEW.md、无 probes/final_cases/RESULT.json**(goal_incoming 的 probes/RESULT.json 为 R25/TB 旧件不误用)。原 22 项矩阵: `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已接受面(addendum "已接受的范围",不重开)
Q3 条目级 500 对 2+脱钩已拒;C14 实际 r21 collect/auditor/lifecycle/record 已核验;Q2 异常保守预占/低正数额度拒绝;有效统计负结果保留;R25/TB 保持。1 项未批早停政策不作否决(未改科学定义)。

## R5 修复映射(仅 Q1 公共判据;通用纯判据,非三个编号特判)
**原则**: 八门的派生声明(布尔/摘要)必须与**在场子输入/数值影子**一致;生产与复验共享 core 冻结纯判据;委托不可掩盖在场坏数值。
- (a) ova `recall_modes_consistent=True` 不再直接采信——从 direct_generator 在场数值重算: 源一致(ova recall 字段=对应语料 empirical_recall)、数值判据 |rec_m-rec_v|<=max(3*sqrt(se_m²+se_v²),0.005)(冻结公式)、ova.tolerance 漂移检查;矛盾/超限即拒且记录声明与重算矛盾
- (b) tail integrity per_corpus 的 ok/pass 必须等于子输入合取(exact_noise_replay_ok≠False ∧ bounds_ok_all_positions≠False ∧ violations 空 ∧ n_violations==0)——子输入矛盾由**真实子条件**拒(不只看上层 ok)
- (c) fixture 委托收紧: replay_ok 缺失走委托前必须核在场数值影子 max_replay_abs_error<=REPLAY_TOL(1e-12, 与 noise_replay.REPLAY_TOL 交叉断言);坏数值保留+删除 replay_ok → 委托被否决,FAIL 不变 PASS;且独立于字段在否,坏 replay 数值一律拒
- (d) 正式报告(无 fixture 标记)缺支撑字段仍 False(直调 helper 无 fixture 控制正确拒绝——addendum 21 行边界已按此实现,rehearsal 入口标注 fixture 属合法双重态)

## 复现与修复证据(WSL 真实依赖,零生成/零 MC/零 fit/零 optimizer)
- 修前复现 3/3(C14 字节): `repair_round5_notclosed/REPRO_Q123_ROUND5_PRE_FIX.py`
  — case1 ova recall 0.30/0.95+consistent=True+digest 自洽: verdict=PASS(洞)
  — case2 ti 子项 exact_noise_replay_ok=False/ok=True: verdict=PASS(洞)
  — case3 max_replay_abs_error=0.25+删 replay_ok: verdict=PASS(洞)
- 修后(C15 字节)同探针: 3/3 verdict=FAIL;case2 ti_recomputed=False(真实子条件);case3 委托被否决(delegated 列表不再含 model.replay_ok)

## 验证(C15 字节)
- 钉 R5 新增 7+qprod 面 **156/156**;r8/r9/r10/r17 cue-contract 历史面 29/29
- 合法对照通过(R5 收紧不误伤);R4 四反例保持;E01 只读复算数值逐值一致(run1 c01 nrv/recall 0.9608/se 0.0283;run2 双坐标保留;K 不足如实 inconclusive)
- E02 R5 七步 rc=0(R01 要素,标注非 261 回归)
- r21 v6 对 C15 完整收集审计/生命周期流程(结果入 EVIDENCE_INDEX);262 v9 适用回归;**C14 原记录保留不改签**
- 原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer

## reviewer 需独立回答
1. 三反例(ova 声明矛盾/ti 子输入矛盾/replay 数值+字段删除)在 checks 全 True+digest 重算自洽下是否真拒;case2 是否由真实子条件拒;case3 委托是否被否决
2. 是否只补了三个编号特判——逐门对账:八个门的输入/冻结规则/派生声明/源对象;同根其余子门(gk/aggregate/bounds/cue_table)规则对账
3. 合法手工 raw 正例经真实 Level A 判断→导出→QualifiedInput 可消费,替身位置明确,无 validator=True
4. 无 fixture 直调控制正确拒绝;rehearsal 入口 fixture 标注不误称无 fixture 路径
5. 未新增统计门槛/未改停止政策;R4 四反例+E01 负结果保持
6. 全 22 项矩阵对账(已确认项验证身份/适用性后复用)

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;主 Agent 不自签;reviewer 模型 zhipu-coding-plan/glm-5.3-flash,平台未返回的后端元数据如实说明

## §0 本轮目标原文(逐字)
继续原任务 RouteC_QualificationProducer_Integration_v1，不另开研究，不恢复8小时时限，不重置原生2/2额度。

当前审阅基线：内容C14=3d2193e24105647f48419ce401016eb442d2baa1；封包HEAD=3d56f5c0a6969e126b797441930b04544e329204。先检查远端和未知在飞工作，不回退或清理别人的修改。

读取本补充包 REVIEW.md、原任务NEXT_GOAL/22项矩阵，以及 probes/final_cases/RESULT.json。Q3条目级关联与C14实际r21归档已通过，不再为旧问题返工；Q2、R25、TrainingBridge及有效统计负结果保留。

本次只继续修Q1公共判据：
- once/attempts数值/差值与direct_generator来源矛盾，但consistent布尔为True、摘要正确，仍整链PASS；
- tail完整性子输入exact_noise_replay_ok=False，但ok/pass=True，仍整链PASS；
- model max_replay_abs_error=0.25、replay_ok=False会拒；删除replay_ok后仍保留坏数值，却因fixture委托变PASS。
不要只补三个编号的特殊判断。逐条核对八个既有门所依赖的输入、冻结规则、派生声明和源对象，生产与复验共享实际纯判据。高成本叶可用明确手工raw夹具，但判定/锁/来源校验不能被委托True取代。不要新增统计门槛或改变科学停止政策。

先在真实WSL依赖下零生成/零MC/零fit/零optimizer复现并修复，保存有效正例、失败原件与修复结果。代码修改产生新候选，用既有r21完整收集审计/生命周期流程及适用262回归获取新候选证据；C14原记录保留，不改签。

必须实际调用用户已配置OMP reviewer（预期zhipu-coding-plan/glm-5.3-flash）。将 REVIEWER_ADDENDUM.md 原文、原任务与本报告/原件一并交给它。主Agent负责修复，reviewer独立判定；FAIL自行修复再提审。模型/工具不可用报告BLOCKED，不自签。

保留 reviewer 独立脚本、夹具和stdout/stderr/results，不能只交结论。实际最终增量ZIP冷读并签包外回执后才能报告完成；不代签ChatGPT CLOSED，不擅自启动正式资格/研究/K11/教学。其余约束见原任务，已接受面只做新变更影响复验。
