# EVIDENCE_CARD — 三臂课程证据卡(2026-10-17 v2,只读现件;入库版)

> 证据源=已有四锚点解析面板(A/B/B64/B64ent)、32 条
> logger(ent_log.json)、128 段逐步动作账本(eval_actions)、
> 三臂运行证据(见 §五 索引)。零新实现/零训练/零新
> forward。course_gate=not_frozen;实验已关闭,不追加
> 系数/seed/步数。
> 口径:v2(审查方 4639)——B64 与 B64ent 分列;删旧比较。

## 一、行为随输入变化(观察,不称"技能已学")
四臂面板 P_hold 均随 s 变化,且延长与高熵改变了该响应:
- **B64(延长,ent=.001)**:四态公开 mode **全 HOLD**;
  H32 条件 P_hold 正/负 s=**.99844/.92708**(rem1 侧
  .99844/.92730)。
- **B64ent(熵臂,ent=.010)**:公开 mode 三态 HOLD+
  **rem1 s−1 一态 REBAL(w≈+.23457,负 s 正仓)**;
  H32 条件 P_hold 正/负 s=**.96682/.51614**(rem1 侧
  .96466/.48475)——负 s 侧 HOLD 概率较 B64 大降。
- s 条件响应只能证明**行为随输入变化**;不足以直接称
  技能已学(方向翻号/期限成本区分仍未建立)。

## 二、未建立
1. **方向翻号**:B64 全 HOLD;B64ent 唯一非 HOLD 态为
   **负 s 正仓**(+.23457)——翻号方向仍错。
2. **期限条件响应存在,但正确的期限/成本技能未建立**。
   同一个 B64ent checkpoint 在负 s、其余固定 flat 观测
   相同、仅 rem32→rem1 时,P_hold 由 **.5161363294** 变为
   **.4847497385**,effective_flat 由 **.5190198610** 变为
   **.4882366564**,差 **.0307832046**;公开 mode 由 HOLD
   变为 **REBAL(+.2345737815)**。这是**固定 checkpoint
   对期限输入的条件差异**,不能写成 B64→B64ent 的熵
   干预差。H1 负 s 仍开正仓,亦不能据差异本身声称正确
   区分期限/成本。effective_flat 是**该 flat 决策锚点的
   保持/调至零仓概率**,不是轨迹收盘仓位统计。
3. **收益未证改善**:配对净 log B64ent **.00012996** vs
   B64 控制 **.00323260**,差 **−.00310265**,配对描述
   SE **.00762152**——未证显著优劣。

## 三、账本分解与计数(如实口径)
- **净 log=价格 log−正费拖累**(同路径可加分解;
  非去费反事实):本臂价格 log **.00456984**、费拖累
  **.00443988**。
- 动作计数(B64ent 2112 步):HOLD **1247**(其中
  **508 为持仓**态 HOLD)、内部连续 **422**、REBAL
  **865**;**锚点条件内部质量 I(.92–.95)≠全轨迹占比**。
- KL/clip 非零只证策略在更新,**不证 advantage 正确**。
- entropy_loss **不含系数**;系数生效证据=实际实参
  (ent_coef_change 读回 .001→.010)与终值字段。
- 方向翻号缺失成因未知:不归因容量/熵/步数。

## 四、下一教学目标候选(仅设计,不实现)
- **C-a 候选**:先限定受控 flat、非末步、正负 s 对称
  场景;逐锚点列**方向符号、公开 mode 及整体动作分布**,
  配对净 log 仅补充。HOLD 不能自动算方向通过,也不把
  负 s 在所有期限/已有仓位下一律做空定为标签。
- **C-b 候选**:固定同一 checkpoint 比较期限输入响应,
  并用已知末步 flat 成本不交易要求判断行为是否正确;
  **不能仅要求面板分化**。当前锚点全 flat,**未验证持仓
  退出能力**。
- 两者均仅设计,不实现/训练,不在本卡冻结阈值。
- 不以收益均值为唯一毕业标准;**阈值由审查方逐课草案,
  本卡不自设**。

## 五、运行证据索引(完整;原件本地+Slack 线程)
| 臂 | 本地 zip | SHA256(完整) | Slack 文件 ID(回执 permalink 见线程 p1792009505.595799 对应消息) |
|---|---|---|---|
| seed_contrast_a1 | F:/trading/seed_contrast_a1_run_20261016.zip | d3e8c6180b496ad9d8eb13582bcd9827885f44ffdf1fca584d25d7db80f52095 | 主包 F0C9ZH9E71P;sidecar F0C9VMGFTEJ |
| seed_extend_a1 | F:/trading/seed_extend_a1_run_20261017.zip | b47d712c26def68793a0f7b28f70d5f42eba748ca156c33b686a27ab16f49faf | 主包 F0CA06TNGF3;sidecar F0C9WF1UX2S |
| entropy_arm_a1 | F:/trading/entropy_arm_a1_run_20261017.zip | a87960df6bcfeff95cf6f085b356b6d44ed479267663a3841ab3be3f78d6cc39 | 主包 F0C9YGF3MEW;sidecar F0CA0K14RH7 |

JSON 内部目录(全;字段经只读复核正确,不需重算):
- **seed_contrast_a1_20261016_output/**:contrast.json
  (boundary=identity/ckpt_sha256/only_change/steps/
  train_counts/A_panel_reference/**B_panel**/A_eval_
  episodes/B_eval_episodes/baselines/budget_final)、
  traces.json(128 trace canonical);
- **seed_extend_a1_20261017_output/**:extend.json
  (cold_read_before_build/identity/boundary{param_hash,
  num_timesteps,ppo_n_updates,optimizer_success,
  eval_calls}/boundary_rng_invariance/steps/final_counts/
  B64_final_sha256/final_eval_episodes/B64_panel.rows/
  budget_final);
- **entropy_arm_a1_20261017_output/**:extend.json
  (同上+ent_coef_change+eval_actions.final_eval 128 段)、
  ent_log.json(rows[]._timesteps/_n_updates/_ent_coef/
  train/entropy_loss·approx_kl·clip_fraction)。

## 六、依赖与恢复(仅历史复现说明,不构成新运行授权)
### 固定外部输入(执行时须在位;SHA256=文件身份)
| 路径 | SHA256 |
|---|---|
| /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/initial.zip | f87005f35210c64c117f247afdc984bd1244cda8e3da8690c45e87a2c7184dba |
| /mnt/f/trading/unified_teaching_pilot_a1_20261016_output/final.zip | 9cb6113387716f3b76f9f198aedd0ac284b199d94363f79f7830bbe347b7b7d1 |
| /mnt/f/trading/diag_panel_a1_20261016_output/diag_panel.json | af2dd1c393d0230db664a28404ef9027492a2aa1a1ef5397dc38206fbca270b8 |
| /mnt/f/trading/seed_contrast_a1_20261016_output/B_final.zip | 5499983789b4886a1b53d01ee451ffd38ff86b35b1612dc7b8ab4ac09fa9cb1b |
| /mnt/f/trading/seed_contrast_a1_20261016_output/traces.json | d153e39d9f2f008ecf3531fc3497f85d4848a3b0a14fb184da3068dc3bdc8f41 |
| /mnt/f/trading/seed_contrast_a1_20261016_output/contrast.json | 53de5abb231fab1d841a5d493f0ec3107a724613b4ea75607d932e06522075a6 |
| /mnt/f/trading/seed_extend_a1_20261017_output/B64_final.zip | 0cae31518d7caa63ae563c444e12b6963f1330d29aa694f0697d0f9272b8cdc9 |
| /mnt/f/trading/seed_extend_a1_20261017_output/extend.json | 3badfb2cec17a7a4697e01f0f944cca70f02e65d560a1151504f6b90bd1a512b |

### 源码依赖(全 SHA 绑定)
- 已入库 pilot 目录五件:runner.py/teach_env.py/policy.py/
  eval_pilot.py/run_spec.json(run_spec=23ce189231b3359765d
  05af1df1d4403d682ce598d17067e952b7d9595b82b47);
- diag_panel/diag_panel.py=5ebd5fa6a39b6d9a56e0d0500c27a6
  0d3e82530e04f7eda4d8b1edf6da1ddfd2;
- 本次 SC(seed_contrast.py)与 SX(seed_extend.py)由本次
  白名单全 SHA 绑定;
- repo 源码以已核基线 commit **4f97809c2d5e09bd02e1765
  31e7fa31010fadbe** 的 stage2_7_0/src 绑定:launcher 复制
  rl_posctl 的 __init__.py/ledger.py/env.py/policy.py/
  versions.py/curriculum.py 六件与 skill_p0 的 __init__.py/
  p0policy.py/p0spec.py/unified_course.py 四件,**共 10 件**。

### 环境/复现说明
- 源码含原绝对输入/测试导入路径:复现须按上表恢复在位;
  **保留历史字节,不声称任意 clean-clone 可独立运行**。
- checkout 依赖环境变量分别指向 repo src、teaching_
  pilot、diag_panel、seed_contrast、seed_extend:
  **PILOT_REPO_SRC / SEED_CONTRAST_PILOT / SEED_CONTRAST_
  DIAG / SEED_CONTRAST_DIR / SEED_EXTEND_DIR**。
- 复现三臂前 **unset PYTEST_ADDOPTS**;不沿用 pilot 的
  5 项 selector。
- 共享外层=仓库路径
  **stage2_7_0/runner/teaching_pilot/outer_teach.sh**
  (SHA **ed7cc63a094d3578a67d7dbc886bfaf1ab9a0121b96e
  cfbc79eb326d6448e2df**):三臂**通过共享 outer 调用
  各自 launcher**;不重复复制。
