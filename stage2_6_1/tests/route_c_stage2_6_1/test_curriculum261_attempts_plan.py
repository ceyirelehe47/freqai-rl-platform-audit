"""阶段 2.6.1:attempt policy / 难度度量 / plan lock / PPO smoke 测试。"""

from __future__ import annotations

import json

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_MAX_ATTEMPTS,
    AttemptRecord,
    EpisodeAttemptLog,
    check_attempt_log,
)
from rl_curriculum.curriculum261_pairs import (
    attempt_statistics,
    family_specs,
    generate_pair,
)
from rl_curriculum.curriculum261_qualification import rung_report


class TestAttemptPolicy:
    def test_max_attempts_is_five_and_first_pass(self):
        assert CURRICULUM261_MAX_ATTEMPTS == 5
        log = EpisodeAttemptLog(family="f", rung="D0", pair_index=0,
                                seed_namespace="qualification")
        log.attempts = [AttemptRecord(0, True)]
        log.selected_attempt = 0
        assert log.first_pass
        assert check_attempt_log(log) == []

    def test_reject_before_accept_requires_reason(self):
        log = EpisodeAttemptLog(family="f", rung="D0", pair_index=0,
                                seed_namespace="qualification")
        log.attempts = [AttemptRecord(0, False, "too_few_cues"),
                        AttemptRecord(1, True)]
        log.selected_attempt = 1
        assert check_attempt_log(log) == []

    def test_tampered_logs_are_caught(self):
        # 选中之前缺拒绝原因
        log = EpisodeAttemptLog(family="f", rung="D0", pair_index=0,
                                seed_namespace="q")
        log.attempts = [AttemptRecord(0, False, ""),
                        AttemptRecord(1, True)]
        log.selected_attempt = 1
        assert check_attempt_log(log) != []
        # 选中之后又出现拒绝(first_pass 被破坏)
        log2 = EpisodeAttemptLog(family="f", rung="D0", pair_index=0,
                                 seed_namespace="q")
        log2.attempts = [AttemptRecord(0, True),
                         AttemptRecord(1, False, "x")]
        log2.selected_attempt = 0
        assert check_attempt_log(log2) != []

    def test_real_generation_attempts_are_structural_only(self):
        stats = attempt_statistics([
            generate_pair("c3_cost", r, i, namespace="calibration")
            for r in ("D0", "D3") for i in range(3)])
        assert stats["n_pairs"] == 6
        assert 0.0 <= stats["first_pass_rate"] <= 1.0
        # 拒绝原因全部来自结构性词表(不含 PnL 语义)
        for reason in stats["rejection_reasons"]:
            assert "pnl" not in reason.lower()
            assert "net_return" not in reason

    def test_all_attempts_fail_raises_no_silent_retry(self):
        from rl_curriculum.curriculum261_api import (
            PairGenerationError, generate_pair_with_attempts)

        def always_reject(_episode):
            return ["too_few_cues"]

        spec = family_specs()["c3_cost"]
        with pytest.raises(PairGenerationError):
            generate_pair_with_attempts(
                spec.generator, spec.rung_params["D1"],
                namespace="calibration", family="c3_cost", rung="D1",
                pair_index=0, structural_validator=always_reject)


class TestDifficultyMetric:
    def test_metric_math_on_report(self):
        records = [generate_pair("c1_opportunity", r, i,
                                 namespace="calibration")
                   for r in ("D0", "D3") for i in range(2)]
        spec = family_specs()["c1_opportunity"]
        rep = rung_report(records, "c1_opportunity",
                          spec.rung_params,
                          {"c1_opportunity": dict(spec.reference_defaults)})
        for rung in ("D0", "D3"):
            m = rep["by_rung"][rung]["policy_means"]
            expected = m["reference"] - max(0.0, m["always_long"])
            assert rep["by_rung"][rung]["difficulty_metric"] == \
                pytest.approx(expected, rel=1e-9)
        # oracle 诊断在有声数据的 rung 上为正(C1 世界结构存在的证据)
        for rung in ("D0", "D3"):
            assert rep["by_rung"][rung]["oracle_positive"]


class TestPlanLock:
    def test_build_lock_load_roundtrip(self, tmp_path):
        from rl_curriculum.curriculum261_plan import (
            build_plan, lock_plan, load_locked_plan, plan_digest)

        plan = build_plan(baseline_commit="cd585f4" + "0" * 32,
                          vendor_pin="52bc96f" + "0" * 34,
                          frozen_contracts={"env_core":
                                            "RouteCEnvCore-v1.0.0"})
        digest = lock_plan(plan, tmp_path)
        assert digest.startswith("qp-")
        loaded, recorded = load_locked_plan(tmp_path)
        assert recorded == digest
        assert plan_digest(loaded) == digest

    def test_tampered_plan_detected(self, tmp_path):
        from rl_curriculum.curriculum261_plan import (
            build_plan, lock_plan, load_locked_plan)

        plan = build_plan(baseline_commit="a" * 40, vendor_pin="b" * 40,
                          frozen_contracts={})
        lock_plan(plan, tmp_path)
        # 篡改阈值
        plan["verdict_thresholds"]["fresh_seed_valid_ratio_min"] = 0.5
        (tmp_path / "qualification_plan.json").write_text(
            json.dumps(plan), encoding="utf-8")
        with pytest.raises(RuntimeError, match="篡改"):
            load_locked_plan(tmp_path)

    def test_code_identity_binds_modules(self):
        from rl_curriculum.curriculum261_plan import build_plan

        plan = build_plan(baseline_commit="a" * 40, vendor_pin="b" * 40,
                          frozen_contracts={})
        ids = plan["code_identity"]
        assert "curriculum261_api.py" in ids
        assert all(v and v != "MISSING" for v in ids.values())


class TestPpoSmoke:
    def test_256_step_smoke_passes(self, tmp_path):
        from rl_curriculum.curriculum261_smoke import run_ppo_smoke

        result = run_ppo_smoke(out_dir=tmp_path)
        assert result["pass"]
        assert result["steps"] == 256
        assert result["rewards_finite"]
        assert result["seed_namespace"] == "training"
        # smoke 结果不含任何课程选择语义
        assert "不参与课程参数选择" in result["note"]
