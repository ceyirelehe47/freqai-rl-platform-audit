"""阶段 2.6.0 测试公共夹具。"""

from __future__ import annotations

import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "experiments"))

import pytest  # noqa: E402

from rl_curriculum.evaluator import EvalConfig  # noqa: E402
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY  # noqa: E402


@pytest.fixture(scope="session")
def gen_a():
    return DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]


@pytest.fixture(scope="session")
def gen_b():
    return DEFAULT_GENERATOR_REGISTRY["probe_smooth_latent_drift"]


@pytest.fixture(scope="session")
def gen_c():
    return DEFAULT_GENERATOR_REGISTRY["probe_null_control"]


@pytest.fixture()
def cfg() -> EvalConfig:
    return EvalConfig(fee=0.001)


TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
