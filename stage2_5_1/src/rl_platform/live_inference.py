"""Dry-run / live 心跳推理(阶段 2.5.1 工作包 G)。

FreqAI 首次 live 调用会传入整段历史 dataframe(数百行),之后每个 heartbeat
只传入最新 CONV_WIDTH 行。阶段 2.5 的实现把两种调用混在一起:顺序重放整段
历史后,用"重放末状态"覆盖当前真实仓位 —— 历史回填会污染实时执行状态。

本模块把两种状态分开:

历史回填调用(len > window_size):
- 用隔离的临时 SequentialPositionPredictor(初始空仓)生成历史目标序列,
  仅供 UI 展示,不写入任何执行状态;
- 最新一行的实际目标:重新从 Trade 表读取当前真实仓位,用真实仓位构造
  最新观察,只让最新一行决定当前交易目标。

增量 heartbeat(len == window_size,conv_width=1 时即单行):
- 每次都从 Trade 表重新读取真实仓位(订单成交状态的唯一真值来源);
- 用最新特征 + 真实仓位构造观察并预测;
- 内存中的 _last_target_position 仅用于跨 backtest 子窗口延续,
  不得成为 live 实际仓位的唯一来源。

do_predict mask 语义(工作包 F):
- do_predict != 1 或观察含 NaN/Inf 的行不调用模型,目标保持当前值,
  不更新顺序状态。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from rl_platform.inference import SequentialPositionPredictor

logger = logging.getLogger(__name__)


def _finite(x: np.ndarray) -> bool:
    return bool(np.isfinite(x).all())


def live_predict_frame(
    model: Any,
    dataframe: pd.DataFrame | np.ndarray,
    pair: str,
    window_size: int,
    read_position_fn: Callable[[str], int],
    do_predict: np.ndarray | list[int] | None = None,
    fallback_target: int | None = None,
) -> tuple[np.ndarray, dict[str, Any]]:
    """live 推理入口,返回 (目标仓位序列, trace)。

    :param read_position_fn: 从 Freqtrade Trade 持久层读取真实仓位的函数
        (生产路径为 dryrun_state.get_initial_position_live,测试注入内存版)。
    :param fallback_target: 最新行 do_predict 无效时沿用的目标
        (None 表示用真实仓位,即不产生信号差异)。
    """
    arr = dataframe.to_numpy(dtype=np.float64) if isinstance(dataframe, pd.DataFrame) \
        else np.asarray(dataframe, dtype=np.float64)
    n = len(arr)
    if do_predict is not None and len(do_predict) != n:
        raise ValueError(
            f"do_predict 长度 {len(do_predict)} 与 dataframe 行数 {n} 不一致"
        )
    real_pos = int(read_position_fn(pair))

    if n > window_size:
        # ---- 历史回填:隔离临时状态重放,不污染执行状态 ----
        iso = SequentialPositionPredictor(model, window_size=window_size)
        iso.current_position = 0
        actions = iso.predict_frame(dataframe, do_predict=do_predict)

        # ---- 最新一行:真实仓位观察 -> 实时目标 ----
        latest_obs = iso.build_observation(arr, n - 1, real_pos)
        dp_ok = True if do_predict is None else int(do_predict[n - 1]) == 1
        if dp_ok and _finite(latest_obs):
            action, _ = model.predict(latest_obs, deterministic=True)
            latest_target = int(action)
        else:
            latest_target = int(real_pos if fallback_target is None else fallback_target)
        actions[n - 1] = latest_target
        mode = "history_backfill"
    else:
        # ---- 增量 heartbeat:单行(= window_size)实时决策 ----
        actions = np.zeros(n, dtype=np.int64)
        obs = SequentialPositionPredictor.build_observation_static(
            arr, n - 1, real_pos, window_size
        ) if n == window_size else None
        dp_ok = True if do_predict is None else int(do_predict[n - 1]) == 1
        if obs is not None and dp_ok and _finite(obs):
            action, _ = model.predict(obs, deterministic=True)
            latest_target = int(action)
        else:
            latest_target = int(real_pos if fallback_target is None else fallback_target)
        actions[n - 1] = latest_target
        mode = "heartbeat"

    trace = {
        "mode": mode,
        "n_rows": n,
        "real_position": real_pos,
        "latest_target": int(actions[n - 1]),
        "do_predict_latest": None if do_predict is None else int(do_predict[n - 1]),
        "pair": pair,
    }
    logger.info(
        "RouteC live 推理: mode=%s rows=%s real_pos=%s latest_target=%s",
        mode, n, real_pos, trace["latest_target"],
    )
    return actions, trace
