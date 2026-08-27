"""工作包 E 测试:amount_epsilon 四处统一(模型/策略/live 执行状态/manifest)。"""

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

PROJ = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "user_data" / "freqaimodels"))

import importlib.util


def _load_module(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, PROJ / rel)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


RUN_EXP_252A = _load_module(
    "experiments/freqai_rl_stage2_5_2a/run_experiment.py", "run_experiment_252a"
)

from rl_platform.execution_state import (  # noqa: E402
    DEFAULT_AMOUNT_EPSILON,
    FLAT,
    PARTIAL_ENTRY,
    PENDING_ENTRY,
    get_model_position_live,
    resolve_execution_state,
)

PAIR = "BTC/USDT"
BOUNDARY_FILLED = 5e-4  # 介于 1e-3 与 1e-8 之间的边界暴露


# ------------------------------------------------------- 真实 Trade/Order 构造
def make_db():
    from freqtrade.persistence import Trade, init_db

    Trade.use_db = True
    init_db("sqlite://")
    Trade.session.rollback()
    for t in Trade.get_trades():
        Trade.session.delete(t)
    Trade.session.commit()
    return Trade


def make_boundary_trade(filled: float):
    """活动 entry 单 filled=BOUNDARY_FILLED(零 trade.amount)。"""
    from freqtrade.persistence import Order, Trade

    t = Trade(
        pair=PAIR, stake_amount=100.0, amount=0.0,
        open_rate=10000.0, open_date=datetime.now(UTC) - timedelta(hours=1),
        fee_open=0.001, fee_close=0.001, is_open=True, is_short=False,
        exchange="binanceus",
    )
    o = Order(
        ft_order_side="buy", ft_pair=PAIR, ft_is_open=True,
        ft_amount=0.01, ft_price=10000.0, order_id="o_eps_boundary",
        symbol=PAIR, side="buy", order_type="limit", status="open",
        price=10000.0, average=10000.0 if filled else None,
        amount=0.01, filled=filled, remaining=0.01 - filled,
        cost=filled * 10000.0,
        order_date=datetime.now(UTC) - timedelta(minutes=5),
    )
    t.orders.append(o)
    return t


# --------------------------------------------------------------- 模型侧读取
def make_route_c_model_config(amount_epsilon: float) -> dict:
    return {
        "freqai": {
            "conv_width": 1,
            "route_c": {
                "execution_mode": "market_open_causal",
                "simulated_slippage_bps": 0.0,
                "price_tick": 0.01,
                "amount_epsilon": amount_epsilon,
                "initial_cash": 100.0,
                "seed": 42,
                "ppo": dict(RUN_EXP_252A.PPO_SMOKE_PARAMS),
            },
        },
    }


def model_rc_config(amount_epsilon: float) -> dict:
    from unittest.mock import patch

    from freqtrade.freqai.RL.BaseReinforcementLearningModel import (
        BaseReinforcementLearningModel,
    )

    from RouteCModel import RouteCModel

    def fake_init(self, **kwargs):
        self.config = kwargs.get("config", {})
        self.freqai_info = self.config.get("freqai", {})
        self.live = False
        self.CONV_WIDTH = 1
        self.activate_tensorboard = False

    with patch.object(BaseReinforcementLearningModel, "__init__", fake_init):
        m = RouteCModel(config=make_route_c_model_config(amount_epsilon))
    return m.rc_config


# --------------------------------------------------------------- 策略侧读取
def strategy_epsilon(amount_epsilon: float) -> float:
    sys.path.insert(0, str(PROJ / "user_data" / "strategies"))
    from RouteCStrategy import RouteCStrategy

    strat = RouteCStrategy.__new__(RouteCStrategy)
    strat.config = make_route_c_model_config(amount_epsilon)
    return strat.route_c_amount_epsilon


@pytest.mark.parametrize("eps", [1e-3, 1e-8, 1e-12])
def test_epsilon_single_source_everywhere(eps):
    """模型 / 策略 / live 执行状态 / manifest 使用同一配置值。"""
    # 模型侧
    rc = model_rc_config(eps)
    assert rc["amount_epsilon"] == eps
    # 策略侧(同一配置源,不允许静默默认)
    assert strategy_epsilon(eps) == eps
    # live 执行状态(经配置值传参)
    Trade = make_db()
    t = make_boundary_trade(BOUNDARY_FILLED)
    Trade.session.add(t)
    Trade.session.commit()
    snap = resolve_execution_state(
        [t], PAIR, amount_epsilon=strategy_epsilon(eps)
    )
    expect_state = (
        PENDING_ENTRY if BOUNDARY_FILLED <= eps else PARTIAL_ENTRY
    )
    assert snap.state == expect_state
    assert get_model_position_live(PAIR, amount_epsilon=eps) == (
        0 if expect_state == PENDING_ENTRY else 1
    )
    # manifest(实验入口的执行合同记录)
    contract = RUN_EXP_252A.build_execution_contract_manifest(
        make_route_c_model_config(eps)["freqai"]["route_c"]
    )
    assert contract["amount_epsilon"] == eps


def test_boundary_exposure_state_changes_with_epsilon():
    """边界暴露 5e-4:eps=1e-3 判零暴露(PENDING_ENTRY,观察 0);
    eps=1e-8/1e-12 判有暴露(PARTIAL_ENTRY,观察 1)。"""
    Trade = make_db()
    t = make_boundary_trade(BOUNDARY_FILLED)
    Trade.session.add(t)
    Trade.session.commit()
    snap_lo = resolve_execution_state([t], PAIR, amount_epsilon=1e-3)
    snap_hi = resolve_execution_state([t], PAIR, amount_epsilon=1e-12)
    assert snap_lo.state == PENDING_ENTRY
    assert snap_lo.model_position == 0
    assert snap_hi.state == PARTIAL_ENTRY
    assert snap_hi.model_position == 1


def test_default_epsilon_unchanged():
    assert DEFAULT_AMOUNT_EPSILON == 1e-12
    Trade = make_db()
    t = make_boundary_trade(0.0)
    Trade.session.add(t)
    Trade.session.commit()
    snap = resolve_execution_state([t], PAIR)
    assert snap.state == PENDING_ENTRY
    snap2 = resolve_execution_state([t], PAIR, amount_epsilon=1e-12)
    assert snap2.state == snap.state
    Trade.session.rollback()


def test_model_rejects_legacy_execution_mode():
    from unittest.mock import patch

    from freqtrade.freqai.RL.BaseReinforcementLearningModel import (
        BaseReinforcementLearningModel,
    )

    from RouteCModel import RouteCModel

    cfg = make_route_c_model_config(1e-12)
    cfg["freqai"]["route_c"]["execution_mode"] = "legacy_noncausal_not_for_training"

    def fake_init(self, **kwargs):
        self.config = kwargs.get("config", {})
        self.freqai_info = self.config.get("freqai", {})
        self.live = False
        self.CONV_WIDTH = 1
        self.activate_tensorboard = False

    with patch.object(BaseReinforcementLearningModel, "__init__", fake_init):
        with pytest.raises(RuntimeError, match="market_open_causal"):
            RouteCModel(config=cfg)
