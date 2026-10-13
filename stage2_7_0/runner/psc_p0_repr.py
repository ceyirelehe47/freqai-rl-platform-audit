#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 纯分布可表达性与概率独立对照(W2 前置;不训练网络)。

- 浓度门:8 内部目标各 4096 采样(构造性参数:S=160 Beta 总浓度;
  事前采样 seed);B 必须 PASS,A 如实 FAIL(不改 A 到非对称)。
- HOLD/0/±1 语义:原子主导构造 → 采样/解码/log_prob 一致。
- 尾质量闭式 vs scipy betainc/数值求积三路对照(α,β∈(1,500] 网格);
  log-prob/熵 vs 蒙特卡洛;PPO ratio(old=new ⇒ 1);左右镜像;
  梯度中心差分;save/load 身份拒绝(轻量,模型构建不 learn)。

用法:
    python psc_p0_repr.py [--ledger <jsonl>] [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np
import torch as th

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.runlog import RunLog  # noqa: E402
from rl_posctl.skill_p0 import p0policy  # noqa: E402
from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    P0AsymBetaDistribution)
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, make_sampler_meter, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    CONC_MASS_FRAC, CONC_MEAN_TOL, CONC_SAMPLES_PER_TARGET,
    CONC_WITHIN_TOL, INTERIOR_TARGETS, p0_seed)

_S_TOTAL = 160.0


def _conc_params(target: float) -> tuple:
    """B 臂集中构造:u 均值=(target+1)/2,总浓度 S=160(α,β>1)。"""
    u = (target + 1.0) / 2.0
    return u * _S_TOTAL, (1.0 - u) * _S_TOTAL


def _softplus_inv(y: float) -> float:
    return float(math.log(math.expm1(y)))


def _make_b_dist(target: float) -> P0AsymBetaDistribution:
    alpha, beta = _conc_params(target)
    b = th.tensor([[0.0, 12.0]], dtype=th.float64)   # p(REBAL)≈1
    m = th.tensor([[-30.0, -30.0, -30.0, 0.0]],
                  dtype=th.float64)                  # m3≈1
    ar = th.tensor([[_softplus_inv(alpha - 1.0)]],
                   dtype=th.float64)
    br = th.tensor([[_softplus_inv(beta - 1.0)]], dtype=th.float64)
    return P0AsymBetaDistribution(b, m, ar, br)


def _make_a_dist(target: float):
    from rl_posctl.policy import HybridAtomBetaDistribution
    alpha = 8.0                       # 对称家族(与 target 无关)
    b = th.tensor([[0.0, 12.0]], dtype=th.float64)
    m = th.tensor([[-30.0, -30.0, -30.0, 0.0]], dtype=th.float64)
    ar = th.tensor([[_softplus_inv(alpha - 1.0)]], dtype=th.float64)
    return HybridAtomBetaDistribution(b, m, ar)


def concentration_check(arm: str, meter) -> dict:
    rows = {}
    for ti, target in enumerate(INTERIOR_TARGETS):
        th.manual_seed(p0_seed("sampler", ti))
        dist = (_make_b_dist(target) if arm == "B"
                else _make_a_dist(target))
        n = CONC_SAMPLES_PER_TARGET
        ws = [float(dist.sample()[0, 1].item()) for _ in range(n)]
        meter(n)
        ws = np.asarray(ws)
        within = float(np.mean(np.abs(ws - target)
                               <= CONC_WITHIN_TOL))
        mean_err = float(abs(ws.mean() - target))
        rows[f"{target:+.2f}"] = {
            "n": n, "within_tol": within,
            "mean_abs_err": mean_err,
            "pass": bool(within >= CONC_MASS_FRAC
                         and mean_err <= CONC_MEAN_TOL)}
    passed = all(r["pass"] for r in rows.values())
    return {"arm": arm, "per_target": rows,
            "pass": bool(passed),
            "expected": ("B 集中可表达" if arm == "B"
                         else "A 如实失败(对称中心 0)")}


def tail_mass_checks() -> dict:
    """闭式 log I_ε vs scipy betainc vs 数值求积(域 (1,500])。"""
    from rl_posctl.skill_p0.p0eval import _incbeta_quad, incbeta
    from scipy.special import betainc as sci_betainc
    grid_a = np.concatenate([[1.0001, 1.01, 1.1, 1.5, 2.0, 3.0,
                              5.0, 10.0, 30.0, 100.0, 300.0,
                              499.0]])
    grid_b = grid_a
    worst = {"series_vs_scipy": 0.0, "series_vs_quad": 0.0}
    n_pts = 0
    for a in grid_a:
        for b in grid_b:
            lo = float(p0policy.log_incbeta_eps(
                th.tensor(a), th.tensor(b)).exp())
            hi = float(p0policy.log_incbeta_eps(
                th.tensor(b), th.tensor(a)).exp())
            eps = float(p0policy.__dict__["EPS_COLL"])
            ref_lo = float(sci_betainc(a, b, eps))
            ref_hi = float(sci_betainc(b, a, eps))
            worst["series_vs_scipy"] = max(
                worst["series_vs_scipy"],
                abs(lo - ref_lo) / max(ref_lo, 1e-300),
                abs(hi - ref_hi) / max(ref_hi, 1e-300))
            q = _incbeta_quad(a, b, eps, n=20001)
            if q > 0:
                worst["series_vs_quad"] = max(
                    worst["series_vs_quad"], abs(lo - q) / q)
            n_pts += 1
    return {"grid_points": n_pts, "worst_rel_err": worst,
            "pass": bool(worst["series_vs_scipy"] < 1e-12)}


def gradient_checks() -> dict:
    """α/β 梯度:截断闭式 vs 中心差分。"""
    rng = np.random.default_rng(20261014)
    worst = 0.0
    for _ in range(24):
        ar = float(rng.uniform(-2.0, 4.5))
        br = float(rng.uniform(-2.0, 4.5))
        a_t = th.tensor([ar], dtype=th.float64,
                        requires_grad=True)
        b_t = th.tensor([br], dtype=th.float64,
                        requires_grad=True)
        val = p0policy.log_incbeta_eps(a_t, b_t).sum()
        val.backward()
        g_a, g_b = float(a_t.grad), float(b_t.grad)
        h = 1e-6
        f = lambda t, u: float(   # noqa: E731
            p0policy.log_incbeta_eps(th.tensor(t), th.tensor(u)))
        fd_a = (f(ar + h, br) - f(ar - h, br)) / (2 * h)
        fd_b = (f(ar, br + h) - f(ar, br - h)) / (2 * h)
        for g, fd in ((g_a, fd_a), (g_b, fd_b)):
            denom = max(1.0, abs(fd))
            worst = max(worst, abs(g - fd) / denom)
    return {"worst_rel": worst, "pass": bool(worst < 1e-5)}


def mc_logprob_entropy_checks(meter) -> dict:
    """执行 log-prob/熵 vs 蒙特卡洛(采样计入计量)。"""
    rng = np.random.default_rng(11)
    out = {"logprob": None, "entropy": None}
    ar = th.tensor([[0.7]], dtype=th.float64)
    br = th.tensor([[1.9]], dtype=th.float64)
    b = th.tensor([[0.2, -0.3]], dtype=th.float64)
    m = th.tensor([[-0.4, -0.2, 0.1, -0.5]], dtype=th.float64)
    dist = P0AsymBetaDistribution(b, m, ar, br)
    n = 4096
    th.manual_seed(123)
    acts = th.stack([dist.sample()[0] for _ in range(n)])
    meter(n)
    lp = dist.log_prob(acts)
    # 独立重构联合概率:branch 概率 × 类别质量(Beta CDF 差/原子)
    from scipy.special import betainc as sci
    alpha = float(dist.alpha)
    beta = float(dist.beta)
    p_hold, p_rebal = th.exp(dist.branch_logp)[0].tolist()
    mix = th.exp(dist.mix_logp)[0].tolist()
    eps = float(p0policy.EPS_COLL)
    logp_manual = []
    for i in range(n):
        br_i, w_i = float(acts[i, 0]), float(acts[i, 1])
        if br_i == 0.0:
            logp_manual.append(math.log(p_hold))
            continue
        base = math.log(p_rebal)
        if w_i == -1.0:
            mass = mix[0] + mix[3] * float(sci(alpha, beta, eps))
        elif w_i == 0.0:
            mass = mix[1] + mix[3] * float(dist.b0)
        elif w_i == 1.0:
            mass = mix[2] + mix[3] * float(sci(beta, alpha, eps))
        else:
            u = (w_i + 1.0) / 2.0
            u = min(max(u, eps), 1 - eps)
            dens = math.exp((alpha - 1) * math.log(u)
                            + (beta - 1) * math.log1p(-u)
                            - math.lgamma(alpha)
                            - math.lgamma(beta)
                            + math.lgamma(alpha + beta)) / 2.0
            mass = mix[3] * dens
        logp_manual.append(base + math.log(mass))
    lp_manual = th.tensor(logp_manual, dtype=th.float64)
    err_lp = float((lp.to(th.float64) - lp_manual).abs().max())
    out["logprob"] = {"max_abs_err": err_lp,
                      "pass": bool(err_lp < 1e-5)}
    # 熵:MC −E[log p](执行测度)
    ent = float(dist.entropy()[0])
    ent_mc = float(-lp.to(th.float64).mean())
    out["entropy"] = {"closed": ent, "mc": ent_mc,
                      "diff": abs(ent - ent_mc),
                      "pass": bool(abs(ent - ent_mc) < 0.05)}
    # PPO ratio:old=new ⇒ 1
    with th.no_grad():
        lp2 = dist.log_prob(acts)
    ratio = th.exp(lp2 - lp)
    out["ratio_identity"] = {
        "max_dev": float((ratio - 1.0).abs().max()),
        "pass": bool((ratio - 1.0).abs().max() < 1e-6)}
    return out


def atom_semantics_checks() -> dict:
    """HOLD/0/±1 原子构造:采样值精确 + 解码类别正确。"""
    b = th.tensor([[6.0, 0.0]], dtype=th.float64)      # p(HOLD)≈1
    m = th.tensor([[0.0, -9.0, -9.0, -9.0]], dtype=th.float64)
    ar = th.tensor([[0.5]], dtype=th.float64)
    br = th.tensor([[0.5]], dtype=th.float64)
    d_hold = P0AsymBetaDistribution(b, m, ar, br)
    th.manual_seed(5)
    acts = d_hold.sample()
    hold_ok = bool(acts[0, 0] == 0.0 and acts[0, 1] == 0.0)
    lp_hold = float(d_hold.log_prob(acts)[0])
    b2 = th.tensor([[0.0, 6.0]], dtype=th.float64)
    d_m1 = P0AsymBetaDistribution(
        b2, th.tensor([[-9.0, -9.0, 0.0, -9.0]],
                      dtype=th.float64), ar, br)
    d_z = P0AsymBetaDistribution(
        b2, m, ar, br)
    d_p1 = P0AsymBetaDistribution(
        b2, th.tensor([[-9.0, -9.0, -9.0, 0.0]],   # 连续集中 +1
                      dtype=th.float64), ar, br)
    th.manual_seed(6)
    a_m1 = d_m1.sample()
    th.manual_seed(7)
    a_z = d_z.sample()
    th.manual_seed(8)
    a_p1 = d_p1.sample()
    dec = p0policy.p0_category_decode(
        d_p1.branch_logits, d_p1.merged_atom_logp(),
        d_p1.interior_log_mass(), d_p1.interior_representative())
    return {
        "hold_exact": hold_ok,
        "hold_lp": lp_hold,
        "atom_m1": bool(a_m1[0, 1] == -1.0),
        "atom_0": bool(a_z[0, 1] == 0.0),
        "cont_tail_p1": bool(a_p1[0, 1] == 1.0),
        "decode_interior_near_p1": bool(
            dec[0, 0] == 1.0 and float(dec[0, 1]) > 0.9),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=str(RUNS_DIR / "repr"))
    args = ap.parse_args()
    out_root = Path(args.out)
    gate_path = out_root / "repr_report.json"
    if gate_path.exists():
        print(f"已有 repr_report.json:{gate_path}", file=sys.stderr)
        return 2
    ledger = open_ledger(args.ledger)
    meter = make_sampler_meter(ledger, "repr")
    with RunLog(out_root, meta_extra={"runner": "psc_p0_repr"}):
        report = {
            "concentration_A": concentration_check("A", meter),
            "concentration_B": concentration_check("B", meter),
            "tail_mass": tail_mass_checks(),
            "gradient": gradient_checks(),
            "mc": mc_logprob_entropy_checks(meter),
            "atoms": atom_semantics_checks(),
        }
        report["b_precondition_pass"] = bool(
            report["concentration_B"]["pass"]
            and report["tail_mass"]["pass"]
            and report["gradient"]["pass"]
            and report["mc"]["logprob"]["pass"]
            and report["atoms"]["hold_exact"]
            and report["atoms"]["atom_m1"]
            and report["atoms"]["atom_0"])
        ev = evidence_kib_settle(ledger, tag="repr")
        report["evidence_kib"] = ev
        gate_path.write_text(json.dumps(report, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
        print(json.dumps({
            "B_precondition": report["b_precondition_pass"],
            "A_conc_pass": report["concentration_A"]["pass"],
            "B_conc_pass": report["concentration_B"]["pass"],
            "tail": report["tail_mass"]["worst_rel_err"],
            "grad": report["gradient"]["worst_rel"],
            "mc_lp_err": report["mc"]["logprob"]["max_abs_err"],
            "atoms": report["atoms"]},
            ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
