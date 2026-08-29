"""阶段 2.6.0c 工作包 F:mock 正式全链路(v4)。

链路:真实 strict Null qualification reports -> issuer/受信 runner ->
受控 PPO smoke checkpoint + attestation -> v3 承诺(含 runtime tree
hash)-> 系统级沙箱加载 -> 正式反事实套件(四原因 3 seed)-> 冻结判定
-> 幂等重试。256/64-step PPO 只作为 provenance/沙箱/接口 smoke,
允许正常挂科;不构成课程训练。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


def _build_flow(tmp_path: Path, env, checkpoint, *, with_issuer_copy=True):
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env["pack"].save(tmp_path / "pack.json")
    env["commitment"].save(tmp_path / "commitment.json")
    ctx_kwargs = {}
    if with_issuer_copy:
        ctx_kwargs["trusted_issuer"] = env["trusted_issuer"]
    write_exam_context(
        tmp_path / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"], **ctx_kwargs)
    return {
        "tmp": tmp_path,
        "pack": str(tmp_path / "pack.json"),
        "commitment": str(tmp_path / "commitment.json"),
        "checkpoint": checkpoint,
        "ctx": str(tmp_path / "ctx.json"),
        "evidence": env["evidence_path"],
    }


def _run_cli(paths, out_name, *extra) -> int:
    from rl_curriculum.hidden_exam_cli import main as exam_main

    tmp = paths["tmp"]
    return exam_main([
        "--sealed-manifest", paths["commitment"],
        "--pack", paths["pack"],
        "--checkpoint", paths["checkpoint"],
        "--context", paths["ctx"],
        "--out", str(tmp / out_name),
        "--builder-provider", "mock",
        "--builder-evidence", paths["evidence"],
        "--retire-registry", str(tmp / "ret.json"),
        "--attempt-registry", str(tmp / "attempts.json"),
        *extra,
    ])


def test_mock_sealed_exam_v4_full_pipeline(tmp_path, sealed_exam_env,
                                           sandbox_checkpoint):
    """端到端:v3 承诺 + 沙箱 + 反事实套件 + 冻结判定(smoke 模型允许
    FAIL,但不得 EXAM_INVALID;幂等重试返回同一结果)。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint)

    rc = _run_cli(paths, "out1.json")
    out1 = json.loads((tmp_path / "out1.json").read_text(encoding="utf-8"))
    assert rc == 0, out1.get("sealed_verification", {}).get("problems")
    assert out1["mode"] == "sealed"
    assert out1["exam_cli_version"] == "hidden-exam-cli-v11"
    status = out1["result"]["status"]
    assert status in ("PASS", "FAIL", "SUSPECTED_CHEATING"), status
    # smoke 模型预期普通挂科,不是作弊(无有效成绩不判作弊)
    assert status == "FAIL"

    # 幂等重试:同 (checkpoint, pack) 返回同一结果
    rc2 = _run_cli(paths, "out2.json")
    out2 = json.loads((tmp_path / "out2.json").read_text(encoding="utf-8"))
    assert rc2 == 0
    assert out2["result"]["status"] == out1["result"]["status"]
    assert out2["attempt"].get("idempotent_retry_of") == \
        out1["attempt"]["attempt_id"]

    # 四种作弊原因的复制证据已在详细路径之外通过 sealed 验证
    # (counterfactual_code_hash/verdict_spec/anticheat spec 全部对账)
    checks = out1["sealed_verification"]["checks"]
    assert all(checks.values()), checks


def test_v4_flow_without_issuer_copy(tmp_path, sealed_exam_env,
                                     sandbox_checkpoint):
    """context 不带 issuer 副本也可正常执行(信任根来自承诺)。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint,
                        with_issuer_copy=False)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 0
    assert out["result"]["status"] != "EXAM_INVALID"


def test_v4_flow_attestation_signed_by_wrong_key(tmp_path, sealed_exam_env,
                                                 sandbox_checkpoint,
                                                 attacker_issuer_keypair,
                                                 schema):
    """checkpoint 的 attestation 由不受信密钥签名(承诺仍绑定 A)
    -> EXAM_INVALID(即便 context 不携带 issuer 副本也无法绕过)。"""
    from tests.route_c_stage2_6_0c.conftest import (
        MOCK_TRAINING_RUNNER_HASH,
        _train_tiny_ppo,
        _write_attested_checkpoint,
    )

    env = sealed_exam_env
    d = tmp_path / "wrong_key"
    d.mkdir()
    material = _train_tiny_ppo(d / "rogue.zip")
    # runner hash 用受信值(材料除签名密钥外全部合法)
    _write_attested_checkpoint(
        d, "rogue.zip", schema, attacker_issuer_keypair,
        MOCK_TRAINING_RUNNER_HASH, material)
    paths = _build_flow(tmp_path, env, str(d / "rogue.zip"),
                        with_issuer_copy=False)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_detailed_disclosure_retires_and_records(tmp_path, sealed_exam_env,
                                                 sandbox_checkpoint):
    """--detailed 披露后包退休;EXAM_INVALID 不退休。"""
    from rl_curriculum.exam_pack import RetirementRegistry

    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint)
    rc = _run_cli(paths, "detail.json", "--detailed",
                  str(tmp_path / "detail_out.json"))
    out = json.loads((tmp_path / "detail.json").read_text(encoding="utf-8"))
    assert rc == 0
    detail = json.loads(
        (tmp_path / "detail_out.json").read_text(encoding="utf-8"))
    assert "replication_evidence" in detail
    assert detail["attestation"]["issuer_fingerprint"].startswith("ik-")
    reg = RetirementRegistry(tmp_path / "ret.json")
    assert reg.is_retired(env["pack"].pack_hash())


def test_runtime_tamper_between_commitment_and_run(tmp_path,
                                                   sealed_exam_env,
                                                   sandbox_checkpoint,
                                                   monkeypatch):
    """承诺后源运行时被改 -> sealed 验证拒绝(EXAM_INVALID)。"""
    import rl_curriculum.sandbox as sandbox_mod

    env = sealed_exam_env
    real = sandbox_mod.compute_runtime_manifest
    src = sandbox_mod.__file__

    def tampered(source_dir=None):
        manifest = real(source_dir)
        manifest = dict(manifest)
        manifest["files"] = dict(manifest["files"])
        manifest["files"]["worker.py"] = "0" * 64
        return manifest

    monkeypatch.setattr(sandbox_mod, "compute_runtime_manifest", tampered)
    del src
    paths = _build_flow(tmp_path, env, sandbox_checkpoint)
    rc = _run_cli(paths, "out.json")
    out = json.loads((tmp_path / "out.json").read_text(encoding="utf-8"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    # EXAM_INVALID 输出脱敏(不披露具体失败检查;fail closed 即证据)


def test_attempts_registry_records_outcome(tmp_path, sealed_exam_env,
                                           sandbox_checkpoint):
    """attempt registry 记录成功/无效尝试。"""
    env = sealed_exam_env
    paths = _build_flow(tmp_path, env, sandbox_checkpoint)
    rc = _run_cli(paths, "out.json")
    assert rc == 0
    registry = json.loads(
        (tmp_path / "attempts.json").read_text(encoding="utf-8"))
    entries = registry["attempts"]
    assert entries
    assert entries[0]["completed"] is True
    assert entries[0]["status"] in ("FAIL", "PASS", "SUSPECTED_CHEATING")
