"""工作包 F:生成器实现指纹来自实际实现(逐族独立)。"""

from __future__ import annotations

import pytest

from rl_curriculum.generator_binding import (
    GeneratorBindingError,
    generator_bindings,
    implementation_hash_of_manifest,
    implementation_manifest,
    verify_generator_bindings,
)
from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY


def test_registry_bindings_are_per_family_and_distinct():
    b = generator_bindings(DEFAULT_GENERATOR_REGISTRY)
    assert len(b) == len(DEFAULT_GENERATOR_REGISTRY)
    hashes = {v["implementation_hash"] for v in b.values()}
    # 每族独立:不同实现模块/类源码的族哈希互不相同
    assert len(hashes) == len(b)
    for family, v in b.items():
        assert v["implementation_hash"].startswith("gi-")
        assert v["manifest"]["family"] == family


def test_manifest_covers_actual_class_module_and_mro():
    gen = DEFAULT_GENERATOR_REGISTRY["probe_null_sign"]
    m = implementation_manifest(gen)
    assert m["module_file"] == "generators.py"
    assert m["class_name"] == "ProbeNullSignGenerator"
    assert m["class_source_hash"]
    # MRO 共享基类(_ProbeNullBase)模块被绑定
    assert any(b["class_name"] == "_ProbeNullBase"
               for b in m["base_class_modules"])
    # 协议模块(generator_api)被绑定
    assert m["protocol_module"]["module_name"].endswith("generator_api")
    # feature pipeline
    assert m["feature_columns_hash"]


def test_implementation_hash_changes_with_class_source(tmp_path):
    """修改生成器自己的类实现 -> 哈希变化(同模块不同类互不冒充)。"""
    import sys
    import textwrap

    sys.path.insert(0, str(tmp_path))
    (tmp_path / "priv_gens.py").write_text(textwrap.dedent('''
        from rl_curriculum.generator_api import BaseMarketGenerator
        from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

        class PrivateA(BaseMarketGenerator):
            family = "private_a"
            family_version = "priv-v1"
            feature_columns = list(PROBE_FEATURE_COLUMNS)
            nuisance_slot_names = ()

            def _generate(self, params, seed, rng):
                n = int(params["episode_bars"])
                import pandas as pd
                return (rng.standard_normal(n) * 1e-4,
                        pd.DataFrame({"h": [0.0] * n}), {})

        class PrivateB(BaseMarketGenerator):
            family = "private_b"
            family_version = "priv-v1"
            feature_columns = list(PROBE_FEATURE_COLUMNS)
            nuisance_slot_names = ()

            def _generate(self, params, seed, rng):
                n = int(params["episode_bars"])
                import pandas as pd
                return (rng.standard_normal(n) * 2e-4,
                        pd.DataFrame({"h": [0.0] * n}), {})
    '''), encoding="utf-8")
    import importlib

    mod = importlib.import_module("priv_gens")
    h_a = implementation_manifest(mod.PrivateA())["implementation_hash"]
    h_b = implementation_manifest(mod.PrivateB())["implementation_hash"]
    assert h_a != h_b
    # 修改类实现(加一行注释级变更)-> 哈希变化
    src = (tmp_path / "priv_gens.py").read_text(encoding="utf-8")
    (tmp_path / "priv_gens.py").write_text(
        src.replace("family = \"private_a\"", "family = \"private_a\"\n            # tampered"),
        encoding="utf-8")
    importlib.invalidate_caches()
    import sys as _s

    _s.modules.pop("priv_gens", None)
    mod2 = importlib.import_module("priv_gens")
    h_a2 = implementation_manifest(mod2.PrivateA())["implementation_hash"]
    assert h_a != h_a2
    _s.modules.pop("priv_gens", None)


def test_declared_dependency_and_resource_binding(tmp_path):
    """声明依赖/资源文件变化 -> 哈希变化;文件缺失直接失败。"""
    import sys
    import textwrap

    dep = tmp_path / "features_dep.py"
    dep.write_text("K = 1.0\n", encoding="utf-8")
    res = tmp_path / "table.csv"
    res.write_text("a,b\n1,2\n", encoding="utf-8")
    sys.path.insert(0, str(tmp_path))
    (tmp_path / "priv_dep_gen.py").write_text(textwrap.dedent(f'''
        from rl_curriculum.generator_api import BaseMarketGenerator
        from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

        class DepGen(BaseMarketGenerator):
            family = "dep_gen"
            family_version = "dep-v1"
            feature_columns = list(PROBE_FEATURE_COLUMNS)
            nuisance_slot_names = ()
            declared_dependencies = ("features_dep.py",)
            resource_files = ("table.csv",)

            def _generate(self, params, seed, rng):
                n = int(params["episode_bars"])
                import pandas as pd
                return (rng.standard_normal(n) * 1e-4,
                        pd.DataFrame({{"h": [0.0] * n}}), {{"K": 1}})
    '''), encoding="utf-8")
    import importlib

    mod = importlib.import_module("priv_dep_gen")
    m1 = implementation_manifest(mod.DepGen())
    assert m1["declared_dependencies"][0]["file_hash"]
    assert m1["resource_files"][0]["file_hash"]
    dep.write_text("K = 2.0\n", encoding="utf-8")
    m2 = implementation_manifest(mod.DepGen())
    assert m1["implementation_hash"] != m2["implementation_hash"]
    res.write_text("a,b\n9,9\n", encoding="utf-8")
    m3 = implementation_manifest(mod.DepGen())
    assert m2["implementation_hash"] != m3["implementation_hash"]
    res.unlink()
    with pytest.raises(GeneratorBindingError):
        implementation_manifest(mod.DepGen())
    import sys as _s

    _s.modules.pop("priv_dep_gen", None)


def test_family_version_changes_hash():
    gen = DEFAULT_GENERATOR_REGISTRY["probe_segmented_drift"]
    m = implementation_manifest(gen)
    m2 = dict(m)
    m2["family_version"] = "tampered-version"
    assert implementation_hash_of_manifest(m) != \
        implementation_hash_of_manifest(m2)


def test_verify_rejects_tampered_implementation(sealed_exam_env):
    env = sealed_exam_env
    bindings = env["commitment"].generator_bindings
    report = verify_generator_bindings(
        env["registry"], bindings,
        required_families=sorted(bindings))
    assert report["pass"], report["problems"]
    tampered = dict(bindings)
    tampered["probe_segmented_drift"] = {
        **bindings["probe_segmented_drift"],
        "implementation_hash": "gi-" + "0" * 64}
    report2 = verify_generator_bindings(
        env["registry"], tampered,
        required_families=sorted(bindings))
    assert not report2["pass"]
    assert any("实现哈希不匹配" in p for p in report2["problems"])
