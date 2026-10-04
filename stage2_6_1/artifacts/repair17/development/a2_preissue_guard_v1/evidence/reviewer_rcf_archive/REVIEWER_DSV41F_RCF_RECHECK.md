# RCF-01/02/03 廉价独立复验(dsv4.1f;RouteC_QAFv2_ReviewClosure_v1 修复轮)

复验域(自建,不共用被审实现者目录):WSL `/home/cryptorl/rcf_review/tree`(= ~/projects/crypto_rl 部署面复制 + 仓库候选面覆盖;被审文件逐字节 SAME)。
解释器 `/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python` 3.11.16,PYTHONDONTWRITEBYTECODE=1,env -u PYTHONPATH。
证据目录:`F:/trading/local/rcf_review/`(= `/mnt/f/trading/local/rcf_review/`;sha 见 EVIDENCE_SHA256SUMS.txt)。

## A. R1(候选 1ea6bba8)复验结论 → 2 项 P2(已由 R2/R3 修复)
- RCF-01 路径:PASS(正例/幂等/软链正例;保护域直指·软链·相对·'..'·混合目录 --allow-replace-broken 全部首写前拒绝且字节不变;guard install/verify 硬编码入口同样硬化)。
- RCF-03 连续前缀:PASS(单次真实 operator 执行到步 1 通过 + 步 2 首昂贵科学调用边界恰一次 + 科学零执行 + 链诚实失败于 audit 前置)。
- RCF-02:P2#1 签发日志预检指向 `state_root/r17_admission_issuance.log.jsonl` 幽灵路径(真实生产名=`deploy_root/r17_admission_issued.jsonl`),「已签发而准入文件不在场」状态漏检,实测可再签第二份准入;B5/B6 复现。P2#2 `--leaf-sentinel` 域校验位于 permit/prereg/准入三件一次性写之后,无效调用消耗一次性授权;B8 复现。
- 归档 25/25 与 local 原件逐字节一致;E1–E4 措辞与代码一致(一级证据见 evidence/probe_A.json、probe_B.json、probe_C.json、probe_C2.json、closure_run1.log)。

## B. R2/R3(候选 cff3f5d2;parent f4684c1e→cff3f5d2)复验结论 → PASS
被审面:operator 早期哨兵块重构 + issuance_log 改真实路径 + guard preissue --report-out 硬化(仅 3 文件;CLI 未变,sha 与 R1 同)。

1. 套件(自建树实跑):closure 18 + guard 25 + launch 42 = **85 passed in 110.88s,0 failed/0 error**(evidence/r2_suites.log;含两条新正例 test_real_issuance_log_refused_pre_write、test_leaf_sentinel_without_test_domain_zero_write,以及既有 test_sentinel_refused_outside_test_domain 两断言)。
2. P2#1 复验(evidence/r2_probe_D.json D1):真实 `<deploy>/r17_admission_issued.jsonl` 在场且准入文件缺席 → rc 4「签发日志在场」,one_shot_writes=0,authority 文件集不变,零 permit/prereg/准入,日志未被改写。
   反面对照 D2:幽灵 state 根路径单独在场不再误拒(校验已对准真实产物),流程正常走到叶哨兵并以 audit 前置诚实失败(rc=1)。
3. P2#2 复验(D3):`--leaf-sentinel determinism-matrix` 不带 `--test-domain` → rc 96「首一次性写前拒绝」,one_shot_writes=0,authority 无任何新增文件(连 identity 都没有),零 permit/prereg/准入。
4. 生产根守卫(D4):`--leaf-sentinel`+`--test-domain` 与 `--sentinel-before-chain`+`--test-domain` 落生产根前缀 → 均 rc 96「生产根…禁止哨兵试跑」、零写、部署根目录未创建;`--sentinel-before-chain` 无 `--test-domain` → rc 96 早期拒绝(既有行为保持)。
5. preissue --report-out 硬化(D5):保护域直指 / 相对路径 / 软链指保护域 → 均 rc 3 拒绝、保护域字节不变、报告未落;正例(全新绝对目录)→ 报告按预期写出(失败门 rc 2)。R1 观察项(probe_A2 旧记录 `report_written_into_protected: true`)现为 false。
6. RCF-01 面无回退(evidence/r2_probe_A.json):正例 rc 0/幂等 mtime 不变/verify ok;保护域直指·软链·相对·'..' 拒绝且目标未创建、保护域字节不变;guard install/verify rc 3 零写且保护域无 verify 报告;混合目录 --allow-replace-broken rc 3 三件字节不变;半写拒绝;软链→普通新目录正对照 rc 0。
7. RCF-03 面无回退(evidence/r2_probe_C.json):单次 operator 执行 → permit 恰 1、准入恰 1、issuance 恰 1 行;manifest 步序 provenance-verify(1)→determinism-matrix(1)→audit(1);步 1 verify pass=true stored==recomputed=r17gtrec-3112e5de…;marker science_executed=false;determinism/ 空、audit CLI 未启动;chain ok=false failed_step=audit,operator rc=1,handoff 在场。
8. 生产等价(evidence/r2_probe_C2.json):哨兵 env 未设 与 设非目标值(`audit`)时候选 vs parent(bbcc7a93 CLI):rc/stdout/产物树/失败原因一致(仅变体目录名出现在报文里);仅 env==`determinism-matrix` 走新分支。

## C. 终判
R2/R3 两处 P2 修复与观察项均已独立复现为「首写前拒绝/零写/正例不误拒」,三面(路径、状态矩阵、连续前缀)+ 生产等价 + 85/85 套件通过 → **PASS**,可进入重型回归与终封。
残余观察(非阻断,供主 Agent 决策):`CURRICULUM261_QAF_TEST_LEAF_SENTINEL` 只经 env 直达 CLI,`--leaf-sentinel` 旗标路径受 --test-domain/生产根双守卫,但手工 export 同名 env 的真实运行不会被 operator 白名单拦截(后果=步 2 被兜底截停、链在 audit 前置诚实失败、一次性授权被消耗);是否把该名纳入 `_env_violations` 由主 Agent 判断。
