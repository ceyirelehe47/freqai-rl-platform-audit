# QProd 返修轮(Q1/Q2/Q3)独立内容验收报告 v1

- Reviewer:OMP 已配置 reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文,未参与被审实现。
- 被审对象:候选 **C8=bd6ed858**(单提交),HEAD=d4a4e73a(证据提交),分支 route-c-stage2-6-1-repair17。
- 验收依据:`local://reviewer_handoff_q123.md`、`REVIEWER_ADDENDUM_ORIGINAL.md`(14 行原文)、原任务包(`F:/trading/trading/goal_incoming/route_c_qpi_v1/RouteC_QualificationProducer_Integration_v1/`:README/NEXT_GOAL/ACCEPTANCE_MATRIX/SCOPE_AND_BUDGET/RUNBOOK/RETURN_REQUIREMENTS/RESEARCH_BOUNDARIES)、E01 原件、修复轮证据与单提交 diff(全部亲读)。
- 复验环境:WSL 部署树 `~/projects/crypto_rl`(src 与 C8 逐字节同步,已核对 5 个改动文件 sha256:levela=b06e38f2…、coordinate=9d827c88…、aggregate=2d91e029…、permit=64153ea4…、ppo262_qprod_export=33207285…,repo 与 deploy 完全一致);python=`/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python`;PYTHONDONTWRITEBYTECODE=1。
- 边界执行:零新增原生生成/零 fit/零 optimizer;原生次数维持 2/2 耗尽、本轮全部为只读复算/合成输入/fake 叶实现/测试;单重型 WSL 作业顺序执行。

## 总判定:**FAIL(工程,1 项 P1 + 1 项 P2;其余全部独立复验通过)**

未满足项(直接证据与复现方式见 §5):
1. **[P1] `curriculum261_qprod_coordinate.py` 通用失败/中断记账被顶掉(死代码 637-648 行)**——非配额失败/中断不再写中断标记与账本行,违背 Q2「失败/重试/中断不能漏账」与 A04;且削弱中断目录重入拒绝。bd6ed858 引入的回归,C7→C8 同探针对拍实证。
2. **[P2] `REPRO_Q123.json` 候选标注失实 + 修复前 15/15 证据未保存**——提交版是 C8 复跑结果(0/15)却硬编码「C7=cda4e975」,EVIDENCE_INDEX 声称的「修复前 reproduced=true ×15」在包内无对应原件,证据-索引自相矛盾(违反「保存失败原件与新结果」/PK01)。reviewer 以 git archive 提取 691bd73a 原件树独立重跑补证:15/15 复现属实,但交付件必须自洽。

以下主体项全部真实复验通过(证据均在 reviewer 自有工作区 `/f/trading/tmp_reviewer_q123/`):

## 1. Q1 公共资格步骤→raw 判定与导出:**PASS**

| 核验点 | 结果 | 证据 |
|---|---|---|
| provenance-verify 复用公共权威(r17_workflow_step_names/r17_producer_of_artifact)对拍,缺 topology/伪步骤→链 FAIL | 通过 | levela.py 443-481 行;钉测试 missing/fake-topology 2 例;REPRO Q1 R1b 复跑 reproduced=False |
| preplan FAIL→plan-roundtrip 前置失败→链 FAIL(<17 步),不再 17 步 PASS | 通过 | levela.py 528-566 行;钉测试断言 ledger verdict=FAIL 且 steps<17;REPRO R1a reproduced=False |
| gate1 cue digest 用公共 `cue_contract_audit_digest` 复算;gate4 复用 262 `parameter_pack_digest`,删除本地重写 | 通过 | levela.py 259-330 行 diff;夹具改为公共函数实算摘要(不可自由伪造) |
| result 绑定 raw_evidence_sha256 + calibration_artifacts_digests | 通过 | levela.py 723-742 行;导出逐项核验(见下行) |
| 导出:producer journal 真实终态恰 1 条(run_terminal_recorded,绑定 plan digest/status=completed/verdict 一致) | 通过 | ppo262_qprod_export.py 248-283 行;终态事件由 QProdRunSession(context.py:477)真实写入;钉测试删 journal→拒 |
| 导出:raw 字节绑定(raw 改坏外层自洽仍拒) | 通过 | 钉测试 raw_tamper_with_consistent_outer→QProdExportError(raw_evidence_sha256 不符) |
| 导出:校准前置逐项 digest(缺失/漂移拒) | 通过 | 钉测试 tamper holdout→拒(校准前置) |
| 判定/锁/身份不可替身,高成本叶替身明示 | 通过 | 真实链=公共判定核心+真实锁;替身仅 fixture 输入且 engineering_fixture=True 标注 |

## 2. Q2 配额/预注册/叶边界记账:**主体 PASS,一项 P1 回归**

| 核验点 | 结果 | 证据 |
|---|---|---|
| 配额须正整数(0/负/bool 拒),0 额度禁入审计 | 通过 | permit.py 149-160 行;REPRO R2a reproduced=False;钉测试 3 参数化例 |
| max_attempts≠C2_BLOCK_MAX_ATTEMPTS(=5)锁定显式拒 | 通过 | coordinate.py 151-171 行;REPRO R2b(max_attempts=3)reproduced=False |
| block_start_index≠0 锁定显式拒 | 通过 | coordinate.py 172-178 行;REPRO R2c(=100)reproduced=False |
| episode 叶边界预.reserve(1 block=8 episode;超限生成前抛 QProdQuotaExceeded) | 通过 | coordinate.py 288-303 行;钉测试 fake 叶断言 fake 未执行、totals 含 unit_note |
| quota_exceeded 显式账本出口(不透支、不静默截短) | 通过 | **reviewer 探针**(patch 核心 raise QProdQuotaExceeded):raised=QProdQuotaExceeded、marker=true、账本 [start, quota_exceeded] |
| 中断/失败全记账 | **FAIL(P1)** | 见 §5 F1:C8 下非配额失败零记账(marker=false、账本仅 [start]);C7 同探针完整记账 |
| E01 账本单位更正(原行保留+追加 correction) | 通过 | run1 原 3 行未动+追加 48;run2 原 4 行未动+追加 48+48;合计 144≤640;`episode_leaf_calls = (2+2+2)×8=48` 逐坐标对上 |
| 绝不透支 2/2 原生次数 | 通过 | 本轮全部复验零原生;探针均 fake 叶/patch 核心,未触任何生成调用 |

## 3. Q3 reader 核验与早停:**PASS**

| 核验点 | 结果 | 证据 |
|---|---|---|
| 必需成员集合精确覆盖(空/子集/多余拒) | 通过 | aggregate.py 118-130 行;REPRO R3a + 钉测试 |
| qcap 冻结计划存在/digest 公共复算/研究计划绑定/namespace 一致/seal 绑定 | 通过 | aggregate.py 131-168 行;REPRO R3e + 钉测试 |
| audit digest 公共函数复算(伪摘要拒)+ seal↔报告一致 | 通过 | aggregate.py 188-206 行;REPRO R3b |
| attempts seeds 条目数=blocks 且 block 范围 [0,blocks)(缺 validation seeds 拒) | 通过 | aggregate.py 249-265 行;REPRO R3d |
| 事件 block 集合与 seeds 对拍;per-block 事件摘要绑定(换位检出) | 通过 | aggregate.py 303-330 行;REPRO R3c(block 0↔1 换位、多重集/召回不变仍拒) |
| legacy E01 seal 缺 per-block 字段只标记不拒 | 通过 | aggregate.py legacy_binding;E01 复算 4 个 seal 全部 legacy_seal_without_event_binding=true 且通过 |
| early_stop 约束启动(零叶调用拒) | 通过 | coordinate.py `_early_stop_boundary`+551-591 行启动守卫;钉测试 refusal + leaf_calls_total=0 |
| early_stop 约束聚合消费(post_stop_not_consumed 排除+违规留痕;有效 K 不足→不决) | 通过 | aggregate.py 402-470 行;钉测试 valid_count=1、primary.insufficient_coordinates |
| 不把数学门换成有利规则 | 通过 | v4=`_load_v4_module()` 实测加载仓库原件 `/home/cryptorl/projects/crypto_rl/report/r20_design_calc_v4.py`;beyond_negative_margin 仍按有利方向不停(沿用 F1 修复),负结果判据仍为 beyond_positive_margin |

## 4. 独立复验运行记录(全部真实命令与 rc)

| # | 命令(WSL) | 结果 |
|---|---|---|
| V1a | `pytest tests/route_c_stage2_6_1/test_curriculum261_qprod_q123_fixes.py + qprod_{aggregate,context,coordinate,levela,permit,plan}.py + route_c_stage2_6_2/{test_ppo262_qprod_export,test_ppo262e_qualified_input}.py` | **131 passed, RC=0**(junit: tmp_reviewer_q123/junit_reviewer_q123.xml) |
| V1b | `pytest test_curriculum261_r20_design_math_v4.py test_curriculum261_r25_cue_dev_entry.py test_curriculum261_r9_cue_contract.py test_curriculum261_r10_cue_contract.py` | **89 passed, RC=0**(R25/TB/v4 数学与黄金接口未破坏) |
| V2 | 复跑 `repro_q123.py`(输出改至 reviewer 目录)对 C8 部署树 | **REPRODUCED 0/15, RC=0** |
| V3 | 对拍探针:patch `curriculum261_r17_cue_contract._run_cue_contract_audit_core` 注入 RuntimeError / QProdQuotaExceeded;C8 部署树 vs C7(git archive 691bd73a)原件树 | C8:非配额失败 marker=**false**、账本 [start];配额 marker=true、[start, quota_exceeded]。C7:非配额失败 marker=true、[start, **interrupted**] → **P1 实证** |
| V4 | C8 reader 只读复算 E01 run1/run2(aggregate_research+_verify_coordinate) | run1: c01 valid(0.96078…/0.02829…)、c02 missing、primary inconclusive;run2: 双 valid(c02 1.0/0.0)、inconclusive;与 `evidence/E01_RECOMPUTE_C8.json` **runs 完全一致**(程序化比对 True);v4 加载自仓库原件 |
| V5 | 同 repro 脚本对 C7 原件树(691bd73a,git archive+部署独有模块补齐) | **REPRODUCED 15/15, RC=0** → 「先复现后修复」事实独立成立 |
| V6 | E02 端到端链重跑(e02_rerun.sh) | REHEARSE_RC=0、EXPORT_RC=0、ISSUE_AUTH_RC=0、COLDREAD_RC=0(cold_read ok/engineering/bundle r4pb-26382fb1…);formal-scope 拒绝单独脚本复验:输出「授权 scope = 'engineering' != 要求 'formal'(工程许可不能解锁正式入口…)」RC=0 |
| V7 | 主代理回归佐证(未重跑全量):deploy 与 C8 改动文件 sha256 一致 + junit 读取 | 261 v7:tests=2634 failures=0 errors=0 skipped=7(≈2627 passed,12:41+08:00);262 v4:tests=240 failures=0 skipped=0(13:25)——与 EVIDENCE_INDEX 声称一致 |

## 5. 发现详情

### F1(P1)通用失败/中断记账回归
- 位置:`stage2_6_1/src/rl_curriculum/curriculum261_qprod_coordinate.py` 622-648 行;死代码 637-648 行。
- 机理:父提交 691bd73a 第 479 行 `except BaseException as exc:`(写 `_write_interrupted` + 账本 interrupted 行)被替换为 `except QProdQuotaExceeded`,旧处理器体残留在 `raise`(636 行)之后不可达。
- 复现:`/f/trading/tmp_reviewer_q123/v3_probe.sh`(WSL,零生成;patch 核心 raise,走真实 try 块)。C8:raised=RuntimeError、`qprod_coordinate_interrupted.json` 不存在、账本仅 start 行。C7 同探针:标记存在+interrupted 行。
- 影响:真实运行中生成器异常/中断不可归属;中断目录可无痕重入(568-571 行的拒绝依赖标记存在);违反 Q2 全记账与 A04。配额路径本身正确(对照探针通过)。
- 修复:恢复通用处理器——在配额分支后补 `except BaseException as exc:` 写中断标记+interrupted 账本行再 `raise`,删除 637-648 行死代码;补一条非配额失败记账钉测试。

### F2(P2)复现证据标注失实
- 位置:`repair_round_q123/REPRO_Q123.json` 第 3 行;`repro_q123.py` 第 358 行硬编码候选标签;EVIDENCE_INDEX.md「复现」节。
- 事实:提交版= C8 复跑(15 项 reproduced=false)沿用 C7 标签;修复前 15/15 原件被同路径输出(/mnt/f/trading/tmp_qprod2/REPRO_Q123.json)覆盖未入库。
- 佐证:reviewer V5 独立重跑 691bd73a 原件树 15/15——事实成立,但包内证据与索引矛盾,冷读必暴露。
- 修复:拆分保存修复前/C8 两份并按实际候选注入标签;更正 EVIDENCE_INDEX。

## 6. 边界与一致性确认
- 原生 2/2 未透支:全部复验零生成、零 fit、零 optimizer;探针仅 patch/fake 叶。
- 实际复验用仓库原 v4(`report/r20_design_calc_v4.py`,V4 打印路径),未以本地 math 适配器充数(ADDENDUM #4)。
- E01 旧 cap 只读容忍:legacy seal 只标记 legacy_seal_without_event_binding,数值与原交付一致(ADDENDUM #5)。
- 平台不提供的后端元数据:未提供,如实记录,不编造。
- 隔离探针存疑边界已全部落到实际 WSL 依赖复验(V3/V4/V5/V6 可对拍)。
- 工作区:reviewer 复验脚本与输出在 `F:/trading/tmp_reviewer_q123/`(未触仓库工作树;唯一 /tmp/c7tree 为一次性提取)。

## 7. 结论
- **判定:FAIL(工程)**——Q2 的失败/中断记账在 C8 引入 P1 回归(F1),交付证据存在 P2 自洽性缺陷(F2);其余 Q1/Q2/Q3 修复主体、E01 复算、E02 链、R25/TB 接口、v4 数学锚均独立复验通过。
- 主 Agent 修复 F1/F2 后交本 reviewer 复验:F1 复验点=非配额失败探针(V3)在 C8 后必须 marker=true+账本 [start, interrupted],且配额路径行为不变;F2 复验点=两份复现原件+标签与索引一致。
- 最终 CLOSED 仍由 ChatGPT 独立终验;本报告不代签,不把工程结论升级为真实资格/研究授权。
