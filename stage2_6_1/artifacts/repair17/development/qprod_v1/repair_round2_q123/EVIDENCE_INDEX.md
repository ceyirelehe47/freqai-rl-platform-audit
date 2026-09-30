# QProd R2 返修轮证据索引 — C10=a2d546f3

## 输入身份
- 基线: C9=6afa31ac(内容 PASS+冷读 PASS,基包 `972d0c0f…` 保持成立)。
- 本轮触发: ChatGPT 第二次 NOT_CLOSED_ENGINEERING(用户目标文本逐字
  归档于交接件 §0;QProd 本次 REVIEW 原文未单独放置——Downloads 两份
  REVIEW 均为 R25 轮,如实记录)。
- addendum 原文: `REVIEWER_ADDENDUM_R2_ORIGINAL.md`(23:39 版)。

## 复现→修复(14/14 → 0/14)
- `repro_round2.py`:零原生复现探针(Q1×6/Q2×3/Q3×5)。
- `REPRO_Q123_ROUND2.json`:C9 上 14/14 reproduced=true。
- `REPRO_Q123_ROUND2_C10.json`:C10 上 0/14(全部拒绝路径生效)。

## 验证
- 钉测试 `tests/route_c_stage2_6_1/test_curriculum261_qprod_r2_fixes.py`
  16 项(部署树 16/16;仓库树含 E01 白名单身份用例)。
- 全 qprod 面:106/106。
- 261 v9(C10 字节):`2644 passed, 8 skipped, RC=0`(2854.44s);
  junit=`evidence/qprod_regress261_v9_junit.xml`(相对 v8 +16=R2 钉测试)。
- 262 v6(C10 字节):`240 passed, RC=0`(147.05s);
  junit=`evidence/qprod_regress262_v6_junit.xml`。
- E01 只读复算:`evidence/E01_RECOMPUTE_C10.json`——legacy 白名单身份
  容忍保持可读;三个真实坐标 report.pass=False(工程小样本真实负结果)
  新语义如实标 audit_fail 并排除出主分析(run1/run2 valid=0,
  primary=inconclusive)。这是 audit-FAIL/v4-偏差类别区分的落实,
  不是原件破坏。
- E02 R2 全链(R01 要素):`evidence/e02/` 7 步全 rc=0
  (authority-init/issue-permit/rehearse/export/issue-consumption-auth/
  formal-scope 拒绝/consumption cold-read;每步 argv/cwd/interpreter/
  rc/stdout/stderr+COLLECTION.json)。上轮 E02 冷读原件缺失,已如实
  承认并由本轮重跑归档;reviewer 独立 E02 冷读由 reviewer 自行执行。
- 原生预算:`qprod_native_budget.json`(max=2,consumed=2)+
  `check_native_budget` 硬门(e01 runner 启动前强制;缺失文件
  fail closed)。MC/episode 余额未用作新运行授权;本轮零新增原生。

## 上轮 reviewer 原件(引用,不重复打包)
- `F:/trading/tmp_reviewer_q123/`(20 件:探针/输出/junit/coldread)。
- 前轮包:仓库 `.../qprod_v1/return_stage/RouteC_QualificationProducer_
  Integration_v1_RETURN_REPAIR_Q123.zip`(SHA `972d0c0f…`,基包)。

## R2 reviewer V1 FAIL→修复(F1/F2)
- F1(P1):e01 runner 预算 gate heredoc 后未检查退出码(fail-open)——
  已修:GATE_RC 捕获+非零即 exit(fail closed)。实测三场景:
  预算文件缺失 rc=97、2/2 耗尽 rc=97(默认路径真实文件)、
  gate python 崩溃同样 fail closed。reviewer 指出"run2 目录存在"
  只是偶然守卫,现已不依赖。
- F2(P2):复现探针 case8 曾依赖 tc._setup(同候选 fixture 已加
  audit_budgets,前提漂移;旧 C10 复现件 0/14 中 case8 来自混合
  部署态,不可复现)——已修:case8 自带无声明载荷(不依赖 fixture);
  重出 `REPRO_Q123_ROUND2_C11.json`(真实 C10+ 字节 0/14)。
  勘误:REPRO_Q123_ROUND2_C10.json 的 case8 结果(reproduced=false
  且 problems 非空)来自部分同步部署态,已被 C11 件取代;其余 13
  项不受影响。
- qprod 面(含 R2 钉):122 passed/1 skipped(部署树 E01 白名单
  用例 skip 属预期)。
