# FiniteRepair R1 独立内容验收报告 — RouteC_A2_RuntimeClosure_NewAttempt_v1

- 审查日期:2026-10-11。审查人:独立 reviewer(委派,zhipu-coding-plan/glm-5.3-flash:max,逐字配置选择器)。
- 被审对象:仓库 `F:/trading/freqai-rl-audit`(branch `route-c-stage2-6-1-repair17`);候选 Commit A=`0735f2559aa80889bfed16c88d20e5c72c280a75`;证据 HEAD=`6c100699`。
- 上游判据:`local/r1_finite_repair/incoming/…FiniteRepair_R1/REVIEW.md`(对 0f494d27 判 FAIL/NOT CLOSED:RCW-F1 vendor 前置缺失、RCW-F2 PIN 历史原件/分支前置缺失、RD09 探针原件未随包)+ `ACCEPTANCE_ADDENDUM.md`(FR01–FR04)。
- 三根:P3=`/home/cryptorl/projects/crypto_rl_qaf_v3`、D3=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3`、PIN=`/home/cryptorl/release_pin_qaf_v3`(全程只读)。本审查探针/脚本/输出仅写 `/home/cryptorl/tmp_fr1_review/` 与 `/f/trading/local/fr1_review/`;隔离域用真实对象 `--shared` 克隆。
- 边界遵守:零真实签发/消费/launch、零生成/fit/MC/PPO、零 47 分钟全量回归(仅定向测试文件)、零对被审文件与旧失败原件的修改。

## 0. 修复内容核对(commit A)

`git show 0735f255 --stat`:src/tests/runner 面恰好 3 件 = `curriculum261_qaf_provenance_guard.py`(探针三类真实读取器接入 + `vendor_static`/`historical_digests`/`branch_lineage` 三个拒绝标记接入 `runtime_dependency_preflight`→`preissue_gate`) + 新增 `test_curriculum261_qaf_v3_finite_repair_r1.py`(14 项成对测试) + `test_curriculum261_qaf_v3_runtime_closure.py`(rd04 正例改真实 P3/PIN)。`git diff --name-only 0f494d27..0735f255 -- stage2_6_2` = 空(262 面未动);其余变更均在 a2_runtime_closure_v1 证据/文档内(重绑)。

代码走读确认同源不放宽:探针内 `vendor_ok = exists && sha==_r17cli.VENDOR_PIN && clean`(与 cmd_audit 判式一致,`curriculum261_r17_cli.py:1239`);`_hist_ok = _historical_binding()["digests_match"]`(同一函数,cmd_audit ok 必含 `hb["digests_match"]`);`heb_ok = historical_evidence_binding(首个存在候选)["ok"]`(与 cmd_audit 同根同函数;heb 自身 gate 重算即排除 `r16_branch_name_ok`,guard 的豁免与其一致,非放宽)。PYTHONPATH=project_dir/src → r6/r17 全部自最终消费源(P3)导入,`vendor_dir_default()` 按模块位置解析 → 真 P3 vendor,非替身。两入口(`qaf_v2_operator_entry.py:221`、`r17_admission_issue.py:268`)在首一次性写前调 `preissue_gate`,拒则 rc=96 且 `one_shot_writes: 0`;`issue(...)` 仅在 gate 通过后执行。

## 1. FR01 vendor 静态合同 — PASS

上游 4 态 + 恢复,本审查自有隔离域(非复用测试 fixture):基线 ok → 缺目录/正确 HEAD+dirty/clean+错 HEAD → 三态均以 `vendor_static` 单标记拒(无其他 FR 标记混入)→ 恢复后三次均回到全绿。证据:`tmp_fr1_review/results/fr1_probe_results.json` 场景 00–06;R1 套件对应 3 负例 + 基线正例(P3 实跑 14/14 passed,33.63s)。

两入口实跑:operator execute / r17_admission_issue 子进程在 vendor 缺失下 rc=96、stdout 含 `vendor_static`、`"one_shot_writes": 0`、`authority/` 目录不存在(场景 18/19 PASS);完整合法域 operator 通过守卫后抵达批准绑定边界才拒(rc=96,无任何 FR 标记,零一次性写)(场景 20 PASS)。R1 套件同型两用例亦绿。

## 2. FR02 PIN 历史原件 — PASS(附 P2 残余记录)

隔离域(--shared 真 PIN,单条件突变):r2 digest 删除 → `historical_digests` 拒;repair5 digest 改字节 → 拒;r11_code_freeze.json 改字节(HEAD 不变)→ 拒;恢复后基线全绿。**HEAD==A 不掩盖工作树历史件损坏**已由第三例直接证明。证据:fr1_probe_results.json 场景 09/10/11 + residual_probe.json 场景 A;R1 套件 digest 删除/改字节/blob 改变/恢复正例 4 项绿。上游 REVIEW §4 表列全部 7 个曾接受状态在本审查矩阵中逐一转为拒绝(vendor×3 + digest×3 + detached→FR03)。

**P2 残余(不属本轮收口项,如实记录)**:`digests_match` 链(r2–r12 digest+r11/r12 blob 基线)+ heb 不覆盖 cmd_audit 另一消费层 `r11_binding/r13_binding` 的工作树原件(repair11 `r11_iteration_aborted.json`/`cue_contract_audit.json`/`cue_event_trace.jsonl`、repair13 `qualification_result.json`/`qualification_exposure_r13.json`/`r13_iteration_aborted.json` 等)。实证(residual_probe.json B/C):隔离域删 `r13_iteration_aborted.json` 或 `cue_event_trace.jsonl` → preflight 仍 ok=true,而同条件下 `cli._r13_failure_binding`/`cli._r11_abort_binding` fail-closed 抛错(即正式链 audit 步会中途失败,签发已消费)。上游 FAIL 判据与其复现矩阵未含该层,修复与 `cmd_audit` 的 `digests_match`/`heb` 两具名条件同源且未放宽 → 本轮不据此判 FAIL;建议后续候选把 `r11/r12/r13_binding.pass`(或其工作树读取面)一并接入前置,消除与 audit 步的最后离差。

## 3. FR03 分支/血统与既有拒例 — PASS

同 commit detached → `branch_lineage` 拒(heb_branch 空,`r17_branch_name_ok=False`);checkout 错分支名(同 HEAD)→ 拒;恢复命名分支 → 全绿。`r16_branch_name_ok` 豁免与 `historical_evidence_binding` 自身 R17 gate 重算语义逐字一致(该函数 ok 排除同一键),非放宽。既有拒例不退回:缺 env → 非 FR 标记拒(场景 16,problem=freeze 面缺失必需要件);`runtime_closure` 全文件 18/18 passed(含 rd03 错 HEAD、rd04 真实 P3/PIN 正例、既有负例回归面);P3 部署面与候选 A 逐字节一致(guard+两测试文件+r17_cli/r17_dependencies/r6_preflight/r17_historical+两入口,P3/D3 各 6 件 MATCH)。PIN 现场实测:HEAD==0735f255、分支 `route-c-stage2-6-1-repair17`、porcelain 0 行。

## 4. FR04 候选/部署/证据/命令四件绑定 — PASS

- tree:`git rev-parse 0735f255^{tree}` = `b5e719ff067295fb202c75cb10f1a09879084eca`(=substance plan_digest git_tree_digest claimed==recomputed)。
- 计划:真实构建器重算 `research_plan_digest(plan_fr1.json)` = `qbpl-aaa1d6d9595f649efe8925a2fb17a0a5cb61d11004a72cd6395e48f7de0b103d`,与文档一致;与 R3 计划(0f494d27)深度 diff **仅 `code_freeze_sha` 一键**——quota/budget/run_scope/rules/stop_mode/engineering_only 全等,科学预算零扩张,qaf_v3 未换 v4。
- record:`regression_evidence_v3_record.json` 字节 sha256 复算 = `1022baae5cc5f44050d31f69ce481de581f5e403c982f820fc85ed7445f9a81b`,record 内 commit_a=0735f255、run=r21_20261011_034944、3004=2997P+7S/0F/0E、cwd=D3;summary.json ok=true。
- 命令/文档:PENDING/COMMANDS/DECISION/CLOSURE 四件全部绑定 A/tree/qbpl/record/admission-id `qaf-v3-0735f255-a2`/freeze `r17fs-4d507dee`。
- 时序 flake 独立复核:attempt16/17 归档 record(d01dde97/bf6e6285)junit 实读 = `test_curriculum261_r17_fail_closed_integrity_unit.py::TestW01BudgetBarrierFullChain::test_w01_budget_first_barrier_record_and_verify` 与 `test_curriculum261_r25_cue_dev_entry.py::…::test_a02_binding_of_plan_a_rejected_for_plan_b`;两文件不在候选 A 变更集内(与修复零逻辑交集)。隔离重跑:W01 1 passed(28.51s)、r25a02 1 passed(3.38s)、配对 2 passed(32.16s),三态全绿。4 份 logs_fr1_20261010 时间线与 attempt15(超时半途)/16/17(单失败)/18(全绿 rc=0)叙述一致。

## 5. RD09 探针原件 — PASS

`evidence/reviewer_r3/probes/` 在仓@6c100699:6 脚本(rcw_probe×4+coldread×2)与 `outputs/local_*` 六份逐字节相同(git blob id 一一比对 SAME);输出件 13 份(3 冻结 JSON+3 gate 拒例+COLD_READ_RECEIPT+3 三方对拍)齐备非空。RD09"原件可读"收口达成(最终 ZIP 封包随"等待最终封包"步执行,不属本轮判定量)。

## 6. 抽查与现场复算

- 活体 preflight 复跑@真实 P3/PIN(只读,2.5s):ok=true,vendor sha=52bc96f4(=VENDOR_PIN)clean,hist_digests_match=true,heb_ok=true,branch 正确——与 `preflight_P3.json` 证据逐字段一致。
- 三方对拍独立复算(CR 归一,排除 pycache):src/rl_curriculum(P3D3 shared=393/PIN shared=326)、tests/route_c(P3D3=176/PIN=145)、runner(P3D3=125/PIN=125)+4 根原件(P3==D3):**全部 0 diff**;与证据 699/598/661 全等相容(P3 tests 多出的 31 件 = RUNTIME_TREE_ALLOWED_EXTRAS 旧 P 血统钉死清单内成员,逐字节核对通过)。
- substance:同根 rc0(plan digest b5e719ff claimed==recomputed)/错根文件内容=`regression_collection_run_cwd_not_deploy_root`(拒)。
- prefix_probe_fr1_0735f255:freeze JSON 绑 A=0735f255+r17fs-4d507dee;step1 provenance pass(stored==recomputed);step2 determinism A5/A6 pass;step3 audit anchored@0735f255、digests_match/ancestry/r11–r14 binding 全 pass;dummy-sha(000…0)拒例 stderr 在档("冻结必须绑定 Commit A");preissue_gate_P3_preconfig_refused.json(E1 未装 fail-closed)在档。

## 7. 收口判定(按上游 REVIEW.md 第 7 节)

| 项 | 判定 | 关键证据 |
|---|---|---|
| FR01 | PASS | 本审查隔离域 4 态+恢复+两入口 rc=96 零一次性写;套件 14/14 |
| FR02 | PASS | digest 删/改/blob 改三态拒+恢复绿;HEAD==A 不掩盖;P2 残余另录 |
| FR03 | PASS | detached/错分支拒;豁免=heb 自身语义;既有拒例 18/18 不退回 |
| FR04 | PASS | A/tree/qbpl/record/admission-id 四件绑定复算全中;预算零扩张;flake 三态绿;262 未动 |
| RD09 | PASS | 6 脚本+输出件在仓,逐字节 SAME |

**FiniteRepair R1 修复验收通过;等待最终封包与冷读。**

非阻塞发现(不改变上述判定):①P2=r11/r13 binding 工作树证据层未入前置(见 §2,建议后续候选补线);②P3=CLOSURE_REPORT_RC.md RD07 行内"three_way_compare.json meta 绑定 0f494d27"为陈旧小句,实际文件已绑 0735f255;③P3=r13 两份 digest 文件不在 digests_match 链属 cmd_audit 既有语义(与前置同源),建议文档注明覆盖边界。

出口状态确认:未签发、未消费、未 launch、未代签任何 CLOSED PASS;`A2_RUNTIME_READY_PENDING_USER_APPROVAL` 维持。
