# QProd R11 返修轮证据索引 — C23=9dcb5a54

## 输入身份
- 基线: R10 封包 HEAD=58d1a9ce(C22 内容 PASS+冷读 PASS 保持)
- 触发: ChatGPT 第十次 NOT_CLOSED(R10 后 Q1 派生差值依赖复验;目标逐字在交接件 §0)
- addendum 原文: REVIEWER_ADDENDUM_R11_ORIGINAL.md(Downloads "(9).md")
- 材料事实: 本轮 Downloads 仅 addendum(9);REVIEW.md/PAIRED_DIFFERENCE_CHECKS.json
  无对应新件;原 22 项矩阵在 goal_incoming 原包

## R11 修复(同根 Q1: 派生差值依赖;digest 域/黄金向量不变)
- k_abs_diff 重算来源依赖回退: _k_sides 每侧 = ova k_mean_*(单键循环已验)
  → 回退 dg.<corpus>.aggregate.k_mean 原始来源;两侧可得即重算对账——
  删任一冗余派生副本(或再删自报 k_tolerance,冻结界由直方图重算)不屏蔽
  在场矛盾差值
- 负绝对差自身非法: k_abs_diff<0 独立拒(|·| 恒非负)
- 双侧真缺: fixture 委托(derivation_missing 账目)/无 fixture 拒
- 不按案例名打补丁: 修派生差值一致性的依赖路径

## 复现与修复(WSL 零生成;fixture 双模式)
- 修前(C22 字节)3 洞 fixture 逃逸(+删 k_mean_model 同根变体): REPRO_R11_PRE_FIX.py
- 修后(C23)三洞全拒(两侧删法都拒);C4/C4b kad=0 相同缺件合法通过;
  R10 六洞+控制不退化;无 fixture 缺必需字段仍拒

## 验证(C23 字节)
- 钉 R11 7;qprod 面 198/198;r8/r9/r10/r17 cue-contract 29/29
- r21 v6 C23: run 20261002_142616 rc=0, 2739/0F/7skip, record 9c14597a,
  verify 2739/2253/164 — evidence/regress_v6/full_regression_v6_c23/
- 262 v18 C23: 240 RC=0 junit 240/0(meta 绑定 9dcb5a54;
  首跑文件名沿旧标签 v16_c21,内容正确,已规范重命名 v18_c23+补 junit;
  一次性 sed 参数化脚本 regress262_r11.sh 已存 tmp_r11,不再手拼)
- E02 R11 七步 rc=0 — evidence/e02/;E01: E01_RECOMPUTE_C23.json(零原生改动)
- C22 及更早记录零改写;原生 2/2 耗尽维持;零新增原生/MC 研究/fit/
  optimizer/模型加载
