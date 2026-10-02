"""修复轮追加验证(审查 gate1_r3 7.1/7.2/7.3)。

- 7.1 QAF 信封迭代标识:注册表派生(_default_recorder 捕获);
  §15 完备性对 QAF 台账 pass=True(真实 sink+真实消费者 e2e)。
- 7.2 迁移账本额度:legacy {max_runs,consumed_runs} 无 started
  时 base 冻结、c02 被拒、consumed_runs 单调不回退。
- 7.3 run_final_qualification_r17 首部守卫恢复(aborted 根拒绝/
  干净沙盒根行为可观测)。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from rl_curriculum.curriculum261_api import _default_recorder
from rl_curriculum.curriculum261_qaf_attempt import QAF_ALL_NEW
from rl_curriculum.curriculum261_qprod_context import QProdContextError
from rl_curriculum.curriculum261_qprod_coordinate import (
    mark_native_completed, reserve_native_execution,
)


class _CaptureRecorder:
    def __init__(self):
        self.calls: list[tuple] = []

    def __call__(self, iteration, namespace, family, rung, pair_index,
                 rung_params):
        self.calls.append((iteration, namespace))
        return None


class TestQafIterationLabels:
    def test_default_recorder_labels_qaf_family(self, monkeypatch):
        import rl_curriculum.curriculum261_api as api_mod
        from rl_curriculum.curriculum261_generation_envelope import (
            active_recorder,
        )
        cap = _CaptureRecorder()
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_generation_envelope."
            "active_recorder", cap)
        for ns in QAF_ALL_NEW:
            api_mod._default_recorder(ns, "c2_context", "D1", 0, None)
        assert len(cap.calls) == len(QAF_ALL_NEW)
        for iteration, ns in cap.calls:
            assert iteration == "qaf_v1", (iteration, ns)
        # 历史名不受影响(注册表族优先,其余子串序)
        api_mod._default_recorder(
            "qualification_r17", "c2_context", "D1", 0, None)
        api_mod._default_recorder(
            "calibration_r19", "c2_context", "D1", 0, None)
        api_mod._default_recorder(
            "stress_r18", "c2_context", "D1", 0, None)
        api_mod._default_recorder(
            "preplan_smoke_r17", "c2_context", "D1", 0, None)
        labels = {c[0] for c in cap.calls[-4:]}
        assert labels == {"r17", "r18", "r19"}

    def test_e2e_qaf_ledger_passes_completeness(self, tmp_path):
        """真实 sink + 真实 _default_recorder + 真实 §15 完备性:
        QAF 台账行不再被丢(pass=True);R19 对照仍 pass。"""
        from rl_curriculum.curriculum261_generation_envelope import (
            envelope_sink, ledger_sink_factory,
        )
        from rl_curriculum.curriculum261_r17_generation_evidence import (
            ExpectedCall, verify_generation_evidence_completeness,
        )
        stage = "orchestration:formal_main"

        def produce(ns: str):
            ledger = tmp_path / (ns + ".jsonl")
            with envelope_sink(ledger_sink_factory(
                    ledger, stage_label=stage)) as sink:
                rec = _default_recorder(
                    ns, "c1_opportunity", "D0", 0, {"a": 1})
                assert rec is not None
                rec.record("attempt", {
                    "attempt": 0, "seed": 12345,
                    "params": {"A": {}, "B": {}}, "episodes": {},
                    "issues": [], "accepted": True})
            rows = [json.loads(ln) for ln in ledger.read_text(
                encoding="utf-8").splitlines()]
            return ledger, rows

        qaf_ledger, qaf_rows = produce("calibration_qaf_v1")
        assert qaf_rows[0]["envelope"]["iteration"] == "qaf_v1"
        r19_ledger, _ = produce("calibration_r19")
        qaf = verify_generation_evidence_completeness(
            qaf_ledger,
            [ExpectedCall("calibration_qaf_v1", "c1_opportunity",
                          "D0", 0)], stage_label=stage)
        r19 = verify_generation_evidence_completeness(
            r19_ledger,
            [ExpectedCall("calibration_r19", "c1_opportunity",
                          "D0", 0)], stage_label=stage)
        assert qaf["pass"], qaf
        assert r19["pass"], r19

class TestLegacyLedgerMigration:
    def _legacy(self, tmp_path, mx=11, consumed=10):
        p = tmp_path / "qprod_native_budget.json"
        p.write_text(json.dumps({
            "max_runs": mx, "consumed_runs": consumed}),
            encoding="utf-8")
        return p
    def test_legacy_consumed_respected_and_monotone(self, tmp_path):
        """审查 7.2 复现对:{max:11,consumed:10} 无 started——
        c01 进入后 c02 必须被拒;base 冻结;completed 不回退。"""
        bp = self._legacy(tmp_path)
        r = reserve_native_execution(bp, coordinate_id="c01")
        assert r["remaining_after"] == 0  # 10+1 = 11
        with pytest.raises(QProdContextError, match="耗尽"):
            reserve_native_execution(bp, coordinate_id="c02")
        mark_native_completed(bp, coordinate_id="c01")
        doc = json.loads(bp.read_text(encoding="utf-8"))
        assert doc["consumed_runs_base"] == 10
        assert doc["consumed_runs"] >= 10  # 单调不回退(旧额度不清零)
        assert "c01" in doc["started"]

    def test_mark_monotone_never_decreases(self, tmp_path):
        p = tmp_path / "b.json"
        p.write_text(json.dumps({
            "max_runs": 5, "consumed_runs": 7,
            "started": {"c09": {"x": 1}}}), encoding="utf-8")
        mark_native_completed(p, coordinate_id="c09")
        doc = json.loads(p.read_text(encoding="utf-8"))
        assert doc["consumed_runs"] >= 7


class TestFinalWorkerGuardRestored:
    def test_guard_raises_without_active_iteration(self, tmp_path,
                                                   monkeypatch):
        """干净沙盒 state root(无 r17 journal)→ 守卫拒绝
        (require_r17_iteration_active 在 plan 装载之前)。"""
        from rl_curriculum.curriculum261_r17_final import (
            run_final_qualification_r17,
        )
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(tmp_path / "empty_state"))
        with pytest.raises(RuntimeError):
            run_final_qualification_r17(tmp_path / "out")

    def test_guard_source_present(self):
        """AST:run_final_qualification_r17 体调用守卫≥1
        (防再次静默删除)。"""
        import ast
        src = Path(
            "rl_curriculum/curriculum261_r17_final.py"
            if False else __import__("rl_curriculum.curriculum261_r17"
                                     "_final", fromlist=["x"]).__file__
        ).read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "run_final_qualification_r17")
        calls = [n for n in ast.walk(fn)
                 if isinstance(n, ast.Call)
                 and isinstance(n.func, ast.Name)
                 and n.func.id == "require_r17_iteration_active"]
        assert len(calls) >= 1
