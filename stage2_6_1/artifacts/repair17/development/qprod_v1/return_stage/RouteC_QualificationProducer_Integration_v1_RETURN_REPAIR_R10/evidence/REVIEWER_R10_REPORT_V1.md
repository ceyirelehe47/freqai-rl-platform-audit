# QProd R10 返修轮独立内容验收报告(v1)

- reviewer: OMP 已配置 reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文、实际工具、真实原件;不沿用 R9/C20 旧 PASS;独立判定,不代签 ChatGPT CLOSED。
- 日期: 2026-10-02
- **结论: 内容验收 PASS**(R10 修复 C21=da5655b5 对 addendum (8) 三同根洞及全部同根不变量成立;无阻断项)
- 独立原件留存: `F:/trading/tmp_r10/reviewer/`(probe_r10_indep.py、probe_holes_fixture.py、probe_out/cases.jsonl(53 例全记录)、probe_out/holes_c20.jsonl、probe_out/holes_c21.jsonl、probe_run.log、各 run_*.sh、legal_input_fixture_{false,true}.json、fix_diff.txt)

## 0. 实际复验环境摘要(不沿用脚本默认标签背书)
- 候选: **C21=da5655b5**(git show 实读;部署树 `~/projects/crypto_rl` 的 `src/rl_curriculum/curriculum261_r17_cue_contract.py` sha256=c2c88d64…a5c3 与仓库 HEAD 工作树逐字节一致;`test_curriculum261_qprod_r10_fixes.py` sha256=b89c76aa…6614f 同)
- 仓库 HEAD=remote=8d60604b(证据提交);工作树对 R10 相关路径干净(artifacts/qprod_v1 下 0 dirty)
- 解释器: `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`(Python 3.11.16);导入路径: cwd=部署树根,`PYTHONPATH=src`(两元域);`PYTHONDONTWRITEBYTECODE=1`
- 执行方式: wsl bash + 脚本文件(规避 wsl.exe 吞变量);全部探针零新增原生/零生成/零 MC 研究/零 fit/零 optimizer/零模型加载(直调公共判定入口 `recompute_audit_semantics_from_report`,输入为合成 report dict)

## 1. 必读原文核对
1. `local://reviewer_handoff_r10.md` — 已读:目标逐字(§0)、修复映射(三洞)、复现与修复证据、边界一致。
2. `REVIEWER_ADDENDUM_R10_ORIGINAL.md`(git HEAD 原件,44 行)— 已读:验收要求主体=五条同根不变量+证据与完成条款,与交接件一致。
3. 原 22 项矩阵 `F:/trading/trading/goal_incoming/route_c_qpi_v1/.../ACCEPTANCE_MATRIX.md` — 已读:B01/A01-A04/C01-C03/K01-K02/X01-X04/E01-E03/R01/P01/D01/RV01/PK01。
4. 证据目录与代码 — 已读:EVIDENCE_INDEX/E01/REPRO/evidence(regress_v6、regress262、e02)/da5655b5+8d60604b 实 diff。
5. 材料事实核对:本轮 Downloads 仅 addendum(8) 一说与交接一致;REVIEW.md/RUN_LOCAL.md/probes/final_run/RESULT.json 无新件,验收按原 22 项矩阵+addendum (8) 执行,与交接边界吻合。

## 2. addendum (8) 同根不变量逐项判定(本人独立探针,53 例全过,PROBE_RC=0)

判据列 `all=all_consistent`,deg=fixture_delegated 条数,disc=threshold_discrepancies 条数;每例均断言 `fixture_mode` 回显真实 `engineering_fixture` 标志。

### (1) 基础检查不依赖无关字段是否提供
| 例 | 模式 | 结果 | 关键理由(disc 首条) |
|---|---|---|---|
| A0 合法完整正式报告 | formal | all=True, deg=0, disc=0 | —(公共判定真实通过) |
| A0f 合法完整报告 | fixture | all=True, deg=0(全字段在场→无缺件可委托) | — |
| A1 坏 validation 直方图(均值4 对来源 160/110),ova 在场 | 双模式 | 均 all=False | "重算均值 4.0 != k_mean"(R9 反例保持) |
| A2a 删整个 ova + 在场 `{"nan":110}` | 双模式 | 均 all=False | "k_histogram 结构/频数非法('nan'=110…)" |
| A2b 删整个 ova + 在场均值4 直方图 | 双模式 | 均 all=False | "重算均值 4.0 != k_mean=1.4545…"(**坏件理由,非缺件理由**) |
| A2c 删整个 ova + n_events=110.5 | 双模式 | 均 all=False | "n_events 非数值/非有限/非整数/负计数(110.5…)" |
| A2d 核心不变量(fixture 委托缺 ova × 在场坏直方图) | 双模式 | 均 all=False;fixture 下委托资格存在但仍拒 | 同 A2b;见 §4-O1 观察 |
| A2e model 侧坏直方图 + 删 ova(对称性) | 双模式 | 均 all=False | "重算均值" |

三变体("nan" 字符串键/hist 均值 4 对声明 1(本探针为 4 对 160/110,实质同义)/110.5)逐一覆盖;拒绝理由均为在场坏件语义,非缺件。

### (2) 单个 ova 派生均值 NaN/Inf
| 例 | 模式 | 结果 |
|---|---|---|
| B1 k_mean_model=NaN,另一侧在场 | 双模式 | 均 all=False("k_mean_model 非数值/非有限") |
| B2 k_mean_model=NaN + 删另一侧 | 双模式 | 均 all=False |
| B2f 同上 fixture | fixture | all=False 且 deg=['once_vs_attempts.k_mean_validation'](**委托已列且仍拒——委托≠清除**) |
| B3 k_mean_validation="nan" + 删 model 侧 | 双模式 | 均 all=False |
| B4 k_mean_model=+Inf | 双模式 | 均 all=False |
| B5 合法单侧删除 | fixture | all=True, deg 恰=`['once_vs_attempts.k_mean_validation']` |
| B5f 合法单侧删除 | formal | all=False("缺必需子依据"——既有 C14 正式语义,非本轮回归) |

"两个齐全才检查"已被消除:单字段在场即验有限性+来源对账。

### (3) n_events=-1(len(events) 计数语义)
| 例 | 模式 | 结果 |
|---|---|---|
| C1 nev=-1,直方图在场,ova 在场 | 双模式 | 均 all=False("负计数") |
| C2 nev=-1 + 删同侧直方图 | 双模式 | 均 all=False;fixture 下 deg 含 `once_vs_attempts.k_tolerance_frozen` 且仍拒 |
| C3 nev=-1 + 删 ova | 双模式 | 均 all=False("负计数"先验在场即拒) |

负值检查在两处先验(缺件先验+直方图在场分支)均生效,有限整数检查不再代替合法计数检查。

### (4) 合法缺件既有工程委托保持
| 例 | 模式 | 结果 | 委托清单(精确断言) |
|---|---|---|---|
| D1 合法删整个 ova | fixture | all=True | `['once_vs_attempts']` |
| D2 合法删整个 ova | formal | all=False(正式缺件语义,既有) | — |
| D4 合法删 validation 直方图 | fixture | all=True | `['once_vs_attempts.k_tolerance_frozen']` |
| D5 同上 | formal | all=False("缺件") | — |
| D6 合法 k_mean 来源缺件 | fixture | all=True | `['once_vs_attempts.k_mean_validation.source_missing']`(R7 语义保持) |
| D7 同上 | formal | all=False("K 来源缺失") | — |

委托只覆盖真正未提供部分(清单逐键精确);负例未被变绿,在场坏输入未被委托清除。

### (5) 公共摘要重算 + fixture_mode 实核
- 每例断言返回含 recomputed 8 键、`fixture_mode` 回显、fixture_delegated 去重排序;formal 模式断言零委托。
- P0 持久对象实核:同一 dict 对象 `engineering_fixture` False→True→False 切换,`fixture_mode` 依次 False→True→False;全字段 fixture 无委托。
- 全部用例真实输入(合法基线 JSON 两态归档)+真实返回(全字段)+失败原因(完整 disc)留存 `probe_out/cases.jsonl`;非只证明 hash 错误拒。

### (6) 原在场坏支撑/部分缺失/合法重排/多键直方图/有限性控制
- E1 合法重排(键序 {"2.0","1.0"} 重排)formal all=True(冻结公式序无关);E2 多键坏均值 no-ova 双模式拒;E3 NaN 浮点字面量键拒;E4 负频数拒;E5 n_events="abc" 拒;E6 k_tolerance 声明 0.05 对冻结公式 0.20234428643024915 漂移拒(**冻结公式重算真实在岗**);E8 dg k_mean=Inf 拒;E10 坏直方图+k_modes_consistent=True 谎报拒(双重理由)。

## 3. 修前/修后对照(本人独立复现,最强证据)
用同一 6 组 fixture 模式反例分别跑 **C20 字节(52e70a17,隔离树)** 与 **C21 字节(部署树)**:

| 组合 | C20 字节 | C21 字节 |
|---|---|---|
| H1aF no-ova+"nan"键 | **all=True(逃逸)** | all=False(拒) |
| H1bF no-ova+hist均值4 | **all=True(逃逸)** | all=False("重算均值 4.0 != …") |
| H1cF no-ova+110.5 | **all=True(逃逸)** | all=False("负计数/小数") |
| H2bF km-NaN 另一侧删 | **all=True(逃逸)** | all=False("非数值/非有限") |
| H2cF kv-"nan" 另一侧删 | **all=True(逃逸)** | all=False |
| H3bF nev=-1 同侧 hist 删 | **all=True(逃逸)** | all=False("负计数";委托已列) |

即:6 洞在 C20 真实存在(独立复现,非转述),C21 全部关闭,且拒绝理由为坏件语义(见 probe_out/holes_c21.jsonl 逐条 disc)。无 fixture 路径修前因缺件拒、修后同为拒但理由升级为坏件——与交接声明一致。

## 4. 证据身份与原件抽查
- **r21 v6 C21**:`regression_evidence_v3_record.json` sha256=b3fc0fa29427ef5…46a48e 与 summary/EVIDENCE_INDEX 一致;commit_a_sha=da5655b5ee2c8f76…;counts 2731/0F/0E/7skip;junit.xml 实测 2731 testcase/0F/0E/7skip;execution.stdout 尾行 2724 passed+7 skipped;**skip 集合与 C20 记录逐项相同(0 新增 skip)**;test_files=163;verify 2731/2245/163 与声明一致。
- **262 v16 C21**:junit 240/0F/0E/0skip;meta 绑定 candidate=da5655b5…、解释器 3.11.16、rc=0。
- **C20 及更早原件零改写**:987f6117→8d60604b 全 diff 仅 repair_round10_notclosed/(新增)+runner 新脚本+src 1 文件+tests 1 文件;qprod_v1 下 round10 之外 0 文件变更;工作树 artifacts/qprod_v1 0 dirty。
- **E01 零原生沿用**:E01_RECOMPUTE_C21.json 数值 payload 与 E01_RECOMPUTE_C19.json 逐字段相同(format/notes 除外);原生 2/2 不重置(run1 valid=1,run2 valid=2)。
- **E02 七步 rc=0**:authority init→permit(digest qppm-5d14f0…)→rehearse(17 ledger steps,PASS)→export→consumption auth(binding e262az-c775… )→formal reject(scope='engineering'≠'formal' 真拒)→cold read ok(bundle r4pb-26382fb1…)。
- **digest 域/黄金向量不变**:`cue_semantic_contract_digest()` C20 字节=C21 字节=`r15cue-cf62a57d688289f37bef5dd75ec988310b1ac38be67b93d1a9a21f45a0c4012c`(本人双树实测)。

## 5. 本人实际执行的定向复跑(部署树,全部 rc=0)
| 跑 | 结果 |
|---|---|
| R10 钉测试 + R8/R9 钉(3 文件) | 31 passed |
| r9/r10 cue-contract 钉 | 12 passed |
| qprod 面(-k qprod) | **190 passed**(与声明 190/190 一致) |
| 独立探针 probe_r10_indep.py(53 例) | ALL OK,PROBE_RC=0 |
| 洞对照 probe_holes_fixture(C20/C21 双树) | C20 6/6 逃逸,C21 6/6 拒 |

全量 r21/262 回归未重跑(约束:最多一个重型作业,主 Agent 已跑毕且原件齐);以上为身份/字节/内容抽查+定向必跑,符合边界。

## 6. 22 项矩阵对账
原则:已结项模块只按新变更影响复验(矩阵明文);R10 变更面=Q1 判定入口语义,故重点复验 C02/X01/X02/R01/E01/E02 相关,其余按 C21 全量回归绿+零变更 diff 复用。

| ID | 本轮判定 | 依据 |
|---|---|---|
| B01 | 符合(复用+核身份) | HEAD=remote=8d60604b;R25/TB 面零变更 diff;qprod 190 绿 |
| A01/A02/A03/A04 | 符合(复用) | R10 零触及;r21 v6 C21 全量 2731/0F;E02 05/06/07 rc=0 |
| C01 | 符合(复用) | E01 payload 与 C19 逐字段同,零新增原生 |
| C02 | 符合(本轮重点复验) | digest 双树实测相同;黄金向量钉绿;报告身份=实际重算(本报告 §2) |
| C03/K01/K02 | 符合(复用) | 零变更面;K 判定消费侧即本轮修复对象,§2/§3 已验 |
| X01 | 符合 | E02 export rc=0;读取侧判定=本探针直调入口,§2 全过 |
| X02 | 符合 | E02 06 formal reject 真拒(授权 scope≠formal) |
| X03/X04/E03 | 符合(复用) | 262 v16 cold read ok,meta 绑 da5655b5;E02 05/07 rc=0 |
| E01 | 符合 | E01 C21=原件数值;2/2 维持 |
| E02 | 符合 | 七步 rc=0,分层真实(rehearse 17 步+冷读,未把沙箱说成正式 PASS) |
| R01 | 符合 | r21 v6 C21 record b3fc0fa2 身份/计数/skip 集合实测核对;262 v16 240 RC=0 |
| P01 | 符合 | 单重型作业=r21 v6 C21(主 Agent);本复验仅定向零重型;零新增原生/MC/fit/optimizer/模型加载 |
| D01 | 符合(复用) | 本轮零变更;内容 PASS 后按边界封增量包 |
| RV01 | 符合 | 本报告=独立 reviewer 全矩阵对账+独立正反例;C19 三项发现修复链完整(R9→R10) |
| PK01 | **按设计待封**(非失败) | 内容 PASS 在先、封包在后(交接边界明文);R9 期 C20 包完整性核验保持,历史字节未动 |

## 7. 非阻塞观察(P3,均不 impacting 验收)
1. **O1 else 分支短路账目**:ova 删除+在场坏 K 支撑时,`k_ok and _delegated_flag(...)` 短路使 fixture_delegated 不记 "once_vs_attempts"(cue_contract.py:1744)。拒绝语义不受影响(拒仍成立,且已拒报告的委托账目无接受性后果);仅审计账目在"已拒"路径少一行标注。可选修:`delegated.append` 与短路解耦。
2. **O2 runner 标签沿用旧轮字符串**:qprod_r10_r21_regress.sh:20 `--label …_r9b_c20` 用于 C21 run。候选身份由 `git rev-parse HEAD`/record commit_a_sha 绑定,不受标签影响;属外观性遗留,建议下轮改标签。
3. **O3 run_id 时戳语义**:record run_id=r21_20261002_063944(+08) 早于 junit 会话起点推算的执行结束(~06:41:08+08)约 1.5 分钟;record sha/commit 绑定/计数/lifecycle UTC(21:59:05Z 起)均自洽,不影响任何身份锚;记录在案备查。

## 8. 局限
- 未重跑全量 r21/262(约束允许且原件经身份/字节/内容抽查);262 v16 仅核对 junit/meta/stdout 原件,未独立复跑。
- REPRO_R10_PRE_FIX.py 原样(非 fixture 模式默认)在我的 C20 隔离树上 6 洞均因缺件拒(all=False)、控制组符合——与交接"无 fixture 路径因缺件拒"一致;fixture 模式逃逸由我的 probe_holes_fixture.py 独立证实(§3)。
- 平台后端元数据(模型服务侧)不可见,如实说明;不代签 ChatGPT CLOSED,最终 CLOSED 由 ChatGPT 独立终验。

## 9. 判定
**PASS** — addendum (8) 五条同根不变量全部经本人独立探针(53 例)+C20/C21 双字节对照成立;合法委托保持;公共摘要重算与 fixture_mode 实核在岗;证据身份链完整;C20 及更早原件零改写;零新增原生/生成/MC 研究/fit/optimizer/模型加载。失败项:无。


## 10. C22 轻量复验(P3 处理后,2026-10-02;最终候选 C22=1361b4bb+证据 7af5268b)
V1 PASS 之后的 P3 处理复验,仅核受影响面:

| 项 | 判定 | 证据(本人实核) |
|---|---|---|
| P3-1 拒绝路径委托账目 | **符合** | src diff 仅 else 分支 6 行(`_ova_delegated = _delegated_flag(...)` 先记账再合成);本人探针 A2d fixture: all_consistent=**False** 且 ledger=`['once_vs_attempts']`;53 例全过(PROBE_RC=0,其余语义零变化);洞对照 6/6 仍拒且 ledger 非空(H1aF/H1bF/H1cF→`['once_vs_attempts']`,H2bF/H2cF/H3bF 保持各自精确条目);新钉 test_r10p3 双断言(拒:False+账目;合法:True+账目) |
| P3-2 runner label | **符合** | qprod_r10_r21_regress.sh:20=`…_r10_c22`;record label 字段=`r21_full_collection_regression_qprod_r10_c22` |
| P3-3 run_id 时戳 | 记录不改(同意) | 实体锚 V1 已核自洽 |
| 新回归身份绑定 | **符合** | `regress_v6/full_regression_v6_c22/regression_evidence_v3_record.json` sha256=3c1820bdccd33d35…f34d55=声明;commit=1361b4bb;run_id=r21_20261002_074445;counts 2732/0F/0E/7skip;test_files=163;262 v17 meta 绑 1361b4bb rc=0(junit 240/0/0,240 testcase);初次 sed 误截已按 OUTPUT_MOVE_NOTE 迁移补齐(EVIDENCE_INDEX 第 45 行注明) |
| 受影响面 | **符合** | R10 钉 7 passed;qprod 面 191 passed(均为本人部署树实跑) |
| C21 record b3fc0fa2 | **零改写** | diff 8d60604b→7af5268b 在 round10 evidence 内仅新增文件,C21 全部证据文件无修改 |
| 树一致性 | **符合** | 部署树 src/tests 两文件 sha256 与仓库工作树逐字节一致(62413e1e…/784f40f8…);remote=7af5268b |

**C22 复验结论: PASS**(V1 的 53 例不变量结论在 C22 语义未动;P3-1/P3-2 修复属实;可封 R10 增量包)。
