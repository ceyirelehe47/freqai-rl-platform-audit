# QProd R2 返修轮独立内容验收报告(reviewer v1)

- reviewer: OMP 配置 zhipu-coding-plan/glm-5.3-flash(独立上下文,未参与实现;平台未返回更多后端元数据,如实说明)
- 被审候选: **C10 = a2d546f3**(单代码提交,分支 route-c-stage2-6-1-repair17),证据 HEAD = **36d66c28**(已确认 a2d546f3 为其父,7 个关键文件两提交字节一致)
- 输入原文: local/reviewer_handoff_r2.md §0(用户目标逐字)、REVIEWER_ADDENDUM_R2_ORIGINAL.md(35 行)、ACCEPTANCE_MATRIX.md(22 项)
- 复验方式: 全部为本人独立执行(部署树 ~/projects/crypto_rl,python=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python,PYTHONDONTWRITEBYTECODE=1);零新增原生/零 fit/零 optimizer(原生 2/2 未动,预算文件读侧核验)
- 独立原件目录: **F:/trading/reviewer_q123_r2/**(清单见 §8)

## 0. 总判定

**FAIL(内容两项;其余全部核验通过)**

| # | 级别 | 项 | 一句话 |
|---|---|---|---|
| F1 | P1 | Q2 原生预算硬门 runner 集成 fail-open | gate 拒绝/崩溃后脚本继续执行,退出码 97 被丢弃;现仅靠 run2 目录存在这一**偶然守卫**阻止第三次原生 |
| F2 | P2 | 复现探针 case8 与已提交 fixture 失配,归档 C10 复现件该例不可复现 | 已提交 repro_round2.py 在已提交 C10 字节上跑出 **1/14 reproduced**(归档件声称 0/14) |

两项均为本补丁引入/本轮证据件,修复后无需第三次原生即可复验(F1 用缺失预算文件+副本脚本验证;F2 为证据件更正)。**Q1/Q3 全部深层修复行为真实成立,16 项钉测试、E01 复算、E02 全链、261/262 回归身份抽查均通过。**

## 1. 字节与部署身份(前置)

- `git show a2d546f3` 与 `36d66c28` 对 7 个关键文件(5 src+runner+钉测试)sha256 两两一致。
- 6afa31ac(C9 代码)→0d67a143(C9 证据)→a2d546f3(C10 代码)→36d66c28(C10 证据);R2 代码改动范围=10 文件(src×4+262 export+runner+tests×4),985 insertions/58 deletions,无越面改动(README/旧面未触碰)。
- WSL 部署树 11 文件(含 context.py)sha256 与 a2d546f3 git blob **逐一相等**(coordinate cdac1668…/aggregate 1b21e73d…/levela c37d58e6…/plan 7dc8797d…/context 07249297…/ppo262 export 86da9e2a…/runner 27010004…/4 个测试文件),**当前部署树=C10 字节**。
- qprod_native_budget.json: max_runs=2, consumed_runs=2 在位;E01 原件(native_smoke_run{1,2})工作树 clean(自 bd6ed858 后零改动)。

## 2. Q1 判定 — PASS(7/7 反例拒,正例通过)

| 反例 | 拒绝机制(代码位) | 我的独立证据 |
|---|---|---|
| cue 内部 checks/MC 失败但顶层 PASS(digest 重算自洽) | levela.judge_qualification_gates: pass 必须==all(checks) 且 checks 全 True;fixture 同构 checks 明细 | 钉测试 r2q1_cue_checks_fail_top_pass PASSED(我跑);repro reproduced=False |
| topology producer 空集/缺失 | run_level_a_rehearsal: 空集拒+与权威全集精确对账 | 钉测试 r2q1_topology_empty PASSED |
| raw 篡改+result SHA 同步更新(自洽伪造) | ppo262_qprod_export: raw_verdict/raw_gates/raw_plan_bind/raw_iteration 内容级对账;SHA 自洽不豁免 | 钉测试 r2q1_raw_tamper PASSED;我复核导出器 L475 `problems or not all(checks)` → raise _reject(),新检查全部阻断 |
| result.iteration_id/source_iteration 错 | result_iteration_consistent + source_iteration 前缀对账 | 钉测试 r2q1_result_iteration PASSED |
| 链步账本 FAIL | level_a_step_ledger 须存在+verdict=PASS+17 步全 ok | 钉测试 r2q1_ledger_fail PASSED |
| 数据前研究计划缺失/绑定断裂 | research_plan_prerequisite_present(digest==prior_plan_digest) | 钉测试 r2q1_research_plan_missing PASSED |
| journal 恰一条 session_acquired | producer_session_acquired_once(==1 且绑定本迭代) | 钉测试 PASSED + 我的补充探针:**双条事件 → QProdExportError("事件数=2;须恰 1 条")**(F:/trading/reviewer_q123_r2 会话记录) |

合法正例: E02 全链 rehearse(17 步 PASS,qapl-6d33b648… 与归档链逐字一致)→export rc=0→冷读 ok。digest 公共函数重算自洽不再是充分条件——以内容对账拒绝,符合 addendum"不只调用公共 hash 函数"。

## 3. Q2 判定 — **部分 FAIL(F1)**;其余通过

通过部分:
- **attempts 逐动作计数**: ledger._episode_actions 按真实动作累计;attempts block 事后按 attempts_made×8 回填(made=max(len,1) 下界保守)。钉测试 48≠16 PASSED;q123_fixes 更新后 64=16+32+16 PASSED。wrapper×8 仅存 legacy 字段。
- **最坏上界预占**: attempts block 启动前 reserve(C2_BLOCK_MAX_ATTEMPTS×8),finally 释放;额度不足→QProdQuotaExceeded 在任何嵌套动作前。钉测试 quota=9 场景 calls==0、episode_leaf_calls==0 PASSED。
- **计划声明 audit_budgets+lock 三方对账**: plan 结构校验缺声明拒/MC=1≠4096 拒(我的直接探针);lock 层我的双向探针: 条目 MC=1 vs 声明 4096 →拒(profile 合同检查),声明 MC=1 vs 条目默认 4096 →拒(R2 新检查,动作前对账文案),声明 episodes_per_block=4 ≠8 →拒;合法一致声明通过预算检查(后被更深 namespace 守卫正常拦截,非预算拒)。正例 lock→run 全流程由 test_curriculum261_qprod_coordinate(绿色)覆盖。
- **有效 0/耗尽/失败/中断反例**: q123_fixes 套件保留且全绿(122+1 全 qprod 面我跑)。
- **MC/episode 余额不是新原生授权**: check_native_budget 拒绝文案明示;函数级 fail-closed(缺失文件/不可解析/字段非法/耗尽四路拒绝,钉测试 PASSED)。

**FAIL 部分(F1,P1)**: 原生预算"硬门"在**唯一集成点**(qprod_e01_native_smoke.sh L20-31 PYGATE 块)不停止脚本:
- 实测(BEFORE,提交版字节): `QPROD_NATIVE_BUDGET=/tmp/absent.json bash qprod_e01_native_smoke.sh` → 打印 `[native-budget] REFUSED: 原生预算文件缺失…` 后**继续执行**,被后续 `if [ -e "$ART" ]` 偶然守卫拦截,rc=**96**(非 97)。预算耗尽(2/2)场景 gate 打印 REFUSED 后同样继续。gate python 因 cwd 无 src 而 ModuleNotFoundError 崩溃(rc=1)时脚本也继续。
- 失效场景: 任何 run2 产物目录不存在/被迁移的树上(打包清理后、新克隆),脚本将无视 REFUSED **直接进入第三次原生生成**。脚本 `set -uo pipefail` 无 `-e`,heredoc 后无退出检查。check_native_budget 在 src 无任何其它调用点(grep 证实)——runner 是唯一执行侧防线。
- 最小修复(我在 /tmp 副本验证 AFTER): heredoc 结束后插入 `GATE_RC=$?` + 非零即 `exit "$GATE_RC"`;实测缺失文件 rc=**97** 停止、2/2 耗尽 rc=**97** 停止,文案完整。修复后 cwd 错误也转为 fail-closed(gate 崩溃→停止)。
- 提交信息与 EVIDENCE_INDEX 声称"e01 runner 启动前强制/硬门"——与实测行为不符,属非故意集成缺口。钉测试只测函数,未测 runner 集成,故 16/16 绿仍有此洞。

## 4. Q3 判定 — PASS(6/6)

| 项 | 证据(我独立执行) |
|---|---|
| qcap×报告×计划三方预算对账(qcap 500/报告 2 拒) | 钉测试 r2q3_qcap_budget_mismatch PASSED(reseal 自洽伪造后仍拒);reader L205-239 实现核对 |
| once(model) seeds 多重集精确对账(重复替代拒) | 钉测试 r2q3_duplicate_model_seed PASSED;旧代码 set 包含检查已改 sorted 多重集对拍 |
| model 语料事件结构+recall 复算对账(删事件+重算摘要自洽拒) | 钉测试 r2q3_model_events_deleted PASSED(测试内 reseal+pbd 重算后仍拒) |
| legacy 容忍限定 E01 digest 白名单 | 白名单 digest=qbpl-6cf9c2008209f7ff28aaab1295f6d29f90d1a8bcf6f10cb6fa1215cb8b770b04;我用 research_plan_digest() 对两 run 原件实算**均等于该值**;新对象缺 per_block_event_digests 拒(钉测试 PASSED) |
| audit_fail 排除主分析/早停/有利标记 | 钉测试 r2q3_audit_fail_excluded PASSED;reader valid 过滤+早停 `not entry.get("audit_fail")`+audit_fail_excluded 标记(跨边界消费点已核对,缺省 .get=False 安全) |
| E01 原件新 reader 如实(非破坏) | **我的独立复算**(aggregate_research 直读原件): run1 c01 valid+legacy+audit_fail+excluded、c02 missing;run2 c01/c02 均 valid+legacy+audit_fail+excluded;两 run valid=0/primary=inconclusive(原因=no_valid_coordinates);原件 cue_contract_audit.json 实测 pass=False 且 checks 明细如实(model_corpus_ok/validation_corpus_ok=False,工程小样本真实负结果)。与 E01_RECOMPUTE_C10.json 逐项一致 |

## 5. 证据件核验

- **REPRO 14/14→0/14**: C9 件与 C10 件齐;**C10 件我独立重跑=1/14**(仅 case8,见 F2),其余 13 例 reproduced=False 与归档一致。
- **钉测试**: 我跑部署树 16 passed+1 skipped(E01 原件用例,部署树无 artifacts 目录,环境性 skip);**仓库树 17/17 全 PASSED**(PYTHONPATH=部署 src+stage2_6_2/tests;E01 白名单用例对真实原件通过)。v8→v9 junit 对比: 2635→2652(+17 恰为新钉测试),skip 7→8,唯一新增 skip 即该 E01 用例(部署树环境性),无移除 skip、无缩集合。
- **261 v9 junit**: 2652 tests/0 fail/0 error/8 skip/2854.1s,timestamp 2026-10-01T00:12:13+08:00,host=Forst——提交时刻 00:11:56 之后 17 秒启动,自洽;期间 00:33-00:34 development/run_supervision/runs/ 出现 supervisor fixture 副产物(echo ok/sleep 等,argv 可见),与"套件内副产物不提交"惯例一致,支持运行真实性。
- **262 v6 junit**: 240/0/0/0 skip/147.0s,00:58:18+08:00(与 261 尾段并行,不同测试根,合理)。
- 局限(如实,不重建伪原件): 两份 junit 仅 XML 本身,无 argv/cwd/interpreter/rc 侧车原件;addendum R01 要素对**全量回归**而言只能以 junit+时间线+副产物交叉印证,不能完整满足。已按"缺件标明"原则在此声明。定向/钉测试/E02 的 R01 要素由我的独立执行补足。

## 6. E02 独立冷读(我自己的链)

- 位置: **F:/trading/reviewer_q123_r2/e02_run/**(持久原件: authority/、base/含 delivery_v1_r2_reference 六件套、01-07 stdout/stderr+rc 内嵌);/tmp 版首次链输出在 F:/trading/reviewer_q123_r2/e02/。
- 7 步全 rc=0: authority-init → issue-permit(code-freeze-sha=qprod-eng-11460de411d6c981,我用 levela_code_identity() 实算,与归档链一致) → rehearse(verdict=PASS,17 ledger steps,qapl-6d33b648… 与归档逐字同) → export → issue-consumption-auth → **formal-scope 拒绝探针 rc=0**(committed 06_formal_reject.probe.py,sha256 前 16=7862b6b82da7b680;"授权 scope='engineering' != 要求 'formal'…正式资格未成立") → consumption-cold-read("cold_read":"ok",scope=engineering,bundle_hash r4pb-26382fb1… 与归档一致)。
- qualification_plan_digest 两链不同(qp262e-1a51f000… vs c77e2895…): 计划含 created_utc(逐次身份),属设计内;parameter_pack_digest 与 preprocessor_bundle_hash 两链逐字相同(内容身份一致);交付内 qualification_plan_digest.txt 与 qapl- 体 hash 一致(前缀系 262 消费侧命名空间),复算相符。

## 7. 22 项矩阵对账

| ID | 判定 | 依据 |
|---|---|---|
| B01 | PASS | HEAD/祖先链清;diff 范围未触 R25/TB;原生 2/2 分账在位(硬门 runner 集成缺口=F1) |
| A01 | PASS(身份确认) | levela 改动均为增量(checks/topology 守卫),上下文贯通面未动;V1 已确认 |
| A02 | PASS(身份确认) | context/permit 未在 R2 diff;适用性不变 |
| A03 | PASS(身份确认) | plan 冻结顺序未变;R2 新增 audit_budgets 结构校验兼容 |
| A04 | PASS(身份确认) | q123 中断/一次性反例保留全绿 |
| C01/C02/C03 | PASS(身份确认) | coordinate 增量不触黄金向量;报告实际 ns/MC/预算面未动 |
| K01 | PASS(身份确认) | K 聚合面未在 diff;事件摘要复算保留 |
| K02 | PASS+增强 | audit_fail 与统计偏差分类(本轮要求),早停正反例保留 |
| X01 | PASS | E02 链 export→冷读实证;零手工修补 |
| X02 | PASS | 七类新拒绝全部实证(§2) |
| X03 | PASS(身份确认) | pack/fit 多重集检查保留(exporter L452-470 我复核) |
| X04 | PASS | formal-scope 拒绝探针实测 |
| E01 | PASS(原件)/F1(硬门) | 原件零改动+如实复算;第三次原生预防当前依赖偶然守卫 |
| E02 | PASS | 我的独立 7 步链+高成本替身明示 |
| E03 | PASS | 冷读 ok+scope/身份拒实测 |
| R01 | PASS(带局限) | 我自己的执行(钉 16+17、qprod 面 122+1、repro、E01、E02);261/262 junit 身份抽查通过;junit 侧车缺件已声明 |
| P01 | PASS | 我全程零新增原生/fit/optimizer;gate 探针用缺失文件+副本脚本,零生成 |
| D01 | PASS(身份确认) | README 未在 R2 diff |
| RV01 | PASS | 本报告即独立 reviewer 全矩阵对账 |
| PK01 | NOT_RUN(按序) | 内容 PASS 后才封包+新目录 ZIP 冷读;本轮不前置 |

## 8. 我的独立原件清单(F:/trading/reviewer_q123_r2/)

1. REPRO_Q123_ROUND2_C10_REVIEWER.json + repro_round2_reviewer.stdout.txt(1/14,F2 实证)
2. E01_RECOMPUTE_REVIEWER_R2.json.stdout.txt(独立只读复算)
3. e02_run/(全链持久原件+delivery 六件套)、e02/(首链 stdout/stderr/rc+06_probe_sha.txt)
4. native_gate_missing_file.stdout.txt(F1 实证: REFUSED 后脚本继续)
5. lock 双向对账、MC1 结构拒、双条 session_acquired 拒、修复版 gate 97 传播: 会话执行记录,关键输出已录于本报告

## 9. 局限与更正记录

- 平台后端元数据仅到配置名,未返回更多,如实说明。
- 261/262 全量回归未由我重跑(任务约定: junit 身份/时间/内容抽查即可);junit 无 R01 侧车原件为既存缺件,已标明未重建。
- F2 中我对归档件的指控以可复现差异为准;若主Agent能出示当日混合部署态(旧 test 文件)的运行日志,可更正为"归档件真实但候选标注不当"——行为结论不变(修复有效),证据标注问题不变。
- 本报告不代签 ChatGPT CLOSED;不递归委派。
