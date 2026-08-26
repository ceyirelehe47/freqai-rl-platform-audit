"""工作包 G:hidden PASS 由冻结 G4 判定器产生(median>0 不足)。"""

from __future__ import annotations

import pytest

from rl_curriculum.verdict_spec import CourseVerdictSpec, probe_course_verdict_spec


def _report(median=0.05, splits=None, vs_flat_ci=0.01, rule_diff=0.01,
            seed_ratio=0.8, turnover=0.1):
    splits = splits or {
        "train": 0.06, "dev_seed_holdout": 0.05,
        "param_extrapolation": 0.04, "family_holdout": 0.03,
    }
    return {
        "overall": {"median": median, "q10": -0.01},
        "by_split": {k: {"n": 4, "median": v} for k, v in splits.items()},
        "vs_baselines": {
            "always_flat": {"paired_diff_bootstrap": {"ci_low": vs_flat_ci}},
            "rule_trend": {"median_diff": rule_diff},
        },
        "seed_pass_ratio_vs_always_flat": seed_ratio,
        "behavior": {"median_turnover": turnover, "median_max_drawdown": 0.05},
    }


def _cf_record(name, passed=True):
    return {"test": name, "pass": passed, "extra": {}, "base": {},
            "variant": {}}


def _all_cf(passed=True):
    from rl_curriculum.verdict_spec import DEFAULT_REQUIRED_COUNTERFACTUALS

    return [_cf_record(n, passed)
            for n in DEFAULT_REQUIRED_COUNTERFACTUALS]


def _null_record(passed=True, families=(True, True, True)):
    per = {f: {"stable_positive_excess": not ok}
           for f, ok in zip(
               ("probe_null_sign", "probe_null_block", "probe_null_volstate"),
               families)}
    return {"test": "null_control", "pass": passed,
            "extra": {"per_family": per}, "base": {}, "variant": {}}


def test_median_positive_alone_does_not_pass():
    """阶段 2.6.0a 核心:overall median > 0 不再足以 PASS。"""
    spec = probe_course_verdict_spec()
    evidence = {
        "integrity_ok": True,
        "report": _report(median=0.5),
        "counterfactual_results": [],  # 没有任何反事实/Null 证据
        "cheating": {"suspected_cheating": False, "cheat_reasons": []},
    }
    v = spec.evaluate(evidence)
    assert v["status"] == "FAIL"
    assert not all(v["hard_gates"].values())


def test_all_g4_gates_pass_yields_pass():
    spec = probe_course_verdict_spec()
    evidence = {
        "integrity_ok": True,
        "report": _report(),
        "counterfactual_results": _all_cf(True) + [_null_record(True)],
        "cheating": {"suspected_cheating": False, "cheat_reasons": []},
    }
    v = spec.evaluate(evidence)
    assert v["status"] == "PASS", v["hard_gates"]
    assert v["grade"] == "G4"
    assert v["recommendation"] == "proceed"


def test_missing_required_counterfactual_fails():
    spec = probe_course_verdict_spec()
    cf = _all_cf(True) + [_null_record(True)]
    cf = [r for r in cf if r["test"] != "price_scale_invariance"]
    v = spec.evaluate({
        "integrity_ok": True, "report": _report(),
        "counterfactual_results": cf,
        "cheating": {"suspected_cheating": False}})
    assert v["status"] == "FAIL"
    assert v["hard_gates"]["counterfactual::price_scale_invariance"] is False


def test_one_null_family_positive_fails():
    spec = probe_course_verdict_spec()
    null = _null_record(passed=False, families=(True, True, False))
    v = spec.evaluate({
        "integrity_ok": True, "report": _report(),
        "counterfactual_results": _all_cf(True) + [null],
        "cheating": {"suspected_cheating": False}})
    assert v["status"] == "FAIL"
    assert v["hard_gates"]["null_control_multi_family"] is False


def test_cheating_yields_suspected_not_pass():
    spec = probe_course_verdict_spec()
    v = spec.evaluate({
        "integrity_ok": True, "report": _report(),
        "counterfactual_results": _all_cf(True) + [_null_record(True)],
        "cheating": {"suspected_cheating": True,
                     "cheat_reasons": ["episode_position"]}})
    assert v["status"] == "SUSPECTED_CHEATING"
    assert v["cheat_reasons"] == ["episode_position"]
    assert v["recommendation"] == "do_not_proceed"


def test_integrity_failure_is_exam_invalid():
    spec = probe_course_verdict_spec()
    v = spec.evaluate({
        "integrity_ok": False,
        "integrity_errors": ["sealed: pack hash mismatch"],
        "report": _report(), "counterfactual_results": [],
        "cheating": {}})
    assert v["status"] == "EXAM_INVALID"
    assert v["grade"] is None


def test_seed_holdout_negative_blocks():
    spec = probe_course_verdict_spec()
    splits = {"train": 0.06, "dev_seed_holdout": -0.02,
              "param_extrapolation": 0.04, "family_holdout": 0.03}
    v = spec.evaluate({
        "integrity_ok": True, "report": _report(splits=splits),
        "counterfactual_results": _all_cf(True) + [_null_record(True)],
        "cheating": {"suspected_cheating": False}})
    assert v["status"] == "FAIL"


def test_threshold_change_changes_verdict_hash():
    """判定阈值变化 -> 新判定器哈希(旧承诺失效)。"""
    a = probe_course_verdict_spec()
    b = CourseVerdictSpec(version=a.version, seed_pass_ratio_min=0.9)
    assert a.verdict_spec_hash() != b.verdict_spec_hash()
    with pytest.raises(Exception, match="判定器哈希"):
        b.assert_hash_binding(a.verdict_spec_hash(), context="tamper")
