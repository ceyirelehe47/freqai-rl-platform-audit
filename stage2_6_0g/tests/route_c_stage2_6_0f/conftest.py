"""阶段 2.6.0f 测试夹具:私有 Builder 身份与 Null 时长合同最终闭环。

- Builder Identity Provider(评估方可信输入;mock/private 双实现);
- builder package tree manifest v2(完整依赖闭包);
- 全局 strict Null duration contract v1(唯一 resolved 时长);
- sealed-exam-commitment-v6 / null-pack-validity-v3 / CLI v7 全链路;
- 256-step PPO smoke(正常 FAIL,不构成课程训练)。
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
def mock_pack():
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack

    return build_mock_hidden_pack()


@pytest.fixture(scope="session")
def duration_contract(mock_pack):
    """mock pack 的全局 duration contract(15m / 96 bars / 192 ep)。"""
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    return derive_global_null_duration_contract(
        mock_pack, required_families=list(FAMILIES))


@pytest.fixture(scope="session")
def mock_identity():
    from compat_stage2_6_0f import mock_builder_identity

    return mock_builder_identity()


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
def mock_pack_materialized(mock_pack):
    return _materialize_null(mock_pack)


@pytest.fixture(scope="session")
def pack_validity_report(mock_pack, mock_pack_materialized, schema, cfg,
                         duration_contract, mock_identity):
    """v3 报告:Provider 派生 builder hash + 全局 duration contract。"""
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    spec = build_spec_for_pack(
        cfg, timeframe=duration_contract["timeframe"],
        episode_bars=int(duration_contract["resolved_bars"]))
    return validate_null_pack(
        mock_pack_materialized, cfg=cfg, schema=schema, spec=spec,
        pack_hash=mock_pack.pack_hash(),
        builder_identity=mock_identity,
        duration_contract=duration_contract)


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_chain, schema, cfg, mock_pack,
                    pack_validity_report):
    """mock 密封考试环境 v7(v6 承诺:provider/contract/runtime 绑定)。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_identity import (
        MockBuilderIdentityProvider,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import build_mock_commitment
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0f")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash="mock-runner-" + "b" * 60,
        allow_smoke=False)
    charter = audit_probe_charter()
    verdict_spec = probe_course_verdict_spec()
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    bindings = build_null_qualification_bindings(
        null_qual_chain["reports"])
    commitment = build_mock_commitment(
        pack=mock_pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=bindings,
        power_analysis_report=null_qual_chain["power_report"],
        pack_validity_report=pack_validity_report,
        builder_provider=MockBuilderIdentityProvider())
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
    }


# ---------------------------------------------------------------- 私有 builder
# 阶段 2.6.0g:私有 builder 资产升级为真实可执行(build 入口符合
# builder-runner-protocol-v1 的单 request 参数形态,A1 构造期验证 +
# formal D1 步骤 4b 产物来源证明全链路);None 入口攻击资产独立成
# PRIVATE_BUILDER_NONE_FILES(2.6.0g P2:入口返回 None 不得与公开
# mock pack 组合通过 formal verification)。
_PRIVATE_RESULT_TAIL = (
    "    return {'format': 'builder-build-result-v1',\n"
    "            'runner_protocol': 'builder-runner-protocol-v1',\n"
    "            'status': 'ok', 'pack': pack,\n"
    "            'attempt_log': list(log)}\n"
)

PRIVATE_BUILDER_A_FILES = {
    "builder_a.py": (
        "'''私有 builder A(测试用;真实可执行,复用公开 mock 构建链,\n"
        "构建结果经 runner 协议规范化返回;不进入 Candidate runtime)。'''\n"
        "\n"
        "BASE_PARAMS = {'episode_bars': 96, 'drift_bps_range': [18.0, 30.0],\n"
        "              'vol_bps_range': [20.0, 32.0], 'initial_price': 100.0}\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    '''builder-runner-protocol-v1 入口:单 request 位置参数,\n"
        "    真实构造 ExamPack 并返回规范化结果(签名不含\n"
        "    candidate/checkpoint/model/policy)。'''\n"
        "    from rl_curriculum.builder_provenance import BUILD_REQUEST_FORMAT\n"
        "    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack\n"
        "\n"
        "    if not isinstance(request, dict) or request.get(\n"
        "            'format') != BUILD_REQUEST_FORMAT:\n"
        "        return {'format': 'builder-build-result-v1',\n"
        "                'runner_protocol': 'builder-runner-protocol-v1',\n"
        "                'status': 'failed', 'pack': None,\n"
        "                'attempt_log': [], 'error': '冻结构建请求格式无效'}\n"
        "    pack, log = build_mock_hidden_pack(\n"
        "        name=str(request.get('pack_name')\n"
        "                 or 'mock_hidden_probe_pack'),\n"
        "        version=str(request.get('pack_version')\n"
        "                    or 'mock-hidden-v5'),\n"
        "        timeframe=str(request.get('timeframe') or '15m'),\n"
        "        with_builder_log=True)\n"
        + _PRIVATE_RESULT_TAIL
    ),
    "helpers.py": (
        "'''seed 推导与 pair 顺序(安全相关辅助模块)。'''\n"
        "\n"
        "PACK_CONSTRUCTION_SALT = 'private-builder-a/pack-construction/v1'\n"
        "\n"
        "\n"
        "def pack_construction_seeds(family, attempt, n):\n"
        "    return [attempt * 100000 + i for i in range(n)]\n"
        "\n"
        "\n"
        "def pack_order_seed(family, attempt):\n"
        "    return hash((PACK_CONSTRUCTION_SALT, family, attempt)) % (2**32)\n"
    ),
    "pack_selection.py": (
        "'''attempt 选择链:构建期 pack materialization 与资格验证。'''\n"
        "\n"
        "MAX_PACK_ATTEMPTS = 8\n"
        "\n"
        "\n"
        "def validate_pack_ephemeral(pack):\n"
        "    return {'pass': True, 'reasons': []}\n"
        "\n"
        "\n"
        "def attempt_loop():\n"
        "    for attempt in range(MAX_PACK_ATTEMPTS):\n"
        "        yield attempt\n"
    ),
    "params.json": (
        '{"episode_bars": 96, "timeframe": "15m",\n'
        ' "families": ["probe_null_sign", "probe_null_volstate",\n'
        '              "probe_null_stochvol"]}\n'
    ),
}

#: None 入口攻击资产(2.6.0g P2):入口真实存在、签名合规,但运行时
#: 返回 None——文件身份(npb-)与 entrypoint 验证都通过,只有产物
#: 来源证明(D1 步骤 4b 实际执行)能拒绝它与公开 mock pack 的组合。
PRIVATE_BUILDER_NONE_FILES = {
    "builder_none.py": (
        "'''攻击用私有 builder:入口存在且签名合规,但返回 None。'''\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    return None\n"
    ),
    "params.json": (
        '{"episode_bars": 96, "timeframe": "15m",\n'
        ' "families": ["probe_null_sign", "probe_null_volstate",\n'
        '              "probe_null_stochvol"]}\n'
    ),
}


def write_private_builder(root: Path, files: dict | None = None,
                          label: str = "private-builder-a",
                          entrypoint_qualname: str = "build_pack") -> Path:
    """在 root 下写一个私有 builder package(含 provider_config.json)。"""
    files = dict(files or PRIVATE_BUILDER_A_FILES)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "provider_config.json").write_text(
        __import__("json").dumps({
            "entrypoint_module": _entrypoint_module(files),
            "entrypoint_qualname": entrypoint_qualname,
            "attempt_loop_module": (
                "pack_selection" if "pack_selection.py" in files
                else _entrypoint_module(files)),
            "attempt_loop_qualname": (
                "attempt_loop" if "pack_selection.py" in files
                else entrypoint_qualname),
            "params_spec": {
                "base_params": {
                    "episode_bars": 96,
                    "drift_bps_range": [18.0, 30.0],
                    "vol_bps_range": [20.0, 32.0],
                    "initial_price": 100.0,
                },
                "flip_flag_key": "antithetic_flip",
                "episode_bars": 96,
            },
            "families": list(FAMILIES),
            "pair_count_per_family": 32,
            "max_attempts": 8,
            "root_label": label,
        }, indent=1),
        encoding="utf-8")
    return root


def _entrypoint_module(files: dict) -> str:
    """entrypoint 所在模块名(默认 builder_a;按文件集合推断)。"""
    if "builder_a.py" in files:
        return "builder_a"
    if "builder_none.py" in files:
        return "builder_none"
    if "builder_b.py" in files:
        return "builder_b"
    return "builder_a"


def private_provider_from_root(root: Path):
    """从 provider_config.json 构造私有 Provider(与 CLI 同源同参数)。

    阶段 2.6.0g P5:统一走 src 的 load_builder_provider_config /
    private_provider_from_config(单一字段清单,CLI 与承诺创建端
    不再分叉;pair_count_per_family / max_attempts /
    external_dependencies 全字段生效)。
    """
    from rl_curriculum.builder_identity import private_provider_from_config

    return private_provider_from_config(root)


@pytest.fixture()
def private_builder_a(tmp_path):
    root = write_private_builder(tmp_path / "private_builder_a")
    return private_provider_from_root(root)


@pytest.fixture()
def private_builder_b(tmp_path):
    """内容不同的第二个私有 builder(替换攻击用;入口合规)。"""
    files = dict(PRIVATE_BUILDER_A_FILES)
    files["builder_a.py"] = files["builder_a.py"].replace(
        "def build_pack(request):", "def build_pack_v2(request):")
    root = write_private_builder(
        tmp_path / "private_builder_b", files, label="private-builder-b",
        entrypoint_qualname="build_pack_v2")
    return private_provider_from_root(root)
