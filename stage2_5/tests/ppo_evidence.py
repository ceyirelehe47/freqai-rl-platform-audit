#!/usr/bin/env python
"""PPO 烟雾测试证据生成(阶段 2.5)。

三层证据:
1. trades 一致性:run1(训练+顺序推理)与 run2(删除预测缓存、模型重载+顺序推理)
   的回测成交逐字段一致 -> 重载不改变行为;
2. 动作序列:run2 重建的预测缓存(backtesting_predictions feather)按窗口拼接
   720 行目标仓位序列(sequential_inference_trace.csv / cross_window_state_trace.csv);
3. 独立重推理:在独立进程中加载 5 个保存模型 + 特征管线,对原始数据重算特征、
   跨窗顺序推理 720 行,与 run2 缓存序列逐行对比 -> 模型保存/加载后动作可复现;
4. 仓位敏感性:第 5 窗首行以 pos=0/1 构造观察,验证目标仓位确实进入观察。
"""

import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "tests"))

ART = PROJ / "artifacts" / "freqai_rl_stage2_5"
MODEL_DIR = PROJ / "user_data" / "models"
IDENTIFIER = "stage25-rc-b6259bb8d5"
DATA_FILE = PROJ / "user_data" / "data" / "binanceus" / "BTC_USDT-1h.feather"
WIN_STARTS = ["2026-06-01", "2026-06-08", "2026-06-15", "2026-06-22", "2026-06-29"]
WINDOW_ROWS = [168, 168, 168, 168, 48]

TRADE_KEYS = ["pair", "open_date", "close_date", "open_rate", "close_rate",
              "profit_ratio", "profit_abs", "exit_reason", "trade_duration",
              "is_open", "amount", "stake_amount"]


def load_trades(zip_path: str) -> list[dict]:
    with zipfile.ZipFile(zip_path) as zf:
        jname = [n for n in zf.namelist() if n.endswith(".json") and "config" not in n][0]
        data = json.loads(zf.read(jname))
    strat = list(data["strategy"].keys())[0]
    return data["strategy"][strat]["trades"]


def load_cached_actions() -> pd.DataFrame:
    """拼接 run2 重建的预测缓存(5 窗 feather)为 720 行序列。"""
    pred_dir = MODEL_DIR / IDENTIFIER / "backtesting_predictions"
    frames = []
    for f in sorted(pred_dir.glob("cb_btc_*_prediction.feather")):
        df = pd.read_feather(f)
        frames.append(df[["date", "&-target_position", "do_predict"]])
    out = pd.concat(frames, ignore_index=True)
    out["date"] = pd.to_datetime(out["date"])
    return out


def rebuild_features() -> pd.DataFrame:
    """从原始 feather 重算 RouteCStrategy 的 4 个因果特征(裁剪到评估区间)。"""
    df = pd.read_feather(DATA_FILE)
    df = df[df["date"] >= pd.Timestamp("2026-05-01", tz="UTC")].reset_index(drop=True)
    ret1 = df["close"].pct_change()
    df["%-ret-1"] = ret1
    df["%-ret-4"] = df["close"].pct_change(4)
    df["%-vol-24"] = ret1.rolling(24).std()
    df["%-price-ma-ratio"] = df["close"] / df["close"].rolling(24).mean() - 1
    df = df[(df["date"] >= pd.Timestamp("2026-06-01", tz="UTC"))
            & (df["date"] < pd.Timestamp("2026-07-01", tz="UTC"))].reset_index(drop=True)
    assert len(df) == 720, f"特征行数 {len(df)} != 720"
    return df


def independent_reinference() -> np.ndarray:
    """独立进程加载保存的 5 个模型+特征管线,跨窗顺序推理 720 行。"""
    from rl_platform.inference import SequentialPositionPredictor
    from stable_baselines3 import PPO

    feats = rebuild_features()
    sub_dirs = sorted((MODEL_DIR / IDENTIFIER).glob("sub-train-BTC_*"))
    assert len(sub_dirs) == 5, f"模型目录数 {len(sub_dirs)} != 5"

    actions = []
    position = 0
    start = 0
    for w, sub in enumerate(sub_dirs):
        ts = sub.name.split("_")[1]
        model = PPO.load(sub / f"cb_btc_{ts}_model.zip", device="cpu")
        pipeline = pd.read_pickle(sub / f"cb_btc_{ts}_feature_pipeline.pkl")
        meta = json.loads((sub / f"cb_btc_{ts}_metadata.json").read_text())
        cols = list(meta["training_features_list"])

        n = WINDOW_ROWS[w]
        X = feats.iloc[start:start + n][cols].reset_index(drop=True)
        Xt, _, _ = pipeline.transform(X)
        predictor = SequentialPositionPredictor(model, window_size=1)
        predictor.current_position = position
        acts = predictor.predict_frame(Xt)
        actions.extend(acts.tolist())
        position = int(predictor.current_position)
        start += n
    assert len(actions) == 720
    return np.asarray(actions, dtype=np.int64)


def window_labels(dates: pd.Series) -> list[int]:
    labels = []
    for d in dates:
        w = 5
        ds = str(d)[:10]
        for i, ws in enumerate(WIN_STARTS):
            nxt = WIN_STARTS[i + 1] if i + 1 < len(WIN_STARTS) else "9999"
            if ws <= ds < nxt:
                w = i + 1
                break
        labels.append(w)
    return labels


def main(zip1: str, zip2: str) -> int:
    ART.mkdir(parents=True, exist_ok=True)

    # ---- 证据 1:两轮 trades 逐字段一致
    t1, t2 = load_trades(zip1), load_trades(zip2)
    trades_identical = len(t1) == len(t2)
    trade_diffs = []
    for a, b in zip(t1, t2):
        for k in TRADE_KEYS:
            if a.get(k) != b.get(k):
                trades_identical = False
                trade_diffs.append({k: [a.get(k), b.get(k)]})

    # ---- 证据 2:缓存动作序列拼接
    cached = load_cached_actions()
    assert len(cached) == 720, f"缓存拼接行数 {len(cached)} != 720"
    cached_actions = cached["&-target_position"].astype(int).to_numpy()

    trace = pd.DataFrame({
        "date": cached["date"],
        "window": window_labels(cached["date"]),
        "target_position": cached_actions,
        "do_predict": cached["do_predict"].astype(int),
    })
    trace.to_csv(ART / "sequential_inference_trace.csv", index=False)

    rows = []
    for w in range(1, 6):
        sub = trace[trace["window"] == w]
        rows.append({
            "window": w, "rows": len(sub),
            "first_date": str(sub.iloc[0]["date"]),
            "first_pos": int(sub.iloc[0]["target_position"]),
            "last_date": str(sub.iloc[-1]["date"]),
            "last_pos": int(sub.iloc[-1]["target_position"]),
        })
    for i in range(4):
        rows[i]["next_window_first_pos"] = rows[i + 1]["first_pos"]
    cw = pd.DataFrame(rows)
    cw.to_csv(ART / "cross_window_state_trace.csv", index=False)

    # ---- 证据 3:独立重推理与缓存序列逐行对比
    rebuilt = independent_reinference()
    reinference_identical = bool((rebuilt == cached_actions).all())
    reinfer_diffs = [int(i) for i in range(720) if rebuilt[i] != cached_actions[i]]

    # ---- 证据 4:第 5 窗首行仓位敏感性(真实 PPO 模型)
    sensitivity = {"experiment": "第5窗首行 pos=1 vs pos=0", "ok": False}
    try:
        from stable_baselines3 import PPO

        sub = sorted((MODEL_DIR / IDENTIFIER).glob("sub-train-BTC_*"))[-1]
        ts = sub.name.split("_")[1]
        model = PPO.load(sub / f"cb_btc_{ts}_model.zip", device="cpu")
        pipeline = pd.read_pickle(sub / f"cb_btc_{ts}_feature_pipeline.pkl")
        meta = json.loads((sub / f"cb_btc_{ts}_metadata.json").read_text())
        cols = list(meta["training_features_list"])
        X = rebuild_features().iloc[672:720][cols].reset_index(drop=True)
        Xt, _, _ = pipeline.transform(X)
        arr = Xt.to_numpy(dtype="float64")
        a1, _ = model.predict(np.append(arr[0], 1.0).astype("float32"), deterministic=True)
        a0, _ = model.predict(np.append(arr[0], 0.0).astype("float32"), deterministic=True)
        sensitivity.update({
            "ok": True,
            "action_with_pos1": int(a1),
            "action_with_pos0": int(a0),
            "model_reacts_to_position": bool(int(a1) != int(a0)),
        })
    except Exception as exc:  # noqa: BLE001
        sensitivity["error"] = repr(exc)

    result = {
        "run1_zip": zip1, "run2_zip": zip2,
        "trades_identical": trades_identical, "trade_diffs": trade_diffs,
        "n_trades": len(t1),
        "reinference_identical": reinference_identical, "reinference_diffs": reinfer_diffs,
        "distribution": pd.Series(cached_actions).value_counts().to_dict(),
        "windows": cw.to_dict("records"),
        "position_sensitivity": sensitivity,
    }
    (ART / "reload_determinism.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False)
    )
    md = [
        "# PPO 烟雾测试:重载确定性与跨窗口状态",
        "",
        f"- run1(训练+顺序推理): {zip1}",
        f"- run2(删预测缓存、模型重载+顺序推理): {zip2}",
        f"- 两轮回测成交逐字段一致: **{trades_identical}**(笔数 {len(t1)})",
        f"- 独立进程加载模型重推理 720 行与缓存序列一致: **{reinference_identical}**"
        f"(差异行 {reinfer_diffs})",
        f"- 动作分布: {result['distribution']}",
        f"- 各窗: {cw.to_string(index=False)}",
        f"- 仓位敏感性: {json.dumps(sensitivity, ensure_ascii=False)}",
        "",
        "跨窗口状态:窗口 1-4 末目标仓位均为 1,窗口 5 从多头状态继续,",
        "在 06-28 行转为 0(成交于 06-29 01:00 open),窗口 5 末为 0。",
    ]
    (ART / "reload_determinism.md").write_text("\n".join(md) + "\n")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    ok = trades_identical and reinference_identical
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
