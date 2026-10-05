# QAFv2 ReviewClosure RC01–RC08 收口报告(RouteC_QAFv2_ReviewClosure_v1)

日期 2026-10-04 | 候选(分支 B,证实缺陷修复)= `d705c494b031823570a90deeed891bcbe763d1d9` | 前候选 `90b3a44a…`(R1 轮)、`9d735c8c…`(R4)、`513e75e3…`(RC 轮)等(未 amend,保留为祖先)
reviewer 线:dsv4.1f(同线续验)| 出口目标:`A2_RETRY_READY_PENDING_USER_APPROVAL`(ChatGPT 完整终验未签,不代签)

## 结论总表

| RC | 映射 PG | 结论 | 证据层级 |
|---|---|---|---|
| RC01 | PG01/PG12 | **通过(复用+现场)** | 现场只读探针:旧 P/D 四哈希逐字节一致;D2 非激活(config/admission/authority/state 面全 absent,A 根仅前置 provenance+验证报告);qaf_v2 零签发/零消费/零业务。上轮任务内 reviewer 通过与 ChatGPT 终验未完成分开陈述(见 REVIEW_INDEX) |
| RC02 | PG02/PG03 | **通过(复用)** | 固定 Git 源(钉死 de81aba2 对象;sha 9af55175/cde2b72a/r17gtrec-3112e5de)与安装幂等/异物/半写/只读不修复 = 既有 25 测试(12 反例);别名/软链接由 harden_root 真实路径解析拒(test_curriculum261_qprod_context symlink/protected 面,D2 全收集内);check rc≠就绪已按披露处理(下游消费 freshness.fresh 字段,P0 机器断言 fresh=true 为交付前提) |
| RC03 | PG04/PG05 | **通过(复用+补强)** | 两 issuer 硬门(permit qaf_v2 无条件;admission 迭代登记驱动,v1 标签在 v2 部署拒)+ operator execute 首签发前批准↔参数绑定门(gate1 F1;含 plan-digest==tree-digest 重算,不符零写)+ launch 消费许可前漂移重查;控制流图见 CONTROL_FLOW.md |
| RC04 | PG05 | **证实缺陷→已修复→补测通过** | 缺陷:qprod_formal_authority 三个一次性写(init/record-approval/issue-permit)为 check→write TOCTOU,并发双写窗口真实存在(对照 admission issuer 已是 O_EXCL)。修复:三处改原子 O_EXCL create-only,败者按在场分类拒绝(8c160d0a);gate1 复验追加 F1(operator execute 首签发前批准↔参数绑定门,含 plan-digest==tree-digest 重算;9210cd24)与 F2(并发 init 败者有界重读含快速路径,不崩溃;513e75e3)。补测:6 项确定性并发/绑定门测试(go-barrier 包真实 runner CLI):permit/record-approval/admission 恰一写一胜、init 单身份、许可文件完好;**非顺序重入冒充** |
| RC05 | PG06/PG07/PG09 | **通过(连续前缀实测)** | RCF-03:真实 operator execute 单次流程(隔离域)→真实签发链(init→record-approval→issue-permit→prereg→admission 恰一件)→launch→真实链:步 1 provenance-verify 读安装目标 pass=true(stored==recomputed);步 2 determinism-matrix 在**完整排程**下执行其全部真实必需前置(预算门/身份解析)后,恰于首个昂贵科学调用 audit_generator_mutable_state 之前被测试域哨兵截停(marker v2 记录 prerequisites_executed,科学零执行,determinism/ 产物空);链诚实失败于下一前置(audit)。反例:R15 错源首签发前拒;手工 env 哨兵/双旗标/生产根守卫全部首写前拒 |
| RC06 | PG08/PG10 | **通过(新候选全量重证)** | 代码变更(runner)→不沿用旧 record:513e75e3 重新部署 P2/D2(三方对拍 625 全等+18 pyc 分类),D2 全收集新 record(见 §新证据);262 面零变化(api/输入锁/镜像未动)→ 240/240 复用适用(基线同码);清理面适用性:上轮 P0 清理(旧 R17 运行态)后 287 项+同源核验已证,本轮部署脚本内置排除,新域恒干净 |
| RC07 | PG11 | **reviewer 闭环(进行至终审)** | 本轮先内部自测(新测试 6/6+受影响 73/73)→ 委 dsv4.1f 续验(快验→复验修复环→终审→冷读),见包外回执 |
| RC08 | PG12 | **单一待批交接(见 PENDING_APPROVAL_SUMMARY 更新)** | 新身份全值见下;E1–E4 与实际代码核对:execute 自动完成环境白名单/门禁/签发/launch,**不自动执行 E2 安装**(要求已就绪,幂等可复核);E1(配置激活)/E2(prepare)/E3(批准原件构造,用户原文外部输入)为前置手动步;无未定义路径变量 |

## 新证据绑定(分支 B 后)

- Commit A:`d705c494b031823570a90deeed891bcbe763d1d9`(parent=97f81a6d;变更=RCF-01 文件链接边界(O_NOFOLLOW/lexists)/RCF-02 首写前完整同根核验/RCF-03 哨兵移位+预算门根查找接线修复+F1 O_TRUNC+F2 测试真实字段)
- 新计划 digest:`qbpl-212a30ef617b70195128449e316e3d44d2aa9b5138ba9666717025c0282a9523`(真实构建器;与旧 A2 差异=code_freeze_sha/iteration/code_identity 4 文件身份哈希,quota/rules/stop/gate_set 全等——evidence/rc_closure/plan_diff.json)
- D2 新 record:`0b1bd93f10a825d5790253ca177f4f7cbe6075fd975141f5bbf751f2d0b89355`(261 全收集 2963=2956 passed+7 skipped/0F/0E,run r21_20261005_132145,cwd=D2,commit d705c494)+ 同根 substance verify rc=0(r17sub-a2b0b30e7…,tree d9a19212bbea…)+ 错根 rc=2
- 部署:P2/D2 重建;三方对拍 625 全等;保护面(旧 P/D)前后一致

## 源码快照(包内 source_snapshots/,候选 d705c494 git blob 原字节,10 文件含 curriculum261_r17_cli.py)

qaf_v2_operator_entry.py / curriculum261_qaf_provenance_guard.py / qprod_formal_authority.py / r17_admission_issue.py / qprod_formal_level_a_entry.py / curriculum261_qprod_formal_levela.py / curriculum261_r17_workflow.py / curriculum261_r17_cli.py / test_curriculum261_qaf_v2_preissue_guard.py / test_curriculum261_qaf_v2_reviewclosure.py(索引含 blob sha 与部署 CR 投影 sha;全部 @d705c494)

## 保留限制

- RC05 停止边界值(provenance-verify)为测试注入;生产 _chain-bounded 仅接受 qualify——截断机制本体是生产冻结函数,已如实标注。
- check 子命令 rc 不编码 freshness(已披露);交付断言以 freshness.fresh 字段为准。
- 262 复用而非重跑:本轮变更不触 262 面;如终验要求,可按同协议补跑。
