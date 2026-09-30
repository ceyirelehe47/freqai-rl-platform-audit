# QProd R4 返修轮证据索引 — C14=3d2193e2

## 输入身份
- 基线: 远端 HEAD 2b49a28e + 内容候选 C13=edbdf40a(R3 PASS, 保持)
- 触发: ChatGPT 第四次 NOT_CLOSED(目标逐字见交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R4_ORIGINAL.md(Downloads "REVIEWER_ADDENDUM (3).md" 04:12 版)
- 材料事实: 本轮未附新 QProd REVIEW.md/reference_task(Downloads 两份 REVIEW 为 R25 旧件不误用)

## R4 三组修复(见 local://reviewer_handoff_r4.md 修复映射)
Q1 冻结语义重算(core 单一事实源; 四反例 checks+digest 自洽仍拒; fixture 双重态);
Q3 manifest 条目级贯通+防脱钩(条目 500 vs global/qcap/report/实际 2 拒);
R01 r21 v6 流程真实原件。

## 验证(C14 字节, 零原生/零 MC 研究/零 fit/零 optimizer)
- 钉+qprod 面 149/149(R4 9 新增; R3/R2/q123 断言随 R4 键名同步, 语义不变)
- **r21 v6 C14: rc=0, 2678 tests/0 fail/7 skip, record_sha256=c497f7ce…,
  collection_tests=2678/static=2192/files=158, verify ok**
  — evidence/regress_v6/full_regression_v6_c14/(audit_collection.json+
  lifecycle.jsonl+audit_execution.json+junit+stdout/stderr+record+summary;
  既有 r21_full_collection_regression 协议, 非自造元数据)
- C7 旧原件(20260930, commit cda4e975)已在 repo 原样: ../full_regression_v6/
- 262 v8 C14: 240 passed RC=0(152.86s) — evidence/regress262/
- E01 只读复算: E01_RECOMPUTE_C14.json(R4 校验下 valid+nrv+如实
  inconclusive 保持; 数值与 R3 输出同值, 未重生成)
- E02 R4 七步 rc=0(evidence/e02/; R01 要素, 标注非 261 回归)
- 原生 2/2 耗尽维持; 早停科学定义未改(R3 事前定义保持)
