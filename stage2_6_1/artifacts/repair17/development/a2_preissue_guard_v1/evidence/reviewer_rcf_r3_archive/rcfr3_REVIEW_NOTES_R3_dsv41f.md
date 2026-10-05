# RCF R3 独立快验记录(dsv4.1f 线;reviewer 自建)

对象:候选 `af5c9d86ee5905b350725c5a6649f1d4f1689037`(parent `74a8a42d`),
被审 6 文件 diff 见 `candidate_74a8a42d_to_af5c9d86.diff`。

## 身份绑定(候选字节 = 被验字节)

仓库候选 blob sha256(sha256 of `git show af5c9d86:<path>` 输出)与
WSL 测试域 `/home/cryptorl/tmp_a2r2/selftest` 内实际执行字节一致:

| 文件 | sha256 |
|---|---|
| stage2_6_1/src/rl_curriculum/curriculum261_r17_cli.py | 3047702dda71e0b441cfbfd0adecf35fa4fe2f779f03db4b8607408fd71035ca |
| stage2_6_1/src/rl_curriculum/curriculum261_qaf_provenance_guard.py | 7c4a4ba6df77eae5998b984710d5a26467b4b65b76cfa7f916a7c32d17cbbdfa |
| stage2_6_1/runner/qprod_formal_authority.py | 6818a8318c52f988c96b1df12e16bd95e0273d929c088995b148f8d9a84e7486 |
| stage2_6_1/runner/qaf_v2_operator_entry.py | c19c0914f36fcae5f3658767e05e35ae4b65b80a74b740b51569e0861e495441 |
| tests/.../test_curriculum261_qaf_v2_reviewclosure.py | c1254a53157c7970ff4689011c2bd97c66c98d610fd59d0a8c607d8a72568b72 |
| tests/.../test_curriculum261_qaf_v2_preissue_guard.py | 159397bd14c4f2ebf64aba4d7b69fd535c692d8d359b9955227ec8f1905c4760 |

`git diff --stat 74a8a42d af5c9d86` = 恰好上述 6 文件(+357/-60);
RCF-03 哨兵/预算门/R1-R2 其余面未被本 patch 触及。

## 探针(全部在 /home/cryptorl/tmp_a2r2 自建沙箱;零生产根)

- `probes/probeA_report_writer.py` → `probeA_out.json`
  真实 r17 CLI `provenance-verify` 四态:普通新报告 rc0/pass=True;
  既有链接(指向历史原件)rc96、原件零变化、链接保留;悬空链接
  rc96、目标目录零新增;长报告→短报告 80260→230B、可解析、
  无旧尾;重复普通覆盖 rc0。
- `probes/probeB_prepare_preissue.py` → `probeB_out.json`
  真实 operator `prepare`(→run_same_source_verify→CLI 真实 writer)
  正常 rc0/报告 pass=True/安装二件 wrote;报告链接 rc2 且原件零
  变化、链接保留;悬空 rc2、受害目录空;真实 `preissue` 门
  (同源 verifier 链)同链接 rc2 refusal=same_source_verify、
  失败 report_out 正常落盘 ok=false;绿色 preissue rc0
  report_out ok=true;report_out 自身链接 rc3 ELOOP 拒绝、原件
  零变化;安装成员悬空链接 rc1 且零字节落盘(安装对照不回退)。
- `probes/probeC_direct_issue.py` → `probeC_out.json`
  真实沙箱域(真 git 仓+真执行器 v6 record+钉钉 provenance)+
  真实 `qprod_formal_authority.py issue-permit --attempt qaf_v2`:
  9 反例(缺参/缺record文件/错cwd/缺JUnit/坏JUnit/部署漂移/
  错候选仓/错plan digest/record commit 漂移)全部 rc96 且
  零新 permit / 零 admission / 零签发日志 / 零 state 文件;
  手工同源 verifier 正例 rc0;正例 rc0 恰 1 permit(bound approval
  digest 一致);重复 rc1 不二签。
- `probes/probeD_binding.py` → `probeD_out.json`(残余绑定探针,
  见 findings:批准绑定 commit X,以 X2(空提交同 tree)/X3
  (仅改 r17_admission_issue.py、tree 不同)参数+改绑 record 调用,
  真实 verifier 与 authority 均接受:X2 rc0 写 permit(permit 绑 X),
  X3 通过核验(rc1=已存在)。

## 既有调用面抽样(pytest,selftest 树,py3.11)

- `pytest_subset.log`:18 passed(TestRCFR2DirectPermitPrecheck 5 +
  TestRCFR2VerifierReportProtection 3 + TestRCFR1FileLinkBoundary 3 +
  TestRCFR1PrepermitFullVerify 3 + TestPermitIssueGate 3 +
  TestOperatorEntryWiring::test_post_issuance_drift_* 1)。
- `pytest_operator_matrix.log`:9 passed(TestRCF02StateMatrix +
  TestExecuteBindingGate)。

## 边界

未触碰真实部署根、真实签发/消费/launch/科学计算;仅测试域写
(selftest 树与自建 work 目录);沙箱内共产生 3 件测试 permit
(probeC 两次运行各 1、probeD 1),无真实 admission/launch。
未重跑 47 分钟全量回归(主 Agent 后续执行)。probe C/D 的
record/deploy 为仓库既有测试支撑在合成候选上真实跑出的域内原件。

---

# R3 gate 复验(候选 a96bedea24b3a84a19d30f505a121d8c3d68bba3,parent af5c9d86)

前轮 finding(direct issue-permit 核验参数未绑定批准候选)已修复,按同口径复验通过:

- diff `af5c9d86..a96bedea` = 仅 2 文件:+12 行 authority 绑定门
  (`_cfs != str(approved["code_freeze_sha"]) → rc96 零写`,位于 substance
  核验调用之前)+26 行测试(`test_same_tree_foreign_commit_refused`);
  两文件均不在 stage2_6_2(无同树同步义务)。
- selftest 树两文件 sha256 = 新候选 blob(04170fe3…/1c7b4b1f…);
  guard/CLI/operator 三文件与 af5c9d86 逐字节不变(7c4a4ba6…/3047702d…/
  c19c0914…),故 R2-01 面不受影响。
- `probes/probeD2_binding_gate.py` → `probeD2_out.json`:
  X2(同 tree 空提交)与 X3(仅改 r17_admission_issue.py、tree 不同)均被
  绑定门 rc96 拒绝(语:"核验候选 … 与批准绑定候选 … 不一致(错候选拒绝;
  两入口同一绑定保证)"),零 permit/admission/签发日志/state;X2+不存在
  record 同样是绑定门先拒(证明门在 substance 核验前早退,非
  regression_evidence_missing);批准候选 X 正例 rc0 恰 1 permit
  (binds approval commit+digest),同参重复 rc1,持 permit 后外来候选
  仍 rc96。手工同源 verifier 对 X2/X3 仍 rc0(差异点确为新增门)。
- `probeA_out_a96bedea.json`/`probeB_out_a96bedea.json`:行级与 af5c9d86
  结果全部一致(报告四态、prepare/preissue 链、report_out/安装对照)。
- `probeC_out_a96bedea.json`:直接路径全矩阵复跑一致(9 反例 rc96 零写、
  正例 rc0 恰 1 permit、重复 rc1)。
- pytest:`pytest_subset_a96bedea.log` 19 passed(含新
  test_same_tree_foreign_commit_refused);`pytest_launch_authority_a96bedea.log`
  TestFormalAuthorityCli 2 passed。

结论:绑定门按同口径闭合,R2-01/R2-02 已闭面无回退;可进入重型回归与封包。
