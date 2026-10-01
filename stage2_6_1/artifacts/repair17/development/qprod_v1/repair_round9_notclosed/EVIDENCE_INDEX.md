# QProd R9 返修轮证据索引 — C19=8c99d7d3

## 输入身份
- 基线: R8 封包 HEAD=21e7aaee(C18=cec19ae5 V1 内容 PASS+冷读 PASS 保持);核现场 HEAD=remote=21e7aaee 未前进
- 触发: ChatGPT 第八次 NOT_CLOSED(R8 后 K 判定限定复验;目标逐字在交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R9_ORIGINAL.md(Downloads "(7).md")
- 材料事实: 本轮 Downloads 仅 addendum(7);用户目标提到的 REVIEW.md/reference_task//probes/final_run/RESULT.json 无对应新件(F:/trading/reviewer_qprod_v1/probes 为 09-30 R25 旧件);原 22 项矩阵在 goal_incoming 原包

## R9 修复(仅两个同根 K 校验问题;digest 域/黄金向量不变)
- 缺件不可屏蔽在场坏件: histogram 闭合重构为独立层——每份在场 K 支撑先独立验证
  (结构 isfinite/频数非负整数/精确总量/均值对源),缺件分支只处理"未提供"
  (fixture 委托/无 fixture 拒);坏直方图+删另一语料直方图(fixture)仍拒;删 ova
  派生均值不再跳过原始直方图闭合(原实现在 ova 派生对存在性块内);委托名保持
  R7 兼容(once_vs_attempts.k_tolerance_frozen),不传染在场坏输入
- 非有限数与精确总量: "nan" 字符串键/NaN 字面量键/k_mean 源非有限/ova
  k_mean_*/k_tolerance/k_abs_diff NaN 全部 isfinite 先验显式拒(NaN 使比较式
  静默 False 的绕过路径封死);Σ频数==n_events 精确比较(int() 截断吞 110.5
  修复;"110" 字符串拒);小数频数双模式拒;整数 111 不等控制拒

## 复现与修复(WSL 零生成;直调 pure helper 记录 fixture_mode)
- 修前(C18 字节)8 洞: REPRO_R9_PRE_FIX.py(r1 缺件屏蔽/r2b 派生缺失跳过/
  r3 r3b r3c 非有限键/r4 小数总量/r5 字符串总量/r6 源非有限/r7 r8 ova NaN)
- 修后(C19)同探针 11/11 反例全拒(双模式),三正控制+R8 反例保持
- 边界: 合法删 ova 派生 fixture 委托保持;单键 {1:110}=110 事件非样本不足
  (冻结容差 0.05 正确);两语料直方图都缺 fixture 双委托/无 fixture 拒

## 验证(C19 字节)
- 钉 R9 11;qprod 面 182/182;r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C19: run 20261002_041458 rc=0, 2723/0F/7skip, record 2d61d8f8,
  verify 2723/2237/162(一次通过)— evidence/regress_v6/full_regression_v6_c19/
- 262 v14 C19: 240 RC=0 — evidence/regress262/(OUTPUT_MOVE_NOTE: sed 未命中
  先落 R6 目录已迁移+R6 字节还原)
- E01: E01_RECOMPUTE_C19.json 沿用 R8 原件数值(E01 原生零改动,源码变更仅
  cue-contract 语义重算面)
- E02 R9 七步 rc=0(evidence/e02/)
- R8 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/optimizer/
  模型加载
