"""checkpoint sidecar manifest 与版本兼容守卫(阶段 2.6.0 工作包 0)。

规则:
- 每个正式 checkpoint 旁必须存在 sidecar manifest(<name>.rl_manifest.json),
  记录冻结规范版本、课程章程哈希、创建信息;
- 模型加载时检查环境、观察和动作版本;不兼容 checkpoint 必须拒绝加载,
  而不是勉强恢复;
- 评估器必须拒绝课程章程哈希不匹配的 checkpoint;
- 阶段 2.5 的旧 smoke checkpoint 无 sidecar(无版本证据),默认拒绝;
  可显式标记为 legacy 工程证据(mark_legacy_engineering_evidence),
  仅用于接口验证,不作为正式评估或迁移模型(formal_eligible=False)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_platform.versions import (
    CHECKPOINT_REQUIRED_VERSIONS,
    SpecVersionMismatchError,
    assert_versions_compatible,
    spec_versions,
)

SIDECAR_SUFFIX = ".rl_manifest.json"
MANIFEST_SCHEMA_VERSION = "checkpoint-manifest-v1"


class CheckpointCompatibilityError(RuntimeError):
    """checkpoint 缺少/违背兼容性证据(fail closed)。"""


def sidecar_path(checkpoint_path) -> Path:
    p = Path(checkpoint_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def save_checkpoint_manifest(
    checkpoint_path,
    *,
    checkpoint_name: str,
    charter_hash: str | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """为 checkpoint 写 sidecar manifest(训练保存路径调用)。"""
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA_VERSION,
        "checkpoint_name": checkpoint_name,
        "checkpoint_path": str(checkpoint_path),
        "checkpoint_sha256": sha256_file(checkpoint_path),
        "spec_versions": spec_versions(),
        "charter_hash": charter_hash,
        "formal_eligible": charter_hash is not None,
        "legacy_engineering_evidence": False,
    }
    if extra:
        manifest["extra"] = extra
    sidecar_path(checkpoint_path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def mark_legacy_engineering_evidence(
    checkpoint_path, *, note: str
) -> dict[str, Any]:
    """将阶段 2.5 旧 smoke checkpoint 标记为工程证据(不作为正式迁移模型)。

    legacy 标记的 checkpoint 允许加载做接口验证,但 formal_eligible=False:
    不得进入正式评估、正式毕业判断或 Warm Start 迁移。
    """
    p = Path(checkpoint_path)
    if not p.is_file():
        raise CheckpointCompatibilityError(f"checkpoint 不存在: {p}")
    manifest: dict[str, Any] = {
        "schema": MANIFEST_SCHEMA_VERSION,
        "checkpoint_name": p.stem,
        "checkpoint_path": str(p),
        "checkpoint_sha256": sha256_file(p),
        "spec_versions": "pre-2.6.0(创建时未冻结版本,无法证明兼容)",
        "charter_hash": None,
        "formal_eligible": False,
        "legacy_engineering_evidence": True,
        "legacy_note": note,
    }
    sidecar_path(p).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return manifest


def load_checkpoint_manifest(checkpoint_path) -> dict[str, Any]:
    p = Path(checkpoint_path)
    if not p.is_file():
        raise CheckpointCompatibilityError(f"checkpoint 不存在: {p}")
    sc = sidecar_path(p)
    if not sc.is_file():
        raise CheckpointCompatibilityError(
            f"checkpoint 缺少 sidecar manifest {sc.name}:无法证明规范版本兼容,"
            f"拒绝加载(不是勉强恢复)"
        )
    manifest = json.loads(sc.read_text(encoding="utf-8"))
    if manifest.get("schema") != MANIFEST_SCHEMA_VERSION:
        raise CheckpointCompatibilityError(
            f"sidecar schema {manifest.get('schema')!r} != {MANIFEST_SCHEMA_VERSION!r}"
        )
    actual = sha256_file(p)
    if manifest.get("checkpoint_sha256") != actual:
        raise CheckpointCompatibilityError(
            "checkpoint SHA-256 与 sidecar 记录不一致(文件被替换/损坏),拒绝加载"
        )
    return manifest


def assert_checkpoint_compatible(
    manifest: dict[str, Any],
    *,
    expected_charter_hash: str | None = None,
    allow_legacy: bool = False,
) -> None:
    """版本守卫:环境/观察/动作/奖励/执行/终端版本逐项匹配。

    - 正式 checkpoint:spec_versions 必须逐项等于冻结版本;
    - legacy 工程证据(allow_legacy=True):仅允许接口验证,
      formal_eligible=False 且不得声明 charter;
    - expected_charter_hash 给出时必须与 manifest 一致。
    """
    if manifest.get("legacy_engineering_evidence"):
        if not allow_legacy:
            raise CheckpointCompatibilityError(
                "legacy 工程证据 checkpoint 不允许在此上下文加载"
                "(仅接口验证上下文 allow_legacy=True)"
            )
        if expected_charter_hash is not None:
            raise CheckpointCompatibilityError(
                "legacy checkpoint 无章程哈希,不得用于章程绑定的正式评估"
            )
        return
    try:
        assert_versions_compatible(
            manifest.get("spec_versions"),
            CHECKPOINT_REQUIRED_VERSIONS,
            context="checkpoint 守卫",
        )
    except SpecVersionMismatchError as exc:
        raise CheckpointCompatibilityError(str(exc)) from exc
    if expected_charter_hash is not None:
        stored = manifest.get("charter_hash")
        if stored != expected_charter_hash:
            raise CheckpointCompatibilityError(
                f"课程章程哈希不匹配:checkpoint={stored} 评估要求="
                f"{expected_charter_hash};拒绝加载"
            )


def load_guarded_checkpoint(
    checkpoint_path,
    *,
    expected_charter_hash: str | None = None,
    allow_legacy: bool = False,
    device: str = "cpu",
):
    """守卫 + 加载 SB3 模型:返回 (model, manifest)。"""
    from stable_baselines3 import PPO  # 延迟导入(评估脚本可能无 SB3 场景)

    manifest = load_checkpoint_manifest(checkpoint_path)
    assert_checkpoint_compatible(
        manifest, expected_charter_hash=expected_charter_hash,
        allow_legacy=allow_legacy,
    )
    model = PPO.load(str(checkpoint_path), device=device)
    return model, manifest
