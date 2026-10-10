# 最终复验报告 — RouteC_A2_RuntimeClosure R3 修复轮 F-1R(终审)

 reviewer 委派与模型三记录(同 v1/v2):原别名 dsv4.1f 不可用→用户 2026-10-10 授权换用→配置选择器 `zhipu-coding-plan/glm-5.3-flash:max`(委派未传 model)→实际运行身份=**元数据不可观测**(如实记录)。

- 终审对象:最终候选 Commit A3=`0f494d27bad2ed0de6876ff32f4cb7d656a19c98`(tree `7a2fecbbea921181562720b07e5b87ca6c4e5f7a`,本人实算一致),证据 HEAD=`d8450b52…`。24ddea34→0f494d27 的 src/tests/runner delta **仅** `curriculum261_qprod_formal_budget.py` 3 行(step-smoke 两条 consumer+一条 metering 改用 `ppo_smoke_ns`)——恰为 F-1R 给定的修复面,无越权改动。
- 探针留档:`/f/trading/local/rcw_r3_review/rcw_probe4.py` + `/home/cryptorl/tmp_rcw_r3/`(eng_freeze_a3/、prereg_a3.json、gate_refused_a3.json、threeway_rerun 输出);全程只读被审对象,零签发/零消费/零 launch。

## ① F-1R 解决条件核验(逐条)
1. 三条字符串参数化:**达成**——draft 原残留处现为 `fit_preprocessor_v2_from_bank_r17('ppo_smoke_qaf_v3')+generate_pair` / `生成 envelope ledger(ppo_smoke_qaf_v3 工程面)` / `fit_preprocessor_v2_from_bank_r17(ppo_smoke_qaf_v3)`(本人 P3 部署源重建 payload 直读)。
2. 全 payload 扫查:**本人独立复扫**(正则 `[a-z0-9_]*_r17\b|qaf_v[0-9]\b` 于 JSON 全文)= **零 namespace 残留**;所余 `_r17` 全为函数符号(`run_ppo_smoke_r17` 等,链内真实函数名,合法)。
3. 重生成+digest 重算:**达成**——draft==rebuilt 逐字段相等;`research_plan_digest`==`qbpl-c2dd9bb802ca890cc6aa2ef2b9ae4ffbb8f5f1788ee7e87dd7854816aabe8a36`(本人重算)。
4. 文档重绑:**达成**——CLOSURE/PENDING/COMMANDS/DECISION_SUMMARY 四文档绑定 A3 终值(A/tree/qbpl-c2dd9bb8/r17fs-5f36c3ca/2e9fccfb/2990/admission-id `qaf-v3-0f494d27-a2`;批准建议文本内 plan digest 已更新,逐值比对)。
5. 受影响测试复绿:**达成**——junit 2990=2983P+7S/0F/0E(18 个 runtime_closure 用例全绿;身份键集合断言语义在 A3 下成立);attempt12/13 如实归档(13=24ddea34 绿被替代)。

## ② A3 活体复验(rcw_probe4,2026-10-10;20 PASS/0 FAIL)
- PIN:branch route-c-stage2-6-1-repair17、HEAD==A3、porcelain 干净 ✓;P3 部署 budget.py 与 A3 blob 字节全等 ✓
- 工程隔离 freeze 重跑(本人 out-dir):`r17fs-5f36c3ca11d63bd6fee1f7ae2d5b6e5234331b23a66c2d14c22f0c174c46a8cd`、missing=[]、head=A3 ✓;dummy-sha 拒 ✓
- 计划:digest==qbpl-c2dd9bb8 ✓;attempt_identity 四键==族 ✓;v2↔v3 深度 diff=9 个身份承载键、零科学语义漂移 ✓;quota/stop/gate_set 全等 ✓
- substance:同根 rc=0(7a2fecbb claimed==recomputed;record==`2e9fccfb14ab9c67992a1031302b690d2af28c6c56f8c0d05d412fb2ce4d5548`,本人对 record 文件实算一致;2990)/错根 rc=2 ✓
- 三方对拍(原脚本口径):698/698、597/597、660/660、mismatches=0 ✓
- preflight ok@A3;E1 缺席 gate fail-closed(one_shot_writes=0)✓;旧 P admission 未变、P2 env 两件仍缺 ✓

## ③ A3 证据链抽查(留档件)
`prefix_probe_0f494d27/`(step1 stored==recomputed、step2 A4/A5/A6、step3 anchored r17fs-5f36c3ca、ancestry ok=True、audit_step_refused=dummy-sha 拒)、`freeze_engineering_P3.json`/`preflight_P3.json`@A3、`substance_verify_D3.json`(7a2fecbb/2e9fccfb/2990)+wrongroot rc2、`regress261_d3/`(run r21_20261010_160557;record 文件 sha 实算==2e9fccfb;junit 2990/0F/0E/7S)、`three_way_compare.json` meta 绑定 A3、`logs_20261010/` 含 part10 唯一日志、attempt13 归档——全部与文档绑定值一致 ✓

## ④ 逐 RD 终判
| RD | v2 | 终判 | 依据 |
|---|---|---|---|
| RD01 | PASS | **PASS** | U8 活测+披露勘正在案 |
| RD02 | PASS | **PASS** | A3 delta 仅 3 行参数化,14 处解析点结论不变 |
| RD03 | PASS | **PASS** | U1/U2/U3@A3 全绿(r17fs-5f36c3ca 复现) |
| RD04 | PASS | **PASS** | 门未动;U7 fail-closed 重演;18 项测试全绿 |
| RD05 | PASS | **PASS** | U5/U7@A3 全绿;前缀 3 步全绿证据在册 |
| RD06 | FAIL(F-1R) | **PASS** | F-1R 三条已清;全 payload 零 namespace 残留;attempt_identity==族;diff=纯身份键;digest/文档/测试全部重绑复绿 |
| RD07 | PASS | **PASS** | record f19126d1→2e9fccfb 级联重建,本人实算相符;三方全等 |
| RD08 | PASS | **PASS** | 日志唯一性+工程消耗披露如实(含 part10) |
| RD09 | PASS | **PASS** | 四文档绑定值与 A3 证据逐值一致;无占位;出口=待批 |

## 结论
**本轮运行依赖与下一尝试工程准备验收通过;等待用户对新身份的执行批准。**

依据:RD01–RD09 全部 PASS;最终身份绑定 Commit A3=`0f494d27bad2ed0de6876ff32f4cb7d656a19c98`/tree `7a2fecbb…`/计划 `qbpl-c2dd9bb8…`/record `2e9fccfb…`(2990=2983P+7S/0F/0E)/admission-id `qaf-v3-0f494d27-a2`,全部经本人独立实算或重演。本结论仅为**运行依赖与工程准备**验收,不构成对 A2 执行结果、Level A/Level B/教学或任何未来资格的判定;真实执行仍待用户按 DECISION_SUMMARY/COMMANDS_APPENDIX 完成 E1–E3 后由 operator 发起,E4 首步 preissue 硬门与全部 fail-closed 路径已独立验证在位。不代签 ChatGPT/CLOSED PASS;未签发/未消费/未 launch。
