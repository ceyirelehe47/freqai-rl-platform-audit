"""阶段 2.6.0e 测试夹具:Null 经济摩擦、功效证明与 Pack 完整性闭环。

- 冻结账本精确摩擦 0.002/1.001 = 0.001998002(null-friction-contract-v2);
- 三态资格协议 null-qualification-v4(64 cluster x 16 原始 Episode);
- 完整资格链(报告 + 中心化四块功效分析 v2 + spec v2)共享磁盘缓存;
- pack-level validity v2(antithetic pair 完整性 + 四块硬门);
- builder manifest(npb- 绑定真实 builder);
- v5 承诺 + hidden-exam-cli-v6 全链路。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
TESTS = Path(__file__).resolve().parents[1]
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))

FAMILIES = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


@pytest.fixture(scope="session")
def schema():
    from rl_curriculum.probe_charter import probe_observation_schema

    return probe_observation_schema()


@pytest.fixture(scope="session")
def cfg():
    from rl_curriculum.mock_sealed_exam import default_eval_config

    return default_eval_config()


@pytest.fixture(scope="session")
def null_qual_chain(schema, cfg):
    """完整资格链 v2(三族报告 + 功效分析 v2 + spec v2;共享缓存)。"""
    from null_qual_cache import cached_null_qual_chain

    return cached_null_qual_chain(schema, cfg)


@pytest.fixture(scope="session")
def null_qual_reports(null_qual_chain):
    return null_qual_chain["reports"]


@pytest.fixture(scope="session")
def mock_pack():
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack

    return build_mock_hidden_pack()


@pytest.fixture(scope="session")
def mock_pack_materialized(mock_pack):
    """物化 null_control Episode(按族分组;供 pack 校验测试直接使用)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    by_family = {}
    for spec in mock_pack.episodes:
        if spec.split == "null_control":
            by_family.setdefault(spec.family, []).append(
                R[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    return by_family


@pytest.fixture(scope="session")
def pack_validity_report(mock_pack, mock_pack_materialized, schema, cfg):
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    from compat_stage2_6_0f import (
        default_duration_contract,
        mock_builder_identity,
    )

    contract = default_duration_contract()
    spec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    return validate_null_pack(
        mock_pack_materialized, cfg=cfg, schema=schema, spec=spec,
        pack_hash=mock_pack.pack_hash(),
        builder_identity=mock_builder_identity(),
        duration_contract=contract)


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_chain, schema, cfg, mock_pack,
                    pack_validity_report):
    """mock 密封考试环境(v5 承诺:runtime + spec/power/manifest 绑定)。"""
    from null_qual_cache import build_commitment_null_materials
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0e")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    charter = audit_probe_charter()
    verdict_spec = probe_course_verdict_spec()
    materials = build_commitment_null_materials(
        mock_pack, schema, cfg, chain=null_qual_chain)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=mock_pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    return {
        "pack": mock_pack,
        "charter": charter,
        "schema": schema,
        "eval_config": cfg,
        "verdict_spec": verdict_spec,
        "registry": DEFAULT_GENERATOR_REGISTRY,
        "commitment": commitment,
        "materials": materials,
        "keypair": keypair,
        "trusted_issuer": issuer,
        "null_qual_reports": null_qual_chain["reports"],
        "power_report": null_qual_chain["power_report"],
        "pack_validity_report": pack_validity_report,
        "profile": default_sandbox_profile(),
    }
