#!/usr/bin/env python
"""阶段二 §14/§18/§20/§21:人工价格序列 + 固定动作序列审计。

直接实例化固定版本真实环境类 AuditBase3RLModel.MyRLEnv
(= Base3ActionRLEnv + 上游官方 3ac 奖励函数),不重新实现任何环境逻辑。

输出:
- artifacts/freqai_rl_platform_audit/synthetic_<seq>_trace.csv (fee=0.001 规范名)
- artifacts/freqai_rl_platform_audit/synthetic_<seq>_fee<fee>_trace.csv (全量)
- artifacts/freqai_rl_platform_audit/synthetic_summary.md
"""
import os
import sys

import numpy as np
import pandas as pd

PROJ = os.path.expanduser("~/projects/crypto_rl")
ART = f"{PROJ}/artifacts/freqai_rl_platform_audit"
sys.path.insert(0, f"{PROJ}/user_data/freqaimodels")

from AuditBase3RLModel import AuditBase3RLModel  # noqa: E402

N = 30
BASE_TS = pd.Timestamp("2026-06-01T00:00:00Z")


def make_prices(seq_name: str) -> pd.DataFrame:
    if seq_name == "constant":
        vals = [100.0] * N
    elif seq_name == "rising":
        vals = [100.0 * (1.1 ** k) for k in range(N)]
    elif seq_name == "falling":
        vals = [100.0 * (0.9 ** k) for k in range(N)]
    elif seq_name == "zigzag":
        base = [100.0, 110.0, 90.0, 120.0, 80.0, 130.0]
        vals = [base[i % len(base)] for i in range(N)]
    else:
        raise ValueError(seq_name)
    df = pd.DataFrame({
        "date": pd.date_range(BASE_TS, periods=N, freq="1h", tz="UTC"),
        "open": vals, "high": vals, "low": vals, "close": vals, "volume": [1.0] * N,
    })
    return df


def make_env(prices: pd.DataFrame, fee: float, randomize_start: bool = False):
    cfg = {
        "freqai": {
            "rl_config": {
                "max_trade_duration_candles": 300,
                "max_training_drawdown_pct": 0.5,
                "model_reward_parameters": {"rr": 1, "profit_aim": 0.02, "win_reward_factor": 2},
                "randomize_starting_position": randomize_start,
            }
        },
        "stake_amount": 100,   # 非 unlimited → 不复利
        "fee": fee,
        "timeframe": "1h",
    }
    feats = pd.DataFrame({"feat_close": prices["close"].astype(float).values})
    env = AuditBase3RLModel.MyRLEnv(
        df=feats,
        prices=prices[["open", "high", "low", "close"]].reset_index(drop=True),
        reward_kwargs={"rr": 1, "profit_aim": 0.02, "win_reward_factor": 2},
        window_size=1,
        starting_point=True,
        id="audit-env",
        seed=42,
        config=cfg,
        live=False,
        fee=fee,
        can_short=False,
        pair="SYN/USDT",
        df_raw=feats,
    )
    return env


ACTION_NAMES = {0: "Hold", 1: "Enter(Buy)", 2: "Exit(Sell)"}
POSITION_NAMES = {0.5: "Neutral", 1.0: "Long", 0.0: "Short"}


def run_script(seq_name: str, fee: float, actions: list[int], label: str) -> pd.DataFrame:
    prices = make_prices(seq_name)
    env = make_env(prices, fee)
    obs, _ = env.reset(seed=42)
    rows = []
    step_no = 0
    done = False
    for act in actions:
        if done:
            break
        tick_before = env._current_tick
        pos_before = env._position
        valid = env._is_valid(act)
        last_trade_tick_before = env._last_trade_tick
        total_profit_before = env._total_profit
        unreal_before = env.get_unrealized_profit()

        obs, reward, term, trunc, info = env.step(act)

        entry_price = (
            float(env.prices["open"].iloc[last_trade_tick_before])
            if last_trade_tick_before is not None else np.nan
        )
        price_used = float(env.prices["open"].iloc[env._current_tick])
        rows.append({
            "step": step_no,
            "tick_before": tick_before,
            "tick_after": env._current_tick,
            "timestamp": str(prices["date"].iloc[env._current_tick]) if
                env._current_tick < len(prices) else "N/A",
            "action_int": act,
            "action_name": ACTION_NAMES[act],
            "action_valid": valid,
            "position_before": POSITION_NAMES.get(pos_before.value, pos_before.value),
            "position_after": POSITION_NAMES.get(env._position.value, env._position.value),
            "price_used_open": price_used,
            "entry_price_open": entry_price,
            "unrealized_pnl": info["current_profit_pct"],
            "total_profit_realized": env._total_profit,
            "total_profit_delta": env._total_profit - total_profit_before,
            "unrealized_pnl_before_step": unreal_before,
            "reward": reward,
            "total_reward": env.total_reward,
            "terminated": term,
            "truncated": trunc,
        })
        done = term or trunc
        step_no += 1
    df = pd.DataFrame(rows)
    df.attrs["label"] = label
    return df


def fmt_hand_calc():
    """§21 手算对照。"""
    fee = 0.001
    lines = []
    lines.append("## 手算对照(与 CSV 逐项比较)\n")

    # 1) 上涨 long:B 序列 100 → 110,fee=0.001,买入 open[t_e],平仓 open[t_x]
    #    entry_adj = 100*(1+0.001) = 100.1
    #    exit_adj = 110/(1+0.001) = 109.89010989...
    #    pnl = (exit_adj - entry_adj)/entry_adj = 9.7803...%
    entry_adj = 100.0 * (1 + fee)
    exit_adj = 110.0 / (1 + fee)
    pnl = (exit_adj - entry_adj) / entry_adj
    lines.append(f"1. 上涨 long 100→110, fee={fee}: "
                 f"entry_adj={entry_adj:.6f}, exit_adj={exit_adj:.6f}, "
                 f"预期 pnl={pnl:.8f} ({pct(pnl)})")
    # 无费对照
    pnl0 = (110.0 - 100.0) / 100.0
    lines.append(f"   无费 pnl={pnl0:.8f};费差={pnl0 - pnl:.8f}")

    # 2) 下跌 long 100 → 90
    entry_adj = 100.0 * (1 + fee)
    exit_adj = 90.0 / (1 + fee)
    pnl = (exit_adj - entry_adj) / entry_adj
    pnl0 = (90.0 - 100.0) / 100.0
    lines.append(f"2. 下跌 long 100→90, fee={fee}: 预期 pnl={pnl:.8f};无费={pnl0:.8f};费差={pnl0 - pnl:.8f}")

    # 3) 恒定价格开平 100 → 100
    entry_adj = 100.0 * (1 + fee)
    exit_adj = 100.0 / (1 + fee)
    pnl = (exit_adj - entry_adj) / entry_adj
    lines.append(f"3. 恒定价格开平 100→100, fee={fee}: 预期 pnl={pnl:.10f} "
                 f"(≈ -2*fee = {-2 * fee})")
    pnl_no_fee = 0.0
    lines.append(f"   无费 pnl={pnl_no_fee:.10f};费差={pnl_no_fee - pnl:.10f}")
    return lines


def pct(x):
    return f"{x * 100:.5f}%"


SCRIPTS = {
    "t1_all_hold": [0] * 29,
    "t2_enter_hold": [1] + [0] * 28,
    "t3_enter_exit": [1, 0, 2] + [0] * 26,
    "t4_repeat_enter": [1] * 29,
    "t5_repeat_exit_flat": [2] * 29,
    "t6_alt_enter_exit": ([1, 2] * 15)[:29],
    "t7_hold_to_end": [1] + [0] * 40,   # 超过数据长度,观察 episode 终止与未平仓
}


def main():
    os.makedirs(ART, exist_ok=True)
    all_lines = ["# 人工价格序列 × 固定动作序列 审计输出",
                 "", "环境: AuditBase3RLModel.MyRLEnv (真实固定版本类)",
                 "价格: open=high=low=close=series 值, volume=1, 30 根 1h",
                 f"window_size=1, seed=42, stake_amount=100(不复利), can_short=False",
                 ""]

    for seq in ("constant", "rising", "falling", "zigzag"):
        for fee in (0.0, 0.001):
            frames = []
            for label, acts in SCRIPTS.items():
                df = run_script(seq, fee, acts, label)
                df.insert(0, "script", label)
                df.insert(0, "fee", fee)
                frames.append(df)
                all_lines.append(
                    f"### {seq} fee={fee} {label}: "
                    f"final_total_profit={df['total_profit_realized'].iloc[-1]:.8f}, "
                    f"final_total_reward={df['total_reward'].iloc[-1]:.3f}, "
                    f"terminated={bool(df['terminated'].iloc[-1])}, "
                    f"last_pos={df['position_after'].iloc[-1]}, "
                    f"unreal_pnl_end={df['unrealized_pnl'].iloc[-1]:.8f}"
                )
            full = pd.concat(frames, ignore_index=True)
            path = f"{ART}/synthetic_{seq}_fee{fee}_trace.csv"
            full.to_csv(path, index=False)
            if fee == 0.001:
                # 规范名(任务书要求)
                full.to_csv(f"{ART}/synthetic_{seq}_trace.csv", index=False)
                print(f"written {ART}/synthetic_{seq}_trace.csv rows={len(full)}")

    # episode/reset 审计:reset 后状态快照
    env = make_env(make_prices("zigzag"), 0.001)
    env.reset(seed=42)
    env.step(1)
    env.step(0)
    snap_pre = {
        "_current_tick": env._current_tick, "_position": env._position.name,
        "_last_trade_tick": env._last_trade_tick,
        "_total_profit": env._total_profit, "total_reward": env.total_reward,
        "trade_history_len": len(env.trade_history),
    }
    env.reset(seed=42)
    snap_post = {
        "_current_tick": env._current_tick, "_position": env._position.name,
        "_last_trade_tick": env._last_trade_tick,
        "_total_profit": env._total_profit, "total_reward": env.total_reward,
        "trade_history_len": len(env.trade_history),
        "_start_tick": env._start_tick, "_end_tick": env._end_tick,
    }
    all_lines.append("\n## reset 语义快照\n")
    all_lines.append(f"reset 前(2 步后): {snap_pre}")
    all_lines.append(f"reset 后: {snap_post}")

    # 随机起点观察
    env_r = make_env(make_prices("zigzag"), 0.001, randomize_start=True)
    starts = []
    for s in (1, 2, 3):
        env_r.reset(seed=s)
        starts.append(env_r._start_tick)
    all_lines.append(f"\n## randomize_starting_position=True 时 _start_tick(seed 1/2/3): {starts}")

    all_lines.append("\n" + "\n".join(fmt_hand_calc()))

    with open(f"{ART}/synthetic_summary.md", "w") as f:
        f.write("\n".join(all_lines) + "\n")
    print("\n".join(all_lines[:14]))
    print("...")


if __name__ == "__main__":
    main()
