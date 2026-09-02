# -*- coding: utf-8 -*-
"""R10 §29 Routing 测试:main→v2_main / holdout→v2_hold / final→v2_final
/ swap 负向 / bundle hash mismatch 拒绝 / namespace provenance mismatch
拒绝(§9)。"""

from __future__ import annotations

import pytest

from rl_curriculum.curriculum261_r10_routing import (
    R10_PREPLAN_ROLE_FIT_NAMESPACE,
    R10_ROLE_FIT_NAMESPACE,
    R10BundleRouting,
    RoutingContractError,
    RoutingLedgerR10,
    build_routing_r10,
    bundle_routing_contract_digest,
    require_eval_routing_r10,
)


class _FakeV2:
    def __init__(self, namespace: str, bundle_hash: str) -> None:
        self.namespace = namespace
        self.bundle_hash = bundle_hash
        self.parameter_state_hash = 'p-' + bundle_hash
        self.manifest_multiset_hash = 'm-' + bundle_hash


def _fake_routings():
    main = _FakeV2("preprocess_fit_calibration_r10", "hash-main-1")
    hold = _FakeV2("preprocess_fit_holdout_r10", "hash-hold-1")
    final = _FakeV2("preprocess_fit_qualification_r10", "hash-final-1")
    return main, hold, final


def test_formal_routing_table_locked():
    assert R10_ROLE_FIT_NAMESPACE == {
        "main": "preprocess_fit_calibration_r10",
        "holdout": "preprocess_fit_holdout_r10",
        "final": "preprocess_fit_qualification_r10",
    }


def test_build_routing_rejects_role_namespace_mismatch():
    main, hold, _ = _fake_routings()
    build_routing_r10("main", main)  # OK
    with pytest.raises(RoutingContractError, match="权威 fit namespace"):
        build_routing_r10("holdout", main)  # holdout role 撞 main bundle
    with pytest.raises(RoutingContractError, match="权威 fit namespace"):
        build_routing_r10("main", hold)


def test_build_routing_rejects_unknown_namespace():
    stranger = _FakeV2("calibration_r5", "hash-x")
    with pytest.raises(RoutingContractError, match="不属于任何 R10 路由表"):
        build_routing_r10("diagnostic", stranger)


def test_build_routing_rejects_bundle_hash_mismatch():
    main, _, _ = _fake_routings()
    with pytest.raises(RoutingContractError, match="bundle hash 与期望不符"):
        build_routing_r10("main", main,
                          expected_bundle_hash="hash-other")


def test_require_eval_routing_routes_by_namespace():
    """§9.1 权威路由:calibration_r10→main;calibration_holdout_r10→
    holdout;qualification_r10→final。"""
    main, hold, final = _fake_routings()
    r_main = build_routing_r10("main", main)
    r_hold = build_routing_r10("holdout", hold)
    r_final = build_routing_r10("final", final)
    ledger = RoutingLedgerR10()
    assert require_eval_routing_r10(
        r_main, "calibration_r10", ledger=ledger) is main
    assert require_eval_routing_r10(
        r_hold, "calibration_holdout_r10", ledger=ledger) is hold
    assert require_eval_routing_r10(
        r_final, "qualification_r10", ledger=ledger) is final
    assert ledger.all_pass()


def test_swap_negative_test():
    """§9.4 负向:故意交换 main/holdout bundle 必须在返回 bundle 前
    失败。"""
    main, hold, _ = _fake_routings()
    r_main = build_routing_r10("main", main)
    with pytest.raises(RoutingContractError, match="routing 合同违反"):
        require_eval_routing_r10(r_main, "calibration_holdout_r10")
    r_hold = build_routing_r10("holdout", hold)
    with pytest.raises(RoutingContractError, match="routing 合同违反"):
        require_eval_routing_r10(r_hold, "calibration_r10")


def test_final_rejects_main_or_holdout_bundle():
    main, hold, _ = _fake_routings()
    r_main = build_routing_r10("main", main)
    r_hold = build_routing_r10("holdout", hold)
    with pytest.raises(RoutingContractError):
        require_eval_routing_r10(r_main, "qualification_r10")
    with pytest.raises(RoutingContractError):
        require_eval_routing_r10(r_hold, "qualification_r10")


def test_unknown_eval_namespace_rejected():
    main, _, _ = _fake_routings()
    r_main = build_routing_r10("main", main)
    with pytest.raises(RoutingContractError, match="权威路由映射"):
        require_eval_routing_r10(r_main, "calibration_r9")


def test_preplan_routing_cannot_serve_formal_namespaces():
    pre = _FakeV2(R10_PREPLAN_ROLE_FIT_NAMESPACE["main"], "hash-pre-1")
    r = build_routing_r10("main", pre, preplan=True)
    with pytest.raises(RoutingContractError, match="正式评估 namespace"):
        require_eval_routing_r10(r, "calibration_r10")
    # preplan 自身 namespace 正常
    assert require_eval_routing_r10(
        r, "preplan_calibration_main_r10") is pre


def test_routing_ledger_matrix():
    main, hold, _ = _fake_routings()
    r_main = build_routing_r10("main", main)
    ledger = RoutingLedgerR10()
    require_eval_routing_r10(r_main, "calibration_r10", ledger=ledger)
    rows = ledger.matrix()
    assert len(rows) == 1
    row = rows[0]
    assert set(row) >= {
        "corpus", "expected_role", "actual_role",
        "expected_fit_namespace", "actual_fit_namespace",
        "expected_bundle_hash", "actual_bundle_hash", "pass"}
    assert row["pass"] is True


def test_routing_contract_digest_stable_and_prefixed():
    d1 = bundle_routing_contract_digest()
    d2 = bundle_routing_contract_digest()
    assert d1 == d2
    assert d1.startswith("r10rt-") and len(d1) == 6 + 64


def test_bundle_routing_frozen_dataclass():
    main, _, _ = _fake_routings()
    r = build_routing_r10("main", main)
    with pytest.raises(Exception):
        r.role = "holdout"  # type: ignore[misc]
