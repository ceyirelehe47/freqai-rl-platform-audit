"""目标仓位 -> Freqtrade 信号转换(阶段 2.5 路线 C)。

模型预测列 &-target_position 表示目标仓位(0/1),不是开仓/退出命令。
策略层把目标状态变化转换为 enter_long / exit_long:

    上一目标 0 -> 当前目标 1: enter_long(写在 K 线 t)
    上一目标 1 -> 当前目标 0: exit_long(写在 K 线 t)
    0 -> 0 / 1 -> 1: 无信号

Freqtrade 回测引擎自身的 shift(1) 使信号在 open[t+1] 成交,
与环境在 open[t+1] 执行完全一致,本层不再额外 shift。
"""

from __future__ import annotations

import pandas as pd


def target_to_signals(df: pd.DataFrame, col: str = "&-target_position") -> pd.DataFrame:
    """在 df 上写入 enter_long / enter_tag / exit_long 列(就地修改并返回)。

    第一行的"上一目标"按 0(空仓)处理,与顺序推理器初始状态一致。
    """
    target = df[col].astype(int)
    prev = target.shift(1, fill_value=0).astype(int)

    enter = (target == 1) & (prev == 0)
    exit_ = (target == 0) & (prev == 1)

    df["enter_long"] = enter.astype(int)
    df.loc[enter, "enter_tag"] = "route_c_target"
    df["exit_long"] = exit_.astype(int)
    return df
