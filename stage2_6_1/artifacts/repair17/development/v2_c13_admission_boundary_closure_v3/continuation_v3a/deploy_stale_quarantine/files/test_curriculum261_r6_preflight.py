# -*- coding: utf-8 -*-
"""R6 §38 测试:Preflight Governance(§29)——sealed 零 final seed/
attestation 绑定/静态 preflight 非 final namespace/plan 锁后 drift。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_r6_param_pack import (
    C2_LADDER_CANDIDATES,
    R4_PARAMETER_PACK_DIGEST,
    ladder_pack_payload,
    write_selected_pack,
)
from rl_curriculum.curriculum261_r6_tape import (
    matched_ladder_contract_identity,
)
from rl_curriculum.curriculum261_r4_preprocessing import (
    preprocessing_v2_contract_digest,
)


def _write_pack(lock_dir, block_count=10):
    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_balanced", c2_ladder=ladder,
        selected_block_count=block_count, design_plan_digest="r6dp-test",
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity="bi-test")
    write_selected_pack(lock_dir, pack)
    return pack


def _build_and_lock_plan(lock_dir, gate_pass=True, block_count=10):
    from rl_curriculum.curriculum261_r6_plan import (
        build_plan_r6,
        lock_plan_r6,
    )

    _write_pack(lock_dir, block_count=block_count)
    from rl_curriculum.curriculum261_r6_param_pack import (
        load_selected_pack,
    )

    pack = load_selected_pack(lock_dir)
    plan = build_plan_r6(
        baseline_commit="40a0d9a",
        vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        frozen_contracts={"env_core": "v"},
        parameter_pack=pack,
        design_plan_digest="r6dp-test",
        selected_c2_candidate="c2l_balanced",
        frozen_parameter_identity={"identity": "r6fp-test"},
        preprocessing_v2_contract_digest=preprocessing_v2_contract_digest(),
        calibration_bundle_hash="b1", holdout_bundle_hash="b2",
        preprocessing_robustness_gate={"pass": gate_pass},
        curriculum_robustness_gate={"pass": gate_pass},
        conditioning_gate_constants={}, supervised_gate_constants={},
        kappa=1.5,
        reference_thresholds_by_family={"c2_context": {}},
        density_thresholds={},
        prior_r2_plan_digest="qp-t", prior_diag262r2_plan_digest="dp-t",
        prior_r4_parameter_pack_digest=R4_PARAMETER_PACK_DIGEST,
        prior_r5_design_plan_digest="r5dp-t",
    )
    path, digest = lock_plan_r6(plan)
    assert path.is_file()
    return digest


def _write_evidence(out_dir, pass_=True):
    for name in ("preprocessing_robustness_gate.json",
                 "curriculum_robustness_gate.json",
                 "supervised_learnability.json",
                 "prelock_static_preflight.json"):
        (out_dir / name).write_text(
            json.dumps({"pass": pass_}), encoding="utf-8")


class SeedCallRecorder:
    """全局记录 derive261_seed 调用(断言 sealed preflight 零 final)。"""

    def __init__(self, monkeypatch):
        import rl_curriculum.curriculum261_api as api

        self.calls = []
        self._api = api
        real = api.derive261_seed

        def wrapped(namespace, *a, **kw):
            self.calls.append(namespace)
            return real(namespace, *a, **kw)

        monkeypatch.setattr(api, "derive261_seed", wrapped)
        # r6 模块内部 from-import 的引用也要替换
        import rl_curriculum.curriculum261_r6_tape as tape

        monkeypatch.setattr(tape, "derive261_seed", wrapped)


def test_sealed_preflight_no_final_seed_access(tmp_path, monkeypatch,
                                               lock_env):
    recorder = SeedCallRecorder(monkeypatch)
    _build_and_lock_plan(lock_env)
    _write_evidence(tmp_path)

    from rl_curriculum.curriculum261_r6_preflight import (
        run_postlock_sealed_preflight,
    )

    att = run_postlock_sealed_preflight(
        tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    finals = [c for c in recorder.calls
              if c in ("qualification_r6",
                       "preprocess_fit_qualification_r6")]
    assert finals == [], f"sealed preflight 派生了 final seed: {finals}"
    assert att["final_seed_derivations_performed"] == 0
    assert att["exposure_marker_written"] is False


@pytest.fixture()
def lock_env(tmp_path, monkeypatch):
    monkeypatch.setenv("CURRICULUM261_R6_LOCK_DIR", str(tmp_path))
    yield tmp_path
    monkeypatch.delenv("CURRICULUM261_R6_LOCK_DIR", raising=False)


def test_sealed_attestation_binds_plan(tmp_path, lock_env):
    _build_and_lock_plan(lock_env)
    _write_evidence(tmp_path)
    from rl_curriculum.curriculum261_r6_preflight import (
        run_postlock_sealed_preflight,
        verify_sealed_attestation,
    )

    att = run_postlock_sealed_preflight(tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    if not att["pass"]:
        failed = {k: v for k, v in att["checks"].items() if v is False}
        pytest.fail(f"attestation checks failed: {failed}")
    v = verify_sealed_attestation(tmp_path)
    assert v["pass"], v
    # 篡改 attestation 内容 -> digest 拒绝
    path = lock_env / "sealed_final_preflight.json"
    obj = json.loads(path.read_text(encoding="utf-8"))
    obj["vendor_sha"] = "tampered"
    path.write_text(json.dumps(obj), encoding="utf-8")
    v2 = verify_sealed_attestation(tmp_path)
    assert not v2["pass"]
    assert not v2["digest_recompute"]


def test_sealed_requires_evidence(tmp_path, lock_env):
    _build_and_lock_plan(lock_env)
    from rl_curriculum.curriculum261_r6_preflight import (
        run_postlock_sealed_preflight,
    )

    att = run_postlock_sealed_preflight(tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert att["pass"] is False
    assert att["checks"]["evidence_supervised_learnability.json"] is False


def test_sealed_binds_selected_block_count(tmp_path, lock_env):
    _build_and_lock_plan(lock_env, block_count=10)
    _write_evidence(tmp_path)
    assert (lock_env / "r6_parameter_pack.json").is_file()
    # 篡改 pack 的 selected_block_count 与 plan 不一致
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES,
        ladder_pack_payload,
        write_selected_pack,
    )

    ladder = C2_LADDER_CANDIDATES["c2l_balanced"]
    pack = ladder_pack_payload(
        selected_c2_candidate="c2l_balanced", c2_ladder=ladder,
        selected_block_count=20, design_plan_digest="r6dp-test",
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity="bi-test")
    write_selected_pack(lock_env, pack)
    from rl_curriculum.curriculum261_r6_preflight import (
        run_postlock_sealed_preflight,
    )

    att = run_postlock_sealed_preflight(tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert att["checks"]["parameter_pack_bound"] is False or \
        att["checks"]["selected_block_count_bound"] is False


def test_static_preflight_touches_only_smoke_ns(tmp_path, lock_env,
                                                monkeypatch):
    """pre-lock static preflight 只触碰 ppo_smoke_r6(非 final)。"""
    recorder = SeedCallRecorder(monkeypatch)
    from rl_curriculum.curriculum261_r6_preflight import (
        run_prelock_static_preflight,
    )

    result = run_prelock_static_preflight(
        tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    finals = [c for c in recorder.calls
              if c not in ("ppo_smoke_r6",)]
    assert finals == [], f"static preflight 触碰非 smoke namespace: {finals}"
    assert result["namespaces_touched"] == ["ppo_smoke_r6"]
    assert result["final_namespaces_touched"] == []
    # matched generator probe 是 static preflight 的组成部分
    assert "matched_block_generator" in result["checks"]
    assert result["checks"]["matched_block_generator"]["pass"]


def test_plan_code_drift_rejected_after_lock(tmp_path, lock_env):
    """plan 锁后 code 漂移 -> sealed preflight code_identity 拒绝。"""
    import shutil

    _build_and_lock_plan(lock_env)
    _write_evidence(tmp_path)
    import rl_curriculum
    from pathlib import Path as _P

    modules_dir = _P(rl_curriculum.__path__[0])
    target = modules_dir / "curriculum261_r6_smoke.py"
    backup = tmp_path / "smoke_backup.py"
    shutil.copy(target, backup)
    try:
        # 模拟 code drift
        target.write_text(
            target.read_text(encoding="utf-8") + "\n# drift\n",
            encoding="utf-8")
        from rl_curriculum.curriculum261_r6_preflight import (
            run_postlock_sealed_preflight,
        )

        att = run_postlock_sealed_preflight(
            tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
        assert att["checks"]["code_identity_matches_plan"] is False
        assert att["pass"] is False
    finally:
        shutil.copy(backup, target)
