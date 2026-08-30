"""阶段 2.6.1:因果矩阵 / latent 隔离 / pair integrity 测试。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    curriculum261_observation_schema,
)
from rl_curriculum.curriculum261_pairs import (
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_qualification import (
    check_htf_resample_equivalence,
    check_latent_isolation,
    check_observation_causality,
    check_reference_causality,
)

FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


class TestObservationCausality:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_future_noise_mutation_keeps_prefix_observation(
            self, family):
        result = check_observation_causality(family, "D2", 0)
        assert result["pass"], result


class TestHtfCausality:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_htf_features_equal_causal_resample(self, family):
        result = check_htf_resample_equivalence(family, "D2", 0)
        assert result["pass"], result

    def test_features_are_prefix_recomputable(self):
        # generator_api 的前缀重算校验在 generate() 内自动执行;
        # 此处显式再验证一次(截断重算特征逐位一致)
        for family in FAMILIES:
            spec = family_specs()[family]
            rp = dict(spec.rung_params["D1"])
            rp["cur261_rung"] = "D1"
            ep = spec.generator.generate(
                spec.generator.base_params(rp, "A"), 20260830,
                split="curriculum261_causality", timeframe="15m")
            cut = 120
            prefix = ep.df.iloc[:cut][
                ["date", "open", "high", "low", "close", "volume"]].copy()
            rebuilt = spec.generator._attach_features(prefix)  # noqa: SLF001
            for col in ("ret_1", "htf_1h_mom", "htf_4h_mom", "vol_24"):
                a = ep.df[col].iloc[:cut].to_numpy(dtype=np.float64)
                b = rebuilt[col].to_numpy(dtype=np.float64)
                assert np.array_equal(a, b), (family, col)


class TestReferenceCausality:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_same_observation_same_action(self, family):
        spec = family_specs()[family]
        result = check_reference_causality(
            family, dict(spec.rung_params["D1"]),
            dict(spec.reference_defaults))
        assert result["pass"], result


class TestLatentIsolation:
    def test_sidecar_never_enters_observation(self):
        records = [generate_pair(f, "D1", 0, namespace="calibration")
                   for f in FAMILIES]
        result = check_latent_isolation(records)
        assert result["pass"], result
        assert result["sidecar_observation_overlap"] == []
        assert result["forbidden_pattern_hits"] == []


class TestPairIntegrity:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_pairs_pass_integrity(self, family):
        for rung in ("D0", "D3"):
            rec = generate_pair(family, rung, 0, namespace="calibration")
            assert rec.integrity_ok, (
                family, rung, rec.integrity)

    @pytest.mark.parametrize("family", FAMILIES)
    def test_pair_shares_nuisance_tables(self, family):
        rec = generate_pair(family, "D2", 1, namespace="calibration")
        n = rec.integrity["nuisance"]
        assert n["same_length"]
        assert n["same_initial_price"]
        assert n["volume_identical"]
        assert n["nuisance_slots_identical"]
        assert n["vol24_ratio_in_range"]

    @pytest.mark.parametrize("family", FAMILIES)
    def test_pair_is_not_two_random_episodes(self, family):
        rec = generate_pair(family, "D1", 0, namespace="calibration")
        c = rec.integrity["construction"]
        shared = [k for k in c if k.startswith("shared_")]
        assert shared and all(c[k] for k in shared), c
        assert c["causal_diff_ok"]
