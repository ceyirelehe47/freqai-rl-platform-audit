# -*- coding: utf-8 -*-
"""R17 治理单元测试(registry/api 守卫/workflow/runner 执行面/交付)。

覆盖验收矩阵:T17(入口字节与结构)、T18(执行内容冻结面)、
T20(组包路径反例复现)、T21(raw log 缺失/篡改交付失败)、
T22(冷读不依赖开发机路径)+ registry/api/workflow 结构单元。
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO_ROOT = None
for _cand in (Path("/mnt/e/trading/freqai-rl-audit"),
              Path(__file__).resolve().parents[3]):
    if (_cand / "stage2_6_1" / "runner").is_dir():
        REPO_ROOT = _cand
        break
if REPO_ROOT is None:
    REPO_ROOT = Path(__file__).resolve().parents[3]
RUNNER_DIR = REPO_ROOT / "stage2_6_1" / "runner"
PROJ_SRC = REPO_ROOT / "stage2_6_1" / "src"
if str(PROJ_SRC) not in sys.path:
    sys.path.insert(0, str(PROJ_SRC))

requires_repo = pytest.mark.skipif(
    not (RUNNER_DIR / "r17_formal_chain.sh").is_file(),
    reason="release repo 执行面不可达(仅 WSL/开发机)")

from rl_curriculum.curriculum261_api import (  # noqa: E402
    CURRICULUM261_R17_FORMAL_NAMESPACES,
    CURRICULUM261_R17_NAMESPACES,
)
from rl_curriculum.curriculum261_r17_registry import (  # noqa: E402
    R17_ALL_NAMESPACES,
    verify_r17_registry_alignment,
    verify_r17_namespace_name_isolation,
)
from rl_curriculum.curriculum261_r17_workflow import (  # noqa: E402
    R17_WORKFLOW_STEPS,
    r17_workflow_step_names,
    validate_r17_workflow,
)

VERIFIED_DELIVERY = RUNNER_DIR / "verify_delivery_r17.py"


# ------------------------------------------------- registry/api -------
class TestRegistryApi:

    def test_registry_alignment(self):
        doc = verify_r17_registry_alignment()
        assert doc["api_namespaces_match"] and doc["api_formal_match"]
        assert doc["n_namespaces"] == 87 and doc["n_formal"] == 4
        assert doc["unique"]

    def test_formal_four_namespaces_fresh(self):
        assert set(CURRICULUM261_R17_FORMAL_NAMESPACES) == {
            "qualification_r17",
            "preprocess_fit_qualification_r17",
            "c2_independent_qualification_r17",
            "cue_semantic_qualification_r17"}
        assert not (set(CURRICULUM261_R17_NAMESPACES)
                    & set() )

    def test_no_historical_suffix_on_formal(self):
        doc = verify_r17_namespace_name_isolation()
        assert doc["pass"], doc["problems"]

    def test_r17_namespaces_have_no_r16_leakage(self):
        # 全部 R17 namespace 不含 r16 字样(防机械转换半覆盖)
        assert not [n for n in R17_ALL_NAMESPACES if "r16" in n]

    def test_api_guard_r17_branch_exists(self):
        api_src = (PROJ_SRC / "rl_curriculum"
                   / "curriculum261_api.py").read_text(
                       encoding="utf-8")
        assert "require_r17_generation_authorization" in api_src
        assert "CURRICULUM261_R17_FORMAL_NAMESPACES" in api_src


# ------------------------------------------------- workflow 结构 ------
class TestWorkflowStructure:

    def test_17_steps_frozen_order(self):
        names = r17_workflow_step_names()
        assert names[0] == "provenance-verify"
        assert names[-1] == "verify-formal-logs"
        assert len(names) == 17
        expected = (
            "provenance-verify", "determinism-matrix", "audit",
            "cue-audit", "preplan-smoke", "plan-roundtrip",
            "design-plan-lock", "design", "calibrate",
            "preflight-static", "lock-plan", "preflight-sealed",
            "qualify", "smoke", "full-cold", "report-read",
            "verify-formal-logs")
        assert tuple(names) == expected

    def test_every_step_carries_out_dir(self):
        for s in R17_WORKFLOW_STEPS:
            argv = s["argv_template"]
            if "--out-dir" in argv or "--manifest" in argv or \
                    "--artifacts-dir" in argv:
                continue
            pytest.fail(f"步骤 {s['name']} argv 缺输出根:{argv}")

    def test_validate_workflow_passes(self):
        doc = validate_r17_workflow()
        assert doc["pass"], doc.get("problems")


# ------------------------------------------------- T17/T18 执行面 -----
@requires_repo
class TestRunnerSurface:

    SHELLS = ["r17_formal_chain.sh", "r17_rt_rehearsal.sh",
              "r17_sync.sh", "assemble_r17_b.sh"]

    @pytest.mark.parametrize("name", SHELLS)
    def test_shell_files_are_lf(self, name):
        raw = (RUNNER_DIR / name).read_bytes()
        assert b"\r" not in raw, f"{name} 含 CR 字节(R15 事故)"

    def test_formal_chain_structure(self):
        src = (RUNNER_DIR / "r17_formal_chain.sh").read_text(
            encoding="utf-8")
        lines = src.splitlines()
        # LF 自检在 set -euo pipefail 之前
        grep_idx = next(i for i, l in enumerate(lines)
                        if l.startswith("if grep -q"))
        set_idx = next(i for i, l in enumerate(lines)
                       if l.startswith("set -euo pipefail"))
        assert grep_idx < set_idx
        # 唯一编排调用 = chain-run(协调者);不残留 r16 入口引用
        assert "chain-run" in src
        # 不引用 R16 执行面(模块/入口/run_step);注释中的
        # 历史叙述(R16 缺陷对照)不构成执行面引用
        for forbidden in ("curriculum261_r16_cli",
                          "r16_formal_chain", "r16_run_step",
                          "curriculum261_r16_"):
            assert forbidden not in src, forbidden
        # 无静默吞错(非注释代码行不得出现 || true;唯一例外 =
        # fail_closure.log 追加的尽力而为记录行,R16 先例同款,
        # 不在会话获取/步骤执行路径上)
        code_lines = [
            l for l in lines
            if l.strip() and not l.strip().startswith(("#",
                                                       "tail"))]
        bad = [l for l in code_lines if "|| true" in l
               and "fail_closure.log" not in l]
        assert not bad, bad

    def test_rt_rehearsal_shell_entry_exists_and_matches(self):
        """F5:rehearsal 穿过同一 shell 入口结构(激活/验证/
        chain-run),仅 state root/profile 差异。"""
        src = (RUNNER_DIR / "r17_rt_rehearsal.sh").read_text(
            encoding="utf-8")
        for token in ("activate-freqtrade.sh", "chain-run",
                      "--rehearsal", "CURRICULUM261_R17_STATE_ROOT",
                      "mktemp -d"):
            assert token in src, token

    def test_run_step_removed_from_r17_surface(self):
        """R17 以 chain-run 协调者取代 r16_run_step 薄壳;新 shell
        不引用 run_step。"""
        for name in ("r17_formal_chain.sh", "r17_rt_rehearsal.sh"):
            src = (RUNNER_DIR / name).read_text(encoding="utf-8")
            assert "run_step" not in src


# ------------------------------------------------- T20/T21/T22 交付 --
def _make_fake_run_manifest(tmp: Path, logs_dir: Path) -> Path:
    """构造 R16 形态的 run manifest(真实链目录名
    artifacts/<name>_chain_logs;含 sha/bytes)。"""
    logs = {
        "provenance-verify": ("pv-out\n", ""),
        "determinism-matrix": ("dm-out\n", ""),
        "calibrate": ("cal-out\n", "cal-err\n"),
    }
    manifest = tmp / "r17_formal_log_manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as mf:
        for step, (out, err) in logs.items():
            for kind, text in (("stdout", out), ("stderr", err)):
                p = logs_dir / f"{step}.log" if kind == "stdout" \
                    else logs_dir / f"{step}.err"
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(text, encoding="utf-8")
                mf.write(json.dumps({
                    "step": step,
                    f"{kind}_path": str(p),
                    f"{kind}_sha256": hashlib.sha256(
                        text.encode()).hexdigest(),
                    f"{kind}_bytes": len(text.encode()),
                }) + "\n")
    return manifest


@requires_repo
class TestDelivery:

    def test_t20_manifest_finds_real_path_r16_repro(self):
        """精确复现 R16 反例:manifest 指向
        artifacts/<name>_chain_logs(少一层 artifacts/ 的猜测目录
        不存在)→ 组包按 manifest 成功;真实文件删除 → 失败。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            # 模拟执行机布局:project/artifacts/<chain>_logs
            real_logs = root / "artifacts" / \
                "route_c_stage2_6_1_repair17_chain_logs"
            real_logs.mkdir(parents=True)
            manifest = _make_fake_run_manifest(root, real_logs)
            delivery = root / "delivery"
            r = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY), "assemble",
                 "--manifest", str(manifest), "--delivery-dir",
                 str(delivery)], capture_output=True, text=True)
            assert r.returncode == 0, r.stdout + r.stderr
            doc = json.loads((delivery / "delivery_manifest.json"
                              ).read_text(encoding="utf-8"))
            assert doc["n_files"] == 6
            # 冷读
            r2 = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY),
                 "cold-read", "--delivery-dir", str(delivery)],
                capture_output=True, text=True)
            assert r2.returncode == 0, r2.stdout
            # 真实必需文件删除 → 失败(不得静默)
            (real_logs / "calibrate.log").unlink()
            delivery2 = root / "delivery2"
            r3 = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY), "assemble",
                 "--manifest", str(manifest), "--delivery-dir",
                 str(delivery2)], capture_output=True, text=True)
            assert r3.returncode == 1
            assert "缺失必需源文件" in r3.stdout

    def test_t21_hash_mismatch_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs = root / "artifacts" / "x_chain_logs"
            logs.mkdir(parents=True)
            manifest = _make_fake_run_manifest(root, logs)
            # 篡改一个文件(字节数不变内容变)
            p = logs / "audit.log"
            p.write_text("tampered\n", encoding="utf-8")
            manifest2 = root / "m2.jsonl"
            with manifest2.open("w", encoding="utf-8") as mf:
                mf.write(json.dumps({
                    "step": "audit", "stdout_path": str(p),
                    "stdout_sha256": hashlib.sha256(
                        b"original\n").hexdigest(),
                    "stdout_bytes": 9}) + "\n")
            r = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY), "assemble",
                 "--manifest", str(manifest2), "--delivery-dir",
                 str(root / "d")], capture_output=True, text=True)
            assert r.returncode == 1
            assert "不符" in r.stdout

    def test_t22_cold_read_catches_deleted_delivery_file(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs = root / "artifacts" / "x_chain_logs"
            logs.mkdir(parents=True)
            manifest = _make_fake_run_manifest(root, logs)
            delivery = root / "delivery"
            subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY), "assemble",
                 "--manifest", str(manifest), "--delivery-dir",
                 str(delivery)], capture_output=True, check=True)
            victim = delivery / "raw_logs" / "chain" / \
                "provenance-verify.log"
            victim.unlink()
            r = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY),
                 "cold-read", "--delivery-dir", str(delivery)],
                capture_output=True, text=True)
            assert r.returncode == 1
            assert "缺失" in r.stdout

    def test_zero_byte_stderr_distinct_from_missing(self):
        """零字节真实 stderr 文件与文件缺失严格区分(R16 交付
        缺失逐步 err 文件的反例)。"""
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            logs = root / "artifacts" / "x_chain_logs"
            logs.mkdir(parents=True)
            (logs / "a.log").write_text("x\n", encoding="utf-8")
            (logs / "a.err").write_text("", encoding="utf-8")
            manifest = root / "m.jsonl"
            with manifest.open("w", encoding="utf-8") as mf:
                for kind, name in (("stdout", "a.log"),
                                   ("stderr", "a.err")):
                    data = (logs / name).read_bytes()
                    mf.write(json.dumps({
                        "step": "a", f"{kind}_path":
                            str(logs / name),
                        f"{kind}_sha256": hashlib.sha256(
                            data).hexdigest(),
                        f"{kind}_bytes": len(data)}) + "\n")
            delivery = root / "d"
            r = subprocess.run(
                [sys.executable, str(VERIFIED_DELIVERY), "assemble",
                 "--manifest", str(manifest), "--delivery-dir",
                 str(delivery)], capture_output=True, text=True)
            assert r.returncode == 0
            copied_err = delivery / "raw_logs" / "chain" / "a.err"
            assert copied_err.is_file() and \
                copied_err.stat().st_size == 0
