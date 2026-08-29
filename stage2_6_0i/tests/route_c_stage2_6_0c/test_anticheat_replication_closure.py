"""阶段 2.6.0c 工作包 C:反作弊复制闭环。

覆盖:
- 正式 run_counterfactual_suite 四种作弊原因均达到冻结 seed 数;
- 按冻结判定器动态计算所需样本数(无 [:2] 硬编码);
- 按 seed 聚合(多 cut 不算多 seed;bootstrap 抽样单位是 seed);
- pack seed 不足 -> EXAM_INVALID;
- 三类此前不可达的 SUSPECTED_CHEATING(absolute_price /
  episode_position / periodic_pattern)在满足证据时真实触发;
- 只有 2 个 seed 时不得判作弊;
- 永真断言清除(静态扫描)。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rl_curriculum.counterfactual import (
    build_replication_evidence,
    classify_cheating,
)
from rl_curriculum.formal_exam import run_counterfactual_suite

from tests.route_c_stage2_6_0c.conftest import (
    ALIGNED_PERIODIC_PARAMS,
    CHEAT_SCENARIO_PARAMS,
    MONOTONE_UP_PARAMS,
)

MIN_EFFECTIVE = 0.02
CHEAT_SEEDS = (211, 212, 213)


# ----------------------------------------------------------- 动态门槛(C1)
def test_required_seed_count_comes_from_frozen_spec(sealed_exam_env):
    """所需样本数 = max(min_distinct_cheat_seeds, min_failing)。"""
    vs = sealed_exam_env["verdict_spec"]
    assert vs.min_distinct_cheat_seeds == 3
    assert vs.min_failing_cheat_episodes == 3
    assert vs.seed_aggregation == "per-seed-worst-variant-v1"


def test_no_hardcoded_two_episode_slice_in_source():
    """formal_exam 源码中不存在 replication_eps[:2] 类硬编码。"""
    src = Path(__import__(
        "rl_curriculum.formal_exam", fromlist=["x"]).__file__).read_text(
        encoding="utf-8")
    assert not re.search(r"replication_eps\[:\d+\]", src), (
        "不得硬编码截取复制样本(每种原因必须按冻结门槛动态取样)")


# ------------------------------------------------------- seed 聚合(C3)
def _record(seed, *, fail=True, variant=-0.01, match=0.5, first=3,
            extra_variants=()):
    return {
        "test": "x", "pass": not fail,
        "action_match_rate": match,
        "first_divergence_step": first,
        "variant": {"net_return": variant},
        "extra": {"episode_seed": seed,
                  "variant_net_returns": list(extra_variants)},
    }


def test_multiple_cuts_same_seed_counted_once():
    """同一 seed 的 9 条 cut 记录:distinct_seeds=1,n_records=9,
    bootstrap 样本量按 seed 计(=1),不构成复制。"""
    records = [_record(201, extra_variants=(-0.02, -0.03))
               for _ in range(9)]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.03},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=3)
    assert ev["n_records"] == 9
    assert ev["distinct_seeds"] == 1
    assert ev["failing_episodes"] == 1
    assert len(ev["variant_net_returns"]) == 1  # seed 级聚合
    assert len(ev["paired_return_diffs"]) == 1
    assert ev["collapse_bootstrap"]["n"] == 1
    assert ev["replication_met"] is False
    assert ev["per_seed"][201]["n_records"] == 9


def test_seed_aggregation_perverse_rule_rejected():
    """未注册的聚合规则被拒绝(规则必须考试前冻结)。"""
    with pytest.raises(ValueError, match="聚合规则"):
        build_replication_evidence(
            [_record(1)], base_net_by_episode={1: 0.0},
            min_effective_net_return=0.0, min_distinct_seeds=3,
            min_failing_episodes=3, seed_aggregation="pick-best-cut")


def test_per_seed_worst_variant_aggregation_is_auditable():
    """seed 内聚合取最坏变体(可审计:per_seed 明细保留原始记录数与
    均值/最坏两套量)。"""
    records = [
        _record(201, variant=-0.01),
        _record(201, variant=-0.03),
        _record(202, variant=-0.02),
        _record(203, variant=0.05, fail=False, match=1.0, first=None),
    ]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.03, 202: 0.02, 203: 0.01},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=3)
    assert ev["per_seed"][201]["variant_net_worst"] == pytest.approx(-0.03)
    assert ev["per_seed"][201]["paired_diff_worst"] == pytest.approx(-0.06)
    assert ev["per_seed"][201]["variant_net_mean"] == pytest.approx(-0.02)
    assert ev["per_seed"][202]["variant_net_worst"] == pytest.approx(-0.02)
    assert ev["variant_net_returns"][0] == pytest.approx(-0.03)  # seed 201
    assert ev["distinct_seeds"] == 3
    assert ev["failing_seed_list"] == [201, 202]
    # 203 记录通过且 variant 为正 -> failing seeds 只有 2 -> 不构成复制
    assert ev["replication_met"] is False


def test_price_scale_variants_aggregate_within_seed():
    """价格尺度的多个 scale 先做 seed 内聚合(不产生独立样本)。"""
    records = [
        _record(201, variant=-0.05, extra_variants=(-0.10, -0.15)),
        _record(202, variant=-0.04, extra_variants=(-0.08, -0.12)),
        _record(203, variant=-0.06, extra_variants=(-0.09, -0.11)),
    ]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.03, 202: 0.03, 203: 0.03},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=3)
    assert len(ev["variant_net_returns"]) == 3  # 每 seed 一个聚合值
    assert ev["per_seed"][201]["variant_net_mean"] == pytest.approx(-0.10)
    assert ev["collapse_evidence_available"] is True
    assert ev["replication_met"] is True


# --------------------------------------------------- pack seed 不足(C1)
def test_pack_seed_insufficient_is_exam_invalid(sealed_exam_env, schema):
    """dev_seed_holdout 只有 2 个不同 seed -> EXAM_INVALID(不降门槛,
    不把 pack 总 Episode 数填进复制统计)。"""
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.exam_pack import materialize_pack
    from rl_curriculum.policies import AlwaysFlatPolicy
    from rl_curriculum.sealed_exam import SealedExamError

    env = sealed_exam_env
    episodes = materialize_pack(env["pack"], env["registry"])
    two_seed_eps = [e for e in episodes if e.spec.seed not in (203,)]
    # 构造只有 2 个 dev seed 的"包"(其余 split 保留)
    two_seed = [
        e for e in two_seed_eps
        if e.spec.split != "dev_seed_holdout"
        or e.spec.seed in (201, 202)]
    assert len({e.spec.seed for e in two_seed
                if e.spec.split == "dev_seed_holdout"}) == 2
    with pytest.raises(SealedExamError, match="不同 seed|门槛"):
        run_counterfactual_suite(
            AlwaysFlatPolicy(), two_seed, EvalConfig(fee=0.001), schema,
            env["registry"], verdict_spec=env["verdict_spec"])


def test_full_pack_four_reasons_meet_frozen_seed_threshold(
        sealed_exam_env, sandbox_checkpoint):
    """正式套件:四种作弊原因全部达到冻结 seed 数(3),tested seeds
    来自实际记录,pack 总 Episode 数不参与复制计算。"""
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.evaluator import EvalConfig
    from rl_curriculum.exam_pack import materialize_pack
    from rl_curriculum.sandbox import SandboxedCandidate

    env = sealed_exam_env
    cand = SandboxedCandidate(
        sandbox_checkpoint,
        expected_charter_hash=charter_hash(env["charter"]),
        expected_observation_schema_hash=env["schema"].schema_hash(),
        expected_runtime_manifest=env["commitment"].candidate_runtime_manifest)
    try:
        episodes = materialize_pack(env["pack"], env["registry"])
        cfg = EvalConfig(**env["eval_config"].manifest())
        records, evidence = run_counterfactual_suite(
            cand, episodes, cfg, env["schema"], env["registry"],
            verdict_spec=env["verdict_spec"])
        required = max(env["verdict_spec"].min_distinct_cheat_seeds,
                       env["verdict_spec"].min_failing_cheat_episodes)
        for reason in ("future_leakage", "absolute_price",
                       "episode_position", "periodic_pattern"):
            ev = evidence[reason]
            assert ev["distinct_seeds"] == required, (
                f"{reason} 实测 seed 数 {ev['distinct_seeds']}"
                f" < 冻结门槛 {required}")
            assert ev["tested_episodes"] == required
            assert ev["seed_aggregation"] == "per-seed-worst-variant-v1"
            assert ev["n_records"] >= ev["distinct_seeds"]
            # tested seeds 来自实际记录的 episode_seed
            recorded_seeds = {
                r["extra"]["episode_seed"] for r in records
                if r["test"] in _EXAMS_BY_REASON[reason]
                and r.get("extra", {}).get("episode_seed") is not None}
            assert set(ev["per_seed"]) <= recorded_seeds
            # pack 总 Episode 数不参与 replication 计算
            assert ev["distinct_seeds"] < len(episodes)
        # common_prefix:3 seed × 3 cut = 9 条记录
        cp = [r for r in records
              if r["test"] == "common_prefix_future_suffix"]
        assert len(cp) == required * 3
    finally:
        cand.close()


_EXAMS_BY_REASON = {
    "future_leakage": ("common_prefix_future_suffix",),
    "absolute_price": ("price_scale_invariance", "initial_price_invariance"),
    "episode_position": ("episode_length_invariance",
                         "time_shift_invariance"),
    "periodic_pattern": ("regime_order_randomization",),
}


# --------------------------------------------- 作弊策略集成(C6,TestOnly)
def _cheat_scene_episodes(env, params, seeds):
    """固定结构场景 episodes + 必需 Null 族(split=train 回退)。"""
    from rl_curriculum.generators import (
        DEFAULT_GENERATOR_REGISTRY as R,
        ProbeSegmentedDriftGenerator,
    )

    gen_a = ProbeSegmentedDriftGenerator()
    eps = [gen_a.generate(dict(params), seed=s, split="train",
                          timeframe="15m") for s in seeds]
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        eps.append(R[fam].generate(
            dict(params), seed=seeds[0], split="null_control",
            timeframe="15m"))
    return eps


@pytest.mark.parametrize("reason,policy_factory", [
    ("absolute_price",
     lambda: __import__("rl_curriculum.probes", fromlist=[
         "AbsolutePriceCheaterProbe"]).AbsolutePriceCheaterProbe(
         buy_below=150.0)),
    ("episode_position",
     lambda: __import__("rl_curriculum.probes", fromlist=[
         "StepCounterCheaterProbe"]).StepCounterCheaterProbe()),
    ("periodic_pattern",
     lambda: __import__("rl_curriculum.probes", fromlist=[
         "PeriodicCheaterProbe"]).PeriodicCheaterProbe(4)),
])
def test_three_seed_cheater_reaches_suspected_cheating(
        reason, policy_factory, sealed_exam_env, schema):
    """3-seed 作弊策略经正式套件 + classify_cheating + 冻结判定器
    最终 SUSPECTED_CHEATING(此前该三类的 seed 上限为 2,状态不可达)。"""
    from rl_curriculum.evaluator import evaluate_policy
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    env = sealed_exam_env
    policy = policy_factory()
    params = CHEAT_SCENARIO_PARAMS[reason]
    episodes = _cheat_scene_episodes(env, params, CHEAT_SEEDS)
    cfg = env["eval_config"]
    # 基础成绩只按探针 split 计算(null 族按构造无方向优势,计入会
    # 稀释中位数;作弊判定的 base 门以课程 split 为准)
    report = evaluate_policy(
        policy, [e for e in episodes if e.spec.split == "train"],
        cfg, env["schema"])
    assert report["overall"]["median"] > MIN_EFFECTIVE, (
        f"{reason} 场景基础成绩须达作弊判定最低有效线,实际 "
        f"{report['overall']['median']}")
    records, evidence = run_counterfactual_suite(
        policy, episodes, cfg, env["schema"], env["registry"],
        verdict_spec=env["verdict_spec"])
    cheating = classify_cheating(
        [_CfAdapter(r) for r in records],
        base_median_net_return=float(report["overall"]["median"]),
        base_seed_pass_ratio=float(
            report["seed_pass_ratio_vs_always_flat"]),
        replication_evidence=evidence,
        min_effective_net_return=MIN_EFFECTIVE,
        min_seed_pass_ratio=0.5,
        min_distinct_seeds=env["verdict_spec"].min_distinct_cheat_seeds,
        min_failing_episodes=(
            env["verdict_spec"].min_failing_cheat_episodes))
    assert cheating["suspected_cheating"], (
        f"{reason}: {cheating['reason_gates'][reason]}")
    assert reason in cheating["cheat_reasons"]
    gate = cheating["reason_gates"][reason]
    assert gate["distinct_seeds"] >= 3
    assert gate["failing_episodes"] >= 3
    # 冻结判定器最终状态
    verdict = probe_course_verdict_spec().evaluate({
        "integrity_ok": True, "integrity_errors": [],
        "report": report, "counterfactual_results": records,
        "cheating": cheating, "replication_evidence": evidence})
    assert verdict["status"] == "SUSPECTED_CHEATING", verdict["status"]


class _CfAdapter:
    """record dict -> classify_cheating 需要的最小视图。"""

    def __init__(self, record):
        self.name = record["test"]
        self.pass_ = bool(record["pass"])
        self.extra = record.get("extra") or {}
        self.base = record.get("base") or {}
        self.variant = record.get("variant") or {}


def test_two_failing_seeds_never_suspected_cheating():
    """3 seed 被测但只有 2 个失败 seed:复制门槛不满足 -> 不判作弊
    (2-seed 考试包在新设计下直接 EXAM_INVALID,不会进入评估;
    本测试锁定证据层语义:失败 seed 数不可替代)。"""
    records = [
        _record(201, variant=-0.05),
        _record(202, variant=-0.04),
        _record(203, variant=0.06, fail=False, match=1.0, first=None),
    ]
    ev = build_replication_evidence(
        records, base_net_by_episode={201: 0.03, 202: 0.03, 203: 0.03},
        min_effective_net_return=0.0, min_distinct_seeds=3,
        min_failing_episodes=3)
    assert ev["distinct_seeds"] == 3
    assert ev["failing_episodes"] == 2
    assert ev["replication_met"] is False
    gate = {
        "divergence_detected": True, "base_effective_score": True,
        "advantage_collapse": True,
        "collapse_evidence_available": True,
        "replicated": ev["replication_met"],
    }
    assert not (gate["base_effective_score"] and gate["divergence_detected"]
                and gate["advantage_collapse"] and gate["replicated"]), (
        "2 个失败 seed 不得构成 SUSPECTED_CHEATING 的第四门")


def test_periodic_aligned_scenario_uses_regime_order_exam(
        sealed_exam_env, schema):
    """周期场景的证据来自 regime_order_randomization(非周期检测器)。"""
    from rl_curriculum.probes import PeriodicCheaterProbe

    env = sealed_exam_env
    policy = PeriodicCheaterProbe(4)
    episodes = _cheat_scene_episodes(env, ALIGNED_PERIODIC_PARAMS,
                                     CHEAT_SEEDS)
    records, evidence = run_counterfactual_suite(
        policy, episodes, env["eval_config"], env["schema"],
        env["registry"], verdict_spec=env["verdict_spec"])
    assert evidence["periodic_pattern"]["distinct_seeds"] == 3
    assert evidence["periodic_pattern"]["n_records"] >= 3


# ------------------------------------------------------- 永真断言清除(C5)
def test_no_tautological_assertions_in_tests():
    """测试树中不存在恒真式断言(字面 or-True / assert-True 模式)。"""
    tests_root = Path(__file__).resolve().parents[1]
    offenders = []
    for f in tests_root.rglob("test_*.py"):
        for i, line in enumerate(f.read_text(encoding="utf-8")
                                 .splitlines(), start=1):
            code = line.split("#", 1)[0]
            if re.search(r"or\s+True\b", code) or re.search(
                    r"assert\s+True\b", code):
                offenders.append(f"{f.relative_to(tests_root)}:{i}: {line}")
    assert not offenders, offenders
