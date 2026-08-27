"""目标仓位 -> Freqtrade 信号转换(阶段 2.5.1 工作包 F 重设计,
阶段 2.5.2 工作包 B 拆分为 backtest / live 两条明确路径)。

模型预测列 &-target_position 表示目标仓位(0/1),不是开仓/退出命令。

Backtest 路径(targets_to_signals,顺序扫描状态机):
    do_predict != 1 -> 不生成信号,仓位状态不变
    空仓 + 有效目标 1 -> enter_long
    多头 + 有效目标 0 -> exit_long
    目标与状态相同   -> 无信号
    initial_position=0,顺序扫描模拟实际仓位;回测 DataFrame 逐 bar 结算,
    Freqtrade 回测引擎自身的 shift(1) 使信号在 open[t+1] 成交,
    与环境在 open[t+1] 执行一致。

Live 路径(latest_row_signals,阶段 2.5.2 工作包 B 七/八节):
    历史行(含 FreqAI 首次传入的整段回填)一律 enter=exit=0,只用于展示;
    只有最新一行根据 [真实执行状态 + 最新目标 + 最新 do_predict + 活动订单]
    生成交易意图:
      FLAT+1 -> enter;LONG+0 -> exit;其余目标与状态一致 -> 无信号;
      PENDING_ENTRY/PARTIAL_ENTRY+1 -> 不生成重复 entry;
      PENDING_EXIT/PARTIAL_EXIT+0  -> 不生成重复 exit;
      挂单期间目标反转(entry+0 / exit+1)-> 不在本 heartbeat 生成任何
      反向订单;取消通过 Freqtrade 官方 adjust_entry_price/adjust_exit_price
      返回 None 的扩展点在 manage_open_orders 阶段完成,
      取消完成后下一 heartbeat 按实际暴露重新决策;
      do_predict != 1 -> 不生成新 entry/exit,不因模型目标取消订单;
      INCONSISTENT -> 不生成任何订单(fail closed)。
    幂等:每次调用先把 enter_long/enter_tag/exit_long 整表清零,
    只在最新行写入,不残留上一 heartbeat 的信号。
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from rl_platform.execution_state import (
    FLAT,
    INCONSISTENT,
    LONG,
    PARTIAL_ENTRY,
    PARTIAL_EXIT,
    PENDING_ENTRY,
    PENDING_EXIT,
)

TARGET_COL = "&-target_position"
DO_PREDICT_COL = "do_predict"
ENTER_TAG = "route_c_target"

# live 交易意图(诊断/trace 用;enter/exit 列只承载实际下单意图)
INTENT_HOLD = "hold"
INTENT_ENTER = "enter"
INTENT_EXIT = "exit"
INTENT_HOLD_PENDING_ENTRY = "hold_pending_entry"
INTENT_HOLD_PENDING_EXIT = "hold_pending_exit"
INTENT_CANCEL_REQUEST_ENTRY = "cancel_request_entry"
INTENT_CANCEL_REQUEST_EXIT = "cancel_request_exit"
INTENT_NO_SIGNAL_INVALID_PREDICTION = "no_signal_invalid_prediction"
INTENT_FAIL_CLOSED = "fail_closed_inconsistent"


def targets_to_signals(
    df: pd.DataFrame,
    target_col: str = TARGET_COL,
    do_predict_col: str = DO_PREDICT_COL,
    initial_position: int = 0,
) -> pd.DataFrame:
    """Backtest 路径:状态机顺序扫描信号生成(就地修改并返回;幂等)。

    :param initial_position: 扫描起点的仓位状态(回测恒为 0;live 已改用
        latest_row_signals,不再从 Trade 表读仓位做整段扫描)。
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


def latest_row_signals(
    df: pd.DataFrame,
    state: str,
    target: int,
    do_predict: int = 1,
    target_col: str = TARGET_COL,
    do_predict_col: str = DO_PREDICT_COL,
) -> tuple[pd.DataFrame, str]:
    """Live 路径:整表清零,只在最新一行写入交易意图(幂等)。

    :param state: execution_state 解析的执行状态(七态)
    :param target: 最新一行目标仓位(&-target_position 末值)
    :param do_predict: 最新一行 do_predict(缺列按 1)
    :return: (df, intent)——intent 为诊断意图字符串
    """
    if target_col not in df.columns:
        raise ValueError(f"缺少目标仓位列 {target_col}")
    target = int(target)
    if target not in (0, 1):
        raise ValueError(f"目标仓位必须是 0 或 1,收到 {target}")
    do_predict = int(do_predict)
    if do_predict_col in df.columns and len(df) > 0:
        do_predict = int(df[do_predict_col].iloc[-1])

    # 幂等清零:历史行(含上一 heartbeat 残留)一律无信号
    df["enter_long"] = 0
    df["enter_tag"] = None
    df["exit_long"] = 0

    intent: str
    if state == INCONSISTENT:
        intent = INTENT_FAIL_CLOSED
    elif do_predict != 1:
        # 无效预测:不生成新订单,也不因模型目标取消既有订单
        intent = INTENT_NO_SIGNAL_INVALID_PREDICTION
    elif state == FLAT:
        intent = INTENT_ENTER if target == 1 else INTENT_HOLD
    elif state == LONG:
        intent = INTENT_EXIT if target == 0 else INTENT_HOLD
    elif state in (PENDING_ENTRY, PARTIAL_ENTRY):
        if target == 1:
            intent = INTENT_HOLD_PENDING_ENTRY
        else:
            # 目标反转:请求取消剩余 entry(adjust_entry_price -> None),
            # 本 heartbeat 不生成 exit,取消完成后下一 heartbeat 按实际暴露处理
            intent = INTENT_CANCEL_REQUEST_ENTRY
    elif state in (PENDING_EXIT, PARTIAL_EXIT):
        if target == 0:
            intent = INTENT_HOLD_PENDING_EXIT
        else:
            intent = INTENT_CANCEL_REQUEST_EXIT
    else:
        raise ValueError(f"未知执行状态 {state!r}")

    if intent == INTENT_ENTER and len(df) > 0:
        df.loc[df.index[-1], "enter_long"] = 1
        df.loc[df.index[-1], "enter_tag"] = ENTER_TAG
    elif intent == INTENT_EXIT and len(df) > 0:
        df.loc[df.index[-1], "exit_long"] = 1
    return df, intent


def target_to_signals(df: pd.DataFrame, col: str = TARGET_COL) -> pd.DataFrame:
    """兼容别名:阶段 2.5 调用名,内部转发到状态机实现(backtest 路径)。"""
    return targets_to_signals(df, target_col=col)
