# RouteC_A2_RuntimeClosure_NewAttempt_v1 — FiniteRepair R2 独立内容验收报告(FR2)

- 审查人:独立第二轮 reviewer(与 R1 reviewer、主 Agent 分离;只读被审对象)
- 日期:2026-10-11
- 被审对象:仓库 `/mnt/f/trading/freqai-rl-audit`(分支 `route-c-stage2-6-1-repair17`)
  - 候选 Commit A = `c0fb685823eb4733bda9f5920601311228d55fde`(tree 实测 `git rev-parse A^{tree}` = `a2621f8e9843aecac7d99bc85377e30d91d90b0f`)
  - 证据 HEAD = `15e1e936`(A→证据 HEAD 三次后继仅 `a2_runtime_closure_v1/` 下文档/证据/计划,`git diff --name-only c0fb6858 15e1e936` 无任何 src/tests/runner/stage2_6_2 变更)
- 三树:P3=`/home/cryptorl/projects/crypto_rl_qaf_v3`、D3=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v3`、PIN=`/home/cryptorl/release_pin_qaf_v3`(全部只读;实测 PIN 工作树 HEAD==`c0fb6858`、分支 `route-c-stage2-6-1-repair17`、porcelain 干净;P3 vendor HEAD==`52bc96f4480b1a0d`、clean)
- 方法:上游 REVIEW.md/ACCEPTANCE_ADDENDUM.md 逐项对照 + 自建隔离域实测 + P3 定向套件复跑 + 证据原件对拍。本方探针/脚本/输出全部位于 `/f/trading/local/fr2_review/` 与 `/home/cryptorl/tmp_fr2_review/fr2_dom/`,未写入任何被审对象。

## 结论总览

| 项 | 判定 | 核心证据 |
|---|---|---|
| FR2-01 历史静态合同(bind 层前置) | **PASS** | 自建隔离域 13 突变/正例场景全过;真实根活体复跑 bind r11/r12/r13 全 true;代码核对 r14/r15 纯 heb 派生 |
| FR2-02 路由和副作用(三入口) | **PASS** | P3 定向套件 27/27 绿;自建入口级注入探针:直接 issue-permit 子进程在 r13 历史突变下 rc=96/`historical_bindings`/零写;合法域穿全部前置至批准原件边界截停 |
| FR2-03 相邻控制保持 | **PASS** | r1 套件 14 项绿;binder wrapper 语义逐字保持(diff+5 例行为探针);vendor/digests/分支单标记拒例不退回 |
| FR2-04 原件与最终绑定 | **PASS** | FR1 探针原件入仓可读;A/tree/计划/record/admission-id 五重绑定逐项复算命中;计划深 diff 仅 code_freeze_sha |

**总判定:FiniteRepair R2 修复验收通过(4/4 PASS,无阻断项)。**(收口行见文末)

---

## FR2-01 历史静态合同(r11/r12/r13 binding 层前置)— PASS

### 修复内容核对(diff c0fb6858~1..c0fb6858)
- `curriculum261_r17_cli.py`:三个真实 binder 重构为只读 checks(`_r11_abort_checks`/`_r12_abort_checks`/`_r13_failure_checks(release_repo)`),wrapper(`_rXX_*_binding(out_dir)`)保留原 release repo 解析 + `raise_reason` 重抛 + 写盘 + fail-closed 重抛;比对面与 R2 前逐字一致(r11:marker blob/iteration/exposure+final 必须缺席/cue audit+trace blob;r12:marker 内容+8 blob+2 digest+exposure/plan/final 缺席;r13:result verdict+failed_checks/exposure/abort+5 blob+2 digest)。
- `curriculum261_qaf_provenance_guard.py`:内嵌探针以 `_rr`(`dep.release_repo_candidates()`,与 binder 同源函数;r17_cli 经 import 共用单一来源)直接调用三个 checks,产出 `bind_states`/`bind_errors`;`runtime_dependency_preflight` 新增 `historical_bindings` 拒绝标记;`_rr is None` 时 checks 返回 raise_reason → False(fail-closed,无 NameError 逃逸)。
- HEAD==A 不掩盖工作区损坏:blob 比对用 `git hash-object <工作树文件>` vs `git rev-parse <基线提交>:<rel>`,与 HEAD 无关;且检查链仍要求 `repo_root` 解析到 PIN 根且 HEAD==A。

### 我自己的隔离域实测(--shared 克隆真实 PIN)
域:PIN --shared 克隆@sparse(HEAD==A、分支 repair17)+ 候选字节 project + vendor@VENDOR_PIN shared 克隆;`runtime_dependency_preflight` 以 monkeypatch `R17_PIN_EXPECTED_ROOT` 指向克隆(P3 定向套件同法)。结果(`fr2_probe_results.json`,12 场景全 PASS):

| 场景 | 拒绝 | bind_states | 单标记 |
|---|---|---|---|
| baseline 正例 | ok=true | r11/r12/r13 全 true | — |
| r11 trace 缺失 | 拒 | r11=false,余 true | 仅 historical_bindings |
| r11 abort marker 字节 | 拒 | r11=false | 仅 |
| r11 应缺席 final 出现 | 拒 | r11=false | 仅 |
| r11 cue audit 改变 | 拒 | r11=false | 仅 |
| r13 abort 缺失 | 拒 | r13=false | 仅 |
| r13 result blob 改变 | 拒 | r13=false | 仅 |
| r13 exposure 缺失 | 拒 | r13=false | 仅 |
| r13 plan digest 改变 | 拒 | r13=false | 仅 |
| r12 marker 字节 | 拒 | r12=false | historical_bindings+branch_lineage(heb 与 binder 同源双检出=设计,实测命中恰此二元) |
| r12 应缺席 exposure 出现 | 拒 | r12=false | 仅 |
| 恢复正例 | ok=true | 全 true | — |

每场景均断言 `repo_head_commit==A`(HEAD==A 全程,损坏仍被拒)。补测上游 17 场景矩阵余下行(`fr2_extra_results.json`,ALL_PASS):r13 result 文件缺失、r13 abort marker 字节改变、r11 abort marker 缺失——全部目标 bind false、单标记、HEAD==A。**上游探针旧行为(突变前置仍 ok)在同输入下已全部转为 `historical_bindings` 拒绝。**

### r14/r15 覆盖核对(代码)
`_r14_failure_binding(out_dir, heb)`/`_r15_failure_binding(out_dir, heb)` 仅消费已算 heb dict(`checks` 的 `r14_*` 键 / 常量 `r15_governance_binding`),零独立工作树读取;r16_historical 的 heb `checks` 含全部 r14_*/r15_* bool 检查,heb gate(`ok`=除 `r16_branch_name_ok` 外全 true)覆盖之——preflight 的 `heb_ok` 即覆盖 r14/r15 所需。**属实。**

### 真实根活体复跑
unpatched 对真实 PIN/P3 复跑 `runtime_dependency_preflight`:ok=true、bind r11/r12/r13 全 true、vendor/hist/heb true——与 `evidence/runtime_verify/preflight_P3.json` 逐字段一致。

## FR2-02 路由和副作用(三入口共同前置)— PASS

### 代码接线核对
`preissue_gate` 第 7 步调用 `runtime_dependency_preflight`(qaf_v1/v2 豁免;qaf_v3 强制),problems(含 `historical_bindings`)→ `_fail`,全程 `one_shot_writes=0`、`report_out` 受路径/链接加固。三入口均在任何一次性写之前调用 gate:operator `cmd_execute`(qaf_v2_operator_entry.py L221)、直接 `issue-permit`(qprod_formal_authority.py L243;缺 --repo/--project-dir 为另一条早拒路径 L229,与本验收无关)、admission(r17_admission_issue.py L268)。拒因均映射 rc=96。

### P3 定向套件(真实部署环境)
`pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v3_finite_repair_r1.py test_curriculum261_qaf_v3_finite_repair_r2.py -q -p no:cacheprovider` → **27 passed(14 r1 + 13 r2),0F/0E**(67.85s)。含:operator execute vendor 突变 rc=96/零写/authority 不存在;admission vendor 突变 rc=96/零写;直接 permit vendor 突变 rc=96/零许可写;合法完整配置穿全部前置在批准原件边界截停(拒因非缺参数;断言输出无任何守卫标记)。

### 我自己的入口级历史突变注入(超出交付测试的补强证据)
交付测试如实披露:入口子进程内 PIN 解析=guard 常量,历史突变不可按 env 注入,入口级以 vendor 证明接线、binding 拒绝由 preflight 级九场景覆盖。**我用测试夹具技术(子进程内、runpy 前 monkeypatch 同一常量,等价 pytest monkeypatch;不改任何被审文件;生产 env 白名单不变)把历史突变真正注入了直接 issue-permit 入口子进程**(`fr2_entry_probe_results.json`,ALL_PASS):
- r13 abort marker 删除 → 真实入口子进程 rc=96,stdout 含 `签发前守卫拒绝(首一次性写前)` + `historical_bindings` + `"one_shot_writes": 0`,authority 目录零 permit 文件;
- 同一子进程合法域 → 穿过全部前置(gate 内 vendor/hist/heb/binding 全绿)在 `用户批准原件缺失` 边界截停(rc=96,零许可写,无守卫标记);
- vendor 缺失同 gate 拒绝(rc=96/vendor_static)作为同路径对照。
**接线充分性评估:充分。** vendor 拒例证明"入口→preissue_gate→preflight problems→rc=96/零写"管道,历史标记与 vendor 标记产生于同一 problems 列表的同一次 preflight 调用;我的注入实验进一步证明同一管道对 `historical_bindings` 端到端生效。零 authority/permit/admission 写、零科学调用(隔离 fixture 域,非真实正式配置)。

## FR2-03 相邻控制保持 — PASS

- r1 套件 14 项(vendor 缺目录/dirty/错 HEAD、digest 缺失/改字节/r11 blob 改变、恢复正例、detached/错分支、缺 env、两入口拒例+合法域至下一边界)全绿(P3 实跑)。
- binder wrapper 语义保持:diff 逐字核对(硬缺失消息原文、写盘→重抛次序、fail-closed 消息不变)+ 行为探针 5 例全 PASS(`fr2_wrapper_probe_results.json`):r11 hard-missing=写前抛 RuntimeError(原消息);r11 trace 缺失=先写 `r11_abort_binding.json` 再抛 fail-closed(原消息);r13 result 损坏 JSON=**原 JSONDecodeError 类型直传**、零写;r13 有效但篡改=先写再抛;健康域=写盘+pass=true。诊断文件只落我方隔离目录。
- 单条件突变不触发相邻标记:FR2-01 全部场景断言 vendor_static/historical_digests/branch_lineage 不出现(r12 marker 字节按设计双检出)。上游 17 场景语义不退回:正例仍过、相邻控制(vendor/digests/分支)拒因不变。
- 未删除后段守卫:cmd_audit 未改动(diff 无此函数),r10–r15 binder/编排调用次序不变;仅必要适用回归(3017 全量,见 FR2-04)。

## FR2-04 原件与最终绑定 — PASS

- **FR1 探针原件在仓可读**:`evidence/reviewer_fr1/probes/`(fr1_probe_driver.py、residual_probe.py、outputs/fr1_probe_results.json、outputs/residual_probe.json、preflight_rerun_P3.json、threeway_sample.json、zip_integrity.json、dom 配件;README_FR1_ORIGINALS.md 如实标注缺失边界:入口完整 stdout 未逐条落盘、fixture 克隆目录未收编)。实读 `residual_probe.json`:B(删 r13 abort marker 前置仍 ok)+ 同条件 audit 侧 RAISED 原件在案——上游 R2 FAIL 的直接依据可复核,未重写 reviewer 原结论,未补造数据。
- **四文件绑定一致**(逐项独立复算):
  - A=`c0fb6858`(PIN HEAD、证据 preflight、freeze、record.commit_a_sha 多点一致);tree=`a2621f8e9843…`(`git rev-parse A^{tree}` 实测命中;substance claimed==recomputed 同值);
  - 计划摘要 `qbpl-5963af98aca388afbbe8a9088da70a26a556ee31096186f12d53c44dbf1145fd`——按 canonical JSON(sort_keys+紧凑分隔符)重算 **逐字命中**;
  - record SHA-256 重算 = `007baaf328b2…` 命中 `evidence/regress261_d3/regression_evidence_v3_record.json`(commit_a=c0fb6858、deploy=D3、run `r21_20261011_061035`);
  - admission-id `qaf-v3-c0fb6858-a2` 见 COMMANDS_APPENDIX.md L49 与 PENDING_APPROVAL_SUMMARY.md。
- **计划与 FR1 深度 diff 仅 code_freeze_sha**:392 个叶子键双侧,唯一差异 `/code_freeze_sha: 0735f255→c0fb6858`(科学预算/规则/run_scope/停止条件零变化)。
- **262 面未动、qaf_v3 保持**:候选 diff 仅 stage2_6_1 四文件;证据提交仅 a2_runtime_closure_v1 下文档/证据;D3 无 artifacts/formal_a_qaf_v3、无 state(零签发/零消费/零 launch 实态)。
- **回归计数一致**:junit.xml 独立解析 3017 tests/0 failure/0 error/7 skipped == summary.json aggregate == record.collection_tests=3017;`logs_fr2_20261011/regression_c0fb6858.log` 尾部 GREEN。
- **attempt19 如实归档**:`evidence/regress261_d3_attempt19_0735f255_superseded_by_fr2/`(record `1022baae…`=上游 REVIEW §1 所引 FR1 record;3004=2997P+7S 与上游终验解析一致,目录名如实标注被 FR2 候选更替)。

## 抽查项

- `prefix_probe_fr2_c0fb6858/`:step1 provenance pass(r17gtrec-3112e5de stored==recomputed);step2 determinism A4/A5/A6 pass;step3 audit **anchored c0fb6858**(surface r17fs-1fed389b,dev_files=574)、ancestry ok、r11/r12/r13/r14 binding 全 pass、determinism_contract=bound;`audit_step_refused.*`=dummy-sha 反例在案。anchored freeze 与 `freeze_engineering_P3.json` 的 `r17fs-1fed389b9fea1764…` 同值。
- substance:D3 同根 rc=0(claimed==recomputed a2621f8e);wrong-root 拒件实测为 `regression_collection_run_cwd_not_deploy_root`。
- 三方对拍抽样复算:7 个关键文件(R2 改动的 guard/r17_cli/两测试 + 3 入口/历史件)CR 归一化 sha256 在 P3==D3==PIN@cand==PIN@HEAD 全等(与 three_way_compare.json 700/599/662 全等口径一致)。
- `preflight_P3.json` 的 bind_states 与我方真实根活体复跑逐字段一致(见 FR2-01)。

## 边界与如实说明

- 本审查未跑 50 分钟全量回归(对拍既有 3017 evidence 原件;定向套件 27 项实跑);未激活真实正式配置、未签发/消费/launch;PIN 工作树与真实 vendor 逐字节未动;隔离域克隆位于我方 tmp。
- 我方第一版补测脚本存在自证判定 bug(把预期的 ok=false 也计入 is True 判定),修正后重跑;被审对象行为在两个版本中均正确。已披露,不计入交付问题。
- 入口级注入使用测试夹具技术(等价 monkeypatch),仅证明接线管道;不构成、也不需要生产环境支持重定向(env 白名单原样)。

---

## 收口(按上游 REVIEW §6)

| 上游要求 | 判定 |
|---|---|
| r11/r12/r13 绑定层进入首一次性签发前必要检查(§3 主阻断) | **满足**(FR2-01:探针→gate→三入口接线 + 13 场景实测) |
| 直接 qprod_formal_authority issue-permit 路径实测证据(§6) | **满足**(FR2-02:P3 套件 13 项 r2 + 独立入口级 historical_bindings 注入拒例 rc=96 零写 + 合法域至批准边界) |
| FR1 探针原件归档(§5) | **满足**(FR2-04:probes/ 目录 + README 如实标注) |
| operator / admission 防御性检查、相邻控制不退回(§6) | **满足**(FR2-03:r1 14 项 + wrapper 语义 5 例 + 单标记矩阵) |
| 候选/回归/三根/计划/命令绑定(§6) | **满足**(FR2-04:五重绑定逐项复算命中) |

**FR2-01 PASS;FR2-02 PASS;FR2-03 PASS;FR2-04 PASS。**

**FiniteRepair R2 修复验收通过;等待最终封包与冷读。**
