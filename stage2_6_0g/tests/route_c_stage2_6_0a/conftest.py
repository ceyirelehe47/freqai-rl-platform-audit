"""阶段 2.6.0a 测试公共夹具。
阶段 2.6.0b 更新:sidecar v3 不再承载 formal_eligible(正式资格来自受信
attestation);sealed commitment v2 必须绑定 trusted_issuer 与 sandbox
profile;CLI v3 删除 --no-subprocess——夹具改为提供 mock issuer /
attested checkpoint / 沙箱 profile 供密封考试链路使用。"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments"))
sys.path.insert(0, str(PROJ_ROOT / "tests"))

import pytest  # noqa: E402

from rl_curriculum.attestation import (  # noqa: E402
    Ed25519KeyPair,
    TrustedIssuerConfig,
    build_attestation_payload,
    write_attestation,
)
from rl_curriculum.checkpoints import (  # noqa: E402
    is_format_compatible,
    save_checkpoint_manifest,
)
from rl_curriculum.evaluator import EvalConfig  # noqa: E402
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY  # noqa: E402
from rl_curriculum.probe_charter import probe_observation_schema  # noqa: E402

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}

#: mock 受控训练 runner 身份(attestation 的 required_training_runner_hash)
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


@pytest.fixture(scope="session")
def gen_a():
    return DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]


@pytest.fixture(scope="session")
def schema():
    return probe_observation_schema()


@pytest.fixture()
def cfg() -> EvalConfig:
    return EvalConfig(fee=0.001)


@pytest.fixture(scope="session")
def mock_issuer_keypair():
    return Ed25519KeyPair.generate("mock-issuer-stage2-6-0a")


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


def _write_attested_checkpoint(
    ckpt: Path, *, schema, keypair, trusted_issuer, checkpoint_name: str,
) -> dict:
    """训练 tiny PPO + v3 sidecar + 受信 attestation;返回材料 dict。"""
    training_material = _train_tiny_ppo(ckpt)
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": training_material["training_budget"]["total_timesteps"],
        "seed": training_material["training_seed"],
        "note": "测试级 PPO(允许挂科);只验证 provenance 与执行链路",
    }
    tm_path = ckpt.with_name(ckpt.name + ".training_manifest.json")
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    charter_h = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        ckpt, checkpoint_name=checkpoint_name,
        charter_hash=charter_h, observation_schema=schema,
        training_manifest_sha256=tm_sha,
        self_declared_formal_eligible=False)
    sidecar_sha = hashlib.sha256(
        (ckpt.parent / (ckpt.name + ".rl_manifest.json")).read_bytes()
    ).hexdigest()
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
        training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        issued_utc="2026-08-26T00:00:00Z",
    )
    att_doc = write_attestation(
        ckpt.with_name(ckpt.name + ".rl_attestation.json"), keypair, payload)
    return {
        "checkpoint": str(ckpt),
        "attestation": att_doc,
        "training_manifest": training_manifest,
        "training_manifest_sha256": tm_sha,
        "training_material": training_material,
        "charter_hash": charter_h,
    }


@pytest.fixture(scope="session")
def attested_checkpoint(tmp_path_factory, schema, mock_issuer_keypair,
                        mock_trusted_issuer):
    """受信 attestation 加持的测试级 PPO(正式资格的合法来源)。"""
    d = tmp_path_factory.mktemp("attested-ckpt")
    ckpt = d / "tiny_attested.zip"
    material = _write_attested_checkpoint(
        ckpt, schema=schema, keypair=mock_issuer_keypair,
        trusted_issuer=mock_trusted_issuer,
        checkpoint_name="tiny_attested_stage2_6_0a")
    material["trusted_issuer"] = mock_trusted_issuer
    return material


@pytest.fixture(scope="session")
def formal_checkpoint(tmp_path_factory, schema):
    """测试级固定维度 PPO + v3 sidecar(无 attestation)。

    阶段 2.6.0b 语义:sidecar 只证明 format_compatible;
    formal_eligible 恒 False(需要受信 attestation,正式资格不在 sidecar)。
    仅用于守卫/适配器等接口级验证,非正式训练。
    """
    pytest.importorskip("stable_baselines3")
    out = tmp_path_factory.mktemp("a_formal_ckpt")
    path = out / "tiny_formal.zip"
    _train_tiny_ppo(path, n_steps=64, seed=11)

    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    manifest = save_checkpoint_manifest(
        path, checkpoint_name="tiny_formal",
        charter_hash=charter_hash(audit_probe_charter()),
        observation_schema=schema,
    )
    assert manifest["formal_eligible"] is False
    assert is_format_compatible(manifest) is True
    return path


@pytest.fixture()
def sealed_exam_env(tmp_path, attested_checkpoint, sandbox_profile,
                    mock_trusted_issuer, schema):
    """小型密封考试环境 v2:pack + context + commitment + attested
    checkpoint + 注册表路径。

    供 CLI 级 EXAM_INVALID / 幂等 / 脱敏测试复用(篡改在测试内完成)。
    阶段 2.6.0b:pack 严格三族 Null(sign/volstate/stochvol,block 已
    降级为诊断族不进包);commitment 绑定沙箱 profile 与受信 issuer。
    """
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        default_eval_config,
        write_exam_context,
    )
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_platform.versions import spec_versions

    charter = audit_probe_charter()
    eval_config = default_eval_config()
    # 阶段 2.6.0d:严格 Null 每族 32 个 antithetic pair cluster
    # (BASE_PARAMS 与资格规范 episode_bars 一致;namespace 推导)
    import sys as _sys
    from pathlib import Path as _P

    _tests = _P(__file__).resolve().parents[1]
    if str(_tests) not in _sys.path:
        _sys.path.insert(0, str(_tests))
    from null_qual_cache import null_episode_specs

    episodes = [
        EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 1,
                    "train", timeframe="15m"),
        EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 2,
                    "train", timeframe="15m"),
        EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 3,
                    "dev_seed_holdout", timeframe="15m"),
        EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 33,
                    "dev_seed_holdout", timeframe="15m"),
        EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 63,
                    "dev_seed_holdout", timeframe="15m"),
    ] + list(null_episode_specs())
    pack = ExamPack(
        name="a_cli_demo", version="v2", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=episodes,
        timeframe="15m",
    )
    pack.save(tmp_path / "pack.json")
    write_exam_context(
        tmp_path / "ctx.json", charter=charter, schema=schema,
        eval_config=eval_config,
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer)
    # 提交物:attested checkpoint + sidecar + attestation 复制到工作区
    ck_src = Path(attested_checkpoint["checkpoint"])
    ckpt = tmp_path / ck_src.name
    shutil.copyfile(ck_src, ckpt)
    for suffix in (".rl_manifest.json", ".rl_attestation.json"):
        shutil.copyfile(
            Path(str(ck_src) + suffix),
            Path(str(ckpt) + suffix))
    # 阶段 2.6.0d:完整资格链(v3 三态 + 功效分析 + pack-level
    # validity)经共享确定性磁盘缓存;v4 承诺绑定全部材料
    from null_qual_cache import build_commitment_null_materials

    materials = build_commitment_null_materials(
        pack, schema, eval_config)
    commitment = build_mock_commitment(
        builder_provider=MockBuilderIdentityProvider(),
        evidence_path=str(tmp_path / "builder_evidence.json"),
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(),
        eval_config=eval_config,
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    commitment.save(tmp_path / "commitment.json")
    return {
        "tmp": tmp_path, "pack": pack, "charter": charter, "schema": schema,
        "checkpoint": ckpt, "commitment": commitment,
        "eval_config": eval_config,
        "profile": sandbox_profile,
        "trusted_issuer": mock_trusted_issuer,
        "attestation": attested_checkpoint["attestation"],
    }


def run_cli(env_dir, out_name, *extra):
    """密封考试 CLI v3(进程内;正式候选仍由系统级沙箱执行)。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = env_dir["tmp"]
    return exam_main([
        "--sealed-manifest", str(tmp / "commitment.json"),
        "--pack", str(tmp / "pack.json"),
        "--checkpoint", str(env_dir["checkpoint"]),
        "--context", str(tmp / "ctx.json"),
        "--out", str(tmp / out_name),
        "--builder-provider", "mock",
        "--builder-evidence", str(tmp / "builder_evidence.json"),
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])
