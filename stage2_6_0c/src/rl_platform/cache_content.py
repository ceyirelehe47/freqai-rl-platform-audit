"""FreqAI 回测预测缓存内容验证(阶段 2.5.2 工作包 E)。

阶段 2.5.1 的 cache_guard 只按「文件名 + 行数」判定 COMPLETE
(与上游 check_if_backtest_prediction_is_valid 同粒度)。同名同长度但
内容来自另一实验、日期整体移动、中间日期顺序变化、目标列或 do_predict
被修改、manifest 缺失/指纹不符的缓存都会静默进入回测进程。

本模块对每个 prediction cache 文件生成并校验内容清单:

    文件名 / SHA-256 / 行数 / 首末时间戳 / 完整 date 序列哈希 /
    目标列哈希 / do_predict 列哈希 / 规范化内容哈希 / 对应窗口

COMPLETE 的内容级判据(全部满足):
    文件集合正确;行数正确;日期范围正确;完整日期序列正确
    (与窗口理论序列和 manifest 双核对);文件与规范化内容哈希正确;
    manifest 存在且 identifier / fingerprint 与当前实验一致。

任何一项不符即 INCONSISTENT(默认 fail closed,错误缓存不得进入
Freqtrade 回测进程);--repair 时整体 quarantine(移动不删除)。
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from rl_platform.cache_guard import (
    CacheCheckResult,
    classify_cache_state,
    expected_cache_filenames,
    quarantine_predictions_dir,
)

SECONDS_IN_DAY = 86400
CACHE_MANIFEST_NAME = "cache_content_manifest.json"
TARGET_COL = "&-target_position"
DO_PREDICT_COL = "do_predict"


class CacheContentError(RuntimeError):
    """缓存内容校验 INCONSISTENT 时的启动前中止错误(fail closed)。"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_text(text: str) -> str:
    return _sha256_bytes(text.encode("utf-8"))


def _ts_to_window(windows: list[dict[str, int]]) -> dict[int, dict[str, int]]:
    return {w["timestamp_model_id"]: w for w in windows}


def file_content_entry(path: Path, window: dict[str, int], timeframe_secs: int) -> dict:
    """单个缓存文件的内容清单条目(不做判定,只采集事实)。"""
    import pandas as pd

    df = pd.read_feather(path)
    if "date" not in df.columns:
        raise CacheContentError(f"{path.name} 缺少 date 列")
    dates = pd.to_datetime(df["date"], utc=True)
    parts = [str(int(d.timestamp())) for d in dates]
    target_vals = (
        [str(int(v)) for v in df[TARGET_COL].astype(int).tolist()]
        if TARGET_COL in df.columns else []
    )
    dp_vals = (
        [str(int(v)) for v in df[DO_PREDICT_COL].astype(int).tolist()]
        if DO_PREDICT_COL in df.columns else []
    )
    content_vals = [
        f"{a}:{b}:{c}"
        for a, b, c in zip(parts, target_vals, dp_vals, strict=True)
    ]
    return {
        "filename": path.name,
        "rows": int(len(df)),
        "first_date": dates.iloc[0].isoformat() if len(df) else None,
        "last_date": dates.iloc[-1].isoformat() if len(df) else None,
        "date_sequence_sha256": _sha256_text(",".join(parts)),
        "target_column_sha256": _sha256_text(",".join(target_vals)),
        "do_predict_column_sha256": _sha256_text(",".join(dp_vals)),
        "content_sha256": _sha256_text(",".join(content_vals)),
        "file_sha256": _sha256_bytes(path.read_bytes()),
        "window": {
            "bt_startts": window["bt_startts"],
            "bt_stopts": window["bt_stopts"],
            "timestamp_model_id": window["timestamp_model_id"],
        },
        "expected_first_date_epoch": window["bt_startts"],
        "expected_last_date_epoch": window["bt_stopts"] - timeframe_secs,
    }


def expected_date_sequence_sha256(window: dict[str, int], timeframe_secs: int) -> str:
    """按窗口理论等间隔序列(半开区间)计算的日期序列哈希。"""
    n = (window["bt_stopts"] - window["bt_startts"]) // timeframe_secs
    return _sha256_text(
        ",".join(str(window["bt_startts"] + i * timeframe_secs) for i in range(n))
    )


def build_cache_content_manifest(
    predictions_dir: str | Path,
    windows: list[dict[str, int]],
    pair: str,
    timeframe_secs: int = 3600,
    fingerprint: dict | None = None,
    identifier: str | None = None,
) -> dict:
    """生成缓存内容清单(仅对名称/行数层 COMPLETE 的缓存调用)。"""
    pred_dir = Path(predictions_dir)
    base: CacheCheckResult = classify_cache_state(pred_dir, windows, pair, timeframe_secs)
    if base.state != "COMPLETE":
        raise CacheContentError(f"只对 COMPLETE 缓存生成内容清单,当前 {base.state}")
    expected = expected_cache_filenames(windows, pair)
    ts_to_window = _ts_to_window(windows)
    files = []
    for name in sorted(expected):
        ts = int(name.split("_")[-2])
        files.append(file_content_entry(pred_dir / name, ts_to_window[ts], timeframe_secs))
    return {
        "identifier": identifier,
        "fingerprint": fingerprint,
        "pair": pair,
        "timeframe_secs": int(timeframe_secs),
        "generated_utc": datetime.now(tz=timezone.utc).isoformat(),
        "files": files,
    }


def verify_cache_content(
    predictions_dir: str | Path,
    windows: list[dict[str, int]],
    pair: str,
    timeframe_secs: int,
    manifest: dict | None,
    fingerprint: dict | None = None,
) -> tuple[str, list[str]]:
    """内容级校验:返回 (COMPLETE/INCONSISTENT, 问题清单)。"""
    pred_dir = Path(predictions_dir)
    try:
        base: CacheCheckResult = classify_cache_state(
            pred_dir, windows, pair, timeframe_secs
        )
    except Exception as exc:  # noqa: BLE001 - feather 损坏等任何读取故障都 fail closed
        return "INCONSISTENT", [f"缓存文件不可读/损坏: {exc!r}"]
    if base.state == "NONE":
        return "NONE", []
    if base.state != "COMPLETE":
        return "INCONSISTENT", [f"名称/行数层已非 COMPLETE: {base.describe()}"]

    issues: list[str] = []
    if not manifest:
        return "INCONSISTENT", ["缓存内容 manifest 缺失(cache_content_manifest.json)"]
    if fingerprint is not None and manifest.get("fingerprint") != fingerprint:
        issues.append("manifest 指纹与当前实验指纹不一致")

    expected = expected_cache_filenames(windows, pair)
    manifest_files = {f.get("filename") for f in manifest.get("files", [])}
    if manifest_files != expected:
        issues.append(f"manifest 文件集合与预期不符: {sorted(manifest_files ^ expected)}")

    ts_to_window = _ts_to_window(windows)
    for f in manifest.get("files", []):
        name = f.get("filename")
        if name not in expected:
            continue
        path = pred_dir / name
        if not path.is_file():
            issues.append(f"{name}: 文件缺失")
            continue
        if _sha256_bytes(path.read_bytes()) != f.get("file_sha256"):
            issues.append(f"{name}: 文件 sha256 与 manifest 不符(内容被修改或调包)")
            # 不 continue:继续给出日期/列级诊断(损坏文件单独兜底)
        ts = int(name.split("_")[-2])
        window = ts_to_window[ts]
        try:
            entry = file_content_entry(path, window, timeframe_secs)
        except Exception as exc:  # noqa: BLE001 - 任何读取故障都归入 INCONSISTENT
            issues.append(f"{name}: 缓存文件不可读/损坏: {exc!r}")
            continue
        if entry["first_date"] != f.get("first_date") or entry["last_date"] != f.get("last_date"):
            issues.append(f"{name}: 首末时间戳与 manifest 不符(日期整体移动)")
        if entry["date_sequence_sha256"] != f.get("date_sequence_sha256"):
            issues.append(f"{name}: 日期序列哈希与 manifest 不符(中间日期顺序变化)")
        if entry["date_sequence_sha256"] != expected_date_sequence_sha256(window, timeframe_secs):
            issues.append(f"{name}: 日期序列与窗口理论序列不符")
        if entry["rows"] != f.get("rows"):
            issues.append(f"{name}: 行数与 manifest 不符")
        if entry["target_column_sha256"] != f.get("target_column_sha256"):
            issues.append(f"{name}: 目标列哈希与 manifest 不符(目标被修改)")
        if entry["do_predict_column_sha256"] != f.get("do_predict_column_sha256"):
            issues.append(f"{name}: do_predict 列哈希与 manifest 不符")
        if entry["content_sha256"] != f.get("content_sha256"):
            issues.append(f"{name}: 规范化内容哈希与 manifest 不符")
    if issues:
        return "INCONSISTENT", issues
    return "COMPLETE", []


def enforce_cache_content(
    predictions_dir: str | Path,
    windows: list[dict[str, int]],
    pair: str,
    timeframe_secs: int,
    manifest: dict | None,
    fingerprint: dict | None = None,
    repair: bool = False,
) -> tuple[str, list[str], Path | None]:
    """启动前内容校验入口:NONE/COMPLETE 放行;INCONSISTENT 默认抛错中止,
    repair=True 时整体 quarantine(移动不删除)后由调用方全窗重推理。"""
    state, issues = verify_cache_content(
        predictions_dir, windows, pair, timeframe_secs, manifest, fingerprint
    )
    if state in ("NONE", "COMPLETE"):
        return state, issues, None
    if not repair:
        raise CacheContentError(
            "缓存内容校验 INCONSISTENT,实验中止(fail closed)。问题清单:\n"
            + "\n".join(issues)
            + "\n如需修复,请加 --repair-partial-cache(quarantine 后全窗口重推理)。"
        )
    quarantine = quarantine_predictions_dir(predictions_dir)
    return state, issues, quarantine


__all__ = [
    "CACHE_MANIFEST_NAME",
    "CacheContentError",
    "build_cache_content_manifest",
    "enforce_cache_content",
    "expected_date_sequence_sha256",
    "file_content_entry",
    "verify_cache_content",
]
