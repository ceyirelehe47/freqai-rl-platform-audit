"""人工价格序列回归测试(任务书十八节)。

四类序列(恒定/上涨/下跌/锯齿,open=high=low=close,volume=1)× 六种目标仓位
序列,逐步驱动 AlignedLongFlatEnv,输出 CSV 并断言:
- 信息截至 t,成交严格位于 open[t+1](执行时间 = 观察时间 + 1h);
- 重复目标不交易、零费用;
- 终端仍多头时正确清算;
- 累计未缩放 log reward == log(最终净值 / 初始净值)(仅浮点误差);
- 锯齿关键成交价与手算一致(买 open[2]=90、卖 open[4]=80,与上一阶段
  审计 RL 环境的成交价相同,但本次信息集为行 1,与回测器语义对齐)。
"""

import math
from pathlib import Path

import pandas as pd

from freqai_rl_stage2_5.util import N_ROWS, build_env, make_values

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5"

# 六种目标仓位序列(长度 = 决策步数 = N - window_size = 29)
SCRIPTS = {
    "s1_flat0": [0] * 29,
    "s2_flat1": [1] * 29,
    "s3_0110": [0, 1, 1, 0] + [0] * 25,
    "s4_111": [1, 1, 1] + [0] * 26,
    "s5_01010": [0, 1, 0, 1, 0] + [0] * 24,
    "s6_end1": [0] * 23 + [1] * 6,
}

CSV_COLUMNS = [
    "seq", "script", "step",
    "decision_time", "execution_time",
    "target_position", "actual_position", "trade_direction",
    "raw_open", "exec_price", "fee_paid", "slippage_cost", "notional", "qty",
    "cash", "btc", "equity_start", "equity_end",
    "reward", "reward_raw", "cum_reward_raw",
    "terminated", "truncated", "terminal_liquidation",
]


def run_case(seq_kind: str, script_name: str, actions: list[int], fee: float = 0.001,
             slippage_bps: float = 0.0) -> list[dict]:
    values = make_values(seq_kind)
    env = build_env(values, fee=fee, slippage_bps=slippage_bps)
    obs, _ = env.reset()
    rows = []
    terminated_seen = False
    for step, action in enumerate(actions):
        obs, reward, terminated, truncated, info = env.step(action)
        assert truncated is False
        row = {c: None for c in CSV_COLUMNS}
        row.update({
            "seq": seq_kind, "script": script_name, "step": step,
            "decision_time": info["decision_time"],
            "execution_time": info["execution_time"],
            "target_position": info["new_target_position"],
            "actual_position": 1 if info["btc"] > 0 else 0,
            "trade_direction": info["trade_direction"],
            "raw_open": info["raw_open"], "exec_price": info["exec_price"],
            "fee_paid": info["fee_paid"], "slippage_cost": info["slippage_cost"],
            "notional": info["notional"], "qty": info["qty"],
            "cash": info["cash"], "btc": info["btc"],
            "equity_start": info["equity_start"], "equity_end": info["equity_end"],
            "reward": info["reward_scaled"], "reward_raw": info["reward_raw"],
            "cum_reward_raw": info["episode_reward_raw"],
            "terminated": terminated, "truncated": truncated,
            "terminal_liquidation": info.get("terminal_liquidation") is not None,
        })
        rows.append(row)
        if terminated:
            terminated_seen = True
            break
    assert terminated_seen, "目标序列执行完毕但 episode 未终止"
    return rows


def assert_timing_and_idempotence(rows: list[dict]):
    for r in rows:
        # 成交严格位于观察末行的下一根 K 线
        assert r["execution_time"] == r["decision_time"] + pd.Timedelta(hours=1)
        prev = 0 if r["step"] == 0 else rows[r["step"] - 1]["target_position"]
        if r["target_position"] == prev:
            assert r["trade_direction"] == "hold"
            assert r["fee_paid"] == 0.0
            assert r["qty"] == 0.0


def test_all_sequences_and_scripts():
    ART.mkdir(parents=True, exist_ok=True)
    summary = []
    for seq_kind in ("constant", "rising", "falling", "zigzag"):
        all_rows = []
        for script_name, actions in SCRIPTS.items():
            rows = run_case(seq_kind, script_name, actions)
            all_rows.extend(rows)
            assert_timing_and_idempotence(rows)

            # 累计 log reward 与净值比一致(仅浮点误差)
            cum = rows[-1]["cum_reward_raw"]
            final_equity = rows[-1]["equity_end"]
            expect = math.log(final_equity / 100.0)
            assert math.isclose(cum, expect, rel_tol=1e-12, abs_tol=1e-12), \
                f"{seq_kind}/{script_name}: cum_reward {cum} != log(E/E0) {expect}"

            # 终端语义:equity_end 按 close 估值,人工序列 close == 执行 bar open
            last = rows[-1]
            assert last["terminated"] is True
            assert math.isclose(
                last["equity_end"], last["cash"] + last["btc"] * last["raw_open"]
            )
            assert last["btc"] == 0.0, "terminated 后仍持多头,清算缺失"

            summary.append({
                "seq": seq_kind, "script": script_name,
                "final_equity": final_equity,
                "cum_log_reward": cum,
                "total_fees": sum(r["fee_paid"] for r in rows),
                "n_trades": sum(1 for r in rows if r["trade_direction"] in ("buy", "sell")),
                "n_liquidations": sum(1 for r in rows if r["terminal_liquidation"]),
            })
        pd.DataFrame(all_rows, columns=CSV_COLUMNS).to_csv(
            ART / f"synthetic_{seq_kind}_trace.csv", index=False
        )
    pd.DataFrame(summary).to_csv(ART / "synthetic_summary.csv", index=False)


def test_zigzag_hand_calculated_trade():
    """s3_0110 锯齿:决策行 1 观察 -> 买 open[2]=90;决策行 3 -> 卖 open[4]=80。"""
    rows = run_case("zigzag", "s3_0110", SCRIPTS["s3_0110"])
    buys = [r for r in rows if r["trade_direction"] == "buy"]
    sells = [r for r in rows if r["trade_direction"] == "sell"]
    assert len(buys) == 1 and len(sells) == 1
    buy, sell = buys[0], sells[0]
    assert buy["decision_time"].hour == 1 and buy["execution_time"].hour == 2
    assert buy["raw_open"] == 90.0
    assert sell["decision_time"].hour == 3 and sell["execution_time"].hour == 4
    assert sell["raw_open"] == 80.0
    # 手算:单笔净值变化比 = 80*(1-0.001) / (90*(1+0.001))
    expect = 80.0 * 0.999 / (90.0 * 1.001)
    actual = sell["cash"] / buy["equity_start"]
    assert math.isclose(actual, expect, rel_tol=1e-12)
    # 该手算值与上一阶段审计 RL 环境成交价(open[2]→open[4])同价位,
    # 但本轮信息集为行 1(上一阶段 RL 环境观察行 0 却延到 open[2] 执行,即 gap=2)


def test_s6_terminal_liquidation():
    rows = run_case("zigzag", "s6_end1", SCRIPTS["s6_end1"])
    liq = [r for r in rows if r["terminal_liquidation"]]
    assert len(liq) == 1 and liq[0]["terminated"]
    last = rows[-1]
    assert last["btc"] == 0.0
    # 终端清算后:最终净值 = 现金(无未入账未实现盈亏)
    assert math.isclose(last["equity_end"], last["cash"])
    # 买入:决策行 22 持 0,step 23 目标 1 -> 执行 bar 24(次日 00:00)
    buys = [r for r in rows if r["trade_direction"] == "buy"]
    assert len(buys) == 1
    assert buys[0]["execution_time"] == pd.Timestamp("2026-06-02T00:00:00Z")


def test_fee_zero_slip_zero_round_trip():
    rows = run_case("constant", "s3_0110", SCRIPTS["s3_0110"], fee=0.0, slippage_bps=0.0)
    last = rows[-1]
    # 恒定价格、零费零滑点:开平后净值严格回到 100
    assert math.isclose(last["equity_end"], 100.0, rel_tol=1e-12)
    assert math.isclose(rows[-1]["cum_reward_raw"], math.log(1.0), abs_tol=1e-15)
