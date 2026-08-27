"""工作包 E 测试:部分缓存防护(任务书十六至十八节)。

单元级:NONE/COMPLETE/PARTIAL/INCONSISTENT 分类、quarantine 修复、
fail-closed 中止、与真实 DataKitchen 窗口推导对拍。
集成级(硬性验收:真实 5 窗实验的部分缓存修复)在证据脚本
ppo_evidence.py 中执行(见 partial_cache_repair_trace.json)。
"""

import json
from pathlib import Path

import pandas as pd
import pytest

from rl_platform.cache_guard import (
    PartialCacheError,
    classify_cache_state,
    derive_expected_windows,
    enforce_cache_state,
    quarantine_predictions_dir,
)

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_1"
TR = "20260601-20260701"
PAIR = "BTC/USDT"


def make_windows():
    return derive_expected_windows(TR, 30, 7)


def window_rows(w: dict) -> int:
    """该窗实际 bar 数(1h,半开区间;末窗可能被截断)。"""
    return (w["bt_stopts"] - w["bt_startts"]) // 3600


def write_pred_file(pred_dir: Path, ts: int, rows: int):
    pred_dir.mkdir(parents=True, exist_ok=True)
    dates = pd.date_range("2026-06-01", periods=rows, freq="1h", tz="UTC")
    pd.DataFrame({
        "date": dates,
        "&-target_position": [0] * rows,
        "do_predict": [1] * rows,
    }).to_feather(pred_dir / f"cb_btc_{ts}_prediction.feather")


def write_all(pred_dir: Path, ws: list):
    for w in ws:
        write_pred_file(pred_dir, w["timestamp_model_id"], window_rows(w))


# ---------------------------------------------------------------- 窗口推导
def test_expected_windows_not_hardcoded():
    """窗口数从 timerange 推导,不写死 5。"""
    assert len(make_windows()) == 5  # 30 天评估 / 7 天窗(末窗截断到 2 天)
    assert [window_rows(w) for w in make_windows()] == [168, 168, 168, 168, 48]
    assert len(derive_expected_windows("20260601-20260615", 30, 7)) == 2  # 14 天整除
    assert len(derive_expected_windows("20260601-20260616", 30, 7)) == 3  # 15 天末窗截断
    assert len(derive_expected_windows("20260601-20260608", 30, 7)) == 1  # 7 天单窗
    assert len(derive_expected_windows("20260601-20260602", 30, 7)) == 1  # 截断单窗


def test_windows_match_real_data_kitchen(tmp_path):
    """与真实 FreqaiDataKitchen.split_timerange 对拍(上游同一算法)。"""
    from freqtrade.freqai.data_kitchen import FreqaiDataKitchen

    conf = {
        "timerange": TR,
        "user_data_dir": tmp_path,
        "config_files": [tmp_path / "config.json"],
        "exchange": {"pair_whitelist": [PAIR]},
        "freqai": {"train_period_days": 30, "backtest_period_days": 7,
                   "identifier": "unittest",
                   "feature_parameters": {"include_corr_pairlist": []}},
    }
    (tmp_path / "config.json").write_text("{}")
    dk = FreqaiDataKitchen(conf)
    mine = make_windows()
    assert len(mine) == len(dk.backtesting_timeranges)
    for mine_w, up_bt, up_tr in zip(
        mine, dk.backtesting_timeranges, dk.training_timeranges, strict=True
    ):
        assert mine_w["bt_startts"] == up_bt.startts
        assert mine_w["bt_stopts"] == up_bt.stopts
        assert mine_w["train_startts"] == up_tr.startts
        assert mine_w["train_stopts"] == up_tr.stopts
        assert mine_w["timestamp_model_id"] == up_tr.stopts


# ---------------------------------------------------------------- 状态分类
def test_classify_none(tmp_path):
    r = classify_cache_state(tmp_path / "backtesting_predictions", make_windows(), PAIR)
    assert r.state == "NONE"


def test_classify_complete(tmp_path):
    pred = tmp_path / "backtesting_predictions"
    write_all(pred, make_windows())
    r = classify_cache_state(pred, make_windows(), PAIR)
    assert r.state == "COMPLETE", r.describe()


def test_classify_partial_windows_1_and_3(tmp_path):
    """任务书十八节:5 个窗口只保留窗口 1 和 3。"""
    pred = tmp_path / "backtesting_predictions"
    ws = make_windows()
    write_pred_file(pred, ws[0]["timestamp_model_id"], window_rows(ws[0]))
    write_pred_file(pred, ws[2]["timestamp_model_id"], window_rows(ws[2]))
    r = classify_cache_state(pred, make_windows(), PAIR)
    assert r.state == "PARTIAL"
    assert len(r.missing_files) == 3  # 窗 2/4/5 缺失
    assert r.extra_files == []


def test_classify_inconsistent_extra_file(tmp_path):
    pred = tmp_path / "backtesting_predictions"
    write_all(pred, make_windows())
    write_pred_file(pred, 1999999999, 168)  # 多余文件
    r = classify_cache_state(pred, make_windows(), PAIR)
    assert r.state == "INCONSISTENT"
    assert r.extra_files == ["cb_btc_1999999999_prediction.feather"]


def test_classify_inconsistent_row_count(tmp_path):
    pred = tmp_path / "backtesting_predictions"
    ws = make_windows()
    for i, w in enumerate(ws):
        rows = 100 if i == 1 else window_rows(w)  # 窗 2 行数错误
        write_pred_file(pred, w["timestamp_model_id"], rows)
    r = classify_cache_state(pred, make_windows(), PAIR)
    assert r.state == "INCONSISTENT"


# ---------------------------------------------------------------- fail closed
def test_enforce_fail_closed_and_cache_untouched(tmp_path):
    """无修复参数:启动前失败,旧缓存未被修改。"""
    pred = tmp_path / "backtesting_predictions"
    ws = make_windows()
    write_pred_file(pred, ws[0]["timestamp_model_id"], window_rows(ws[0]))
    write_pred_file(pred, ws[2]["timestamp_model_id"], window_rows(ws[2]))
    before = sorted(p.name for p in pred.glob("*.feather"))
    with pytest.raises(PartialCacheError, match="PARTIAL"):
        enforce_cache_state(pred, make_windows(), PAIR)
    after = sorted(p.name for p in pred.glob("*.feather"))
    assert before == after  # 未被修改
    assert pred.is_dir()  # 未被删除/移动


def test_enforce_none_and_complete_pass(tmp_path):
    r, q = enforce_cache_state(tmp_path / "backtesting_predictions", make_windows(), PAIR)
    assert r.state == "NONE" and q is None
    pred = tmp_path / "backtesting_predictions"
    write_all(pred, make_windows())
    r2, q2 = enforce_cache_state(pred, make_windows(), PAIR)
    assert r2.state == "COMPLETE" and q2 is None
    assert pred.is_dir()  # COMPLETE 不移动任何文件


# ---------------------------------------------------------------- 修复(quarantine)
def test_repair_quarantines_whole_dir(tmp_path):
    pred = tmp_path / "backtesting_predictions"
    ws = make_windows()
    keep = [ws[0], ws[2]]
    for w in keep:
        write_pred_file(pred, w["timestamp_model_id"], window_rows(w))
    snapshot = {p.name: p.read_bytes() for p in pred.glob("*.feather")}

    r, quarantine = enforce_cache_state(pred, make_windows(), PAIR, repair=True)
    assert r.state == "PARTIAL"
    assert quarantine is not None and quarantine.is_dir()
    assert not pred.exists()  # 原目录整体移走
    # quarantine 内文件内容与原来逐字节一致(不删除、不修改)
    restored = {p.name: p.read_bytes() for p in quarantine.glob("*.feather")}
    assert restored == snapshot
    # 说明文件存在
    assert list(quarantine.parent.glob(f"{quarantine.name}.txt"))
    # 修复后再次检查:状态回到 NONE(缓存目录已空)
    r2, _ = enforce_cache_state(pred, make_windows(), PAIR)
    assert r2.state == "NONE"


def test_quarantine_keeps_model_dirs(tmp_path):
    """quarantine 只动 backtesting_predictions,兄弟模型目录保留。"""
    models = tmp_path
    pred = models / "backtesting_predictions"
    sub = models / "sub-train-BTC_123"
    sub.mkdir(parents=True)
    (sub / "model.pkl").write_text("trained-model")
    write_pred_file(pred, 123, 168)
    q = quarantine_predictions_dir(pred)
    assert (sub / "model.pkl").exists()
    assert q.name.startswith("backtesting_predictions_quarantine_")


def test_partial_cache_guard_evidence(tmp_path):
    ART.mkdir(parents=True, exist_ok=True)
    pred = tmp_path / "backtesting_predictions"
    ws = make_windows()
    write_pred_file(pred, ws[0]["timestamp_model_id"], window_rows(ws[0]))
    write_pred_file(pred, ws[2]["timestamp_model_id"], window_rows(ws[2]))
    r = classify_cache_state(pred, make_windows(), PAIR)
    (ART / "partial_cache_guard_unit.json").write_text(json.dumps({
        "timerange": TR,
        "expected_files": sorted(r.expected_files),
        "actual_files": sorted(r.actual_files),
        "missing": r.missing_files,
        "state": r.state,
        "fail_closed": "是(单元级,集成级见 partial_cache_repair_trace.json)",
    }, indent=2, ensure_ascii=False))
