"""阶段 2.6.0g 收尾:P5 统一 Provider 配置解析(v4 字段清单)。

- attempt_loop 字段已废除(v4):显式报错带迁移提示,不静默忽略;
- 未知字段/破损 JSON/必填缺失 fail closed;
- CLI 与承诺创建端同源(同一 load_builder_provider_config)。
"""

from __future__ import annotations

import json

import pytest

from tests.route_c_stage2_6_0f.conftest import (
    private_provider_from_root,
    write_private_builder,
)


def test_valid_config_loads(tmp_path):
    from rl_curriculum.builder_identity import (
        load_builder_provider_config,
    )

    root = write_private_builder(tmp_path / "cfg_ok")
    cfg = load_builder_provider_config(root)
    assert cfg["entrypoint_module"] == "builder_a"
    assert cfg["entrypoint_qualname"] == "build_pack"
    assert cfg["pair_count_per_family"] == 32
    assert cfg["max_attempts"] == 8
    assert "attempt_loop_module" not in cfg


def test_attempt_loop_fields_removed_with_migration_error(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = write_private_builder(tmp_path / "cfg_loop")
    cfg = json.loads((root / "provider_config.json").read_text())
    cfg["attempt_loop_module"] = "pack_selection"
    cfg["attempt_loop_qualname"] = "attempt_loop"
    (root / "provider_config.json").write_text(json.dumps(cfg))
    with pytest.raises(BuilderIdentityError, match="attempt_loop|废除"):
        load_builder_provider_config(root)


def test_unknown_field_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = write_private_builder(tmp_path / "cfg_unknown")
    cfg = json.loads((root / "provider_config.json").read_text())
    cfg["typo_field"] = 1
    (root / "provider_config.json").write_text(json.dumps(cfg))
    with pytest.raises(BuilderIdentityError, match="未知字段"):
        load_builder_provider_config(root)


def test_missing_required_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = write_private_builder(tmp_path / "cfg_missing")
    cfg = json.loads((root / "provider_config.json").read_text())
    del cfg["entrypoint_qualname"]
    (root / "provider_config.json").write_text(json.dumps(cfg))
    with pytest.raises(BuilderIdentityError, match="必填"):
        load_builder_provider_config(root)


def test_broken_json_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    root = write_private_builder(tmp_path / "cfg_broken")
    (root / "provider_config.json").write_text("{not json")
    with pytest.raises(BuilderIdentityError, match="解析"):
        load_builder_provider_config(root)


def test_missing_file_rejected(tmp_path):
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        load_builder_provider_config,
    )

    with pytest.raises(BuilderIdentityError, match="缺失"):
        load_builder_provider_config(tmp_path / "cfg_absent")


def test_cli_uses_same_config_path(tmp_path):
    """CLI(--builder-provider private)与测试共用同一 Provider 构造。"""
    root = write_private_builder(tmp_path / "cfg_cli")
    from rl_curriculum.builder_identity import (
        private_provider_from_config,
    )

    provider = private_provider_from_root(root)
    provider2 = private_provider_from_config(root)
    assert provider.builder_identity().manifest_hash == \
        provider2.builder_identity().manifest_hash


def test_provider_config_hash_stable(tmp_path):
    from rl_curriculum.builder_evidence import provider_config_hash

    root = write_private_builder(tmp_path / "cfg_hash")
    provider = private_provider_from_root(root)
    h1 = provider_config_hash(provider)
    h2 = provider_config_hash(provider)
    assert h1 == h2 and h1.startswith("pcf-")
