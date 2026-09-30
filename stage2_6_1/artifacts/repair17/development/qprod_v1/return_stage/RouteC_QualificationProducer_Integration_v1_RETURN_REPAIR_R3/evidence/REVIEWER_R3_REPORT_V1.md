# QProd RouteC_QualificationProducer_Integration_v1 — 第三次返修轮(R3)独立内容验收报告 v1

- Reviewer: 用户配置 OMP reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、实际工具、真实原件;未沿用 C11/R2 旧 PASS,按 R3 新语义全 22 项对账。
- 验收对象: 内容候选 **C12 = 29c465da**(单提交,已 push);证据提交 HEAD = **dd7874ce**;基线 = c848928f + C11(8f92a985,保持成立)。
- 触发: ChatGPT 第三次 NOT_CLOSED_ENGINEERING;addendum 原文(2)已归档 `.../repair_round3_notclosed/REVIEWER_ADDENDUM_R3_ORIGINAL.md`(27 行,Q1/Q2/Q3/R01 四段+原件局限段,已通读)。
- 验收日期: 2026-10-01。零新增原生/零 fit/零 optimizer;原生预算 2/2 硬门在位未动(`qprod_native_budget.json` max=2 consumed=2,本轮 git clean)。

## 0. 输入材料事实(如实)
- 本轮 Downloads/任务包未附新 QProd REVIEW.md、无 reference_task/(两份 REVIEW 为 9/29 R25 旧件,未误用)。验收以:用户目标逐字(交接件 §0)+ addendum (2) 原文 + 原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md` 为准。
- `local://reviewer_handoff_r3.md` 经 `local://` URI 首次读取失败,实际位于 `/f/trading/local/reviewer_handoff_r3.md`,已全文读取(修复映射四点+§0 逐字与 addendum 一致)。

## 1. 身份与字节同步核验
| 项 | 命令/方式 | 结果 |
|---|---|---|
| 本地 HEAD | `git rev-parse HEAD` | dd7874cef5d2cfdc23d9e2908e5759eb67d35c21 ✓ |
| 远端 push | `git ls-remote origin route-c-stage2-6-1-repair17` | dd7874ce... = 本地 HEAD ✓ |
| 单提交 | `git show 29c465da --stat` | 11 文件,+906/-54;仅 qprod/r17-cue/262-export 源+测试+证据,未触 R25/TB/旧面 ✓ |
| 部署树字节 | sha256sum 仓库 9 个改动文件 vs WSL `/home/cryptorl/projects/crypto_rl` 同名文件 | **9/9 逐字节一致**(5 源: aggregate/coordinate/levela/r17_cue_contract/ppo262_qprod_export;4 测试: coordinate/q123/r2/r3)✓ |
| E01 原件零改动 | 250 文件 git-tracked,`git status --porcelain` 空;最后提交 bd6ed858(前轮) | run1/run2 自 bd6ed858 起零改动,R2→R3 未触碰 ✓ |

C12 提交时间 2026-10-01 02:21:53+0800;回归 started_utc 2026-09-30T18:22:17Z(=02:22:17+0800,提交后 24 秒启动)、finished 19:04:45Z;时序自洽。

## 2. 主 Agent 验证记录复跑(部署树 C12 字节,定向必跑项)
```
cd /home/cryptorl/projects/crypto_rl && export PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=src
python -m pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_r3_fixes.py \
  test_curriculum261_qprod_r2_fixes.py test_curriculum261_qprod_q123_fixes.py \
  test_curriculum261_qprod_coordinate.py test_curriculum261_qprod_aggregate.py \
  test_curriculum261_qprod_levela.py -q
→ 89 passed in 8.25s
python -m pytest test_curriculum261_qprod_context.py permit.py plan.py \
  tests/route_c_stage2_6_2/test_ppo262_qprod_export.py -q → 51 passed in 3.78s
```
合计 **140/140 通过**;钉测试分账实测 R3=17、R2=17(含 1 例改写)、q123=21,合计 55/55 ✓(与全量 junit 对账见 §5)。

## 3. Reviewer 独立探针(正反例自建,零真实生成;原件留存)
脚本 `F:/trading/tmp_r3/probe_r3.py`,输出日志 `F:/trading/tmp_r3/probe_r3_output.log`(WSL 部署树执行)。**17/17 全过**:
- P1/P1b 真实工程排练(数值合法正例): `judge_qualification_gates` verdict=**PASS**,cue gate pass=True,`numbers_consistent_with_checks=True`,`checks_set_matches_authority=True` → **Q1 正例必须通过 ✓**
- P2 用外来键 `foreign_substitute_ok` 替换必需键 `mc_close_to_analytic`(剩余全 True+digest 重算自洽)→ verdict=FAIL,checks_set 不匹配拒 → **替换必需 check 拒 ✓**
- P3 追加多余键 `extra_padding_check` → FAIL 拒(键集合=权威 8 项精确一致) → **加键拒 ✓**
- P3b 数值全部合法但把 `mc_close_to_analytic` 改 False(digest 自洽)→ numbers_consistent=False 拒 → checks 布尔与公共数值矛盾双向拦截 ✓
- P4 配额 60:C2 上界 40 预占后异常,`episode_leaf_calls=40`、`uncertain_blocks=1`;第二次动作最坏 80>60 → **QProdQuotaExceeded 生成前拦截** → 异常不确定预占保留且后续累计不逃账 ✓
- P5a/P5b/P5c 早停边界(启动侧 `_early_stop_boundary`): 低 recall+se=0.02(audit_pass=False)→触发 c01;se=0(退化)→不触发;collect_all_k→恒不触发 → **启动侧与聚合消费侧同一定义(v4 classify_primary, delta=P0-recall>margin, se>0 才判负)✓**
- P6 qcap `block_range.start_index=1`(重算 digest+seal 同步)→ invalid,problems 含"start_index=1 != 0(范围矛盾)" → **范围贯通拒 ✓**
- P7 E01 只读复算(前后 sha256 全树快照零变异): run1 valid=1/primary=inconclusive/stats_gate_failed=[c01],c01 recall=0.9607843137254902 se=0.028292718593392892 nrv=true;run2 valid=2,[c01,c02],c02 recall=1.0 se=0.0 nrv=true —— **与 E01_RECOMPUTE_C12.json 逐字段一致,且复算本身零改写原件 ✓**

## 4. addendum 四段逐项判定
### Q1 公共业务数值+权威检查集合+17 步 — **PASS**
- 单一事实源: core `AUDIT_REQUIRED_CHECK_NAMES`(8 键)+`_synthetic_probe_check_names_and_values` 组装(与原内联 dict 同键同值同序,读 diff 确认纯结构抽取);读取侧 `qprod_required_cue_check_names()` 对拍 `_synthetic_probe_check_names()`,漂移即 QProdContextError。
- gate1 数值级重算(levela.judge_qualification_gates): MC `|p_hat-p_contract|<=tolerance`(报告 tolerance=AUDIT_MC_ABS_TOL=0.001,与 core 语义一致)、双语料 `|emp-ana|<=max(3*se,0.005)`(AUDIT_DIFF_SE_FACTOR=3.0 与 core 一致),重算值≠checks 布尔即拒 — 钉测试 MC 失败/语料失败两反例 + 我的 P1/P3b 正反双向探针均过。
- 删减/替换/加键: set 相等核验,钉测试删键例+P2 替换例+P3 加键例全拒。
- 17 步权威序列(262 export): 步名序列==`r17_workflow_step_names()`,重复同一步 17 次/换序/failed_at 残留均拒(即使全 ok)——钉测试 dup+swap 两反例过;正常 17 步导出(E02 step04 rc=0、te 测试)不受伤。
- R2 拒绝路径无退化: r2q1 raw tamper/result-iteration mismatch/ledger fail/研究计划前置缺失/session acquire + q123 raw-tamper-consistent-outer/journal/calibration-tamper 共 17+21 项全在且全过。

### Q2 异常不丢账+许可 vs 需求动作前拦截 — **PASS**
- `_GenerationLedger.episode_leaf_calls = _episode_actions + _inflight_upper`;attempts 异常(BaseException)路径 `uncertain_blocks+=1` 后上界**不退 0**,异常按真实类别传播;正常完成精确回填释放。totals 分列 settled/uncertain_upper/uncertain_blocks。
- 钉测试: 一般异常(≥40 保留)、24 动作结算后异常(64=24+40,分账断言)、KeyboardInterrupt(≥40 保留)全过;我的 P4 证明预存上界对**后续动作的配额硬拦截**。
- 许可为正但不足: `run_coordinate_audit_locked` 在任何生成动作前对账 `mc_events_per_coordinate>=qcap.mc_events(4096)`、`max_successful_episodes_total>=blocks*8*2(32)`、`max_native_executions>=1`,不足即 refusal(leaf_calls 快照=0,配额账本 refused 行)。钉测试 mc=1/正文=1 两反例过,拒绝消息明确"研究计划预算声明不代替许可上限"。
- 计数模拟零真实生成: 全部替身叶(我的探针亦然),原生预算文件零变化。

### Q3 有效统计负结果保留(R2 规则撤回)+范围贯通 — **PASS**
- `aggregate_research`: audit_pass=False(结构核验通过)→ `stats_gate="cue_contract_fail"`+`negative_result_valid=True`+note,**保留进 valid 主分析**;`audit_fail_excluded` 键全仓无残留(生产/消费双侧 grep 证实干净切换);新输出键 `stats_gate_failed_coordinate_ids` 无下游消费者(聚合报告为终件)。
- K 不足(<planned_k)→ inconclusive(insufficient_coordinates,描述性统计);SE 退化(se=0)→ inconclusive(degenerate_se_prevents_v4_application,不发明替代数学,坐标保留);完整合成 K=11 → 正常主分析(钉测试断言非 inconclusive/非 halted_technically_corrupt)。四类钉测试全过。
- 早停事前定义且启动/消费一致: stop_mode 冻结于研究计划;两侧同一 v4 classify_primary(delta=p0-recall, se>0, beyond_positive_margin);我的 P5 三探针+钉测试(audit_fail 坐标参与触发)+q123 早停排除 post_stop/启动守卫两钉均过。
- 范围贯通: qcap `block_range.start_index==0`+`count==报告 blocks`+双语料事件 block 集合==`range(计划 blocks_per_corpus)`;钉测试 count 篡改拒+我的 P6 start_index 篡改拒;旧 E01 合法兼容走计划 digest 白名单(legacy 事件摘要绑定缺位容忍),**不豁免范围检查**——E01 四个 qcap 均含 block_range(count=2==报告 2),我的 P7 证实 E01 在新范围检查下仍 valid。
- 不重抽样/不改 seed/不放宽 margin/不删统计失败坐标: diff 无重抽样路径;margin/rules 来自冻结计划;E01 原件哈希零变异;统计失败坐标(run1 c01、run2 c01+c02)数值保留。

### R01/PK01 完整回归原件+E01 实执行 — **PASS(打包后 ZIP 冷读为下一步骤,不在本轮内容范围)**
- 261 v10: argv=`python -m pytest tests/route_c_stage2_6_1`、cwd=部署树、interpreter Python 3.11.16、rc=0、stdout 尾行 `2662 passed, 7 skipped ... in 2523.26s`、stderr 空;junit 解析 tests=2669/failures=0/errors=0/skipped=7/time=2522.9 与 stdout 一致;7 个 skip 全部为 R12–R16 历史 governance 分支上下文旧例,**无新增 skip/xfail、无缩集合**(v9=2652/8skip → v10=2652+17 新增=2669,skip 8→7=E01 实执行)。COLLECTION auditor/lifecycle 在位。
- 262 v7: 240 passed rc=0(145.95s),junit 一致,零 skip。
- SOURCE_MAP: 7 文件 repo blob↔deploy sha 全 MATCH、0 MISMATCH;我另行独立对账全部 9 个改动文件逐字节一致(补齐 map 未列的 q123/coordinate 两个测试文件,见 §6 观察)。
- E02 七步原件(`evidence/e02/`,R01 要素): 7 步 meta 全 rc=0,argv/cwd/interpreter 齐;step06 formal-scope 拒绝输出"工程许可不能解锁正式入口";COLLECTION 明确标注 **"E02 is engineering-path chain; 261 regression originals are in regress/"** —— 七步不冒充 261 回归 ✓。新候选适用: E02 于 C12 字节部署树执行(18:22:48Z),step04 走新 17 步序列校验导出 rc=0。
- E01 skip 撤回: v9 测试含 `pytest.skip("E01 originals not present in this tree")`,R3 改为双候选真实归档路径断言(仓库树+/mnt/f,均缺才如实 FAIL,不静默跳过),实测在归档原件上执行 `_verify_coordinate`(valid+audit_fail=True+legacy 标记)。未删用例、未重生成。

## 5. 22 项矩阵对账
| ID | 判定 | 本轮证据(变化面复验/未变化面身份复用) |
|---|---|---|
| B01 | PASS | 单提交仅 qprod 面;R25/TB 零触碰;原生 2/2 分账未动;worktree 证据区 clean |
| A01 | PASS(复用+复跑) | context/plan 面未改;140 定向+E02 步 01-04 rc=0(C12 字节) |
| A02 | PASS(复用+复跑) | E02 step06 formal 拒绝 rc=0;q123/r2 隔离钉通过 |
| A03 | PASS(复用) | 冻结/两阶段面未改;r2q2 plan budgets 钉通过 |
| A04 | PASS(R3 变化面) | Q2 异常预占新语义钉+P4;interrupted marker/q123 nonpositive-quota 钉过 |
| C01 | PASS | 坐标锁核验未改;许可额度动作前新 gate 钉过;E01 原件未动 |
| C02 | PASS(R3 变化面) | checks 组装重构为同键同值抽取(读 diff);黄金面常量路径未改;v10 全量含黄金面测试 RC=0;P1 数值一致 |
| C03 | PASS | anchor 块未改;full-K 正例 11 坐标局部 p_contract 各异无一删除 |
| K01 | PASS | full-K 合成主分析+E01 K=1/2 如实 inconclusive;duplicate-seed/事件重复钉过 |
| K02 | PASS(R3 变化面) | 新语义下 early-stop 触发钉+collect_all 反例+P5 边界三态+post_stop 排除/启动守卫钉 |
| X01 | PASS(R3 变化面) | 262 export 17 步权威序列校验新增;te 套件过;E02 step04 rc=0 |
| X02 | PASS | dup-17/换序/删键/替键/加键/数值矛盾全拒(钉+P2/P3/P3b) |
| X03 | PASS(复用) | pack/fit 来源面未改;51-face(含 te)全过 |
| X04 | PASS(复用) | 消费授权面未改;E02 step05/06/07 rc=0 |
| E01 | PASS | 原件零改动(§1);只读复算独立重现(P7);预算 2/2 未动 |
| E02 | PASS | 7 步 rc=0 原件+非回归标注+formal 拒绝;高成本替身位置 levela 测试明示 |
| E03 | PASS(复用) | E02 step07 冷读 rc=0;q123 导出篡改钉过 |
| R01 | PASS | §4 完整原件核验;无新增 skip;计数实际;新候选绑定 SOURCE_MAP+我的 9/9 字节对账 |
| P01 | PASS | 本轮 reviewer 侧重型作业=0(仅定向 8s+3.8s 测试与 15s 探针);主 Agent 单重型作业=261 v10;零新增原生/fit/optimizer |
| D01 | 内容范围外(打包步骤) | 最终增量 ZIP 出包后按流程执行冷读+回执;本轮内容 PASS 为其前置 |
| RV01 | PASS | 即本报告;独立正反例原件: tmp_r3/probe_r3.py + probe_r3_output.log |
| PK01 | 内容范围外(打包步骤) | 同 D01;当前全部证据原件已入库 dd7874ce 并 push |

## 6. 非阻塞观察(P3,不拦截本轮)
1. **EVIDENCE_INDEX 钉测试分账笔误**: 写"R3 18 新增+R2 16",实测 R3=17、R2=17(总数 55 正确;v10=2652+17=2669 与 junit 吻合)。仅文档拆分数字,建议打包轮更正。
2. **SOURCE_MAP 覆盖 7/9**: 未列 test_curriculum261_qprod_q123_fixes.py 与 test_curriculum261_qprod_coordinate.py;我已独立逐字节对账 9/9 一致,无实际影响,建议打包轮补全。
3. **陈旧注释**: `_verify_coordinate` 返回处注释仍写"聚合消费侧据此排除"(R2 语义),与消费点新注释(保留进主分析)矛盾;纯注释,无行为影响。
4. 合成夹具 full-K 用例的 se 为浮点噪声正值(~1.1e-16),v4 据此产出估计——既有夹具特性(非本轮引入);真实 E01 的 se 语义(0.0283/0.0)不受影响。

## 7. 局限(如实)
- 平台未提供本轮 ChatGPT 终验元数据,NOT_CLOSED 触发以交接件 §0 逐字与 addendum 归档件为准。
- 261 v10/262 v7 全量未重跑(预算纪律): 以原件(META/argv/junit/stdout/时间线)+SOURCE_MAP+我的 9/9 部署树字节对账+140 项定向复跑作身份/内容抽查;此限制与交接件允许的抽查口径一致。
- 未代签 ChatGPT CLOSED;最终 CLOSED 由 ChatGPT 独立终验。

## 8. 结论
**内容验收 PASS**(Q1/Q2/Q3/R01 四段全部通过,22 项矩阵无 FAIL/BLOCKED 内容项;D01/PK01 最终 ZIP 冷读属打包后步骤)。失败项列表: 无。
