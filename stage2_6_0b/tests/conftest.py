"""阶段 2.6.0b 测试夹具:沙箱 profile / mock issuer / attested checkpoint /
mock sealed 环境。"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

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
from rl_curriculum.probe_charter import probe_observation_schema  # noqa: E402

TRAIN_PARAMS = dict(BASE_PARAMS)

#: mock 受控训练 runner 身份(实验脚本/测试共用)
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


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
    return Ed25519KeyPair.generate("mock-issuer-stage2-6-0b")


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


@pytest.fixture(scope="session")
def attested_checkpoint(tmp_path_factory, schema, mock_issuer_keypair,
                        mock_trusted_issuer):
    """测试级 PPO checkpoint + v3 sidecar + 受信 attestation。

    返回 {checkpoint, sidecar, attestation, manifest, training_manifest,
    training_manifest_sha256, training_material}。
    """
    d = tmp_path_factory.mktemp("attested-ckpt")
    ckpt = d / "test_ppo.zip"
    training_material = _train_tiny_ppo(ckpt)
    # 受控训练 manifest(不可变训练材料)
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": training_material["training_budget"]["total_timesteps"],
        "seed": training_material["training_seed"],
        "note": "测试级 PPO(允许挂科);只验证 provenance 与执行链路",
    }
    tm_path = d / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    charter_h = charter_hash(audit_probe_charter())
    sidecar = save_checkpoint_manifest(
        ckpt, checkpoint_name="test_ppo_stage2_6_0b",
        charter_hash=charter_h, observation_schema=schema,
        training_manifest_sha256=tm_sha,
        self_declared_formal_eligible=False)
    sidecar_sha = hashlib.sha256(
        (d / "test_ppo.zip.rl_manifest.json").read_bytes()).hexdigest()
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
        issuer_id=mock_issuer_keypair.issuer_id,
        training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        issued_utc="2026-08-26T00:00:00Z",
    )
    att_doc = write_attestation(
        ckpt.with_name(ckpt.name + ".rl_attestation.json"),
        mock_issuer_keypair, payload)
    return {
        "checkpoint": str(ckpt),
        "sidecar": sidecar,
        "attestation": att_doc,
        "training_manifest": training_manifest,
        "training_manifest_path": str(tm_path),
        "training_manifest_sha256": tm_sha,
        "training_material": training_material,
        "charter_hash": charter_h,
    }


@pytest.fixture(scope="session")
def null_qual_reports(schema, cfg):
    """三族严格 Null 的资格审查报告(session 级共享;3 seed 最小覆盖)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.null_qualification import qualify_null_family

    reports = {}
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        reports[fam] = qualify_null_family(
            R[fam], params=BASE_PARAMS, timeframe="15m",
            seeds=[11, 22, 33], cfg=cfg, schema=schema)
    return reports


@pytest.fixture(scope="session")
def sealed_exam_env(null_qual_reports, schema, cfg, mock_trusted_issuer,
                    sandbox_profile):
    """mock 密封考试环境:pack + commitment v2 + 全部绑定材料。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
    )
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    charter = audit_probe_charter()
    pack = build_mock_hidden_pack()
    verdict_spec = probe_course_verdict_spec()
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=sandbox_profile,
        trusted_issuer=mock_trusted_issuer,
        null_qualification_bindings=build_null_qualification_bindings(
            null_qual_reports),
    )
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
    }


@pytest.fixture(scope="session")
def sandbox_checkpoint(tmp_path_factory, attested_checkpoint):
    """沙箱执行可用的 checkpoint(同一 attested checkpoint)。"""
    return attested_checkpoint["checkpoint"]


def run_candidate_in_sandbox(checkpoint: str, *, probe_code: str,
                             profile=None, timeout: float = 240):
    """在沙箱内执行攻击探针代码(C8);返回 CompletedProcess。

    探针作为 bootstrap 的 exec 目标运行:与正式候选 worker 相同的
    隔离链(unshare namespaces -> bootstrap mounts/Landlock/rlimits ->
    execve)。
    """
    from rl_curriculum.sandbox import (
        UNSHARE_BIN,
        assemble_runtime_staging,
        build_bootstrap_config,
        default_sandbox_profile,
    )
    import tempfile

    tmp = Path(tempfile.mkdtemp(prefix="sbx-probe-"))
    staging = str(assemble_runtime_staging(str(tmp / "runtime")))
    (tmp / "model").mkdir()
    (tmp / "scratch").mkdir()
    prof = profile or default_sandbox_profile()
    cfg = build_bootstrap_config(
        prof, checkpoint_path=checkpoint, workdir=str(tmp),
        exec_argv=[sys.executable, "-I", "-c", probe_code],
        exec_env={"PATH": "/usr/bin:/bin"}, extra_read_exec=[staging])
    argv = [UNSHARE_BIN, "--user", "--map-root-user", "--mount", "--pid",
            "--mount-proc", "--fork", "--net",
            sys.executable, "-m", "rl_candidate_runtime.bootstrap", cfg]
    env = {"PATH": "/usr/bin:/bin", "PYTHONPATH": staging,
           "LANG": "C.UTF-8"}
    proc = subprocess.run(argv, capture_output=True, text=True, env=env,
                          cwd=staging, timeout=timeout)
    return proc


SANDBOX_PROBE_TEMPLATE = r'''
import json, os, socket, sys

TARGETS = json.loads(r"""__TARGETS_JSON__""")

def try_read(path):
    try:
        with open(path, "rb") as f:
            data = f.read(128)
        return {"ok": True, "len": len(data)}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__,
                "errno": getattr(e, "errno", None)}

def try_list(path):
    try:
        return {"ok": True, "entries": sorted(os.listdir(path))[:20]}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__,
                "errno": getattr(e, "errno", None)}

def try_write(path, data=b"x"):
    try:
        with open(path, "wb") as f:
            f.write(data)
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "err": type(e).__name__,
                "errno": getattr(e, "errno", None)}

report = {"targets": {}, "cwd": os.getcwd(), "extra": {}}
for name, path in TARGETS:
    report["targets"][name] = {"read": try_read(path),
                               "list": try_list(path),
                               "write": try_write(path + ".attempt")}
__EXTRA_CODE__
print(json.dumps(report))
'''


def build_probe_code(extra_code: str = "",
                     targets: list | None = None) -> str:
    """构造沙箱攻击探针(targets 烘焙进代码;extra_code 填充 extra)。"""
    code = SANDBOX_PROBE_TEMPLATE.replace(
        "__TARGETS_JSON__", json.dumps(targets or []))
    code = code.replace("__EXTRA_CODE__", extra_code or "pass")
    return code
