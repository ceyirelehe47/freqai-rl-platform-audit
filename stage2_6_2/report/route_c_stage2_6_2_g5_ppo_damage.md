# Stage 2.6.2 — G5 诊断:C3 Branch D 的 PPO 损伤机制(GOAL G5)

- 迭代:`s262_diag_g5`(非正式诊断;**不构成正式 Stage 2.6.2 输入**;
  不进入 official namespace/seed;ppo_final_eval_262 零接触)
- 计划锁:`g5dp-423ec7bc…` 起三次零数据/零持久化废止(全部记录于
  现行计划 `supersedes_note`;磁盘证据零污染),现行锁随
  `g5_code_sha256` 锚定代码身份
- 判定规则/停止规则:见计划(6 arms × 3 seeds × 27,552 steps,
  固定预算;预注册 preserved/improved 判据)
- 预算实际执行:3 BC 训练 + 18 fine-tune runs(全部真实执行,
  checkpoint 全存,verify_expected 全过)

## 结果(artifacts/g5_ppo_damage/g5_diagnostic_results.json)

- **H0 成立**:A0_control 复现 Branch D——BC 三 seed 学会
  (heldout bal 0.903-0.904;det cost_selectivity_gap 0.204-0.214),
  r2 原配置 fine-tune 后三 seed 全毁(drop 0.403-0.418;
  behavior gap → 0.000)。
- **五个机制干预全部不能保留**:

| arm | drops(3 seeds) | KL(π_ft‖π_BC) | 判定 |
|---|---|---|---|
| A0_control(r2 原配) | 0.418/0.403/0.404 | 0.45/1.34/2.31 | 摧毁(对照) |
| A1_lr_low(3e-5) | 0.403/0.403/0.404 | **0.008/0.082/0.130** | 摧毁 |
| A2_epochs_low(2) | 0.403/0.403/0.404 | 0.012/1.23/0.23 | 摧毁 |
| A3_advnorm_off | 0.403/0.421/0.445 | **0.017/0.022/0.009** | 摧毁 |
| A4_vf_low(0.05) | 0.403/0.430/0.404 | 0.41/0.44/1.60 | 摧毁 |
| A5_clip_low(0.05) | 0.456/0.418/0.439 | 0.08/0.20/0.21 | 摧毁 |

## 机制结论(可复核)

1. **摧毁与 PPO 更新幅度无关**:A1/A3 的 fine-tune 后策略与 BC 策略
   的 KL 仅 0.008-0.130(分布几乎重合),held-out balanced accuracy
   仍坍塌 ~0.40。把更新调小一个量级、去掉 advantage 归一化、
   解耦 value 损失、收紧信任域,都无法保留 BC 能力——
   "PPO 更新太大/病态"假说被否定。
2. **真实机制 = BC 选择性的亚阈值边际脆弱性**:BC 的 Long/Flat
   概率分离极窄(r2 已知限制#2:pgap≈0.0003-0.0017 与克隆精度
   0.87-0.92 并存)。held-out 精度是 argmax 口径——logits 悬在
   0.5 附近时,任何系统性微移(PPO 的 value/entropy 压力方向)
   都会成批翻转确定性动作。摧毁在概率空间是"小移动",在决策
   空间是"大雪崩"。
3. **推论(下一合同的依据)**:保留 BC 能力不能靠缩小更新,必须
   锚定边际结构本身——(a) fine-tune 期 BC/KL 正则(显式锚),
   或 (b) margin-aware BC(把克隆目标从 0.5 邻域推开,如 logit
   margin/温度),或 (c) 评估口径同时报告概率分离(pgap)而非
   仅 argmax。三者为 G5 后续候选,属下一份冻结合同;本轮证据
   已足以排除"调小 PPO 步长"这条线。

## 边界与诚实记录

- 判定按预注册规则执行:A0 sanity 过(h0_control_reproduced=True),
  无 arm preserved(全为 False;improved 同 False);
- capture 未列入判定(r2 §16-1 窄 denominator 口径;本结果文件仍
  全量记录);probability gap 逐 seed 在 results 原件;
- 全部 checkpoints(after_bc/ep16/ep48/ep96 × 18 runs)经
  verify_expected;BC critic 三 seed 前后哈希相等(actor-only 克隆);
- 2.6.1 api.py 漂移经 ppo262_input_lock 的 R17 框架轮登记精确锚定
  (repo 92818db2;r2 结论保持其自身 input lock 身份);
- 零正式面接触;非正式声明在计划与结果双载体。

## 复核路径

```
python -m rl_curriculum.ppo262_g5 run --out-dir artifacts/g5_ppo_damage
# 计划锁 create-only;结果判定代码即预注册规则;18 runs ≈ 7 分钟
pytest tests/route_c_stage2_6_2/test_ppo262_g5.py
```
