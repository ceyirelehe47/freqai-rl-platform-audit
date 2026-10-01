# RouteC_QualificationProducer_Integration_v1 R6+R7 返修轮增量交付

## 基包(不重复打包)
- R5 增量包 = RouteC_..._RETURN_REPAIR_R5.zip(SHA-256 0324c40d...,
  内容 C15=1139887e);链条 R4(a8630ac9)→R3(21f89291)→R2(846495db)
  →C9(972d0c0f)。本包仅含 R6/R7/R7b(P3) 新增源码/证据/审查原件。

## 身份
- 仓库: ceyirelehe47/freqai-rl-audit, 分支 route-c-stage2-6-1-repair17
- 候选链: C16=f45958ad(R6) → C17=0663be91(R7, reviewer 内容 PASS 对象)
  → C17b=079713cd(R7 P3 一行委托标注, reviewer 最小复验 PASS)
  → a3ab2061/b3397972(证据);封包 HEAD b3397972
- 触发: ChatGPT 第六次 NOT_CLOSED(目标逐字在交接件 §0;本轮 Downloads
  仅 addendum(5), REVIEW.md/(1).md 为 09-29 R25 旧件未误用)

## R6 修复(仅 Q1 同根一般规则)
- ova K 链完整对账: k_mean_* 对 dg.<corpus>.aggregate.k_mean(来源)、
  k_abs_diff 对 |k_m-k_v|(派生)、重算差值对容差;来源 1/1 而派生 1/4
  差值 0 拒
- 无 fixture 缺必需子依据≠True(C14 语义回归): ova 10 必需键+
  fpb.bitwise_ok 缺件拒;tail 布尔子依据缺失≠True
- gk 分层一致: pass==(verdict=="PASS")(生产规则)、final.verdict 等顶层
  verdict;FAIL+pass=True 拒;INDETERMINATE 拒保留
- fixture 双重态: 缺件如实 fixture_delegated, 在场键仍对账

## R7 修复(reviewer R6-V1 FAIL 两项 K 链绕过)
- F1: k_mean 声明在场而 dg.aggregate.k_mean 缺件→无 fixture"K 来源
  缺失"拒(不静默跳过);fixture 委托(.source_missing)
- F2: k_tolerance 锚定冻结公式 max(3*pooled_se,0.05)——pooled se 由在场
  k_histogram 重算(ddof=1 同生产式);漂移>1e-9 拒;重算差值以冻结值为界;
  k_histogram 缺件/非法=缺件拒(fixture 委托)
- R7b(P3): fixture 分支 k_histogram 非法补 k_tolerance_frozen_malformed
  委托标注;digest 绑定 aggregate 登记未来轮(P3-1, golden vector 语义面)

## 复现与修复(WSL 零生成/零 MC/零 fit/零 optimizer;直调 pure helper)
- 修前(C15)5/5 放行: REPRO_R6_PRE_FIX.py;修后(C16)5/5 拒
- R7 两洞修前(C16)F1/F2 放行: REPRO_R7_HOLES_PRE_FIX.py;修后(C17)拒
- 合法对照(支撑完整+精确容差+k_histogram)各轮保持通过

## 验证
- 钉 R6 11+R7 4;qprod 面 171/171;r8/r9/r10/r17 cue-contract 29/29
- r21 v6: C16 三次运行(E 盘环境失败原件 3a5976e1+t09 偶发原件 037a770b
  +终 PASS 96d0b862);C17 一次通过 ae607c94;C17b 一次通过 26958bf7
  (各 2700/0F/7skip, verify 2700/2214/160);C15/C14/C13 记录不改签
- 262: v10/v11/v12 各 240 RC=0;E01 复算 C16/C17 coords 逐值 identical;
  E02 R6/R7 各七步 rc=0
- E 盘物理不可用→WSL symlink 环境修复(零代码改动, E_DRIVE_BRIDGE_NOTE)
- 原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/模型加载

## 验收
- reviewer(glm-5.3-flash): R6-V1 FAIL(F1 来源缺件静默跳过/F2 容差无
  冻结锚——R6 patch 引入的两绕过, 探针实证)→R7 修复→V2 复验 PASS(C17)
  →P3 处理(C17b)→V3 最小复验 PASS;独立探针/夹具/输出随包
- 最终 CLOSED 由 ChatGPT 独立终验;本包不构成任何真实资格/研究授权
