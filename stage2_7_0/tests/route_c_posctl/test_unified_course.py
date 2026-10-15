# -*- coding: utf-8 -*-
"""UNIFIED_COURSE_CONTRACT_V1 阶段A 纯数据测试。

零 bank 生成/零参考求解/零候选加载/零训练;不改生产信任表/奖励。
"""
import pathlib
import sys

import pytest

SRC = pathlib.Path(__file__).resolve().parents[2] / "src"
sys.path.insert(0, str(SRC))

from rl_posctl.skill_p0 import unified_course as uc  # noqa: E402
from rl_posctl.skill_p0 import course_contract as cc  # noqa: E402


STATE = {"c": 1, "g": 0, "q": 0.75, "s": 1}
ACCT = {"account_exposure": 0.1,
        "account_solvency": 9.5}
HOR = {"remaining_horizon": 32, "total_horizon": 64}


def ser(**overrides):
    st = dict(STATE, **overrides)
    vals = dict(st)
    vals.update(ACCT)
    vals.update(HOR)
    names = uc.OBS_COLUMNS
    return {"names": names,
            "values": [vals[c] for c in names]}


# ---- 观察契约/列序 -------------------------------------------
def test_obs_vector_binds_by_name():
    v = uc.obs_vector(STATE, ACCT, HOR)
    assert list(v) == list(uc.OBS_COLUMNS)
    assert v["s"] == 1 and v["q"] == 0.75


def test_obs_rejects_extra_future_field():
    bad = dict(STATE, future_return=0.5)
    with pytest.raises(uc.UnifiedSpecError,
                       match="non-contract fields"):
        uc.obs_vector(bad, ACCT, HOR)


def test_column_permutation_detected():
    s = ser()
    uc.verify_serialization_complete(s, {**STATE, **ACCT, **HOR})
    swapped = dict(s)
    swapped["names"] = ["c", "g", "s", "q"] + list(uc.OBS_COLUMNS[4:])
    with pytest.raises(uc.UnifiedSpecError,
                       match="permutation|names"):
        uc.verify_serialization_complete(
            swapped, {**STATE, **ACCT, **HOR})


def test_obs_vector_columns_strictly_frozen():
    # 未来列/未知列/重复列/改序全拒
    for bad_cols in (
            ["future_return"] + list(uc.OBS_COLUMNS[1:]),
            ["c", "c"] + list(uc.OBS_COLUMNS[2:]),
            list(reversed(uc.OBS_COLUMNS)),
            list(uc.OBS_COLUMNS[:-1])):
        with pytest.raises(uc.UnifiedSpecError,
                           match="frozen OBS_COLUMNS"):
            uc.obs_vector(STATE, ACCT, HOR,
                          columns=bad_cols)
    # 唯一合法=逐字冻结序
    v = uc.obs_vector(STATE, ACCT, HOR,
                      columns=uc.OBS_COLUMNS)
    assert list(v) == list(uc.OBS_COLUMNS)


# ---- 同 obs 互斥标签 ----------------------------------------
def _hold():
    return {"arm": "A", "kind": "hold"}


def _atom(v):
    return {"arm": "A", "kind": "atom", "value": v}


def _iv(lo, hi):
    return {"arm": "A", "kind": "interval",
            "lo": lo, "hi": hi}


def test_same_obs_conflict_rejected():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    t = [{"obs": obs, "allowed_actions": [_atom(1.0)]},
         {"obs": obs, "allowed_actions": [_atom(-1.0)]}]
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex(t)


def test_same_obs_common_intersection_semantics():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    # 两两重叠但共同交集为空 → 冲突
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs,
             "allowed_actions": [_iv(0.0, 0.5)]},
            {"obs": obs,
             "allowed_actions": [_iv(0.3, 0.8)]},
            {"obs": obs,
             "allowed_actions": [_iv(0.6, 1.0)]}])
    # 同名标签不同区间(有共同重叠)→ 通过
    uc.check_same_obs_mutex([
        {"obs": obs, "label": "amplitude_hi",
         "allowed_actions": [_iv(0.3, 0.6)]},
        {"obs": obs, "label": "amplitude_hi",
         "allowed_actions": [_iv(0.4, 0.7)]}])
    # 不同表示但重叠(原子在区间)→ 通过
    uc.check_same_obs_mutex([
        {"obs": obs,
         "allowed_actions": [_iv(0.5, 1.0)]},
        {"obs": obs,
         "allowed_actions": [_atom(1.0)]}])
    # hold 组 vs 数值组 → 共同交集空 → 冲突
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": [_hold()]},
            {"obs": obs,
             "allowed_actions": [_atom(1.0)]}])


def test_g1g2_g3_disjoint_atoms_rejected():
    """完整单反例:G1={-1},G2={-1},G3={+1} 同 obs——
    两两多有重叠但共同交集空,必须拒(不得 flatten 后
    见任意两项重叠就放行)。"""
    obs = uc.obs_vector(STATE, ACCT, HOR)
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs,
             "allowed_actions": [_atom(-1.0)]},
            {"obs": obs,
             "allowed_actions": [_atom(-1.0)]},
            {"obs": obs,
             "allowed_actions": [_atom(1.0)]}])


def test_single_record_union_atoms_directly_compatible():
    """完整单反例:单条记录自身允许并集 {-1,+1} 合法——
    直接相容(不得因"内部两项不相交"误拒);两条同并集亦过。"""
    obs = uc.obs_vector(STATE, ACCT, HOR)
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions":
         [_atom(-1.0), _atom(1.0)]}])       # 单条并集
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions":
         [_atom(-1.0), _atom(1.0)]},
        {"obs": obs, "allowed_actions":
         [_atom(-1.0), _atom(1.0)]}])       # 两记录共同交集非空
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions":
         [_atom(-1.0), _atom(1.0)]},
        {"obs": obs,
         "allowed_actions": [_atom(-1.0)]}])  # 交={-1}


def test_precise_interval_intersection():
    """[.21,.31]∩[.25,.35]=[.25,.31] 真实非空——固定五点
    采样会误拒;精确端点/中点运算必须放行。"""
    obs = uc.obs_vector(STATE, ACCT, HOR)
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [_iv(0.21, 0.31)]},
        {"obs": obs, "allowed_actions": [_iv(0.25, 0.35)]}])
    # 规范化并集:同组两段重叠先合并再参与交集
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions":
         [_iv(0.0, 0.3), _iv(0.25, 0.6)]},
        {"obs": obs, "allowed_actions": [_iv(0.5, 0.8)]}])
    # 真实不相交仍拒
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs,
             "allowed_actions": [_iv(0.21, 0.25)]},
            {"obs": obs,
             "allowed_actions": [_iv(0.30, 0.35)]}])


def test_open_interval_flags_respected():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    # (0.2,0.3) 开 vs [0.3,0.4] 闭:端点 0.3 不在开区间,
    # 但相邻端点中点 0.25∈开区间?0.25∉[0.3,0.4] → 空,拒
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": [
                dict(_iv(0.2, 0.3), open=True)]},
            {"obs": obs, "allowed_actions": [
                _iv(0.3, 0.4)]}])
    # (0.2,0.4) 开 vs [0.25,0.35] 闭 → 内部 0.25 命中,过
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [
            dict(_iv(0.2, 0.4), open=True)]},
        {"obs": obs, "allowed_actions": [
            _iv(0.25, 0.35)]}])


def test_expressiveness_empty_atoms_rejected():
    with pytest.raises(uc.UnifiedSpecError,
                       match="empty atom target"):
        uc.evaluate_action_expressiveness(
            _gq(metric="deterministic_hit", atoms=[]))


def test_same_obs_consistent_union_ok():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [_atom(1.0)]},
        {"obs": obs,
         "allowed_actions": [_iv(0.6, 1.0)]}])   # 原子在区间
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [_hold()]}])
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [_iv(.3, .6)]},
        {"obs": obs, "allowed_actions": [_iv(.5, .8)]}])


def test_empty_allowed_set_rejected():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    with pytest.raises(uc.UnifiedSpecError,
                       match="empty allowed"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": []}])


def test_typed_action_entry_validation():
    for bad in ({"arm": "C", "kind": "hold"},
                {"arm": "A", "kind": "spin"},
                {"arm": "A", "kind": "atom", "value": 0.5},
                {"arm": "A", "kind": "interval",
                 "lo": 0.6, "hi": 0.3},        # 倒置
                {"arm": "A", "kind": "interval",
                 "lo": -1.2, "hi": 0.3},       # 越界
                {"arm": "A", "kind": "interval",
                 "lo": float("nan"), "hi": 0.3},
                {"arm": "A", "kind": "atom", "value": 1.0,
                 "p_gate": float("nan")}):
        with pytest.raises(uc.UnifiedSpecError):
            uc.check_same_obs_mutex([{
                "obs": uc.obs_vector(STATE, ACCT, HOR),
                "allowed_actions": [bad]}])


# ---- 隐藏换任务 ----------------------------------------------
def _variant(**over):
    return uc.make_task_spec(**over)


def _variant_old(**over):
    v = {"task_id": "t",
         "transition_kernel": uc.UNIFIED_TASK[
             "transition_kernel"],
         "drift": uc.UNIFIED_TASK["drift"],
         "mu_candidate": uc.UNIFIED_TASK["mu_candidate"],
         "noise": uc.UNIFIED_TASK["noise"],
         "sigma_by_g": uc.UNIFIED_TASK["sigma_by_g"],
         "economy": uc.UNIFIED_TASK["economy"],
         "horizon": uc.UNIFIED_TASK["horizon"],
         "account_encoding": uc.UNIFIED_TASK[
             "account_encoding"],
         "action_families": uc.ACTION_FAMILIES,
         "spec_versions": uc.SPEC_VERSIONS,
         "obs_columns": uc.OBS_COLUMNS,
         "transition_independence":
             uc.UNIFIED_TASK["transition_independence"]}
    v.update(over)
    return v


def test_hidden_swap_full_field_coverage():
    uc.check_hidden_task_swap([_variant(), _variant()])
    for field, over in (
            ("mu_candidate", {"mu_candidate": 2.4e-3}),
            ("sigma_by_g", {"sigma_by_g": {"0": 0.05,
                                           "1": 0.06}}),
            ("noise", {"noise": "gauss_candidate"}),
            ("account_encoding",
             {"account_encoding": dict(
                 uc.UNIFIED_TASK["account_encoding"],
                 solvency="asinh(e)/4_candidate")}),
            ("obs_columns", {"obs_columns":
                             ["c", "g", "q", "s", "a", "b",
                              "r", "h"]}),
            ("decode_ids", {"action_families": dict(
                uc.ACTION_FAMILIES,
                B_asymmetric_beta=dict(
                    uc.ACTION_FAMILIES[
                        "B_asymmetric_beta"],
                    decode_id="other-v9"))})):
        with pytest.raises(uc.UnifiedSpecError,
                           match="hidden task swap"):
            uc.check_hidden_task_swap(
                [_variant(), _variant(**over)])
    k = dict(uc.UNIFIED_TASK["transition_kernel"])
    k = dict(k, s=dict(k["s"], hold_p=0.10,
                       resample_p=0.90))
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap(
            [_variant(), _variant(transition_kernel=k)])
    e = dict(uc.UNIFIED_TASK["economy"], fee_rate=2e-3)
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap(
            [_variant(), _variant(economy=e)])


# ---- 账本一致性 ----------------------------------------------
def test_ledger_consistency_and_truncation():
    uc.check_ledger_account(
        {"exposure": 0.5, "solvency_raw": 2.0,
         "solvency_capped": 2.0})
    uc.check_ledger_account(
        {"exposure": 0.0, "solvency_raw": float("inf"),
         "solvency_capped": 40.0})
    uc.check_ledger_account(
        {"exposure": 0.01, "solvency_raw": 100.0,
         "solvency_capped": 40.0})
    for bad, pat in (
            ({"exposure": 0.5, "solvency_raw": 999.0,
              "solvency_capped": 999.0}, "1/\\|e\\|"),
            ({"exposure": 0.5,
              "solvency_raw": float("nan"),
              "solvency_capped": 2.0}, "not finite"),
            ({"exposure": 0.0,
              "solvency_raw": float("-inf"),
              "solvency_capped": 40.0}, r"\+inf"),
            ({"exposure": 0.0, "solvency_raw": 40.0,
              "solvency_capped": 40.0}, r"\+inf"),
            ({"exposure": 0.0,
              "solvency_raw": float("inf"),
              "solvency_capped": 999.0}, "fixed cap"),
            ({"exposure": float("nan"),
              "solvency_raw": 1.0,
              "solvency_capped": 1.0}, "not finite"),
            ({"exposure": 0.5}, "missing")):
        with pytest.raises(uc.UnifiedSpecError,
                           match=pat):
            uc.check_ledger_account(bad)


# ---- 未来字段/输入白名单 -------------------------------------
def test_future_inputs_rejected():
    uc.check_future_fields(dict(STATE))
    with pytest.raises(uc.UnifiedSpecError,
                       match="forbidden input"):
        uc.check_future_fields(
            dict(STATE, future_signal=1))
    with pytest.raises(uc.UnifiedSpecError,
                       match="outside allowlist"):
        uc.check_future_fields(
            dict(STATE, secret_z=0))


# ---- 动作表达性 ----------------------------------------------
def _gq(arm="A", metric="distribution_probability",
        decoder="P0CategoryMax-v1", lo=.3, hi=.6,
        p=.8, atoms=None, initial_state="flat",
        hold_allowed=False,
        target_kind="rebal_target"):
    return {"arm": arm, "metric": metric, "decoder": decoder,
            "interval": [lo, hi], "threshold": p,
            "atoms": atoms, "initial_state": initial_state,
            "hold_allowed": hold_allowed,
            "target_kind": target_kind}


def test_expressiveness_status_machine():
    # proved_impossible:A+分布概率+单侧内部+>.5
    r = uc.evaluate_action_expressiveness(_gq())
    assert r["status"] == "proved_impossible"
    assert "decode-independent" in r["reason"] or \
        "decode-" in r["reason"]
    # 换解码不能规避(分布质量上界与解码无关)
    r2 = uc.evaluate_action_expressiveness(
        _gq(decoder="mixture-mean-v1"))
    assert r2["status"] == "proved_impossible"
    # 端点区间不适用内部上界→not_established
    r3 = uc.evaluate_action_expressiveness(
        _gq(lo=.6, hi=1.0, p=.8))
    assert r3["status"] == "not_established"
    # validated:仅 A+CategoryMax+deterministic_hit+原子目标
    r4 = uc.evaluate_action_expressiveness(
        _gq(metric="deterministic_hit", atoms=[1.0]))
    assert r4["status"] == "validated"
    # B 一律 not_established(不得与已达等价)
    for metric in ("distribution_probability",
                   "deterministic_hit"):
        rb = uc.evaluate_action_expressiveness(
            _gq(arm="B", metric=metric, atoms=[1.0]))
        assert rb["status"] == "not_established"


def test_expressiveness_input_validation():
    for bad in (_gq(arm="C"), _gq(lo=.6, hi=.3),
                _gq(lo=-1.5), _gq(p=float("nan")),
                _gq(metric="vibe"), _gq(decoder="v9"),
                _gq(initial_state="midair"),
                dict(_gq(), hold_allowed=None),
                _gq(target_kind="vague")):
        with pytest.raises(uc.UnifiedSpecError):
            uc.evaluate_action_expressiveness(bad)


def test_expressiveness_applicability_domain_held_hold():
    # 已有仓位+允许 HOLD+有效敞口口径:[.3,.6] 命中概率可为 1
    # (HOLD 保持数量,敞口随价漂移停区间内)——不得判 proved_
    # impossible,必须 not_established。
    r = uc.evaluate_action_expressiveness(_gq(
        initial_state="held", hold_allowed=True,
        target_kind="effective_exposure"))
    assert r["status"] == "not_established"
    # flat 但 HOLD 参与门(有效敞口含 HOLD 混合):同 not_established
    r2 = uc.evaluate_action_expressiveness(_gq(
        initial_state="flat", hold_allowed=True,
        target_kind="effective_exposure"))
    assert r2["status"] == "not_established"
    # 已证明适用域保持:flat+rebal 目标+HOLD 不参与→proved
    r3 = uc.evaluate_action_expressiveness(_gq())
    assert r3["status"] == "proved_impossible"
    assert "proved domain" in r3["reason"]


def _dec(arm="A", did="P0CategoryMax-v1", scope=None,
         metric="deterministic_hit"):
    e = {"task_id": uc.UNIFIED_TASK["task_id"],
         "arm": arm, "metric": metric, "decode_id": did}
    if scope:
        e["scope"] = scope
    return e


def test_decode_identity_bound_to_task_arm_metric():
    uc.check_decode_identity({"actions": [_dec()]})
    # A+mixture-mean(B 的候选解码)不得过
    with pytest.raises(uc.UnifiedSpecError,
                       match="not declared for arm"):
        uc.check_decode_identity({"actions": [
            _dec(did="mixture-mean-v1")]})
    # B 的两个已声明解码都可
    uc.check_decode_identity({"actions": [
        _dec(arm="B")]})
    uc.check_decode_identity({"actions": [
        _dec(arm="B", did="mixture-mean-v1")]})
    # 缺字段/未知 arm/metric/task 绑定
    with pytest.raises(uc.UnifiedSpecError,
                       match="lacks"):
        uc.check_decode_identity({"actions": [{"a": 1}]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="unknown arm"):
        uc.check_decode_identity({"actions": [
            _dec(arm="C")]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="unknown metric"):
        uc.check_decode_identity({"actions": [
            _dec(metric="vibe")]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="task binding"):
        uc.check_decode_identity({"actions": [
            dict(_dec(), task_id="other")]})
    # 混用 decode / 历史 scope 混排
    # 混用两个不同 decode(A:CategoryMax + B:mixture-mean)→拒
    with pytest.raises(uc.UnifiedSpecError,
                       match="mixed decode"):
        uc.check_decode_identity({"actions": [
            _dec(), _dec(arm="B",
                         did="mixture-mean-v1")]})
    # 同一公共解码跨 A/B(当前既有主接口)→允许
    uc.check_decode_identity({"actions": [
        _dec(), _dec(arm="B")]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="cannot mix"):
        uc.check_decode_identity({"actions": [
            _dec(), _dec(scope="historical_diagnostic")]})
    # 纯历史诊断报告(另身份)允许
    uc.check_decode_identity({"actions": [
        _dec(scope="historical_diagnostic")]})


# ---- 门/毕业 -------------------------------------------------
def test_gates_uncalibrated_no_claim_no_number_blacklist():
    for k, v in uc.SEVEN_SKILLS.items():
        assert v["gate_status"] == "not_specified", k
        assert v["negative_controls"]
    uc.check_graduation_claim({"direction_neutral_flat": {
        "graduated": False}})
    # 未冻结:任何 graduated/门记录(数字或结构)都拒——
    # 拒绝依据=未校准+无独立批准身份,非数字黑名单
    with pytest.raises(uc.UnifiedSpecError,
                       match="not frozen"):
        uc.check_graduation_claim(
            {"direction_neutral_flat": {
                "graduated": True}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="not frozen"):
        uc.check_graduation_claim(
            {"direction_neutral_flat": {
                "graduated": True, "gate": 0.90}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="not frozen"):
        uc.check_graduation_claim(
            {"direction_neutral_flat": {
                "graduated": False, "gate": {
                    "task_id": "t", "gate_version": "1",
                    "approval": {"channel": "c",
                                 "ref": "r"}}}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="unknown skill"):
        uc.check_graduation_claim({"ghost": {
            "graduated": False}})


def test_frozen_gate_graduation_needs_structured_identity():
    # 构造临时 frozen 状态验证身份链要求(不改全局)
    import copy
    saved = copy.deepcopy(uc.SEVEN_SKILLS)
    try:
        uc.SEVEN_SKILLS["direction_neutral_flat"] = dict(
            saved["direction_neutral_flat"],
            gate_status="frozen")
        # 空凭字符串/数字不能毕业
        with pytest.raises(uc.UnifiedSpecError,
                           match="structured gate record"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": "frozen"}})
        with pytest.raises(uc.UnifiedSpecError,
                           match="structured gate record"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": 0.91}})
        with pytest.raises(uc.UnifiedSpecError,
                           match="gate_version empty"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": " ",
                        "gate_digest": "0" * 64,
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}})
        # 缺 task 绑定/缺结构化批准也拒
        with pytest.raises(uc.UnifiedSpecError,
                           match="task binding"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": {
                        "task_id": "other-task",
                        "gate_version": "1",
                        "gate_digest": "0" * 64,
                        "approval": {"channel": "c",
                                     "ref": "r"}}}})
        with pytest.raises(uc.UnifiedSpecError,
                           match="approval"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "1",
                        "gate_digest": "0" * 64,
                        "approval": "approved"}}})
    finally:
        uc.SEVEN_SKILLS.clear()
        uc.SEVEN_SKILLS.update(saved)


def test_verify_serialization_partial_and_complete():
    s0 = ser()
    with pytest.raises(uc.UnifiedSpecError,
                       match="non-empty"):
        uc.verify_serialization_partial(s0, {})
    # partial:子集对即可过(另名,不算完整已验)
    uc.verify_serialization_partial(s0, {"s": 1})
    # complete:缺任一字段拒;expected 只给 {'c':1} 而其余七列
    # 错值必须失败
    with pytest.raises(uc.UnifiedSpecError,
                       match="ALL 8 fields"):
        uc.verify_serialization_complete(s0, {"c": 1})
    wrong = {**STATE, **ACCT, **HOR, "s": -1}
    with pytest.raises(uc.UnifiedSpecError):
        uc.verify_serialization_complete(s0, wrong)


def test_frozen_columns_immutable():
    import pytest as _pt
    with _pt.raises(TypeError):
        uc.OBS_COLUMNS[0] = "x"
    assert isinstance(uc.OBS_COLUMNS, tuple)
    assert uc.ACTOR_INPUTS is uc.OBS_COLUMNS   # 共享不可变元组


def test_spec_versions_and_semantics_completeness():
    t = uc.UNIFIED_TASK
    for k in ("obs", "reward", "action", "execution"):
        assert "candidate" in uc.SPEC_VERSIONS[k]
    econ = t["economy"]
    assert econ["price_tick"] == 0.0
    assert econ["reward_scale"] == 1.0
    term = econ["termination_threefold"]
    for k in ("invalid_terminal", "pre_action_risk",
              "terminal_liquidation"):
        assert k in term
    assert "transition_independence" in t
    enc = t["account_encoding"]["solvency"]
    assert "min(solvency, 40)" in enc
    assert t["account_provenance"].startswith(
        "not_established")


def test_action_family_facts():
    a = uc.ACTION_FAMILIES["A_symmetric_beta_atoms"]
    assert "REBALANCE 原子 {-1, 0, +1}" in a["structure"]
    b = uc.ACTION_FAMILIES["B_asymmetric_beta"]
    # 当前 P0 A/B 公共解码=CategoryMax;mixture-mean 仅候选
    assert b["decode_id"] == "P0CategoryMax-v1"
    assert b["candidate_decode"] == "mixture-mean-v1"
    assert b["reachability"] == "not_established"


def test_numeric_purification_edges():
    # solvency_capped=NaN / raw='nan' 字符串 / bool 全拒
    for bad, pat in (
            ({"exposure": 0.5, "solvency_raw": 2.0,
              "solvency_capped": float("nan")},
             "solvency_capped"),
            ({"exposure": 0.5, "solvency_raw": "nan",
              "solvency_capped": 2.0}, "solvency_raw"),
            ({"exposure": 0.5, "solvency_raw": True,
              "solvency_capped": 2.0}, "solvency_raw"),
            ({"exposure": 0.0,
              "solvency_raw": float("inf"),
              "solvency_capped": "40"}, "solvency_capped")):
        with pytest.raises(uc.UnifiedSpecError,
                           match=pat):
            uc.check_ledger_account(bad)


def test_probability_gates_bounded():
    # p_gate 2/-1 拒;threshold 2/-1 拒
    for pg in (2.0, -1.0):
        with pytest.raises(uc.UnifiedSpecError,
                           match=r"p_gate out of \[0,1\]"):
            uc.check_same_obs_mutex([{
                "obs": uc.obs_vector(STATE, ACCT, HOR),
                "allowed_actions": [
                    dict(_atom(1.0), p_gate=pg)]}])
    for th in (2.0, -1.0):
        with pytest.raises(uc.UnifiedSpecError,
                           match=r"threshold out of \[0,1\]"):
            uc.evaluate_action_expressiveness(
                _gq(p=th))


def test_signature_requires_fields_no_none_none():
    # 空 spec/缺字段不得经 None==None 判同任务
    with pytest.raises(uc.UnifiedSpecError,
                       match="missing required field"):
        uc.check_hidden_task_swap(
            [{"task_id": "t"}, {"task_id": "t"}])
    v = _variant()
    for drop in ("mu_candidate", "economy", "noise",
                 "action_families"):
        v2 = {k: x for k, x in v.items() if k != drop}
        with pytest.raises(uc.UnifiedSpecError,
                           match="missing required field"):
            uc.check_hidden_task_swap([v, v2])
    # spec_versions 与完整动作结构入签名
    v3 = _variant()
    v3["spec_versions"] = dict(uc.SPEC_VERSIONS,
                               reward="other-v2")
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([_variant(), v3])
    v4 = _variant()
    v4["action_families"] = dict(
        uc.ACTION_FAMILIES,
        A_symmetric_beta_atoms=dict(
            uc.ACTION_FAMILIES[
                "A_symmetric_beta_atoms"],
            structure="changed-structure"))
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([_variant(), v4])


def test_gate_registry_digest_chain_test_isolation():
    import copy
    saved = copy.deepcopy(uc.SEVEN_SKILLS)
    try:
        uc.SEVEN_SKILLS["direction_neutral_flat"] = dict(
            saved["direction_neutral_flat"],
            gate_status="frozen")
        # 生产注册表空:即使结构齐全也拒(本轮无新冻结门)
        with pytest.raises(uc.UnifiedSpecError,
                           match="no registered frozen gate"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True,
                    "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "v1",
                        "gate_digest": "0" * 64,
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}})
        # 空串 gate_version 拒
        with pytest.raises(uc.UnifiedSpecError,
                           match="gate_version empty"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True,
                    "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "",
                        "gate_digest": "0" * 64,
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}},
                registry_gates={"direction_neutral_flat": {
                    "gate_version": "v1",
                    "gate_def": {"x": 1}}})
        # 测试隔离注入临时注册表:摘要不一致拒;一致才过
        tmp_reg = {"direction_neutral_flat": {
            "gate_version": "v1",
            "gate_def": {"metric": "min_over_grid",
                         "threshold": 0.8}}}
        good_digest = uc._gate_digest(
            tmp_reg["direction_neutral_flat"][
                "gate_def"])
        # 伪造 gate_version:对不上注册版本→拒
        with pytest.raises(uc.UnifiedSpecError,
                           match="gate_version .* != registered"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True,
                    "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "v9",
                        "gate_digest": uc._gate_digest(
                            tmp_reg[
                                "direction_neutral_flat"][
                                "gate_def"]),
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}},
                registry_gates=tmp_reg)
        # 额外覆盖字段(threshold=-999)→严格引用拒
        with pytest.raises(uc.UnifiedSpecError,
                           match="forbidden override"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True,
                    "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "v1",
                        "gate_digest": uc._gate_digest(
                            tmp_reg[
                                "direction_neutral_flat"][
                                "gate_def"]),
                        "threshold": -999,
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}},
                registry_gates=tmp_reg)
        with pytest.raises(uc.UnifiedSpecError,
                           match="gate_digest"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True,
                    "gate": {
                        "task_id": uc.UNIFIED_TASK[
                            "task_id"],
                        "gate_version": "v1",
                        "gate_digest": "f" * 64,
                        "approval": {
                            "channel": "c",
                            "ref": "r"}}}},
                registry_gates=tmp_reg)
        uc.check_graduation_claim(
            {"direction_neutral_flat": {
                "graduated": True,
                "gate": {
                    "task_id": uc.UNIFIED_TASK["task_id"],
                    "gate_version": "v1",
                    "gate_digest": good_digest,
                    "approval": {
                        "channel": "c", "ref": "r"}}}},
            registry_gates=tmp_reg)
    finally:
        uc.SEVEN_SKILLS.clear()
        uc.SEVEN_SKILLS.update(saved)
    assert uc.REGISTRY_GATES == {}   # 生产仍空


def test_spec_versions_and_independence_bound():
    # SPEC_VERSIONS 真正进入任务本体与快照
    assert uc.UNIFIED_TASK["spec_versions"] is \
        uc.SPEC_VERSIONS or uc.UNIFIED_TASK[
            "spec_versions"] == uc.SPEC_VERSIONS
    snap = uc.build_registry_snapshot()
    assert snap["task"]["spec_versions"] == \
        uc.SPEC_VERSIONS
    # transition_independence 绑定进任务与签名
    assert "transition_independence" in uc.UNIFIED_TASK
    v = _variant()
    v2 = _variant(transition_independence="coupled_candidate")
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([v, v2])
    for drop in ("transition_independence",
                 "spec_versions"):
        v3 = {k: x for k, x in _variant().items()
              if k != drop}
        with pytest.raises(uc.UnifiedSpecError,
                           match="missing required field"):
            uc.check_hidden_task_swap([_variant(), v3])


def test_interval_union_boundary_cases():
    """收尾单组1 三个裁定+间隙不填平+同端 AND 语义。"""
    obs = uc.obs_vector(STATE, ACCT, HOR)
    # [-.5,0)∪(0,.5] 与 {0}:必须无交→冲突
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": [
                dict(_iv(-0.5, 0.0), open="hi"),
                dict(_iv(0.0, 0.5), open="lo")]},
            {"obs": obs,
             "allowed_actions": [_atom(0.0)]}])
    # [-.5,.5)∪[0,.5] 与 [.5,1]:有交(.5 闭)→过
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [
            dict(_iv(-0.5, 0.5), open="hi"),
            _iv(0.0, 0.5)]},
        {"obs": obs,
         "allowed_actions": [_iv(0.5, 1.0)]}])
    # (0,.25]∪[0,.5] 与 [-.5,0]:有交(0 闭)→过
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [
            dict(_iv(0.0, 0.25), open="lo"),
            _iv(0.0, 0.5)]},
        {"obs": obs,
         "allowed_actions": [_iv(-0.5, 0.0)]}])
    # 间隙不被 eps 填平
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs,
             "allowed_actions": [_iv(0.2, 0.3)]},
            {"obs": obs, "allowed_actions": [
                _iv(0.3000000000005, 0.4)]}])
    # 同端合并 AND:(0,.5]∪(0,.3] 左端保持开→与 {0} 仍无交
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": [
                dict(_iv(0.0, 0.5), open="lo"),
                dict(_iv(0.0, 0.3), open="lo")]},
            {"obs": obs,
             "allowed_actions": [_atom(0.0)]}])
    # 嵌套同 hi 不同开闭:hi 开闭=AND→开;区间内部仍有交
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [
            _iv(0.2, 0.5),
            dict(_iv(0.2, 0.5), open="hi")]},
        {"obs": obs,
         "allowed_actions": [_iv(0.45, 0.55)]}])
    # 双方 hi 均开:union 端点仍开(并集=任一含即含,双开才开)
    # → .5 不可达 → 与 [.5,.6] 无交
    with pytest.raises(uc.UnifiedSpecError,
                       match="COMMON INTERSECTION"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": [
                dict(_iv(0.2, 0.5), open="hi"),
                dict(_iv(0.21, 0.5), open="hi")]},
            {"obs": obs,
             "allowed_actions": [_iv(0.5, 0.6)]}])
    # 一闭一开同端:并集端点闭合→.5 可达 → 有交
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": [
            dict(_iv(0.2, 0.5), open="hi"),
            _iv(0.21, 0.5)]},
        {"obs": obs,
         "allowed_actions": [_iv(0.5, 0.6)]}])


def test_make_task_spec_strict_schema():
    snap_task = uc.build_registry_snapshot()["task"]
    assert "obs_columns" in snap_task
    assert "action_families" in snap_task
    uc.check_hidden_task_swap(
        [uc.make_task_spec(), uc.make_task_spec()])
    tk = uc.UNIFIED_TASK["transition_kernel"]
    k = {"transition_kernel": dict(
        tk, s=dict(tk["s"], hold_p=2.0))}
    k2 = {"transition_kernel": dict(
        tk, s=dict(tk["s"], resample_p=-1.0))}
    q_bad_len = {"transition_kernel": dict(
        tk, q=dict(tk["q"], fresh_p=[0.5, 0.5]))}
    q_bad_sum = {"transition_kernel": dict(
        tk, q=dict(tk["q"], fresh_p=[
            0.1, 0.1, 0.1, 0.1, 0.1]))}
    sv_missing = {"spec_versions": {
        "obs": "a", "reward": "b", "action": "c"}}
    sv_extra = {"spec_versions": dict(
        uc.SPEC_VERSIONS, extra="x")}
    hz_bad = {"horizon": {"values": [0, 64]}}
    hz_frac = {"horizon": {"values": [32.5]}}
    mu_nan = {"mu_candidate": float("nan")}
    for over in (k, k2, q_bad_len, q_bad_sum, sv_missing,
                 sv_extra, hz_bad, hz_frac, mu_nan):
        with pytest.raises(uc.UnifiedSpecError):
            uc.make_task_spec(**over)
    # 两份同样无效:进入比较通道前即拒(不判"同任务")
    with pytest.raises(uc.UnifiedSpecError):
        uc.check_hidden_task_swap(
            [uc.make_task_spec(**k),
             uc.make_task_spec(**k)])
    # 有效换值仍被签出
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([
            uc.make_task_spec(),
            uc.make_task_spec(economy=dict(
                uc.UNIFIED_TASK["economy"],
                fee_rate=2e-3))])


def test_obs_domain_strict():
    for bad in ({"s": float("nan")}, {"s": 0.5},
                {"q": 1.5}, {"c": 2}):
        with pytest.raises(uc.UnifiedSpecError):
            uc.obs_vector({**STATE, **bad}, ACCT, HOR)
    with pytest.raises(uc.UnifiedSpecError,
                       match="positive int"):
        uc.obs_vector(STATE, ACCT, {
            "remaining_horizon": -1,
            "total_horizon": 64})
    with pytest.raises(uc.UnifiedSpecError,
                       match="remaining > total"):
        uc.obs_vector(STATE, ACCT, {
            "remaining_horizon": 65,
            "total_horizon": 64})


def test_strict_typing_atoms_open():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    with pytest.raises(uc.UnifiedSpecError,
                       match="numeric non-bool"):
        uc.check_same_obs_mutex([{"obs": obs, "allowed_actions": [
            {"arm": "A", "kind": "atom",
             "value": True}]}])
    with pytest.raises(uc.UnifiedSpecError,
                       match="numeric non-bool"):
        uc.evaluate_action_expressiveness(
            _gq(metric="deterministic_hit",
                atoms=[True]))
    with pytest.raises(uc.UnifiedSpecError,
                       match="numeric non-bool"):
        uc.evaluate_action_expressiveness(
            _gq(metric="deterministic_hit",
                atoms=["1"]))
    with pytest.raises(uc.UnifiedSpecError,
                       match="open flag invalid"):
        uc.check_same_obs_mutex([{"obs": obs, "allowed_actions": [
            dict(_iv(0.1, 0.2), open=1)]}])
    # open=True 严格布尔仍合法
    uc.check_same_obs_mutex([{"obs": obs, "allowed_actions": [
        dict(_iv(0.1, 0.2), open=True)]}])


def test_registry_snapshot_shape_and_isolation():
    snap = uc.build_registry_snapshot()
    assert snap["schema"] == uc.SPEC_SCHEMA
    assert snap["calibration"] == "incomplete"
    assert len(snap["skills"]) == 7
    assert snap["combination_module"][
        "gate_status"] == "not_specified"
    assert snap["task"]["status"] == "candidate_uncalibrated"
    # 深拷贝:改快照不反写全局注册
    snap["skills"]["direction_neutral_flat"][
        "gate_status"] = "hacked"
    snap["task"]["mu_candidate"] = 9.9
    assert uc.SEVEN_SKILLS["direction_neutral_flat"][
        "gate_status"] == "not_specified"
    assert uc.UNIFIED_TASK["mu_candidate"] == 1.2e-3


# ---- 阶段选择语义 --------------------------------------------
def test_phase_selection_declares_no_future_swap():
    ps = uc.UNIFIED_TASK["phase_selection"]
    assert "同一核" in ps["rule"] or "同一" in ps["rule"]
    assert "未来" in ps["rule"]


def test_transition_semantics_precise():
    k = uc.UNIFIED_TASK["transition_kernel"]
    # D2 语义:s 重抽 .22 → hold=.78(不得再写成 hold=.22)
    assert k["s"]["resample_p"] == 0.22
    assert k["s"]["hold_p"] == 0.78
    for f in ("c", "g"):
        assert "resample_dist" in k[f]
        assert k[f]["hold_p"] + k[f]["resample_p"] == 1.0
    assert "fresh_p" in k["q"]
    assert abs(sum(k["q"]["fresh_p"]) - 1.0) < 1e-12


def test_old_c1_contract_untouched():
    # 旧规范仍在且版本不变
    assert cc.CONTRACT_VERSION == "COURSE_CONTRACT_V1"
    c = cc.build_contract()
    assert c["c1"]["direction_gate"]["threshold"] == 0.80
    assert c["c1"]["neutral_gate"]["threshold"] == 0.75
