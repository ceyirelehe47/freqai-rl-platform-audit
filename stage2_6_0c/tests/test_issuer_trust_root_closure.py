"""阶段 2.6.0c 工作包 A:issuer 信任根收归 sealed commitment。

攻击矩阵:
- 端到端 context issuer override 攻击(承诺仍绑定 A,context 换 B,
  checkpoint 由 B 自签,runner 也改成 B 信任的)必须 EXAM_INVALID;
- 正式 API/CLI 不存在 issuer override 通道;
- context issuer 缺失不影响执行器从承诺构造信任根;
- 承诺 issuer 公钥与 fingerprint 不一致被拒;
- 承诺 runner hash 被改被拒;
- 承诺 smoke 策略被改 = 原承诺失效(承诺哈希变化)。
"""

from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0c.conftest import MOCK_TRAINING_RUNNER_HASH


# ---------------------------------------------------------------- API 面
def test_formal_api_has_no_issuer_override():
    """正式 run_sealed_exam 签名不存在 issuer 覆盖参数。"""
    from rl_curriculum.formal_exam import run_sealed_exam

    params = inspect.signature(run_sealed_exam).parameters
    assert "trusted_issuer" not in params, (
        "run_sealed_exam 不得携带可覆盖信任根的 issuer 参数(工作包 A)")
    # 任何以 issuer 命名的参数只允许 context_issuer_payload(展示副本
    # 的 canonical equality 检查输入,不是信任根)
    issuer_like = [p for p in params if "issuer" in p]
    assert issuer_like == ["context_issuer_payload"], issuer_like
    # 缺省必须为 None(不存在"非空优先"语义)
    assert params["context_issuer_payload"].default is None


def test_cli_does_not_pass_issuer_from_context():
    """CLI 不再从 context 读取 issuer 作为运行时参数。"""
    import rl_curriculum.hidden_exam_cli as cli

    src = inspect.getsource(cli.main)
    assert "trusted_issuer=ctx" not in src, (
        "CLI 不得把 context issuer 作为信任根传给执行器")
    assert "context_issuer_payload=ctx" in src
    # load_exam_context 不再返回 TrustedIssuerConfig 对象(只有展示副本)
    src2 = inspect.getsource(
        __import__("rl_curriculum.mock_sealed_exam",
                   fromlist=["load_exam_context"]).load_exam_context)
    assert "TrustedIssuerConfig" not in src2


def test_context_issuer_payload_is_display_copy_only(tmp_path, schema,
                                                      sandbox_profile,
                                                      mock_trusted_issuer):
    """context 的 issuer 副本与承诺一致时不阻断(仅 equality 检查)。"""
    from rl_curriculum.mock_sealed_exam import (
        load_exam_context,
        write_exam_context,
    )

    write_exam_context(tmp_path / "ctx.json", schema=schema,
                       sandbox_profile=sandbox_profile,
                       trusted_issuer=mock_trusted_issuer)
    ctx = load_exam_context(tmp_path / "ctx.json")
    assert ctx["trusted_issuer_payload"] == \
        mock_trusted_issuer.canonical_payload()
    # 不带 issuer 的 context 也能加载(副本缺失不影响信任根)
    write_exam_context(tmp_path / "ctx2.json", schema=schema,
                       sandbox_profile=sandbox_profile)
    ctx2 = load_exam_context(tmp_path / "ctx2.json")
    assert "trusted_issuer_payload" not in ctx2


# ------------------------------------------------------------ 自洽校验
def test_issuer_fingerprint_inconsistency_rejected(mock_trusted_issuer):
    """承诺 issuer 公钥与 fingerprint 不一致 -> 自洽校验失败。"""
    from rl_curriculum.attestation import (
        AttestationError,
        Ed25519KeyPair,
        verify_issuer_payload_self_consistency,
    )

    payload = mock_trusted_issuer.canonical_payload()
    # 换成另一把公钥但保留原 fingerprint
    other = Ed25519KeyPair.generate("other-key")
    tampered = dict(payload,
                    public_key_pem=other.public_pem.decode("utf-8"))
    with pytest.raises(AttestationError, match="指纹不自洽"):
        verify_issuer_payload_self_consistency(tampered)


def test_issuer_self_consistency_matrix(mock_trusted_issuer):
    from rl_curriculum.attestation import (
        AttestationError,
        verify_issuer_payload_self_consistency,
    )

    payload = mock_trusted_issuer.canonical_payload()
    verify_issuer_payload_self_consistency(payload)  # 原样通过
    cases = {
        "protocol": {**payload, "protocol": "training-attestation-v0"},
        "issuer_id": {**payload, "issuer_id": "  "},
        "runner_hash_empty": {
            **payload, "required_training_runner_hash": "x"},
        "runner_hash_space": {
            **payload, "required_training_runner_hash": "mock runner hash"},
        "smoke_not_bool": {**payload, "allow_smoke": "false"},
        "extra_field": {**payload, "note": "attacker"},
        "missing_field": {k: v for k, v in payload.items()
                          if k != "allow_smoke"},
        "bad_pem": {**payload, "public_key_pem": "not a pem"},
    }
    for name, tampered in cases.items():
        with pytest.raises(AttestationError):
            verify_issuer_payload_self_consistency(tampered)


# ------------------------------------------------------- 端到端攻击矩阵
def _setup_sealed_flow(tmp_path, env, checkpoint) -> dict:
    """布置 CLI 全链路材料(pack/context/commitment/registry 路径)。"""
    env["pack"].save(tmp_path / "pack.json")
    env["commitment"].save(tmp_path / "commitment.json")
    return {
        "tmp": tmp_path,
        "pack": str(tmp_path / "pack.json"),
        "commitment": str(tmp_path / "commitment.json"),
        "checkpoint": checkpoint,
    }


def _run_cli(paths, ctx_path, out_name="out.json") -> int:
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = paths["tmp"]
    return exam_main([
        "--sealed-manifest", paths["commitment"],
        "--pack", paths["pack"],
        "--checkpoint", paths["checkpoint"],
        "--context", str(ctx_path),
        "--out", str(tmp / out_name),
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
    ])


def test_context_issuer_override_attack_end_to_end(
        tmp_path, sealed_exam_env, sandbox_checkpoint, schema,
        sandbox_profile, attacker_issuer_keypair):
    """核心攻击:承诺仍绑定 issuer A;context 改为 issuer B;checkpoint
    attestation 由 B 自签;runner hash 也改成 B 所信任的。

    预期:EXAM_INVALID——正式信任根唯一来自承诺,context 副本与承诺
    任何字段不同都被拒绝(即便 B 的整套自签材料完全自洽)。
    """
    from rl_curriculum.attestation import TrustedIssuerConfig
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    attacker_runner = "attacker-runner-" + "c" * 57
    attacker_issuer = TrustedIssuerConfig.from_keypair(
        attacker_issuer_keypair,
        required_training_runner_hash=attacker_runner)
    # 攻击者的 context:issuer 副本指向自己的公钥与 runner
    ctx_path = tmp_path / "ctx_attacker.json"
    write_exam_context(ctx_path, charter=env["charter"], schema=schema,
                       verdict_spec=env["verdict_spec"],
                       eval_config=env["eval_config"],
                       sandbox_profile=sandbox_profile,
                       trusted_issuer=attacker_issuer)
    # 攻击者的 checkpoint:复制 A 的文件字节,attestation 由 B 签且
    # 声明 B 信任的 runner hash(整套 B 材料完全自洽)
    import hashlib as _h
    import shutil

    d = tmp_path / "attacker"
    d.mkdir()
    shutil.copyfile(sandbox_checkpoint, d / "stolen.zip")
    shutil.copyfile(str(sandbox_checkpoint) + ".rl_manifest.json",
                    str(d / "stolen.zip") + ".rl_manifest.json")
    ckpt_sha = _h.sha256((d / "stolen.zip").read_bytes()).hexdigest()
    sidecar_sha = _h.sha256(
        (d / "stolen.zip.rl_manifest.json").read_bytes()).hexdigest()
    tm_sha = _h.sha256(b"attacker-training-manifest").hexdigest()
    (d / "stolen.zip.training_manifest.json").write_bytes(
        b"attacker-training-manifest")
    from rl_curriculum.attestation import (
        build_attestation_payload,
        write_attestation,
    )

    payload = build_attestation_payload(
        checkpoint_sha256=ckpt_sha, sidecar_sha256=sidecar_sha,
        training_manifest_sha256=tm_sha,
        charter_hash=env["commitment"].charter_hash,
        observation_schema_hash=env["schema"].schema_hash(),
        route_c_env_version="RouteCEnvCore-v1.0.0",
        training_generator_hashes={},
        training_pack_hash="attacker-pack",
        training_code_hash="attacker-code",
        ppo_params={"declared_by": "attacker"},
        network_architecture={"declared_by": "attacker"},
        training_budget={"total_timesteps": 64},
        training_seed=7, is_smoke=False, allow_formal_evaluation=True,
        issuer_id=attacker_issuer_keypair.issuer_id,
        training_runner_hash=attacker_runner,
        issued_utc="2026-08-26T00:00:00Z")
    write_attestation(d / "stolen.zip.rl_attestation.json",
                      attacker_issuer_keypair, payload)

    paths = _setup_sealed_flow(tmp_path, env, str(d / "stolen.zip"))
    rc = _run_cli(paths, ctx_path)
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_context_without_issuer_copy_uses_commitment_root(
        tmp_path, sealed_exam_env, sandbox_checkpoint, schema,
        sandbox_profile):
    """context 不带 issuer 副本时,执行器仍从承诺构造信任根正常执行
    (A 签名的 checkpoint 通过;输出不是 EXAM_INVALID)。"""
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    ctx_path = tmp_path / "ctx_no_issuer.json"
    write_exam_context(ctx_path, charter=env["charter"], schema=schema,
                       verdict_spec=env["verdict_spec"],
                       eval_config=env["eval_config"],
                       sandbox_profile=sandbox_profile)
    paths = _setup_sealed_flow(tmp_path, env, sandbox_checkpoint)
    rc = _run_cli(paths, ctx_path)
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    status = out.get("status") or out["result"]["status"]
    assert status != "EXAM_INVALID"
    assert rc == 0


def test_commitment_runner_hash_modified_rejected(
        tmp_path, sealed_exam_env, sandbox_checkpoint, schema,
        sandbox_profile, mock_trusted_issuer):
    """承诺 issuer 的 runner hash 被改 -> A 签 attestation 的 runner
    hash 不再受信 -> EXAM_INVALID。"""
    import copy as _copy

    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    tampered = _copy.deepcopy(env["commitment"])
    tampered.trusted_issuer = {
        **tampered.trusted_issuer,
        "required_training_runner_hash": "hijacked-runner-" + "d" * 55,
    }
    ctx_path = tmp_path / "ctx.json"
    write_exam_context(ctx_path, charter=env["charter"], schema=schema,
                       verdict_spec=env["verdict_spec"],
                       eval_config=env["eval_config"],
                       sandbox_profile=sandbox_profile,
                       trusted_issuer=mock_trusted_issuer)
    env["pack"].save(tmp_path / "pack.json")
    tampered.save(tmp_path / "commitment.json")
    paths = {
        "tmp": tmp_path,
        "pack": str(tmp_path / "pack.json"),
        "commitment": str(tmp_path / "commitment.json"),
        "checkpoint": sandbox_checkpoint,
    }
    rc = _run_cli(paths, ctx_path)
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5 and out["status"] == "EXAM_INVALID"


def test_commitment_smoke_policy_modified_invalidates(sealed_exam_env):
    """allow_smoke 是承诺冻结的一部分:被改 = 承诺哈希变化(原承诺失效)。"""
    env = sealed_exam_env
    c = copy.deepcopy(env["commitment"])
    original_hash = c.commitment_hash()
    c.trusted_issuer = {**c.trusted_issuer, "allow_smoke": True}
    assert c.commitment_hash() != original_hash
    # canonical payload 内 smoke 字段被承诺哈希覆盖
    payload = c.canonical_payload()
    assert payload["trusted_issuer"]["allow_smoke"] is True
    assert env["commitment"].trusted_issuer["allow_smoke"] is False


def test_smoke_checkpoint_rejected_when_issuer_disallows_smoke(
        sealed_exam_env):
    """受信配置 allow_smoke=False 时 smoke attestation 不得通过。"""
    from rl_curriculum.attestation import verify_attestation

    env = sealed_exam_env
    issuer = env["trusted_issuer"]
    assert issuer.allow_smoke is False
    doc = {"payload": {"is_smoke": True,
                       "issuer_id": issuer.issuer_id,
                       "training_runner_hash":
                       issuer.required_training_runner_hash},
           "signature": "00", "public_key_pem": issuer.public_key_pem,
           "key_fingerprint": issuer.key_fingerprint}
    with pytest.raises(Exception):
        verify_attestation(
            doc, trusted=issuer, checkpoint_path="/nonexistent",
            sidecar_sha256="x", training_manifest_sha256="x",
            charter_hash="c", observation_schema_hash="o")
