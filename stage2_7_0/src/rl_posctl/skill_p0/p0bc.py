# -*- coding: utf-8 -*-
"""PSC_P0_v1 BC 诊断(仅表示/监督拟合诊断;主 PPO 全新初始化)。

- BC-A(人工目标映射):合成可观察输入表,标签=事前简单映射
  (12 类:HOLD、原子 −1/0/+1、8 个内部目标);映射规则:
    dim0(cue)∈[−1,1] → REBALANCE(dim0);dim0=2.0 → HOLD;
    其余 7 维为种子化填充(与真实观察同量级;dim7=0.5 即 H=64)。
  不从隐藏未来读答案;训练/验证各目标与分支全覆盖。
- BC-B(同信息 C1 教师):行=DP 状态空间抽样(s,c,q,g,W_GRID
  敞口点,remaining),标签=同信息数值参考动作(教师知道公开转移
  律;不读未来/样本 ID);并列规则:best−hv<1e-12 → 标 HOLD。
- 拟合:两分布 × 3 BC seed × 512 minibatch(batch≤256,Adam 3e-4);
  验证门:分支准确率 ≥95%、内部确定性 MAE ≤0.05、内部随机 ≥90%
  落 ±0.10、原子解码语义正确;逐目标报告。
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import numpy as np
import torch as th

from rl_posctl.curriculum import W_GRID
from rl_posctl.skill_p0.p0policy import P0ActorCriticPolicy
from rl_posctl.skill_p0.p0spec import (
    BC_ACC_GATE, BC_MAE_GATE, BC_STOCH_GATE, BC_TRAIN_ROWS, BC_VAL_ROWS,
    BC_UPDATES_PER_FIT, INTERIOR_TARGETS, LEARNING_RATE, TEACHER_TIE_TOL,
    p0_seed)

BC_A_CLASSES = (
    ("hold", 2.0), ("atom", -1.0), ("atom", 0.0), ("atom", 1.0)) + tuple(
    ("interior", t) for t in INTERIOR_TARGETS)
_STOCH_PER_ROW = 10


def _fill_dims(rng: np.random.Generator, n: int) -> np.ndarray:
    """dims1..7 种子化填充(s/c/q/g 状态、账户、时间;H=64)。"""
    cols = []
    cols.append(rng.integers(0, 2, size=n).astype(float))
    cols.append(rng.choice([0.0, 0.25, 0.5, 0.75, 1.0], size=n))
    cols.append(rng.integers(0, 2, size=n).astype(float))
    cols.append(np.arcsinh(rng.uniform(-1.25, 1.25, size=n)) / 4.0)
    cols.append(np.arcsinh(np.minimum(
        rng.uniform(1.0, 40.0, size=n), 40.0)) / 4.0)
    cols.append(rng.integers(1, 65, size=n).astype(float) / 128.0)
    cols.append(np.full(n, 64.0 / 128.0))
    return np.stack(cols, axis=1)


def build_bc_a_tables() -> dict:
    """BC-A 表(确定性;train 2048/val 1024;12 类全覆盖)。"""
    def _make(n_rows: int, part: int) -> dict:
        rng = np.random.default_rng(p0_seed("bc_manual", 0, part))
        per = n_rows // len(BC_A_CLASSES)
        rem = n_rows - per * len(BC_A_CLASSES)
        cues, labels = [], []
        for ci, (kind, val) in enumerate(BC_A_CLASSES):
            cnt = per + (1 if ci < rem else 0)
            cues.append(np.full(cnt, val, dtype=float))
            labels.extend([(kind, val)] * cnt)
        cue = np.concatenate(cues)
        rest = _fill_dims(rng, n_rows)
        obs = np.concatenate([cue[:, None], rest], axis=1).astype(
            np.float32)
        actions = np.zeros((n_rows, 2), dtype=np.float32)
        for i, (kind, val) in enumerate(labels):
            if kind == "hold":
                actions[i] = (0.0, 0.0)
            else:
                actions[i] = (1.0, float(val))
        return {"obs": obs, "actions": actions,
                "kinds": [k for k, _ in labels],
                "targets": [float(v) for _, v in labels]}
    return {"train": _make(BC_TRAIN_ROWS, 0),
            "val": _make(BC_VAL_ROWS, 1)}


def _solv_of_w(w: float) -> float:
    """刚调仓到 w(净值 100,价格 100)的偿付比:20/|w|(w=0 取 40)。"""
    return min(40.0, 20.0 / max(abs(w), 1e-9))


def teacher_label(ref: dict, s: float, c: float, q: float, g: float,
                  w: float, remaining: int) -> dict:
    """同信息教师:DP 策略查表 + 并列规则(best−hv<tol → HOLD)。"""
    table = ref["table"]
    state = np.array([s, c, q, g])
    d = np.abs(table - state).sum(axis=1)
    i = int(np.argmin(d))
    if d[i] > 1e-9:
        raise RuntimeError(f"教师状态不匹配 {state}")
    w_idx = int(np.argmin(np.abs(ref["grid"] - w)))
    sl = int(remaining)
    pol = ref["policies"][sl][i, w_idx]
    hv = float(ref["hold_values"][sl][i, w_idx])
    vv = float(ref["values"][sl][i, w_idx])
    advantage = float(vv - hv)
    if pol < 0:                          # DP 已取 HOLD(tie 或更优)
        return {"branch": 0, "w": 0.0, "advantage": advantage,
                "near_tie_hold": True}
    if advantage < TEACHER_TIE_TOL:      # 近似并列 → HOLD(预注册)
        return {"branch": 0, "w": 0.0, "advantage": advantage,
                "near_tie_hold": True}
    return {"branch": 1, "w": float(W_GRID[int(pol)]),
            "advantage": advantage, "near_tie_hold": False}


def build_bc_b_tables(ref: dict) -> dict:
    """BC-B 表(DP 状态空间抽样;train/val 隔离;覆盖校验+确定性补足)。"""
    s_vals = (-1.0, 0.0, 1.0)
    c_vals = (0.0, 1.0)
    q_vals = (0.0, 0.25, 0.5, 0.75, 1.0)
    g_vals = (0.0, 1.0)
    w_vals = [float(x) for x in W_GRID]

    def _rows(n_rows: int, part: int) -> dict:
        rng = np.random.default_rng(p0_seed("bc_teacher", 0, part))
        picks = []
        seen = set()
        while len(picks) < n_rows:
            pick = (s_vals[rng.integers(0, 3)], c_vals[
                rng.integers(0, 2)], q_vals[rng.integers(0, 5)],
                g_vals[rng.integers(0, 2)],
                w_vals[int(rng.integers(0, len(w_vals)))],
                int(rng.integers(1, 65)))
            if pick not in seen:
                seen.add(pick)
                picks.append(pick)
        obs = np.zeros((n_rows, 8), dtype=np.float32)
        actions = np.zeros((n_rows, 2), dtype=np.float32)
        kinds, targets, advs = [], [], []
        for i, (s, c, q, g, w, rem) in enumerate(picks):
            lab = teacher_label(ref, s, c, q, g, w, rem)
            obs[i] = (s, c, q, g, math.asinh(w) / 4.0,
                      math.asinh(_solv_of_w(w)) / 4.0,
                      rem / 128.0, 64.0 / 128.0)
            actions[i] = (float(lab["branch"]), float(lab["w"]))
            if lab["branch"] == 0:
                kinds.append("hold")
                targets.append(0.0)
            elif lab["w"] in (-1.0, 0.0, 1.0):
                kinds.append("atom")
                targets.append(float(lab["w"]))
            else:
                kinds.append("interior")
                targets.append(float(lab["w"]))
            advs.append(lab["advantage"])
        return {"obs": obs, "actions": actions, "kinds": kinds,
                "targets": targets, "advantages": advs}

    train = _rows(BC_TRAIN_ROWS, 0)
    val = _rows(BC_VAL_ROWS, 1)
    # C1 启蒙参数下教师最优动作收敛到 {HOLD,0,±1}(Kelly μ/σ²≫1,
    # 中间仓位无经济依据——C4 课题 NOT_RUN);覆盖要求=分支级:
    # hold/rebalance 各≥30;内部标签如实计数(可为 0,内部表达前提
    # 由纯分布检查+BC-A 承担,不以教师表冒充)。
    for name, tab in (("train", train), ("val", val)):
        n_hold = tab["kinds"].count("hold")
        n_rebal = len(tab["kinds"]) - n_hold
        if n_hold < 30 or n_rebal < 30:
            raise RuntimeError(
                f"BC-B {name} 分支覆盖不足 hold={n_hold} "
                f"rebalance={n_rebal}(需各≥30)")
    return {"train": train, "val": val}


# ---------------------------------------------------------------------------
# 拟合与验证
# ---------------------------------------------------------------------------
def _decode_actions(policy, obs: th.Tensor) -> np.ndarray:
    with th.no_grad():
        view = policy.get_distribution(obs)
        return view.mode().numpy()


def bc_validate(policy, table: dict, *, sampler_meter=None,
                seed: int) -> dict:
    obs = th.as_tensor(table["obs"], dtype=th.float32)
    acts = table["actions"]
    dec = _decode_actions(policy, obs)
    kinds = np.array(table["kinds"])
    targets = np.array(table["targets"], dtype=float)
    n = len(kinds)
    branch_ok = (dec[:, 0] == acts[:, 0])
    acc = float(branch_ok.mean())
    interior = kinds == "interior"
    mae = float(np.mean(np.abs(
        dec[interior, 1] - targets[interior]))) if interior.any() else None
    stoch_frac = None
    if interior.any():
        th.manual_seed(seed)
        idx = np.where(interior)[0]
        with th.no_grad():
            view = policy.get_distribution(obs[th.as_tensor(idx)])
            samples = th.stack(
                [view.sample() for _ in range(_STOCH_PER_ROW)], dim=1)
        if sampler_meter is not None:
            sampler_meter(int(samples.numel()))
        ws = samples[:, :, 1].numpy()
        stoch_frac = float(np.mean(
            np.abs(ws - targets[idx][:, None]) <= 0.10))
    atom = kinds == "atom"
    atom_ok = None
    if atom.any():
        atom_ok = float(np.mean(
            (dec[atom, 0] == acts[atom, 0])
            & (dec[atom, 1] == acts[atom, 1])))
    per_target = {}
    for tgt in sorted(set(float(t) for t in targets[interior])):
        sel = interior & (targets == tgt)
        per_target[f"{tgt:+.2f}"] = {
            "n": int(sel.sum()),
            "branch_acc": float(branch_ok[sel].mean()),
            "mae": float(np.mean(np.abs(
                dec[sel, 1] - targets[sel]))),
        }
    return {"n": n, "branch_accuracy": acc, "interior_mae": mae,
            "interior_stoch_within_0p10": stoch_frac,
            "atom_semantics_ok": atom_ok,
            "hold_share": float((kinds == "hold").mean()),
            "per_target": per_target}


def bc_fit(*, arm: str, seed: int, tables: dict, out_dir: Path,
           ledger, tag: str, sampler_meter=None) -> dict:
    """一次 BC 拟合:预约(bc_fits/epochs/updates)→512 minibatch →
    验证 → 结清。epochs = 等价全通过数(=updates·batch/rows,向上取整)"""
    from gymnasium import spaces
    obs_space = spaces.Box(-np.inf, np.inf, (8,), np.float32)
    act_space = spaces.Box(np.array([0.0, -1.0]),
                           np.array([1.0, 1.0]), dtype=np.float32)
    th.manual_seed(seed)
    policy = P0ActorCriticPolicy(
        obs_space, act_space, lambda _: LEARNING_RATE, arm=arm)
    n_rows = len(tables["train"]["kinds"])
    epochs_eq = int(math.ceil(
        BC_UPDATES_PER_FIT * 256 / n_rows))
    rid = ledger.reserve(
        f"bc:{tag}", bc_fits=1, bc_epochs=epochs_eq,
        bc_minibatch_updates=BC_UPDATES_PER_FIT)
    rng = np.random.default_rng(seed)
    obs_all = th.as_tensor(tables["train"]["obs"],
                           dtype=th.float32)
    act_all = th.as_tensor(tables["train"]["actions"],
                           dtype=th.float32)
    opt = policy.optimizer
    losses = []
    try:
        for step in range(BC_UPDATES_PER_FIT):
            sel = rng.integers(0, n_rows, size=256)
            obs_b = obs_all[th.as_tensor(sel)]
            act_b = act_all[th.as_tensor(sel)]
            dist = policy.get_distribution(obs_b)
            loss = -dist.log_prob(act_b).mean()
            opt.zero_grad()
            loss.backward()
            opt.step()
            if step % 32 == 0 or step == BC_UPDATES_PER_FIT - 1:
                losses.append({"step": step,
                               "loss": float(loss.item())})
    except BaseException:
        ledger.abandon(rid, f"bc:{tag}",
                       note="BC 拟合异常中断,保守保留预约")
        raise
    val = bc_validate(policy, tables["val"],
                      sampler_meter=sampler_meter, seed=seed)
    n_interior = int(sum(1 for k in tables["val"]["kinds"]
                         if k == "interior"))
    if n_interior > 0:
        gates = {
            "branch_acc_gate": val["branch_accuracy"] >= BC_ACC_GATE,
            "interior_mae_gate": (
                val["interior_mae"] is not None
                and val["interior_mae"] <= BC_MAE_GATE),
            "interior_stoch_gate": (
                val["interior_stoch_within_0p10"] is not None
                and val["interior_stoch_within_0p10"] >= BC_STOCH_GATE),
            "atom_gate": (val["atom_semantics_ok"] is not None
                          and val["atom_semantics_ok"] >= BC_ACC_GATE),
        }
    else:
        # 教师表无内部标签(C1 启蒙最优动作=网格端点/0;见
        # build_bc_b_tables 注):内部门按"不适用"如实记录并排除,
        # 不以 None 冒充通过;内部前提由纯分布检查+BC-A 承担。
        gates = {
            "branch_acc_gate": val["branch_accuracy"] >= BC_ACC_GATE,
            "interior_mae_gate": None,
            "interior_stoch_gate": None,
            "atom_gate": (val["atom_semantics_ok"] is not None
                          and val["atom_semantics_ok"] >= BC_ACC_GATE),
            "interior_gate_not_applicable": True,
        }
    applicable = [v for k, v in gates.items()
                  if v is not None and k != "interior_gate_not_applicable"]
    rec = {"arm": arm, "seed": seed, "tag": tag,
           "updates": BC_UPDATES_PER_FIT, "epochs_eq": epochs_eq,
           "batch": 256, "loss_curve": losses,
           "n_val_interior": n_interior,
           "validation": val, "gates": gates,
           "pass": bool(applicable) and all(applicable)}
    out = Path(out_dir) / f"bc_{arm}_{seed}_{tag}_record.json"
    if out.exists():
        raise RuntimeError(f"BC 记录已存在,拒绝覆盖:{out}")
    out.write_text(json.dumps(rec, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    ledger.commit(rid, f"bc:{tag}", bc_fits=1, bc_epochs=epochs_eq,
                  bc_minibatch_updates=BC_UPDATES_PER_FIT)
    return rec
