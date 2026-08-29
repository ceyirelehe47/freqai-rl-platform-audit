"""工作包 F 测试:do_predict 与实际仓位状态机(任务书十九至二十二节)。"""

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rl_platform.inference import FixedSequencePolicy, SequentialPositionPredictor
from rl_platform.signal_convert import targets_to_signals

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_1"
COLS = ["row", "do_predict", "target_raw_policy", "target_effective",
        "sim_position_before", "signal", "sim_position_after"]


def make_df(targets, dps):
    return pd.DataFrame({
        "&-target_position": targets,
        "do_predict": dps,
    })


# ------------------------------------------------- 二十二节场景 1:空仓入场被阻止
def test_entry_blocked_by_do_predict_zero():
    """实际空仓,模型希望 1,该行 do_predict=0 -> 无入场,状态仍 0;
    下一有效行模型再次希望 1 -> 正常入场。"""
    df = make_df([1, 1], [0, 1])
    targets_to_signals(df)
    assert list(df["enter_long"]) == [0, 1]
    # 状态机视角:第 0 行被阻止时仓位仍 0
    assert list(df["exit_long"]) == [0, 0]


# ------------------------------------------------- 场景 2:多头退出被阻止
def test_exit_blocked_by_do_predict_zero():
    df = make_df([1, 0, 0], [1, 0, 1])
    targets_to_signals(df)
    assert list(df["enter_long"]) == [1, 0, 0]
    assert list(df["exit_long"]) == [0, 0, 1]  # 第 1 行被阻止,第 2 行正常退出


# ------------------------------------------------- 场景 3:模型过期(do_predict=2)
def test_model_expired_do_predict_two():
    df = make_df([1, 1], [2, 1])
    targets_to_signals(df)
    assert list(df["enter_long"]) == [0, 1]
    df2 = make_df([0, 0], [2, 1])
    targets_to_signals(df2, initial_position=1)
    assert list(df2["exit_long"]) == [0, 1]


# ------------------------------------------------- 场景 4:重复调用一致
def test_populate_idempotency():
    """entry/exit populate 先后重复调用同一转换,结果完全相同。"""
    df = make_df([1, 1, 0, 0, 1, 0], [1, 0, 1, 1, 1, 1])
    targets_to_signals(df)
    first = (list(df["enter_long"]), list(df["exit_long"]), list(df["enter_tag"]))
    # 模拟第二次 populate(populate_exit_trend 在 entry 之后被再次调用)
    targets_to_signals(df)
    second = (list(df["enter_long"]), list(df["exit_long"]), list(df["enter_tag"]))
    assert first == second
    # 不残留旧信号:全 0 目标 + do_predict=1 时三列全部清零
    df.loc[:, "&-target_position"] = 0
    targets_to_signals(df)
    assert list(df["enter_long"]) == [0] * 6
    assert list(df["exit_long"]) == [0] * 6


def test_signals_with_stale_columns_cleanup():
    """旧 dataframe 残留信号必须被清除(幂等重建)。"""
    df = make_df([0, 0], [1, 1])
    df["enter_long"] = 1
    df["exit_long"] = 1
    df["enter_tag"] = "stale"
    targets_to_signals(df)
    assert list(df["enter_long"]) == [0, 0]
    assert list(df["exit_long"]) == [0, 0]
    assert all(t is None for t in df["enter_tag"])


# ------------------------------------------------- 初始仓位(live 真实仓位)
def test_initial_position_from_live_state():
    """live 下扫描起点是真实仓位:多头 + 目标 0 -> 直接 exit(无历史依赖)。"""
    df = make_df([0, 0], [1, 1])
    targets_to_signals(df, initial_position=1)
    assert list(df["exit_long"]) == [1, 0]


# ------------------------------------------------- 推理器 mask(十九节)
def test_predictor_do_predict_mask():
    """无效行不调用模型、目标保持当前值、状态不更新。"""
    calls = []

    class Counting:
        def predict(self, obs, deterministic=True):
            calls.append(int(obs[-1]))
            return 1, None

    pred = SequentialPositionPredictor(Counting(), window_size=1)
    out = pred.predict_frame(
        pd.DataFrame(np.zeros((4, 2))), do_predict=[1, 0, 2, 1]
    )
    assert list(out) == [1, 1, 1, 1]
    assert len(calls) == 2  # 只有 2 个有效行调用了模型
    assert calls == [0, 1]  # 顺序状态正确推进


def test_predictor_mask_length_mismatch():
    pred = SequentialPositionPredictor(FixedSequencePolicy([1]), window_size=1)
    with pytest.raises(ValueError, match="不一致"):
        pred.predict_frame(pd.DataFrame(np.zeros((3, 2))), do_predict=[1, 1])


def test_predictor_nan_observation_kept():
    """观察含 NaN/Inf 的行同样不调用模型、不更新状态。"""
    feats = pd.DataFrame(np.zeros((3, 2)))
    feats.iloc[1] = np.nan
    pred = SequentialPositionPredictor(FixedSequencePolicy([1]), window_size=1)
    out = pred.predict_frame(feats)  # 行 0 预测为 1;行 1 NaN 保持;行 2 有效
    assert list(out) == [1, 1, 1]
    assert pred.current_position == 1


# ------------------------------------------------- 状态轨迹证据
def test_do_predict_state_trace_evidence():
    ART.mkdir(parents=True, exist_ok=True)
    rows = []

    def run_case(name, targets, dps, initial=0):
        df = make_df(targets, dps)
        targets_to_signals(df, initial_position=initial)
        sim = initial
        for i in range(len(df)):
            before = sim
            sig = "enter" if df["enter_long"].iloc[i] else (
                "exit" if df["exit_long"].iloc[i] else "none")
            if sig == "enter":
                sim = 1
            elif sig == "exit":
                sim = 0
            rows.append({
                "case": name, "row": i, "do_predict": dps[i],
                "target_raw_policy": targets[i],
                "target_effective": int(df["&-target_position"].iloc[i]),
                "sim_position_before": before,
                "signal": sig, "sim_position_after": sim,
            })

    run_case("entry_blocked", [1, 1], [0, 1])
    run_case("exit_blocked", [1, 0, 0], [1, 0, 1])
    run_case("model_expired", [1, 1], [2, 1])
    run_case("initial_long_exit", [0, 0], [1, 1], initial=1)
    pd.DataFrame(rows).to_csv(ART / "do_predict_state_trace.csv", index=False)
    assert rows[-1]["sim_position_after"] == 0  # initial_long_exit 最终退出
