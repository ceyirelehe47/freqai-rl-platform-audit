# -*- coding: utf-8 -*-
"""事前固定计划与预算(RouteC_PositionControl R2;PosctlDevPlan-v3)。

R2(FiniteRepair R2):修复轮的**有限正确性复验**预算,不是 R1 充值,
更不是新的模型/课程选优授权。R1 账本终态(eval 76,432/65,536 超限
10,896 + 两次 5,632 事故)与 smoke_2 原件丢失保持原字节留档;R2 用
新任务身份 PosCtl_R2_20261012 的独立账本(TaskLedger,先预约后执行)。

R2 面摘要(versions.POSCTL_R2_BUDGET;分项各自生效不可挪额):
真 PPO ≤1,024 步/≤8 次/单次 ≤128;BC=0(不重训);无梯度 env 交互
≤32,768;夹具生成 ≤2,048 调用(失败/同 seed 重建均计);合成合计
≤33,792(派生总项);新增证据 ≤256MiB(不含既有历史原件复制)。

事前固定(看任何学习结果之前):训练面、bank/分区种子、评估协议、
经济失败处理(训练中出现 reward_valid=False → RUN_INVALID 停止,
不删样本/不重抽/不补造)。

gamma=0.99 为训练折扣;账本核对与评估呈现用未折扣原始奖励,
两者区别在报告说明。
"""

from __future__ import annotations

from rl_posctl.versions import POSCTL_R2_BUDGET, POSCTL_R2_TASK_ID

# ---------------- 历史候选(旧轮 18 格结果绑定,本轮不重跑) ----------------
MLP_WIDTHS = (128, 256, 512, 1024)
MODEL_SEEDS = (1001, 1002, 1003)
CAPACITY_STEPS = 65_536          # 旧轮历史(已消耗,存档)
SERIES_STEPS = 32_768            # 旧轮历史(已消耗,存档)

# ---------------- R2 修复验证面(事前固定) ----------------
RUN_NAME = "PosCtl_R2_20261012"
TASK_ID = POSCTL_R2_TASK_ID
TRAIN_COURSE = "c4d2"            # 训练面课程(与 R1 同名,规格 v3 参考)
TRAIN_BANK_EPISODES = 64         # (R1 bank 原件可复用;R2 新生成须入账)
EVAL_EPISODES = 24               # R1 无梯度评估 episode 数(历史)
MASTER_SEED = 20261012           # bank 主种子(train/dev/eval 派生)

# 训练面规格覆盖(Curriculum-v3 默认参数即训练面;显式钉死防止
# 默认漂移;与 R1 相同——R2 不改课程参数,只修参考动力学):
# 有界均匀噪声 a=√3σ,σ∈[0.03,0.06],μ_max=1.2e-3。
TRAIN_SPEC_OVERRIDES = dict(mu_max=1.2e-3, sigma_lo=0.03,
                            sigma_hi=0.06)

ROLLOUT = 128                    # R2 单次 learn 上限(预算面 ppo_steps_single)
BATCH = 256
N_EPOCHS = 10
GAMMA = 0.99
ENT_COEF = 0.0
LEARNING_RATE = 3e-4

# R2 额度(动作发生前由 TaskLedger 预约;R1 面已耗尽超限留档)
BUDGET = dict(POSCTL_R2_BUDGET)

# 兼容别名:runner 里的历史引用(全部指向新账本;不得再事后计账)
from rl_posctl.budget import (  # noqa: E402,F401
    BudgetExceeded, ReservationLedger, TaskLedger, create_only_dir)
