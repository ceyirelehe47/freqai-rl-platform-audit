"""正式 Builder Identity Provider(阶段 2.6.0f/2.6.0g;收尾版 v4)。

v3(提前提交的中间版本)遗留缺陷:

- Private Provider 构造期与产物来源证明期在**主评估进程**受控
  import 私有 builder 模块并取回 callable 直接调用——私有顶层代码
  进入评估主进程,无进程隔离(工作包 B1/C3);
- build 入口签名只检查"存在位置参数"且显式放行 ``*args``
  (工作包 C1);
- require_builder_identity 不重算 manifest/tree 自洽,手工构造的
  不自洽 BuilderIdentity 可通过(工作包 F)。

v4 语义(null-pack-builder-manifest-v4):

- 主进程对私有 Builder 只做 **AST 静态检查**(module 源文件位于
  受信 root 内、qualname 是真实的函数定义、入口类型属于预注册
  允许范围、签名是精确的 ``build_pack(request)`` 单参数形态);
  运行时 callable 类型/签名/返回值验证全部移入隔离 Runner
  (rl_builder_runtime.runner;C3);
- manifest 绑定 run_mode(builder_execution | mock_payload_
  assembly):mode 由 Provider 派生、被 npb- 绑定,commitment 与
  evidence 同步对账,不再依赖 isinstance 判定通道(D2);
- require_builder_identity 重算自洽:canonical manifest hash ==
  manifest_hash、builder_protocol 一致、package_tree 逐文件与
  tree_hash 自洽、entrypoint 报告与 staged 文件一致、run_mode
  与 commitment 一致(F);
- external_dependencies 是静态 AST 闭包**预检**(allowlist 候选
  与诊断),不是正式运行时依赖身份;实际 lock 由隔离 Runner 的
  import 审计派生并进入 evidence(G1/G3);
- 独立 attempt-loop entrypoint 已废除(C2):attempt 循环是 build
  入口内部的构建循环,其真实执行由规范化 attempt log
  (builder-attempt-log-v1,经 result 携带并被 nal- 哈希绑定)证明,
  不再接受"manifest 声明一个从未执行的函数"。
"""

from __future__ import annotations

import hashlib
import json
import platform
import sys
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

#: builder manifest 协议(阶段 2.6.0g 收尾:v3 的主进程 import 与
#: *args 放行升级为静态检查 + 隔离 Runner 运行时验证的 v4)
BUILDER_MANIFEST_FORMAT = "null-pack-builder-manifest-v4"
#: v1 只绑定手工挑选函数;v2 entrypoint 只接受字符串声明;v3 在主
#: 评估进程受控 import 私有 builder 并直接调用(无隔离 Runner、无
#: Builder Run Evidence、*args 放行、request 黑名单而非白名单)
_DEPRECATED_BUILDER_MANIFEST_FORMATS = (
    "null-pack-builder-manifest-v1",
    "null-pack-builder-manifest-v2",
    "null-pack-builder-manifest-v3",
)
#: builder 协议语义版本(assemble/attempt/seed/pair 语义契约;
#: 语义未变化,本轮不升级)
BUILDER_PROTOCOL = "null-pack-builder-protocol-v3"

#: 预注册 entrypoint 类型允许范围(普通函数/静态方法/类方法;
#: 类构造器、协程函数与任意 callable 实例被拒绝——builder 必须是
#: 可静态定位源码的真实函数定义)
ALLOWED_ENTRYPOINT_KINDS = ("function", "staticfunction", "classfunction")

#: package tree 扫描排除目录(编译缓存不是源码身份)
TREE_EXCLUDE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache"})
#: build 入口签名的候选别名黑名单(C1:参数名本身即拒绝)
PACK_BUILDER_FORBIDDEN_PARAMS: tuple[str, ...] = (
    "candidate", "candidate_path", "checkpoint", "checkpoint_path",
    "model", "policy", "score", "scores", "result", "exam_result",
    "verdict", "outcome", "prediction", "ranking",
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
) -> dict[str, Any]:
    """builder package tree manifest(B2;v4 不再有 attempt-loop 声明)。

    - 相对路径排序稳定(posix 形式);
    - 每个文件内容 sha256 与字节数;
    - entrypoint 模块与 qualname 显式声明(assemble 与 attempt 循环
      都在 build 入口内部,由 attempt log 运行证据证明;C2);
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


#: import 名与发行名不一致的包(闭包扫描输出的 module 名为 import 名,
#: 版本查询按发行名)
_DISTRIBUTION_NAME_ALIASES = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
}


def _package_version(name: str) -> str:
    return _cached_package_version(
        _DISTRIBUTION_NAME_ALIASES.get(name, name))


@lru_cache(maxsize=None)
def _cached_package_version(name: str) -> str:
    from importlib.metadata import PackageNotFoundError, version

    try:
        return str(version(name))
    except PackageNotFoundError:
        return f"<missing:{name}>"


def check_builder_signature_policy(*fns: Any) -> None:
    """公开 mock builder 函数签名不得包含候选相关参数(动态强制)。

    v4:私有 builder 的签名检查移入隔离 Runner(运行时)与 AST 静态
    预检;本函数只对主进程内可导入的公开(mock)函数执行。
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


# ------------------------------------------------- A1:入口静态验证(主进程)
def _module_source_within(root: Path, module: str) -> Path | None:
    """module 声明对应的源文件,必须位于受信 root 内。

    支持两种形态(按此顺序定位):
    - 私有 builder 形态:module 是 root 下的模块路径("builder_a";
      root 目录名与 module 同名时不误剥前缀);
    - 包内绝对形态:module 以 root 目录名开头
      ("rl_curriculum.mock_sealed_exam" 相对 rl_curriculum 包目录),
      剥掉包名前缀后定位。
    返回 None 表示 root 内不存在该源文件(module 拼写错误/入口文件
    缺失/路径逃逸)。
    """
    if not module or module.startswith(".") or ".." in module.split("."):
        return None
    root_name = root.resolve().name
    candidates: list[list[str]] = [module.split(".")]
    stripped = module.split(".")
    while stripped and stripped[0] == root_name and root_name:
        stripped = stripped[1:]
    if stripped and stripped != module.split("."):
        candidates.append(stripped)
    root_resolved = root.resolve()
    for parts in candidates:
        if not parts:
            continue
        for cand in (root.joinpath(*parts).with_suffix(".py"),
                     root.joinpath(*parts) / "__init__.py"):
            try:
                resolved = cand.resolve()
                if resolved.is_file() and str(resolved).startswith(
                        str(root_resolved) + "/"):
                    return resolved
            except OSError:
                continue
    return None


def _ast_resolve_qualname(source: Path, qualname: str):
    """AST 静态解析 qualname(最多 Class.method 两级)。

    返回 (节点, kind) 或 (None, 原因)。只有真实的 FunctionDef /
    AsyncFunctionDef 定义能被解析——注释、字符串字面量、变量赋值、
    不存在的符号在 AST 中都不是函数定义节点,天然被拒绝(不以字符串
    搜索判定)。
    """
    import ast as _ast

    try:
        tree = _ast.parse(source.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError, OSError) as exc:
        return None, f"源文件无法解析: {exc}"
    parts = [p for p in qualname.split(".") if p]
    if not parts or len(parts) > 2:
        return None, "qualname 必须是 module 内顶层函数或 Class.method"
    scope: list = list(tree.body)
    node = None
    for i, part in enumerate(parts):
        node = None
        for n in scope:
            if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef,
                              _ast.ClassDef)) and n.name == part:
                node = n
                break
        if node is None:
            return None, f"AST 中不存在 {qualname!r} 的定义"
        if i < len(parts) - 1:
            if not isinstance(node, _ast.ClassDef):
                return None, "qualname 嵌套路径中间层必须是类"
            scope = list(node.body)
    assert node is not None
    if isinstance(node, _ast.ClassDef):
        return node, "class"
    if isinstance(node, _ast.AsyncFunctionDef):
        return node, "async_function"
    deco_names = set()
    for d in node.decorator_list:
        if isinstance(d, _ast.Name):
            deco_names.add(d.id)
    if "staticmethod" in deco_names:
        return node, "staticfunction"
    if "classmethod" in deco_names:
        return node, "classfunction"
    return node, "function"


def _ast_signature_params(node: Any) -> tuple[list[str], list[str]]:
    """从 AST 函数定义提取 (参数名列表, 违规原因列表)。

    C1:build 入口必须是精确的 ``build_pack(request)``——恰好一个
    位置参数,除此之外不得有其他参数(第二个位置参数/可选额外参数/
    *args/**kwargs/keyword-only/候选别名参数名全部拒绝)。静态检查
    在主进程执行,运行时在隔离 Runner 再次强制(C3)。
    """
    a = node.args
    positional = list(a.posonlyargs) + list(a.args)
    params = [arg.arg for arg in positional]
    problems: list[str] = []
    if len(positional) != 1:
        problems.append(
            f"入口必须恰好接受一个 request 参数(AST 静态检出 "
            f"{len(positional)} 个位置参数)")
    if a.vararg is not None:
        problems.append(f"入口不接受 *args(参数 {a.vararg.arg!r})")
    if a.kwarg is not None:
        problems.append(f"入口不接受 **kwargs(参数 {a.kwarg.arg!r})")
    if a.kwonlyargs:
        problems.append(
            f"入口不接受 keyword-only 参数 "
            f"{[x.arg for x in a.kwonlyargs]!r}")
    if a.defaults:
        problems.append(
            "入口参数不得有默认值(可选额外参数被拒绝:"
            f"{params[-len(a.defaults):] if a.defaults else []})")
    if any(d is not None for d in a.kw_defaults):
        problems.append("keyword-only 参数不得有默认值")
    for name in params:
        if name in PACK_BUILDER_FORBIDDEN_PARAMS:
            problems.append(f"入口参数名 {name!r} 是候选相关禁止参数")
    return params, problems


def validate_builder_entrypoint(
    root: Path | str, module: str, qualname: str, *,
    where: str,
    require_request_protocol: bool = False,
) -> dict[str, Any]:
    """A1(静态版,v4):builder entrypoint 必须真实存在且形态合规。

    只做 **AST 静态检查**(主进程不 import 私有代码;B1/C3):
    1. module 源文件存在于受信 root 内;
    2. qualname 在源文件 AST 中是真实的函数定义(注释/字符串/赋值/
       不存在符号均被拒绝;不以字符串搜索判定);
    3. 入口类型属于预注册允许范围(function/staticfunction/
       classfunction;类构造器与协程函数被拒绝);
    4. require_request_protocol=True 时(build 入口),AST 签名必须是
       精确的 ``build_pack(request)`` 单参数形态(C1);
    5. 报告携带源文件相对路径与内容哈希(F:entrypoint 报告与 staged
       文件一致性的对账输入)。

    运行时 callable 类型/签名/返回值验证由隔离 Runner 执行
    (rl_builder_runtime.runner)。
    """
    import ast as _ast  # noqa: F401 - 供类型注解与解析使用
    import hashlib as _hl

    root = Path(root)
    if not module or not qualname:
        raise BuilderIdentityError(
            f"{where}: entrypoint 声明不完整(module={module!r}, "
            f"qualname={qualname!r});入口必须显式声明并真实存在")
    source = _module_source_within(root, module)
    if source is None:
        raise BuilderIdentityError(
            f"{where}: entrypoint module {module!r} 的源文件不存在于"
            f"受信 root {root} 内(拼写错误、入口文件缺失或路径逃逸均"
            f"拒绝;不接受 manifest 字符串自报)")
    node, kind_or_reason = _ast_resolve_qualname(source, qualname)
    if node is None:
        raise BuilderIdentityError(
            f"{where}: qualname {qualname!r} 在 {source.name} 中不是"
            f"真实的函数定义({kind_or_reason};注释、字符串、变量赋值"
            f"或不存在的符号均被拒绝)")
    kind = kind_or_reason
    if kind not in ALLOWED_ENTRYPOINT_KINDS:
        raise BuilderIdentityError(
            f"{where}: 入口类型 {kind!r} 不在预注册允许范围 "
            f"{ALLOWED_ENTRYPOINT_KINDS}(类构造器与协程函数被拒绝;"
            f"入口必须是可静态定位源码的真实函数)")
    params: list[str] = []
    problems: list[str] = []
    if require_request_protocol:
        params, problems = _ast_signature_params(node)
        if problems:
            raise BuilderIdentityError(
                f"{where}: build 入口 {module}.{qualname} 的签名违规"
                f"(C1:只允许精确的 build_pack(request) 单参数形态): "
                f"{'; '.join(problems)}")
    data = source.read_bytes()
    rel = source.relative_to(root.resolve()).as_posix()
    return {
        "module": str(module),
        "qualname": str(qualname),
        "kind": str(kind),
        "source_file": rel,
        "source_sha256": _hl.sha256(data).hexdigest(),
        "signature_params": params,
        "imported_from_root": True,
        "request_protocol": bool(require_request_protocol),
    }


#: mock builder 的共享外部依赖(builder 链实际 import 的非 stdlib 身份;
#: v4 语义:静态预检 + allowlist 候选,正式运行时身份由隔离 Runner 的
#: import 审计派生并进入 Builder Run Evidence——G1/G3)
def shared_external_dependency_manifest(
    extra_roots: list[tuple[str, Path | str]] | None = None,
) -> list[dict[str, Any]]:
    """静态 AST import 闭包预检(G1:预检/allowlist 候选/诊断)。

    AST 扫描 rl_curriculum、rl_platform 与调用方给定的 builder root
    内全部 .py 文件的 import 语句(模块级与函数级一视同仁),收集
    非 stdlib、非内部包的顶级模块名并绑定其版本身份。这不是完整
    运行时 lock:动态/条件/插件式 import 不在静态可见范围内,实际
    身份由隔离 Runner 的 sys.modules 审计重新派生(G2),并与本静态
    allowlist 对账(实际加载未注册依赖 -> fail closed;G3)。
    """
    roots: list[tuple[str, Path]] = [("rl_curriculum", _rl_curriculum_root())]
    for label, path in (extra_roots or []):
        roots.append((str(label), Path(path)))
    imports = _static_import_closure(roots)
    deps: list[dict[str, Any]] = [
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
    ]
    for name in imports:
        deps.append({
            "module": name,
            "kind": "package_version",
            "version": _package_version(name),
        })
    return deps


def _static_import_closure(
    roots: list[tuple[str, Path]],
) -> list[str]:
    """从给定 root 出发的静态 import 闭包(顶级外部模块名,排序稳定)。

    内部包(rl_curriculum / rl_platform)被 import 时继续递归扫描其
    目录;其余顶级名(排除 stdlib 与 root 自身包名)作为外部依赖返回。
    只做 AST 解析,不执行任何被扫描代码。
    """
    import ast as _ast

    internal_packages = {"rl_curriculum", "rl_platform",
                         "rl_candidate_runtime", "rl_builder_runtime"}
    internal_dirs: dict[str, Path] = {name: path for name, path in roots}
    internal_dirs.setdefault("rl_platform", _rl_platform_root())
    scanned: set[str] = set()
    external: set[str] = set()
    queue: list[tuple[str, Path]] = list(roots) + [
        ("rl_platform", internal_dirs["rl_platform"])]
    while queue:
        name, path = queue.pop(0)
        if name in scanned or not path.is_dir():
            continue
        scanned.add(name)
        for py in sorted(path.rglob("*.py")):
            if any(part in TREE_EXCLUDE_DIRS for part in py.parts):
                continue
            try:
                tree = _ast.parse(py.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError, OSError):
                continue
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        external.add(alias.name.split(".")[0])
                elif isinstance(node, _ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue
                    if node.module:
                        external.add(node.module.split(".")[0])
    stdlib = set(getattr(sys, "stdlib_module_names", ()))
    out = {
        name for name in external
        if name and name not in stdlib and name not in scanned
        and name not in internal_packages
    }
    return sorted(out)


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

    @property
    def run_mode(self) -> str:
        return str(self.manifest.get("run_mode") or "")


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
            "run_mode": manifest.get("run_mode"),
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
            "entrypoints_validated": {
                role: {
                    "qualname": report.get("qualname"),
                    "kind": report.get("kind"),
                    "request_protocol": report.get("request_protocol"),
                }
                for role, report in (
                    manifest.get("entrypoints_validated") or {}).items()
            },
        },
    )


@runtime_checkable
class BuilderIdentityProvider(Protocol):
    """评估方侧 Provider 抽象(v4)。

    独立评估方的可信主机输入:在评估环境中重新计算 builder canonical
    manifest 与 hash,而不是读取自报值。实现必须保证:
    - 不从候选 checkpoint / sidecar / 考试 pack / 考试 context 获取信任;
    - 不进入 Candidate 沙箱(候选不可读、不可覆盖、不可选择);
    - **不要求主评估进程 import 或执行私有 Builder**(v4:私有 Builder
      只在隔离 Runner 内执行;Provider 提供静态身份、冻结请求与运行
      模式,不再提供主进程可执行入口);
    - builder_run_mode() 派生构建通道(D2:mode 被 manifest 绑定,
      不依赖 isinstance 判定 payload 许可)。
    """

    def builder_identity(self) -> BuilderIdentity: ...

    def frozen_build_request(
        self, pack: Any, duration_contract: dict[str, Any],
    ) -> dict[str, Any]: ...

    def builder_run_mode(self) -> str: ...


class MockBuilderIdentityProvider:
    """公开 mock builder 的 Provider(公开流程专用,必须显式传入)。

    tree root = rl_curriculum 包目录:mock builder 的 assemble /
    attempt 循环 / _validate_pack_ephemeral / build_spec_for_pack /
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
        # 签名政策动态强制(公开代码在主进程可导入;v4 语义保留)
        from rl_curriculum.null_pack_validation import (
            pack_builder_attempt_log,
            validate_null_pack,
        )

        check_builder_signature_policy(
            mock_sealed_exam.assemble_mock_hidden_pack,
            mock_sealed_exam.build_mock_hidden_pack,
            validate_null_pack,
            pack_builder_attempt_log,
            mock_sealed_exam.mock_build_pack,
        )
        # A1 静态验证(v4:主进程只做 AST 检查;mock 入口同样通过
        # 真实存在性与精确单参数形态验证)
        self._entrypoint_report = validate_builder_entrypoint(
            self._root, "rl_curriculum.mock_sealed_exam",
            "mock_build_pack", where="MockBuilderIdentityProvider",
            require_request_protocol=True)

    @property
    def root(self) -> Path:
        return self._root

    def builder_run_mode(self) -> str:
        from rl_curriculum.builder_provenance import (
            BUILDER_RUN_MODE_MOCK_ASSEMBLY,
        )

        return BUILDER_RUN_MODE_MOCK_ASSEMBLY

    def builder_identity(self) -> BuilderIdentity:
        from rl_curriculum.null_pack_validation import MAX_PACK_ATTEMPTS

        tree = builder_package_tree_manifest(
            self._root,
            root_label="rl_curriculum(mock builder package)",
            entrypoint_module="rl_curriculum.mock_sealed_exam",
            entrypoint_qualname="mock_build_pack",
        )
        manifest = {
            "format": BUILDER_MANIFEST_FORMAT,
            "builder_protocol": BUILDER_PROTOCOL,
            "run_mode": self.builder_run_mode(),
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
            "entrypoints_validated": {
                "entrypoint": dict(self._entrypoint_report),
            },
        }
        return _build_identity(manifest)

    def frozen_build_request(
        self, pack: Any, duration_contract: dict[str, Any],
    ) -> dict[str, Any]:
        from rl_curriculum.builder_provenance import (
            build_frozen_build_request,
        )

        return build_frozen_build_request(
            self.builder_identity(), pack=pack,
            duration_contract=duration_contract,
            mode=self.builder_run_mode(),
            include_mock_pack_payload=True)


class PrivateBuilderIdentityProvider:
    """评估方私有 builder 的 Provider(v4:主进程零私有代码执行)。

    私有 builder 源码位于评估方私有目录(测试时为临时目录),不进入
    Candidate runtime,不进入公开 commitment;完整 manifest 保留在
    评估方私有目录,公开承诺只携带 manifest hash、协议版本与非敏感
    摘要。formal verifier 从本 Provider 重新计算 hash(A4)。

    v4:构造期只执行 AST 静态验证(不 import 私有模块——私有 Builder
    的 import 与执行只发生在隔离 Runner;B1/C3);构建通道固定为
    builder_execution(真实构建,不存在 payload 组装通道)。
    """

    def __init__(
        self, root: Path | str, *,
        entrypoint_module: str,
        entrypoint_qualname: str,
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
        self._params_spec = dict(params_spec or {})
        self._families = list(families or [])
        self._pair_count = int(pair_count_per_family)
        self._max_attempts = int(max_attempts)
        self._external_dependencies = list(
            external_dependencies
            if external_dependencies is not None
            else shared_external_dependency_manifest(
                extra_roots=[(str(root_label), self._root)]))
        self._root_label = str(root_label)
        # ---- A1 静态版(v4):module 源文件位于受信 root 内、qualname
        #      是 AST 中真实的函数定义、入口类型属于预注册允许范围、
        #      签名是精确的 build_pack(request) 单参数形态。任何失败
        #      即 BuilderIdentityError;主进程**不 import 私有模块**
        #      (运行时验证移入隔离 Runner)。
        self._entrypoint_report = validate_builder_entrypoint(
            self._root, self._entrypoint_module,
            self._entrypoint_qualname,
            where=f"PrivateBuilderIdentityProvider({self._root_label})",
            require_request_protocol=True)

    @property
    def root(self) -> Path:
        return self._root

    def builder_run_mode(self) -> str:
        from rl_curriculum.builder_provenance import (
            BUILDER_RUN_MODE_EXECUTION,
        )

        return BUILDER_RUN_MODE_EXECUTION

    def builder_identity(self) -> BuilderIdentity:
        tree = builder_package_tree_manifest(
            self._root,
            root_label=self._root_label,
            entrypoint_module=self._entrypoint_module,
            entrypoint_qualname=self._entrypoint_qualname,
        )
        manifest = {
            "format": BUILDER_MANIFEST_FORMAT,
            "builder_protocol": BUILDER_PROTOCOL,
            "run_mode": self.builder_run_mode(),
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
            "entrypoints_validated": {
                "entrypoint": dict(self._entrypoint_report),
            },
        }
        return _build_identity(manifest)

    def frozen_build_request(
        self, pack: Any, duration_contract: dict[str, Any],
    ) -> dict[str, Any]:
        from rl_curriculum.builder_provenance import build_frozen_build_request

        return build_frozen_build_request(
            self.builder_identity(), pack=pack,
            duration_contract=duration_contract,
            mode=self.builder_run_mode())


# ------------------------------------------------- P5:统一配置解析
#: provider_config.json 的全部字段(必填/可选;CLI 与承诺创建端共用
#: 同一解析——不存在两套字段清单导致 CLI 遗漏 pair_count_per_family /
#: max_attempts / external_dependencies 的分叉)。
#: v4:attempt_loop_module/attempt_loop_qualname 已废除(独立 attempt-
#: loop entrypoint 不再保留;attempt 循环由 build 入口内部的规范化
#: attempt log 运行证据证明——C2)。
PROVIDER_CONFIG_REQUIRED_FIELDS = ("entrypoint_module", "entrypoint_qualname")
PROVIDER_CONFIG_OPTIONAL_FIELDS = (
    "params_spec",
    "families", "pair_count_per_family", "max_attempts",
    "external_dependencies", "root_label",
)
PROVIDER_CONFIG_FILENAME = "provider_config.json"


def load_builder_provider_config(root: Path | str) -> dict[str, Any]:
    """读取并规范化评估方私有 Provider 配置(P5)。

    唯一的 provider_config.json 解析路径:CLI(--builder-provider
    private)与承诺创建端/测试 conftest 都经由本函数构造 Provider,
    字段清单单一来源;缺失文件、JSON 破损或必填字段缺失均
    fail closed(BuilderIdentityError),未知字段拒绝(拼写错误不得
    静默失效)。v4 已废除的 attempt_loop_* 字段显式报错(带迁移
    提示,不静默忽略)。
    """
    import json as _json

    root = Path(root)
    cfg_path = root / PROVIDER_CONFIG_FILENAME
    if not cfg_path.is_file():
        raise BuilderIdentityError(
            f"私有 Provider 配置缺失: {cfg_path}(评估方必须提供只读 "
            f"provider_config.json)")
    try:
        raw = _json.loads(cfg_path.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise BuilderIdentityError(
            f"私有 Provider 配置无法解析: {cfg_path}: {exc}") from exc
    if not isinstance(raw, dict):
        raise BuilderIdentityError(
            f"私有 Provider 配置必须是 JSON 对象: {cfg_path}")
    removed = sorted(set(raw) & {
        "attempt_loop_module", "attempt_loop_qualname"})
    if removed:
        raise BuilderIdentityError(
            f"私有 Provider 配置含 v4 已废除字段 {removed}:独立 "
            f"attempt-loop entrypoint 不再保留(attempt 循环由 build "
            f"入口内部的规范化 attempt log 运行证据证明,C2);请从"
            f"配置中删除这些字段")
    unknown = sorted(set(raw) - set(PROVIDER_CONFIG_REQUIRED_FIELDS)
                     - set(PROVIDER_CONFIG_OPTIONAL_FIELDS))
    if unknown:
        legal = sorted(set(PROVIDER_CONFIG_REQUIRED_FIELDS)
                       | set(PROVIDER_CONFIG_OPTIONAL_FIELDS))
        raise BuilderIdentityError(
            f"私有 Provider 配置含未知字段 {unknown}(拼写错误不得静默"
            f"失效;合法字段: {legal})")
    missing = [f for f in PROVIDER_CONFIG_REQUIRED_FIELDS if not raw.get(f)]
    if missing:
        raise BuilderIdentityError(
            f"私有 Provider 配置缺少必填字段 {missing}: {cfg_path}")
    cfg: dict[str, Any] = {
        "entrypoint_module": str(raw["entrypoint_module"]),
        "entrypoint_qualname": str(raw["entrypoint_qualname"]),
        "params_spec": dict(raw.get("params_spec") or {}),
        "families": list(raw.get("families") or []),
        "pair_count_per_family": int(
            raw.get("pair_count_per_family", 32)),
        "max_attempts": int(raw.get("max_attempts", 8)),
        "external_dependencies": (
            list(raw["external_dependencies"])
            if raw.get("external_dependencies") is not None else None),
        "root_label": str(raw.get("root_label") or "private-builder"),
    }
    return cfg


def private_provider_from_config(
    root: Path | str, config: dict[str, Any] | None = None,
) -> "PrivateBuilderIdentityProvider":
    """从统一配置构造私有 Provider(P5:CLI 与承诺创建端同源)。

    config 为 None 时从 root/provider_config.json 读取
    (load_builder_provider_config);显式传入时视为已规范化的配置
    (同样走 load 的字段校验不重复——调用方负责来源)。
    """
    cfg = dict(config) if config is not None else \
        load_builder_provider_config(root)
    return PrivateBuilderIdentityProvider(
        root,
        entrypoint_module=cfg["entrypoint_module"],
        entrypoint_qualname=cfg["entrypoint_qualname"],
        params_spec=cfg.get("params_spec"),
        families=cfg.get("families"),
        pair_count_per_family=int(cfg.get("pair_count_per_family", 32)),
        max_attempts=int(cfg.get("max_attempts", 8)),
        external_dependencies=cfg.get("external_dependencies"),
        root_label=cfg.get("root_label", "private-builder"),
    )


def require_builder_identity(
    identity: BuilderIdentity | None, *,
    where: str,
    expected_run_mode: str | None = None,
) -> BuilderIdentity:
    """formal 路径的 BuilderIdentity 必填 + 自洽重算守卫(工作包 F)。

    重算并验证(fail closed,手工构造的不自洽身份被拒绝):
    - identity 非 None 且为 BuilderIdentity(不存在隐式 mock fallback);
    - manifest format == v4;
    - canonical manifest hash 重算 == identity.manifest_hash
      (manifest A + hash B 攻击被拒);
    - manifest.builder_protocol == identity.builder_protocol
      (protocol A + protocol B 攻击被拒);
    - package_tree 逐文件自洽:重放 tree digest == tree_hash、
      file_count == len(files)、路径唯一(文件清单被改但 tree hash
      未改的攻击被拒);
    - entrypoints_validated 与 staged 文件一致:每份报告的
      source_file 在文件清单内且 source_sha256 == 该文件内容哈希
      (entrypoint 报告与实际 staged 文件不一致的攻击被拒);
    - signature_policy.enforced is True;
    - run_mode 属于预注册集合,且与 commitment 期望一致(runtime
      mode 与 commitment 一致)。
    """
    from rl_curriculum.builder_provenance import BUILDER_RUN_MODES

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
            f"(v1 手工函数清单、v2 纯字符串入口声明、v3 主进程受控 "
            f"import 均已弃用;v4 要求主进程零私有代码执行 + 隔离 "
            f"Runner 运行时验证)")
    manifest = identity.manifest or {}
    # F:canonical manifest hash 重算(public digest 伪造无法通过——
    # npb- 只认 canonical manifest 内容)
    recomputed = canonical_builder_manifest_hash(manifest)
    if recomputed != identity.manifest_hash:
        raise BuilderIdentityError(
            f"{where} builder manifest hash 不自洽(重算 {recomputed} "
            f"vs 自报 {identity.manifest_hash}):manifest 与 hash 来自"
            f"不同版本的攻击被拒绝(EXAM_INVALID)")
    if str(manifest.get("builder_protocol")) != str(
            identity.builder_protocol):
        raise BuilderIdentityError(
            f"{where} builder protocol 不自洽(manifest="
            f"{manifest.get('builder_protocol')!r} vs identity="
            f"{identity.builder_protocol!r})")
    tree = manifest.get("package_tree") or {}
    files = list(tree.get("files") or [])
    digest = hashlib.sha256()
    seen: set[str] = set()
    for entry in files:
        rel = str(entry.get("path") or "")
        sha = str(entry.get("sha256") or "")
        if not rel or not sha or rel in seen:
            raise BuilderIdentityError(
                f"{where} package_tree 文件清单不自洽(路径 {rel!r})")
        seen.add(rel)
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        try:
            digest.update(bytes.fromhex(sha))
        except ValueError as exc:
            raise BuilderIdentityError(
                f"{where} package_tree 文件哈希非十六进制({rel!r})") \
                from exc
    if digest.hexdigest() != str(tree.get("tree_hash") or ""):
        raise BuilderIdentityError(
            f"{where} package_tree tree_hash 与文件清单不自洽"
            f"(文件清单被改但 tree hash 未改的攻击被拒绝;"
            f"EXAM_INVALID)")
    if int(tree.get("file_count") or 0) != len(files):
        raise BuilderIdentityError(
            f"{where} package_tree file_count({tree.get('file_count')})"
            f" != 实际文件数({len(files)})")
    sha_by_path = {str(e.get("path")): str(e.get("sha256"))
                   for e in files}
    for role, report in (manifest.get("entrypoints_validated")
                         or {}).items():
        src = str((report or {}).get("source_file") or "")
        src_sha = str((report or {}).get("source_sha256") or "")
        if src not in sha_by_path:
            raise BuilderIdentityError(
                f"{where} entrypoint 报告({role})的 source_file "
                f"{src!r} 不在 staged 文件清单内(报告与实际 staged "
                f"文件不一致的攻击被拒绝;EXAM_INVALID)")
        if src_sha and sha_by_path[src] != src_sha:
            raise BuilderIdentityError(
                f"{where} entrypoint 报告({role})的 source_sha256 与 "
                f"staged 文件 {src!r} 内容不一致(EXAM_INVALID)")
    policy = manifest.get("signature_policy") or {}
    if policy.get("enforced") is not True:
        raise BuilderIdentityError(
            f"{where} builder manifest 的 signature_policy.enforced "
            f"必须为 True")
    run_mode = str(manifest.get("run_mode") or "")
    if run_mode not in BUILDER_RUN_MODES:
        raise BuilderIdentityError(
            f"{where} builder manifest 的 run_mode {run_mode!r} 不在"
            f"预注册范围 {BUILDER_RUN_MODES}(EXAM_INVALID)")
    if expected_run_mode is not None and run_mode != expected_run_mode:
        raise BuilderIdentityError(
            f"{where} builder run_mode({run_mode!r})与 commitment 绑定"
            f"的运行模式({expected_run_mode!r})不一致(runtime mode "
            f"与 commitment 一致性被拒绝;EXAM_INVALID)")
    return identity


def provider_runtime_isolation_report(
    identity: BuilderIdentity,
) -> dict[str, Any]:
    """Provider/Candidate 隔离证据:builder root 不在候选运行时目录内。

    候选运行时(rl_candidate_runtime)与 builder package tree 是不相交
    的目录;Provider 不进入 Candidate 沙箱(候选不可读/不可覆盖/不可
    选择 builder 身份)。此报告仅作审计证据,不参与信任判定。
    v4 补充:Builder Runner(rl_builder_runtime)与 Candidate Runner
    (rl_candidate_runtime)同样是不相交的最小运行时。
    """
    import rl_builder_runtime
    import rl_candidate_runtime

    runtime_root = _module_path(rl_candidate_runtime).parent
    builder_runtime_root = _module_path(rl_builder_runtime).parent
    tree_root_label = str((identity.manifest.get("package_tree") or {})
                          .get("root_label"))
    return {
        "builder_root_label": tree_root_label,
        "candidate_runtime_root": str(runtime_root),
        "builder_runtime_root": str(builder_runtime_root),
        "disjoint": True,
        "note": (
            "Builder Identity Provider 是评估方可信主机输入;identity "
            "只经评估方代码进入 formal verifier,不传入 Candidate "
            "sandbox,checkpoint/sidecar/context/pack 均无 provider 字段;"
            "私有 Builder 只在隔离 Builder Runner(rl_builder_runtime,"
            "与 rl_candidate_runtime 不同的最小运行时与挂载集合)内执行"
        ),
    }
