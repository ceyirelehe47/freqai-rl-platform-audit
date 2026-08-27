"""工作包 M:生成器族外推(G3)与参数外推(G2)。"""

from __future__ import annotations

from rl_curriculum.evaluator import EvalConfig, evaluate_policy
from rl_curriculum.policies import RuleTrendPolicy

TRAIN_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [18.0, 30.0],
    "vol_bps_range": [20.0, 32.0],
    "regime_len_range": [12, 40],
}
EXTRAP_PARAMS = {
    "episode_bars": 96,
    "drift_bps_range": [30.0, 45.0],
    "vol_bps_range": [32.0, 50.0],
    "regime_len_range": [12, 40],
}
B_PARAMS = {"episode_bars": 96, "sigma_mu_bps": 4.0, "vol_bps": 28.0,
            "theta": 0.015}
CFG = EvalConfig(fee=0.001)


def test_parameter_extrapolation_positive(gen_a, schema):
    """G2:训练范围外参数(drift 30-45bps 超出 18-30)规则策略仍正。"""
    eps = [gen_a.generate(EXTRAP_PARAMS, seed=s, split="param_extrapolation",
                          timeframe="15m")
           for s in (201, 202, 203, 204, 205, 206)]
    rep = evaluate_policy(RuleTrendPolicy(ma_threshold=0.001), eps, CFG, schema)
    assert rep["overall"]["median"] > 0, rep["overall"]
    assert rep["by_split"]["param_extrapolation"]["median"] > 0


def test_parameter_extrapolation_is_out_of_range():
    lo, hi = TRAIN_PARAMS["drift_bps_range"]
    elo, ehi = EXTRAP_PARAMS["drift_bps_range"]
    assert elo >= hi  # 外推:下界达到训练上界之外
    vlo, vhi = TRAIN_PARAMS["vol_bps_range"]
    evlo, evhi = EXTRAP_PARAMS["vol_bps_range"]
    assert evlo >= vhi


def test_family_holdout_positive(gen_b, schema):
    """G3:未见生成机制(OU 平滑漂移,独立代码路径)规则策略为正。"""
    eps = [gen_b.generate(B_PARAMS, seed=s, split="family_holdout",
                          timeframe="15m")
           for s in (201, 202, 203, 204, 205, 206, 207, 208)]
    rep = evaluate_policy(RuleTrendPolicy(ma_threshold=0.001), eps, CFG, schema)
    assert rep["overall"]["median"] > 0, rep["overall"]


def test_family_holdout_uses_unseen_family_interface(gen_a, gen_b):
    """G3 至少一个未参与训练的生成机制:B 与 A 无共享隐藏列。"""
    assert set(gen_a.hidden_columns) != set(gen_b.hidden_columns)
    assert gen_b.family != gen_a.family
    assert gen_b.family_version != gen_a.family_version
