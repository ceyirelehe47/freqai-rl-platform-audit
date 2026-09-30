# 逐矩阵结论(ACCEPTANCE_MATRIX 对照)

格式:ID — 判定 — 直接证据位置。全部适用候选 C7=cda4e975
(回归/复算绑定);证据相对本 RETURN 根目录。

| ID | 判定 | 证据 |
|---|---|---|
| B01 | PASS | 基线 d910409a→候选链 C1..C7/E1..E6(git log+git_receipts/);TB 旧账逐字节未动(reviewer V1 §B01 核);scope/新旧配额分账(engineering/ROUND_README.md §配额) |
| A01 | PASS | 全链写点出自 ctx 根(levela 模块全文);17 步账本 real/double/NOT_RUN 分层(engineering/level_a_e2e/*/level_a_step_ledger.json);reviewer V1 A01 PASS |
| A02 | PASS(F4 修复后) | 错层/错根/env 重定向/终态重入/owner 接管/authority 外许可全拒(测试 39 项+reviewer 探针 P3/P4);protected_old_roots 按规范名+env 根非空保护,部署树实测拒绝(reviewer V2 复验);旧根事实零写 |
| A03 | PASS | qbpl-/qapl- 双计划;prior_plan_digest+calibration digest 衔接;create-only+digest 复算(测试+run1/run2 计划原件) |
| A04 | PASS | 无许可/清单外零叶调用(refusal_*.json 快照);重复消费/终态重入/中断不重抽;技术损坏(corrupt)与统计失败分类分开(F3 修复+测试) |
| C01 | PASS | run1/run2:manifest→qcap- 锁→真实 generator(namespace→seed 对拍);两坐标 namespace/seed 不同且正确;关锁/rehearsal 冒充(预算不匹配)拒 |
| C02 | PASS | 共享核心抽取;旧 wrapper 黄金向量不变(r8/r9/r10 18 项+v3/v5/v6 全量回归);报告实际 ns/MC(blocks=2/mc=4096 非 1e6;run2 cue_contract_audit.json);正式不降级(锁时拒绝) |
| C03 | PASS | 固定 P0=0.9504...(来源标注);局部 p_contract_local 每坐标独立保留;不等不删(测试);delta/SE/方向/v4 倍率复算(K01 测试逐位对拍) |
| K01 | PASS | 11 合成坐标手工复算(测试);少 K 不决(run1 insufficient 原件);重复/清单外/摘要错/来源错/汇总-only 全拒(测试+reviewer 探针) |
| K02 | PASS(F1 修复后) | 双模式反例;有利跨界不早停(F1 测试);无效/中断不补抽;B 只读 A 终态(测试) |
| X01 | PASS | producer→导出器→load_qualified_input 六件套直达(E02 原件 delivery_*/;零手工补 JSON;receipt 三摘要) |
| X02 | PASS | PASS-only/缺件/FAIL/旧 R2/exposure 未终态/formal 全拒零成功包(12 项 262 测试+export_rejected 原件) |
| X03 | PASS | pack 换源拒;fit_records 换条目拒(摘要自洽仍拒);逐项 multiset;v1 不变(test_v1_preprocessing_inputs_unchanged) |
| X04 | PASS | 双 pack 进入共享准备;pack digest/D1 参数在边界可区分;工程件 formal 拒(E02 原件 formal-scope rejection OK);V2 env reset/step 真实(bank=标注替身) |
| E01 | PASS | run1(c01 成功 6/32/4096;c02 零叶调用被拒——缺陷证据)+run2(双坐标 6+6 叶/32+32 正文/4096+4096 MC);两 run 合计 18/640、96/128、12288/16384;raw_episodes/ df+hidden 归档;事件表/seed 日志/seal/quota ledger 全在 |
| E02 | PASS(F2 修复后) | 步账本 17 步;真实控制步与替身标注;sequence_ok=true 且 PASS 一致(C7 复跑原件);smoke=NOT_RUN |
| E03 | PASS | 新进程冷读(零生成/fit/optimizer);formal 拒;错 scope/身份拒(262 测试+E02 原件) |
| R01 | PASS | full_regression_v6(C7)ok=true 2614/0/0/7(record 绑定 commit);regression_262_v3 240 rc=0;无新增 skip(7 项历史 skip 身份未变);失败中间原件保留 |
| P01 | PASS | 单重型作业(监护记录);配额账本中断不逃账(run1 refused 行);未消费正式数据/许可/训练;部署正式计数=0 |
| D01 | PASS | README 实际命令;决定页两页内(readiness md);TB 不再列待实现 |
| RV01 | PASS | reviewer 两轮实际调用(配置 glm-5.3-flash;运行时后端元数据未提供);FAIL→C7 修复→V2 复验 PASS;probe/报告原件在 reviewer_originals/ |
| PK01 | 待封包冷读 | 本 ZIP 封包后 reviewer 包外终回执(流程最后一环) |

模型记录:配置模型 zhipu-coding-plan/glm-5.3-flash(ping 与两轮
reviewer 调用);运行时后端元数据平台不暴露——未提供。
