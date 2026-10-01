# QProd R8 返修轮证据索引 — C18=cec19ae5

## 输入身份
- 基线: C17b=079713cd+证据 b3397972+封包 044a0307(R6/R7 轮 reviewer V1-V3
  PASS+冷读 PASS 保持);核现场 HEAD=remote=044a0307 未前进
- 触发: ChatGPT 第七次 NOT_CLOSED(R6/R7 合并包终验后 Q1 限定返修)
- addendum 原文: REVIEWER_ADDENDUM_R8_ORIGINAL.md(Downloads "(6).md")
- 材料事实: 本轮 Downloads 仅 addendum(6);REVIEW.md/(1).md 为 09-29 R25
  旧件未误用;原 22 项矩阵在 goal_incoming 原包

## R8 修复(仅 Q1 同根收口;digest 域/黄金向量不变;P3 仍未来轮)
- K 输入闭合: histogram 频数非负整数、Σ频数==n_events(生产端每 unique
  event 恰计一次)、加权均值==k_mean(均值/方差共用同一已验支撑);
  {4:110} 声明均值 1/{1:109} 对 110/负频数全拒;键序重排无关
- 在场非法≠未提供: 结构/频数非法 histogram 即使 fixture 在场也不得委托
  为 True(R7b 的 k_tolerance_frozen_malformed 委托撤销);缺件(未提供)
  fixture 仍委托;合法手工输入双模式通过
- gk 子门: graph_integrity_ok=False 与 PASS 并存拒(生产 fail-closed 早退
  规则);无 fixture PASS 缺 final 拒(生产端 PASS 必经 tier1/tier2);
  FAIL 早退无 final 不加拒
- tail 语料覆盖: 预期语料集合=direct_generator 上下文,不由 per_corpus
  自身键集合自列;缺整份语料无 fixture 拒/fixture 委托

## 复现与修复(WSL 零生成;直调 pure helper 记录 fixture_mode)
- 修前 7/7 洞(C17b 字节): REPRO_R8_PRE_FIX.py(h1 均值矛盾/h2 总量矛盾/
  h3 负频数/h4 gk integrity/h5 gk 缺 final/h6 tail 缺语料/h7 fixture 非法)
- 修后(C18)同探针 7/7 拒;三正控制(无 fixture 合法/fixture 合法/双键
  键序重排+冻结容差同步)全过

## 验证(C18 字节)
- 钉 R8 12;qprod 面 182/182;r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C18: run 20261002_013343 rc=0, 2711/0F/7skip, record f9e44621,
  verify 2711/2225/161(一次通过)— evidence/regress_v6/full_regression_v6_c18/
- 262 v13 C18: 240 RC=0 — evidence/regress262/regress262_v13_c18
- E01 只读复算: E01_RECOMPUTE_C18.json(coords 与 R5-R7 identical);
  E02 R8 七步 rc=0(evidence/e02/)
- C17b/C17/C16/C15 记录均不改写;原生 2/2 耗尽维持;零新增原生/MC 研究/
  fit/optimizer/模型加载
