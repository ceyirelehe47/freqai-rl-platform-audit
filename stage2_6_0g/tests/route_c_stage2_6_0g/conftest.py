"""阶段 2.6.0g 测试夹具:Builder 产物来源证明与私有 EntryPoint 验证闭环。

- A1:entrypoint/attempt-loop 真实存在性验证(AST + 受控 import);
- A2:builder-runner-protocol-v2 统一调用协议(冻结构建请求/规范化
  结果/None 失败);
- P1/P2:产物来源证明(重放产物 pack_hash == commitment.pack_hash;
  私有入口返回 None 不得与公开 mock pack 组合通过);
- P5:统一 Provider 配置解析(CLI 与承诺创建端同源);
- P6:builder 链实际 import 的静态闭包(gymnasium 等第三方覆盖);
- P7:mock 构建辅助函数的隐式 Provider fallback 已删除;
- sealed-exam-commitment-v8 / null-pack-builder-manifest-v4 /
  hidden-exam-cli-v9 全链路。
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
def mock_provider():
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider

    return MockBuilderIdentityProvider()


@pytest.fixture(scope="session")
def mock_identity(mock_provider):
    return mock_provider.builder_identity()


@pytest.fixture(scope="session")
def mock_pack():
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack

    return build_mock_hidden_pack()


@pytest.fixture(scope="session")
def duration_contract(mock_pack):
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        mock_pack, required_families=list(FAMILIES))


@pytest.fixture(scope="session")
def frozen_request(mock_provider, mock_pack, duration_contract):
    return mock_provider.frozen_build_request(mock_pack, duration_contract)


def _materialize_null(pack, registry=None):
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    by_family: dict[str, list] = {}
    for spec in pack.episodes:
        if spec.split == "null_control":
            by_family.setdefault(spec.family, []).append(
                R[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    return by_family


@pytest.fixture(scope="session")
def pack_validity_report(mock_pack, schema, cfg, duration_contract,
                         mock_identity):
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    spec = build_spec_for_pack(
        cfg, timeframe=duration_contract["timeframe"],
        episode_bars=int(duration_contract["resolved_bars"]))
    return validate_null_pack(
        _materialize_null(mock_pack), cfg=cfg, schema=schema, spec=spec,
        pack_hash=mock_pack.pack_hash(),
        builder_identity=mock_identity, duration_contract=duration_contract)


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_chain, schema, cfg, mock_pack,
                    pack_validity_report, mock_provider, tmp_path_factory):
    """mock 密封考试环境(v8 承诺:nbr- 冻结请求 + bre- evidence 绑定)。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_evidence import (
        load_builder_run_evidence,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0g")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair,
        required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    charter = audit_probe_charter()
    verdict_spec = probe_course_verdict_spec()
    bindings = build_null_qualification_bindings(
        null_qual_chain["reports"])
    ev_dir = tmp_path_factory.mktemp("mock-evidence")
    ev_path = ev_dir / "builder_evidence.json"
    commitment = build_mock_commitment(
        pack=mock_pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=bindings,
        power_analysis_report=null_qual_chain["power_report"],
        pack_validity_report=pack_validity_report,
        builder_provider=mock_provider,
        evidence_path=str(ev_path))
    evidence = load_builder_run_evidence(ev_path)
    return {
        "pack": mock_pack,
        "charter": charter,
        "schema": schema,
        "eval_config": cfg,
        "verdict_spec": verdict_spec,
        "registry": DEFAULT_GENERATOR_REGISTRY,
        "commitment": commitment,
        "keypair": keypair,
        "trusted_issuer": issuer,
        "null_qual_reports": null_qual_chain["reports"],
        "power_report": null_qual_chain["power_report"],
        "pack_validity_report": pack_validity_report,
        "profile": default_sandbox_profile(),
        "provider": mock_provider,
        "evidence": evidence,
        "evidence_path": str(ev_path),
    }


# ---------------------------------------------------------------- 私有 builder
from tests.route_c_stage2_6_0f.conftest import (  # noqa: E402
    PRIVATE_BUILDER_A_FILES,
    PRIVATE_BUILDER_NONE_FILES,
    private_provider_from_root,
    write_private_builder,
)


@pytest.fixture()
def private_builder_a(tmp_path):
    """真实可执行的私有 builder A(重放产物 == 公开 mock 构建链产物)。"""
    root = write_private_builder(tmp_path / "g_private_builder_a")
    return private_provider_from_root(root)


@pytest.fixture()
def private_builder_none(tmp_path):
    """None 入口攻击 builder(P2):文件身份/entrypoint 验证都通过,
    只有产物来源证明能拒绝。"""
    root = write_private_builder(
        tmp_path / "g_private_builder_none", dict(PRIVATE_BUILDER_NONE_FILES),
        label="private-builder-none")
    return private_provider_from_root(root)


@pytest.fixture()
def private_builder_wrong_pack(tmp_path):
    """真实构建但产物不同的私有 builder(hash 不匹配攻击)。

    入口合规且真实构造 pack,但无视冻结构建请求的 timeframe 固定
    用 5m 构造 -> 产物 pack_hash 与承诺绑定的 15m pack 不同,重放
    对账必须拒绝。
    """
    files = dict(PRIVATE_BUILDER_A_FILES)
    files["builder_a.py"] = files["builder_a.py"].replace(
        "    timeframe = str(request['timeframe'])\n",
        "    timeframe = '5m'\n")
    root = write_private_builder(
        tmp_path / "g_private_builder_wrong", files,
        label="private-builder-wrong")
    return private_provider_from_root(root)
