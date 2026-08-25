#!/usr/bin/env python
"""阶段 2.5.2 PPO 回归烟雾验证(任务书二十节)。

前提:experiments/freqai_rl_stage2_5_2/run_experiment.py 已完成一次烟雾
(或由本脚本自动补跑)。验证链路(不评价收益):

    完整指纹 -> FreqAI 滑窗 -> PPO(预算准确)-> 模型保存 -> 模型加载
    -> 顺序推理 -> RouteCStrategy -> Freqtrade 回测 -> 缓存内容校验

检查项:
1. 训练预算:num_timesteps == rounded(ceil(base/n_steps)*n_steps) 全窗成立;
2. 动作无 NaN / 非 0/1 值;
3. 缓存内容校验 COMPLETE(sha/日期序列/列哈希);
4. 复跑(缓存完整):内容校验通过、交易路径逐字段可复现;
5. 模型重载确定性:删缓存保模型 -> 0 次重新训练,动作逐字段一致;
6. 证据写 artifacts/freqai_rl_stage2_5_2/ppo_regression_smoke.json
   + cache_content_manifest.json(副本)。

用法(WSL,conda freqtrade-rl 环境):
    python tests/freqai_rl_stage2_5_2/ppo_smoke.py
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PROJ_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ_ROOT / "src"))
sys.path.insert(0, str(PROJ_ROOT / "tests"))

from rl_platform.cache_content import (  # noqa: E402
    CACHE_MANIFEST_NAME,
    build_cache_content_manifest,
    verify_cache_content,
)
from rl_platform.cache_guard import derive_expected_windows  # noqa: E402

RUNNER = PROJ_ROOT / "experiments" / "freqai_rl_stage2_5_2" / "run_experiment.py"
RUNTIME = PROJ_ROOT / "experiments" / "freqai_rl_stage2_5_2" / "runtime"
ART = PROJ_ROOT / "artifacts" / "freqai_rl_stage2_5_2"
TIMEFRAME_SECS = 3600
PAIR = "BTC/USDT"
TIMERANGE = "20260601-20260701"


def run_experiment(suffix: str) -> dict:
    cmd = [
        sys.executable, str(RUNNER),
        "--timerange", TIMERANGE, "--seed", "42", "--fee", "0.001",
        "--slippage-bps", "5", "--price-tick", "0.01",
        "--suffix", suffix, "--export", "none",
    ]
    ret = subprocess.run(cmd).returncode
    assert ret == 0, f"runner {suffix} 退出码 {ret}"
    manifests = sorted(RUNTIME.glob("manifest_stage252-rc-*_" + suffix + ".json"))
    assert manifests, f"未找到 {suffix} manifest"
    return json.loads(manifests[-1].read_text(encoding="utf-8"))


def load_trades() -> list[dict]:
    """从 freqtrade backtest_results 动态发现最新结果(不硬编码文件名)。"""
    from freqtrade.data.btanalysis import load_backtest_data

    df = load_backtest_data(PROJ_ROOT / "user_data" / "backtest_results")
    cols = ["pair", "open_date", "close_date", "open_rate", "close_rate",
            "amount", "stake_amount", "profit_ratio", "exit_reason"]
    return df[cols].to_dict(orient="records")


def main() -> int:
    ART.mkdir(parents=True, exist_ok=True)
    models_root = PROJ_ROOT / "user_data" / "models"

    # ---------------- run 1(基线;已有则复用其 manifest 重跑保证时序一致)
    m1 = run_experiment("smoke")
    identifier = m1["identifier"]
    assert m1["cache_guard"]["state"] in ("NONE", "COMPLETE"), m1["cache_guard"]
    windows = derive_expected_windows(
        TIMERANGE, m1["config_normalized"]["freqai"]["train_period_days"],
        m1["config_normalized"]["freqai"]["backtest_period_days"],
    )
    models_dir = models_root / identifier
    pred_dir = models_dir / "backtesting_predictions"

    # ---------------- 1. 预算准确 + 2. 动作合法
    budgets = m1["post_run"]["ppo_budgets"]
    budget_ok = all(b["actual_num_timesteps"] == b["rounded_budget"] for b in budgets)
    assert budgets and budget_ok, [(b["base_budget"], b["rounded_budget"],
                                    b["actual_num_timesteps"]) for b in budgets]
    actions_csv = Path(m1["post_run"]["actions_csv"])
    import pandas as pd

    acts = pd.read_csv(actions_csv)
    assert acts["&-target_position"].isin([0, 1]).all(), "动作存在非 0/1 值"
    assert not acts["&-target_position"].isna().any(), "动作存在 NaN"
    n_actions = len(acts)

    # ---------------- 3. 缓存内容校验 COMPLETE
    content = json.loads((models_dir / CACHE_MANIFEST_NAME).read_text(encoding="utf-8"))
    cstate, cissues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, content, m1["fingerprint"])
    assert cstate == "COMPLETE", cissues

    # 基线交易路径(run 1 之后读取最新 backtest_results)
    trades1 = load_trades()

    # ---------------- 4. 复跑:缓存完整 -> 内容校验通过 -> 路径可复现
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

    # ---------------- 5. 模型重载确定性:删缓存保模型 -> 0 次重训 -> 动作一致
    actions_before = acts.copy()
    shutil.rmtree(pred_dir)  # 只删预测缓存;模型目录(sub-train-*)全部保留
    m3 = run_experiment("smoke-reload")
    assert m3["cache_guard"]["state"] == "NONE", "删缓存后应为 NONE"
    acts3 = pd.read_csv(m3["post_run"]["actions_csv"])
    assert len(acts3) == n_actions, (len(acts3), n_actions)
    pd.testing.assert_frame_equal(
        actions_before.reset_index(drop=True)[["date", "&-target_position", "do_predict"]],
        acts3.reset_index(drop=True)[["date", "&-target_position", "do_predict"]],
        check_dtype=False,
    ), "模型重载后动作不一致"
    # 0 次重新训练:预算记录数量与 run1 相同且内容一致(无新增 sub-train 目录)
    b3 = {(b["model_dir"], b["rounded_budget"], b["actual_num_timesteps"]) for b in m3["post_run"]["ppo_budgets"]}
    b1 = {(b["model_dir"], b["rounded_budget"], b["actual_num_timesteps"]) for b in budgets}
    assert b3 == b1, "重载轮不应有新的训练预算记录"

    # ---------------- 证据落盘
    evidence = {
        "identifier": identifier,
        "fingerprint": m1["fingerprint"],
        "timerange": TIMERANGE,
        "config": {"seed": 42, "fee": 0.001, "slippage_bps": 5.0,
                   "price_tick": 0.01, "conv_width": 1},
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
    print(json.dumps(evidence, indent=2, ensure_ascii=False))
    print("PPO 回归烟雾: 全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
