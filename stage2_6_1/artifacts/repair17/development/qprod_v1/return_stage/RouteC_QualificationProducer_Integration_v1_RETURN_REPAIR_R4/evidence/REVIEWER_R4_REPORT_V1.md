# QProd R4 返修轮独立内容验收报告 v1
- reviewer: OMP 用户配置 reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、实际工具、真实原件;未沿用 C13 旧 PASS
- 对象: 第四次返修轮 C14=3d2193e24105647f48419ce401016eb442d2baa1(修复)+ b38b95cc(证据,当前 HEAD,已 push)
- 输入: local/reviewer_handoff_r4.md、REVIEWER_ADDENDUM_R4_ORIGINAL.md(32 行原文)、原 22 项矩阵(ACCEPTANCE_MATRIX.md)、repair_round4_notclosed/ 全部证据、git show 3d2193e2/b38b95cc、C7 旧原件与 E01 原件对照
- 边界: 零新增原生/MC 研究/fit/optimizer(本轮所有验证均为合成/只读/定向);原生 2/2 耗尽未清零;不代签 ChatGPT CLOSED

## 0. 结论
**PASS**(内容验收;失败项:无)。最终 CLOSED 由 ChatGPT 独立终验;内容 PASS 后进入增量 ZIP 冷读+包外回执(PK01 尾段)。

## 1. 独立验证记录(本轮实际执行,全部 rc=0)
WSL 部署树 /home/cryptorl/projects/crypto_rl,python=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python,PYTHONDONTWRITEBYTECODE=1:
1. `bash /mnt/f/trading/tmp_r4_review.sh`(探针脚本,26s):
   - 仓库状态: HEAD=b38b95cc;3d2193e2 为 HEAD 祖先;5 个改动文件 porcelain 空(工作树=提交内容)
   - A. 部署树 vs C14 提交字节身份: 3 个 src(r17_cue_contract/levela/aggregate)+2 个测试文件 **MATCH**;runner 脚本与 b38b95cc 证据提交 MATCH(c10c5e6b…,首次比对误用 3d2193e2 已更正——该脚本属证据提交)
   - B. 定向测试: r4+r3 两文件 `pytest -q -p no:cacheprovider` → **26 passed**(r4=9,r3=17),rc=0
   - C. E01 只读复算(独立重跑,C14 代码): run1 valid=1/inconclusive/stats_gate_failed=[c01];run2 valid=2/inconclusive/[c01,c02];全部数值(recall 0.9607843137254902/se 0.028292718593392892/c02 se=0.0 等)与 E01_RECOMPUTE_C14.json 逐值一致 → **E01-RECOMPUTE-MATCH: OK**
   - D. fixture 双重态探针: 见 §2.6 → **FIXTURE-DOUBLE-STATE: OK**
   - E. r21 record 158 测试文件身份: **deploy@run == deploy@now 158/158**;与 C14 提交 146/158 字节同,12 个为 **CRLF-only**(内容零差异,见 §4.3);collection/execution verdict=pass、violations=[]
2. 证据面核验(Windows 侧只读): record sha256 实算=c497f7ce…4324 与 summary/声明一致;junit.xml sha256 与 record 绑定一致、2678 testcases/0 failure;262 v8 junit 240/0 fail、meta candidate=3d2193e2、rc=0;e02 七个 meta 全 rc=0
3. C7/E01 原件保护: `git status --porcelain` 于 full_regression_v6/ 与 native_smoke_run{1,2} 为空(最后触达提交=e487a10e C7 轮);E01_RECOMPUTE_C14.json 与 R3 的 C12 版除 format 标签外 **diff 为空**

## 2. Q1 规则同源(不只 8 个名字同源)
### 2.1 单一事实源
`recompute_audit_semantics_from_report`(curriculum261_r17_cue_contract.py,+166 行,R4 新增)与生成内核同模块共享冻结常量 AUDIT_MC_ABS_TOL=0.001 / AUDIT_DIFF_TOL_FLOOR=0.005 / AUDIT_DIFF_SE_FACTOR=3.0(L108-110),无报告自带阈值。逐条对照:
| 规则 | 生成内核(§12) | recompute | 等价 |
|---|---|---|---|
| MC | `abs_diff <= AUDIT_MC_ABS_TOL`(L914-916) | 同冻结常量;**不读** report.monte_carlo.tolerance,tolerance≠0.001 记 threshold_drift 并按冻结值判 | ✓ |
| per-corpus | `replay_ok ∧ bounds_ok ∧ cue_table ∧ ci[0]<=p_contract<=ci[1] ∧ |emp-ana|<=max(3SE,0.005) ∧ tail_ok`(L765-786) | 逐键同公式重算(L1152-1205);整体与 tail 均为 max(3·SE,0.005) 冻结公式 | ✓ |
| tail integrity | 子条件 per_corpus ok∧无 violations | ti 在场→重算子条件;缺失→正式 False/fixture 委托 | ✓ |
| global_k/once_vs_attempts/aggregate | 子条件一致性重算(pass/verdict≠INDETERMINATE/recall+k modes+bitwise) | 同 | ✓ |
digest 函数本体未改(diff 仅在 `_synthetic_probe_check_names` 与 `cue_contract_audit_digest` 之间插入);黄金向量通道不变,2678/0F 含全部旧接口黄金向量测试。
### 2.2 Level A gate1 接线
`judge_qualification_gates`(levela.py L296-343)以 `from rl_curriculum.curriculum261_r17_cue_contract import recompute_audit_semantics_from_report` 调用单一事实源,替换 R3 手搓数值逻辑;`cue_ok` 合取保留 R3 全部既有通道(digest 复算一致、checks_all_true、pass==all(checks)、checks 键集合==权威 8 项)**并新增 semantics_consistent**;threshold_drift 落入 observed 如实上报。读取侧(export)同源。旧键 mc_close_recomputed/numbers_consistent_with_checks 在 src+tests 全库无残留引用(干净切换,R3 测试键名同步语义不变)。
### 2.3 四反例(全部 checks 强制全 True+digest 重算自洽,拒)
`_mutate_and_redigest` 修改后强制 `checks={k:True}`、`pass=True`、重算 audit_digest——hash 通道自洽,拒绝只能来自语义重算:
- CI 排除解析值(validation ci95 抬到 p_contract 之上)→ validation_corpus_ok 重算 False,verdict FAIL ✓
- replay=False(model)→ model_replay_bitwise_ok=False、model_corpus_ok=False,FAIL ✓
- tail 数值失败+容差放大到 1.0 → validation_tail_numeric_within=False + threshold_drift 含 tail.diff_tolerance ✓
- MC 容限 1.0(p_hat 偏 0.05)→ mc_close_to_analytic 按冻结 0.001 判 False + threshold_drift 含"冻结值" ✓
纯结构用例补 CI/replay/MC 漂移直判。测试文件 9 项本轮实跑通过。
### 2.4 合法对照
未篡改 rehearse 产物 gate1 PASS、semantics_consistent=True、threshold_drift==[](test_r4q1_legal_control_passes);手工构造正式结构报告(全字段+checks 全 True)recompute all_consistent=True(test_r4q1_recompute_pure_structure_cases)——合法手工 raw 正例可过。
### 2.5 阈值来源
全部三个阈值取自模块冻结常量;报告自带 tolerance/diff_tolerance 仅用于**漂移检测**(≠冻结公式即记 discrepancy),永不作为判据。
### 2.6 fixture 双重态(独立探针实测)
合法 fixture 报告(engineering_fixture=True):fixture_mode=True;fixture_delegated=恰好 10 个**在场缺失**支撑键(model/validation 的 replay_ok/bounds_ok/cue_table + global_k_audit + once_vs_attempts + aggregate_recompute_ok + tail_mirror_bound_integrity),逐一核对报告中确为缺失(委托诚实);在场数值字段(emp/ana/ci95/tail 8 events)全在且真实过冻结公式;把**在场** replay_ok 翻 False → model_corpus_ok=False(不被委托吞掉);gate1 合法 fixture PASS。正式报告缺任何支撑字段=False(fail closed)。
### 2.7 不放宽论证
recompute 仅作合取新增(semantics_consistent 替换并严格强于 R3 numbers_consistent);checks 全 True+数值违规则必 mismatch→all_consistent=False→gate 拒;唯一 PASS 路径=数值真实满足冻结规则。fixture 只豁免"缺失支撑字段的存在性",不豁免任何在场数值判据。未发现放宽路径。

## 3. Q3 条目向下关联
### 3.1 条目 500 vs global/qcap/report/实际 2 → 拒
`_verify_coordinate`(aggregate.py L241-283)新增: (a) 条目级 blocks_per_corpus/mc_events ↔ global audit_budgets 对账;(b) 条目 blocks ↔ qcap budgets 对账。测试(实跑通过): 计划重冻结为"条目 500+global 2"新计划后,`_verify_coordinate` invalid(problems 含 "blocks_per_corpus=500 != global audit_budgets 2")且 **aggregate_research 完整装载路径 valid_coordinate_count==0**;既有 R2/R3 通道(qcap↔report、plan↔report、block_range、事件范围)全部保留。
### 3.2 防脱钩
传入 coordinate 必须逐字段等于冻结 manifest 同 id 条目: 不在清单→拒;字段不一致→拒并列 differing keys。测试: 用同计划另一条目的合法(已注册)namespace 构造 rogue 条目→invalid("脱钩")。aggregate 主路径传 manifest 本体条目不受影响。
### 3.3 legacy(E01)兼容与合法对照
audit_budgets 整块缺失的 legacy 计划: global 侧对账跳过,条目↔qcap↔report 三方仍在;合法 2 块对照(global=qcap=report=实际=条目一致)valid(test_r4q3_legal_two_block_control_still_valid);E01 原件经 C14 代码复算仍 valid+nrv+如实 inconclusive(§1.C)。
### 3.4 E01 未重生成
E01_RECOMPUTE_C14.json 与 R3 C12 版除 format 标签(c12→c14)外 diff 为空;native_smoke_run{1,2} 原件 git 状态原样;我的独立复算数值逐值一致。

## 4. R01 真实审计记录
### 4.1 audit_collection.json 正文(非三行声明)
format=cur261-r24-collection-audit-v3;argv=真实 pytest 子进程 `-p r21_collection_auditor tests/route_c_stage2_6_1 --collect-only -q`;**三阶段快照**(configure/collection_finish/sessionfinish,各含 collected_items/snapshot/violations;collection_finish 起 collected_items=2678);lifecycle 五块(monitor/register_guard/reconcile(38 events/33 plugins/uncovered=[])/events/violations)+44 行 JSONL 逐事件(seq/pid/utc/分类);白名单 env(PYTEST_DISABLE_PLUGIN_AUTOLOAD=1)。verdict=pass,violations=[]。
### 4.2 执行与 record
audit_execution.json 同构(2678,junitxml 真实路径);execution.stdout 2671 passed+7 skipped in 2536.52s(42 分 16 秒真实耗时),7 skip==historical_skip_ids 7 项(无新增 skip);record(format cur261-r17-candidate-regression-evidence-v6)含 commit_a_sha=3d2193e2、158 测试文件逐件 deploy_sha256、junit sha256(实算一致)、audit_manifest sha256、executor 身份;**record sha256 实算=c497f7ce…=summary 声明**;verify collection_tests=2678/static=2192/files=158。执行器=既有 stage2_6_1/runner/r21_full_collection_regression.py(--shard 能力默认单目标,与 C7 旧件同接线同形状),非自造元数据。
### 4.3 身份链
record 158 文件: deploy@run==deploy@now 158/158;==C14 提交 146/158 字节同;12 个差异文件(r14_governance、r15×7、r7×4)经逐文件 CR 剥离比对 **全部为 CRLF-only(repo blob CRLF vs deploy LF,内容零差异,real_diff=0)**——属 R7/R14/R15 时代既有换行风格差异,非本轮引入、无行为影响。行为面(3 个改动 src+2 个改动测试+runner)与 C14 提交逐字节一致。
### 4.4 旧原件
C7 full_regression_v6/(e487a10e)与 E01 native_smoke_run{1,2} git 状态原样未倒填;C14 新件独立归档于 repair_round4_notclosed/evidence/regress_v6/full_regression_v6_c14/(summary 结构与 C7 同协议: 2614→2678 测试、154→158 文件,增量恰=q123 21+r2 17+r3 17+r4 9=64 测试、4 文件,完全对账)。
### 4.5 262 与 E02 定位
262 v8: meta candidate=3d2193e2、rc=0、240 passed(152.86s)、junit 240/0——stage2_6_2 在 2b49a28e→b38b95cc 零改动,适用性成立。E02 七步 rc=0,COLLECTION.json 明确标注 "E02 is engineering-path chain; 261 regression originals are in regress/"——只作链路证据,不冒充 261 回归。

## 5. 22 项矩阵对账
| 项 | 判定 | 依据(本轮复验方式) |
|---|---|---|
| B01 | PASS | HEAD=b38b95cc 接续 2b49a28e;diff 未触 R25/TB 面;r21 0F |
| A01 | PASS | 17 步上下文面未被 R4 触及(gate1 仅判定侧);r21 0F+e02 rc=0 |
| A02 | PASS | 许可/状态隔离面零改动;复用 C13 结论+回归绿 |
| A03 | PASS | 两阶段计划面零改动;复用+回归绿 |
| A04 | PASS | 一次性/中断面零改动;interrupted/missing 语义在 diff 外未动 |
| C01 | PASS | coordinate 面零改动;复用+回归绿 |
| C02 | PASS | Q1 强核对:共享核心+冻结常量+黄金向量通道不变(§2.1);r21 0F |
| C03 | PASS | 锚面零改动;复用+回归绿 |
| K01 | PASS | K 聚合面零改动;复用+回归绿 |
| K02 | PASS | 早停科学定义未改(R3 事前定义 delta>margin、se=0 退化不判负,R4 diff 未触;旧早停探针按 addendum 不作否决、亦未翻绿) |
| X01 | PASS | 公共判定→导出链: gate1 新判定下合法对照过+e02 04 export rc=0+零手工修补 |
| X02 | PASS | e02 06 formal_reject rc=0;四反例拒(§2.3) |
| X03 | PASS | pack/fit 来源面零改动;复用+回归绿 |
| X04 | PASS | 消费/授权隔离零改动;e02 05/07 rc=0 |
| E01 | PASS | 2/2 原件原样;只读复算数值逐值一致(§3.4);无新原生 |
| E02 | PASS | R4 七步 rc=0,标注为链路证据非 261 回归(§4.5) |
| E03 | PASS | e02 07 cold_read ok(C14 bundle r4pb-26382fb1…,零生成/fit/optimizer) |
| R01 | PASS | §4 全部:真实 r21 v6 原件+record sha256 验证+身份链+C7 原样+7 skip 既有 |
| P01 | PASS | 本轮零原生/MC/fit/optimizer;qprod_native_budget.json consumed=2/max=2 未清零;重型作业唯一(r21 42min),e02 为轻量链 |
| D01 | PASS(沿用) | 出口文档面未被本轮触及;待终验轮确认 |
| RV01 | PASS(本报告) | 独立上下文实际工具;四反例/正例/探针原件见 §1-§4 |
| PK01 | 待内容 PASS 后段 | 增量 ZIP 冷读+包外回执为本报告 PASS 后既定流程,不在本轮内容验收范围 |

## 6. 局限与如实说明
1. 12 个测试文件 repo blob 为 CRLF、部署副本为 LF(R7/R14/R15 时代既有,内容零差异)——建议后续轮统一,非本轮缺陷、不作否决。
2. EVIDENCE_INDEX/交接称 "R3 18" 与实际收集 17 有 1 之差;但 149 总数精确对账(137 侧 261+12 侧 262)且全绿,属文字误差非证据缺陷。
3. "分片执行"=r21 执行器既有 shard 接线(本轮单目标,与 C7 同形状);record 中 1 collect+1 execute 与 C7 一致。
4. 本报告为 OMP reviewer 内容验收;不代签 ChatGPT CLOSED;后端元数据(平台未返回者)无从核验,如实留白。
5. 早停: 本轮未改定义;1 个旧早停探针按 addendum 与未批政策相关,维持不翻绿、不否决。

## 7. 判定
**PASS** — Q1/Q3/R01 三组修复全部实质达标;四反例真拒、合法对照真过、阈值全冻结、fixture 委托诚实;条目贯通+防脱钩在装载与 aggregate 双路径拒;E01 未重生成;R01 为真实 r21 协议原件且身份链闭合;22 项无 FAIL/BLOCKED。失败项:无。
