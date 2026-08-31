# -*- coding: utf-8 -*-
"""阶段 2.6.1 repair R2 协议测试(§27):
gate 三层 enforcement / R2 seed space / qualification_r2 封闭 /
统一合同蕴含 / exposure 一次性 / production runtime identity /
preprocessing boundary / C2 双诊断。"""
from __future__ import annotations

import json

import numpy as np
import pytest

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_ITERATION_ID,
    CURRICULUM261_R2_NAMESPACES,
    derive261_seed,
    qualification_r2_exposed,
    qualification_r2_lock_marker,
    qualification_r2_unlocked,
)
from rl_curriculum.curriculum261_pairs import (
    compute_pair_integrity,
    generate_pair,
    pair_structural_contract,
)


def _gate_pass() -> dict:
    return {"format": "cur261-robustness-gate-v2", "pass": True,
            "families": {}}


def _gate_fail() -> dict:
    return {"format": "cur261-robustness-gate-v2", "pass": False,
            "families": {}}


# ------------------------------------------------ Layer A/B/C gate enforcement
class TestGateEnforcement:
    def test_build_plan_rejects_missing_gate(self):
        from rl_curriculum.curriculum261_plan import build_plan

        with pytest.raises(RuntimeError, match="robustness gate"):
            build_plan(baseline_commit="a" * 40, vendor_pin="b" * 40,
                       frozen_contracts={})

    def test_build_plan_rejects_failed_gate(self):
        from rl_curriculum.curriculum261_plan import build_plan

        with pytest.raises(RuntimeError, match="robustness gate"):
            build_plan(baseline_commit="a" * 40, vendor_pin="b" * 40,
                       frozen_contracts={},
                       robustness_gate=_gate_fail())

    def test_build_plan_accepts_passed_gate_and_binds_digest(self):
        from rl_curriculum.curriculum261_plan import build_plan

        plan = build_plan(
            baseline_commit="a" * 40, vendor_pin="b" * 40,
            frozen_contracts={}, robustness_gate=_gate_pass(),
            gate_artifact_digest="ab" * 32)
        assert plan["robustness_gate"]["pass"] is True
        assert plan["robustness_gate_artifact_digest"] == "ab" * 32

    def test_final_runner_fails_closed_on_gate_false(self, tmp_path,
                                                    monkeypatch):
        """Layer C:合法 digest 但 gate=false 的 plan,final 必须在
        生成任何 qualification pair 之前拒绝。

        marker 目录必须指向空 tmp(真实 exposure marker 存在时
        final 会先撞一次性守卫——那是另一项测试覆盖的合同)。"""
        from rl_curriculum.curriculum261_final import run_final_qualification
        from rl_curriculum.curriculum261_plan import build_plan, lock_plan

        monkeypatch.setenv("CURRICULUM261_R2_LOCK_DIR", str(tmp_path))
        plan = build_plan(
            baseline_commit="a" * 40, vendor_pin="b" * 40,
            frozen_contracts={}, robustness_gate=_gate_pass())
        # 构造 gate=false 的合法 digest plan(lock 后整体重写)
        plan["robustness_gate"] = _gate_fail()
        lock_plan(plan, tmp_path / "plan")
        with pytest.raises(RuntimeError,
                           match="robustness_gate.pass"):
            run_final_qualification(
                plan_dir=tmp_path / "plan", out_dir=tmp_path / "out",
                vendor_dir=tmp_path)  # vendor 不可达也应先被 gate 拦

    def test_exposure_marker_blocks_second_run(self, tmp_path,
                                               monkeypatch):
        """exposure 一次性:marker 存在 -> 同 iteration 永久结束。"""
        from rl_curriculum.curriculum261_api import (
            write_qualification_r2_exposure,
        )
        from rl_curriculum.curriculum261_final import run_final_qualification

        monkeypatch.setenv("CURRICULUM261_R2_LOCK_DIR", str(tmp_path))
        write_qualification_r2_exposure("qp-test", status="completed")
        assert qualification_r2_exposed()
        with pytest.raises(RuntimeError, match="已执行过"):
            run_final_qualification(
                plan_dir=tmp_path, out_dir=tmp_path / "o",
                vendor_dir=tmp_path)


# ------------------------------------------------ R2 seed space 与封闭性
class TestR2SeedSpace:
    def test_iteration_id_and_namespaces(self):
        assert CURRICULUM261_ITERATION_ID == "r2"
        assert "qualification_r2" in CURRICULUM261_R2_NAMESPACES
        assert "stress_r2" in CURRICULUM261_R2_NAMESPACES

    def test_r2_seeds_disjoint_from_r0_r1(self):
        """R2 全部 namespace 与 R0/R1 qualification seed 无碰撞。

        枚举用 _derive261_seed_raw(纯哈希,qualification_r2 在 lock
        前由守卫封闭——守卫语义本身由本类另外两项测试覆盖)。"""
        from rl_curriculum.curriculum261_api import _derive261_seed_raw

        for fam in ("c1_opportunity", "c2_context", "c3_cost"):
            for rung in ("D0", "D1", "D2", "D3"):
                for p in range(10):
                    for att in range(5):
                        old = _derive261_seed_raw(
                            "qualification", fam, rung, p, att)
                        for ns in CURRICULUM261_R2_NAMESPACES:
                            assert _derive261_seed_raw(
                                ns, fam, rung, p, att) != old

    def test_qualification_r2_blocked_before_lock(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R2_LOCK_DIR", str(tmp_path))
        assert not qualification_r2_unlocked()
        with pytest.raises(Exception, match="不可访问"):
            derive261_seed("qualification_r2", "c1_opportunity",
                           "D0", 0, 0)

    def test_qualification_r2_unlocked_after_lock(self, tmp_path,
                                                  monkeypatch):
        monkeypatch.setenv("CURRICULUM261_R2_LOCK_DIR", str(tmp_path))
        lock_file = qualification_r2_lock_marker()
        lock_file.parent.mkdir(parents=True, exist_ok=True)
        lock_file.write_text("{}", encoding="utf-8")
        assert qualification_r2_unlocked()
        seed = derive261_seed("qualification_r2", "c1_opportunity",
                              "D0", 0, 0)
        assert isinstance(seed, int)

    def test_namespace_integrity_report_passes(self):
        from rl_curriculum.curriculum261_qualification import (
            seed_namespace_integrity_report,
        )

        rep = seed_namespace_integrity_report()
        assert rep["pass"], rep["pairwise_collisions"]
        assert rep["calibration_vs_qualification_r2_disjoint"]


# ------------------------------------------------ 统一合同蕴含
class TestUnifiedPairContract:
    @pytest.mark.parametrize("family,rung",
                             [("c1_opportunity", "D1"),
                              ("c2_context", "D2"),
                              ("c3_cost", "D1")])
    def test_accepted_implies_final_integrity(self, family, rung):
        """acceptance 与 final 同源:contract 无拒绝 -> integrity pass
        (同一确定性输入的同一判定)。"""
        for p in range(2):
            rec = generate_pair(family, rung, p,
                                namespace="calibration_r2")
            contract_issues = pair_structural_contract(
                rec.episodes["A"], rec.episodes["B"], family)
            integrity = compute_pair_integrity(rec)
            assert not contract_issues, contract_issues
            assert integrity["pass"] is True
            assert rec.integrity_ok

    def test_contract_detects_broken_pair(self):
        """人为破坏共享表 -> contract 必须拒绝(与 final 同判)。"""
        rec = generate_pair("c2_context", "D0", 0,
                            namespace="calibration_r2")
        broken = rec.episodes["B"]
        broken.hidden["cue_dir"] = broken.hidden["cue_dir"] * 0
        issues = pair_structural_contract(
            rec.episodes["A"], broken, "c2_context")
        assert issues, "破坏 cue 表后合同必须拒绝"


# ------------------------------------------------ production runtime identity
class TestProductionRuntimeIdentity:
    def test_runtime_config_identity_records_real_config(self):
        from rl_curriculum.curriculum261_production_obs import (
            production_runtime_config_identity,
        )

        rc = production_runtime_config_identity()
        assert rc["drop_ohlc_from_features"] is False
        assert rc["add_state_info"] is False
        assert rc["model_type"] == "PPO"
        assert rc["policy_type"] == "MlpPolicy"
        assert rc["conv_width_supported"] == 1
        assert len(rc["config_sha256"]) == 64
        assert "MinMaxScaler" in " ".join(rc["default_feature_pipeline"])

    def test_preprocessing_boundary_declares_domain_gap(self):
        from rl_curriculum.curriculum261_production_obs import (
            curriculum_preprocessing_boundary,
        )

        b = curriculum_preprocessing_boundary()
        assert "causal unscaled" in b["boundary_name"]
        assert b["explicitly_not_equivalent_to"]
        gap = b["registered_domain_gap"]
        assert gap["gap"] == (
            "FreqAI scaler / production preprocessing transfer")
        assert gap["not_this_stage"] is True

    def test_plan_binds_runtime_config_and_boundary(self):
        from rl_curriculum.curriculum261_plan import build_plan
        from rl_curriculum.curriculum261_production_obs import (
            curriculum_preprocessing_boundary,
            production_runtime_config_identity,
        )

        plan = build_plan(
            baseline_commit="a" * 40, vendor_pin="b" * 40,
            frozen_contracts={}, robustness_gate=_gate_pass())
        assert plan["production_runtime_config_identity"] == (
            production_runtime_config_identity())
        assert plan["preprocessing_boundary"] == (
            curriculum_preprocessing_boundary())


# ------------------------------------------------ C2 双诊断
class TestC2Diagnostics:
    @pytest.fixture()
    def c2_records(self):
        return [generate_pair("c2_context", r, i,
                              namespace="calibration_r2")
                for r in ("D0", "D3") for i in range(2)]

    def test_local_cue_context_independence(self, c2_records):
        from rl_curriculum.curriculum261_qualification import (
            check_c2_local_cue_independence,
        )

        rep = check_c2_local_cue_independence(c2_records)
        assert rep["pass"], rep["checks"]
        # wick carrier:cue 读数与上下文零耦合,象限 mean 差在抽样内
        assert rep["checks"]["mean_gap_within_3se"]

    def test_context_observability_margin(self, c2_records):
        from rl_curriculum.curriculum261_qualification import (
            check_c2_context_observability,
        )

        rep = check_c2_context_observability(c2_records)
        assert rep["direction"]["accuracy"] > 0.9
        assert rep["width"]["accuracy"] > 0.9
        assert rep["pass"]
        assert rep["discriminator"]["observation_only"] is True
