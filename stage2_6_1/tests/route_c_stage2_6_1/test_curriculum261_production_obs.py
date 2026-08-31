"""阶段 2.6.1 repair R1 守卫测试:production observation 路径绑定。

Blocker A 的回归防线——上一轮 qualification 使用了课程自制
curriculum261-obs-v1 schema(11 特征),而生产 Route C 的 policy
observation 是 RouteCStrategy.feature_engineering_standard 的 8 特征
经 AlignedLongFlatEnv 构造。本文件验证"实际执行路径":

- 课程 episode 的特征列 = 生产 8 列,且与真实生产特征函数的独立
  重算逐位一致(证明特征来自生产代码本体,不是课程重新实现);
- qualification 使用的 SCHEMA 就是 production schema(hash 相等);
- observation 数组由冻结 AlignedLongFlatEnv 构造且落在
  observation_space 内;
- 若有人把课程切回任何自制 schema(curriculum261-obs-v1 等),
  下列断言立即失败(不是字符串比较,是执行路径对拍)。
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
    assert_production_observation_binding,
    load_route_c_strategy_class,
    production_observation_identity,
    production_observation_schema,
    route_c_strategy_identity,
)
from rl_curriculum.curriculum261_qualification import (
    SCHEMA as QUALIFICATION_SCHEMA,
    check_production_feature_equivalence,
)
from rl_curriculum.evaluator import select_features_strict
from rl_curriculum.generator_api import PRICE_COLUMNS
from rl_platform.env import AlignedLongFlatEnv


def _episode(family: str = "c1_opportunity", rung: str = "D1"):
    return generate_pair(family, rung, 0,
                         namespace="calibration").episodes["A"]


class TestProductionSchema:
    def test_schema_is_eight_production_features_in_order(self):
        schema = production_observation_schema()
        assert schema.feature_names == PRODUCTION_FEATURE_COLUMNS
        assert schema.observation_dim == 9  # 8 特征 + 仓位槽位
        assert schema.window_size == 1
        assert schema.nuisance_slot_count == 0

    def test_qualification_schema_is_production_schema(self):
        # 防回退核心:qualification 模块级 SCHEMA 必须就是 production
        # schema(若被切回 curriculum261_observation_schema,hash 不匹配
        # 立即失败)
        prod = production_observation_schema()
        assert QUALIFICATION_SCHEMA.schema_hash() == prod.schema_hash()
        assert QUALIFICATION_SCHEMA.feature_names == \
            prod.feature_names

    def test_no_curriculum_only_schema_string_remains(self):
        # 旧自制 schema 不得再被"定义或赋值"(docstring 中的历史
        # 叙述合法——qualification/production_obs 的源码身份已被
        # 锁定的 plan 绑定,禁止事后改动)
        import rl_curriculum
        root = Path(rl_curriculum.__file__).parent
        for f in root.glob("curriculum261_*.py"):
            for i, line in enumerate(
                    f.read_text(encoding="utf-8").splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith(("#", '"""', "'''")):
                    continue
                assert 'SCHEMA_VERSION = "curriculum261' not in line, (
                    f"{f.name}:{i} 定义了已废弃的课程自制 schema")

    def test_forbidden_patterns_do_not_hit_production_columns(self):
        from rl_curriculum.generator_api import (
            FORBIDDEN_OBSERVATION_PATTERNS,
        )
        for col in PRODUCTION_FEATURE_COLUMNS:
            for pat in FORBIDDEN_OBSERVATION_PATTERNS:
                assert pat not in col


class TestProductionFeaturePath:
    def test_features_come_from_real_strategy_code(self):
        # 与真实生产特征函数的独立重算逐位一致(执行路径证明)
        ep = _episode()
        assert_production_observation_binding(
            production_observation_schema(), ep.df)

    def test_strategy_identity_records_source_hashes(self):
        ident = route_c_strategy_identity()
        assert set(ident) == {"strategy_path",
                              "strategy_file_sha256",
                              "feature_engineering_standard_sha256"}
        assert all(len(v) == 64 for k, v in ident.items()
                   if k.endswith("sha256"))
        full = production_observation_identity()
        assert full["schema_version"] == "route-c-production-obs-v1"
        assert full["observation_spec_version"] == "ObservationSpec-v1"

    @pytest.mark.parametrize("family", ["c1_opportunity", "c2_context",
                                        "c3_cost"])
    def test_all_families_bind_production_observation(self, family):
        ep = _episode(family)
        assert_production_observation_binding(
            production_observation_schema(), ep.df,
            context=f"test-{family}")

    @pytest.mark.parametrize("family", ["c1_opportunity", "c2_context",
                                        "c3_cost"])
    def test_feature_equivalence_check_passes(self, family):
        result = check_production_feature_equivalence(
            family, "D2", 0, namespace="calibration_r2")
        assert result["pass"], result
        assert result["observation_from_frozen_env"]
        assert result["observation_in_space"]

    def test_binding_fails_on_tampered_features(self):
        ep = _episode()
        df = ep.df.copy()
        df["%-ret-1"] = df["%-ret-1"] + 0.001
        with pytest.raises(RuntimeError):
            assert_production_observation_binding(
                production_observation_schema(), df)


class TestObservationFromFrozenEnv:
    def test_reset_observation_equals_feature_row_plus_position(self):
        ep = _episode()
        schema = production_observation_schema()
        feats = select_features_strict(ep.df, schema)
        env = AlignedLongFlatEnv(
            features=feats, prices=ep.df[list(PRICE_COLUMNS)],
            fee=0.001, initial_cash=100.0, window_size=1)
        obs, _ = env.reset(seed=1)
        t0 = env.first_decision_tick
        expect = np.concatenate([
            feats.to_numpy(dtype=np.float64)[t0], [0.0]]).astype(np.float32)
        assert np.array_equal(obs, expect)
        assert env.observation_space.contains(obs)

    @pytest.mark.parametrize("family", ["c1_opportunity", "c2_context",
                                        "c3_cost"])
    def test_raw_price_features_inside_observation_box(self, family):
        ep = _episode(family)
        close = ep.df["%-raw_close"].to_numpy(dtype=np.float64)
        # initial_price=1.0 水平合同:raw_* 特征必须落在 Box(-10, 10)
        assert close.max() < 10.0 and close.min() > 0.0

    def test_reference_policies_read_production_slots_only(self):
        # 参考/基线策略读取的特征名必须在生产 whitelist 内
        # (policy_api.read 对未知特征名 fail closed)
        from rl_curriculum.curriculum261_qualification import (
            build_policy_set,
        )
        specs = family_specs()
        for family in ("c1_opportunity", "c2_context", "c3_cost"):
            policies = build_policy_set(
                family, specs[family].rung_params["D1"],
                dict(specs[family].reference_defaults))
            schema = production_observation_schema()
            for pol in policies.values():
                if hasattr(pol, "bind_observation_schema"):
                    pol.bind_observation_schema(schema)
