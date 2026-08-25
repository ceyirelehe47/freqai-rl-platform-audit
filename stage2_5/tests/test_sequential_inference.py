"""顺序推理确定性测试(任务书二十一节)。

用 ScriptedPolicy(按可控特征输出固定目标仓位)验证:
1. 首次推理动作序列;
2. 相同进程再次推理(新 predictor 实例 + 同初始仓位)逐行一致;
3. 跨窗口:整段推理 == 前段推理(状态延续) + 后段推理(从上一窗口末状态开始);
4. 观察构造与训练环境一致(末维为当前目标仓位);
5. 目标仓位 -> entry/exit 信号转换正确、无重复信号;
6. FixedSequencePolicy 位置序列完全一致。

(SB3 级别的模型重载复现在 PPO 烟雾测试后做:删除预测缓存重跑,
导出的 &-target_position 序列必须逐行一致。)
"""

import numpy as np
import pandas as pd

from rl_platform.inference import (
    FixedSequencePolicy,
    ScriptedPolicy,
    SequentialPositionPredictor,
)
from rl_platform.signal_convert import target_to_signals


def make_features(n: int = 100, seed: int = 7) -> pd.DataFrame:
    rng = np.random.RandomState(seed)
    col0 = rng.randn(n)
    col1 = np.cumsum(rng.randn(n))
    return pd.DataFrame({"f0": col0, "f1": col1})


def test_observation_shape_and_position_component():
    feats = make_features(50)
    pred = SequentialPositionPredictor(ScriptedPolicy(0, 0.0), window_size=1)
    obs = pred.build_observation(feats.to_numpy(), 10, 1)
    assert obs.shape == (3,)  # 2 特征 + 1 仓位
    assert obs[-1] == 1.0
    obs0 = pred.build_observation(feats.to_numpy(), 10, 0)
    assert obs0[-1] == 0.0
    assert (obs[:-1] == obs0[:-1]).all()


def test_first_and_repeat_inference_identical():
    feats = make_features(100)
    policy = ScriptedPolicy(0, 0.1)
    a1 = SequentialPositionPredictor(policy).predict_frame(feats)
    a2 = SequentialPositionPredictor(policy).predict_frame(feats)
    assert (a1 == a2).all()
    # scripted policy 语义:首列特征 > 0.1 -> 1
    expect = (feats["f0"].to_numpy() > 0.1).astype(int)
    assert (a1 == expect).all()


def test_cross_window_state_continuity():
    """整段推理 == 前窗推理 + 后窗从上一窗口末状态继续推理。"""
    feats = make_features(120)
    policy = ScriptedPolicy(0, 0.0)
    whole = SequentialPositionPredictor(policy).predict_frame(feats)

    p1 = SequentialPositionPredictor(policy)
    part1 = p1.predict_frame(feats.iloc[:70].reset_index(drop=True))
    assert p1.current_position == whole[69]

    p2 = SequentialPositionPredictor(policy)
    p2.current_position = int(p1.current_position)
    part2 = p2.predict_frame(feats.iloc[70:].reset_index(drop=True))

    assert (np.concatenate([part1, part2]) == whole).all()
    assert p2.current_position == whole[-1]


def test_fixed_sequence_policy():
    actions = [0, 1, 1, 0, 0, 1]
    feats = make_features(len(actions))
    pred = SequentialPositionPredictor(FixedSequencePolicy(actions))
    out = pred.predict_frame(feats)
    assert out.tolist() == actions


def test_target_to_signals():
    df = pd.DataFrame({"&-target_position": [0, 1, 1, 0, 0, 0, 1, 1]})
    out = target_to_signals(df)
    assert out["enter_long"].tolist() == [0, 1, 0, 0, 0, 0, 1, 0]
    assert out["exit_long"].tolist() == [0, 0, 0, 1, 0, 0, 0, 0]
    # 重复目标不产生重复信号
    assert (out.loc[out["&-target_position"] == 1, "enter_long"].sum()
            == 2)  # 两次进入(0->1)各一次


def test_nan_guard_keeps_position():
    """预热期特征含 NaN 时保持当前目标仓位,不调用模型。"""
    feats = make_features(20)
    feats.iloc[5:8, 0] = np.nan
    feats.iloc[5:8, 1] = np.nan
    policy = ScriptedPolicy(0, -10.0)  # 恒输出 1
    pred = SequentialPositionPredictor(policy)
    out = pred.predict_frame(feats)
    # NaN 行保持之前的仓位:前 5 行为 1(阈值 -10 恒 1),NaN 行保持 1
    assert out[5:8].tolist() == [1, 1, 1]
    assert (out[:5] == 1).all()
