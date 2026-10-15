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
    assert list(v) == uc.OBS_COLUMNS
    assert v["s"] == 1 and v["q"] == 0.75


def test_obs_rejects_extra_future_field():
    bad = dict(STATE, future_return=0.5)
    with pytest.raises(uc.UnifiedSpecError,
                       match="non-contract fields"):
        uc.obs_vector(bad, ACCT, HOR)


def test_column_permutation_detected():
    s = ser()
    uc.verify_serialization(s, {**STATE, **ACCT, **HOR})
    swapped = dict(s)
    swapped["names"] = ["c", "g", "s", "q"] + uc.OBS_COLUMNS[4:]
    with pytest.raises(uc.UnifiedSpecError,
                       match="permutation|names"):
        uc.verify_serialization(
            swapped, {**STATE, **ACCT, **HOR})


def test_obs_vector_columns_strictly_frozen():
    # 未来列/未知列/重复列/改序全拒
    for bad_cols in (
            ["future_return"] + uc.OBS_COLUMNS[1:],
            ["c", "c"] + uc.OBS_COLUMNS[2:],
            list(reversed(uc.OBS_COLUMNS)),
            uc.OBS_COLUMNS[:-1]):
        with pytest.raises(uc.UnifiedSpecError,
                           match="frozen OBS_COLUMNS"):
            uc.obs_vector(STATE, ACCT, HOR,
                          columns=bad_cols)
    # 唯一合法=逐字冻结序
    v = uc.obs_vector(STATE, ACCT, HOR,
                      columns=uc.OBS_COLUMNS)
    assert list(v) == uc.OBS_COLUMNS


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
                       match="mutually-exclusive"):
        uc.check_same_obs_mutex(t)


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
         "action_families": uc.ACTION_FAMILIES}
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
    k = dict(k, s=dict(k["s"], hold_p=0.10))
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
              "solvency_capped": 2.0}, "non-finite"),
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
              "solvency_capped": 1.0}, "non-finite"),
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
def test_arm_a_interior_gate_impossible():
    # 适用域:flat 起点才套上界
    uc.check_action_expressiveness(
        {"arm": "A", "interval": [0.3, 0.6],
         "threshold": 0.4, "initial_state": "flat"})
    with pytest.raises(uc.UnifiedSpecError,
                       match="not expressible"):
        uc.check_action_expressiveness(
            {"arm": "A", "interval": [0.3, 0.6],
             "threshold": 0.8, "initial_state": "flat"})
    uc.check_action_expressiveness(
        {"arm": "A", "interval": [0.6, 1.0],
         "threshold": 0.8, "initial_state": "flat"})
    # 非flat起点不在上界规则适用域(仅校验区间/门合法性)
    uc.check_action_expressiveness(
        {"arm": "A", "interval": [0.3, 0.6],
         "threshold": 0.8, "initial_state": "held"})


def test_expressiveness_input_validation():
    for bad in ({"arm": "C", "interval": [.1, .2],
                 "threshold": .5,
                 "initial_state": "flat"},
                {"arm": "A", "interval": [.6, .3],
                 "threshold": .5,
                 "initial_state": "flat"},
                {"arm": "A", "interval": [-1.5, .3],
                 "threshold": .5,
                 "initial_state": "flat"},
                {"arm": "A", "interval": [.1, .2],
                 "threshold": float("nan"),
                 "initial_state": "flat"}):
        with pytest.raises(uc.UnifiedSpecError):
            uc.check_action_expressiveness(bad)


def test_arm_b_reachability_stays_candidate():
    uc.check_action_expressiveness(
        {"arm": "B", "interval": [0.3, 0.6],
         "threshold": 0.8, "initial_state": "flat"})


def test_decode_identity():
    uc.check_decode_identity({"actions": [
        {"decode_id": "P0CategoryMax-v1", "a": 1}]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="mixed decode"):
        uc.check_decode_identity({"actions": [
            {"decode_id": "P0CategoryMax-v1"},
            {"decode_id": "mixture-mean-v1"}]})
    with pytest.raises(uc.UnifiedSpecError,
                       match="lacks decode_id"):
        uc.check_decode_identity({"actions": [{"a": 1}]})


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
        # 缺 task 绑定/缺结构化批准也拒
        with pytest.raises(uc.UnifiedSpecError,
                           match="task binding"):
            uc.check_graduation_claim(
                {"direction_neutral_flat": {
                    "graduated": True, "gate": {
                        "task_id": "other-task",
                        "gate_version": "1",
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
                        "approval": "approved"}}})
    finally:
        uc.SEVEN_SKILLS.clear()
        uc.SEVEN_SKILLS.update(saved)


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
