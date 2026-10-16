# -*- coding: utf-8 -*-
"""count_proof v3 — 解析算量证明(Fraction 精确;零 V/零真实积分)。

审查方 3869 公式:
  B  = 2*(52/1000) / ((1-53/1000)^2 * (1/128))
  U  = B*81 + 2*161 + 5*(B*(21/100)*(121/100) + 2)
     = 1553.201946... < 1554 < 2000
- k<.052, h<.053(以 52/1000、53/1000 为界);
- A161: sum|w(1-w)| = 81(Fraction 精确);
- 5 个 HOLD: 负 e 的 |e(1-e)| = |e|(1+|e|),|e|<.21
  → (21/100)*(121/100),逐臂 +2 基片;
- REBAL 逐臂 ceil 上界贡献含 +2(故 2*161 项)。
(旧 1385 界推导有误已删。)
"""
from fractions import Fraction as F

B = 2 * F(52, 1000) / ((1 - F(53, 1000)) ** 2 * F(1, 128))
ws = [F(-160 + 2 * i, 160) for i in range(161)]
assert ws[0] == -1 and ws[160] == 1
sum161 = sum(abs(w * (1 - w)) for w in ws)
U = (B * 81) + 2 * 161 + 5 * (B * F(21, 100) * F(121, 100) + 2)
print("sum|w(1-w)| =", sum161, "== 81:", sum161 == 81)
print("B  =", float(B))
print("U  =", float(U))
print("1553.201946 < 1554 < 2000:",
      float(U) < 1554 < 2000)
assert sum161 == 81
assert float(U) < 1554 < 2000
print("COUNT_PROOF_OK (Fraction exact)")
