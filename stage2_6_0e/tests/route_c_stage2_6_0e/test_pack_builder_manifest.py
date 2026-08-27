"""工作包 D6(D7-15/16/17):pack builder manifest 绑定真实 builder。

npb- 必须绑定真正构造 EpisodeSpec 的 builder 函数 / seed namespace
推导 / pair 顺序 / attempt 循环 / 匿名拒绝日志 / validator / 参数规范
/ family 列表;修改 builder 或 validator 都改变 npb-;builder 签名不得
包含 candidate/checkpoint/model/policy。
"""

from __future__ import annotations

import inspect
import json

import pytest

from rl_curriculum.null_pack_validation import (
    PACK_BUILDER_MANIFEST_FORMAT,
    pack_builder_code_hash,
    pack_builder_manifest,
    pack_builder_manifest_hash,
)


def test_manifest_binds_real_builder_not_validator_file_only():
    """D6:manifest 覆盖真实 builder(assemble)而非只哈希 validator
    所在文件——各函数绑定含模块/限定名/源码哈希。"""
    m = pack_builder_manifest()
    assert m["format"] == PACK_BUILDER_MANIFEST_FORMAT
    assert m["builder_function"]["module"] == "rl_curriculum.mock_sealed_exam"
    assert m["builder_function"]["qualname"] == \
        "assemble_mock_hidden_pack"
    assert len(m["builder_function"]["source_sha256"]) == 64
    assert m["attempt_loop"]["qualname"] == "build_mock_hidden_pack"
    assert {b["qualname"] for b in m["seed_namespace_derivation"]} == {
        "qualification_seeds", "pack_construction_seeds"}
    assert m["pair_order_derivation"]["qualname"] == "pack_order_seed"
    assert m["pack_validator"]["qualname"] == "validate_null_pack"
    assert m["anonymous_reject_log_generator"]["qualname"] == \
        "pack_builder_attempt_log"
    assert m["max_attempts"] == 8
    assert m["pair_count_per_family"] == 32
    assert set(m["families"]) == {
        "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"}
    assert m["params_spec"]["flip_flag_key"] == "antithetic_flip"


def test_modifying_builder_changes_npb(monkeypatch):
    """D7-15:修改 actual builder(assemble 函数源码)-> npb- 变化。"""
    h0 = pack_builder_manifest_hash()

    def fake_assemble(**kwargs):
        return None

    fake_assemble.__module__ = "rl_curriculum.mock_sealed_exam"
    fake_assemble.__qualname__ = "assemble_mock_hidden_pack"
    # 构造不同源码的"被改 builder"
    src = inspect.getsource(
        __import__("rl_curriculum.mock_sealed_exam",
                   fromlist=["assemble_mock_hidden_pack"]
                   ).assemble_mock_hidden_pack)
    altered = src.replace('add("probe_segmented_drift", BASE_PARAMS',
                          'add("probe_segmented_drift", dict(BASE_PARAMS)')

    def fake_with_source():
        return None

    monkeypatch.setattr(
        "rl_curriculum.null_pack_validation._fn_binding",
        lambda fn: {"module": fn.__module__,
                    "qualname": fn.__qualname__,
                    "source_sha256": __import__("hashlib").sha256(
                        (altered if fn.__qualname__
                         == "assemble_mock_hidden_pack"
                         else inspect.getsource(fn)).encode(
                            "utf-8")).hexdigest()})
    h1 = pack_builder_manifest_hash()
    assert h1 != h0
    assert h1.startswith("npb-")


def test_modifying_validator_changes_npb(monkeypatch):
    """D7-16:只修改 validator -> npb- 变化。"""
    h0 = pack_builder_manifest_hash()

    def tampered_binding(fn):
        import hashlib
        import inspect as _i

        src = _i.getsource(fn)
        if fn.__qualname__ == "validate_null_pack":
            src = src + "\n# altered\n"
        return {"module": fn.__module__, "qualname": fn.__qualname__,
                "source_sha256": hashlib.sha256(
                    src.encode("utf-8")).hexdigest()}

    monkeypatch.setattr(
        "rl_curriculum.null_pack_validation._fn_binding", tampered_binding)
    h1 = pack_builder_manifest_hash()
    assert h1 != h0


def test_builder_signature_policy_enforced():
    """D7-17:builder 函数签名包含 candidate/checkpoint/model/policy
    时拒绝构建 manifest(fail closed)。"""
    def evil_assemble(*, candidate=None):
        return None

    def innocent_attempt(**kwargs):
        return None

    with pytest.raises(ValueError, match="禁止参数.*candidate"):
        pack_builder_manifest(builder_fn=evil_assemble,
                              attempt_fn=innocent_attempt)
    with pytest.raises(ValueError, match="禁止参数"):
        pack_builder_manifest(
            builder_fn=innocent_attempt,
            attempt_fn=lambda checkpoint=None: None)


def test_manifest_deterministic_and_hash_stable():
    """manifest 确定可复现;canonical 哈希稳定。"""
    m1 = pack_builder_manifest()
    m2 = pack_builder_manifest()
    assert json.dumps(m1, sort_keys=True) == json.dumps(m2, sort_keys=True)
    assert pack_builder_manifest_hash() == pack_builder_manifest_hash()
    assert pack_builder_code_hash() == pack_builder_manifest_hash()


def test_manifest_binds_params_and_family_list():
    """参数规范与 family 列表进入 manifest(修改 pair 数/参数/family
    列表 -> npb- 变化由 canonical 内容承载)。"""
    m = pack_builder_manifest()
    import hashlib

    tampered = dict(m)
    tampered["pair_count_per_family"] = 16
    h = "npb-" + hashlib.sha256(json.dumps(
        tampered, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert h != pack_builder_manifest_hash()
    assert m["params_spec"]["base_params"]["episode_bars"] == 96


def test_commitment_binds_manifest_hash(sealed_exam_env):
    """承诺的 pack_builder_code_hash == 当前 builder manifest 哈希。"""
    c = sealed_exam_env["commitment"]
    assert c.pack_builder_code_hash == pack_builder_manifest_hash()
    assert c.pack_builder_code_hash.startswith("npb-")
    # pack validity 报告也携带同一 manifest 哈希
    assert sealed_exam_env["pack_validity_report"][
        "builder_manifest_hash"] == pack_builder_manifest_hash()
