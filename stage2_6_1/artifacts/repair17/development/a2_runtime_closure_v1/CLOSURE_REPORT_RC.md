# CLOSURE REPORT — RouteC_A2_RuntimeClosure_NewAttempt_v1（RD01–RD09）

日期：2026-10-10(R3 修复轮终验) | 出口：**A2_RUNTIME_READY_PENDING_USER_APPROVAL**
日期再记:2026-10-11 接续 **FiniteRepair R2**(上游对 FR1 RETURN aaf4d3e3 判 **FAIL/NOT CLOSED**:R1 reviewer 定性"矩阵外"的 r11/r13 binding 层残余被上游**改判为原任务核心遗漏**(REVIEW.md §3-§4:示例表非穷举白名单);另要求直接 qprod_formal_authority issue-permit 路径证据与 FR1 探针原件归档)。R2 修复=最终候选 `c0fb6858`(见下节)。
## FiniteRepair R2 修复记录(0735f255 → c0fb6858)
- **binding 层前置**:从三个真实 binder 提取只读 checks(`_r11_abort_checks`/`_r12_abort_checks`/`_r13_failure_checks`;binder wrapper 语义逐字保持——写盘、fail-closed 重抛、原异常直传),探针接入 → `preissue_gate` → 三条签发路径(operator execute / **直接 qprod_formal_authority issue-permit** / r17_admission_issue)首写前;新拒绝标记 `historical_bindings`(逐 iteration 状态)。覆盖:r11(marker blob+cue audit+trace blob+exposure/final 必须缺席)、r12(marker 内容+8 blob+2 digest+exposure/plan/final 缺席)、r13(result verdict/failed_checks+exposure/abort 内容+5 blob+2 digest);r14/r15 由 heb 派生键覆盖(其 binder 从 heb checks 机械提取,无独立工作树读取)。
- **成对测试 +13**(FR2-01/02):r11 trace 缺失/marker 字节/final 出现/audit 改变;r13 abort 缺失/result blob 改变/exposure 缺失/plan digest 改变;r12 marker 字节(heb+binder 双层同源检出)/exposure 出现;恢复正例;**直接 permit 入口**实跑 rc=96 零许可写+合法域穿全部前置至批准边界(入口子进程 PIN 常量不可注入历史突变——与 FR1 admission 先例同构用 vendor 证明接线,binding 拒绝由 preflight 级九场景覆盖)。套件 45/45 绿@c0fb6858。
- **FR1 原件归档(R2 REVIEW §5)**:`evidence/reviewer_fr1/probes/`(fr1_probe_driver.py、residual_probe.py、fr1_probe_results.json、residual_probe.json、preflight_rerun_P3.json、threeway_sample.json、zip_integrity.json、dom 配件+README 说明边界:入口完整 stdout 未逐条落盘的缺失如实标注;fixture 克隆目录按"不复制临时环境"边界未收编)。
- **RCW-F1**:探针接入 vendor 真实消费者合同(`vendor_dir_default()`/`_vendor_state()`/`VENDOR_PIN` 同源;缺目录/dirty/错 HEAD → `vendor_static` 拒)。
- **RCW-F2**:探针接入 PIN 历史原件(`_historical_binding()` 17 件 digest+r11/r12 blob 基线 → `historical_digests` 拒)与分支/血统(`historical_evidence_binding()` 命名分支+ancestry+r16 链;r16_branch_name_ok 按其自身 R17 语义豁免 → `branch_lineage` 拒)。
- **接线**:三类检查入 `runtime_dependency_preflight` → `preissue_gate` → 两个受支持签发入口(operator execute/r17_admission_issue)首一次性写前;成对测试 14 项(隔离域=真实对象 `--shared` 克隆:完整合法基线+单条件突变+两入口子进程实跑 rc=96 零一次性写+合法域过 gate 至批准绑定边界截停),既有 14 拒例回归不退回;套件 32/32 绿@0735f255。
- **RD09 补齐**:reviewer 探针原件(rcw_probe×4+coldread×2+输出件)入 `evidence/reviewer_r3/probes/` 并入包。
- **验证@c0fb6858(FR2 终态)**:计划 `qbpl-5963af98…`(draft==rebuilt)/preflight ok(含三合同)/freeze `r17fs-1fed389b`/三方 **700/599/662 全等**/活链前缀 3 步全绿(audit anchored)/dummy-sha 拒/全量回归 **3017=3010P+7S/0F/0E**(run `r21_20261011_061035`,record `007baaf3…`)/substance 同根 rc0/错根 rc2。回归尝试 15–20(19=0735f255 绿但 FR2 候选更替;20=FR2 全绿 3017):15=包装 60 分钟超时半途;16/17=各一个既有**时序脆弱测试**满载 flake(W01 子进程 rc=94、r25a02 秒级时间戳同秒 digest 撞;两者隔离与配对重跑均绿,与修复无逻辑交集,如实留档);18=全绿。
## 独立验收记录(R3 循环)
- 委派模型:原别名 dsv4.1f(commandcode/deepseek/deepseek-v4.1-flash:max)服务方 400 额度不足→用户 2026-10-10 明确授权换用并自行修改配置→配置选择器 `zhipu-coding-plan/glm-5.3-flash:max`;reviewer 运行身份元数据不可观测(其报告如实记录)。
- R3 内容审查(报告 `local/rcw_r3_review/REVIEW_REPORT_v1.md` + 仓库留档 `evidence/reviewer_r3/`):RD01–RD05/RD07–RD09 **PASS**;RD06 **FAIL F-1**(计划文本硬编码 v1/r17 旧 smoke/audit-bank 身份)+F-2(文档计数 14→17、约30→52)。
- 修复(本轮内):F-1→`curriculum261_qprod_formal_budget.py`/`curriculum261_qprod_formal_levela.py` 参数化 + `attempt_identity` 注册 + 新增 RD06 测试 + `test_payload_diff_identity_only` 更新为"差异=身份键集合、科学字段全等";F-2→计数勘正(隔离测试现 18 项;探针目录 52 个)。修复后全套级联复验+全量回归重跑;同一 reviewer 经 v2/v3 两轮复验(F-1 主体+F-1R 残留)后于 v3 终报告签发结论行(见 evidence/reviewer_r3/)。

## RD01 失败保留
旧 P2/D2/qaf_v1/qaf_v2 保护原件逐字节未变(轮初 `w1_audit/old_scene_identity.txt` ↔ 2026-10-10 `old_scene_identity_after_20261010.txt`:旧 P admission `b465e5f1…`、issued `956178b2…`、全部单件同 SHA;P2 仍缺 env 两件=失败根因原样保留;P2/D2 零新文件)。如实披露(`w1_audit/old_scene_disclosure_20261010.md`):标准部署树 crypto_rl 内 52 个 dummy-sha 哨兵链负例探针目录+2 个 src 文件按惯例同步为候选版本。本轮零签发/零消费/零 launch/零科学计算;唯一 preissue 调用只读且因 E1 未装而正确拒绝。

## RD02 完整静态输入
`w1_audit/RUNTIME_STATIC_DEPS.md`:A 表(开发根 10 项)+ B 表(pinned 发布源身份+历史绑定件)+ C 表(D3 面)+ 生产者边界,全部来自冻结源码实读(reviewer 抽验 5 项全对)。98 项旧 P 血统 extras 清单钉死。

## RD03 候选与发布源
`release_repo_candidates()` pin 优先接入全部 14 处 src 解析点(reviewer 实数核对);PIN=独立 clone `route-c-stage2-6-1-repair17` 分支态 HEAD==c0fb6858(FR2 候选;FR1 时点为 0735f255,R3 时点为 0f494d27)、porcelain 干净(detach 会破 ancestry 分支名检查——留档负例)。成对实测@A3:工程隔离正例写出冻结产物(r17fs-1fed389b、missing=[]);活 audit 反例=dummy sha 拒(`prefix_probe_fr2_c0fb6858/audit_step_refused.stderr`);detach 反例(`prefix_probe_85a879a4/ancestry_refused_detached_head.json`);旧 P 52 目录历史探针同型拒绝。

## RD04 前置生效
`runtime_dependency_preflight`(真实 freeze 读取器子进程@P3+三面 CR 投影逐文件+原件字节)入 `preissue_gate`,operator execute 与直接 issue-permit 两入口首一次性写前同一前置;隔离正反例现 **18 项**(reviewer 实证 17 项全真实消费者形态+F-1 修复新增 1 项);E1 未装时全门 fail-closed(`preissue_gate_P3_preconfig_refused.json`,one_shot_writes=0,reviewer 当日重演同判)。

## RD05 消费边界
真实域@FR2 四件:preflight ok(含 vendor/历史/分支三合同+r11/r12/r13 binding 层) + freeze 工程隔离写出(r17fs-1fed389b) + **活链前缀 3 步全绿**(provenance→determinism A4/A5/A6→audit anchored、ancestry ok、全 binding pass、determinism_contract=bound,`prefix_probe_fr2_c0fb6858/`)+ substance 同根 rc=0(plan digest a2621f8e claimed==recomputed、record 3017 绿)/错根 rc=2。中间候选(85a879a4/ae50a20c/0f494d27/0735f255)同名证据留档备查。

## RD06 新尝试无科学漂移
qaf_v3:26 全新 namespace、迭代 qprod_a_formal_v3、注册表单一来源、api 匹配表、262 A2RC_V1 登记(活 audit 探针逐层补齐 5 提交)。**F-1 修复后授权文本与真实可达消费身份一致**:计划 `run_scope.attempt_identity` 显式注册 audit_bank=preplan_audit_bank_qaf_v3/preplan_smoke=preplan_smoke_qaf_v3/ppo_smoke=ppo_smoke_qaf_v3(与链内 cmd_audit/cmd_preplan_smoke/cmd_preflight_static/smoke 同源),budget consumers/description/smoke_policy 全部随族参数化;v1↔v2 payload 深度 diff=8 身份承载键,quota/stop_mode/rules(除身份文本)全等(更新后测试断言)。计划=真实构建器 `qbpl-5963af98aca388afbbe8a9088da70a26a556ee31096186f12d53c44dbf1145fd`(draft==rebuilt 实测)。v2 消费不恢复。

## RD07 最终部署/证据
P3/D3/PIN 三新根;三方对拍 CR 投影 **700/599/662 全等**(`three_way_compare.json` meta 绑定 c0fb6858);全收集 **3017 tests(3010P+7S)/0F/0E**(run `r21_20261011_061035`,cwd=D3,record `007baaf328b2bfe948784c016f51b934dfea5a211fbba2eab5cef3798ef04fc4`)由 substance 同根 rc0 复核;262 适用=A2RC_V1 注册面(两树镜像同步)。回归尝试 1–20 全归档(11/13/14/19=绿但候选更替;12=单失败如实保留;15=60 分钟包装超时半途[attempt15_partial];16/17=各 1 个既有**时序脆弱测试**满载 flake[W01 子进程 rc=94;r25a02 秒级时间戳同秒 digest 撞],两测试隔离与配对重跑均绿,非本修复逻辑所致;18/20=全绿 3004/3017)。

## RD08 日志/用量
各次尝试唯一 out-dir+归档;2026-10-10 各级联唯一日志(`runtime_verify/logs_20261010/` 9 件,含三次全量回归执行日志);工程计算如实记账:determinism-matrix 前缀探针共 5 次工程跑(85a879a4×2 含 detach 拒次、ae50a20c×1、24ddea34×1、0f494d27×1)+全量回归 7 次(2989 绿/2990 绿×2/3004 绿×2/3017 绿×1/两次时序 flake 如上)——均为既有工程电池/测试面,非科学资格计算。

## RD09 最终交付
COMMANDS_APPENDIX(E1–E4 绑 A3 终值)+ PENDING_APPROVAL_SUMMARY(批准建议文本)+ 本报告;reviewer 复验通过后封 RETURN,包外双回执绑定实算 SHA。

## 已知残余离差(独立 reviewer P2 发现,非本轮矩阵项;如实披露)
preflight 已覆盖上游 FAIL 判据的两大具名消费条件(digests_match/heb.ok)与 vendor 合同;cmd_audit 最终 ok 另含 r11_binding/r13_binding 等out-dir 绑定检查,其 **PIN 工作树证据层**(repair11/cue_event_trace.jsonl、repair13/r13_iteration_aborted.json 等)不在前置覆盖内——reviewer 实证:删除后 preflight 仍 ok、同条件下 audit 步 binding fail-closed 中止(首个一次性写之后)。判定:属前置与 audit 步的残余离差,**不在上游本轮收口矩阵内**(REVIEW.md §3/§4 具名遗漏已闭合),按"范围有界"原则本轮不扩面;建议下一候选把 *_binding.pass 的工作树读取面接入前置(见 evidence/reviewer_r3/ 之外的本轮 reviewer 报告 /f/trading/local/fr1_review/REVIEW_REPORT_FR1.md)。

## 结论
上轮失败根因(freeze dev root 缺件)与发布源 HEAD 漂移冲突系统性闭合;reviewer R3 全矩阵审查的 F-1/F-2 已修复并在最终候选上全套复验;一次 A2 执行的全部事前静态输入已实装、对拍、活链前缀与全量回归证明。**未签发、未消费、未 launch——仅待用户批准。**
