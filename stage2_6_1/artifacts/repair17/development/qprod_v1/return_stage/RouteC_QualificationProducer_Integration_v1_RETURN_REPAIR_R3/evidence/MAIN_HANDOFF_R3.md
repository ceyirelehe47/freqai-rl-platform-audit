# QProd R3 返修轮 reviewer 交接(第三次 NOT_CLOSED_ENGINEERING)

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 基线: 证据 HEAD c848928f(封包提交) + 内容候选 C11=8f92a985(V2 内容 PASS + ZIP 冷读 PASS, 保持成立)
- 本轮触发: ChatGPT 第三次 NOT_CLOSED_ENGINEERING(用户目标文本逐字见 §0)
- 本轮候选: **C12=29c465da**(单提交, 已 push)

## 输入原件说明(如实)
- `REVIEWER_ADDENDUM (2).md`(2026-10-01 02:10, 用户指定路径 `C:\Users\15027\Downloads\REVIEWER_ADDENDUM (2).md`)已归档: 仓库 `.../qprod_v1/repair_round3_notclosed/REVIEWER_ADDENDUM_R3_ORIGINAL.md`
- 目标文本提及的 REVIEW.md 与 reference_task/: **本轮 Downloads/任务包均未附新的 QProd REVIEW**(Downloads 两份 REVIEW.md/REVIEW (1).md 仍为 9/29 R25 轮, 不误用); reference_task/ 仅存在于 TrainingBridge 旧轮目录。本轮以用户目标逐字+addendum (2)+原 22 项矩阵为准——材料事实如实记录, 不编造 REVIEW 原文
- 原任务 22 项矩阵: `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`
- 前轮原件: `.../qprod_v1/repair_round2_q123/`(R2)+`F:/trading/reviewer_q123_r2/`(R2 reviewer)+`F:/trading/tmp_reviewer_q123/`(R1)
- E01 原件: `.../qprod_v1/native_smoke_run{1,2}/`(零改动)

## R3 修复映射(四点)
### Q1 公共业务数值与权威检查集合
- 权威必需检查集合单一事实源: r17 core `AUDIT_REQUIRED_CHECK_NAMES`(8 键)+`_synthetic_probe_check_names_and_values` 组装; 读取侧 `qprod_required_cue_check_names()` 对拍(键集漂移即拒)
- gate1 数值级重算(不只 all(checks)+SHA): MC closeness(|p_hat-p_contract|<=tolerance)、双语料 closeness(|emp-ana|<=max(3SE,0.005))从报告公共数值独立重算, 与 checks 布尔矛盾即拒——"MC 数据失败但顶层 PASS 且 checks/SHA 自洽"不再通过(成功夹具≠数值合法)
- 17 步权威序列: export 校验步骤名序列==r17_workflow_step_names()(顺序=依赖); 复制同一步 17 次/换序/缺步即使全 ok 也拒; failed_at 残留拒
- 保留: raw/result/iteration/journal/holdout/研究计划/终态全部 R2 拒绝路径(不退化)

### Q2 异常不丢账+许可vs需求动作前拦截
- attempts 一般异常/KeyboardInterrupt: 未结算预占保留(不退 0); episode_leaf_calls=已结算+不确定上界; 正常完成按 attempts_made 精确回填释放; totals 分列 settled/uncertain_upper/uncertain_blocks
- 例子: 24 动作结算后异常 → 累计 24+40=64(不逃账)
- 许可为正但不足: run 动作前(run_coordinate_audit_locked, 生成前)对账 permit.quota.mc_events_per_coordinate>=qcap 需求(4096)、max_successful_episodes_total>=blocks*8*2(32)、max_native_executions>=1; 拒绝落 refusal(零叶调用); 研究计划预算声明不代替许可上限(三方对账取严)

### Q3 有效统计负结果保留(R2 规则撤回)
- 撤回"audit_pass=False 一律剔除主分析/早停"及错误测试; audit_pass=False(结构合法)→ stats_gate="cue_contract_fail"+negative_result_valid, **保留进主分析**
- collect-all: K 不足(<planned_k)→ inconclusive 如实; SE 退化(se=0)→ 不发明数学, inconclusive; 不删样凑绿
- early-stop: 事前定义 delta>margin(v4 classify); 结构合法坐标(含统计 gate FAIL)照常参与; se=0 属退化不判负(不发明替代数学)
- E01 新语义(实测): run1 c01 valid(nrv=true, recall 0.9608/se 0.0283 保留), K=1<11 inconclusive; run2 c01+c02 valid 保留(c02 recall=1.0/se=0 如实), K=2 inconclusive
- 范围贯通: manifest↔qcap(namespaces+block_range.start/count)↔report(blocks)↔双语料事件 block 集合↔计划声明; 范围矛盾拒; legacy 兼容基于计划 digest 白名单身份, 不构成范围豁免

### R01 完整回归原件+E01 实执行
- 完整 261 v10 + 262 v7 在 C12 字节: `evidence/regress/`(每 suite 完整 stdout/stderr/argv/cwd/interpreter/rc/junit + META + SOURCE_MAP repo blob↔deploy sha 逐文件 MATCH + COLLECTION auditor/lifecycle)。E02 七步明确标注"不是 261 回归"并另列 `evidence/e02/`(R01 要素 7 步 rc=0)
- E01 测试撤回 skip: 两处归档路径(仓库树+/mnt/f)任一存在必须实执行, 均缺才 FAIL(不静默跳过); 现用仓库归档真实原件跑

## 验证(C12 字节, 零原生/零 fit/零 optimizer)
- 钉测试: R3 新增 18 + R2 16(1 例改写撤回语义) + q123 21 = 55/55; qprod 其余面 85/85
- E01 只读复算: E01_RECOMPUTE_C12.json(nrv 保留/K 如实 inconclusive)
- E02 R3 七步全 rc=0(R01 要素齐)
- 261 v10/262 v7 完整原件: 结果写入 EVIDENCE_INDEX(跑完追加)
- 原生 2/2 耗尽硬门维持; 本轮零新增原生/fit/optimizer

## 边界(不变)
- 正式资格/研究/K=11/教学 NOT_RUN; R25/TB/R19 不动; 不重开旧坐标/G5c
- 最终 CLOSED 由 ChatGPT 独立终验; 主 Agent 不自签

## reviewer 需独立回答
1. Q1: 数值确实满足公共判据的正例是否通过; MC/语料数值失败+checks True+SHA 自洽是否拒; 删减必需 check 是否拒; 复制同一步 17 次/换序是否拒; R2 拒绝路径是否无退化
2. Q2: 3/24 动作后异常/中断是否不丢账(不确定预占保留, 累计不逃账); 正 quota 但 MC=1/正文=1 对需求是否动作前拒; 计划预算是否不能替代许可上限
3. Q3: 统计 gate FAIL(结构合法)是否保留进 collect-all 主分析; K 不足/SE 退化是否如实 inconclusive; early-stop 是否事前定义且一致; manifest-qcap-report-语料范围是否贯通; E01 原件数值是否保留
4. R01: 261/262 完整原件是否真实(候选绑定/source-map/lifecycle); E01 用例是否实执行无新增 skip; 22 项矩阵对账(已确认项身份/适用性复用)

## §0 本轮目标原文(逐字)
继续当前 RouteC_QualificationProducer_Integration_v1，不另起研究、不重置配额。当前 GitHub 证据 HEAD=c848928fa29c324559aa6a99155faf2018b84624，已审内容候选 C11=8f92a985b7f534aca217ebd409ff47a8906cfb05，本次 ChatGPT 独立终验 NOT_CLOSED_ENGINEERING。

先读取附带 REVIEW.md、reference_task/ 中真正的 QProd 原任务/22项矩阵/上次审查，以及 REVIEWER_ADDENDUM.md。不要误用 Downloads 中 R25 的同名 REVIEW，不要只按自编14例修复。

有限返修目标：
1. Q1 从公共业务数值与必需检查集合判定，不能只验证 all(checks) 与 SHA；17步来源按权威步骤/依赖核验，不接受复制同一步17次。保留已经修好的 raw/result/来源/终态拒绝。
2. Q2 内层 attempts 一般异常/部分失败/中断不丢已发生动作或不确定预占；许可为正但 MC=1 对需求4096、正文总量1对需求32，在动作前拒绝。记录的研究计划预算不能代替许可上限。
3. Q3 撤回 audit_pass=False 一律从主分析删除的规则及相应错误测试。区分技术无效与有效统计负结果；collect-all 保留有效负结果，early-stop 使用事前一致定义。已有 E01 本来不足K/退化SE，应保留数值并如实不决，不能删样凑绿。补清单条目与 qcap/report/两语料范围关联。
4. R01 当前完整回归原件仍缺，E02七步COLLECTION不能充当261回归记录。补原件并对新候选适用验证；新增E01 skip须改为正确读取已有原件后实际执行，不能删用例/默认接受新增skip。

原文委派已配置 reviewer（zhipu-coding-plan/glm-5.3-flash），独立上下文、实际工具、真实原件。失败由主Agent自行修复后再提审，最终全22项对账。reviewer报告和实际脚本/输出随包；内容PASS后从实际最终ZIP冷读并签包外回执。不得自签、改标准、换reviewer挑PASS或沿用C11旧PASS。

不设单轮总时限。最多一个重型WSL任务，资源监护/单作业超时保留。原生执行2/2已耗尽，零新增原生/fit/optimizer；测试以归档/手工raw/叶边界替身为主。适用全回归按既有任务要求执行，未获许可不得执行第三次独立原生批次。

已有R25/TrainingBridge结项、历史R19 FAIL与来源限制不动。正式资格/研究/K11/教学均NOT_RUN。本报告的模拟计数不是新数据，局部组件检查不是用户WSL全链通过；在真实环境复验时记录实际候选和导入路径，勿抄本地审阅标签。

只有实现、独立reviewer全矩阵、最终交付字节均通过，才可报告本轮完成并提交ChatGPT终验。没有通过则继续修复；真实阻塞如实报告未完成。
