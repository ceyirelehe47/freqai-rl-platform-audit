# QAFv2 ReviewClosure 独立续验报告(第一关:RC01–RC08)

reviewer 线:用户指定 dsv4.1f 独立验收线(本会话不参与被审实现;不递归派 reviewer;未由主 Agent 代签)
日期:2026-10-04 | 被审候选(分支 B):Commit A `8c160d0a7320748f2485bdc5d993da355b317663`(parent 8ffece2b;证据提交 9a8d95f0)
隔离环境:自建 scratch 副本 `/home/cryptorl/tmp_rc_review/selftest`(源头 = 仓库 9a8d95f0 工作树;代码面逐字节 == 8c160d0a git blob,已核)+ 独立 sandbox 域 domA/domB/domC
证据目录(本目录,files 见下表):`/f/trading/local/rc_review/`(WSL: /mnt/f/trading/local/rc_review/)

## 0. 结论

**overall_correctness = incorrect**;confidence ≈ 0.88。原因:RC03 的"首一次性签发前核清批准↔调用参数"未成立(实复现 permit+admission 先落盘、后拒),且 RC04 修复引入 init 并发败者崩溃(自然并发 23/40 复现)。RC04 修复主体(TOCTOU 双写消除)、RC05 连续前缀、RC06 绑定/对拍/同根核验、RC01/02/07 已独立复核通过;RC08 交接文本另有 2 处不一致(低优先)。

## 1. 独立复核方法与实测(均为本会话自跑)

| # | 检查 | 命令/脚本(全部在 /f/trading/local/rc_review/) | 结果 |
|---|---|---|---|
| 1 | 快照/候选字节 | verify_scratch_bytes.sh;INDEX.json vs `git show 8c160d0a:...` | 9 快照全部 == 候选 blob;scratch 5 文件 EXACT |
| 2 | affected 72 独立复跑 | run_tests.sh(guard+reviewclosure)、run_launch_only.sh | 25+5=30 passed;launch 42 passed → 72/72 |
| 3 | RC04 修复前/后 A/B(人工交错) | rc04_ab.py + wrap_word.py | record-approval:OLD 双写(2×rc0,wrote_a+b,文件留 1 份);NEW 恰一胜(opened_a/refused_b);init:OLD 双写 2×rc0;NEW 败者 FileExistsError→分类路径崩溃(见 finding B) |
| 4 | RC04 自然并发 A/B | init_natural_ab.py | OLD 2×40:80 rc0/0 traceback/21 轮双写;NEW 2×40:57 rc0+23 崩溃(23/40 轮败者 traceback,cmd_init 行 86);NEW 4×15:2/45 败者崩溃 |
| 5 | RC04 permit 并发(真实 qaf_v2 守卫路径) | probe_permit_conc.py(domC,4 并发) | 恰 1 胜(rc0),3 个"许可已存在"rc1,0 traceback,1 文件 |
| 6 | RC03 绑定时序反例(核心 finding A) | probe_mismatch.py(domA stale/doxB wrongcand) | stale:permit+admission 均落盘,launch 才拒("批准绑定计划 != 当前计划");wrongcand:permit 落盘,admission 阶段才拒(regression_evidence_commit_unbound);reentry_probe.py:重入 rc=4 不重签 |
| 7 | RC05 机制 | rc05_checks.json(bound_workflow_plan_r17 实调) | 注入 stop=provenance-verify → steps=[provenance-verify,verify-formal-logs],其余 15 步 not_run;verify argv --stopped-at provenance-verify;build_formal_level_a_plan 拒 provenance-verify(生产边界=qualify/verify-formal-logs);bound 仅 run_bounded_formal_chain 调用 |
| 8 | RC06 record | sha256/计数/字段直读 + rerun_substance.sh | 新 record sha 7b4b2be2;2942=2935P+7S/0F/0E;commit 8c160d0a;run0.cwd=D2;run_id r21_20261004_231816;junit sha 自洽;旧 record 8436a1a7 归档不改签 |
| 9 | RC06 同根/错根 substance | rerun_substance.sh(同源 src=P2) | D2 rc=0(sha/计数承诺一致);P2 错根 rc=2 regression_collection_run_cwd_not_deploy_root |
| 10 | RC06 计划 | verify_plan.py | 重算 digest=qbpl-4f202534(新)/qbpl-9aef2bce(旧);payload 逐字节等文件;新旧差异仅 /code_freeze_sha |
| 11 | RC06 三方对拍 | three_way_mine.py(自写) | 625 文件 blob-CR==P2==D2,0 mismatch,18 pyc 分类缺席 |
| 12 | RC06 262 适用 | git diff efb35552..8c160d0a -- stage2_6_2 stage2_6_1/src(空)+ 262 测试无 runner 引用 | 262 面零变化,复用 240/240 适用(未重跑,junit 18:05 旧件在案) |
| 13 | RC01 保护面 | protection_compare_now.json | 旧 P/D 五面(含 4 文件 sha)当前 == 22:31 快照 == 18:07 旧快照 == 前轮 reviewer 独立值;零改 |
| 14 | D2 非激活/新鲜度 | rc05_checks.json + d2_state_check.sh | config/admission/authority/state 全 absent;freshness.fresh=true;A 根 ready=true 无异物 |
| 15 | RC02 钉死源 | 代码/pytest 反例(guard 套件)+ D2 实装 | 25 项全绿含 12+ 反例;stored=r17gtrec-3112e5de;j/d sha 9af55175/cde2b72a |

## 2. Findings(4)

### A. [P1] 首一次性签发前未核对"批准↔调用参数"绑定(违反 NEXT_GOAL §3.2)
- 文件: `stage2_6_1/runner/qaf_v2_operator_entry.py:212-220`(cmd_execute 步骤 2–4 之前)
- 复现(domA stale):正确 E4 参数 + 绑定旧计划 digest 的自洽批准 → permit 与 admission 均落盘,launch 才拒:
  `{"refused": "正式 Level A launch 拒绝(受控副作用前): 批准绑定计划 'qbpl-fc18ecea…' != 当前计划 'qbpl-af9c05bb…' (错计划拒绝…)"}`
  复现(domB wrongcand):--code-freeze-sha 指向另一真实提交 → permit 落盘;admission 在 substance 阶段才拒(`regression_evidence_commit_unbound`)。
- 影响:一次性 permit/admission 被消耗,入口重入 rc=4 受控拒绝,本轮尝试须换新 namespace;正是"不得直到 permit 已产生,才首次发现调用参数与批准中的候选/计划不相符"所禁。
- 修复方向:execute 在首个一次性写前解析 --approval-json,复用 build_formal_level_a_plan+research_plan_digest+validate_formal_approval(与 launch 同款)与 qaf_input_scope_for_attempt 范围核对;--plan-digest 与候选树 digest 重算比对;失败零写。

### B. [P2] 并发 init 败者读取未写完身份文件崩溃
- 文件: `stage2_6_1/runner/qprod_formal_authority.py:85-92`(FileExistsError 处理器)
- 复现:自然 2 并发 init ×40 轮 → 23 轮败者 traceback(JSONDecodeError at cmd_init 行 86,赢者 open 已建档、写未达);人工 barrier 确定性复现;同测旧版(8ffece2b)0 traceback(但 21/40 轮双写)。
- 影响:并发败者以崩溃(rc=1+回溯)代替"按在场身份分类拒绝",入口将输出"authority init 失败"含回溯;未破坏落盘身份(仍单写),但违背本次 RC04 意图与"并发只允许单一受控请求、另一受控拒绝"的可预期行为。
- 修复方向:败者(及快速路径/issue-permit 的身份读取,行 267 同类模式)对空/半写文件做有界重读/退避后再分类;保持 O_EXCL 不变。

### C1. [P2] 待批摘要 §5 仍请求批准旧候选/旧计划
- 文件: `stage2_6_1/artifacts/repair17/development/a2_preissue_guard_v1/PENDING_APPROVAL_SUMMARY.md:33`
- 现状:§1 与 COMMANDS_APPENDIX 已绑定 `8c160d0a`/`qbpl-4f202534…`,§5 仍写"以 Commit A `efb35552` / 计划 `qbpl-9aef2bce…`…请批准"。用户按 §5 构造批准原件将与实际交付/执行参数不符(且与 A 叠加会先耗 permit/admission)。
- 修复:§5 改用新身份(与 §1/附录一致)。

### C2. [P3] E3/E4 命令使用未定义的 `$PREP`
- 文件: `stage2_6_1/artifacts/repair17/development/a2_preissue_guard_v1/COMMANDS_APPENDIX.md:32,42`
- 现状:附录固定值区未定义 `PREP`;E3"写 `$PREP/approval_qaf_v2.json`"与 E4`--approval-json $PREP/approval_qaf_v2.json` 留未定义路径,违反"无未定义路径变量"要求。
- 修复:定义 PREP(如 `PREP=$D2/authority`)或用显式路径。

## 3. 逐 RC 结论(简)

- RC01 通过:旧 P/D 五面当前==22:31==18:07==前轮 reviewer 值;qaf_v2 零签发/消费;D2 非激活。旧账与 v1 失败原样。
- RC02 通过:钉死源三重身份、反例与正例=guard 25 项(独立复跑)+ D2 实装两件字节==钉死。
- RC03 **未通过**:两 issuer 守卫与 launch 漂移重查成立(代码读核+测试),但"首一次性签发前核清候选/计划"未成立(见 A);"输入范围/A2 双参数"同等在 launch 才核对。
- RC04 部分通过:TOCTOU 双写被真实消除(A/B 与 4 并发实测);败者分类路径崩溃(见 B),测试"already∈(1,2)"断言在这种情况下会失败但测试 harness 未命中该交错。
- RC05 通过:独立复跑 5 项全绿;bound 机制、生产边界、科学叶 NOT_RUN 均实核。
- RC06 通过:record 新绑定/旧归档/同根 rc0/错根 rc2/计划重算/三方 625 全等/262 面零变化复用依据成立(未重跑如实)。
- RC07 进行中:本报告即独立续验;后端元数据:会话按用户指定 dsv4.1f 线发起,配置映射见前轮回执(agentModelOverrides reviewer→commandcode/deepseek/deepseek-v4.1-flash:max);实际服务侧元数据在本会话工具面内不可直接观测,如实标注。
- RC08 **存在 2 处文本不一致**(见 C1/C2),其余(E1/E2 与代码一致、E4 序列与 cmd_execute 一致)通过。

## 4. 观察(不阻断)
- CLOSURE_REPORT/PENDING 文字"三方对拍 624 文件"与证据文件 625(本轮新增 1 测试文件)不一致;证据本体 all_equal=true。
- E4 注记"自动完成 E2 安装核验"仅指核验;实际安装仍须先跑 E2(prepare),建议措辞显式列 E2 为前置步。
- `entry check` rc 不反映 freshness(既披露);本轮我以字段/直调 guard 复核,结论一致。
