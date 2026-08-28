"""阶段 2.6.0h 测试夹具:Builder 后代执行、有效沙箱证明与 Attempt
选择策略闭环。

- A1/A3:seccomp 进程树策略(子进程/exec 全禁;线程放行)与真实
  攻击 Builder(子 Python import 未注册第三方、/bin/sh、
  posix_spawn、fork+exec、ctypes.CDLL、外部可执行文件);
- B1/B3:私有最小 /dev、宿主 /dev/shm//etc//sys/临时目录不可利用;
- C1-C3:Effective Sandbox Report(实际生效状态 + 探针 + esb-);
- D1-D4:运行时依赖锁 v2(进程树边界 + distribution 实际内容 +
  native 绑定);
- E2/E3:first_pass attempt 硬约束;
- F:evidence v2 新核心哈希(esb-/acs-/进程树计数/isolation);
- G:checkpoint 前访问守卫 v2(事件扩展 + namespace 不可命名);
- sealed-exam-commitment-v9 / null-pack-builder-manifest-v5 /
  builder-run-evidence-v2 / hidden-exam-cli-v10 全链路。
"""

from __future__ import annotations

import json
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

RESULT_V3 = {"format": "builder-build-result-v3",
             "runner_protocol": "builder-runner-protocol-v3"}
LOG_V2 = "builder-attempt-log-v2"


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


def _materialize_null(pack):
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
    """mock 密封考试环境(v9 承诺:evidence v2 + attempt policy 绑定)。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_evidence import load_builder_run_evidence
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0h")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair,
        required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    charter = audit_probe_charter()
    verdict_spec = probe_course_verdict_spec()
    bindings = build_null_qualification_bindings(
        null_qual_chain["reports"])
    ev_dir = tmp_path_factory.mktemp("mock-evidence-0h")
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
    private_provider_from_root,
    write_private_builder,
)


@pytest.fixture()
def private_builder_a(tmp_path):
    """真实可执行的私有 builder A(0f 自包含模板,v3/v2 协议)。"""
    root = write_private_builder(tmp_path / "h_private_builder_a")
    return private_provider_from_root(root)


# ------------------------------------------------- 0h 攻击 builder 构造器
PACK_TMPL = """    pack = {{
        'schema': 'exam-pack-v1',
        'name': request['pack_name'],
        'version': request['pack_version'],
        'visibility': 'mock_hidden',
        'charter_hash': '',
        'spec_versions': {{}},
        'timeframe': request['timeframe'],
        'episodes': [
            {{'family': 'probe_null_sign',
             'params': {{'episode_bars': 96}}, 'seed': 1,
             'split': 'null_control',
             'timeframe': request['timeframe']}}],
        'notes': {notes},
    }}
"""


def _result_tail(max_attempts=2, accepts=1):
    attempts = []
    for i in range(accepts):
        attempts.append("{'attempt': %d, 'verdict': 'reject', "
                        "'reject_reasons': ['p%d']}" % (i, i))
    attempts.append("{'attempt': %d, 'verdict': 'accept', "
                    "'reject_reasons': []}" % accepts)
    body = ", ".join(attempts)
    return (
        "    log = {'format': 'builder-attempt-log-v2',\n"
        "           'max_attempts': %d,\n"
        "           'attempts': [%s],\n"
        "           'selected_attempt': %d}\n"
        "    return {'format': 'builder-build-result-v3',\n"
        "            'runner_protocol': 'builder-runner-protocol-v3',\n"
        "            'status': 'ok', 'pack': pack,\n"
        "            'attempt_log': log, 'error': None}\n"
        % (max_attempts, body, accepts))


def write_attack_builder(root: Path, body: str, *, max_attempts: int = 2,
                         extra_files: dict | None = None,
                         external_dependencies: list | None = None,
                         label: str = "attack-builder",
                         notes: str = "{}") -> Path:
    """写入攻击 builder root(body 是 build_pack 函数体的语句序列)。"""
    root.mkdir(parents=True, exist_ok=True)
    src = (
        "'''0h 攻击 builder(测试专用)。'''\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        f"{body}"
        f"{PACK_TMPL.format(notes=notes)}"
        f"{_result_tail(max_attempts=max_attempts)}"
    )
    (root / "builder_attack.py").write_text(src, encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}',
                                      encoding="utf-8")
    cfg = {
        "entrypoint_module": "builder_attack",
        "entrypoint_qualname": "build_pack",
        "families": ["probe_null_sign"],
        "pair_count_per_family": 2,
        "max_attempts": max_attempts,
        "root_label": label,
    }
    if external_dependencies is not None:
        cfg["external_dependencies"] = external_dependencies
    (root / "provider_config.json").write_text(
        json.dumps(cfg), encoding="utf-8")
    for name, content in (extra_files or {}).items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, bytes):
            p.write_bytes(content)
        else:
            p.write_text(content, encoding="utf-8")
    return root


def attack_request(provider, pack, duration_contract):
    """从攻击 provider 派生 v3 冻结请求。"""
    return provider.frozen_build_request(pack, duration_contract)


@pytest.fixture()
def descendant_demo_profile():
    """演示 PoC 专用 profile:seccomp 关闭 + 允许后代(仅测试)。

    正式 evidence 校验拒绝此类 profile 的产物(C3 降级矩阵)。
    """
    from rl_curriculum.builder_runner import (
        ALLOW_DESCENDANTS,
        BuilderRunnerProfile,
    )

    return BuilderRunnerProfile(
        install_seccomp=False, process_tree_policy=ALLOW_DESCENDANTS)
