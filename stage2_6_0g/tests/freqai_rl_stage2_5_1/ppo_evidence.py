#!/usr/bin/env python
"""阶段 2.5.1 证据收集脚本(工作包 H,任务书二十八/二十九节 + 十八节集成验收)。

全部从 manifest 与实际模型目录动态发现,不硬编码 identifier、窗口日期、
固定行数或回测 zip 名。用法(WSL,conda freqtrade-rl,需代理已 source):

    python tests/freqai_rl_stage2_5_1/ppo_evidence.py --suffix smoke

流程:
0. 发现最新 manifest(suffix 匹配)作为基线;
1. PPO 预算证据(每窗 base/rounded/actual,来自模型目录 ppo_budget.json);
2. TensorBoard tags;
3. reload determinism:删除全部预测缓存保留模型 -> 重跑 ->
   断言 0 次重新训练(mtime 不变)+ 动作逐行一致 + 交易一致;
4. 部分缓存集成(硬性验收):只保留窗口 1/3 缓存 -> 无修复参数必须
   启动前失败(退出码 3,缓存未动)-> --repair-partial-cache 重跑 ->
   quarantine 记录 + 动作/交易与基线一致;
5. 汇总 ppo_hardening_smoke.json。
"""

import argparse
import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pandas as pd

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "tests"))

RUNTIME = PROJ / "experiments" / "freqai_rl_stage2_5_1" / "runtime"
RESULTS = PROJ / "user_data" / "backtest_results"
ART = PROJ / "artifacts" / "freqai_rl_stage2_5_1"
RUN_EXPERIMENT = PROJ / "experiments" / "freqai_rl_stage2_5_1" / "run_experiment.py"


def run_experiment(args: list[str]) -> tuple[int, str]:
    cmd = [sys.executable, str(RUN_EXPERIMENT)] + args
    proc = subprocess.run(cmd, capture_output=True, text=True)
    return proc.returncode, proc.stdout + proc.stderr


def latest_manifest(suffix: str) -> Path:
    ms = sorted(RUNTIME.glob(f"manifest_*_{suffix}.json"),
                key=lambda p: p.stat().st_mtime)
    if not ms:
        raise SystemExit(f"未找到 manifest_{suffix}")
    return ms[-1]


def latest_export_zip() -> Path:
    zips = [p for p in sorted(RESULTS.glob("*.zip"), key=lambda p: p.stat().st_mtime)
            if "meta" not in p.name and "config" not in p.name and "market_data" not in p.name]
    if not zips:
        raise SystemExit("未找到回测导出 zip")
    return zips[-1]


def load_trades(zip_path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(zip_path) as zf:
        main = [n for n in zf.namelist() if n.endswith(".json") and "meta" not in n
                and "config" not in n and "market_data" not in n][0]
        data = json.loads(zf.read(main))
    strat = list(data["strategy"].values())[0]
    return pd.DataFrame(strat["trades"])


def actions_of(manifest: dict) -> pd.DataFrame:
    return pd.read_csv(manifest["post_run"]["actions_csv"])


def model_state(models_dir: Path) -> dict:
    """每窗 sub-train 目录内模型文件的 (路径, mtime) 快照:证明未重新训练。

    只覆盖 sub-train-*/(模型/pipeline/预算);根目录的 run_params.json、
    pair_dictionary.json 会在每次 FreqAI 启动时被重写,不属于训练产物。
    """
    out = {}
    for sub in sorted(models_dir.glob("sub-train-*")):
        for p in sorted(sub.rglob("*")):
            if p.is_file():
                out[str(p.relative_to(models_dir))] = p.stat().st_mtime
    return out


def tb_tags(models_dir: Path) -> list[str]:
    tags: set[str] = set()
    try:
        from tensorboard.backend.event_processing.event_file_loader import EventFileLoader
    except ImportError:
        return ["tensorboard 包不可用"]
    for f in models_dir.rglob("events.out.tfevents.*"):
        try:
            for ev in EventFileLoader(str(f)).Load():
                for v in ev.summary.value:
                    tags.add(v.tag)
        except Exception as e:  # noqa: BLE001
            tags.add(f"<load error {e}>")
    return sorted(tags)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--suffix", default="smoke")
    args = ap.parse_args()
    ART.mkdir(parents=True, exist_ok=True)

    base_manifest_path = latest_manifest(args.suffix)
    m = json.loads(base_manifest_path.read_text())
    identifier = m["identifier"]
    models_dir = PROJ / "user_data" / "models" / identifier
    pred_dir = models_dir / "backtesting_predictions"
    print(f"[evidence] identifier={identifier}")

    summary = {
        "identifier": identifier,
        "fingerprint": m["fingerprint"],
        "expected_windows": len(m["expected_windows"]),
    }

    # ------------------------------------------------ 1. PPO 预算
    budgets = m["post_run"]["ppo_budgets"]
    bd = pd.DataFrame(budgets)
    bd.to_csv(ART / "ppo_budget_per_window.csv", index=False)
    assert (bd["rounded_budget"] % bd["n_steps"] == 0).all()
    assert (bd["actual_num_timesteps"] == bd["rounded_budget"]).all()
    summary["ppo_budgets"] = {
        "windows": len(bd),
        "base_budgets": bd["base_budget"].tolist(),
        "rounded_budgets": bd["rounded_budget"].tolist(),
        "actual_num_timesteps": bd["actual_num_timesteps"].tolist(),
        "episode_resets": bd["episode_resets"].tolist(),
    }
    print(f"[evidence] 预算: base={bd['base_budget'].tolist()} "
          f"rounded={bd['rounded_budget'].tolist()} "
          f"actual={bd['actual_num_timesteps'].tolist()}")

    # ------------------------------------------------ 2. TensorBoard tags
    tags = tb_tags(models_dir)
    (ART / "tensorboard_tags.txt").write_text(
        "\n".join(tags) + "\n", encoding="utf-8")
    required_tags = ["rollout/ep_rew_mean", "rollout/ep_len_mean",
                     "train/policy_gradient_loss", "train/value_loss",
                     "train/entropy_loss", "train/explained_variance",
                     "train/approx_kl"]
    missing = [t for t in required_tags if t not in tags]
    summary["tensorboard"] = {"n_tags": len(tags), "missing_required": missing}
    print(f"[evidence] TB tags={len(tags)} 缺失必需={missing}")

    # ------------------------------------------------ 基线动作/交易
    actions_base = actions_of(m)
    trades_base = load_trades(latest_export_zip())
    trades_base.to_csv(ART / "baseline_trades.csv", index=False)
    base_model_state = model_state(models_dir)
    summary["baseline"] = {"actions_rows": len(actions_base),
                           "trades": len(trades_base),
                           "action_distribution": m["post_run"]["action_distribution"]}

    # ------------------------------------------------ 3. reload determinism
    keep_cache = sorted(pred_dir.glob("*.feather"))
    for f in keep_cache:
        f.unlink()
    rc, out = run_experiment(["--suffix", "reload"])
    assert rc == 0, f"reload 运行失败 rc={rc}\n{out[-2000:]}"
    m2 = json.loads(latest_manifest("reload").read_text())
    actions_reload = actions_of(m2)
    trades_reload = load_trades(latest_export_zip())
    same_actions = actions_base.equals(actions_reload)
    trades_equal = trades_base.equals(trades_reload)
    model_state_after = model_state(models_dir)
    no_retrain = model_state_after == base_model_state
    reload_result = {
        "identifier": m2["identifier"],
        "identifier_unchanged": m2["identifier"] == identifier,
        "actions_identical": bool(same_actions),
        "trades_identical": bool(trades_equal),
        "no_retraining_model_files_unchanged": bool(no_retrain),
        "n_trades": int(len(trades_reload)),
    }
    (ART / "reload_determinism.json").write_text(
        json.dumps(reload_result, indent=2, ensure_ascii=False))
    assert same_actions, "重载后动作序列不一致"
    assert trades_equal, "重载后交易不一致"
    assert no_retrain, "重载后模型文件被重写(重新训练)"
    print(f"[evidence] reload determinism: OK (trades={len(trades_reload)})")

    # ------------------------------------------------ 4. 部分缓存(集成硬验收)
    # 只保留窗口 1 和 3 的缓存
    caches = sorted(pred_dir.glob("*.feather"),
                    key=lambda p: int(p.name.split("_")[2]))
    n_win = len(caches)
    removed = []
    for i, f in enumerate(caches):
        if i not in (0, 2):
            removed.append(f.name)
            f.unlink()
    snapshot_before = {p.name: p.stat().st_mtime for p in pred_dir.glob("*.feather")}

    # 4a. 无修复参数:必须启动前失败(退出码 3)
    rc_partial, out_partial = run_experiment(["--suffix", "partial-nofix"])
    snapshot_after = {p.name: p.stat().st_mtime for p in pred_dir.glob("*.feather")}
    nofix_ok = rc_partial == 3 and snapshot_before == snapshot_after

    # 4b. 修复模式
    rc_fix, out_fix = run_experiment(["--suffix", "partial-fix",
                                      "--repair-partial-cache"])
    assert rc_fix == 0, f"修复运行失败 rc={rc_fix}\n{out_fix[-2000:]}"
    m3 = json.loads(latest_manifest("partial-fix").read_text())
    quarantine = m3["cache_guard"].get("quarantine")
    actions_fix = actions_of(m3)
    trades_fix = load_trades(latest_export_zip())
    model_state_fix = model_state(models_dir)
    fix_result = {
        "nofix_exit_code": rc_partial,
        "nofix_cache_untouched": bool(nofix_ok),
        "removed_windows_for_test": removed,
        "repair_exit_code": rc_fix,
        "quarantine": quarantine,
        "actions_identical_to_baseline": bool(actions_base.equals(actions_fix)),
        "trades_identical_to_baseline": bool(trades_base.equals(trades_fix)),
        "no_retraining_model_files_unchanged": bool(model_state_fix == base_model_state),
        "identifier_unchanged": m3["identifier"] == identifier,
    }
    (ART / "partial_cache_repair_trace.json").write_text(
        json.dumps(fix_result, indent=2, ensure_ascii=False))
    assert nofix_ok, "无修复参数未能在启动前中止(或缓存被修改)"
    assert quarantine and Path(quarantine).is_dir(), "quarantine 目录不存在"
    assert actions_base.equals(actions_fix), "修复后动作序列与基线不一致"
    assert trades_base.equals(trades_fix), "修复后交易与基线不一致"
    assert model_state_fix == base_model_state, "修复后发生重新训练"
    print(f"[evidence] 部分缓存: nofix rc=3 ✓ quarantine={quarantine} 修复一致 ✓")

    # ------------------------------------------------ 5. 汇总
    summary["reload_determinism"] = reload_result
    summary["partial_cache"] = fix_result
    (ART / "ppo_hardening_smoke.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False))
    print("[evidence] 全部证据收集完成 ->", ART / "ppo_hardening_smoke.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
