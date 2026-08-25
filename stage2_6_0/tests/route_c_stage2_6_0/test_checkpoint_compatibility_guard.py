"""工作包 0/F:checkpoint sidecar manifest 与版本兼容守卫(fail closed)。"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))

from rl_curriculum.charter import charter_hash  # noqa: E402
from rl_curriculum.checkpoints import (  # noqa: E402
    CheckpointCompatibilityError,
    load_checkpoint_manifest,
    load_guarded_checkpoint,
    mark_legacy_engineering_evidence,
    save_checkpoint_manifest,
)
from rl_curriculum.probe_charter import audit_probe_charter  # noqa: E402

CH = charter_hash(audit_probe_charter())


@pytest.fixture(scope="module")
def tiny_checkpoint(tmp_path_factory):
    """极短测试级 PPO(仅接口验证;非正式训练)。"""
    pytest.importorskip("stable_baselines3")
    from stable_baselines3 import PPO

    sys.path.insert(0, str(PROJ_ROOT / "src"))
    from rl_platform.env import AlignedLongFlatEnv

    rng = __import__("numpy").random.default_rng(3)
    n = 48
    rets = rng.normal(0.0005, 0.004, n)
    close = 100.0 * __import__("numpy").cumprod(1 + rets)
    open_ = __import__("numpy").concatenate([[100.0], close[:-1]])
    import pandas as pd

    prices = pd.DataFrame({"open": open_, "close": close,
                           "high": open_ * 1.001, "low": open_ * 0.999})
    feats = pd.DataFrame({"f0": rets})
    env = AlignedLongFlatEnv(features=feats, prices=prices, fee=0.001)
    model = PPO("MlpPolicy", env, n_steps=32, batch_size=32, n_epochs=1,
                seed=1, policy_kwargs={"net_arch": [8, 8]}, verbose=0,
                device="cpu")
    model.learn(total_timesteps=32)
    out = tmp_path_factory.mktemp("ckpt")
    path = out / "tiny.zip"
    model.save(str(path).removesuffix(".zip"))
    return path


def test_guard_accepts_matching_checkpoint(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH)
    model, manifest = load_guarded_checkpoint(
        tiny_checkpoint, expected_charter_hash=CH)
    assert manifest["formal_eligible"] is True
    assert model is not None


def test_guard_rejects_missing_sidecar(tiny_checkpoint):
    sc = tiny_checkpoint.with_name(tiny_checkpoint.name + ".rl_manifest.json")
    if sc.exists():
        sc.unlink()
    with pytest.raises(CheckpointCompatibilityError, match="sidecar"):
        load_guarded_checkpoint(tiny_checkpoint)


def test_guard_rejects_version_mismatch(tiny_checkpoint):
    m = save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                                 charter_hash=CH)
    bad = dict(m)
    versions = dict(m["spec_versions"])
    versions["env_core_version"] = "RouteCEnvCore-v0.9.0"
    bad["spec_versions"] = versions
    sc = tiny_checkpoint.with_name(tiny_checkpoint.name + ".rl_manifest.json")
    sc.write_text(json.dumps(bad))
    with pytest.raises(CheckpointCompatibilityError, match="env_core_version"):
        load_guarded_checkpoint(tiny_checkpoint, expected_charter_hash=CH)
    # observation/action 版本同样必须拒绝
    versions2 = dict(m["spec_versions"])
    versions2["observation_spec_version"] = "ObservationSpec-v2"
    bad2 = dict(m)
    bad2["spec_versions"] = versions2
    sc.write_text(json.dumps(bad2))
    with pytest.raises(CheckpointCompatibilityError):
        load_guarded_checkpoint(tiny_checkpoint)


def test_guard_rejects_charter_mismatch(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH)
    with pytest.raises(CheckpointCompatibilityError, match="章程哈希不匹配"):
        load_guarded_checkpoint(tiny_checkpoint,
                                expected_charter_hash="c-other")


def test_guard_rejects_replaced_binary(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH)
    data = bytearray(tiny_checkpoint.read_bytes())
    data[-1] ^= 0xFF  # 篡改最后一个字节
    tiny_checkpoint.write_bytes(bytes(data))
    with pytest.raises(CheckpointCompatibilityError, match="SHA-256"):
        load_checkpoint_manifest(tiny_checkpoint)


def test_legacy_checkpoint_marked_evidence_only(tiny_checkpoint, tmp_path):
    copy = tmp_path / "legacy.zip"
    shutil.copyfile(tiny_checkpoint, copy)
    sidecar = copy.with_name(copy.name + ".rl_manifest.json")
    if sidecar.exists():
        sidecar.unlink()
    m = mark_legacy_engineering_evidence(copy, note="工程证据")
    assert m["legacy_engineering_evidence"] is True
    assert m["formal_eligible"] is False
    _model, lm = load_guarded_checkpoint(copy, allow_legacy=True)
    assert lm["formal_eligible"] is False  # 不作为正式评估/迁移模型
    with pytest.raises(CheckpointCompatibilityError):
        load_guarded_checkpoint(copy)  # 默认上下文拒绝
    with pytest.raises(CheckpointCompatibilityError):
        load_guarded_checkpoint(copy, allow_legacy=True,
                                expected_charter_hash=CH)  # 无章程资格


def test_sb3_policy_adapter_runs(tiny_checkpoint):
    from rl_curriculum.policies import SB3CheckpointPolicy

    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH)
    pol = SB3CheckpointPolicy(tiny_checkpoint, expected_charter_hash=CH)
    assert pol.manifest["charter_hash"] == CH
