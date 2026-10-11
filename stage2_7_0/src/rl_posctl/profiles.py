# -*- coding: utf-8 -*-
"""事前固定的小型开发计划与预算账(RouteC_PositionControl E5)。

在看任何学习结果之前固定:候选配置、模型 seed、bank 与分区、
rollout/batch、评估协议、checkpoint 节点、经济失败处理。
预算(EXPERIMENTS_AND_BUDGET §2):
- 正确性 smoke ≤ 8×2048 = 16,384 步;
- CPU/GPU 性能测量共 ≤65,536 环境步(含暖机);
- MLP 容量 pilot:4 宽度 × 3 seed × 65,536 = 786,432;
- 时序对照:2 结构 × 3 seed × 32,768 = 196,608;
- 新 PPO 交互合计 ≤1,064,960;
- 无梯度评估(参考/基线/模型)≤4,194,304 环境步;
- 可选 BC 诊断 ≤4 次 fit(本轮不使用,记录为 NOT_USED)。

gamma=0.99 为训练折扣;账本核对与评估呈现用未折扣原始奖励,
两者区别在报告说明。经济失败(reward_valid=False):训练运行立即
停止并记 RUN_INVALID,不删样本、不重抽、不补造。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# ---------------- 事前固定:候选与 seed ----------------
MLP_WIDTHS = (128, 256, 512, 1024)
MODEL_SEEDS = (1001, 1002, 1003)
CAPACITY_STEPS = 65_536
SERIES_STEPS = 32_768
TRAIN_COURSE = "c4d2"          # 容量与时序 pilot 共用训练面
TRAIN_BANK_EPISODES = 128      # 训练域 bank 容量(全部候选同序复用)
EVAL_EPISODES = 60
MASTER_SEED = 20261012         # bank 主种子(train/dev/eval 派生)

# 训练面规格覆盖(事前固定):smoke 阶段发现默认 σ(0.10-0.20/bar)
# 下未训练策略(均匀混合分布,±1 原子各约 1/4 质量)空头在数百 bar
# 内必然清零——训练夹具生存性缺陷(非学习结果调整;未做任何学习
# 成绩评估)。降为 σ∈[0.03,0.06]、μ=8e-4:随机策略每运行清零概率
# ~1e-3,内点 Kelly(f*=μ/σ²≈0.89)仍成立,费用不变。
TRAIN_SPEC_OVERRIDES = dict(mu_max=0.0008, sigma_lo=0.03,
                            sigma_hi=0.06)

ROLLOUT = 2048
BATCH = 256
N_EPOCHS = 10
GAMMA = 0.99
ENT_COEF = 0.0
LEARNING_RATE = 3e-4

BC_FITS_USED = 0               # 本轮未使用(可选额度未动)

BUDGET = {
    "smoke_steps": 16_384,
    "perf_steps": 65_536,
    "capacity_steps": 786_432,
    "series_steps": 196_608,
    "new_ppo_total": 1_064_960,
    "eval_no_grad_steps": 4_194_304,
    "bc_fits": 4,
}


@dataclass
class UsageLedger:
    """实验步数/评估消耗账本(JSONL;fail-closed 超限)。"""

    path: Path
    used: dict = field(default_factory=lambda: dict(
        ppo_steps=0, eval_steps=0, gen_calls=0, episodes=0))

    def __post_init__(self) -> None:
        self.path = Path(self.path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            for line in self.path.read_text(
                    encoding="utf-8").splitlines():
                if line.strip():
                    rec = json.loads(line)
                    for k in self.used:
                        self.used[k] += rec.get(k, 0)

    def charge(self, *, ppo_steps: int = 0, eval_steps: int = 0,
               gen_calls: int = 0, episodes: int = 0,
               tag: str = "") -> None:
        self.used["ppo_steps"] += ppo_steps
        self.used["eval_steps"] += eval_steps
        self.used["gen_calls"] += gen_calls
        self.used["episodes"] += episodes
        if (self.used["ppo_steps"] > BUDGET["new_ppo_total"]
                or self.used["eval_steps"]
                > BUDGET["eval_no_grad_steps"]):
            raise RuntimeError(
                f"实验预算超限:{self.used}(fail closed)")
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "tag": tag, **{k: v for k, v in (
                    ("ppo_steps", ppo_steps),
                    ("eval_steps", eval_steps),
                    ("gen_calls", gen_calls),
                    ("episodes", episodes)) if v},
                "cum": dict(self.used)},
                ensure_ascii=False) + "\n")
