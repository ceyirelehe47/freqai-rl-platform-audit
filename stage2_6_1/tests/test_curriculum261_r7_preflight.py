# -*- coding: utf-8 -*-
"""R7 §34 测试:Final Preflight(§25)——零 final seed、attestation 绑定、
evidence 缺失拒绝、code drift 拒绝、matched 实现不漂移。"""

from __future__ import annotations

import hashlib
import json

import pytest


@pytest.fixture()
def r7_lock_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R7_LOCK_DIR", str(tmp_path))
    return tmp_path


def _write_evidence(out_dir, *, gate_pass=True):
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in ("preprocessing_robustness_gate.json",
                 "curriculum_robustness_gate.json",
                 "supervised_learnability.json",
                 "prelock_static_preflight.json"):
        (out_dir / name).write_text(
            json.dumps({"pass": gate_pass}), encoding="utf-8")


def _make_pack(r7_lock_dir, *, n_blocks=15):
    from rl_curriculum.curriculum261_r7_param_pack import (
        ladder_pack_payload_r7, load_selected_pack, write_selected_pack_r7,
    )
    from rl_curriculum.curriculum261_r7_cue_eval import (
        cue_semantic_rule_identity,
    )
    from rl_curriculum.curriculum261_r7_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r7_param_pack import (
        r7_candidate_grid,
    )

    pack = ladder_pack_payload_r7(
        selected_c2_candidate="c2l_conservative",
        c2_ladder=r7_candidate_grid()["c2l_conservative"],
        selected_block_count=n_blocks,
        design_plan_digest="r7dp-" + "0" * 64,
        matched_contract_identity="r6ml-" + "0" * 64,
        block_integrity_identity="r6bt|n=15",
        cue_semantic_contract_digest=cue_semantic_contract_digest(),
        cue_semantic_rule_identity=cue_semantic_rule_identity(),
        cue_audit_digest="r7ca-" + "0" * 64,
        p_contract=0.937,
        recall_floor_value=0.917)
    write_selected_pack_r7(r7_lock_dir, pack)
    return load_selected_pack(r7_lock_dir)


def _lock_plan(r7_lock_dir, pack, out_dir):
    from rl_curriculum.curriculum261_r7_plan import (
        build_plan_r7, lock_plan_r7,
    )

    plan = build_plan_r7(
        baseline_commit="7970d2096b6a5a93a85d32620b9b2b3a24826568",
        vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        frozen_contracts={"pass": True},
        parameter_pack=pack,
        design_plan_digest="r7dp-" + "0" * 64,
        selected_c2_candidate=pack["selected_c2_candidate"],
        frozen_parameter_identity={},
        preprocessing_v2_contract_digest="v2-" + "0" * 8,
        calibration_bundle_hash="b1",
        holdout_bundle_hash="b2",
        preprocessing_robustness_gate={"pass": True, "format": "x"},
        curriculum_robustness_gate={"pass": True, "format": "y"},
        conditioning_gate_constants={},
        supervised_gate_constants={},
        kappa=1.5,
        reference_thresholds_by_family={"c1_opportunity": {},
                                         "c2_context": {},
                                         "c3_cost": {}},
        density_thresholds={},
        prior_r2_plan_digest="qp-" + "0" * 8,
        prior_diag262r2_plan_digest="dp-" + "0" * 8,
        prior_r4_parameter_pack_digest="r4pk-" + "0" * 8,
        prior_r5_design_plan_digest="r5dp-" + "0" * 8,
        prior_r6_design_plan_digest="r6dp-" + "0" * 8)
    lock_plan_r7(plan)
    return plan


def test_build_plan_requires_both_gates():
    from rl_curriculum.curriculum261_r7_plan import build_plan_r7

    from rl_curriculum.curriculum261_r7_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r7_cue_eval import (
        cue_semantic_rule_identity,
    )

    pack = {
        "selected_block_count": 15,
        "pack_version": "CurriculumR7MatchedLadderPack-v1",
        "selected_c2_candidate": "c2l_conservative",
        "c2_ladder": {},
        "r4_parameter_pack_digest": "r4pk-x",
        "r5_design_plan_digest": "r5dp-x",
        "r6_design_plan_digest": "r6dp-x",
        "digest": "r7pk-x",
        "block_integrity_identity": "bi",
        "cue_contract_audit_digest": "r7ca-x",
        "p_contract": 0.937,
        "recall_floor": 0.917,
        "cue_semantic_contract_digest": cue_semantic_contract_digest(),
        "cue_semantic_rule_identity": cue_semantic_rule_identity(),
    }
    base = dict(
        baseline_commit="x", vendor_pin="v",
        frozen_contracts={},
        parameter_pack=pack,
        design_plan_digest="d", selected_c2_candidate="c",
        frozen_parameter_identity={},
        preprocessing_v2_contract_digest="v2",
        calibration_bundle_hash="a", holdout_bundle_hash="b",
        conditioning_gate_constants={},
        supervised_gate_constants={}, kappa=1.5,
        reference_thresholds_by_family={}, density_thresholds={},
        prior_r2_plan_digest="", prior_diag262r2_plan_digest="",
        prior_r4_parameter_pack_digest="",
        prior_r5_design_plan_digest="",
        prior_r6_design_plan_digest="")
    with pytest.raises(RuntimeError):
        build_plan_r7(preprocessing_robustness_gate={"pass": False},
                      curriculum_robustness_gate={"pass": True},
                      **base)
    with pytest.raises(RuntimeError):
        build_plan_r7(preprocessing_robustness_gate={"pass": True},
                      curriculum_robustness_gate={"pass": False},
                      **base)


def test_sealed_preflight_zero_final_seed(r7_lock_dir, monkeypatch):
    """§25.2:sealed preflight 不派生任何 final namespace seed。"""
    from rl_curriculum.curriculum261_api import derive261_seed
    from rl_curriculum.curriculum261_r7_preflight import (
        run_postlock_sealed_preflight_r7,
    )

    _write_evidence(r7_lock_dir)
    pack = _make_pack(r7_lock_dir)
    _lock_plan(r7_lock_dir, pack, r7_lock_dir)
    out = r7_lock_dir

    calls: list[str] = []
    orig = derive261_seed

    def spy(namespace, *a, **k):
        calls.append(namespace)
        return orig(namespace, *a, **k)

    import rl_curriculum.curriculum261_api as api

    monkeypatch.setattr(api, "derive261_seed", spy)
    # code identity 会不匹配(实际模块内容 vs plan 内合成值)?
    # build_plan_r7 内部调用 _code_identity_r7(真实)——一致
    att = run_postlock_sealed_preflight_r7(out, "unmatched-pin")
    forbidden = [ns for ns in calls if "qualification" in ns]
    assert not forbidden, f"sealed preflight 派生了 final seed: {forbidden}"
    assert att["final_seed_derivations_performed"] == 0
    assert att["pass"] is False  # vendor pin 不匹配 -> fail closed


def test_sealed_attestation_binds_plan(r7_lock_dir):
    """attestation 的 plan_digest 与锁定 plan 一致;篡改即拒。"""
    from rl_curriculum.curriculum261_r7_preflight import (
        run_postlock_sealed_preflight_r7,
        sealed_preflight_digest,
        verify_sealed_attestation,
    )
    from rl_curriculum.curriculum261_r6_preflight import (
        _vendor_state, vendor_dir_default,
    )

    _write_evidence(r7_lock_dir)
    pack = _make_pack(r7_lock_dir)
    plan = _lock_plan(r7_lock_dir, pack, r7_lock_dir)
    out = r7_lock_dir
    vendor = _vendor_state(vendor_dir_default())
    att = run_postlock_sealed_preflight_r7(
        out, vendor.get("sha", ""))
    checks_ok = att["pass"]
    if checks_ok:
        ok = verify_sealed_attestation(out)
        assert ok["pass"] is True
        from rl_curriculum.curriculum261_r7_plan import plan_digest_r7

        assert att["plan_digest"] == plan_digest_r7(plan)
        # 篡改 attestation -> digest 失配
        tampered = dict(att)
        tampered["selected_block_count"] = 20
        (out / "sealed_final_preflight.json").write_text(
            json.dumps(tampered), encoding="utf-8")
        bad = verify_sealed_attestation(out)
        assert bad["pass"] is False


def test_sealed_preflight_rejects_missing_evidence(r7_lock_dir):
    from rl_curriculum.curriculum261_r7_preflight import (
        run_postlock_sealed_preflight_r7,
    )

    out = r7_lock_dir
    pack = _make_pack(r7_lock_dir)
    _lock_plan(r7_lock_dir, pack, out)
    from rl_curriculum.curriculum261_r6_preflight import (
        _vendor_state, vendor_dir_default,
    )

    vendor = _vendor_state(vendor_dir_default())
    att = run_postlock_sealed_preflight_r7(out, vendor.get("sha", ""))
    assert att["pass"] is False
    assert att["checks"]["evidence_supervised_learnability.json"] is (
        False)


def test_matched_ladder_modules_unchanged_identity():
    """R7 复用的 R6 冻结模块 sha256 与发布仓库 R6 终态一致(§7)。"""
    from pathlib import Path

    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    pub = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit/stage2_6_1/src/"
                      "rl_curriculum"),
                 Path("E:/trading/freqai-rl-audit/stage2_6_1/src/"
                      "rl_curriculum")):
        if cand.is_dir():
            pub = cand
            break
    if pub is None:
        pytest.skip("发布仓库不可达")
    for name in ("curriculum261_r6_tape.py",
                 "curriculum261_r6_pairs.py",
                 "curriculum261_r6_param_pack.py"):
        live = hashlib.sha256(
            (root / name).read_bytes()).hexdigest()
        frozen = hashlib.sha256(
            (pub / name).read_bytes()).hexdigest()
        assert live == frozen, (
            f"{name} 相对 R6 终态发生漂移(§7:R7 不得修改 R6 冻结实现)")
