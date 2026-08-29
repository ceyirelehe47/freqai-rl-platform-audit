"""工作包 0/F + 阶段 2.6.0a 工作包 F:checkpoint sidecar 与守卫。

阶段 2.6.0a 语义变化(旧断言与新断言差异见报告第 24 节):
- sidecar v2 绑定 observation schema(有序特征/shape/window/dtype/
  归一化 pipeline);formal_eligible 需要 charter + observation 绑定;
- v1 sidecar(阶段 2.6.0)即使写了 formal_eligible=true 也被视为
  不具备正式资格(is_formal_eligible 强制 False);
- SB3CheckpointPolicy 的 expected_charter_hash 与
  expected_observation_schema_hash 均为必填(无法"忘记传参"跳过校验)。
阶段 2.6.0b 更新:sidecar v3 的 formal_eligible 恒 False(自声明被忽略,
正式资格唯一来源是受信 training attestation);"双绑定即正式"的旧断言
改为"双绑定 -> is_format_compatible 为真 + is_formal_eligible 恒假"。
"""

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
    is_format_compatible,
    is_formal_eligible,
    load_checkpoint_manifest,
    load_guarded_checkpoint,
    mark_legacy_engineering_evidence,
    save_checkpoint_manifest,
)
from rl_curriculum.probe_charter import (  # noqa: E402
    audit_probe_charter,
    probe_observation_schema,
)

CH = charter_hash(audit_probe_charter())
SCHEMA = probe_observation_schema()
OH = SCHEMA.schema_hash()


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


def _sidecar(checkpoint):
    return checkpoint.with_name(checkpoint.name + ".rl_manifest.json")


def test_guard_accepts_matching_checkpoint(tiny_checkpoint):
    m = save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                                 charter_hash=CH,
                                 observation_schema=SCHEMA)
    # 阶段 2.6.0b:sidecar 自声明的 formal_eligible 被明确忽略(恒 False);
    # 双绑定只证明 format_compatible,正式资格来自受信 attestation
    assert m["formal_eligible"] is False
    assert m["formal_eligibility_source"] == (
        "training_attestation_only(rl_curriculum.attestation;"
        "sidecar 自声明无效)")
    assert is_format_compatible(m) is True
    assert is_formal_eligible(m) is False
    # 训练侧强行自声明正式资格同样无效
    m2 = save_checkpoint_manifest(
        tiny_checkpoint, checkpoint_name="tiny",
        charter_hash=CH, observation_schema=SCHEMA,
        self_declared_formal_eligible=True)
    assert m2["self_declared_formal_eligible"] is True
    assert m2["formal_eligible"] is False
    assert is_format_compatible(m2) is True
    assert is_formal_eligible(m2) is False
    model, manifest = load_guarded_checkpoint(
        tiny_checkpoint, expected_charter_hash=CH,
        expected_observation_schema_hash=OH)
    assert manifest["formal_eligible"] is False
    assert model is not None


def test_charter_only_sidecar_not_formal(tiny_checkpoint):
    """只绑定 charter、不绑定 observation schema -> formal_eligible=false
    (阶段 2.6.0 旧断言认为 charter 即 formal;新断言要求双绑定)。"""
    m = save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                                 charter_hash=CH)
    assert m["formal_eligible"] is False
    assert is_formal_eligible(m) is False
    # 可加载做接口验证,但正式上下文(observation 绑定)拒绝
    load_guarded_checkpoint(tiny_checkpoint, expected_charter_hash=CH)
    with pytest.raises(CheckpointCompatibilityError, match="observation"):
        load_guarded_checkpoint(
            tiny_checkpoint, expected_charter_hash=CH,
            expected_observation_schema_hash=OH)


def test_v1_sidecar_never_formal(tiny_checkpoint):
    """伪造 v1 schema 且 formal_eligible=true -> is_formal_eligible 仍 False。"""
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
    m = json.loads(_sidecar(tiny_checkpoint).read_text(encoding="utf-8"))
    m["schema"] = "checkpoint-manifest-v1"
    m.pop("observation_schema_hash", None)
    _sidecar(tiny_checkpoint).write_text(json.dumps(m), encoding="utf-8")
    manifest = load_checkpoint_manifest(tiny_checkpoint)  # v1 可加载
    assert manifest["schema"] == "checkpoint-manifest-v1"
    assert is_formal_eligible(manifest) is False


def test_guard_rejects_missing_sidecar(tiny_checkpoint):
    sc = _sidecar(tiny_checkpoint)
    if sc.exists():
        sc.unlink()
    with pytest.raises(CheckpointCompatibilityError, match="sidecar"):
        load_guarded_checkpoint(tiny_checkpoint)


def test_guard_rejects_version_mismatch(tiny_checkpoint):
    m = save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                                 charter_hash=CH,
                                 observation_schema=SCHEMA)
    bad = dict(m)
    versions = dict(m["spec_versions"])
    versions["env_core_version"] = "RouteCEnvCore-v0.9.0"
    bad["spec_versions"] = versions
    _sidecar(tiny_checkpoint).write_text(json.dumps(bad), encoding="utf-8")
    with pytest.raises(CheckpointCompatibilityError, match="env_core_version"):
        load_guarded_checkpoint(
            tiny_checkpoint, expected_charter_hash=CH,
            expected_observation_schema_hash=OH)
    versions2 = dict(m["spec_versions"])
    versions2["observation_spec_version"] = "ObservationSpec-v2"
    bad2 = dict(m)
    bad2["spec_versions"] = versions2
    _sidecar(tiny_checkpoint).write_text(json.dumps(bad2), encoding="utf-8")
    with pytest.raises(CheckpointCompatibilityError):
        load_guarded_checkpoint(tiny_checkpoint)


def test_guard_rejects_charter_mismatch(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
    with pytest.raises(CheckpointCompatibilityError, match="章程哈希不匹配"):
        load_guarded_checkpoint(tiny_checkpoint,
                                expected_charter_hash="c-other",
                                expected_observation_schema_hash=OH)


def test_guard_rejects_observation_schema_mismatch(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
    with pytest.raises(CheckpointCompatibilityError,
                       match="observation schema hash 不匹配"):
        load_guarded_checkpoint(tiny_checkpoint,
                                expected_charter_hash=CH,
                                expected_observation_schema_hash="o-other")


def test_guard_rejects_reordered_features_binding(tiny_checkpoint):
    """相同维度但特征顺序不同 -> 拒绝(语义错位,总维度相同不算数)。"""
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
    m = json.loads(_sidecar(tiny_checkpoint).read_text(encoding="utf-8"))
    names = m["observation_feature_names"]
    m["observation_feature_names"] = [names[1], names[0]] + names[2:]
    # 保持维度相同:顺序交换不改变 dim;schema hash 不变(伪造)但特征序不同
    _sidecar(tiny_checkpoint).write_text(json.dumps(m), encoding="utf-8")
    # sidecar binding 与 schema 精确比较:assert_same_semantics 拒绝
    with pytest.raises(Exception, match="有序特征名不同|不匹配"):
        from rl_curriculum.policies import SB3CheckpointPolicy

        SB3CheckpointPolicy(
            tiny_checkpoint,
            expected_charter_hash=CH,
            expected_observation_schema_hash=OH,
            schema=SCHEMA)


def test_guard_rejects_replaced_binary(tiny_checkpoint):
    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
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


def test_sb3_policy_adapter_requires_both_bindings(tiny_checkpoint):
    """SB3CheckpointPolicy 双必填:缺任一哈希参数 -> TypeError(无法跳过)。"""
    from rl_curriculum.policies import SB3CheckpointPolicy

    save_checkpoint_manifest(tiny_checkpoint, checkpoint_name="tiny",
                             charter_hash=CH, observation_schema=SCHEMA)
    with pytest.raises(TypeError):
        SB3CheckpointPolicy(tiny_checkpoint)  # 缺 charter/obs 绑定
    with pytest.raises(TypeError):
        SB3CheckpointPolicy(tiny_checkpoint, expected_charter_hash=CH)
    pol = SB3CheckpointPolicy(
        tiny_checkpoint, expected_charter_hash=CH,
        expected_observation_schema_hash=OH, schema=SCHEMA)
    assert pol.manifest["charter_hash"] == CH
    assert pol.manifest["observation_schema_hash"] == OH
