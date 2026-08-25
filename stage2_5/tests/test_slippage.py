"""滑点测试(任务书二十节)。

1. 环境滑点公式手算(已在 test_ledger 覆盖,这里做端到端环境级验证);
2. 滑点增加时,相同动作序列与价格下最终净值单调下降;
3. Freqtrade 用户策略扩展点(custom_entry_price / custom_exit_price)可在
   不修改核心源码的情况下复现相同确定性滑点(源码调用点:
   optimize/backtesting.py:1041(entry)与 :892(exit),limit 单生效,
   且会被 clamp 到当根 high/low 内)——端到端对比见 test_env_vs_freqtrade
   的 fee001_slip5bps 轮;
4. 单调性证据文件 slippage_monotonicity。
"""

import json
import math
from pathlib import Path

from freqai_rl_stage2_5.util import build_env, make_values

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5"


def run_with_slippage(seq_kind: str, bps: float, fee: float = 0.001) -> dict:
    env = build_env(make_values(seq_kind), fee=fee, slippage_bps=bps)
    env.reset()
    # 0->1->0 反复(决策序列),驱动多次开平
    targets = []
    for i in range(29):
        targets.append(1 if (i // 3) % 2 == 0 else 0)
    last = None
    for a in targets:
        _, _, terminated, _, info = env.step(a)
        last = info
        if terminated:
            break
    return {
        "slippage_bps": bps, "fee": fee,
        "final_equity": last["equity_end"],
        "total_fees": None,  # 由环境内部累计,下面从 info 重新聚合
    }


def run_collect(seq_kind: str, bps: float, fee: float = 0.001):
    env = build_env(make_values(seq_kind), fee=fee, slippage_bps=bps)
    env.reset()
    targets = [1 if (i // 3) % 2 == 0 else 0 for i in range(29)]
    fees = 0.0
    slips = 0.0
    last = None
    for a in targets:
        _, _, terminated, _, info = env.step(a)
        fees += info["fee_paid"]
        slips += info["slippage_cost"]
        last = info
        if terminated:
            break
    return {"final_equity": last["equity_end"], "total_fees": fees,
            "total_slippage_cost": slips}


def test_slippage_formula_end_to_end():
    """锯齿第 0 步买入:成交价 = open[t+1]*(1+bps/1e4),费用按滑点后名义金额。"""
    env = build_env(make_values("zigzag"), fee=0.001, slippage_bps=5.0)
    env.reset()
    _, _, _, _, info = env.step(1)  # 决策行 0 -> 买在 open[1]=110
    exec_expected = 110.0 * (1 + 5.0 / 10000.0)
    qty_expected = 100.0 / (exec_expected * 1.001)
    assert math.isclose(info["exec_price"], exec_expected, rel_tol=1e-12)
    assert math.isclose(info["qty"], qty_expected, rel_tol=1e-12)
    assert math.isclose(info["fee_paid"], qty_expected * exec_expected * 0.001, rel_tol=1e-12)
    assert math.isclose(info["slippage_cost"], qty_expected * 5.0 / 10000.0 * 110.0, rel_tol=1e-9)


def test_slippage_monotonicity():
    ART.mkdir(parents=True, exist_ok=True)
    rows = []
    prev_equity = None
    for seq_kind in ("zigzag", "rising", "falling"):
        prev = None
        for bps in (0.0, 5.0, 10.0):
            r = run_collect(seq_kind, bps)
            r.update({"seq": seq_kind, "slippage_bps": bps})
            rows.append(r)
            if prev is not None:
                assert r["final_equity"] < prev, \
                    f"{seq_kind}: 滑点 {bps}bps 净值未单调下降"
            prev = r["final_equity"]
        prev_equity = prev
    pd_rows = rows
    import pandas as pd

    df = pd.DataFrame(pd_rows)[["seq", "slippage_bps", "final_equity",
                                "total_fees", "total_slippage_cost"]]
    df.to_csv(ART / "slippage_monotonicity.csv", index=False)
    summary = {
        "conclusion": "相同动作序列与价格下,滑点 0/5/10bps 的最终净值在三类序列上均严格单调下降;"
        "费用与滑点分别累计,无重复扣除(费用按滑点后名义金额,滑点成本单独记录)。",
        "rows": rows,
    }
    (ART / "slippage_monotonicity.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False)
    )
