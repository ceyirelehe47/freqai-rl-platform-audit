# 独立复验报告 — RouteC_A2_RuntimeClosure R3 修复轮(对照 REVIEW_REPORT_v1)

 reviewer 委派与模型三记录(同 v1):请求来源=原别名 dsv4.1f 不可用→用户 2026-10-10 授权换用;配置选择器=`cfg://task.agentModelOverrides.reviewer = zhipu-coding-plan/glm-5.3-flash:max`(委派未传 model);实际运行身份=**元数据不可观测**(如实记录)。

- 复验对象:修复候选 Commit A''=`24ddea34f2a32ae08bf1238e95112391c0d84ab4`(tree `9020b844caf3c80fbfbe5a3fd37448c2155a1870`,本人 `git rev-parse 24ddea34^{tree}` 实算一致),证据 HEAD=`da8ffaebcc22bd5e95f60004a3f07ffbafe0fb47`(相对 A'' src/tests/runner 零变化,本人 diff 实证为空)。
- 边界遵守:全程只读被审对象;探针仅写本人目录(`/f/trading/local/rcw_r3_review/rcw_probe3.py` + `/home/cryptorl/tmp_rcw_r3/`:eng_freeze_a2/、prereg_a2.json、gate_refused_a2.json、threeway_rerun 输出等);零签发/零消费/零 launch;未触碰 PIN 分支态。

## ① F-1 修复解决条件核验

| 条件(v1 报告给定) | 结果 |
|---|---|
| 构建器以 qaf_attempt_family(formal_attempt) 参数化文本 | **主体达成**:`build_budget_items(attempt_family=None)` 新增 audit_bank_ns/preplan_smoke_ns/ppo_smoke_ns(None=历史 r17 语义);`build_formal_level_a_plan` 内 fam 驱动 description/smoke_policy/budget_items,`preflight_formal_level_a` 同源传 fam(diff 实读一致) |
| 或显式登记 attempt 实际 namespace | **达成**:`run_scope.attempt_identity`{attempt,audit_bank,preplan_smoke,ppo_smoke,source} 机器可读注册,本人实测四键全等族解析(preplan_audit_bank_qaf_v3/preplan_smoke_qaf_v3/ppo_smoke_qaf_v3) |
| 重新生成 draft + digest 重算 | **达成**:draft==rebuilt 逐字段相等;`research_plan_digest`==`qbpl-cf43299003ae573108401e10b6f5eefbdf4afb2d59d3dd0bbc542d7c1197059e`(本人 P3 部署源真实构建器重算) |
| 文档重绑 | **达成**:CLOSURE/PENDING/COMMANDS 全部重绑 A''/tree/qbpl-cf432990/r17fs-f835a8a2/f19126d1/2990/admission-id `qaf-v3-24ddea34-a2`(逐值比对);F-2 计数勘正(隔离测试 18 项、探针 52 个+勘正注记) |
| 受影响测试复绿 | **达成**:新增 `test_rd06_plan_identity_texts_follow_attempt_family`(断言 desc/policy 无 v1 名、attempt_identity==族、bank/preplan/preflight consumer 随族);`test_payload_diff_identity_only` 更新为身份键集合语义;junit 2990=2983P+7S/0F/0E 中 18 个 runtime_closure 用例全绿;ae50a20c 中间候选 1 失败(钉旧语义差异测试)如实归档 attempt12 |
| **残留** | **未清**:step-14 smoke 三条字符串仍指名 `ppo_smoke_r17`(见发现 F-1R)——与同文档 `attempt_identity.ppo_smoke=ppo_smoke_qaf_v3` 自相矛盾 |

## ② 复验探针(rcw_probe3,2026-10-10 实测)

- T1 PIN@A'':HEAD==24ddea34、分支 route-c-stage2-6-1-repair17、porcelain 干净 ✓
- T2 P3 部署同步:levela.py/budget.py 与 A'' blob **字节级全等**(raw_eq=True;初跑 FAIL 系本人探针 text 模式解码瑕疵,字节级复核更正)✓
- T3 工程隔离 freeze 重跑(本人 out-dir):digest=`r17fs-f835a8a2ea1e3af02cb19eedc4eed38e47b7dcdcd57db3bcb38d149a5838b299`(与证据一致)、missing=[]、head=A''、dev=572;dummy-sha `1111…` 拒 ✓
- T4 计划重算:digest==qbpl-cf432990 ✓;draft==rebuilt ✓;payload 全文无 `ppo_smoke_qaf_v1` ✓;attempt_identity 四键==族 ✓;desc/policy 随族 ✓;audit bank consumer=`generate_fit_bank('preplan_audit_bank_qaf_v3', fit_pairs=2)` ✓;v2↔v3 同 code_identity 深度 diff=**9 个身份承载键**(v1 报告所述 8 键 + `/code_freeze_sha`,后者因 v2 计划绑定旧候选而合理入列;零科学语义键漂移)✓;quota/stop/gate_set 全等 ✓;**残留 stale 串 2 条 consumer+1 条 metering**(F-1R)
- T5 substance 重跑:同根 rc=0、claimed==recomputed==`9020b844`、record sha==`f19126d1…`、counts 2990/0F/0E/7S;错根 rc=2 同理由 ✓
- T6 三方对拍(实现侧原脚本口径,输出重定向本人目录):**698/698、597/597、660/660、mismatches=0** ✓
- T7 preflight 活测:ok=true、root=PIN、head=A'' ✓
- T8 gate:E1 配置实测缺席→fail-closed 拒、one_shot_writes=0 ✓
- T9 旧现场:P1 admission `b465e5f1…`/issued `956178b2…` 未变、P2 env 两件仍 MISSING、P2/D2 自 2026-10-06 起零新文件(mtime 全树扫)、crypto_rl 两同步件与 A'' blob 关系留档(此二文件 A'' 未改,blob 与 85a879a4 期相同)✓

## ③ A'' 证据链抽查(留档件)

- `prefix_probe_24ddea34/`:step1 provenance stored==recomputed r17gtrec-3112e5de;step2 A4/A5/A6 真实工程跑;step3 `ancestry ok=True`、全 binding pass、anchored r17fs-f835a8a2;`audit_step_refused.stderr`=dummy-sha 拒;`r17_code_freeze.json`/`baseline_ancestry.json` 与日志一致 ✓
- `freeze_engineering_P3.json`/`preflight_P3.json`@A''(head=24ddea34,r17fs-f835a8a2,ok=true)✓
- `substance_verify_D3.json`(9020b844 claimed==recomputed,f19126d1,2990)✓;`substance_verify_wrongroot.json` rc=2 ✓
- `regress261_d3/`:record 文件 sha256 实算==`f19126d157f9318ff1166e93fecaa4c9436e20fe7bc3f5c305bb6ed881bae0e9`;summary/junit 实测 2990/0F/0E/7S;18 个 runtime_closure 用例在册 ✓;attempt12(ae50a20c,1F,run r21_20261010_135745)如实归档 ✓
- 三方 `three_way_compare.json` meta 绑定 A'' ✓;`logs_20261010/` 8 件唯一日志名,工程记账升级披露(determinism 前缀共 4 次+全量回归 2 次)如实 ✓
- 中间候选证据(85a879a4/ae50a20c 前缀探针、attempt9-11)留档未删,替代关系如实标注 ✓

## ④ 逐 RD 复验判定

| RD | v1 判定 | v2 复验判定 | 依据 |
|---|---|---|---|
| RD01 | PASS | **PASS** | T9 活测再证保护面未变;披露勘正后计数与实况一致 |
| RD02 | PASS | **PASS** | 本轮 diff 仅 budget/levela 参数化(+47/−11),落点与既有模式一致,无新解析面;14 处解析点结论不受影响 |
| RD03 | PASS | **PASS** | T1/T2/T3@A'' 全绿(r17fs-f835a8a2 复现) |
| RD04 | PASS | **PASS** | 门代码未动;T8 重演 fail-closed;隔离测试 18 项全绿(新增 1 项即 F-1 回归) |
| RD05 | PASS | **PASS** | T5/T7@A'' 全绿;前缀 3 步全绿证据在册 |
| RD06 | FAIL(F-1) | **FAIL(F-1R 残留,范围大幅收窄)** | 主体修复+attempt_identity 注册+文档/测试全部到位;唯 step-14 smoke 三条字符串残留旧名(见 F-1R) |
| RD07 | PASS | **PASS** | A'' 级联重建:2990/record f19126d1/三方 698-597-660 全部本人重测相符;旧候选证据如实归档为中间候选 |
| RD08 | PASS | **PASS** | 8 件唯一日志;工程消耗(4 次 determinism 前缀+2 次全量回归)升级披露如实 |
| RD09 | PASS | **PASS** | 三文档绑定值与 A'' 证据逐值一致;admission-id/命令已更新;无占位 |

## 发现

### F-1R(P2,同 F-1 类残留,范围收窄至 step-14 smoke 三条字符串)
- 位置:plans/A2_qaf_v3/qprod_formal_level_a_draft_plan.json:355(`"consumer": "fit_preprocessor_v2_from_bank_r17('ppo_smoke_r17')+generate_pair"`)、:356(`"metering": "生成 envelope ledger(ppo_smoke_r17 工程面)"`)、:364(`"consumer": "fit_preprocessor_v2_from_bank_r17(ppo_smoke_r17)"`);根=curriculum261_qprod_formal_budget.py step-"smoke" 条目未随 `ppo_smoke_ns` 参数化(修复已建立该变量)。
- 影响:qaf_v3 的第 14 步 smoke 实际 fit 源=ppo_smoke_qaf_v3(family.ppo_smoke,cmd_smoke r17_cli 同源解析;attempt_identity 亦如此注册)——这三条与同文档 attempt_identity 自相矛盾,批准绑定文档中仍有文实不符点;同 F-1 的对账暴露面,范围从"主授权字段+多处 consumer"缩至"3 条次要计量字符串"。
- 复现:本人探针 T4 `STALE_SMOKE_ITEMS`/`RESIDUAL` 输出(/home/cryptorl/tmp_rcw_r3/);draft :355/:356/:364 直读。
- 解决条件:`build_budget_items` 的 step-"smoke" 两条 consumer+一条 metering 改用 `ppo_smoke_ns`(与 preflight 条目同法)→重生成 draft→重算 qbpl digest→重绑三文档与批准建议→受影响测试(身份键集合断言保持)复绿→独立复验。修复后 RD06 即转 PASS,届时可签结论行。

### P3 观察项(不阻塞)
- CLOSURE_REPORT RD06 "budget consumers…全部随族参数化"表述超范围(step-14 三条未随),F-1R 修复后即准确。
- v1 报告 P3 观察项(W1 头部旧"Commit A"命名、runner 界外 6/7 处计数)状态不变,不阻塞。

## 结论

- RD01–RD05、RD07–RD09:在 A'' 复验维持 **PASS**(旧候选绑定证据已全部在 A'' 重建或如实归档为中间候选证据)。
- RD06:**FAIL(F-1R)**——F-1 主体修复合格(参数化+注册+重生成+重绑+测试复绿全部实证),残留仅 step-14 smoke 三条字符串;按 v1 同一标准(授权文本与真实可达消费身份一致)暂不签结论行。
- 『本轮运行依赖与下一尝试工程准备验收通过;等待用户对新身份的执行批准』:**待 F-1R 修复并独立复验后签发**(修复为 2-3 行参数化+既定重绑级联,预计不触及其余 RD 证据)。
