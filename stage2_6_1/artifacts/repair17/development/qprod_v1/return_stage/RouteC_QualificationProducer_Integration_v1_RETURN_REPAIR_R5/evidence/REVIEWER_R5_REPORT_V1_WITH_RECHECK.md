# QProd R5(C15=1139887e)独立内容验收报告 — OMP reviewer v1

- reviewer: 用户已配置 OMP reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、实际工具、真实原件;不沿用 C14 旧 PASS。
- 审阅对象: R5 修复提交 **C15=1139887e5eed84118b639ac28086a0fefa5a56a8**;证据提交 **6b55a84754c04bb0c927f13784ebe0f996961dca**(分支 route-c-stage2-6-1-repair17,与 origin 同步已 push)。
- 判定: **FAIL(仅 1 项证据打包缺陷;Q1 内容面判据全部独立通过)**
- 日期: 2026-10-01;零新增原生/零生成/零 MC 研究/零 fit/零 optimizer;重型作业全部复用主 Agent 已跑原件(我做身份/字节/内容抽查),定向探针自行新跑。

## 0. 必读原文核对
1. `F:/trading/local/reviewer_handoff_r5.md` ✓(§0 目标逐字在案)
2. `repair_round5_notclosed/REVIEWER_ADDENDUM_R5_ORIGINAL.md` ✓ 32 行,与 Downloads "(4)" 归档一致(逐字要点:已接受范围/最低 5 用例/持久判定边界对象/零新增/验收交付)
3. 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md` ✓(B01,A01-A04,C01-C03,K01-K02,X01-X04,E01-E03,R01,P01,D01,RV01,PK01=22 项)
4. C14→C15 代码差 = `git diff --stat 3d2193e2..1139887e` 恰好 2 文件(curriculum261_r17_cue_contract.py +125/-6、test_curriculum261_qprod_r5_fixes.py +192)——其余全部模块两提交字节相同(本报告 C14 快照复现依赖此事实)。

## 1. 独立验证矩阵(全部为本人实际执行)
| # | 核验点 | 命令/方法 | rc | 结果 |
|---|---|---|---|---|
| V1 | 部署树与 C15 字节一致 | sha256 对拍 repo vs ~/projects/crypto_rl(cue_contract/levela/r5 测试 3 文件) | 0 | 3/3 match=YES(40ef4e16…/544bfa62…/54ef4c26…) |
| V2 | 修后探针(C15 字节) | REPRO_Q123_ROUND5_PRE_FIX.py,cwd=部署树 | 0 | **3/3 verdict=FAIL**:case1 ova_recomputed=False;case2 ti_recomputed=False(真实子条件);case3 delegated **不含 model.replay_ok**(委托被否决),validation.replay_ok 仍在(无坏数值不误伤) |
| V3 | 修前三洞独立复现(C14 字节) | git archive 3d2193e2 → tmp_r5/reviewer/c14_snap,补齐部署树独有环境件(67 个 rl_curriculum 缺失模块+rl_platform 等 5 包+artifacts 夹具计划+user_data+experiments+vendor;均属 C14↔C15 零差异面或共享环境) | 0 | **3/3 verdict=PASS(洞坐实)**:case1/2 sem_consistent=True;case3 delegated **含 model.replay_ok**;快照内 cue_contract 无 `_REPLAY_TOL_REF`(0 处)、含 C14 旧 ti 行(1 处)——确证跑的是 C14 判据 |
| V4 | 非特判对抗变体(本人设计,9 项) | probe_r5_adv.py,插入式/镜像式变异+重算 digest | 0 | **9/9 OK**(详表见 §2) |
| V5 | 钉测+历史面定向 | pytest r5/r4/q123/r3 修复面 + r9_cue_contract+r9_noise_replay+r10_cue_contract | 0 | **75 passed**(25.61s),含合法对照 r5q1a、正式无 fixture 拒绝 r5q1f |
| V6 | E01 原件与复算 | git status(原件 clean);E01_RECOMPUTE_C15 vs C14 逐值对比 | - | 原生 2/2 耗尽(qprod_native_budget.json);run1 c01 recall=0.9607843137254902/se=0.028292718593392892、run2 双坐标、primary=inconclusive **逐值一致**;仅 C15 件缺 `stats_gate_failed` 汇总字段(§5-R3) |
| V7 | E02 七步 | 7 个 meta.txt rc + stdout 内容 | 7×0 | authority→permit→rehearse(verdict=PASS,ledger 17 步)→export→consumption_auth→**formal_reject(工程 scope≠formal 拒)**→cold_read ok;时间戳 2026-09-30T22:25:40Z=C15 提交(22:23:02Z)之后 ✓ |
| V8 | 262 v9 | meta(candidate=1139887e,py3.11.16)+junit+stdout | 0 | **240 passed/0F/0E/0S**,153.56s |
| V9 | r21 v6 C15 全量 | summary/record/junit/CANDIDATE/r21_run.stdout 本地原件交叉 | 0 | run_id r21_20261001_070428,record_sha256=4dd5df96…(重算一致),commit_a_sha=**1139887e** ✓,counts 2685/0F/0E/7skip,junit 同,verify 2685/2199/159;**但未入库**(见 F1) |

## 2. V4 对抗变体明细(证明"非三个编号特判")
| 变体 | 变异 | 预期 | 实测 |
|---|---|---|---|
| v0 合法对照 | 无变异 | PASS+delegation 如实列示 | PASS,fixture_mode=True,delegated 10 项全列(含 model.replay_ok/bounds/cue_table、ova、ti、gk、aggregate) |
| v1 ova 容差漂移 | 插入自洽 ova 后 tolerance=0.9 | FAIL(阈值漂移) | FAIL,tol_drift=True |
| v2 ti 计数矛盾 | violations=["mirror:pos3"] 但 n_violations=0,ok=True | FAIL(真实子条件) | FAIL,ti_rec=False |
| v3 坏影子+真声明 | validation.max_replay_abs_error=0.4 且 replay_ok=True(仅 validation) | FAIL 且 model 不受累 | FAIL,model_ok=True/validation_ok=False(逐语料通用) |
| v4 gk 矛盾 | pass=True+verdict=INDETERMINATE | FAIL | FAIL,not_indet=False |
| v5 MC 漂移+改容限 | p_hat+0.05、tolerance=1.0 | FAIL(冻结容限+漂移记录) | FAIL,mc_rec=False,drift_mc=True |
| v6 剥 fixture 标记 | 合法 rehearsal 报告删 engineering_fixture 后重签 digest | FAIL(缺支撑字段不委托) | FAIL,fixture_mode=False,delegated=[] |
| v7 正式缺块(直调 helper) | 无 fixture 报告缺 once_vs_attempts 整块 | once_vs_attempts_consistent=False | OK,False,delegated=[] |
| v8 ova 来源不一致 | recall_validation 与 dg 差 0.01(差值自身仍在容差内) | FAIL(来源不一致腿) | FAIL,src_drift=True |

## 3. 八门逐门对账(生产规则 vs 复核规则,输入/冻结公式/归属)
权威键集 AUDIT_REQUIRED_CHECK_NAMES(mc_close_to_analytic, model_corpus_ok, validation_corpus_ok, once_vs_attempts_consistent, aggregate_recompute_ok, tail_mirror_bound_integrity_pass, global_k_audit_pass, global_k_audit_not_indeterminate);读取侧 qprod_required_cue_check_names() 经 _synthetic_probe_check_names() 对拍 core 生成键集(单一事实源,漂移即抛错)。
1. **mc_close_to_analytic**:重算 |p_hat−p_contract|≤AUDIT_MC_ABS_TOL(0.001 冻结,不读报告自带 tolerance),tolerance 漂移记录 discrepancy——与生产同常量。v5 证实。
2. **model/validation_corpus_ok**:重算 replay∧bounds∧cue_table∧p_contract∈CI95∧|emp−ana|≤max(3SE,0.005)∧tail 同式;diff_tolerance 漂移检查;R5 新增 replay 数值影子(max_replay_abs_error>1e-12 一律拒,与字段在否、与委托无关)。与生产 _run_cue_contract_audit_core 同公式。v3 证实逐语料通用。
3. **once_vs_attempts_consistent**:R5 从 direct_generator 在场数值重算——源一致(ova recall 字段=dg empirical_recall)、|rec_m−rec_v|≤max(3·sqrt(se_m²+se_v²),0.005)(与生产 832 行公式及 plan payload 预注册 "recall_tolerance_rule" 逐字同)、tolerance 漂移、k 判据、声明矛盾记录。v1/v8 证实两腿独立生效。
4. **tail_mirror_bound_integrity_pass**:R5 重算=子输入合取(exact_noise_replay_ok≠False ∧ bounds_ok_all_positions≠False ∧ violations 空 ∧ n_violations==0)∧各子项声明 ok;矛盾记 disc。V2-case2/v2 证实由真实子条件拒绝。
5/6. **global_k_audit_pass/not_indeterminate**:生产=global_k 审计结论;重算读 gk.pass 与 verdict≠INDETERMINATE——归属一致。v4 证实。
7. **aggregate_recompute_ok**:生产=聚合复算(事件表核对,不在报告内);重算=该声明值;两侧同源同归属,fixture 缺席时如实列入 delegated。v0 证实。
8. **同根子门 bounds/cue_table**:fixture 缺席→delegated 如实列名;正式缺→False。v0/v6/v7 证实。
- **非特判检查**:diff 中无任何案例号/魔数特判;三条修复均为通用公式;伪造报告须自行重签 digest 后仍被数值/子条件判据拒绝(V2/V4)。
- **validator=True 检查**:无此类概念;判定全部由冻结纯判据重算得出。

## 4. 22 项矩阵对账
| 项 | 判定 | 依据 |
|---|---|---|
| B01 | PASS | HEAD=6b55a847/C15=1139887e/C14=3d2193e2 接续;推送面 C14 r21 原件 clean(工作树污染见 F1);R25/TB 未重开 |
| A01 | PASS(复用+新证) | levela 未改;E02 rehearse ledger 17 步新证 |
| A02/A03/A04 | PASS(复用) | faces 无 R5 变更(2 文件差);r21 v6 2685/0F 绑 commit_a_sha=1139887e |
| C01 | PASS(复用+新证) | E02 rehearse 双坐标新跑 |
| C02 | PASS | 共享 core 黄金向量未动(diff 无);重算与生产同公式(§3) |
| C03 | PASS(复用) | 未触及 |
| K01/K02 | PASS(复用) | 未触及;E01 负结果保留(V6) |
| X01 | PASS | E02 04_export+07_cold_read 新证(C15 字节) |
| X02 | PASS | E02 06_formal_reject 拒绝;V2/V4 全部伪造 PASS 被拒 |
| X03/X04 | PASS(复用) | 未触及;262 v9 新证 |
| E01 | PASS | 原件 clean、预算 2/2、复算逐值一致 |
| E02 | PASS | 七步 rc=0;fixture 标注如实(v0);剥标记即拒(v6)——21 行边界成立 |
| E03 | PASS | cold read ok;错 scope/身份拒(06);篡改类全拒(V2/V4) |
| R01 | **FAIL(打包)** | r21 v6 C15 内容/身份核实通过,但全套原件未入库且不在 EVIDENCE_INDEX 声称路径(F1);262 v9 ✓ |
| P01 | PASS | 单重型作业口径;原生预算未清零 |
| D01/PK01 | 待办(非本轮否决) | 最终 RETURN 包未建(R3/R4 后无 R5 zip,符合 NOT_CLOSED 阶段);PK01 须在 F1 修复后从包字节冷读 |
| RV01 | 本报告 | 独立上下文/实际正反例/失败→修→复验链齐 |
| 判定规则 | — | 必需项存在 FAIL→不得全项 PASS |

## 5. 发现
### F1(P1,阻断):C15 r21 v6 全量回归证据未入库、路径错位、R4 共享证据文件被覆盖
- 事实:6b55a847 未包含 r21 v6 C15 任何文件;`repair_round5_notclosed/evidence/` 下无 regress_v6/(提交与工作树均无);全套原件实际在 `repair_round4_notclosed/evidence/regress_v6/full_regression_v6_c15/` 且 **untracked**(?? ,check-ignore=1 非忽略);EVIDENCE_INDEX.md:21 声称 `evidence/regress_v6/full_regression_v6_c15/(r21 既有协议全套)`——推送树中该路径不存在。
- 原因:`stage2_6_1/runner/qprod_r5_r21_regress.sh:10` 将 EVD 指到 **repair_round4_notclosed** 的 regress_v6,运行覆盖了 R4 已提交的 `CANDIDATE.txt`(HEAD=3d2193e2 内容)与 `r21_run.stdout.txt`(HEAD=r21_20261001_050302/C14 record c497f7ce),git status=2 M;推送 HEAD 中 C14 内容尚完好,但工作树已失真,按提交打包则 R4 面被改签、R5 面缺失。
- 影响:若按当前推送字节出 RETURN 包,R01/PK01 冷读必失败(EVIDENCE_INDEX 引用不存在路径);C14"原记录保留不改签"在推送面成立、在工作树面被破坏。
- 修复建议(1. 改 EVD 指向 repair_round5_notclosed/evidence/regress_v6;2. git restore R4 两个被覆盖文件;3. 将 full_regression_v6_c15/ 移至 round5 声称路径后 git add 连同 CANDIDATE.txt/r21_run.stdout.txt 一并提交并 push):
```bash
EVD=$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round5_notclosed/evidence/regress_v6
```
### F2(P3):runner 标签与头注沿用 R4 字样
- `--label r21_full_collection_regression_qprod_r5_c14`(行 20)与头注 "(C15=3d2193e2+)"(行 2)均为 C14 留存字样;record notes 因此带 c14 标签(commit_a_sha=1139887e 绑定未受影响)。
```bash
  --label r21_full_collection_regression_qprod_r5_c15 \
```
### F3(P3):E01_RECOMPUTE_C15.json 缺 `stats_gate_failed` 汇总字段
- C14 件含 `runs.native_smoke_run{1,2}.stats_gate_failed=['c01']/['c01','c02']`,C15 件无此键;数值面逐值一致、负结果仍由 audit_fail/primary=inconclusive 记载,属证据文档字段回退。
```json
  "stats_gate_failed": ["c01"],
```
(run1)/`"stats_gate_failed": ["c01", "c02"],`(run2),置于各 run 的 coords 同级。

## 6. 残余观察(非阻断、非本补丁引入,仅记录)
- R1: ti per_corpus 子字段(exact_noise_replay_ok 等)**缺失**(非为 False)而 ok=True 时,正式模式亦不拒——R4 语义原样保留;生产端恒写全字段,建议下轮考虑"正式报告子字段必须在场"。
- R2: ova.k_tolerance 无法从在场数据交叉复核(k pooled se 不落盘),recall tolerance 可而 k 不可——R4 语义原样。
- R3: "r8/r9/r10/r17 历史面 29/29"无测试清单可精确复现;本人以 75 测定向集(r9/r10 cue 面+r3/r4/q123/r5 修复面)覆盖,全量由 r21 v6 2685/0F 兜底。
- R4: ova tolerance 漂移分支存在内外重复条件(无害冗余)。

## 7. 结论
- Q1 三洞修复真实、通用、非特判;修前 3/3 洞与修后 3/3 拒均经本人独立复现;合法输入不误伤;替身位置如实列示;无 fixture 直调正确拒绝;零新增原生/MC/fit/optimizer;停止政策与统计门槛未动。
- **唯一阻断项为 F1 证据打包缺陷**:修复(移动+入库+restore+push)后,本评审对其余面的判定无需重跑,仅需对新增证据提交做身份/路径复核即可转 PASS。
- reviewer 模型 zhipu-coding-plan/glm-5.3-flash;平台未返回本会话之外的后端元数据,如实说明。最终 CLOSED 由 ChatGPT 独立终验,本报告不代签。

## 8. reviewer 附件(F:/trading/tmp_r5/reviewer/)
- probe_r5_reviewer.sh / probe_r5_adv.py(脚本)
- probe_r5_adv.stdout.txt(9 变体输出)/ c14_repro.stdout.txt(C14 三洞输出)
- c14_snap/(C14 快照+补齐环境件;3d2193e2 git archive 所出,补齐件均属零差异面)
- step0/1/3 输出见 bg_39 会话记录(V1/V2/V5 同款重跑)

## 9. 复验(V1 修复轮,同日)— 最终判定翻转为 PASS
Main 修复提交 **d32d519a + 40ea2302**(已 push,分支与 origin 同步;`git diff 1139887e..HEAD -- src/tests` 为空,候选内容不变)。
| 项 | 复验方法 | 结果 |
|---|---|---|
| F1 归位 | `git ls-tree HEAD -- repair_round5_notclosed/evidence/regress_v6/`(15 文件=13 c15 全套+CANDIDATE+r21_run.stdout/stderr);record 重算 sha256=**4dd5df96…**(与我先前对错置原件所验字节一致);commit_a_sha=1139887e;counts 2685/0F/7skip;junit 同;summary 一致;重建 CANDIDATE.txt/r21_run.stdout.txt 与我留存的实际运行输出逐字节相符;round4 侧 `git status` clean(字节复位 HEAD,c15 目录移出);`git diff 6b55a847..HEAD -- repair_round4_notclosed/` 为空 | ✓ |
| F2 字样 | runner 头注 R5/C15=1139887e、EVD→round5、label→…_r5_c15 | ✓(既有 record 保留原 c14 标签属原件不改写,身份由 commit_a_sha 绑定,接受) |
| F3 字段 | E01 C15 vs C14 逐值对比:仅 format 键+新增 notes 差异;stats_gate_failed=['c01']/['c01','c02'] 与 R4 同值,数值零改动 | ✓ |
- EVIDENCE_INDEX.md 未改而其第 21 行路径声明由归位变为真实。
- **最终判定:PASS(C15=1139887e,证据 HEAD=40ea2302)**;本报告 §5 三项发现全部关闭。后续 R5 增量包冷读+包外回执按交接流程另行执行。
