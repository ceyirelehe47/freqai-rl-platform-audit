"""阶段 2.6.0b 工作包 G:可信训练来源证明(training attestation)。

2.6.0a 的问题:formal_eligible=true 由训练侧在 checkpoint sidecar 中
自行填写即可生效——sidecar 只能证明"格式兼容",不能证明"训练来源
可信"。本模块建立独立受信签发方机制:

- TrainingAttestation:受控训练 runner 的不可变训练材料摘要,
  Ed25519 签名后成为 checkpoint 的正式资格唯一来源;
- 覆盖:checkpoint SHA-256 / sidecar hash / 训练 manifest hash /
  章程 hash / Observation Schema hash / RouteC 环境版本 / 训练生成器
  与训练包 hash / 训练代码 hash / PPO 完整参数 / 网络架构与参数量 /
  训练预算 / 训练随机种子 / 是否 smoke / 是否允许正式评估 / 签发方
  身份 / 签名时间;
- TrustedIssuerConfig:受信签发公钥指纹 + 允许的训练 runner hash +
  smoke 策略;进入 sealed commitment(G6),评估方不持有私钥;
- 验证:签名有效 + 每一项绑定哈希与实际提交材料逐项相等 + runner
  受信 + smoke 策略一致;任一不符 -> 拒绝(formal_eligible=false)。

本阶段使用临时 mock 密钥验证流程;真实签发私钥永不进入本仓库、
训练 Agent 工作区、环境变量或 checkpoint。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ATTESTATION_PROTOCOL = "training-attestation-v1"
_ATTESTATION_SUFFIX = ".rl_attestation.json"


class AttestationError(RuntimeError):
    """训练 attestation 无效/不完整/不受信(fail closed)。"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def canonical_json(payload: dict[str, Any]) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")


# ---------------------------------------------------------------- 载荷
def build_attestation_payload(
    *,
    checkpoint_sha256: str,
    sidecar_sha256: str,
    training_manifest_sha256: str,
    charter_hash: str,
    observation_schema_hash: str,
    route_c_env_version: str,
    training_generator_hashes: dict[str, str],
    training_pack_hash: str,
    training_code_hash: str,
    ppo_params: dict[str, Any],
    network_architecture: dict[str, Any],
    training_budget: dict[str, Any],
    training_seed: int,
    is_smoke: bool,
    allow_formal_evaluation: bool,
    issuer_id: str,
    training_runner_hash: str,
    issued_utc: str,
) -> dict[str, Any]:
    """构造 attestation 载荷(签名字节 = canonical_json(payload))。"""
    payload = {
        "protocol": ATTESTATION_PROTOCOL,
        "checkpoint_sha256": checkpoint_sha256,
        "sidecar_sha256": sidecar_sha256,
        "training_manifest_sha256": training_manifest_sha256,
        "charter_hash": charter_hash,
        "observation_schema_hash": observation_schema_hash,
        "route_c_env_version": route_c_env_version,
        "training_generator_hashes": dict(training_generator_hashes),
        "training_pack_hash": training_pack_hash,
        "training_code_hash": training_code_hash,
        "ppo_params": dict(ppo_params),
        "network_architecture": dict(network_architecture),
        "training_budget": dict(training_budget),
        "training_seed": int(training_seed),
        "is_smoke": bool(is_smoke),
        "allow_formal_evaluation": bool(allow_formal_evaluation),
        "issuer_id": issuer_id,
        "training_runner_hash": training_runner_hash,
        "issued_utc": issued_utc,
    }
    return payload


def payload_hash(payload: dict[str, Any]) -> str:
    return "ta-" + _sha256_bytes(canonical_json(payload))


# ---------------------------------------------------------------- 签发方
@dataclass(frozen=True)
class Ed25519KeyPair:
    """mock 受信签发密钥对(仅评估方/签发工具持有私钥)。"""

    private_pem: bytes
    public_pem: bytes
    issuer_id: str
    fingerprint: str

    @staticmethod
    def generate(issuer_id: str = "mock-issuer") -> "Ed25519KeyPair":
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey

        key = Ed25519PrivateKey.generate()
        priv = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption())
        pub = key.public_key().public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo)
        return Ed25519KeyPair(
            private_pem=priv, public_pem=pub, issuer_id=issuer_id,
            fingerprint=key_fingerprint(pub))

    def sign(self, payload: dict[str, Any]) -> bytes:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import \
            Ed25519PrivateKey

        key = serialization_load_private(self.private_pem)
        return key.sign(canonical_json(payload))


def serialization_load_private(pem: bytes):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PrivateKey

    key = serialization.load_pem_private_key(pem, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise AttestationError("私钥不是 Ed25519")
    return key


def serialization_load_public(pem: bytes):
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import \
        Ed25519PublicKey

    key = serialization.load_pem_public_key(pem)
    if not isinstance(key, Ed25519PublicKey):
        raise AttestationError("公钥不是 Ed25519")
    return key


def key_fingerprint(public_pem: bytes) -> str:
    return "ik-" + _sha256_bytes(public_pem)


@dataclass(frozen=True)
class TrustedIssuerConfig:
    """受信签发方配置(进入 sealed commitment;评估方只持有公钥)。"""

    issuer_id: str
    public_key_pem: str
    key_fingerprint: str
    required_training_runner_hash: str
    allow_smoke: bool = False
    protocol: str = ATTESTATION_PROTOCOL

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "protocol": self.protocol,
            "issuer_id": self.issuer_id,
            "public_key_pem": self.public_key_pem,
            "key_fingerprint": self.key_fingerprint,
            "required_training_runner_hash": self.required_training_runner_hash,
            "allow_smoke": self.allow_smoke,
        }

    @staticmethod
    def from_keypair(
        keypair: Ed25519KeyPair, *, required_training_runner_hash: str,
        allow_smoke: bool = False,
    ) -> "TrustedIssuerConfig":
        return TrustedIssuerConfig(
            issuer_id=keypair.issuer_id,
            public_key_pem=keypair.public_pem.decode("utf-8"),
            key_fingerprint=keypair.fingerprint,
            required_training_runner_hash=required_training_runner_hash,
            allow_smoke=allow_smoke,
        )


# ------------------------------------------------------------ attestation 文件
def write_attestation(
    path, keypair: Ed25519KeyPair, payload: dict[str, Any],
) -> dict[str, Any]:
    """签发工具:对载荷签名并写出 attestation 文件。"""
    signature = keypair.sign(payload)
    doc = {
        "payload": payload,
        "signature": signature.hex(),
        "public_key_pem": keypair.public_pem.decode("utf-8"),
        "key_fingerprint": keypair.fingerprint,
        "payload_hash": payload_hash(payload),
    }
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(doc, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    return doc


def attestation_path(checkpoint_path) -> Path:
    p = Path(checkpoint_path)
    return p.with_name(p.name + _ATTESTATION_SUFFIX)


def load_attestation(path) -> dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise AttestationError(f"attestation 文件不存在: {p.name}")
    doc = json.loads(p.read_text(encoding="utf-8"))
    payload = doc.get("payload") or {}
    if payload.get("protocol") != ATTESTATION_PROTOCOL:
        raise AttestationError(
            f"attestation 协议 {payload.get('protocol')!r} != "
            f"{ATTESTATION_PROTOCOL!r}(旧版本 attestation 不得被接受)")
    for key in ("payload", "signature", "public_key_pem", "key_fingerprint"):
        if not doc.get(key):
            raise AttestationError(f"attestation 缺少字段 {key!r}")
    if payload_hash(payload) != doc.get("payload_hash"):
        raise AttestationError(
            "attestation payload hash 与文件记录不一致(载荷被篡改)")
    return doc


def verify_attestation(
    doc: dict[str, Any],
    *,
    trusted: TrustedIssuerConfig,
    checkpoint_path: str,
    sidecar_sha256: str,
    training_manifest_sha256: str,
    charter_hash: str,
    observation_schema_hash: str,
) -> dict[str, Any]:
    """正式资格验证(G4/G5):签名 + 逐项绑定 + 受信链。

    任何一项不符 -> AttestationError(调用方映射 EXAM_INVALID 或
    formal_eligible=false)。训练侧自行填写的任何 boolean 不参与判定。
    """
    checks: dict[str, bool] = {}
    problems: list[str] = []

    def check(name: str, ok: bool, message: str) -> None:
        checks[name] = bool(ok)
        if not ok:
            problems.append(message)

    payload = doc["payload"]
    # 1. 签名在受信公钥下有效
    try:
        pub = serialization_load_public(
            trusted.public_key_pem.encode("utf-8"))
        pub.verify(bytes.fromhex(doc["signature"]),
                   canonical_json(payload))
        check("signature_valid", True, "")
    except Exception as exc:  # noqa: BLE001
        check("signature_valid", False,
              f"attestation 签名验证失败(未受信密钥或载荷被改): {exc!r}")
    # 2. 公钥指纹/签发方身份与受信配置一致
    check("key_fingerprint_trusted",
          doc.get("key_fingerprint") == trusted.key_fingerprint,
          "attestation 公钥指纹与受信 issuer 不符")
    check("issuer_id_trusted",
          payload.get("issuer_id") == trusted.issuer_id,
          "attestation 签发方身份与受信 issuer 不符")
    # 3. checkpoint 逐字节绑定
    actual_ckpt = _sha256_file(checkpoint_path)
    check("checkpoint_binding",
          payload.get("checkpoint_sha256") == actual_ckpt,
          "attestation 绑定的 checkpoint SHA-256 与实际文件不符"
          "(checkpoint 被替换)")
    # 4. sidecar / 训练 manifest / 章程 / observation 绑定
    check("sidecar_binding",
          payload.get("sidecar_sha256") == sidecar_sha256,
          "attestation 绑定的 sidecar hash 与实际不符(sidecar 被修改)")
    check("training_manifest_binding",
          payload.get("training_manifest_sha256") == training_manifest_sha256,
          "attestation 绑定的训练 manifest hash 与实际不符(被修改)")
    check("charter_binding",
          payload.get("charter_hash") == charter_hash,
          "attestation 绑定的章程 hash 与本次考试章程不符")
    check("observation_binding",
          payload.get("observation_schema_hash") == observation_schema_hash,
          "attestation 绑定的 observation schema hash 与本次考试不符")
    # 5. 环境/训练 runner/smoke 策略
    from rl_platform.versions import ENV_CORE_VERSION

    check("env_version_binding",
          payload.get("route_c_env_version") == ENV_CORE_VERSION,
          "attestation 记录的 RouteC 环境版本与当前冻结版本不符")
    check("training_runner_trusted",
          payload.get("training_runner_hash")
          == trusted.required_training_runner_hash,
          "训练 runner hash 与受信配置要求不符(未授权训练管道)")
    check("smoke_policy",
          (not payload.get("is_smoke")) or trusted.allow_smoke,
          "smoke 模型的 attestation 被用于正式评估(受信配置禁止)")
    check("allow_formal_evaluation",
          bool(payload.get("allow_formal_evaluation")),
          "attestation 未允许该 checkpoint 进入正式评估")
    report = {
        "checks": checks, "problems": problems,
        "payload_hash": payload_hash(payload),
        "pass": not problems,
    }
    if problems:
        raise AttestationError(
            "训练 attestation 验证失败(正式资格拒绝): "
            + "; ".join(problems))
    return report


def formal_eligibility_from_attestation(
    *,
    checkpoint_path: str,
    sidecar_manifest: dict[str, Any],
    trusted: TrustedIssuerConfig,
    training_manifest_sha256: str,
    charter_hash: str,
    observation_schema_hash: str,
    attestation_path: str | None = None,
) -> dict[str, Any]:
    """sidecar(format_compatible)+ 受信 attestation -> 正式资格判定。

    sidecar 中自行填写的一切 boolean(含 formal_eligible)被忽略;
    正式资格 = attestation 验证通过(G1/G4)。
    """
    path = attestation_path or str(
        Path(checkpoint_path).with_name(
            Path(checkpoint_path).name + _ATTESTATION_SUFFIX))
    out: dict[str, Any] = {
        "format_compatible": bool(
            sidecar_manifest.get("schema") == "checkpoint-manifest-v3"),
        "formal_eligible": False,
        "sidecar_self_declared_eligible_ignored": bool(
            sidecar_manifest.get("formal_eligible")),
    }
    try:
        doc = load_attestation(path)
        verify_attestation(
            doc, trusted=trusted, checkpoint_path=checkpoint_path,
            sidecar_sha256=_sha256_file(
                str(Path(checkpoint_path)
                    .with_name(Path(checkpoint_path).name
                               + ".rl_manifest.json"))),
            training_manifest_sha256=training_manifest_sha256,
            charter_hash=charter_hash,
            observation_schema_hash=observation_schema_hash)
    except AttestationError as exc:
        out["formal_eligible"] = False
        out["reason"] = str(exc)
        return out
    out["formal_eligible"] = True
    out["payload_hash"] = payload_hash(doc["payload"])
    return out
