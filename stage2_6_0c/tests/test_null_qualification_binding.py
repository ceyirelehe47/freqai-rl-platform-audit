"""阶段 2.6.0c 工作包 D:真实 Null 资格报告强制绑定。

覆盖:
- bool-only 绑定(只有 qualification_pass=true)被拒绝;
- 缺真实报告 payload 被拒绝;
- 报告 hash 被改 / payload 被篡改被拒绝;
- family/family_version/generator implementation/qualification code
  对账;
- fee/schema/timeframe/seed 对账;
- required checks 缺失或为 false 被拒绝;
- 未识别/缺失关键字段被拒绝;
- 资格报告与生成器绑定/资格考试代码的真实材料变化全部失效。
"""

from __future__ import annotations

import copy

import pytest

from rl_curriculum.null_qualification import (
    MIN_QUALIFICATION_SEEDS,
    NULL_BINDING_KEYS,
    NULL_REPORT_REQUIRED_KEYS,
    REQUIRED_NULL_CHECKS,
    build_null_qualification_bindings,
    qualification_report_hash,
    verify_null_qualification_bindings,
)

FAMILIES = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _verify_kwargs(sealed_exam_env):
    from rl_curriculum.generator_binding import generator_bindings

    env = sealed_exam_env
    return {
        "generator_bindings": generator_bindings(dict(env["registry"])),
        "observation_schema_hash": env["schema"].schema_hash(),
        "eval_config_manifest": env["eval_config"].manifest(),
        "timeframe": "15m",
    }


def _ok_bindings(sealed_exam_env):
    return copy.deepcopy(
        sealed_exam_env["commitment"].null_qualification_bindings)


def test_valid_bindings_verify(sealed_exam_env):
    report = verify_null_qualification_bindings(
        _ok_bindings(sealed_exam_env),
        required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert report["pass"], report["problems"]
    assert all(report["checks"].values())


def test_bindings_embed_full_report_payload(sealed_exam_env):
    """binding 携带完整 canonical 报告(payload 键集合精确)。"""
    bindings = _ok_bindings(sealed_exam_env)
    for fam in FAMILIES:
        bound = bindings[fam]
        assert set(bound) == set(NULL_BINDING_KEYS)
        payload = bound["report_payload"]
        assert set(payload) == set(NULL_REPORT_REQUIRED_KEYS)
        # 重算 hash 与绑定一致
        assert qualification_report_hash(payload) == bound["report_hash"]
        # 对账材料在报告内
        assert payload["generator_implementation_hash"].startswith("gi-")
        assert payload["qualification_code_hash"].startswith("nqc-")
        assert payload["observation_schema_hash"].startswith("o-")
        assert payload["eval_config_manifest"]["fee"] == 0.001
        assert set(payload["checks"]) == set(REQUIRED_NULL_CHECKS)


# ------------------------------------------------------ bool-only(D1)
def test_bool_only_binding_rejected(sealed_exam_env):
    """旧式 {qualification_pass: true} 布尔绑定被拒绝。"""
    bindings = _ok_bindings(sealed_exam_env)
    bindings["probe_null_sign"] = {"qualification_pass": True}
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("bool-only" in p or "v2 结构" in p
               for p in report["problems"])


def test_binding_with_pass_but_no_report_rejected(sealed_exam_env):
    """只有 qualification_pass=true 没有 report_payload 的绑定被拒。"""
    bindings = _ok_bindings(sealed_exam_env)
    bindings["probe_null_sign"] = {
        "family_version": "x", "qualification_pass": True,
        "report_hash": "nq-" + "0" * 64}
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("v2 结构" in p or "真实报告" in p
               for p in report["problems"])


def test_build_rejects_bool_only_shortcut(sealed_exam_env):
    """构建侧同样不存在占位通道:键集合不符直接失败。"""
    bad = {"probe_null_sign": {"qualification_pass": True}}
    with pytest.raises(Exception):
        build_null_qualification_bindings(bad)


# -------------------------------------------------------- 篡改矩阵(D4)
def test_report_hash_tampered_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    bindings["probe_null_sign"]["report_hash"] = "nq-" + "9" * 64
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("hash 与绑定记录不一致" in p for p in report["problems"])


def test_report_payload_tampered_rejected(sealed_exam_env):
    """payload 内容被改(如 fee)但保留旧 hash -> 重算 hash 不等。"""
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["eval_config_manifest"] = {
        **payload["eval_config_manifest"], "fee": 0.0005}
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("hash 与绑定记录不一致" in p for p in report["problems"])


def test_wrong_family_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["family"] = "probe_null_volstate"
    # 重算 hash 保持自洽(模拟攻击者重新打包一致报告)
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("family" in p for p in report["problems"])


def test_wrong_family_version_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["family_version"] = "probe-null-sign-v999"
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    bindings["probe_null_sign"]["family_version"] = "probe-null-sign-v999"
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("family_version" in p for p in report["problems"])


def test_generator_implementation_mismatch_rejected(sealed_exam_env):
    """Null 实现改变(generator_bindings 换新值)但报告未重新生成。"""
    env = sealed_exam_env
    kwargs = _verify_kwargs(env)
    kwargs["generator_bindings"] = copy.deepcopy(kwargs["generator_bindings"])
    kwargs["generator_bindings"]["probe_null_sign"][
        "implementation_hash"] = "gi-newimplementation" + "0" * 40
    report = verify_null_qualification_bindings(
        _ok_bindings(env), required_families=list(FAMILIES), **kwargs)
    assert not report["pass"]
    assert any("实现已改变但报告未重新生成" in p
               for p in report["problems"])


def test_qualification_code_change_invalidates_report(sealed_exam_env):
    """资格审查代码改变但报告未重新生成 -> 对账失败。"""
    from unittest.mock import patch

    import rl_curriculum.null_qualification as nq

    with patch.object(nq, "qualification_code_hash",
                      return_value="nqc-tampered"):
        report = verify_null_qualification_bindings(
            _ok_bindings(sealed_exam_env),
            required_families=list(FAMILIES),
            **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("资格审查代码已改变" in p for p in report["problems"])


def test_seed_count_insufficient_rejected(sealed_exam_env):
    """报告 seed 数不足(MIN_QUALIFICATION_SEEDS)被拒。"""
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["seeds"] = [11, 22]
    payload["distinct_seeds"] = 2
    payload["checks"]["multi_seed_coverage"] = True  # 伪造通过
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("seed 数不足" in p for p in report["problems"])


def test_seed_distinct_inconsistency_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["distinct_seeds"] = 9  # 与 seeds 去重数矛盾
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("distinct_seeds" in p for p in report["problems"])


def test_fee_mismatch_rejected(sealed_exam_env):
    """报告的 fee(经 EvalConfig manifest)与本次考试不一致被拒。"""
    env = sealed_exam_env
    kwargs = _verify_kwargs(env)
    kwargs["eval_config_manifest"] = {
        **kwargs["eval_config_manifest"], "fee": 0.002}
    report = verify_null_qualification_bindings(
        _ok_bindings(env), required_families=list(FAMILIES), **kwargs)
    assert not report["pass"]
    assert any("fee" in p for p in report["problems"])


def test_schema_mismatch_rejected(sealed_exam_env):
    env = sealed_exam_env
    kwargs = _verify_kwargs(env)
    kwargs["observation_schema_hash"] = "os-different-schema"
    report = verify_null_qualification_bindings(
        _ok_bindings(env), required_families=list(FAMILIES), **kwargs)
    assert not report["pass"]
    assert any("Observation Schema" in p for p in report["problems"])


def test_timeframe_mismatch_rejected(sealed_exam_env):
    env = sealed_exam_env
    kwargs = _verify_kwargs(env)
    kwargs["timeframe"] = "1h"
    report = verify_null_qualification_bindings(
        _ok_bindings(env), required_families=list(FAMILIES), **kwargs)
    assert not report["pass"]
    assert any("timeframe" in p for p in report["problems"])


def test_missing_required_check_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    del payload["checks"]["multi_seed_coverage"]
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("checks 键集合" in p for p in report["problems"])


def test_false_required_check_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["checks"]["oracle_no_stable_directional_edge"] = False
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("未通过的检查" in p for p in report["problems"])


def test_unrecognized_report_fields_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["attacker_note"] = "trust me"
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("未识别" in p for p in report["problems"])


def test_missing_report_field_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    del payload["qualification_code_hash"]
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("缺失" in p for p in report["problems"])


def test_report_pass_false_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    payload = bindings["probe_null_sign"]["report_payload"]
    payload["pass"] = False
    bindings["probe_null_sign"]["qualification_pass"] = False
    bindings["probe_null_sign"]["report_hash"] = \
        qualification_report_hash(payload)
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("pass" in p for p in report["problems"])


def test_missing_family_binding_rejected(sealed_exam_env):
    bindings = _ok_bindings(sealed_exam_env)
    del bindings["probe_null_stochvol"]
    report = verify_null_qualification_bindings(
        bindings, required_families=list(FAMILIES),
        **_verify_kwargs(sealed_exam_env))
    assert not report["pass"]
    assert any("未绑定" in p for p in report["problems"])


# ------------------------------------------------------- 报告真实生成(D2)
def test_real_reports_carry_full_reconciliation_material(
        null_qual_reports):
    """真实生成的报告内嵌全部对账材料(每族)。"""
    for fam, report in null_qual_reports.items():
        assert set(report) == set(NULL_REPORT_REQUIRED_KEYS)
        assert report["format"] == "null-qualification-v2"
        assert report["distinct_seeds"] >= MIN_QUALIFICATION_SEEDS
        assert set(report["checks"]) == set(REQUIRED_NULL_CHECKS)
        assert report["pass"] is True
        assert report["qualification_params"][
            "min_distinct_qualification_seeds"] == MIN_QUALIFICATION_SEEDS


def test_null_generator_change_invalidates_old_report(
        null_qual_reports, sealed_exam_env):
    """Null 生成器实现变化(implementation hash)后旧报告对账失败:
    报告记录的 implementation hash 与新绑定不一致(D3)。"""
    env = sealed_exam_env
    from rl_curriculum.generator_binding import (
        implementation_manifest,
    )

    # 用被"替换实现"的哈希构造新绑定(模拟 Null 实现已变)
    new_bindings = copy.deepcopy(_verify_kwargs(env)["generator_bindings"])
    m = implementation_manifest(env["registry"]["probe_null_sign"])
    del m  # 真实实现仍在;直接改绑定值模拟实现变化
    new_bindings["probe_null_sign"]["implementation_hash"] = \
        "gi-replaced-" + "7" * 50
    kwargs = _verify_kwargs(env)
    kwargs["generator_bindings"] = new_bindings
    report = verify_null_qualification_bindings(
        _ok_bindings(env), required_families=list(FAMILIES), **kwargs)
    assert not report["pass"]
    assert any("实现已改变但报告未重新生成" in p
               for p in report["problems"])
