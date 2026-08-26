"""候选侧 checkpoint 守卫(最小运行时自包含实现,阶段 2.6.0b 工作包 C6/G1)。

sidecar manifest v3 语义(阶段 2.6.0b):
- sidecar 只证明 format_compatible(文件 SHA-256 / 冻结规范版本 /
  章程与 observation 绑定);formal_eligible 不再由 sidecar 中的任何
  boolean 决定——正式资格只来自受信签发方签名的 training attestation
  (评估主进程在沙箱外验证;候选运行时根本看不到 attestation)。
- checkpoint 文件被替换(SHA 不符)立即拒绝;
- 冻结规范版本逐项比对,不兼容立即拒绝。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_candidate_runtime.versions import CHECKPOINT_REQUIRED_VERSIONS

SIDECAR_SUFFIX = ".rl_manifest.json"
#: 本运行时可加载的 sidecar schema(阶段 2.6.0b 起 v3;v1/v2 仅存于
#: 历史 artifacts,正式沙箱执行器不接受)
LOADABLE_SCHEMAS = ("checkpoint-manifest-v3",)


class CandidateCheckpointError(RuntimeError):
    """checkpoint 证据不足/被篡改(fail closed,worker 拒绝加载)。"""


def sidecar_path(checkpoint_path) -> Path:
    p = Path(checkpoint_path)
    return p.with_name(p.name + SIDECAR_SUFFIX)


def sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_and_verify_sidecar(
    checkpoint_path,
    *,
    expected_charter_hash: str,
    expected_observation_schema_hash: str,
) -> dict[str, Any]:
    """加载并逐项验证 sidecar;任何不符抛 CandidateCheckpointError。

    只做格式/绑定级验证(format_compatible);不判定 formal_eligible
    (那需要受信 attestation,由评估主进程验证)。
    """
    p = Path(checkpoint_path)
    if not p.is_file():
        raise CandidateCheckpointError(f"checkpoint 不存在: {p}")
    sc = sidecar_path(p)
    if not sc.is_file():
        raise CandidateCheckpointError(
            f"checkpoint 缺少 sidecar manifest: {sc.name}")
    manifest = json.loads(sc.read_text(encoding="utf-8"))
    if manifest.get("schema") not in LOADABLE_SCHEMAS:
        raise CandidateCheckpointError(
            f"sidecar schema {manifest.get('schema')!r} 不在可加载集合 "
            f"{LOADABLE_SCHEMAS}(旧版本 checkpoint 不得进入正式沙箱执行)")
    if manifest.get("checkpoint_sha256") != sha256_file(p):
        raise CandidateCheckpointError(
            "checkpoint SHA-256 与 sidecar 记录不一致(文件被替换/损坏)")
    stored_versions = manifest.get("spec_versions") or {}
    problems = []
    for key, expected in CHECKPOINT_REQUIRED_VERSIONS.items():
        actual = stored_versions.get(key)
        if actual != expected:
            problems.append(f"{key}: checkpoint={actual} 冻结={expected}")
    if problems:
        raise CandidateCheckpointError(
            "规范版本不兼容: " + "; ".join(problems))
    if manifest.get("charter_hash") != expected_charter_hash:
        raise CandidateCheckpointError("charter hash 与评估要求不符")
    if manifest.get("observation_schema_hash") != \
            expected_observation_schema_hash:
        raise CandidateCheckpointError(
            "observation schema hash 与评估要求不符")
    return manifest


def load_candidate_model(checkpoint_path, *, device: str = "cpu"):
    """守卫通过后加载 SB3 PPO 模型(候选运行时的唯一模型入口)。"""
    from stable_baselines3 import PPO

    return PPO.load(str(checkpoint_path), device=device)
