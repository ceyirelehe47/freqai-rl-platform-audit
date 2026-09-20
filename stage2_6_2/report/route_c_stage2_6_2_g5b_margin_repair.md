# Stage 2.6.2 — G5b 诊断:BC 边际脆弱性的保留干预(GOAL G5,修复结论)

- 迭代:`s262_diag_g5b`(非正式诊断;**不构成正式 Stage 2.6.2 输入**;
  official namespace/seed 零接触;ppo_final_eval_262 零接触)
- 计划锁:`g5bdp-…`(create-only;`g5b_code_sha256` 锚定代码)
- 预算实际执行:6 次 BC(2 形态 × 3 seeds)+ 12 次 fine-tune
  (4 arms × 3 seeds × 27,552 steps,分段 12 × 8-episode bank 周期;
  rehearsal 段间 1 epoch 加权 CE);checkpoint verify_expected 全过
- 前序:`s262_diag_g5`(更新幅度被排除;KL≈0.008-0.13 仍全毁;
  机制 = 亚阈值边际 argmax 脆弱性)

## 结果(artifacts/g5_ppo_damage/g5b_diagnostic_results.json)

BC 侧(seed 29201-29203):

| BC 形态 | heldout bal | mean|z1−z0| | frac<0.5 | det gap |
|---|---|---|---|---|
| standard(加权 CE,r2 同款) | 0.857-0.919 | **0.05** | **1.000** | 0.19-0.21 |
| margin(hinge,m=2.0) | 0.992-0.994 | **5.11-5.78** | **≈0.01** | 0.07-0.15 |

fine-tune 判定(预注册规则):

| arm | drops(3 seeds) | det gaps | preserved | selective |
|---|---|---|---|---|
| B0_control | 0.401/0.434/0.446 | ≈0(坍塌) | — | —(sanity:摧毁复现 ✓) |
| **B2_margin_bc** | 0.029/0.046/0.208 | 0.046/0.211/0.130 | **✓(2/3)** | **✓(2/3)** |
| B3_rehearsal | 0.400/0.438/0.465 | ≈0 | ✗ | ✗ |
| **B4_margin_rehearsal** | **0.008/0.016/0.008** | 0.043/0.221/0.121 | **✓(3/3)** | **✓(3/3)** |

关键内部量:standard BC 微调后 KL(π_ft‖π_BC)=0.45-0.68、边际
坍回 ~2.5(相对其 0.05 已是"巨变",argmax 翻转);margin BC 微调后
KL=0.017-0.27、边际保持 4.8-11.2(frac<0.5 ≤ 3%)。B4 的复训把
KL 压到 0.017-0.08。

## 结论(机制 → 修复闭环,可复核)

1. **B0 复现 Branch D 摧毁**(drop≈0.40-0.45,gap→0):对照有效;
2. **margin-aware BC 单独即修复保留**(B2:2/3 seeds preserved&
   selective;第三 seed drop 0.208 亦远低于对照的 0.44);
3. **margin + 周期复训 = 3/3 稳健修复**(B4:drop ≤ 0.016,
   gap 保留至 BC 水平的 22%-110%,边际全保持);
4. **复训单独无效**(B3:与对照同毁)——与 G5 机制一致:标准 BC
   的亚阈值边际(0.05;frac<0.5=100%)复训只是反复重申脆弱结构,
   修复必须**加宽边际本身**;更新侧干预(G5)与排练侧干预(B3)
   都不能救,边际侧干预(B2/B4)能救;
5. **GOAL G5 出口达成(C3)**:对 C3 Branch D 取得可复核的修复
   结论 = 边际 BC(开发集标定 hinge,m=2.0,300ep,lr 1e-3;
   标定过程如实入计划)+ 可选周期复训;正式使用须按 G6 前置的
   G4 有效资格与原训练门禁,本结论非正式输入。

## 诚实记录

- margin BC 的优化预算(300ep/1e-3)与 standard(30ep/3e-4)不同
  ——这是干预的一部分,计划内声明(标定:softplus 30ep 仅达
  0.05;hinge 300ep 达 5.46);
- B2 seed29203 drop 0.208(preserved 判定按预注册 ≥2/3 规则);
- 全部 checkpoint(after_bc/ep16/ep48/ep96 × 12)verify_expected
  过;critic 全程不动(BC actor-only 哈希前后相等);
- 段式 learn 与整段调用的 rollout 边界逐位对齐(n_steps=574;
  段=2296=4 rollouts);梯度/rollout 记录来自同一 DiagnosedPPO2。

## 复核路径

```
python -m rl_curriculum.ppo262_g5b lock --out-dir artifacts/g5_ppo_damage
python -m rl_curriculum.ppo262_g5b run --out-dir artifacts/g5_ppo_damage
pytest tests/route_c_stage2_6_2/test_ppo262_g5b.py
```
