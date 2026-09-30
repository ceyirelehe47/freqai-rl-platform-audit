# REVIEWER_CONTENT_REPORT_V2 — RouteC_QualificationProducer_Integration_v1 返修轮复验

- 独立评审者:omp 独立 reviewer 会话(与 V1 报告同一 reviewer 线;非实现者)
- 配置模型:zhipu-coding-plan/glm-5.3-flash;运行时后端元数据:未提供(平台未暴露,如实记录)
- 复验快照:最终代码候选 **C7 = cda4e975**(修复 V1 FAIL 项 F1-F4);证据链 **E3=e487a10e / E4=c5066915** 仅证据/回执;本地 HEAD=c5066915
- 代码面边界核验:`git show cda4e975 --stat` = 3 src + 3 tests(aggregate/context/levela + 对应测试),`git diff cda4e975..c5066915` 无任何 src/tests/runner 变更(仅证据原件与回执)→ **V1 未受影响矩阵项的代码身份零变化,可复用**
- 部署树同步独立核对:18/18 文件(11 模块 + 6 qprod 测试 + 262 export 测试)repo 工作树 ↔ /home/cryptorl/projects/crypto_rl sha256 逐一相等
- 方法边界:零原生生成/零 fit/零 optimizer 更新(原生预算保持 2/2);全部核验 = 部署树合成测试 + 只读复算 + 隔离探针(/tmp/rv2_probes;probes/rv2_*.py 与 rv2_*.txt 结果留存);未修改任何被审原件
- 远端:live `git ls-remote origin` = **c50669157b88…** = 本地 HEAD(与交接一致;E4 回执因提交-推送自引用限制只记到 e487a10e,实时远端已核实)

## 判定:**PASS**(V1 FAIL 四项 F1-F4 全部按修复通过条件验证通过;受影响面复验通过;全矩阵复核未发现新缺陷)

---

## 一、四项修复逐项复验(按 V1 报告的修复通过条件)

### F1 早停方向语义 — **修复验证 PASS**
- 代码:`curriculum261_qprod_aggregate.py:295-314` 早停触发条件收敛为 `negative = single["magnitude"] == "beyond_positive_margin"`(统计负结果=recall 显著偏低);`beyond_negative_margin`(recall 偏高,有利)仅记 `entry["favorable_beyond_margin"]=True`,不早停、不标 `statistical_negative`。
- 独立探针复跑(V1 同款探针,C7 部署树代码):
  - `P1a.favorable-coordinate-is-valid :: state=valid recall=0.98636…` PASS
  - `P1b.single-magnitude-is-beyond-negative :: magnitude=beyond_negative_margin delta=-0.03593` PASS
  - `P1c.earlystop-should-not-trigger-on-favorable :: early_stopped_at=None statistical_negative=None` **PASS**(V1 此项 FAIL:`early_stopped_at=c01 statistical_negative=True`)
- 新增测试在案并跑通:`test_favorable_beyond_margin_does_not_early_stop`(同坐标有利跨界断言不早停/不标负/favorable 标记,且反向验证负结果仍正常早停)。
- 原 K02 双模式反例保留并通过:`test_stop_modes_early_stop_vs_collect_all`(deploy 树全绿)。
- 附:collect_all_k 模式下 favorable 标记不写(仅在早停模式分支内记录)——与"标记只服务于早停判定"的设计一致,E01 run2 复算 favorable=[None,None] 与此相符,非缺陷。

### F2 verify-formal-logs 序列核验死门 — **修复验证 PASS**
- 代码:`curriculum261_qprod_levela.py:663-698`:`seq_ok = recorded + ["verify-formal-logs"] == steps`(核验含本步;复核权威 17 步集合实测不含 `fail-closure-rehearsal`,长度数学成立:16+1=17);`seq_ok=False` 时写 FAIL 账本 + `record_terminal(status="failed", verdict="FAIL")` 并返回,不再无条件封 PASS。
- 被审原件(非探针):E02 两变体 C7 复跑后 `qprod_v1/level_a_e2e/{v1_r2_reference,v2_perturbed}/…/artifacts/formal_log_verification.json` 均 `sequence_ok=true` 且 `recorded_including_this_step == expected`(17=17,逐项相等);对应 `level_a_step_ledger.json` 均 `verdict=PASS`(17 步全 ok)——**门真实闭合,证据不再自相矛盾**。
- 复跑绑定:两变体 `qprod_code_freeze.json.code_identity` 四文件 sha256 与 repo C7 工作树逐一相等(context/permit/plan/levela)→ 复跑确在 C7 代码上执行。
- 新增钉测试在案并跑通:`test_rehearsal_happy_path_with_honest_ledger` 内新增 `assert verification["sequence_ok"] is True`(V1 的"恒 False 死门下 PASS 与 false 并存"被永久钉死)。

### F3 技术损坏类别不可达/损坏事件表崩溃 — **修复验证 PASS**
- 代码:`curriculum261_qprod_aggregate.py` 事件表解析失败(:193-201)与 block seed 日志解析失败(:149-155)均捕获 `json.JSONDecodeError/UnicodeDecodeError` → `state=technically_corrupt`;聚合主循环 `corrupt_stop`(:265,:292-293)→ `enough = len(valid)>=planned_k and not corrupt_stop`(:328)→ 主分类 `halted_technically_corrupt`(:331-336)——V1 的死分支成为真实可达语义。
- 独立直探针(rv2_probe_f3halt.py,planned_k=1 的强边界:K 已收齐仍必须停):
  - 有效 c01 + 损坏 c02(seal 成员摘要与损坏字节自洽)→ states=[valid, technically_corrupt],primary=halted_technically_corrupt **PASS**
  - 损坏 seed 日志变体(摘要同步刷新,隔离单一损坏维度)→ technically_corrupt + halted_technically_corrupt **PASS**
  - V1 探针 P2 对照:C6 时 `unhandled JSONDecodeError` 崩溃;C7 同夹具 `no crash but state=technically_corrupt`(该探针为 bug 演示器,两分支恒记 FAIL,消息体即修复证据)
- 新增测试在案并跑通:`test_corrupted_events_table_halts_as_technically_corrupt`。
- 有效路径零回归:run1/run2 只读复算 rc_agg=0 双通过 + 85 项 qprod 测试全绿(见下)。

### F4 旧根零写守卫空转 — **修复验证 PASS**
- 代码:`curriculum261_qprod_context.py:114-142` `protected_old_roots()` 改为**按规范名保护**:包祖先 0..4 各基下 `artifacts/route_c_stage2_6_1_repair{17,18,19}`(**无论目录存在与否**)+ `<base>/trading/packs`(存在时)+ 环境声明的 `CURRICULUM261_R17_DEPLOYED_STATE_ROOT`;`harden_root`(:144-166)realpath 语义拒绝保护根内路径。
- 部署树实测(V1 缺陷的唯一相关环境):
  - `protected_old_roots()` = **15 条非空**(5 基 × 3 规范名;V1 为空列表)
  - 真实冻结根 `/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17`(实测 exists=True)内路径 `harden_root(.../qprod_probe_child, create=False)` **被拒绝**(V1 probe2 中被接受)——P4a/P4b 双双转 PASS
  - env 幽灵根注入(不存在的 `/tmp/rv2_f4_ghost/deploy/artifacts/route_c_stage2_6_1_repair17/state`):进入保护集、其内子路径拒绝 **PASS**;非保护路径正例接受 **PASS**(rv2_probe_f4.py 20/20)
- 单测非空转化:`test_harden_root_rejects_protected_old_roots` 重写为断言保护集非空 + 规范名在集 + 每个根拒绝子路径 + env 注入拒绝(V1 版本遍历空列表空转通过,掩盖缺口)。

## 二、受影响面复验(V1 报告约束)

- **A02(V1 FAIL→F4)**:错层拒绝(P3b)、env 重定向拒(P4c)、缺部署配置拒(P4d)、终态不可重入(P4e)、owner 死不可接管(P4f)、formal_ready 下工程入口拒(P4g)、许可重放/错 SHA/越权 scope/authority 目录外(P3a/P3c/P3d/P3e)全部在 C7 重跑通过;冻结根内路径拒绝由失效转**生效**(F4)。有效沙箱正例不受影响(E02 复跑成功建上下文)。**转 PASS**。
- **K01(V1 PASS 附 F3)**:11 合成坐标复算、少 K 不决、复制事件表两坐标同判 invalid、seal 篡改/汇总替代/namespace 冒充/清单外拒绝(单测+探针)身份未变全绿;损坏数据路径由"未处理崩溃"转"corrupt 分类+停止语义"(F3)。**维持 PASS(缺陷消除)**。
- **K02(V1 PASS 附 F1)**:collect_all_k/early_stop 双模式反例(`test_stop_modes_early_stop_vs_collect_all`)保留通过;有利方向不再误标负结果/误早停(F1);B 不改 A 终态测试在案。**维持 PASS(缺陷消除)**。
- **E02(V1 PASS 附 F2)**:C7 复跑原件逐标记核验(每变体 8/8):①17 步账本 PASS 全 ok ②sequence_ok=true ③expected==recorded_including_this_step ④code_identity==C7 工作树哈希 ⑤导出回执 bindings/checks 齐(checks 全 true)⑥delivery 8 件在案(含 SYNTHETIC_ONLY.md)⑦cold check envelope_load_ok=true ⑧许可恰消费一次+consumption auth 在案;账本执行分层 real=11/fixture_double=5/not_run=1(诚实分层);engineering_fixture=true(SYNTHETIC_ONLY 边界)。我的独立只读复跑:formal scope 双变体拒绝 ✓、engineering 装载+EntrySpec 断言 ✓、两预定 pack D1 rung 可区分 ✓、pack 摘要与 V1 轮同一对预定 pack(e262pk-806f… / e262pk-5138…)一致 ✓。**维持 PASS(矛盾消除)**。

## 三、回归绑定核验与 E01 只读复算

- **full_regression_v6**:record `commit_a_sha=cda4e975…`;counts=**2614/0/0/7**(执行尾行 `2607 passed, 7 skipped` = 2607+7=2614 ✓);run_returncodes=[0,0];ok=true;run_id=r21_20260930_081727(晚于 C7 提交时刻)。**import_surface 321/321 成员 sha256 与当前部署树逐一相等**(本复验独立重算)→ 回归确在 C7 部署状态执行。7 skip 与 v5 逐 id 相等(r12-r16 governance 历史 skip,非本轮新增);2612→2614 的 +2 恰为 F1/F3 两个新测试 ✓。
- **regression_262_v3**:rc=0,`240 passed`(stdout 在案)。
- **部署树 qprod 面测试**:261 树 `-k qprod` 73 passed + 262 树 `-k qprod` 12 passed = **85/85 全绿**(与交接"85 项"精确对账;V1 同口径为 71+12=83,+2=85 ✓)。
- **E01 原生原件完整性**:`git diff 1d905ad2..c5066915` 限定 run1/run2 → run1 **零变化**;run2 **仅** `qprod_aggregate_report.json` 1 行(`aggregated_utc` 22:59:00Z→23:36:57Z,复算经标准 aggregate 命令原位刷新,见观察项 O1);原生数据原件(raw_episodes 64/128 csv、事件表、seed 日志、seal、许可、账本)逐字节未动。原生执行预算 **2/2 未动**,零新增生成/fit/更新。
- **C7 只读复算(run2,独立执行,零写)**:rc_agg=0;stop_mode=collect_all_k;early_stopped_at=None;主分类仍 **inconclusive / degenerate_se_prevents_v4_application**(valid=2/11,c02 SE=0 退化坐标保留,不删样不另立公式);cold_read_reproduces=**true**(primary/valid_count/逐坐标(state,recall@12位) 全等);**deep_equal_modulo_utc=true**(与在案报告除时间戳外逐 JSON 相等)。run1 复算 rc_agg=0 → insufficient_coordinates(valid+missing),与 V1 判读一致。

## 四、全矩阵终判(B01/A01-A04/C01-C03/K01-K02/X01-X04/E01-E03/R01/P01/D01)

复用依据:C7 代码面仅 aggregate/context/levela 三模块(+测试);V1 已验项中受这三模块影响的 A01(17 步序列核验)/A02(根守卫)/K01/K02(聚合语义)/E02(排练链)已全部重验(上文);其余项依赖面(api.py 白名单、permit/plan/coordinate、导出与装载、262 侧、回归执行器、配额账目)字节零变化。

| 项 | V2 判定 | 依据 |
|---|---|---|
| B01 | PASS(复用+核) | C7/E3/E4 未触及 api.py 与 R17 正式 namespace;TB 旧账 6 行末时戳 2026-09-28(零新增) |
| A01 | PASS(重验) | F2 修复后序列核验真实闭合;E02 两变体 17 步 real/fixture_double/not_run 诚实分层 |
| A02 | **PASS(转正)** | F4 守卫生效(部署树 15 根全拒)+ P3/P4 拒绝面 11 项 C7 复跑全过 |
| A03 | PASS(复用) | plan.py 零变化;E02 复跑 qbpl-/qapl- 双 digest 在案 |
| A04 | PASS(复用+核) | permit/coordinate 零变化;E02 复跑许可恰消费一次;journal 在案 |
| C01 | PASS(复用) | coordinate/cue_contract 零变化;E01 原件未动 |
| C02 | PASS(复用) | 同上;core 抽取面零变化 |
| C03 | PASS(复用+核) | run2 复算 p_contract_local≠P0 结构未变(deep_equal_modulo_utc) |
| K01 | PASS(重验) | F3 损坏语义补全;单测/探针全绿 |
| K02 | PASS(重验) | F1 方向语义修复;双模式测试保留通过 |
| X01 | PASS(重验) | E02 复跑六件套+回执 checks 全 true;独立装载通过 |
| X02 | PASS(复用+核) | EN1-EN4 导出拒绝路径 C7 复跑全过(zero bundle) |
| X03 | PASS(复用+核) | v2 preprocessing/fitsource 面零变化;新原件装载=绑定复算通过 |
| X04 | PASS(复用+核) | 两预定 pack 独立装载 + D1 可区分复验 ✓ |
| E01 | PASS(复算) | 原件字节完整(除 O1 时间戳行);C7 复算 rc_agg=0/cold=true/主分类不变 |
| E02 | PASS(重验) | C7 复跑原件 8/8 标记×2;F2 矛盾消除 |
| E03 | PASS(复用+核) | 装载/EntrySpec 断言独立复跑;formal 拒绝双变体复跑 ✓ |
| R01 | PASS(重验) | v6(2614/0/0/7,ok,import_surface 321/321)+ 262_v3(240,rc=0)C7 绑定 |
| P01 | PASS(复用+核) | 无总时限;E01/E02 配额结算未动;原生 2/2;正式面零消费 |
| D01 | PASS(复用) | 决定页未变;ROUND_README 返修轮段补齐回归/E02/E01 复算口径 |
| PK01 | 待条件(同 V1) | RETURN 封包未发生;封包后按 REVIEWER_PROMPT §四 冷读+签回执;本判定不构成 PK01 PASS |

## 五、配额与账目对照(独立复算)

- 原生:run1(6 叶/32 正文/4096 MC,c02 零叶拒绝)+ run2(12 叶/64 正文/8192 MC)= 合计 **18/96/12288 ≤ 640/128/16384;原生运行 2/2**。本轮 reviewer 侧零生成/零 fit/零更新,探针全部合成/只读。
- C7 轮新增动作 = E02/E03 工程 e2e 复跑(夹具替身,零原生)+ 两轮回归(部署树 pytest)+ 只读复算;无新增原生预算项。

## 六、观察项(P3,非阻塞;不影响本判定)

- **O1 E01 run2 聚合报告时间戳行被复算原位刷新**:标准 `aggregate` 命令语义即原位写报告,内容除 `aggregated_utc` 外逐字节相等且 git 历史透明;但 ROUND_README"原生原件不变"表述未披露此 1 行差异。建议:封包前在 ROUND_README 返修轮段补一句披露(或以 1d905ad2 字节还原该行,复算回执另存),使"原件不变"在字节级严格成立。
- **O2 新增单测内一条永假死断言**:`test_harden_root_rejects_protected_old_roots` 中第二个 `harden_root(ghost / "something", …)` 与前一调用同处一个 `pytest.raises` 块,永不可达;且若可达其期望错误(该路径不在 env 根 ghost/state 之内)并不成立,属误导性死代码。建议删除该行(前一行已完整覆盖 env 根内路径拒绝)。
- **O3 push 回执未含 E4 自身推送结果**(提交-推送自引用限制);live `git ls-remote` 已核实远端 HEAD=c5066915,风险闭合,仅记录。

## 结论

**PASS**。F1-F4 全部按 V1 报告的修复通过条件验证通过,受影响面(A02/K01/K02/E02)复验通过,回归绑定与 E01 只读复算与交接口径逐一相符,全矩阵无新缺陷。修复前不得封 RETURN/签 PK01 的限制解除:可进入 RETURN 封包;PK01 仍待封包后冷读(含 CRC/清单精确覆盖/关键源码=C7/最终回归入包/本报告字节入包)。

证据留存:probes/rv2_probe_f4.py、rv2_probe_f3halt.py、rv2_probe_e02b.py、rv2_run_all_output.txt、rv2_f3_e01_e02_results.txt、rv2_e02b_results.txt(V1 探针 rv1_probe*.py 原样保留作对照)。
