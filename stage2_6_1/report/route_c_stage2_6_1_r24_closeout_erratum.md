# R24 报告与探针标签勘误(新增说明文件)

说明日期:2026-09-26。本文件为 RouteC_R24_SupervisionEvidence_Closeout_v1
轮新增;不覆盖、不修改其所引用的任何历史报告、索引或运行结果。观察提交
(历史原件所属):`3ab09c479864a608127ba48c76bf1a3856cb2245`。

## 1. 测试数口径

关联原报告:
`stage2_6_1/report/route_c_stage2_6_1_r24_partial_registration_closure.md`

原报告第 6 节把回归总数误写为"2470 passed / 0 failed / 0 errors + 7
skipped"。按该轮原始 `execution.stdout.txt` 与 `summary.json`:

**2463 passed + 7 skipped = 2470 tests;0 failures、0 errors。**

pytest 原输出尾部为 `2463 passed, 7 skipped, 10 warnings in 2365.45s
(0:39:25)`(原件:
`full_regression_20260926_v1/execution.stdout.txt`)。summary 的
aggregate(tests=2470, skipped=7)与之一致;"2470"是收集/执行实例总数,
不是 passed 数。被测候选 `d085590d00c6214c2f33d56a6f861f57e284faea`,
内层 run_id `r21_20260926_065511`。本勘误不修改这些原件,不把 7 个
历史 skip 再加到总数上,也不重新运行测试。

## 2. rejected 变体的标签

关联原索引:
`stage2_6_1/artifacts/repair17/development/r24_partial_registration_closure/probe_v1/index.json`

其中 `executor_rejected` 步的 `verify_regression_evidence` 值写作
`UNEXPECTED-ACCEPT`。该变体的构造是公开注册 API 在写入注册表**之前**
因重名("pytestconfig")抛 ValueError——对象未入册、零钩子安装,从未
参与收集;按任务合同与项目测试
`test_pre_insertion_failure_eligible` 的断言,合法测试树在该真实前置
拒绝后应能通过 full 核验。

因此"接受"本身是预期行为;`UNEXPECTED-ACCEPT` 是探针判定字符串沿用了
负例措辞的标签错误,不是准入绕过,也不是守卫缺陷。本勘误将其解释为
"真实前置拒绝、零安装零参与,核验预期接受"。不改写旧 index、不修探针
代码、不重跑;不为该标签产生新的被测候选。

## 3. 验收边界

以上均为说明性勘误,不改变任何代码或原件字节。R24 注册异常/部分安装的
限定工程修复维持独立审查已接受的结论;C 维持上一轮限定接受。外层监护
原件的回收/归档情况见同轮新增的
`stage2_6_1/report/route_c_stage2_6_1_r24_supervision_recovery.md`。
在 ChatGPT 独立核验之前,本勘误不构成整轮 CLOSED PASS 或新的研究授权。
