# -*- coding: utf-8 -*-
"""PSC_P0_v1 题目有效性门(prequal;不使用 PPO/BC 结果调题)。

- 参考 = 本轮同信息有限期数值网格求解器(41 点动作网格,三级细化
  (81,16,10)→(161,32,20)→(321,64,40),主判定末级;H=32/64/96)。
- 题目门:H=64 参考期望净对数初值 >0.02;经验细化差 < 相对最强固定
  基线期望优势的 10%;prequal 配对回放参考对 flat/±1/±0.5 净优势
  为正且两侧方向正确。无法证明 → NOT_ESTABLISHED。
- 反事实观察探针:修改未来收益/课程元数据不改当下观察(纯构造,
  零经济步、零生成)。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rl_posctl.curriculum import (
    error_report, initial_value, reference_policy, spec_fingerprint,
    validate_refinements)
from rl_posctl.skill_p0.p0eval import (
    constant_action_fn, eval_on_bank, hold_action_fn,
    reference_action_fn, sign_action_fn)
from rl_posctl.skill_p0.p0spec import (
    BASELINE_NAMES, C1_HORIZON, REFINEMENTS, TASK_ERR_FRAC,
    TASK_VALUE_GATE, c1_spec)


def baseline_fns() -> dict:
    return {
        "flat": hold_action_fn(),
        "const+1": constant_action_fn(1.0),
        "const-1": constant_action_fn(-1.0),
        "const+0.5": constant_action_fn(0.5),
        "const-0.5": constant_action_fn(-0.5),
    }


def solve_reference(horizon: int) -> dict:
    """固定 C1 规格三级细化求解(缓存复用;求解单列计量/墙钟)。"""
    import time
    spec = c1_spec("prequal", 0, horizon=horizon)
    out = {"horizon": horizon,
           "spec_fingerprint": spec_fingerprint(spec)}
    values = []
    for lvl in REFINEMENTS:
        t0 = time.time()
        v = initial_value(spec, n_dense=lvl[0], n_ext=lvl[1],
                          m_quad=lvl[2])
        values.append(v)
        out[f"value_{lvl[0]}_{lvl[1]}_{lvl[2]}"] = v
        out[f"wall_s_{lvl[0]}_{lvl[1]}_{lvl[2]}"] = round(
            time.time() - t0, 3)
    report = error_report(spec, refinements=REFINEMENTS)
    out["err_bound"] = report["err_bound"]
    out["err_bound_kind"] = report["err_bound_kind"]
    out["refinements"] = [list(x) for x in REFINEMENTS]
    out["values"] = values
    return out


def task_validity_gate(prequal_items, *, ledger=None) -> dict:
    """题目门全链(参考/基线回放按 eval_steps 计量)。"""
    ref_solutions = {h: solve_reference(h) for h in (32, 64, 96)}
    v64 = ref_solutions[64]["values"][-1]
    result = {"reference": ref_solutions,
              "value_gate": bool(v64 > TASK_VALUE_GATE),
              "value64": v64}

    # 基线与参考在 prequal 上重放(每 episode 真实账本)
    spec64 = c1_spec("prequal", 0, horizon=C1_HORIZON)
    ref = reference_policy(spec64)
    replay = {}
    for name, fn in baseline_fns().items():
        replay[f"baseline:{name}"] = eval_on_bank(
            prequal_items, fn, ledger=ledger, tag=f"prequal:{name}")
    replay["reference"] = eval_on_bank(
        prequal_items, reference_action_fn(ref, spec64),
        ledger=ledger, tag="prequal:reference")
    replay["sign_rule"] = eval_on_bank(
        prequal_items, sign_action_fn(), ledger=ledger,
        tag="prequal:sign")

    def _mean(rows):
        vals = [r["net_log_return"] for r in rows
                if r["net_log_return"] is not None]
        if len(vals) != len(rows):
            return None
        return float(np.mean(vals))

    means = {k: _mean(v) for k, v in replay.items()}
    result["replay_means"] = means
    base_means = [means[f"baseline:{n}"] for n in BASELINE_NAMES]
    if any(v is None for v in base_means) or means["reference"] is None:
        result["gate_status"] = "NOT_ESTABLISHED"
        result["reason"] = "基线/参考回放出现经济失败"
        return result
    best_base = max(base_means)
    advantage = means["reference"] - best_base
    result["best_baseline_mean"] = best_base
    result["reference_advantage_vs_best"] = advantage
    result["err_frac_of_advantage"] = (
        ref_solutions[64]["err_bound"] / advantage
        if advantage > 0 else None)
    result["refinement_gate"] = bool(
        advantage > 0 and
        ref_solutions[64]["err_bound"]
        < TASK_ERR_FRAC * advantage)
    result["advantage_gate"] = bool(advantage > 0)

    # 配对优势:参考 − 基线,逐 episode 差的均值(两侧方向并列)
    paired = {}
    for n in BASELINE_NAMES:
        diffs = [(replay["reference"][i]["net_log_return"]
                  - replay[f"baseline:{n}"][i]["net_log_return"])
                 for i in range(len(prequal_items))]
        paired[n] = float(np.mean(diffs))
    result["paired_mean_advantage"] = paired
    result["paired_gate"] = bool(
        all(v > 0 for v in paired.values()))

    # 方向响应:|mean s|>0.2 的 episode,参考平均带符号敞口与 s 同号
    rows = replay["reference"]
    n_ok = 0
    n_tot = 0
    for i, item in enumerate(prequal_items):
        s_mean = float(np.mean(
            item[1]["s"].to_numpy()[:C1_HORIZON]))
        if abs(s_mean) <= 0.2:
            continue
        n_tot += 1
        exp = rows[i]["summary"].get("mean_signed_exposure")
        if exp is not None and np.sign(exp) == np.sign(s_mean):
            n_ok += 1
    result["direction_response"] = {
        "n": n_tot, "n_ok": n_ok,
        "frac": (n_ok / n_tot) if n_tot else None}
    result["direction_gate"] = bool(
        n_tot > 0 and n_ok / n_tot >= 0.90)

    result["gate_status"] = (
        "ESTABLISHED" if (
            result["value_gate"] and result["refinement_gate"]
            and result["advantage_gate"] and result["paired_gate"]
            and result["direction_gate"]) else "NOT_ESTABLISHED")
    return result


# ---------------------------------------------------------------------------
# 反事实观察探针(零经济步)
# ---------------------------------------------------------------------------
def _mk_env(features, prices):
    from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv
    from rl_posctl.skill_p0.p0spec import (
        C1_FEE, FUNDING_SCHEDULE, INITIAL_CASH, MAINTENANCE_MARGIN,
        REWARD_SCALE)
    return P0FiniteTimeEnv(
        features=features, prices=prices, fee=C1_FEE, window_size=1,
        funding_schedule=dict(FUNDING_SCHEDULE),
        maintenance_margin=MAINTENANCE_MARGIN,
        initial_cash=INITIAL_CASH, reward_scale=REWARD_SCALE)


def counterfactual_probes(item, t_check: int = 10) -> dict:
    """修改未来收益/元数据不改当下观察(纯构造)。"""
    prices, feats, meta = item
    close = prices["close"].to_numpy(dtype=np.float64)
    n = len(close)
    # (1) 未来收益放大(t_check+5 之后):当下 obs[t_check] 不变
    r = close[1:] / close[:-1] - 1.0
    r2 = r.copy()
    split = min(t_check + 5, n - 1)
    r2[split:] = r2[split:] * 2.0 + 1e-4
    close2 = 100.0 * np.cumprod(np.concatenate([[0.0], r2]) + 1.0)
    open2 = np.empty_like(close2)
    open2[0] = 100.0
    open2[1:] = close2[:-1]
    env_a = _mk_env(feats, prices)
    env_b = _mk_env(feats, pd.DataFrame({"open": open2,
                                         "close": close2}))
    obs_a = env_a._observation(t_check)        # noqa: SLF001 只读
    obs_b = env_b._observation(t_check)        # noqa: SLF001
    future_invariant = bool(np.array_equal(obs_a, obs_b))
    # (2) 课程元数据/配对标签变化:obs 只依赖特征与账户,构造同数据
    #     不同 meta 的两份 bank 项,obs 必须逐位一致
    item_c = (prices, feats, dict(meta, pair_index=999, variant=9,
                                  sha256="x" * 64))
    env_c = _mk_env(item_c[1], item_c[0])
    obs_c = env_c._observation(t_check)        # noqa: SLF001
    meta_invariant = bool(np.array_equal(obs_a, obs_c))
    return {"t_check": t_check, "future_invariant": future_invariant,
            "meta_invariant": meta_invariant,
            "pass": future_invariant and meta_invariant}


def mirror_probe(item, mirror_item) -> dict:
    """镜像端点分布构造验证:r'=−r(重构口径),s'=−s,价格正。"""
    p0, f0, _ = item
    p1, f1, _ = mirror_item
    r0 = p0["close"].to_numpy()[1:] / p0["close"].to_numpy()[:-1] - 1
    r1 = p1["close"].to_numpy()[1:] / p1["close"].to_numpy()[:-1] - 1
    return {
        "r_negated": bool(np.allclose(r1, -r0, rtol=0, atol=1e-12)),
        "s_negated": bool(np.allclose(
            f1["s"].to_numpy(), -f0["s"].to_numpy(), atol=0)),
        "cgq_identical": bool(
            np.allclose(f1["c"], f0["c"])
            and np.allclose(f1["q"], f0["q"])
            and np.allclose(f1["g"], f0["g"])),
        "prices_positive": bool(np.all(
            p1["close"].to_numpy() > 0)),
    }
