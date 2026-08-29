"""阶段 2.6.0g 收尾:工作包 F 攻击矩阵——BuilderIdentity 自洽重算。

攻击形态是"完全自签":攻击者构造 manifest 并重算 npb-(hash 层
自洽),深层自洽检查必须独立兜底拒绝——

- 文件清单被改但 tree digest 不重放 -> 拒绝;
- file_count 与实际文件数不符 -> 拒绝;
- entrypoint 报告与 staged 文件不一致(source_sha256/外部文件)
  -> 拒绝;
- run_mode 缺失/未注册/与 commitment 不一致 -> 拒绝;
- signature_policy.enforced != True -> 拒绝;
- manifest A + hash B(不自签)/ protocol 不自洽 -> 拒绝;
- public digest 伪造 -> 不影响判定(npb- 才是信任源);
- v3 format -> canonical hash 层直接拒绝。
"""

from __future__ import annotations

import copy

import pytest

from rl_curriculum.builder_identity import (
    BuilderIdentity,
    BuilderIdentityError,
    canonical_builder_manifest_hash,
)


def _resign(manifest, base):
    """完全自签攻击:重算 npb- 保持 hash 层自洽。"""
    return BuilderIdentity(
        manifest=copy.deepcopy(manifest),
        manifest_hash=canonical_builder_manifest_hash(manifest),
        builder_protocol=str(base.builder_protocol),
        public_digest={},
    )


def test_self_consistent_identity_passes(mock_identity):
    from rl_curriculum.builder_identity import require_builder_identity

    out = require_builder_identity(mock_identity, where="test")
    assert out is mock_identity


def test_manifest_hash_mismatch_rejected(mock_identity):
    """manifest A + hash B 攻击(不自签)。"""
    from dataclasses import replace

    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    tampered = replace(mock_identity, manifest_hash="npb-" + "0" * 64)
    with pytest.raises(BuilderIdentityError, match="不自洽"):
        require_builder_identity(tampered, where="test")


def test_protocol_mismatch_rejected(mock_identity):
    """protocol A(identity) + protocol B(manifest) 攻击。"""
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["builder_protocol"] = "null-pack-builder-protocol-v9"
    tampered = BuilderIdentity(
        manifest=manifest,
        manifest_hash=canonical_builder_manifest_hash(manifest),
        builder_protocol=mock_identity.builder_protocol,
        public_digest={},
    )
    with pytest.raises(BuilderIdentityError,
                       match="protocol 不自洽"):
        require_builder_identity(tampered, where="test")


def test_files_changed_tree_hash_unchanged_rejected(mock_identity):
    """文件清单被改但 tree_hash 字段未跟(完全自签)-> digest 重放拒绝。"""
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    files = manifest["package_tree"]["files"]
    files[0]["sha256"] = "0" * 64
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="tree_hash"):
        require_builder_identity(tampered, where="test")


def test_file_count_mismatch_rejected(mock_identity):
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["package_tree"]["file_count"] = \
        len(manifest["package_tree"]["files"]) + 5
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="file_count"):
        require_builder_identity(tampered, where="test")


def test_entrypoint_report_stale_sha_rejected(mock_identity):
    """entrypoint 报告的 source_sha256 与 staged 文件不一致。"""
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["entrypoints_validated"]["entrypoint"][
        "source_sha256"] = "f" * 64
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError,
                       match="source_sha256|不一致"):
        require_builder_identity(tampered, where="test")


def test_entrypoint_report_foreign_file_rejected(mock_identity):
    """报告指向不在文件清单内的 source_file。"""
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["entrypoints_validated"]["entrypoint"][
        "source_file"] = "not_in_tree.py"
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="source_file"):
        require_builder_identity(tampered, where="test")


def test_public_digest_forgery_ignored(mock_identity):
    """public digest 被伪造:npb- 只认 canonical manifest 内容。"""
    from dataclasses import replace

    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    forged = {
        "format": "null-pack-builder-manifest-v5",
        "builder_protocol": "null-pack-builder-protocol-v3",
        "run_mode": "builder_execution",
        "package_tree_hash": "forged",
        "entrypoint_qualname": "totally_different",
    }
    tampered = replace(mock_identity, public_digest=forged)
    out = require_builder_identity(tampered, where="test")
    assert out.manifest_hash == mock_identity.manifest_hash


def test_run_mode_missing_rejected(mock_identity):
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest.pop("run_mode")
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="run_mode"):
        require_builder_identity(tampered, where="test")


def test_run_mode_unregistered_rejected(mock_identity):
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["run_mode"] = "stealth_hybrid"
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="run_mode"):
        require_builder_identity(tampered, where="test")


def test_run_mode_commitment_mismatch_rejected(mock_identity):
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    with pytest.raises(BuilderIdentityError, match="run_mode"):
        require_builder_identity(
            mock_identity, where="test",
            expected_run_mode="builder_execution")


def test_signature_policy_not_enforced_rejected(mock_identity):
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    manifest = copy.deepcopy(mock_identity.manifest)
    manifest["signature_policy"]["enforced"] = False
    tampered = _resign(manifest, mock_identity)
    with pytest.raises(BuilderIdentityError, match="signature_policy"):
        require_builder_identity(tampered, where="test")


def test_none_identity_rejected():
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    with pytest.raises(BuilderIdentityError, match="缺少"):
        require_builder_identity(None, where="test")


def test_bad_type_rejected():
    from rl_curriculum.builder_identity import (
        require_builder_identity,
    )

    with pytest.raises(BuilderIdentityError, match="类型无效"):
        require_builder_identity("not-an-identity", where="test")


def test_old_format_rejected_at_canonical_hash():
    """v3 format 在 canonical hash 层直接拒绝(_build_identity 同)。"""
    with pytest.raises(BuilderIdentityError, match="v4"):
        canonical_builder_manifest_hash(
            {"format": "null-pack-builder-manifest-v3"})
