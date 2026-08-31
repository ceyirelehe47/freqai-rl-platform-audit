"""Repair R1:config metric 与三层门禁 regression tests(任务书 §23)。"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

from rl_curriculum.ppo262_metrics import (  # noqa: E402
    config_dev_d1_capture,
)


# ============================================================ Config scoring
class TestConfigDevD1Metric:
    def test_d1_only_metric_does_not_need_d0_d2(self):
        """D1-only 评估集(只有 D1 cell)可直接评分,不调用 D0-D2 公式。"""
        table = {
            "c1_opportunity/D1": {"capture": 0.12},
            "c2_context/D1": {"capture": 0.0},
            "c3_cost/D1": {"capture": -9.7},
        }
        v = config_dev_d1_capture(
            table, ("c1_opportunity", "c2_context", "c3_cost"))
        assert v == pytest.approx((0.12 + 0.0 - 9.7) / 3)

    def test_missing_cell_raises_not_null(self):
        """完整指标输入不足必须报错,而非返回 null。"""
        with pytest.raises(ValueError, match="D1 cell 缺失"):
            config_dev_d1_capture(
                {"c1_opportunity/D1": {"capture": 0.1}},
                ("c1_opportunity", "c2_context"))

    def test_none_capture_raises_not_null(self):
        with pytest.raises(ValueError, match="capture 为 None"):
            config_dev_d1_capture(
                {"c1_opportunity/D1": {"capture": None}},
                ("c1_opportunity",))

    def test_score_always_finite(self):
        v = config_dev_d1_capture(
            {"f/D1": {"capture": 0.0}}, ["f"])
        assert v == 0.0  # 全 flat 坍塌 -> capture 0 仍是有限数值


class TestSelectConfigNoFallback:
    def test_all_fail_returns_none(self):
        from rl_curriculum.ppo262_cli import select_config_from_scores
        sel, notes, all_fail = select_config_from_scores(
            {"a": 0.0, "b": -3.2, "c": -9.7},
            {"a": {"f1": 0.0, "f2": 0.0, "f3": -9.7},
             "b": {"f1": 0.0, "f2": 0.0, "f3": -9.7},
             "c": {"f1": 0.0, "f2": 0.0, "f3": -9.7}})
        assert sel is None and all_fail is True
        assert "fallback" not in str(notes.get("all_fail", "")).lower() or (
            "removed" in notes.get("fallback_semantics", ""))

    def test_null_score_raises(self):
        from rl_curriculum.ppo262_cli import select_config_from_scores
        with pytest.raises(ValueError, match="有限数值"):
            select_config_from_scores({"a": None}, {})

    def test_valid_score_selects_best(self):
        from rl_curriculum.ppo262_cli import select_config_from_scores
        sel, _, all_fail = select_config_from_scores(
            {"a": 0.4, "b": 0.1},
            {"a": {"f1": 0.4}, "b": {"f1": 0.1}})
        assert sel == "a" and not all_fail

    def test_family_positive_prevents_all_fail(self):
        """任一 family capture > 0.05 -> 不是 all-fail(仍可选)。"""
        from rl_curriculum.ppo262_cli import select_config_from_scores
        sel, _, all_fail = select_config_from_scores(
            {"a": -0.01},
            {"a": {"f1": 0.2, "f2": -0.1, "f3": -0.1}})
        assert sel is not None and not all_fail


# ============================================================ Gate enforcement
def _fake_probe_result(family: str, *, passed: bool, complete: bool = True,
                       contradiction: bool = False) -> dict:
    d = {
        "format": "ppo262-probe-result-v1",
        "family": family,
        "namespace": f"ppo_probe_train_262_{family[:2]}",
        "config": "cand_a_center",
        "model_seed": 26201,
        "budget_episodes": 160,
        "budget_steps": 160 * 287,
        "env_audit": {
            "steps_taken": 160 * 287, "episodes_consumed": 160,
            "first_pass_order_ok": True, "exposure_counts": {},
        },
        "train_pass": True,
        "capture_table": {f"{family}/{r}": {"capture": 0.2}
                          for r in ("D0", "D1", "D2", "D3")},
        "core_capture": 0.2,
        "behavior": {},
        "behavior_gap": 0.2,
        "gate_core_capture_gt_0.10": passed and not contradiction,
        "gate_behavior_gap_gt_0.10": passed and not contradiction,
        "pass": passed,
        "episode_curve": [{"episode_key": "x"}] * 3,
    }
    if not complete:
        d.pop("capture_table")
        d.pop("episode_curve")
    return d


class TestOfficialGates:
    def test_config_fail_blocks_probe(self, tmp_lock_dir):
        from rl_curriculum.ppo262_cli import cmd_probe, official_config_gate

        class _A:
            family = "c1_opportunity"
        ok, info = official_config_gate()
        assert not ok  # 无 selected config
        rc = cmd_probe(_A())
        assert rc == 2  # fail closed,未进入训练

    def test_config_all_fail_selected_removed(self, tmp_lock_dir, capsys):
        from rl_curriculum.ppo262_cli import cmd_config_dev_select
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        result = {
            "candidates": {
                n: {"capture_tables": {
                    "c1_opportunity": {
                        "c1_opportunity/D1": {"capture": 0.0}},
                    "c2_context": {
                        "c2_context/D1": {"capture": 0.0}},
                    "c3_cost": {
                        "c3_cost/D1": {"capture": -9.7}}}}
                for n in ("cand_a_center",)},
            "candidate_scores": {"cand_a_center": None},
        }
        (art / "ppo_config_development_result.json").write_text(
            json.dumps(result), encoding="utf-8")
        # 预置 stale selected config,验证 all-fail 重选会清除
        (art / "selected_ppo_config.json").write_text(
            json.dumps({"selected_candidate": "cand_a_center"}),
            encoding="utf-8")

        class _A:
            pass
        rc = cmd_config_dev_select(_A())
        assert rc == 2
        assert not (art / "selected_ppo_config.json").is_file()
        assert not (art / "selected_ppo_config_digest.txt").is_file()
        reread = json.loads(
            (art / "ppo_config_development_result.json").read_text())
        assert reread["all_fail"] is True
        assert reread["selected_candidate"] is None
        # 重算后的 score 必须有限非 null
        assert reread["candidate_scores"]["cand_a_center"] == pytest.approx(
            (0.0 + 0.0 - 9.7) / 3)

    def _write_probes(self, art: Path, families, passed: dict):
        for fam in families:
            d = _fake_probe_result(fam, passed=passed[fam])
            (art / f"probe_results_{fam}.json").write_text(
                json.dumps(d), encoding="utf-8")

    def test_probe_fail_blocks_core(self, tmp_lock_dir):
        from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
        from rl_curriculum.ppo262_cli import cmd_core
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        (art / "selected_ppo_config.json").write_text(json.dumps({
            "selected_candidate": "cand_a_center",
            "config": {"n_steps": 574, "device": "cpu"}}), encoding="utf-8")
        passed = {f: True for f in CURRICULUM261_FAMILIES}
        passed["c2_context"] = False
        self._write_probes(art, CURRICULUM261_FAMILIES, passed)

        class _A:
            replicate = 1
            order = "staged"
        assert cmd_core(_A()) == 2

    def test_probe_missing_blocks_core(self, tmp_lock_dir):
        from rl_curriculum.ppo262_cli import cmd_core
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        (art / "selected_ppo_config.json").write_text(json.dumps({
            "selected_candidate": "cand_a_center",
            "config": {}}), encoding="utf-8")
        # 无任何 probe artifact

        class _A:
            replicate = 1
            order = "staged"
        assert cmd_core(_A()) == 2

    def test_forged_empty_pass_artifact_rejected(self, tmp_lock_dir):
        """手工伪造 {"pass": true} 空 artifact 无法通过 probe gate。"""
        from rl_curriculum.ppo262_cli import official_probe_gate
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        (art / "probe_results_c1_opportunity.json").write_text(
            json.dumps({"pass": True}), encoding="utf-8")
        ok, info = official_probe_gate()
        assert not ok and "缺少必需字段" in info["reason"]

    def test_forged_contradictory_artifact_rejected(self, tmp_lock_dir):
        from rl_curriculum.ppo262_cli import official_probe_gate
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        d = _fake_probe_result(
            "c1_opportunity", passed=False, contradiction=True)
        d["pass"] = True  # 伪造:pass=True 但 gate 字段为 False
        (art / "probe_results_c1_opportunity.json").write_text(
            json.dumps(d), encoding="utf-8")
        ok, info = official_probe_gate()
        assert not ok and "内部矛盾" in info["reason"]

    def test_incomplete_capture_table_rejected(self, tmp_lock_dir):
        from rl_curriculum.ppo262_cli import official_probe_gate
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        d = _fake_probe_result("c1_opportunity", passed=True,
                               complete=False)
        d["capture_table"] = {"c1_opportunity/D1": {"capture": 0.2}}
        d["episode_curve"] = [{"k": 1}]
        (art / "probe_results_c1_opportunity.json").write_text(
            json.dumps(d), encoding="utf-8")
        ok, info = official_probe_gate()
        assert not ok and "D0" in info["reason"]

    def test_probe_pass_allows_gate(self, tmp_lock_dir):
        from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
        from rl_curriculum.ppo262_cli import official_probe_gate
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        self._write_probes(art, CURRICULUM261_FAMILIES,
                           {f: True for f in CURRICULUM261_FAMILIES})
        ok, info = official_probe_gate()
        assert ok and info["ok"]

    def test_probe_fail_blocks_final_lock(self, tmp_lock_dir):
        from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
        from rl_curriculum.ppo262_cli import cmd_final_lock
        art = tmp_lock_dir / "art"
        art.mkdir(exist_ok=True)
        (art / "selected_ppo_config.json").write_text(json.dumps({
            "selected_candidate": "cand_a_center",
            "config": {}, "config_digest": "pc-x"}), encoding="utf-8")
        passed = {f: True for f in CURRICULUM261_FAMILIES}
        passed["c3_cost"] = False
        self._write_probes(art, CURRICULUM261_FAMILIES, passed)

        class _A:
            pass
        assert cmd_final_lock(_A()) == 2

    def test_diagnostic_command_executable_after_gates_closed(
            self, tmp_lock_dir, monkeypatch):
        """official gate 关闭后,diagnostic 命令仍可显式执行。"""
        import rl_curriculum.ppo262_diagnose_cli as dcli
        calls = []
        monkeypatch.setattr(dcli, "cmd_baseline_integrity",
                            lambda a: calls.append(1) or 0)
        rc = dcli.main(["baseline-integrity"])
        assert rc == 0 and calls

    def test_diagnostic_artifacts_not_accepted_by_official_runner(
            self, tmp_lock_dir):
        """repair1/ 目录下的 probe artifact 不被 official gate 接受
        (official gate 只读顶层 probe_results_*.json)。"""
        from rl_curriculum.ppo262_cli import official_probe_gate
        art = tmp_lock_dir / "art"
        (art / "repair1").mkdir(parents=True)
        d = _fake_probe_result("c1_opportunity", passed=True)
        (art / "repair1" / "probe_results_c1_opportunity.json").write_text(
            json.dumps(d), encoding="utf-8")
        ok, info = official_probe_gate()
        assert not ok  # 顶层缺失 -> 关闭;诊断目录不参与 official gate
