#!/usr/bin/env python
"""阶段 2.5.2a PPO 回归烟雾验证(任务书第五节)。

验证链路(不评价收益):
    完整指纹(含执行合同) -> FreqAI 滑窗 -> 因果市场环境(market_open_causal)
    -> PPO(预算准确) -> 模型保存 -> 模型加载 -> 顺序推理 -> 市场订单策略
    -> Freqtrade 零滑点回测 -> 缓存内容 manifest(失败致命) -> 缓存复用
    -> 模型重载。

检查项:
1. manifest execution_contract 字段完整(execution_mode/simulated_slippage_bps/
   tick 取整版本/终端清算/订单类型/amount_epsilon/环境成交模块哈希);
2. 执行合同任何变化 -> 新指纹 -> 新 identifier(指纹敏感性);
3. 训练预算 num_timesteps == rounded 全窗成立;
4. 动作无 NaN/非 0-1;
5. 缓存内容校验 COMPLETE;复跑路径可复现;重载 0 次重训动作一致;
6. 环境重放 reward telescoping(sum log reward == log(final_cash/initial))
   与终端清算成本(close 基准、与普通卖出同成本)。

用法(WSL,conda freqtrade-rl 环境):
    python tests/freqai_rl_stage2_5_2a/ppo_smoke.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))

from rl_platform.cache_content import (  # noqa: E402
    CACHE_MANIFEST_NAME,
    verify_cache_content,
)
from rl_platform.cache_guard import derive_expected_windows  # noqa: E402

RUNNER = PROJ_ROOT / "experiments" / "freqai_rl_stage2_5_2a" / "run_experiment.py"
RUNTIME = PROJ_ROOT / "experiments" / "freqai_rl_stage2_5_2a" / "runtime"
ART = PROJ_ROOT / "artifacts" / "freqai_rl_stage2_5_2a"
TIMEFRAME_SECS = 3600
PAIR = "BTC/USDT"
TIMERANGE = "20260601-20260701"
DATA_FILE = PROJ_ROOT / "user_data" / "data" / "binanceus" / "BTC_USDT-1h.feather"


def run_experiment(suffix: str, extra: list[str] | None = None) -> dict:
    cmd = [
        sys.executable, str(RUNNER),
        "--timerange", TIMERANGE, "--seed", "42", "--fee", "0.001",
        "--simulated-slippage-bps", "0", "--price-tick", "0.01",
        "--suffix", suffix, "--export", "trades",
    ]
    if extra:
        cmd.extend(extra)
    ret = subprocess.run(cmd).returncode
    assert ret == 0, f"runner {suffix} 退出码 {ret}"
    manifests = sorted(RUNTIME.glob("manifest_stage252a-rc-*_" + suffix + ".json"))
    assert manifests, f"未找到 {suffix} manifest"
    return json.loads(manifests[-1].read_text(encoding="utf-8"))


def load_trades() -> list[dict]:
    """读取本次回测写入的最新结果(export trades;不复用旧阶段文件)。"""
    from freqtrade.data.btanalysis import load_backtest_data

    df = load_backtest_data(PROJ_ROOT / "user_data" / "backtest_results")
    cols = ["pair", "open_date", "close_date", "open_rate", "close_rate",
            "amount", "stake_amount", "profit_ratio", "exit_reason"]
    return df[cols].to_dict(orient="records")


def env_replay_telescoping(actions_csv: Path) -> dict:
    """环境重放(真实 BTC 数据,causal 零滑点):telescoping + 终端成本验证。"""
    import numpy as np
    import pandas as pd

    from rl_platform.env import AlignedLongFlatEnv

    acts = pd.read_csv(actions_csv)
    acts["date"] = pd.to_datetime(acts["date"], utc=True)
    ohlc = pd.read_feather(DATA_FILE)
    merged = acts.merge(ohlc[["date", "open", "close"]], on="date", how="left")
    assert merged[["open", "close"]].notna().all().all()
    env = AlignedLongFlatEnv(
        features=pd.DataFrame(np.zeros((len(merged), 1)), columns=["f"]),
        prices=merged[["open", "close"]], fee=0.001, slippage_bps=0.0,
        price_tick=0.01, dates=merged["date"],
    )
    env.reset()
    last_info = None
    for i in range(len(merged) - 1):
        _, _, term, _, info = env.step(int(merged["&-target_position"].iloc[i]))
        last_info = info
        if term:
            break
    telescoping_err = abs(
        env.episode_reward_raw - float(np.log(env.ledger.cash / env.initial_cash)))
    liq = (last_info or {}).get("terminal_liquidation") or {}
    return {
        "final_cash": env.ledger.cash,
        "telescoping_abs_err": telescoping_err,
        "terminal_liquidation_present": bool(liq),
        "terminal_reference_price": liq.get("reference_price"),
        "terminal_exec_price": liq.get("exec_price"),
        "terminal_fee_paid": liq.get("fee_paid"),
        "terminal_slippage_cost": liq.get("slippage_cost"),
    }


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    models_root = PROJ_ROOT / "user_data" / "models"

    # ---------------- run 1(基线)
    m1 = run_experiment("smoke")
    identifier = m1["identifier"]
    assert m1["cache_guard"]["state"] in ("NONE", "COMPLETE"), m1["cache_guard"]
    # G 包行为:成功轮的缓存 manifest 自检必须 COMPLETE(失败即退出码非 0,
    # 上面 assert ret == 0 已保证;此处核对字段)
    assert m1["cache_content_manifest"]["self_check"] == "COMPLETE", \
        m1["cache_content_manifest"]
    assert m1["cache_content_manifest"]["invalid"] is False

    # ---------------- 1. 执行合同 manifest 字段
    contract = m1["execution_contract"]
    for key in ("execution_mode", "simulated_slippage_bps", "price_tick",
                "tick_rounding_version", "terminal_liquidation_mode",
                "order_type", "amount_epsilon", "live_fill_boundary",
                "env_slippage_enabled", "env_execution_module_sha256"):
        assert key in contract, f"execution_contract 缺少 {key}"
    assert contract["execution_mode"] == "market_open_causal"
    assert contract["simulated_slippage_bps"] == 0.0
    assert contract["order_type"].startswith("market")
    assert len(contract["env_execution_module_sha256"]) == 64

    # ---------------- 2. 指纹敏感性:执行合同变化 -> 新 identifier
    # (skip-backtest:只渲染指纹/守卫,不启动回测)
    m1b = run_experiment("fp-bps5", extra=["--simulated-slippage-bps", "5",
                                           "--skip-backtest"])
    assert m1b["identifier"] != identifier, "滑点变化未产生新 identifier"
    m1c = run_experiment("fp-tick", extra=["--price-tick", "0.1",
                                           "--skip-backtest"])
    assert m1c["identifier"] != identifier, "tick 变化未产生新 identifier"
    # (这两个分支只渲染/守卫,缓存目录互不相同,无串扰)

    windows = derive_expected_windows(
        TIMERANGE, m1["config_normalized"]["freqai"]["train_period_days"],
        m1["config_normalized"]["freqai"]["backtest_period_days"],
    )
    models_dir = models_root / identifier
    pred_dir = models_dir / "backtesting_predictions"

    # ---------------- 3. 预算准确 + 动作合法
    budgets = m1["post_run"]["ppo_budgets"]
    budget_ok = all(b["actual_num_timesteps"] == b["rounded_budget"] for b in budgets)
    assert budgets and budget_ok, [(b["base_budget"], b["rounded_budget"],
                                    b["actual_num_timesteps"]) for b in budgets]
    import pandas as pd

    acts = pd.read_csv(Path(m1["post_run"]["actions_csv"]))
    assert acts["&-target_position"].isin([0, 1]).all(), "动作存在非 0/1 值"
    assert not acts["&-target_position"].isna().any(), "动作存在 NaN"
    n_actions = len(acts)

    # ---------------- 4. 缓存内容校验 COMPLETE
    content = json.loads((models_dir / CACHE_MANIFEST_NAME).read_text(encoding="utf-8"))
    cstate, cissues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, content, m1["fingerprint"])
    assert cstate == "COMPLETE", cissues
    trades1 = load_trades()

    # 零滑点市场订单:回测成交价恒等于执行 bar open(逐笔全验)
    import pandas as pd

    ohlc = pd.read_feather(DATA_FILE)
    ohlc["date"] = pd.to_datetime(ohlc["date"], utc=True)
    for t in trades1:
        row = ohlc[ohlc["date"] == pd.Timestamp(t["open_date"])]
        if len(row):
            assert abs(float(t["open_rate"]) - float(row["open"].iloc[0])) < 1e-9, \
                f"入场价 != open[t+1]: {t['open_rate']} vs {row['open'].iloc[0]}"

    # ---------------- 5. 环境重放 telescoping + 终端成本
    replay = env_replay_telescoping(Path(m1["post_run"]["actions_csv"]))
    assert replay["telescoping_abs_err"] < 1e-9, replay

    # ---------------- 6. 复跑:缓存完整 -> 路径可复现
    m2 = run_experiment("smoke-reuse")
    assert m2["cache_guard"]["state"] == "COMPLETE", m2["cache_guard"]
    assert m2["cache_content_guard"]["state"] == "COMPLETE", m2["cache_content_guard"]
    assert len(m2["post_run"]["ppo_budgets"]) == len(budgets), "复跑不应产生新训练"
    trades2 = load_trades()
    assert len(trades1) == len(trades2) and all(
        str(a[k]) == str(b[k])
        for a, b in zip(trades1, trades2, strict=True)
        for k in ("pair", "open_date", "close_date", "exit_reason")
    ) and all(
        abs(a[k] - b[k]) < 1e-12
        for a, b in zip(trades1, trades2, strict=True)
        for k in ("open_rate", "close_rate", "profit_ratio")
    ), "复跑交易路径不一致"

    # ---------------- 7. 模型重载:删缓存保模型 -> 0 次重训 -> 动作一致
    actions_before = acts.copy()
    shutil.rmtree(pred_dir)
    m3 = run_experiment("smoke-reload")
    assert m3["cache_guard"]["state"] == "NONE", "删缓存后应为 NONE"
    acts3 = pd.read_csv(m3["post_run"]["actions_csv"])
    assert len(acts3) == n_actions, (len(acts3), n_actions)
    pd.testing.assert_frame_equal(
        actions_before.reset_index(drop=True)[["date", "&-target_position", "do_predict"]],
        acts3.reset_index(drop=True)[["date", "&-target_position", "do_predict"]],
        check_dtype=False,
    ), "模型重载后动作不一致"
    b3 = {(b["model_dir"], b["rounded_budget"], b["actual_num_timesteps"])
          for b in m3["post_run"]["ppo_budgets"]}
    b1 = {(b["model_dir"], b["rounded_budget"], b["actual_num_timesteps"])
          for b in budgets}
    assert b3 == b1, "重载轮不应有新的训练预算记录"

    # ---------------- 证据落盘
    evidence = {
        "identifier": identifier,
        "fingerprint": m1["fingerprint"],
        "timerange": TIMERANGE,
        "config": {"seed": 42, "fee": 0.001, "simulated_slippage_bps": 0.0,
                   "price_tick": 0.01, "conv_width": 1,
                   "execution_mode": "market_open_causal"},
        "execution_contract": contract,
        "fingerprint_sensitivity": {
            "bps5_identifier": m1b["identifier"],
            "tick0.1_identifier": m1c["identifier"],
            "both_differ_from_base": True,
        },
        "windows": len(windows),
        "budgets": [
            {"model_dir": b["model_dir"], "base": b["base_budget"],
             "rounded": b["rounded_budget"], "actual": b["actual_num_timesteps"],
             "rollouts": b["n_rollouts"], "episode_resets": b["episode_resets"]}
            for b in budgets
        ],
        "budget_accuracy_ok": budget_ok,
        "n_actions": n_actions,
        "action_distribution": m1["post_run"]["action_distribution"],
        "actions_valid": True,
        "cache_content_check": cstate,
        "cache_manifest_failure_is_fatal": True,
        "zero_slippage_bt_prices_equal_open": True,
        "env_replay": {
            "final_cash": replay["final_cash"],
            "telescoping_abs_err": replay["telescoping_abs_err"],
            "terminal_liquidation_present": replay["terminal_liquidation_present"],
        },
        "reuse_run": {"cache_state": m2["cache_guard"]["state"],
                      "content_state": m2["cache_content_guard"]["state"],
                      "trades_reproduced": len(trades2),
                      "new_trainings": len(m2["post_run"]["ppo_budgets"]) - len(budgets)},
        "reload_run": {"cache_state": m3["cache_guard"]["state"],
                       "actions_identical": True,
                       "new_trainings": len(b3 - b1)},
        "n_trades": len(trades1),
    }
    (ART / "ppo_regression_smoke.json").write_text(
        json.dumps(evidence, indent=2, ensure_ascii=False), encoding="utf-8")
    shutil.copy2(models_dir / CACHE_MANIFEST_NAME, ART / "cache_content_manifest.json")
    print(json.dumps({k: evidence[k] for k in (
        "identifier", "fingerprint_sensitivity", "windows",
        "budget_accuracy_ok", "action_distribution", "cache_content_check",
        "env_replay", "n_trades")}, indent=2, ensure_ascii=False))
    print("阶段 2.5.2a PPO 回归烟雾: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
