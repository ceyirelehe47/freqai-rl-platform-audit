"""阶段 2.6.0c 测试夹具:v3 承诺 / 真实 Null 报告 / mock issuer /
attested checkpoint / 作弊探针场景。

与 2.6.0b 夹具同构,新增:
- commitment v3(绑定候选运行时 manifest + 真实 Null 资格报告);
- issuer 信任根只来自承诺(context 只携带展示副本);
- 作弊策略集成场景(固定结构 episodes,TestOnlyProbe 协议,不进入
  正式 Candidate 接口)。
"""

from __future__ import annotations

import hashlib
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

from rl_curriculum.attestation import (  # noqa: E402
    Ed25519KeyPair,
    TrustedIssuerConfig,
    build_attestation_payload,
    write_attestation,
)
from rl_curriculum.checkpoints import save_checkpoint_manifest  # noqa: E402
from rl_curriculum.mock_sealed_exam import (  # noqa: E402
    BASE_PARAMS,
    default_eval_config,
)
from rl_curriculum.builder_identity import MockBuilderIdentityProvider
from rl_curriculum.probe_charter import probe_observation_schema  # noqa: E402

#: mock 受控训练 runner 身份
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60

#: 作弊探针固定结构场景(与 tests/route_c_stage2_6_0/test_cheater_detection
#: 相同的结构:漂移块位置保证基础成绩达标且对应变体优势真实崩溃)
FIXED_STRUCTURE_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 37], [1, 60.0, 14], [0, 0.0, 45]],
}
MONOTONE_UP_PARAMS = {
    "episode_bars": 96,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[1, 28.0, 48], [1, 28.0, 48]],
}
ALIGNED_PERIODIC_PARAMS = {
    "episode_bars": 92,
    "vol_bps_range": [8.0, 10.0],
    "initial_price": 100.0,
    "regimes": [[0, 0.0, 4], [1, 800.0, 3], [0, 0.0, 85]],
}
CHEAT_SCENARIO_PARAMS = {
    "episode_position": FIXED_STRUCTURE_PARAMS,
    "absolute_price": MONOTONE_UP_PARAMS,
    "periodic_pattern": ALIGNED_PERIODIC_PARAMS,
}


@pytest.fixture(scope="session")
def schema():
    return probe_observation_schema()


@pytest.fixture(scope="session")
def cfg():
    return default_eval_config()


@pytest.fixture(scope="session")
def gen_a():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    return ProbeSegmentedDriftGenerator()


@pytest.fixture(scope="session")
def mock_issuer_keypair():
    return Ed25519KeyPair.generate("mock-issuer-stage2-6-0c")


@pytest.fixture(scope="session")
def attacker_issuer_keypair():
    """攻击者 B 的密钥对(context issuer override 场景)。"""
    return Ed25519KeyPair.generate("attacker-issuer-B")


@pytest.fixture(scope="session")
def mock_trusted_issuer(mock_issuer_keypair):
    return TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair,
        required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=False,
    )


@pytest.fixture(scope="session")
def sandbox_profile():
    from rl_curriculum.sandbox import default_sandbox_profile

    return default_sandbox_profile()


def _train_tiny_ppo(path: Path, *, n_steps: int = 64) -> dict:
    """测试级 PPO 训练 + 训练 manifest(受控训练 runner 模拟)。"""
    import gymnasium as gym
    import numpy as np
    from stable_baselines3 import PPO

    class TinyLongFlatEnv(gym.Env):
        def __init__(self):
            super().__init__()
            self.observation_space = gym.spaces.Box(
                -1e9, 1e9, (9,), np.float32)
            self.action_space = gym.spaces.Discrete(2)
            self._rng = np.random.default_rng(0)
            self._obs = np.zeros(9, np.float32)

        def reset(self, seed=None, options=None):
            self._obs = np.zeros(9, np.float32)
            return self._obs, {}

        def step(self, action):
            drift = 0.0003 if self._obs[4] > 0 else -0.0002
            ret = drift + 0.0004 * self._rng.standard_normal()
            self._obs = np.roll(self._obs, 1)
            self._obs[0] = ret
            self._obs[4] += 0.1 * (ret - self._obs[4])
            return self._obs, ret, False, False, {}

    model = PPO("MlpPolicy", TinyLongFlatEnv(), n_steps=n_steps,
                batch_size=16, seed=7, verbose=0, device="cpu")
    model.save(str(path))
    n_params = sum(p.numel() for p in model.policy.parameters())
    return {
        "ppo_params": {
            "n_steps": n_steps, "batch_size": 16, "seed": 7,
            "learning_rate": float(model.learning_rate),
            "n_epochs": int(model.n_epochs),
            "gamma": float(model.gamma),
        },
        "network_architecture": {
            "policy_class": type(model.policy).__name__,
            "parameter_count": int(n_params),
        },
        "training_budget": {"total_timesteps": int(n_steps)},
        "training_seed": 7,
    }


def _write_attested_checkpoint(d: Path, ckpt_name: str, schema,
                               keypair: Ed25519KeyPair,
                               runner_hash: str,
                               training_material: dict) -> dict:
    """对 checkpoint 写 sidecar + 用指定签发方签名 attestation。"""
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    ckpt = d / ckpt_name
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": runner_hash,
        "steps": training_material["training_budget"]["total_timesteps"],
        "seed": training_material["training_seed"],
        "note": "测试级 PPO(允许挂科);只验证 provenance 与执行链路",
    }
    tm_path = d / (ckpt_name + ".training_manifest.json")
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        ckpt, checkpoint_name=ckpt_name,
        charter_hash=charter_h, observation_schema=schema,
        training_manifest_sha256=tm_sha,
        self_declared_formal_eligible=False)
    sidecar_sha = hashlib.sha256(
        (d / (ckpt_name + ".rl_manifest.json")).read_bytes()).hexdigest()
    ckpt_sha = hashlib.sha256(ckpt.read_bytes()).hexdigest()
    payload = build_attestation_payload(
        checkpoint_sha256=ckpt_sha,
        sidecar_sha256=sidecar_sha,
        training_manifest_sha256=tm_sha,
        charter_hash=charter_h,
        observation_schema_hash=schema.schema_hash(),
        route_c_env_version="RouteCEnvCore-v1.0.0",
        training_generator_hashes={},
        training_pack_hash="mock-training-pack",
        training_code_hash="mock-training-code",
        ppo_params=training_material["ppo_params"],
        network_architecture=training_material["network_architecture"],
        training_budget=training_material["training_budget"],
        training_seed=training_material["training_seed"],
        is_smoke=False,
        allow_formal_evaluation=True,
        issuer_id=keypair.issuer_id,
        training_runner_hash=runner_hash,
        issued_utc="2026-08-26T00:00:00Z",
    )
    att_doc = write_attestation(
        ckpt.with_name(ckpt.name + ".rl_attestation.json"), keypair, payload)
    return {
        "checkpoint": str(ckpt),
        "attestation": att_doc,
        "training_manifest_sha256": tm_sha,
        "training_material": training_material,
        "charter_hash": charter_h,
    }


@pytest.fixture(scope="session")
def attested_checkpoint(tmp_path_factory, schema, mock_issuer_keypair):
    """评估方受信签发方 A 签名的 checkpoint(session 共享)。"""
    d = tmp_path_factory.mktemp("attested-ckpt-2c")
    material = _train_tiny_ppo(d / "test_ppo_2c.zip")
    out = _write_attested_checkpoint(
        d, "test_ppo_2c.zip", schema, mock_issuer_keypair,
        MOCK_TRAINING_RUNNER_HASH, material)
    out["trusted_issuer"] = TrustedIssuerConfig.from_keypair(
        mock_issuer_keypair,
        required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=False)
    return out


@pytest.fixture(scope="session")
def null_qual_chain(schema, cfg):
    """完整资格链(报告 + 功效分析 + spec;共享磁盘缓存,64 cluster
    x 16 episodes 的 antithetic pair 结构;阶段 2.6.0d)。"""
    from null_qual_cache import cached_null_qual_chain

    return cached_null_qual_chain(schema, cfg)


@pytest.fixture(scope="session")
def null_qual_reports(null_qual_chain):
    return null_qual_chain["reports"]


@pytest.fixture(scope="session")
def null_qual_bindings(null_qual_chain):
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    return build_null_qualification_bindings(null_qual_chain["reports"])


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_chain, schema, cfg, mock_trusted_issuer,
                    sandbox_profile):
    """mock 密封考试环境:pack + commitment v4(含 runtime manifest 与
    完整 Null 资格链绑定)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
    )
    from null_qual_cache import build_commitment_null_materials
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import (
        compute_runtime_manifest,
        runtime_tree_hash,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    charter = audit_probe_charter()
    pack = build_mock_hidden_pack()
    verdict_spec = probe_course_verdict_spec()
    materials = build_commitment_null_materials(
        pack, schema, cfg, chain=null_qual_chain)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
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
        "profile": sandbox_profile,
        "trusted_issuer": mock_trusted_issuer,
        "null_qual_reports": null_qual_reports,
        "runtime_manifest": compute_runtime_manifest(),
        "runtime_hash": runtime_tree_hash(commitment.candidate_runtime_manifest),
    }


@pytest.fixture(scope="session")
def sandbox_checkpoint(attested_checkpoint):
    return attested_checkpoint["checkpoint"]
