"""工作包 C(C1-C4):正式执行器对完整 power report 的重跑验证与
攻击矩阵。

任务书 C4 的 14 类攻击全部必须被拒绝(public summary 不是信任源;
npa- 哈希重算对账;scenario manifest/MC 配置/比例置信界核验;
power 代码与 family 报告变化 -> 旧报告失效;v1 报告拒绝)。
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

from rl_curriculum.null_power_analysis import power_analysis_report_hash
from rl_curriculum.null_power_reverification import (
    reverify_committed_power_analysis,
)
from rl_curriculum.null_qualification import qualification_report_hash
from rl_curriculum.null_qualification_spec import (
    POWER_SCENARIO_MANIFEST,
    scenario_manifest_hash,
)

FAMS = ["probe_null_sign", "probe_null_volstate", "probe_null_stochvol"]


def _reverify(sealed_exam_env, mutate=None, *, commitment=None) -> dict:
    from rl_curriculum.sealed_exam import SealedExamCommitment

    if commitment is None:
        data = json.loads(sealed_exam_env["commitment"].to_json())
        if mutate is not None:
            mutate(data)
        commitment = SealedExamCommitment.from_json(json.dumps(data))
    env = sealed_exam_env
    return reverify_committed_power_analysis(
        commitment=commitment, eval_config=env["eval_config"],
        timeframe="15m", episode_bars=96, required_families=FAMS)


def test_valid_commitment_passes_reverification(sealed_exam_env):
    """基线:合法承诺的完整重跑验证全过(缓存命中也验证内容哈希)。"""
    r = _reverify(sealed_exam_env)
    assert r["pass"] is True, r["problems"]
    assert r["targets_met"] is True
    r2 = _reverify(sealed_exam_env)
    assert r2["pass"] is True  # 第二次命中可信缓存


def test_attack_1_public_summary_tampered(sealed_exam_env):
    """C4-1:只改 public_summary 的任何字段 -> from_json 结构拒绝
    (targets_met=false)或与完整报告重派生值不一致 -> 拒绝(摘要不是
    信任源)。"""
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    data = json.loads(sealed_exam_env["commitment"].to_json())
    data["null_power_analysis"]["public_summary"]["targets_met"] = False
    with pytest.raises(SealedExamError, match="完整功效分析"):
        SealedExamCommitment.from_json(json.dumps(data))

    for field, value in (
        ("max_false_invalid_at_zero", 0.123456),
        ("min_rejection_power_at_1x_margin", 0.654321),
        ("required_scenario_count", 999),
        ("min_qualification_clusters", 32),
    ):
        def mutate(data, f=field, v=value):
            data["null_power_analysis"]["public_summary"][f] = v

        r = _reverify(sealed_exam_env, mutate)
        assert not r["pass"], (field, r["problems"])
        assert any("public_summary" in p or "摘要" in p
                   for p in r["problems"]), (field, r["problems"])


def test_attack_2_forged_npa_string(sealed_exam_env):
    """C4-2:伪造 npa- 格式字符串 -> 重跑哈希不匹配。"""
    def mutate(data):
        data["null_power_analysis"]["report_hash"] = \
            "npa-" + "f" * 64

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_report_hash"] is False


@pytest.mark.parametrize("drop", ["oracle", "rule_trend",
                                  "high_turnover_vs_flat"])
def test_attack_3_4_5_missing_required_scenarios(sealed_exam_env, drop):
    """C4-3/4/5:场景清单缺 Oracle/Rule/HFT 场景(以删除对应场景的
    篡改清单哈希注入承诺)-> scenario manifest 校验拒绝。"""
    tampered = copy.deepcopy(POWER_SCENARIO_MANIFEST)
    tampered["blocks"][drop]["scenarios"] = \
        tampered["blocks"][drop]["scenarios"][:-1]
    forged = "npss-" + hashlib.sha256(json.dumps(
        tampered, sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")).hexdigest()
    assert forged != scenario_manifest_hash()

    def mutate(data):
        data["null_power_analysis"]["scenario_spec_hash"] = forged

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_scenario_manifest"] is False


@pytest.mark.parametrize("field,value", [
    # C4-6:报告 target edge 被改(场景 target 定义被改写)
    ("margin", 0.001999),
    # C4-7:报告 tolerance 被改
    ("tolerance_by_block", {"always_long_vs_flat": 0.004,
                            "oracle": 0.0019980019980019303,
                            "rule_trend": 0.0019980019980019303,
                            "high_turnover_vs_flat": 0.001}),
    # C4-8:报告 MC seed 被改
    ("mc_seed", 99999999),
    # C4-9:报告 cluster 数被改
    ("min_qualification_clusters", 32),
    # C4-10:报告比例置信方法被改
    ("confidence_method", "clopper-pearson-hoaxed"),
])
def test_attack_6_to_10_report_fields_tampered(
        sealed_exam_env, field, value):
    """C4-6..10:篡改完整报告的 target/tolerance/MC seed/cluster 数/
    置信方法,并重算其哈希注入承诺(自洽伪造)-> 执行器按当前材料
    重跑产生原始报告 -> 哈希不匹配,拒绝。"""
    env = sealed_exam_env

    def mutate(data):
        report = copy.deepcopy(env["power_report"])
        report[field] = value
        data["null_power_analysis"]["report_hash"] = \
            power_analysis_report_hash(report)
        # 摘要与被篡改报告保持一致(更强攻击:摘要自洽)
        data["null_power_analysis"]["public_summary"] = {
            "margin": report.get("margin"),
            "min_qualification_clusters": report.get(
                "min_qualification_clusters"),
            "targets_met": bool(report["targets"]["targets_met"]),
            "required_scenario_count": report.get(
                "required_scenario_count"),
            "max_false_invalid_at_zero": report.get(
                "targets", {}).get("max_false_invalid_at_zero"),
            "max_false_qualified_at_2x_margin": report.get(
                "targets", {}).get("max_false_qualified_at_2x_margin"),
            "min_rejection_power_at_1x_margin": report.get(
                "targets", {}).get("min_rejection_power_at_1x_margin"),
        }

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"], (field, r["problems"])
    assert r["checks"]["power_report_hash"] is False


def test_attack_11_report_hash_content_mismatch(sealed_exam_env):
    """C4-11:报告 hash 与内容不符(注入另一合法报告的哈希)。"""
    other = copy.deepcopy(sealed_exam_env["power_report"])
    other["scenarios"] = other["scenarios"][:-1]

    def mutate(data):
        data["null_power_analysis"]["report_hash"] = \
            power_analysis_report_hash(other)

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_report_hash"] is False


def test_attack_12_power_code_changed_report_stale(sealed_exam_env):
    """C4-12:power code 改变但报告未重跑 -> code hash 与当前实现
    不一致,拒绝。"""
    def mutate(data):
        data["null_power_analysis"]["code_hash"] = "npac-" + "a" * 64

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_code_hash"] is False


def test_attack_13_family_cluster_values_changed(sealed_exam_env):
    """C4-13:family 报告 cluster values 被改(并重算 nq- 哈希使绑定
    自洽)但 power 报告未重跑 -> 执行器从被改材料重跑 -> npa- 不匹配。"""
    def mutate(data):
        payload = data["null_qualification_bindings"]["probe_null_sign"][
            "report_payload"]
        cv = payload["always_long_vs_flat"]["cluster_values"]
        cv[0] = float(cv[0]) + 0.01  # 注入显著优势
        data["null_qualification_bindings"]["probe_null_sign"][
            "report_hash"] = qualification_report_hash(payload)

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_report_hash"] is False


def test_attack_14_legacy_v1_power_report_rejected(sealed_exam_env):
    """C4-14:旧 null-power-analysis-v1 报告(未中心化/只覆盖 Always
    Long/点估计)被新执行器拒绝。"""
    def mutate(data):
        report = copy.deepcopy(sealed_exam_env["power_report"])
        report["format"] = "null-power-analysis-v1"
        data["null_power_analysis"]["report_hash"] = \
            power_analysis_report_hash(report)

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert r["checks"]["power_report_hash"] is False


def test_missing_family_payload_fails(sealed_exam_env):
    """缺任一 family 的完整报告 payload -> 无法重跑 -> 拒绝。"""
    def mutate(data):
        data["null_qualification_bindings"]["probe_null_stochvol"] = {
            "qualification_pass": True}

    r = _reverify(sealed_exam_env, mutate)
    assert not r["pass"]
    assert any("完整资格报告 payload" in p for p in r["problems"])


def test_full_sealed_verification_rejects_power_tamper(sealed_exam_env):
    """完整 verify_sealed_commitment 层:power 报告篡改 -> SealedExamError
    (EXAM_INVALID;与单元层一致的攻击面)。"""
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
        verify_sealed_commitment,
    )

    env = sealed_exam_env
    data = json.loads(env["commitment"].to_json())
    report = copy.deepcopy(env["power_report"])
    report["mc_seed"] = 12345
    data["null_power_analysis"]["report_hash"] = power_analysis_report_hash(
        report)
    c = SealedExamCommitment.from_json(json.dumps(data))
    with pytest.raises(SealedExamError, match="power|功效"):
        verify_sealed_commitment(
            c, pack=env["pack"], charter=env["charter"],
            schema=env["schema"], registry=env["registry"],
            eval_config=env["eval_config"], verdict_spec=env["verdict_spec"],
            sandbox_profile=default_sandbox_profile())


def test_cache_content_hash_verified(sealed_exam_env, monkeypatch, tmp_path):
    """缓存命中后仍验证内容哈希:被篡改的缓存文件 -> 重建而非采用。"""
    from rl_curriculum import null_power_reverification as npr

    # 先填缓存
    r = _reverify(sealed_exam_env)
    assert r["pass"]
    cache_files = sorted(npr._cache_root().glob("*.json"))
    assert cache_files
    # 篡改缓存报告内容(保持 report_hash 字段不变 -> 内容哈希不符)
    victim = cache_files[-1]
    cached = json.loads(victim.read_text(encoding="utf-8"))
    cached["report"]["margin"] = 0.42
    victim.write_text(json.dumps(cached, sort_keys=True,
                                 ensure_ascii=False), encoding="utf-8")
    r2 = _reverify(sealed_exam_env)
    assert r2["pass"] is True  # 篡改被识别 -> 重跑 -> 仍通过
