"""工作包 L:G5 迁移考试协议(Warm Start vs Cold Start)与空白演示。

协议(每次从课程 A 迁移到课程 B):
- Warm Start:加载课程 A 毕业 checkpoint;
- Cold Start:随机初始化;
- 要求完全相同的:课程 B 环境、课程 B 数据、随机种子、训练预算、
  模型容量、PPO 参数、考试包、评估次数;
- 比较:达到及格线所需步数、最终隐藏考试成绩、多 seed 中位数、
  最差分位数、换手、旧课程能力遗忘、Warm−Cold 的 paired bootstrap 区间。

结论:
- POSITIVE_TRANSFER:Warm Start 稳定优于 Cold Start;
- NEUTRAL_TRANSFER:无显著优势也无明显更差;
- NEGATIVE_TRANSFER:Warm Start 稳定更差(不得强行微调保留预训练;
  允许放弃旧 checkpoint,保留 Cold Start 路线,记录污染来源)。

本阶段不运行正式迁移训练:run_blank_demo 用占位策略在相同协议骨架上
跑空白演示(demo_only=true),证明协议可执行、可复现、结论可机读。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from rl_curriculum.evaluator import paired_bootstrap_ci, summarize_returns

TRANSFER_PROTOCOL_VERSION = "transfer-protocol-v1"


@dataclass
class TransferArm:
    """一条迁移臂:warm(加载课程 A checkpoint)或 cold(随机初始化)。"""

    name: str                    # "warm" | "cold"
    policy_factory: Callable[[], Any]  # 相同训练预算/种子下可重复构造
    origin: str                  # "course_A_checkpoint" | "random_init"


@dataclass
class TransferProtocolSpec:
    """迁移考试必须完全相同的要素(进入 manifest)。"""

    target_course_charter_hash: str
    exam_pack_hash: str
    seeds: list[int]
    training_budget_steps: int
    model_capacity: dict
    ppo_params: dict
    n_eval_runs: int

    def manifest(self) -> dict[str, Any]:
        return {
            "protocol_version": TRANSFER_PROTOCOL_VERSION,
            "target_course_charter_hash": self.target_course_charter_hash,
            "exam_pack_hash": self.exam_pack_hash,
            "seeds": list(self.seeds),
            "training_budget_steps": self.training_budget_steps,
            "model_capacity": dict(self.model_capacity),
            "ppo_params": dict(self.ppo_params),
            "n_eval_runs": self.n_eval_runs,
        }


def conclude_transfer(
    warm_scores: list[float], cold_scores: list[float]
) -> dict[str, Any]:
    """配对比较 Warm − Cold(逐 seed 配对,paired bootstrap 95% 区间)。"""
    if len(warm_scores) != len(cold_scores) or not warm_scores:
        raise ValueError("Warm/Cold 臂 seed 数必须一致且非空")
    diffs = [w - c for w, c in zip(warm_scores, cold_scores)]
    boot = paired_bootstrap_ci(diffs)
    if boot["ci_low"] > 0:
        verdict = "POSITIVE_TRANSFER"
    elif boot["ci_high"] < 0:
        verdict = "NEGATIVE_TRANSFER"
    else:
        verdict = "NEUTRAL_TRANSFER"
    return {
        "verdict": verdict,
        "warm": summarize_returns(warm_scores),
        "cold": summarize_returns(cold_scores),
        "paired_diff_bootstrap": boot,
        "policy_on_negative_transfer": (
            "NEGATIVE_TRANSFER 时不得强行微调保留预训练;允许放弃旧 "
            "checkpoint,保留 Cold Start 路线,记录污染来源"
        ),
    }


def run_blank_demo(
    spec: TransferProtocolSpec,
    eval_arm: Callable[[TransferArm, int], float],
) -> dict[str, Any]:
    """空白演示:两条臂用同一占位策略工厂,相同 seed 逐个评估。

    eval_arm(arm, seed) -> score 由调用方提供(演示用恒等分数或
    固定公式);正式迁移训练(阶段 2.6.x)将替换为真实训练+评估。
    """
    warm = TransferArm("warm", lambda: object(), "course_A_checkpoint")
    cold = TransferArm("cold", lambda: object(), "random_init")
    warm_scores = [float(eval_arm(warm, s)) for s in spec.seeds]
    cold_scores = [float(eval_arm(cold, s)) for s in spec.seeds]
    result = conclude_transfer(warm_scores, cold_scores)
    return {
        "demo_only": True,
        "note": (
            "空白演示:仅验证 G5 协议可执行与结论可机读;"
            "未运行正式迁移训练(阶段 2.6.0 范围外)"
        ),
        "protocol": spec.manifest(),
        **result,
    }
