"""阶段 2.6.0c 工作包 B:候选运行时内容绑定与 staging TOCTOU 防护。

覆盖:
- runtime canonical tree hash(稳定/内容敏感/逐安全关键文件);
- 源 runtime 篡改矩阵(bootstrap 跳过 Landlock/worker 改协议/guard
  跳过 sidecar 检查/增删文件/symlink);
- staging 实际执行副本与承诺逐字节一致;
- launch 前哈希失败(staging 在复制后被替换 -> fail closed);
- 承诺缺 runtime hash 拒绝。
"""

from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path

import pytest

import rl_candidate_runtime
from rl_curriculum.sandbox import (
    CANDIDATE_RUNTIME_MANIFEST_FORMAT,
    REQUIRED_RUNTIME_FILES,
    CandidateSandboxError,
    compute_runtime_manifest,
    runtime_tree_hash,
    verify_staged_runtime,
)

SRC_RUNTIME = Path(rl_candidate_runtime.__file__).parent


@pytest.fixture()
def runtime_copy(tmp_path) -> Path:
    """独立可篡改的运行时副本。"""
    dst = tmp_path / "rl_candidate_runtime"
    dst.mkdir()
    for f in SRC_RUNTIME.rglob("*.py"):
        shutil.copyfile(f, dst / f.name)
    return dst


# ------------------------------------------------------------ manifest 基础
def test_manifest_covers_all_required_files():
    manifest = compute_runtime_manifest()
    assert manifest["format"] == CANDIDATE_RUNTIME_MANIFEST_FORMAT
    files = manifest["files"]
    for name in REQUIRED_RUNTIME_FILES:
        assert name in files, name
    assert manifest["runtime_package_version"].startswith(
        "rl-candidate-runtime-")
    assert manifest["worker_protocol"] == "candidate-worker-v2"


def test_manifest_stable_and_content_sensitive(runtime_copy):
    m1 = compute_runtime_manifest(str(runtime_copy))
    m2 = compute_runtime_manifest(str(runtime_copy))
    assert m1 == m2
    assert runtime_tree_hash(m1) == runtime_tree_hash(m2)
    # 任一安全关键文件单字节变化 -> tree hash 变化
    for name in REQUIRED_RUNTIME_FILES:
        target = runtime_copy / name
        original = target.read_bytes()
        target.write_bytes(original + b"\n# tampered\n")
        m_tampered = compute_runtime_manifest(str(runtime_copy))
        assert runtime_tree_hash(m_tampered) != runtime_tree_hash(m1), name
        target.write_bytes(original)


def test_manifest_rejects_missing_required_file(runtime_copy):
    (runtime_copy / "versions.py").unlink()
    with pytest.raises(CandidateSandboxError, match="缺少必备文件"):
        compute_runtime_manifest(str(runtime_copy))


def test_manifest_rejects_symlink(runtime_copy):
    (runtime_copy / "worker.py").unlink()
    (runtime_copy / "worker.py").symlink_to(SRC_RUNTIME / "worker.py")
    with pytest.raises(CandidateSandboxError, match="符号链接"):
        compute_runtime_manifest(str(runtime_copy))


def test_extra_files_enter_manifest_not_silently_ignored(runtime_copy):
    """额外可执行 helper 进入 manifest(旧承诺因此失效,不被忽略)。"""
    m_before = compute_runtime_manifest(str(runtime_copy))
    (runtime_copy / "evil_helper.py").write_text(
        "import os\nos.system('true')\n", encoding="utf-8")
    m_after = compute_runtime_manifest(str(runtime_copy))
    assert "evil_helper.py" in m_after["files"]
    assert runtime_tree_hash(m_after) != runtime_tree_hash(m_before)
    # 旧 manifest 与新增文件后的目录不再匹配
    with pytest.raises(CandidateSandboxError, match="额外文件"):
        verify_staged_runtime(runtime_copy, m_before)


# ------------------------------------------------------- 源篡改矩阵(B3/B4)
def test_bootstrap_landlock_skip_tamper_invalidates(runtime_copy):
    """bootstrap 跳过 Landlock 的篡改使旧 manifest/承诺失效。"""
    m_before = compute_runtime_manifest(str(runtime_copy))
    src = (runtime_copy / "bootstrap.py").read_text(encoding="utf-8")
    tampered = src.replace("apply_landlock(", "print('skip',  # apply_landlock(")
    if tampered == src:  # 名称变化兜底:直接追加替换实现
        tampered = src + "\napply_landlock = lambda *a, **k: None\n"
    (runtime_copy / "bootstrap.py").write_text(tampered, encoding="utf-8")
    m_after = compute_runtime_manifest(str(runtime_copy))
    assert (m_after["files"]["bootstrap.py"]
            != m_before["files"]["bootstrap.py"])
    assert runtime_tree_hash(m_after) != runtime_tree_hash(m_before)
    with pytest.raises(CandidateSandboxError):
        verify_staged_runtime(runtime_copy, m_before)


def test_worker_protocol_tamper_invalidates(runtime_copy):
    """worker 修改 reset/act 协议使旧 manifest 失效。"""
    m_before = compute_runtime_manifest(str(runtime_copy))
    src = (runtime_copy / "worker.py").read_text(encoding="utf-8")
    assert '{"op": "reset"}' in src
    (runtime_copy / "worker.py").write_text(
        src.replace('{"op": "reset"}', '{"op": "reset", "seed": 1}'),
        encoding="utf-8")
    m_after = compute_runtime_manifest(str(runtime_copy))
    assert runtime_tree_hash(m_after) != runtime_tree_hash(m_before)


def test_guard_sidecar_skip_tamper_invalidates(runtime_copy):
    """guard 跳过 sidecar 检查使旧 manifest 失效。"""
    m_before = compute_runtime_manifest(str(runtime_copy))
    src = (runtime_copy / "guard.py").read_text(encoding="utf-8")
    (runtime_copy / "guard.py").write_text(
        src + "\nload_and_verify_sidecar = load_candidate_model  # 短路\n",
        encoding="utf-8")
    m_after = compute_runtime_manifest(str(runtime_copy))
    assert runtime_tree_hash(m_after) != runtime_tree_hash(m_before)


def test_runtime_package_version_change_invalidates():
    """runtime 协议版本字段被 manifest 绑定:版本变化 -> tree hash 变化。"""
    m = compute_runtime_manifest()
    m2 = copy.deepcopy(m)
    m2["runtime_package_version"] = "rl-candidate-runtime-tampered"
    assert runtime_tree_hash(m2) != runtime_tree_hash(m)


def test_deleted_runtime_file_invalidates(runtime_copy):
    m_before = compute_runtime_manifest(str(runtime_copy))
    (runtime_copy / "guard.py").unlink()
    # 缺必备文件直接拒绝构建 manifest;相对旧 manifest 的 staging 校验
    # 同样 fail closed
    with pytest.raises(CandidateSandboxError):
        compute_runtime_manifest(str(runtime_copy))
    with pytest.raises(CandidateSandboxError, match="缺失文件"):
        verify_staged_runtime(runtime_copy, m_before)


def test_runtime_symlink_replacement_rejected(runtime_copy):
    """runtime 文件被符号链接替换 -> staging 验证拒绝。"""
    m = compute_runtime_manifest(str(runtime_copy))
    (runtime_copy / "guard.py").unlink()
    (runtime_copy / "guard.py").symlink_to(SRC_RUNTIME / "guard.py")
    with pytest.raises(CandidateSandboxError, match="符号链接"):
        verify_staged_runtime(runtime_copy, m)


# --------------------------------------------------- staging 集成(B2/TOCTOU)
def test_staged_runtime_matches_source_bytes(tmp_path):
    """正常复制:staging 副本与源 manifest 逐字节一致(验证通过)。"""
    from rl_curriculum.sandbox import assemble_runtime_staging

    staging = assemble_runtime_staging(str(tmp_path / "runtime"))
    verify_staged_runtime(
        Path(staging) / "rl_candidate_runtime", compute_runtime_manifest())


def test_launch_fails_when_staging_replaced_before_launch(
        tmp_path, sandbox_checkpoint, monkeypatch, schema):
    """TOCTOU:staging 在复制完成后、启动前被替换 -> fail closed,
    候选 worker 永远不被加载。"""
    import rl_curriculum.sandbox as sandbox_mod

    real_assemble = sandbox_mod.assemble_runtime_staging
    real_manifest = compute_runtime_manifest()

    def tampering_assemble(dest_dir, **kw):
        staging = real_assemble(dest_dir, **kw)
        # 复制完成后、launch 之前:替换 staging 内的 worker.py
        victim = Path(staging) / "rl_candidate_runtime" / "worker.py"
        victim.write_bytes(victim.read_bytes() + b"\n# replaced\n")
        return staging

    monkeypatch.setattr(sandbox_mod, "assemble_runtime_staging",
                        tampering_assemble)
    with pytest.raises(CandidateSandboxError, match="TOCTOU|不一致"):
        sandbox_mod.launch_sandboxed(
            sandbox_mod.default_sandbox_profile(),
            checkpoint_path=sandbox_checkpoint,
            exec_argv=["/usr/bin/python3", "-m",
                       "rl_candidate_runtime.worker", "__CHECKPOINT__",
                       "c-x", "o-x"],
            exec_env={},
            staging_dir=tmp_path / "runtime",
            expected_runtime_manifest=real_manifest)


def test_launch_fails_when_staging_file_removed(
        tmp_path, sandbox_checkpoint, monkeypatch):
    """staging 文件被删除 -> 同样 fail closed。"""
    import rl_curriculum.sandbox as sandbox_mod

    real_assemble = sandbox_mod.assemble_runtime_staging
    real_manifest = compute_runtime_manifest()

    def deleting_assemble(dest_dir, **kw):
        staging = real_assemble(dest_dir, **kw)
        (Path(staging) / "rl_candidate_runtime" / "guard.py").unlink()
        return staging

    monkeypatch.setattr(sandbox_mod, "assemble_runtime_staging",
                        deleting_assemble)
    with pytest.raises(CandidateSandboxError):
        sandbox_mod.launch_sandboxed(
            sandbox_mod.default_sandbox_profile(),
            checkpoint_path=sandbox_checkpoint,
            exec_argv=["/usr/bin/python3", "-m",
                       "rl_candidate_runtime.worker", "__CHECKPOINT__",
                       "c-x", "o-x"],
            exec_env={},
            staging_dir=tmp_path / "runtime",
            expected_runtime_manifest=real_manifest)


def test_commitment_binds_runtime_tree(sealed_exam_env):
    """承诺包含 runtime manifest 与 tree hash,且与当前源一致。"""
    env = sealed_exam_env
    manifest = env["commitment"].candidate_runtime_manifest
    assert manifest["format"] == CANDIDATE_RUNTIME_MANIFEST_FORMAT
    assert env["commitment"].candidate_runtime_hash == \
        runtime_tree_hash(manifest)
    assert manifest == compute_runtime_manifest()


def test_commitment_without_runtime_hash_rejected(sealed_exam_env):
    """缺 runtime hash 的承诺(v2 形态)不得进入 v3 执行器。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    payload = json.loads(sealed_exam_env["commitment"].to_json())
    del payload["candidate_runtime_manifest"]
    del payload["candidate_runtime_hash"]
    with pytest.raises(SealedExamError,
                       match="候选运行时内容|runtime"):
        SealedExamCommitment.from_json(json.dumps(payload))


def test_runtime_tamper_fails_sealed_verification(
        sealed_exam_env, runtime_copy, monkeypatch):
    """源 runtime 被篡改(改 bootstrap.py)后,旧承诺的 sealed 验证失败
    (candidate_runtime_manifest check fail closed)。"""
    import rl_curriculum.sandbox as sandbox_mod

    from rl_curriculum.sealed_exam import SealedExamError

    (runtime_copy / "bootstrap.py").write_text(
        (runtime_copy / "bootstrap.py").read_text(encoding="utf-8")
        + "\n# tampered\n", encoding="utf-8")
    tampered_manifest = compute_runtime_manifest(str(runtime_copy))

    original_compute = sandbox_mod.compute_runtime_manifest

    def compute_from_tampered(source_dir=None):
        return original_compute(str(runtime_copy))

    # verify_sealed_commitment 在函数内从 sandbox 模块局部导入,
    # 必须补丁 sandbox 模块本身
    monkeypatch.setattr(sandbox_mod, "compute_runtime_manifest",
                        compute_from_tampered)
    # 承诺保持原样(绑定未篡改的 manifest):当前源已被篡改 ->
    # candidate_runtime_manifest 检查失败 -> 旧承诺失效
    env = sealed_exam_env
    assert env["commitment"].candidate_runtime_manifest != tampered_manifest
    from rl_curriculum.charter import validate_charter
    from rl_curriculum.sealed_exam import verify_sealed_commitment

    with pytest.raises(SealedExamError, match="候选运行时"):
        verify_sealed_commitment(
            env["commitment"], pack=env["pack"],
            charter=validate_charter(env["charter"]),
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"],
            verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"], **__import__('compat_stage2_6_0f', fromlist=['verify_kwargs']).verify_kwargs())
