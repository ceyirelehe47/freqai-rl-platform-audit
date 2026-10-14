# -*- coding: utf-8 -*-
"""PSC_P0_v1 评估:episode 重放、固定基线、行为门与配对 bootstrap。

- 经济评估一律走真实账本(evalreport.run_policy/summarize 全量指标,
  失败不删样本不置零);eval_steps 逐 episode 计量。
- 策略接口 = run_policy 原生 (feature_row, exposure_ratio,
  steps_left)(全可观察;模型从 env.get_observation() 取 8 维观察)。
- 行为门概率用**独立积分/原子质量**(scipy.special.betainc 主算,
  numpy 数值求积独立对拍;固定采样核对可选,计入 dist_sample_actions):
    P(REBAL ∧ w≥x) = p_r·[m₊ + m₃·(1 − I_{(1+x)/2}(α,β))]
    P(REBAL ∧ w≤−x) = p_r·[m₋ + m₃·I_{(1−x)/2}(α,β)]
    P(HOLD ∨ |w|≤x) = p_h + p_r·[m₀ + m₃·b₀
                                  + m₃·(I_{(1+x)/2} − I_{(1−x)/2})]
  (原子质量含执行映射合并:±1 边界尾/0 单元;I_x 为正则化不完全
  Beta;A 臂 α=β 同式。)
- bootstrap:pair 内镜像端点聚合 → pair 上模型平均 → 配对重采样
  (10,000 次/项;计入 bootstrap_draws)。
"""

from __future__ import annotations

import math

import numpy as np
import torch as th

from rl_posctl.evalreport import run_policy, summarize
from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv
from rl_posctl.skill_p0.p0spec import (
    BEHAVIOR_GRID, BEHAVIOR_MIN_P_DIRECTIONAL, BEHAVIOR_MIN_P_NEUTRAL,
    BEHAVIOR_W_MIN, BEHAVIOR_W_NEUTRAL, BOOTSTRAP_ALPHA, BOOTSTRAP_DRAWS,
    C1_FEE, FUNDING_SCHEDULE, INITIAL_CASH, MAINTENANCE_MARGIN,
    REWARD_SCALE)

try:                                    # 独立对照库(可选)
    from scipy.special import betainc as _betainc
except ImportError:                     # pragma: no cover
    _betainc = None


def _incbeta_quad(a: float, b: float, x: float, n: int = 200_001
                  ) -> float:
    """I_x(a,b) 数值求积(独立于 scipy 与闭式级数的第三路)。"""
    if x <= 0.0:
        return 0.0
    if x >= 1.0:
        return 1.0
    u = np.linspace(0.0, x, n)
    lnB = math.lgamma(a) + math.lgamma(b) - math.lgamma(a + b)
    with np.errstate(divide="ignore", invalid="ignore"):
        logpdf = ((a - 1.0) * np.log(u) + (b - 1.0)
                  * np.log1p(-u) - lnB)
    pdf = np.where(np.isfinite(logpdf), np.exp(logpdf), 0.0)
    return float(np.trapezoid(pdf, u))


def incbeta(a: float, b: float, x: float) -> float:
    if _betainc is not None:
        return float(_betainc(a, b, x))
    return _incbeta_quad(a, b, x)


# ---------------------------------------------------------------------------
# episode 重放
# ---------------------------------------------------------------------------
def make_env(item) -> P0FiniteTimeEnv:
    prices, feats, _ = item
    return P0FiniteTimeEnv(
        features=feats, prices=prices, fee=C1_FEE, window_size=1,
        funding_schedule=dict(FUNDING_SCHEDULE),
        maintenance_margin=MAINTENANCE_MARGIN,
        initial_cash=INITIAL_CASH, reward_scale=REWARD_SCALE)


def episode_steps_upper_bound(item) -> int:
    """单 episode 重放步数上界(= 价格行数 − 1;决策期恒定)。"""
    prices = item[0]
    return max(0, len(prices) - 1)


def eval_on_bank(items, action_fn, *, ledger=None, tag: str = "",
                 raw_sink=None, env_factory=None, runner=None,
                 summarizer=None) -> list:
    """逐 episode 重放(先校验+唯一预约 → 执行 → 按实际结算)。

    R1/F2 修复:旧版先 make_env→run_policy→summarize(整个工作叶
    已发生)再 reserve/commit;额度不足时工作已被执行。新次序:
      1) 输入校验(items 非空/action_fn 可调/上界可计算)在任何
         资源或工作之前;
      2) 唯一一次预约,额度 = 全部 episode 步数上界合计;
      3) 逐 episode 执行;raw_sink 在每个 episode 行产生时立即
         持久化(先于任何聚合使用);
      4) 按实际观察步数一次性结清;异常 → abandon 保守保留
         (已发生量不归零)。
    env_factory/runner/summarizer 为显式测试注入点(默认真实经济
    环境;替身须明示,不得 mock 掉校验/预约/结算本身)。
    """
    if not items:
        raise ValueError("eval_on_bank: items 为空,拒绝执行")
    if not callable(action_fn):
        raise TypeError("eval_on_bank: action_fn 不可调用,拒绝执行")
    ub_total = sum(episode_steps_upper_bound(it) for it in items)
    _env_factory = env_factory or make_env
    _runner = runner or run_policy
    _summarizer = summarizer or summarize
    rid = None
    if ledger is not None:
        rid = ledger.reserve(f"eval:{tag}", eval_steps=int(ub_total))
    rows = []
    observed = 0
    try:
        for i, item in enumerate(items):
            env = _env_factory(item)
            infos = _runner(
                env, lambda row, ratio, sl: action_fn(
                    env, row, ratio, sl))
            summary = _summarizer(infos)
            steps = summary["n_steps"]
            observed += int(steps)
            row = {"episode": i,
                   "pair_index": item[2]["pair_index"],
                   "variant": item[2]["variant"],
                   "steps": steps, "summary": summary,
                   "net_log_return": summary["net_log_return"],
                   "reward_valid": bool(
                       summary["net_log_return_valid"]),
                   "economic_failure": bool(
                       summary["economic_failure"])}
            if raw_sink is not None:
                raw_sink(row)
            rows.append(row)
    except BaseException as exc:
        if rid is not None:
            ledger.abandon(rid, f"eval:{tag}", note=(
                "eval_on_bank 异常中断,保守保留预约余额;"
                f"observed_steps={observed},reserved_ub="
                f"{int(ub_total)},exc={exc!r}"))
        raise
    if rid is not None:
        ledger.commit(rid, f"eval:{tag}", eval_steps=int(observed))
    return rows


def model_action_fn(model, *, deterministic: bool):
    """模型执行(deterministic=公共解码;sampled=分布采样)。"""
    def fn(env, row, ratio, steps_left):
        obs = env.get_observation()
        act, _ = model.predict(np.asarray(obs)[None, :],
                               deterministic=deterministic)
        return np.asarray(act[0])
    return fn


def constant_action_fn(w: float):
    """固定目标基线:每步 REBALANCE(w)(恒目标,重瞄比例付费)。"""
    def fn(env, row, ratio, steps_left):
        return np.array([1.0, float(w)])
    return fn


def hold_action_fn():
    """flat 基线:HOLD 每步(空仓起步即全程空仓,无费用)。"""
    def fn(env, row, ratio, steps_left):
        return np.array([0.0, 0.0])
    return fn


def sign_action_fn():
    """简单 sign(s) 规则:REBALANCE(s)(s∈{−1,0,+1} 可观察)。"""
    def fn(env, row, ratio, steps_left):
        s = float(row["s"])
        return np.array([1.0, float(np.clip(s, -1.0, 1.0))])
    return fn


def reference_action_fn(ref: dict, spec):
    """同信息数值参考重放:可观察 (s,c,q,g)+账户敞口+剩余步数查
    DP 表执行(教师知道公开转移律;不读未来)。"""
    table = ref["table"]
    grid = ref["grid"]
    from rl_posctl.curriculum import W_GRID

    def fn(env, row, ratio, steps_left):
        state = np.array([row["s"], row["c"], row["q"], row["g"]])
        d = np.abs(table - state).sum(axis=1)
        i = int(np.argmin(d))
        if d[i] > 1e-9:
            raise RuntimeError(f"参考状态不匹配 {state}")
        w_idx = int(np.argmin(np.abs(grid - ratio)))
        pol = ref["policies"].get(int(steps_left))
        if pol is None:
            raise RuntimeError(f"steps_left {steps_left} 超出 DP 表")
        a = pol[i, w_idx]
        if a < 0:
            return np.array([0.0, 0.0])
        return np.array([1.0, float(W_GRID[int(a)])])
    return fn


# ---------------------------------------------------------------------------
# 行为门(反事实网格;独立积分/原子质量)
# ---------------------------------------------------------------------------
def counterfactual_obs(s: float, c: float, q: float, g: float,
                       remaining: int, horizon: int = 64,
                       feature_names=None) -> np.ndarray:
    """空仓反事实观察(exposure=0,solvency 取上限 40;时间两维)。

    feature_names = env 实际特征列序(默认 s,c,q,g)。bank 序列化经
    json sort_keys 实际列为字母序 [c,g,q,s](计划修订 D):门构造必须
    按 env.feature_names 排列,否则信号进错槽位(2026-10-14 confirm
    行为门全数失真的根因;经济评估不受影响——训练/评估同一布局)。"""
    names = list(feature_names or ("s", "c", "q", "g"))
    vals = {"s": s, "c": c, "q": q, "g": g}
    head = [vals[k] for k in names]
    return np.asarray(
        head + [math.asinh(0.0) / 4.0,
                math.asinh(40.0) / 4.0,
                remaining / 128.0, horizon / 128.0],
        dtype=np.float32)


def behavior_grid_obs(feature_names=None) -> list:
    rows = []
    for s in (-1.0, 0.0, 1.0):
        for c in BEHAVIOR_GRID["c"]:
            for q in BEHAVIOR_GRID["q"]:
                for g in BEHAVIOR_GRID["g"]:
                    for rem in BEHAVIOR_GRID["remaining"]:
                        rows.append((s, c, q, g, rem,
                                     counterfactual_obs(
                                         s, c, q, g, rem,
                                         feature_names=feature_names)))
    return rows


def dist_probs(model, obs_batch: np.ndarray) -> dict:
    """分布类别概率(原子合并 + 连续积分;scipy betainc/求积)。"""
    obs = th.as_tensor(np.asarray(obs_batch), dtype=th.float32)
    with th.no_grad():
        view = model.policy.get_distribution(obs)
    dist = view.dist
    p = th.exp(dist.branch_logp).to(th.float64).numpy()
    m = th.exp(dist.mix_logp).to(th.float64).numpy()
    if hasattr(dist, "beta"):
        alpha = dist.alpha.to(th.float64).numpy()
        beta = dist.beta.to(th.float64).numpy()
    else:
        alpha = dist.alpha.to(th.float64).numpy()
        beta = alpha
    out = {
        "p_hold": p[:, 0], "p_rebal": p[:, 1],
        "m": m, "alpha": alpha, "beta": beta,
    }
    if hasattr(dist, "Qlo"):
        out["Qlo"] = dist.Qlo.to(th.float64).numpy()
        out["Qhi"] = dist.Qhi.to(th.float64).numpy()
        out["b0"] = dist.b0.to(th.float64).numpy()
    else:
        out["Qlo"] = out["Qhi"] = dist.Q.to(th.float64).numpy()
        out["b0"] = dist.b0.to(th.float64).numpy()
    return out


def gate_probabilities(model, obs_batch: np.ndarray) -> dict:
    """P(REBAL∧w≥x)/P(REBAL∧w≤−x)/P(HOLD∨|w|≤x)(原子+积分)。"""
    d = dist_probs(model, obs_batch)
    m = d["m"]
    a, b = d["alpha"], d["beta"]
    n = a.shape[0]
    up_c = (1.0 + BEHAVIOR_W_MIN) / 2.0
    dn_c = (1.0 - BEHAVIOR_W_MIN) / 2.0
    neu_hi = (1.0 + BEHAVIOR_W_NEUTRAL) / 2.0
    neu_lo = (1.0 - BEHAVIOR_W_NEUTRAL) / 2.0
    i_up = np.array([incbeta(a[k], b[k], up_c) for k in range(n)])
    i_dn = np.array([incbeta(a[k], b[k], dn_c) for k in range(n)])
    i_nh = np.array([incbeta(a[k], b[k], neu_hi) for k in range(n)])
    i_nl = np.array([incbeta(a[k], b[k], neu_lo) for k in range(n)])
    p_r = d["p_rebal"]
    p_h = d["p_hold"]
    return {
        "p_rebal_up": p_r * (m[:, 2] + m[:, 3] * (1.0 - i_up)),
        "p_rebal_down": p_r * (m[:, 0] + m[:, 3] * i_dn),
        "p_neutral_band": (p_h + p_r * (
            m[:, 1] + m[:, 3] * d["b0"] + m[:, 3] * (i_nh - i_nl))),
    }



def bootstrap_results_all_valid_positive(boot: dict) -> bool:
    """臂级 bootstrap 全门判定(R1/F3b:生产者-消费者一致)。

    消费规则:每个 {baseline: {mode: result}} 的 result 必须
    valid 为真且 lower_positive 为真;**缺 valid 一律判败**
    (旧版生产者不产 valid 而消费者要求 valid → 正例永假断路)。
    空集合判败(无证据 ≠ 通过)。
    """
    if not isinstance(boot, dict) or not boot:
        return False
    for b in boot.values():
        if not isinstance(b, dict) or not b:
            return False
        for m in b.values():
            if not isinstance(m, dict):
                return False
            if m.get("valid") is not True:
                return False
            if m.get("lower_positive") is not True:
                return False
    return True


def behavior_gate(model, *, meter=None, sampled_check: int = 0,
                  feature_names=None) -> dict:
    """行为门:min-over-grid 口径(正负两侧分别;镜像条件即 s=∓)。"""
    rows = behavior_grid_obs(feature_names=feature_names)
    obs = np.stack([r[5] for r in rows])
    gp = gate_probabilities(model, obs)
    s_arr = np.array([r[0] for r in rows])
    long_ok = gp["p_rebal_up"][s_arr == 1.0]
    short_ok = gp["p_rebal_down"][s_arr == -1.0]
    neutral = gp["p_neutral_band"][s_arr == 0.0]
    result = {
        "n_conditions": len(rows),
        "long_min": float(long_ok.min()),
        "long_mean": float(long_ok.mean()),
        "short_min": float(short_ok.min()),
        "short_mean": float(short_ok.mean()),
        "neutral_min": float(neutral.min()),
        "neutral_mean": float(neutral.mean()),
    }
    result["pass_long"] = result["long_min"] >= (
        BEHAVIOR_MIN_P_DIRECTIONAL)
    result["pass_short"] = result["short_min"] >= (
        BEHAVIOR_MIN_P_DIRECTIONAL)
    result["pass_neutral"] = result["neutral_min"] >= (
        BEHAVIOR_MIN_P_NEUTRAL)
    result["pass"] = (result["pass_long"] and result["pass_short"]
                      and result["pass_neutral"])
    if sampled_check > 0:
        th.manual_seed(20261014)
        sel = np.linspace(0, len(rows) - 1, min(
            sampled_check, len(rows))).astype(int)
        # R1/F2:预约在采样执行之前(旧版先采样后计量)
        if meter is not None:
            meter(int(len(sel)))
        for k in sel:
            model.policy.get_distribution(
                th.as_tensor(obs[k][None, :], dtype=th.float32)
            ).sample()
        result["sampled_check_conditions"] = int(len(sel))
    return result


# ---------------------------------------------------------------------------
# 配对 bootstrap
# ---------------------------------------------------------------------------
def pair_advantage_matrix(model_rows: dict, baseline_rows: list) -> dict:
    """model_rows:{model_key: rows};baseline rows 同 bank 顺序。

    pair_value[p] = mean_models(mean_endpoints(netlog_model
    − netlog_baseline))。失败(None)如实返回标记。
    """
    keys = sorted(model_rows)
    n_eps = len(baseline_rows)
    per_model = {}
    for k in keys:
        rows = model_rows[k]
        if len(rows) != n_eps:
            raise ValueError(f"{k} 行数 {len(rows)} != {n_eps}")
        per_model[k] = [r["net_log_return"] for r in rows]
    base = [r["net_log_return"] for r in baseline_rows]
    if any(v is None for v in base):
        return {"valid": False, "reason": "baseline 出现经济失败"}
    pairs = {}
    for idx in range(n_eps):
        p = baseline_rows[idx]["pair_index"]
        vals = []
        for k in keys:
            v = per_model[k][idx]
            if v is None:
                return {"valid": False, "reason":
                        f"{k} 在 episode {idx} 经济失败"}
            vals.append(v - base[idx])
        pairs.setdefault(p, []).append(sum(vals) / len(vals))
    pair_vals = []
    for p in sorted(pairs):
        if len(pairs[p]) != 2:
            return {"valid": False, "reason":
                    f"pair {p} 端点数 {len(pairs[p])} != 2"}
        pair_vals.append(sum(pairs[p]) / len(pairs[p]))
    return {"valid": True, "pair_values": pair_vals,
            "n_pairs": len(pair_vals)}


def paired_bootstrap(pair_values, *, seed: int,
                     draws: int = BOOTSTRAP_DRAWS,
                     meter=None, raw_sink=None,
                     rng_factory=None) -> dict:
    """配对 bootstrap(R1/F3b:生产者显式 valid 语义 + 预约前置)。

    - 输入校验(≥2 个有限数值、draws≥1)在任何采样/预约之前;
      无效 → {"valid": False, "reason": ...},不消耗任何采样额度;
    - meter(预约)在重采样矩阵生成**之前**调用(旧版工作后再计);
    - raw_sink(pair_values/seed/draws/alpha 设置)先于结果写盘,
      读回原件可独立重算汇总;
    - 返回恒含 "valid";消费者(arm gate)对 valid 为假或缺失一律
      判失败,不把缺 valid 默认为有效。
    """
    if (isinstance(draws, bool) or not isinstance(draws, int)
            or draws < 1):
        return {"valid": False,
                "reason": f"draws={draws!r} 非法(须 ≥1)"}
    try:
        vals_in = list(pair_values)
    except TypeError:
        return {"valid": False, "reason": "pair_values 不可迭代"}
    if len(vals_in) < 2:
        return {"valid": False,
                "reason": f"pair 数 {len(vals_in)} < 2,无法重采样"}
    for v in vals_in:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            return {"valid": False,
                    "reason": f"pair 值 {v!r} 非数值"}
        if not math.isfinite(float(v)):
            return {"valid": False,
                    "reason": f"pair 值 {v!r} 非有限(缺样本/无效)"}
    if raw_sink is not None:
        raw_sink({"kind": "bootstrap_input",
                  "pair_values": [float(v) for v in vals_in],
                  "seed": int(seed), "draws": int(draws),
                  "alpha": BOOTSTRAP_ALPHA})
    if meter is not None:
        meter(int(draws))
    factory = rng_factory or np.random.default_rng
    rng = factory(seed)
    vals = np.asarray(vals_in, dtype=np.float64)
    n = vals.shape[0]
    idx = rng.integers(0, n, size=(draws, n))
    means = vals[idx].mean(axis=1)
    lo = float(np.quantile(means, BOOTSTRAP_ALPHA / 2.0))
    hi = float(np.quantile(means, 1.0 - BOOTSTRAP_ALPHA / 2.0))
    return {"valid": True, "reason": None,
            "mean": float(vals.mean()), "ci95_lo": lo,
            "ci95_hi": hi,
            "draws": int(draws), "n_pairs": int(n),
            "lower_positive": bool(lo > 0.0)}


def old_decode_diagnostic(model, obs_batch: np.ndarray) -> np.ndarray:
    """旧 mean/质量差解码(只读附加诊断,不用于 P0 主评分)。"""
    obs = th.as_tensor(np.asarray(obs_batch), dtype=th.float32)
    with th.no_grad():
        view = model.policy.get_distribution(obs)
        return view.dist.mode().numpy()
