"""工作包 F:checkpoint 与课程章程绑定(不属于该课程即拒绝)。"""

from __future__ import annotations

import json
import shutil

from rl_curriculum.checkpoints import save_checkpoint_manifest
from rl_curriculum.sealed_exam import SealedExamError
from tests.route_c_stage2_6_0a.conftest import run_cli


def test_wrong_charter_checkpoint_rejected(sealed_exam_env, tmp_path):
    """checkpoint 绑定其他课程章程 -> CLI EXAM_INVALID。"""
    ckpt = tmp_path / "other_course.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(
        ckpt, checkpoint_name="other_course",
        charter_hash="c-other-course-not-this-one",
        observation_schema=sealed_exam_env["schema"])
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5
    out = json.loads((sealed_exam_env["tmp"] / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_no_charter_checkpoint_rejected(sealed_exam_env, tmp_path):
    ckpt = tmp_path / "no_charter.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(ckpt, checkpoint_name="no_charter",
                             observation_schema=sealed_exam_env["schema"])
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5


def test_committed_checkpoint_sha_pinned(sealed_exam_env, formal_checkpoint,
                                         tmp_path):
    """承诺 pin 具体 checkpoint SHA:任何其他正式 checkpoint 也拒绝。"""
    from rl_curriculum.checkpoints import sha256_file
    from rl_curriculum.sealed_exam import (
        SealedExamError,
        verify_checkpoint_requirements,
    )

    commitment = sealed_exam_env["commitment"]
    commitment.checkpoint_requirements["checkpoint_sha256"] = (
        sha256_file(formal_checkpoint))
    # 另一个合法 checkpoint(不同 SHA)被拒绝:快速训练第二个模型
    import numpy as np
    import pandas as pd
    from stable_baselines3 import PPO
    from rl_platform.env import AlignedLongFlatEnv

    rng = np.random.default_rng(7)
    n = 48
    rets = rng.normal(0.0003, 0.003, n)
    close = 100.0 * np.cumprod(1 + rets)
    open_ = np.concatenate([[100.0], close[:-1]])
    env2 = AlignedLongFlatEnv(
        features=pd.DataFrame({f"f{i}": rng.normal(0, 1, n)
                               for i in range(8)}),
        prices=pd.DataFrame({"open": open_, "close": close,
                             "high": open_ * 1.001, "low": open_ * 0.999}),
        fee=0.001)
    m2 = PPO("MlpPolicy", env2, n_steps=32, batch_size=32, n_epochs=1,
             seed=99, policy_kwargs={"net_arch": [8, 8]}, verbose=0,
             device="cpu")
    m2.learn(total_timesteps=32)
    other = tmp_path / "other_formal.zip"
    m2.save(str(other).removesuffix(".zip"))
    from rl_curriculum.checkpoints import save_checkpoint_manifest

    save_checkpoint_manifest(
        other, checkpoint_name="other_formal",
        charter_hash=sealed_exam_env["commitment"].charter_hash,
        observation_schema=sealed_exam_env["schema"])
    other_sha = sha256_file(other)
    assert other_sha != sha256_file(formal_checkpoint)
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    manifest = load_checkpoint_manifest(other)
    with pytest_raises_sealed():
        verify_checkpoint_requirements(
            commitment, manifest, checkpoint_sha256=other_sha)


def pytest_raises_sealed():
    import pytest

    return pytest.raises(SealedExamError, match="SHA-256")
