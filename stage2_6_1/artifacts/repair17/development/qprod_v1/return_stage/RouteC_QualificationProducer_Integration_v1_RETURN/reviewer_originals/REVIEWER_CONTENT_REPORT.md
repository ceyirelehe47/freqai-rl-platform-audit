# REVIEWER_CONTENT_REPORT — RouteC_QualificationProducer_Integration_v1

- 独立评审者:omp 独立 reviewer 会话(非实现者;未委派下一级 reviewer)
- 配置模型:zhipu-coding-plan/glm-5.3-flash;运行时后端元数据:**未提供**(平台未暴露,如实记录)
- 审阅快照:最终代码候选 **C6 = f1bebc37**(E1=1d905ad2/E2=f56437cb 仅证据回执;本地 HEAD=f56437cb;代码面工作树与 f1bebc37 零差异,`git diff f1bebc37 -- <src/runner/tests>` 为空)
- 基线:d910409a(TB E7);diff 面 26 文件 +6043/-21,与交接 §3 一致
- 部署树:/home/cryptorl/projects/crypto_rl(qprod 11 个模块 sha256 与仓库 C6 及回归 import_surface 逐一致)
- 方法边界:零原生生成(原生预算保持 2/2 未动);全部核验为只读复算/部署树合成测试/隔离目录探针(/tmp/rv1_probes + probes/*.py);未修改被审实现与历史原件(冷读前后 sha256 对拍 ORIGINALS-UNCHANGED)

## 判定:**FAIL**(4 项缺陷,均 C6 引入、可复现、本轮可修;修复后按候选复验)

核心链路(上下文/许可/计划/坐标锁/聚合复算/导出/消费)主体实现与证据为真:
1 个拒绝面探针 17+ 项、导出 4 条拒绝路径、formal 拒绝、双 pack 冷读、E01 冷读复算、83 项部署树测试、2612/0/0/7 与 240/0 回归均独立复核通过。
但存在 4 处**漏校验/死门/语义错**,其中 F4 使 A02"旧 R17/R19 状态根零写"守卫在部署树(唯一存在这些根的环境)静默失效,F2 使 E02 证据内部自相矛盾(PASS 封口内含 ok=False 门)。按"遗漏校验/接口错误不得 PASS"判 FAIL。

---

## 缺陷清单(FAIL 项,含修复通过条件)

### F1 [P2] 早停模式把有利方向跨界当作"统计负结果"
- 位置:`stage2_6_1/src/rl_curriculum/curriculum261_qprod_aggregate.py:288-296`
- 矛盾:早停触发条件为 `magnitude in ("beyond_positive_margin","beyond_negative_margin")`。v4 语义(r20_design_calc_v4.py:196-197):beyond_positive_margin=recall 偏低(负结果);beyond_negative_margin=recall **偏高**(有利)。NEXT_GOAL §4/RESEARCH_BOUNDARIES §4 合同="首个**统计负结果**早停"。
- 复现(probes/rv1_probe.py P1a-P1c,2026-09-30):合成坐标 recall=0.98636(delta=-0.0359,CI 上界<-margin)= beyond_negative_margin,early_stop_on_first_negative 下 `early_stopped_at="c01"`、`statistical_negative=True`——有利坐标被当负结果提前终止研究并错误标注。
- 修复通过条件:触发条件仅 `beyond_positive_margin`;新增"有利跨界不早停、不标 statistical_negative"测试;既有 K02 双模式反例不回归。

### F2 [P2] verify-formal-logs 序列核验恒 False(自比时第 17 步尚未记账)且 verdict 不受其制
- 位置:`stage2_6_1/src/rl_curriculum/curriculum261_qprod_levela.py:664-678`
- 矛盾:`recorded` 在 `record("verify-formal-logs")` 之前取账本(16 项),与完整 17 步列表比较 ⇒ `seq_ok` 结构性恒 False;随后无条件写 `verdict:"PASS"` 并 `record_terminal(verdict="PASS")`。
- 证据(被审原件,非探针):`level_a_e2e/v1_r2_reference/.../formal_log_verification.json` 与 `v2_perturbed/...` 均 `sequence_ok:false, expected n=17, recorded n=16, prefix equal=true`,而两变体 `level_a_step_ledger.json` verdict=PASS——门死+证据自相矛盾(执行顺序实际正确,但核验器无法证明,且失败不封口)。
- 修复通过条件:核验含本步(如 `recorded+["verify-formal-logs"]`)或先记账后比较;`seq_ok=False` 走 fail_closure 不封 PASS;复跑 E02 两变体 ok=True/verdict=PASS 一致。

### F3 [P2] 聚合器"技术损坏"类别不可达;损坏事件表直接未处理崩溃
- 位置:`stage2_6_1/src/rl_curriculum/curriculum261_qprod_aggregate.py:187`(调用点)、`55`/`278`(COORDINATE_STATE_CORRUPT 定义与唯一消费点)
- 矛盾:`_verify_coordinate` 只产出 valid/invalid/interrupted/missing;`technically_corrupt` 无任何产生路径 ⇒ `halted_technically_corrupt` 分支(NEXT_GOAL §4"技术损坏即使收齐模式也停止")为死代码。事件表存在但非 JSON 时 `_load_events` 的 `json.JSONDecodeError` 未捕获,整个聚合崩溃而非优雅分类。
- 复现(probes/rv1_probe.py P2):seal 成员摘要与损坏字节自洽的坐标 ⇒ `unhandled JSONDecodeError`。
- 修复通过条件:事件表解析失败 ⇒ 该坐标分类 corrupt 并触发 corrupt_stop 停止语义(保留边界);新增损坏夹具测试;有效坐标路径不回归。

### F4 [P2] 旧根零写守卫在部署树解析为空(harden_root 接受冻结正式根内路径)
- 位置:`stage2_6_1/src/rl_curriculum/curriculum261_qprod_context.py:114-133`(推导 `pkg_dir.parents[2]/[3]`)
- 矛盾:部署树包位于 `<deploy>/src/rl_curriculum`,parents[1]=`<deploy>`(artifacts/ 实际所在),parents[2]=`~/projects`、parents[3]=`/home/cryptorl` 均无 artifacts/ ⇒ `protected_old_roots()` 返回 `[]`。实测(probes/rv1_probe2.py):`harden_root("/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17/qprod_probe_child", create=False)` **被接受**——与 docstring"覆盖部署树/仓库树下 artifacts/route_c_stage2_6_1_repair{17,18,19}"不符。仓库树推导 parents[2]=仓库根(其 artifacts/ 存在但不含 repair17 冻结根;冻结根实为 stage2_6_1/artifacts/repair17 布局)。单测 `test_harden_root_rejects_protected_old_roots` 遍历空列表空转通过,掩盖缺口。
- 实际影响边界:本轮 E01/E02 实写仅落 F: qprod_v1 面与部署树外,冻结根零写事实成立;formal 入口另被 deploy-config fail-closed。但 A02 要求的"错根拒绝/旧状态根零写"守卫在其唯一相关环境默认失效。
- 修复通过条件:推导覆盖实际两树布局(如并入 parents[1]/artifacts 与 parents[2]/stage2_6_1/artifacts 候选);单测注入合成受保护根(env 变量路径)使非空转;部署树下 `protected_old_roots()` 非空且 harden_root 拒绝冻结根内路径(探针复验)。

---

## 逐矩阵项核验(B01/A01-A04/C01-C03/K01-K02/X01-X04/E01-E03/R01/P01/D01)

适用版本均=C6(f1bebc37);时间=2026-09-30。

- **B01 基线与旧面保护 — PASS(附 F4)**:HEAD=f56437cb,C1..E2 链见 `git log`;基线 d910409a。TB 旧账未动:`stage2_6_2/artifacts/eng_training_bridge_v1/ppo262e_quota_ledger.jsonl` 工作树 +3 行均为 2026-09-28(UTC)TB 轮在飞记录(bank_generation_replay/ppo_smoke),本轮无新增;R25/TB 结项未重开(diff 无触及)。api.py diff 对 `CURRICULUM261_R17_FORMAL_NAMESPACES` 仅注释提及,元组逐字节未变(基线/C6 抽取对比)。新 namespace 走显式枚举白名单追加。旧根守卫缺口见 F4(事实零写成立)。
- **A01 Level A 上下文贯通 — PASS**:全链写点均出自 `ctx.artifact_root/state_root`(curriculum261_qprod_levela.py 全文核);`ensure_same` 消费边界防漂移;e2e 产物落 `qprod_level_a_qprod_a_eng_v1/{artifacts,state}`;17 步账本 real/fixture_double/not_run 诚实分层(v1_r2_reference/.../level_a_step_ledger.json,smoke=not_run)。序列核验门缺陷见 F2。
- **A02 A/B 状态与许可隔离 — FAIL→见 F4**:错层拒绝(probe P3b)、env 重定向拒(P4c)、缺部署配置拒(P4d)、formal_ready 下工程入口拒(P4g)、终态不可重入(P4e)、owner 死不可接管(P4f)、authority 目录外许可拒(P3e)均实测通过;冻结根内路径拒绝**失效**(P4a/P4b/probe2)。有效沙箱正例:build_engineering_context 正常建上下文(E01/E02 实跑)。A/B 状态独立:E01 run1/run2 state 分离;B 聚合对 A 终态只读(测试+代码 §level_a_terminal read_only)。
- **A03 冻结与两阶段计划 — PASS**:研究计划 create-only+digest 复算(plan.py `_freeze`);资格计划强制 `prior_plan_digest`+`calibration_artifacts`;Level A 排练先冻 run plan(qbpl- 语义经 freeze_research_plan)再于 calibrate 后冻资格计划(e2e state/ 两 digest 文件在案);同一 digest 不复用(前缀 qbpl-/qapl-/qcap- 分离,坐标审计计划绑 research_plan_digest)。
- **A04 一次性与中断收尾 — PASS**:无许可/清单外/终态重入拒绝零叶调用+refusal_*.json+ledger refused 行(probe P6a:leaf_calls_total=0+refused row);许可一次性消费+重放拒(P3a);中断标记拒重入(单测 test_run_refuses_interrupted_directory_no_autoredraw + probe P6e 在前置层即拒);_write_interrupted 带 generation 快照不自动重抽;E01 run1 缺陷(C4)修复已验证:consume-permit 整批一次,run-coordinate 仅验证+要求消费记录(runner qprod_level_b_entry.py cmd_consume_permit/cmd_run_coordinate)。注:run1 历史原件无 refusal 文件系 C2 时代行为,聚合如实记 c02=missing,当前代码拒绝留证由探针证明。
- **C01 坐标级锁与真实调用 — PASS**:run2 双坐标 ledger start/complete,namespace c01/c02 各 model/validation 四个不同注册 ns;block seed 日志与 derive261_block_seed 对拍(聚合 reader 复算);关锁拒绝=load_coordinate_audit_plan 未锁定即拒+create-only;清单外坐标拒(P6a)。重复 seed 空间拒绝:计划结构校验"P5a 跨坐标重复/P5b model=validation"(probe)。
- **C02 公共算法与报告身份 — PASS**:核心=同一 `_run_cue_contract_audit_core`(抽取自 r17_cue_contract,旧 wrapper report_actual_values=False 写 AUDIT_* 常量,r8/r9/r10 cue 面 39 项测试在 v5 全过=黄金向量未漂移);坐标报告写实际值:run2 c01 报告 `audit_namespaces=cue_qprod_v1_c01_*`,`audit_n_events_mc=4096`(非 1e6),`blocks=2`,`coordinate_execution`(qbpl-/qcap-/engineering_only)在案;工程预算锁 2/4096,formal 必须 500/1e6,降级尝试拒(probe P6c)。
- **C03 局部锚与固定主锚分离 — PASS**:run2 seal 内 `p_contract_local=0.9503774480932101` ≠ P0=0.950431552876822,坐标保留 valid;聚合 anchor 块两锚分列;测试 test_local_anchor_not_equal_p0_is_not_a_deletion_reason;delta/SE 主分析用固定 P0 复算(probe P1 数值对拍)。
- **K01 K 聚合直接证据 — PASS(附 F3)**:11 合成坐标全量复算测试通过(83 项含);少 K 不决(run1 insufficient_coordinates 原件、run2 degenerate_se 原件);复制事件表=两坐标同判 invalid(单测);seal 摘要篡改/汇总替代/namespace 冒充/清单外均拒(单测+probe)。损坏数据路径缺陷见 F3。
- **K02 A/B 停止分层 — PASS(附 F1)**:collect_all_k 与 early_stop 双模式反例单测通过(负结果继续收齐/首个负结果早停,statistical_negative 如实);中断/无效不补抽;B 不改 A 终态(test_level_b_aggregation_does_not_touch_level_a)。早停方向语义缺陷见 F1。
- **X01 真实生产导出接口 — PASS**:公共 raw 判定(judge_qualification_gates 实算)→导出器复算比对→六件套;e2e 两变体 delivery 齐备(qprod_export_receipt.json 绑定三摘要);零手工修补(E02 脚本链自动化,我的独立冷读复跑通过)。
- **X02 未成立资格拒绝 — PASS**:probe4 四条:formal scope 拒、pack 篡改拒(实算 FAIL≠PASS)、缺 raw 拒、PASS 字符串对失败证据拒;全部零六件套(export_rejected.json 唯一产物)。
- **X03 pack 与 fit 来源完整 — PASS**:preprocessing v2(fit_records+source_kind)与 envelope fit manifest multiset 逐项对应+namespace 一致(代码 §47);v1 表示不变不放宽(禁混用 v1 字段);bundle hash 绑定计划;load_qualified_input 授权三摘要绑定+binding_digest 复算(冷读通过=合法路径工作)。
- **X04 消费与授权不串用 — PASS**:两套预定 pack 差异 6 字段(D1 rung,pack digest e262pk-806f… vs e262pk-5138…)经同一 load_qualified_input→prepare_smoke_inputs→V2 env reset/step 边界(独立复跑 rc=0 ×2);formal scope 双变体独立拒绝(空 formal admission 注册表 fail-closed);授权锚由隔离 authority 外部签发(qprod_eng_authority.py,src 无签发函数)。
- **E01 受限原生坐标正例 — PASS**:run1(c01 完整/c02 拒)+run2(双坐标完整)原件在案;ledger 叶调用分相记账(once/attempts/bitwise_replay=2/2/2×每坐标);raw_episodes/*.csv run1=64、run2=128(逐 rung/side df+hidden);事件表+seed 日志在案;两 run 合计 18 叶/96 正文/12288 MC ≤ 640/128/16384(SCOPE_AND_BUDGET §3);原生执行 2/2,未换坐标/参数择优。冷读复现 true 且 ORIGINALS-UNCHANGED。
- **E02 工程路径分层证明 — PASS(附 F2)**:Level A 公共锁/判定/导出真实调用;高成本替身位置逐步明示(步账本 execution 列+note);smoke=not_run 不假写;bank=标注夹具替身。序列核验门缺陷见 F2(执行顺序本身经 prefix-equal 证明正确)。
- **E03 导出冷读与篡改 — PASS**:新进程 load→EntrySpec→冻结 V2 env reset 4 步(独立复跑);零生成/零 fit/零 optimizer;错 scope(formal)与工程许可边界拒绝。
- **R01 最终候选适用回归 — PASS**:full_regression_v5 summary ok=true 2612/0/0/7,commit_a_sha=f1bebc37,import_surface 与部署树逐哈希一致;qprod 收集 71 项(70+C5 补 1)全过;7 skip 全部为 r12-r16 governance 分支上下文历史 skip(TB 基线 2541/7 同源,非本轮新增;新测试文件零 skip/xfail 标记);regression_262_v2 240/0/0/0 rc=0。测试计数对账:2541+71=2612 ✓。
- **P01 运行纪律 — PASS**:无总时限;E01/E02 单作业串行;配额动作前 start/完成 complete/拒绝 refused 全结算;配额与 SCOPE_AND_BUDGET §3 对照全 ≤ 上限;TB 旧账未动(见 B01);正式数据/许可/训练零消费(部署 formal 注册表空,formal 装载恒拒)。
- **D01 真实可执行下一出口 — PASS**:report/route_c_stage2_6_1_qprod_v1_readiness.md ≤2 页,三分(实现就绪/待批/NOT_RUN)+每步预算+失败出口+待决项;命令见 ROUND_README/RETURN README;未把 TB 旧项列为待实现。轻微:决定页头部标"候选 C1(e956c61a)"为撰写时点,最终候选 C6 以 ROUND_README 候选链为准(建议封包时更新,非阻塞)。
- **RV01 独立 reviewer 全矩阵 — 本报告**:真实独立 omp 会话,配置 zhipu-coding-plan/glm-5.3-flash;正反例=部署树 83 项测试+探针 17 项拒绝面+4 条导出拒绝+2×冷读+4 缺陷复现;原生预算 2/2 未动,零新增生成。
- **PK01 当前最终包齐备 — 待条件**:本轮最终 RETURN ZIP 尚未封包(合同时序=内容通过后封 RETURN);封包后须按 REVIEWER_PROMPT §四 冷读(CRC/清单精确覆盖/关键源码=C6/最终回归入包/本报告字节入包)并签包外回执;本判定不构成 PK01 PASS。

## 配额与账目对照(独立复算)
- E01:run1 6 叶/32 正文/4096 MC(c01)+c02 零叶拒绝;run2 12 叶/64 正文/8192 MC。合计 18/96/12288,对账=交接 §6;上限 640/128/16384/2 次原生,未超。
- MC 实际=4096/坐标(报告与 ledger complete 行一致),未冒充 1e6。
- 本轮 reviewer 侧:零生成、零 fit、零更新;部署树 pytest 83 项+探针均为合成/只读。

## 结论
FAIL(4 项 P2,修复条件见上)。修复须形成新候选并做适用回归(261/262);受影响面(A02/F4、E02/F2、K01/F3、K02/F1)由我按上述探针复验,其余项身份未变可复用。修复前不得封 RETURN/签 PK01。
