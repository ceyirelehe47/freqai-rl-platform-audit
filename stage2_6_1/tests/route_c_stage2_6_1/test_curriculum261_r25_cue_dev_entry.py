# -*- coding: utf-8 -*-
"""R25 cue-bias 开发研究薄入口工程测试(D01-D08 面)。

真实组件(原生成叶函数/trace/原 bootstrap/v4 主分析)+ smoke
namespace(s3;与 c01..c11 研究坐标完全不重);无 mock recall。
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

_DEPLOY_ROOT = Path(__file__).resolve().parents[2]
_ENTRY = _DEPLOY_ROOT / "stage2_6_1_runner" / "r25_cue_bias_dev_entry.py"
_PY = sys.executable

S3_MODEL_NS = "cue_dev_smoke_s3_model"
S3_VALIDATION_NS = "cue_dev_smoke_s3_validation"
P0_STUDY = 0.950431552876822


def _run(*args, timeout=600):
    return subprocess.run(
        [_PY, str(_ENTRY), *args], capture_output=True, text=True,
        cwd=str(_DEPLOY_ROOT), timeout=timeout)


def _mini_plan(tmp: Path, *, blocks: int = 4,
               validation_ns: str = S3_VALIDATION_NS,
               model_ns: str = S3_MODEL_NS,
               planned_k: int = 1) -> Path:
    """测试专用 mini-plan(研究计划外;smoke namespace;digest 自洽)。

    直接以入口同一 digest 规则构造,不用 plan-create(其名单固定
    11+3,测试需要自由变体验证守卫)。
    """
    plan = {
        "format": "r25-cue-bias-dev-plan-v1",
        "created_utc": "2026-09-26T00:00:00+00:00",
        "task": "test-mini",
        "interpreter": _PY,
        "argv0": str(_ENTRY),
        "entry_sha256": "0" * 64,
        "generation_code_identity": {},
        "study": {
            "p0_fixed_reference": P0_STUDY,
            "delta_definition": "P0 - recall(validation)",
            "planned_k": planned_k, "margin": 0.003, "alpha": 0.05,
            "r_analysis": 1.5,
            "aggregation": "test",
            "main_analysis_entry": "report/r20_design_calc_v4.py::"
                                   "classify_primary"},
        "generation": {
            "model_mode": "once", "validation_mode": "attempts",
            "block_seed": "derive261_block_seed",
            "canonical_observation": "D0/A", "cluster_unit":
            "matched_block",
            "bootstrap": {"n_boot": 20000, "seed": 20270102},
            "sentinel": "test", "detector": {}, "episode_bars": 288},
        "not_run_diagnostic_items": ["monte_carlo_1e6"],
        "budget": {"per_coordinate_max_seconds": 2700,
                   "total_wall_clock_seconds": 28800,
                   "finalize_reserve_seconds": 2700},
        "namespaces_authority": "curriculum261_api",
        "namespaces_registered": [model_ns, validation_ns],
        "coordinates": [{
            "id": "c01", "model_namespace": model_ns,
            "validation_namespace": validation_ns,
            "blocks_per_corpus": blocks, "role": "study"}],
        "smoke_coordinates": [],
    }
    import hashlib
    body = json.dumps(plan, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")
    plan["plan_digest"] = "r25dp-" + hashlib.sha256(body).hexdigest()
    path = tmp / "mini_plan.json"
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path


@pytest.fixture(scope="module")
def mini_run(tmp_path_factory):
    """一次真实 mini 生成(4+4 blocks,smoke s3 namespace),全模块共享。"""
    base = tmp_path_factory.mktemp("r25_mini")
    plan = _mini_plan(base)
    proc = _run("run-coordinate", "--plan", str(plan),
                "--coordinate", "c01",
                "--out-root", str(base / "out"))
    assert proc.returncode == 0, proc.stdout + proc.stderr
    coord = base / "out" / "coord_c01"
    summary = json.loads((coord / "summary.json").read_text(
        encoding="utf-8"))
    return base, plan, coord, summary


class TestNamespaceIsolationD02:
    def test_dev_namespaces_registered_and_explicit(self):
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R25_DEV_NAMESPACES,
            CURRICULUM261_SEED_NAMESPACES,
            CURRICULUM261_R17_FORMAL_NAMESPACES,
            _is_candidate_semantic_namespace,
        )
        assert len(CURRICULUM261_R25_DEV_NAMESPACES) == 28
        assert len(set(CURRICULUM261_R25_DEV_NAMESPACES)) == 28
        study = [n for n in CURRICULUM261_R25_DEV_NAMESPACES
                 if "_c" in n]
        assert len(study) == 22  # 11 对研究
        for name in CURRICULUM261_R25_DEV_NAMESPACES:
            assert name in CURRICULUM261_SEED_NAMESPACES
            assert name not in CURRICULUM261_R17_FORMAL_NAMESPACES
            assert not _is_candidate_semantic_namespace(name)
            assert name.startswith("cue_dev_")

    def test_seed_guard_accepts_dev_rejects_arbitrary(self):
        from rl_curriculum.curriculum261_api import GeneratorError, \
            derive261_seed
        seed = derive261_seed("cue_dev_r25_c01_model", "c2", "D0", 0, 0)
        assert isinstance(seed, int)
        with pytest.raises(GeneratorError):
            derive261_seed("cue_dev_r25_c99_model", "c2", "D0", 0, 0)
        with pytest.raises(GeneratorError):
            derive261_seed("arbitrary_evil_namespace", "c2", "D0", 0, 0)

    def test_unregistered_coordinate_refused(self, tmp_path):
        plan = _mini_plan(tmp_path)
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "c99", "--out-root",
                    str(tmp_path / "o"))
        assert proc.returncode != 0
        assert "不在计划名单" in proc.stdout + proc.stderr

    def test_plan_tamper_refused(self, tmp_path):
        plan = _mini_plan(tmp_path)
        data = json.loads(plan.read_text(encoding="utf-8"))
        data["study"]["margin"] = 0.05  # 数据后改计划
        plan.write_text(json.dumps(data), encoding="utf-8")
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "c01", "--out-root",
                    str(tmp_path / "o"))
        assert proc.returncode != 0
        assert "digest" in (proc.stdout + proc.stderr)

    def test_foreign_namespace_in_plan_refused(self, tmp_path):
        plan = _mini_plan(tmp_path, validation_ns="not_a_dev_namespace")
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "c01", "--out-root",
                    str(tmp_path / "o"))
        assert proc.returncode != 0
        assert "未在 api 开发名单" in proc.stdout + proc.stderr


class TestWriteOnceOriginalsD05D08:
    def test_sealed_dir_refuses_rerun(self, mini_run):
        base, plan, coord, _ = mini_run
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "c01", "--out-root",
                    str(base / "out"))
        assert proc.returncode != 0
        assert "sealed" in (proc.stdout + proc.stderr)

    def test_interrupted_dir_refuses_rerun(self, mini_run, tmp_path):
        base, plan, coord, _ = mini_run
        victim = tmp_path / "out" / "coord_c01"
        victim.mkdir(parents=True)
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "c01", "--out-root",
                    str(tmp_path / "out"))
        assert proc.returncode != 0
        assert "interrupted" in (proc.stdout + proc.stderr)


class TestRealPipelineD01D04D06:
    def test_events_recomputable_from_originals(self, mini_run):
        _, _, coord, summary = mini_run
        events = [
            json.loads(line) for line in
            (coord / "validation_events.jsonl").read_text(
                encoding="utf-8").splitlines() if line.strip()]
        per_block: dict[int, dict[str, int]] = {}
        for event in events:
            slot = per_block.setdefault(
                event["block_index"], {"n": 0, "hit": 0})
            slot["n"] += 1
            slot["hit"] += 1 if event["detected"] else 0
        total_n = sum(s["n"] for s in per_block.values())
        total_hit = sum(s["hit"] for s in per_block.values())
        v = summary["validation"]
        assert v["n_events"] == total_n == len(events)
        assert v["n_detected"] == total_hit
        assert abs(v["recall"] - total_hit / total_n) < 1e-15
        # 唯一事件身份(无重复 block/cue_bar)
        keys = {(e["block_index"], e["cue_bar"]) for e in events}
        assert len(keys) == len(events)
        # 事件字段 = 原 trace 组件形状
        for field in ("k_actual", "primary_present", "detected",
                      "cue_read", "block_seed"):
            assert field in events[0]
        # once/attempts 证据在场
        attempts = (coord /
                    "validation_block_attempts.jsonl").read_text(
            encoding="utf-8").splitlines()
        assert len(attempts) == 4
        log0 = json.loads(attempts[0])
        assert log0["format"] == "cur261-r6-block-attempt-log-v1"
        assert log0["max_attempts"] == 5
        assert v["first_pass_bitwise_check"]["bitwise_ok"] is True

    def test_local_p_contract_is_diagnostic_only(self, mini_run):
        _, _, _, summary = mini_run
        local = summary["model"]["local_p_contract_diagnostic"]
        assert 0.5 < local < 1.0
        # 诊断保留真实局部值;主参考 P0 是常量,不被其覆盖
        assert local != P0_STUDY

    def test_cold_read_recomputes_and_classifies(self, mini_run):
        base, plan, coord, summary = mini_run
        result_path = base / "cold_result.json"
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(base / "out"),
                    "--result", str(result_path))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        result = json.loads(result_path.read_text(encoding="utf-8"))
        row = result["coordinates"][0]
        v = summary["validation"]
        assert row["recall_validation"] == v["recall"]
        assert row["se_k"] == v["block_cluster_bootstrap"]["se"]
        assert result["p0_fixed_reference"] == P0_STUDY
        assert abs(row["delta_k"]
                   - (P0_STUDY - v["recall"])) < 1e-15
        primary = result["primary"]
        # D07:v4 实际倍率进入区间
        assert primary["r_analysis"] == 1.5
        assert primary["planned_k"] == 1
        assert primary["margin"] == 0.003
        assert primary["alpha"] == 0.05
        assert primary["k_coordinates"] == 1
        assert result["contrast_r1"]["r_analysis"] == 1.0
        # 4-block smoke SE 大 ⇒ 小坐标应当不决/触界语义如实
        assert primary["magnitude"] in {
            "within_equivalence_bounds", "beyond_positive_margin",
            "beyond_negative_margin", "inconclusive"}

    def test_cold_read_detects_member_tamper(self, mini_run, tmp_path):
        base, plan, coord, _ = mini_run
        copied_root = tmp_path / "out"
        shutil.copytree(base / "out", copied_root)
        events_path = copied_root / "coord_c01" / (
            "validation_events.jsonl")
        lines = events_path.read_text(encoding="utf-8").splitlines()
        # 复制一份事件行制造重复身份 + 封存后字节变化
        events_path.write_text(
            "\n".join(lines + [lines[0]]) + "\n", encoding="utf-8")
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(copied_root),
                    "--result", str(tmp_path / "r.json"))
        assert proc.returncode == 0  # 冷读不崩,问题如实列出
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        problems = "\n".join(result["integrity_problems"])
        assert "重复事件身份" in problems
        assert "封存后字节变化" in problems
        assert result["complete_k"] is False

    def test_cold_read_insufficient_k_inconclusive(self, mini_run):
        base, plan, coord, _ = mini_run
        result_path = base / "cold_partial.json"
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(base / "out"),
                    "--result", str(result_path))
        assert proc.returncode == 0
        result = json.loads(result_path.read_text(encoding="utf-8"))
        # mini plan planned_k=1 且单坐标齐全 ⇒ complete;主结论入口
        # 的 planned_k 保护由 v4 的 insufficient_coordinates 分支
        # 覆盖(构造 k<planned 由下述单元面验证)。
        assert result["k_available"] == 1

    def test_v4_insufficient_coordinates(self, mini_run):
        import importlib.util
        v4_path = _DEPLOY_ROOT / "stage2_6_1_runner" / (
            "r20_design_calc_v4.py")
        if not v4_path.is_file():
            v4_path = _DEPLOY_ROOT.parents[0] / (
                "freqai-rl-audit") / "stage2_6_1" / "report" / (
                "r20_design_calc_v4.py")
        spec = importlib.util.spec_from_file_location("v4m", v4_path)
        v4 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(v4)
        out = v4.classify_primary(
            0.004, [0.001, 0.001, 0.001], 0.003,
            r_analysis=1.5, alpha=0.05, planned_k=11)
        assert out["magnitude"] == "inconclusive"
        assert out["not_resolved_reason"] == "insufficient_coordinates"
        assert out["direction"] == "positive"  # 方向仍如实描述


class TestStudyPlanFrozen:
    def test_real_plan_digest_stable_and_names_match(self):
        plan_path = _DEPLOY_ROOT / (
            "artifacts/repair17/development/r25_cue_bias_dev/plan"
            "/dev_plan.json")
        if not plan_path.is_file():
            pytest.skip("研究计划尚未生成(部署树布局)")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        from rl_curriculum.curriculum261_api import (
            CURRICULUM261_R25_DEV_NAMESPACES)
        ids = [row["id"] for row in plan["coordinates"]]
        assert ids == [f"c{i:02d}" for i in range(1, 12)]
        for row in plan["coordinates"]:
            assert row["blocks_per_corpus"] == 500
            assert row["model_namespace"] in (
                CURRICULUM261_R25_DEV_NAMESPACES)
            assert row["validation_namespace"] in (
                CURRICULUM261_R25_DEV_NAMESPACES)
        assert plan["study"]["planned_k"] == 11
        assert plan["study"]["r_analysis"] == 1.5
        assert plan["study"]["margin"] == 0.003
        assert plan["study"]["p0_fixed_reference"] == P0_STUDY
        smoke_ids = [r["id"] for r in plan["smoke_coordinates"]]
        assert not set(smoke_ids) & set(ids)
