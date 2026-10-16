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
    "spec_versions": SPEC_VERSIONS,   # 绑定入任务本体
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

# spec 自身 round-trip:obs 列与动作族绑进任务本体(在家族定义后)
UNIFIED_TASK["obs_columns"] = OBS_COLUMNS
UNIFIED_TASK["action_families"] = ACTION_FAMILIES


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

def validate_obs_fields(vals: dict) -> None:
    """完整 8 字段观察的**双侧同一严格 schema**:全字段在场、
    严格数值类型(拒 bool/str,不做静默 float 转换)、有限、
    特征域合法。obs_vector / same-obs / 序列化 complete 校验
    共用本函数。"""
    if (not isinstance(vals, dict)
            or set(vals) != set(OBS_COLUMNS)):
        raise UnifiedSpecError(
            "obs must carry exactly the 8 contract fields "
            "(got %r)" % (sorted(vals) if isinstance(
                vals, dict) else type(vals).__name__))
    sv = _num(vals["s"], "obs s")
    if sv not in (-1.0, 0.0, 1.0):
        raise UnifiedSpecError(
            "obs s out of {-1,0,1}: %r" % sv)
    for f in ("c", "g", "q"):
        fv = _num(vals[f], "obs %s" % f)
        if not 0.0 <= fv <= 1.0:
            raise UnifiedSpecError(
                "obs %s out of [0,1]: %r" % (f, fv))
    for f in ("account_exposure", "account_solvency"):
        _num(vals[f], "obs %s" % f)   # 有限即可(编码域)
    for f in ("remaining_horizon", "total_horizon"):
        hv = vals[f]
        if (isinstance(hv, bool)
                or not isinstance(hv, int) or hv < 1):
            raise UnifiedSpecError(
                "obs %s must be positive int: %r" % (f, hv))
    if vals["remaining_horizon"] > vals["total_horizon"]:
        raise UnifiedSpecError("remaining > total horizon")


def obs_vector(state: dict, account: dict,
               horizon: dict, columns=None) -> dict:
    """按名构造观察。列绑定唯一:columns 必须逐字等于冻结
    OBS_COLUMNS;并做**特征域校验**(s/c/g/q/期限)。"""
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
    validate_obs_fields(vals)   # 与 same-obs/complete 同一 schema
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


def verify_serialization_partial(ser: dict,
                                 expected_state: dict) -> None:
    """**部分**逐名比对(另名;不得当作完整已验)。"""
    if not isinstance(expected_state, dict) or not expected_state:
        raise UnifiedSpecError(
            "expected_state must be non-empty (empty validation "
            "is a no-op and rejected)")
    vec = check_column_binding(ser)
    for k, v in expected_state.items():
        if vec[k] != v:
            raise UnifiedSpecError(
                "column permutation/labeling error at %r: got %r "
                "want %r (strict equality; no silent coercion)"
                % (k, vec[k], v))


def verify_serialization_complete(ser: dict,
                                  full_expected: dict) -> None:
    """**完整**比对(双侧同 schema):expected 八字段严格域校验;
    actual(wire)值同样严格类型检查——bool/数字字符串不做
    静默 float 转换;随后逐字段相等。"""
    if (not isinstance(full_expected, dict)
            or set(full_expected) != set(OBS_COLUMNS)):
        raise UnifiedSpecError(
            "complete verification requires ALL %d fields "
            "(partial subset rejected)" % len(OBS_COLUMNS))
    validate_obs_fields(full_expected)
    vec = check_column_binding(ser)
    validate_obs_fields(vec)   # actual 侧同一严格 schema
    for k in OBS_COLUMNS:
        if vec[k] != full_expected[k]:
            raise UnifiedSpecError(
                "complete mismatch at %r: actual=%r "
                "expected=%r" % (k, vec[k],
                                 full_expected[k]))


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
        if isinstance(v, bool) or not isinstance(
                v, (int, float)):
            raise UnifiedSpecError(
                "atom value must be numeric non-bool "
                "(True/'1' rejected): %r" % (v,))
        v = float(v)
        if not math.isfinite(v) or v not in (
                -1.0, 0.0, 1.0):
            raise UnifiedSpecError(
                "atom value %r not in {-1,0,1}" % v)
    if kind == "interval":
        lo, hi = a.get("lo"), a.get("hi")
        lo = _num(lo, "interval lo")
        hi = _num(hi, "interval hi")
        if not (-1.0 <= lo < hi <= 1.0):
            raise UnifiedSpecError(
                "interval inverted/out-of-bounds [%r,%r]"
                % (lo, hi))
        op = a.get("open")
        if op is not None:
            ok = (isinstance(op, bool)
                  or op in ("lo", "hi")
                  or (isinstance(op, tuple) and set(op) <=
                      {"lo", "hi"} and op))
            if isinstance(op, int) and not isinstance(
                    op, bool):
                ok = False   # open=1 不等价 True(严格 bool)
            if not ok:
                raise UnifiedSpecError(
                    "interval open flag invalid %r "
                    "(strict bool / 'lo' / 'hi' / tuple)"
                    % (op,))
    p = a.get("p_gate")
    if p is not None:
        pv = _num(p, "p_gate")
        if not (0.0 <= pv <= 1.0):
            raise UnifiedSpecError(
                "p_gate out of [0,1]: %r" % p)


def _iv_open(a: dict):
    """返回 (lo_open, hi_open)。"""
    op = a.get("open", False)
    if op is True:
        return True, True
    if op in ("lo",):
        return True, False
    if op in ("hi",):
        return False, True
    if isinstance(op, tuple):
        return ("lo" in op, "hi" in op)
    return False, False


def _group_acceptable(acts) -> dict:
    """一组 allowed 的可接受集合:hold 标记+原子集+**规范化**
    区间并(排序;精确开闭合并:touch 比较旧段 hi_open 与新段
    lo_open;同端合并 open=双方 open 的 AND)。"""
    atoms, ivs, hold = set(), [], False
    for a in acts:
        if a["kind"] == "hold":
            hold = True
        elif a["kind"] == "atom":
            atoms.add(float(a["value"]))
        else:
            lo_o, hi_o = _iv_open(a)
            ivs.append((float(a["lo"]), float(a["hi"]),
                        lo_o, hi_o))
    ivs.sort(key=lambda t: (t[0], t[1]))
    merged = []
    for lo, hi, lo_o, hi_o in ivs:
        if merged:
            m_lo, m_hi, m_lo_o, m_hi_o = merged[-1]
            touch = (lo < m_hi or (
                lo == m_hi and not (
                    m_hi_o and lo_o)))   # 旧 hi_open x 新 lo_open
            if touch:
                n_hi, n_hi_o = (
                    (m_hi, m_hi_o) if m_hi > hi else
                    ((hi, hi_o) if hi > m_hi else
                     (m_hi, m_hi_o and hi_o)))  # 同端:AND
                n_lo_o = (m_lo_o and lo_o
                          if m_lo == lo else m_lo_o)
                merged[-1] = (m_lo, n_hi, n_lo_o, n_hi_o)
                continue
        merged.append((lo, hi, lo_o, hi_o))
    return {"hold": hold, "atoms": atoms, "ivs": merged}


def _in_union(x: float, g: dict) -> bool:
    """x 是否属于该组并集——**精确开闭比较,无 eps 扩张**
    (间隙 [.2,.3] vs [.3000000000005,.4] 不被填平)。"""
    if x in g["atoms"]:
        return True
    for lo, hi, lo_o, hi_o in g["ivs"]:
        if ((x > lo or (x == lo and not lo_o)) and
                (x < hi or (x == hi and not hi_o))):
            return True
    return False


def _common_nonempty(gs: list) -> bool:
    """多组可接受集合的**共同交集**是否非空——**精确区间运算**:
    候选点=所有区间端点+相邻端点中点+全体原子;某候选属于每组
    并集(开闭感知)即非空。不投固定采样点(如 [.21,.31]∩
    [.25,.35]=[.25,.31] 必须判非空),无数值求解。"""
    if all(g["hold"] for g in gs):
        return True
    cands = set()
    for g in gs:
        cands |= g["atoms"]
        for lo, hi, _lo, _hi in g["ivs"]:
            cands |= {lo, hi}
    pts = sorted(cands)
    for a, b in zip(pts, pts[1:]):
        cands.add((a + b) / 2.0)
    return any(_in_union(c, g) for c in cands
               for g in [gs[0]]) and any(
        all(_in_union(c, g) for g in gs) for c in cands)


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
        validate_obs_fields(entry["obs"])   # 完整8字段严格
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
    "obs_columns", "action_families",
    "transition_independence", "spec_versions")
# 全部字段必须显式在场:spec_versions(含 reward 版本)与
# transition_independence 均为决策相关并绑定进签名;economy
# 内 reward_scale/price_tick 已属 economy;完整动作结构=
# action_families 全量。


def validate_task_spec(v: dict) -> None:
    """本版本唯一候选的**完整递归 schema 校验**(非黑名单):
    结构=固定模板精确匹配(未知结构/不支持语义直接拒,扩展须
    显式新 schema);数值=仅验证声明允许的候选域(可变候选仍受
    域约束并参与签名)。构造/签名/比较共用本入口。"""
    if not isinstance(v, dict) or not v.get("task_id"):
        raise UnifiedSpecError("spec missing task_id")
    if v.get("schema") != SPEC_SCHEMA:
        raise UnifiedSpecError(
            "unknown schema %r (want %r)"
            % (v.get("schema"), SPEC_SCHEMA))
    _tpl_top(v)
    _tpl_kernel(v["transition_kernel"])
    _tpl_sigma(v.get("sigma_by_g"))
    _tpl_economy(v.get("economy"))
    _tpl_encoding(v.get("account_encoding"))
    _tpl_actions(v.get("action_families"))


def _tpl_top(v):
    if v.get("obs_columns") is not None and \
            list(v["obs_columns"]) != list(OBS_COLUMNS):
        raise UnifiedSpecError(
            "obs_columns template mismatch (change requires "
            "a new schema version)")
    mu = _num(v.get("mu_candidate"), "mu_candidate")
    if mu <= 0:
        raise UnifiedSpecError("mu_candidate must be > 0")
    for f, tpl in (("drift", UNIFIED_TASK["drift"]),
                   ("noise", UNIFIED_TASK["noise"])):
        if v.get(f) != tpl:
            raise UnifiedSpecError(
                "%s template mismatch: unsupported semantics "
                "rejected (new schema required)" % f)
    if not isinstance(v.get("transition_independence"),
                      str) or not v[
                          "transition_independence"].strip():
        raise UnifiedSpecError("bad transition_independence")
    sv = v.get("spec_versions")
    if (not isinstance(sv, dict)
            or set(sv) != {"obs", "reward", "action",
                           "execution"}
            or not all(isinstance(x, str) and x.strip()
                       for x in sv.values())):
        raise UnifiedSpecError(
            "spec_versions must carry exactly the four "
            "non-empty version subkeys")
    hz = v.get("horizon")
    if (not isinstance(hz, dict)
            or set(hz) != {"values", "visible"}
            or not isinstance(hz["values"], list)
            or not hz["values"]
            or not all(isinstance(x, int)
                       and not isinstance(x, bool) and x > 0
                       for x in hz["values"])
            or not isinstance(hz["visible"], str)):
        raise UnifiedSpecError("bad horizon structure")


def _tpl_kernel(k):
    if not isinstance(k, dict) or set(k) != {
            "s", "c", "q", "g"}:
        raise UnifiedSpecError(
            "transition_kernel must have exactly s/c/q/g")
    S = k.get("s")
    if (not isinstance(S, dict)
            or set(S) != {"values", "hold_p",
                          "resample_p", "resample_dist"}
            or S.get("values") != [-1, 0, 1]
            or S.get("resample_dist")
            != "uniform_over_values"):
        raise UnifiedSpecError(
            "kernel s template mismatch")
    for f in ("c", "g"):
        C = k.get(f)
        if (not isinstance(C, dict)
                or set(C) != {"values", "hold_p",
                              "resample_p",
                              "resample_dist"}
                or C.get("values") != [0, 1]
                or C.get("resample_dist")
                != "uniform_over_{0,1}"):
            raise UnifiedSpecError(
                "kernel %s template mismatch" % f)
    Q = k.get("q")
    qv = Q.get("values") if isinstance(Q, dict) else None
    if (not isinstance(Q, dict)
            or set(Q) != {"values", "hold_p",
                          "fresh_p", "resample_dist"}
            or not isinstance(qv, list) or len(qv) != 5
            or not all(_num_ok_in01(x) for x in qv)
            or [float(x) for x in qv] != [
                0.0, 0.25, 0.5, 0.75, 1.0]
            or Q.get("resample_dist")
            != "fresh_p_over_5_levels"):
        raise UnifiedSpecError(
            "kernel q template mismatch (values must be "
            "the five finite levels)")
    for comp in ("s", "c", "q", "g"):
        hp = _num(k[comp].get("hold_p"),
                  "%s hold_p" % comp)
        if not 0.0 <= hp <= 1.0:
            raise UnifiedSpecError(
                "kernel %s hold_p out of [0,1]" % comp)
    for comp in ("s", "c", "g"):
        hp2 = _num(k[comp].get("hold_p"),
                   "%s hold_p" % comp)
        rp = _num(k[comp].get("resample_p"),
                  "%s resample_p" % comp)
        if not 0.0 <= rp <= 1.0:
            raise UnifiedSpecError(
                "kernel %s resample_p out of [0,1]" % comp)
        if abs(hp2 + rp - 1.0) > 1e-9:
            raise UnifiedSpecError(
                "kernel %s hold+resample != 1" % comp)
    fp = k["q"].get("fresh_p")
    if (not isinstance(fp, list) or len(fp) != 5):
        raise UnifiedSpecError("kernel q fresh_p length")
    for x in fp:
        xv = _num(x, "q fresh_p entry")
        if not 0.0 <= xv <= 1.0:
            raise UnifiedSpecError(
                "q fresh_p entry out of [0,1]: %r" % x)
    if abs(sum(map(float, fp)) - 1.0) > 1e-9:
        raise UnifiedSpecError("q fresh_p sum != 1")


def _num_ok_in01(x):
    try:
        xv = _num(x, "probe")
        return 0.0 <= xv <= 1.0
    except UnifiedSpecError:
        return False


def _tpl_sigma(sg):
    if (not isinstance(sg, dict)
            or set(sg) != {"0", "1"}):
        raise UnifiedSpecError(
            "sigma_by_g keys must be exactly g0/g1")
    for gk in ("0", "1"):
        gv = _num(sg[gk], "sigma_by_g[%s]" % gk)
        if gv <= 0:
            raise UnifiedSpecError(
                "sigma_by_g[%s] must be > 0" % gk)


def _tpl_economy(econ):
    if not isinstance(econ, dict):
        raise UnifiedSpecError("bad economy")
    need = {"fee_rate", "slippage_bps", "price_tick",
            "reward_scale", "funding", "maintenance_margin",
            "initial_cash", "execution",
            "termination_threefold"}
    if set(econ) != need:
        raise UnifiedSpecError(
            "economy must declare exactly the full set "
            "(execution/termination/funding included): "
            "missing=%r extra=%r"
            % (sorted(need - set(econ)),
               sorted(set(econ) - need)))
    if econ["funding"] != "none_candidate":
        raise UnifiedSpecError(
            "funding semantics unsupported (template: "
            "none_candidate)")
    if econ["execution"] != UNIFIED_TASK[
            "economy"]["execution"]:
        raise UnifiedSpecError(
            "execution template mismatch")
    term = econ["termination_threefold"]
    if (not isinstance(term, dict)
            or set(term) != {"invalid_terminal",
                             "pre_action_risk",
                             "terminal_liquidation"}
            or not all(isinstance(x, str) and x
                       for x in term.values())):
        raise UnifiedSpecError(
            "termination_threefold template mismatch")
    for f in ("fee_rate", "slippage_bps", "price_tick",
              "reward_scale", "maintenance_margin",
              "initial_cash"):
        _num(econ.get(f), "economy %s" % f)
    if econ["fee_rate"] < 0:
        raise UnifiedSpecError("fee_rate must be >= 0")
    if econ["slippage_bps"] < 0:
        raise UnifiedSpecError(
            "slippage_bps must be >= 0")
    if econ["price_tick"] < 0:
        raise UnifiedSpecError(
            "price_tick must be >= 0")
    if econ["reward_scale"] <= 0:
        raise UnifiedSpecError("reward_scale must be > 0")
    if econ["maintenance_margin"] <= 0:
        raise UnifiedSpecError(
            "maintenance_margin must be > 0")
    if econ["initial_cash"] <= 0:
        raise UnifiedSpecError("initial_cash must be > 0")


def _tpl_encoding(enc):
    if (not isinstance(enc, dict)
            or set(enc) != {"exposure", "solvency"}
            or enc.get("exposure") != "asinh(exposure)/4"
            or enc.get("solvency")
            != UNIFIED_TASK["account_encoding"][
                "solvency"]):
        raise UnifiedSpecError(
            "account_encoding template mismatch "
            "(unsupported semantics rejected)")


def _tpl_actions(af):
    if not isinstance(af, dict) or set(af) != {
            "A_symmetric_beta_atoms",
            "B_asymmetric_beta"}:
        raise UnifiedSpecError(
            "action_families template mismatch")
    A = af.get("A_symmetric_beta_atoms")
    if (not isinstance(A, dict)
            or set(A) != {"arm", "decode_id",
                          "decode_semantics",
                          "structure",
                          "internal_upper_bound",
                          "bound_status"}
            or A.get("arm") != "A"
            or A.get("decode_id")
            != "P0CategoryMax-v1"
            or not isinstance(
                A.get("internal_upper_bound"),
                (int, float))
            or isinstance(
                A.get("internal_upper_bound"), bool)
            or not isinstance(A.get("structure"), str)
            or not A.get("structure")):
        raise UnifiedSpecError(
            "A family template mismatch")
    B = af.get("B_asymmetric_beta")
    if (not isinstance(B, dict)
            or set(B) != {"arm", "decode_id",
                          "candidate_decode",
                          "decode_semantics",
                          "structure", "reachability",
                          "note"}
            or B.get("arm") != "B"
            or B.get("decode_id")
            != "P0CategoryMax-v1"
            or B.get("candidate_decode")
            != "mixture-mean-v1"
            or B.get("reachability")
            != "not_established"
            or not isinstance(B.get("structure"), str)
            or not B.get("structure")):
        raise UnifiedSpecError(
            "B family template mismatch")


def make_task_spec(**overrides) -> dict:
    """唯一完整构造器:基于 UNIFIED_TASK 深拷贝+覆盖+严格校验。
    snapshot/task_signature/consumers 一律经此或 validate 通过
    的对象;禁止测试手工拼装绕过真实入口。"""
    import copy
    v = copy.deepcopy(UNIFIED_TASK)
    for k, val in overrides.items():
        v[k] = copy.deepcopy(val)
    validate_task_spec(v)
    return v


def task_signature(v: dict) -> tuple:
    """同 task 决策签名。**必填字段必须显式在场**:缺失/空
    spec 不得经"两个 None 相等"判为同任务(缺任一即抛错)。
    覆盖:漂移/μ/噪声/σ_g/完整转移/经济(含 reward_scale/
    price_tick)/期限/账户编码/obs 列/**spec_versions(含
    reward 版本)**/**完整动作结构**(全量 action_families,
    非仅 arm+decode)。"""
    for f in TASK_SIGNATURE_FIELDS:
        if f not in v or v[f] in (None, "", {}, []):
            raise UnifiedSpecError(
                "task spec missing required field %r "
                "(empty/missing specs cannot be compared "
                "as same-task)" % f)
    if not v.get("spec_versions"):
        raise UnifiedSpecError(
            "task spec missing spec_versions (obs/reward/"
            "action/execution)")
    parts = [json_lite(v[f]) for f in
             TASK_SIGNATURE_FIELDS]
    parts.append(json_lite(v["spec_versions"]))
    return tuple(parts)


def check_hidden_task_swap(variants: list) -> None:
    """同 task_id 决策签名不同 = 隐藏换任务,拒绝(全字段)。
    入口强制严格 validate——直接传原始 dict 的旁路同样先过
    schema(无效输入在比较前即拒,两份无效不判同任务)。"""
    for v in variants:
        validate_task_spec(v)   # 消费入口强制,非仅构造器
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


def _num(x, what):
    """数值净化:先拒 bool/字符串/非数值类型,再 isfinite;
    不依赖差值比较吞 NaN。"""
    if (isinstance(x, bool)
            or not isinstance(x, (int, float))):
        raise UnifiedSpecError(
            "%s not numeric type (bool/str rejected): %r"
            % (what, x))
    x = float(x)
    if not math.isfinite(x):
        raise UnifiedSpecError(
            "%s not finite: %r" % (what, x))
    return x


def check_ledger_account(acct: dict) -> None:
    """合法账本一致性(全有限;flat 唯一合法原值=+inf 再按固定
    cap 40 编码;非 flat=1/|e|;NaN/-inf/自选 cap 拒)。"""
    e = _num(acct["exposure"], "exposure")
    raw_sent = acct.get("solvency_raw", "__missing__")
    capped_sent = acct.get("solvency_capped",
                           "__missing__")
    if raw_sent == "__missing__" or (
            capped_sent == "__missing__"):
        raise UnifiedSpecError(
            "ledger entry missing solvency_raw/capped")
    if abs(e) < 1e-12:
        # flat:唯一合法原值 = +inf(字符串/NaN/有限/bool 全拒)
        if raw_sent is not math.inf and raw_sent != \
                math.inf:
            raise UnifiedSpecError(
                "flat solvency_raw must be +inf; got %r "
                "(str/NaN/-inf/finite/bool rejected)"
                % (raw_sent,))
        capped = _num(capped_sent, "solvency_capped")
        if abs(capped - FLAT_SOLVENCY_CAP) > 1e-9:
            raise UnifiedSpecError(
                "flat encoding must use fixed cap %.1f "
                "(got %r; input cannot choose cap)"
                % (FLAT_SOLVENCY_CAP, capped))
    else:
        raw = _num(raw_sent, "solvency_raw")
        capped2 = _num(capped_sent, "solvency_capped")
        want = 1.0 / abs(e)
        if abs(raw - want) > 1e-9:
            raise UnifiedSpecError(
                "non-flat solvency %r != 1/|e|=%r "
                "(silent truncation?)" % (raw, want))
        want_cap = min(want, FLAT_SOLVENCY_CAP)
        if abs(capped2 - want_cap) > 1e-9:
            raise UnifiedSpecError(
                "non-flat capped %r != min(raw,%.1f)=%r"
                % (capped2, FLAT_SOLVENCY_CAP, want_cap))


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
    lo = _num((gate_request.get("interval") or
               (None, None))[0], "interval lo")
    hi = _num((gate_request.get("interval") or
               (None, None))[1], "interval hi")
    if not (-1.0 <= lo < hi <= 1.0):
        raise UnifiedSpecError(
            "interval inverted/out-of-bounds [%r,%r]"
            % (lo, hi))
    p = _num(gate_request.get("threshold"), "threshold")
    if not (0.0 <= p <= 1.0):
        raise UnifiedSpecError(
            "probability threshold out of [0,1]: %r" % p)
    init_state = gate_request.get("initial_state")
    if init_state not in ("flat", "held"):
        raise UnifiedSpecError(
            "initial_state must be flat|held, got %r"
            % init_state)
    hold_allowed = gate_request.get("hold_allowed")
    if not isinstance(hold_allowed, bool):
        raise UnifiedSpecError(
            "hold_allowed must be explicit bool")
    target_kind = gate_request.get("target_kind")
    if target_kind not in ("rebal_target",
                           "effective_exposure"):
        raise UnifiedSpecError(
            "target_kind must be rebal_target|"
            "effective_exposure (REBAL 目标分布 vs 完整 "
            "HOLD 混合行为), got %r" % target_kind)
    base = {"metric": metric, "decoder": decoder,
            "initial_state": init_state,
            "hold_allowed": hold_allowed,
            "target_kind": target_kind}
    strictly_interior_one_side = (
        (lo > 0 or hi < 0) and lo > -1 + 1e-12
        and hi < 1 - 1e-12)
    if metric == "distribution_probability":
        # 解析上界唯一已证明适用域:A 臂对称 REBAL 目标分布、
        # flat 起点、HOLD 不参与该门(target 不受持仓保持影响)。
        # 已有仓位+允许 HOLD 时,有效敞口可停在区间内(如 .4 持仓
        # HOLD 使 [.3,.6] 命中概率 1)——上界不适用,not_established。
        proved_domain = (arm == "A"
                         and target_kind == "rebal_target"
                         and init_state == "flat"
                         and hold_allowed is False)
        if (proved_domain and strictly_interior_one_side
                and p > internal_interval_upper_bound_arm_a()
                + 1e-12):
            return dict(base, status="proved_impossible",
                        reason=("A-arm symmetric REBAL target "
                                "distribution mass over one-"
                                "side interior interval <= .5 "
                                "(decode-independent; proved "
                                "domain: flat start, HOLD not "
                                "part of this gate)"))
        return dict(base, status="not_established",
                    reason=("outside the proved domain of the "
                            "analytic bound (e.g. held posi- "
                            "tion with HOLD allowed can keep "
                            "effective exposure inside the "
                            "interval with probability 1); no "
                            "validated reachability claim"))
    # deterministic_hit
    atom_target = (set(gate_request.get("atoms", ()))
                   if gate_request.get("atoms") is not None
                   else None)
    if atom_target is not None and not atom_target:
        raise UnifiedSpecError(
            "empty atom target set — invalid request, "
            "cannot yield 'validated'")
    if atom_target is not None:
        for x in atom_target:
            if isinstance(x, bool) or not isinstance(
                    x, (int, float)):
                raise UnifiedSpecError(
                    "atom target must be numeric non-bool "
                    "(True/'1' rejected): %r" % (x,))
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


def _declared_decoders(arm: str) -> set:
    fams = (UNIFIED_TASK.get("action_families")
            or ACTION_FAMILIES)
    out = set()
    for fam in fams.values():
        if fam.get("arm") == arm:
            if fam.get("decode_id"):
                out.add(fam["decode_id"])
            if fam.get("candidate_decode"):
                out.add(fam["candidate_decode"])
    return out


def check_decode_identity(report: dict) -> None:
    """解码身份绑定 task/arm/metric+该任务已声明 decoder;
    A 臂+mixture-mean(仅 B 候选)不得通过;历史诊断须显式另
    身份(scope)且不得与当前任务条目混排。"""
    ids = set()
    scopes = set()
    for item in report.get("actions", []):
        for k in ("task_id", "arm", "metric",
                  "decode_id"):
            if not item.get(k):
                raise UnifiedSpecError(
                    "action entry lacks %r" % k)
        if item["task_id"] != UNIFIED_TASK["task_id"]:
            raise UnifiedSpecError(
                "decode entry task binding mismatch")
        if item["arm"] not in ARMS:
            raise UnifiedSpecError("unknown arm %r"
                                   % item["arm"])
        if item["metric"] not in METRICS:
            raise UnifiedSpecError("unknown metric %r"
                                   % item["metric"])
        declared = _declared_decoders(item["arm"])
        if item["decode_id"] not in declared:
            raise UnifiedSpecError(
                "decode %r not declared for arm %r "
                "(declared=%r)" % (
                    item["decode_id"], item["arm"],
                    sorted(declared)))
        ids.add(item["decode_id"])
        scopes.add(item.get("scope", "current_task"))
    if len(ids) > 1:
        raise UnifiedSpecError(
            "mixed decode identities %r in one report"
            % sorted(ids))
    if scopes == {"historical_diagnostic"}:
        return  # 历史诊断另身份:仅允许纯历史报告
    if len(scopes) > 1:
        raise UnifiedSpecError(
            "cannot mix historical_diagnostic and "
            "current-task entries")


# 已冻结门注册表(内容+摘要)。**生产当前为空**——本轮没有
# 任何新冻结门;毕业主张必须绑定注册表内门的 gate_digest,
# 自造字符串/摘要不能自证。测试隔离可注入临时注册表。
REGISTRY_GATES: dict = {}


def _gate_digest(gate_def: dict) -> str:
    import hashlib
    return hashlib.sha256(
        json_lite(gate_def).encode("utf-8")).hexdigest()


def check_graduation_claim(skill_status: dict,
                           registry_gates=None) -> None:
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
            for k in ("task_id", "gate_version",
                      "gate_digest", "approval"):
                if k not in gate:
                    raise UnifiedSpecError(
                        "skill %r gate record missing %r"
                        % (skill, k))
            gv = gate["gate_version"]
            if (not isinstance(gv, str)
                    or not gv.strip()):
                raise UnifiedSpecError(
                    "skill %r gate_version empty/invalid"
                    % skill)
            # 严格门引用:报告禁止携带任何覆盖字段(threshold
            # /gate_def 重述等);验证一律采用注册完整门。
            allowed = {"task_id", "gate_version",
                       "gate_digest", "approval"}
            extra_keys = set(gate) - allowed
            if extra_keys:
                raise UnifiedSpecError(
                    "gate record carries forbidden override "
                    "fields %r (strict reference only; the "
                    "registered gate is authoritative)"
                    % sorted(extra_keys))
            ap = gate["approval"]
            if (not isinstance(ap, dict)
                    or not isinstance(ap.get("channel"),
                                      str)
                    or not ap.get("channel").strip()
                    or not isinstance(ap.get("ref"), str)
                    or not ap.get("ref").strip()):
                raise UnifiedSpecError(
                    "skill %r approval must be structured "
                    "{channel,ref} (arbitrary strings "
                    "cannot self-attest)" % skill)
            # 报告侧 task 绑定先查(先于注册表)
            if gate["task_id"] != UNIFIED_TASK["task_id"]:
                raise UnifiedSpecError(
                    "skill %r gate task binding mismatch"
                    % skill)
            # 注册条目先取:版本+完整门定义+权威批准
            reg = (REGISTRY_GATES if registry_gates is None
                   else registry_gates)
            entry = reg.get(skill)
            if not entry:
                raise UnifiedSpecError(
                    "skill %r has no registered frozen gate "
                    "(production registry empty this round; "
                    "simulated approvals are test-isolation "
                    "only)" % skill)
            # 注册条目须含版本+完整门定义;digest 每次现算
            reg_ver = entry.get("gate_version")
            if (not isinstance(reg_ver, str)
                    or not reg_ver.strip()):
                raise UnifiedSpecError(
                    "registry entry for %r lacks gate_version"
                    % skill)
            if gv != reg_ver:
                raise UnifiedSpecError(
                    "skill %r gate_version %r != registered "
                    "%r" % (skill, gv, reg_ver))
            want_digest = _gate_digest(entry["gate_def"])
            if gate["gate_digest"] != want_digest:
                raise UnifiedSpecError(
                    "skill %r gate_digest %r != registered "
                    "%r (recomputed from full gate_def)"
                    % (skill, gate["gate_digest"][:12],
                       want_digest[:12]))
            # approval 与注册权威完全一致(注册无批准→报告
            # 不得自补;伪造 channel/ref 拒)
            reg_ap = entry.get("approval")
            if (not isinstance(reg_ap, dict)
                    or not isinstance(
                        reg_ap.get("channel"), str)
                    or not reg_ap.get("channel").strip()
                    or not isinstance(
                        reg_ap.get("ref"), str)
                    or not reg_ap.get("ref").strip()):
                raise UnifiedSpecError(
                    "skill %r registered gate carries no "
                    "authoritative approval — report "
                    "cannot supply one" % skill)
            if ap != reg_ap:
                raise UnifiedSpecError(
                    "skill %r approval %r != registered "
                    "authoritative %r (exact match "
                    "required)" % (skill, ap, reg_ap))


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
