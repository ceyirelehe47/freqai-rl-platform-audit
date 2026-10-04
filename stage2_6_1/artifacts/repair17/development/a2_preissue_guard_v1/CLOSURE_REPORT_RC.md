# QAFv2 ReviewClosure RC01–RC08 收口报告(RouteC_QAFv2_ReviewClosure_v1)

日期 2026-10-04 | 候选(分支 B,证实缺陷修复)= `8c160d0a7320748f2485bdc5d993da355b317663` | 前候选 `efb35552…`(未 amend,保留为祖先)
reviewer 线:dsv4.1f(同线续验)| 出口目标:`A2_RETRY_READY_PENDING_USER_APPROVAL`(ChatGPT 完整终验未签,不代签)

## 结论总表

| RC | 映射 PG | 结论 | 证据层级 |
|---|---|---|---|
| RC01 | PG01/PG12 | **通过(复用+现场)** | 现场只读探针:旧 P/D 四哈希逐字节一致;D2 非激活(config/admission/authority/state 面全 absent,A 根仅前置 provenance+验证报告);qaf_v2 零签发/零消费/零业务。上轮任务内 reviewer 通过与 ChatGPT 终验未完成分开陈述(见 REVIEW_INDEX) |
| RC02 | PG02/PG03 | **通过(复用)** | 固定 Git 源(钉死 de81aba2 对象;sha 9af55175/cde2b72a/r17gtrec-3112e5de)与安装幂等/异物/半写/只读不修复 = 既有 25 测试(12 反例);别名/软链接由 harden_root 真实路径解析拒(test_curriculum261_qprod_context symlink/protected 面,D2 全收集内);check rc≠就绪已按披露处理(下游消费 freshness.fresh 字段,P0 机器断言 fresh=true 为交付前提) |
| RC03 | PG04/PG05 | **通过(复用+补强)** | 两 issuer 硬门(permit qaf_v2 无条件;admission 迭代登记驱动,v1 标签在 v2 部署拒)+ launch 消费许可前漂移重查 = 既有测试;控制流图见 CONTROL_FLOW.md |
| RC04 | PG05 | **证实缺陷→已修复→补测通过** | 缺陷:qprod_formal_authority 三个一次性写(init/record-approval/issue-permit)为 check→write TOCTOU,并发双写窗口真实存在(对照 admission issuer 已是 O_EXCL)。修复:三处改原子 O_EXCL create-only,败者按在场分类拒绝(8c160d0a)。补测:5 项确定性并发测试(go-barrier 包真实 runner CLI):permit/record-approval/admission 恰一写一胜、init 单身份、许可文件完好;**非顺序重入冒充** |
| RC05 | PG06/PG07/PG09 | **通过(新增连续前缀测试)** | 新测试:真实守卫安装→真实守卫签发链(init→record-approval→issue-permit→prereg→admission,隔离域)→admission 闸门→唯一链会话→真实 build_workflow_plan_r17+**生产冻结函数** bound_workflow_plan_r17(停止边界=provenance-verify,测试注入的唯一差异;生产允许边界=qualify/verify-formal-logs)→真实 execute_workflow_chain_r17:步 1 provenance-verify 子进程读安装目标(pass=true,stored==recomputed=r17gtrec-3112e5de…);**下一科学叶 determinism-matrix NOT_RUN**(不在排程/无产物/无 manifest 事件);verify-formal-logs 只读收口在排程。与既有 sentinel 测试(入口→签发→派发边界)拼成全链;v1/v2 职责/seed/两 smoke 分账不回归(既有 25+9 测试) |
| RC06 | PG08/PG10 | **通过(新候选全量重证)** | 代码变更(runner)→不沿用旧 record:8c160d0a 重新部署 P2/D2(三方对拍 624 全等+18 pyc 分类),D2 全收集新 record(见 §新证据);262 面零变化(api/输入锁/镜像未动)→ 240/240 复用适用(基线同码);清理面适用性:上轮 P0 清理(旧 R17 运行态)后 287 项+同源核验已证,本轮部署脚本内置排除,新域恒干净 |
| RC07 | PG11 | **reviewer 闭环(进行至终审)** | 本轮先内部自测(新测试 5/5+受影响 72/72)→ 委 dsv4.1f 续验(快验→终审→冷读),见包外回执 |
| RC08 | PG12 | **单一待批交接(见 PENDING_APPROVAL_SUMMARY 更新)** | 新身份全值见下;E1–E4 与实际代码核对:execute 自动完成 E2/环境/签发/launch;E1(配置激活)与 E3(批准原件构造,用户原文外部输入)为前置手动步;无未定义路径变量 |

## 新证据绑定(分支 B 后)

- Commit A:`8c160d0a7320748f2485bdc5d993da355b317663`(parent=8ffece2b;变更=runner qprod_formal_authority.py 原子化+新测试文件)
- 新计划 digest:`qbpl-4f20253496c7c4552a6283f987e7f95eab82f011dcac6b9024c5d5dde1ac6e47`(真实构建器;与旧 A2 差异=code_freeze_sha/iteration/code_identity 4 文件身份哈希,quota/rules/stop/gate_set 全等——evidence/rc_closure/plan_diff.json)
- D2 新 record:`7b4b2be2af91396d867e2c8af61bddc9f0a672aea7e73b55c92542c7c84077ef`(261 全收集 2942=2935 passed+7 skipped/0F/0E,run r21_20261004_231816,cwd=D2)+ 同根 substance verify rc=0(r17sub-1596cd46…)+ 错根 rc=2
- 部署:P2/D2 重建;三方对拍 624 全等;保护面(旧 P/D)前后一致

## 源码快照(包内 source_snapshots/,候选 8c160d0a git blob 原字节)

qaf_v2_operator_entry.py / curriculum261_qaf_provenance_guard.py / qprod_formal_authority.py / r17_admission_issue.py / qprod_formal_level_a_entry.py / curriculum261_qprod_formal_levela.py / curriculum261_r17_workflow.py / test_curriculum261_qaf_v2_preissue_guard.py / test_curriculum261_qaf_v2_reviewclosure.py(索引含 blob sha 与部署 CR 投影 sha)

## 保留限制

- RC05 停止边界值(provenance-verify)为测试注入;生产 _chain-bounded 仅接受 qualify——截断机制本体是生产冻结函数,已如实标注。
- check 子命令 rc 不编码 freshness(已披露);交付断言以 freshness.fresh 字段为准。
- 262 复用而非重跑:本轮变更不触 262 面;如终验要求,可按同协议补跑。
