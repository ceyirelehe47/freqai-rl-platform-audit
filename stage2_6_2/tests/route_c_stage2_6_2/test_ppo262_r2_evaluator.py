"""R2 family-aware evaluator 测试(sentinel 回归 + denominator 合同)。

覆盖任务书 §5/§20:
- mixed C1/C2/C3 bank:正确 reference identity(逐族);
- 错误 family policy(bank[0].family shortcut)会被检测;
- single-family evaluator 拒绝 mixed bank;
- negative/zero denominator 不计算普通 capture(invalid_reference_gap);
- 不使用 bank[0] shortcut(mixed == 逐族 single 的并集);
- 跨 family 证据拼接被拒(§17)。
"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_r2_evaluator import (
    CrossFamilyEvidenceError, EXPECTED_REFERENCE_CLASS,
    MixedFamilyBankError, decide_family_branch,
    evaluate_mixed_family_bank, evaluate_single_family_bank,
    family_eval_capture, family_recovery_evidence,
)
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_SMOKE_NS, derive262r2_seed,
)


@pytest.fixture(scope="module")
def mixed_bank(locked_rung_params):
    keys = []
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for rung in ("D0", "D1"):
            for j in range(2):
                for v in ("A", "B"):
                    keys.append(EpisodeKey(
                        DIAG262R2_SMOKE_NS, fam, rung, 900000 + j, v))
    return generate262_bank(
        keys, locked_plan_rung_params=locked_rung_params,
        derive_seed_fn=derive262r2_seed)


@pytest.fixture(scope="module")
def policy_sets(locked_rung_params, locked_reference_thresholds):
    from rl_curriculum.ppo262_metrics import build_261_policy_set
    out = {}
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        out[fam] = build_261_policy_set(
            fam, locked_rung_params[fam]["D1"],
            locked_reference_thresholds[fam])
    return out


def test_mixed_bank_reference_identity_per_family(
        mixed_bank, locked_rung_params, locked_reference_thresholds,
        policy_sets):
    result = evaluate_mixed_family_bank(
        policy_sets["c1_opportunity"]["reference"], mixed_bank,
        locked_rung_params, locked_reference_thresholds)
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        for rung, cell in result["cells"][fam].items():
            ident = cell["reference_identity"]
            assert ident["reference_class"] == \
                EXPECTED_REFERENCE_CLASS[fam]
            assert ident["reference_class_matches_family_contract"]
            # threshold identity 可追溯(记录了解析值)
            assert ident["threshold_identity"]["reference_thresholds"]


def test_mixed_equals_union_of_single_family(
        mixed_bank, locked_rung_params, locked_reference_thresholds,
        policy_sets):
    pol = policy_sets["c1_opportunity"]["reference"]
    mixed = evaluate_mixed_family_bank(
        pol, mixed_bank, locked_rung_params, locked_reference_thresholds)
    for fam in ("c1_opportunity", "c2_context", "c3_cost"):
        fam_bank = [e for e in mixed_bank if e.key.family == fam]
        single = evaluate_single_family_bank(
            pol, fam_bank, locked_rung_params,
            locked_reference_thresholds)
        assert set(single["cells"][fam]) == set(mixed["cells"][fam])
        for rung in single["cells"][fam]:
            a, b = single["cells"][fam][rung], mixed["cells"][fam][rung]
            for k in ("reference_mean", "denominator", "capture",
                      "best_baseline", "status"):
                assert a[k] == b[k], (fam, rung, k)


def test_single_family_evaluator_rejects_mixed_bank(
        mixed_bank, locked_rung_params, locked_reference_thresholds,
        policy_sets):
    with pytest.raises(MixedFamilyBankError):
        evaluate_single_family_bank(
            policy_sets["c1_opportunity"]["reference"], mixed_bank,
            locked_rung_params, locked_reference_thresholds)


def test_bank0_family_shortcut_detected(
        mixed_bank, locked_rung_params, locked_reference_thresholds,
        policy_sets):
    """R1 bug 复现:bank[0].family(C1)的 policy set 评估整个 bank,
    C2/C3 cells 的 reference_mean 必须与正确评估不同。"""
    from rl_curriculum.ppo262_metrics import evaluate_policy_on_bank
    correct = evaluate_mixed_family_bank(
        policy_sets["c1_opportunity"]["reference"], mixed_bank,
        locked_rung_params, locked_reference_thresholds)
    by_rung = {}
    for e in mixed_bank:
        by_rung.setdefault((e.key.family, e.key.rung), []).append(e)
    for (fam, rung), eps in sorted(by_rung.items()):
        if fam == "c1_opportunity":
            continue
        buggy_rows = evaluate_policy_on_bank(
            policy_sets["c1_opportunity"]["reference"], eps,
            collect_actions=False)
        buggy_mean = float(np.mean(
            [r["net_return"] for r in buggy_rows]))
        assert buggy_mean != correct["cells"][fam][rung][
            "reference_mean"], (
            f"bank[0].family shortcut 未被检测:{fam}/{rung}")


def test_negative_or_zero_denominator_invalid():
    # D2 invalid(R<=B)被排除;D0/D1 valid -> 加权只在 valid cells 上
    cells = {
        "c1_opportunity": {
            "D0": {"reference_gap_valid": True, "capture": 0.5},
            "D1": {"reference_gap_valid": True, "capture": 0.2},
            "D2": {"reference_gap_valid": False, "capture": None,
                   "status": "invalid_reference_gap",
                   "denominator": -0.01},
        }
    }
    out = family_eval_capture("c1_opportunity", cells)
    assert out["valid"] is True
    assert set(out["valid_cells"]) == {"D0", "D1"}
    assert "D2" in out["invalid_cells"]
    assert out["capture"] == pytest.approx(
        (0.20 * 0.5 + 0.30 * 0.2) / 0.50)
    # D1 invalid(核心 rung)或只剩 <2 valid cells -> evidence 无效
    cells2 = {
        "c1_opportunity": {
            "D0": {"reference_gap_valid": False, "capture": None},
            "D1": {"reference_gap_valid": False, "capture": None},
            "D2": {"reference_gap_valid": True, "capture": 0.2},
        }
    }
    assert family_eval_capture("c1_opportunity", cells2)["valid"] is False
    cells3 = {
        "c1_opportunity": {
            "D0": {"reference_gap_valid": True, "capture": 0.5},
            "D1": {"reference_gap_valid": False, "capture": None},
            "D2": {"reference_gap_valid": True, "capture": 0.2},
        }
    }
    assert family_eval_capture("c1_opportunity", cells3)["valid"] is False


def test_required_baselines_per_family(
        mixed_bank, locked_rung_params, locked_reference_thresholds,
        policy_sets):
    result = evaluate_mixed_family_bank(
        policy_sets["c1_opportunity"]["reference"], mixed_bank,
        locked_rung_params, locked_reference_thresholds)
    expect = {
        "c1_opportunity": {"always_flat", "always_long"},
        "c2_context": {"always_flat", "always_long", "c2_local_only"},
        "c3_cost": {"always_flat", "always_long", "c3_cost_ignorant"},
    }
    for fam in expect:
        for rung, cell in result["cells"][fam].items():
            assert set(
                cell["reference_identity"]["required_baselines"]) == \
                expect[fam]


def test_cross_family_evidence_rejected():
    cap = {"family": "c1_opportunity", "valid": True, "capture": 0.4}
    prob = {"family": "c3_cost", "probability_gap": 0.2,
            "sampling_sufficient": True}
    beh = {"family": "c1_opportunity", "det_behavior_gap": 0.3}
    with pytest.raises(CrossFamilyEvidenceError):
        family_recovery_evidence("c1_opportunity", cap, prob, beh)
    # 同族通过
    ok = family_recovery_evidence(
        "c1_opportunity", cap, {**prob, "family": "c1_opportunity"}, beh)
    assert ok["family"] == "c1_opportunity"


def test_decide_family_branch_precedence():
    kw = dict(unscaled_recovered=False, scaled_recovered=False,
              linear_all_fail=False, class_balanced_all_fail=False,
              bc_executed=False, bc_retained_2of3=False,
              bc_destroyed_2of3=False)
    assert decide_family_branch(**{**kw, "unscaled_recovered": True}) \
        == "A"
    assert decide_family_branch(**{**kw, "scaled_recovered": True}) \
        == "B"
    assert decide_family_branch(**{
        **kw, "linear_all_fail": True,
        "class_balanced_all_fail": True}) == "E"
    assert decide_family_branch(**{
        **kw, "bc_executed": True, "bc_retained_2of3": True}) == "C"
    assert decide_family_branch(**{
        **kw, "bc_executed": True, "bc_destroyed_2of3": True}) == "D"
    # supervised 学会(linear 未全败)但 BC 未执行 -> F
    assert decide_family_branch(**kw) == "F"
    # 任何 family F 使 global diagnostics FAIL(由 validator 组合)
