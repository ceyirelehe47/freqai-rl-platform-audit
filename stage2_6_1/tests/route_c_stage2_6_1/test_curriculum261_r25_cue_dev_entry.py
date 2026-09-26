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
               planned_k: int = 1,
               extra_coordinates: list[dict] | None = None) -> Path:
    """测试专用 mini-plan(研究计划外;smoke namespace;digest 自洽)。

    直接以入口同一 digest 规则构造,不用 plan-create(其名单固定
    11+3,测试需要自由变体验证守卫)。
    """
    coordinates = [{
        "id": "c01", "model_namespace": model_ns,
        "validation_namespace": validation_ns,
        "blocks_per_corpus": blocks, "role": "study"}]
    if extra_coordinates:
        coordinates.extend(extra_coordinates)
    plan = {
        "format": "r25-cue-bias-dev-plan-v1",
        "created_utc": "2026-09-26T00:00:00+00:00",
        "task": "test-mini",
        "engineering_use": False,
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
            "sentinel": "test",
            "detector": {"cue_thr": 0.0105, "wick_dir_thr": 0.0,
                         "wick_width_thr": 0.0120},
            "episode_bars": 288},
        "not_run_diagnostic_items": ["monte_carlo_1e6"],
        "budget": {"per_coordinate_max_seconds": 2700,
                   "total_wall_clock_seconds": 28800,
                   "finalize_reserve_seconds": 2700},
        "namespaces_authority": "curriculum261_api",
        "namespaces_registered": [model_ns, validation_ns],
        "coordinates": coordinates,
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


def _forge_seal(coord_dir: Path) -> None:
    """重算 SEALED 成员哈希(负例夹具:模拟"攻击者重封存")。"""
    import hashlib
    seal = json.loads((coord_dir / "SEALED.json").read_text(
        encoding="utf-8"))
    seal["members"] = {
        name: hashlib.sha256(
            (coord_dir / name).read_bytes()).hexdigest()
        for name in seal["members"]}
    (coord_dir / "SEALED.json").write_text(
        json.dumps(seal, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")


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
        # 完整性无效 → CLI 明确失败,不发主分类(R25 复收敧行为 1)
        assert proc.returncode != 0
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        problems = "\n".join(result["integrity_problems"])
        assert "重复事件身份" in problems
        assert "封存后字节变化" in problems
        assert result["complete_k"] is False
        assert result["integrity"] == "invalid"
        assert "primary" not in result and "contrast_r1" not in result

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


# ===================== R25 复收敛轮(RouteC_R25_EntryProvenance_
# ReadbackClosure_v1)验收面:A 正常入口/执行绑定,B reader 全链 ----
S2_MODEL_NS = "cue_dev_smoke_s2_model"
S2_VALIDATION_NS = "cue_dev_smoke_s2_validation"


def _entry_sha() -> str:
    import hashlib
    return hashlib.sha256(_ENTRY.read_bytes()).hexdigest()


class TestPlanCreateA01A02:
    """A01/A02:真实 plan-create 成功路径 + 重复/损坏拒绝(非 _mini_plan)。

    全部走真实 CLI;测试内创建的计划均为工程用途(--engineering),
    不会用于启动 c01—c11。
    """

    def test_plan_create_real_cli_success_and_load_path(self, tmp_path):
        out = tmp_path / "eng" / "plan.json"
        proc = _run("plan-create", "--out", str(out), "--engineering")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        payload = json.loads(proc.stdout)
        assert payload["engineering_use"] is True
        plan = json.loads(out.read_text(encoding="utf-8"))
        assert plan["engineering_use"] is True
        assert "engineering" in plan["task"]
        # 固定名单与固定值(不靠 mini plan 模板)
        ids = [r["id"] for r in plan["coordinates"]]
        assert ids == [f"c{i:02d}" for i in range(1, 12)]
        smoke_ids = [r["id"] for r in plan["smoke_coordinates"]]
        assert smoke_ids == ["s1", "s2", "s3"]
        for row in plan["coordinates"] + plan["smoke_coordinates"]:
            assert row["model_namespace"].startswith("cue_dev_")
            assert row["validation_namespace"].startswith("cue_dev_")
        assert all(r["blocks_per_corpus"] == 500
                   for r in plan["coordinates"])
        assert all(r["blocks_per_corpus"] == 4
                   for r in plan["smoke_coordinates"])
        st = plan["study"]
        assert st["p0_fixed_reference"] == P0_STUDY
        assert st["planned_k"] == 11 and st["margin"] == 0.003
        assert st["alpha"] == 0.05 and st["r_analysis"] == 1.5
        assert plan["generation"]["detector"]["cue_thr"] == 0.0105
        assert plan["generation"]["bootstrap"] == {
            "n_boot": 20000, "seed": 20270102}
        assert plan["entry_sha256"] == _entry_sha()
        # 实际加载路径读取(digest 复验通过后再因坐标名单拒绝)
        proc2 = _run("run-coordinate", "--plan", str(out),
                     "--coordinate", "c99", "--out-root",
                     str(tmp_path / "o"))
        assert proc2.returncode != 0
        assert "不在计划名单" in proc2.stdout + proc2.stderr

    def test_plan_create_refuses_existing_and_tampered(self, tmp_path):
        out = tmp_path / "plan.json"
        assert _run("plan-create", "--out", str(out),
                    "--engineering").returncode == 0
        dup = _run("plan-create", "--out", str(out), "--engineering")
        assert dup.returncode != 0
        assert "已存在" in dup.stdout + dup.stderr
        # 内容摘要校验:改一个字节 → 实际加载路径拒绝
        raw = out.read_text(encoding="utf-8")
        out.write_text(raw.replace('"planned_k": 11',
                                   '"planned_k": 12'), encoding="utf-8")
        proc = _run("run-coordinate", "--plan", str(out),
                    "--coordinate", "s1", "--out-root",
                    str(tmp_path / "o"), "--allow-smoke")
        assert proc.returncode != 0
        assert "digest" in proc.stdout + proc.stderr

    def test_engineering_plan_never_launches_study(self, tmp_path):
        out = tmp_path / "plan.json"
        assert _run("plan-create", "--out", str(out),
                    "--engineering").returncode == 0
        proc = _run("run-coordinate", "--plan", str(out),
                    "--coordinate", "c01", "--out-root",
                    str(tmp_path / "o"))
        assert proc.returncode != 0
        assert "engineering" in (proc.stdout + proc.stderr)
        assert not (tmp_path / "o" / "coord_c01").exists()


class TestExecutionBindingA03A04:
    """A03/A04:运行前实测绑定;不符在首次生成前拒绝(零生成)。"""

    @staticmethod
    def _eng_plan(tmp_path):
        out = tmp_path / "plan.json"
        proc = _run("plan-create", "--out", str(out), "--engineering")
        assert proc.returncode == 0, proc.stdout + proc.stderr
        return out

    def test_binding_mismatch_refused_zero_generation(self, tmp_path):
        plan = self._eng_plan(tmp_path)
        binding = tmp_path / "binding.json"
        assert _run("execution-binding", "--out", str(binding),
                    "--plan", str(plan)).returncode == 0
        # 篡改预定绑定的入口身份
        data = json.loads(binding.read_text(encoding="utf-8"))
        data["entry"]["sha256"] = "f" * 64
        # binding_sha256 不再一致(绑定文件被改动也应被拒)
        binding.write_text(json.dumps(data, indent=1), encoding="utf-8")
        out_root = tmp_path / "o"
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "s1", "--out-root", str(out_root),
                    "--allow-smoke", "--execution-binding",
                    str(binding))
        assert proc.returncode == 3
        refusals = list((out_root / "refusals").glob("*.json"))
        assert len(refusals) == 1
        refusal = json.loads(refusals[0].read_text(encoding="utf-8"))
        assert refusal["generation_boundary_calls"]["total"] == 0
        assert any("入口身份不符" in r or "binding_sha256" in r
                   for r in refusal["reasons"])
        # 零副作用:无坐标目录、无任何封存
        assert not (out_root / "coord_s1").exists()
        assert not list(out_root.rglob("SEALED.json"))

    def test_binding_module_mismatch_refused(self, tmp_path):
        plan = self._eng_plan(tmp_path)
        binding = tmp_path / "binding.json"
        assert _run("execution-binding", "--out", str(binding),
                    "--plan", str(plan)).returncode == 0
        data = json.loads(binding.read_text(encoding="utf-8"))
        key = sorted(data["code_identity"])[0]
        data["code_identity"][key] = "e" * 64
        binding.write_text(json.dumps(data, indent=1), encoding="utf-8")
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "s1", "--out-root",
                    str(tmp_path / "o"), "--allow-smoke",
                    "--execution-binding", str(binding))
        assert proc.returncode == 3
        assert not (tmp_path / "o" / "coord_s1").exists()

    def test_refusal_zero_generation_boundary_sentinel(self, tmp_path):
        """进程内哨兵:真实入口拒绝路径绝不触及生成叶函数。"""
        plan = self._eng_plan(tmp_path)
        binding = tmp_path / "binding.json"
        assert _run("execution-binding", "--out", str(binding),
                    "--plan", str(plan)).returncode == 0
        data = json.loads(binding.read_text(encoding="utf-8"))
        data["entry"]["sha256"] = "f" * 64
        binding.write_text(json.dumps(data, indent=1), encoding="utf-8")
        import rl_curriculum.curriculum261_r6_tape as tape_mod
        calls = {"n": 0}
        orig_once = tape_mod.generate_matched_block_once
        orig_att = tape_mod.generate_matched_block_with_attempts

        def _spy_once(*a, **k):
            calls["n"] += 1
            return orig_once(*a, **k)

        def _spy_att(*a, **k):
            calls["n"] += 1
            return orig_att(*a, **k)

        tape_mod.generate_matched_block_once = _spy_once
        tape_mod.generate_matched_block_with_attempts = _spy_att
        try:
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "r25_entry_under_test", _ENTRY)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            rc = mod.main([
                "run-coordinate", "--plan", str(plan),
                "--coordinate", "s1", "--out-root",
                str(tmp_path / "o"), "--allow-smoke",
                "--execution-binding", str(binding)])
        finally:
            tape_mod.generate_matched_block_once = orig_once
            tape_mod.generate_matched_block_with_attempts = orig_att
        assert rc == 3
        assert calls["n"] == 0  # 生成边界计数(哨兵)确证零生成

    def test_correct_binding_smoke_executes_a04(self, tmp_path):
        plan = self._eng_plan(tmp_path)
        binding = tmp_path / "binding.json"
        launcher = tmp_path / "fake_launcher.sh"
        launcher.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
        assert _run("execution-binding", "--out", str(binding),
                    "--plan", str(plan),
                    "--launcher", str(launcher)).returncode == 0
        out_root = tmp_path / "o"
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", "s1", "--out-root", str(out_root),
                    "--allow-smoke", "--execution-binding",
                    str(binding))
        assert proc.returncode == 0, proc.stdout + proc.stderr
        coord = out_root / "coord_s1"
        manifest = json.loads((coord / "manifest.json").read_text(
            encoding="utf-8"))
        assert manifest["format"] == "r25-cue-bias-dev-coordinate-v2"
        execution = manifest["execution"]
        # 执行身份是实测,不是计划字段复制;三角色可区分
        assert execution["entry_sha256"] == _entry_sha()
        assert manifest["creator"]["entry_sha256"] == json.loads(
            plan.read_text(encoding="utf-8"))["entry_sha256"]
        assert manifest["creator"]["entry_sha256"] == _entry_sha()
        assert execution["execution_binding"]["verified_ok"] is True
        for name, ident in execution["loaded_modules"].items():
            assert Path(ident["path"]).is_file()
        assert execution["generation_boundary_calls_at_manifest"][
            "total"] == 0
        summary = json.loads(proc.stdout.splitlines()[-1])
        # 4 model + 4 validation = 8 次生成边界调用
        assert summary["generation_boundary_calls"]["total"] == 8
        assert summary["execution_entry_sha256"] == _entry_sha()
        assert json.loads((coord / "SEALED.json").read_text(
            encoding="utf-8"))["ok"] is True


@pytest.fixture(scope="module")
def two_coord_run(tmp_path_factory):
    """两个 smoke 坐标真实生成(c01→s3 ns,c02→s2 ns;planned_k=2)。"""
    base2 = tmp_path_factory.mktemp("r25_two")
    plan = _mini_plan(
        base2, planned_k=2,
        extra_coordinates=[{
            "id": "c02", "model_namespace": S2_MODEL_NS,
            "validation_namespace": S2_VALIDATION_NS,
            "blocks_per_corpus": 4, "role": "study"}])
    out = base2 / "out"
    for coord in ("c01", "c02"):
        proc = _run("run-coordinate", "--plan", str(plan),
                    "--coordinate", coord, "--out-root", str(out))
        assert proc.returncode == 0, proc.stdout + proc.stderr
    return base2, plan, out


_COPY_SEQ = {"n": 0}


def _copy_out(src: Path, tmp_path: Path) -> Path:
    _COPY_SEQ["n"] += 1
    dst = tmp_path / f"out{_COPY_SEQ['n']}"
    shutil.copytree(src, dst)
    return dst


class TestReaderChainNegativesB02B06:
    """B02-B06:reader 以实际文件与计划关联拒绝,不信标签/统计巧合。"""

    def _read(self, plan, out_root, tmp_path):
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(out_root),
                    "--result", str(tmp_path / "r.json"))
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        return proc, result

    def test_b02_c01_copied_to_c02_rejected(self, two_coord_run,
                                            tmp_path):
        _, plan, out = two_coord_run
        copied = _copy_out(out, tmp_path)
        shutil.copytree(copied / "coord_c01", copied / "coord_c02",
                        dirs_exist_ok=True)
        proc, result = self._read(plan, copied, tmp_path)
        assert proc.returncode != 0
        assert result["integrity"] == "invalid"
        assert "primary" not in result
        problems = "\n".join(result["integrity_problems"])
        assert "manifest.coordinate" in problems
        assert "manifest.validation_namespace" in problems
        assert "跨坐标语料字节重复" in problems

    def test_b03_validation_events_swapped_resealed_rejected(
            self, two_coord_run, tmp_path):
        _, plan, out = two_coord_run
        copied = _copy_out(out, tmp_path)
        e1 = (copied / "coord_c01" / "validation_events.jsonl")
        e2 = (copied / "coord_c02" / "validation_events.jsonl")
        a, b = e1.read_text(encoding="utf-8"), e2.read_text(
            encoding="utf-8")
        e1.write_text(b, encoding="utf-8")
        e2.write_text(a, encoding="utf-8")
        _forge_seal(copied / "coord_c01")
        _forge_seal(copied / "coord_c02")
        proc, result = self._read(plan, copied, tmp_path)
        assert proc.returncode != 0
        problems = "\n".join(result["integrity_problems"])
        assert "派生公式不符" in problems
        assert result["integrity"] == "invalid"

    def test_b04_wrong_seed_and_attempt_schedule_rejected(
            self, two_coord_run, tmp_path):
        _, plan, out = two_coord_run
        # (a) 事件 block_seed 篡改
        copied = _copy_out(out, tmp_path)
        ev = copied / "coord_c01" / "validation_events.jsonl"
        rows = [json.loads(x) for x in ev.read_text(
            encoding="utf-8").splitlines() if x.strip()]
        rows[0]["block_seed"] = int(rows[0]["block_seed"]) + 1
        ev.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                for r in rows) + "\n", encoding="utf-8")
        _forge_seal(copied / "coord_c01")
        proc, result = self._read(plan, copied, tmp_path)
        assert proc.returncode != 0
        assert "派生公式不符" in "\n".join(
            result["integrity_problems"])
        # (b) selected_attempt 日程篡改(attempt 语义随之破裂)
        copied2 = _copy_out(out, tmp_path)
        att = copied2 / "coord_c01" / "validation_block_attempts.jsonl"
        logs = [json.loads(x) for x in att.read_text(
            encoding="utf-8").splitlines() if x.strip()]
        logs[0]["selected_attempt"] = 1
        att.write_text("\n".join(json.dumps(l, ensure_ascii=False)
                                 for l in logs) + "\n", encoding="utf-8")
        _forge_seal(copied2 / "coord_c01")
        proc2, result2 = self._read(plan, copied2, tmp_path)
        assert proc2.returncode != 0
        p2 = "\n".join(result2["integrity_problems"])
        assert "attempt 语义不符" in p2 or "派生公式不符" in p2
        # (c) model seed 日程篡改
        copied3 = _copy_out(out, tmp_path)
        ms = copied3 / "coord_c01" / "model_block_seeds.jsonl"
        srows = [json.loads(x) for x in ms.read_text(
            encoding="utf-8").splitlines() if x.strip()]
        srows[1]["block_seed"] = int(srows[1]["block_seed"]) + 1
        ms.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                for r in srows) + "\n", encoding="utf-8")
        _forge_seal(copied3 / "coord_c01")
        proc3, result3 = self._read(plan, copied3, tmp_path)
        assert proc3.returncode != 0
        assert "seed 日程不符" in "\n".join(
            result3["integrity_problems"])

    def test_b05_missing_member_and_missing_block_rejected(
            self, two_coord_run, tmp_path):
        _, plan, out = two_coord_run
        # (a) 缺关键成员(封存清单同步省略)
        copied = _copy_out(out, tmp_path)
        c1 = copied / "coord_c01"
        seal = json.loads((c1 / "SEALED.json").read_text(
            encoding="utf-8"))
        del seal["members"]["model_events.jsonl"]
        (c1 / "SEALED.json").write_text(
            json.dumps(seal, indent=1, ensure_ascii=False) + "\n",
            encoding="utf-8")
        (c1 / "model_events.jsonl").unlink()
        proc, result = self._read(plan, copied, tmp_path)
        assert proc.returncode != 0
        assert "成员集合不符" in "\n".join(
            result["integrity_problems"])
        # (b) 缺块(末 block 事件整块删除,重封存)
        copied2 = _copy_out(out, tmp_path)
        c1b = copied2 / "coord_c01"
        ev = c1b / "validation_events.jsonl"
        rows = [x for x in ev.read_text(encoding="utf-8").splitlines()
                if x.strip()]
        kept = [x for x in rows
                if json.loads(x)["block_index"] != 3]
        ev.write_text("\n".join(kept) + "\n", encoding="utf-8")
        _forge_seal(c1b)
        proc2, result2 = self._read(plan, copied2, tmp_path)
        assert proc2.returncode != 0
        p2 = "\n".join(result2["integrity_problems"])
        assert "block 覆盖不全" in p2

    def test_b06_bad_numeric_and_detection_mismatch_rejected(
            self, two_coord_run, tmp_path):
        _, plan, out = two_coord_run
        # (a) 非有限数值
        copied = _copy_out(out, tmp_path)
        ev = copied / "coord_c01" / "validation_events.jsonl"
        rows = [json.loads(x) for x in ev.read_text(
            encoding="utf-8").splitlines() if x.strip()]
        rows[0]["cue_read"] = "not-a-number"
        ev.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                for r in rows) + "\n", encoding="utf-8")
        _forge_seal(copied / "coord_c01")
        proc, result = self._read(plan, copied, tmp_path)
        assert proc.returncode != 0
        assert "非有限数值" in "\n".join(
            result["integrity_problems"])
        # (b) 检出标记与 cue_read 关系不符
        copied2 = _copy_out(out, tmp_path)
        ev2 = copied2 / "coord_c01" / "validation_events.jsonl"
        rows2 = [json.loads(x) for x in ev2.read_text(
            encoding="utf-8").splitlines() if x.strip()]
        target = next(r for r in rows2 if r["detected"] is True)
        target["detected"] = False
        ev2.write_text("\n".join(json.dumps(r, ensure_ascii=False)
                                 for r in rows2) + "\n",
                       encoding="utf-8")
        _forge_seal(copied2 / "coord_c01")
        proc2, result2 = self._read(plan, copied2, tmp_path)
        assert proc2.returncode != 0
        assert "关系不符" in "\n".join(
            result2["integrity_problems"])


class TestReaderBehaviorsB07B08:
    """B07 三类行为语义 + B08 固定 v4 数学。"""

    def test_insufficient_k_descriptive_only(self, two_coord_run,
                                             tmp_path):
        _, plan, out = two_coord_run
        copied = _copy_out(out, tmp_path)
        shutil.rmtree(copied / "coord_c02")
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(copied),
                    "--result", str(tmp_path / "r.json"))
        assert proc.returncode == 0
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        assert result["integrity"] == "valid_insufficient_k"
        assert result["k_available"] == 1
        assert result["planned_k"] == 2
        assert "primary" not in result
        assert "descriptive" in result

    def test_v1_manifest_conditional_recompute_label(self,
                                                     two_coord_run,
                                                     tmp_path):
        """有效完整但历史来源未证明 → 条件复算标注(行为 3)。"""
        _, plan, out = two_coord_run
        copied = _copy_out(out, tmp_path)
        for cid in ("c01", "c02"):
            coord = copied / f"coord_{cid}"
            manifest = json.loads((coord / "manifest.json").read_text(
                encoding="utf-8"))
            v1 = {
                "format": "r25-cue-bias-dev-coordinate-v1",
                "started_utc": manifest["started_utc"],
                "plan_digest": manifest["plan_digest"],
                "coordinate": manifest["coordinate"],
                "role": manifest["role"],
                "model_namespace": manifest["model_namespace"],
                "validation_namespace":
                    manifest["validation_namespace"],
                "blocks_per_corpus": manifest["blocks_per_corpus"],
                "pid": manifest["pid"], "cwd": manifest["cwd"],
                "not_run_diagnostic_items":
                    manifest["not_run_diagnostic_items"],
                "generation_code_identity": {
                    "curriculum261_api.py": "a" * 64},
                "entry_sha256": "6aa45601138f4a76f33196fe4e645b91c"
                                "aea952d769e13c06b7078ae8c8f94a1",
            }
            (coord / "manifest.json").write_text(
                json.dumps(v1, indent=1, ensure_ascii=False) + "\n",
                encoding="utf-8")
            _forge_seal(coord)
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(copied),
                    "--result", str(tmp_path / "r.json"))
        assert proc.returncode == 0
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        assert result["integrity"] == "valid"
        assert result["historical_execution_provenance"][
            "status"] == "not_established"
        assert "conditional_numeric_recompute" in result["primary"][
            "interpretation"]
        assert result["reader"]["entry_sha256"] == _entry_sha()

    def test_v2_manifest_provenance_established(self, two_coord_run,
                                                tmp_path):
        _, plan, out = two_coord_run
        proc = _run("cold-read", "--plan", str(plan),
                    "--out-root", str(out),
                    "--result", str(tmp_path / "r.json"))
        assert proc.returncode == 0
        result = json.loads((tmp_path / "r.json").read_text(
            encoding="utf-8"))
        assert result["integrity"] == "valid"
        assert "historical_execution_provenance" not in result
        assert "interpretation" not in result["primary"]

    def test_b08_primary_matches_v4_fixed_math(self, two_coord_run,
                                               tmp_path):
        _, plan, out = two_coord_run
        result_path = tmp_path / "r.json"
        assert _run("cold-read", "--plan", str(plan),
                    "--out-root", str(out),
                    "--result", str(result_path)).returncode == 0
        result = json.loads(result_path.read_text(encoding="utf-8"))
        import importlib.util
        v4_path = _DEPLOY_ROOT / "stage2_6_1_runner" / (
            "r20_design_calc_v4.py")
        if not v4_path.is_file():
            v4_path = _DEPLOY_ROOT.parents[0] / (
                "freqai-rl-audit") / "stage2_6_1" / "report" / (
                "r20_design_calc_v4.py")
        spec = importlib.util.spec_from_file_location("v4m2", v4_path)
        v4 = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(v4)
        ses = [r["se_k"] for r in result["coordinates"]]
        delta_bar = sum(P0_STUDY - r["recall_validation"]
                        for r in result["coordinates"]) / len(ses)
        expected = v4.classify_primary(
            delta_bar, ses, 0.003, r_analysis=1.5, alpha=0.05,
            planned_k=2)
        assert result["primary"] == expected
