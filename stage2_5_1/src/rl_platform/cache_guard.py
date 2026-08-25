"""FreqAI 回测预测缓存完整性守卫(阶段 2.5.1 工作包 E)。

上一阶段审计发现 FreqAI 缓存校验只按"文件名 + 行数"判定
(check_if_backtest_prediction_is_valid)。如果某个 identifier 的
backtesting_predictions 目录只残留部分窗口的缓存,FreqAI 会让前几个窗口
命中缓存、后几个窗口重新推理 —— 而顺序推理的跨窗口目标仓位状态在
"命中缓存"的窗口不会推进(那几个窗口根本不调用 rl_model_predict),
导致新推理窗口从错误仓位开始,状态被静默污染。

本模块在实验启动前对缓存做 fail-closed 检查:

    NONE          没有任何窗口缓存(全新实验,正常)
    COMPLETE      预期窗口缓存全部存在且行数一致(全部复用,正常)
    PARTIAL       只存在部分预期窗口
    INCONSISTENT  存在多余文件,或文件行数与窗口 bar 数不符

PARTIAL / INCONSISTENT 默认中止实验;显式 --repair-partial-cache 时把整个
backtesting_predictions 目录移动到带时间戳的 quarantine 目录(不删除),
保留已训练模型,全部窗口重新顺序推理。

预期窗口集合从 timerange 与 FreqAI 窗口配置推导(复刻上游
data_kitchen.create_fulltimerange + split_timerange 的整数秒算法,
并用真实 DataKitchen 对拍测试验证一致),不写死窗口数。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SECONDS_IN_DAY = 86400


class PartialCacheError(RuntimeError):
    """缓存状态为 PARTIAL / INCONSISTENT 时的启动前中止错误。"""


@dataclass
class CacheCheckResult:
    state: str  # NONE / COMPLETE / PARTIAL / INCONSISTENT
    expected_files: set[str] = field(default_factory=set)
    actual_files: set[str] = field(default_factory=set)
    missing_files: list[str] = field(default_factory=list)
    extra_files: list[str] = field(default_factory=list)
    row_counts: dict[str, int] = field(default_factory=dict)  # 实际行数(存在的文件)

    def describe(self) -> str:
        lines = [f"缓存状态: {self.state}"]
        lines.append(f"预期文件({len(self.expected_files)}): {sorted(self.expected_files)}")
        lines.append(f"实际文件({len(self.actual_files)}): {sorted(self.actual_files)}")
        if self.missing_files:
            lines.append(f"缺失: {sorted(self.missing_files)}")
        if self.extra_files:
            lines.append(f"多余: {sorted(self.extra_files)}")
        if self.row_counts:
            lines.append(f"实际行数: {self.row_counts}")
        return "\n".join(lines)


def derive_expected_windows(
    timerange: str, train_period_days: int, backtest_period_days: int
) -> list[dict[str, int]]:
    """复刻上游窗口推进算法,返回每窗 train/bt 起止 epoch 秒与缓存文件名时间戳。

    与 data_kitchen.split_timerange 的整数秒逻辑逐行对齐:
    full 起点 = config 起点前移 train_period_days;每窗 train = [start, start+train),
    bt = [train_stop, train_stop+bt) 截断到 config 终点;start += bt;bt 终点
    触及 config 终点时停止。timestamp_model_id = int(train.stopts)。
    """
    import re

    m = re.match(r"^(\d{8})-(\d{8})$", timerange.strip())
    if not m:
        raise ValueError(f"timerange 必须是 YYYYMMDD-YYYYMMDD,收到 {timerange!r}")
    start_ts = int(
        datetime.strptime(m.group(1), "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
    )
    config_stop = int(
        datetime.strptime(m.group(2), "%Y%m%d").replace(tzinfo=timezone.utc).timestamp()
    )
    if config_stop <= start_ts:
        raise ValueError(f"timerange 终点必须晚于起点: {timerange}")

    train_period = int(train_period_days) * SECONDS_IN_DAY
    bt_period = int(backtest_period_days) * SECONDS_IN_DAY
    windows: list[dict[str, int]] = []
    cursor = start_ts - train_period  # full_timerange 起点
    while True:
        train_start = cursor
        train_stop = train_start + train_period
        bt_start = train_stop
        bt_stop = min(bt_start + bt_period, config_stop)
        windows.append({
            "train_startts": train_start,
            "train_stopts": train_stop,
            "bt_startts": bt_start,
            "bt_stopts": bt_stop,
            "timestamp_model_id": train_stop,
        })
        if bt_stop >= config_stop:
            break
        cursor += bt_period
    return windows


def expected_cache_filenames(windows: list[dict[str, int]], pair: str) -> set[str]:
    coin = pair.split("/")[0]
    return {
        f"cb_{coin.lower()}_{w['timestamp_model_id']}_prediction.feather"
        for w in windows
    }


def expected_rows_per_window(
    windows: list[dict[str, int]], timeframe_secs: int
) -> dict[str, int]:
    """每个预期缓存文件的窗口 bar 数(半开区间换算)。"""
    return {
        f"w{i+1}": (w["bt_stopts"] - w["bt_startts"]) // timeframe_secs
        for i, w in enumerate(windows)
    }


def classify_cache_state(
    predictions_dir: str | Path,
    windows: list[dict[str, int]],
    pair: str,
    timeframe_secs: int = 3600,
) -> CacheCheckResult:
    """检查缓存目录,判定 NONE / COMPLETE / PARTIAL / INCONSISTENT。"""
    pred_dir = Path(predictions_dir)
    expected = expected_cache_filenames(windows, pair)
    actual = {p.name for p in pred_dir.glob("*.feather")} if pred_dir.is_dir() else set()

    result = CacheCheckResult(state="NONE", expected_files=expected, actual_files=actual)
    if not actual:
        return result

    import pandas as pd

    row_counts: dict[str, int] = {}
    for name in sorted(actual):
        row_counts[name] = len(pd.read_feather(pred_dir / name))
    result.row_counts = row_counts

    expected_rows = expected_rows_per_window(windows, timeframe_secs)
    ordered_expected = sorted(
        expected, key=lambda n: int(n.split("_")[-2])
    )  # cb_<coin>_<ts>_prediction.feather
    ordered_rows = [expected_rows[f"w{i+1}"] for i in range(len(ordered_expected))]

    result.missing_files = sorted(expected - actual)
    result.extra_files = sorted(actual - expected)
    rows_mismatch = [
        (name, row_counts[name], want)
        for name, want in zip(ordered_expected, ordered_rows, strict=True)
        if name in row_counts and row_counts[name] != want
    ]

    if result.extra_files or rows_mismatch:
        result.state = "INCONSISTENT"
    elif result.missing_files:
        result.state = "PARTIAL"
    else:
        result.state = "COMPLETE"
    return result


def enforce_cache_state(
    predictions_dir: str | Path,
    windows: list[dict[str, int]],
    pair: str,
    timeframe_secs: int = 3600,
    repair: bool = False,
) -> tuple[CacheCheckResult, Path | None]:
    """单一入口:NONE/COMPLETE 直接放行;PARTIAL/INCONSISTENT 默认抛错中止,
    repair=True 时整体 quarantine 后返回 (result, quarantine 路径)。"""
    result = classify_cache_state(predictions_dir, windows, pair, timeframe_secs)
    if result.state in ("NONE", "COMPLETE"):
        return result, None
    if not repair:
        raise PartialCacheError(
            f"预测缓存状态为 {result.state},实验中止(fail closed)。\n"
            f"{result.describe()}\n"
            "如需修复,请加 --repair-partial-cache(整体 quarantine 后全窗口重推理)。"
        )
    quarantine = quarantine_predictions_dir(predictions_dir)
    return result, quarantine


def quarantine_predictions_dir(predictions_dir: str | Path) -> Path:
    """把整个缓存目录改名进 quarantine(同文件系统原子 rename,不删除)。"""
    pred_dir = Path(predictions_dir)
    if not pred_dir.is_dir():
        raise FileNotFoundError(f"缓存目录不存在: {pred_dir}")
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    quarantine = pred_dir.parent / f"{pred_dir.name}_quarantine_{ts}"
    pred_dir.rename(quarantine)
    # 保留一份说明文件,记录 quarantine 来源(目录内文件未做任何修改)
    (quarantine.parent / f"{quarantine.name}.txt").write_text(
        f"quarantined_at_utc: {ts}\n"
        f"source_dir_name: {pred_dir.name}\n"
        "reason: partial/inconsistent backtesting_predictions; "
        "repair mode moves the whole directory aside and re-predicts all windows.\n",
        encoding="utf-8",
    )
    return quarantine


__all__ = [
    "CacheCheckResult",
    "PartialCacheError",
    "SECONDS_IN_DAY",
    "classify_cache_state",
    "derive_expected_windows",
    "enforce_cache_state",
    "expected_cache_filenames",
    "expected_rows_per_window",
    "quarantine_predictions_dir",
]
