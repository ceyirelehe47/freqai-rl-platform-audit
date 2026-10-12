# -*- coding: utf-8 -*-
"""RouteC_CueAudit R1(FiniteRepair_R1)F1–F5 修复测试。

对应 IndependentReview_33407fd4 阻塞发现,全部针对**新候选真实模块**
(非 reference/probes 旧片段):
- F1:保留 cue namespace 任一侧涉及(混族/单边/跨角色)即拒绝,
  免锁/缩减组合零 core 调用;合法正式/普通工程对照。
- F2:正式身份关键步骤真实 handler 链,实跑 4 步:cue-audit→
  preplan-smoke→plan-roundtrip→design-plan-lock(跨步产物真实流动
  与消费);audit/determinism-matrix 与 design 及其后步骤依赖真实
  repo 冻结面,如实列为未验证层次(测试内注释披露)。负例组合。
  科学重叶=生成函数级替身(边界明示)。
- F3:child 原件执行期落盘/原字节/冲突前置/中断保全/时刻区分。
- F4:观察器 PID+starttime 绑定;父 shell 同 pattern/无关同名进程
  不误认;PID 复用识别;纯 pattern 拒绝。
- F5:多重集工具真多重集/状态分离/正反例与 rc。
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

_BASE = Path(__file__).resolve().parents
TREE = next(b for b in _BASE if (b / "src" / "rl_curriculum").is_dir()
            or (b / "stage2_6_1" / "src" / "rl_curriculum").is_dir())
SRC_DIR = (TREE / "src" if (TREE / "src" / "rl_curriculum").is_dir()
           else TREE / "stage2_6_1" / "src")
RUNNER_DIR = (TREE / "stage2_6_1" / "runner"
              if (TREE / "stage2_6_1" / "src" / "rl_curriculum").is_dir()
              else Path.home() / "projects" / "crypto_rl" / (
                  "stage2_6_1_runner"))
sys.path.insert(0, str(SRC_DIR))
sys.path.insert(0, str(RUNNER_DIR))

import rl_curriculum.curriculum261_r17_cue_contract as cue_mod  # noqa: E402
from rl_curriculum.curriculum261_qaf_attempt import (  # noqa: E402
    QAF3_ATTEMPT_ID, QAF_ATTEMPTS, qaf_attempt_family,
)
from rl_curriculum.curriculum261_r17_cue_contract import (  # noqa: E402
    protected_cue_namespace_role, registered_cue_contract_family,
    run_cue_contract_audit,
)

FAM3 = qaf_attempt_family(QAF3_ATTEMPT_ID)
FAM2 = qaf_attempt_family("qaf_v2")


# ==================== F1:保留身份任一侧涉及 ====================
class TestF1ProtectedIdentity:
    def _capture_core(self, monkeypatch):
        calls = []
        monkeypatch.setattr(
            cue_mod, "_run_cue_contract_audit_core",
            lambda *a, **k: calls.append(k) or {"pass": True})
        return calls

    @pytest.mark.parametrize("m,v", [
        (FAM3.cue_contract_model, FAM2.cue_contract_validation),
        (FAM2.cue_contract_model, FAM3.cue_contract_validation),
        # 跨角色:v3 的 validation 名放在 model 位
        (FAM3.cue_contract_validation, FAM3.cue_contract_model),
        (FAM3.cue_contract_validation, None),
        # 单边
        (FAM3.cue_contract_model, None),
        (None, FAM3.cue_contract_validation),
        (None, FAM3.cue_contract_model),
        # 注册名+未知工程名
        (FAM3.cue_contract_model, "eng_ns_x"),
        ("eng_ns_x", FAM3.cue_contract_validation),
    ])
    def test_protected_involvement_unlocked_rejected(self, m, v,
                                                     monkeypatch):
        calls = self._capture_core(monkeypatch)
        with pytest.raises(RuntimeError, match="保留 cue namespace"):
            run_cue_contract_audit(
                None, blocks_per_corpus=2, mc_events=64,
                model_namespace=m, validation_namespace=v,
                require_locked_plan=False)
        assert calls == []  # core 零调用

    def test_protected_involvement_with_lock_rejected_pre_plan(
            self, tmp_path, monkeypatch):
        """混族 + require_locked_plan=True:计划加载前拒绝(core 零调
        用;loader 也零调用——不读不存在的计划)。"""
        calls = self._capture_core(monkeypatch)
        loads = []
        monkeypatch.setattr(
            cue_mod, "load_locked_cue_audit_plan_r17",
            lambda d: loads.append(d) or {})
        with pytest.raises(RuntimeError, match="保留 cue namespace"):
            run_cue_contract_audit(
                tmp_path, require_locked_plan=True,
                model_namespace=FAM3.cue_contract_model,
                validation_namespace=FAM2.cue_contract_validation)
        assert calls == [] and loads == []

    @pytest.mark.parametrize("scale", [
        {}, {"blocks_per_corpus": 10}, {"mc_events": 2_000_000},
        # R1 复验整改补:显式等价规模(与正式默认同值的显式传入;
        # 免锁形态下即使规模"正确"也必须拒绝)
        {"blocks_per_corpus": cue_mod.AUDIT_BLOCKS_PER_CORPUS,
         "mc_events": cue_mod.AUDIT_N_EVENTS}])
    def test_full_pair_unlocked_or_scaled_rejected(self, scale,
                                                   monkeypatch):
        calls = self._capture_core(monkeypatch)
        with pytest.raises(RuntimeError):
            run_cue_contract_audit(
                model_namespace=FAM3.cue_contract_model,
                validation_namespace=FAM3.cue_contract_validation,
                require_locked_plan=False, **scale)
        assert calls == []

    def test_role_resolver(self):
        assert protected_cue_namespace_role(
            FAM3.cue_contract_model) == (FAM3, "model")
        assert protected_cue_namespace_role(
            FAM3.cue_contract_validation) == (FAM3, "validation")
        assert protected_cue_namespace_role("rt_cue_model_r17") is None
        assert protected_cue_namespace_role(None) is None
        assert protected_cue_namespace_role(
            cue_mod.AUDIT_MODEL_NAMESPACE) is None  # legacy 非保留

    def test_legal_formal_and_plain_engineering_controls(
            self, tmp_path, monkeypatch):
        from rl_curriculum.curriculum261_r17_cue_contract import (
            lock_cue_audit_plan_r17,
        )
        calls = self._capture_core(monkeypatch)
        # 合法正式正例(完整对+锁定计划+冻结规模)
        lock_cue_audit_plan_r17(
            tmp_path, model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation)
        run_cue_contract_audit(
            tmp_path, require_locked_plan=True,
            model_namespace=FAM3.cue_contract_model,
            validation_namespace=FAM3.cue_contract_validation)
        assert calls[0]["formal"] is True
        # 普通工程正例(不涉保留名)不受影响
        run_cue_contract_audit(
            None, blocks_per_corpus=2, mc_events=64,
            model_namespace="eng_ns_a", validation_namespace="eng_ns_b")
        assert calls[1]["formal"] is False


# ==================== F3:child 原件执行期保全 ====================
class TestF3ChildOriginals:
    def _mod(self):
        import importlib
        return importlib.import_module("qaf_v2_operator_entry")

    def test_conflict_rejected_before_child_runs(self, tmp_path):
        op = self._mod()
        (tmp_path / "operator_child_logs").mkdir()
        (tmp_path / "operator_child_logs"
         / "execute_launch.meta.json").write_text("x")
        with pytest.raises(FileExistsError):
            op.open_child_original_slots(tmp_path, "launch")
        # child 未启动:marker 不存在
        assert not (tmp_path / "child_ran").exists()

    def test_crlf_raw_bytes_fidelity(self, tmp_path):
        op = self._mod()
        slots = op.open_child_original_slots(tmp_path, "launch")
        rec = op.run_child_with_originals(
            [sys.executable, "-c",
             "import sys;sys.stdout.buffer.write(b'one\\r\\ntwo\\rEND');"
             "sys.stdout.flush();sys.stderr.buffer.write(b'ERR\\r\\n');"
             "sys.exit(7)"],
            cwd=str(tmp_path), env=dict(os.environ), slots=slots,
            child="launch")
        raw = slots.out_path.read_bytes()
        assert raw == b"one\r\ntwo\rEND"  # 原字节,无换行转换
        assert slots.err_path.read_bytes() == b"ERR\r\n"
        meta = rec["meta"]
        assert meta["returncode"] == 7
        import hashlib
        assert meta["stdout_sha256"] == hashlib.sha256(raw).hexdigest()
        assert meta["stdout_bytes"] == len(raw)

    def test_long_output_full_and_timing_fields(self, tmp_path):
        op = self._mod()
        slots = op.open_child_original_slots(tmp_path, "launch")
        rec = op.run_child_with_originals(
            [sys.executable, "-c", "print('L'*20000);print('E'*500,"
             "file=__import__('sys').stderr)"],
            cwd=str(tmp_path), env=dict(os.environ), slots=slots,
            child="launch")
        assert len(slots.out_path.read_bytes()) >= 20_000  # 超 tail 全保
        m = rec["meta"]
        assert m["started_utc"] and m["ended_utc"] and m["archived_utc"]
        assert m["started_utc"] <= m["ended_utc"] <= m["archived_utc"]

    def test_parent_interrupted_preserves_partial(self, tmp_path,
                                                  monkeypatch):
        op = self._mod()
        slots = op.open_child_original_slots(tmp_path, "launch")
        real_popen = subprocess.Popen

        class FakeProc:
            def __init__(self, *a, **k):
                self._p = real_popen(*a, **k)

            def wait(self):
                # 等已产出内容落盘后再模拟父侧中断
                deadline = time.time() + 10
                while time.time() < deadline:
                    if b"partial" in slots.out_path.read_bytes():
                        break
                    time.sleep(0.05)
                raise KeyboardInterrupt
        monkeypatch.setattr(op.subprocess, "Popen", FakeProc)
        with pytest.raises(KeyboardInterrupt):
            op.run_child_with_originals(
                [sys.executable, "-c",
                 "import time;print('partial',flush=True);time.sleep(30)"],
                cwd=str(tmp_path), env=dict(os.environ), slots=slots,
                child="launch")
        monkeypatch.setattr(op.subprocess, "Popen", real_popen)
        meta = json.loads(slots.meta_path.read_text("utf-8"))
        assert meta["returncode"] is None  # rc 不可得,如实
        assert meta["rc_source"] == "parent_interrupted"
        assert b"partial" in slots.out_path.read_bytes()  # 已产出保全

    def test_empty_stderr_nonzero_rc(self, tmp_path):
        op = self._mod()
        slots = op.open_child_original_slots(tmp_path, "launch")
        rec = op.run_child_with_originals(
            [sys.executable, "-c", "raise SystemExit(3)"],
            cwd=str(tmp_path), env=dict(os.environ), slots=slots,
            child="launch")
        assert slots.err_path.read_bytes() == b""
        assert rec["meta"]["returncode"] == 3
        assert rec["meta"]["stderr_bytes"] == 0

    def test_no_overwrite_of_existing_originals(self, tmp_path):
        op = self._mod()
        op.open_child_original_slots(tmp_path, "launch").close()
        with pytest.raises(FileExistsError):
            op.open_child_original_slots(tmp_path, "launch")


# ==================== F4:观察器实例绑定 ====================
class TestF4WatcherBinding:
    def _spawn(self, code, lifetime):
        return subprocess.Popen(
            [sys.executable, "-c",
             "import time\n" + code + "\ntime.sleep(%r)\n" % lifetime],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def _run_sync(self, watcher, timeout=30):
        import threading
        box = {}

        def _go():
            box["rc"] = watcher.run()

        t = threading.Thread(target=_go)
        t.start()
        t.join(timeout=timeout)
        return box

    def test_normal_end_rc_recorded(self, tmp_path):
        from qaf_child_watcher import ChildWatcher
        rc_file = tmp_path / "rc"
        child = self._spawn(
            "open(%r,'w').write('0')" % str(rc_file), 0.4)
        out = tmp_path / "w.jsonl"
        w = ChildWatcher(child.pid, rc_file, out,
                         target_log=tmp_path / "nope.log",
                         interval_s=0.05, max_ticks=300)
        box = self._run_sync(w)
        child.wait(timeout=30)
        assert box["rc"] == 0
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        assert rows[-1]["final_reason"] == "rc_recorded_and_process_ended"

    def test_abnormal_no_rc(self, tmp_path):
        from qaf_child_watcher import ChildWatcher
        import signal
        child = self._spawn("", 30)
        time.sleep(0.3)
        out = tmp_path / "w.jsonl"
        w = ChildWatcher(child.pid, tmp_path / "rc", out,
                         interval_s=0.05, max_ticks=400, grace_ticks=2)
        import threading
        box = {}
        t = threading.Thread(target=lambda: box.update(rc=w.run()))
        t.start()
        time.sleep(0.3)
        child.send_signal(signal.SIGKILL)
        child.wait(timeout=30)
        t.join(timeout=30)
        assert box["rc"] == 0
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        assert rows[-1]["final_reason"] == "abnormal_end_no_rc"

    def test_parent_shell_same_pattern_not_confused(self, tmp_path):
        """父 shell/无关进程 cmdline 含 pattern 不影响 PID 绑定判定
        (v1 在此场景永不退出;v2 以 (pid,starttime) 判定)。"""
        from qaf_child_watcher import ChildWatcher
        decoy = subprocess.Popen(
            ["bash", "-c", "sleep 30 # qafv3_watched_marker"])
        rc_file = tmp_path / "rc"
        child = self._spawn(
            "open(%r,'w').write('0')" % str(rc_file), 0.4)
        out = tmp_path / "w.jsonl"
        w = ChildWatcher(child.pid, rc_file, out, pattern=(
            "qafv3_watched_marker"), interval_s=0.05, max_ticks=300)
        box = self._run_sync(w)
        child.wait(timeout=30)
        decoy.kill()
        decoy.wait(timeout=30)
        assert box["rc"] == 0  # 不因同 pattern 无关进程卡死
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        assert rows[-1]["final_reason"] == "rc_recorded_and_process_ended"

    def test_pid_reuse_detected_by_start_token(self, tmp_path):
        """绑定 token 与现存活进程 starttime 不符 → 立即视为目标
        不存在(异常结束路径),不误绑复用 PID 的新进程。"""
        from qaf_child_watcher import ChildWatcher
        other = self._spawn("", 30)  # 占位活进程
        w = ChildWatcher(other.pid, tmp_path / "rc",
                         tmp_path / "w.jsonl", interval_s=0.05,
                         max_ticks=50, grace_ticks=2,
                         start_token=-12345)  # 失配 token
        box = self._run_sync(w, timeout=15)
        other.kill()
        other.wait(timeout=30)
        assert box["rc"] == 0
        rows = [json.loads(x) for x in
                (tmp_path / "w.jsonl").read_text().splitlines()]
        assert rows[0]["target_alive"] is False
        assert rows[-1]["final_reason"] == "abnormal_end_no_rc"

    def test_stop_file(self, tmp_path):
        from qaf_child_watcher import ChildWatcher
        import threading
        child = self._spawn("", 30)
        time.sleep(0.2)
        stop = tmp_path / "stop"
        out = tmp_path / "w.jsonl"
        w = ChildWatcher(child.pid, tmp_path / "rc", out, stop_file=stop,
                         interval_s=0.05, max_ticks=400)
        box = {}
        t = threading.Thread(target=lambda: box.update(rc=w.run()))
        t.start()
        time.sleep(0.2)
        stop.write_text("", encoding="utf-8")
        t.join(timeout=30)
        child.kill()
        child.wait(timeout=30)
        rows = [json.loads(x) for x in out.read_text().splitlines()]
        assert rows[-1]["final_reason"] == "stop_requested"

    def test_pattern_only_cli_refused(self, tmp_path, capsys):
        from qaf_child_watcher import main as watcher_main
        rc = watcher_main([
            "--pattern", "anything", "--rc-file", str(tmp_path / "rc"),
            "--out", str(tmp_path / "w.jsonl")])
        assert rc == 2
        assert not (tmp_path / "w.jsonl").exists()

    def test_pid_file_binding(self, tmp_path):
        from qaf_child_watcher import main as watcher_main
        rc_file = tmp_path / "rc"
        child = self._spawn(
            "open(%r,'w').write('0')" % str(rc_file), 0.4)
        (tmp_path / "pid").write_text(str(child.pid))
        import threading
        box = {}
        t = threading.Thread(target=lambda: box.update(
            rc=watcher_main([
                "--pid-file", str(tmp_path / "pid"),
                "--rc-file", str(rc_file),
                "--out", str(tmp_path / "w.jsonl"),
                "--interval", "0.05", "--max-ticks", "300"])))
        t.start()
        t.join(timeout=30)
        child.wait(timeout=30)
        assert box["rc"] == 0
        rows = [json.loads(x) for x in
                (tmp_path / "w.jsonl").read_text().splitlines()]
        assert rows[-1]["final_reason"] == "rc_recorded_and_process_ended"


    def test_max_ticks_exhausted(self, tmp_path):
        """R1 复验整改补:max_ticks 用尽如实 rc=3,不伪装正常结束
        (v1 终止形态回归覆盖)。"""
        from qaf_child_watcher import ChildWatcher
        child = self._spawn("", 5.0)   # 长跑目标
        try:
            w = ChildWatcher(
                child.pid, rc_file=tmp_path / "rc",
                out_file=tmp_path / "w.jsonl", interval_s=0.03,
                max_ticks=3, grace_ticks=2)
            rc = w.run()
            assert rc == 3
            rows = [json.loads(x) for x in
                    (tmp_path / "w.jsonl").read_text().splitlines()]
            assert rows[-1]["final_reason"] == "max_ticks_exhausted"
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_out_create_only_conflict_refused(self, tmp_path):
        """R1 复验整改补:观察输出已存在时拒绝创建(rc=2),既有
        文件字节不被触碰。"""
        from qaf_child_watcher import main as watcher_main
        child = self._spawn("", 3.0)
        try:
            out = tmp_path / "w.jsonl"
            out.write_text("EXISTING-ORIGINAL\n", encoding="utf-8")
            rc = watcher_main([
                "--pid", str(child.pid),
                "--rc-file", str(tmp_path / "rc"),
                "--out", str(out),
                "--interval", "0.05", "--max-ticks", "5"])
            assert rc == 2
            assert out.read_text(
                encoding="utf-8") == "EXISTING-ORIGINAL\n"
        finally:
            child.kill()
            child.wait(timeout=10)

    def test_init_dead_target_refused(self, tmp_path):
        """R1 复验整改补:init 时目标已死(starttime 采样不到)拒绝
        绑定(fail closed,不退化为 PID 存在性)。"""
        from qaf_child_watcher import ChildWatcher
        dead = self._spawn("", 0.05)
        dead.wait(timeout=10)
        with pytest.raises(RuntimeError, match="启动身份不可得"):
            ChildWatcher(dead.pid, rc_file=tmp_path / "rc",
                         out_file=tmp_path / "w.jsonl")

# ==================== F5:多重集工具 ====================
class TestF5MultisetComparator:
    def _load(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location(
            "cmc", RUNNER_DIR / "ci_multiset_compare.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @staticmethod
    def _junit(path, cases):
        parts = ['<?xml version="1.0"?><testsuites>']
        for name, status, skipmsg in cases:
            inner = (f'<skipped message="{skipmsg}"/>' if status ==
                     "skipped" else
                     f'<{status} message="x"/>' if status in (
                         "failure", "error") else "")
            parts.append(
                f'<testsuite name="s"><testcase classname="c" '
                f'name="{name}">{inner}</testcase></testsuite>')
        parts.append("</testsuites>")
        Path(path).write_text("".join(parts), encoding="utf-8")

    def test_same_all_green_ok(self, tmp_path):
        mod = self._load()
        cases = [("t1", "passed", ""), ("t2", "passed", "")]
        self._junit(tmp_path / "a.xml", cases)
        self._junit(tmp_path / "b.xml", cases)
        r = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "a.xml"),
            mod.parse_junit_multiset(tmp_path / "b.xml"))
        assert r["verdict"] == "OK"

    def test_duplicates_preserved_as_multiset(self, tmp_path):
        mod = self._load()
        self._junit(tmp_path / "a.xml",
                    [("t1", "passed", ""), ("t1", "passed", "")])
        self._junit(tmp_path / "b.xml", [("t1", "passed", "")])
        r = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "a.xml"),
            mod.parse_junit_multiset(tmp_path / "b.xml"))
        assert r["verdict"] == "REGRESSED" and r["count_reduced"]

    def test_added_only_ok_removed_regressed(self, tmp_path):
        mod = self._load()
        self._junit(tmp_path / "a.xml", [("t1", "passed", "")])
        self._junit(tmp_path / "b.xml",
                    [("t1", "passed", ""), ("t2", "passed", "")])
        r = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "a.xml"),
            mod.parse_junit_multiset(tmp_path / "b.xml"))
        assert r["verdict"] == "OK" and len(r["added"]) == 1
        r2 = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "b.xml"),
            mod.parse_junit_multiset(tmp_path / "a.xml"))
        assert r2["verdict"] == "REGRESSED" and r2["removed"]

    def test_status_and_new_skip_regressed(self, tmp_path):
        mod = self._load()
        self._junit(tmp_path / "a.xml", [("t1", "passed", "")])
        self._junit(tmp_path / "b.xml", [("t1", "failure", "")])
        r = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "a.xml"),
            mod.parse_junit_multiset(tmp_path / "b.xml"))
        assert r["verdict"] == "REGRESSED" and r["status_changes"]
        self._junit(tmp_path / "c.xml",
                    [("t1", "passed", ""), ("t2", "skipped", "why")])
        self._junit(tmp_path / "d.xml",
                    [("t1", "passed", ""), ("t2", "skipped", "other")])
        r2 = mod.compare_multisets(
            mod.parse_junit_multiset(tmp_path / "c.xml"),
            mod.parse_junit_multiset(tmp_path / "d.xml"))
        assert r2["verdict"] == "REGRESSED" and r2["new_skips"]

    def test_malformed_and_missing_rc2(self, tmp_path, capsys):
        mod = self._load()
        (tmp_path / "bad.xml").write_text("<not-junit/>",
                                          encoding="utf-8")
        rc = mod.main(["--base-junit", str(tmp_path / "bad.xml"),
                       "--new-junit", str(tmp_path / "bad.xml"),
                       "--out", str(tmp_path / "o.json")])
        assert rc == 2
        rc2 = mod.main(["--base-junit", str(tmp_path / "nope.xml"),
                        "--new-junit", str(tmp_path / "bad.xml"),
                        "--out", str(tmp_path / "o.json")])
        assert rc2 == 2

    def test_cli_rc_matches_verdict(self, tmp_path):
        mod = self._load()
        self._junit(tmp_path / "a.xml", [("t1", "passed", "")])
        self._junit(tmp_path / "b.xml",
                    [("t1", "passed", ""), ("t9", "passed", "")])
        rc = mod.main(["--base-junit", str(tmp_path / "a.xml"),
                       "--new-junit", str(tmp_path / "b.xml"),
                       "--out", str(tmp_path / "ok.json")])
        assert rc == 0
        self._junit(tmp_path / "c.xml", [("t1", "failure", "")])
        rc2 = mod.main(["--base-junit", str(tmp_path / "a.xml"),
                        "--new-junit", str(tmp_path / "c.xml"),
                        "--out", str(tmp_path / "bad.json")])
        assert rc2 == 1


# ==================== F2:真实 handler 链组合 ====================
def _install_leaf_stubs(monkeypatch):
    """科学重叶替身(生成函数级;与既有 CI 测试同边界)。

    被替身:generate_matched_block_once/with_attempts、cue 事件
    trace、聚簇统计、global-K null、fit bank 生成。保留真实:
    分类/计划锁与三方一致/预算门/serializer/digest/各 cmd 的
    身份-计划-产物绑定与跨步消费。
    """
    import pandas as pd
    stub = type("S", (), {"gen_ns": [], "bank_ns": []})()

    def gen_once(ladder, seed, ns):
        stub.gen_ns.append(ns)
        ep = type("EP", (), {})()
        ep.hidden = {"cue_dir": pd.Series([0, 0, 0, 0])}
        ep.df = None
        return {r: {"A": ep, "B": ep}
                for r in ("D0", "D1", "D2", "D3")}

    def gen_attempts(ladder, *, namespace, block_index):
        stub.gen_ns.append(namespace)
        b = type("B", (), {})()
        b.block_index = block_index
        b.attempt_log = type("L", (), {})()
        b.attempt_log.selected_attempt = 0
        b.episodes = gen_once(ladder, 0, namespace)
        return b
    events = [{"block_index": 0, "cue_bar": 10, "detected": True,
               "k_actual": 2, "primary_present": True,
               "mirror_candidates": 1, "mirror_positions": [2],
               "effective_sigma_bps": 9.0, "actual_noise": 0.0,
               "cue_read": 1.0},
              {"block_index": 0, "cue_bar": 11, "detected": True,
               "k_actual": 2, "primary_present": True,
               "mirror_candidates": 1, "mirror_positions": [3],
               "effective_sigma_bps": 9.0, "actual_noise": 0.0,
               "cue_read": 1.0}]
    monkeypatch.setattr(cue_mod, "generate_matched_block_once",
                        gen_once)
    monkeypatch.setattr(
        cue_mod, "generate_matched_block_with_attempts", gen_attempts)
    monkeypatch.setattr(
        cue_mod, "cue_event_trace",
        lambda ep, ladder, seed, bi: {
            "events": list(events), "max_replay_abs_error": 0.0,
            "replay_ok": True, "bounds_ok": True})
    monkeypatch.setattr(
        cue_mod, "trace_matched_blocks",
        lambda blocks, ladder: {
            "events": list(events),
            "block_traces": [{"events": list(events),
                              "max_replay_abs_error": 0.0,
                              "replay_ok": True, "bounds_ok": True}
                             for _ in blocks]})
    monkeypatch.setattr(
        cue_mod, "summarize_events",
        lambda evs, n: {"n_events": len(evs), "n_detected": sum(
            1 for e in evs if e["detected"]), "recall": 1.0,
            "cue_position_distribution": {10: len(evs)},
            "k_mean": 2.0, "tail": {"recall": 1.0}})
    # audit 步 fit bank 叶(r3_calibration 源模块;cli 惰性导入)
    monkeypatch.setattr(
        "rl_curriculum.curriculum261_r3_calibration.generate_fit_bank",
        lambda ns, pairs: stub.bank_ns.append(ns) or [])
    monkeypatch.setattr(cue_mod, "_cluster_bootstrap",
                        lambda counts: {"point": 1.0, "se": 0.01,
                                        "ci95": [0.5, 1.0], "lcb95": 0.9,
                                        "n_events": 2})
    monkeypatch.setattr(
        cue_mod, "_once_vs_attempts_bitwise_check_r17",
        lambda *a, **k: {"bitwise_ok": True, "n_blocks_checked": 2})
    monkeypatch.setattr(cue_mod, "block_attempt_statistics",
                        lambda blocks: {"n_blocks": len(blocks)})
    monkeypatch.setattr(cue_mod, "matched_block_seed_of", lambda b: 7)
    monkeypatch.setattr(cue_mod, "_tail_k_position_checks",
                        lambda evs, n: {})
    monkeypatch.setattr(cue_mod, "_tail_mirror_bound_integrity",
                        lambda evs, r, b, n: {"pass": True})
    import rl_curriculum.curriculum261_r17_global_k as gk

    def run_gk(evs, *, b_tier1, b_tier2=None, n=None):
        return {"contract_version": "stub", "contract_digest": "d",
                "graph_integrity_ok": True, "n_eligible_cells": 1,
                "T_obs": 0.1, "argmax_cell": "c", "final": "tier1",
                "verdict": "REJECT", "pass": True}

    monkeypatch.setattr(gk, "run_global_k_audit", run_gk)
    monkeypatch.setattr(gk, "cell_diagnostics_from_result",
                        lambda res, evs, n=None: [])
    return stub



def _f2_heavy_in_subprocess(node_name: str):
    """真实 cue-audit 机力(bootstrap/MC/子进程探针)会在本 pytest
    进程留下数百个后台线程,污染同进程后续 r17 Supervisor 测试的
    截止点线程前提(unshielded_threads -> control rc=7)。因此重载
    类测试在**子进程 pytest** 中执行:本体不变,仅隔离线程面;
    子进程 rc/junit 如实透传。"""
    if os.environ.get("_R1_F2_CHILD") == "1":
        return True                        # 子进程:执行真实本体
    import subprocess as _sp
    argv = [sys.executable, "-m", "pytest", "-q",
            f"{__file__}::TestF2RealHandlerChain::{node_name}"]
    env = dict(os.environ)
    env["_R1_F2_CHILD"] = "1"
    # cwd 不指向测试目录:否则子 pytest 会在 tests/route_c_stage2_6_1
    # 内建 .pytest_cache,污染 r21 部署面预检(unexpected 目录)
    r = _sp.run(argv, capture_output=True, text=True, env=env,
                timeout=900)
    tail = (r.stdout or "")[-2000:]
    assert r.returncode == 0, (
        f"子进程 F2 链测试失败 rc={r.returncode}:\n{tail}\n"
        f"stderr={(r.stderr or '')[-500:]}")
    return False                           # 父进程:已由子进程覆盖

class TestF2RealHandlerChain:
    def test_identity_chain_real_handlers_flow(self, tmp_path,
                                               monkeypatch):
        """正式身份关键步骤真实 handler 串行链,实跑 4 步:
        cue-audit→preplan-smoke→plan-roundtrip→design-plan-lock。

        - 全部经真实 cli.main(argv);科学重叶=生成函数级替身;
        - 跨步产物**真实流动**:cue-audit 写 cue_contract_audit.json
          (qaf_v3 实际 ns 报告)→ plan-roundtrip 真实读取并绑定
          audit_digest → design-plan-lock 真实读取 audit+plan+
          roundtrip,写入带族 design namespace 与真实锁定计划
          digest 的 design plan。audit/determinism-matrix 与
          design 及其后步骤依赖真实 repo 冻结面,超出隔离工程域,
          列为未验证层次(见下方内联注释),不在此冒充。
        - 线程面隔离:真实 cue-audit 机力在进程内留下数百后台线程,
          会污染同进程后续 r17 Supervisor 测试(unshielded_threads
          -> control rc=7);本测试经子进程 pytest 执行(见
          _f2_heavy_in_subprocess),本体与断言不变。
        """
        if not _f2_heavy_in_subprocess(
                "test_identity_chain_real_handlers_flow"):
            return
        import rl_curriculum.curriculum261_r17_cli as cli
        _install_leaf_stubs(monkeypatch)
        out = tmp_path / "chain"
        out.mkdir()
        # preplan rehearsal 前置件(明示工程 fixture:真实 consumer
        # 校验 pass/rehearsal_digest 字段)
        rehearsal = {
            "pass": True,
            "rehearsal_digest": "r15pr-" + "ab" * 31,
            "note": "declared engineering fixture for design-plan-lock"
                    " precondition(真实 handler 只校验结构字段)",
        }
        (out / "preplan").mkdir()
        (out / "preplan" / "preplan_end_to_end_rehearsal.json"
         ).write_text(json.dumps(rehearsal), encoding="utf-8")
        # determinism 合同前置件(同为明示工程 fixture:真实 handler
        # (_generation_determinism_gate_binding)只校验存在与 pass
        # 字段;真实 determinism-matrix 步骤依赖真实 repo HEAD 冻结
        # 面,属未验证层次,不在此冒充)
        det = {
            "pass": True,
            "note": "declared engineering fixture for design-plan-lock"
                    " determinism gate precondition",
        }
        (out / "determinism").mkdir()
        (out / "determinism" / (
            "generation_determinism_contract.json"
        )).write_text(json.dumps(det), encoding="utf-8")
        # code freeze 门 = 机械身份门(绑定真实 repo HEAD + 干净树,
        # 隔离工程域无法建真冻结)。按 F2"明确边界替代"以真实当前
        # HEAD 替代该读取器;不冒充已冻结。其余(audit/smoke/
        # roundtrip/dep/abort 绑定/determinism gate)全部真实。
        import subprocess as _sp
        from rl_curriculum.curriculum261_r17_dependencies import (
            release_repo_candidates as _rrc,
        )
        _repo = next(p for p in _rrc() if p.is_dir())
        _head = _sp.run(
            ["git", "-C", str(_repo), "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True
        ).stdout.strip()
        monkeypatch.setattr(
            cli, "_code_freeze_sha",
            lambda _out, _h=_head: _h,
        )

        def run(*argv):
            return cli.main(list(argv))

        # 1) cue-audit:真实锁定计划+三方一致+实际 ns 报告(audit/
        # determinism-matrix 前置步的冻结面/历史绑定 machinery 依赖
        # 真实 repo HEAD 与 fit-bank 真实记录,超出隔离工程域——
        # 如实列为未验证层次,不在此冒充;cue 身份链自 cue-audit 起)
        rc_c = run("cue-audit", "--out-dir", str(out),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID)
        assert rc_c == 0
        report = json.loads(
            (out / "cue_contract_audit.json").read_text("utf-8"))
        assert report["formal_audit"] is True
        assert report["audit_namespaces"]["model"] == (
            FAM3.cue_contract_model)
        digest = report["audit_digest"]
        # 3) preplan-smoke(attempt ns;生成叶替身)
        rc_p = run("preplan-smoke", "--out-dir", str(out),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID)
        assert rc_p == 0
        # 4) plan-roundtrip:真实读取 cue 报告并绑定 digest
        rc_r = run("plan-roundtrip", "--out-dir", str(out))
        assert rc_r == 0
        rt = json.loads(
            (out / "plan_roundtrip_validation.json").read_text("utf-8"))
        assert rt.get("pass") is True
        # 5) design-plan-lock:真实消费 audit+锁定 plan+roundtrip
        rc_d = run("design-plan-lock", "--out-dir", str(out),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID)
        assert rc_d == 0
        plan = json.loads(
            (out / "r17_design_plan.json").read_text("utf-8"))
        assert plan["design_data"]["corpora"][0] == (
            FAM3.design_matched_main)
        assert plan["cue_audit_plan_digest"].startswith("r15ap-")
        assert plan["cue_semantic_contract"]["audit_digest"] == digest
        # 未验证层次(如实):design 及其后步骤依赖真实 git repo HEAD
        # 上下文(resolve_dependency_identity_r17 校验 HEAD==freeze
        # sha),超出隔离工程域;其 argv 解析面由
        # test_argv_parse_layer_renamed_evidence 覆盖,不在此冒充。

    def test_chain_negative_combinations(self, tmp_path, monkeypatch):
        """负例:错身份 vs 锁定计划 / 缺件 / 工程件冒充正式。"""
        import rl_curriculum.curriculum261_r17_cli as cli
        _install_leaf_stubs(monkeypatch)
        out = tmp_path / "neg"
        out.mkdir()

        def run(*argv):
            return cli.main(list(argv))

        # 锁 v3 计划后传 v2 尝试 → rc=2(零科学)
        assert run("cue-audit", "--out-dir", str(out),
                   "--formal-namespace-attempt", QAF3_ATTEMPT_ID) == 0
        assert run("cue-audit", "--out-dir", str(out),
                   "--formal-namespace-attempt", "qaf_v2") == 2
        # plan-roundtrip 缺 cue 报告 → 真实报错
        out2 = tmp_path / "neg2"
        out2.mkdir()
        (out2 / "preplan_engineering_smoke.json").write_text(
            json.dumps({"identity": {"sentinel_digest": "s"}}),
            encoding="utf-8")
        try:
            rc = run("plan-roundtrip", "--out-dir", str(out2))
            refused = rc != 0
        except Exception:
            refused = True  # handler 不吞错:异常同为 fail-closed
        assert refused
        # design-plan-lock 缺 rehearsal → 真实拒绝(异常或非零同口径)
        out3 = tmp_path / "neg3"
        out3.mkdir()
        try:
            rc3 = run("design-plan-lock", "--out-dir", str(out3),
                      "--formal-namespace-attempt", QAF3_ATTEMPT_ID)
            refused3 = rc3 != 0
        except Exception:
            refused3 = True  # 缺件在读取处 fail-closed(不吞错)
        assert refused3

    def test_argv_parse_layer_renamed_evidence(self, tmp_path,
                                               monkeypatch):
        """解析/派发层证据(原 passthrough 测试改名声明:仅证明
        argv 可解析与 attempt 字段到达 10 个身份步骤,不独立证明
        CI07;CI07 由上面真实 handler 链测试支撑)。"""
        import rl_curriculum.curriculum261_r17_cli as cli
        from rl_curriculum.curriculum261_r17_workflow import (
            build_workflow_plan_r17, r17_workflow_step_names,
        )
        monkeypatch.setenv("CURRICULUM261_R17_STATE_ROOT",
                           str(tmp_path / "state"))
        plan = build_workflow_plan_r17(
            profile="formal", out_dir=str(tmp_path),
            freeze_sha="c0fb685823eb4733bda9f5920601311228d55fde",
            formal_attempt=QAF3_ATTEMPT_ID)
        assert [s["name"] for s in plan["steps"]] == list(
            r17_workflow_step_names())
        identity_steps = {
            "determinism-matrix", "audit", "cue-audit", "preplan-smoke",
            "design-plan-lock", "design", "calibrate", "preflight-static",
            "qualify", "smoke"}
        seen = set()
        for step in plan["steps"]:
            argv = list(step["argv"])
            cmd = argv[0]
            recorder = {}

            def _rec(ns, _c=cmd):
                recorder["ns"] = ns
                return 0

            orig = getattr(cli, "cmd_" + cmd.replace("-", "_"), None)
            monkeypatch.setattr(
                cli, "cmd_" + cmd.replace("-", "_"), _rec)
            try:
                rc = cli.main(argv)
            finally:
                monkeypatch.setattr(
                    cli, "cmd_" + cmd.replace("-", "_"), orig)
            assert rc == 0
            if cmd in identity_steps:
                assert getattr(
                    recorder["ns"], "formal_namespace_attempt",
                    None) == QAF3_ATTEMPT_ID, cmd
                seen.add(cmd)
        assert seen == identity_steps
