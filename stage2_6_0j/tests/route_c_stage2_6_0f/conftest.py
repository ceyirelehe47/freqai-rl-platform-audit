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
                    pack_validity_report, tmp_path_factory):
    """mock 密封考试环境(v8 承诺:provider/contract/runtime/evidence)。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_evidence import (
        load_builder_run_evidence,
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
    ev_dir = tmp_path_factory.mktemp("mock-evidence-0f")
    ev_path = ev_dir / "builder_evidence.json"
    commitment = build_mock_commitment(
        pack=mock_pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=bindings,
        power_analysis_report=null_qual_chain["power_report"],
        pack_validity_report=pack_validity_report,
        builder_provider=MockBuilderIdentityProvider(),
        evidence_path=str(ev_path))
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
        "evidence": load_builder_run_evidence(ev_path),
        "evidence_path": str(ev_path),
    }


# ---------------------------------------------------------------- 私有 builder
# 阶段 2.6.0g 收尾:私有 builder 资产升级为**自包含**版本——不 import
# rl_curriculum(隔离 Runner 的 PYTHONPATH 只有 staging,评估方评估
# 代码不进入 Builder 沙箱),只依赖标准库 hashlib/json,从自身冻结
# seed namespace 真实构造 pack(不复制外部 pack、不读取 mock 载荷);
# build 入口是精确的 build_pack(request) 单参数形态(C1),返回
# builder-build-result-v3(规范化 attempt log:builder-attempt-log-v2)。
# None 入口攻击资产独立成 PRIVATE_BUILDER_NONE_FILES(P2)。
PRIVATE_BUILDER_A_FILES = {
    "builder_a.py": (
        "'''自包含私有 builder A(测试用):在隔离 Runner 内从冻结\n"
        "seed namespace 真实构造完整考试 pack(train/dev/null 全 split);\n"
        "不依赖 rl_curriculum,不读取 mock pack payload,不进入\n"
        "Candidate runtime。'''\n"
        "\n"
        "from helpers import (\n"
        "    BASE_PARAMS,\n"
        "    CHARTER_HASH,\n"
        "    EXTRAPOLATION_PARAMS,\n"
        "    FAMILY_HOLDOUT_PARAMS,\n"
        "    SPEC_VERSIONS,\n"
        "    fixed_split_seeds,\n"
        "    pack_construction_seeds,\n"
        "    pair_order,\n"
        ")\n"
        "from pack_selection import pack_passes_structure_check\n"
        "\n"
        "\n"
        "def build_pack(request):\n"
        "    '''builder-runner-protocol-v3 入口:精确单 request 位置参数,\n"
        "    真实构造 ExamPack 规范并返回规范化结果(签名不含\n"
        "    candidate/checkpoint/model/policy)。'''\n"
        "    if not isinstance(request, dict) or request.get(\n"
        "            'format') != 'builder-build-request-v3':\n"
        "        return {'format': 'builder-build-result-v3',\n"
        "                'runner_protocol': 'builder-runner-protocol-v3',\n"
        "                'status': 'failed', 'pack': None,\n"
        "                'attempt_log': {'format': 'builder-attempt-log-v2',\n"
        "                                'max_attempts': 0, 'attempts': [],\n"
        "                                'selected_attempt': None},\n"
        "                'error': 'frozen request format invalid'}\n"
        "    families = list(request['families'])\n"
        "    n_pairs = int(request['pair_count_per_family'])\n"
        "    timeframe = str(request['timeframe'])\n"
        "    max_attempts = int(request['max_attempts'])\n"
        "    attempts = []\n"
        "    selected = None\n"
        "    pack = None\n"
        "    for attempt in range(max_attempts):\n"
        "        episodes = []\n"
        "        # 非 null split(train/dev/extrapolation/holdout):seeds\n"
        "        # 从私有 namespace 派生(不复制外部 pack 的字面 seeds)\n"
        "        for fam, params, split in (\n"
        "            ('probe_segmented_drift', BASE_PARAMS, 'train'),\n"
        "            ('probe_segmented_drift', BASE_PARAMS,\n"
        "             'dev_seed_holdout'),\n"
        "            ('probe_segmented_drift', EXTRAPOLATION_PARAMS,\n"
        "             'param_extrapolation'),\n"
        "            ('probe_smooth_latent_drift', FAMILY_HOLDOUT_PARAMS,\n"
        "             'family_holdout'),\n"
        "        ):\n"
        "            for s in fixed_split_seeds(fam, split, attempt):\n"
        "                episodes.append({\n"
        "                    'family': fam, 'params': dict(params),\n"
        "                    'seed': int(s), 'split': split,\n"
        "                    'timeframe': timeframe})\n"
        "        flip_params = dict(BASE_PARAMS)\n"
        "        flip_params['antithetic_flip'] = True\n"
        "        for fam in families:\n"
        "            base_seeds = pack_construction_seeds(\n"
        "                fam, attempt, n_pairs)\n"
        "            for s in pair_order(fam, attempt, n_pairs):\n"
        "                episodes.append({\n"
        "                    'family': fam, 'params': dict(flip_params),\n"
        "                    'seed': int(base_seeds[s]),\n"
        "                    'split': 'null_control',\n"
        "                    'timeframe': timeframe})\n"
        "                episodes.append({\n"
        "                    'family': fam, 'params': dict(BASE_PARAMS),\n"
        "                    'seed': int(base_seeds[s]),\n"
        "                    'split': 'null_control',\n"
        "                    'timeframe': timeframe})\n"
        "        candidate_pack = {\n"
        "            'schema': 'exam-pack-v1',\n"
        "            'name': str(request['pack_name']),\n"
        "            'version': str(request['pack_version']),\n"
        "            'visibility': 'mock_hidden',\n"
        "            'charter_hash': CHARTER_HASH,\n"
        "            'spec_versions': dict(SPEC_VERSIONS),\n"
        "            'timeframe': timeframe,\n"
        "            'episodes': episodes,\n"
        "            'notes': {'builder': 'private-builder-a',\n"
        "                      'namespace': 'pack-construction-v1'},\n"
        "        }\n"
        "        ok, reasons = pack_passes_structure_check(\n"
        "            candidate_pack, families, n_pairs, timeframe)\n"
        "        if not ok:\n"
        "            attempts.append({\n"
        "                'attempt': attempt, 'verdict': 'reject',\n"
        "                'reject_reasons': reasons})\n"
        "            continue\n"
        "        attempts.append({\n"
        "            'attempt': attempt, 'verdict': 'accept',\n"
        "            'reject_reasons': []})\n"
        "        pack = candidate_pack\n"
        "        selected = attempt\n"
        "        break\n"
        "    if pack is None:\n"
        "        return {'format': 'builder-build-result-v3',\n"
        "                'runner_protocol': 'builder-runner-protocol-v3',\n"
        "                'status': 'failed', 'pack': None,\n"
        "                'attempt_log': {\n"
        "                    'format': 'builder-attempt-log-v2',\n"
        "                    'max_attempts': max_attempts,\n"
        "                    'attempts': attempts,\n"
        "                    'selected_attempt': None},\n"
        "                'error': 'no attempt passed structure check'}\n"
        "    return {\n"
        "        'format': 'builder-build-result-v3',\n"
        "        'runner_protocol': 'builder-runner-protocol-v3',\n"
        "        'status': 'ok', 'pack': pack,\n"
        "        'attempt_log': {\n"
        "            'format': 'builder-attempt-log-v2',\n"
        "            'max_attempts': max_attempts,\n"
        "            'attempts': attempts,\n"
        "            'selected_attempt': selected},\n"
        "        'error': None}\n"
    ),
    "helpers.py": (
        "'''seed 推导与 pair 顺序(安全相关辅助模块;冻结 seed namespace)。'''\n"
        "\n"
        "import hashlib\n"
        "\n"
        "PACK_CONSTRUCTION_SALT = (\n"
        "    'private-builder-a/pack-construction/v1')\n"
        "CHARTER_HASH = (\n"
        "    'c-486078090822cce09a6a2460885bf198259f0f8f32512d066d2ce6e7ebcfbe7e')\n"
        "SPEC_VERSIONS = {\n"
        "    'action_spec_version': 'BinaryLongFlatAction-v1',\n"
        "    'env_core_version': 'RouteCEnvCore-v1.0.0',\n"
        "    'execution_contract_version': 'MarketOpenCausalExecution-v1',\n"
        "    'observation_spec_version': 'ObservationSpec-v1',\n"
        "    'reward_spec_version': 'NetLogEquityReward-v1',\n"
        "    'terminal_liquidation_version': 'TerminalLiquidation-v1'}\n"
        "BASE_PARAMS = {'episode_bars': 96,\n"
        "               'drift_bps_range': [18.0, 30.0],\n"
        "               'vol_bps_range': [20.0, 32.0],\n"
        "               'initial_price': 100.0}\n"
        "EXTRAPOLATION_PARAMS = {'episode_bars': 96,\n"
        "                       'drift_bps_range': [30.0, 45.0],\n"
        "                       'vol_bps_range': [32.0, 50.0],\n"
        "                       'initial_price': 100.0}\n"
        "FAMILY_HOLDOUT_PARAMS = {'episode_bars': 96, 'theta': 0.02,\n"
        "                         'sigma_mu_bps': 3.0, 'vol_bps': 36.0,\n"
        "                         'initial_price': 100.0}\n"
        "\n"
        "\n"
        "def _tagged(tag):\n"
        "    return hashlib.sha256(\n"
        "        (PACK_CONSTRUCTION_SALT + '|' + tag).encode('utf-8'))\n"
        "\n"
        "\n"
        "def fixed_split_seeds(family, split, attempt):\n"
        "    return [int(_tagged('fixed|' + family + '|' + split + '|'\n"
        "                        + str(attempt) + '|' + str(i)\n"
        "                        ).hexdigest()[:8], 16)\n"
        "            for i in range(3)]\n"
        "\n"
        "\n"
        "def pack_construction_seeds(family, attempt, n):\n"
        "    return [int(_tagged('seed|' + family + '|' + str(attempt)\n"
        "                        + '|' + str(i)).hexdigest()[:8], 16)\n"
        "            for i in range(n)]\n"
        "\n"
        "\n"
        "def pair_order(family, attempt, n):\n"
        "    return sorted(range(n),\n"
        "                  key=lambda i: _tagged(\n"
        "                      'order|' + family + '|' + str(attempt)\n"
        "                      + '|' + str(i)).hexdigest())\n"
    ),
    "pack_selection.py": (
        "'''attempt 选择链:构建期 pack 结构自检(镜像成对/族齐/时长一致)。'''\n"
        "\n"
        "MAX_PACK_ATTEMPTS = 8\n"
        "\n"
        "\n"
        "def pack_passes_structure_check(pack, families, n_pairs, timeframe):\n"
        "    reasons = []\n"
        "    episodes = pack.get('episodes') or []\n"
        "    by_family = {}\n"
        "    for ep in episodes:\n"
        "        by_family.setdefault(ep['family'], []).append(ep)\n"
        "    for fam in families:\n"
        "        eps = by_family.get(fam) or []\n"
        "        if len(eps) != 2 * n_pairs:\n"
        "            reasons.append('pair-count-mismatch:' + fam)\n"
        "        for i in range(0, len(eps) - 1, 2):\n"
        "            a, b = eps[i], eps[i + 1]\n"
        "            if a['seed'] != b['seed'] \\\n"
        "                    or a['params'].get('antithetic_flip') \\\n"
        "                    == b['params'].get('antithetic_flip'):\n"
        "                reasons.append('mirror-broken:' + fam)\n"
        "                break\n"
        "        for ep in eps:\n"
        "            if ep['timeframe'] != timeframe:\n"
        "                reasons.append('timeframe-mismatch:' + fam)\n"
        "                break\n"
        "    if pack.get('timeframe') != timeframe:\n"
        "        reasons.append('pack-timeframe-mismatch')\n"
        "    return (not reasons), reasons[:3]\n"
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
#: 返回 None——文件身份(npb-)与 entrypoint 静态验证都通过,只有产物
#: 来源证明(隔离 Runner 实际执行)能拒绝它与公开 mock pack 的组合。
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
    """在 root 下写一个私有 builder package(含 provider_config.json)。

    v4:不再生成 attempt_loop 字段(独立 attempt-loop entrypoint 已
    废除;attempt 循环由 build 入口内部的规范化 attempt log 运行
    证据证明)。
    """
    files = dict(files or PRIVATE_BUILDER_A_FILES)
    root.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (root / name).write_text(content, encoding="utf-8")
    (root / "provider_config.json").write_text(
        __import__("json").dumps({
            "entrypoint_module": _entrypoint_module(files),
            "entrypoint_qualname": entrypoint_qualname,
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
