"""目标仓位 -> Freqtrade 信号转换(阶段 2.5.1 工作包 F 重设计)。

模型预测列 &-target_position 表示目标仓位(0/1),不是开仓/退出命令。
阶段 2.5 用 target.shift(1) 推断"上一目标"生成信号,存在两类问题:
- do_predict != 1 的行只被策略层事后过滤,目标序列本身可能已经变化
  ("无效预测行不能改变目标状态"被破坏);
- live 下不能依赖上一根预测目标判断订单是否已成交(订单可能未成交)。

阶段 2.5.1 改为明确的"有效目标 -> 信号"状态机:

    do_predict != 1
    -> 不生成信号,仓位状态不变

    空仓(模拟/真实)+ 有效目标 1 -> enter_long,仓位状态变 1
    多头(模拟/真实)+ 有效目标 0 -> exit_long, 仓位状态变 0
    目标与仓位状态相同           -> 无信号

- Backtesting:initial_position=0,顺序扫描模拟实际仓位;
- Dry-run/live:initial_position 从 Freqtrade Trade 持久层读取的真实仓位
  (每个 heartbeat 重新读取),最新行信号 = 真实仓位与最新目标的差异,
  不依赖上一根预测目标。

幂等性(工作包 F 二十一节):每次调用先把 enter_long/enter_tag/exit_long
统一清零重建,populate_entry_trend 与 populate_exit_trend 先后重复调用
结果完全一致,不残留旧信号。Freqtrade 回测引擎自身的 shift(1) 使信号
在 open[t+1] 成交,与环境在 open[t+1] 执行一致,本层不再额外 shift。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TARGET_COL = "&-target_position"
DO_PREDICT_COL = "do_predict"
ENTER_TAG = "route_c_target"


def targets_to_signals(
    df: pd.DataFrame,
    target_col: str = TARGET_COL,
    do_predict_col: str = DO_PREDICT_COL,
    initial_position: int = 0,
) -> pd.DataFrame:
    """状态机信号生成(就地修改并返回;幂等,可重复调用)。

    :param initial_position: 扫描起点的仓位状态(回测 0;live 从 Trade 表读取)。
    """
    if target_col not in df.columns:
        raise ValueError(f"缺少目标仓位列 {target_col}")
    target = df[target_col].astype(int).to_numpy()
    if do_predict_col in df.columns:
        dp = df[do_predict_col].astype(int).to_numpy()
    else:
        dp = np.ones(len(df), dtype=int)

    sim = int(initial_position)
    enter = np.zeros(len(df), dtype=int)
    exit_ = np.zeros(len(df), dtype=int)
    tags = np.full(len(df), None, dtype=object)

    for i in range(len(df)):
        if dp[i] != 1:
            # 无效预测行:不生成信号,仓位状态不变
            continue
        t = target[i]
        if sim == 0 and t == 1:
            enter[i] = 1
            tags[i] = ENTER_TAG
            sim = 1
        elif sim == 1 and t == 0:
            exit_[i] = 1
            sim = 0

    # 统一清零重建(幂等):先清三列,再写入本次结果
    df["enter_long"] = enter
    df["enter_tag"] = tags
    df["exit_long"] = exit_
    return df


def target_to_signals(df: pd.DataFrame, col: str = TARGET_COL) -> pd.DataFrame:
    """兼容别名:阶段 2.5 调用名,内部转发到状态机实现。"""
    return targets_to_signals(df, target_col=col)
