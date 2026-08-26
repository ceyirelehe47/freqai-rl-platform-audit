"""工作包 F2:私有生成器模块篡改测试(两模块/依赖/资源/版本/无关族)。"""

from __future__ import annotations

import sys
import textwrap

import pytest

from rl_curriculum.generator_binding import (
    implementation_manifest,
    verify_generator_bindings,
)

MOD_A = textwrap.dedent('''
    from rl_curriculum.generator_api import BaseMarketGenerator
    from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

    def shared_scale():
        return 1.5e-4

    class HiddenGenA(BaseMarketGenerator):
        family = "hidden_gen_a"
        family_version = "hidden-a-v1"
        feature_columns = list(PROBE_FEATURE_COLUMNS)
        nuisance_slot_names = ()
        declared_dependencies = ("feature_helpers.py",)

        def _generate(self, params, seed, rng):
            n = int(params["episode_bars"])
            import pandas as pd
            from feature_helpers import scale_a
            return (rng.standard_normal(n) * scale_a(),
                    pd.DataFrame({"h": [0.0] * n}), {})
''')

MOD_B = textwrap.dedent('''
    from rl_curriculum.generator_api import BaseMarketGenerator
    from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

    class HiddenGenB(BaseMarketGenerator):
        family = "hidden_gen_b"
        family_version = "hidden-b-v1"
        feature_columns = list(PROBE_FEATURE_COLUMNS)
        nuisance_slot_names = ()

        def _generate(self, params, seed, rng):
            n = int(params["episode_bars"])
            import pandas as pd
            return (rng.standard_normal(n) * 3e-4,
                    pd.DataFrame({"h": [0.0] * n}), {})
''')


@pytest.fixture()
def private_modules(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "hidden_module_a.py").write_text(MOD_A, encoding="utf-8")
    (tmp_path / "hidden_module_b.py").write_text(MOD_B, encoding="utf-8")
    (tmp_path / "feature_helpers.py").write_text(
        "def scale_a():\n    return 1.5e-4\n", encoding="utf-8")
    import importlib

    ma = importlib.import_module("hidden_module_a")
    mb = importlib.import_module("hidden_module_b")
    yield ma, mb, tmp_path
    sys.modules.pop("hidden_module_a", None)
    sys.modules.pop("hidden_module_b", None)
    sys.modules.pop("feature_helpers", None)


def _reload(tmp_path, name):
    import importlib

    sys.modules.pop(name, None)
    sys.modules.pop("feature_helpers", None)
    importlib.invalidate_caches()
    return importlib.import_module(name)


def test_modify_target_class_changes_its_hash_not_unrelated(
        private_modules):
    ma, mb, tmp_path = private_modules
    h_a1 = implementation_manifest(ma.HiddenGenA())["implementation_hash"]
    h_b1 = implementation_manifest(mb.HiddenGenB())["implementation_hash"]
    # 修改 A 的类实现
    (tmp_path / "hidden_module_a.py").write_text(
        MOD_A.replace("return (rng.standard_normal(n)",
                      "return (rng.standard_normal(n) * 1.0001"),
        encoding="utf-8")
    ma2 = _reload(tmp_path, "hidden_module_a")
    h_a2 = implementation_manifest(ma2.HiddenGenA())["implementation_hash"]
    assert h_a1 != h_a2
    # 无关生成器(B)绑定不受影响
    h_b2 = implementation_manifest(mb.HiddenGenB())["implementation_hash"]
    assert h_b1 == h_b2


def test_modify_feature_dependency_changes_hash(private_modules):
    ma, _mb, tmp_path = private_modules
    h1 = implementation_manifest(ma.HiddenGenA())["implementation_hash"]
    (tmp_path / "feature_helpers.py").write_text(
        "def scale_a():\n    return 2.5e-4\n", encoding="utf-8")
    ma2 = _reload(tmp_path, "hidden_module_a")
    h2 = implementation_manifest(ma2.HiddenGenA())["implementation_hash"]
    assert h1 != h2


def test_modify_family_version_changes_hash(private_modules):
    ma, _mb, tmp_path = private_modules
    h1 = implementation_manifest(ma.HiddenGenA())["implementation_hash"]
    (tmp_path / "hidden_module_a.py").write_text(
        MOD_A.replace('"hidden-a-v1"', '"hidden-a-v2"'), encoding="utf-8")
    ma2 = _reload(tmp_path, "hidden_module_a")
    h2 = implementation_manifest(ma2.HiddenGenA())["implementation_hash"]
    assert h1 != h2


def test_unrelated_module_change_does_not_silent_replace_target(
        private_modules):
    """修改无关生成器模块不得静默替换目标族绑定(逐族独立校验)。"""
    ma, mb, tmp_path = private_modules
    registry = {ma.HiddenGenA().family: ma.HiddenGenA(),
                mb.HiddenGenB().family: mb.HiddenGenB()}
    from rl_curriculum.generator_binding import generator_bindings

    bound = {f: {k: v[k] for k in
                 ("family_version", "implementation_hash", "manifest_hash")}
             for f, v in generator_bindings(registry).items()}
    # 篡改 B 的实现
    (tmp_path / "hidden_module_b.py").write_text(
        MOD_B.replace("3e-4", "9e-4"), encoding="utf-8")
    mb2 = _reload(tmp_path, "hidden_module_b")
    registry2 = {ma.HiddenGenA().family: ma.HiddenGenA(),
                 mb2.HiddenGenB().family: mb2.HiddenGenB()}
    report = verify_generator_bindings(
        registry2, bound, required_families=sorted(bound))
    assert not report["pass"]
    failed = {k for k, v in report["checks"].items() if not v}
    # 只有 hidden_gen_b 的检查失败:A 的绑定不受影响
    assert all("hidden_gen_b" in k for k in failed)
    assert any("hidden_gen_a" in k and v
               for k, v in report["checks"].items())
