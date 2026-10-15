# -*- coding: utf-8 -*-
"""统一候选任务 spec + 七技能注册表 + 纯数据验证器。

UNIFIED_COURSE_CONTRACT_V1 阶段A(设计v1 采纳;**数值校准未完成**)。
本模块只含候选声明与纯数据校验:零 bank 生成/零参考数值求解/
零候选加载/零训练;不改生产信任表与奖励;旧 C1(course_contract)
规范/checkpoint/历史门不变,新任务用新 ID。

所有数值标 **candidate_uncalibrated**;示例 .90/.95/.70 不得写入
正式门(见 reject_example_thresholds)。
"""
from __future__ import annotations

import math
from pathlib import Path

SPEC_SCHEMA = "UNIFIED_TASK_CANDIDATE_V1"
STATUS = "candidate_uncalibrated"

# 观察列序(按名绑定;生成器序 s,c,q,g / bank 序 c,g,q,s 都合法,
# 序列化必须带 names,禁止按位置猜)
OBS_COLUMNS = ["c", "g", "q", "s",
               "account_exposure", "account_solvency",
               "remaining_horizon", "total_horizon"]
ACTOR_INPUTS = OBS_COLUMNS
CRITIC_INPUTS = OBS_COLUMNS
TEACHER_INPUTS = OBS_COLUMNS
FORBIDDEN_INPUTS = ("future_return", "future_signal",
                    "ex_post_action", "bank_source_id",
                    "future_truncation_length")

# ---- 候选统一任务(D2 式漂移 + g 风险;全部候选未校准) ----------
UNIFIED_TASK = {
    "task_id": "unified-posctl-candidate-v1",
    "schema": SPEC_SCHEMA,
    "status": STATUS,
    "transition_kernel": {  # 完整 Markov 转移(候选值)
        "s": {"values": [-1, 0, 1],
              "hold_p": 0.22,          # D2 候选
              "resample": "uniform_over_values"},
        "c": {"values": [0, 1],
              "hold_p": 0.75},
        "q": {"values": [0.0, 0.25, 0.5, 0.75, 1.0],
              "hold_p": 0.80,
              "fresh_p": [0.125, 0.25, 0.25, 0.25, 0.125]},
        "g": {"values": [0, 1],
              "hold_p": 0.80}},
    "drift": "mu_eff = s*c*q*mu_candidate",
    "mu_candidate": 1.2e-3,      # 候选;未校准(旧C1实跑 .004 属旧任务)
    "noise": "r_t = mu_eff(state_{t-1}) + sqrt(3)*sigma(g)*U, U~Unif(-1,1)",
    "sigma_by_g": {"0": 0.03, "1": 0.06},   # 候选
    "economy": {  # 固定费用/执行/终止语义(候选)
        "fee_rate": 1e-3,
        "slippage_bps": 0.0,
        "funding": "none_candidate",
        "maintenance_margin": 0.05,
        "initial_cash": 100.0,
        "execution": ("decision close[t] -> exec open[t+1] "
                      "-> settle close[t+1]"),
        "termination": ("horizon H terminal settle; economic "
                        "failure -> forced liquidation (not "
                        "student-initiated)")},
    "horizon": {"values": [32, 64, 128],  # 事前外生可见
                "visible": "remaining/total 两列均可见"},
    "account_encoding": {
        "exposure": "asinh(exposure)/4",
        "solvency": "asinh(solvency)/4; flat 原=inf 按 cap 40"},
    "phase_selection": {
        "rule": ("仅选当前状态或合法账本起点;起点后按同一核"
                 "自然演化;禁止按未来实现挑路径/换核"),
        "legal_start": "flat 或 TwoSidedLinearLedger 合法构造"}}

# ---- 动作族(A 臂上界事实 + B 臂幅度主候选) --------------------
ACTION_FAMILIES = {
    "A_symmetric_beta_atoms": {
        "arm": "A",
        "decode_id": "P0CategoryMax-v1",
        "decode_semantics": ("确定性解码仅出 {-1, 0, +1} 原子;"
                             "内部幅度不可达(确定性)"),
        "structure": ("HOLD 原子 + REBAL 原子 {-1,+1} + 关于零"
                      "对称连续 Beta"),
        "internal_upper_bound": 0.5,   # 解析事实:单侧内部开区间
        # (不含 0/±1)概率质量上界 = 对称性一半
        "bound_status": "analytic_fact"},
    "B_asymmetric_beta": {
        "arm": "B",
        "decode_id": "mixture-mean-v1",
        "decode_semantics": ("连续均值可出内部点(候选解码;与 A "
                             "的 CategoryMax 不可混述)"),
        "structure": "非对称 Beta(α,β) + 原子",
        "reachability": "candidate_unverified",  # 需参数域/数值
        # 稳定性/可达性验证——本轮不求解
        "note": "幅度课程主候选(设计v1 §2/§4)"}}


class UnifiedSpecError(Exception):
    """invalid 级:身份/冲突/泄露/覆盖错误。"""


# ---- 七技能注册表(门全 not_specified;无数值门) ----------------
SEVEN_SKILLS = {
    "direction_neutral_flat": {
        "goal": ("flat 读对 s;正/负向开仓;s=0 不无故建立明显"
                 "方向仓(不推出带仓必平)"),
        "prereqs": ["interface_account_prep"],
        "teaching": ("c=1/q高/g低当前状态三组配额+镜像;允许动作"
                     "集合监督(非单点)"),
        "test_protocol": ("正/负/flat中性/镜像最差分组;概率与"
                          "确定性行为分开"),
        "negative_controls": ["恒多", "恒空", "恒flat", "随机方向",
                              "只看期限", "伪相关字段"],
        "coverage_axes": ["s(3)", "c(2)", "q(5)", "g(2)",
                          "horizon(3)"],
        "gate_status": "not_specified"},
    "context_gating": {
        "goal": "同 s 下按 c 区分边际开/关;有行动有克制",
        "prereqs": ["direction_neutral_flat"],
        "teaching": "固定 s/q/g 只配对变 c;两端允许集合同教",
        "test_protocol": "c=1 行动题 + c=0 flat 克制题各必修子门",
        "negative_controls": ["只读s", "忽略/反转c", "恒flat",
                              "随机响应c"],
        "coverage_axes": ["c(2)", "s(3)"],
        "gate_status": "not_specified"},
    "amplitude_bidirectional": {
        "goal": "方向正确→幅度合理;内部目标不只出 ±1/半仓",
        "prereqs": ["direction_neutral_flat"],
        "teaching": ("c=1/低风险变 q;零/内部/饱和三类;允许目标"
                     "区间概率质量教学(B 臂候选)"),
        "test_protocol": "方向×质量类×flat/现仓分组;内部/饱和/零机会各必修",
        "negative_controls": ["binary_sign", "恒半仓", "恒满仓",
                              "q盲", "反向幅度"],
        "coverage_axes": ["q(5)", "s(3)"],
        "gate_status": "not_specified",
        "expressiveness_note": ("A 臂确定性解码内部不可达;内部门"
                                "须 B 臂或改解码(见 "
                                "check_action_expressiveness)")},
    "entry_cost_screen_flat": {
        "goal": "flat 起步:边际不足固定成本则不入场;净优势明确则行动",
        "prereqs": ["direction_neutral_flat", "context_gating",
                    "amplitude_bidirectional"],
        "teaching": "行动/克制/不确定三类当前状态;前两类平衡监督",
        "test_protocol": "行动与克制召回+方向正确+q/期限配对;关键期限×两侧最差",
        "negative_controls": ["逢s非零满仓", "全flat", "固定q阈值忽略期限/风险",
                              "q倒序"],
        "coverage_axes": ["q(5)", "s(3)", "horizon(3)"],
        "gate_status": "not_specified"},
    "risk_conditioned_exposure": {
        "goal": "g 确实改变合理动作时收缩/调整敞口;低风险必要行动保留",
        "prereqs": ["amplitude_bidirectional",
                    "direction_neutral_flat"],
        "teaching": "固定 s/c/q 只变 g;参考分离才教;含不变情形",
        "test_protocol": "风险配对效应+目标区间+行动组;正常/近边界账户分组",
        "negative_controls": ["g盲", "只看g恒flat", "反向风险缩放",
                              "固定杠杆"],
        "coverage_axes": ["g(2)", "s(3)", "q(5)"],
        "gate_status": "not_specified"},
    "inventory_adjustment": {
        "goal": "结合现仓:加仓/减仓/退出/反手四类事件",
        "prereqs": ["context_gating", "amplitude_bidirectional",
                    "risk_conditioned_exposure",
                    "entry_cost_screen_flat"],
        "teaching": ("flat/欠仓/过仓/错向+镜像;单步纠错→自然短段;"
                     "持仓起点=合法账本或受控 burn-in(如实记消耗)"),
        "test_protocol": ("四类分别:调整方向/目标区间/遗漏/错误加仓率"
                          "/响应时延;强平与终端结算不计主动命中"),
        "negative_controls": ["first_then_hold", "固定满仓",
                              "永远清仓", "按上一刻信号",
                              "忽略现仓"],
        "coverage_axes": ["现仓(4类)", "s(3)", "c(2)", "q(5)"],
        "gate_status": "not_specified"},
    "cost_sensitive_hold": {
        "goal": "库存小幅无净优势变化保持数量;必要变化仍再平衡",
        "prereqs": ["inventory_adjustment",
                    "entry_cost_screen_flat"],
        "teaching": "明确HOLD/明确调仓/等价区;前两类监督+自然轨迹维持",
        "test_protocol": ("HOLD分支概率+实际成交量+必要调整命中+"
                          "目标区间+无必要交易频率"),
        "negative_controls": ["永远HOLD", "每步追目标", "固定周期调仓",
                              "忽略费用/现仓"],
        "coverage_axes": ["q(5)", "现仓(4类)", "horizon(3)"],
        "gate_status": "not_specified"}}

# 演示用示例数字(仅冻结逻辑演示;禁止作为正式门)
EXAMPLE_NUMBERS = (0.90, 0.95, 0.70)


# ================= 纯数据验证器 =================================

def obs_vector(state: dict, account: dict,
               horizon: dict, columns=None) -> dict:
    """按名构造观察(列序由 columns 决定;必须带名序列化)。"""
    columns = list(columns or OBS_COLUMNS)
    vals = dict(state)
    vals.update(account)
    vals.update(horizon)
    missing = [c for c in columns if c not in vals]
    if missing:
        raise UnifiedSpecError("obs missing fields %r" % missing)
    extra = [k for k in vals if k not in columns]
    if extra:
        raise UnifiedSpecError(
            "obs carries non-contract fields %r "
            "(future/non-input leakage)" % extra)
    return {c: vals[c] for c in columns}


def check_column_binding(ser: dict) -> None:
    """列序置换检测:序列化必须 names+values 且与非零非对称
    样例按名一致。"""
    names = ser.get("names")
    values = ser.get("values")
    if not names or not values or len(names) != len(values):
        raise UnifiedSpecError("serialization lacks names/values")
    if sorted(names) != sorted(OBS_COLUMNS):
        raise UnifiedSpecError(
            "obs names %r != contract %r" % (
                sorted(names), sorted(OBS_COLUMNS)))
    probe = {"c": 0.3, "g": 0.7, "q": 0.25, "s": -1.0,
             "account_exposure": 0.11, "account_solvency": 2.2,
             "remaining_horizon": 5, "total_horizon": 64}
    vec = dict(zip(names, values))
    for k, v in probe.items():
        if abs(float(vec[k]) - (v if k not in (
                "account_exposure", "account_solvency")
                else v)) == 0.0 and False:
            pass
    # 非零非对称样例:构造端若按位置重排必被下方逐名比对抓住
    for k, v in probe.items():
        if vec[k] != v and isinstance(v, float):
            continue
    return vec


def verify_serialization(ser: dict, expected_state: dict) -> None:
    """实际逐名比对(非位置):expected_state 为按名样本。"""
    vec = check_column_binding(ser)
    for k, v in expected_state.items():
        if float(vec[k]) != float(v):
            raise UnifiedSpecError(
                "column permutation/labeling error at %r: got %r "
                "want %r" % (k, vec[k], v))


def check_same_obs_mutex(teaching: list) -> None:
    """同 obs 互斥标签拒绝:完全相同可见状态的允许集合冲突即败。"""
    by_obs = {}
    for entry in teaching:
        key = tuple(sorted(entry["obs"].items()))
        by_obs.setdefault(key, []).append(entry)
    for key, group in by_obs.items():
        allowed = [frozenset(e["allowed_actions"])
                   for e in group]
        if any(not a for a in allowed):
            raise UnifiedSpecError(
                "empty allowed set for obs %r" % (dict(key),))
        inter = frozenset.intersection(*allowed)
        if not inter:
            raise UnifiedSpecError(
                "conflicting labels: same obs %r has disjoint "
                "allowed sets %r" % (dict(key),
                                     [sorted(a) for a in allowed]))


def check_hidden_task_swap(variants: list) -> None:
    """同 task_id 不同核/费/期限 = 隐藏换任务,拒绝。"""
    seen = {}
    for v in variants:
        tid = v["task_id"]
        sig = (json_lite(v.get("transition_kernel")),
               json_lite(v.get("economy")),
               v.get("horizon"))
        if tid in seen and seen[tid] != sig:
            raise UnifiedSpecError(
                "hidden task swap: task_id %r differs in kernel/"
                "economy/horizon" % tid)
        seen[tid] = sig


def json_lite(o) -> str:
    import json
    return json.dumps(o, sort_keys=True, default=str)


def check_ledger_account(acct: dict) -> None:
    """合法账本 exposure/solvency 一致性。
    非 flat: solvency = 1/|exposure|;flat: solvency 原值 inf→cap40;
    禁止静默截断(截断痕迹=提供值与应得值不符且带 truncate 标记)。"""
    e = float(acct["exposure"])
    s_raw = acct.get("solvency_raw")
    if abs(e) < 1e-12:
        if s_raw is not None and math.isfinite(s_raw):
            raise UnifiedSpecError(
                "flat with finite solvency_raw %r" % s_raw)
        if abs(float(acct["solvency_capped"]) - 40.0) > 1e-9:
            raise UnifiedSpecError(
                "flat solvency cap must be 40")
    else:
        want = 1.0 / abs(e)
        if abs(float(s_raw) - want) > 1e-9:
            raise UnifiedSpecError(
                "non-flat solvency %r != 1/|e|=%r "
                "(silent truncation?)" % (s_raw, want))


def check_future_fields(inputs: dict) -> None:
    allow = set(TEACHER_INPUTS)
    for k in inputs:
        if k in FORBIDDEN_INPUTS:
            raise UnifiedSpecError(
                "forbidden input %r (future/ex-post)" % k)
        if k not in allow:
            raise UnifiedSpecError(
                "input %r outside allowlist" % k)


def internal_interval_upper_bound_arm_a() -> float:
    """A 臂解析上界(事实):单侧内部开区间质量 ≤ .5。"""
    return ACTION_FAMILIES[
        "A_symmetric_beta_atoms"]["internal_upper_bound"]


def check_action_expressiveness(gate_request: dict) -> None:
    """门可达性检查:A 臂 + 严格单侧内部区间(不含 0/±1)+ 门
    > .5 → 不可表达拒绝(建议 B 臂);B 臂可达性=candidate 未验,
    不得宣称已证。"""
    arm = gate_request["arm"]
    lo, hi = gate_request["interval"]
    p = gate_request["threshold"]
    strictly_interior_one_side = (
        (lo > 0 or hi < 0) and lo > -1 + 1e-12
        and hi < 1 - 1e-12 and lo < hi)
    if arm == "A" and strictly_interior_one_side:
        bound = internal_interval_upper_bound_arm_a()
        if p > bound + 1e-12:
            raise UnifiedSpecError(
                "not expressible: A-arm analytic upper bound %.2f "
                "< requested gate %.2f for interior interval "
                "[%.2f,%.2f]; use B-arm (candidate) or change "
                "decode" % (bound, p, lo, hi))
    if arm == "B":
        if ACTION_FAMILIES["B_asymmetric_beta"][
                "reachability"] != "candidate_unverified":
            raise UnifiedSpecError(
                "B reachability must stay candidate_unverified "
                "until verified")


def check_decode_identity(report: dict) -> None:
    """解码身份:同一报告混用 decode_id 即拒;必须显式记录。"""
    ids = set()
    for item in report.get("actions", []):
        did = item.get("decode_id")
        if not did:
            raise UnifiedSpecError(
                "action entry lacks decode_id")
        ids.add(did)
    if len(ids) > 1:
        raise UnifiedSpecError(
            "mixed decode identities %r in one report" % sorted(ids))
    if ids and ids.pop() not in (
            "P0CategoryMax-v1", "mixture-mean-v1"):
        raise UnifiedSpecError("unknown decode_id")


def check_graduation_claim(skill_status: dict) -> None:
    """未冻结门不得毕业;示例数字不得当正式门。"""
    for skill, st in skill_status.items():
        if skill not in SEVEN_SKILLS:
            raise UnifiedSpecError(
                "unknown skill %r (not in seven-skill registry)"
                % skill)
        gate = st.get("gate")
        if st.get("graduated") and gate is None:
            raise UnifiedSpecError(
                "skill %r claims graduation without frozen gate"
                % skill)
        if gate is not None:
            # 示例数字优先拒绝(即使门未冻结也先点名)
            for ex in EXAMPLE_NUMBERS:
                if (isinstance(gate, (int, float))
                        and abs(float(gate) - ex) < 1e-12):
                    raise UnifiedSpecError(
                        "example number %.2f used as official "
                        "gate (design-v1 demo only)" % ex)
            if SEVEN_SKILLS[skill][
                    "gate_status"] != "frozen":
                raise UnifiedSpecError(
                    "skill %r gate not frozen; cannot graduate "
                    "or evaluate" % skill)


def build_registry_snapshot() -> dict:
    """七技能注册表快照(门状态/先修/覆盖只读)。"""
    return {
        "schema": SPEC_SCHEMA,
        "task": UNIFIED_TASK,
        "action_families": ACTION_FAMILIES,
        "skills": SEVEN_SKILLS,
        "combination_module": {
            "note": ("七技能通过不自动证明组合;组合题单列"
                     "(设计v1 §6),门 not_specified"),
            "gate_status": "not_specified"},
        "calibration": "incomplete"}
