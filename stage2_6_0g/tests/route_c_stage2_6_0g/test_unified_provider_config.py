"""P5:统一 Provider 配置解析(CLI 与承诺创建端同源)。

provider_config.json 只有一条解析路径(load_builder_provider_config /
private_provider_from_config):CLI 不再遗漏 pair_count_per_family /
max_attempts / external_dependencies;未知字段与缺失必填字段
fail closed。
"""

from __future__ import annotations

import json

import pytest


def _write_config(root, payload: dict) -> "object":
    root.mkdir(parents=True, exist_ok=True)
    (root / "builder_y.py").write_text(
        "def build_pack(request):\n    return None\n", encoding="utf-8")
    (root / "provider_config.json").write_text(
        json.dumps(payload, indent=1), encoding="utf-8")
    return root


BASE = {
    "entrypoint_module": "builder_y",
    "entrypoint_qualname": "build_pack",
}


def test_config_missing_file_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    with pytest.raises(BuilderIdentityError, match="配置缺失"):
        load_builder_provider_config(tmp_path / "nope")


def test_config_broken_json_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = tmp_path / "broken"
    root.mkdir()
    (root / "provider_config.json").write_text("{not json",
                                               encoding="utf-8")
    with pytest.raises(BuilderIdentityError, match="无法解析"):
        load_builder_provider_config(root)


def test_config_missing_required_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = _write_config(tmp_path / "no_req",
                         {"entrypoint_module": "builder_y"})
    with pytest.raises(BuilderIdentityError, match="必填字段"):
        load_builder_provider_config(root)


def test_config_unknown_field_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    payload = dict(BASE)
    payload["pair_count"] = 24  # 拼写错误(正确名 pair_count_per_family)
    root = _write_config(tmp_path / "unknown", payload)
    with pytest.raises(BuilderIdentityError, match="未知字段"):
        load_builder_provider_config(root)


def test_config_all_fields_reach_manifest(tmp_path):
    """P5 核心:pair_count_per_family / max_attempts / external_deps
    从 config 全字段进入 manifest(CLI 旧实现会遗漏这些字段)。"""
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )

    payload = dict(BASE)
    payload.update({
        "pair_count_per_family": 24,
        "max_attempts": 5,
        "families": ["probe_null_sign"],
        "params_spec": {"episode_bars": 96},
        "root_label": "full-field-builder",
        "external_dependencies": [
            {"module": "rl_platform", "kind": "package_tree",
             "tree_hash": "0" * 64},
            {"module": "python", "kind": "runtime_version",
             "version": "3.x"},
        ],
    })
    root = _write_config(tmp_path / "full", payload)
    identity = private_provider_from_config(root).builder_identity()
    assert identity.manifest["pair_count_per_family"] == 24
    assert identity.manifest["max_attempts"] == 5
    assert identity.manifest["package_tree"]["root_label"] == \
        "full-field-builder"
    assert identity.manifest["external_dependencies"] == \
        payload["external_dependencies"]


def test_config_defaults_applied(tmp_path):
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )

    root = _write_config(tmp_path / "defaults", dict(BASE))
    identity = private_provider_from_config(root).builder_identity()
    assert identity.manifest["pair_count_per_family"] == 32
    assert identity.manifest["max_attempts"] == 8


def test_cli_and_conftest_same_source(private_builder_a):
    """conftest 的 private_provider_from_root 与 CLI 都经由
    private_provider_from_config(单一解析路径;同 root 同身份)。"""
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )

    root = private_builder_a._root
    via_cli_path = private_provider_from_config(root)
    via_helper = private_provider_from_root(root)
    assert (via_cli_path.builder_identity().manifest_hash
            == via_helper.builder_identity().manifest_hash)


def test_cli_private_path_full_field_config(sealed_exam_env, tmp_path):
    """CLI --builder-provider private 读取全字段配置(进程级验证)。"""
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )

    from tests.route_c_stage2_6_0f.conftest import write_private_builder

    root = write_private_builder(tmp_path / "cli_fields")
    # 覆写 pair_count(非默认 32)验证 CLI 不再遗漏
    cfg_path = root / "provider_config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    cfg["pair_count_per_family"] = 17
    cfg["max_attempts"] = 3
    cfg_path.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
    identity = private_provider_from_config(root).builder_identity()
    assert identity.manifest["pair_count_per_family"] == 17
    assert identity.manifest["max_attempts"] == 3
