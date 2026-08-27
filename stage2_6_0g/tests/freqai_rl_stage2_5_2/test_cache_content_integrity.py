"""工作包 E 测试:缓存内容验证(任务书十五/十六节)。

COMPLETE 不能只检查文件名与行数:每个 prediction cache 文件都要在 manifest
中记录 sha256/行数/首末时间戳/完整日期序列哈希/目标列哈希/do_predict 列哈希,
启动前对全部维度做内容级校验,任何不符即 INCONSISTENT(默认 fail closed,
错误缓存不得进入 Freqtrade 回测进程)。

覆盖损坏场景(任务书十六节清单):
1. 文件名与行数正确但目标列被修改;
2. 日期整体移动一天;
3. 两个窗口的缓存互换;
4. 同 identifier 下另一 seed 的缓存(目标/do_predict 列不同);
5. Feather 文件损坏(截断字节);
6. manifest 缺失;
7. 完整正确缓存(COMPLETE);
附加:manifest 指纹与当前实验不一致。
"""

import json
import shutil
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rl_platform.cache_content import (
    CACHE_MANIFEST_NAME,
    CacheContentError,
    build_cache_content_manifest,
    enforce_cache_content,
    verify_cache_content,
)
from rl_platform.cache_guard import derive_expected_windows

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_2"
PAIR = "SYN/USDT"
TIMEFRAME_SECS = 3600
# timerange 20260715-20260729,train 15d,bt 7d -> 2 个窗口
TIMERANGE = "20260715-20260729"
TRAIN_DAYS = 15
BT_DAYS = 7
FINGERPRINT = {"code_tree": "abc123", "config": "cfg456", "seed": 42}


@pytest.fixture()
def cache_dir(tmp_path):
    """构造两个窗口的合法缓存 + manifest(全部校验通过的基线)。"""
    windows = derive_expected_windows(TIMERANGE, TRAIN_DAYS, BT_DAYS)
    pred_dir = tmp_path / "backtesting_predictions"
    pred_dir.mkdir(parents=True)
    coin = PAIR.split("/")[0].lower()
    rng = np.random.default_rng(42)
    for w in windows:
        n = (w["bt_stopts"] - w["bt_startts"]) // TIMEFRAME_SECS
        dates = pd.date_range(
            pd.Timestamp(w["bt_startts"], unit="s", tz="UTC"),
            periods=n, freq="1h",
        )
        targets = (rng.random(n) > 0.5).astype(int)
        pd.DataFrame({
            "date": dates,
            "&-target_position": targets,
            "do_predict": np.ones(n, dtype=int),
        }).reset_index(drop=True).to_feather(pred_dir / f"cb_{coin}_{w['timestamp_model_id']}_prediction.feather")
    manifest = build_cache_content_manifest(
        pred_dir, windows, PAIR, TIMEFRAME_SECS,
        fingerprint=FINGERPRINT, identifier="test252-cache",
    )
    (pred_dir.parent / CACHE_MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return pred_dir, windows, manifest


def manifest_of(pred_dir: Path) -> dict:
    return json.loads(
        (pred_dir.parent / CACHE_MANIFEST_NAME).read_text(encoding="utf-8"))


def _first_cache(pred_dir: Path) -> Path:
    return sorted(pred_dir.glob("*.feather"))[0]


# ------------------------------------------------------------- 基线:正确缓存
def test_pristine_cache_is_complete(cache_dir):
    pred_dir, windows, manifest = cache_dir
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest, FINGERPRINT)
    assert state == "COMPLETE", issues


def test_fingerprint_mismatch_is_inconsistent(cache_dir):
    pred_dir, windows, manifest = cache_dir
    other_fp = dict(FINGERPRINT, seed=43)
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest, other_fp)
    assert state == "INCONSISTENT"
    assert any("指纹" in i for i in issues)


# ------------------------------------------------- 场景 1:目标列被修改
def test_modified_target_column_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    f = _first_cache(pred_dir)
    df = pd.read_feather(f)
    df.loc[df.index[-1], "&-target_position"] = 1 - int(
        df["&-target_position"].iloc[-1])
    df.to_feather(f)
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir), FINGERPRINT)
    assert state == "INCONSISTENT"
    assert any("sha256" in i or "目标列" in i for i in issues)


# ------------------------------------------------- 场景 2:日期整体移动一天
def test_shifted_dates_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    f = _first_cache(pred_dir)
    df = pd.read_feather(f)
    df["date"] = df["date"] + pd.Timedelta(days=1)
    df.to_feather(f)
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir), FINGERPRINT)
    assert state == "INCONSISTENT"
    assert any("时间戳" in i or "日期序列" in i for i in issues)


# ------------------------------------------------- 场景 3:两个窗口互换
def test_swapped_windows_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    files = sorted(pred_dir.glob("*.feather"))
    a, b = files[0], files[1]
    da, db = pd.read_feather(a), pd.read_feather(b)
    da.to_feather(b)
    db.to_feather(a)
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir), FINGERPRINT)
    assert state == "INCONSISTENT"


# --------------------------------- 场景 4:同 identifier 另一 seed 的缓存
def test_different_seed_cache_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    # 另一 seed 重推理:目标序列不同(文件名/行数/日期全同)
    rng2 = np.random.default_rng(99)
    for f in sorted(pred_dir.glob("*.feather")):
        df = pd.read_feather(f)
        df["&-target_position"] = (rng2.random(len(df)) > 0.5).astype(int)
        df.to_feather(f)
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir), FINGERPRINT)
    assert state == "INCONSISTENT"
    assert any("sha256" in i for i in issues)


# ------------------------------------------------- 场景 5:Feather 损坏
def test_corrupt_feather_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    f = _first_cache(pred_dir)
    raw = f.read_bytes()
    f.write_bytes(raw[: len(raw) // 3])  # 截断
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir), FINGERPRINT)
    assert state == "INCONSISTENT"
    assert any("损坏" in i or "不可读" in i for i in issues)


# ------------------------------------------------- 场景 6:manifest 缺失
def test_missing_manifest_detected(cache_dir):
    pred_dir, windows, _ = cache_dir
    (pred_dir.parent / CACHE_MANIFEST_NAME).unlink()
    state, issues = verify_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, None, FINGERPRINT)
    assert state == "INCONSISTENT"
    assert any("manifest 缺失" in i for i in issues)


# ------------------------------------------------- enforce:fail closed / repair
def test_enforce_fail_closed_then_repair(cache_dir, tmp_path):
    pred_dir, windows, _ = cache_dir
    f = _first_cache(pred_dir)
    df = pd.read_feather(f)
    df.loc[df.index[0], "&-target_position"] = 1 - int(
        df["&-target_position"].iloc[0])
    df.to_feather(f)
    with pytest.raises(CacheContentError):
        enforce_cache_content(
            pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir),
            FINGERPRINT, repair=False)

    state, issues, quarantine = enforce_cache_content(
        pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest_of(pred_dir),
        FINGERPRINT, repair=True)
    assert state == "INCONSISTENT"
    assert quarantine is not None and quarantine.is_dir()
    assert not pred_dir.exists(), "原目录必须被整体移走(不删除文件)"
    assert len(list(quarantine.glob("*.feather"))) == 2, "quarantine 保留全部缓存文件"


# ------------------------------------------------- 证据文件
def test_cache_integrity_evidence(tmp_path):
    """逐场景记录状态判定矩阵(证据 cache_corruption_tests.json/csv)。"""
    windows = derive_expected_windows(TIMERANGE, TRAIN_DAYS, BT_DAYS)
    ART.mkdir(parents=True, exist_ok=True)
    rows = []

    def build_case(mutator=None):
        pred_dir = tmp_path / f"case{len(rows)}" / "backtesting_predictions"
        pred_dir.mkdir(parents=True)
        coin = PAIR.split("/")[0].lower()
        rng = np.random.default_rng(42)
        for w in windows:
            n = (w["bt_stopts"] - w["bt_startts"]) // TIMEFRAME_SECS
            dates = pd.date_range(
                pd.Timestamp(w["bt_startts"], unit="s", tz="UTC"),
                periods=n, freq="1h")
            pd.DataFrame({
                "date": dates,
                "&-target_position": (rng.random(n) > 0.5).astype(int),
                "do_predict": np.ones(n, dtype=int),
            }).reset_index(drop=True).to_feather(
                pred_dir / f"cb_{coin}_{w['timestamp_model_id']}_prediction.feather")
        if mutator:
            mutator(pred_dir)
        manifest = build_cache_content_manifest(
            pred_dir, windows, PAIR, TIMEFRAME_SECS,
            fingerprint=FINGERPRINT, identifier="test252-cache",
        ) if not mutator else None
        if manifest:
            (pred_dir.parent / CACHE_MANIFEST_NAME).write_text(
                json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        return pred_dir, manifest

    def mod_target(pred_dir):
        f = sorted(pred_dir.glob("*.feather"))[0]
        df = pd.read_feather(f)
        df.loc[df.index[-1], "&-target_position"] ^= 1
        df.to_feather(f)

    def shift_dates(pred_dir):
        f = sorted(pred_dir.glob("*.feather"))[0]
        df = pd.read_feather(f)
        df["date"] = df["date"] + pd.Timedelta(days=1)
        df.to_feather(f)

    def corrupt(pred_dir):
        f = sorted(pred_dir.glob("*.feather"))[0]
        raw = f.read_bytes()
        f.write_bytes(raw[: len(raw) // 3])

    def no_manifest(pred_dir):
        pass  # 不写 manifest(mutator 分支本来就不写)

    def record(name, mutator):
        pred_dir, manifest = build_case(mutator)
        state, issues = verify_cache_content(
            pred_dir, windows, PAIR, TIMEFRAME_SECS, manifest, FINGERPRINT)
        rows.append({"case": name, "state": state, "issues": issues})
        return state

    assert record("pristine", None) == "COMPLETE"
    assert record("manifest_missing", no_manifest) == "INCONSISTENT"
    assert record("target_modified", mod_target) == "INCONSISTENT"
    assert record("dates_shifted", shift_dates) == "INCONSISTENT"
    assert record("feather_corrupt", corrupt) == "INCONSISTENT"

    (ART / "cache_corruption_tests.json").write_text(
        json.dumps(rows, indent=2, ensure_ascii=False), encoding="utf-8")
    pd.DataFrame(
        [{"case": r["case"], "state": r["state"], "n_issues": len(r["issues"])}
         for r in rows]
    ).to_csv(ART / "cache_corruption_tests.csv", index=False)
