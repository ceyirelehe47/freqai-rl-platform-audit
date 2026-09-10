"""工作包 G:泛化等级 G0-G5。

- G0:只在训练 Episode 表现良好;
- G1:相同生成器、未见随机种子通过(G1 不得被称为真正泛化);
- G2:相同机制、参数外推通过;
- G3:未见生成器族通过(至少一个未参与训练的生成机制);
- G4:反事实、Null Control 和反作弊考试通过(课程正式毕业最低要求);
- G5:迁移到下一课程或真实环境后,Warm Start 稳定优于或不劣于
  Cold Start(可迁移预训练模型最低要求;本阶段只定义协议,
  见 transfer.py,不运行正式迁移训练)。

具体课程及格线将在阶段 2.6.2 基于 Oracle、规则和 trivial 基线校准后
冻结;本函数只输出等级(结构判定),不是收益门槛。
"""

from __future__ import annotations

from typing import Any

GRADE_ORDER = ["G0", "G1", "G2", "G3", "G4"]
GRADE_WITH_TRANSFER = "G5"


def _split_median(report: dict[str, Any], split: str) -> float | None:
    entry = report.get("by_split", {}).get(split)
    if entry is None or entry.get("n", 0) == 0:
        return None
    return float(entry["median"])


def classify_generalization(
    report: dict[str, Any],
    *,
    counterfactual_all_pass: bool | None = None,
    null_control_pass: bool | None = None,
    cheating_detected: bool = False,
) -> dict[str, Any]:
    """按结构判定 G0-G4(G5 由 transfer.py 的 Warm/Cold 协议单独判定)。

    通过定义(结构性的,非收益门槛):对应 split 的扣费收益中位数 > 0。
    """
    train = _split_median(report, "train")
    dev_seed = _split_median(report, "dev_seed_holdout")
    param_ext = _split_median(report, "param_extrapolation")
    family_holdout = _split_median(report, "family_holdout")

    gates = {
        "train_positive": train is not None and train > 0.0,
        "dev_seed_holdout_positive": dev_seed is not None and dev_seed > 0.0,
        "param_extrapolation_positive": (
            param_ext is not None and param_ext > 0.0),
        "family_holdout_positive": (
            family_holdout is not None and family_holdout > 0.0),
    }
    if not gates["train_positive"]:
        grade = "G0"
    elif not gates["dev_seed_holdout_positive"]:
        grade = "G0"
    elif not gates["param_extrapolation_positive"]:
        grade = "G1"
    elif not gates["family_holdout_positive"]:
        grade = "G2"
    else:
        grade = "G3"

    cf_ok: bool | None = counterfactual_all_pass
    if cf_ok is None and null_control_pass is not None:
        cf_ok = null_control_pass
    if grade == "G3":
        if cheating_detected:
            grade = "G3"  # 作弊另行判 SUSPECTED_CHEATING,不参与升级
        elif cf_ok is True:
            grade = "G4"
    return {
        "grade": grade,
        "gates": gates,
        "counterfactual_all_pass": cf_ok,
        "cheating_detected": cheating_detected,
        "note": (
            "G1 只是未见随机种子,不得单独称为真正泛化;G4 为课程毕业"
            "最低等级;G5 需 Warm/Cold 迁移协议(transfer.py)"
        ),
    }
