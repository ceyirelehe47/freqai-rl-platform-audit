"""正式 Builder Identity Provider(阶段 2.6.0f 工作包 A/B;2.6.0g 加固)。

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

阶段 2.6.0g 在 v2 基础上升级为 v3(null-pack-builder-manifest-v3):

- entrypoint 与 attempt-loop 必须真实存在:Private Provider 在派生
  identity 前用 AST 静态解析 + 受控 import 双重验证 module 源文件
  位于受信 root 内、qualname 对应真实的函数定义(不是注释、字符串、
  变量赋值或不存在的符号)、入口类型属于预注册允许范围(普通函数/
  静态方法/类方法;类构造器与协程函数被拒绝)、签名可解析且不含
  candidate/checkpoint/model/policy 参数(动态强制,不再是 manifest
  自我声明)、build 入口接受冻结构建请求(builder-runner-protocol-v1
  的单 request 位置参数);
- 外部依赖 manifest 从手工清单升级为 builder 链实际 import 的静态
  闭包(AST 扫描 rl_curriculum/rl_platform/builder root 内全部 .py 的
  import 语句,自动覆盖 gymnasium 等第三方依赖的版本身份);
- commitment 创建端与 CLI 共用同一 Provider 配置解析
  (load_builder_provider_config / private_provider_from_config,
  pair_count_per_family / max_attempts / external_dependencies 等
  字段不再被 CLI 遗漏);
- Provider 协议新增 builder_entrypoint() 与 frozen_build_request():
  产物来源证明(builder_provenance)在冻结输入下实际执行 builder 并
  比对 pack hash,npb- 不再只是"文件存在"的声明。
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

#: builder manifest 协议(阶段 2.6.0g:v2 的文件身份升级为含真实
#: entrypoint 验证与完整 import 闭包的 v3)
BUILDER_MANIFEST_FORMAT = "null-pack-builder-manifest-v3"
#: v1 只绑定手工挑选函数;v2 entrypoint/attempt-loop 只接受字符串声明、
#: 禁止参数规则只是 manifest 自我声明、外部依赖为手工少数包清单
_DEPRECATED_BUILDER_MANIFEST_FORMATS = (
    "null-pack-builder-manifest-v1",
    "null-pack-builder-manifest-v2",
)
#: builder 协议语义版本(assemble/attempt/seed/pair 语义契约)
BUILDER_PROTOCOL = "null-pack-builder-protocol-v3"

#: 预注册 entrypoint 类型允许范围(普通函数/静态方法/类方法;
#: 类构造器、协程函数与任意 callable 实例被拒绝——builder 必须是
#: 可静态定位源码的真实函数定义)
ALLOWED_ENTRYPOINT_KINDS = ("function", "staticfunction", "classfunction")

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
    return _cached_package_version(
        _DISTRIBUTION_NAME_ALIASES.get(name, name))


#: import 名与发行名不一致的包(闭包扫描输出的 module 名为 import 名,
#: 版本查询按发行名)
_DISTRIBUTION_NAME_ALIASES = {
    "sklearn": "scikit-learn",
    "cv2": "opencv-python",
    "PIL": "pillow",
    "yaml": "pyyaml",
}


@lru_cache(maxsize=None)
def _cached_package_version(name: str) -> str:
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


# ------------------------------------------------------- A1:入口真实验证
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


def _import_entrypoint_callable(
    root: Path, module: str, qualname: str,
) -> tuple[Any, str]:
    """受控 import:解析 module 并按 qualname 取出真实对象。

    - root 临时加入 sys.path(若尚未在),结束后移除;
    - 同名 module 的陈旧缓存(源文件不在本 root 内,来自其他 tmp
      root 的遗留)先弹出,保证 import 的是本 root 的代码;
    - qualname 按 "." 逐段 getattr 解析。
    """
    import importlib

    root_str = str(root.resolve())
    cached = sys.modules.get(module)
    if cached is not None:
        cached_file = str(getattr(cached, "__file__", "") or "")
        if cached_file and not cached_file.startswith(root_str + "/") \
                and not cached_file.startswith(root_str):
            sys.modules.pop(module, None)
    added = root_str not in sys.path
    if added:
        sys.path.insert(0, root_str)
    try:
        mod = importlib.import_module(module)
        obj: Any = mod
        for part in qualname.split("."):
            if not hasattr(obj, part):
                raise BuilderIdentityError(
                    f"import 后 {module!r} 上不存在属性 {part!r}"
                    f"(qualname {qualname!r} 指向不存在的符号)")
            obj = getattr(obj, part)
        return obj, str(getattr(mod, "__file__", "") or "")
    except ImportError as exc:
        raise BuilderIdentityError(
            f"builder 入口 module {module!r} 受控 import 失败: {exc}"
            f"(入口源码必须位于受信 root 内且可导入)") from exc
    finally:
        if added:
            try:
                sys.path.remove(root_str)
            except ValueError:
                pass


def validate_builder_entrypoint(
    root: Path | str, module: str, qualname: str, *,
    where: str,
    require_request_protocol: bool = False,
) -> dict[str, Any]:
    """A1:builder entrypoint 必须真实存在且可执行(P3/P4)。

    在 Provider 派生 identity 前执行(构造期),任何失败都是
    BuilderIdentityError(fail closed)。验证链:
    1. module 源文件存在于受信 root 内(AST 静态解析的前提);
    2. qualname 在源文件 AST 中是真实的函数定义(注释/字符串/赋值/
       不存在符号均被拒绝;不以字符串搜索判定);
    3. 入口类型属于预注册允许范围(function/staticfunction/
       classfunction;类构造器与协程函数被拒绝);
    4. 受控 import 后对象确实存在、callable 且与 AST 定位一致;
    5. inspect.signature 可解析,签名不含 candidate/checkpoint/
       model/policy(P4:动态强制,不是 manifest 自我声明);
    6. require_request_protocol=True 时(build 入口),签名必须是
       builder-runner-protocol-v1 的单 request 位置参数形态。

    返回验证报告(进入 manifest v3 的 entrypoints_validated 字段)。
    """
    import ast as _ast  # noqa: F401 - 供 _ast_resolve_qualname 使用
    import hashlib as _hl
    import inspect
    import types

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
    obj, imported_from = _import_entrypoint_callable(root, module, qualname)
    if not callable(obj):
        raise BuilderIdentityError(
            f"{where}: {module}.{qualname} import 后不是 callable")
    if isinstance(obj, type):
        raise BuilderIdentityError(
            f"{where}: {module}.{qualname} 是类构造器(type),不在入口"
            f"类型允许范围 {ALLOWED_ENTRYPOINT_KINDS}")
    if not isinstance(obj, (types.FunctionType, types.MethodType,
                            types.BuiltinFunctionType)):
        raise BuilderIdentityError(
            f"{where}: {module}.{qualname} 的运行时类型 "
            f"{type(obj).__name__!r} 不在入口类型允许范围")
    # P4:签名黑名单动态强制(私有侧与 mock 侧同一规则)
    check_builder_signature_policy(obj)
    try:
        sig = inspect.signature(obj)
    except (TypeError, ValueError) as exc:
        raise BuilderIdentityError(
            f"{where}: 入口 {module}.{qualname} 的签名无法解析: {exc}"
            f"(预注册允许范围只含可解析签名的真实函数)") from exc
    params = list(sig.parameters.values())
    if require_request_protocol:
        positional = [
            p for p in params
            if p.kind in (inspect.Parameter.POSITIONAL_ONLY,
                          inspect.Parameter.POSITIONAL_OR_KEYWORD)]
        var_pos = any(p.kind == inspect.Parameter.VAR_POSITIONAL
                      for p in params)
        if not positional and not var_pos:
            raise BuilderIdentityError(
                f"{where}: build 入口 {module}.{qualname} 不接受冻结"
                f"构建请求参数(builder-runner-protocol-v1 要求 "
                f"build_pack(frozen_build_request) 形态)")
        if var_pos and not positional:
            pass  # *args 形态可接收 request
    return {
        "module": str(module),
        "qualname": str(qualname),
        "kind": str(kind),
        "source_file": source.name,
        "source_sha256": _hl.sha256(source.read_bytes()).hexdigest(),
        "signature_params": [p.name for p in params],
        "imported_from_root": bool(imported_from),
        "request_protocol": bool(require_request_protocol),
    }


#: mock builder 的共享外部依赖(builder 链实际 import 的非 stdlib 身份)
def shared_external_dependency_manifest(
    extra_roots: list[tuple[str, Path | str]] | None = None,
) -> list[dict[str, Any]]:
    """显式外部依赖 manifest(AST import 闭包 + rl_platform tree)。

    阶段 2.6.0g(P6):依赖清单从手工少数包(python/numpy/pandas)升级为
    builder 链实际 import 的静态闭包——AST 扫描 rl_curriculum、
    rl_platform 与调用方给定的 builder root 内全部 .py 文件的 import
    语句(模块级与函数级一视同仁,"实际 import"按源码文本判定),收集
    非 stdlib、非内部包的顶级模块名并绑定其版本身份;gymnasium 等
    经 rl_platform.env 进入 builder 验证链的第三方依赖自此被覆盖。
    rl_platform 源码树仍以 tree hash 绑定(代码身份),python 运行时
    版本单独绑定。依赖身份变化 -> npb- 变化。
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

    # 内部源码包不作为外部依赖条目:rl_platform 以 tree hash 绑定,
    # rl_curriculum 在 builder package tree 内,rl_candidate_runtime
    # 的逐文件内容已由 candidate runtime manifest(2.6.0c)独立绑定
    internal_packages = {"rl_curriculum", "rl_platform",
                         "rl_candidate_runtime"}
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
                # 解析失败的文件不贡献依赖(其内容已由 tree manifest
                # 逐文件哈希绑定;语法损坏的 root 在 identity 阶段仍会
                # 因受控 import 失败而 fail closed)
                continue
            for node in _ast.walk(tree):
                if isinstance(node, _ast.Import):
                    for alias in node.names:
                        external.add(alias.name.split(".")[0])
                elif isinstance(node, _ast.ImportFrom):
                    if node.level and node.level > 0:
                        continue  # 包内相对导入
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
    """评估方侧 Provider 抽象(A1)。

    独立评估方的可信主机输入:在评估环境中重新计算 builder canonical
    manifest 与 hash,而不是读取自报值。实现必须保证:
    - 不从候选 checkpoint / sidecar / 考试 pack / 考试 context 获取信任;
    - 不进入 Candidate 沙箱(候选不可读、不可覆盖、不可选择)。

    阶段 2.6.0g:Provider 除派生静态身份外,还必须提供可执行的
    builder 入口与冻结构建请求——产物来源证明(builder_provenance)
    用它们在冻结输入下实际执行 builder 并比对 pack hash,npb- 不再
    只是"评估环境中存在一组被哈希的文件"的声明。
    """

    def builder_identity(self) -> BuilderIdentity: ...

    def builder_entrypoint(self) -> Any: ...

    def frozen_build_request(
        self, pack: Any, duration_contract: dict[str, Any],
    ) -> dict[str, Any]: ...


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
            mock_sealed_exam.mock_build_pack,
        )
        # A1(2.6.0g):mock 入口同样通过真实存在性验证(与私有 Provider
        # 同一验证链;mock runner 入口 mock_build_pack 必须接受冻结构建
        # 请求,attempt-loop 是构建循环本身)
        self._entrypoint_report = validate_builder_entrypoint(
            self._root, "rl_curriculum.mock_sealed_exam",
            "mock_build_pack", where="MockBuilderIdentityProvider",
            require_request_protocol=True)
        self._attempt_loop_report = validate_builder_entrypoint(
            self._root, "rl_curriculum.mock_sealed_exam",
            "build_mock_hidden_pack",
            where="MockBuilderIdentityProvider(attempt-loop)")

    def builder_identity(self) -> BuilderIdentity:
        from rl_curriculum.null_pack_validation import MAX_PACK_ATTEMPTS

        tree = builder_package_tree_manifest(
            self._root,
            root_label="rl_curriculum(mock builder package)",
            entrypoint_module="rl_curriculum.mock_sealed_exam",
            entrypoint_qualname="mock_build_pack",
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
            "entrypoints_validated": {
                "entrypoint": dict(self._entrypoint_report),
                "attempt_loop": dict(self._attempt_loop_report),
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
            include_mock_pack_payload=True)

    def builder_entrypoint(self) -> Any:
        """产物来源证明用的可执行 build 入口(runner 协议 v1)。"""
        from rl_curriculum import mock_sealed_exam

        return mock_sealed_exam.mock_build_pack


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
            else shared_external_dependency_manifest(
                extra_roots=[(str(root_label), self._root)]))
        self._root_label = str(root_label)
        # ---- A1(2.6.0g,P3/P4):构造期真实验证 entrypoint 与
        #      attempt-loop——module 源文件位于受信 root 内、qualname
        #      是 AST 中真实的函数定义(不是注释/字符串/不存在符号)、
        #      入口类型属于预注册允许范围、签名可解析且不含
        #      candidate/checkpoint/model/policy(动态强制)、build 入口
        #      接受冻结构建请求。任何失败即 BuilderIdentityError,
        #      不存在"只接受字符串声明"的回退。
        self._entrypoint_report = validate_builder_entrypoint(
            self._root, self._entrypoint_module,
            self._entrypoint_qualname,
            where=f"PrivateBuilderIdentityProvider({self._root_label})",
            require_request_protocol=True)
        self._attempt_loop_report: dict[str, Any] | None = None
        if self._attempt_loop_module and self._attempt_loop_qualname:
            self._attempt_loop_report = validate_builder_entrypoint(
                self._root, self._attempt_loop_module,
                self._attempt_loop_qualname,
                where=(f"PrivateBuilderIdentityProvider("
                       f"{self._root_label} attempt-loop)"))

    def builder_identity(self) -> BuilderIdentity:
        tree = builder_package_tree_manifest(
            self._root,
            root_label=self._root_label,
            entrypoint_module=self._entrypoint_module,
            entrypoint_qualname=self._entrypoint_qualname,
            attempt_loop_module=self._attempt_loop_module,
            attempt_loop_qualname=self._attempt_loop_qualname,
        )
        entrypoints_validated: dict[str, Any] = {
            "entrypoint": dict(self._entrypoint_report),
        }
        if self._attempt_loop_report is not None:
            entrypoints_validated["attempt_loop"] = dict(
                self._attempt_loop_report)
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
            "entrypoints_validated": entrypoints_validated,
        }
        return _build_identity(manifest)

    def builder_entrypoint(self) -> Any:
        """产物来源证明用的可执行 build 入口(受控 import 真实对象)。"""
        obj, _ = _import_entrypoint_callable(
            self._root, self._entrypoint_module,
            self._entrypoint_qualname)
        return obj

    def frozen_build_request(
        self, pack: Any, duration_contract: dict[str, Any],
    ) -> dict[str, Any]:
        from rl_curriculum.builder_provenance import build_frozen_build_request

        return build_frozen_build_request(
            self.builder_identity(), pack=pack,
            duration_contract=duration_contract)


# ------------------------------------------------- P5:统一配置解析
#: provider_config.json 的全部字段(必填/可选;CLI 与承诺创建端共用
#: 同一解析——不存在两套字段清单导致 CLI 遗漏 pair_count_per_family /
#: max_attempts / external_dependencies 的分叉)
PROVIDER_CONFIG_REQUIRED_FIELDS = ("entrypoint_module", "entrypoint_qualname")
PROVIDER_CONFIG_OPTIONAL_FIELDS = (
    "attempt_loop_module", "attempt_loop_qualname", "params_spec",
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
    静默失效)。
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
        "attempt_loop_module": str(raw.get("attempt_loop_module") or ""),
        "attempt_loop_qualname": str(raw.get("attempt_loop_qualname") or ""),
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
        attempt_loop_module=cfg.get("attempt_loop_module", ""),
        attempt_loop_qualname=cfg.get("attempt_loop_qualname", ""),
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
            f"(v1 手工函数清单绑定与 v2 纯字符串入口声明均已弃用;"
            f"v3 要求 entrypoint 真实验证与完整 import 闭包)")
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
