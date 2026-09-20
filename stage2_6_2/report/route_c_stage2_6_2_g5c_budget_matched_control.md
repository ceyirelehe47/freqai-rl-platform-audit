# G5c 预算匹配机制对照:G5b 干预归因修正(GOAL G5;非正式)

- 迭代: s262_diag_g5c(独立开发坐标:全新 diag262g5c 命名空间/种子
  29301-29303;计划锁 g5cdp- 一次且仅一次;9 次 BC + 9 次微调
  全部真实执行,checkpoint verify_expected 全过)
- 起因: G5b 因果范围审查(route_c_stage2_6_2_g5b_causal_scope_
  review.md)——B0/B2 双臂损失形态×预算共变,干预归因超界
- 本对照三臂:C0=CE 30ep/3e-4(G5b 失败对照同预算);C1=CE
  300ep/1e-3(**与 margin 臂预算逐字相同**);C2=hinge 300ep/1e-3/
  m2.0(G5b B2 同配方)

## 结果(artifacts/g5_ppo_damage_g5c/g5c_diagnostic_results.json)

BC 侧(3 seeds):

| 臂 | heldout bal | mean\|z1−z0\| |
|---|---|---|
| C0_std30 | 0.886-0.921 | 0.05 |
| C1_std300 | 0.991-0.994 | **7.47-8.09** |
| C2_margin300 | 0.990-0.992 | 4.34-5.84 |

微调判定(与 G5b 逐字同规则):

| 臂 | drops | det gaps | preserved | selective |
|---|---|---|---|---|
| C0_std30 | 0.396/0.481/0.427 | ≈0(坍塌) | ✗ | ✗(sanity ✓) |
| **C1_std300** | **0.044/-0.004/-0.001** | 0.146/0.207/0.194 | **✓(3/3)** | **✓(3/3)** |
| C2_margin300 | 0.067/0.255/0.168 | ≈0 | ✗(0/3) | ✗ |

## 结论(修正 G5b 的干预归因)

1. **因果变量 = BC 优化充分性(经由边际宽度),不是 hinge 损失
   形态**:预算匹配的 CE(C1)边际最宽且 3/3 保留;G5b 的
   "margin-BC 修复"是预算混杂的表象——同预算下 CE 更优。
2. **机制层结论在两个实验中一致并强化**:保留随边际宽度走
   (0.05→毁;4.3-5.8→新坐标 0/3;7.5-8.1→3/3 全保)。hinge
   m=2.0 在满足后梯度归零(宽度~4-6),CE 持续推宽(7.5-8.1);
   观察与"宽度是操作变量"一致(不宣称具体阈值,样本 3+3)。
3. **修正后的可执行处方(GOAL G5 出口,C3 Branch D)**:修复 =
   把 BC 优化到充分边际宽度;CE 加大优化预算即可达(30ep/3e-4
   →300ep/1e-3),hinge 非必要且固定 m 可能欠额。正式使用仍须
   G4 有效资格与原训练门禁;两实验全部非正式。
4. G5b/G5c 原件均保留不追改;G5b 报告的干预措辞以本文件与
   因果范围审查为准收束。

## 复核路径

```
python -m rl_curriculum.ppo262_g5c lock --out-dir artifacts/g5_ppo_damage_g5c
python -m rl_curriculum.ppo262_g5c run --out-dir artifacts/g5_ppo_damage_g5c
pytest tests/route_c_stage2_6_2/test_ppo262_g5c.py
```
