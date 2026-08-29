"""工作包 G 测试(一):首次 live 全历史推理不覆盖真实仓位(任务书二十三节)。

走真实 RouteCModel.rl_model_predict 调用链(测试级 harness:
patch 父类 __init__ 设置最小属性,与阶段 2.5 干-run 测试同一约定),
Trade 状态来自 freqtrade.persistence 真实模型 + 内存 SQLite,
不连接真实账户、不提交订单、无 API Key。
"""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np
import pandas as pd
import pytest

from rl_platform.inference import ReadPositionPolicy, ScriptedPolicy

ART = Path(__file__).resolve().parents[2] / "artifacts" / "freqai_rl_stage2_5_1"
ROOT = ART.parents[1]
PAIR = "BTC/USDT"


def load_route_c_model():
    spec = importlib.util.spec_from_file_location(
        "route_c_model_live_test",
        ROOT / "user_data" / "freqaimodels" / "RouteCModel.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.RouteCModel


@pytest.fixture()
def fresh_db():
    from freqtrade.persistence import Trade, init_db

    Trade.use_db = True  # Backtesting 会全局置 False,此处复位(测试隔离)
    init_db("sqlite://")
    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    yield
    Trade.session.rollback()


def make_model(live=True):
    RouteCModel = load_route_c_model()

    def fake_super_init(self, **kwargs):
        cfg = kwargs["config"]
        self.freqai_info = cfg["freqai"]
        self.config = cfg
        self.CONV_WIDTH = self.freqai_info.get("conv_width", 1)
        self.live = live
        self.activate_tensorboard = False

    with patch(
        "freqtrade.freqai.RL.BaseReinforcementLearningModel."
        "BaseReinforcementLearningModel.__init__",
        fake_super_init,
    ):
        return RouteCModel(config={
            "freqai": {"conv_width": 1,
                       "route_c": {"ppo": {}, "slippage_bps": 0.0, "seed": 42}},
        })


def make_dk(rows: int):
    """最小 dk:pair 与 label_list(rl_model_predict 实际使用的公开属性)。"""
    return SimpleNamespace(pair=PAIR, label_list=["&-target_position"])


def open_long_trade(fee=0.001):
    from datetime import UTC, datetime, timedelta

    from freqtrade.persistence import Trade

    return Trade(
        pair=PAIR, stake_amount=100.0, amount=0.01, open_rate=10000.0,
        open_date=datetime.now(UTC) - timedelta(hours=2),
        fee_open=fee, fee_close=fee, is_open=True, is_short=False,
        exchange="binanceus",
    )


# ------------------------------------------------ 二十五节场景 1/2:历史回填 + 真实仓位
def test_full_history_backfill_keeps_real_position(fresh_db):
    """首次传入 100 行历史,真实仓位为 1:
    - 最新观察仓位分量必须为 1(ReadPositionPolicy 直接回显观察末维);
    - 历史回填结束后实时状态仍为 1(_last_target_position = 实时目标,非重放末态);
    - 历史段用隔离临时状态(空仓起点),不覆盖执行状态。"""
    from freqtrade.persistence import Trade

    Trade.session.add(open_long_trade())
    Trade.session.commit()

    model = make_model(live=True)
    assert model._last_target_position is None
    df = pd.DataFrame(np.zeros((100, 2)))
    dk = make_dk(100)
    out = model.rl_model_predict(df, dk, ReadPositionPolicy())

    assert len(out) == 100
    latest = int(out["&-target_position"].iloc[-1])
    assert latest == 1, "最新一行必须由真实仓位(1)驱动"
    assert all(int(v) == 0 for v in out["&-target_position"].iloc[:-1]), \
        "历史回填应从隔离空仓状态重放(ReadPositionPolicy 恒 0)"
    assert model._last_target_position == 1
    trace = model.live_trace[-1]
    assert trace["mode"] == "history_backfill"
    assert trace["real_position"] == 1 and trace["latest_target"] == 1


# ------------------------------------------------ 场景 3:下一 heartbeat 从数据库读取
def test_next_heartbeat_reads_trade_table(fresh_db):
    from freqtrade.persistence import Trade

    Trade.session.add(open_long_trade())
    Trade.session.commit()
    model = make_model(live=True)
    # 首次历史回填
    model.rl_model_predict(pd.DataFrame(np.zeros((100, 2))), make_dk(100),
                           ReadPositionPolicy())
    # 下一 heartbeat:单行,Trade 仍为 1 -> 状态仍从数据库读取
    out2 = model.rl_model_predict(pd.DataFrame(np.zeros((1, 2))), make_dk(1),
                                  ReadPositionPolicy())
    assert int(out2["&-target_position"].iloc[-1]) == 1
    assert model.live_trace[-1]["mode"] == "heartbeat"
    assert model.live_trace[-1]["real_position"] == 1


# ------------------------------------------------ 场景 4:模型重新加载后仍正确
def test_model_reload_resyncs_from_trade(fresh_db):
    from freqtrade.persistence import Trade

    Trade.session.add(open_long_trade())
    Trade.session.commit()
    model_a = make_model(live=True)
    model_a.rl_model_predict(pd.DataFrame(np.zeros((100, 2))), make_dk(100),
                             ReadPositionPolicy())
    # 模拟重新加载:新实例,内存状态清空
    model_b = make_model(live=True)
    assert model_b._last_target_position is None
    out = model_b.rl_model_predict(pd.DataFrame(np.zeros((1, 2))), make_dk(1),
                                   ReadPositionPolicy())
    assert int(out["&-target_position"].iloc[-1]) == 1


# ------------------------------------------------ 场景 5:空仓初始状态
def test_flat_initial_position(fresh_db):
    """Trade 表为空 -> 真实仓位 0 -> 最新目标由模型在 pos=0 观察下决定。"""
    model = make_model(live=True)
    out = model.rl_model_predict(pd.DataFrame(np.zeros((50, 2))), make_dk(50),
                                 ReadPositionPolicy())
    assert int(out["&-target_position"].iloc[-1]) == 0
    assert model.live_trace[-1]["real_position"] == 0


# ------------------------------------------------ 场景 6:do_predict=0/2
def test_do_predict_invalid_latest_row(fresh_db):
    """最新行 do_predict=0/2 -> 不调用模型,目标保持当前值(不更新状态):
    - 已有上一目标(_last_target_position)时沿用该目标;
    - 无先验目标时回落到真实仓位(不产生差异信号);
    信号层由状态机按 do_predict 跳过,无效行不会产生交易动作(见 do_predict 测试)。"""
    from freqtrade.persistence import Trade

    Trade.session.add(open_long_trade())
    Trade.session.commit()

    # 已有上一目标 0(退出未成交中),最新行无效 -> 目标保持 0
    model3 = make_model(live=True)
    model3._last_target_position = 0
    dk = make_dk(1)
    dk.do_predict = np.array([0], dtype=int)
    out3 = model3.rl_model_predict(pd.DataFrame(np.zeros((1, 2))), dk,
                                   ScriptedPolicy(feature_index=0))
    assert int(out3["&-target_position"].iloc[-1]) == 0

    # 模型过期 do_predict=2 同样保持
    dk2 = make_dk(1)
    dk2.do_predict = np.array([2], dtype=int)
    model4 = make_model(live=True)
    model4._last_target_position = 0
    out4 = model4.rl_model_predict(pd.DataFrame(np.zeros((1, 2))), dk2,
                                   ScriptedPolicy(feature_index=0))
    assert int(out4["&-target_position"].iloc[-1]) == 0

    # 无先验目标(首次调用即无效) -> 回落到真实仓位(1)
    dk3 = make_dk(1)
    dk3.do_predict = np.array([0], dtype=int)
    model5 = make_model(live=True)
    out5 = model5.rl_model_predict(pd.DataFrame(np.zeros((1, 2))), dk3,
                                   ScriptedPolicy(feature_index=0))
    assert int(out5["&-target_position"].iloc[-1]) == 1


# ------------------------------------------------ 历史回填规模边界
def test_history_backfill_does_not_mutate_model_state(fresh_db):
    """连续两次历史回填:执行状态只由最新行 + Trade 决定。"""
    from freqtrade.persistence import Trade

    Trade.session.add(open_long_trade())
    Trade.session.commit()
    model = make_model(live=True)
    model.rl_model_predict(pd.DataFrame(np.ones((80, 2))), make_dk(80),
                           ReadPositionPolicy())
    assert model._last_target_position == 1
    # Trade 平仓后再次历史回填 -> 实时目标回到 0
    for t in Trade.get_trades_proxy(is_open=True):
        t.is_open = False
    Trade.session.commit()
    out = model.rl_model_predict(pd.DataFrame(np.ones((80, 2))), make_dk(80),
                                 ReadPositionPolicy())
    assert int(out["&-target_position"].iloc[-1]) == 0
    assert model._last_target_position == 0


# ------------------------------------------------ 证据
def test_live_full_history_trace_evidence(fresh_db):
    from freqtrade.persistence import Trade

    ART.mkdir(parents=True, exist_ok=True)
    rows = []
    Trade.session.add(open_long_trade())
    Trade.session.commit()
    model = make_model(live=True)
    for step, n in enumerate((100, 1, 1)):
        out = model.rl_model_predict(pd.DataFrame(np.zeros((n, 2))), make_dk(n),
                                     ReadPositionPolicy())
        tr = model.live_trace[-1]
        rows.append({
            "heartbeat": step, "n_rows": n, "mode": tr["mode"],
            "real_position_from_trade": tr["real_position"],
            "latest_target": tr["latest_target"],
            "do_predict_latest": tr["do_predict_latest"],
            "history_isolated": all(
                int(v) == 0 for v in out["&-target_position"].iloc[:-1]) if n > 1 else None,
            "last_target_position_attr": model._last_target_position,
        })
    pd.DataFrame(rows).to_csv(ART / "live_full_history_trace.csv", index=False)
    assert rows[0]["latest_target"] == 1 and rows[-1]["latest_target"] == 1
