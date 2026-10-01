# QProd 返修轮10(R10)reviewer 交接(R9 后 Q1 缺件组合复验;第九次 NOT_CLOSED)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: R9 封包 HEAD=987f6117(C20=52e70a17 reviewer V2 内容 PASS+冷读 PASS 保持);本轮起点核实现场 HEAD=remote=987f6117 未前进
- 本轮触发: ChatGPT 第九次 NOT_CLOSED(目标逐字见 §0)
- 本轮候选: **C21=da5655b5**(R10 修复,已推)
- 输入原件: `REVIEWER_ADDENDUM (8).md`(已归档 `.../qprod_v1/repair_round10_notclosed/REVIEWER_ADDENDUM_R10_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 仅 addendum(8)(05:52);用户目标提到 REVIEW.md/RUN_LOCAL.md/reference_task//validation/PAIRED_MASKING_CHECKS.json/probes/final_run/RESULT.json 无对应新件;原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## 已验面(addendum (8) 明示,不重开)
R9/C20 上轮 91 例 90 符合+1 未批早停观察不阻塞;7 实际失败全拒;reviewer C19 三项发现有价值;原 36 项脚本本地重放 36/36;C20 完整 r21/262 归档+最终 RETURN 字节已核验;Q2/Q3/R25/TB 保持。

## R10 修复(三个同根洞;digest 域/黄金向量不变)
- **K 支撑检查脱离 ova 父级**: K 块(271 行)从 `if once_vs_attempts:` 内整体搬至顶层(搬移脚本逐行 dedent-4,difflib 对比内容 diff=0;`REPRO_R10_PRE_FIX.py`+`tmp_r10/move_k_block.py`)——删除整个 once_vs_attempts(fixture 委托缺 ova)时在场坏直方图("nan" 键/均值矛盾/小数 n_events)仍拒;无 ova else 分支改为 `k_ok AND 委托`(委托不清除在场坏输入)
- **ova 派生均值单键独立**: `_ova_k_nonfinite` 与来源对账循环改为每键在场即验 isfinite+对账(不再以双在场为前提)——单侧 NaN/Inf 另一侧在场或被删除均拒;R7 source_missing 委托语义保持
- **n_events 计数语义**: 两处先验(C20 缺件先验+直方图在场分支)加 `_nef/_nev < 0` 拒——len(events) 恒非负,有限整数检查不代替合法计数检查;-1 直方图在场或同侧直方图删除均拒
- 不按测试名打补丁: 修的是验证层的进入条件与字段独立性

## 复现与修复证据(WSL 真实依赖;零生成/零 MC/零 fit/零 optimizer;直调 pure helper,fixture_mode 双模式)
- 修前(C20 字节)6 洞(fixture 模式 all=True 逃逸;无 fixture 路径因缺件拒——拒绝理由是缺件而非坏件): H1aF no-ova+"nan"键/H1bF no-ova+hist均值4/H1cF no-ova+110.5/H2bF km-NaN另一侧删/H2cF kv-"nan"另一侧删/H3bF nev=-1同侧hist删 — `REPRO_R10_PRE_FIX.py`
- 修后(C21)同探针: 6 洞全拒(理由为新先验语义),无 fixture 路径同样全拒
- 控制保持: 合法双模式/no-ova 合法 fixture 委托 True/无 fixture 缺件拒/单侧派生值合法删除委托 True/R9 反例(ova 在场坏直方图+缺件屏蔽)仍拒

## 验证(C21 字节)
- 钉 R10 6;qprod 面 190/190(含 R5-R9 全部钉);r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C21: run 20261002_063944 rc=0, 2731/0F/7skip, record b3fc0fa2, verify 2731/2245/163(一次通过) — evidence/regress_v6/full_regression_v6_c21/
- 262 v16 C21: 240 RC=0(meta 绑定 da5655b5)— evidence/regress262/
- E02 R10 七步 rc=0;E01 沿用原件数值(E01_RECOMPUTE_C21.json)
- C20 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## reviewer 需独立回答(addendum (8) §同根不变量)
1. 合法完整工程 raw 正例经真实公共判定通过;坏 validation 直方图 ova 在场拒;只删整个 once_vs_attempts 保留同一坏直方图仍拒("nan" 键/均值 4 对声明 1/110.5 三变体)
2. 单个 ova 派生均值 NaN/Inf 另一侧在场拒;只删另一侧仍拒——"两个齐全才检查"≠单字段合法性
3. n_events=-1 直方图在场拒;删同侧直方图仍拒(len(events) 计数语义)
4. 合法缺 ova/缺单侧派生值/缺 hist 委托保持;委托只覆盖真正未提供部分;不以一律拒绝使负例变绿
5. 实际核对入口持久对象 fixture_mode;同输入对照保存真实输入/返回/失败原因(不只证明报告 hash 错误会拒)
6. 原在场坏支撑/部分缺失/合法重排/多键直方图/有限性控制一起复验;你的实际环境复验另记候选/解释器/导入路径摘要,不沿用脚本默认 C20 标签给新候选背书
7. 22 项矩阵对账(已验项核身份/适用性后复用);新候选完整 r21/262 回归(我方已跑,原件齐,抽查身份即可);C20 原件保持原字节

## 边界(不变)
- 最终 CLOSED 由 ChatGPT 独立终验;reviewer 模型 zhipu-coding-plan/glm-5.3-flash,平台未返回的后端元数据如实说明
- 内容 PASS 后封 R10 增量包(链 R9 372996b9→R8 083c2065→…,引用不嵌套);回执包外绑定最终 ZIP SHA;不塞回被验 ZIP

## §0 本轮目标原文(逐字)
继续原 RouteC_QualificationProducer_Integration_v1 的 Q1 限定返修。

先读取本包 REVIEW.md、RUN_LOCAL.md、reference_task/ 原目标及22项验收矩阵，
并查看 validation/PAIRED_MASKING_CHECKS.json 和 probes/final_run/RESULT.json。
本次审查对象 C20=52e70a172a46f400803a9a216f827026d099542a，
封包 HEAD=987f61175aa9835aa54c804e901ae918f1b531ad。

上一轮七个明确反例已全修好；C20 的完整 r21/262 归档与实际 ZIP 已核验。
不要重开 Q2/Q3、R25、TrainingBridge，不推倒已有工作。

只继续修同根 Q1：
- K 支撑的独立合法性检查仍被 if once_vs_attempts: 父级包住，
  整段缺失时在场坏直方图/均值矛盾/小数计数会逃逸。
- 对 ova 的两个派生均值都存在才检查有限性，导致一个缺失时另一侧 NaN/Inf 放行。
- n_events=-1 在直方图缺失时放行；有限整数检查不能代替合法计数检查。

用同一坏输入先证拒绝，再只删父级/另一侧支撑，仍应因在场坏数据拒绝。
合法缺件的既有工程委托保留；不要求新 schema，不修改科学阈值/digest/黄金向量，
也不要仅按7个测试名打补丁。先逐个校验在场对象，再判缺件与跨输入关系。

主 Agent 实现与基础自测后，将 REVIEWER_ADDENDUM.md 原文交给 OMP 已配置 reviewer，
预期模型 zhipu-coding-plan/glm-5.3-flash，独立上下文与实际工具核验。
不是主会话扮演 reviewer。主 Agent 不得代写 PASS、缩减原必需项或不断换 reviewer。
普通错误在本任务中自行修复，独立复验失败/影响项，原22项矩阵核对复用依据。
本次旧内容 PASS 不可沿用。

新语义候选需要其适用的 r21 完整回归证据与262回归；C20历史原件不改签。
独立内容PASS之后再封包，reviewer从最终ZIP冷读并在包外绑定实际SHA，
验收回执不放回其所验ZIP。增量交付可继续，无需递归嵌套旧包。
全部必需项通过才报告完成；BLOCKED/FAIL不是完成。

默认无单轮8小时时限；单重型任务、资源保护仍执行。原生执行2/2不重置；
本次反例零新增原生/研究MC/fit/optimizer/模型加载。
不启动真实正式资格、K11研究或教学；无法在原授权内继续时如实报告未完成。
