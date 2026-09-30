# QProd R5 返修轮证据索引 — C15=1139887e

## 输入身份
- 基线: 封包 HEAD 3d56f5c0 + 内容候选 C14=3d2193e2(R4 PASS, 保持)
- 触发: ChatGPT 第五次 NOT_CLOSED(目标逐字见交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R5_ORIGINAL.md(Downloads "REVIEWER_ADDENDUM (4).md" 06:16)
- 材料事实: 本轮未附 REVIEW.md/probes/final_cases/RESULT.json(如实; 旧 probes 不误用)

## R5 修复(仅 Q1 纯判据, 见 local://reviewer_handoff_r5.md)
派生声明必须与在场子输入/数值影子一致; 委托不可掩盖坏数值;
REPLAY_TOL 交叉断言; 正式报告缺字段 False。

## 复现与修复
- 修前 3/3 洞(C14): REPRO_Q123_ROUND5_PRE_FIX.py(WSL 零生成)
- 修后(C15)同探针 3/3 FAIL(真实子条件/委托否决)

## 验证(C15 字节, 零原生/零生成/零 MC/零 fit/零 optimizer)
- 钉 R5 7+qprod 面 156/156;r8/r9/r10/r17 cue-contract 面 29/29
- **r21 v6 C15: rc=0, 2685 tests/0F/7skip, record_sha256=4dd5df96...,
  collection=2685/static=2199/files=159, verify ok** —
  evidence/regress_v6/full_regression_v6_c15/(r21 既有协议全套)
- C14 原记录(full_regression_v6_c14)保留不改签
- 262 v9 C15: 240 passed RC=0(153.56s) — evidence/regress262/
- E01 只读复算: E01_RECOMPUTE_C15.json(逐值与 R3/R4 一致)
- E02 R5 七步 rc=0(evidence/e02/; R01 要素, 标注非 261 回归)
- 原生 2/2 耗尽维持; 无新增统计门槛; 停止政策未改
