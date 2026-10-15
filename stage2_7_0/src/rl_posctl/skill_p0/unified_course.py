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
OBS_COLUMNS = ("c", "g", "q", "s",
               "account_exposure", "account_solvency",
               "remaining_horizon", "total_horizon")  # tuple 不可变
ACTOR_INPUTS = OBS_COLUMNS
CRITIC_INPUTS = OBS_COLUMNS
TEACHER_INPUTS = OBS_COLUMNS

# 接口版本(候选;校准未完成)
SPEC_VERSIONS = {
    "obs": "PosctlObsUnified-candidate-v1",
    "reward": "net-log-equity-v1-candidate",
    "action": "action-v1-candidate",
    "execution": "execution-v1-candidate"}
FORBIDDEN_INPUTS = ("future_return", "future_signal",
                    "ex_post_action", "bank_source_id",
                    "future_truncation_length")

# ---- 候选统一任务(D2 式漂移 + g 风险;全部候选未校准) ----------
UNIFIED_TASK = {
    "task_id": "unified-posctl-candidate-v1",
    "schema": SPEC_SCHEMA,
    "status": STATUS,
    "transition_kernel": {  # 完整 Markov 转移(候选值;语义精确:
        # D2 候选=重抽概率 .22 → hold=.78;校准未完成不影响语义)
        "s": {"values": [-1, 0, 1],
              "hold_p": 0.78, "resample_p": 0.22,
              "resample_dist": "uniform_over_values"},
        "c": {"values": [0, 1],
              "hold_p": 0.75, "resample_p": 0.25,
              "resample_dist": "uniform_over_{0,1}"},
        "q": {"values": [0.0, 0.25, 0.5, 0.75, 1.0],
              "hold_p": 0.80,
              "fresh_p": [0.125, 0.25, 0.25, 0.25, 0.125],
              "resample_dist": "fresh_p_over_5_levels"},
        "g": {"values": [0, 1],
              "hold_p": 0.80, "resample_p": 0.20,
              "resample_dist": "uniform_over_{0,1}"}},
    "drift": "mu_eff = s*c*q*mu_candidate",
    "mu_candidate": 1.2e-3,      # 候选;未校准(旧C1实跑 .004 属旧任务)
    "noise": "r_t = mu_eff(state_{t-1}) + sqrt(3)*sigma(g)*U, U~Unif(-1,1)",
    "sigma_by_g": {"0": 0.03, "1": 0.06},   # 候选
    "transition_independence": (
        "候选声明:逐 bar 的 s/c/q/g 分量独立抽取,无跨分量"
        "耦合;联合分布=分量乘积(未校准)"),
    "economy": {  # 固定费用/执行/终止语义(候选)
        "fee_rate": 1e-3,
        "slippage_bps": 0.0,
        "price_tick": 0.0,          # 候选(与现 env 参数对齐待核)
        "reward_scale": 1.0,
        "funding": "none_candidate",
        "maintenance_margin": 0.05,
        "initial_cash": 100.0,
        "execution": ("decision close[t] -> exec open[t+1] "
                      "-> settle close[t+1]"),
        "termination_threefold": {
            "invalid_terminal": ("经济失败→reward_valid=False"
                                 " 无效终结(非一律称强平)"),
            "pre_action_risk": ("动作前强制风险处置(非学生"
                                "主动决策,单列记账)"),
            "terminal_liquidation": ("终端清算腿(期末结算单列,"
                                     "不与学生主动退出混同)")}},
    "horizon": {"values": [32, 64, 128],  # 事前外生可见
                "visible": "remaining/total 两列均可见"},
    "account_encoding": {
        "exposure": "asinh(exposure)/4",
        "solvency": "asinh(min(solvency, 40))/4;"
                    " flat 原值=+inf→min 后=40"},
    "account_provenance": (
        "not_established:比例一致仅证明比例关系,不等于合法"
        "账本来源;本段不构造账本,合法起点链未建立"),
    "phase_selection": {
        "rule": ("仅选当前状态或合法账本起点;起点后按同一核"
                 "自然演化;禁止按未来实现挑路径/换核"),
        "legal_start": "flat 或 TwoSidedLinearLedger 合法构造"}}

# ---- 动作族(A 臂上界事实 + B 臂幅度主候选) --------------------
ACTION_FAMILIES = {
    "A_symmetric_beta_atoms": {
        "arm": "A",
        "decode_id": "P0CategoryMax-v1",   # 当前 P0 A/B 公共解码
        "decode_semantics": ("确定性解码仅出原子 {-1,0,+1};"
                             "内部幅度不可达(确定性)"),
        "structure": ("HOLD 原子 + REBALANCE 原子 {-1, 0, +1}"
                      "(REBALANCE(0)=目标零仓,与 HOLD 保持"
                      "数量语义不同)+关于零对称连续 Beta"),
        "internal_upper_bound": 0.5,   # 解析事实:单侧内部开区间
        "bound_status": "analytic_fact"},
    "B_asymmetric_beta": {
        "arm": "B",
        "decode_id": "P0CategoryMax-v1",  # 既有主接口同为公共解码
        "candidate_decode": "mixture-mean-v1",  # 候选,未接入
        "decode_semantics": ("当前公共解码=P0CategoryMax-v1;"
                             "mixture-mean 仅为候选解码,不得"
                             "写作既有主接口"),
        "structure": "非对称 Beta(α,β) + 原子",
        "reachability": "not_established",  # 未验证;不得与"已达"
        # 等价返回(见 evaluate_action_expressiveness)
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




# ================= 纯数据验证器 =================================

def obs_vector(state: dict, account: dict,
               horizon: dict, columns=None) -> dict:
    """按名构造观察。列绑定唯一:columns 必须逐字等于冻结
    OBS_COLUMNS(顺序含);未知列/重复列/未来列/改序即拒。"""
    if columns is not None and list(columns) != list(
            OBS_COLUMNS):
        bad = [c for c in columns
               if list(columns).count(c) > 1
               or c not in OBS_COLUMNS]
        raise UnifiedSpecError(
            "columns %r != frozen OBS_COLUMNS (unknown/"
            "duplicate/future/reordered rejected%s)"
            % (list(columns),
               "; e.g. %r" % bad[:3] if bad else ""))
    columns = list(OBS_COLUMNS)
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


def check_column_binding(ser: dict) -> dict:
    """列序绑定:names+values 逐名取值(位置不作依据)。"""
    names = ser.get("names")
    values = ser.get("values")
    if not names or not values or len(names) != len(values):
        raise UnifiedSpecError("serialization lacks names/values")
    if list(names) != list(OBS_COLUMNS):
        raise UnifiedSpecError(
            "obs names %r != frozen columns %r (unknown/dup/"
            "reorder rejected)" % (list(names),
                                   list(OBS_COLUMNS)))
    return dict(zip(names, values))


def verify_serialization(ser: dict, expected_state: dict) -> None:
    """逐名比对(非位置);expected_state 必须非空。"""
    if not isinstance(expected_state, dict) or not expected_state:
        raise UnifiedSpecError(
            "expected_state must be non-empty (empty validation "
            "is a no-op and rejected)")
    vec = check_column_binding(ser)
    for k, v in expected_state.items():
        if float(vec[k]) != float(v):
            raise UnifiedSpecError(
                "column permutation/labeling error at %r: got %r "
                "want %r" % (k, vec[k], v))


ARMS = ("A", "B")
KINDS = ("hold", "atom", "interval")


def _validate_action_entry(a: dict) -> None:
    if not isinstance(a, dict):
        raise UnifiedSpecError(
            "allowed entry must be typed dict, got %r" % (a,))
    arm = a.get("arm")
    if arm not in ARMS:
        raise UnifiedSpecError("unknown arm %r" % arm)
    kind = a.get("kind")
    if kind not in KINDS:
        raise UnifiedSpecError("unknown kind %r" % kind)
    if kind == "atom":
        v = a.get("value")
        if v not in (-1.0, 0.0, 1.0):
            raise UnifiedSpecError(
                "atom value %r not in {-1,0,1}" % v)
    if kind == "interval":
        lo, hi = a.get("lo"), a.get("hi")
        for x in (lo, hi):
            if not (isinstance(x, (int, float))
                    and math.isfinite(float(x))):
                raise UnifiedSpecError(
                    "interval bound non-finite %r/%r" % (lo, hi))
        if not (-1.0 <= float(lo) < float(hi) <= 1.0):
            raise UnifiedSpecError(
                "interval inverted/out-of-bounds [%r,%r]"
                % (lo, hi))
    p = a.get("p_gate")
    if p is not None and (not isinstance(p, (int, float))
                          or isinstance(p, bool)
                          or not math.isfinite(float(p))):
        raise UnifiedSpecError(
            "NaN/invalid p_gate %r" % p)


def _group_acceptable(acts) -> dict:
    """一组 allowed 的可接受动作集合:hold 标记+原子集+区间。"""
    atoms, ivs, hold = set(), [], False
    for a in acts:
        if a["kind"] == "hold":
            hold = True
        elif a["kind"] == "atom":
            atoms.add(float(a["value"]))
        else:
            ivs.append((float(a["lo"]), float(a["hi"])))
    return {"hold": hold, "atoms": atoms, "ivs": ivs}


def _common_nonempty(gs: list) -> bool:
    """多组可接受集合的**共同交集**是否非空(组内并,组间交)。
    hold 与数值动作视为不同动作;共同交集可来自:全体含 hold,
    或某数值点落在每组的原子/区间并内。"""
    if all(g["hold"] for g in gs):
        return True
    cand = None
    for g in gs:
        pts = set(g["atoms"])
        for lo, hi in g["ivs"]:
            pts |= {a for a in (-1.0, -0.5, 0.0, 0.5, 1.0)
                    if lo <= a <= hi}
        cand = pts if cand is None else (cand & pts)
    return bool(cand)


def check_same_obs_mutex(teaching: list) -> None:
    """同 obs 相容性语义(单 1792096619 精确化):
    每条记录先构造自身允许动作**并集**(hold 标记+原子集+区间),
    再对同 obs 的**全部记录**求**共同交集**(非任意两项、非仅
    两两);共同交集空=冲突;**单条非空合法集合直接相容**。"""
    by_obs = {}
    for entry in teaching:
        acts = entry.get("allowed_actions")
        if not acts:
            raise UnifiedSpecError(
                "empty allowed set for obs %r"
                % (entry.get("obs"),))
        for a in acts:
            _validate_action_entry(a)
        key = tuple(sorted(entry["obs"].items()))
        by_obs.setdefault(key, []).append(
            _group_acceptable(acts))
    for key, groups in by_obs.items():
        if len(groups) > 1 and not _common_nonempty(groups):
            raise UnifiedSpecError(
                "conflicting labels: same obs %r typed allowed "
                "sets have EMPTY COMMON INTERSECTION (pairwise "
                "overlap is not compatibility)"
                % (dict(key),))


# 决策相关 spec 全字段(签名必须覆盖;缺一即换任务可被隐藏)
TASK_SIGNATURE_FIELDS = (
    "transition_kernel", "drift", "mu_candidate", "noise",
    "sigma_by_g", "economy", "horizon", "account_encoding",
    "obs_columns", "action_families", "decode_ids")


def task_signature(v: dict) -> tuple:
    """同 task 决策签名:漂移/风险/噪声/完整转移/经济/观察
    编码/期限/动作族/解码 全量;obs 列与解码从声明取。"""
    parts = [json_lite(v.get(f)) for f in
             TASK_SIGNATURE_FIELDS[:-2]]
    parts.append(json_lite(list(
        v.get("obs_columns") or OBS_COLUMNS)))
    fam = v.get("action_families") or ACTION_FAMILIES
    parts.append(json_lite(
        {k: {"arm": x.get("arm"),
             "decode_id": x.get("decode_id")}
         for k, x in fam.items()}))
    return tuple(parts)


def check_hidden_task_swap(variants: list) -> None:
    """同 task_id 决策签名不同 = 隐藏换任务,拒绝(全字段)。"""
    seen = {}
    for v in variants:
        tid = v["task_id"]
        sig = task_signature(v)
        if tid in seen and seen[tid] != sig:
            import difflib
            diff = [f for f in TASK_SIGNATURE_FIELDS
                    [:len(TASK_SIGNATURE_FIELDS) - 2]]
            raise UnifiedSpecError(
                "hidden task swap: task_id %r differs in "
                "decision-relevant spec (fields: %r...)"
                % (tid, diff[:4]))
        seen[tid] = sig


def json_lite(o) -> str:
    import json
    return json.dumps(o, sort_keys=True, default=str)


FLAT_SOLVENCY_CAP = 40.0   # 固定编码常数(输入不可自选 cap)


def check_ledger_account(acct: dict) -> None:
    """合法账本一致性(全有限;flat 唯一合法原值=+inf 再按固定
    cap 40 编码;非 flat=1/|e|;NaN/-inf/自选 cap 拒)。"""
    e = float(acct["exposure"])
    if not math.isfinite(e):
        raise UnifiedSpecError(
            "non-finite exposure %r" % e)
    raw = acct.get("solvency_raw", "__missing__")
    capped = acct.get("solvency_capped", "__missing__")
    if raw == "__missing__" or capped == "__missing__":
        raise UnifiedSpecError(
            "ledger entry missing solvency_raw/capped")
    if abs(e) < 1e-12:
        # flat:唯一合法原值 = +inf(不允许 -inf/NaN/有限值)
        if raw != math.inf:
            raise UnifiedSpecError(
                "flat solvency_raw must be +inf; got %r "
                "(-inf/NaN/finite rejected)" % (raw,))
        if abs(float(capped) - FLAT_SOLVENCY_CAP) > 1e-9:
            raise UnifiedSpecError(
                "flat encoding must use fixed cap %.1f "
                "(got %r; input cannot choose cap)"
                % (FLAT_SOLVENCY_CAP, capped))
    else:
        if (isinstance(raw, float)
                and not math.isfinite(raw)):
            raise UnifiedSpecError(
                "non-flat non-finite solvency_raw %r" % raw)
        want = 1.0 / abs(e)
        if abs(float(raw) - want) > 1e-9:
            raise UnifiedSpecError(
                "non-flat solvency %r != 1/|e|=%r "
                "(silent truncation?)" % (raw, want))
        want_cap = min(want, FLAT_SOLVENCY_CAP)
        if abs(float(capped) - want_cap) > 1e-9:
            raise UnifiedSpecError(
                "non-flat capped %r != min(raw,%.1f)=%r"
                % (capped, FLAT_SOLVENCY_CAP, want_cap))


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


METRICS = ("distribution_probability", "deterministic_hit")
EXPRESSIVENESS_STATUS = ("proved_impossible",
                         "not_established", "validated")


def evaluate_action_expressiveness(gate_request: dict) -> dict:
    """门可达性状态机:返回 {status,metric,decoder,reason}。
    - proved_impossible:A 臂+分布概率门+严格单侧内部区间
      (不含 0/±1)且 threshold>解析上界 .5 —— 上界属分布
      本身,**换解码不能规避**(decode 无关性记录在 reason);
    - validated:仅 deterministic_hit+原子目标(A 臂,CategoryMax
      确定性出原子,结构可达);
    - not_established:其余(含 B 全部——未验证,不得与已达
      等价返回)。
    输入校验失败(未知 arm/metric/decoder/区间/NaN 门)抛错。"""
    arm = gate_request.get("arm")
    if arm not in ARMS:
        raise UnifiedSpecError("unknown arm %r" % arm)
    metric = gate_request.get("metric")
    if metric not in METRICS:
        raise UnifiedSpecError(
            "unknown metric %r (bind distribution_probability|"
            "deterministic_hit)" % metric)
    decoder = gate_request.get("decoder")
    if decoder not in ("P0CategoryMax-v1", "mixture-mean-v1"):
        raise UnifiedSpecError("unknown decoder %r" % decoder)
    lo, hi = gate_request.get("interval", (None, None))
    for x in (lo, hi):
        if not (isinstance(x, (int, float))
                and math.isfinite(float(x))):
            raise UnifiedSpecError(
                "interval bound invalid %r/%r" % (lo, hi))
    if not (-1.0 <= float(lo) < float(hi) <= 1.0):
        raise UnifiedSpecError(
            "interval inverted/out-of-bounds [%r,%r]"
            % (lo, hi))
    p = gate_request.get("threshold")
    if (not isinstance(p, (int, float))
            or isinstance(p, bool)
            or not math.isfinite(float(p))):
        raise UnifiedSpecError(
            "NaN/invalid threshold %r" % p)
    base = {"metric": metric, "decoder": decoder}
    strictly_interior_one_side = (
        (lo > 0 or hi < 0) and lo > -1 + 1e-12
        and hi < 1 - 1e-12)
    if metric == "distribution_probability":
        if (arm == "A" and strictly_interior_one_side
                and p > internal_interval_upper_bound_arm_a()
                + 1e-12):
            return dict(base, status="proved_impossible",
                        reason=("A-arm symmetric distribution "
                                "mass over one-side interior "
                                "interval <= .5 (decode-"
                                "independent: bound is a "
                                "property of the distribution,"
                                "changing decoder cannot evade)"))
        return dict(base, status="not_established",
                    reason=("no validated reachability for "
                            "this arm/metric/interval yet"))
    # deterministic_hit
    atom_target = (set(gate_request.get("atoms", ()))
                   if gate_request.get("atoms") is not None
                   else None)
    if arm == "A" and decoder == "P0CategoryMax-v1" and (
            atom_target is not None
            and set(map(float, atom_target)) <= {
                -1.0, 0.0, 1.0}):
        return dict(base, status="validated",
                    reason=("CategoryMax deterministic decode "
                            "outputs atoms {-1,0,+1}; atom "
                            "targets structurally attainable"))
    return dict(base, status="not_established",
                reason=("deterministic_hit validated only for "
                        "A-arm CategoryMax atom targets in this "
                        "phase"))


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
    """毕业判定的合法身份链:须(1)注册表内技能;(2)门已 frozen;
    (3)graduated 附**结构化门记录**={task_id,spec/gate_version,
    approval{channel,ref}}——批准是身份/状态问题,不是数字黑名单;
    未校准(not_specified)一律不可毕业(本段七技能全部如此)。"""
    for skill, st in skill_status.items():
        if skill not in SEVEN_SKILLS:
            raise UnifiedSpecError(
                "unknown skill %r (not in seven-skill registry)"
                % skill)
        if SEVEN_SKILLS[skill]["gate_status"] != "frozen":
            if st.get("graduated") or st.get("gate") is not None:
                raise UnifiedSpecError(
                    "skill %r gate not frozen (uncalibrated); "
                    "no graduation/gate claim allowed — "
                    "rejection is about missing independent "
                    "approval & uncalibrated status, not about "
                    "any particular number" % skill)
            continue
        gate = st.get("gate")
        if st.get("graduated"):
            if not isinstance(gate, dict):
                raise UnifiedSpecError(
                    "skill %r graduation requires structured "
                    "gate record, got %r" % (skill, gate))
            for k in ("task_id", "gate_version", "approval"):
                if k not in gate:
                    raise UnifiedSpecError(
                        "skill %r gate record missing %r"
                        % (skill, k))
            ap = gate["approval"]
            if (not isinstance(ap, dict)
                    or not isinstance(ap.get("channel"),
                                      str)
                    or not ap.get("channel").strip()
                    or not isinstance(ap.get("ref"), str)
                    or not ap.get("ref").strip()):
                raise UnifiedSpecError(
                    "skill %r approval must be structured "
                    "{channel,ref}" % skill)
            if gate["task_id"] != UNIFIED_TASK["task_id"]:
                raise UnifiedSpecError(
                    "skill %r gate task binding mismatch" % skill)


def build_registry_snapshot() -> dict:
    """七技能注册表快照(深拷贝;改快照不得反写全局注册)。"""
    import copy
    return {
        "schema": SPEC_SCHEMA,
        "task": copy.deepcopy(UNIFIED_TASK),
        "action_families": copy.deepcopy(ACTION_FAMILIES),
        "skills": copy.deepcopy(SEVEN_SKILLS),
        "combination_module": {
            "note": ("七技能通过不自动证明组合;组合题单列"
                     "(设计v1 §6),门 not_specified"),
            "gate_status": "not_specified"},
        "calibration": "incomplete"}
