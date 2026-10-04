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

## D. R4(候选 9d735c8c)+ 最终绑定复核 → PASS(非阻断项 3,见 E)
R4 变更面:operator 早期块新增「env `CURRICULUM261_QAF_TEST_LEAF_SENTINEL` 在场而未 `--test-domain` → rc 96 零写」+ 新测试;CLI 未变(sha f28d22fc 同 R1/R2)。
1. 套件(自建树实跑):closure **19 passed in 78.94s**(evidence/r4_closure.log)。
2. E1(probe evidence/r4_probe_E.json):手工 export env + 无 --test-domain → rc 96 专用拒绝语、one_shot_writes=0、authority 零新增、零 permit/准入 ✓。
3. E2:手工 export env + --test-domain(隔离域)→ 正常走全链,步 2 叶哨兵 marker(science_executed=false)、链诚实在 audit 前置失败(rc=1)✓ 未被过拒。
4. E3(残余角,非阻断):手工 export env + --test-domain + **生产根前缀** deploy 根 → 生产根守卫不触发(它只看两旗标),run 正常消耗 permit+准入并进链(marker 在场、failed_step=audit)。触发需同时(a)手抄测试域 env、(b)显式声明 --test-domain、(c)真实生产根;后果 fail-closed(科学零执行)但一次性授权被消耗。一行可扩展(第三条件纳入 env 名)或写入「保留限制」。
5. 最终绑定复核(verify_final_bindings2.py 输出 evidence/final_bindings2.txt):
   - record sha256=a102f967af98…,counts 2956/0F/0E/7S,commit 9d735c8c,run r21_20261005_054959,cwd/deploy_root=D2,protocol full/scope formal ✓
   - plan digest 重算=qbpl-c080e607… ✓;与上一 qaf_v2 计划(1364953b^=513e75e3/qbpl-d10885c1)payload 差异仅 `code_freeze_sha`,去该字段后 digest 相等 ✓(不变量全等)
   - substance_verify_D2:tree 6a81d734 claimed==recomputed、record sha a102f967、2956/0F/0E/7S ✓;错根 preissue 拒绝 zero-write ✓;three_way_compare 625 all_equal+18 pyc 分类 ✓
   - source_snapshots 10/10 == git blob@9d735c8c(含 r17_cli/两测试件)✓;归档 reviewer_rcf_archive INDEX/SUMS 与 local 原件逐字节一致(9 件)✓;reviewer_rc_archive 25/25 ✓
6. 非阻断项:(i) `CLOSURE_REPORT_RC.md:26` 快照标题仍写「候选 513e75e3 git blob 原字节」且未列 r17_cli;(ii) `EVIDENCE_INDEX.md:3` 仍写「最终候选 513e75e3」;(iii) RC08 行「execute 自动完成 E2」与 COMMANDS_APPENDIX E4「不自动执行 E2」冲突;(iv) E3 残余角;(v) R1 最小复现 probe_B(R1) 未随 R2 集入仓归档(仅 local)。

## E. R5(候选 90b3a44a;证据 3bf779cc)+ 封包前最终复核 → PASS(全部非阻断项闭环)
R5 代码面仅 operator 早期块第三条件纳入 env 名(3+/1-,tests/CLI 未变;guard/CLI/test sha 与 R2 同):
1. 自建树实跑 closure **19 passed in 80.54s**(evidence/r5_closure.log)。
2. probe_E(evidence/r5_probe_E.json):E1(手工 env 无 --test-domain)→ rc 96 零写 ✓;E2(手工 env + --test-domain,隔离域)→ 正常走链、步 2 marker science_executed=false、链诚实失败 audit ✓;E3(手工 env + --test-domain + 生产根前缀)→ **rc 96「属生产根清单,禁止哨兵试跑」、零 permit/准入、无 marker/无链** ✓(我方 R1/R4 残余观察闭环)。
3. 面无回退(evidence/r5_probe_D.json):D1 真实签发日志 rc 4 零写;D3 叶旗标无域 rc 96 零写;D4 双旗标+生产根 rc 96 零写且目录未建、--sentinel-before-chain 无域 rc 96;D5 report-out 保护域/相对/软链拒+正例照写。
4. 绑定复核(evidence/r5_bindings.txt):record sha=ff8040fc00bb…(2956=2949P+7S/0F/0E、commit 90b3a44a、run r21_20261005_065335、cwd=D2)✓;plan 重算=qbpl-136cade5…(plan code_freeze_sha=90b3a44a),与 R4 计划 qbpl-c080e607 payload 差异仅 code_freeze_sha、去该字段 digest 相等 ✓;substance tree 1bc17f33 claimed==recomputed + r17sub-4ed46d7c ✓;错根 zero-write 拒绝 ✓;three_way 625 all_equal@90b3a44a(+18 pyc 分类)✓;source_snapshots 10/10 == git blob@90b3a44a(含 r17_cli/两测试件)✓;R4 record 归档 regress261_d2_r5_9d735c8c(a102f967/run 054959)✓。
5. 归档与文档:reviewer_rcf_archive 9 件逐件 INDEX sha 校验通过,`rcf_probe_B_state.py` 与我的 R1 原件逐字节同(sha 3e360821…);CLOSURE_REPORT_RC.md:3/:22/:23 与 EVIDENCE_INDEX.md:3、PENDING_APPROVAL_SUMMARY、COMMANDS_APPENDIX 全绑 90b3a44a/ff8040fc/qbpl-136cade5;快照节标题已改 90b3a44a/10 文件含 r17_cli;RC08 行已改「execute 不自动执行 E2 安装」与附录 E4 一致。
6. 残余(纯 cosmetic,不阻断):CLOSURE_REPORT_RC.md:28 的枚举行仍列 9 个文件名(标题与 INDEX.json 均为 10,含 r17_cli)。
