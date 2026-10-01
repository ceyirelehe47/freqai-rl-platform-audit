# QProd 返修轮9(R9)reviewer 交接(R8 后 K 判定限定复验;第八次 NOT_CLOSED)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: R8 封包 HEAD=21e7aaee(C18=cec19ae5 reviewer V1 内容 PASS+冷读 PASS 保持);核现场 HEAD=remote=21e7aaee 未前进,无回退
- 本轮触发: ChatGPT 第八次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C19=8c99d7d3**(R9 修复)+证据 1877f4a9(已推)
- 输入原件: `REVIEWER_ADDENDUM (7).md`(已归档 `.../qprod_v1/repair_round9_notclosed/REVIEWER_ADDENDUM_R9_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(7);用户目标提到 REVIEW.md/reference_task//probes/final_run/RESULT.json 无对应新件——F:/trading/reviewer_qprod_v1/probes 为 09-30 R25 旧轮件,非本轮;原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已验面(addendum (7) 明示,不重开)
七个旧反例确实已修;R8 独立终验/候选链/C18 归档回归保持;Q2/Q3/R25/TB 不重开;历史 digest 域/黄金向量不改;1 未批早停观察非阻塞。

## R9 修复映射(仅两个同根 K 校验问题)
- **缺件不可屏蔽在场坏件**(§1): histogram 闭合验证重构为独立层——每份在场 K 支撑先独立验证(结构 isfinite/频数非负整数/精确总量/均值对源),缺件分支只处理"未提供"(fixture 委托/无 fixture 拒)。同一坏直方图删除另一语料直方图(fixture 自动加标志)仍拒;删除 ova 派生均值(k_mean_model)不再跳过两份原始直方图闭合(原实现 histogram 验证在 `if ova.k_mean_model is not None and ova.k_mean_validation is not None:` 块内)。委托名保持 R7 兼容(once_vs_attempts.k_tolerance_frozen),不传染在场坏输入。
- **非有限数与精确总量**(§2): JSON 字符串键 "nan"(float() 可解析)/NaN 字面量键/k_mean 源 "nan"/ova k_mean_*、k_tolerance、k_abs_diff NaN——全部 isfinite 先验显式拒(NaN 使 abs(x-y)>1e-9 与 <= 比较静默 False 绕过的路径封死);Σ频数==n_events 精确比较(int() 截断吞 110.5 修复,非数值 "110" 字符串拒);小数频数 {1:109.5} 双模式拒;整数 111 不等控制拒。
- 不针对案例名加条件: 验证为内容语义层(独立 per-corpus 闭合),非编号特判。

## 复现与修复证据(WSL 真实依赖;零生成/零 MC/零 fit/零 optimizer;直调 pure helper 记录 fixture_mode)
- 修前(C18 字节)8 洞: `repair_round9_notclosed/REPRO_R9_PRE_FIX.py`
  — r1 坏直方图+删 model 直方图+fixture: True(洞:缺件屏蔽在场坏件)
  — r2b 坏直方图+删 ova.k_mean_model+fixture: True(洞:派生缺失跳过闭合)
  — r3/r3b/r3c "nan" 键/NaN 字面量键: True(洞:非有限绕过)
  — r4 n_events=110.5: True(洞:int 截断)
  — r5 n_events="110": True(洞:字符串静默 int)
  — r6 k_mean 源 "nan": True(洞:来源非有限绕过)
  — r7/r8 ova NaN: 恰被声明门拒,但缺件组合可绕过(加固)
- 修后(C19 字节)同探针: 11/11 反例全拒(含双模式),三正控制+R8 反例保持
- 边界用例: 合法删 ova 派生均值 fixture 委托保持/单键 {1:110}=110 事件非样本不足(冻结容差=0.05 正确)/两语料直方图都缺 fixture 双委托+无 fixture 拒

## 验证(C19 字节)
- 钉 R9 11; qprod 面 182/182; r8/r9/r10/r17 cue-contract 面 29/29
- r21 v6 C19: run 20261002_041458 rc=0, 2723/0F/7skip, record 2d61d8f8, verify 2723/2237/162(一次通过) — evidence/regress_v6/full_regression_v6_c19/
- 262 v14 C19: 240 RC=0(OUTPUT_MOVE_NOTE: 初次 sed 未命中先落 R6 目录,已整组迁移+R6 字节还原)
- E02 R9 七步 rc=0(evidence/e02/,输出目录 repair_round9_notclosed)
- E01: E01_RECOMPUTE_C19.json 沿用 R8 原件数值(E01 原生零改动;本轮源码变更仅 cue-contract 语义重算面)
- C18 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## reviewer 需独立回答
1. §1: 先验证完整合法正例+单项坏直方图拒;同一坏直方图删除另一语料直方图(fixture 自动添加)仍拒;删除一个 ova 派生均值是否跳过在场原始直方图——基础合法性/内部关系是否先于跨语料完整性分支(非案例名特判)
2. §2: "nan" 字符串键/NaN 不产生可用 K 支撑;直方图总数 110 对 n_events=110.5 拒(无 int 截断);整数 111 不等控制/小数频数控制/合法多键方差均值容限/顺序重排继续成立
3. 委托边界: 明确缺失的高成本输入 fixture 委托保持且不传染;合法手工正例可过
4. R5-R8 反例与正控制不退化;digest 域/黄金向量未动;接码格式风格未被升级为缺陷
5. 22 项矩阵对账(已验项核身份/适用性后复用);r21/262/E01/E02 身份与适用性;C18 原件未改签
6. 你可真实 WSL 复验并提交实际导入路径/摘要/固定候选与原始输出;不把本轮脚本候选标签当未来身份凭证

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;主 Agent 不自签;reviewer 模型 zhipu-coding-plan/glm-5.3-flash,平台未返回的后端元数据如实说明
- 内容 PASS 后封 R9 增量包(链 R8 083c2065→R6 ad48db11→R5 0324c40d→...→C9,引用不嵌套);回执包外绑定最终 ZIP SHA;不把回执塞回其所核验 ZIP

## §0 本轮目标原文(逐字)
继续当前 RouteC_QualificationProducer_Integration_v1；这不是新研究任务。

读取 REVIEW.md、REVIEWER_ADDENDUM.md、reference_task/ 原QProd要求和22项矩阵，以及 probes/final_run/RESULT.json 的实际反例。

R8 C18=cec19ae5410cc48425bec4dfd23d31e01847f9b4，封包HEAD=21e7aaee，尚未通过ChatGPT独立终验。上轮七例已修，包身份和C18归档回归通过；剩余仅为K在场输入校验被缺件分支跳过，以及非有限数/事件总量截断。

你负责修复和基础自测，实际委派用户已配置的reviewer（zhipu-coding-plan/glm-5.3-flash）验收；把REVIEWER_ADDENDUM.md原文交给它，提供原要求与固定候选。FAIL自行修复复验，不能自己判任务完成或沿用C18旧PASS。

重点不是再次只修案例编号：每份在场K支撑先独立验证，再处理缺件/跨语料计算；检查缺另一份直方图或派生均值不再掩盖坏支撑。非有限K与n_events的小数信息不得在计算/转换中被吞掉。保留合法完整、多键、重排及旧反例正反控制。

主Agent和reviewer可以在隔离目录用合成输入或现有原件验证，不生成新研究数据。原生2/2额度已耗尽，绝不重置或第三次原生运行；不恢复单轮8小时限制，保留单重型任务和资源保护。不重开Q2/Q3/R25/TB，不改变历史digest域/黄金向量，不批准正式资格/K11研究/教学训练。

新语义候选完成适用的r21完整审计回归与262回归，原C18记录保持原样。独立内容PASS后封包，reviewer冷读最终ZIP并出绑定实际摘要的包外回执，全部交齐才能报告本轮实现与独立验收完成；CLOSED仍待ChatGPT终验。
