# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 准备段测试(纯数学;零求解预算)。"""
import json
import math
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rl_posctl.skill_p0 import unified_ref_adapter as ur  # noqa


def test_dependency_and_purity():
    assert ur.dependency_available() is True
    # 模块源不 import p0eval/torch/env(纯数学契约)
    import re as _re
    src = pathlib.Path(ur.__file__).read_text(
        encoding="utf-8")
    imports = _re.findall(
        r"^\s*(?:from|import)\s+([^\n]+)", src,
        _re.MULTILINE)
    joined = "\n".join(imports)
    for bad in ("p0eval", "torch", "offline_skill_report",
                "load_p0_model", "confirm", "stable_baselines"):
        assert bad not in joined, bad


def test_config_pinned_and_digest_bound():
    cfg = ur.CALIB_CONFIG
    assert cfg["mu"] == 0.0012
    assert cfg["sigma_by_g"] == {"0": 0.03, "1": 0.06}
    assert cfg["fee"] == 0.001 and cfg["H"] == 32
    assert cfg["initial_cash"] == 100.0
    assert cfg["slippage_bps"] == cfg["price_tick"] == 0.0
    assert cfg["funding"] == "none"
    assert cfg["maintenance_margin"] == 0.05
    assert cfg["reward_scale"] == 1.0
    assert len(cfg["kernel_ref"]) == 64
    assert len(cfg["economy_ref"]) == 64
    assert cfg["task_ref"] == "unified-posctl-candidate-v1"
    # digest 变化即失配:改任一数值必换键
    cfg2 = dict(cfg, fee=0.002)
    d2 = __import__("hashlib").sha256(json.dumps(
        cfg2, sort_keys=True).encode()).hexdigest()
    assert d2 != ur.CONFIG_DIGEST


def test_questions_exact_64_and_shape():
    qs = ur.QUESTIONS
    assert len(qs) == 64
    grid = [q for q in qs if q["id"].startswith("G")]
    tail = [q for q in qs if q["id"].startswith("T")]
    assert len(grid) == 60 and len(tail) == 4
    seen = {(q["s"], q["c"], q["q"], q["g"])
            for q in grid}
    assert len(seen) == 60   # 3×2×5×2 全覆盖无重复
    assert all(q["remaining"] == q["total"] == 32
               for q in grid)
    for q in tail:
        assert q["remaining"] == 1 and q["total"] == 32
        assert q["s"] in (-1, 1)
        assert q["c"] == 1 and q["q"] == 1.0
        assert q["g"] in (0, 1)
    assert all(
        q["account"] == {"exposure": 0.0,
                         "solvency_raw": math.inf}
        for q in qs)


def test_tiers_and_action_grids():
    assert ur.TIERS["L0"] == {
        "n_dense": 81, "n_ext_per_side": 16,
        "gauss_legendre": 12, "n_actions": 41}
    assert ur.TIERS["L1"]["n_actions"] == 81
    assert ur.TIERS["L2"]["n_actions"] == 161
    assert ur.BUDGET == {"max_runs": 3,
                         "wall_clock_s": 900,
                         "cpu_s": 600, "rss_gib": 1.0}
    assert ur.FORBIDDEN_SWEEP == ("mu", "sigma", "fee",
                                  "seed")
    for tier, n in (("L0", 41), ("L1", 81),
                    ("L2", 161)):
        w = ur.action_grid(tier)
        assert len(w) == n
        assert w[0] == -1.0 and w[-1] == 1.0
        assert w[n // 2] == 0.0
        d = [abs(w[i + 1] - w[i]) for i in range(n - 1)]
        assert max(d) - min(d) < 1e-12   # 等距(浮点容差)
    with pytest.raises(ValueError):
        ur.action_grid("L0x")


def test_account_grid_domains():
    g0 = ur.account_grid("L0")
    assert abs(g0[0] + 20.0) < 1e-9 or g0[0] >= -20.0
    assert g0.max() <= 20.0 + 1e-9 and \
        g0.min() >= -20.0 - 1e-9
    dense = [x for x in g0 if abs(x) <= 1.25 + 1e-12]
    assert len(dense) == 81
    total = 81 + 2 * 16
    assert len(g0) == total


def test_step_math_fee_and_hold_semantics():
    # 无交易目标=当前敞口:HOLD 路径零费
    lg, nxt = ur.step_growth(0.5, 0.5, 0.01)
    assert lg == math.log(1.0 + 0.5 * 0.01)
    assert abs(nxt - 0.5 * 1.01 / (1 + 0.005)) < 1e-15
    # 调仓付费一次
    lg2, _ = ur.step_growth(0.0, 1.0, 0.0)
    assert abs(lg2 - math.log(1 - 0.001)) < 1e-15
    # 破产→-inf
    lg3, _ = ur.step_growth(1.0, 1.0, -2.0)
    assert lg3 == -math.inf
    # 终端清算:flat 无费;有仓清算付费一次
    assert ur.terminal_liquidation_log(0.0, 0.01) == \
        math.log(1.0)
    tl = ur.terminal_liquidation_log(1.0, 0.0)
    assert abs(tl - math.log(1 - 0.001)) < 1e-15


def test_jensen_negative_control_last_bar_flat():
    """末 bar、flat、s=0:μ_eff=0,任何非零敞口 E[ln(1+wx)]
    <0(方差拖累)→最优=0/HOLD;此为解析负控(Jensen),非求解。"""
    acc = 1e-9
    qs = {w: 0.0 for w in ur.action_grid("L0")}
    u, wu, sigma = ur.noise_nodes(0, 12)
    for w in list(qs):
        tot = 0.0
        for ui, wi in zip(u, wu):
            x = math.sqrt(3) * sigma * ui   # s=0 → μ=0
            lg, _ = ur.step_growth(0.0, w, x)
            tot += 0.5 * wi * lg            # U∈[-1,1] 密度 1/2
        qs[w] = tot + (ur.terminal_liquidation_log(
            w, 0.0) if False else 0.0)
    hold = qs[0.0]
    best_nonzero = max(v for w, v in qs.items()
                       if w != 0.0)
    assert best_nonzero < hold - acc or \
        best_nonzero < -acc   # 严格负优势


def test_must_act_uses_q_diff_not_total_value():
    r = ur.must_act_from_q(0.0, {0.5: 1e-3, -1.0: -1.0})
    assert r["status"] == "act" and r["best_w"] == 0.5
    r2 = ur.must_act_from_q(0.0, {0.5: -1e-3})
    assert r2["status"] == "no_act"
    r3 = ur.must_act_from_q(0.0, {})
    assert r3["status"] == "not_established"
    r4 = ur.must_act_from_q(
        0.0, {0.5: float("nan")})
    assert r4["status"] == "unstable"
    # 近优点集为离散清单(非凸包)
    r5 = ur.must_act_from_q(
        0.0, {0.5: 1e-3, 0.45: 1e-3 - 1e-15, -1: -1})
    assert isinstance(r5["near_opt_points"], list)


def test_query_contract_and_cache_key():
    q = dict(ur.QUESTIONS[0])
    mq = ur.make_query(q)
    assert set(mq) == {"s", "c", "q", "g", "remaining",
                       "total", "account"}
    bad = dict(q, future_return=0.1)
    with pytest.raises(ValueError):
        ur.make_query(bad)
    bad2 = dict(q, remaining=40)
    with pytest.raises(ValueError):
        ur.make_query(bad2)
    k1 = ur.cache_key("G001", 0.0, 0.5, "L0")
    k2 = ur.cache_key("G001", 0.1, 0.5, "L0")
    k3 = ur.cache_key("G001", 0.0, 0.25, "L0")
    k4 = ur.cache_key("G001", 0.0, 0.5, "L1")
    assert len({k1, k2, k3, k4}) == 4   # 坐标/档全入键


def test_status_prepared_and_gates_unspecified():
    assert ur.STATUS == "prepared_not_run"
    from rl_posctl.skill_p0 import unified_course as uc
    for v in uc.SEVEN_SKILLS.values():
        assert v["gate_status"] == "not_specified"
    assert uc.REGISTRY_GATES == {}
