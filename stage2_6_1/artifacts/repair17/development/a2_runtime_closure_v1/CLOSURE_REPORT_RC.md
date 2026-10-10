# CLOSURE REPORT — RouteC_A2_RuntimeClosure_NewAttempt_v1（RD01–RD09）

日期：2026-10-10(R3 修复轮终验) | 出口：**A2_RUNTIME_READY_PENDING_USER_APPROVAL**
最终候选（Commit A）= `0f494d27bad2ed0de6876ff32f4cb7d656a19c98`（tree `7a2fecbbea921181562720b07e5b87ca6c4e5f7a`）。演进链：`0cab6ec8`(W1–W4 主体)→`8916ab9d`→`61180756`→`2f3e7faa`→`b3e3bffd`(RcwGate1 P0–P3)→`c0801c56`(R2)→`afc7d82e`/`8da55a52`/`34d7f7c8`/`45a47547`/`85a879a4`(活 audit 探针 qaf_v3 注册补丁)→`24ddea34`(R3:reviewer F-1 修复,F-1R 前身——计划授权身份文本随 qaf_attempt_family 参数化+run_scope.attempt_identity 显式注册+RD06 回归测试+差异测试更新为身份键集合语义,含 ae50a20c 中间候选 amend)→`0f494d27`(R3 残留 F-1R:step-smoke 三条字符串改用 ppo_smoke_ns)。其后提交均为纯 artifacts 证据,src/tests/runner 相对 24ddea34 零变化。

## 独立验收记录(R3 循环)
- 委派模型:原别名 dsv4.1f(commandcode/deepseek/deepseek-v4.1-flash:max)服务方 400 额度不足→用户 2026-10-10 明确授权换用并自行修改配置→配置选择器 `zhipu-coding-plan/glm-5.3-flash:max`;reviewer 运行身份元数据不可观测(其报告如实记录)。
- R3 内容审查(报告 `local/rcw_r3_review/REVIEW_REPORT_v1.md` + 仓库留档 `evidence/reviewer_r3/`):RD01–RD05/RD07–RD09 **PASS**;RD06 **FAIL F-1**(计划文本硬编码 v1/r17 旧 smoke/audit-bank 身份)+F-2(文档计数 14→17、约30→52)。
- 修复(本轮内):F-1→`curriculum261_qprod_formal_budget.py`/`curriculum261_qprod_formal_levela.py` 参数化 + `attempt_identity` 注册 + 新增 RD06 测试 + `test_payload_diff_identity_only` 更新为"差异=身份键集合、科学字段全等";F-2→计数勘正(隔离测试现 18 项;探针目录 52 个)。修复后全套 A'' 级联复验+全量回归重跑;待同一 reviewer 复验 RD06 后签结论行。

## RD01 失败保留
旧 P2/D2/qaf_v1/qaf_v2 保护原件逐字节未变(轮初 `w1_audit/old_scene_identity.txt` ↔ 2026-10-10 `old_scene_identity_after_20261010.txt`:旧 P admission `b465e5f1…`、issued `956178b2…`、全部单件同 SHA;P2 仍缺 env 两件=失败根因原样保留;P2/D2 零新文件)。如实披露(`w1_audit/old_scene_disclosure_20261010.md`):标准部署树 crypto_rl 内 52 个 dummy-sha 哨兵链负例探针目录+2 个 src 文件按惯例同步为候选版本。本轮零签发/零消费/零 launch/零科学计算;唯一 preissue 调用只读且因 E1 未装而正确拒绝。

## RD02 完整静态输入
`w1_audit/RUNTIME_STATIC_DEPS.md`:A 表(开发根 10 项)+ B 表(pinned 发布源身份+历史绑定件)+ C 表(D3 面)+ 生产者边界,全部来自冻结源码实读(reviewer 抽验 5 项全对)。98 项旧 P 血统 extras 清单钉死。

## RD03 候选与发布源
`release_repo_candidates()` pin 优先接入全部 14 处 src 解析点(reviewer 实数核对);PIN=独立 clone `route-c-stage2-6-1-repair17` 分支态 HEAD==24ddea34、porcelain 干净(detach 会破 ancestry 分支名检查——留档负例)。成对实测@A'':工程隔离正例写出冻结产物(r17fs-5f36c3ca、missing=[]);活 audit 反例=dummy sha 拒(`prefix_probe_0f494d27/audit_step_refused.stderr`);detach 反例(`prefix_probe_85a879a4/ancestry_refused_detached_head.json`);旧 P 52 目录历史探针同型拒绝。

## RD04 前置生效
`runtime_dependency_preflight`(真实 freeze 读取器子进程@P3+三面 CR 投影逐文件+原件字节)入 `preissue_gate`,operator execute 与直接 issue-permit 两入口首一次性写前同一前置;隔离正反例现 **18 项**(reviewer 实证 17 项全真实消费者形态+F-1 修复新增 1 项);E1 未装时全门 fail-closed(`preissue_gate_P3_preconfig_refused.json`,one_shot_writes=0,reviewer 当日重演同判)。

## RD05 消费边界
真实域@A'' 四件:preflight ok + freeze 工程隔离写出 + **活链前缀 3 步全绿**(provenance→determinism A4/A5/A6→audit anchored r17fs-5f36c3ca、ancestry ok、全 binding pass、determinism_contract=bound,`prefix_probe_0f494d27/`)+ substance 同根 rc=0(plan digest 9020b844 claimed==recomputed、record 2990 绿)/错根 rc=2。中间候选(85a879a4/ae50a20c)同名证据留档备查。

## RD06 新尝试无科学漂移
qaf_v3:26 全新 namespace、迭代 qprod_a_formal_v3、注册表单一来源、api 匹配表、262 A2RC_V1 登记(活 audit 探针逐层补齐 5 提交)。**F-1 修复后授权文本与真实可达消费身份一致**:计划 `run_scope.attempt_identity` 显式注册 audit_bank=preplan_audit_bank_qaf_v3/preplan_smoke=preplan_smoke_qaf_v3/ppo_smoke=ppo_smoke_qaf_v3(与链内 cmd_audit/cmd_preplan_smoke/cmd_preflight_static/smoke 同源),budget consumers/description/smoke_policy 全部随族参数化;v1↔v2 payload 深度 diff=8 身份承载键,quota/stop_mode/rules(除身份文本)全等(更新后测试断言)。计划=真实构建器 `qbpl-c2dd9bb802ca890cc6aa2ef2b9ae4ffbb8f5f1788ee7e87dd7854816aabe8a36`(draft==rebuilt 实测)。v2 消费不恢复。

## RD07 最终部署/证据
P3/D3/PIN 三新根;三方对拍 CR 投影 **698/597/660 全等**(`three_way_compare.json` meta 绑定 A'');全收集 **2990 tests(2983P+7S)/0F/0E**(run `r21_20261010_160557`,cwd=D3,record `2e9fccfb14ab9c67992a1031302b690d2af28c6c56f8c0d05d412fb2ce4d5548`)由 substance 同根 rc0 复核;262 适用=A2RC_V1 注册面(两树镜像同步)。回归尝试 1–13 全归档(13=24ddea34 绿但 F-1R 候选更替)(11=85a879a4 绿但候选更替;12=ae50a20c 单失败[钉旧语义的差异测试,随修复更新]——失败原件保留)。

## RD08 日志/用量
各次尝试唯一 out-dir+归档;2026-10-10 各级联唯一日志(`runtime_verify/logs_20261010/` 8 件,含两次全量回归执行日志);工程计算如实记账:determinism-matrix 前缀探针共 5 次工程跑(85a879a4×2 含 detach 拒次、ae50a20c×1、24ddea34×1、0f494d27×1)+全量回归 3 次(2989 绿/2990 绿×2)——均为既有工程电池/测试面,非科学资格计算。

## RD09 最终交付
COMMANDS_APPENDIX(E1–E4 绑 A'' 终值)+ PENDING_APPROVAL_SUMMARY(批准建议文本)+ 本报告;reviewer 复验通过后封 RETURN,包外双回执绑定实算 SHA。

## 结论
上轮失败根因(freeze dev root 缺件)与发布源 HEAD 漂移冲突系统性闭合;reviewer R3 全矩阵审查的 F-1/F-2 已修复并在最终候选上全套复验;一次 A2 执行的全部事前静态输入已实装、对拍、活链前缀与全量回归证明。**未签发、未消费、未 launch——仅待用户批准。**
