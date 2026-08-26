"""阶段 2.6.0 测试公共夹具(阶段 2.6.0a 更新:新增 observation schema)。"""

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
def formal_checkpoint(tmp_path_factory):
    """阶段 2.6.0a:测试级固定维度 PPO checkpoint + v2 sidecar(正式资格)。

    仅用于验证正式接口(非正式训练):schema 8 特征 + 仓位槽位 -> obs dim 9。
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
    feats = pd.DataFrame(
        {f"f{i}": rng.normal(0, 1, n) for i in range(8)})
    env = AlignedLongFlatEnv(features=feats, prices=prices, fee=0.001)
    model = PPO("MlpPolicy", env, n_steps=32, batch_size=32, n_epochs=1,
                seed=1, policy_kwargs={"net_arch": [8, 8]}, verbose=0,
                device="cpu")
    model.learn(total_timesteps=64)
    out = tmp_path_factory.mktemp("formal_ckpt")
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
def cfg() -> EvalConfig:
    return EvalConfig(fee=0.001)


TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
