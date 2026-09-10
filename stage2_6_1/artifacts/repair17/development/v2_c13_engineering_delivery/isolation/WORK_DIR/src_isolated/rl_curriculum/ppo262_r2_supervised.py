"""阶段 2.6.2 Repair R2:family 分开的监督对照(U/W/B)与扩展二分类指标。

R1 缺陷:C2 的 reference Long label 仅约 2.4%,unweighted full-batch
CE 直接收敛到全 Flat;且 C1/C2/C3 混进一个 classifier。R2:

- 每族独立执行(linear + MLP × 3 supervised seeds);
- Control U — Unweighted CE(R1 历史对照口径);
- Control W — Class-Weighted CE(权重只来自 train label 分布,
  绝不读 eval labels);
- Control B — Balanced Minibatches(每 minibatch 内 Long/Flat 各半;
  只重采样训练呈现,不改 eval 分布);
- 指标:balanced accuracy 之外至少报告 Long recall / Long precision /
  PR-AUC / ROC-AUC / FPR / predicted Long rate / 概率校准 /
  behavior-gap proxy / held-out pair performance。
"""

from __future__ import annotations

from typing import Any

import numpy as np


CONTROL_KINDS = ("U", "W", "B")


def balanced_class_weights_torch(y: np.ndarray) -> dict[int, float]:
    """逆频率类权重(只来自给定 label 分布;train-only 合同)。"""
    from rl_curriculum.ppo262_r2_train import balanced_class_weights
    return balanced_class_weights(y)


# ---------------------------------------------------------------- 指标
def extended_binary_metrics(y_true: np.ndarray, p_long: np.ndarray,
                            *, threshold: float = 0.5) -> dict[str, Any]:
    """二分类(Long=1)扩展指标(输入概率;threshold 得到硬判决)。"""
    from rl_curriculum.ppo262_diag_metrics import calibration_curve_summary

    y = np.asarray(y_true, dtype=int)
    p = np.asarray(p_long, dtype=float)
    pred = (p >= threshold).astype(int)
    tp = int(np.sum((pred == 1) & (y == 1)))
    fp = int(np.sum((pred == 1) & (y == 0)))
    fn = int(np.sum((pred == 0) & (y == 1)))
    tn = int(np.sum((pred == 0) & (y == 0)))
    long_recall = tp / (tp + fn) if (tp + fn) else None
    long_precision = tp / (tp + fp) if (tp + fp) else None
    flat_recall = tn / (tn + fp) if (tn + fp) else None
    fpr = fp / (fp + tn) if (fp + tn) else None
    recalls = [r for r in (long_recall, flat_recall) if r is not None]
    bal = float(np.mean(recalls)) if recalls else None
    out: dict[str, Any] = {
        "n": int(len(y)),
        "true_long_rate": float(np.mean(y == 1)) if len(y) else None,
        "predicted_long_rate": float(np.mean(pred == 1)) if len(y) else None,
        "accuracy": float(np.mean(pred == y)) if len(y) else None,
        "balanced_accuracy": bal,
        "long_recall": long_recall,
        "long_precision": long_precision,
        "flat_recall": flat_recall,
        "false_positive_rate": fpr,
        "confusion": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
        "calibration": calibration_curve_summary(y, p),
        "brier_score": float(np.mean((p - y) ** 2)) if len(y) else None,
    }
    try:
        from sklearn.metrics import (
            average_precision_score, roc_auc_score,
        )
        if len(np.unique(y)) == 2:
            out["pr_auc"] = float(average_precision_score(y, p))
            out["roc_auc"] = float(roc_auc_score(y, p))
        else:
            out["pr_auc"] = None
            out["roc_auc"] = None
    except ImportError:
        out["pr_auc"] = None
        out["roc_auc"] = None
        out["sklearn_missing"] = True
    # behavior-gap proxy(与 supervised_metrics 同口径)
    if len(y) and np.any(y == 1) and np.any(y == 0):
        out["behavior_gap_proxy"] = float(
            np.mean(pred[y == 1] == 1) - np.mean(pred[y == 0] == 1))
    else:
        out["behavior_gap_proxy"] = None
    return out


def heldout_pair_performance(y_true, p_long, row_pairs) -> dict[str, Any]:
    """逐 held-out pair 的 balanced accuracy 分布。"""
    y = np.asarray(y_true, dtype=int)
    p = np.asarray(p_long, dtype=float)
    pairs: dict[tuple, list[int]] = {}
    for i, pk in enumerate(row_pairs):
        pairs.setdefault(tuple(pk), []).append(i)
    per_pair: dict[str, dict[str, Any]] = {}
    bal_accs = []
    for pk, idxs in sorted(pairs.items(), key=lambda kv: str(kv[0])):
        idxs = np.asarray(idxs)
        yy, pp = y[idxs], p[idxs]
        pred = (pp >= 0.5).astype(int)
        r1 = float(np.mean(pred[yy == 1] == 1)) if np.any(yy == 1) else None
        r0 = (float(np.mean(pred[yy == 0] == 0))
              if np.any(yy == 0) else None)
        rs = [r for r in (r1, r0) if r is not None]
        bal = float(np.mean(rs)) if rs else None
        key = f"{pk[0]}/pair{pk[1]}"
        per_pair[key] = {
            "n": int(len(yy)), "balanced_accuracy": bal,
            "true_long_rate": float(np.mean(yy == 1)),
        }
        if bal is not None:
            bal_accs.append(bal)
    return {
        "n_pairs": len(per_pair),
        "per_pair": per_pair,
        "mean_pair_balanced_accuracy": (
            float(np.mean(bal_accs)) if bal_accs else None),
        "min_pair_balanced_accuracy": (
            float(np.min(bal_accs)) if bal_accs else None),
    }


# ---------------------------------------------------------------- MLP 控制
def _balanced_minibatch_indices(y: np.ndarray, batch_size: int,
                                rng: np.random.Generator) -> np.ndarray:
    """Balanced minibatch 索引(Long/Flat 各半;类别不足时按最少类
    数量 x2 截断并放回重采样补足到 batch_size)。"""
    pos = np.where(y == 1)[0]
    neg = np.where(y == 0)[0]
    half = batch_size // 2
    take_pos = rng.choice(pos, size=half, replace=len(pos) < half)
    take_neg = rng.choice(neg, size=batch_size - half,
                          replace=len(neg) < (batch_size - half))
    return np.concatenate([take_pos, take_neg])


def train_supervised_mlp(
    Xtr: np.ndarray, ytr: np.ndarray, *, control: str, seed: int,
    epochs: int = 20, lr: float = 3e-4, batch_size: int = 512,
) -> dict[str, Any]:
    """训练一个 supervised MLP([128,128] Tanh;control U/W/B)。

    - U:unweighted full-batch CE(R1 口径);
    - W:full-batch weighted CE,权重只来自 ytr;
    - B:balanced minibatch CE(每步 Long/Flat 各半;rng=seed 派生)。
    返回 {"net", "history"};eval 由 caller 用 predict_long 完成。
    """
    import torch
    if control not in CONTROL_KINDS:
        raise ValueError(f"未知 control {control!r}")
    torch.manual_seed(int(seed))
    net = torch.nn.Sequential(
        torch.nn.Linear(Xtr.shape[1], 128), torch.nn.Tanh(),
        torch.nn.Linear(128, 128), torch.nn.Tanh(),
        torch.nn.Linear(128, 2))
    opt = torch.optim.Adam(net.parameters(), lr=lr)
    Xt = torch.as_tensor(Xtr, dtype=torch.float32)
    yt = torch.as_tensor(ytr, dtype=torch.long)
    class_weight = None
    if control == "W":
        wmap = balanced_class_weights_torch(ytr)
        class_weight = torch.as_tensor(
            [wmap[int(c)] for c in (0, 1)], dtype=torch.float32)
    rng = np.random.default_rng(int(seed))
    history = []
    for epoch in range(epochs):
        if control == "B":
            idx = _balanced_minibatch_indices(
                ytr, min(batch_size, len(ytr)), rng)
            xb, yb = Xt[idx], yt[idx]
        else:
            xb, yb = Xt, yt
        opt.zero_grad()
        logits = net(xb)
        if control == "W":
            loss = torch.nn.functional.cross_entropy(
                logits, yb, weight=class_weight)
        else:
            loss = torch.nn.functional.cross_entropy(logits, yb)
        loss.backward()
        opt.step()
        history.append({"epoch": epoch + 1, "loss": float(loss.item())})
    return {"net": net, "history": history, "control": control,
            "seed": int(seed)}


def mlp_predict_long(trained: dict[str, Any], X: np.ndarray) -> np.ndarray:
    """MLP 的 P(Long)(softmax[:,1])。"""
    import torch
    with torch.no_grad():
        logits = trained["net"](
            torch.as_tensor(X, dtype=torch.float32))
        return torch.softmax(logits, dim=-1)[:, 1].numpy()


def train_linear_probe(Xtr: np.ndarray, ytr: np.ndarray, *,
                       seed: int = 262):
    from sklearn.linear_model import LogisticRegression
    lin = LogisticRegression(max_iter=2000, random_state=int(seed))
    lin.fit(Xtr, ytr)
    return lin
