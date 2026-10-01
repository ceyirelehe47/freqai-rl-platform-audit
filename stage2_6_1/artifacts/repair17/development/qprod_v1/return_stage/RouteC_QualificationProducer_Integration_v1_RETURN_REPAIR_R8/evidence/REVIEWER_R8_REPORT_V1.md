# QProd R8 返修轮(C18)独立内容验收报告 v1

- reviewer: OMP 用户配置 reviewer, zhipu-coding-plan/glm-5.3-flash, 独立上下文, 独立工具, 实际原件
- 日期: 2026-10-02
- 被审对象: C18=cec19ae5(R8 修复) + e4553c88(证据), 分支 route-c-stage2-6-1-repair17
- 基线: C17b=079713cd + 证据 b3397972 + 封包 044a0307;核现场 HEAD=origin=e4553c88(已核实 `git status -sb` 无 ahead/behind)
- 依据原文(按序已读): `local://reviewer_handoff_r8.md` → `repair_round8_notclosed/REVIEWER_ADDENDUM_R8_ORIGINAL.md`(addendum(6)) → `F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/ACCEPTANCE_MATRIX.md`(22 项) → 证据原件 → 代码 diff → E01 原件
- 不沿用 C17b/C17/C16 旧 PASS;已验成果仅做身份/适用性核对后复用

## 0. 结论

**PASS(内容验收通过)**,附 1 项 P2 + 2 项 P3 非阻塞发现(均属封包期须处理的证据归档事项,不属代码内容缺陷;详见 §7)。

核验方式:全部结论基于本会话独立执行的真实命令与输出(命令/rc/输出要点随项标注),独立脚本与原始输出保留于 `F:/trading/tmp_r8/reviewer/`。零新增原生/零生成/零 MC 研究/零 fit/零 optimizer/零模型加载;原生 2/2 不重置(E01 仅只读复算;2711 项回归 skip=7 与 C16/C17b 完全一致,原生面未被触碰)。

## 1. R8 改动面确认(先于内容判定)

- `git show cec19ae5 --stat`: 恰 4 个文件 —— `curriculum261_r17_cue_contract.py`(+102/-14, 全部位于 `recompute_audit_semantics_from_report` 内的 4 个 hunk)、`test_curriculum261_qprod_r8_fixes.py`(新增)、`REPRO_R8_PRE_FIX.py`(新增)、`REVIEWER_ADDENDUM_R8_ORIGINAL.md`(归档)。
- `git show e4553c88 --stat`: 证据索引/E01 复算/262 v13/E02 七步/runner 脚本,共 30 文件 199 插入,0 删除。
- `git diff 044a0307..HEAD --stat -- stage2_6_1/artifacts/repair17/development/qprod_v1`: 31 文件 **326 插入、0 删除** —— C15/C16/C17/C17b 已提交记录零改写;工作树中 `repair_round6_notclosed/evidence/regress_v6/CANDIDATE.txt`、`r21_run.stdout.txt` 的修改未提交(HEAD 版本仍为 079713cd 候选,历史面完好),系 R8 runner 写入路径选择所致(见 §7-F2)。
- `git diff 079713cd..044a0307 -- src`(两树 src): 空 → 提取的 044a0307 版 cue_contract 模块即 C17b 修前字节。
- digest 域/黄金向量: 独立对拍 —— 从 044a0307 提取修前模块 import 后与 C18 模块分别计算 `cue_semantic_contract_digest()`: **r15cue-cf62a57d688289f37bef5dd75ec988310b1ac38be67b93d1a9a21f45a0c4012c 完全一致**(probe P12);`cue_contract_audit_digest` 函数本体不在 R8 diff 内。

## 2. §11 K 输入闭合 —— 真拒且按内容拒绝(判定: PASS)

R8 在 `recompute_audit_semantics_from_report` 的 K 段(curriculum261_r17_cue_contract.py:1510-1573)新增三条闭合规则:频数须非负整数(`cf != ci or ci < 0` → 拒)、Σ频数==`aggregate.n_events`、加权均值 Σ(k·c)/Σc==`aggregate.k_mean`(1e-9 与 R6/R7 来源对账同容差)。

生产语义核对(`curriculum261_r17_noise_replay.py:225-242`): `k_counts[e["k_actual"]] = k_counts.get(...)+1` 逐 event 恰计一次、`n_events=len(events)`、`k_mean=sum(k_actual)/n_events`、`k_histogram={str(k):c sorted}` —— R8 三规则与生产端不变量一一对应,**未发明额外阈值**(1e-9 沿用同函数既有对账容差)。均值与方差共用同一已验支撑:方差(pooled se→冻结容差)仍由直方图重算,但直方图本身先过总量/均值闭合,不再是"只从直方图取方差"。

独立探针(自选数值,与主Agent反例不同值;`probe_r8_independent.stdout.txt`,se=0.02、n_events=120、k_mean=2.0):

| 探针 | 输入(独立值) | 期望 | 实际 |
|---|---|---|---|
| P1 | validation {5:120}, 声明 k_mean 2.0 | 拒 | 拒(disc: 重算均值 5.0 != k_mean=2.0) |
| P2 | model {2:119} vs n_events 120 | 拒 | 拒(disc: 频数总量 119 != n_events=120) |
| P3/P3b | {2:119.5} 小数频数,无/有 fixture | 拒 | 双模式均拒(结构/频数非法) |
| P3n | {2:130, 9:-10} 负频数 | 拒 | 拒('9'=-10 非法) |
| P8/P8b | 合法双键 {1:50,2:70}/{1:52,2:68}+冻结容差精确同步 | 过 | fixture 零委托真通过 + 无 fixture 通过 |
| P9 | 同 P8 但键序重排 {2:70,1:50} | 过且逐值同 | 过;recomputed 与 P8 完全相等 |

主Agent反例重放(C18 字节,本会话独立执行 REPRO_R8_PRE_FIX.py): h1 {4:110} 声明均值 1 → False、h2 {1:109} → False、h3 {1:110,2:-1} → False;翻 reject 门均为 `once_vs_attempts_consistent`(K 判定门),非编号特判。**顺序重排不拒**由 P9 证明。

## 3. §13 在场非法 ≠ 未提供 —— 委托撤销且合法替身保留(判定: PASS)

- R7b 的 `k_tolerance_frozen_malformed` 委托已彻底移除:当前 src/runner/tests 全树 grep 0 命中(旧钉点亦已改写,无陈旧钉残留;qprod 面全绿佐证)。
- 在场非法任何模式恒拒: 修后代码中结构/频数非法分支无条件 `k_ok=False`+disc,不进入 fixture 委托列表。独立探针 P7b: {"garbage-key-9":120} **fixture 在场** → all_consistent=False,`fixture_mode=True` 如实记录,`fixture_delegated` 无该键,disc 明示"在场非法不得被 fixture 委托为 True"。
- 缺件仍如实委托: P10(fixture 下 k_histogram 整块缺失 → `fixture_delegated=['once_vs_attempts.k_tolerance_frozen']`,all_consistent=True)/P10b(无 fixture 同输入 → 拒)。"缺高成本叶"与"坏支撑"两种证明区分成立。
- 合法手工输入不一律拒: P8 fixture 通过且 `fixture_delegated==[]`(真通过,非委托通过)。
- 消费侧闭合(跨边界核对): 唯一消费点 `curriculum261_qprod_levela.py:326` `semantics_consistent=bool(sem["all_consistent"])` → `cue_ok`(行 339-346)→ `gates["cue_audit_pass"]` → `verdict=all(g["pass"])`(行 438);rehearsal 自动加 `engineering_fixture=True`(行 605)后 gate 从盘读入重算,fixture 模式在 `frozen_semantics_detail.fixture_mode` 落盘。即工程入口自动补 fixture 也无法把在场非法洗成 True。
- 两种证明区分: E02 03_rehearse(rc=0, verdict PASS, ledger_steps=17)为 rehearsal 自动 fixture 路径;P7b/P8 直调 pure helper 显式记录 `fixture_mode`。无混用。

## 4. §15 子门支撑(判定: PASS)

生产规则核对(`curriculum261_r17_global_k.py:717-723`): `if not all(g.integrity["ok"])` → `graph_integrity_ok:False, pass:False, verdict:"FAIL"` + **早退 return**(不写 final);PASS 路径必经 tier1/tier2,`pass==(verdict=="PASS")`(行 777-778)。R8 三条子门规则与生产不变量逐条对应。

独立探针(全部自选值):
- P4: graph_integrity_ok=False + verdict=PASS/pass=True/final=PASS → **拒**(disc: 与生产 fail-closed 早退规则矛盾);P4b 对照(FAIL 早退、无 final、checks 如实声明 False)→ all_consistent=True 且无任何 gk disc —— 不加拒边界正确。
- P5: PASS 缺 final 无 fixture → 拒(disc: 生产端 PASS 必经 tier1/tier2);P5b fixture → 委托恰为 `['global_k_audit.final']`,all_consistent=True。
- P6: dg 两语料而 tail.per_corpus 仅 model,无 fixture → 拒("缺整份 validation 支撑;预期集合由上下文决定");P6b fixture → 委托 `tail_mirror_bound_integrity.per_corpus[validation]`。
- **P6c(反"自列冒充")**: 向 direct_generator 注入第三语料 holdout → tail 预期集合随之增长,缺 holdout 支撑被拒 —— 证明预期集合确来自有效上下文(dg),既非硬编码双语料、也非遍历 per_corpus 自身键。在场语料坏子依据拒保持(R5/R6 语义,钉测试 test_r8d_tail_inreport_bad_subkey_still_rejected + qprod 面 0F)。
- 未运行任何随机 Global-K 研究(纯判定重算;合规)。

主Agent反例重放(C18): h4(integrity False+PASS)→ `global_k_audit_pass=False`、h5(PASS 缺 final)→ 同门 False、h6(tail 缺 validation)→ `tail_mirror_bound_integrity_pass=False`。

## 5. 修前/修后对拍与"内容拒绝"证明(判定: PASS)

- 修前(本 reviewer 用 044a0307=C17b 字节模块,经 shadow 包独立搭环境重放主Agent REPRO_R8_PRE_FIX.py): **h1-h7 全部 all=True(7 洞真实存在)+ 3 正控制 True**(`repro_prefix_c17b.stdout.txt`)。
- 修后(同脚本的提交版在 C18 部署字节直接重放): h1-h7 全拒(逐门: ova×3、gk×2、tail×1、ova-fixture×1),3 正控制全过(本会话 §48 记录)。
- 内容拒绝(非旧 SHA/非示例值特判): 我的探针全部使用与主Agent不同的数值/键(garbage-key-9、5:120、119.5、holdout 等)均被同一规则拒绝,且合法异值(P8)通过、digest 域未变(P12)而新检查生效 —— addendum 第 4 点(反例公共 digest 正确、不以 digest 域未变拒收新检查)成立。
- addendum 第 5 点(P3 不被借用延期): 新检查全部在旧 digest 域不变下按内容实现(P12 实证),未以"全自洽 K 字段 hash 登记"替代本轮矛盾拒绝。

## 6. 证据身份与适用性(r21/262/E01/E02/旧记录)

- **r21 v6 C18**(repair_round6_notclosed/evidence/regress_v6/full_regression_v6_c18/): `regression_evidence_v3_record.json` sha256 复算==f9e44621ae9e69b36a9c1a723e4799011c778df05d8b767d4a43b14b12b61d75 ✓;record 内 12 个成员文件 sha256 逐一复算全对(2 个 deploy 侧绝对路径条目为部署树身份记录,已按部署实文核验: conftest 3f18b250... 与记录一致)✓;junit.xml: tests=2711 failures=0 errors=0 skipped=7 ✓;record 内 commit_a_sha=cec19ae5410... ✓;summary.verify 2711/2225/161(一次通过)✓;executor/auditor blob=deploy sha256 相等(记录内自证,runner 与 R7 轮同一 r21 流程)。依约不重跑全量(单重型作业已由主Agent执行,原件齐)。
- **262 v13 C18**: meta candidate=cec19ae5410...,rc=0,stdout 240 passed(`regress262_v13_c18.*`)✓。
- **E01 C18 只读复算**: `E01_RECOMPUTE_C18.json` zero_native/read_only=true;coords 与 C15/C16/C17 三轮逐值相等(本会话 python 对比 True×3)✓;E01 原件 `qprod_v1/native_smoke_run{1,2}` 最后改动为 bd6ed858(旧轮),工作树零 diff,R8 两提交未触碰 → 未重新生成 ✓。
- **E02 R8**: 7 步 meta 全 rc=0;03_rehearse verdict=PASS(工程 scope);06_formal_reject 探针 rc=0 且输出 "formal-scope rejection OK: qualified input 拒绝: 授权 scope='engineering' != 要求 'formal'";07 cold read rc=0。链路标签 COLLECTION.json 写 "E02_R3 chain" 系链格式名沿用(时间戳 2026-10-01T16:55Z 为本轮执行),如实记录不判缺陷。
- **部署树同步**: 部署 `src/rl_curriculum/curriculum261_r17_cue_contract.py` 与仓库 HEAD 文件 sha256 相等(beb6648150...),R8 测试文件相等(6bacb6ae...)—— 本轮全部探针/测试跑在 C18 字节上。
- **E 盘桥接**: `/mnt/e/trading/freqai-rl-audit -> /mnt/f/trading/freqai-rl-audit` 在位(历史面测试前提成立)。
- **远端**: origin/route-c-stage2-6-1-repair17 = e4553c88 = 本地 HEAD(两提交已推)。
- **已验成果复用核对**(不重开,仅身份/适用性): 五旧反例 C15→C17b 拒绝保持由 qprod 面内 r5_fixes/r6_fixes 钉测试全绿佐证;R6 K 修复保留(同上+本面 K 段在其上叠加);Q2/Q3(q123/r2-r4_fixes)在 170 全绿内;历史 envfail_e_drive/flaky_t09 原件目录在册(tracked);1 未批早停观察未重开。**R8 未使任何旧反例回潮**(170+12+34 全部 0F)。

## 7. 发现(非阻塞,不改变本轮内容判定)

- **F2(P2, 封包前须处理)R8 的 r21 回归证据目录未提交未推送**: `full_regression_v6_c18/`(13 文件,含 record f9e44621/junit/audit)在 git 中为 untracked,e4553c88 未包含。既有惯例是随证据提交(b3397972 即含 full_regression_v6_c17b/;c14-c17b 各目录均 tracked,共 205 文件)。远端现缺 R8 的 r21 原件;本地原件齐且我已逐字节核验。处置:随最终封包逐字节收入(或补提交),并保持与回执 SHA 绑定一致。
- **F3(P3)R8 runner 把运行标记写进 R6 轮证据目录**: `qprod_r8_r21_regress.sh` 的 EVD 指向 `repair_round6_notclosed/evidence/regress_v6/`,`tee CANDIDATE.txt`/`r21_run.stdout.txt` 覆盖了 tracked 的 C17b 轮同名文件(工作树版,未提交;HEAD 提交历史未改写)。建议封包前把 R8 版标记迁入 R8 证据目录并还原 R6 目录的历史字节,避免后续误提交造成旧轮工作树记录被改写。
- **F4(P3)文档计数小误**: EVIDENCE_INDEX/handoff 称"钉 R8 12",实际钉文件为 11 个测试函数(pytest 收集 11,覆盖七反例+三正控制+FAIL 早退+fixture 委托标注+在场坏子不退化等 13 类断言)。覆盖完整,仅计数口径不精确,建议修正索引文字。
- 观察项(不要求行动): (a) 直方图频数为数字字符串("120")或 bool 时按数值语义放行——总量/均值闭合仍对其精确约束,数值语义无洞,属宽松接码非矛盾放行;(b) e4553c88 在 R8 regress262 目录带入 0 字节 `regress262_v11_c17.stderr.txt`(无害冗余);(c) "qprod 面 182" = stage2_6_1 `-k qprod` 170 + `test_ppo262_qprod_export.py` 12(两段均已独立跑通 0F);"cue-contract 面 29" 为我实测 34(r8=11,r9=6,r10=6,r17binding=11)的子集,34/34 全过,声称保守无隐瞒。

## 8. 22 项矩阵对账

| ID | 判定 | 本轮依据 |
|---|---|---|
| B01 | PASS | HEAD=origin=e4553c88;R25/TB 结项记录零改写(diff 0 删除);scope 仅 Q1 同根收口 |
| A01 | PASS(复用) | 上下文贯通路径 R8 未触;levela/coordinate/plan/permit/context 钉测试在 170 全绿内 |
| A02 | PASS(复用) | 许可/隔离面未触;E02 01-02 步 rc=0;A02 钉在套内全绿 |
| A03 | PASS(复用) | 冻结/两阶段计划未触;E02 rehearse qapl 绑定 rc=0 |
| A04 | PASS(复用) | 一次性/中断语义未触;A04 钉在套内全绿 |
| C01 | PASS(复用) | 坐标锁未触;E02 c01 namespace 链 rc=0 |
| C02 | PASS(复用+R8 增量) | 共享核心判定函数为 R8 唯一改点;黄金向量/digest 域逐值不变(P12);报告身份键未动 |
| C03 | PASS(复用) | 锚分离未触;C03 钉在套内全绿 |
| K01 | PASS(R8 直接强化) | §2/§5: 频数/总量/均值闭合+生产语义对应+独立值探针全拒 |
| K02 | PASS(复用) | 停止分层未触;K02 钉在套内全绿 |
| X01 | PASS(复用) | 导出接口未触;E02 04_export rc=0(公共 raw 判定→导出→QualifiedInput) |
| X02 | PASS(R8 强化) | 矛盾报告拒(all_consistent→gate→verdict 链);E02 06 formal 拒 rc=0 |
| X03 | PASS(复用) | pack/fit 来源未触;X03 钉在套内全绿 |
| X04 | PASS(复用) | 消费/授权未触;E02 05/07 rc=0;06 证明工程/正式不串用 |
| E01 | PASS(只读) | 复算 coords 与 C15/C16/C17 逐值一致;原生 2/2 原件零改动;零新增原生 |
| E02 | PASS | R8 七步 rc=0;分层证明完整(rehearse 工程链+formal 拒+cold read);fixture_mode 双路径区分(§3) |
| E03 | PASS | E02 07 新进程冷读 rc=0;绑定 hash/namespace 与 export 一致 |
| R01 | PASS | r21 v6 C18 2711/0F/7skip record f9e44621 成员逐字节核验;262 v13 240 RC=0;无新增 skip(7 与 C16/C17b 同);证据归档缺陷见 F2(封包项,非计数缩水) |
| P01 | PASS | 单重型作业=r21(主Agent已跑);本轮零新增原生/MC/fit/optimizer/模型加载;探针均为纯判定 |
| D01 | PASS(复用) | README/下一出口 R8 未触,基包链有效 |
| RV01 | PASS | 即本报告: 指定模型/独立上下文/实际正反例/修前修后对拍/原件留存 tmp_r8/reviewer |
| PK01 | 待封包(本轮按约不判 FAIL) | 内容 PASS 后封包;F2/F3 为封包清单项;最终 ZIP 冷读+包外回执属后续步骤 |

无一项 FAIL/BLOCKED。按矩阵判定规则,本候选内容验收通过;PK01 的最终包动作按本轮合同发生在内容 PASS 之后。

## 9. 局限(如实)

- r21 全量回归未重跑(按约定做身份/字节/内容抽查: record 哈希、12 成员哈希、junit 计数、候选绑定、执行器身份),资源保护合规;重跑自担 40 分钟未触发。
- Level A gate 拒绝链以代码引用(levela:326/339-346/438)+ 钉测试 + E02 七步实证,未对"gate 拒绝后再驱动整个 rehearsal 入口"做端到端负例注入(该路径由同一 bool 收口,无旁路分支;风险极低)。
- 平台未返回 reviewer 后端元数据(模型自报 zhipu-coding-plan/glm-5.3-flash,如实说明)。
- 直方图 leniency(字符串/bool 频数)与 E02 链标签沿用为观察项,未升级为发现(数值语义闭合,无矛盾放行)。

## 10. 边界声明

本报告为独立内容验收,不代签 ChatGPT 最终 CLOSED;不重置原生 2/2;P3(全自洽 K 未被旧 digest 绑定)仍留未来轮。返回 **PASS**,失败项:无;封包前请处理 §7 F2(必须)与 F3/F4(建议)。

## 11. 附记:V1 三项发现的处置核验(2026-10-02,23355a7d)

主Agent 处置后本 reviewer 最小核验(全部独立命令实证):
- **F2(P2)**: full_regression_v6_c18/(13 文件)已 tracked 于 `repair_round8_notclosed/evidence/regress_v6/`;record sha256 复算==f9e44621ae9e69b36a9c1a723e4799011c778df05d8b767d4a43b14b12b61d75;10 个本地成员哈希逐一复算全对(另 2 条为部署树 conftest 身份记录,此前已对部署实文核验一致);旧路径已迁移不残留;`git ls-remote origin` = 23355a7d0843fc0b001db6fe16466ff5c3b4fdac = 本地 HEAD(已推)。远端可审计性恢复。
- **F3(P3)**: runner EVD 已改指 R8 目录(HEAD 版行 10);`git diff e4553c88..HEAD -- repair_round6_notclosed` 为空且两文件工作树 clean → C17b 轮 CANDIDATE.txt/r21_run.stdout.txt 字节级还原;R8 运行标记重建于 R8 目录(candidate=cec19ae5410...,rc=0,summary 尾行 record_sha256=f9e44621... 与 record 一致),RUN_MARKERS_REBUILT.md 如实说明重建来源。
- **F4(P3)**: EVIDENCE_INDEX 行 31 已改"钉 R8 11(测试函数)"。
- 内容候选未动: `git diff e4553c88..23355a7d -- stage2_6_1/src stage2_6_1/tests stage2_6_2/src stage2_6_2/tests` 为空;diff 全量 17 文件 8214 插入/2 删除,全部为证据/脚本/索引面。
- 本报告 §6/§7 所引 full_regression_v6_c18/ 路径自处置起以 R8 目录新路径为准(同字节)。
- 结论不变:**PASS**;可封 R8 增量包,本 reviewer 按约对最终 ZIP 做冷读核验。
