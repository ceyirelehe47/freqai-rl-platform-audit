"""工作包 E3/E4/E5:单 seed 失败不判作弊;缺崩溃证据不默认成立。"""

from __future__ import annotations

import pytest


def _records(reason_exam: str, seeds, pass_flags):
    return [
        {"test": reason_exam, "pass": pass_flags[i],
         "action_match_rate": 0.5 if not pass_flags[i] else 1.0,
         "first_divergence_step": 1 if not pass_flags[i] else None,
         # 变体收益:失败记录大幅崩溃,通过记录也轻微为负(全部低于
         # min_effective=0,优势崩溃的 bootstrap 上界才稳健)
         "variant": {"net_return": -0.05 if not pass_flags[i] else -0.001},
         "extra": {"episode_seed": s, "variant_net_returns":
                   [-0.05 if not pass_flags[i] else -0.001]}}
        for i, s in enumerate(seeds)
    ]


def _classify(records, evidence, **kw):
    from rl_curriculum.counterfactual import classify_cheating

    return classify_cheating(
        [type("R", (), {"name": r["test"], "pass_": r["pass"],
                        "extra": r["extra"], "base": {}, "variant": {}})()
         for r in records],
        base_median_net_return=kw.get("base_median", 0.02),
        base_seed_pass_ratio=0.8,
        replication_evidence=evidence,
        min_effective_net_return=0.0,
        min_seed_pass_ratio=0.5,
        min_distinct_seeds=kw.get("min_seeds", 3),
        min_failing_episodes=kw.get("min_failing", 3),
    )


def _evidence(records, *, min_seeds=3, min_failing=3):
    from rl_curriculum.counterfactual import build_replication_evidence

    return build_replication_evidence(
        records, base_net_by_episode={}, min_effective_net_return=0.0,
        min_distinct_seeds=min_seeds, min_failing_episodes=min_failing)


def test_single_seed_failure_not_cheating():
    """5 个 seed 只有 1 个失败 -> 不判作弊(普通 FAIL)。"""
    seeds = [201, 202, 203, 204, 205]
    records = _records("common_prefix_future_suffix", seeds,
                       [False, True, True, True, True])
    ev = _evidence(records)
    out = _classify(records, {"future_leakage": ev})
    assert not out["suspected_cheating"]
    assert "future_leakage" not in out["cheat_reasons"]
    assert ev["failing_episodes"] == 1
    assert ev["replication_met"] is False


def test_two_seeds_failing_still_not_cheating_with_min_three():
    seeds = [201, 202, 203, 204]
    records = _records("time_shift_invariance", seeds,
                       [False, False, True, True])
    ev = _evidence(records)
    out = _classify(records, {"episode_position": ev})
    assert not out["suspected_cheating"]


def test_no_effective_score_not_cheating():
    seeds = [201, 202, 203, 204]
    records = _records("price_scale_invariance", seeds,
                       [False, False, False, False])
    ev = _evidence(records)
    out = _classify(records, {"absolute_price": ev},
                    base_median=-0.01)  # 未达最低有效成绩
    assert not out["suspected_cheating"]
    assert out["ordinary_failure_only"] is True


def test_missing_collapse_evidence_is_invalid():
    """E3:依赖被检出但缺少变体收益证据 -> missing_collapse_evidence,
    不得默认成立;判定器必须输出 EXAM_INVALID。"""
    seeds = [201, 202, 203]
    records = [
        {"test": "common_prefix_future_suffix", "pass": False,
         "action_match_rate": 0.4, "first_divergence_step": 1,
         "variant": {},  # 无变体收益
         "extra": {"episode_seed": s}}
        for s in seeds
    ]
    ev = _evidence(records)
    assert ev["collapse_evidence_available"] is False
    out = _classify(records, {"future_leakage": ev})
    assert not out["suspected_cheating"], "缺崩溃证据时不得判作弊"
    assert "future_leakage" in out["missing_collapse_evidence"]
    # 判定器:required 原因缺崩溃证据 -> EXAM_INVALID
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    verdict = probe_course_verdict_spec().evaluate({
        "integrity_ok": True, "integrity_errors": [],
        "report": {"overall": {"median": 0.01, "q10": None},
                   "by_split": {}, "behavior": {}, "vs_baselines": {},
                   "seed_pass_ratio_vs_always_flat": 0.8},
        "counterfactual_results": records,
        "cheating": out,
        "replication_evidence": {"future_leakage": ev},
    })
    assert verdict["status"] == "EXAM_INVALID"


def test_diagnostic_insufficient_evidence_not_cheating():
    seeds = [201, 202]
    records = _records("regime_order_randomization", seeds,
                       [False, False])
    ev = _evidence(records)
    out = _classify(records, {"periodic_pattern": ev})
    assert not out["suspected_cheating"]
    assert out["ordinary_failure_only"] is True


def test_no_default_collapse_in_source():
    """旧版 `if not extra_nets: return True` 已删除(源码级断言:
    检查旧实现特有的带注释代码行,模块文档中对旧语义的引述不在此列)。"""
    import inspect

    from rl_curriculum import counterfactual as cf

    src = inspect.getsource(cf)
    assert "无变体成绩可查时以反事实失败本身为准" not in src
    assert "variant_collapsed" not in src
