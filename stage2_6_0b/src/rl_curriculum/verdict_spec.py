"""阶段 2.6.0a 工作包 G + 阶段 2.6.0b 工作包 D/E/H/I:冻结课程判定器。

CourseVerdictSpec(course-verdict-spec-v2)新增(阶段 2.6.0b):
- nuisance_equivalence: NuisanceEquivalenceSpec(双边等价区间/动作一致率/
  换手/仓位容差/变换 seed 数)——阈值预注册进入判定器哈希与密封承诺,
  不得考后调整(D4);
- anticheat replication 门槛(min_distinct_cheat_seeds /
  min_failing_cheat_episodes):每种作弊原因的真实多 seed 重复标准;
- required_null_families 更新为严格三族(sign/volstate/stochvol);
  block shuffle(probe_null_block)重新分类为
  partial_dependency_destruction,不在严格集合中(H1)。

状态四态:PASS / FAIL / SUSPECTED_CHEATING / EXAM_INVALID;
G4 硬门与判定器哈希绑定语义保留(2.6.0a)。

本阶段使用探针课程的 mock 阈值验证基础设施;正式趋势课程门槛将在
阶段 2.6.2 基于 Oracle/规则/trivial 基线校准后另行冻结。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from rl_curriculum.counterfactual import NuisanceEquivalenceSpec
from rl_curriculum.grades import classify_generalization

VERDICT_SPEC_FORMAT = "course-verdict-spec-v2"

DEFAULT_REQUIRED_COUNTERFACTUALS: tuple[str, ...] = (
    "common_prefix_future_suffix",
    "price_scale_invariance",
    "initial_price_invariance",
    "episode_length_invariance",
    "time_shift_invariance",
    "regime_order_randomization",
    "nuisance_slot_injection",
    "nuisance_slot_shuffle",
    "signal_ablation",
    "trend_direction_mirror",
    "cost_monotonicity",
    "null_control",
)


class VerdictSpecError(RuntimeError):
    """判定器 spec 损坏/证据缺失(fail closed -> EXAM_INVALID)。"""


@dataclass(frozen=True)
class CourseVerdictSpec:
    """版本化、可哈希的课程判定器(mock 阈值用于验证基础设施)。"""

    version: str
    # ---- 作弊判定门槛(工作包 J + 2.6.0b E:真实多 seed 重复)
    min_effective_net_return: float = 0.0      # 原始考试最低有效成绩(作弊判定的前提)
    min_seed_pass_ratio_for_cheat: float = 0.5
    min_replication_episodes: int = 3          # 兼容字段(= min_failing_cheat_episodes)
    min_distinct_cheat_seeds: int = 3          # 每种作弊原因的不同 seed 数下限
    min_failing_cheat_episodes: int = 3        # 每种作弊原因的失败 Episode 数下限
    # ---- nuisance 双边等价(工作包 D:预注册等价区间)
    nuisance_equivalence: NuisanceEquivalenceSpec = field(
        default_factory=NuisanceEquivalenceSpec)
    # ---- G4 硬门阈值(mock 探针课程值;正式课程 2.6.2 校准冻结)
    required_positive_splits: tuple[str, ...] = (
        "dev_seed_holdout", "param_extrapolation", "family_holdout")
    vs_always_flat_ci_low_min: float = 0.0
    vs_rule_baseline_median_diff_min: float = 0.0
    seed_pass_ratio_min: float = 0.6
    median_turnover_max: float = 0.5
    q10_min: float | None = None
    median_max_drawdown_max: float | None = None
    required_counterfactuals: tuple[str, ...] = DEFAULT_REQUIRED_COUNTERFACTUALS
    # ---- 严格 Null 家族(H2:三种不同机制;block shuffle 不在其中)
    required_null_families: tuple[str, ...] = (
        "probe_null_sign", "probe_null_volstate", "probe_null_stochvol")
    notes: str = (
        "阶段 2.6.0b mock 探针课程阈值:仅用于验证判定基础设施,"
        "不是正式趋势课程及格线(2.6.2 校准后另行冻结)")

    # -------------------------------------------------------------- 哈希
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "format": VERDICT_SPEC_FORMAT,
            "version": self.version,
            "min_effective_net_return": self.min_effective_net_return,
            "min_seed_pass_ratio_for_cheat": self.min_seed_pass_ratio_for_cheat,
            "min_replication_episodes": self.min_replication_episodes,
            "min_distinct_cheat_seeds": self.min_distinct_cheat_seeds,
            "min_failing_cheat_episodes": self.min_failing_cheat_episodes,
            "nuisance_equivalence": self.nuisance_equivalence.canonical_payload(),
            "required_positive_splits": list(self.required_positive_splits),
            "vs_always_flat_ci_low_min": self.vs_always_flat_ci_low_min,
            "vs_rule_baseline_median_diff_min": (
                self.vs_rule_baseline_median_diff_min),
            "seed_pass_ratio_min": self.seed_pass_ratio_min,
            "median_turnover_max": self.median_turnover_max,
            "q10_min": self.q10_min,
            "median_max_drawdown_max": self.median_max_drawdown_max,
            "required_counterfactuals": list(self.required_counterfactuals),
            "required_null_families": list(self.required_null_families),
            "notes": self.notes,
        }

    def canonical(self) -> str:
        return json.dumps(
            self.canonical_payload(), sort_keys=True,
            separators=(",", ":"), ensure_ascii=False,
        )

    def verdict_spec_hash(self) -> str:
        return "v-" + hashlib.sha256(self.canonical().encode("utf-8")).hexdigest()

    def assert_hash_binding(self, expected_hash: str, *, context: str = "") -> None:
        actual = self.verdict_spec_hash()
        if actual != expected_hash:
            raise VerdictSpecError(
                f"[{context}] 判定器哈希不匹配:期望 {expected_hash},实际 "
                f"{actual}(阈值/硬门/等价区间/复制门槛任何变化都会改变判定器;"
                f"不得用修改后的判定规则继续声称同一考试)")

    # -------------------------------------------------------------- 判定
    def evaluate(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """按冻结硬门输出四态判定与 G0-G4 等级。

        evidence 结构:
        - integrity_ok: bool;integrity_errors: [str]
          (sealed 校验失败/评估异常/Episode 无效 -> EXAM_INVALID);
        - report: evaluate_policy 输出(候选);
        - counterfactual_results: [PairResult.to_record(), ...];
        - cheating: classify_cheating 输出;
        - replication_evidence: {reason: build_replication_evidence 输出}
          (2.6.0b E:缺失崩溃证据的 required 反作弊 -> EXAM_INVALID)。
        """
        integrity_errors = list(evidence.get("integrity_errors") or [])
        if not evidence.get("integrity_ok", True) or integrity_errors:
            return {
                "status": "EXAM_INVALID",
                "grade": None,
                "hard_gates": {},
                "integrity_errors": integrity_errors,
                "score_band": None,
                "recommendation": "do_not_proceed",
                "verdict_spec_hash": self.verdict_spec_hash(),
            }
        report = evidence.get("report")
        if not isinstance(report, dict):
            raise VerdictSpecError("evidence.report 缺失(EXAM_INVALID 应在上游拦截)")
        cf_records = list(evidence.get("counterfactual_results") or [])
        cheating = evidence.get("cheating") or {
            "suspected_cheating": False, "cheat_reasons": []}

        # E3:required 反作弊原因被检出依赖但缺少优势崩溃证据 ->
        # 证据链不完整,不得默认成立,也不得给分:EXAM_INVALID
        missing_collapse = list(
            cheating.get("missing_collapse_evidence") or [])
        if missing_collapse:
            return {
                "status": "EXAM_INVALID",
                "grade": None,
                "hard_gates": {},
                "integrity_errors": [
                    f"required 反作弊原因缺少优势崩溃证据(不得默认成立): "
                    f"{missing_collapse}"],
                "score_band": None,
                "recommendation": "do_not_proceed",
                "verdict_spec_hash": self.verdict_spec_hash(),
            }

        by_cf = {r.get("test"): r for r in cf_records}
        gates: dict[str, bool] = {}

        def split_median(split: str) -> float | None:
            entry = report.get("by_split", {}).get(split)
            if entry is None or entry.get("n", 0) == 0:
                return None
            return float(entry["median"])

        for split in self.required_positive_splits:
            m = split_median(split)
            gates[f"split_positive::{split}"] = m is not None and m > 0.0

        vs = report.get("vs_baselines") or {}
        flat_ci = (vs.get("always_flat") or {}).get("paired_diff_bootstrap") or {}
        gates["vs_always_flat_bootstrap_ci_low_positive"] = bool(
            flat_ci.get("ci_low") is not None
            and float(flat_ci["ci_low"]) > self.vs_always_flat_ci_low_min)
        rule = vs.get("rule_trend") or {}
        rule_med = rule.get("median_diff")
        gates["vs_rule_baseline_median_diff"] = bool(
            rule_med is not None
            and float(rule_med) > self.vs_rule_baseline_median_diff_min)

        gates["seed_pass_ratio"] = bool(
            report.get("seed_pass_ratio_vs_always_flat", 0.0)
            >= self.seed_pass_ratio_min)
        gates["median_turnover_bounded"] = bool(
            report.get("behavior", {}).get("median_turnover", 1.0)
            <= self.median_turnover_max)
        overall = report.get("overall") or {}
        if self.q10_min is not None:
            gates["q10_threshold"] = bool(
                overall.get("q10") is not None
                and float(overall["q10"]) >= self.q10_min)
        if self.median_max_drawdown_max is not None:
            gates["max_drawdown_bounded"] = bool(
                report.get("behavior", {}).get("median_max_drawdown", 1.0)
                <= self.median_max_drawdown_max)

        for name in self.required_counterfactuals:
            rec = by_cf.get(name)
            if rec is None:
                # 未运行的必须考试 -> 硬门失败(fail closed,不得缺考)
                gates[f"counterfactual::{name}"] = False
            else:
                gates[f"counterfactual::{name}"] = bool(rec.get("pass"))

        null_rec = by_cf.get("null_control")
        if null_rec is None:
            gates["null_control_multi_family"] = False
        else:
            per_family = (null_rec.get("extra") or {}).get("per_family") or {}
            covered = all(f in per_family for f in self.required_null_families)
            gates["null_control_multi_family"] = bool(
                null_rec.get("pass") and covered)

        gates["no_cheating_evidence"] = not bool(cheating.get("suspected_cheating"))

        grade_info = classify_generalization(
            report,
            counterfactual_all_pass=all(
                gates.get(f"counterfactual::{n}", False)
                for n in self.required_counterfactuals),
            null_control_pass=gates.get("null_control_multi_family", False),
            cheating_detected=bool(cheating.get("suspected_cheating")),
        )
        grade = grade_info["grade"]

        if bool(cheating.get("suspected_cheating")):
            status = "SUSPECTED_CHEATING"
        elif grade == "G4" and all(gates.values()):
            status = "PASS"
        else:
            status = "FAIL"

        # 非敏感粗粒度分数带(工作包 H:不泄露具体收益/分位数)
        med = overall.get("median")
        if med is None:
            band = None
        elif med <= -0.01:
            band = "band_losing"
        elif med <= 0.0:
            band = "band_nonpositive"
        elif med <= 0.01:
            band = "band_small_positive"
        else:
            band = "band_positive"

        return {
            "status": status,
            "grade": grade,
            "hard_gates": gates,
            "integrity_errors": [],
            "score_band": band,
            "cheat_reasons": list(cheating.get("cheat_reasons") or []),
            "grade_info": grade_info,
            "replication_evidence": evidence.get("replication_evidence") or {},
            "recommendation": "proceed" if status == "PASS" else "do_not_proceed",
            "verdict_spec_hash": self.verdict_spec_hash(),
        }


def probe_course_verdict_spec() -> CourseVerdictSpec:
    """审计探针课程的 mock 判定器(阈值仅用于验证基础设施)。"""
    return CourseVerdictSpec(version="probe-course-verdict-mock-v2")


def verdict_spec_from_json(data: dict[str, Any]) -> CourseVerdictSpec:
    """从 canonical payload 重建判定器(mock_sealed_exam 上下文载入)。"""
    ne = data.get("nuisance_equivalence") or {}
    return CourseVerdictSpec(
        version=data["version"],
        min_effective_net_return=float(data["min_effective_net_return"]),
        min_seed_pass_ratio_for_cheat=float(
            data["min_seed_pass_ratio_for_cheat"]),
        min_replication_episodes=int(data["min_replication_episodes"]),
        min_distinct_cheat_seeds=int(data.get("min_distinct_cheat_seeds", 3)),
        min_failing_cheat_episodes=int(
            data.get("min_failing_cheat_episodes",
                     data.get("min_replication_episodes", 3))),
        nuisance_equivalence=NuisanceEquivalenceSpec(
            delta_return=float(ne.get("delta_return", 0.002)),
            action_match_min=float(ne.get("action_match_min", 0.98)),
            turnover_abs_tol=float(ne.get("turnover_abs_tol", 0.02)),
            position_abs_tol=float(ne.get("position_abs_tol", 0.02)),
            n_transform_seeds=int(ne.get("n_transform_seeds", 3)),
            bootstrap_iters=int(ne.get("bootstrap_iters", 2000)),
            bootstrap_alpha=float(ne.get("bootstrap_alpha", 0.05)),
        ),
        required_positive_splits=tuple(data["required_positive_splits"]),
        vs_always_flat_ci_low_min=float(data["vs_always_flat_ci_low_min"]),
        vs_rule_baseline_median_diff_min=float(
            data["vs_rule_baseline_median_diff_min"]),
        seed_pass_ratio_min=float(data["seed_pass_ratio_min"]),
        median_turnover_max=float(data["median_turnover_max"]),
        q10_min=data.get("q10_min"),
        median_max_drawdown_max=data.get("median_max_drawdown_max"),
        required_counterfactuals=tuple(data["required_counterfactuals"]),
        required_null_families=tuple(data["required_null_families"]),
        notes=data.get("notes", ""),
    )
