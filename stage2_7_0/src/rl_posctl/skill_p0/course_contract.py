# -*- coding: utf-8 -*-
"""课程契约(版本化,机器可读)— COURSE_CONTRACT_OFFLINE_V1。

复用 p0spec/p0eval/curriculum 既有常数与网格定义;本模块只做
绑定与校验,不含任何模型前向/环境 step/训练/bank 生成。

语义约定(与既有验收一致):
- 技能 fail = 有效证据不达标(报告如实给出);
- invalid = 格式/身份/版本错误(非静默,进程非零退出);
- 带仓中性处理 = not_specified(不套 flat 门);
- 净 log 权益 = 现有训练奖励;收益仅辅助诊断(不作门)。
"""
from __future__ import annotations

import math
from pathlib import Path

CONTRACT_VERSION = "COURSE_CONTRACT_V1"

# 来源绑定(候选 commit;12 模块 blob 全等核验由入口执行)
CANDIDATE_COMMIT = ("3a241c4932476e3c9dfb2ebd5c94b"
                    "b4f9cf41938")
CODE_PATHS = {
    "p0spec": "src/rl_posctl/skill_p0/p0spec.py",
    "p0eval": "src/rl_posctl/skill_p0/p0eval.py",
    "curriculum": "src/rl_posctl/curriculum.py",
    "env": "src/rl_posctl/env.py",
    "p0registry": "src/rl_posctl/skill_p0/p0registry.py",
}


class ContractError(Exception):
    """invalid 级错误(格式/身份/版本)。"""


def expected_conditions() -> list:
    """108 条件(flat 反事实;来自 p0spec.BEHAVIOR_GRID)。"""
    from rl_posctl.skill_p0.p0spec import BEHAVIOR_GRID
    rows = []
    for s in (-1.0, 0.0, 1.0):
        for c in BEHAVIOR_GRID["c"]:
            for q in BEHAVIOR_GRID["q"]:
                for g in BEHAVIOR_GRID["g"]:
                    for rem in BEHAVIOR_GRID["remaining"]:
                        rows.append((float(s), float(c),
                                     float(q), float(g), int(rem)))
    return rows


def build_contract() -> dict:
    """机器可读契约(全量;入口会原样嵌入报告)。"""
    from rl_posctl.skill_p0 import p0spec as spec
    conds = expected_conditions()
    n_neutral = sum(1 for c in conds if c[0] == 0.0)
    return {
        "contract_version": CONTRACT_VERSION,
        "candidate_commit": CANDIDATE_COMMIT,
        "code_paths": dict(CODE_PATHS),
        "c1": {
            "course_id": "c1",
            "feature_order": ["c", "g", "q", "s"],
            "obs_dim": 8,
            "obs_layout": ("[c,g,q,s, asinh(exposure)/4, "
                           "asinh(solvency)/4, "
                           "remaining/128, horizon/128]"),
            "obs_spec_version": "PosctlObsP0Time-v1",
            "horizon": 64,
            "synthetic_visible_signal": "s(决策 bar 可观测;"
                                        "驱动下一 bar 收益)",
            "causal_timing": ("decision close[t] -> exec "
                              "open[t+1] -> settle close[t+1]"),
            "initial_state_gate": "flat counterfactual "
                                  "(exposure=0, solv cap 40)",
            "grid_conditions": len(conds),
            "neutral_conditions": n_neutral,
            "direction_gate": {
                "metric": "min-over-grid p_rebal_up(s=+1) "
                          "/ p_rebal_down(s=-1)",
                "threshold": float(
                    spec.BEHAVIOR_MIN_P_DIRECTIONAL),
                "amplitude_edge": float(spec.BEHAVIOR_W_MIN),
                "semantics": "min_over_grid"},
            "neutral_gate": {
                "metric": "min-over-grid p_neutral_band(s=0)",
                "threshold": float(
                    spec.BEHAVIOR_MIN_P_NEUTRAL),
                "band": float(spec.BEHAVIOR_W_NEUTRAL),
                "semantics": "min_over_grid",
                "initial_state": "flat_only"},
            "held_position_neutral": "not_specified",
            "objective": ("net log equity "
                          "(env.py:466-467;训练奖励)"),
            "returns_role": "auxiliary_diagnostic_only"},
        "other_courses": {
            "c2": {"course_id": "c2",
                   "drift_factor": "s*c*mu_max",
                   "gates": "not_specified",
                   "promotion": "not_specified"},
            "c3": {"course_id": "c3",
                   "drift_factor": "s*c*q*mu_max*0.5",
                   "gates": "not_specified",
                   "note": "q 条件化漂移(q∈Q_LEVELS 改变有效"
                           "信号幅度);幅度相关条件化已在"
                           "课程体系内存在",
                   "promotion": "not_specified"},
            "c4d0": {"course_id": "c4d0",
                     "drift_factor": "s*q*mu_max",
                     "gates": "not_specified",
                     "note": "同上:q 条件化漂移",
                     "promotion": "not_specified"},
            "c4d1": {"course_id": "c4d1",
                     "drift_factor": "s*c*q*mu_max",
                     "gates": "not_specified",
                     "promotion": "not_specified"},
            "c4d2": {"course_id": "c4d2",
                     "drift_factor": "s*c*q*mu_max",
                     "gates": "not_specified",
                     "promotion": "not_specified"},
            "c4d3": {"course_id": "c4d3",
                     "drift_factor": "s*c*q*mu_max",
                     "gates": "not_specified",
                     "promotion": "not_specified"}},
        "status_semantics": {
            "pass": "有效证据达标",
            "fail": "有效证据不达标(如实报告)",
            "invalid": "格式/身份/版本错误(非零退出)",
            "not_specified": "契约未规定;不得自创门"}}


def validate_grid_rows(rows, *, contract_version,
                       expect_model) -> dict:
    """grid 行校验;任何违规抛 ContractError(invalid)。

    校验:版本、单 model(拒绝混档)、精确 108 条件集(缺/重)、
    概率有限、obs 布局 cgqs+8 维、flat 初态。
    """
    if contract_version != CONTRACT_VERSION:
        raise ContractError(
            "unknown contract version %r" % (
                contract_version,))
    if not isinstance(rows, list):
        raise ContractError("grid rows not a list")
    models = {r.get("model") for r in rows}
    if None in models or len(models) != 1:
        raise ContractError(
            "mixed or missing model field: %r" % models)
    if models.pop() != expect_model:
        raise ContractError("model != expected tier model")
    want = {c for c in expected_conditions()}
    got = []
    for r in rows:
        try:
            key = (float(r["s"]), float(r["c"]),
                   float(r["q"]), float(r["g"]),
                   int(r["remaining"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise ContractError(
                "bad condition fields %r: %r" % (r, exc))
        got.append(key)
        for p in ("p_rebal_up", "p_rebal_down",
                  "p_neutral_band"):
            v = r.get(p)
            if not (isinstance(v, (int, float))
                    and math.isfinite(float(v))):
                raise ContractError(
                    "non-finite %s=%r at %r" % (p, v, key))
        obs = r.get("obs")
        if not isinstance(obs, list) or len(obs) != 8:
            raise ContractError("obs dim != 8 at %r" % (key,))
        # 布局:前 4 = [c,g,q,s];第 5 = asinh(exposure)/4
        # (flat=0.0);第 6 = asinh(solv)/4(上限 40)
        if any(abs(obs[i] - v) > 1e-6 for i, v in (
                (0, float(r["c"])), (1, float(r["g"])),
                (2, float(r["q"])), (3, float(r["s"])))):
            raise ContractError(
                "obs layout not [c,g,q,s] at %r: %r"
                % (key, obs[:4]))
        if abs(float(obs[4])) > 1e-6:
            raise ContractError(
                "non-flat initial exposure in obs[4]=%r "
                "at %r (gate semantics is flat-only)"
                % (obs[4], key))
        if abs(float(obs[5])
               - math.asinh(40.0) / 4.0) > 1e-6:
            raise ContractError(
                "solvency slot not flat-cap at %r" % (key,))
    if len(got) != len(set(got)):
        seen, dup = set(), []
        for k in got:
            (dup.append(k) if k in seen else seen.add(k))
        raise ContractError(
            "duplicate conditions: %r" % dup[:4])
    if set(got) != want:
        missing = sorted(want - set(got))[:4]
        extra = sorted(set(got) - want)[:4]
        raise ContractError(
            "condition set mismatch: missing=%r extra=%r"
            % (missing, extra))
    return {"conditions": len(got), "model": expect_model}


def skill_eval(rows) -> dict:
    """min-over-grid 三技能(纯数据;fail=有效不达标)。"""
    from rl_posctl.skill_p0 import p0spec as spec
    up = [r for r in rows if float(r["s"]) == 1.0]
    dn = [r for r in rows if float(r["s"]) == -1.0]
    ne = [r for r in rows if float(r["s"]) == 0.0]

    def worst(cells, key):
        w = min(cells, key=lambda r: float(r[key]))
        return float(w[key]), (float(w["s"]), float(w["c"]),
                               float(w["q"]), float(w["g"]),
                               int(w["remaining"]))

    v_up, c_up = worst(up, "p_rebal_up")
    v_dn, c_dn = worst(dn, "p_rebal_down")
    v_ne, c_ne = worst(ne, "p_neutral_band")
    th_d = float(spec.BEHAVIOR_MIN_P_DIRECTIONAL)
    th_n = float(spec.BEHAVIOR_MIN_P_NEUTRAL)
    return {
        "direction_up": {"min": v_up, "worst_condition":
                         list(c_up), "threshold": th_d,
                         "status": ("pass" if v_up >= th_d
                                    else "fail")},
        "direction_down": {"min": v_dn,
                           "worst_condition": list(c_dn),
                           "threshold": th_d,
                           "status": ("pass" if v_dn >= th_d
                                      else "fail")},
        "neutral_flat": {"min": v_ne,
                         "worst_condition": list(c_ne),
                         "threshold": th_n,
                         "status": ("pass" if v_ne >= th_n
                                    else "fail")},
        "held_position_neutral": "not_specified"}
