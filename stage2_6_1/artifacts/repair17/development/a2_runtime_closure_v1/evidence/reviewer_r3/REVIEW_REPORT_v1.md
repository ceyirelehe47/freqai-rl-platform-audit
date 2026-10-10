# 独立内容验收报告 — RouteC_A2_RuntimeClosure_NewAttempt_v1(RD01–RD09)

 reviewer 委派与模型三记录:
1. 请求来源:原定 reviewer 别名 `dsv4.1f`(= commandcode/deepseek/deepseek-v4.1-flash:max)因服务方 400 额度不足不可用;用户于 2026-10-10 明确授权换用其他模型。
2. 配置选择器:`cfg://task.agentModelOverrides.reviewer = zhipu-coding-plan/glm-5.3-flash:max`;本次委派未传 `model` 参数,由该配置解析。
3. 实际运行身份:**元数据不可观测**(会话内无运行时模型元数据可读;如实记录,不伪称具体后端型号;过程配置标签不代表服务后端型号已验证)。

- 日期:2026-10-10。被审对象:freqai-rl-audit 分支 route-c-stage2-6-1-repair17,候选 Commit A=`85a879a46d0a20831644eb9aae52e0537436713f`(tree `06827b7d1534e136fd2b65347ec0f7ce392c0c3e`,本人实算一致),证据+文档 HEAD=`eba9e75d14683187857f541a2e8611e77b4804e7`。
- 独立性声明:本人未参与实现;未修改任何被审对象(仓库工作区、WSL P3/D3/PIN、旧 P2/D2/旧 P 全程只读);全部探针写入本人隔离目录 `/f/trading/local/rcw_r3_review/` + `/home/cryptorl/tmp_rcw_r3/`(探针脚本 rcw_probe.py/rcw_probe2.py、threeway_rerun.py 及全部原始输出均留存可查)。
- 判定依据:任务包原件(`F:/trading/trading/goal_incoming/RouteC_A2_RuntimeClosure_NewAttempt_v1/`)原始要求,不采信主 Agent 改写摘要。

## 总判定

| RD | 判定 | 一句话依据(详见下节) |
|---|---|---|
| RD01 失败保留 | **PASS** | 旧 P2/D2/旧 P 原件逐字节实算未变;P2 仍缺 env 两件;2026-10-06 后 P2/D2 零新文件;rehearsal 负例抽样实证 |
| RD02 完整静态输入 | **PASS** | A 表 10 项逐一对照真实源码函数/落点成立;B 表 14 处解析点实数相符;producer 边界列明 |
| RD03 候选与发布源 | **PASS** | 本人亲测:pin 优先解析、工程隔离正例(digest r17fs-c4b5818c 复现)、dummy-sha 拒、PIN 分支态 HEAD==A clean |
| RD04 前置生效 | **PASS** | 两入口同一 preissue_gate 首一次性写前;E1 未装 fail-closed 本人重演(one_shot_writes=0);隔离测试 17 项全真实消费者、全绿无跳过 |
| RD05 消费边界 | **PASS** | 本人重跑 substance 同根 rc=0(claimed==recomputed=06827b7d)/错根 rc=2(同理由串);前缀探针证据内部自洽 |
| RD06 新尝试无科学漂移 | **FAIL(P2)** | 注册/种子/api/双注册表/框架迭代全绿;计划 draft==rebuilt、digest 复算一致、v2→v3 仅 identity 两键差;**但计划文本 embedded_preflight_smoke/smoke_policy 硬编码 `ppo_smoke_qaf_v1`、budget_items 多处指名 `preplan_smoke_r17`/`ppo_smoke_r17`,而链实际解析 `ppo_smoke_qaf_v3`/`preplan_audit_bank_qaf_v3` 等——授权文本违反其自述 R3-A-1 原则与 RD06"全输入身份贯通"** |
| RD07 最终部署/证据 | **PASS** | record sha256/junit/summary 实算相符(2989=2982P+7S/0F/0E);三方对拍按原脚本口径精确复现 698/597/660 全等;262 适用性成立;失败尝试 9/10 如实归档 |
| RD08 日志/用量 | **PASS** | 终验日志 4 件唯一无覆盖;determinism 前缀 ×2 工程跑已披露且有日志实证(part3=detached 拒次、part4=全绿次) |
| RD09 最终交付 | **PASS** | 文档绑定值与证据原件逐值一致;E1–E4 命令参数面在 operator entry 全部存在;无"稍后补"占位;出口=A2_RUNTIME_READY_PENDING_USER_APPROVAL(未冒称执行) |

**结论行(『本轮运行依赖与下一尝试工程准备验收通过;等待用户对新身份的执行批准』)按交付要求本轮不签**:RD06 存在一项 P2 真实缺陷(见发现 F-1),须主 Agent 轮内修复(参数化计划构建器 smoke 身份文本→重新生成 draft→重算 qbpl digest→重绑 PENDING/COMMANDS/CLOSURE/批准建议文本→受影响测试复绿)并经独立复验 RD06 后方可签发。其余八项 RD 全部独立实测 PASS;修复仅触及计划文本面,RD01–RD05/RD07–RD09 的证据不受影响(除计划 digest 衍生值需重绑)。

## 逐 RD 证据(实测值)

### RD01 — PASS
- 本人 WSL 实算 sha256:旧 P `.r17_formal_admission.json`=`b465e5f17a651d0aee7f9a10fbb406448a37e1eae414c541aef7861db668ab6c`、`r17_admission_issued.jsonl`=`956178b282e42ae73be1cdd3ade0772af53cf7eb2682fe8b9d02a20411fdcb6f`;P2 RouteCStrategy.py=`dc5deab4…`、activate=`6c43ec58…`;D2 env=`e7a0850e…`、reqs=`4e727d3d…`;旧 P 四单件同 evidence/w1_audit/old_scene_identity*.txt 全等。
- P2 `environment.yml`/`requirements-lock.txt` 实测仍 MISSING(失败根因原样保留,未修补)。
- mtime 全树扫:P2 最新件=2026-10-05 15:22(安装时),D2 最新件=2026-10-05 18:32(v2 失败封口时);**2026-10-06 00:00 后 P2/D2 零文件**。
- `rehearsal_inventory_20261010.txt` 实列 52 目录(全 20261005 日);抽样 5 个(首 2/中 1/末 2)逐一验证目录在旧 P `r17_rt_runs/` 真实存在且含 `code_freeze_sha 与 repo HEAD 不一致` 拒绝文本——dummy-sha 拒绝负例成立。
- 披露核实:`crypto_rl/src/rl_curriculum/curriculum261_r17_admission_substance.py` 部署件与候选 blob 逐字节相等(本人 raw 比对 True;披露引用 `57f0425d…` 为 git blob SHA-1,本人 `git rev-parse 85a879a4:<path>` 实算=57f0425dbe3f152b0ad66c3961289f77d45e2eb0,一致);`__init__.py` 部署件 sha256=7aa2541d…(与 guard RUNTIME_TREE_ALLOWED_EXTRAS 值一致)。
- 本轮零签发/零消费:唯一 gate 调用拒绝证据 `runtime_verify/preissue_gate_P3_preconfig_refused.json`(one_shot_writes=0),且本人当日重演同拒绝(见 RD04)。
- 小瑕疵(P3,不阻塞):披露 §2.1 写"约 30 个"探针目录,实际 52 个(清单文件本身完整);`RUNTIME_STATIC_DEPS.md` 头部仍称 a96bedea 为"Commit A"(W1 期命名,与终版文档 Commit A=85a879a4 撞名,实质内容已按现候选核实无误)。

### RD02 — PASS
抽验 5 项全部与 85a879a4 真实源码一致:
- A1–A6:`R17_FREEZE_DEV_DIRS`(src/rl_curriculum、tests/route_c_stage2_6_1)与 `R17_FREEZE_DEV_FILES`(RouteCStrategy.py/requirements-lock.txt/environment.yml/activate-freqtrade.sh)在 dependencies.py 实存;`_freeze_dev_root()`=rl_curriculum.__file__.parents[2]。
- A7:`_load_v4_module()` qprod_aggregate.py:59,candidates[0]=parents[2]/report ✓。
- A8:`_r10_design_plan_path()` r17_design.py:451 ✓。
- A9:`production_runtime_config_identity()` production_obs.py:224(+_project_root:220;文档行号 215 系 a96bedea 旧冻结源,函数/语义一致)✓。
- A10:levela.py:507 `project_dir/stage2_6_1_runner` is_dir 检查 ✓。
- B 表"src 内 14 处解析点"实数相符:r17_cli 12 处 + dependencies 1 处 + provenance 1 处,全部接入 `release_repo_candidates()`;runner 面 r17_v2_c13_*+r17_supervision 的界外硬编码文档称 6 处、实际 7 处(计数口径小出入,均明确声明界外不改,无消费影响)。
- D 表 producer 边界(动态产物不预造)与预算 gate 由 launch 写的说明与源码一致。
- 附注:r17_admission.py 的 `DEFAULT_RELEASE_REPO`(env R17_RELEASE_REPO 可覆写)未接 pin——但该路径仅用于 admission gate 的 commit-exists 检查(HEAD 无关),链上两签发入口恒显式传 --repo,无实际解析漂移面;不算缺陷。

### RD03 — PASS(全部本人亲测,2026-10-10)
- `python -c` 导入 P3 部署源实测:`release_repo_candidates()[0] = /home/cryptorl/release_pin_qaf_v3`(pin 优先),`_freeze_release_repo()` 解析=PIN。
- PIN 状态:`HEAD=85a879a46d0a20831644eb9aae52e0537436713f`、tree=`06827b7d…`、分支=`route-c-stage2-6-1-repair17`、porcelain 干净、`.git` 为目录(独立 clone,非 worktree 链接)。
- 工程隔离正例(本人自建 out-dir `/home/cryptorl/tmp_rcw_r3/eng_freeze_rcw`):真实 `write_r17_code_freeze` 写出成功,`freeze_surface_digest=r17fs-c4b5818c0aec55fedde63fba523366a6d20b7bbe874e8732ffff9913935070af`(与 evidence 冻结件一致)、`missing=[]`、dev=572、tracked=613、root=PIN、head=A。
- dummy-sha 反例(本人自建 out-dir):`1111…` 被拒,报错`code_freeze_sha 与 repo HEAD 不一致——冻结必须绑定Commit A 提交(HEAD=85a879a4…,传入=1111…)`——严格性未删。
- detach 负例证据链核验:`ancestry_refused_detached_head.json` ok=false 与 `curriculum261_r17_historical.historical_evidence_binding`(current_branch/r17_branch_name_ok 计入 ok)及 cmd_audit 尾部 `heb.get("ok")` 进 rc 判定(返回 1)逻辑闭合;披露 §3 与日志 w5_part3(step3 rc=1,ancestry ok=False)一致;恢复分支态后 step3 全绿日志在案。

### RD04 — PASS
- 代码路径实读:operator `cmd_execute`(qaf_v2_operator_entry.py:221)在环境白名单/哨兵守卫之后、批准原件读取与任何一次性写之前调用 `preissue_gate`;直接 issuer `cmd_issue_permit`(qprod_formal_authority.py:243)同位置同门;admission issuer(r17_admission_issue.py:268)同门。两入口共用的第 7 检查 `runtime_dependencies` 对 qaf_v3 强制(缺 candidate_sha 直接拒),qaf_v1/v2 豁免并注记。
- `runtime_dependency_preflight` 为真实读取器:子进程在 P3 真实 import 冻结函数(freeze manifest+HEAD==A+pin 解析+freeze 路径 clean)+src/tests/runner 三面 vs 候选 CR 投影逐文件+已接受原件字节(98 extras 钉死);非 mock-verifier。
- E1 未装 fail-closed:证据 `preissue_gate_P3_preconfig_refused.json`(deploy_roots 拒:受信任部署配置缺失;one_shot_writes=0)+ **本人当日对 D3 现场重演同拒绝**(refusal 逐字一致、zero writes、authority 目录未创建;输出存 `/home/cryptorl/tmp_rcw_r3/gate_refused_rcw.json`)。D3 `qprod_deploy_config.json` 实测缺席=与"配置仅批准轮激活"一致。
- 隔离测试:test_curriculum261_qaf_v3_runtime_closure.py 实含 **17** 个测试(文档称 14 系旧数,3 项系 qaf_v3 注册补丁期新增;P3 计数瑕疵);逐个审读为真实消费者形态(真实 freeze 子进程、真实 gate、真实 issuer CLI、真实 api import),负例含缺件/错字节/错 HEAD/dirty pin/非 pin 解析/src 漂移;junit.xml 实证 17 项全部在最终绿收集中执行(7 个 skip 全为历史 binding 环境型测试,与本文件无关)。

### RD05 — PASS(本人重跑)
- 同根 substance verify(PIN 为 repo、--deploy-root D3):rc=0,`plan_digest_claimed==plan_digest_recomputed==06827b7d…`,counts={tests:2989,failures:0,errors:0,skipped:7},record sha256=`de43964e…` 实算一致。
- 错根(--deploy-root P3):rc=2,原因 `regression_collection_run_cwd_not_deploy_root`(与证据文件 substance_verify_wrongroot.json 逐字一致)。
- 活链前缀探针日志一致性:step1 stored==recomputed r17gtrec-3112e5de…(与 guard `EXPECTED_TOPOLOGY_DIGEST_PREFIX` 常量同前缀);step2 A4/A5/A6 真实工程跑;step3 anchored surface r17fs-c4b5818c…(与本人 freeze 重算 digest 一致);audit_step_refused.stderr=dummy-sha 拒、audit_step.stderr=缺 determinism contract 拒(fail-closed 另证)。前缀产物与工程消耗(两次 determinism)记账见 RD08。

### RD06 — FAIL(P2,发现 F-1;其余子项全绿)
- 注册面实测(P3 部署源真实 import):QAF3_ALL_NEW=26 名唯一、与 v1/v2 逐名不相交;iteration=qprod_a_formal_v3;input_scope 映射正确;26 名全部在 `CURRICULUM261_SEED_NAMESPACES`(derive261_seed 实测可派生且随 rung 变化);api `CURRICULUM261_R17_NAMESPACES`/`CURRICULUM261_R17_FORMAL_NAMESPACES`、r17_registry 双注册表、`R17_FRAMEWORK_ITERATIONS`(含 qaf_v3)全接通——活链探针逐层暴露后补齐的 5 提交(afc7d82e→85a879a4)与 git 历史一致;85a879a4 相对 45a47547 恰为 3 个测试期望文件(235/24 计数),本人 diffstat 实证。
- 计划不变量(真实构建器重算,同 code_identity 下 v2 vs v3 payload 深度 diff):**仅 `/code_freeze_sha` 与 `/iteration_id` 两键差**;quota/rules/gate_set/budget/budget_items 全等;本人重算 `research_plan_digest(draft)==qbpl-2c65de6fe59a03b817ee3653d744a8c05ccdaf35dac6bba02cf66a20179330e4` 且 draft==rebuilt 逐字段相等。
- v2 消费不恢复:freshness/one-shot 面未动(gate 第 4 检查在);qaf_v3 全新 namespace 注册保证旧机会不冒新。
- **FAIL 部分(授权文本身份失真)**:见发现 F-1。

### RD07 — PASS
- record `regression_evidence_v3_record.json` sha256 实算=`de43964e7ebe476f5ce2e3a88800d157278aa8a99d092a0bb496445a7784e994`(与 summary/文档/substance 复核三处一致);bind commit_a=85a879a4;run r21_20261006_073405 cwd=D3;junit.xml 实测 suites=1 tests=2989 failures=0 errors=0 skipped=7;collection/execution/manifest/auditor 面 proto v6 齐备;executor blob==deploy sha 相符。
- 三方对拍:本人先以独立投影脚本复验(共享件零差异),再取实现侧原脚本 `tmp_a2rc_w5/threeway_w5.py`(输出重定向至本人目录,未覆写证据)原口径重跑:**P3D3 698/698、P3PIN 597/597、D3PIN 660/660、mismatches=0**,与 `evidence/three_way_compare.json` 及 meta 候选绑定精确一致。三根不重叠、PIN/证据仓职责分离成立。
- 262 适用性:本轮候选对 262 消费面的唯一变更是 `A2RC_V1_REGISTERED_CODE_CHANGES`(api.py 登记,两树镜像同 patch 同步,本人 diff 实证);注册面变更不触 262 输入语义,历史 240 passed 复用有据,非换 SHA 改签。
- 失败尝试归档:attempt9(b3e3bffd 绿 2987)、attempt10(45a47547 4F)summary 如实;1–8/尝试目录独立存在。

### RD08 — PASS
- 终验日志 4 件唯一文件名、大小互异、无相互覆盖(w5_rerun_0400Z=4543B/part2_0430Z=8534B/part3_prefix_0450Z=2395B/part4_prefix2_0510Z=1514B);各回归尝试独立 out-dir 归档。
- 工程消耗如实:determinism-matrix 前缀探针 ×2 次工程跑已披露且与日志对应(part3=detached 拒绝次含真实 A4/A5/A6;part4=恢复分支后全绿次)——属工程确定性电池,非科学资格计算,记账口径正确。
- 无恢复件冒称现场日志:恢复件(E0 等)均标 recovered 来源;拒绝输出各自独立成件(gate 两件、audit_step_refused/audit_step 分立)。

### RD09 — PASS
- 绑定值逐一对上:Commit A/tree(本人 git 实算)、计划 qbpl-2c65de6f…(本人真实构建器重算)、record de43964e…(实算)、freeze r17fs-c4b5818c…(本人重跑复现)、三方 698/597/660(原口径复现)、2989 计数(junit/summary)、admission-id `qaf-v3-85a879a4-a2`(COMMANDS E4 与 operator --admission-id 参数匹配;id 为预注册串,create-only 一次性由 issuer 保证)。
- E1–E4 命令面:operator entry argparse 实存 --repo/--deploy-root/--project-dir/--approval-json/--regression-evidence/--admission-id/--authorization/--plan-digest/--plan-digest-method/--code-freeze-sha/--stop-after/--model-update;config_candidate 为 PREP 域副本且注明 D3 未激活。
- 三文档(CLOSURE/PENDING/COMMANDS)无"稍后补/TBD/待补"占位;出口状态=A2_RUNTIME_READY_PENDING_USER_APPROVAL,批准文字为建议模板,未构造正式批准原件,未代签。

## src/tests/runner 变更面(caea5db5..85a879a4)— 合规
18 文件,+1150/−50:guard(+417 preflight/gate 接入)、qaf_attempt(+105 v3 注册)、r17_cli(40,12 解析点换单一来源+模块级 import)、r17_dependencies(24,pin 单一来源)、registry/api/generation_evidence/provenance(v3 对齐)、两树 input_lock(A2RC_V1 对称)、runner 3 文件(仅 candidate_sha 透传)、既有 4 测试文件期望更新、新测试文件 531 行。无删除严格检查(write_r17_code_freeze 的 HEAD==A+clean+完整性由本人正反例实测仍在);无越权改动;14 处解析点接线正确。eba9e75d 相对 85a879a4 src/tests/runner 零变化(本人 diff 实证)。

## 发现清单

### F-1(P2)计划授权文本的 smoke 输入身份未随尝试参数化(qaf_v3 计划指名 v1/r17 旧身份)
- 位置:`stage2_6_1/artifacts/repair17/development/a2_runtime_closure_v1/plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json:445`(embedded_preflight_smoke.description:"输入身份 ppo_smoke_qaf_v1")、`:460`(rules.smoke_policy 同文);同类:同文件 :76/:130(audit/preplan-smoke consumer 指 `preplan_smoke_r17`,实际=attempt family 的 `preplan_audit_bank_qaf_v3`/`preplan_smoke_qaf_v3`)、:220/:238/:265/:355-356/:364/:400(smoke 步 consumer 指 `ppo_smoke_r17`,实际=`ppo_smoke_qaf_v3`);根在 `curriculum261_qprod_formal_levela.py:94/148/174` 构建器硬编码(该文件本轮未改,文本自 476d2733 存在,v2 执行计划同瑕疵,既往审查未指出)。
- 触发条件/影响:qaf_v3 批准将绑定本计划 digest;链实际经 `qaf_attempt_family("qaf_v3")` 解析 smoke/audit-bank namespace(v3 新身份,r17_cli.py:2406-2409/2701-2703、cmd_audit audit_bank_ns 实证),与计划文本相悖——授权表示与真实可达更新路径不一致,违反文本自述的 R3 修复 A-1 原则与 ACCEPTANCE_MATRIX RD06"全输入身份贯通";执行后按计划对账 envelope ledger namespace 将出现文实不符。机器可校验字段(quota/counts)不含 namespace,不构成越权放行;实际消费走 v3 新身份(安全方向),但授权文档事实错误成立。
- 复现:本人 `/home/cryptorl/tmp_rcw_r3/` 探针 S4 输出:rebuilt payload `SMOKE_DESC` 含 ppo_smoke_qaf_v1;`V2_V3_DIFF` 仅两 identity 键(即文本未随 attempt 变)。
- 判定解决条件:构建器以 `qaf_attempt_family(formal_attempt)` 参数化上述文本(或显式在计划中登记 attempt 实际 namespace),重新生成 draft→重算 qbpl digest→重绑 PENDING_APPROVAL_SUMMARY 批准建议文本/COMMANDS/CLOSURE_REPORT RD06 及 E3 批准 10 键中 research_plan_digest 相关值→受影响测试(计划构建/审批绑定相关)复绿→独立复验 RD06 后本项转 PASS。

### P3 观察项(不阻塞、不单独计数为缺陷)
1. CLOSURE_REPORT/PENDING 称"隔离 14 项"测试,实际 17 项(3 项为注册补丁期新增,文档计数未随之更新)。
2. 披露"约 30 个"探针目录 vs 实际 52 个(清单文件完整,计数措辞失准)。
3. RUNTIME_STATIC_DEPS.md 头部"Commit A=a96bedea…"为 W1 期命名,与终版 Commit A=85a879a4 撞名;runner 界外硬编码计数"6 处"实为 7 处(含 r17_supervision 1 处)。

## 探针留档(全部可复查)
- `/f/trading/local/rcw_r3_review/rcw_probe.py`、`rcw_probe2.py`(探针源);`/home/cryptorl/tmp_rcw_r3/`:rcw_probe.py、threeway_rerun.py、threeway_rerun.json、three_way_rcw.json、three_way_rcw2.json、gate_refused_rcw.json、eng_freeze_rcw/r17_code_freeze.json、prereg_rcw.json、substance_same_root.json、substance_wrong_root.json 等。被审对象零写入;旧 P2/D2/旧 P 零写入。
