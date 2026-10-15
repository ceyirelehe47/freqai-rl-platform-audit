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


# ---- 同 obs 互斥标签 ----------------------------------------
def test_same_obs_conflict_rejected():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    t = [{"obs": obs, "allowed_actions": ["rebal_up"]},
         {"obs": obs, "allowed_actions": ["hold_flat"]}]
    with pytest.raises(uc.UnifiedSpecError,
                       match="conflicting labels"):
        uc.check_same_obs_mutex(t)


def test_same_obs_consistent_union_ok():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": ["hold", "rebal_up"]},
        {"obs": obs, "allowed_actions": ["rebal_up"]}])
    uc.check_same_obs_mutex([
        {"obs": obs, "allowed_actions": ["hold"]}])
    assert True


def test_empty_allowed_set_rejected():
    obs = uc.obs_vector(STATE, ACCT, HOR)
    with pytest.raises(uc.UnifiedSpecError,
                       match="empty allowed"):
        uc.check_same_obs_mutex([
            {"obs": obs, "allowed_actions": []}])


# ---- 隐藏换任务 ----------------------------------------------
def test_hidden_kernel_swap_rejected():
    v1 = {"task_id": "t", "transition_kernel":
          uc.UNIFIED_TASK["transition_kernel"],
          "economy": uc.UNIFIED_TASK["economy"],
          "horizon": uc.UNIFIED_TASK["horizon"]}
    v2 = dict(v1, economy=dict(
        v1["economy"], fee_rate=2e-3))
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([v1, v2])
    uc.check_hidden_task_swap([v1, dict(v1)])
    v3 = dict(v1, transition_kernel=dict(
        v1["transition_kernel"]))
    v3["transition_kernel"] = dict(
        v3["transition_kernel"], s=dict(
            v3["transition_kernel"]["s"], hold_p=0.10))
    with pytest.raises(uc.UnifiedSpecError,
                       match="hidden task swap"):
        uc.check_hidden_task_swap([v1, v3])


# ---- 账本一致性 ----------------------------------------------
def test_ledger_consistency_and_truncation():
    uc.check_ledger_account(
        {"exposure": 0.5, "solvency_raw": 2.0,
         "solvency_capped": 2.0})
    uc.check_ledger_account(
        {"exposure": 0.0, "solvency_raw": None,
         "solvency_capped": 40.0})
    with pytest.raises(uc.UnifiedSpecError,
                       match="1/\\|e\\|"):
        uc.check_ledger_account(
            {"exposure": 0.5, "solvency_raw": 1.9,
             "solvency_capped": 1.9})   # 截断痕迹
    with pytest.raises(uc.UnifiedSpecError,
                       match="cap"):
        uc.check_ledger_account(
            {"exposure": 0.0, "solvency_raw": None,
             "solvency_capped": 39.0})


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
    uc.check_action_expressiveness(
        {"arm": "A", "interval": [0.3, 0.6],
         "threshold": 0.4})   # ≤ .5 上界 → 允许声明
    with pytest.raises(uc.UnifiedSpecError,
                       match="not expressible"):
        uc.check_action_expressiveness(
            {"arm": "A", "interval": [0.3, 0.6],
             "threshold": 0.8})
    # 端点区间(含 ±1)不受内部上界约束
    uc.check_action_expressiveness(
        {"arm": "A", "interval": [0.6, 1.0],
         "threshold": 0.8})


def test_arm_b_reachability_stays_candidate():
    uc.check_action_expressiveness(
        {"arm": "B", "interval": [0.3, 0.6],
         "threshold": 0.8})   # 候选允许声明


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
def test_all_gates_not_specified_and_examples_rejected():
    for k, v in uc.SEVEN_SKILLS.items():
        assert v["gate_status"] == "not_specified", k
        assert v["negative_controls"]
    uc.check_graduation_claim({"direction_neutral_flat": {
        "graduated": False}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="without frozen gate"):
        uc.check_graduation_claim(
            {"direction_neutral_flat": {"graduated": True}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="example number"):
        uc.check_graduation_claim(
            {"direction_neutral_flat": {
                "graduated": True, "gate": 0.90}})
    with pytest.raises(uc.UnifiedSpecError,
                       match="unknown skill"):
        uc.check_graduation_claim({"ghost": {
            "graduated": False}})


def test_registry_snapshot_shape():
    snap = uc.build_registry_snapshot()
    assert snap["schema"] == uc.SPEC_SCHEMA
    assert snap["calibration"] == "incomplete"
    assert len(snap["skills"]) == 7
    assert snap["combination_module"][
        "gate_status"] == "not_specified"
    assert snap["task"]["status"] == "candidate_uncalibrated"


# ---- 阶段选择语义 --------------------------------------------
def test_phase_selection_declares_no_future_swap():
    ps = uc.UNIFIED_TASK["phase_selection"]
    assert "同一核" in ps["rule"] or "同一" in ps["rule"]
    assert "未来" in ps["rule"]


def test_old_c1_contract_untouched():
    # 旧规范仍在且版本不变
    assert cc.CONTRACT_VERSION == "COURSE_CONTRACT_V1"
    c = cc.build_contract()
    assert c["c1"]["direction_gate"]["threshold"] == 0.80
    assert c["c1"]["neutral_gate"]["threshold"] == 0.75
