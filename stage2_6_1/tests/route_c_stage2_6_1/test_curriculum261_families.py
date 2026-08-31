"""阶段 2.6.1:C1/C2/C3 family 语义测试。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    curriculum261_eval_config,
)
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_qualification import evaluate_pair_corpus
from rl_curriculum.evaluator import run_policy_episode
from rl_curriculum.policies import AlwaysFlatPolicy, AlwaysLongPolicy

from rl_curriculum.curriculum261_production_obs import (
    production_observation_schema,
)
SCHEMA = production_observation_schema()
CFG = curriculum261_eval_config()


def _mini_corpus(family, rungs=("D0", "D3"), n=2):
    return [generate_pair(family, r, i, namespace="calibration_r2")
            for r in rungs for i in range(n)]


class TestC1:
    def test_both_opportunity_and_flat_regions_exist(self):
        for rung in ("D0", "D3"):
            rec = generate_pair("c1_opportunity", rung, 0,
                                namespace="calibration_r2")
            h = rec.episodes["A"].hidden
            states = h["seg_state"].to_numpy()
            assert (states == 2).sum() >= 12  # opp 区域存在
            assert (states != 2).sum() >= 12  # flat/neg 区域存在
            # regime 转变存在
            assert (np.diff(states) != 0).sum() >= 2

    def test_always_long_not_universal_on_a_side(self):
        # A 侧净漂移为 0 -> always_long 只输摩擦;variant B 无漂移同理
        for rung in ("D0", "D3"):
            rec = generate_pair("c1_opportunity", rung, 0,
                                namespace="calibration_r2")
            for side in ("A", "B"):
                ep = rec.episodes[side]
                r = run_policy_episode(AlwaysLongPolicy(), ep, CFG, SCHEMA)
                # 净漂移按构造抵消:always_long 收益应显著小于机会区漂移
                assert r.net_return < 0.05

    def test_reference_beats_constants_on_mini_corpus(self):
        records = _mini_corpus("c1_opportunity")
        spec = family_specs()["c1_opportunity"]
        ev = evaluate_pair_corpus(
            records, "c1_opportunity", spec.rung_params["D0"],
            dict(spec.reference_defaults))
        assert ev["policy_means"]["reference"] > 0.0
        assert ev["policy_means"]["reference"] > max(
            ev["policy_means"]["always_long"], 0.0)


class TestC2:
    def test_local_cue_gating_structure_exists(self):
        rec = generate_pair("c2_context", "D2", 0, namespace="calibration_r2")
        for side in ("A", "B"):
            h = rec.episodes[side].hidden
            cue = h["cue_dir"].to_numpy()
            gate = (h["wick_dir_state"].to_numpy() if side == "A"
                    else h["wick_width_state"].to_numpy())
            # 两种门控极性都与 cue 共存(对比性前提)
            assert ((cue != 0) & (gate > 0)).sum() >= 1
            assert ((cue != 0) & (gate < 0)).sum() >= 1

    def test_gate_binding_swaps_between_variants(self):
        rec = generate_pair("c2_context", "D1", 0, namespace="calibration_r2")
        c = rec.integrity["construction"]
        assert c["A_gate_is_wick_dir"] and c["B_gate_is_wick_width"]
        assert c["A_payoff_bound_to_dir"]
        assert c["B_payoff_bound_to_width"]
        assert c["A_payoff_not_bound_to_width"]
        assert c["B_payoff_not_bound_to_dir"]

    def test_local_only_is_limited(self):
        # local-only 只看局部 cue:在两个 variant 上 E[payoff]=0,
        # 只输摩擦(聚合显著为负或接近零,绝不可能稳定为正)
        records = _mini_corpus("c2_context", rungs=("D0", "D3"), n=3)
        spec = family_specs()["c2_context"]
        ev = evaluate_pair_corpus(
            records, "c2_context", spec.rung_params["D3"],
            dict(spec.reference_defaults))
        assert ev["policy_means"]["c2_local_only"] < \
            ev["policy_means"]["reference"]


class TestC3:
    def test_friction_constant_comes_from_frozen_ledger(self):
        from rl_curriculum.curriculum261_c3 import (
            FRICTION, FRICTION_BPS)
        from rl_curriculum.null_friction import \
            ledger_round_trip_retention
        expected = 1.0 - ledger_round_trip_retention(
            fee=0.001, slippage=0.0)
        assert FRICTION == pytest.approx(expected, rel=1e-12)
        assert FRICTION_BPS == pytest.approx(19.98, abs=0.01)

    def test_above_and_below_cost_signals_exist_on_a(self):
        rec = generate_pair("c3_cost", "D2", 0, namespace="calibration_r2")
        h = rec.episodes["A"].hidden
        above = (h["above_cost"].to_numpy() == 1).sum()
        below = ((h["sig_dir"].to_numpy() != 0)
                 & (h["distractor_flag"].to_numpy() == 0)
                 & (h["above_cost"].to_numpy() == 0)).sum()
        assert above >= 2 and below >= 2

    def test_b_variant_all_below_cost_and_decoupled(self):
        rec = generate_pair("c3_cost", "D3", 0, namespace="calibration_r2")
        c = rec.integrity["construction"]
        assert c["B_all_below_cost"] and c["B_gross_constant"]
        assert c["A_gross_monotone_in_strength"] and c["A_has_above_cost"]

    def test_cost_aware_beats_cost_ignorant(self):
        records = _mini_corpus("c3_cost", rungs=("D1", "D3"), n=3)
        spec = family_specs()["c3_cost"]
        ev = evaluate_pair_corpus(
            records, "c3_cost", spec.rung_params["D1"],
            dict(spec.reference_defaults))
        assert ev["policy_means"]["reference"] > \
            ev["policy_means"]["c3_cost_ignorant"]


class TestAlwaysFlat:
    @pytest.mark.parametrize("family", FAMILIES_ := (
            "c1_opportunity", "c2_context", "c3_cost"))
    def test_always_flat_is_exactly_zero(self, family):
        rec = generate_pair(family, "D1", 0, namespace="calibration_r2")
        r = run_policy_episode(AlwaysFlatPolicy(),
                               rec.episodes["A"], CFG, SCHEMA)
        assert r.net_return == pytest.approx(0.0, abs=1e-12)
