# -*- coding: utf-8 -*-
"""事前固定计划与预算(RouteC_PositionControl R1;PosctlDevPlan-v2)。

R1(SCOPE_AND_BUDGET):本轮为有限修复验证,不重跑 18 格容量/时序
pilot(旧结果=原版本历史,只读归档,不回填新参数)。旧轮预算违规
(smoke 21,516>16,384、11 次>8)留档不清零;新额度见
versions.POSCTL_R1_BUDGET,由 rl_posctl.budget.ReservationLedger
在动作发生前预约执行。

事前固定(看任何学习结果之前):训练面、bank/分区种子、rollout/
batch、评估协议、经济失败处理(训练中出现 reward_valid=False →
RUN_INVALID 停止,不删样本/不重抽/不补造)。

gamma=0.99 为训练折扣;账本核对与评估呈现用未折扣原始奖励,
两者区别在报告说明。
"""

from __future__ import annotations

from rl_posctl.versions import POSCTL_R1_BUDGET

# ---------------- 历史候选(旧轮 18 格结果绑定,本轮不重跑) ----------------
MLP_WIDTHS = (128, 256, 512, 1024)
MODEL_SEEDS = (1001, 1002, 1003)
CAPACITY_STEPS = 65_536          # 旧轮历史(已消耗,存档)
SERIES_STEPS = 32_768            # 旧轮历史(已消耗,存档)

# ---------------- R1 修复验证面(事前固定) ----------------
RUN_NAME = "PosCtl_R1_20261012"
TRAIN_COURSE = "c4d2"            # 训练面课程(与旧轮同名,规格 v2)
TRAIN_BANK_EPISODES = 64         # 训练 bank(R1 额度 512 内)
EVAL_EPISODES = 24               # R1 无梯度评估 episode 数
MASTER_SEED = 20261012           # bank 主种子(train/dev/eval 派生)

# 训练面规格覆盖(Curriculum-v2 默认参数即训练面;显式钉死防止
# 默认漂移):有界均匀噪声 a=√3σ,σ∈[0.03,0.06],μ_max=1.2e-3。
# 选择依据(事前,未看任何学习结果):DP 参考在 (64, c4d2) 规格下
# 出现非平凡混合(内部仓位双侧/HOLD/调仓/反手,edge>flat,见
# validity 探针);随机策略单 bar 最大损失 |w|·a ≤ 5.2% 无破产尾。
TRAIN_SPEC_OVERRIDES = dict(mu_max=1.2e-3, sigma_lo=0.03,
                            sigma_hi=0.06)

ROLLOUT = 2048
BATCH = 256
N_EPOCHS = 10
GAMMA = 0.99
ENT_COEF = 0.0
LEARNING_RATE = 3e-4

# R1 额度(动作发生前由 ReservationLedger 预约;旧 UsageLedger
# 的"事后计账+只查 PPO 总额"模式废弃)
BUDGET = dict(POSCTL_R1_BUDGET)

# 兼容别名:runner 里的历史引用(全部指向新账本;不得再事后计账)
from rl_posctl.budget import (  # noqa: E402,F401
    BudgetExceeded, ReservationLedger, create_only_dir)
