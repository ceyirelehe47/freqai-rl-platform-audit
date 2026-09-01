"""R5 测试:两级 preflight(§34 Exposure/Preflight)。

- sealed preflight 不派生任何 final namespace seed(monkeypatch 全局
  derive261_seed 记录调用);
- static preflight 只使用非 final namespace;
- attestation 绑定 plan digest;篡改即拒;
- gate FAIL 时 plan 未锁 -> sealed preflight fail closed。
"""

from __future__ import annotations

import json

import pytest

import rl_curriculum.curriculum261_api as api_mod
import rl_curriculum.curriculum261_r5_preflight as pf
from rl_curriculum.curriculum261_r5_preflight import (
    run_postlock_sealed_preflight,
    sealed_preflight_digest,
    verify_sealed_attestation,
)

FINAL_NAMESPACES = ("qualification_r5", "preprocess_fit_qualification_r5")


@pytest.fixture
def seed_call_recorder(monkeypatch):
    """全局记录 derive261_seed 调用(final namespace 即失败)。"""
    calls: list[tuple] = []
    real = api_mod.derive261_seed

    def wrapper(namespace, *a, **kw):
        calls.append((namespace,) + a)
        if namespace in FINAL_NAMESPACES:
            raise AssertionError(
                f"preflight 不得派生 final namespace seed: {namespace}")
        return real(namespace, *a, **kw)

    monkeypatch.setattr(api_mod, "derive261_seed", wrapper)
    return calls


def _build_and_lock_plan(lock_dir, gate_pass=True):
    """在临时 lock dir 构建并锁定一个最小合法 plan(含全部绑定)。"""
    from rl_curriculum.curriculum261_r5_plan import (
        build_plan_r5,
        lock_plan_r5,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r5_param_pack import (
        C2_TIER_A_CANDIDATES,
        R4_PARAMETER_PACK_DIGEST,
        frozen_parameter_identity_r5,
        ladder_pack_payload,
        load_selected_pack,
        write_selected_pack,
    )

    write_selected_pack(lock_dir, ladder_pack_payload(
        tier="A", selected_c2_candidate="c2_a_alpha26_vol16",
        c2_d3_params=dict(
            C2_TIER_A_CANDIDATES["c2_a_alpha26_vol16"]),
        design_plan_digest="r5dp-test"))
    pack = load_selected_pack(lock_dir)

    plan = build_plan_r5(
        baseline_commit="95bb927", vendor_pin="52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        frozen_contracts={"env_core": "v"},
        parameter_pack=pack,
        design_plan_digest="r5dp-test",
        selected_c2_candidate="c2_a_alpha26_vol16",
        tier_executed="A",
        frozen_parameter_identity=frozen_parameter_identity_r5("A"),
        preprocessing_v2_contract_digest=(
            preprocessing_v2_contract_digest()),
        calibration_bundle_hash="b1", holdout_bundle_hash="b2",
        preprocessing_robustness_gate={"pass": gate_pass},
        curriculum_robustness_gate={"pass": gate_pass},
        conditioning_gate_constants={}, supervised_gate_constants={},
        kappa=1.5, reference_thresholds_by_family={"c2_context": {}},
        density_thresholds={},
        prior_r2_plan_digest="qp-t", prior_diag262r2_plan_digest="dp-t",
        prior_r4_baseline_commit="d1",
        prior_r4_parameter_pack_digest=R4_PARAMETER_PACK_DIGEST,
    )
    path, digest = lock_plan_r5(plan)
    assert path.is_file()
    return digest


def _write_evidence(out_dir, pass_=True):
    for name in ("preprocessing_robustness_gate.json",
                 "curriculum_robustness_gate.json",
                 "supervised_learnability.json",
                 "prelock_static_preflight.json"):
        (out_dir / name).write_text(
            json.dumps({"pass": pass_}), encoding="utf-8")


def test_sealed_preflight_no_final_seed_access(
        monkeypatch, tmp_path, seed_call_recorder):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    out = tmp_path
    digest = _build_and_lock_plan(out)
    _write_evidence(out, pass_=True)

    att = run_postlock_sealed_preflight(
        out, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert att["pass"] is True
    assert att["final_seed_derivations_performed"] == 0
    assert att["final_namespaces_touched"] == []
    # 记录器确认:整个 sealed preflight 期间 derive261_seed 从未被
    # final namespace 调用(或根本未被调用)
    assert all(c[0] not in FINAL_NAMESPACES for c in seed_call_recorder)

    from rl_curriculum.curriculum261_r5_namespaces import (
        qualification_r5_unlocked,
    )

    assert qualification_r5_unlocked() is True
    assert att["plan_digest"] == digest

    # attestation 文件 + digest 落盘且可验证
    ok = verify_sealed_attestation(out)
    assert ok["pass"] is True

    # 篡改 attestation -> 拒绝
    att_path = out / "sealed_final_preflight.json"
    tampered = json.loads(att_path.read_text(encoding="utf-8"))
    tampered["vendor_pin_expected"] = "0000"
    att_path.write_text(json.dumps(tampered), encoding="utf-8")
    assert verify_sealed_attestation(out)["pass"] is False


def test_sealed_preflight_fails_on_missing_evidence(
        monkeypatch, tmp_path, seed_call_recorder):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    out = tmp_path
    _build_and_lock_plan(out)
    # 不写 evidence 文件
    att = run_postlock_sealed_preflight(
        out, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert att["pass"] is False
    assert verify_sealed_attestation(out)["pass"] is False


def test_sealed_preflight_requires_plan(monkeypatch, tmp_path):
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR", str(tmp_path))
    with pytest.raises(RuntimeError):
        run_postlock_sealed_preflight(
        tmp_path, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")


def test_sealed_preflight_digest_binding():
    att = {"format": "cur261-r5-sealed-final-preflight-v1",
           "pass": True, "plan_digest": "qp5-x"}
    d = sealed_preflight_digest(att)
    assert d.startswith("r5fa-")
    att["plan_digest"] = "qp5-y"
    assert sealed_preflight_digest(att) != d



def test_static_preflight_uses_no_final_namespace(
        monkeypatch, tmp_path, seed_call_recorder):
    """§26A:static preflight 全部使用非 final namespace(ppo_smoke_r5)。"""
    monkeypatch.setenv("CURRICULUM261_R5_LOCK_DIR",
                       str(tmp_path / "lockdir"))
    out = tmp_path / "static_out"
    result = pf.run_prelock_static_preflight(
        out, "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5")
    assert result["final_namespaces_touched"] == []
    assert result["namespaces_touched"] == ["ppo_smoke_r5"]
    assert all(c[0] not in FINAL_NAMESPACES for c in seed_call_recorder)
    # vendor pin 在测试环境应为真 pin(通过/失败取决于环境,但结构完整)
    assert "vendor" in result["checks"]
    assert result["checks"]["marker_atomic_exclusive"] is True
    assert result["checks"]["concurrent_final_lock_rejected"] is True
    assert (out / "prelock_static_preflight.json").is_file()
