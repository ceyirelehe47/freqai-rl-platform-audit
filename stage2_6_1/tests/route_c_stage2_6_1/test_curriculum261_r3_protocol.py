"""R3 协议测试:gate/lock/exposure/plan digest/guard 完整性(§34 Protocol)。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.curriculum261_r3_namespaces import (
    qualification_r3_exposure_marker,
    qualification_r3_unlocked,
    qualification_r3_unlocked_detail,
    write_qualification_r3_exposure,
)
from rl_curriculum.curriculum261_r3_plan import (
    build_plan_r3,
    plan_digest_r3,
)


def _gate(pass_: bool) -> dict:
    return {"format": "f", "pass": pass_}


def _plan_kwargs(**over):
    kw = dict(
        baseline_commit="x" * 40, vendor_pin="y" * 40,
        frozen_contracts={"env_core": "RouteCEnvCore-v1.0.0"},
        preprocessing_contract_digest="r3pc-test",
        calibration_state_hash="r3pre-a",
        holdout_state_hash="r3pre-b",
        preprocessing_robustness_gate=_gate(True),
        curriculum_robustness_gate=_gate(True),
        conditioning_gate_constants={"k": 1},
        supervised_gate_constants={"k": 1},
        kappa=1.5,
        rung_params_by_family={}, reference_thresholds_by_family={},
        prior_r2_plan_digest="qp-old",
        prior_diag262r2_plan_digest="dp-old",
    )
    kw.update(over)
    return kw


def test_build_plan_rejects_when_preprocessing_gate_fails():
    with pytest.raises(RuntimeError, match="preprocessing robustness"):
        build_plan_r3(**_plan_kwargs(
            preprocessing_robustness_gate=_gate(False)))


def test_build_plan_rejects_when_curriculum_gate_fails():
    with pytest.raises(RuntimeError, match="curriculum robustness"):
        build_plan_r3(**_plan_kwargs(
            curriculum_robustness_gate=_gate(False)))


def test_plan_digest_stable_and_created_utc_excluded():
    plan = build_plan_r3(**_plan_kwargs())
    d1 = plan_digest_r3(plan)
    plan["created_utc"] = "2026-09-01T00:00:00"
    d2 = plan_digest_r3(plan)
    assert d1 == d2 and d1.startswith("qp3-")


def test_plan_digest_detects_tampering():
    plan = build_plan_r3(**_plan_kwargs())
    d1 = plan_digest_r3(plan)
    plan["kappa"] = 0.1  # 篡改
    assert plan_digest_r3(plan) != d1


class TestQualificationR3Guard:
    """§32 技术债修复:guard 必须验证 plan+digest+重算+gate 四要素。"""

    def test_locked_when_no_plan(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        assert qualification_r3_unlocked() is False
        assert qualification_r3_unlocked_detail()["unlocked"] is False

    def test_plan_alone_insufficient(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        plan = build_plan_r3(**_plan_kwargs())
        (tmp_path / "qualification_plan_r3.json").write_text(
            json.dumps(plan, default=str), encoding="utf-8")
        assert qualification_r3_unlocked() is False  # digest 缺失

    def test_plan_and_digest_but_gate_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        plan = build_plan_r3(**_plan_kwargs())
        # 手工篡改 gate=false(模拟绕过 build_plan_r3 前置检查的 plan)
        plan["robustness_gate"]["curriculum"]["pass"] = False
        plan["robustness_gate"]["pass"] = False
        (tmp_path / "qualification_plan_r3.json").write_text(
            json.dumps(plan, default=str), encoding="utf-8")
        (tmp_path / "qualification_plan_digest_r3.txt").write_text(
            plan_digest_r3(plan), encoding="utf-8")
        detail = qualification_r3_unlocked_detail()
        assert detail["gate_pass"] is False
        assert qualification_r3_unlocked() is False  # gate=false 拒绝

    def test_digest_mismatch_rejected(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        plan = build_plan_r3(**_plan_kwargs())
        (tmp_path / "qualification_plan_r3.json").write_text(
            json.dumps(plan, default=str), encoding="utf-8")
        (tmp_path / "qualification_plan_digest_r3.txt").write_text(
            "qp3-tampered", encoding="utf-8")
        assert qualification_r3_unlocked() is False  # digest 不一致

    def test_full_valid_lock_unlocks(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        from rl_curriculum.curriculum261_r3_plan import lock_plan_r3
        from rl_curriculum.curriculum261_r3_namespaces import (
            qualification_r3_plan_path,
        )

        plan = build_plan_r3(**_plan_kwargs())
        path, digest = lock_plan_r3(plan)
        assert path == qualification_r3_plan_path()
        assert qualification_r3_unlocked() is True
        assert qualification_r3_unlocked_detail()["digest_matches"]

    def test_qualification_seed_guard_after_lock(self, tmp_path,
                                                 monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        from rl_curriculum.curriculum261_api import derive261_seed

        with pytest.raises(Exception):
            derive261_seed("qualification_r3", "c1_opportunity",
                           "D0", 0, 0)
        from rl_curriculum.curriculum261_r3_plan import lock_plan_r3

        lock_plan_r3(build_plan_r3(**_plan_kwargs()))
        assert derive261_seed("qualification_r3", "c1_opportunity",
                              "D0", 0, 0)


class TestExposure:
    def test_exposure_written_once_and_detected(self, tmp_path,
                                                monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        marker = qualification_r3_exposure_marker()
        assert not marker.exists()
        write_qualification_r3_exposure("qp3-x", status="running")
        assert marker.exists()
        payload = json.loads(marker.read_text(encoding="utf-8"))
        assert payload["iteration"] == "r3"
        assert payload["plan_digest"] == "qp3-x"

    def test_final_rejects_after_exposure(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
        write_qualification_r3_exposure("qp3-x")
        from rl_curriculum.curriculum261_r3_final import (
            run_final_qualification_r3,
        )

        with pytest.raises(RuntimeError, match="exposure marker 存在"):
            run_final_qualification_r3(tmp_path / "out")


def test_final_qualification_requires_locked_plan(tmp_path, monkeypatch):
    """无 plan 时 final fail closed(不触任何 qualification seed)。"""
    monkeypatch.setenv("CURRICULUM261_R3_LOCK_DIR", str(tmp_path))
    from rl_curriculum.curriculum261_r3_final import (
        run_final_qualification_r3,
    )

    with pytest.raises(RuntimeError, match="plan 不存在"):
        run_final_qualification_r3(tmp_path / "out")


def test_iteration_field_is_r3_everywhere():
    """§32:R3 代码产出的 iteration 字段必须为 r3(不残留 r2/diag262r2)。"""
    from rl_curriculum.curriculum261_r3_calibration import (
        run_generator_stress_r3,
    )
    from rl_curriculum.curriculum261_r3_namespaces import (
        CURRICULUM261_ITERATION_ID_R3,
    )

    assert CURRICULUM261_ITERATION_ID_R3 == "r3"
    for ns in __import__("rl_curriculum.curriculum261_r3_namespaces",
                         fromlist=["CURRICULUM261_R3_NAMESPACES"]
                         ).CURRICULUM261_R3_NAMESPACES:
        assert ns.endswith("_r3")
        assert not ns.startswith(("diag262", "qualification_r2"))


def test_no_duplicate_seed_derivation():
    """§32:重复/被覆盖的 seed derivation 已删除(单一 _derive261_seed_raw)。"""
    import inspect

    from rl_curriculum import curriculum261_api as api

    src = inspect.getsource(api)
    assert src.count("def _derive261_seed_raw") == 1
