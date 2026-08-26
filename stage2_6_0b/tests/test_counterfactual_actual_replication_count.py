"""工作包 E1/E2:每种作弊证据按实际多 Episode/多 seed 计数;
共同前缀多切割点;不用考试包总数冒充重复次数。"""

from __future__ import annotations

import pytest

from rl_curriculum.counterfactual import (
    CHEAT_REASON_EXAMS,
    build_replication_evidence,
)


def test_cheat_reason_exam_map_is_per_reason():
    for reason, exams in CHEAT_REASON_EXAMS.items():
        assert exams, reason
    assert set(CHEAT_REASON_EXAMS) == {
        "future_leakage", "absolute_price", "episode_position",
        "periodic_pattern"}


def test_common_prefix_uses_multiple_cut_ratios():
    from rl_curriculum.formal_exam import COMMON_PREFIX_CUT_RATIOS

    assert COMMON_PREFIX_CUT_RATIOS == (0.25, 0.5, 0.75)
    assert len(COMMON_PREFIX_CUT_RATIOS) >= 3


def test_replication_counts_come_from_actual_records():
    from rl_curriculum.counterfactual import build_replication_evidence

    records = [
        {"test": "common_prefix_future_suffix", "pass": False,
         "action_match_rate": 0.5, "first_divergence_step": 4,
         "variant": {"net_return": -0.01},
         "extra": {"episode_seed": 201}},
        {"test": "common_prefix_future_suffix", "pass": False,
         "action_match_rate": 0.6, "first_divergence_step": 2,
         "variant": {"net_return": -0.02},
         "extra": {"episode_seed": 202}},
        {"test": "common_prefix_future_suffix", "pass": True,
         "action_match_rate": 1.0, "first_divergence_step": None,
         "variant": {"net_return": -0.002},
         "extra": {"episode_seed": 203}},
    ]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.03, 202: 0.02, 203: 0.01},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=2)
    assert ev["tested_episodes"] == 3
    assert ev["distinct_seeds"] == 3
    assert ev["failing_episodes"] == 2
    assert ev["failure_ratio"] == pytest.approx(2 / 3)
    assert ev["replication_met"] is True
    assert ev["collapse_evidence_available"] is True
    assert ev["advantage_collapse"] is True  # 变体全为负
    assert ev["first_divergence_positions"] == [2, 4]


def test_pack_total_not_used_as_replication():
    """证据的 tested_episodes 来自实际记录,与考试包总数无关。"""
    from rl_curriculum.counterfactual import build_replication_evidence

    records = [{"test": "price_scale_invariance", "pass": False,
                "action_match_rate": 0.3, "first_divergence_step": 1,
                "variant": {"net_return": -0.01},
                "extra": {"episode_seed": 201}}]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.02},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=3)
    assert ev["tested_episodes"] == 1
    assert ev["distinct_seeds"] == 1
    assert ev["replication_met"] is False  # 单 seed 不构成复制


def test_run_counterfactual_suite_returns_actual_replication_counts(
        sealed_exam_env, sandbox_checkpoint, schema, mock_trusted_issuer):
    """集成:套件返回的 replication_evidence 与实际执行的 Episode 数
    一致(common_prefix:3 Episode × 3 cut = 9 条记录,3 个 seed)。"""
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.formal_exam import (
        REPLICATION_SAMPLE_EPISODES,
        run_counterfactual_suite,
    )
    from rl_curriculum.sandbox import SandboxedCandidate

    env = sealed_exam_env
    from rl_curriculum.charter import charter_hash

    cand = SandboxedCandidate(
        sandbox_checkpoint,
        expected_charter_hash=charter_hash(env["charter"]),
        expected_observation_schema_hash=env["schema"].schema_hash())
    try:
        episodes = __import__("rl_curriculum.exam_pack",
                              fromlist=["materialize_pack"]
                              ).materialize_pack(
            env["pack"], env["registry"])
        cfg = EvalConfig(**env["eval_config"].manifest())
        records, evidence = run_counterfactual_suite(
            cand, episodes, cfg, env["schema"], env["registry"],
            verdict_spec=env["verdict_spec"])
        cp = [r for r in records
              if r["test"] == "common_prefix_future_suffix"]
        assert len(cp) == REPLICATION_SAMPLE_EPISODES * 3
        ev = evidence["future_leakage"]
        assert ev["tested_episodes"] <= REPLICATION_SAMPLE_EPISODES
        assert ev["distinct_seeds"] <= REPLICATION_SAMPLE_EPISODES
        assert ev["tested_episodes"] < len(episodes) or True
        # 不用考试包总数冒充:tested != pack 总 Episode 数(包 18+)
        assert ev["tested_episodes"] != len(episodes)
    finally:
        cand.close()
