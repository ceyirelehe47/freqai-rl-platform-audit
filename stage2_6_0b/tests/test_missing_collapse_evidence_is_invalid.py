"""工作包 E3(专文件):缺少优势崩溃证据 -> EXAM_INVALID / 证据不足,
绝不默认成立。"""

from __future__ import annotations


def _missing_evidence_records():
    seeds = [201, 202, 203]
    return [
        {"test": "common_prefix_future_suffix", "pass": False,
         "action_match_rate": 0.4, "first_divergence_step": 1,
         "variant": {},  # 关键:无变体收益数据
         "extra": {"episode_seed": s}}
        for s in seeds
    ]


def test_missing_collapse_evidence_flagged_not_assumed():
    from rl_curriculum.counterfactual import (
        build_replication_evidence,
        classify_cheating,
    )

    records = _missing_evidence_records()
    ev = build_replication_evidence(
        records, base_net_by_episode={}, min_effective_net_return=0.0,
        min_distinct_seeds=3, min_failing_episodes=3)
    assert ev["collapse_evidence_available"] is False
    assert ev["advantage_collapse"] is False  # 不默认成立
    out = classify_cheating(
        [type("R", (), {"name": r["test"], "pass_": r["pass"],
                        "extra": r["extra"], "base": {}, "variant": {}})()
         for r in records],
        base_median_net_return=0.02, base_seed_pass_ratio=0.8,
        replication_evidence={"future_leakage": ev},
        min_effective_net_return=0.0, min_seed_pass_ratio=0.5,
        min_distinct_seeds=3, min_failing_episodes=3)
    assert not out["suspected_cheating"]
    assert "future_leakage" in out["missing_collapse_evidence"]


def test_required_exam_missing_collapse_is_exam_invalid():
    from rl_curriculum.counterfactual import (
        build_replication_evidence,
        classify_cheating,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    records = _missing_evidence_records()
    ev = build_replication_evidence(
        records, base_net_by_episode={}, min_effective_net_return=0.0,
        min_distinct_seeds=3, min_failing_episodes=3)
    cheating = classify_cheating(
        [type("R", (), {"name": r["test"], "pass_": r["pass"],
                        "extra": r["extra"], "base": {}, "variant": {}})()
         for r in records],
        base_median_net_return=0.02, base_seed_pass_ratio=0.8,
        replication_evidence={"future_leakage": ev},
        min_effective_net_return=0.0)
    verdict = probe_course_verdict_spec().evaluate({
        "integrity_ok": True, "integrity_errors": [],
        "report": {"overall": {"median": 0.01, "q10": None},
                   "by_split": {}, "behavior": {}, "vs_baselines": {},
                   "seed_pass_ratio_vs_always_flat": 0.8},
        "counterfactual_results": records,
        "cheating": cheating,
        "replication_evidence": {"future_leakage": ev},
    })
    assert verdict["status"] == "EXAM_INVALID"
    assert any("缺少优势崩溃证据" in e
               for e in verdict["integrity_errors"])


def test_diagnostic_reason_missing_collapse_is_insufficient():
    from rl_curriculum.counterfactual import (
        build_replication_evidence,
        classify_cheating,
    )

    records = [
        {"test": "regime_order_randomization", "pass": False,
         "action_match_rate": 0.5, "first_divergence_step": 1,
         "variant": {},
         "extra": {"episode_seed": s}}
        for s in (201, 202, 203)
    ]
    ev = build_replication_evidence(
        records, base_net_by_episode={}, min_effective_net_return=0.0,
        min_distinct_seeds=3, min_failing_episodes=3)
    out = classify_cheating(
        [type("R", (), {"name": r["test"], "pass_": r["pass"],
                        "extra": r["extra"], "base": {}, "variant": {}})()
         for r in records],
        base_median_net_return=0.02, base_seed_pass_ratio=0.8,
        replication_evidence={"periodic_pattern": ev},
        min_effective_net_return=0.0)
    assert not out["suspected_cheating"]
    assert "periodic_pattern" in out["missing_collapse_evidence"]
