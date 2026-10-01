# RouteC_QualificationProducer_Integration_v1 R8 返修轮增量交付

## 基包(不重复打包)
- R6 增量包 = RouteC_..._RETURN_REPAIR_R6.zip(SHA-256 ad48db11...,
  内容候选链 C16→C17→C17b);链条 R5(0324c40d)→R4(a8630ac9)→
  R3(21f89291)→R2(846495db)→C9(972d0c0f)。本包仅含 R8 新增源码/
  证据/审查原件。

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 候选链: 044a0307(R6 封包基线)→C18=cec19ae5(R8 修复, reviewer
  内容 PASS 对象)→e4553c88(证据)→23355a7d(P2/P3 处置, src/tests
  零改动);封包 HEAD 23355a7d
- 触发: ChatGPT 第七次 NOT_CLOSED(R6/R7 合并包终验后 Q1 限定返修;
  目标逐字在交接件 §0;本轮 Downloads 仅 addendum(6), REVIEW.md/
  (1).md 为 09-29 R25 旧件未误用;目标提到的 RESULT/README_REPLAY
  在 Downloads 无对应新件,如实说明)

## R8 修复(仅 Q1 同根收口;digest 域/黄金向量/研究政策不变)
- K 输入闭合: histogram 频数非负整数、Σ频数==aggregate.n_events
  (生产端每 unique event 恰计一次)、加权均值==aggregate.k_mean(均值
  /方差共用同一已验支撑);{4:110} 声明均值 1/{1:109} 对 110/负频数/
  小数频数全拒;键序重排无关
- 在场非法≠未提供: 结构/频数非法 histogram 即使 fixture 在场也不得
  委托为 True(R7b 的 malformed 委托撤销);缺件 fixture 仍如实委托;
  合法手工输入(双键直方图+冻结容差同步+键序重排)双模式通过
- gk 子门: graph_integrity_ok=False 与 PASS 并存拒(生产 fail-closed
  早退);无 fixture PASS 缺 final 拒(生产端 PASS 必经 tier1/tier2);
  FAIL 早退无 final 不加拒
- tail 语料覆盖: 预期语料集合=direct_generator 上下文,不由 per_corpus
  自身键集合自列;缺整份语料无 fixture 拒/fixture 委托

## 复现与修复(WSL 零生成/零 MC/零 fit/零 optimizer;直调 pure helper)
- 修前(C17b)7/7 洞: REPRO_R8_PRE_FIX.py;修后(C18)7/7 拒+三正控制保持
- reviewer 独立探针(不同数值)证实同类反例真拒、正控制双模式通过、
  digest 域逐值不变(r15cue-cf62a57d 新旧一致)

## 验证(C18 字节)
- 钉 R8 11(断言覆盖 ~13 类);qprod 面 182/182;r8/r9/r10/r17 面 29/29
- r21 v6 C18: run 20261002_013343 rc=0, 2711/0F/7skip, record
  f9e44621, verify 2711/2225/161(一次通过);262 v13 240 RC=0;
  E01 复算 C18 与 R5-R7 identical;E02 R8 七步 rc=0
- C17b 及更早记录零改写(git diff 空);原生 2/2 耗尽维持;零新增原生/
  MC 研究/fit/optimizer/模型加载
- 运行标记说明: RUN_MARKERS_REBUILT.md(首版 runner EVD 误指 R6 目录,
  R6 历史字节已还原,R8 标记按会话回执重建;run 原件未触碰)

## 验收
- reviewer(glm-5.3-flash): V1 内容 PASS(C18)+3 非阻塞发现(P2 C18
  r21 目录未提交→已补 tracked;P3 runner EVD/计数→已修);处置最小
  核验三项确认,结论 PASS 不变;独立探针/原件随包
- 最终 CLOSED 由 ChatGPT 独立终验;本包不构成任何真实资格/研究授权
