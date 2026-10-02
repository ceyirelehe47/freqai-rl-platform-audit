# QProd R12 返修轮证据索引 — C24=6261d5ef

## 输入身份
- 基线: R11 封包 HEAD=4566c23d(C23 内容 PASS+冷读 PASS 保持)
- 触发: ChatGPT 第十一次 NOT_CLOSED(R11 后 Q1 判据与声明依赖分离;目标逐字在交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R12_ORIGINAL.md(Downloads "(10).md")
- 材料事实: 本轮 Downloads 仅 addendum(10);REVIEW.md/HELPER_COMPARISON.json 无对应
  新件——成对对照由 C22 影子(git show 58d1a9ce)重建于 REPRO_R12_PRE_FIX.py;
  原 22 项矩阵在 goal_incoming 原包

## R12 修复(同根 Q1: 判据与声明依赖分离;digest 域/黄金向量不变)
- 实际一致性门重算与 k_abs_diff 声明解耦: len(_k_sides)==2 即重算 k_derived=|km-kv|
  并判门(冻结界优先/声明兜底),可省声明键缺失不得把已知门失败改 True(理由注明
  "与差值声明副本是否提供无关")
- 声明核对仅在声明在场: 来源相等对账(R11 回退保持)/有限性(R9 先验)/非负性(R11);
  不在场只记录该声明缺失(_OVA_REQ 委托/无 fixture 拒)
- 委托不覆盖已知门失败;双侧真缺按原工程/正式缺件边界(R11 derivation_missing 保持)

## 复现与修复(WSL 零生成;fixture 双模式;C22 影子对照)
- 修前(C23 字节): G1b/G1c(1/4 删kad/再删kt)与 G2b'(4/1 删kad) C23=True vs C22=False
  (成对退化);G1a/G2a 完整双版均拒;L1a-c 合法 1/1 双版均 True
- 修后(C24): G1a-c/G2 全拒;L1a-c 保持 True;R11 探针(三反例+两侧删法+合法缺件)
  全保持;R10 六洞全拒;无 fixture 缺必需仍拒

## 验证(C24 字节)
- 钉 R12 7(+R11/R10 联 21);qprod 面 205/205;cue 套件 43/43(六文件,含 r9/r10_cue_eval)
- r21 v7 C24: run 20261002_175459 rc=0, 2746/0F/7skip, record f7e76b9e,
  verify 2746/2260/165 — evidence/regress_v6/full_regression_v7_c24/
  (顶层目录名沿 r11 惯例 regress_v6,内容目录 full_regression_v7_c24)
- 262 v19 C24: 240 RC=0 junit 240/0(meta 绑定 6261d5ef,参数化 runner tmp_r11
  sed 派生) — evidence/regress262/
- E02 R12 七步 rc=0 — evidence/e02/;E01: E01_RECOMPUTE_C24.json(零原生改动)
- C23 及更早记录零改写;零新增原生/MC 研究/fit/optimizer/模型加载;原生 2/2 耗尽维持
- reviewer 模型: AGENTS.md 硬绑定已解除(用户 2026-10-02),按 task.agentModelOverrides
  当前解析执行
