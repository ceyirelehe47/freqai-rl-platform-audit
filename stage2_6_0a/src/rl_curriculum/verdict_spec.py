"""阶段 2.6.0a 工作包 G:冻结课程判定器(CourseVerdictSpec)。

阶段 2.6.0 的隐藏考试 PASS 条件是 overall median return > 0——单一
收益中位数既不覆盖 G4 硬门,也无法区分普通挂科、作弊与考试无效。

本模块定义版本化、可哈希的判定器 spec:
- 判定器哈希进入 sealed commitment(E:verdict rules hash);
- 任何阈值/硬门变化 -> 新 spec 哈希 -> 旧 commitment 校验失败;
- 正式状态四态:PASS / FAIL / SUSPECTED_CHEATING / EXAM_INVALID;
- G4 硬门(全部通过才 PASS):
  1. seed holdout 中位扣费收益 > 0;
  2. 参数外推中位扣费收益 > 0;
  3. 未见生成器族中位扣费收益 > 0;
  4. 相对 Always Flat 的 paired bootstrap CI low > 0;
  5. 相对可观察规则基线优势(可配置,默认要求中位差 > 0);
  6. seed pass ratio >= 阈值;
  7. 中位换手 <= 阈值;
  8. q10 / 最大回撤阈值(可配置);
  9. 必须的反事实考试全部通过(含 nuisance/消融/镜像/成本单调);
 10. 多族 Null Control 一致通过;
 11. classify_cheating 无成立作弊证据(四门证据齐备才判作弊)。

本阶段使用探针课程的 mock 阈值验证基础设施;正式趋势课程门槛将在
阶段 2.6.2 基于 Oracle/规则/trivial 基线校准后另行冻结,不在此处
预注册。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any

from rl_curriculum.grades import classify_generalization

VERDICT_SPEC_FORMAT = "course-verdict-spec-v1"

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
    # ---- 作弊判定门槛(工作包 J:普通挂科与作弊分离)
    min_effective_net_return: float = 0.0      # 原始考试最低有效成绩(作弊判定的前提)
    min_seed_pass_ratio_for_cheat: float = 0.5
    min_replication_episodes: int = 3
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
    required_null_families: tuple[str, ...] = (
        "probe_null_sign", "probe_null_block", "probe_null_volstate")
    notes: str = (
        "阶段 2.6.0a mock 探针课程阈值:仅用于验证判定基础设施,"
        "不是正式趋势课程及格线(2.6.2 校准后另行冻结)")

    # -------------------------------------------------------------- 哈希
    def canonical_payload(self) -> dict[str, Any]:
        return {
            "format": VERDICT_SPEC_FORMAT,
            "version": self.version,
            "min_effective_net_return": self.min_effective_net_return,
            "min_seed_pass_ratio_for_cheat": self.min_seed_pass_ratio_for_cheat,
            "min_replication_episodes": self.min_replication_episodes,
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
                f"{actual}(阈值/硬门任何变化都会改变判定器;不得用修改后的"
                f"判定规则继续声称同一考试)")

    # -------------------------------------------------------------- 判定
    def evaluate(self, evidence: dict[str, Any]) -> dict[str, Any]:
        """按冻结硬门输出四态判定与 G0-G4 等级。

        evidence 结构:
        - integrity_ok: bool;integrity_errors: [str]
          (sealed 校验失败/评估异常/Episode 无效 -> EXAM_INVALID);
        - report: evaluate_policy 输出(候选);
        - counterfactual_results: [PairResult.to_record(), ...];
        - cheating: classify_cheating 输出。
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
            "recommendation": "proceed" if status == "PASS" else "do_not_proceed",
            "verdict_spec_hash": self.verdict_spec_hash(),
        }


def probe_course_verdict_spec() -> CourseVerdictSpec:
    """审计探针课程的 mock 判定器(阈值仅用于验证基础设施)。"""
    return CourseVerdictSpec(version="probe-course-verdict-mock-v1")
