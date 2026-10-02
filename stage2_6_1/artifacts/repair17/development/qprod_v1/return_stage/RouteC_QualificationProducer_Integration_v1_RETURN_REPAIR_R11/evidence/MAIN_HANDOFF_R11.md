# QProd 返修轮11(R11)reviewer 交接(R10 后 Q1 派生差值依赖复验;第十次 NOT_CLOSED)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: R10 封包 HEAD=58d1a9ce(C22 内容 PASS+冷读 PASS 保持)
- 本轮触发: ChatGPT 第十次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C23=9dcb5a54**(R11 修复);证据链 9dcb5a54→d855033c→1ccd206b(已推)
- 输入原件: `REVIEWER_ADDENDUM (9).md`(已归档 `.../qprod_v1/repair_round11_notclosed/REVIEWER_ADDENDUM_R11_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(9);用户目标提到 REVIEW.md/validation/PAIRED_DIFFERENCE_CHECKS.json 无对应新件;原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已验面(addendum (9) 明示,不重开)
R10/C22 旧 104 项 103 符合+1 政策观察不阻塞;7 旧失败已拒;C22 r21/262 归档与最终 ZIP 验证成立;reviewer 53 项本地重放全符合;Q2/Q3/R25/TB、合法工程缺件委托、历史原件与配额保持。

## R11 修复(同根 Q1:派生差值依赖;digest 域/黄金向量不变)
- **k_abs_diff 重算来源依赖回退**: `_k_sides` 每侧取值 = ova k_mean_*(在场,单键循环已验)→ 回退 dg.<corpus>.aggregate.k_mean 原始来源;两侧均可得即重算绝对差并对账 k_abs_diff——删任一冗余派生副本(或再删自报 k_tolerance,冻结界由直方图重算)不得屏蔽在场矛盾差值
- **负绝对差自身非法**: k_abs_diff<0 独立拒(|·| 恒非负,与重算来源可得无关)
- **双侧真缺**(ova 副本+dg 来源都缺): fixture 委托(derivation_missing 账目)/无 fixture 拒(缺失≠True)
- 不按案例名打补丁: 修的是派生差值一致性的依赖路径

## 复现与修复证据(WSL 零生成;fixture 双模式)
- 修前(C22 字节)3 洞 fixture 逃逸: C1b kad=-0.02+删kv/C2b kad=0.02+删kv/C3b kad=0.5+删kv+删kt — `REPRO_R11_PRE_FIX.py`(另有"删 k_mean_model"同根变体同样逃逸)
- 修后(C23): 三洞全拒(两侧删法都拒,理由含"回退 direct_generator 原始来源重算");C4 kad=0 相同缺件合法通过;C4b 再删自报容限通过(委托账目含 k_tolerance)
- R10 六洞+控制复跑不退化;无 fixture 缺必需字段仍拒

## 验证(C23 字节)
- 钉 R11 7;qprod 面 198/198;r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C23: run 20261002_142616 rc=0, 2739/0F/7skip, record 9c14597a(commit_a_sha=9dcb5a54), verify 2739/2253/164 — evidence/regress_v6/full_regression_v6_c23/(首跑目录沿旧 OUT 名 v6_c21 内容正确已规范重命名+runner 修复)
- 262 v18 C23: 240 RC=0 junit 240/0(meta 绑定 9dcb5a54;首跑文件名沿旧标签已规范重命名+补 junit)
- E02 R11 七步 rc=0;E01 沿用原件数值(E01_RECOMPUTE_C23.json)
- C22 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## reviewer 需独立回答(addendum (9) §只验同一 Q1 不变量)
1. kad=-0.02 完整拒;只删 k_mean_validation(或 model)仍拒
2. kad=0.02 完整拒;删任一侧派生均值仍拒(与来源实际差值 0 矛盾)
3. kad=0.5 完整拒;删派生 validation 均值+自报 k_tolerance 仍拒(冻结界可从直方图重算)
4. kad=0 相同缺件合法工程委托通过;两侧顺序/合法多键/前轮反例保持;无 fixture 缺必需字段仍拒
5. 单项合法性/来源可算关系/跨字段完整性分开;摘要正确重算;真实输入输出命令 rc 模块路径留存;你的环境复验另记候选/解释器/导入路径,不沿用 C22 标签给新候选背书
6. 检查当前 K 依赖路径(不仅断言三个编号变绿);22 项矩阵对账(未变项核适用性复用)
7. 新候选完整 r21/262 回归(我方已跑,原件齐,抽查身份即可);C22 原件保持原字节

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;reviewer 模型 zhipu-coding-plan/glm-5.3-flash
- 内容 PASS 后封 R11 增量包(链 R10 225683cd→R9 372996b9→…,引用不嵌套);回执包外绑定最终 ZIP SHA
- 不递归委派;零新增原生/研究 MC/fit/optimizer/模型加载;正式资格/K11/教学 NOT_RUN

## §0 本轮目标原文(逐字)
继续当前 RouteC_QualificationProducer_Integration_v1，处理 R10/C22 独立终验。

读取本包 REVIEW.md、validation/PAIRED_DIFFERENCE_CHECKS.json 及原始任务/22项矩阵。
本轮不是新研究任务，不重置配额，不恢复8小时时限，不重开Q2/Q3/R25/TrainingBridge。

已确认：R10的7个旧反例均已修好，最终ZIP及C22适用r21/262归档通过；保留这些成果。
剩余只有同一Q1：K差值一致性仍被冗余派生字段缺失屏蔽。原始均值1/1及两份直方图完整，
差值-0.02、0.02或0.5本来拒绝；删一个派生均值（第三例再删声明容限）后却17步PASS。
先验证并保留失败证据，再从依赖关系修复；不只按案例名打补丁，不一律拒绝合法委托。

独立验收必须实际调用已配置reviewer，预期zhipu-coding-plan/glm-5.3-flash。
把 REVIEWER_ADDENDUM.md 原文及原任务、固定候选、原始结果交给它；主Agent不代写结论。
FAIL由主Agent在当前任务内修复后再次独立复验；不可沿用C22的PASS。

反例先用零生成/零研究MC/零fit/零optimizer/零模型加载方式复验。
原生2/2已耗尽；不得进行第三次原生运行。适用新候选的完整r21/262回归照原授权执行。
后续candidate/代码路径和摘要必须实际读取，不沿用助手脚本内的历史C22标签。
内容PASS后最终ZIP冷读、包外回执齐备才可报告"已完成，待ChatGPT独立终验"；
真实硬限制或权限阻塞则如实未完成，不代签CLOSED。
