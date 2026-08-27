"""阶段 2.6.0g 收尾:mock formal 集成(CLI v9 全链 + 4b 失败时
Checkpoint/沙箱零接触的结构性证据)。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0c.conftest import (
    MOCK_TRAINING_RUNNER_HASH,
    _train_tiny_ppo,
    _write_attested_checkpoint,
)


def test_mock_cli_v9_full_chain(sealed_exam_env, tmp_path):
    """mock CLI v9:--builder-evidence + 第三次重组装 + 256步 PPO
    smoke 正常 FAIL。"""
    from rl_curriculum.builder_evidence import (
        write_builder_run_evidence,
    )
    from rl_curriculum.hidden_exam_cli import main as exam_main
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = sealed_exam_env
    d = tmp_path / "mock_chain"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    ev_path = d / "evidence.json"
    write_builder_run_evidence(ev_path, env["evidence"])
    write_exam_context(
        d / "ctx.json", charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"])
    material = _train_tiny_ppo(d / "smoke.zip", n_steps=256)
    attested = _write_attested_checkpoint(
        d, "smoke.zip", env["schema"], env["keypair"],
        MOCK_TRAINING_RUNNER_HASH, material)
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", attested["checkpoint"],
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "mock",
        "--builder-evidence", str(ev_path),
        "--retire-registry", str(d / "ret.json"),
        "--attempt-registry", str(d / "att.json"),
    ])
    out = json.loads((d / "out.json").read_text(encoding="utf-8"))
    assert rc == 0, out.get("sealed_verification", {})
    assert out["exam_cli_version"] == "hidden-exam-cli-v9"
    assert out["result"]["status"] == "FAIL"
    assert out["builder_provenance"]["mode"] == "mock_payload_assembly"
    assert out["builder_stage_access_audit"]["violations"] == []


def test_provenance_failure_never_touches_candidate(sealed_exam_env,
                                                    tmp_path,
                                                    monkeypatch):
    """4b 失败(evidence 缺失)时:checkpoint 从未被加载、Candidate
    沙箱从未启动(monkeypatch _load_sandboxed_candidate +
    load_checkpoint_manifest spy + audit hook)。"""
    from rl_curriculum import formal_exam
    from rl_curriculum.builder_evidence import (
        write_builder_run_evidence,
    )
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    env = sealed_exam_env
    d = tmp_path / "prov_fail"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    ev_path = d / "evidence.json"
    write_builder_run_evidence(ev_path, env["evidence"])
    calls = {"sandbox": 0, "ckpt_manifest": 0}

    def spy_sandbox(*a, **kw):
        calls["sandbox"] += 1
        raise AssertionError("沙箱不得启动")

    def spy_manifest(*a, **kw):
        calls["ckpt_manifest"] += 1
        raise AssertionError("checkpoint manifest 不得被加载")

    monkeypatch.setattr(formal_exam, "_load_sandboxed_candidate",
                        spy_sandbox)
    import rl_curriculum.checkpoints as ckpt_mod

    monkeypatch.setattr(ckpt_mod, "load_checkpoint_manifest",
                        spy_manifest)
    sentinel = d / "fake_checkpoint.zip"
    sentinel.write_bytes(b"SENTINEL")
    from rl_curriculum.access_guard import BuilderStageAccessGuard

    with BuilderStageAccessGuard([str(sentinel)]):
        out, rc = formal_exam.run_sealed_exam(
            sealed_manifest_path=str(d / "commitment.json"),
            pack_path=str(d / "pack.json"),
            checkpoint_path=str(sentinel),
            out_path=str(d / "out.json"),
            retire_registry_path=str(d / "ret.json"),
            attempt_registry_path=str(d / "att.json"),
            charter=env["charter"], schema=env["schema"],
            verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
            sandbox_profile=env["profile"],
            builder_provider=env["provider"],
            builder_evidence_path=str(d / "missing_evidence.json"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"
    assert calls["sandbox"] == 0
    assert calls["ckpt_manifest"] == 0


def test_provenance_failure_before_verify_checks(sealed_exam_env,
                                                 tmp_path):
    """4b 在 verify 之前失败 -> sealed_checks 为空(结构性顺序证据:
    integrity gate 先于承诺逐项验证,更先于候选加载)。"""
    from rl_curriculum import formal_exam

    env = sealed_exam_env
    d = tmp_path / "prov_early"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    out, rc = formal_exam.run_sealed_exam(
        sealed_manifest_path=str(d / "commitment.json"),
        pack_path=str(d / "pack.json"),
        checkpoint_path=str(d / "nonexistent.zip"),
        out_path=str(d / "out.json"),
        retire_registry_path=str(d / "ret.json"),
        attempt_registry_path=str(d / "att.json"),
        charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"],
        builder_provider=env["provider"],
        builder_evidence_path=str(d / "no_evidence.json"))
    assert rc == 5
    assert out["status"] == "EXAM_INVALID"


def test_mock_cli_missing_evidence_arg_rejected(sealed_exam_env,
                                                tmp_path):
    from rl_curriculum.hidden_exam_cli import main as exam_main

    env = sealed_exam_env
    d = tmp_path / "no_ev_arg"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    rc = exam_main([
        "--sealed-manifest", str(d / "commitment.json"),
        "--pack", str(d / "pack.json"),
        "--checkpoint", str(d / "none.zip"),
        "--context", str(d / "ctx.json"),
        "--out", str(d / "out.json"),
        "--builder-provider", "mock",
    ])
    assert rc == 2


def test_idempotent_retry_carries_audit(sealed_exam_env, tmp_path):
    """幂等重试输出同样携带 builder_provenance 与访问审计。"""
    from rl_curriculum.builder_evidence import (
        write_builder_run_evidence,
    )
    from rl_curriculum.formal_exam import run_sealed_exam

    env = sealed_exam_env
    d = tmp_path / "idem"
    d.mkdir()
    env["pack"].save(d / "pack.json")
    env["commitment"].save(d / "commitment.json")
    ev_path = d / "evidence.json"
    write_builder_run_evidence(ev_path, env["evidence"])
    material = _train_tiny_ppo(d / "smoke.zip", n_steps=256)
    attested = _write_attested_checkpoint(
        d, "smoke.zip", env["schema"], env["keypair"],
        MOCK_TRAINING_RUNNER_HASH, material)
    kwargs = dict(
        sealed_manifest_path=str(d / "commitment.json"),
        pack_path=str(d / "pack.json"),
        checkpoint_path=attested["checkpoint"],
        out_path=str(d / "out1.json"),
        retire_registry_path=str(d / "ret.json"),
        attempt_registry_path=str(d / "att.json"),
        charter=env["charter"], schema=env["schema"],
        verdict_spec=env["verdict_spec"], eval_config=env["eval_config"],
        sandbox_profile=env["profile"],
        builder_provider=env["provider"],
        builder_evidence_path=str(ev_path))
    out1, rc1 = run_sealed_exam(**kwargs)
    assert rc1 == 0 and out1["result"]["status"] == "FAIL"
    kwargs["out_path"] = str(d / "out2.json")
    out2, rc2 = run_sealed_exam(**kwargs)
    assert rc2 == 0
    assert out2["attempt"]["idempotent_retry_of"] == \
        out1["attempt"]["attempt_id"]
    assert "builder_provenance" in out2
    assert out2["builder_stage_access_audit"]["violations"] == []
