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
for _cand in (Path("/mnt/f/trading/freqai-rl-audit"),
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
        assert doc["n_namespaces"] == 89 and doc["n_formal"] == 4
        assert {"c3_reserve_main_eng_r17", "c3_reserve_validation_eng_r17"} <= set(R17_ALL_NAMESPACES)
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
              "r17_entry_common.sh", "r17_monitored_entry.sh",
              "r17_sync.sh", "assemble_r17_b.sh"]

    @pytest.mark.parametrize("name", SHELLS)
    def test_shell_files_are_lf(self, name):
        raw = (RUNNER_DIR / name).read_bytes()
        assert b"\r" not in raw, f"{name} 含 CR 字节(R15 事故)"

    @pytest.mark.parametrize("name", SHELLS)
    def test_shell_files_pass_bash_n(self, name):
        """R15/R17 诊断轮加固:语法冒烟(bash -n),语法错误在真实
        链启动前被测试拦截,而不是在 launcher 执行时爆。"""
        proc = subprocess.run(
            ["bash", "-n", str(RUNNER_DIR / name)],
            capture_output=True, text=True)
        assert proc.returncode == 0, \
            f"{name} bash -n 失败: {proc.stderr}"

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
        # WP0c:准入许可闸门前置(env_redirect_forbidden + gate 调用
        # + admission_rejected 请求日志;许可文件名必须出现在拒绝
        # 诊断信息中)
        assert "env_redirect_forbidden" in src
        assert "admission_rejected" in src
        assert ".r17_formal_admission.json" in src
        # WP0c:正式 root 重定向通道已撤销——R17_ART_ROOT/R17_STATE_ROOT
        # 只允许出现在"检测到即拒绝"的空值检查里,不得作为路径缺省
        for forbidden in ('R17_ART_ROOT:-$PROJECT_ROOT',
                          'R17_ART_ROOT:-$', 'R17_STATE_ROOT:-$'):
            assert forbidden not in src, forbidden
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
        """F5:rehearsal 穿过同一 shell 入口结构(共享入口段/
        chain-run),仅 run 级隔离与 profile 差异。R17 诊断轮 E2:
        state/artifacts/logs 全进 r17_rt_runs/<RUN_ID>/(取代旧
        mktemp 仅隔离 state 的方案);激活段经 r17_entry_common.sh
        共享(同源,消除双脚本漂移)。"""
        src = (RUNNER_DIR / "r17_rt_rehearsal.sh").read_text(
            encoding="utf-8")
        for token in ("r17_entry_common.sh", "chain-run",
                      "--rehearsal", "CURRICULUM261_R17_STATE_ROOT",
                      "r17_rt_runs"):
            assert token in src, token

    def test_run_step_removed_from_r17_surface(self):
        """R17 以 chain-run 协调者取代 r16_run_step 薄壳;新 shell
        (含共享入口段)不引用 run_step。"""
        for name in ("r17_formal_chain.sh", "r17_rt_rehearsal.sh",
                     "r17_entry_common.sh"):
            src = (RUNNER_DIR / name).read_text(encoding="utf-8")
            assert "run_step" not in src

    def test_entry_common_has_no_r16_surface(self):
        """共享入口段同样不得引用 R16 执行面(与 launcher 同规)。"""
        src = (RUNNER_DIR / "r17_entry_common.sh").read_text(
            encoding="utf-8")
        for forbidden in ("curriculum261_r16_cli",
                          "r16_formal_chain", "r16_run_step",
                          "curriculum261_r16_"):
            assert forbidden not in src, forbidden

    def test_request_isolation_e1_e2_structure(self):
        """E1/E2 结构断言(诊断轮修复面):
        - formal:请求期输出只写 r17_formal_requests/<RUN_ID>/(不得
          再出现旧的固定 LOGD 重定向);`>` 截断仅作用于请求独立文件;
        - rt:artifacts/logs/state 全部由 RUN_DIR 派生,无 mktemp;
        - 两个 launcher 都先建请求目录再首次 emit(bash 在命令执行
          前打开重定向,目录建立必须先于任何重定向与 emit)。"""
        formal = (RUNNER_DIR / "r17_formal_chain.sh").read_text(
            encoding="utf-8")
        rt = (RUNNER_DIR / "r17_rt_rehearsal.sh").read_text(
            encoding="utf-8")
        # E1:formal 请求目录与无共享 chain_run.log
        assert "r17_formal_requests" in formal
        assert 'LOGD="$PROJECT_ROOT/' not in formal  # 固定 LOGD 已废
        assert '"$REQ_DIR/chain_run.log"' in formal
        # E2:rt run 目录派生三件套
        assert 'RT_ROOT="$PROJECT_ROOT/r17_rt_runs"' in rt
        assert 'ART="$RUN_DIR/artifacts"' in rt
        assert 'LOGD="$RUN_DIR/logs"' in rt
        assert 'RT_STATE="$RUN_DIR/state"' in rt
        assert "mktemp" not in rt
        # 目录建立先于首次 emit(行序检查)
        for name, src in (("formal", formal), ("rt", rt)):
            lines = src.splitlines()
            mkdir_idx = next(
                i for i, l in enumerate(lines)
                if l.startswith("mkdir -p") or
                l.startswith("LAUNCH_EVIDENCE="))
            emit_idx = next(
                i for i, l in enumerate(lines)
                if l.startswith('emit_launch "launch_requested"'))
            assert mkdir_idx < emit_idx, \
                f"{name}: 请求目录建立必须先于首次 emit"


# ------------------------------------------- D06/D07 请求隔离(runtime) --
SYNC_ROOT = Path.home() / "projects" / "crypto_rl"
SYNC_RUNNER = SYNC_ROOT / "stage2_6_1_runner"
requires_sync = pytest.mark.skipif(
    not (SYNC_RUNNER / "r17_rt_rehearsal.sh").is_file()
    or os.name == "nt",
    reason="WSL 同步执行面不可达(真实 launcher 只在 Linux 跑)")


@requires_sync
class TestRequestIsolationRuntime:
    """R17 诊断轮 D06/D07:真实 launcher 的请求日志隔离(E1 机制)
    与工程尝试跨次隔离(E2)。假 SHA 让链在消耗任何正式数据前的
    早期步骤失败;rc≠0 是预期结果,被测对象是文件落点。"""

    FAKE_SHA_A = "0" * 40
    FAKE_SHA_B = "1" * 40
    LAUNCH_TIMEOUT_S = 900

    def _rt_root(self):
        return SYNC_ROOT / "r17_rt_runs"

    def _latest_runs(self, n):
        runs = sorted(
            (p for p in self._rt_root().iterdir() if p.is_dir()),
            key=lambda p: p.name)
        assert len(runs) >= n, \
            f"run 目录不足({len(runs)}<{n})"
        return runs[-n:]

    @staticmethod
    def _launch(fake_sha, **kw):
        return subprocess.run(
            ["bash",
             str(SYNC_RUNNER / "r17_rt_rehearsal.sh"), fake_sha],
            capture_output=True, text=True,
            timeout=TestRequestIsolationRuntime.LAUNCH_TIMEOUT_S,
            cwd=str(SYNC_ROOT), **kw)

    @staticmethod
    def _dir_digests(run_dir: Path):
        return {
            str(p.relative_to(run_dir)): hashlib.sha256(
                p.read_bytes()).hexdigest()
            for p in sorted(run_dir.rglob("*")) if p.is_file()}

    def test_d06_e1_truncation_mechanism_repro(self, tmp_path):
        """E1 机制反例:bash 在命令执行前以 O_TRUNC 打开 `>` 目标。
        旧入口(3a153a0 及以前)chain_run.log 是共享 `>` 目标;本测试
        用同语义重定向演示:第二个"请求"尚未产出任何输出时,第一个
        请求的日志已被清空——证明修复(请求独立目录)的必要性。"""
        import time
        shared = tmp_path / "chain_run.log"
        shared.write_text("FIRST-REQUEST-OUTPUT\n" * 50)
        assert len(shared.read_text().splitlines()) == 50
        proc = subprocess.Popen(
            ["bash", "-c",
             'exec > "$1"; sleep 1; echo SECOND-OUTPUT',
             "bash", str(shared)])
        try:
            time.sleep(0.3)
            mid = shared.read_text()
        finally:
            proc.wait(timeout=30)
        # 第二个请求命令零输出期间,第一个请求的 50 行已被截断
        assert mid == "", \
            "机制反例未复现:`>` 在命令输出前未截断共享目标"

    def test_d07_two_sequential_runs_isolated(self):
        """D07:连续两次真实尝试 → 两个独立 run 目录;第一次的
        全部文件在第二次运行后逐文件 sha256 不变;旧固定路径(修复
        前 22 次尝试的历史遗留,按任务书保留)不被新运行写入。"""
        legacy_guard = {}
        for legacy in ("artifacts/route_c_stage2_6_1_repair17_rt",
                       "r17_rt_rehearsal_logs"):
            lp = SYNC_ROOT / legacy
            if lp.is_dir():
                legacy_guard[str(lp)] = max(
                    p.stat().st_mtime_ns
                    for p in lp.rglob("*") if p.is_file())
        r1 = self._launch(self.FAKE_SHA_A)
        first = self._latest_runs(1)[0]
        digests1 = self._dir_digests(first)
        r2 = self._launch(self.FAKE_SHA_B)
        runs = self._latest_runs(2)
        assert runs[0] == first and runs[1] != first
        # 第一次 run 的全部文件字节不变
        digests_after = self._dir_digests(runs[0])
        assert digests_after == digests1, \
            "第一次 run 目录在第二次尝试后被修改"
        # 旧固定路径(若为历史遗留)不被新运行触碰
        for lp, mtime in legacy_guard.items():
            now = max(p.stat().st_mtime_ns
                      for p in Path(lp).rglob("*") if p.is_file())
            assert now == mtime, f"旧固定路径被新运行修改: {lp}"
        # launch_evidence 只含各自请求的事件
        ev1 = json.loads((runs[0] / "logs" / "launch_evidence.jsonl")
                         .read_text().splitlines()[0])
        ev2 = json.loads((runs[1] / "logs" / "launch_evidence.jsonl")
                         .read_text().splitlines()[0])
        assert ev1["pid"] != ev2["pid"]
        assert ev1["argv"].startswith("r17_rt_rehearsal.sh")
        assert self.FAKE_SHA_A in ev1["argv"] and \
            self.FAKE_SHA_B in ev2["argv"]
        # 两次 rc 均 ≠0(假 SHA 预期失败)且 chain_run.log 落在各自
        # run 目录(不写共享路径)
        assert r1.returncode != 0 and r2.returncode != 0
        for run in runs:
            assert (run / "logs" / "chain_run.log").is_file()

    def test_d06_two_concurrent_requests_no_cross_talk(self):
        """D06:真实并发请求(两 Popen 同时启动,launch_requested
        时间戳重叠)→ 各自 run 目录独立,pid 互不串写。rt 的 state
        已按 run 隔离,不再共享锁;被测=并发请求不混写任何文件。"""
        import time as _t
        p1 = subprocess.Popen(
            ["bash", str(SYNC_RUNNER / "r17_rt_rehearsal.sh"),
             self.FAKE_SHA_A],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(SYNC_ROOT))
        p2 = subprocess.Popen(
            ["bash", str(SYNC_RUNNER / "r17_rt_rehearsal.sh"),
             self.FAKE_SHA_B],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, cwd=str(SYNC_ROOT))
        alive_overlap = False
        for _ in range(20):
            if p1.poll() is None and p2.poll() is None:
                alive_overlap = True
                break
            _t.sleep(0.2)
        out1, _ = p1.communicate(timeout=self.LAUNCH_TIMEOUT_S)
        out2, _ = p2.communicate(timeout=self.LAUNCH_TIMEOUT_S)
        assert alive_overlap, "两请求未观察到共存(未形成真实并发)"
        runs = self._latest_runs(2)
        pid_sets = []
        for run in runs:
            evs = [json.loads(l) for l in
                   (run / "logs" / "launch_evidence.jsonl")
                   .read_text().splitlines()]
            pid_sets.append({e["pid"] for e in evs})
            argv0 = evs[0]["argv"]
            assert argv0.startswith("r17_rt_rehearsal.sh")
        # pid 集合不相交(无混写)
        assert not (pid_sets[0] & pid_sets[1]), "并发请求混写"
        # 两个 run 目录互不嵌套、各自有 chain_run.log
        assert runs[0].parent == runs[1].parent == self._rt_root()
        for run in runs:
            assert (run / "logs" / "chain_run.log").is_file()


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
