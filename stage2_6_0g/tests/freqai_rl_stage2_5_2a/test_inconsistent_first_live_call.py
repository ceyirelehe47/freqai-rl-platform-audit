"""工作包 D 测试:INCONSISTENT 首次启动 fail-closed(不再 int(None))。

冻结语义:执行状态 INCONSISTENT -> 不调用模型(含历史展示重放)、
展示目标安全值 0、最新一行不生成 entry/exit、不取消现有订单、
trace 记录 fail_closed/execution_state/model_called/latest_target_valid/reason。
"""

import numpy as np
import pandas as pd
import pytest

from rl_platform.execution_state import InconsistentExecutionStateError
from rl_platform.live_inference import live_predict_frame
from rl_platform.signal_convert import (
    INTENT_FAIL_CLOSED,
    latest_row_signals,
)


class ExplodingModel:
    """predict 被调用即失败:用于证明 fail-closed 分支完全不调用模型。"""

    def __init__(self):
        self.calls = 0

    def predict(self, *args, **kwargs):
        self.calls += 1
        raise AssertionError("INCONSISTENT fail-closed 状态下模型被调用")


def read_inconsistent(pair: str) -> int:
    raise InconsistentExecutionStateError("执行状态: INCONSISTENT(pair=BTC/USDT)\n测试注入")


def make_df(n, cols=("f1", "f2")):
    rng = np.random.default_rng(5)
    return pd.DataFrame(
        rng.normal(0, 1, size=(n, len(cols))), columns=list(cols)
    )


# ---------------------------------------------------------------- 首次全历史
def test_first_full_history_inconsistent_no_typeerror():
    """1) 首次全历史调用 + INCONSISTENT + fallback_target=None:无 TypeError。"""
    model = ExplodingModel()
    df = make_df(150)
    actions, trace = live_predict_frame(
        model=model, dataframe=df, pair="BTC/USDT", window_size=1,
        read_position_fn=read_inconsistent, do_predict=None, fallback_target=None,
    )
    # 安全展示值:全 0(明确的展示占位,不是真实目标空仓)
    assert actions.tolist() == [0] * 150
    assert trace["fail_closed"] is True
    assert trace["execution_state"] == "INCONSISTENT"
    assert trace["model_called"] is False
    assert trace["latest_target_valid"] is False
    assert trace["latest_target"] == 0
    assert trace["fail_closed_reason"] and "INCONSISTENT" in trace["fail_closed_reason"]
    assert trace["mode"] == "fail_closed_inconsistent"
    assert model.calls == 0


def test_heartbeat_single_row_inconsistent():
    """2) 单行 heartbeat + INCONSISTENT:同样 fail-closed。"""
    model = ExplodingModel()
    df = make_df(1)
    actions, trace = live_predict_frame(
        model=model, dataframe=df, pair="BTC/USDT", window_size=1,
        read_position_fn=read_inconsistent, do_predict=[1], fallback_target=1,
    )
    assert actions.tolist() == [0]
    assert trace["fail_closed"] is True
    assert trace["model_called"] is False
    assert trace["latest_target_valid"] is False
    # fallback_target 存在也不用:安全值 0,且不得解释为真实目标空仓
    assert trace["latest_target"] == 0
    assert model.calls == 0


def test_pending_order_inconsistent_no_order_no_cancel():
    """3/6/7) 已有 pending order + INCONSISTENT:信号层最高优先级,
    不生成任何订单,也不产生取消意图(即使目标与挂单方向相反)。"""
    df = make_df(3)
    df["&-target_position"] = [0, 0, 0]  # latest_row_signals 要求目标列
    for target in (0, 1):  # 无论目标方向
        df2, intent = latest_row_signals(df.copy(), "INCONSISTENT", target, 1)
        assert intent == INTENT_FAIL_CLOSED
        assert int(df2["enter_long"].iloc[-1]) == 0
        assert int(df2["exit_long"].iloc[-1]) == 0
        assert df2["enter_long"].sum() == 0 and df2["exit_long"].sum() == 0


def test_model_never_called_even_for_history_replay():
    """4) 历史展示重放也不调用模型(mock 调用即失败,零调用)。"""
    model = ExplodingModel()
    live_predict_frame(
        model=model, dataframe=make_df(80), pair="BTC/USDT", window_size=1,
        read_position_fn=read_inconsistent, do_predict=np.ones(80, dtype=int),
        fallback_target=None,
    )
    assert model.calls == 0
    # 对照:状态正常时模型确实被调用(证明 mock 具备检测能力)
    calls = {"n": 0}

    class CountingModel:
        def predict(self, obs, deterministic=True):
            calls["n"] += 1
            return 1, None

    live_predict_frame(
        model=CountingModel(), dataframe=make_df(80), pair="BTC/USDT",
        window_size=1, read_position_fn=lambda p: 0,
        do_predict=np.ones(80, dtype=int), fallback_target=None,
    )
    assert calls["n"] > 0


def test_do_predict_invalid_with_inconsistent_still_fail_closed():
    """INCONSISTENT 优先于 do_predict 无效:两者叠加仍 fail closed。"""
    model = ExplodingModel()
    actions, trace = live_predict_frame(
        model=model, dataframe=make_df(50), pair="BTC/USDT", window_size=1,
        read_position_fn=read_inconsistent,
        do_predict=np.zeros(50, dtype=int), fallback_target=None,
    )
    assert trace["fail_closed"] is True
    assert trace["mode"] == "fail_closed_inconsistent"
    assert model.calls == 0


def test_normal_path_still_works():
    """回归:非 INCONSISTENT 时首次全历史调用行为不变(历史重放+最新行)。"""
    class OnesModel:
        def predict(self, obs, deterministic=True):
            return 1, None

    df = make_df(30)
    actions, trace = live_predict_frame(
        model=OnesModel(), dataframe=df, pair="BTC/USDT", window_size=1,
        read_position_fn=lambda p: 0, do_predict=None, fallback_target=None,
    )
    assert trace["fail_closed"] is False
    assert trace["model_called"] is True
    assert trace["latest_target_valid"] is True
    assert trace["latest_target"] == 1
    assert set(np.unique(actions).tolist()) <= {0, 1}
