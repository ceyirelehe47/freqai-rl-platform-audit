# -*- coding: utf-8 -*-
"""eval_pilot v3 — 真评价(冷载隔离/RNG 恢复/纯 ledger 基线重放)。

- 每 checkpoint 128 episode(64 H32 ±各 32+64 tail ±各 32),
  **实际 counter 计步**(≤2112 硬核);1024 随机读出+确定性;
- reset 返回 (obs, info) 先拆再喂;
- 基线=解析 all-HOLD(flat 净 log=0)+**已保存路径的纯 ledger
  重放**(const ±1/signal-full 用 policy episode 记录的 r 序列
  在新 TwoSidedLinearLedger 上重放;零额外环境步);
- 经济失败序列化 {valid:false, net_log:null,
  raw_marker:"-inf", reason};原始 -inf 不改 0;JSON 安全;
- PPO.load/predict 全程 try/finally 恢复 torch/NumPy/Python
  全局 RNG(实快照恢复,非声明);
- 固定响应摘要:每侧(rem32/rem1×s±)方向正确/反向/有效 flat
  (执行语义 HOLD+REBAL0 合并)占比+均值;tail 零交易率。
"""
import math
import os
import random
import sys

import numpy as np
import torch as th

_HERE = os.path.dirname(
    os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import teach_env as TE  # noqa
from rl_posctl.ledger import (  # noqa: E402
    TwoSidedLinearLedger)

READOUT_STATES = [
    (32, 1), (32, -1), (1, 1), (1, -1)]
N_READOUT = 256
H32_N = 32
TAIL_N = 32
EVAL_CAP = 2112
FLAT_TOL = 1e-9


def _action(policy, obs,
            deterministic):
    o = th.as_tensor(
        obs, dtype=th.float32
    ).unsqueeze(0)
    with th.no_grad():
        a = policy.predict(
            o,
            deterministic=(
                deterministic))[0]
    return np.asarray(a).reshape(-1)


def _run_episodes(policy, env, eps,
                  seed_kw):
    """跑 eps(结构统一 [(kw, max_steps)]);实际计数。
    返回 (results, steps_used, r_paths)。"""
    results = []
    steps = 0
    r_paths = []
    for kw, ms in eps:
        obs, _info = env.reset(**kw)
        total = 0.0
        failed = None
        rs = []
        trace = []
        for _ in range(ms):
            a = _action(policy, obs,
                        False)
            # 每步动作前可见 (s,c,q,rem) 记录
            trace.append({
                "s": float(env.s),
                "c": float(env.c),
                "q": float(env.q),
                "rem": float(env.rem)})
            obs, r, term, _tr, info = \
                env.step(a)
            rs.append(info.get("r"))
            if trace:
                trace[-1]["r"] = \
                    info.get("r")
            steps += 1
            if steps > EVAL_CAP:
                raise RuntimeError(
                    "eval step cap")
            ef = info.get(
                "economic_failure")
            if ef is not None or (
                    not info.get(
                        "reward_valid",
                        True)):
                failed = ef or {
                    "phase": "unknown",
                    "reason":
                        "reward_valid"
                        " false"}
                total = -math.inf
                break
            total += r
            if term:
                break
        results.append({
            "kw": kw,
            "valid": failed is None,
            "net_log": (
                None if failed
                else total),
            "raw_marker": (
                "-inf"
                if failed else None),
            "failed_reason": (
                failed or None),
            "trace": trace})
        r_paths.append(
            {"kw": kw, "rs": rs,
             "trace": trace})
    return results, steps, r_paths


def _ledger_replay(kw, rs, action_fn,
                   trace=None):
    """纯 ledger 重放已保存 r 路径+逐步可见状态(零环境步)。
    同 env 风险顺序:开盘风险(+平后复查)→动作→扣费复查→
    close 结算(非末步同 bar 收盘风险强平/末步清算)。
    action_fn(state) → w(None=HOLD);state 取 trace 逐步
    (s,c,q,rem),signal_full 用 sign(s*c*q) 逐步信号。
    返回 {valid,net_log,raw_marker}(-inf 统一标记,
    JSON 安全)。"""
    led = TwoSidedLinearLedger()
    price = 1.0
    rem = kw["remaining"]
    total = 0.0

    def _fail():
        return {"valid": False,
                "net_log": None,
                "raw_marker": "-inf"}

    for i, r in enumerate(rs):
        if r is None:
            break
        st = (trace[i]
              if trace and i < len(
                  trace) else {
                  "s": kw["s"],
                  "c": 1, "q": 1.0})
        open_p = price
        eq0 = led.equity(open_p)
        if eq0 <= 0.0:
            return _fail()
        if (led.qty != 0.0
                and eq0 < TE.MAINT
                * abs(led.qty)
                * open_p):
            led.risk_flatten(open_p)
            if led.equity(
                    open_p) <= 0.0:
                return _fail()
        w = action_fn(st)
        if w is None:
            led.hold(open_p)
        else:
            led.apply_target_ratio(
                w, open_p)
        if led.equity(open_p) <= 0.0:
            return _fail()
        close = open_p * (1.0 + r)
        if rem <= 1:
            led.liquidate(close)
            eqf = led.equity(close)
            if eqf <= 0.0:
                return _fail()
            return {
                "valid": True,
                "net_log": total
                + math.log(
                    eqf / eq0),
                "raw_marker": None}
        eqc = led.equity(close)
        if eqc <= 0.0:
            return _fail()
        if (led.qty != 0.0
                and eqc < TE.MAINT
                * abs(led.qty)
                * close):
            led.risk_flatten(close)
            if led.equity(
                    close) <= 0.0:
                return _fail()
        total += math.log(
            led.equity(close) / eq0)
        price = close
        rem -= 1
    return {"valid": True,
            "net_log": total,
            "raw_marker": None}


def _summary(results, readouts):
    """固定响应摘要(每侧+总体)。"""
    out = {}
    sides = {
        "h32_pos": lambda d: (
            d["kw"]["remaining"] == 32
            and d["kw"]["s"] > 0),
        "h32_neg": lambda d: (
            d["kw"]["remaining"] == 32
            and d["kw"]["s"] < 0),
        "tail_pos": lambda d: (
            d["kw"]["remaining"] == 1
            and d["kw"]["s"] > 0),
        "tail_neg": lambda d: (
            d["kw"]["remaining"] == 1
            and d["kw"]["s"] < 0)}
    for name, pred in sides.items():
        sel = [d for d in results
               if pred(d)]
        valid = [d for d in sel
                 if d["valid"]]
        nets = [d["net_log"]
                for d in valid]
        out[name] = {
            "n": len(sel),
            "n_valid": len(valid),
            "mean_net_log": (
                float(np.mean(nets))
                if nets else None),
            "min_net_log": (
                float(np.min(nets))
                if nets else None)}
    # 读出方向/flat 摘要(执行语义合并)
    for ro in readouts:
        key = "ro_rem%d_s%+d" % (
            ro["remaining"], ro["s"])
        acts = ro["stochastic"]
        br = np.array(
            [a[0] for a in acts])
        w = np.array(
            [a[1] for a in acts])
        reb = br >= 0.5
        # 有效 flat=HOLD 或 REBAL 精确 w==0(不与近零混算)
        flat_exact = (~reb) | (
            reb & (w == 0.0))
        near_zero = reb & (
            (w != 0.0)
            & (np.abs(w) <= FLAT_TOL))
        sgn = np.sign(ro["s"])
        correct = reb & (
            np.sign(w) == sgn) & (
            np.abs(w) > FLAT_TOL)
        reverse = reb & (
            np.sign(w) == -sgn) & (
            np.abs(w) > FLAT_TOL)
        out[key] = {
            "n": len(acts),
            "dir_correct_frac": float(
                correct.mean()),
            "dir_reverse_frac": float(
                reverse.mean()),
            "effective_flat_frac":
                float(flat_exact
                      .mean()),
            "near_zero_w_frac": float(
                near_zero.mean())}
        out[key][
            "tail_zero_trade"] = (
            out[key][
                "effective_flat_frac"]
            if ro["remaining"] == 1
            else None)
    return out


def evaluate_checkpoint(
        ckpt_path, spec, tag, book,
        out_dir, env_factory=None,
        _loader=None):
    seed = spec["seeds"][
        "eval_init"
        if tag == "initial"
        else "eval_final"]
    # RNG 全局隔离(实快照/finally 恢复)
    ts = th.get_rng_state()
    ns = np.random.get_state()
    ps = random.getstate()
    try:
        from stable_baselines3 \
            import PPO
        load = _loader or PPO.load
        cold = load(ckpt_path,
                    device="cpu")
        factory = (env_factory
                   or
                   TE.UnifiedPilotEnv)
        env = factory(
            random.Random(seed))
        eps = (
            [({"remaining": 32,
               "s": 1}, 32)] * H32_N
            + [({"remaining": 32,
                 "s": -1}, 32)]
            * H32_N
            + [({"remaining": 1,
                 "s": 1}, 1)] * TAIL_N
            + [({"remaining": 1,
                 "s": -1}, 1)]
            * TAIL_N)
        results, steps, r_paths = \
            _run_episodes(
                cold.policy, env,
                eps, seed)
        readouts = []
        for (rem, s) in READOUT_STATES:
            env2 = factory(
                random.Random(
                    seed + 7))
            obs, _i = env2.reset(
                remaining=rem, s=s)
            stoch = [
                _action(cold.policy,
                        obs,
                        False).tolist()
                for _ in range(
                    N_READOUT)]
            det = _action(
                cold.policy, obs,
                True).tolist()
            readouts.append({
                "remaining": rem,
                "s": s,
                "n": N_READOUT,
                "stochastic": stoch,
                "deterministic":
                    det})
        # 基线:解析 HOLD+纯 ledger 重放
        baselines = {
            "all_HOLD_analytic":
                0.0}
        def _act_const(w):
            return lambda st: w

        def _act_signal(st):
            return float(np.sign(
                st["s"] * st["c"]
                * st["q"]))
        for name, fn in (
                ("const_long",
                 _act_const(1.0)),
                ("const_short",
                 _act_const(-1.0)),
                ("signal_full",
                 _act_signal)):
            vals = []
            for p in r_paths:
                vals.append({
                    "kw": p["kw"],
                    **_ledger_replay(
                        p["kw"],
                        p["rs"],
                        fn,
                        trace=p.get(
                            "trace"))})
            baselines[name] = vals
        out = {
            "tag": tag,
            "seed": seed,
            "episodes": results,
            "steps_used": steps,
            "readouts": readouts,
            "baselines":
                baselines,
            "summary": _summary(
                results, readouts)}
        why, _c, _p = (
            book.checkpoint(
                "eval_" + tag))
        if why:
            raise RuntimeError(
                "budget(eval_%s):"
                " %s" % (tag, why))
        return out
    finally:
        th.set_rng_state(ts)
        np.random.set_state(ns)
        random.setstate(ps)
