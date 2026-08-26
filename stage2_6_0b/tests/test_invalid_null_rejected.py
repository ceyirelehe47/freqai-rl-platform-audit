"""工作包 H3/H5:无效 Null(残留漂移/残留可预测性)被拒绝;
修改 Null 实现使原资格证明失效。"""

from __future__ import annotations

import pytest

from rl_curriculum.null_qualification import (
    qualify_null_family,
    qualification_code_hash,
    qualification_report_hash,
    verify_null_qualification_bindings,
)


def _qualify(generator, params=None, seeds=(11, 22, 33)):
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS, default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    return qualify_null_family(
        generator, params=params or dict(BASE_PARAMS), timeframe="15m",
        seeds=list(seeds), cfg=default_eval_config(),
        schema=probe_observation_schema())


def test_drifting_pseudo_null_rejected():
    """残留漂移的伪 Null(direction_weights 偏多 + 不做方向随机化)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    params = {"episode_bars": 96, "direction_weights": [0.0, 0.85, 0.15]}
    rep = _qualify(ProbeSegmentedDriftGenerator(), params=params)
    assert not rep["pass"]
    assert rep["reasons"]


def test_predictable_pseudo_null_rejected():
    """探针 A 冒充 Null:Oracle 在其上有稳定方向优势 -> INVALID_NULL。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    rep = _qualify(ProbeSegmentedDriftGenerator(),
                   seeds=(101, 102, 103, 104, 105, 106))
    assert not rep["pass"]


def test_unpassed_null_cannot_enter_exam(null_qual_reports):
    """qualification_pass=false 的族被 verify 拒绝(不得进入正式硬门)。"""
    from rl_curriculum.null_qualification import build_null_qualification_bindings

    bad = {**null_qual_reports}
    bad["probe_null_sign"] = dict(null_qual_reports["probe_null_sign"])
    bad["probe_null_sign"]["pass"] = False
    bindings = build_null_qualification_bindings(bad)
    report = verify_null_qualification_bindings(
        bindings, required_families=[
            "probe_null_sign", "probe_null_volstate", "probe_null_stochvol"])
    assert not report["pass"]
    assert any("未通过资格审查" in p for p in report["problems"])


def test_missing_binding_rejected():
    report = verify_null_qualification_bindings(
        {}, required_families=["probe_null_sign"])
    assert not report["pass"]
    assert any("未绑定" in p for p in report["problems"])


def test_implementation_change_invalidates_qualification(null_qual_reports):
    """H5:修改 Null 实现 -> 报告哈希仍旧但实现哈希变化 -> 承诺的
    implementation_hash 校验失败(资格证明对实现失效)。"""
    from rl_curriculum.generator_binding import (
        implementation_manifest,
        verify_generator_bindings,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    bindings = {}
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        m = implementation_manifest(R[fam])
        bindings[fam] = {
            "family_version": m["family_version"],
            "implementation_hash": m["implementation_hash"],
            "manifest_hash": __import__("hashlib").sha256(
                __import__("json").dumps(m, sort_keys=True,
                                         separators=(",", ":")).encode()
            ).hexdigest(),
        }
    # 正常通过
    ok = verify_generator_bindings(
        dict(R), bindings, required_families=sorted(bindings))
    assert ok["pass"]
    # 模拟实现被替换:expected 哈希被换成旧值
    tampered = dict(bindings)
    tampered["probe_null_sign"] = {
        **bindings["probe_null_sign"],
        "implementation_hash": "gi-" + "9" * 64}
    bad = verify_generator_bindings(
        dict(R), tampered, required_families=sorted(bindings))
    assert not bad["pass"]
    assert any("实现哈希不匹配" in p for p in bad["problems"])


def test_qualification_report_hash_and_code_hash():
    rep = {"format": "null-qualification-v1", "pass": True,
           "checks": {}, "family": "x"}
    assert qualification_report_hash(rep).startswith("nq-")
    assert qualification_code_hash().startswith("nqc-")
