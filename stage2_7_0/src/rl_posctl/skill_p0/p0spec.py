# -*- coding: utf-8 -*-
"""PSC_P0_v1 渐进式技能课程 P0:规格、种子派生与身份常量。

本模块只承载事前冻结的计划常数(任务包 + plan/P0_LOCKED_PLAN.md);
不得出现任何依赖学习结果的选择。种子派生机械可枚举,与旧
posctl(qaf/qualification/R1-R4)研究种子域零复用(见 SEED_LEDGER)。
"""

from __future__ import annotations

import hashlib

from rl_posctl.curriculum import CourseSpec, spec_for
from rl_posctl.versions import (
    POSCTL_PSC_P0_ARM_A_FAMILY, POSCTL_PSC_P0_ARM_B_FAMILY,
    POSCTL_PSC_P0_DECODE_RULE, POSCTL_PSC_P0_OBS_SPEC_VERSION,
    POSCTL_PSC_P0_TASK_ID, POSCTL_PSC_P0_TIME_FEATURES)

TASK_ID = POSCTL_PSC_P0_TASK_ID
OBS_SPEC_VERSION = POSCTL_PSC_P0_OBS_SPEC_VERSION
ARM_A_FAMILY = POSCTL_PSC_P0_ARM_A_FAMILY
ARM_B_FAMILY = POSCTL_PSC_P0_ARM_B_FAMILY
DECODE_RULE = POSCTL_PSC_P0_DECODE_RULE
TIME_FEATURES = POSCTL_PSC_P0_TIME_FEATURES
ARMS = ("A", "B")
ARM_FAMILY = {"A": ARM_A_FAMILY, "B": ARM_B_FAMILY}
N_DIST_PARAMS = {"A": 7, "B": 8}

# ------------------------------ C1 启蒙规格(包常数) -----------------------
C1_HORIZON = 64                      # 训练决策长度
HORIZON_CHECKS = (32, 96)            # 期限迁移检查(不训练)
C1_MU_MAX = 0.004
C1_SIGMA_LO = 0.006
C1_SIGMA_HI = 0.006
C1_FEE = 0.001
C1_SLIPPAGE_BPS = 0.0
C1_PRICE_TICK = 0.0
C1_S_SWITCH_P = 0.10
C1_HOLD_PS = {"c_hold_p": 0.85, "g_hold_p": 0.85, "q_hold_p": 0.80}
INITIAL_CASH = 100.0
MAINTENANCE_MARGIN = 0.05
REWARD_SCALE = 1.0
GAMMA = 1.0
# 资金费:公开预设空计划(已知零资金费教学仿真,非"未知按零冒充")
FUNDING_SCHEDULE: dict[int, float] = {}

# 网格固定:两臂 [128,128] Tanh;rollout 1024×1;batch 256;10 epochs。
HIDDEN = (128, 128)
N_STEPS = 1024
N_ENVS = 1
BATCH_SIZE = 256
N_EPOCHS = 10
LEARNING_RATE = 3e-4
GAE_LAMBDA = 0.95
CLIP_RANGE = 0.2
VF_COEF = 0.5
MAX_GRAD_NORM = 0.5
ENT_COEF = 0.001
MAIN_TOTAL_STEPS = 131_072
CHECKPOINT_STEPS = (0, 32_768, 65_536, 131_072)
SMOKE_STEPS_SINGLE = 512             # smoke 用 n_steps=512(20 opt/learn)
TECHRETRY_STEPS_SINGLE = 32_768
OPT_STEPS_PER_ROLLOUT = N_EPOCHS * (N_STEPS // BATCH_SIZE)   # 40
OPT_STEPS_MAIN_UB = (MAIN_TOTAL_STEPS // N_STEPS) * OPT_STEPS_PER_ROLLOUT
TECHRETRY_OPT_STEPS_UB = (
    TECHRETRY_STEPS_SINGLE // N_STEPS) * OPT_STEPS_PER_ROLLOUT

# ------------------------------ 数据分区(包常数) -------------------------
BANK_SIZES = {          # purpose -> (pairs, variants_per_pair)
    "prequal": (32, 2),
    "train": (256, 2),
    "dev": (32, 2),
    "confirm": (64, 2),
    "hz32": (16, 2),
    "hz96": (16, 2),
}
LOCKED_PURPOSES = ("confirm", "hz32", "hz96")   # 默认不可生成/使用
PLANNED_EPISODES = sum(p * v for p, v in BANK_SIZES.values())   # 832

# ------------------------------ seed(冻结公式) ----------------------------
BC_SEEDS = (270101, 270102, 270103)
PPO_SEEDS = (270201, 270202, 270203)
PURPOSES = tuple(BANK_SIZES) + (
    "bc_manual", "bc_teacher", "sampler", "bootstrap", "evalsample")


def p0_seed(purpose: str, i: int, j: int = 0, k: int = 0) -> int:
    """机械派生:int(sha256("PSC_P0_v1|{purpose}|{i}|{j}|{k}")[:16], 16)。"""
    for name, v in (("i", i), ("j", j), ("k", k)):
        if isinstance(v, bool) or not isinstance(v, int):
            raise ValueError(f"p0_seed {name} 必须为 int:{v!r}")
    if purpose not in PURPOSES:
        raise ValueError(f"p0_seed 未知 purpose {purpose!r}")
    tag = f"PSC_P0_v1|{purpose}|{i}|{j}|{k}".encode("utf-8")
    return int(hashlib.sha256(tag).hexdigest()[:16], 16)


def c1_spec(purpose: str, pair_index: int, horizon: int = C1_HORIZON,
            ) -> CourseSpec:
    """P0 C1 启蒙规格(pair 级;镜像端点复用同 spec seed,仅变换)。"""
    if purpose not in BANK_SIZES:
        raise ValueError(f"bank purpose 未知 {purpose!r}")
    seed = p0_seed(purpose, pair_index)
    return spec_for(
        "c1", seed=seed, horizon=int(horizon), mu_max=C1_MU_MAX,
        sigma_lo=C1_SIGMA_LO, sigma_hi=C1_SIGMA_HI, fee=C1_FEE,
        slippage_bps=C1_SLIPPAGE_BPS, **C1_HOLD_PS)


def bank_horizon(purpose: str) -> int:
    if purpose == "hz32":
        return 32
    if purpose == "hz96":
        return 96
    return C1_HORIZON


# ------------------------------ 检查常数 -----------------------------------
INTERIOR_TARGETS = (-0.8, -0.6, -0.4, -0.2, 0.2, 0.4, 0.6, 0.8)
ATOM_TARGETS = (-1.0, 0.0, 1.0)
CONC_SAMPLES_PER_TARGET = 4096
CONC_WITHIN_TOL = 0.10
CONC_MASS_FRAC = 0.95
CONC_MEAN_TOL = 0.02
BC_UPDATES_PER_FIT = 512
BC_TRAIN_ROWS = 2048
BC_VAL_ROWS = 1024
BC_ACC_GATE = 0.95
BC_MAE_GATE = 0.05
BC_STOCH_GATE = 0.90
REFINEMENTS = ((81, 16, 10), (161, 32, 20), (321, 64, 40))
JUDGED_GRID = (321, 64, 40)
TASK_VALUE_GATE = 0.02
TASK_ERR_FRAC = 0.10
TEACHER_TIE_TOL = 1e-12
BEHAVIOR_GRID = {
    "c": (0.0, 1.0), "q": (0.0, 0.5, 1.0), "g": (0.0, 1.0),
    "remaining": (16, 32, 64),
}
BEHAVIOR_MIN_P_DIRECTIONAL = 0.80
BEHAVIOR_MIN_P_NEUTRAL = 0.75
BEHAVIOR_W_MIN = 0.25
BEHAVIOR_W_NEUTRAL = 0.10
BOOTSTRAP_DRAWS = 10_000
BOOTSTRAP_ALPHA = 0.05
