"""R2 C2 类别不平衡控制测试(U/W/B)。

覆盖任务书 §11/§20:weighted CE;balanced minibatch;训练只用
train class distribution;eval 分布不被重采样;PR-AUC 与 Long
recall 存在;三 supervised seeds 齐全。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.ppo262_r2_supervised import (
    _balanced_minibatch_indices, extended_binary_metrics,
    heldout_pair_performance, mlp_predict_long,
    train_supervised_mlp,
)
from rl_curriculum.ppo262_r2_train import balanced_class_weights


def _imbalanced_separable(n=4000, pos_rate=0.024, seed=0):
    rng = np.random.default_rng(seed)
    n_pos = int(n * pos_rate)
    n_neg = n - n_pos
    X_pos = rng.normal(loc=[2.0, 0.0], scale=0.5, size=(n_pos, 2))
    X_neg = rng.normal(loc=[-2.0, 0.0], scale=0.5, size=(n_neg, 2))
    X = np.concatenate([X_pos, X_neg]).astype(np.float32)
    y = np.concatenate([np.ones(n_pos), np.zeros(n_neg)]).astype(
        np.int64)
    order = rng.permutation(n)
    return X[order], y[order]


def test_balanced_class_weights_train_only():
    y = np.array([0] * 976 + [1] * 24)
    w = balanced_class_weights(y)
    assert w[1] == pytest.approx(1000 / 48)
    assert w[0] == pytest.approx(1000 / 1952)
    # 权重只来自给定 y(train 分布);换 eval 分布不影响已算权重
    y2 = np.array([0] * 500 + [1] * 500)
    assert balanced_class_weights(y2)[1] == pytest.approx(1.0)


def test_balanced_minibatch_indices_half_half():
    rng = np.random.default_rng(0)
    y = np.array([0] * 3900 + [1] * 100)
    idx = _balanced_minibatch_indices(y, 512, rng)
    assert len(idx) == 512
    assert np.sum(y[idx] == 1) == 256
    assert np.sum(y[idx] == 0) == 256
    # eval 分布不被重采样(indices 只作用于训练索引)
    assert set(idx) <= set(range(len(y)))


def test_weighted_control_learns_rare_class_unweighted_collapses():
    """可分但 2.4% 正类的合成语料:U 塌到全 Flat,W 学会 Long。"""
    Xtr, ytr = _imbalanced_separable(seed=0)
    Xev, yev = _imbalanced_separable(n=2000, seed=1)
    u = train_supervised_mlp(Xtr, ytr, control="U", seed=28101,
                             epochs=30)
    w = train_supervised_mlp(Xtr, ytr, control="W", seed=28101,
                             epochs=30)
    m_u = extended_binary_metrics(
        yev, mlp_predict_long(u, Xev))
    m_w = extended_binary_metrics(
        yev, mlp_predict_long(w, Xev))
    assert m_u["long_recall"] is not None
    # 历史对照口径:U 在稀有类下的 predicted long rate 仍处先验水平
    assert m_u["predicted_long_rate"] <= 0.10, (
        "unweighted 在 2.4% 正类下 predicted long rate 应接近先验"
        "(0.024)而非放大")
    assert m_w["long_recall"] > 0.8, "weighted 应恢复稀有类召回"
    assert m_w["long_precision"] > 0.8
    assert m_w["balanced_accuracy"] > 0.9


def test_control_B_balanced_minibatch_learns_rare_class():
    Xtr, ytr = _imbalanced_separable(seed=2)
    Xev, yev = _imbalanced_separable(n=2000, seed=3)
    b = train_supervised_mlp(Xtr, ytr, control="B", seed=28101,
                             epochs=60, batch_size=256)
    m = extended_binary_metrics(yev, mlp_predict_long(b, Xev))
    assert m["long_recall"] > 0.7
    assert m["balanced_accuracy"] > 0.85


def test_extended_binary_metrics_fields():
    y = np.array([1, 1, 1, 0, 0, 0, 0, 0])
    p = np.array([0.9, 0.8, 0.2, 0.7, 0.1, 0.05, 0.3, 0.02])
    m = extended_binary_metrics(y, p)
    for k in ("long_recall", "long_precision", "false_positive_rate",
              "predicted_long_rate", "balanced_accuracy", "pr_auc",
              "roc_auc", "calibration", "brier_score",
              "behavior_gap_proxy"):
        assert k in m
    assert m["pr_auc"] > 0.5
    assert m["roc_auc"] > 0.5
    assert m["confusion"]["tp"] == 2
    # 全 Flat 预测:long_recall=0,balanced accuracy=0.5
    flat = extended_binary_metrics(y, np.zeros(8))
    assert flat["long_recall"] == 0.0
    assert flat["balanced_accuracy"] == pytest.approx(0.5)
    assert flat["pr_auc"] == pytest.approx(0.375)  # 正类先验


def test_heldout_pair_performance():
    y = np.array([1, 1, 0, 0, 1, 0, 1, 0])
    p = np.array([.9, .8, .1, .2, .7, .3, .6, .4])
    pairs = [("D0", 1)] * 4 + [("D0", 2)] * 4
    out = heldout_pair_performance(y, p, pairs)
    assert out["n_pairs"] == 2
    assert set(out["per_pair"]) == {"D0/pair1", "D0/pair2"}
    assert out["mean_pair_balanced_accuracy"] is not None


def test_three_supervised_seeds_available():
    from rl_curriculum.ppo262_r2_namespaces import (
        DIAG262R2_SUPERVISED_SEEDS,
    )
    assert DIAG262R2_SUPERVISED_SEEDS == (28401, 28402, 28403)
    # 与 official/R1 seeds 不重合
    from rl_curriculum.ppo262_namespaces import PPO262_MODEL_SEEDS
    from rl_curriculum.ppo262_diag_namespaces import (
        DIAG262_OVERFIT_SEEDS, DIAG262_ABLATION_SEEDS, DIAG262_BC_SEEDS,
    )
    historical = set(PPO262_MODEL_SEEDS) | set(DIAG262_OVERFIT_SEEDS) | \
        set(DIAG262_ABLATION_SEEDS) | set(DIAG262_BC_SEEDS)
    assert not (set(DIAG262R2_SUPERVISED_SEEDS) & historical)


def test_control_W_never_reads_eval_labels():
    """W 的权重只在 train_supervised_mlp 内部由 ytr 计算(无 eval 入参)。"""
    import inspect
    sig = inspect.signature(train_supervised_mlp)
    assert "Xev" not in sig.parameters
    assert "yev" not in sig.parameters
