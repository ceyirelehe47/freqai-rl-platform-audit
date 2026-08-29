"""工作包 D6(D7-15/16/17)+ 阶段 2.6.0f 工作包 B:pack builder manifest
绑定真实 builder 的完整依赖闭包。

v2(null-pack-builder-manifest-v2)语义:
- npb- 绑定 builder package tree(root 下全部文件逐文件 sha256,排序
  稳定,额外文件不忽略)+ 显式外部依赖 manifest + 参数规范 + family
  列表 + attempt 上限 + 签名政策;
- 修改 builder 包内任意文件(assemble/validator/中间 helper/资源)
  -> npb- 变化;新增/删除文件 -> npb- 变化;
- builder 函数签名不得包含 candidate/checkpoint/model/policy
  (Provider 侧动态强制);
- 承诺与 pack validity 报告的 builder hash 必须来自同一 Provider。
"""

from __future__ import annotations

import json

import pytest


def _mock_identity():
    from rl_curriculum.builder_identity import (
        MockBuilderIdentityProvider,
    )

    return MockBuilderIdentityProvider().builder_identity()


def test_manifest_binds_full_package_tree_not_function_list():
    """v2:manifest 覆盖 builder package tree(不再手工挑选函数清单)。"""
    m = _mock_identity().manifest
    assert m["format"] == "null-pack-builder-manifest-v5"
    tree = m["package_tree"]
    assert tree["entrypoint_module"] == "rl_curriculum.mock_sealed_exam"
    assert tree["entrypoint_qualname"] == "mock_build_pack"
    # v4:独立 attempt-loop 声明已废除(C2:attempt 循环由 build 入口
    # 内部的规范化 attempt log 运行证据证明)
    assert "attempt_loop_qualname" not in tree
    assert tree["file_count"] == len(tree["files"]) >= 1
    paths = [f["path"] for f in tree["files"]]
    # 实际 attempt 选择链的中间依赖全部进入 tree
    for must in ("mock_sealed_exam.py", "null_pack_validation.py",
                 "null_qualification_spec.py", "generators.py",
                 "param_resolution.py", "sealed_exam.py"):
        assert must in paths, must
    assert paths == sorted(paths)  # 排序稳定
    assert len(tree["tree_hash"]) == 64
    # 外部依赖 manifest 显式绑定(rl_platform tree + 运行时版本)
    deps = {d["module"]: d for d in m["external_dependencies"]}
    assert set(deps) >= {"rl_platform", "python", "numpy", "pandas"}
    assert len(deps["rl_platform"]["tree_hash"]) == 64
    assert m["max_attempts"] == 8
    assert m["pair_count_per_family"] == 32
    assert set(m["families"]) == {
        "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"}
    assert m["params_spec"]["flip_flag_key"] == "antithetic_flip"


def test_modifying_builder_package_file_changes_npb(tmp_path):
    """修改真实 builder package 文件(assemble 所在模块)-> npb- 变化
    (阶段 2.6.0f B4:真实文件修改 + Provider 重算,不依赖 monkeypatch)。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    src_root = tmp_path / "builder_a"
    src_root.mkdir()
    (src_root / "builder_a.py").write_text(
        "def assemble_private_pack(request):\n    return None\n",
        encoding="utf-8")
    (src_root / "helpers.py").write_text(
        "def seed_derivation(fam, attempt, n):\n    return list(range(n))\n",
        encoding="utf-8")
    prov = PrivateBuilderIdentityProvider(
        src_root, entrypoint_module="builder_a",
        entrypoint_qualname="assemble_private_pack")
    h0 = prov.builder_identity().manifest_hash
    # 修改 assemble 模块内容
    (src_root / "builder_a.py").write_text(
        "def assemble_private_pack(request):\n    return None  # altered\n",
        encoding="utf-8")
    h1 = prov.builder_identity().manifest_hash
    assert h0 != h1
    assert h1.startswith("npb-")


def test_modifying_intermediate_helper_changes_npb(tmp_path):
    """修改中间依赖 helper(_validate_pack_ephemeral 等所在链路的任意
    安全相关辅助模块)-> npb- 变化。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "builder_b"
    root.mkdir()
    (root / "entry.py").write_text("def assemble(request):\n    pass\n",
                                   encoding="utf-8")
    (root / "pack_validator.py").write_text(
        "def validate(episodes):\n    return True\n", encoding="utf-8")
    prov = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="assemble")
    h0 = prov.builder_identity().manifest_hash
    (root / "pack_validator.py").write_text(
        "def validate(episodes):\n    return False  # tampered\n",
        encoding="utf-8")
    h1 = prov.builder_identity().manifest_hash
    assert h0 != h1


def test_resource_file_changes_npb(tmp_path):
    """被 builder 读取的资源文件变化 -> npb- 变化(资源进入 hash)。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "builder_c"
    root.mkdir()
    (root / "entry.py").write_text("def assemble(request):\n    pass\n",
                                   encoding="utf-8")
    (root / "params.json").write_text('{"episode_bars": 96}\n',
                                      encoding="utf-8")
    prov = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="assemble")
    h0 = prov.builder_identity().manifest_hash
    (root / "params.json").write_text('{"episode_bars": 192}\n',
                                      encoding="utf-8")
    h1 = prov.builder_identity().manifest_hash
    assert h0 != h1


def test_adding_or_removing_package_file_changes_npb(tmp_path):
    """新增/删除 package 文件不能被静默忽略 -> npb- 变化。"""
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "builder_d"
    root.mkdir()
    (root / "entry.py").write_text("def assemble(request):\n    pass\n",
                                   encoding="utf-8")
    prov = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="assemble")
    h0 = prov.builder_identity().manifest_hash
    (root / "extra_module.py").write_text("X = 1\n", encoding="utf-8")
    h1 = prov.builder_identity().manifest_hash
    assert h0 != h1
    (root / "extra_module.py").unlink()
    h2 = prov.builder_identity().manifest_hash
    assert h2 == h0  # 删除后恢复原身份(确定性)


def test_symlink_in_builder_package_rejected(tmp_path):
    """builder package tree 内 symlink -> fail closed。"""
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        PrivateBuilderIdentityProvider,
    )

    root = tmp_path / "builder_e"
    root.mkdir()
    (root / "entry.py").write_text("def assemble(request):\n    pass\n",
                                   encoding="utf-8")
    target = tmp_path / "outside.py"
    target.write_text("SECRET = 1\n", encoding="utf-8")
    (root / "link.py").symlink_to(target)
    prov = PrivateBuilderIdentityProvider(
        root, entrypoint_module="entry", entrypoint_qualname="assemble")
    with pytest.raises(BuilderIdentityError, match="symlink"):
        prov.builder_identity()


def test_builder_signature_policy_enforced():
    """D7-17:builder 函数签名包含 candidate/checkpoint/model/policy
    时 Provider 拒绝(v1 语义在 Provider 侧保留动态强制)。"""
    from rl_curriculum.builder_identity import (
        BuilderIdentityError,
        check_builder_signature_policy,
    )

    def evil_assemble(*, candidate=None):
        return None

    def innocent_attempt(**kwargs):
        return None

    with pytest.raises(BuilderIdentityError, match="禁止参数.*candidate"):
        check_builder_signature_policy(evil_assemble, innocent_attempt)
    with pytest.raises(BuilderIdentityError, match="禁止参数"):
        check_builder_signature_policy(
            innocent_attempt, lambda checkpoint=None: None)


def test_manifest_deterministic_and_hash_stable():
    """manifest 确定可复现;canonical 哈希稳定。"""
    i1 = _mock_identity()
    i2 = _mock_identity()
    assert json.dumps(i1.manifest, sort_keys=True) == json.dumps(
        i2.manifest, sort_keys=True)
    assert i1.manifest_hash == i2.manifest_hash
    assert i1.manifest_hash.startswith("npb-")
    assert i1.pack_builder_code_hash == i1.manifest_hash
    assert i1.builder_protocol == "null-pack-builder-protocol-v3"


def test_manifest_binds_params_and_family_list():
    """参数规范与 family 列表进入 manifest(修改 pair 数/参数/family
    列表 -> npb- 变化由 canonical 内容承载)。"""
    import copy
    import hashlib

    identity = _mock_identity()
    m = identity.manifest
    tampered = copy.deepcopy(m)
    tampered["pair_count_per_family"] = 16
    h = "npb-" + hashlib.sha256(json.dumps(
        tampered, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert h != identity.manifest_hash
    assert m["params_spec"]["base_params"]["episode_bars"] == 96


def test_commitment_binds_manifest_hash(sealed_exam_env):
    """承诺的 pack_builder_code_hash == 当前 Provider builder 身份。"""
    c = sealed_exam_env["commitment"]
    identity = _mock_identity()
    assert c.pack_builder_code_hash == identity.manifest_hash
    assert c.pack_builder_code_hash.startswith("npb-")
    # pack validity 报告也携带同一 Provider 派生的 manifest 哈希
    assert sealed_exam_env["pack_validity_report"][
        "builder_manifest_hash"] == identity.manifest_hash
