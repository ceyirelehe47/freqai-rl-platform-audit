"""工作包 G/M:判定器哈希绑定(规则被替换即 EXAM_INVALID)。"""

from __future__ import annotations

import json

import pytest

from rl_curriculum.sealed_exam import SealedExamError, verify_sealed_commitment
from rl_curriculum.verdict_spec import CourseVerdictSpec, probe_course_verdict_spec
from tests.route_c_stage2_6_0a.conftest import run_cli


def _verify(env, verdict_spec=None):
    return verify_sealed_commitment(
        env["commitment"], pack=env["pack"], charter=env["charter"],
        schema=env["schema"],
        registry=__import__("rl_curriculum.generators", fromlist=["x"])
        .DEFAULT_GENERATOR_REGISTRY,
        eval_config=env["eval_config"],
        verdict_spec=verdict_spec or probe_course_verdict_spec())


def test_verdict_hash_binding(sealed_exam_env):
    report = _verify(sealed_exam_env)
    assert report["checks"]["verdict_spec_hash"] is True


def test_changed_threshold_rejected_unit(sealed_exam_env):
    """阈值变化 -> 新判定器哈希 -> 旧承诺拒绝(单元级)。"""
    changed = CourseVerdictSpec(
        version=probe_course_verdict_spec().version,
        min_effective_net_return=0.5)
    with pytest.raises(SealedExamError, match="判定器哈希"):
        _verify(sealed_exam_env, verdict_spec=changed)


def test_missing_required_counterfactual_list_rejected(sealed_exam_env):
    changed = CourseVerdictSpec(
        version=probe_course_verdict_spec().version,
        required_counterfactuals=("only_one_exam",))
    with pytest.raises(SealedExamError, match="判定器哈希"):
        _verify(sealed_exam_env, verdict_spec=changed)


def test_verdict_hash_tamper_rejected_cli(sealed_exam_env):
    tmp = sealed_exam_env["tmp"]
    data = json.loads((tmp / "commitment.json").read_text())
    data["verdict_spec_hash"] = "v-tampered"
    (tmp / "commitment.json").write_text(json.dumps(data, ensure_ascii=False))
    rc = run_cli(sealed_exam_env, "out.json")
    assert rc == 5
    out = json.loads((tmp / "out.json").read_text())
    assert out["status"] == "EXAM_INVALID"


def test_verdict_spec_canonical_roundtrip():
    spec = probe_course_verdict_spec()
    payload = spec.canonical_payload()
    assert json.dumps(payload, sort_keys=True, ensure_ascii=False,
                       separators=(",", ":")) == spec.canonical()
    clone = CourseVerdictSpec(
        version=spec.version,
        min_effective_net_return=spec.min_effective_net_return,
        min_seed_pass_ratio_for_cheat=spec.min_seed_pass_ratio_for_cheat,
        min_replication_episodes=spec.min_replication_episodes,
        required_positive_splits=spec.required_positive_splits,
        vs_always_flat_ci_low_min=spec.vs_always_flat_ci_low_min,
        vs_rule_baseline_median_diff_min=(
            spec.vs_rule_baseline_median_diff_min),
        seed_pass_ratio_min=spec.seed_pass_ratio_min,
        median_turnover_max=spec.median_turnover_max,
        required_counterfactuals=spec.required_counterfactuals,
        required_null_families=spec.required_null_families,
        notes=spec.notes)
    assert clone.verdict_spec_hash() == spec.verdict_spec_hash()
