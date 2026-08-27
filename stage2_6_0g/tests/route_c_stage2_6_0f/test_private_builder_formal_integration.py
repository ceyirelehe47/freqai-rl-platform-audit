"""工作包 A4(收尾版):私有 Builder 的 formal 集成路径。

v2 语义:私有链路的承诺 pack 必须就是私有 Builder 在隔离 Runner 内
的实际产物(precommit 双跑取得),不再用公开 mock pack 组合私有身份。

必须证明:
- private builder A + 承诺(其自身产物) + provider A -> formal PASS;
- private builder A 的承诺 + provider B -> EXAM_INVALID;
- private builder A 被修改后仍使用旧承诺 -> EXAM_INVALID;
- Provider 缺失 -> EXAM_INVALID;
- CLI 完整链路(--builder-evidence)smoke 正常 FAIL。
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
from tests.route_c_stage2_6_0f.conftest import (
    private_provider_from_root,
    write_private_builder,
)

FAMILIES = ("probe_null_sign", "probe_null_volstate",
            "probe_null_stochvol")


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


def _private_chain(sealed_exam_env, provider, tmp_path):
    """私有链路材料:precommit 双跑私有 pack + validity + 承诺 v8。"""
    from rl_curriculum.builder_evidence import precommit_builder_runs
    from rl_curriculum.mock_sealed_exam import (
        assemble_mock_hidden_pack,
        build_mock_commitment,
    )
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    env = sealed_exam_env
    identity = provider.builder_identity()
    seed_pack = assemble_mock_hidden_pack()
    dc_seed = derive_global_null_duration_contract(
        seed_pack, required_families=list(FAMILIES))
    # 探路构建:dc 依赖 pack episode 数,先探一次取最终 pack 形态
    probe_req = provider.frozen_build_request(seed_pack, dc_seed)
    _pev, probe_runs = precommit_builder_runs(
        provider, probe_req, builder_root=provider.root)
    pack = probe_runs[0]["pack"]
    dc_seed = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    req = provider.frozen_build_request(pack, dc_seed)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    pack = runs[0]["pack"]
    contract = derive_global_null_duration_contract(
        pack, required_families=list(FAMILIES))
    spec = build_spec_for_pack(
        env["eval_config"], timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    pv = validate_null_pack(
        _materialize_null(pack), cfg=env["eval_config"],
        schema=env["schema"], spec=spec, pack_hash=pack.pack_hash(),
        builder_identity=identity, duration_contract=contract)
    ev_path = tmp_path / "private_evidence.json"
    from rl_curriculum.builder_evidence import (
        write_builder_run_evidence,
    )

    write_builder_run_evidence(ev_path, evidence)
    commitment = build_mock_commitment(
        pack=pack, charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"], trusted_issuer=env["trusted_issuer"],
        null_qualification_bindings=_bindings(env),
        power_analysis_report=env["power_report"],
        pack_validity_report=pv,
        builder_provider=provider)
    return {
        "pack": pack, "contract": contract, "commitment": commitment,
        "evidence": evidence, "ev_path": str(ev_path),
    }


def _bindings(sealed_exam_env):
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    return build_null_qualification_bindings(
        sealed_exam_env["null_qual_reports"])


def _verify(commitment, sealed_exam_env, identity, pack, contract):
    from rl_curriculum.sealed_exam import verify_sealed_commitment

    env = sealed_exam_env
    return verify_sealed_commitment(
        commitment, pack=pack, charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"],
        builder_identity=identity, duration_contract=contract)


def test_private_a_with_provider_a_passes(sealed_exam_env, private_builder_a,
                                          duration_contract, tmp_path):
    """场景 1:private A 的自身产物承诺 + provider A -> formal PASS。"""
    ch = _private_chain(sealed_exam_env, private_builder_a, tmp_path)
    identity = private_builder_a.builder_identity()
    report = _verify(ch["commitment"], sealed_exam_env, identity,
                     ch["pack"], ch["contract"])
    assert report["pass"]
    assert report["checks"]["pack_builder_code_hash"] is True
    assert ch["commitment"].pack_builder_code_hash == identity.manifest_hash
    assert ch["commitment"].builder_run_evidence["mode"] == \
        "builder_execution"


def test_private_a_committed_but_provider_b_rejected(sealed_exam_env,
                                                     private_builder_a,
                                                     private_builder_b,
                                                     duration_contract,
                                                     tmp_path):
    """场景 2:private A 的承诺 + provider B -> EXAM_INVALID(替换攻击)。"""
    from rl_curriculum.sealed_exam import SealedExamError

    ch = _private_chain(sealed_exam_env, private_builder_a, tmp_path)
    wrong_identity = private_builder_b.builder_identity()
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        _verify(ch["commitment"], sealed_exam_env, wrong_identity,
                ch["pack"], ch["contract"])


def test_private_a_modified_old_commitment_rejected(sealed_exam_env,
                                                    private_builder_a,
                                                    duration_contract,
                                                    tmp_path):
    """场景 3:private A 的源码被修改后,旧承诺失效(Provider 重算)。"""
    from rl_curriculum.sealed_exam import SealedExamError

    ch = _private_chain(sealed_exam_env, private_builder_a, tmp_path)
    root = Path(private_builder_a.root)
    victim = root / "pack_selection.py"
    victim.write_text(
        victim.read_text(encoding="utf-8") + "\n# tampered\n",
        encoding="utf-8")
    new_identity = private_builder_a.builder_identity()
    assert new_identity.manifest_hash != \
        ch["commitment"].pack_builder_code_hash
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        _verify(ch["commitment"], sealed_exam_env, new_identity,
                ch["pack"], ch["contract"])


def test_missing_provider_rejected(sealed_exam_env, tmp_path):
    """场景 4:run_sealed_exam 缺 Provider -> EXAM_INVALID(fail closed)。"""
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
        builder_provider=None,
        builder_evidence_path=env["evidence_path"])
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
    verifier/证据四方同一私有 builder 身份;smoke 模型正常 FAIL。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    ch = _private_chain(env, private_builder_a, tmp_path)
    d = tmp_path / "private_flow"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
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
        "--builder-provider-root", str(Path(private_builder_a.root)),
        "--builder-evidence", ch["ev_path"],
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v9"
    assert out["result"]["status"] == "FAIL"  # smoke 正常挂科
    assert out["builder_provenance"]["mode"] == "builder_execution"
    assert out["builder_provenance"]["replay_isolated_process"] is True
    checks = out["sealed_verification"]["checks"]
    assert checks.get("pack_builder_code_hash") is True


def test_run_sealed_exam_private_provider_mismatch(
        sealed_exam_env, private_builder_a, private_builder_b,
        private_checkpoint, tmp_path):
    """CLI 链路:承诺用 private A,运行时 Provider 用 B -> EXAM_INVALID。"""
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    ch = _private_chain(env, private_builder_a, tmp_path)
    d = tmp_path / "mismatch_flow"
    d.mkdir()
    ch["pack"].save(d / "pack.json")
    ch["commitment"].save(d / "commitment.json")
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
        "--builder-provider-root", str(Path(private_builder_b.root)),
        "--builder-evidence", ch["ev_path"],
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
