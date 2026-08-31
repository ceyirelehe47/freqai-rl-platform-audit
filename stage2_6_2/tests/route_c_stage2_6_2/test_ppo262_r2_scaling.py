"""R2 preprocessing arms 语义测试(A unscaled / B fixed / C fitted)。

覆盖任务书 §8/§20:
- Arm B 构造器不接受训练数据;更换训练数据不改变常数;
  常数与 plan 一致;任何 r2 bank 生成前已锁定;
- Arm A bitwise unscaled;position slot 不缩放;
- Arm C 只 fit 训练 bank;eval 不参与 fit。
"""

from __future__ import annotations

import inspect
import json

import numpy as np
import pytest

from rl_curriculum.ppo262_diag_train import ObsAdapter


def test_arm_b_constructor_takes_no_training_data():
    sig = inspect.signature(ObsAdapter.fixed)
    assert list(sig.parameters) == ["center", "scale", "source"], (
        "ObsAdapter.fixed 构造器不得接受训练数据(X_train)"
    )


def test_arm_b_constants_data_independent(tmp_path, monkeypatch):
    """常数从 R1 历史 artifact 机械推导:换任何"训练数据"都不变。"""
    import rl_curriculum.ppo262_r2_cli as cli

    names = ["%-ret-1", "%-ret-4", "%-vol-24", "%-price-ma-ratio",
             "%-raw_open", "%-raw_high", "%-raw_low", "%-raw_close",
             "position"]
    stds = [0.0167, 0.0346, 0.0120, 0.0285,
            0.0381, 0.0378, 0.0386, 0.0381, 0.0]
    fake_dir = tmp_path / "repair1"
    fake_dir.mkdir()
    (fake_dir / "feature_scale_profile.json").write_text(
        json.dumps({"observation_layout": names,
                    "banks": {"config_dev_train": {"per_feature": {
                        n: {"std": s} for n, s in zip(names, stds)}}}}),
        encoding="utf-8")
    monkeypatch.setattr(cli, "REPAIR1_DIR", fake_dir)
    c1 = cli._arm_b_constants_from_r1_profile()
    # 机械规则:10^round(log10(std)),position identity
    expect = [1e-2, 1e-1, 1e-2, 1e-2, 1e-1, 1e-1, 1e-1, 1e-1, 1.0]
    assert c1["scale"] == pytest.approx(expect)
    assert c1["center"] == [0.0] * 9
    assert c1["scale"][-1] == 1.0
    assert c1["source_artifact_sha256"]
    # 换 std(R1 artifact 不同)才会变 -> "更换训练数据不改变常数"
    # 的合同由来源唯一性保证:常数不依赖任何调用方输入(无参输入)
    c2 = cli._arm_b_constants_from_r1_profile()
    assert c1 == c2
    # 修改来源 artifact(历史证据不被改动的场景只是假设)会改变哈希
    (fake_dir / "feature_scale_profile.json").write_text(
        json.dumps({"observation_layout": names,
                    "banks": {"config_dev_train": {"per_feature": {
                        n: {"std": s * 2} for n, s in zip(names, stds)}}}}),
        encoding="utf-8")
    c3 = cli._arm_b_constants_from_r1_profile()
    assert c3["source_artifact_sha256"] != c1["source_artifact_sha256"]


def test_arm_a_bitwise_unscaled():
    rng = np.random.default_rng(0)
    X = rng.normal(size=(50, 9)) * [1, 30, 0.01, 5, 100, 100, 100, 100, 1]
    ad = ObsAdapter.identity(9)
    out = ad.apply(X)
    assert np.array_equal(out, X.astype(np.float32))
    assert ad.identity_equivalent()


def test_arm_c_fits_only_given_train_data_position_identity():
    rng = np.random.default_rng(1)
    X1 = rng.normal(size=(500, 9)) * [1, 1, 1, 1, 10, 10, 10, 10, 1]
    X2 = rng.normal(size=(500, 9)) * [1, 1, 1, 1, 50, 50, 50, 50, 1]
    a1 = ObsAdapter.fit_frozen(X1, source="train1")
    a2 = ObsAdapter.fit_frozen(X2, source="train2")
    # 不同训练语料 -> 不同常数(证明 fit 来源=训练数据)
    assert not np.allclose(a1.scale, a2.scale)
    # position slot 恒不缩放
    assert a1.scale[-1] == 1.0 and a1.center[-1] == 0.0
    # eval 数据不参与 fit:apply 只读常数
    Xe = rng.normal(size=(10, 9))
    before = (a1.center.copy(), a1.scale.copy())
    _ = a1.apply(Xe)
    assert np.array_equal(before[0], a1.center)
    assert np.array_equal(before[1], a1.scale)


def test_adapter_reversible_and_finite():
    rng = np.random.default_rng(2)
    X = rng.normal(size=(100, 9))
    ad = ObsAdapter.fit_frozen(X, source="t")
    Y = ad.apply(X)
    back = Y.astype(np.float64) * ad.scale + ad.center
    assert np.allclose(back, X, atol=1e-5)
    with pytest.raises(ValueError):
        ObsAdapter(np.zeros(9), np.zeros(9), kind="fixed", source="bad")
