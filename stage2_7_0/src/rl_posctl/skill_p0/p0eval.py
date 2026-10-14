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
    BASELINE_NAMES, BEHAVIOR_GRID, BEHAVIOR_MIN_P_DIRECTIONAL,
    BEHAVIOR_MIN_P_NEUTRAL, BEHAVIOR_W_MIN, BEHAVIOR_W_NEUTRAL,
    BOOTSTRAP_ALPHA, BOOTSTRAP_DRAWS, BOOTSTRAP_MODES, C1_FEE,
    FUNDING_SCHEDULE, INITIAL_CASH, MAINTENANCE_MARGIN, REWARD_SCALE)

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


def _validate_bank_items(items) -> None:
    """全部 item 的 pair/variant 身份完整性校验(R2/C2)。

    在任何预约/环境构造/经济工作之前执行:每个 item 须为长度 ≥3
    的序列,item[2] 含 pair_index(int≥0)与 variant(int 或非空
    str)。malformed 输入在此拒绝,不得先创建环境再 KeyError。
    """
    for i, item in enumerate(items):
        try:
            n = len(item)
        except TypeError:
            n = -1
        if n < 3:
            raise ValueError(
                f"eval_on_bank: item[{i}] 结构非法(须 "
                f"(prices, feats, meta) 三元组):{item!r}")
        meta = item[2]
        if not isinstance(meta, dict):
            raise ValueError(
                f"eval_on_bank: item[{i}].meta 非字典:{meta!r}")
        pi = meta.get("pair_index")
        if isinstance(pi, bool) or not isinstance(pi, int) or pi < 0:
            raise ValueError(
                f"eval_on_bank: item[{i}] 缺/非法 pair_index"
                f"({pi!r};须 int≥0),在预约/工作前拒绝")
        var = meta.get("variant")
        if (isinstance(var, bool) or not isinstance(var, (int, str))
                or var == "" or var is None):
            raise ValueError(
                f"eval_on_bank: item[{i}] 缺/非法 variant"
                f"({var!r};须 int 或非空 str),在预约/工作前拒绝")


def eval_on_bank(items, action_fn, *, ledger=None, tag: str = "",
                 raw_sink=None, env_factory=None, runner=None,
                 summarizer=None) -> list:
    """逐 episode 重放(先校验+唯一预约 → 执行 → 按实际结算)。

    R1/F2 修复:旧版先 make_env→run_policy→summarize(整个工作叶
    已发生)再 reserve/commit;额度不足时工作已被执行。新次序:
      1) 输入校验(items 非空/action_fn 可调/上界可计算/**全部
         item 的 pair/variant 身份完整**)在任何资源或工作之前
         (R2/C2:缺 pair_index/variant 的 malformed 输入在预约、
         建环境、经济工作之前拒绝,不得先建环境再 KeyError);
      2) 唯一一次预约,额度 = 全部 episode 步数上界合计;
      3) 逐 episode 执行;raw_sink 在每个 episode 行产生时立即
         持久化(先于任何聚合使用;行携带 tag/身份/成本/失败);
      4) 按实际观察步数一次性结清;异常 → abandon 保守保留
         (已发生量不归零)。
    env_factory/runner/summarizer 为显式测试注入点(默认真实经济
    环境;替身须明示,不得 mock 掉校验/预约/结算本身)。
    """
    if not items:
        raise ValueError("eval_on_bank: items 为空,拒绝执行")
    if not callable(action_fn):
        raise TypeError("eval_on_bank: action_fn 不可调用,拒绝执行")
    _validate_bank_items(items)
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
            row = {"episode": i, "tag": str(tag),
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



def bootstrap_results_all_valid_positive(
        boot: dict, *, required_baselines=None,
        required_modes=None) -> bool:
    """臂级 bootstrap 全门判定(R1/F3b + R2/C2:必需结果集合)。

    消费规则:
    - 必需集合(p0spec 冻结的 5 基线 × 2 模式)**必须齐备**:
      删除整基线、整个模式、缺任一 required 键 → 证据不足判败,
      不得宽松遍历仅在场的结果后宣布完整(含从存档报告读入的
      bgate_v2 共享消费端);
    - 每个 result 的 valid 为真且 lower_positive 为真;缺 valid
      一律判败(无证据 ≠ 通过;空集合判败);
    - 出现集合外的多余基线/模式同样判败(结果集合必须精确)。
    """
    req_b = tuple(required_baselines or BASELINE_NAMES)
    req_m = tuple(required_modes or BOOTSTRAP_MODES)
    if not isinstance(boot, dict):
        return False
    if set(boot) != set(req_b):
        return False
    for b in req_b:
        per_mode = boot[b]
        if not isinstance(per_mode, dict) or set(per_mode) != set(req_m):
            return False
        for m in req_m:
            r = per_mode[m]
            if not isinstance(r, dict):
                return False
            if r.get("valid") is not True:
                return False
            if r.get("lower_positive") is not True:
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
def _row_identity(row, where: str):
    """行身份 (pair_index, variant);缺失/非法即拒绝(R2/C2)。"""
    if not isinstance(row, dict):
        raise ValueError(f"{where}: 行非字典 {row!r}")
    pi = row.get("pair_index")
    var = row.get("variant")
    if isinstance(pi, bool) or not isinstance(pi, int):
        raise ValueError(
            f"{where}: 行缺/非法 pair_index({pi!r})")
    if isinstance(var, bool) or not isinstance(var, (int, str)):
        raise ValueError(
            f"{where}: 行缺/非法 variant({var!r})")
    return (int(pi), var)


def _row_value_ok(row, where: str):
    """行有效性/数值核验:失败标记如实拒绝,NaN/None 拒绝,
    不静默消费带经济失败/无效奖励的有限数值(不删失败分母)。"""
    if row.get("economic_failure") is True:
        return (False, f"{where}: episode {row.get('episode')}"
                " economic_failure=True(失败分母保留,不删除)")
    if row.get("reward_valid") is False:
        return (False, f"{where}: episode {row.get('episode')}"
                " reward_valid=False")
    v = row.get("net_log_return")
    if v is None:
        return (False, f"{where}: episode {row.get('episode')}"
                " 经济失败(net_log_return=None)")
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return (False, f"{where}: episode {row.get('episode')}"
                f" net_log_return 非数值({v!r})")
    if not math.isfinite(float(v)):
        return (False, f"{where}: episode {row.get('episode')}"
                f" net_log_return 非有限({v!r};缺样本/NaN)")
    return (True, float(v))


def pair_advantage_matrix(model_rows: dict, baseline_rows: list) -> dict:
    """model_rows:{model_key: rows};baseline rows 同 bank。

    R2/C2:配对按 (pair_index, variant) 身份**显式对齐**,不做
    位置默认匹配:
    - baseline 身份重复/缺失即拒绝;每个模型的身份集合必须与
      baseline 完全一致(pair_index=999、variant 错值、行序重排
      中的错配 → 拒绝;行序重排但身份一致 → 正确映射,结果不变);
    - 行有效性:economic_failure/reward_valid/None/NaN 在配对前
      拒绝(失败分母保留在 reason,不删除、不给有效值);
    - pair_value[p] = mean_models(mean_endpoints(netlog_model
      − netlog_baseline)),数学与 R1 一致(仅在身份对齐后计算)。
    行数不一致仍为结构错误(ValueError)。
    """
    keys = sorted(model_rows)
    n_eps = len(baseline_rows)
    if not baseline_rows:
        return {"valid": False, "reason": "baseline 行为空(无证据)"}
    for k in keys:
        rows = model_rows[k]
        if rows is None:
            return {"valid": False, "reason":
                    f"缺必需模型行 {k}(种子缺失/RUN_INVALID;"
                    "必需结果集合不齐备,不得跳过)"}
        if not isinstance(rows, list):
            raise ValueError(f"{k} 行集非列表:{rows!r}")
        if len(rows) != n_eps:
            raise ValueError(f"{k} 行数 {len(rows)} != {n_eps}")
    base_ids = {}
    for idx, r in enumerate(baseline_rows):
        rid_ = _row_identity(r, f"baseline[{idx}]")
        if rid_ in base_ids:
            return {"valid": False, "reason":
                    f"baseline 身份重复 {rid_}"
                    f"(episodes {base_ids[rid_]} 与 {idx})"}
        base_ids[rid_] = idx
    base_vals = {}
    for idx, r in enumerate(baseline_rows):
        rid_ = _row_identity(r, f"baseline[{idx}]")
        ok, val = _row_value_ok(r, f"baseline[{rid_}]")
        if not ok:
            return {"valid": False, "reason": val}
        base_vals[rid_] = val
    per_model = {}
    for k in keys:
        m_map = {}
        for idx, r in enumerate(model_rows[k]):
            rid_ = _row_identity(r, f"{k}[{idx}]")
            if rid_ in m_map:
                return {"valid": False, "reason":
                        f"{k} 身份重复 {rid_}"
                        f"(episodes {m_map[rid_]} 与 {idx})"}
            m_map[rid_] = idx
        missing = [x for x in base_ids if x not in m_map]
        extra = [x for x in m_map if x not in base_ids]
        if missing or extra:
            return {"valid": False, "reason":
                    f"{k} 配对身份不一致(缺失 {missing[:4]} / "
                    f"多余 {extra[:4]};须显式按 (pair_index,"
                    "variant) 对齐,不做位置匹配)"}
        vals = {}
        for idx, r in enumerate(model_rows[k]):
            rid_ = _row_identity(r, f"{k}[{idx}]")
            ok, val = _row_value_ok(r, f"{k}[{rid_}]")
            if not ok:
                return {"valid": False, "reason": val}
            vals[rid_] = val - base_vals[rid_]
        per_model[k] = vals
    pairs = {}
    for rid_ in base_ids:
        p = rid_[0]
        pairs.setdefault(p, []).append(
            sum(per_model[k][rid_] for k in keys) / len(keys))
    pair_vals = []
    for p in sorted(pairs):
        if len(pairs[p]) != 2:
            return {"valid": False, "reason":
                    f"pair {p} 端点数 {len(pairs[p])} != 2"
                    "(缺端点/重复端点,必需端点集合不齐备)"}
        pair_vals.append(sum(pairs[p]) / len(pairs[p]))
    return {"valid": True, "pair_values": pair_vals,
            "n_pairs": len(pair_vals),
            "identities": [list(x) for x in base_ids]}


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
