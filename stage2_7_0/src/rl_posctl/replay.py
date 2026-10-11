# -*- coding: utf-8 -*-
"""动作轨迹录制/回放(RouteC_PositionControl W1)。

无需训练即可复算同一输入与动作轨迹的净值,支撑独立审查:
- record(env):跑一遍动作序列,导出可序列化轨迹(含逐步账本原件);
- replay(config, actions):用同一 prices/features/费用参数与动作
  序列,从零重建环境逐步重放,逐步断言与录制值一致(数量/费用/
  净值/奖励)。回放确定性 = 环境确定性(无 run 级熵;动作序列为
  外部给定)。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

import numpy as np
import pandas as pd

from rl_posctl.env import HybridPositionEnv
from rl_posctl.versions import POSCTL_REPLAY_SPEC_VERSION


def env_config_of(env: HybridPositionEnv) -> dict[str, Any]:
    """环境可序列化配置(重建等价环境所需全部参数)。"""
    return {
        "fee": env.fee,
        "slippage_bps": env.slippage_bps,
        "price_tick": env.price_tick,
        "initial_cash": env.initial_cash,
        "reward_scale": env.reward_scale,
        "window_size": env.window_size,
        "funding_schedule": dict(env.funding_schedule),
        "maintenance_margin": env.maintenance_margin,
    }


def record_episode(env: HybridPositionEnv,
                   actions: Sequence) -> dict[str, Any]:
    """录制:reset + 逐步执行动作序列,返回完整轨迹。"""
    obs, _ = env.reset()
    trajectory: list[dict[str, Any]] = []
    for a in actions:
        o, r, term, trunc, info = env.step(a)
        trajectory.append({
            "action": [float(a[0]), float(a[1])],
            "qty": info["qty"], "cash": info["cash"],
            "avg_entry": info["avg_entry"],
            "equity_start": info["equity_start"],
            "equity_end": info["equity_end"],
            "fee": info["fee"], "reward_raw": info["reward_raw"],
            "fill_kind": info["fill_kind"],
            "exec_price": info["exec_price"],
            "achieved_ratio": info["achieved_ratio"],
            "funding_payment": info["funding_payment"],
            "terminated": info["terminated"],
            "reward_valid": info["reward_valid"],
        })
        if term or trunc:
            break
    return {
        "format": POSCTL_REPLAY_SPEC_VERSION,
        "config": env_config_of(env),
        "actions": [[float(a[0]), float(a[1])] for a in actions],
        "steps": trajectory,
        "episode_reward_raw": env.episode_reward_raw,
        "economic_failure": env.economic_failure,
    }


def replay_episode(prices: pd.DataFrame, features,
                   config: dict[str, Any],
                   actions: Sequence[Sequence[float]],
                   expect: dict[str, Any] | None = None,
                   atol: float = 1e-9) -> dict[str, Any]:
    """回放:同一输入+动作序列重建重算;可选对拍录制原件。

    expect 非空时逐步断言 qty/cash/equity/fee/reward 与录制一致
    (容限 atol 运行前固定),任一不符抛 AssertionError。
    """
    env = HybridPositionEnv(
        features=features, prices=prices, **config)
    env.reset()
    outs = []
    for a in actions:
        o, r, term, trunc, info = env.step(a)
        outs.append(info)
        if term or trunc:
            break
    if expect is not None:
        steps = expect["steps"]
        assert len(steps) == len(outs), (
            f"回放步数 {len(outs)} != 录制 {len(steps)}")
        for i, (rec, got) in enumerate(zip(steps, outs)):
            for key in ("qty", "cash", "avg_entry", "equity_start",
                        "equity_end", "fee", "exec_price"):
                rv, gv = rec[key], got[key]
                assert abs(rv - gv) <= atol * max(1.0, abs(rv)), (
                    f"step{i} {key}: replay={gv!r} record={rv!r}")
            rrv = rec["reward_raw"]
            grv = got["reward_raw"]
            if rrv is None or grv is None:
                assert (rrv is None) == (grv is None), f"step{i} reward"
            else:
                assert abs(rrv - grv) <= atol * max(1.0, abs(rrv)), (
                    f"step{i} reward_raw: {grv!r} vs {rrv!r}")
        assert ((expect["episode_reward_raw"] is None)
                == (env.episode_reward_raw is None)), "episode reward"
        if env.episode_reward_raw is not None:
            assert abs(expect["episode_reward_raw"]
                       - env.episode_reward_raw) <= atol, (
                "episode_reward_raw 不一致")
    return {
        "episode_reward_raw": env.episode_reward_raw,
        "final_cash": env.ledger.cash,
        "steps": outs,
        "economic_failure": env.economic_failure,
    }


def save_trajectory(traj: dict[str, Any], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(traj, ensure_ascii=False, indent=1, default=float),
        encoding="utf-8")


def load_trajectory(path: Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))
