"""阶段 2.6.0a 测试公共夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments"))

import pytest  # noqa: E402

from rl_curriculum.evaluator import EvalConfig  # noqa: E402
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY  # noqa: E402
from rl_curriculum.probe_charter import probe_observation_schema  # noqa: E402

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}


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
def formal_checkpoint(tmp_path_factory):
    """测试级固定维度 PPO + v2 sidecar(正式资格;非正式训练)。

    与阶段 2.6.0 的 smoke checkpoint 相同定位:只证明固定维度模型
    能真实执行全部 G4 考试,允许挂科。
    """
    pytest.importorskip("stable_baselines3")
    import numpy as np
    import pandas as pd
    from stable_baselines3 import PPO

    from rl_platform.env import AlignedLongFlatEnv

    rng = np.random.default_rng(3)
    n = 64
    rets = rng.normal(0.0004, 0.003, n)
    close = 100.0 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    prices = pd.DataFrame({"open": open_, "close": close,
                           "high": open_ * 1.001, "low": open_ * 0.999})
    feats = pd.DataFrame({f"f{i}": rng.normal(0, 1, n) for i in range(8)})
    env = AlignedLongFlatEnv(features=feats, prices=prices, fee=0.001)
    model = PPO("MlpPolicy", env, n_steps=32, batch_size=32, n_epochs=1,
                seed=1, policy_kwargs={"net_arch": [8, 8]}, verbose=0,
                device="cpu")
    model.learn(total_timesteps=64)
    out = tmp_path_factory.mktemp("a_formal_ckpt")
    path = out / "tiny_formal.zip"
    model.save(str(path).removesuffix(".zip"))

    from rl_curriculum.charter import charter_hash
    from rl_curriculum.checkpoints import save_checkpoint_manifest
    from rl_curriculum.probe_charter import audit_probe_charter

    manifest = save_checkpoint_manifest(
        path, checkpoint_name="tiny_formal",
        charter_hash=charter_hash(audit_probe_charter()),
        observation_schema=probe_observation_schema(),
    )
    assert manifest["formal_eligible"] is True
    return path


@pytest.fixture()
def sealed_exam_env(tmp_path, formal_checkpoint):
    """小型密封考试环境:pack + context + commitment + checkpoint。

    供 CLI 级 EXAM_INVALID / 幂等 / 脱敏测试复用(篡改在测试内完成)。
    """
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.exam_pack import EpisodeSpec, ExamPack
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        default_eval_config,
        write_exam_context,
    )
    from rl_curriculum.probe_charter import (
        audit_probe_charter,
        probe_observation_schema,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_platform.versions import spec_versions

    charter = audit_probe_charter()
    schema = probe_observation_schema()
    pack = ExamPack(
        name="a_cli_demo", version="v1", visibility="mock_hidden",
        charter_hash=charter_hash(charter),
        spec_versions=spec_versions(),
        episodes=[
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 1,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 2,
                        "train", timeframe="15m"),
            EpisodeSpec("probe_segmented_drift", {"episode_bars": 64}, 3,
                        "dev_seed_holdout", timeframe="15m"),
            EpisodeSpec("probe_null_sign", {"episode_bars": 64}, 4,
                        "null_control", timeframe="15m"),
            EpisodeSpec("probe_null_block", {"episode_bars": 64}, 5,
                        "null_control", timeframe="15m"),
            EpisodeSpec("probe_null_volstate", {"episode_bars": 64}, 6,
                        "null_control", timeframe="15m"),
        ],
        timeframe="15m",
    )
    pack.save(tmp_path / "pack.json")
    write_exam_context(tmp_path / "ctx.json", charter=charter, schema=schema,
                       eval_config=default_eval_config())
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=probe_course_verdict_spec(),
        eval_config=default_eval_config())
    commitment.save(tmp_path / "commitment.json")
    return {
        "tmp": tmp_path, "pack": pack, "charter": charter, "schema": schema,
        "checkpoint": formal_checkpoint, "commitment": commitment,
        "eval_config": default_eval_config(),
    }


def run_cli(env_dir, out_name, *extra):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = env_dir["tmp"]
    return exam_main([
        "--sealed-manifest", str(tmp / "commitment.json"),
        "--pack", str(tmp / "pack.json"),
        "--checkpoint", str(env_dir["checkpoint"]),
        "--context", str(tmp / "ctx.json"),
        "--out", str(tmp / out_name),
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        "--no-subprocess",
        *extra,
    ])
