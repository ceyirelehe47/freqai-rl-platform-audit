"""阶段 2.6.0 测试公共夹具(阶段 2.6.0a 更新:新增 observation schema)。
阶段 2.6.0b 更新:sidecar v3 的 formal_eligible 恒 False(正式资格来自
受信 attestation);formal_checkpoint 夹具升级为 mock issuer 签发的
attested checkpoint,并新增 sandbox_profile 夹具,供密封考试 CLI v3
(无 --no-subprocess,候选一律系统级沙箱执行)走真实全链路。"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments"))

import pytest  # noqa: E402

from rl_curriculum.attestation import (  # noqa: E402
    Ed25519KeyPair,
    TrustedIssuerConfig,
    build_attestation_payload,
    write_attestation,
)
from rl_curriculum.evaluator import EvalConfig  # noqa: E402
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY  # noqa: E402
from rl_curriculum.probe_charter import probe_observation_schema  # noqa: E402

#: mock 受控训练 runner 身份(attestation 的 required_training_runner_hash)
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


@pytest.fixture(scope="session")
def gen_a():
    return DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]


@pytest.fixture(scope="session")
def gen_b():
    return DEFAULT_GENERATOR_REGISTRY["probe_smooth_latent_drift"]


@pytest.fixture(scope="session")
def gen_c():
    return DEFAULT_GENERATOR_REGISTRY["probe_null_control"]


@pytest.fixture(scope="session")
def schema():
    """阶段 2.6.0a:课程级 observation schema(有序 whitelist + nuisance)。"""
    return probe_observation_schema()


@pytest.fixture(scope="session")
def mock_issuer_keypair():
    return Ed25519KeyPair.generate("mock-issuer-stage2-6-0")


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


def _train_tiny_ppo(path: Path, *, n_steps: int = 64, seed: int = 7) -> dict:
    """测试级 PPO 训练 + 训练材料(受控训练 runner 模拟;obs dim 9)。"""
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
                batch_size=16, seed=seed, verbose=0, device="cpu")
    model.save(str(path))
    n_params = sum(p.numel() for p in model.policy.parameters())
    return {
        "ppo_params": {
            "n_steps": n_steps, "batch_size": 16, "seed": seed,
            "learning_rate": float(model.learning_rate),
            "n_epochs": int(model.n_epochs),
            "gamma": float(model.gamma),
        },
        "network_architecture": {
            "policy_class": type(model.policy).__name__,
            "parameter_count": int(n_params),
        },
        "training_budget": {"total_timesteps": int(n_steps)},
        "training_seed": seed,
    }


@pytest.fixture(scope="session")
def formal_checkpoint(tmp_path_factory, schema, mock_issuer_keypair,
                      mock_trusted_issuer):
    """测试级固定维度 PPO + v3 sidecar + 受信 attestation(obs dim 9)。

    阶段 2.6.0b 语义:sidecar 只证明 format_compatible;formal_eligible
    恒 False——正式资格唯一来源是 mock issuer 签名的 training
    attestation。密封考试 CLI(v3)据此走真实沙箱全链路。
    """
    pytest.importorskip("stable_baselines3")
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.checkpoints import (
        is_format_compatible,
        save_checkpoint_manifest,
    )
    from rl_curriculum.probe_charter import audit_probe_charter

    out = tmp_path_factory.mktemp("formal_ckpt")
    path = out / "tiny_formal.zip"
    training_material = _train_tiny_ppo(path, n_steps=64, seed=11)
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": training_material["training_budget"]["total_timesteps"],
        "seed": training_material["training_seed"],
        "note": "测试级 PPO(允许挂科);只验证 provenance 与执行链路",
    }
    tm_path = out / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    manifest = save_checkpoint_manifest(
        path, checkpoint_name="tiny_formal",
        charter_hash=charter_h,
        observation_schema=schema,
        training_manifest_sha256=tm_sha,
    )
    # 阶段 2.6.0b:sidecar 自声明资格被忽略;格式兼容由绑定决定
    assert manifest["formal_eligible"] is False
    assert is_format_compatible(manifest) is True
    sidecar_sha = hashlib.sha256(
        (out / "tiny_formal.zip.rl_manifest.json").read_bytes()).hexdigest()
    ckpt_sha = hashlib.sha256(path.read_bytes()).hexdigest()
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
        issuer_id=mock_issuer_keypair.issuer_id,
        training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        issued_utc="2026-08-26T00:00:00Z",
    )
    write_attestation(
        path.with_name(path.name + ".rl_attestation.json"),
        mock_issuer_keypair, payload)
    return path


@pytest.fixture()
def cfg() -> EvalConfig:
    return EvalConfig(fee=0.001)


TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
