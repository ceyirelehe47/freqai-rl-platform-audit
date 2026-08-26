"""工作包 J:mock 正式全链路 v3(评估方准备 -> 受控训练 -> 沙箱评估 ->
冻结判定;篡改即 EXAM_INVALID)。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="module")
def mock_exam_workspace(tmp_path_factory, sealed_exam_env,
                        attested_checkpoint):
    """mock 评估工作区:pack/context/commitment/registries/issuer 公钥。"""
    from rl_curriculum.mock_sealed_exam import (
        build_mock_hidden_pack,
        write_exam_context,
    )

    ws = tmp_path_factory.mktemp("mock-exam-ws")
    pack = sealed_exam_env["pack"]
    pack_path = ws / "pack.json"
    pack.save(pack_path)
    ctx_path = ws / "context.json"
    write_exam_context(
        ctx_path, charter=sealed_exam_env["charter"],
        schema=sealed_exam_env["schema"],
        verdict_spec=sealed_exam_env["verdict_spec"],
        eval_config=sealed_exam_env["eval_config"],
        sandbox_profile=sealed_exam_env["profile"],
        trusted_issuer=sealed_exam_env["trusted_issuer"])
    manifest_path = ws / "commitment.json"
    sealed_exam_env["commitment"].save(manifest_path)
    # 训练侧提交物(checkpoint + sidecar + attestation 来自受控 runner)
    ck_dir = ws / "submission"
    ck_dir.mkdir()
    ck_src = Path(attested_checkpoint["checkpoint"])
    ck_dst = ck_dir / ck_src.name
    ck_dst.write_bytes(ck_src.read_bytes())
    for suffix in (".rl_manifest.json", ".rl_attestation.json"):
        (ck_dir / (ck_src.name + suffix)).write_text(
            Path(str(ck_src) + suffix).read_text())
    return {
        "workspace": ws,
        "pack": pack_path,
        "context": ctx_path,
        "commitment": manifest_path,
        "checkpoint": ck_dst,
        "retire": ws / "retired.json",
        "attempts": ws / "attempts.json",
        "out": ws / "result.json",
    }


def _cli_env():
    import os

    env = dict(os.environ)
    src_root = str(Path(__file__).resolve().parents[2] / "src")
    env["PYTHONPATH"] = src_root + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_cli(env):
    return subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--sealed-manifest", str(env["commitment"]),
         "--pack", str(env["pack"]),
         "--checkpoint", str(env["checkpoint"]),
         "--context", str(env["context"]),
         "--out", str(env["out"]),
         "--retire-registry", str(env["retire"]),
         "--attempt-registry", str(env["attempts"])],
        capture_output=True, text=True, timeout=3600, env=_cli_env())


def test_mock_sealed_exam_v3_full_pipeline(mock_exam_workspace):
    env = mock_exam_workspace
    proc = _run_cli(env)
    assert proc.returncode in (0,), proc.stderr[-3000:]
    out = json.loads(env["out"].read_text(encoding="utf-8"))
    assert out["mode"] == "sealed"
    assert out["exam_cli_version"] == "hidden-exam-cli-v3"
    status = out["result"]["status"]
    # 测试级 PPO 允许 FAIL,但必须是四态之一且来自冻结判定器
    assert status in ("PASS", "FAIL", "SUSPECTED_CHEATING")
    assert out["result"]["integrity_ok"] is True
    assert out["sealed_verification"]["checks"]  # 逐项验证已执行
    assert out["result"]["hard_gates"]


def test_idempotent_retry_returns_same_attempt(mock_exam_workspace):
    env = dict(mock_exam_workspace)
    env["out"] = env["workspace"] / "result2.json"
    proc = _run_cli(env)
    assert proc.returncode == 0
    out = json.loads(env["out"].read_text(encoding="utf-8"))
    assert out["attempt"].get("idempotent_retry_of")


def test_tampered_pack_is_exam_invalid(mock_exam_workspace, tmp_path):
    """篡改矩阵:改 pack(种子)-> EXAM_INVALID(退出码 5)。"""
    env = mock_exam_workspace
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec

    pack = ExamPack.load(env["pack"])
    tampered = ExamPack(
        name=pack.name, version=pack.version, visibility=pack.visibility,
        charter_hash=pack.charter_hash,
        spec_versions=pack.spec_versions,
        episodes=[EpisodeSpec(e.family, dict(e.params), e.seed + 1,
                              e.split, e.timeframe)
                  for e in pack.episodes],
        timeframe=pack.timeframe, notes=pack.notes)
    tpath = tmp_path / "tampered_pack.json"
    tampered.save(tpath)
    out_path = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--sealed-manifest", str(env["commitment"]),
         "--pack", str(tpath),
         "--checkpoint", str(env["checkpoint"]),
         "--context", str(env["context"]),
         "--out", str(out_path),
         "--retire-registry", str(tmp_path / "r.json"),
         "--attempt-registry", str(tmp_path / "a.json")],
        capture_output=True, text=True, timeout=600, env=_cli_env())
    assert proc.returncode == 5
    result = json.loads(out_path.read_text(encoding="utf-8"))
    assert result["status"] == "EXAM_INVALID"


def test_tampered_eval_config_is_exam_invalid(mock_exam_workspace, tmp_path,
                                              sealed_exam_env):
    """改 EvalConfig(fee)-> EXAM_INVALID。"""
    from rl_curriculum.mock_sealed_exam import write_exam_context

    env = mock_exam_workspace
    cfg = sealed_exam_env["eval_config"]
    import dataclasses

    bad_cfg = dataclasses.replace(cfg, fee=cfg.fee * 10)
    ctx2 = tmp_path / "ctx2.json"
    write_exam_context(
        ctx2, charter=sealed_exam_env["charter"],
        schema=sealed_exam_env["schema"],
        verdict_spec=sealed_exam_env["verdict_spec"],
        eval_config=bad_cfg,
        sandbox_profile=sealed_exam_env["profile"],
        trusted_issuer=sealed_exam_env["trusted_issuer"])
    out_path = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--sealed-manifest", str(env["commitment"]),
         "--pack", str(env["pack"]),
         "--checkpoint", str(env["checkpoint"]),
         "--context", str(ctx2),
         "--out", str(out_path),
         "--retire-registry", str(tmp_path / "r.json"),
         "--attempt-registry", str(tmp_path / "a.json")],
        capture_output=True, text=True, timeout=600, env=_cli_env())
    assert proc.returncode == 5
    assert json.loads(out_path.read_text(encoding="utf-8"))[
        "status"] == "EXAM_INVALID"


def test_tampered_checkpoint_is_exam_invalid(mock_exam_workspace, tmp_path):
    """替换 checkpoint 字节(atts 绑定失败)-> EXAM_INVALID。"""
    env = mock_exam_workspace
    bad = tmp_path / "bad.zip"
    bad.write_bytes(Path(env["checkpoint"]).read_bytes() + b"x")
    for suffix in (".rl_manifest.json", ".rl_attestation.json"):
        (tmp_path / (bad.name + suffix)).write_text(
            Path(str(env["checkpoint"]) + suffix).read_text())
    out_path = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--sealed-manifest", str(env["commitment"]),
         "--pack", str(env["pack"]),
         "--checkpoint", str(bad),
         "--context", str(env["context"]),
         "--out", str(out_path),
         "--retire-registry", str(tmp_path / "r.json"),
         "--attempt-registry", str(tmp_path / "a.json")],
        capture_output=True, text=True, timeout=600, env=_cli_env())
    assert proc.returncode == 5


def test_missing_attestation_is_exam_invalid(mock_exam_workspace, tmp_path):
    """提交物缺 attestation -> EXAM_INVALID(自声明无效)。"""
    env = mock_exam_workspace
    ck = tmp_path / env["checkpoint"].name
    ck.write_bytes(Path(env["checkpoint"]).read_bytes())
    (tmp_path / (ck.name + ".rl_manifest.json")).write_text(
        Path(str(env["checkpoint"]) + ".rl_manifest.json").read_text())
    # 不复制 attestation
    out_path = tmp_path / "out.json"
    proc = subprocess.run(
        [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
         "--sealed-manifest", str(env["commitment"]),
         "--pack", str(env["pack"]),
         "--checkpoint", str(ck),
         "--context", str(env["context"]),
         "--out", str(out_path),
         "--retire-registry", str(tmp_path / "r.json"),
         "--attempt-registry", str(tmp_path / "a.json")],
        capture_output=True, text=True, timeout=600, env=_cli_env())
    assert proc.returncode == 5
