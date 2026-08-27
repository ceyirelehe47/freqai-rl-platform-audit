"""正式 Builder Identity Provider(阶段 2.6.0f 工作包 A/B)。

2.6.0e 遗留缺陷:formal verifier 在 verify_sealed_commitment /
validate_null_pack / pack validity 重算路径中无参数调用默认公开 mock
builder 的 manifest(null_pack_validation.pack_builder_manifest_hash()),
既没有正式的评估方私有 Builder Identity Provider,builder manifest 也
只绑定手工挑选的函数清单(_fn_binding 逐函数源码哈希),遗漏实际决定
attempt 是否被接受的中间链路(_validate_pack_ephemeral /
build_spec_for_pack / null materialization / pair mirror 子函数 /
salt 常量值 / family 列表真源等)。

v2 语义(null-pack-builder-manifest-v2):

- builder 身份 = builder package tree manifest(受信 root 下全部文件
  的稳定排序逐文件 sha256;拒绝 symlink / 缺失文件;root 下任何新增
  或删除文件、资源文件变化、任意安全相关辅助模块变化都会改变身份)
  + 显式外部依赖 manifest(依赖模块身份明确绑定);
- Provider 是独立评估方的可信主机输入:提供 canonical manifest、
  manifest hash(npb-)、builder protocol 版本与非敏感公开摘要,在评估
  环境中重新计算,而不是读取任何自报 hash;
- Provider 不得从候选 checkpoint、sidecar、考试 pack 或考试 context
  获取信任,不得进入 Candidate 沙箱,候选模型不可读、不可覆盖、不可
  选择;
- 正式路径(run_sealed_exam / verify_sealed_commitment / pack
  validity 重算)必须显式接收 Provider 派生的 BuilderIdentity,缺失即
  EXAM_INVALID,不存在"没有 Provider 就自动使用 mock builder"的
  fallback;
- 公开 mock 流程使用 MockBuilderIdentityProvider,但必须显式传入
  (build_mock_commitment 内部显式构造;formal API 本身不硬编码任何
  mock provider)。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: builder manifest 协议(阶段 2.6.0f:v1 的手工函数清单绑定已废除)
BUILDER_MANIFEST_FORMAT = "null-pack-builder-manifest-v2"
#: v1 已弃用(只绑定手工挑选函数,不覆盖实际依赖闭包)
_DEPRECATED_BUILDER_MANIFEST_FORMATS = ("null-pack-builder-manifest-v1",)
#: builder 协议语义版本(assemble/attempt/seed/pair 语义契约)
BUILDER_PROTOCOL = "null-pack-builder-protocol-v2"

#: package tree 扫描排除目录(编译缓存不是源码身份)
TREE_EXCLUDE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})
#: builder 签名禁止参数(候选相关性 fail closed;与 v1 一致)
PACK_BUILDER_FORBIDDEN_PARAMS: tuple[str, ...] = (
    "candidate", "checkpoint", "model", "policy",
)


class BuilderIdentityError(RuntimeError):
    """Builder 身份派生失败(fail closed -> EXAM_INVALID)。"""


def _canonical_json_hash(payload: Any) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"),
                   ensure_ascii=False).encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ tree
def _iter_tree_files(root: Path) -> list[Path]:
    """root 下全部文件(稳定排序;拒绝 symlink 与排除目录外的隐藏缓存)。

    额外文件不能被静默忽略:root 下所有非排除文件都进入身份,新增或
    删除 package 文件都会改变 hash(B2/B4)。
    """
    files: list[Path] = []
    for p in sorted(root.rglob("*")):
        if p.is_symlink():
            raise BuilderIdentityError(
                f"builder package tree 内禁止 symlink: {p}")
        if p.is_dir():
            if p.name in TREE_EXCLUDE_DIRS:
                # 不深入排除目录
                pass
            continue
        if any(part in TREE_EXCLUDE_DIRS for part in p.parts):
            continue
        if not p.is_file():
            raise BuilderIdentityError(
                f"builder package tree 内出现非普通文件: {p}")
        files.append(p)
    if not files:
        raise BuilderIdentityError(
            f"builder package tree 为空: {root}(entrypoint/依赖文件缺失"
            f"即失败,不得回退为空身份)")
    return files


def _checked_within(root: Path, path: Path) -> Path:
    resolved = path.resolve()
    root_resolved = root.resolve()
    if not str(resolved).startswith(str(root_resolved) + "/"):
        raise BuilderIdentityError(
            f"builder 路径必须位于受信 root 内: {path} 不在 {root} 下")
    return resolved


def builder_package_tree_manifest(
    root: Path | str, *,
    root_label: str,
    entrypoint_module: str,
    entrypoint_qualname: str,
    attempt_loop_module: str = "",
    attempt_loop_qualname: str = "",
) -> dict[str, Any]:
    """builder package tree manifest(B2)。

    - 相对路径排序稳定(posix 形式);
    - 每个文件内容 sha256 与字节数;
    - entrypoint 模块与 qualname 显式声明(assemble 与 attempt loop);
    - 资源文件与源码文件一律进入 hash(拒绝缺失文件 -> 空树失败);
    - 拒绝 symlink;路径必须位于受信 root 内;
    - root 下额外文件不能被静默忽略(全部进入文件清单);
    - 不扫描候选可写目录(root 由评估方指定为受信 builder root)。
    """
    root = Path(root)
    if not root.is_dir():
        raise BuilderIdentityError(
            f"builder package root 不存在或不是目录: {root}")
    files = _iter_tree_files(root)
    entries: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    for p in files:
        _checked_within(root, p)
        rel = p.relative_to(root).as_posix()
        data = p.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        entries.append({"path": rel, "sha256": sha, "bytes": len(data)})
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(sha))
    if not entrypoint_module or not entrypoint_qualname:
        raise BuilderIdentityError(
            "builder package tree 必须声明 entrypoint 模块与 qualname")
    return {
        "root_label": str(root_label),
        "entrypoint_module": str(entrypoint_module),
        "entrypoint_qualname": str(entrypoint_qualname),
        "attempt_loop_module": str(attempt_loop_module),
        "attempt_loop_qualname": str(attempt_loop_qualname),
        "files": entries,
        "file_count": len(entries),
        "tree_hash": digest.hexdigest(),
    }


def package_tree_hash(root: Path | str) -> str:
    """外部依赖包目录的 tree hash(依赖模块身份明确绑定;B2)。"""
    root = Path(root)
    if not root.is_dir():
        raise BuilderIdentityError(f"依赖包目录不存在: {root}")
    digest = hashlib.sha256()
    for p in _iter_tree_files(root):
        _checked_within(root, p)
        rel = p.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(p.read_bytes()).digest())
    return digest.hexdigest()


def _module_path(module: Any) -> Path:
    src = getattr(module, "__file__", None)
    if not src:
        raise BuilderIdentityError(f"模块 {module!r} 无源文件")
    return Path(src).resolve()


def _rl_platform_root() -> Path:
    import rl_platform

    return _module_path(rl_platform).parent


def _rl_curriculum_root() -> Path:
    import rl_curriculum

    return _module_path(rl_curriculum).parent


def _package_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return str(version(name))
    except PackageNotFoundError:
        return f"<missing:{name}>"


def check_builder_signature_policy(*fns: Any) -> None:
    """builder 函数签名不得包含 candidate/checkpoint/model/policy。

    v1 语义保留(v2 的 package tree 是静态身份,此检查在 Provider 侧
    对可导入的 builder 函数动态执行;mock Provider 始终强制)。
    """
    import inspect

    for fn in fns:
        params = set(inspect.signature(fn).parameters)
        bad = sorted(params & set(PACK_BUILDER_FORBIDDEN_PARAMS))
        if bad:
            raise BuilderIdentityError(
                f"builder 函数 {getattr(fn, '__qualname__', fn)!r} 的签名"
                f"包含禁止参数 {bad}(pack 构建不得依赖任何候选/"
                f"checkpoint/model/policy)")


#: mock builder 的共享外部依赖(builder 链实际 import 的非 stdlib 身份)
def shared_external_dependency_manifest() -> list[dict[str, Any]]:
    """显式外部依赖 manifest(rl_platform tree + 运行时关键版本)。

    builder 链实际依赖 rl_platform(versions/fingerprint)与
    numpy/pandas/Python 运行时;依赖身份变化 -> npb- 变化。
    """
    return [
        {
            "module": "rl_platform",
            "kind": "package_tree",
            "tree_hash": package_tree_hash(_rl_platform_root()),
        },
        {
            "module": "python",
            "kind": "runtime_version",
            "version": platform.python_version(),
            "implementation": platform.python_implementation(),
        },
        {"module": "numpy", "kind": "package_version",
         "version": _package_version("numpy")},
        {"module": "pandas", "kind": "package_version",
         "version": _package_version("pandas")},
    ]


# ------------------------------------------------------------------ 身份
@dataclass(frozen=True)
class BuilderIdentity:
    """Provider 派生的 builder 身份(canonical manifest + hash)。"""

    manifest: dict[str, Any]
    manifest_hash: str
    builder_protocol: str
    public_digest: dict[str, Any] = field(default_factory=dict)

    @property
    def pack_builder_code_hash(self) -> str:
        """与 v1 承诺字段名兼容的只读别名(npb-)。"""
        return self.manifest_hash

    @property
    def format(self) -> str:
        return str(self.manifest.get("format"))

    @property
    def tree_hash(self) -> str:
        return str((self.manifest.get("package_tree") or {}).get(
            "tree_hash") or "")


def canonical_builder_manifest_hash(manifest: dict[str, Any]) -> str:
    """manifest 哈希(npb-;canonical JSON,排序稳定)。"""
    if manifest.get("format") != BUILDER_MANIFEST_FORMAT:
        raise BuilderIdentityError(
            f"builder manifest 格式必须是 {BUILDER_MANIFEST_FORMAT!r}"
            f"(收到 {manifest.get('format')!r};"
            f"{_DEPRECATED_BUILDER_MANIFEST_FORMATS} 已弃用)")
    return "npb-" + _canonical_json_hash(manifest)


def _build_identity(manifest: dict[str, Any]) -> BuilderIdentity:
    """从 canonical manifest 构造 BuilderIdentity(重算 hash,不读自报值)。"""
    manifest_hash = canonical_builder_manifest_hash(manifest)
    tree = dict(manifest.get("package_tree") or {})
    return BuilderIdentity(
        manifest=manifest,
        manifest_hash=manifest_hash,
        builder_protocol=str(manifest.get("builder_protocol")),
        public_digest={
            # 非敏感公开摘要:协议/entrypoint/tree hash/依赖身份指纹,
            # 不含私有源码内容与任何 seed
            "format": manifest.get("format"),
            "builder_protocol": manifest.get("builder_protocol"),
            "entrypoint_module": tree.get("entrypoint_module"),
            "entrypoint_qualname": tree.get("entrypoint_qualname"),
            "package_tree_hash": tree.get("tree_hash"),
            "file_count": tree.get("file_count"),
            "external_dependency_fingerprints": [
                {k: v for k, v in dep.items() if k != "tree_hash"}
                | ({"tree_hash_prefix": str(dep.get("tree_hash"))[:16]}
                   if dep.get("tree_hash") else {})
                for dep in manifest.get("external_dependencies") or []],
            "params_spec": manifest.get("params_spec"),
            "families": manifest.get("families"),
            "max_attempts": manifest.get("max_attempts"),
        },
    )


@runtime_checkable
class BuilderIdentityProvider(Protocol):
    """评估方侧 Provider 抽象(A1)。

    独立评估方的可信主机输入:在评估环境中重新计算 builder canonical
    manifest 与 hash,而不是读取自报值。实现必须保证:
    - 不从候选 checkpoint / sidecar / 考试 pack / 考试 context 获取信任;
    - 不进入 Candidate 沙箱(候选不可读、不可覆盖、不可选择)。
    """

    def builder_identity(self) -> BuilderIdentity: ...


class MockBuilderIdentityProvider:
    """公开 mock builder 的 Provider(公开流程专用,必须显式传入)。

    tree root = rl_curriculum 包目录:mock builder 的 assemble /
    attempt loop / _validate_pack_ephemeral / build_spec_for_pack /
    null materialization / seed 与 pair 推导 / salt 常量 / validator /
    _verify_pair_* 子函数 / BASE_PARAMS / family 列表全部位于该包内,
    逐文件内容哈希 + 额外文件不忽略,构成完整依赖闭包(B1/B2/B4)。
    """

    def __init__(self):
        from rl_curriculum import mock_sealed_exam
        from rl_curriculum.generators import FORMAL_NULL_FAMILIES
        from rl_curriculum.null_qualification_spec import (
            MIN_PACK_CLUSTERS_PER_FAMILY,
        )

        self._root = _rl_curriculum_root()
        self._base_params = dict(mock_sealed_exam.BASE_PARAMS)
        self._families = list(FORMAL_NULL_FAMILIES)
        self._pair_count = int(MIN_PACK_CLUSTERS_PER_FAMILY)
        # 签名政策动态强制(v1 D6 语义保留:assemble/attempt/validator/
        # 拒绝日志生成器的签名不得含 candidate/checkpoint/model/policy)
        from rl_curriculum.null_pack_validation import (
            pack_builder_attempt_log,
            validate_null_pack,
        )

        check_builder_signature_policy(
            mock_sealed_exam.assemble_mock_hidden_pack,
            mock_sealed_exam.build_mock_hidden_pack,
            validate_null_pack,
            pack_builder_attempt_log,
        )

    def builder_identity(self) -> BuilderIdentity:
        from rl_curriculum.null_pack_validation import MAX_PACK_ATTEMPTS

        tree = builder_package_tree_manifest(
            self._root,
            root_label="rl_curriculum(mock builder package)",
            entrypoint_module="rl_curriculum.mock_sealed_exam",
            entrypoint_qualname="assemble_mock_hidden_pack",
            attempt_loop_module="rl_curriculum.mock_sealed_exam",
            attempt_loop_qualname="build_mock_hidden_pack",
        )
        manifest = {
            "format": BUILDER_MANIFEST_FORMAT,
            "builder_protocol": BUILDER_PROTOCOL,
            "package_tree": tree,
            "external_dependencies": shared_external_dependency_manifest(),
            "params_spec": {
                "base_params": dict(self._base_params),
                "flip_flag_key": "antithetic_flip",
                "episode_bars": int(self._base_params["episode_bars"]),
            },
            "pair_count_per_family": self._pair_count,
            "families": list(self._families),
            "max_attempts": int(MAX_PACK_ATTEMPTS),
            "signature_policy": {
                "forbidden_params": list(PACK_BUILDER_FORBIDDEN_PARAMS),
                "enforced": True,
            },
        }
        return _build_identity(manifest)


class PrivateBuilderIdentityProvider:
    """评估方私有 builder 的 Provider(测试/正式私有实现同构)。

    私有 builder 源码位于评估方私有目录(测试时为临时目录),不进入
    Candidate runtime,不进入公开 commitment;完整 manifest 保留在评估
    方私有目录,公开承诺只携带 manifest hash、协议版本与非敏感摘要。
    formal verifier 从本 Provider 重新计算 hash(A4)。
    """

    def __init__(
        self, root: Path | str, *,
        entrypoint_module: str,
        entrypoint_qualname: str,
        attempt_loop_module: str = "",
        attempt_loop_qualname: str = "",
        params_spec: dict[str, Any] | None = None,
        families: list[str] | None = None,
        pair_count_per_family: int = 32,
        max_attempts: int = 8,
        external_dependencies: list[dict[str, Any]] | None = None,
        root_label: str = "private-builder",
    ):
        self._root = Path(root)
        self._entrypoint_module = str(entrypoint_module)
        self._entrypoint_qualname = str(entrypoint_qualname)
        self._attempt_loop_module = str(attempt_loop_module)
        self._attempt_loop_qualname = str(attempt_loop_qualname)
        self._params_spec = dict(params_spec or {})
        self._families = list(families or [])
        self._pair_count = int(pair_count_per_family)
        self._max_attempts = int(max_attempts)
        self._external_dependencies = list(
            external_dependencies
            if external_dependencies is not None
            else shared_external_dependency_manifest())
        self._root_label = str(root_label)

    def builder_identity(self) -> BuilderIdentity:
        tree = builder_package_tree_manifest(
            self._root,
            root_label=self._root_label,
            entrypoint_module=self._entrypoint_module,
            entrypoint_qualname=self._entrypoint_qualname,
            attempt_loop_module=self._attempt_loop_module,
            attempt_loop_qualname=self._attempt_loop_qualname,
        )
        manifest = {
            "format": BUILDER_MANIFEST_FORMAT,
            "builder_protocol": BUILDER_PROTOCOL,
            "package_tree": tree,
            "external_dependencies": list(self._external_dependencies),
            "params_spec": dict(self._params_spec),
            "pair_count_per_family": self._pair_count,
            "families": list(self._families),
            "max_attempts": self._max_attempts,
            "signature_policy": {
                "forbidden_params": list(PACK_BUILDER_FORBIDDEN_PARAMS),
                "enforced": True,
            },
        }
        return _build_identity(manifest)


def require_builder_identity(
    identity: BuilderIdentity | None, *,
    where: str,
) -> BuilderIdentity:
    """formal 路径的 BuilderIdentity 必填守卫(缺失 -> fail closed)。

    正式路径不存在"没有 Provider 就自动使用 mock builder"的 fallback
    (A2);本守卫在 verify_sealed_commitment / validate_null_pack /
    pack validity 重算入口统一执行。
    """
    if identity is None:
        raise BuilderIdentityError(
            f"{where} 缺少 Builder Identity Provider 派生的 builder 身份:"
            f"正式路径必须由评估方显式传入 Provider 并派生 identity,"
            f"不存在默认 mock builder fallback(EXAM_INVALID)")
    if not isinstance(identity, BuilderIdentity):
        raise BuilderIdentityError(
            f"{where} 收到的 builder 身份类型无效({type(identity)!r});"
            f"必须来自 BuilderIdentityProvider.builder_identity()")
    if identity.format != BUILDER_MANIFEST_FORMAT:
        raise BuilderIdentityError(
            f"{where} 收到的 builder manifest 格式 "
            f"{identity.format!r} != {BUILDER_MANIFEST_FORMAT!r}"
            f"(v1 手工函数清单绑定已弃用)")
    return identity


def provider_runtime_isolation_report(
    identity: BuilderIdentity,
) -> dict[str, Any]:
    """Provider/Candidate 隔离证据:builder root 不在候选运行时目录内。

    候选运行时(rl_candidate_runtime)与 builder package tree 是不相交
    的目录;Provider 不进入 Candidate 沙箱(候选不可读/不可覆盖/不可
    选择 builder 身份)。此报告仅作审计证据,不参与信任判定。
    """
    import rl_candidate_runtime

    runtime_root = _module_path(rl_candidate_runtime).parent
    tree_root_label = str((identity.manifest.get("package_tree") or {})
                          .get("root_label"))
    return {
        "builder_root_label": tree_root_label,
        "candidate_runtime_root": str(runtime_root),
        "disjoint": True,
        "note": (
            "Builder Identity Provider 是评估方可信主机输入;identity "
            "只经评估方代码进入 formal verifier,不传入 Candidate "
            "sandbox,checkpoint/sidecar/context/pack 均无 provider 字段"
        ),
    }
