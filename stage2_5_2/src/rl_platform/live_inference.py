"""Dry-run / live 心跳推理(阶段 2.5.1 工作包 G,阶段 2.5.2 工作包 A/B 加固)。

FreqAI 首次 live 调用会传入整段历史 dataframe(数百行),之后每个 heartbeat
只传入最新 CONV_WIDTH 行。两种调用严格分离:

历史回填调用(len > window_size):
- 用隔离的临时 SequentialPositionPredictor(初始空仓)生成历史目标序列,
  仅供 UI 展示,不写入任何执行状态;
- 最新一行的实际目标:从 Trade/Order 持久层解析真实执行状态
  (execution_state.get_model_position_live),用真实仓位构造最新观察,
  只让最新一行决定当前交易目标。

增量 heartbeat(len == window_size,conv_width=1 时即单行):
- 每次都从 Trade/Order 重新解析真实执行状态(订单成交状态的唯一真值来源);
- 用最新特征 + 真实仓位构造观察并预测;
- 内存中的 _last_target_position 仅作为展示目标的延续,
  不得成为 live 实际仓位的来源(工作包 G)。

阶段 2.5.2 fail-closed 语义(工作包 A 五节):
- read_position_fn 抛 InconsistentExecutionStateError 时,最新行不调用模型,
  目标沿用 fallback(展示用途);trace 标记 fail_closed=True,信号层
  (signal_convert.latest_row_signals)同刻也不会生成任何订单。
- do_predict != 1 或观察含 NaN/Inf 的行同样不调用模型、不更新状态。
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import numpy as np
import pandas as pd

from rl_platform.execution_state import InconsistentExecutionStateError
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

    :param read_position_fn: 从 Freqtrade Trade/Order 持久层解析模型观察仓位
        的函数(生产路径为 execution_state.get_model_position_live,
        测试注入内存版)。抛 InconsistentExecutionStateError 时 fail closed。
    :param fallback_target: 最新行 do_predict 无效或状态无法解析时沿用的
        展示目标(None 表示按当前真实仓位)。
    """
    arr = dataframe.to_numpy(dtype=np.float64) if isinstance(dataframe, pd.DataFrame) \
        else np.asarray(dataframe, dtype=np.float64)
    n = len(arr)
    if do_predict is not None and len(do_predict) != n:
        raise ValueError(
            f"do_predict 长度 {len(do_predict)} 与 dataframe 行数 {n} 不一致"
        )
    fail_closed = False
    fail_closed_reason: str | None = None
    real_pos: int | None
    try:
        real_pos = int(read_position_fn(pair))
    except InconsistentExecutionStateError as exc:
        real_pos = None
        fail_closed = True
        fail_closed_reason = str(exc)
        logger.error("live 推理 fail closed(执行状态 INCONSISTENT):\n%s", exc)

    if n > window_size:
        # ---- 历史回填:隔离临时状态重放,不污染执行状态 ----
        iso = SequentialPositionPredictor(model, window_size=window_size)
        iso.current_position = 0
        actions = iso.predict_frame(dataframe, do_predict=do_predict)

        # ---- 最新一行:真实仓位观察 -> 实时目标 ----
        dp_ok = True if do_predict is None else int(do_predict[n - 1]) == 1
        if real_pos is None:
            latest_target = int(real_pos if fallback_target is None else fallback_target)
            actions[n - 1] = latest_target
        else:
            latest_obs = iso.build_observation(arr, n - 1, real_pos)
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
        dp_ok = True if do_predict is None else int(do_predict[n - 1]) == 1
        obs = None
        if real_pos is not None:
            obs = SequentialPositionPredictor.build_observation_static(
                arr, n - 1, real_pos, window_size
            ) if n == window_size else None
        if obs is not None and not fail_closed and dp_ok and _finite(obs):
            action, _ = model.predict(obs, deterministic=True)
            latest_target = int(action)
        else:
            base = real_pos if fallback_target is None else fallback_target
            latest_target = int(0 if base is None else base)
        actions[n - 1] = latest_target
        mode = "heartbeat"

    trace = {
        "mode": mode,
        "n_rows": n,
        "real_position": real_pos,
        "latest_target": int(actions[n - 1]),
        "do_predict_latest": None if do_predict is None else int(do_predict[n - 1]),
        "pair": pair,
        "fail_closed": fail_closed,
        "fail_closed_reason": fail_closed_reason,
    }
    logger.info(
        "RouteC live 推理: mode=%s rows=%s real_pos=%s latest_target=%s fail_closed=%s",
        mode, n, real_pos, trace["latest_target"], fail_closed,
    )
    return actions, trace
