# FFAB 后续 A2-R2:签发前防错与新尝试一体化准备 — 待批摘要

任务 RouteC_A2_PreIssueGuard_NewAttempt_v1 | 出口 `A2_RETRY_READY_PENDING_USER_APPROVAL` | 日期 2026-10-04

## 1. 新身份(全部实值,无占位)

| 项 | 值 |
|---|---|
| 新 Commit A | `90b3a44abca514d642d5f6afbf00a3157209f2a5`(已推;祖先链 …→9d735c8c→R5 生产根守卫扩展;RCF-01/02/03+残余观察全闭,无 amend) |
| 尝试 | `qaf_v2`(26 全新 namespace,含 design_qaf_v2_* 显式三名;与 v1 逐名不相交) |
| QProd 迭代 | `qprod_a_formal_v2` |
| 新 A2 计划 digest | `qbpl-136cade5042ad66b9677c022a9290d4498d966a827052eaeac16a0a2a3ab7f6b`(真实构建器;与旧 A2 差异仅身份字段+code_freeze_sha,quota/rules/stop_mode/gate_set 全等;tree digest 1bc17f33d5e54b901818464c34dff5c03406f601) |
| D2 同根 record | sha256 `ff8040fc00bb55326391042bda7c98b3df2aa8d30314d6b2b57bb747e091d69e`(261 全收集 2956=2949 passed+7 skipped/0F/0E,run r21_20261005_065335,cwd=D2,commit 90b3a44a;同根 substance verify rc=0,r17sub-4ed46d7cc1218a1…;错根 rc=2 拒) |
| 262 适用 | 240/240 全绿(api/输入锁/镜像受影响面实跑) |
| 部署映射 | P2=`/home/cryptorl/projects/crypto_rl_qaf_v2`(业务入口);D2=`/home/cryptorl/projects/crypto_rl_formal_a_qaf_v2`(签发根,非激活);三方对拍 625 文件 blob-CR 投影==P2==D2,18 冻结 pyc 单独分类缺席 |

## 2. 旧失败保留

qaf_v1 失败现场与消费账原样(permit/admission 各一,iteration_aborted 463ae45f…);旧 P/D 本轮前后摘要逐字节一致(PROTECTION_UNCHANGED);旧批准不迁移——qaf_v2 需新批准。

## 3. 防错就位(PG02–PG09)

固定 Git 源安装器(钉死 sha 三重)+ 实际目标幂等安装 + 同源 verifier + 新鲜度;两 issuer(admission+permit)首一次性写前硬门(迭代登记驱动,v1 标签不匹配部署登记即拒);launch 消费许可前漂移重查;统一操作员入口(环境白名单/A2 双参数/哨兵仅测试域/重入不重复签发)。R15 错源、缺字段、错配、签发后漂移、错根共 12+ 反例全拒,沙箱真实签发+链步 1 实跑正例全绿(25 项测试)。gate1 reviewer(dsv4.1f)两轮:6 findings+N1/N2 全修复,终判 correct/0.88。

gate2 终审 P0 已修复:D2 未来 A state 根陈旧 R17 运行态(自 P 全量拷贝残留)已清理;受影响面 guard+7 既有(=8 文件)复跑 222 全绿;reviewer 超集 11 文件 287/287 全绿;机器断言 entry check freshness.fresh=true(blocking=[]);同根 substance verify 复跑 rc=0(record 8436a1a7 不变);部署脚本已排除该面(evidence/p0_stateface_fix/)。

## 4. 未授权项

本轮新签发/许可消费/launch/业务生成/fit/PPO = 0;B 与正式教学未批准。数值上限沿用旧 A2(113,176 eps/MC 1e6/bootstrap 7.5e6/PPO 2-512-80 等),仅核对非额度。

## 5. 批准请求(仅一次)

请批准:以 Commit A `90b3a44abca514d642d5f6afbf00a3157209f2a5` / 计划 `qbpl-136cade5042ad66b9677c022a9290d4498d966a827052eaeac16a0a2a3ab7f6b` / qaf_v2 身份,经本轮交付的操作员入口执行**一次** A2(`--stop-after verify-formal-logs --model-update` 全链;命令序列见 RETURN 包 COMMANDS_APPENDIX,E1 配置激活/E2 prepare 前置安装(幂等)/E3 批准原件为手动前置步;E4 execute 自动完成 环境白名单→preissue 门→批准↔参数绑定门→首写前状态/证据全核(含只读同根实质核验)→签发(守卫内建)→一次性 launch→收尾(execute 不自动执行 E2))。批准原文将按 statement digest 绑定进 qfap 原件。
