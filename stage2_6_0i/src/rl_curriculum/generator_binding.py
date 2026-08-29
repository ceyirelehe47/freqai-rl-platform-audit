"""阶段 2.6.0b 工作包 F:生成器实现指纹(绑定真实实现模块)。

2.6.0a 的问题:所有 generator binding 哈希公共 generators.py——无法
证明私有隐藏生成器的实现未被替换(改 A 族实现 == 改 B 族哈希;改无
关生成器也会使目标族承诺失效,反之改目标族实现时若注册表模块整体
未变则发现不了)。

本模块从实际实现推导每个生成器族的独立指纹:

- 类实现源码(inspect.getsource,类体变化即变化);
- 实际定义模块文件内容(模块级 helper 变化即变化);
- MRO 上每个实现基类的模块文件(共享生成逻辑变化即变化);
- 显式声明的依赖文件(declared_dependencies:特征模块/资源等);
- 显式声明的资源文件(resource_files,缺失即失败);
- family_version 字符串。

输出:gi-<sha256> 与逐项 manifest(进入 sealed commitment 的
generator_bindings)。修改任何一项 -> 该族 implementation hash 变化;
修改无关生成器(不同模块/不同类)不影响目标族绑定。
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rl_curriculum.generator_api import BaseMarketGenerator


class GeneratorBindingError(RuntimeError):
    """生成器实现指纹推导失败(fail closed)。"""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _module_info(module: Any) -> dict[str, Any]:
    path = getattr(module, "__file__", None)
    if not path or not Path(path).is_file():
        raise GeneratorBindingError(
            f"模块 {getattr(module, '__name__', '?')} 无源文件"
            f"(动态/内建模块不得用于正式生成器)")
    p = Path(path)
    return {
        "module_name": module.__name__,
        "module_file": p.name,
        "module_hash": _sha256_bytes(p.read_bytes()),
    }


def _class_source(gen_type: type) -> dict[str, Any]:
    try:
        source = inspect.getsource(gen_type)
    except (OSError, TypeError) as exc:
        raise GeneratorBindingError(
            f"无法读取类 {gen_type.__name__} 源码: {exc}") from exc
    return {
        "class_name": gen_type.__name__,
        "class_source_hash": _sha256_bytes(source.encode("utf-8")),
    }


def implementation_manifest(
    generator: BaseMarketGenerator,
) -> dict[str, Any]:
    """从实际实现推导实现指纹 manifest(F1)。"""
    gen_type = type(generator)
    module = inspect.getmodule(gen_type)
    if module is None:
        raise GeneratorBindingError(
            f"生成器 {gen_type.__name__} 无法解析定义模块")
    manifest: dict[str, Any] = {
        "family": generator.family,
        "family_version": generator.family_version,
        **_module_info(module),
        **_class_source(gen_type),
    }
    # MRO:每个实现基类的模块(共享生成逻辑,如 _ProbeNullBase)
    mro_modules: list[dict[str, Any]] = []
    seen: set[str] = set()
    for base in gen_type.__mro__[1:]:
        if base is object or base is BaseMarketGenerator:
            continue
        base_module = inspect.getmodule(base)
        if base_module is None:
            continue
        info = _module_info(base_module)
        if info["module_name"] in seen:
            continue
        seen.add(info["module_name"])
        mro_modules.append({
            "class_name": base.__name__,
            **info,
        })
    manifest["base_class_modules"] = mro_modules
    # 生成器协议基类模块(generator_api.py)同样绑定
    api_module = inspect.getmodule(BaseMarketGenerator)
    if api_module is not None:
        manifest["protocol_module"] = _module_info(api_module)
    # F3:显式声明的依赖文件列表(相对定义模块目录)
    declared = list(getattr(generator, "declared_dependencies", ()) or ())
    deps: list[dict[str, Any]] = []
    module_dir = Path(module.__file__).parent
    for rel in declared:
        target = (module_dir / rel).resolve()
        if not target.is_file():
            raise GeneratorBindingError(
                f"生成器 {generator.family} 声明依赖 {rel!r} 不存在"
                f"(文件缺失直接失败;动态未声明资源不得用于正式生成器)")
        deps.append({
            "declared_path": rel,
            "file_hash": _sha256_bytes(target.read_bytes()),
        })
    manifest["declared_dependencies"] = deps
    # 资源文件(同样必须存在)
    resources = list(getattr(generator, "resource_files", ()) or ())
    res: list[dict[str, Any]] = []
    for rel in resources:
        target = (module_dir / rel).resolve()
        if not target.is_file():
            raise GeneratorBindingError(
                f"生成器 {generator.family} 声明资源 {rel!r} 不存在")
        res.append({
            "resource_path": rel,
            "file_hash": _sha256_bytes(target.read_bytes()),
        })
    manifest["resource_files"] = res
    # feature pipeline:生成器声明的特征列集合(特征依赖的结构性绑定)
    manifest["feature_columns_hash"] = _sha256_bytes(
        json.dumps(list(generator.feature_columns),
                   separators=(",", ":")).encode("utf-8"))
    manifest["implementation_hash"] = implementation_hash_of_manifest(manifest)
    return manifest


def implementation_hash_of_manifest(manifest: dict[str, Any]) -> str:
    payload = json.dumps(
        {k: v for k, v in manifest.items() if k != "implementation_hash"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "gi-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class GeneratorImplementationBinding:
    """单族绑定(进入 sealed commitment)。"""

    family: str
    family_version: str
    implementation_hash: str
    manifest_hash: str

    def canonical_payload(self) -> dict[str, Any]:
        return {
            "family": self.family,
            "family_version": self.family_version,
            "implementation_hash": self.implementation_hash,
            "manifest_hash": self.manifest_hash,
        }


def generator_bindings(
    registry: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """注册表中每个生成器族的独立实现绑定(F1/F4)。

    返回 {family: {family_version, implementation_hash, manifest_hash,
    manifest}};与 2.6.0a 的共享 generators.py 哈希不同,本绑定逐族
    来自实际实现模块/类源码/依赖/资源。
    """
    bindings: dict[str, dict[str, Any]] = {}
    for family in sorted(registry):
        gen = registry[family]
        manifest = implementation_manifest(gen)
        bindings[family] = {
            "family_version": gen.family_version,
            "implementation_hash": manifest["implementation_hash"],
            "manifest_hash": _sha256_bytes(
                json.dumps(manifest, sort_keys=True,
                           separators=(",", ":"),
                           ensure_ascii=False).encode("utf-8")),
            "manifest": manifest,
        }
    return bindings


def verify_generator_bindings(
    registry: dict[str, Any],
    expected: dict[str, dict[str, Any]],
    *,
    required_families: list[str] | None = None,
) -> dict[str, Any]:
    """逐族验证实际实现与承诺绑定一致(F4)。

    - 考试包引用的每个族都必须有绑定;
    - 实现哈希/版本/manifest 哈希逐项比对;
    - 修改任何实现成分 -> 该族校验失败(EXAM_INVALID);
    - 修改无关生成器(不在 required_families 中的族)不会静默替换
      目标族绑定(逐族独立计算)。
    """
    problems: list[str] = []
    checks: dict[str, bool] = {}
    families = required_families or sorted(expected)
    actual = generator_bindings(registry)
    for family in families:
        bound = expected.get(family)
        if bound is None:
            checks[f"generator_bound::{family}"] = False
            problems.append(f"承诺未绑定生成器族 {family!r}")
            continue
        if family not in actual:
            checks[f"generator_registered::{family}"] = False
            problems.append(f"注册表缺少生成器族 {family!r}(实现缺失)")
            continue
        act = actual[family]
        checks[f"generator_version::{family}"] = bool(
            act["family_version"] == bound["family_version"])
        if not checks[f"generator_version::{family}"]:
            problems.append(
                f"生成器族 {family} 版本不匹配:实际 {act['family_version']}"
                f" 承诺 {bound['family_version']}")
        checks[f"generator_implementation::{family}"] = bool(
            act["implementation_hash"] == bound["implementation_hash"])
        if not checks[f"generator_implementation::{family}"]:
            problems.append(
                f"生成器族 {family} 实现哈希不匹配:实际 "
                f"{act['implementation_hash']} 承诺 "
                f"{bound['implementation_hash']}"
                f"(实际实现模块/类源码/依赖/资源被替换)")
        checks[f"generator_manifest::{family}"] = bool(
            act["manifest_hash"] == bound["manifest_hash"])
        if not checks[f"generator_manifest::{family}"]:
            problems.append(
                f"生成器族 {family} 实现 manifest 哈希不匹配"
                f"(实现成分清单变化)")
    return {"checks": checks, "problems": problems,
            "pass": not problems}
