"""工作包 F:formal_eligible=false 的 checkpoint 不得参加正式考试。"""

from __future__ import annotations

import json
import shutil

from rl_curriculum.checkpoints import (
    is_formal_eligible,
    mark_legacy_engineering_evidence,
    save_checkpoint_manifest,
)
from rl_curriculum.probe_charter import probe_observation_schema
from tests.route_c_stage2_6_0a.conftest import run_cli


def test_legacy_checkpoint_rejected(sealed_exam_env, tmp_path):
    """legacy 工程证据 checkpoint -> CLI EXAM_INVALID。"""
    legacy = tmp_path / "legacy.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], legacy)
    sc = legacy.with_name(legacy.name + ".rl_manifest.json")
    if sc.exists():
        sc.unlink()
    m = mark_legacy_engineering_evidence(legacy, note="2.5 smoke")
    assert m["formal_eligible"] is False
    assert is_formal_eligible(m) is False
    env = dict(sealed_exam_env)
    env["checkpoint"] = legacy
    rc = run_cli(env, "out.json")
    assert rc == 5
    out = json.loads((sealed_exam_env["tmp"] / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_charter_only_sidecar_rejected(sealed_exam_env, tmp_path):
    """v2 但缺 observation 绑定(仅 charter)-> is_formal_eligible=False
    -> CLI EXAM_INVALID。"""
    ckpt = tmp_path / "charter_only.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(ckpt, checkpoint_name="charter_only",
                             charter_hash=sealed_exam_env["commitment"]
                             .charter_hash)
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5


def test_v1_sidecar_from_2_6_0_rejected(sealed_exam_env, tmp_path):
    """阶段 2.6.0 的 v1 sidecar(即使 formal_eligible=true)-> 拒绝。"""
    ckpt = tmp_path / "old_v1.zip"
    shutil.copyfile(sealed_exam_env["checkpoint"], ckpt)
    save_checkpoint_manifest(ckpt, checkpoint_name="old",
                             charter_hash=sealed_exam_env["commitment"]
                             .charter_hash,
                             observation_schema=probe_observation_schema())
    sc = ckpt.with_name(ckpt.name + ".rl_manifest.json")
    m = json.loads(sc.read_text())
    m["schema"] = "checkpoint-manifest-v1"
    m.pop("observation_schema_hash", None)
    sc.write_text(json.dumps(m))
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    manifest = load_checkpoint_manifest(ckpt)
    assert is_formal_eligible(manifest) is False
    env = dict(sealed_exam_env)
    env["checkpoint"] = ckpt
    rc = run_cli(env, "out.json")
    assert rc == 5


def test_smoke_only_checkpoint_not_formal():
    """smoke-only 语义在 sidecar 字段层可表达且被 is_formal_eligible 排除。"""
    fake = {"schema": "checkpoint-manifest-v2",
            "legacy_engineering_evidence": False,
            "formal_eligible": False, "charter_hash": "c-x"}
    assert is_formal_eligible(fake) is False
