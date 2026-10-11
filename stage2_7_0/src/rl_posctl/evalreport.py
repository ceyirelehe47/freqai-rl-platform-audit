# -*- coding: utf-8 -*-
"""评估与指标(RouteC_PositionControl W4 评价面)。

输出(CURRICULUM_AND_EVALUATION §1):净收益/净对数收益、回撤、
回报波动、绝对/有符号敞口分布、换手名义量与实际费用、反手次数、
HOLD 比例;gamma 折扣训练目标与未折扣账本对数分开呈现。
不填未知年化前提的 Sharpe 年化分。
"""

from __future__ import annotations

import math

import numpy as np

from rl_posctl.env import HybridPositionEnv


def run_policy(env: HybridPositionEnv, policy_fn):
    """以可观察状态驱动的策略跑一个 episode(无梯度)。

    policy_fn(feat_row_dict, current_ratio) -> (branch, w)。
    返回逐步 info 列表(账本原件)。
    """
    obs, _ = env.reset()
    infos = []
    while True:
        t = env._current_tick
        row = env._feature_row(t)
        ratio = env.ledger.exposure_ratio(env._close[t]) \
            if env.ledger.equity(env._close[t]) > 0 else 0.0
        act = policy_fn(row, ratio)
        obs, r, term, trunc, info = env.step(act)
        infos.append(info)
        if term or trunc:
            break
    return infos


def summarize(infos: list[dict]) -> dict:
    eq = np.array([i["equity_end"] for i in infos], dtype=float)
    logret = np.array([i["reward_raw"] for i in infos
                       if i["reward_raw"] is not None])
    peak = np.maximum.accumulate(eq)
    dd = float((1.0 - eq / peak).max()) if len(eq) else 0.0
    fees = float(sum(i["fee"] for i in infos))
    flips = int(sum(
        1 for i in infos
        if i["signed_qty"] != 0.0 and i.get("fill_kind") == "rebalance"
        and (i["qty"] * (i["qty"] - i["signed_qty"])) < 0))
    holds = sum(1 for i in infos if i["action_branch"] == 0)
    exposure = [abs(i["exposure_ratio_close"])
                for i in infos if i["exposure_ratio_close"] is not None]
    signed = [i["exposure_ratio_close"]
              for i in infos if i["exposure_ratio_close"] is not None]
    net_log = float(logret.sum()) if len(logret) else math.nan
    vol = float(logret.std(ddof=1)) if len(logret) > 1 else math.nan
    return {
        "final_equity": float(eq[-1]) if len(eq) else math.nan,
        "net_log_return": net_log,
        "net_return": float(eq[-1] / infos[0]["equity_start"] - 1.0)
        if len(eq) else math.nan,
        "max_drawdown": dd,
        "logret_vol_per_step": vol,
        "total_fees": fees,
        "turnover_notional": float(sum(
            abs(i["signed_qty"]) * i["exec_price"] for i in infos)),
        "n_flips": flips,
        "hold_share": holds / max(1, len(infos)),
        "mean_abs_exposure": float(np.mean(exposure)) if exposure else 0.0,
        "mean_signed_exposure": float(np.mean(signed)) if signed else 0.0,
        "n_steps": len(infos),
        "economic_failure": bool(
            any(not i["reward_valid"] for i in infos)),
    }
