# QProd 返修轮4(R4)reviewer 交接(第四次 NOT_CLOSED,C13 后)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: 远端 HEAD 2b49a28e(R3 封包) + 内容候选 C13=edbdf40a(R3 内容 PASS+冷读 PASS, 保持)
- 本轮触发: ChatGPT 第四次 NOT_CLOSED(用户目标逐字见 §0)
- 本轮候选: **C14=3d2193e2**(R4 修复单提交;证据件随后)
- 输入原件: `REVIEWER_ADDENDUM (3).md`(用户指定 `C:\Users\15027\Downloads\REVIEWER_ADDENDUM (3).md`, 已归档 `.../qprod_v1/repair_round4_notclosed/REVIEWER_ADDENDUM_R4_ORIGINAL.md`)
- 材料事实(如实): 本轮 Downloads 未附新 QProd REVIEW.md、无 reference_task/ 目录(同前轮; 两份 REVIEW 为 R25 旧件不误用)。原 22 项矩阵: `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`

## R3 已保持项(不重开)
Q2 异常/中断不确定预占保留、低正数许可动作前拦截、错误步骤序列拒绝、collect-all 保留有效统计负结果、E01 撤回 skip——全部保留(addendum "已接受修改不要重开")。

## R4 修复映射(addendum (3) 三组)
### Q1 规则同源(不只 8 个名字同源)
- r17 core 新增 `recompute_audit_semantics_from_report`:从报告公共数值以**冻结常量**(AUDIT_MC_ABS_TOL/AUDIT_DIFF_SE_FACTOR/AUDIT_DIFF_TOL_FLOOR)独立重算每条 PASS 规则:MC(|p_hat-p_contract|<=冻结容限,**不读** report.monte_carlo.tolerance——擅自改 1.0 既记 threshold_drift 又按冻结值判)、per-corpus replay_ok∧bounds_ok∧cue_table∧p_contract∈CI95∧|emp-ana|<=max(3SE,0.005) 冻结公式∧tail 数值同公式、tail integrity 子条件、global_k、once_vs_attempts、aggregate
- Level A gate1 调用该单一事实源函数(替换 R3 手搓数值逻辑),重算 8 键与报告 checks 逐键对账+阈值漂移检查;四反例(CI 排除解析值/replay=False/tail 偏差超限+容差放大/MC 容限 1.0)**全部 checks=True+digest 重算自洽**仍拒
- 工程 fixture 双重态(报告 engineering_fixture=true):**在场数值字段必须真实过冻结公式**;支撑字段(ova/global_k/ti/replay 等)缺失的键委托声明值并列入 fixture_delegated 如实标注(不静默换 True);正式报告缺字段即 False
- 合法对照(未篡改 rehearse/2 块合成)通过——`test_r4q1_legal_control_passes`

### Q3 实际计划条目向下关联
- `_verify_coordinate` 新增: (a)防脱钩——传入 coordinate 必须逐字段等于冻结 manifest 同 id 条目(构造条目绕过清单审计拒, differing keys 列明); (b)条目级 blocks_per_corpus/mc_events ↔ global audit_budgets ↔ qcap budgets ↔ report/实际 四方对账——条目 500 而 global/qcap/report/实际 2 → invalid(装载+aggregate 路径都拒)
- legacy 计划(audit_budgets 整块缺失, 如 E01):global 侧无基准不误报,条目↔qcap↔report 三方仍在(范围矛盾检查不受影响;E01 白名单身份由计划 digest 层控制)
- 不重生成 E01:E01_RECOMPUTE_C14.json 只读复算, run1 c01 valid(nrv, recall 0.9608/se 0.0283 保留)K=1 inconclusive; run2 双坐标保留(c02 se=0 如实)K=2 inconclusive——与 R3 输出逐字节同值(数值未动)

### R01 真实审计记录(r21 流程)
- 用仓库既有 `r21_full_collection_regression.py`(v6 受控 full 配置; manifest 先行落盘+白名单环境+`-p r21_collection_auditor` 真实子进程 collect-only+分片执行同接线+record 全件 sha256 绑定+verify 自验)对 **C14** 跑 261 全量 → `evidence/regress_v6/full_regression_v6_c14/`(audit_collection.json+lifecycle.jsonl/audit_execution.json+junit/collection+execution stdout/stderr/record/summary)
- 旧原件: C7 轮(20260930, commit cda4e975)full_regression_v6 已在 repo(原样, 不倒填; 本轮新跑的 C14 原件独立归档)
- E02 R4 七步 rc=0(evidence/e02/, R01 要素; 标注非 261 回归)
- 262 v7 逐候选适用: 普通 pytest 完整原件(stdout/junit/meta)——r21 流程 target 为 261 面(r21 执行器 DEPLOYED_TEST_ROOT), 262 按既有任务要求跑全量留原件

## 验证(C14 字节, 零原生/零 MC 研究/零 fit/零 optimizer)
- 钉: R4 新增 9 + R3 18 + R2 17 + q123 21 + 其余 qprod 面 = 149/149
- E01 只读复算(R4 校验下保持 valid+nrv+如实 inconclusive)
- r21 v6 C14 原件 + 262 v7 全量(结果入 EVIDENCE_INDEX)
- 原生 2/2 耗尽维持; addendum "1 个旧早停探针与未批政策相关不作为否决依据"——本轮未改早停科学定义(R3 语义保持: 事前定义 delta>margin, se=0 退化不判负)

## reviewer 需独立回答
1. Q1: 对比 core 生成内核 PASS 规则与 recompute/Level A 判定等价性;四反例(checks 全 True+digest 自洽)是否真拒;合法对照是否真过;阈值是否全部来自冻结常量(无报告自带值);fixture 双重态是否只委托缺失支撑字段而在场数值仍真验
2. Q3: 条目 500/global 2/qcap-report-实际 2 的完整计划装载+aggregate 是否拒;传入条目与 manifest 脱钩是否拒;合法 2 块对照与旧 E01 是否仍 valid;是否未重生成 E01
3. R01: 打开 COLLECTION/audit_collection.json 读正文——collect-only+auditor 三阶段快照+lifecycle JSONL+分片执行+record sha256 绑定+verify 是否真实(非三行声明);C7 旧原件是否原样;C14 是否有适用真实运行;E02 是否仍只作链路证据
4. 全 22 项矩阵对账(已确认项验证身份/适用性后复用)

## 边界(不变)
- 零新增原生/MC 研究/fit/optimizer;原生 2/2 不清零;正式资格/K11/教学 NOT_RUN;R25/TB 不重开
- 脚本本地隔离依赖模式不是 WSL 端到端证据;真实环境复验记录实际导入路径/摘要/候选(不沿用静态标签)
- 最终 CLOSED 由 ChatGPT 独立终验;主 Agent 不自签

## §0 本轮目标原文(逐字)
继续原任务 RouteC_QualificationProducer_Integration_v1；本次为C13/R3的有限返修，不是新研究轮次。

先读同目录 REVIEW.md、REVIEWER_ADDENDUM.md，以及 reference_task/NEXT_GOAL.md 和 ACCEPTANCE_MATRIX.md（QProd原任务22项，不是R25同名旧文件）。当前已审代码 C13=edbdf40ae5a4237ba68282a5875a8c78d600ac4a；本次实测远端HEAD=2b49a28e6fa02faf837c2507898c4129e3aeaaa7。已推进的新工作树正常接续，不回退或清理未知文件。

已支持的Q2异常预占／低正数许可拒绝、17重复步骤拒绝、collect-all保留有效统计负结果，以及撤回E01新增skip，全部保留。

必须修复三组剩余问题：
1. Q1公共审计核心与Level A判定不等价：CI排除解析值、replay失败、tail数值失败、报告自行把MC容限放宽到1.0，外层checks和hash自洽时仍可17步PASS。共享实际公共规则与冻结阈值，不复制另一份删减算法；合法对照保持。
2. Q3研究计划具体coordinate_manifest条目500 blocks、global/qcap/report及实际两语料2 blocks，完整aggregate仍判valid。贯通具体条目、qcap、报告、实际范围，不只检查global rules；不要为此重生成E01。
3. R01的COLLECTION.json只是三行auditor/lifecycle文字声明，实际脚本为普通pytest。保留当前真实stdout/JUnit，但不能用声明代替实际collect-only/auditor/lifecycle及完整record。使用既有完整回归证据流程（包含r21_collection_auditor）为最终新候选取得适用原件。旧时确有原件则原样补入；没有捕获的历史不倒填。不要另造一套同名元数据绕过现有协议。

独立运行现有GLM-5.3-Flash reviewer，将REVIEWER_ADDENDUM.md原文转交，连同原22项矩阵、完整原件及固定候选。失败你自行修复，再独立复验最终候选，内容PASS后封RETURN，reviewer从新目录冷读实际最终ZIP并出包外回执。不得用本次旧PASS或自己选择的少量全绿测试代替完成条件。

无单轮8小时时限；原生2/2耗尽、不清零、不启动第三次原生执行；本补充零新增原生/MC研究/fit/BC/PPO，正式资格/K11/教学NOT_RUN。适用工程回归依原任务执行并保留保护。R25和TrainingBridge不重开。

本次49用例中1个旧早停假设与未批准政策相关，不作为此次代码否决依据；不要把它改成形式上翻绿的新科学定义。其余6个内容反例围绕两类不变量；原件缺口单独处理。脚本本地隔离依赖模式不是WSL端到端证据，真实环境复验必须记录实际导入路径/摘要/新候选，不沿用脚本里的静态C13标签。
