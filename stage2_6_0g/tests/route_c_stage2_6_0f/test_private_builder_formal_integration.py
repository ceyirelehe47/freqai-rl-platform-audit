"""工作包 A4:私有 Builder 的 formal 集成路径(完整 verify / run 链路)。

必须证明:
- private builder A + commitment A + provider A -> formal verification
  PASS;
- private builder A + commitment A + provider B -> EXAM_INVALID;
- private builder A 被修改后仍使用旧 commitment -> EXAM_INVALID;
- Provider 缺失 -> EXAM_INVALID。

不只在 helper 单元测试中比较 hash:verify_sealed_commitment 与
run_sealed_exam(CLI private provider)两条完整集成路径都覆盖。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0c.conftest import (
    MOCK_TRAINING_RUNNER_HASH,
    _train_tiny_ppo,
    _write_attested_checkpoint,
)


def _materialize_null(pack):
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    by_family: dict[str, list] = {}
    for spec in pack.episodes:
        if spec.split == "null_control":
            by_family.setdefault(spec.family, []).append(
                R[spec.family].generate(
                    dict(spec.params), spec.seed, split=spec.split,
                    timeframe=spec.timeframe))
    return by_family


def _private_commitment(sealed_exam_env, provider):
    """用私有 Provider 全链构建 v6 承诺(pv 报告同 Provider 派生)。"""
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.mock_sealed_exam import build_mock_commitment

    env = sealed_exam_env
    identity = provider.builder_identity()
    contract = derive_global_null_duration_contract(
        env["pack"], required_families=[
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"])
    spec = build_spec_for_pack(
        env["eval_config"], timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        _materialize_null(env["pack"]), cfg=env["eval_config"],
        schema=env["schema"], spec=spec,
        pack_hash=env["pack"].pack_hash(),
        builder_identity=identity, duration_contract=contract)
    return build_mock_commitment(
        pack=env["pack"], charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
        null_qualification_bindings=_bindings(env),
        power_analysis_report=env["power_report"],
        pack_validity_report=pv,
        builder_provider=provider)


def _bindings(sealed_exam_env):
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    return build_null_qualification_bindings(
        sealed_exam_env["null_qual_reports"])


def _verify(commitment, sealed_exam_env, identity, contract):
    from rl_curriculum.sealed_exam import verify_sealed_commitment

    env = sealed_exam_env
    return verify_sealed_commitment(
        commitment, pack=env["pack"], charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"],
        builder_identity=identity, duration_contract=contract)


def test_private_a_with_provider_a_passes(sealed_exam_env, private_builder_a,
                                          duration_contract):
    """场景 1:private A + commitment A + provider A -> formal PASS。"""
    commitment = _private_commitment(sealed_exam_env, private_builder_a)
    identity = private_builder_a.builder_identity()
    report = _verify(commitment, sealed_exam_env, identity,
                     duration_contract)
    assert report["pass"]
    assert report["checks"]["pack_builder_code_hash"] is True
    assert commitment.pack_builder_code_hash == identity.manifest_hash


def test_private_a_committed_but_provider_b_rejected(sealed_exam_env,
                                                     private_builder_a,
                                                     private_builder_b,
                                                     duration_contract):
    """场景 2:private A 的承诺 + provider B -> EXAM_INVALID(替换攻击)。"""
    from rl_curriculum.sealed_exam import SealedExamError

    commitment = _private_commitment(sealed_exam_env, private_builder_a)
    wrong_identity = private_builder_b.builder_identity()
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        _verify(commitment, sealed_exam_env, wrong_identity,
                duration_contract)


def test_private_a_modified_old_commitment_rejected(sealed_exam_env,
                                                    private_builder_a,
                                                    duration_contract):
    """场景 3:private A 的源码被修改后,旧承诺失效(Provider 重算)。"""
    from rl_curriculum.sealed_exam import SealedExamError

    commitment = _private_commitment(sealed_exam_env, private_builder_a)
    root = Path(private_builder_a._root)
    # 修改安全相关辅助模块(attempt 选择链)
    victim = root / "pack_selection.py"
    victim.write_text(
        victim.read_text(encoding="utf-8") + "\n# tampered\n",
        encoding="utf-8")
    new_identity = private_builder_a.builder_identity()
    assert new_identity.manifest_hash != commitment.pack_builder_code_hash
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        _verify(commitment, sealed_exam_env, new_identity,
                duration_contract)


def test_missing_provider_rejected(sealed_exam_env, tmp_path):
    """场景 4:run_sealed_exam 缺 Provider -> EXAM_INVALID(fail closed,
    输出完整性失败而非崩溃)。"""
    from rl_curriculum.formal_exam import run_sealed_exam

    env = sealed_exam_env
    d = tmp_path / "no_provider"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    out, rc = run_sealed_exam(
        sealed_manifest_path=str(d / "commitment.json"),
        pack_path=str(d / "pack.json"),
        checkpoint_path=str(d / "nonexistent.zip"),
        out_path=str(d / "out.json"),
        retire_registry_path=str(d / "ret.json"),
        attempt_registry_path=str(d / "att.json"),
        charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"],
        builder_provider=None)
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert out["result"]["integrity_ok"] is False


@pytest.fixture(scope="module")
def private_checkpoint(tmp_path_factory, sealed_exam_env, schema):
    """mock issuer 签名的受控 PPO smoke checkpoint(私有链路用)。"""
    d = tmp_path_factory.mktemp("private-ckpt")
    material = _train_tiny_ppo(d / "smoke_private.zip", n_steps=256)
    out = _write_attested_checkpoint(
        d, "smoke_private.zip", schema, sealed_exam_env["keypair"],
        MOCK_TRAINING_RUNNER_HASH, material)
    return out["checkpoint"]


def test_run_sealed_exam_full_pipeline_with_private_provider(
        sealed_exam_env, private_builder_a, private_checkpoint, tmp_path):
    """完整 run_sealed_exam(CLI private provider)链路:承诺/报告/
    verifier 三方同一私有 builder 身份;smoke 模型正常 FAIL。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    commitment = _private_commitment(env, private_builder_a)
    d = tmp_path / "private_flow"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    commitment.save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(private_builder_a._root)),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v8"
    assert out["result"]["status"] == "FAIL"  # smoke 正常挂科
    checks = out["sealed_verification"]["checks"]
    assert checks.get("pack_builder_code_hash") is True


def test_run_sealed_exam_private_provider_mismatch(
        sealed_exam_env, private_builder_a, private_builder_b,
        private_checkpoint, tmp_path):
    """CLI 链路:承诺用 private A,运行时 Provider 用 B -> EXAM_INVALID。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    commitment = _private_commitment(env, private_builder_a)
    d = tmp_path / "mismatch_flow"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    commitment.save(d / "commitment.json")
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", private_checkpoint,
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "private",
        "--builder-provider-root", str(Path(private_builder_b._root)),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
