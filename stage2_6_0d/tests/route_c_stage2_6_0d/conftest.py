"""阶段 2.6.0d 测试夹具:Strict Null 统计资格与经济等价闭环(完整语义)。

- 三态资格协议 null-qualification-v3(QUALIFIED / INVALID_NULL /
  INSUFFICIENT_EVIDENCE;margin 来自 qualification spec 的精确
  往返摩擦 1-(1-fee)^2*(1-slip)^2 = 0.001999);
- 独立统计单位 seed cluster(64 cluster x 16 原始派生 Episode);
- 完整资格链(报告 + 确定性功效分析 + spec)共享磁盘缓存;
- pack-level validity(antithetic pair,每族 32 独立 pair cluster);
- 小样本反例(3 seed x 1 episode)复现 2.6.0c 审查发现。
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
def gen_a():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    return ProbeSegmentedDriftGenerator()


@pytest.fixture(scope="session")
def null_qual_chain(schema, cfg):
    """完整资格链(三族报告 64 cluster x 16 ep + 功效分析 + spec)。"""
    from null_qual_cache import cached_null_qual_chain

    return cached_null_qual_chain(schema, cfg)


@pytest.fixture(scope="session")
def null_qual_reports(null_qual_chain):
    return null_qual_chain["reports"]


@pytest.fixture(scope="session")
def small_sample_reports(schema, cfg):
    """3 seed x 1 episode 的小样本资格报告(2.6.0c 现状:功效不足,
   必须 INSUFFICIENT_EVIDENCE;含 stochvol/sign 反例数值)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family

    return {
        fam: qualify_null_family(
            R[fam], params=dict(BASE_PARAMS), timeframe="15m",
            seeds=[11, 22, 33], cfg=cfg, schema=schema,
            episodes_per_seed=1)
        for fam in FAMILIES
    }


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_chain, schema, cfg):
    """mock 密封考试环境(v4 承诺:runtime + spec/power/pack 绑定)。"""
    from null_qual_cache import build_commitment_null_materials
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0d")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    charter = audit_probe_charter()
    pack = build_mock_hidden_pack()
    verdict_spec = probe_course_verdict_spec()
    materials = build_commitment_null_materials(
        pack, schema, cfg, chain=null_qual_chain)
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    return {
        "pack": pack,
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
    }
