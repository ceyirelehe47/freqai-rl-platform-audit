# -*- coding: utf-8 -*-
"""评估与指标(RouteC_PositionControl W4 评价面;R1 修复成本/回撤对账)。

R1 修复(P1:评分漏计真实成本、漏记第一段回撤):
- 费用分类汇总:模型动作费 + 风险平仓费 + 终端清算费 + 资金费,
  并与账本累计(info.fees_cum/funding_cum 末步)总账对账;
- 换手名义量:模型动作 + 风险平仓 + 终端清算全部成交腿;
- 回撤:净值序列**前置初始净值**(infos[0].equity_start)后再取
  峰值——初始至首步末的回撤不再漏记;
- 经济失败:net_log_return/net_return 标记 invalid 并保留失败原因,
  不用截断的部分 log 收益冒充整段;失败分母不隐藏;
- gamma 折扣训练目标与未折扣账本对数分开呈现;不填未知年化前提
  的 Sharpe 年化分。

R2 修复(FiniteRepair R2 / FINDINGS R2-03:资金费现金流符号):
- 旧 total_cost_all_in = fees + funding_total 把带符号现金流
  (负=支出)反向计入——多头付费例净成本被低估、空头收费例被高估
  (reviewer 平价反例:fees=.09995,资金费现金流=-.049975,净值损失
  .149925,旧口径只报 .049975)。
- 新口径:funding_total/funding_cashflow_total=带符号现金流;
  **net_cost = 全部费用 − 资金费现金流**(支付增成本、收到抵扣,
  不伪造"成本必须非负")。分项对账(feess_match/funding_match)
  各自相等不自动推出总成本正确,净成本由平价无滑点例的净值损失
  独立复算(见 test_posctl_r2_costs)。
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np

from rl_posctl.env import HybridPositionEnv


def run_policy(env: HybridPositionEnv, policy_fn):
    """以可观察状态驱动的策略跑一个 episode(无梯度)。

    policy_fn(feat_row_dict, current_ratio, steps_left)
    -> (branch, w)。steps_left = n_rows−1−decision_tick(供有限
    视野 DP 参考取精确解;不用的策略可 *args 吞掉)。
    返回逐步 info 列表(账本原件)。
    """
    obs, _ = env.reset()
    infos = []
    while True:
        t = env._current_tick
        row = env._feature_row(t)
        ratio = env.ledger.exposure_ratio(env._close[t]) \
            if env.ledger.equity(env._close[t]) > 0 else 0.0
        act = policy_fn(row, ratio, env.n_rows - 1 - t)
        obs, r, term, trunc, info = env.step(act)
        infos.append(info)
        if term or trunc:
            break
    return infos

def _leg(i: dict, key: str) -> dict | None:
    v = i.get(key)
    return v if isinstance(v, dict) else None


def summarize(infos: list[dict]) -> dict[str, Any]:
    """把逐步 info 原件汇总成指标;成本/换手全腿计入并对账。"""
    if not infos:
        return {"n_steps": 0, "economic_failure": False,
                "net_log_return": math.nan, "net_return": math.nan}

    eq = np.array([i["equity_end"] for i in infos], dtype=float)
    eq0 = float(infos[0]["equity_start"])
    # 回撤净值序列前置初始净值:覆盖 初始→首步末 的第一段回撤
    eq_series = np.concatenate([[eq0], eq])
    peak = np.maximum.accumulate(eq_series)
    dd = float((1.0 - eq_series / peak).max())

    logret = np.array([i["reward_raw"] for i in infos
                       if i["reward_raw"] is not None], dtype=float)
    n_failed = int(sum(1 for i in infos if not i["reward_valid"]))
    economic_failure = n_failed > 0

    # ---- 费用分类(全部成交腿;HOLD 无费) ----
    model_fees = float(sum(i.get("fee") or 0.0 for i in infos))
    risk_fees, term_fees, extra_fees = 0.0, 0.0, 0.0
    risk_turnover, term_turnover, extra_turnover = 0.0, 0.0, 0.0
    n_risk, n_extra = 0, 0
    for i in infos:
        ra = _leg(i, "risk_action")
        if ra is not None and ra.get("fee") is not None:
            risk_fees += float(ra["fee"])
            risk_turnover += abs(float(ra["signed_qty"])) * float(
                ra["exec_price"])
            n_risk += 1
        tl = _leg(i, "terminal_liquidation")
        if tl is not None and tl.get("fee") is not None:
            term_fees += float(tl["fee"])
            term_turnover += abs(float(tl["signed_qty"])) * float(
                tl["exec_price"])
        for ex in i.get("extra_risk_fills") or []:
            extra_fees += float(ex["fee"])
            extra_turnover += abs(float(ex["signed_qty"])) * float(
                ex["exec_price"])
            n_extra += 1
    # 资金费现金流(带符号;负=账户支出,正=收到入账;与账本
    # settle_funding 的 payment 口径一致)
    funding_cashflow = float(sum(
        i.get("funding_payment") or 0.0 for i in infos))

    # ---- 总账对账(vs 账本累计;末步 info 携带) ----
    fees_cum = infos[-1].get("fees_cum")
    funding_cum = infos[-1].get("funding_cum")
    report_total_fees = model_fees + risk_fees + term_fees + extra_fees
    recon: dict[str, Any] = {
        "report_total_fees": report_total_fees,
        "ledger_fees_cum": (float(fees_cum)
                            if fees_cum is not None else None),
        "report_funding_cashflow": funding_cashflow,
        "ledger_funding_cum": (float(funding_cum)
                               if funding_cum is not None else None),
    }
    if fees_cum is not None:
        recon["fees_match"] = bool(math.isclose(
            report_total_fees, float(fees_cum),
            rel_tol=1e-9, abs_tol=1e-12))
    if funding_cum is not None:
        recon["funding_match"] = bool(math.isclose(
            funding_cashflow, float(funding_cum),
            rel_tol=1e-9, abs_tol=1e-12))

    # ---- 净成本(R2-03 符号修正) ----
    # 净成本 = 全部费用 − 资金费现金流:
    #   支付资金费(现金流<0)增加成本;收到资金费(现金流>0)抵扣
    # 成本——不伪造"所有成本必须非负"(空头持续收资金费可使净成本
    # 为负=净收益)。费用按实际成交价计(方向不利滑点/tick 取整已含
    # 在 exec_price 内,净值口径与费用口径不重复计)。
    net_cost = report_total_fees - funding_cashflow

    # ---- 换手(全腿) ----
    model_turnover = float(sum(
        abs(i.get("signed_qty") or 0.0) * (i.get("exec_price") or 0.0)
        for i in infos))
    turnover = model_turnover + risk_turnover + term_turnover \
        + extra_turnover

    # ---- 行为 ----
    flips = int(sum(
        1 for i in infos
        if (i.get("signed_qty") or 0.0) != 0.0
        and i.get("fill_kind") == "rebalance"
        and (i["qty"] * (i["qty"] - i["signed_qty"])) < 0))
    holds = sum(1 for i in infos if i["action_branch"] == 0)
    exposure = [abs(i["exposure_ratio_close"])
                for i in infos if i["exposure_ratio_close"] is not None]
    signed = [i["exposure_ratio_close"]
              for i in infos if i["exposure_ratio_close"] is not None]

    out: dict[str, Any] = {
        "final_equity": float(eq[-1]),
        "initial_equity": eq0,
        # 经济失败时整段 log 收益不可解释:主字段 None + valid=False,
        # 部分和单独保留(不隐藏失败分母,不用截断段冒充整段)
        "net_log_return": (float(logret.sum())
                           if len(logret) and not economic_failure
                           else None),
        "net_log_return_valid": not economic_failure,
        "net_return": (float(eq[-1] / eq0 - 1.0)
                       if (eq0 != 0.0 and not economic_failure)
                       else None),
        "net_return_valid": not economic_failure,
        "net_log_return_partial_sum": (float(logret.sum())
                                       if len(logret) else None),
        "max_drawdown": dd,
        "max_drawdown_includes_initial": True,
        "logret_vol_per_step": (float(logret.std(ddof=1))
                                if len(logret) > 1 else math.nan),
        "total_fees": report_total_fees,
        "model_action_fees": model_fees,
        "risk_action_fees": risk_fees,
        "terminal_liquidation_fees": term_fees,
        "extra_risk_fees": extra_fees,
        "funding_total": funding_cashflow,
        # 资金费现金流(带符号;负=支出/正=收到;旧字段名保留为
        # 现金流口径,勿再当"正值成本"相加——R2-03 符号修正)
        "funding_cashflow_total": funding_cashflow,
        "net_cost": net_cost,
        "net_cost_definition": (
            "model_action_fees+risk_action_fees"
            "+terminal_liquidation_fees+extra_risk_fees"
            "-funding_cashflow_total;费用按实际成交价(含滑点/tick)"
            "计,不与净值口径重复"),
        "turnover_notional": turnover,
        "model_action_turnover": model_turnover,
        "risk_action_turnover": risk_turnover,
        "terminal_liquidation_turnover": term_turnover,
        "n_risk_actions": n_risk,
        "n_extra_risk_fills": n_extra,
        "n_open_risk_actions": int(sum(
            1 for i in infos if i.get("open_risk_triggered"))),
        "n_flips": flips,
        "hold_share": holds / max(1, len(infos)),
        "mean_abs_exposure": float(np.mean(exposure)) if exposure else 0.0,
        "mean_signed_exposure": float(np.mean(signed)) if signed else 0.0,
        "n_steps": len(infos),
        "n_reward_invalid_steps": n_failed,
        "economic_failure": economic_failure,
        "economic_failure_reasons": [
            i["economic_failure"]["reason"] for i in infos
            if i.get("economic_failure")],
        "reconciliation": recon,
    }
    return out
