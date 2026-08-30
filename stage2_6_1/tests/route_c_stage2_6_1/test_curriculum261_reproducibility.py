"""阶段 2.6.1:Reproducibility / 冻结合同 / seed namespace 测试。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS,
    CURRICULUM261_TIMEFRAME,
    curriculum261_eval_config,
    curriculum261_observation_schema,
    derive261_seed,
)
from rl_curriculum.curriculum261_pairs import generate_pair, family_specs
from rl_curriculum.curriculum261_qualification import (
    check_fresh_seed_validity,
    check_reproducibility,
)
from rl_curriculum.evaluator import select_features_strict

FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


class TestReproducibility:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_same_seed_same_episode(self, family):
        rec1 = generate_pair(family, "D1", 0, namespace="calibration")
        rec2 = generate_pair(family, "D1", 0, namespace="calibration")
        for side in ("A", "B"):
            assert rec1.episodes[side].df.equals(rec2.episodes[side].df)
            assert rec1.episodes[side].hidden.equals(
                rec2.episodes[side].hidden)
        assert (rec1.attempt_log.episode_hashes
                == rec2.attempt_log.episode_hashes)

    @pytest.mark.parametrize("family", FAMILIES)
    def test_different_seed_different_episode(self, family):
        rec1 = generate_pair(family, "D1", 0, namespace="calibration")
        rec2 = generate_pair(family, "D1", 1, namespace="calibration")
        assert not rec1.episodes["A"].df.equals(rec2.episodes["A"].df)

    @pytest.mark.parametrize("family,rung",
                             [(f, r) for f in FAMILIES for r in
                              ("D1", "D3")])
    def test_check_reproducibility_passes(self, family, rung):
        result = check_reproducibility(family, rung, 0, "calibration")
        assert result["pass"], result

    def test_fresh_seed_validity(self):
        result = check_fresh_seed_validity(8)
        assert result["pass"], result


class TestSeedNamespaces:
    def test_namespaces_are_disjoint_by_derivation(self):
        a = derive261_seed("calibration", "c1_opportunity", "D0", 0, 0)
        b = derive261_seed("qualification", "c1_opportunity", "D0", 0, 0)
        c = derive261_seed("training", "c1_opportunity", "D0", 0, 0)
        assert len({a, b, c}) == 3

    def test_unknown_namespace_rejected(self):
        with pytest.raises(Exception):
            derive261_seed("unknown_ns", "c1_opportunity", "D0", 0, 0)

    def test_ab_share_seed(self):
        # pair A/B 共享同一 seed(seed 公式不含 side)——nuisance 合同基础
        spec = family_specs()["c1_opportunity"]
        params_a = spec.generator.base_params(
            dict(spec.rung_params["D1"]), "A")
        params_b = spec.generator.base_params(
            dict(spec.rung_params["D1"]), "B")
        assert spec.generator.derive_seed(params_a, 123) == \
            spec.generator.derive_seed(params_b, 123)


class TestFrozenContracts:
    def test_six_frozen_contract_ids_unchanged(self):
        from rl_platform import versions as v

        assert v.ENV_CORE_VERSION == "RouteCEnvCore-v1.0.0"
        assert v.OBSERVATION_SPEC_VERSION == "ObservationSpec-v1"
        assert v.ACTION_SPEC_VERSION == "BinaryLongFlatAction-v1"
        assert v.REWARD_SPEC_VERSION == "NetLogEquityReward-v1"
        assert v.EXECUTION_CONTRACT_VERSION == "MarketOpenCausalExecution-v1"
        assert v.TERMINAL_LIQUIDATION_VERSION == "TerminalLiquidation-v1"

    def test_env_class_attributes_expose_frozen_versions(self):
        from rl_platform.env import AlignedLongFlatEnv

        assert AlignedLongFlatEnv.env_core_version == "RouteCEnvCore-v1.0.0"
        assert AlignedLongFlatEnv.observation_spec_version ==             "ObservationSpec-v1"
        assert AlignedLongFlatEnv.action_spec_version ==             "BinaryLongFlatAction-v1"


    def test_curriculum_eval_config_matches_frozen_ledger(self):
        cfg = curriculum261_eval_config()
        assert cfg.fee == 0.001
        assert cfg.slippage_bps == 0.0
        assert cfg.price_tick == 0.0
        assert cfg.initial_cash == 100.0
        assert cfg.window_size == 1

    def test_schema_frozen(self):
        schema = curriculum261_observation_schema()
        assert schema.observation_dim == 12
        assert schema.window_size == 1
        assert schema.dtype == "float32"
        assert schema.nuisance_slot_count == 3


class TestEpisodeContract:
    @pytest.mark.parametrize("family", FAMILIES)
    def test_episode_length_and_timeframe(self, family):
        rec = generate_pair(family, "D2", 0, namespace="calibration")
        for side in ("A", "B"):
            ep = rec.episodes[side]
            assert len(ep.df) == CURRICULUM261_EPISODE_BARS
            assert ep.spec.timeframe == CURRICULUM261_TIMEFRAME
            # 时间索引严格递增
            dates = ep.df["date"].astype("int64").to_numpy()
            assert (np.diff(dates) > 0).all()

    @pytest.mark.parametrize("family", FAMILIES)
    def test_observation_columns_match_schema(self, family):
        schema = curriculum261_observation_schema()
        rec = generate_pair(family, "D0", 0, namespace="calibration")
        feats = select_features_strict(
            rec.episodes["A"].df, schema)
        assert list(feats.columns) == list(schema.feature_names)
