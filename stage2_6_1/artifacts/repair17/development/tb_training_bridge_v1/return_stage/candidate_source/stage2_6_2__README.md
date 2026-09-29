# Stage 2.6.2 — 小规模 PPO 教学实验(FAIL,如实报告)

- **判定:FAIL** — 三族 per-family probe 全部无法学习,core experiment 与 sealed final evaluation 按 §10/§13 未执行。
- Iteration:`s262_r0`;baseline `1927faa647d34e4f45ed9c46d100f500081560b8`
- R2 输入:plan digest `qp-8f64a1b5…`(PASS,只读零漂移,输入锁 13 项全过)
- 主报告:[`report/route_c_stage2_6_2_small_ppo_teaching.md`](report/route_c_stage2_6_2_small_ppo_teaching.md)

## 核心结论

在冻结路线(PPO + MLP + Long/Flat + causal-unscaled 生产观察)下,PPO 无法从 C1/C2/C3 curriculum 学到任何预期能力:

| 族 | probe 预算 | 终态 | core capture | 行为 gap |
|---|---|---|---|---|
| C1 | 45,920 steps | Always Long→Always Flat | -0.026 | 0.0 |
| C2 | 68,880 steps | Always Flat | 0.0 | 0.0 |
| C3 | 68,880 steps | Always Flat | -8.36 | 0.0 |

C1-only 用 4 倍 probe 预算(640 eps = 183,680 steps = core 全预算)同样坍塌并死锁——非预算不足。学习动力学健康(换手 128→0 的摩擦规避真实发生)但策略无法形成对观察的选择性响应;机制分析与证据边界见主报告附录 A。

## 目录结构

```
stage2_6_2/
  README.md                        本文件
  src/rl_curriculum/
    ppo262_namespaces.py           2.6.2 seed 派生/namespace/final 封存
    ppo262_input_lock.py           R2 只读输入绑定与验证(13 项)
    ppo262_banks.py                episode bank 构成/staged-mixed 顺序
    ppo262_env.py                  multi-episode curriculum env(SB3)
    ppo262_config.py               3 个预注册 PPO candidate
    ppo262_train.py                训练 runner(checkpoint/曲线/审计)
    ppo262_metrics.py              capture/行为/retention/pair-cluster
    ppo262_final.py                sealed final 协议(本轮未消费)
    ppo262_smoke.py                PPO smoke(14 项全过)
    ppo262_cli.py                  CLI(input-lock/…/summarize)
  tests/route_c_stage2_6_2/        49 项测试(全绿;2.6.1 回归 106 项全绿)
  report/                          主报告(§31 24 问全答)
  artifacts/                       全部真实运行证据(无空 artifact)
  models/                          probe(3)+延长诊断(1)证据模型 zip +
                                   全部 17 个模型的 manifest(sha256 等)
  runner/ppo262_fail_closure.py    FAIL 收尾脚本(诊断+core 计划+判定)
```

## 未产生的 artifacts(如实说明)

以下 artifacts 属 core/final 阶段,因 probe FAIL 按 §10「不要继续烧 core
experiment 预算」与 §13「停止」**有意未产生**(不制造空 artifact):

`staged_training_manifests / mixed_training_manifests /
manifest_pairing_integrity / training_run_summary /
training_learning_curves / dev_evaluation_results /
final_evaluation_plan(+digest) / final_evaluation_exposure /
final_evaluation_raw / final_evaluation_summary /
reference_gap_capture / behavior_skill_matrix / retention_matrix /
staged_vs_mixed_comparison / pair_cluster_uncertainty /
regression_fullcold_summary`

对应能力已实现并有测试覆盖(见 `src/` 与 `tests/`),`core_experiment_plan.json` 记录了完整预注册设计与未执行理由。final namespace `ppo_final_eval_262` 从未解锁、从未生成(regression_summary:`final_namespace_untouched=true`)。

## 隔离与纪律

- 2.6.1 generator/Route C/ObservationSpec/reward/fee/时序零修改(输入锁逐文件哈希验证);
- 未使用 qualification_r2 的任何 seed(枚举验证零重合);
- 未修改 reward scale、未用 reward normalization / VecNormalize / FreqAI scaler;
- 未 backtest / dry-run / real trading;未进入 2.6.3。

## 环境复现

WSL `CryptoRL-Ubuntu-24.04`,conda `freqtrade-rl`,项目 `~/projects/crypto_rl`,
vendor `52bc96f4480b1a0da6a9b455bd00b17fbb6786a5`。SB3 2.9.0 / torch
2.13.0+cu130 / gymnasium 1.3.0。

---

## Stage 2.6.2 Repair R1 — PPO 可学习性诊断与实验基础设施闭环(2026-08-31)

Stage 状态不变:**FAIL**。本轮为诊断轮(`s262_diag_r1`),判定
**Repair R1 Diagnostics: PASS**,机械落入决策树 **Branch D**。

- **Harness 修复**:config-development null-score bug(独立
  `config_dev_D1_capture` 指标 + all-fail 无 fallback + official 选择为空)、
  config/probe/final 三层硬门禁 fail closed(伪造 artifact 无法绕过)、
  episode attribution 完整化(terminal info 携带 identity/cost)、PPO
  rollout/update 诊断正确绑定(SB3 2.9.0 时序根因实测修正,含 grad_norm
  捕获)。
- **诊断证据**:raw:ret/vol 尺度比实测 82.9 倍,随机初始化第一层贡献占比
  raw 98.7%;unscaled 小尺度特征列梯度低 40–7000 倍(scaling 解除);
  unscaled MLP 监督全坍塌而 fitted MLP 学会 C1/C3(泛化);
  D0 重复暴露下 unscaled PPO C3 2/3、C1 1/3 seeds 可学;
  A/B/C 严格配对 ablation:Arm A 全坍塌,Arm C 下 C1 eval core capture
  0.16/0.44/0.60(3/3 恢复)但 C2/C3 大亏;BC warm-start 能学
  (held-out 0.80)而 PPO fine-tune 摧毁(0.48)。
- **下一步**:PPO optimization repair(不进 2.6.3);scaled 预处理若升级为
  正式合同必须先走 2.6.1 R3(Arm B/C 仅 diagnostic evidence)。
- 产物:`artifacts/repair1/`(21 文件,含诊断计划锁
  `dp-eb37187b…`);主报告
  `report/route_c_stage2_6_2_repair1_diagnostics.md`;新增 47 项测试
  (合计 96 全绿)。r0 证据零覆盖;official final namespace
  未解锁/未生成/未暴露。

---

## Stage 2.6.2 Repair R2 — Family-aware 评估、三 Seed BC 与真实 PPO 梯度诊断闭环(2026-08-31)

Stage 状态不变:**FAIL**。本轮为诊断轮,最终 iteration `s262_diag_r2_1`
(计划锁 `dp-ee6f8dc1…`;前两锁 `dp-0551c1a1`/`dp-0a0c2e2c` 因锁后
harness 缺陷按 §13 废弃,详见主报告 §0),判定
**Repair R2 Diagnostics: PASS**(语义 validator 60 项检查零问题)。

R1 被独立审查判 FAIL / Branch F 的七项缺陷全部修复并有测试锚定:
mixed-family evaluator 改为显式 family × rung 分组(单族入口拒绝
mixed bank;每 cell 记录 reference identity 与 threshold 解析值;
R <= B 的 cell 标记 invalid_reference_gap 并从 branch 排除);
BC 三 seed × 三族全部真实执行(critic 不动 / actor 导入哈希验证 /
held-out pair 双隔离);Arm B 常数改为 precommitted(只来自 R1 历史
artifact 的机械规则,构造器无数据入参,锁先于任何 r2 bank 生成),
旧 Arm B 更名 coarse_train_fitted;216 个 probability checkpoints
真实落盘(哈希可重算、可重新加载评估,含 after_bc_before_ppo);
梯度插桩改为 SB3 2.9.0 PPO.train() 忠实副本(真实 clipped surrogate,
backward 后/step 前捕获,单 minibatch 手工复算数值等价);C2 类别
不平衡三对照(U/W/B,权重只来自 train labels);判定按 family 独立、
跨族证据拼接被拒。

**Family branches**:C1 = **B**(unscaled 坍塌 -0.019/0/0,scaled
0.76-1.51 且概率分离真实)、C2 = **A**(unscaled scratch 即恢复
2/3,capture ≈ 11-12 伴门控概率分离 0.15-0.29)、C3 = **D**(BC
克隆 0.87-0.92 被 fine-tune 摧毁至 0.43-0.62,3/3;scratch 无 arm
恢复——巨大 capture 来自 0.002-0.008 的窄 reference-gap,概率/行为
判据正确排除)。

**监督结论**:C2(Long 率 2.16%)在 unscaled 下连 W/B 类平衡对照都
学不会,在 fixed/fitted 下三 seed 全学会(W/B bal 0.71-0.94)——
C2 可学性 blocker 是 scaling 而非 representation 不可学,Branch E
被否定。

**推荐路线**:任一 family = B → **Stage 2.6.1 Repair R3**(重新冻结
preprocessing 并重新 qualification,不得直接 official 2.6.2);C3=D
的证据在其后指向 PPO Optimization Repair。

产物:`artifacts/repair2/`(33 文件)、`models/repair2/`(36 run ×
216 checkpoints,.pt + 哈希)、主报告
`report/route_c_stage2_6_2_repair2_diagnostics.md`、新增 9 个测试
文件(53 项;stage2_6_2 全套 149 项全绿;affected 2.6.1 106 项与
Route C 代表 276 项全绿)。r0/R1 证据零覆盖(哈希重算验证);
official final namespace 未解锁/未生成/未暴露。

## Stage 2.6.2 侧的 R3 联动更新(2026-09-01)

阶段 2.6.1 Repair R3(预处理合同轮,诚实 FAIL,详见
`../stage2_6_1/report/route_c_stage2_6_1_repair3_preprocessing_qualification.md`)对本目录做了一处登记式更新:

- `ppo262_input_lock.py`:新增 `R3_REGISTERED_CODE_CHANGES` 显式
  白名单——2.6.1 的 `curriculum261_api.py` 在 R3 迭代中合法变更
  (R3 namespace 白名单 + qualification_r3 完整守卫 + 重复派生
  函数合并)。守卫语义不变:登记文件必须精确等于登记哈希(二次
  漂移仍 fail closed);未登记文件的任何漂移仍然 fail;
- `tests/route_c_stage2_6_2/test_ppo262_input_lock.py`:守卫测试
  相应更新,并新增 R2 seed 派生黄金向量测试(证明 R3 变更不改变
  R2 corpus 的 seed 派生);
- Stage 2.6.2 official 状态保持 **FAIL**;C3 PPO Branch D 仍开放。
