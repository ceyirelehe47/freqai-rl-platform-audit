# QProd 返修轮12(R12)reviewer 交接(R11 后 Q1 判据与声明依赖分离;第十一次 NOT_CLOSED)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: R11 封包 HEAD=4566c23d(C23 内容 PASS+冷读 PASS 保持)
- 触发: ChatGPT 第十一次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C24=6261d5ef**(R12 修复,已推)
- 输入原件: `REVIEWER_ADDENDUM (10).md`(已归档 `.../qprod_v1/repair_round12_notclosed/REVIEWER_ADDENDUM_R12_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(10);目标提到的 REVIEW.md/HELPER_COMPARISON.json 无对应新件——成对对照由 C22 影子(git show 58d1a9ce)重建,原件 `REPRO_R12_PRE_FIX.py`;原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已接受面(addendum (10) 明示,不重开)
R11 三差值反例已修;C23 ZIP+完整回归原件已核验;Q2/Q3/R25/TB 不重开;历史 112 用例 111 符合+1 未批早停观察非阻塞;本次 120 用例 116 符合/3 同一新退化/1 政策观察。

## R12 修复(同根 Q1: 判据与声明依赖分离;digest 域/黄金向量不变)
- **实际一致性门重算与 k_abs_diff 声明解耦**: `if len(_k_sides)==2:` 即重算 k_derived=|km-kv| 并判门(冻结界优先/声明兜底)——两侧来源与冻结界可得时门必算,可省声明键缺失不得把已知门失败改 True(理由注明"与差值声明副本是否提供无关")
- **声明核对仅在声明在场时**: k_abs_diff 对账(来源相等,R11 回退语义保持)/有限性(R9 先验)/非负性(R11)——不在场只记录该声明缺失(_OVA_REQ 委托/无 fixture 拒)
- 委托不能覆盖已知门失败;双侧真缺(_k_sides 不齐)按原工程/正式缺件边界(R11 derivation_missing 语义保留),不推测未给数据

## 复现与修复证据(WSL 零生成;fixture 双模式;C22 影子对照)
- 修前(C23 字节): G1b 1/4 删kad / G1c 再删kt / G2b' 4/1 删kad → **C23=True vs C22=False**(成对退化);G1a/G2a 完整双版均拒;L1a-c 合法 1/1 双版均 True
- 修后(C24): G1a-c/G2 全拒(理由含"与差值声明副本是否提供无关");L1a-c 保持 True(缺件委托账目含 k_abs_diff/k_tolerance)
- R11 探针(三反例+两侧删法+合法缺件)全保持;R10 六洞全拒;无 fixture 缺必需仍拒

## 验证(C24 字节)
- 钉 R12 7(+R11/R10 联 21);qprod 面 205/205;cue 套件 43/43(六文件)
- r21 v7 C24: (运行中——evidence/regress_v7/full_regression_v7_c24/)
- 262 v19 C24: (运行中)
- E02 R12 七步 rc=0;E01 沿用原件数值(E01_RECOMPUTE_C24.json)
- C23 及更早记录零改写;零新增原生/MC 研究/fit/optimizer/模型加载;原生 2/2 耗尽维持

## reviewer 需独立回答(addendum (10) §当前必须核验)
1. 1/4 完整(kad=3)/只删 k_abs_diff/删 kad+k_tolerance: 均须因在场来源确认门失败而拒;4/1 对称同样
2. 相同删项作用于合法 1/1 真差 0 正例: 工程委托仍过
3. 真正无法取足双侧: 按原工程/正式边界,不推测;无 fixture 缺件继续拒
4. R10 三反例(-0.02/0.02/0.5)在 R11 修复后拒绝行为保持,不回滚
5. 源码两点: 两侧来源+冻结界可得即重算门(不被可省声明键阻断);差值在场另做来源相等/有限/非负检查,不在场只记录缺失
6. 持久工程报告确实经过当前实际函数执行(不把模型推断替代执行);摘要每次正确重算;你的环境复验另记导入路径/摘要/候选/命令/rc,不复用 C23 标签
7. 22 项矩阵逐项确认适用性(未变已接受项可复用);新候选 r21 完整证据+262 回归(我方已跑,原件抽查身份即可);旧 record 不改签

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;reviewer 模型以 task.agentModelOverrides 当前解析为准(2026-10-02 用户已解除 AGENTS.md 硬绑定;addendum(10) 原文写的具体模型名属成文时点,以用户最新指示与配置为准,按实际解析模型执行与记录,不因此 BLOCKED)
- 内容 PASS 后封 R12 RETURN 增量包(链 R11 c7be678d→R10 225683cd→…);reviewer 从最终 ZIP 新目录冷读+绑定 SHA 包外回执;被审内容修改按影响复验
- 不递归委派;零新增原生/研究 MC/fit/optimizer/模型加载;正式资格/K11/教学 NOT_RUN;单重型作业/超时/资源保护保持

## §0 本轮目标原文(逐字)
给当前主 Agent：继续 RouteC_QualificationProducer_Integration_v1 原任务的 Q1 返修。这不是新研究任务，不恢复 8 小时时限、不重置任何配额。先读本包 REVIEW.md 及原任务/22 项矩阵。

R11 的三处旧差值修复和最终包/回归已被独立确认有效；保留。仅修本次确认的一个新退化：C23 把 K 一致性门重算放进 `k_abs_diff 在场` 的条件内。两份直方图、原始/派生均值和冻结界全部可得时，删除冗余 k_abs_diff 后，真实 |1-4|=3>0.05 的失败判据仍被声称 consistent=True 并得到工程 PASS。相同输入 C22 拒绝、C23 放行，详见成对证据。

实现目标：把"根据已有支撑重算实际一致性门"和"核对在场的冗余差值声明"分开。真实支撑充分时即计算门，与 k_abs_diff/k_tolerance 声明副本是否存在无关；字段在场再核对声明。缺件委托不能覆盖已知门失败。保留 R11 的来源回退、负绝对差和此前全部合法缺件控制，不以一律拒绝 fixture 修绿测试。

基础自测后，实际通过 OMP 委派已配置 reviewer，预期模型 zhipu-coding-plan/glm-5.3-flash，独立上下文。将 REVIEWER_ADDENDUM.md 原文转交，并提供本包原始输入/输出、原任务22项矩阵、实际新候选及全部证据；不要只转述"已修复"。reviewer FAIL 后由你自行修复并复验，不代签、不换 reviewer 求绿、不能沿用 C23 PASS。无法调用指定 reviewer 或缺必要权限时明确 BLOCKED。

限定验证：先用零新增生成/研究MC/fit/optimizer/模型加载的 helper 与工程排练检查；对称的1/4和4/1、差值副本有/无、声明容限有/无、合法1/1缺件及上轮三反例必须覆盖。对新候选做适用的 r21 完整证据流程和262回归，C23旧原件不改签。该轮没有新增封包/回归缺件问题，不要重新制造旧事项。

内容验收通过后再封RETURN，reviewer从最终ZIP新目录冷读并签绑定SHA-256的包外回执；任何被审内容修改则按影响复验。全部必需项完成才能报告"独立reviewer与最终包核验通过，待ChatGPT终验"。

Q2/Q3/R25/TrainingBridge保持已接受状态，原生2/2耗尽，不启动第三次；不启动正式资格/K11/教学，不借用旧配额。无默认总时限但单重型作业、超时及资源保护保持。原授权内自行修复，遇真实硬限制或越权才如实报告未完成。
