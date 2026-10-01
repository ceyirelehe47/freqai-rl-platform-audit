# QProd 返修轮 6(C16=f45958ad)独立内容验收报告(OMP reviewer 独立轮)

- Reviewer: 用户配置 OMP reviewer(zhipu-coding-plan/glm-5.3-flash),独立上下文,未参与实现,未沿用 C14/C15 旧 PASS。
- 日期: 2026-10-02(所有命令实际执行,输出原件留存 `F:/trading/tmp_r6/reviewer/`)
- **结论: R6-V1 FAIL → R7(C17=0663be91)修复复验 PASS**(2026-10-02 增补,见文末 §11;C16 两项发现经独立探针复验已修复,残留一项 P3 非阻塞观察)。

---

## 1. 验收对象与身份

| 项 | 值 | 核验方式 |
|---|---|---|
| 候选 | C16 = f45958ad(R6 修复) | `git show --stat f45958ad`:5 文件(core py +157/-26、r4 测试夹具升级、r6 新钉测试 213 行、REPRO、addendum 原件) |
| 证据 | d147db2f(R6 证据) | r21 三次运行原件 + E01/E02/262v10 + EVIDENCE_INDEX |
| 现场 | HEAD = d147db2f = `origin/route-c-stage2-6-1-repair17`(ls-remote 一致) | `git log --oneline -3` + `git ls-remote` |
| 基线 | c9e28ce3 为 HEAD 祖先;R5 内容 PASS 保持 | `git log` 链 |
| 改动面 | c9e28ce3..HEAD 仅 4 个非证据文件:core py、r4 测试、r6 测试、runner `qprod_r6_r21_regress.sh`(薄封装,既有 r21 协议) | `git diff --name-only c9e28ce3..HEAD`;无政策/停止规则/冻结常量改动 |
| 部署树同步 | `src/rl_curriculum/curriculum261_r17_cue_contract.py` 等 5 文件 sha256 与仓库一致(SYNC-OK) | `sync_check2.sh`(WSL) |

## 2. 独立复现:修前有洞、修后真拒(双态探针)

自行构建报告(与提交版 REPRO 数值不同源:p_contract=0.6、k_mean=3.0、SE=0.02),直调 pure helper,`fixture_mode=False`:

- **C15 字节**(从 `git show 1139887e:...` 提取,sha256=40ef4e16…,替换部署树副本单一文件):C1EX(来源 1/1、派生声明 1/4、差值 0)→ `all_consistent=True`(**洞确认**);N2 recall abs_diff 派生矛盾→True;N3 gk final 层矛盾→True;N9 缺 tolerance→True;N11 fixture 掩盖在场 K 矛盾→True —— 5 洞均在 C15 实测放行。
- **C16 字节**(部署树,与仓库 14fedb8d… 一致):C1EX/N1-N12 全部 `all_consistent=False`,合法对照与 fixture 正例保持 True。
- **提交版 REPRO_R6_PRE_FIX.py** 逐字节复跑:C16 上 c1-c5 全 False + ctl True;C15 上 c1-c5 全 True + ctl True —— 与交接声明一致。

逐门归因(非仅门级 False):C1EX 同时触发 K 来源不一致、K 派生差值矛盾、重算差值 2.75>k_tolerance=0.05 三条独立规则;N3 触发"分层矛盾";N9/N10 触发"缺必需子依据/缺件不得视为 True";N11 在 fixture 下仍由在场数值拒。

## 3. 非特判证明(扩展变体,全部实测)

| 变体 | C16 结果 | 说明 |
|---|---|---|
| N1 仅 validation 侧来源不符(派生自洽 0.5/0.5) | 拒 | 来源对账与声明两侧无关 |
| N2 recall abs_diff≠|rec_m−rec_v| | 拒 | R6 补的 recall 派生差值规则生效 |
| N3 verdict=PASS/pass=True/final.verdict=FAIL(镜像方向) | 拒 | 分层规则双向 |
| N4 tail per_corpus={} + pass=True | 拒 | 缺件≠True 在 tail 层成立 |
| N5 bitwise_ok 在场=False | 拒 | 在场 False 对账 |
| N6 fixture + gk 缺 verdict/pass | pass 门 False(fail-closed),delegated 如实标注 | 保守方向 |
| N7 INDETERMINATE+pass=True | pass 门与 not_indeterminate 双 False | "不是不决≠已经 PASS"保持 |
| N8 k_tolerance 自带值抬高(来源/派生自洽 0.5 差) | **通过(见发现 F2)** | 声明容限无冻结锚 |
| N9 仅缺 tolerance 一个必需键 | 拒 | _OVA_REQ 十键逐一必需 |
| N10 ova 整块缺失、无 fixture | 拒(委托旗标返回 False) | 三控制之"缺件明确 False" |
| N11 fixture + 在场 K 矛盾 | 拒 | 委托不掩盖在场矛盾 |
| N12 fixture + ova 缺两键 | 通过且 fixture_delegated 如实列两键 | 工程 rehearsal 路径诚实标注 |
| digest 段 | 合法报告 digest 重算一致;ova 篡改不改 digest 但被重算层捕获 | digest 与重算互为独立防线 |

三控制确认:纯 helper 无 fixture 路径明确 True(ctl)/明确 False(N5)/缺件(N4/N9/N10)三态齐备。

## 4. 发现(本轮 FAIL 依据)

### F1(P2):K 来源对账可因删除 `dg.<corpus>.aggregate.k_mean` 整体绕过
- 位置:`curriculum261_r17_cue_contract.py:1423`(`if src_k is not None and abs(...)`)。
- 探针(probe_r6_source_absent.py,C16 字节):删除两语料 `aggregate` 子键后,(a) `cue_contract_audit_digest` 不读 aggregate → digest 重算一致(digest-ok=True),消费者 digest 防线不触发;(b) ova 声明 K 链(哪怕与真实来源 3.0 矛盾的 1.0/1.0)→ `all_consistent=True`,零 discrepancy。攻击者抹去唯一交叉来源后,K 链退化为纯自我一致声明,LevelA `cue_audit_pass` 门(present+pass+digest_ok+checks_all_true+pass_recomputed+checks_set_ok+semantics_consistent)逐项皆可满足。
- 这违反本轮自述一般原则(addendum (5) #5"必要依据缺失→拒绝";ovA 侧十键缺失已拒,而交叉来源侧缺失静默跳过,不对称无注释支持)。生产端恒写 aggregate,合法报告不受影响;属反伪造读取门的可绕过缺陷。对比:recall 交叉源 `empirical_recall` 缺失时消费侧 digest KeyError→拒,故该形态仅在 K 侧真实可利用。
- 建议(最小修复,无 fixture 分支内):ova 声明 k_mean_* 在场而 `dg.<corpus>.aggregate.k_mean` 缺失 → 记"K 来源缺件"disc 且 `k_ok=False`(fixture 分支走既有如实委托)。

### F2(P2):K 容限无冻结锚,声明 `k_tolerance` 被按面值接受
- 位置:`curriculum261_r17_cue_contract.py:1441`(重算差值仅对报告自带 `k_tolerance` 比较)。
- 探针 N8:来源 3.0/2.5 真差 0.5、派生自洽、`k_tolerance=1.0` → `all_consistent=True`。生产规则为 `max(3*pooled_se, 0.05)`(plan payload 冻结声明,`k_mean_tolerance_rule`),pooled se 可由在场 `aggregate.k_histogram` 精确重算,但重算未做该漂移检查;而 recall 侧 `tolerance` 已按冻结公式 1e-12 对账(R5)。同一报告内两容限对账强度不一致,违反"与旧 recall 修复共用一致原则,不只比较报告自带的差值和容限"。
- 建议:无 fixture 下按 k_histogram 重算 pooled se → `max(3*se,0.05)` 与声明 `k_tolerance` 对账(超 1e-9 记漂移 disc);K 直方图不受 digest 绑定,删除/改写直方图同 F1 处理(缺件/矛盾拒)。

两发现均:patch 引入、探针实证、有离散修复、非既有行为回归、不涉统计门槛或停止政策变更。修复后按流程做 R6→R7 增量钉测试与受影响面复验即可,无需重开其他已验项。

## 5. 消费路径与合法对照

- 实际判定:`recompute_audit_semantics_from_report` 为 R4-Q1 单一事实源,LevelA 导出门 `cue_audit_pass`(`curriculum261_qprod_levela.py:322-346`)以 `sem["all_consistent"]` 作硬条件——合法对照经该门通过(我的 ctl + N12 均为 all_consistent=True,八门与 checks 全对齐)。
- 现有消费面实测(WSL 部署树,PYTHONDONTWRITEBYTECODE=1,PYTHONPATH=src):R6 钉 11 passed;qprod 261 面 155 passed;262 qprod export 12 passed(**155+12=167,与交接"qprod 面 167/167"精确对账**);r9/r10 cue-contract+cue_eval+r12_global_k 51 passed(交接"29/29"标签无法唯一分解为文件组合,我的覆盖为其超集,全量 2696 亦覆盖,不构成矛盾)。

## 6. r21 三次运行链与 E 盘桥接抽查

1. `r21_20261001_202247` rc=4,9F:失败项逐一核对 junit——r11/r12 R10 marker 缺失×2、r14/r15 allowlist "release repo 不可达"×4、R15 链锚 NoneType×1、runner r15 步链文件缺失×2,全部为 E 盘锚定历史面环境性失败,与 E_DRIVE_BRIDGE_NOTE 归因一致。record 3a5976e1、绑定 commit_a_sha=f45958ad。
2. `r21_20261001_210843` rc=4,1F:仅 `test_t09_owner_death_rejects_new_requests`(JSONDecodeError 读半写文件)。**本人独立复跑**:单测 4 passed、execgov 全文件 22 passed——偶发归因与"22 passed"声明独立证实。record 037a770b。
3. `r21_20261001_215012` rc=0:2696/0F/0E/7skip;junit 实测 tests=2696/failures=0/errors=0/skipped=7;record sha256=96d0b862…(复算一致);`import_surface` 内 `curriculum261_r17_cue_contract.py`=14fedb8d… **与仓库 C16 字节哈希逐位一致(回归确证跑在候选字节上)**;verify 2696/2210/160 与声明一致。
- 桥接:`/mnt/e/trading/freqai-rl-audit` → `/mnt/f/trading/freqai-rl-audit`(readlink 实测),目标仓库 HEAD=d147db2f、origin 同 URL(git 同源);桥接件位于仓外,零代码改动;终轮全量 0F 使单面 120-passed 复跑声明被子集化(该复跑原始 stdout 未单独留存,如实记为轻微证据完整性局限)。

## 7. E01/E02/262/C15 原件核查

- E01:`E01_RECOMPUTE_C16.json` 与 R5 版逐值 identical=True(两 run coords 全等、stats_gate_failed [c01]/[c01,c02] 一致);zero_native=true/read_only=true;原件 `native_smoke_run{1,2}` 最后触碰提交为早期轮(bd6ed858 前),R6 零改动。
- E02:七步(01_authority_init…07_consumption_cold_read)meta 全 rc=0,argv/interpreter 齐,COLLECTION.json 标注 zero_native/zero_fit/zero_optimizer。
- 262 v10:meta 绑定 candidate=f45958ad,stdout 实测 `240 passed` RC=0。
- C15/C14:`repair_round5_notclosed/` 最后触碰为 d32d519a(R5 轮),C16 两提交未触碰;E01 原件零改动;**旧三反例+R4 四反例+合法对照不退化**由 qprod 155 面(含 r2/r3/r4/r5/q123 钉)全绿证实。
- 零新增:两提交无新增原生/MC 研究/fit/optimizer/模型加载;无新增统计门槛;冻结常量与停止政策面未触碰(改动面清单为证);原生 2/2 耗尽维持。

## 8. 22 项矩阵对账

| ID | 判定 | 本轮证据(C16 身份核验后复用 C15 已验项) |
|---|---|---|
| B01 | PASS* | HEAD=remote=d147db2f,c9e28ce3 祖先;R25/TB 面零触碰;在飞未提交变更(已知 receipts typechange)未动 |
| A01/A02/A03/A04 | PASS(复用) | coordinate/permit/plan/context 模块零改动;qprod 面 155 全绿;r21 2696 覆盖 |
| C01/C02/C03 | PASS(复用) | 零改动面;黄金向量/共享 core 未触碰;cue-contract 面 51 全绿 |
| K01 | PASS(复用) | 11 坐标原件未动;r12_global_k 25 用例绿 |
| K02 | PASS(复用) | 停止政策零改动(diff 面) |
| X01-X04 | PASS(复用) | levela/pack/consumer 零改动;262 export 12 绿 |
| E01 | PASS | 原件零改动 + R6 只读复算逐值 identical |
| E02 | PASS | 七步 rc=0 原件 |
| E03 | PASS(复用) | E02 步骤 07 cold-read;消费门零改动 |
| R01 | PASS | r21 v6 C16 正式 record 96d0b862(绑定/计数/哈希实证) |
| P01 | PASS | 三次全量运行串行、失败原件保留、中断不逃账;零正式数据消费 |
| D01 | PASS(复用) | README 零改动(c9e28ce3..HEAD diff 空) |
| RV01 | 本报告 | 独立上下文实际工具执行,正反例+双态复现 |
| PK01 | 本轮不适用 | 按 §0"内容独立 PASS 之后才封包";封包后需新目录冷读+包外回执 |

*PASS(复用)=C15 已验、本轮身份/适用性核验通过且受影响面(r17 cue contract recompute→levela 门)实测不退化。

## 9. 局限(如实)

1. 未重跑 r21 全量(按约,主 Agent 已跑毕;本人做身份/字节/内容抽查:record sha 复算、commit 绑定、import_surface 哈希对拍、junit 解析)。
2. "cue-contract 面 29/29"与"单面复跑 120 passed/22 passed"的原始 stdout 未作为独立文件留存;前者由我的 51 用例超集覆盖,后者由终轮 0F 与本人 t09/execgov 复跑(4+22 passed)覆盖。
3. N6 形态(fixture 下 gk 缺 verdict/pass → pass 门 False 但 delegated 列键)为 fail-closed 保守行为,非缺陷,如实记录。
4. 平台未返回的后端元数据不作伪造声明;本报告全部结论基于实际命令输出。

## 10. 判定

- **FAIL**:F1(K 来源缺件绕过,P2)与 F2(K 容限无冻结锚,P2)为本轮新增 K 链规则内部的同根残留,违反 addendum (5) #2/#5 明示一般原则;按"通过当前反例只是必要条件"及 C15 轮同尺度(同根完整性优先于个案通过),C16 不能以此形态通过。
- 其余全部验证面(五反例逐门真拒、非特判扩展变体 12/12 拒或如实标注、合法对照经实际消费门通过、C14 语义回归恢复、R4/R5 反例不退化、记录链/桥接/E01/E02/262/22 项对账)均通过。
- 修复路径明确且小:无 fixture 分支补"K 来源缺件拒"与"k_tolerance 冻结公式(k_histogram 重算 pooled se)漂移拒",fixture 分支走既有如实委托;修后做增量钉测试+qprod/cue 受影响面+适用全量即可,不重开已验项。


---

## 11. R7 复验增补(2026-10-02,C17=0663be91 + 证据 a3ab2061,已推远端)

主 Agent 针对本报告 F1/F2 修复。以下全部为本 reviewer 独立复验(非沿用主 Agent 自测)。

### 11.1 修复实现核读(0663be91 diff,+102 行 core)
- F1:k_mean 声明在场而 `dg.<corpus>.aggregate.k_mean` 缺件 → 无 fixture 记 "K 来源缺失,不得静默跳过来源对账" disc + `k_ok=False`;fixture 如实委托 `once_vs_attempts.k_mean_*.source_missing` 并跳过该语料。✔ 与建议一致。
- F2:pooled se 由在场 `dg.aggregate.k_histogram` 展开计数按 ddof=1 重算(与生产端同式同库),`k_tol_frozen=max(3*pooled,0.05)`;|声明−冻结|>1e-9 → "K 容差漂移" disc + k_ok=False;重算 K 差值以冻结值为界(声明值仅 fixture 兜底);直方图缺件/结构非法/单样本 → 无 fixture 拒、fixture 委托 `k_tolerance_frozen`。✔ 与建议一致。
- C16 三份运行原件(c16/envfail/flaky)`git diff d147db2f..a3ab2061` 逐字节未动;REPRO_R6_PRE_FIX.py 仅正例夹具补 k_histogram(语义升级,反例变体未动);修前放行原件已归档 `REPRO_R7_HOLES_PRE_FIX.py`。

### 11.2 独立探针复验(probe_r7_indep.py / probe_r7_residual.py,C17 字节,fixture_mode=False)
| 变体 | 结果 |
|---|---|
| ctl 合法(含 k_histogram)/ctl-fixture | True/True |
| R6 五反例(C1EX/C2/C3/C4/C5) | 全拒,归因与 R6 轮一致(不退化) |
| F1 来源缺件(k_mean 删、histogram 留) | 拒("K 来源缺失") |
| F1b aggregate 整删 | 拒(来源缺失+直方图缺件双 disc) |
| F1-fixture 来源缺件 | 通过且 delegated=['…source_missing'](如实) |
| F2 声明容差 1.0(真差 0.5,冻结 0.05) | 拒(容差漂移+冻结界差值双拒) |
| F2b 直方图缺件 / F2c 结构非法 / F2d 单样本 | 全拒 |
| F2e fixture 直方图缺件 | 通过且 delegated=['k_tolerance_frozen'](如实) |
| 残余:自洽伪造 K 子系统(ddof=1 精确容差) | 通过(all_consistent=True)——见 11.4 |

### 11.3 测试面与证据(全部实测)
- 部署树 3 文件 sha256 与仓库一致(SYNC-OK)。
- r6+r7 钉 **15 passed**;qprod 261 面 **159 passed**;262 qprod export **12 passed**(159+12=**171**,与主 Agent "qprod 面 171/171" 精确对账);r9/r10 cue-contract+cue_eval+r12_global_k **51 passed**。
- r21 v6 C17:run 20261001_230626 rc=0,2700/0F/0E/7skip,record sha256 复算=ae607c94…一致,commit_a_sha=0663be91,`import_surface` core 哈希 63da0a87… 与仓库 C17 字节逐位一致,verify 2700/2214/160。
- 262 v11:candidate=0663be91,240 passed RC=0;E01 C17 与 C16/R5 coords 逐值 identical、zero_native/read_only=true;E02 R7 七步 rc=0。

### 11.4 残余观察(P3,非阻塞,如实记录)
1. **K 子系统仍自参考**:aggregate(k_mean/k_histogram)不受 `cue_contract_audit_digest` 绑定,能伪造报告者可整体自洽伪造 K 子系统(保均值、膨胀方差、按 ddof=1 精确报容差)通过重算层——探针 RESIDUAL 实测通过。这是 digest 核心未绑定 aggregate 的**既有缺口**(早于本 patch,非 C17 引入),重算层无封闭手段;建议未来轮把 aggregate 纳入 digest 绑定(涉及 golden vector/生产 digest 语义,属独立设计变更,不在本轮"零改锁"边界内)。
2. fixture 模式下 k_histogram **结构非法**(非缺失)时静默跳过且无 delegated 标注(F2c 无 fixture 已拒;fixture 分支建议补 `k_tolerance_frozen` 委托标注)——极边缘,工程排练面,不影响正式判定路径。

### 11.5 R7 终判
- **PASS**:F1/F2 已按建议语义修复并经 9 个独立变体复验;R6 五反例与全部旧反例不退化;合法对照经实际消费门通过;r21 v6 C17 一次通过且字节绑定确证;262/E01/E02 一致;22 项矩阵结论不变(R01 更新为 C17 record,PK01 仍待封包后冷读)。
- 封包前置条件满足:同意进入 R6+R7 合并增量包(基包 R5 0324c40d)冷读+包外回执流程。


---

## 12. C17b 最小复验增补(2026-10-02,079713cd + 证据 b3397972,已推远端)

P3-2(fixture 下 k_histogram 结构非法静默跳过)修复:fixture 分支补 `once_vs_attempts.k_tolerance_frozen_malformed` 委托标注(+4 行,无 fixture 拒不变)。独立复验:
- 部署树 3 文件 sha256 与仓库一致;diff 逐行核读与描述一致。
- 探针 7 变体:ctl/ctl-fixture True;R6-C1EX 拒;**F2c-fixture → delegated=['k_tolerance_frozen_malformed'] 且通过(不再静默)**;F2c 无 fixture 拒不变;F1-fixture source_missing、F2e k_tolerance_frozen 委托不变。
- qprod 面 171 passed(159+12)。
- r21 v6 C17b:run 20261001_235807 rc=0,2700/0F/7skip,record 26958bf7(sha256 复算一致),commit_a_sha=079713cd,import_surface core 哈希 d995426a… 与仓库 C17b 字节逐位一致;262 v12 candidate=079713cd,240 passed RC=0。
- P3-1(digest 不绑定 aggregate)已登记未来轮,超本轮授权,维持非阻塞观察。

**C17b 终判:PASS。同意封 R6+R7(+P3)合并增量包(基包 R5 0324c40d)并交 reviewer 冷读+包外回执。**
