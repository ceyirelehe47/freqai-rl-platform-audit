"""工作包 B:builder 完整依赖闭包(package tree + 外部依赖 manifest)。

- 实际 package tree 绑定:修改任意安全相关辅助模块/资源/参数/family
  列表/attempt 上限都会改变 npb-;
- 修改 _validate_pack_ephemeral / build_spec_for_pack 所在链路的
  中间验证 helper -> 旧承诺失效;
- pack validity report 使用实际 Provider 派生的 builder hash
  (承诺/报告/verifier 三方一致);
- mock builder tree 覆盖完整 rl_curriculum 包(中间依赖不可遗漏)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.route_c_stage2_6_0f.conftest import write_private_builder


def _private_provider(root, **kw):
    from rl_curriculum.builder_identity import (
        PrivateBuilderIdentityProvider,
    )

    defaults = dict(entrypoint_module="builder_a",
                    entrypoint_qualname="build_pack")
    defaults.update(kw)
    return PrivateBuilderIdentityProvider(root, **defaults)


def test_tree_binds_every_file_in_builder_root(tmp_path):
    """package tree 覆盖 root 下全部文件(含资源),排序稳定。"""
    root = write_private_builder(tmp_path / "pb")
    prov = _private_provider(root)
    identity = prov.builder_identity()
    files = identity.manifest["package_tree"]["files"]
    names = {f["path"] for f in files}
    expected = {"builder_a.py", "helpers.py", "pack_selection.py",
                "params.json", "provider_config.json"}
    assert expected <= names
    assert [f["path"] for f in files] == sorted(f["path"] for f in files)
    for f in files:
        assert len(f["sha256"]) == 64
        assert f["bytes"] > 0


def test_tamper_matrix_changes_npb(tmp_path):
    """篡改矩阵:修改任一安全相关内容 -> npb- 变化(真实文件修改 +
    Provider 重算,非 monkeypatch)。"""
    import copy

    cases = {
        "assemble 函数": ("builder_a.py", "def build_pack(request):",
                          "def build_pack_altered(request):"),
        "attempt 选择链 helper": ("pack_selection.py",
                                   "validate_pack_ephemeral",
                                   "validate_pack_ephemeral_v2"),
        "seed 推导 salt": ("helpers.py", "PACK_CONSTRUCTION_SALT",
                            "PACK_CONSTRUCTION_SALT_V2"),
        "资源文件": ("params.json", '"episode_bars": 96',
                       '"episode_bars": 192'),
    }
    results = {}
    for label, (fname, old, new) in cases.items():
        root = write_private_builder(tmp_path / f"pb_{label}")
        prov = _private_provider(root)
        h0 = prov.builder_identity().manifest_hash
        p = root / fname
        content = p.read_text(encoding="utf-8")
        assert old in content, (fname, old)
        p.write_text(content.replace(old, new), encoding="utf-8")
        h1 = prov.builder_identity().manifest_hash
        results[label] = (h0 != h1)
        assert h0 != h1, label
    # 全部 4 类篡改都改变 npb-
    assert all(results.values()) and len(results) == 4


def test_builder_manifest_semantic_fields_change_npb(tmp_path):
    """BASE_PARAMS / family 列表 / attempt max 变化 -> npb- 变化。"""
    root = write_private_builder(tmp_path / "pb_sem")
    prov0 = _private_provider(root)
    h0 = prov0.builder_identity().manifest_hash
    prov1 = _private_provider(
        root, params_spec={"base_params": {"episode_bars": 192},
                           "flip_flag_key": "antithetic_flip",
                           "episode_bars": 192})
    h1 = prov1.builder_identity().manifest_hash
    prov2 = _private_provider(
        root, families=["probe_null_sign", "probe_null_volstate"])
    h2 = prov2.builder_identity().manifest_hash
    prov3 = _private_provider(root, max_attempts=4)
    h3 = prov3.builder_identity().manifest_hash
    assert len({h0, h1, h2, h3}) == 4


def test_external_dependency_change_changes_npb(tmp_path):
    """显式外部依赖 manifest 变化 -> npb- 变化(依赖身份绑定)。"""
    root = write_private_builder(tmp_path / "pb_dep")
    prov0 = _private_provider(root, external_dependencies=[])
    prov1 = _private_provider(
        root, external_dependencies=[
            {"module": "python", "kind": "runtime_version",
             "version": "3.11.0", "implementation": "CPython"}])
    h0 = prov0.builder_identity().manifest_hash
    h1 = prov1.builder_identity().manifest_hash
    assert h0 != h1


def test_mock_tree_covers_intermediate_helpers(mock_identity):
    """mock builder tree 覆盖实际 attempt 选择链的中间依赖文件
    (_validate_pack_ephemeral / build_spec_for_pack / null materialization
    / seed 推导 / pair 顺序 / validator / 参数与 family 配置)。"""
    files = {f["path"] for f in mock_identity.manifest[
        "package_tree"]["files"]}
    for must in ("mock_sealed_exam.py",          # assemble/attempt/_validate
                 "null_pack_validation.py",       # validator/build_spec
                 "null_qualification_spec.py",    # seed/pair/常量
                 "generators.py",                 # null family 真源
                 "generator_api.py",              # EpisodeSpec/物化
                 "param_resolution.py",           # duration 解析
                 "null_qualification.py"):        # 资格材料
        assert must in files, must
    # manifest 的 family 列表与生成器真源一致(单一事实来源对齐)
    from rl_curriculum.generators import FORMAL_NULL_FAMILIES

    assert set(mock_identity.manifest["families"]) == set(
        FORMAL_NULL_FAMILIES)


def test_pack_validity_report_uses_provider_hash(sealed_exam_env,
                                                 mock_identity,
                                                 pack_validity_report):
    """pack validity report 的 builder_manifest_hash 来自实际 Provider
    (承诺/报告/verifier 三方一致;B3)。"""
    env = sealed_exam_env
    assert pack_validity_report[
        "builder_manifest_hash"] == mock_identity.manifest_hash
    assert env["commitment"].pack_builder_code_hash == (
        mock_identity.manifest_hash)
    # 执行器路径(verify)同样对账通过
    from compat_stage2_6_0f import default_duration_contract

    from rl_curriculum.sealed_exam import verify_sealed_commitment

    report = verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"], registry=env["registry"],
        eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
        sandbox_profile=env["profile"],
        builder_identity=mock_identity,
        duration_contract=default_duration_contract())
    assert report["checks"]["pack_builder_code_hash"] is True


def test_modifying_mock_builder_intermediate_helper_invalidates_commitment(
        sealed_exam_env, monkeypatch, mock_identity, duration_contract):
    """修改 mock builder 包内中间 helper(等价 _validate_pack_ephemeral
    链路)后,同一承诺不再通过 verify(旧承诺失效)。

    通过临时改写 tree 扫描输入(真实文件内容的受控副本)证明:npb-
    变化 -> verify 12b 拒绝。不修改真实源文件(受控等价:Provider 对
    tree 文件集合的读取结果注入一个被改文件的哈希)。
    """
    from rl_curriculum.builder_identity import MockBuilderIdentityProvider
    from rl_curriculum.sealed_exam import SealedExamError

    env = sealed_exam_env
    original = MockBuilderIdentityProvider.builder_identity

    class TamperedProvider(MockBuilderIdentityProvider):
        def builder_identity(self):
            ident = original(self)
            manifest = json.loads(json.dumps(ident.manifest))
            for f in manifest["package_tree"]["files"]:
                if f["path"] == "null_pack_validation.py":
                    # 等价于修改 validator(中间验证 helper)文件内容
                    f["sha256"] = ("0" * 64)
                    break
            from rl_curriculum.builder_identity import (
                BuilderIdentity,
                canonical_builder_manifest_hash,
            )

            new_hash = canonical_builder_manifest_hash(manifest)
            return BuilderIdentity(
                manifest=manifest, manifest_hash=new_hash,
                builder_protocol=manifest["builder_protocol"])

    tampered_identity = TamperedProvider().builder_identity()
    assert tampered_identity.manifest_hash != (
        env["commitment"].pack_builder_code_hash)
    with pytest.raises(SealedExamError, match="manifest|构建算法"):
        from rl_curriculum.sealed_exam import verify_sealed_commitment

        verify_sealed_commitment(
            env["commitment"], pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=env["profile"],
            builder_identity=tampered_identity,
            duration_contract=duration_contract)
