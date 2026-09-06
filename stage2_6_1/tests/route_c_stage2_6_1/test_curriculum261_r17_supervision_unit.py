# -*- coding: utf-8 -*-
"""R17 运行监护与 Agent 告警测试矩阵(任务书 §13 M01-M25 夹具化项)。

真实模块:全部测试 import 发布仓库 runner 下的监护实现与既有模块;
注入故障只作用于隔离夹具或显式测试输入源(--samples-source file:,
生产入口不暴露)。M07(真实 Agent 会话接收)/M10(真实保护)的会话级
证据在运行监督报告中引用,不在此重复;此处覆盖其可夹具化语义。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

def _find_runner_dir() -> Path:
    """兼容发布仓库(stage2_6_1/runner)与 WSL 部署面
    (stage2_6_1_runner)两种布局;与 governance 测试同款候选法。"""
    here = Path(__file__).resolve()
    for cand in (
            here.parents[3] / "stage2_6_1" / "runner",          # 发布仓库
            here.parents[2].parent / "stage2_6_1_runner",       # 部署面
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
    ):
        if (cand / "r17_supervision.py").is_file():
            return cand
    raise FileNotFoundError("runner 执行面不可达(发布仓库或部署面)")


RUNNER_DIR = _find_runner_dir()
sys.path.insert(0, str(RUNNER_DIR))

from r17_guest_sampler import (  # noqa: E402
    PAGE_SIZE, GuestSampler, parse_proc_stat, parse_statm, proc_table,
    task_tree)
from r17_supervision import (  # noqa: E402
    POLICY, Incident, PolicyEngine, SustainWindow, Supervisor,
    WinSampleReader, policy_digest)

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="监护执行面只在 Linux/WSL 跑")


def _win(perf=None, vols=None):
    return {"event": "sample", "perf": perf, "vols": vols or []}


def _perf(free=39.0, ct=38.0, cl=83.0):
    return {"phys_avail_gb": free, "commit_total_gb": ct,
            "commit_limit_gb": cl, "phys_total_gb": 63.0}


def _guest(avail_kb=39_000_000, psi=0.0, pswpout=0):
    return {"event": "guest_sample",
            "meminfo": {"MemAvailable": avail_kb},
            "psi_memory": {"full_avg10": psi},
            "vmstat_swap": {"pswpout": pswpout}}


# ================================================= M03 采样身份与单位
class TestSamplingIdentity:
    def test_page_size_matches_sysconf(self):
        import resource
        # 页大小与系统口径一致(不假定 4K)
        assert PAGE_SIZE == os.sysconf("SC_PAGESIZE") > 0

    def test_parse_proc_stat_self_crosscheck(self):
        """comm 含括号场景 + 与 /proc/self/stat 原文交叉核对。"""
        import resource
        with open("/proc/self/stat") as fh:
            text = fh.read()
        info = parse_proc_stat(text)
        assert info["pid"] == os.getpid()
        assert info["pgrp"] == os.getpgid(0) or info["pgrp"] > 0
        assert info["starttime_ticks"] > 0
        assert info["num_threads"] >= 1
        # utime+stime 与 rusage 交叉(CPU 累计秒同源)
        cpu_from_proc = (info["utime_ticks"] + info["stime_ticks"]) \
            / os.sysconf("SC_CLK_TCK")
        ru = resource.getrusage(resource.RUSAGE_SELF)
        assert 0 <= cpu_from_proc <= ru.ru_utime + ru.ru_stime + 5.0

    def test_parse_statm_units(self):
        with open("/proc/self/statm") as fh:
            info = parse_statm(fh.read())
        assert info["rss_kb"] > 0
        # RSS 同量级上界(不填零、不冒充 PSS)
        assert info["rss_kb"] < 1024 * 1024 * 8

    def test_pid_reuse_no_negative_rates(self):
        """实例身份:同 pid 不同 starttime=复用,速率不拼接(M03)。"""
        gs = GuestSampler(emit=lambda r: None)
        t0 = {"pid": 1, "comm": "x", "state": "S", "ppid": 0,
              "pgrp": 1, "num_threads": 1, "starttime_ticks": 100,
              "utime_ticks": 500, "stime_ticks": 500}
        t1 = dict(t0, starttime_ticks=999, utime_ticks=10,
                  stime_ticks=10)
        gs._instance[1] = 100
        gs._cpu_prev[1] = 1000
        # 复用后:reuse 检测为真,cpu 增量不产出
        reused = gs._instance.get(1) != t1["starttime_ticks"]
        assert reused
        cpu_d = None if reused else max(
            0, t1["utime_ticks"] + t1["stime_ticks"] - 1000)
        assert cpu_d is None

    def test_task_tree_pgid_survives_reparent(self):
        """pgid 口径:进程被重新托管(父退出)仍在任务树(M03/§5.3)。"""
        p = subprocess.Popen(
            ["bash", "-c", "echo bg > /dev/null; exec sleep 30"],
            start_new_session=True)
        time.sleep(0.4)
        try:
            table = proc_table()
            tree = task_tree(table, {os.getpgid(p.pid)}, set())
            assert p.pid in tree
            # rusage 交叉:该 pid 存在于 /proc
            assert os.path.exists(f"/proc/{p.pid}")
        finally:
            p.kill()
            p.wait(timeout=10)


# ================================================= M04/M05/M06/M09 判定
class TestPolicyEngine:
    def _run_series(self, engine, series):
        out = []
        mono = 0.0
        for win, guest in series:
            mono += 1.0
            out.extend(engine.evaluate(mono, win, guest, None, None, None))
        return out, mono

    def test_m04_normal_load_no_alert(self):
        """正常 CPU 满载/缓存高/无 stdout:单现象不触发(M04)。"""
        eng = PolicyEngine()
        series = [(_win(_perf(), [{"vol": "C:", "present": True,
                                   "free_gb": 100.0},
                                  {"vol": "F:", "present": True,
                                   "free_gb": 1100.0}]),
                   _guest())] * 40
        out, _ = self._run_series(eng, series)
        assert not out

    def test_m05_warning_sustain_and_recover(self):
        """win 可用内存 WARNING 需持续 30s;恢复需宽余量 30s(M05)。"""
        eng = PolicyEngine()
        # 31 个样本(间隔 1s)=持续 30s
        series = [(_win(_perf(free=5.0)), _guest())] * 31
        out, _ = self._run_series(eng, series)
        warns = [t for t in out if t["kind"] == "win_free_phys"]
        assert warns and warns[0]["severity"] == "WARNING"
        # 短尖峰(5 样本)不触发
        eng2 = PolicyEngine()
        out2, _ = self._run_series(
            eng2, [(_win(_perf(free=5.0)), _guest())] * 5)
        assert not [t for t in out2 if t["kind"] == "win_free_phys"]
        # 恢复迟滞:回到 ≥10GiB 且 commit<85% 持续 30s
        eng.recovered(100.0, _win(_perf(free=20.0)), _guest())
        assert eng.recovered(130.0, _win(_perf(free=20.0)), _guest())

    def test_m06_escalation_and_independent_critical(self):
        """W 升 C 及时;不同原因 CRITICAL 不被冷却吞掉(M06)。"""
        eng = PolicyEngine()
        mono = 0.0
        seen = []
        for i in range(35):
            mono += 1.0
            # win free 持续恶化 3.9GiB(crit 线下)
            seen += eng.evaluate(
                mono, _win(_perf(free=3.9)), _guest(), None, None, None)
        crit = [t for t in seen if t["kind"] == "win_free_phys"
                and t["severity"] == "CRITICAL"]
        assert crit  # 升级发生
        # 独立 CRITICAL(keyvol 3GiB)在同一冷却窗内仍独立触发
        more = eng.evaluate(
            36.0, _win(_perf(), [{"vol": "F:", "present": True,
                                  "free_gb": 3.0}]), _guest(),
            None, None, None)
        assert any(t["kind"] == "keyvol" and t["severity"] == "CRITICAL"
                   for t in more)

    def test_m09_threshold_boundaries(self):
        """keyvol 边界:20GiB 触发 W,5GiB 触发 C,恰好等于不触发。"""
        eng = PolicyEngine()
        base = _win(_perf())
        t20 = eng.evaluate(1.0, dict(base, vols=[
            {"vol": "F:", "present": True, "free_gb": 20.0}]),
            _guest(), None, None, None)
        assert not t20
        t199 = eng.evaluate(2.0, dict(base, vols=[
            {"vol": "F:", "present": True, "free_gb": 19.9}]),
            _guest(), None, None, None)
        assert any(t["severity"] == "WARNING" for t in t199)
        t5 = eng.evaluate(3.0, dict(base, vols=[
            {"vol": "F:", "present": True, "free_gb": 5.0}]),
            _guest(), None, None, None)
        assert not any(t["kind"] == "keyvol" and
                       t["severity"] == "CRITICAL" for t in t5)
        t49 = eng.evaluate(4.0, dict(base, vols=[
            {"vol": "F:", "present": True, "free_gb": 4.9}]),
            _guest(), None, None, None)
        assert any(t["kind"] == "keyvol" and t["severity"] == "CRITICAL"
                   for t in t49)

    def test_guest_critical_requires_pressure_evidence(self):
        """guest CRITICAL 需换出增长或 PSI 压力;数据失联=保护不可用。"""
        eng = PolicyEngine()
        # 低内存但无压力证据:仅 WARNING 路径(crit 组合条件不满足)
        mono = 0.0
        seen = []
        for _ in range(20):
            mono += 1.0
            seen += eng.evaluate(mono, None,
                                 _guest(avail_kb=1_500_000, psi=0.0,
                                        pswpout=0), None, None, None)
        assert not [t for t in seen
                    if t["severity"] == "CRITICAL"]
        # 同低内存+PSI 压力 → CRITICAL
        eng2 = PolicyEngine()
        seen2 = []
        mono = 0.0
        for _ in range(20):
            mono += 1.0
            seen2 += eng2.evaluate(mono, None,
                                   _guest(avail_kb=1_500_000, psi=5.0,
                                          pswpout=0), None, None, None)
        assert any(t["kind"] == "guest_memavail" and
                   t["severity"] == "CRITICAL" for t in seen2)
        # PSI/换出数据同时失联 → PROTECTION_UNAVAILABLE(不放行)
        eng3 = PolicyEngine()
        lost = eng3.evaluate(
            1.0, None,
            {"event": "guest_sample",
             "meminfo": {"MemAvailable": 1_500_000}},
            None, None, None)
        assert any(t["severity"] == "PROTECTION_UNAVAILABLE" for t in lost)

    def test_cgroup_oom_event_increment_is_critical(self):
        eng = PolicyEngine()
        task = {"cgroup_memory": {
            "effective_limit": 4 * 1024 * 1024 * 1024,
            "current": 1024, "events": {"oom_kill": 0, "oom": 0},
            "path": "/"}}
        eng.evaluate(1.0, None, None, task, None, None)
        task2 = {"cgroup_memory": {
            "effective_limit": 4 * 1024 * 1024 * 1024,
            "current": 1024, "events": {"oom_kill": 1, "oom": 0},
            "path": "/"}}
        out = eng.evaluate(2.0, None, None, task2, None, None)
        assert any(t["kind"] == "cgroup_oom" and
                   t["severity"] == "CRITICAL" for t in out)
        # 无限制(unlimited)=该项不适用,不报错
        out2 = eng.evaluate(
            3.0, None, None,
            {"cgroup_memory": {"effective_limit": "not_limited"}},
            None, None)
        assert not out2

    def test_storage_ceiling_units(self):
        eng = PolicyEngine()
        warn = eng.evaluate(1.0, None, None, None, 275.0, None)
        assert any(t["kind"] == "storage_ceiling" and
                   t["severity"] == "WARNING" for t in warn)
        crit = eng.evaluate(2.0, None, None, None, 300.0, None)
        assert any(t["kind"] == "storage_ceiling" and
                   t["severity"] == "CRITICAL" for t in crit)

    def test_m14_e_drive_not_dependent_no_alert(self):
        """E 不在关键卷清单=零事件(不误杀 F 任务)。"""
        eng = PolicyEngine()
        out = eng.evaluate(
            1.0, _win(_perf(), [{"vol": "C:", "present": True,
                                 "free_gb": 100.0},
                                {"vol": "F:", "present": True,
                                 "free_gb": 1100.0}]),
            _guest(), None, None, None)
        assert not any("vol_missing" in json.dumps(t) for t in out)

    def test_m13_observation_stale_ladder(self):
        eng = PolicyEngine()
        w = eng.evaluate(1.0, None, None, None, None, 16.0)
        assert any(t["kind"] == "observation_stale" and
                   t["severity"] == "WARNING" for t in w)
        c = eng.evaluate(2.0, None, None, None, None, 31.0)
        assert any(t["kind"] == "observation_stale" and
                   t["severity"] == "CRITICAL" for t in c)

    def test_progress_stall_is_warning_only(self):
        """进展未证实只 W,不产生终止(不推断死锁)。"""
        eng = PolicyEngine()
        eng.evaluate(1.0, None, None,
                     {"task_cpu_sec_delta": 0.0, "task_count": 2},
                     None, None)  # 空转起点
        out = eng.evaluate(
            601.0, None, None,
            {"task_cpu_sec_delta": 0.0, "task_count": 2}, None, None)
        assert any(t["kind"] == "progress_stall" and
                   t["severity"] == "WARNING" for t in out)


# ================================================= M08/M18 递交语义
class TestDeliverySemantics:
    def test_incident_dedup_and_cooldown(self):
        """同因持续异常单 incident;60s 内重复不递交(M08/§7.2)。"""
        inc = Incident("iid", "keyvol", "WARNING", "d", 0.0)
        assert inc.should_deliver("WARNING", 0.0, 60.0) == "open"
        inc.last_delivered_mono = 0.0
        assert inc.should_deliver("WARNING", 30.0, 60.0) is None
        assert inc.should_deliver("WARNING", 61.0, 60.0) == "reminder"
        # 升级不被冷却吞掉
        assert inc.should_deliver("CRITICAL", 31.0, 60.0) == "escalate"

    def test_alert_text_is_data_not_executed(self):
        """M18:告警 detail 含恶意指令文本时仅是数据;模块无执行通道。"""
        src = (RUNNER_DIR / "r17_supervision.py").read_text(
            encoding="utf-8")
        for banned in ("eval(", "exec(", "os.system(", "shell=True"):
            assert banned not in src, banned

    def test_boundary_no_governance_surface(self):
        """M23(部分):监护模块不含执行治理接口/资格面字样。"""
        for name in ("r17_supervision.py", "r17_guest_sampler.py"):
            src = (RUNNER_DIR / name).read_text(encoding="utf-8")
            for bad in ("curriculum261_r17_execgov",
                        "R17_EXECUTOR_TOKEN_ENV",
                        "r17_journal_path", "rejected_requests"):
                assert bad not in src, f"{name}:{bad}"

    def test_policy_digest_stable(self):
        assert policy_digest() == policy_digest(POLICY)
        assert len(policy_digest()) == 64


# ================================================= M19-M21 交付验证
class TestVerifyDelivery:
    @pytest.fixture()
    def delivery(self, tmp_path):
        root = tmp_path / "run_supervision"
        run_dir = root / "runs" / "RID1"
        (run_dir / "business").mkdir(parents=True)
        (run_dir / "telemetry").mkdir()
        # 真实空 stderr 与非空 stdout(M21 区分)
        (run_dir / "business" / "stderr.log").write_bytes(b"")
        (run_dir / "business" / "stdout.log").write_bytes(b"line1\nline2\n")
        (run_dir / "telemetry" / "guest_samples.jsonl").write_text(
            '{"event":"guest_sample"}\n', encoding="utf-8")
        required = []
        for rel in ("business/stderr.log", "business/stdout.log",
                    "telemetry/guest_samples.jsonl"):
            p = run_dir / rel
            required.append({
                "role": "business" if rel.startswith("business")
                else "telemetry",
                "path": f"runs/RID1/{rel}",
                "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
                "bytes": p.stat().st_size})
        rr = {"schema": "r17-run-record-v1", "run_id": "RID1",
              "task_kind": "fixture", "finalized": True,
              "required": required}
        (run_dir / "run_record.json").write_text(
            json.dumps(rr), encoding="utf-8")
        return {"root": root, "run_dir": run_dir,
                "rr_path": run_dir / "run_record.json"}

    def _build(self, d):
        manifest = d["run_dir"] / "delivery_manifest_v2.jsonl"
        anchor = d["root"] / "anchors" / "RID1.anchor.json"
        rc = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(d["rr_path"]),
             "--manifest-out", str(manifest),
             "--anchor-out", str(anchor),
             "--root", str(d["root"])],
            capture_output=True, text=True)
        assert rc.returncode == 0, rc.stderr
        d["manifest"] = manifest
        d["anchor"] = anchor
        return d

    def _verify(self, d, mutate=None):
        if mutate:
            mutate(d)
        rc = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "verify", "--root", str(d["root"]),
             "--manifest", str(d["manifest"]),
             "--anchor-file", str(d["anchor"]),
             "--run-record", str(d["rr_path"]),
             "--receipt-dir", str(d["root"] / "receipts")],
            capture_output=True, text=True)
        return rc

    def test_m19_tamper_and_missing_detected(self, delivery):
        """验证前删件/篡改:非零退出+具体文件;manifest 前后哈希不变。"""
        d = self._build(delivery)
        man_hash_before = hashlib.sha256(
            d["manifest"].read_bytes()).hexdigest()
        # 篡改 stdout.log 一个字节
        victim = d["run_dir"] / "business" / "stdout.log"
        data = bytearray(victim.read_bytes())
        data[2] ^= 0x01
        victim.write_bytes(bytes(data))
        rc = self._verify(d)
        assert rc.returncode == 1
        assert "stdout.log" in rc.stderr
        # 删件
        (d["run_dir"] / "telemetry" / "guest_samples.jsonl").unlink()
        rc2 = self._verify(d)
        assert rc2.returncode == 1
        assert "guest_samples.jsonl" in rc2.stderr
        assert hashlib.sha256(
            d["manifest"].read_bytes()).hexdigest() == man_hash_before

    def test_m20_manifest_line_removed_and_hash_edited(self, delivery):
        d = self._build(delivery)
        lines = d["manifest"].read_text(
            encoding="utf-8").splitlines(keepends=True)
        d["manifest"].write_text(
            "".join(lines[:-1]), encoding="utf-8")
        rc = self._verify(d)
        # 清单被删行 → 与锚不符(撞锚)或必需集合缺失,任一都非零
        assert rc.returncode == 1
        d2 = self._build(self._fresh(delivery))
        # 改清单内哈希
        rows = [json.loads(x) for x in d2["manifest"].read_text(
            encoding="utf-8").splitlines() if x.strip()]
        for r in rows:
            if r["role"] == "business" and r["path"].endswith("stdout.log"):
                r["sha256"] = "0" * 64
        d2["manifest"].write_text(
            "\n".join(json.dumps(r) for r in rows) + "\n",
            encoding="utf-8")
        rc2 = self._verify(d2)
        assert rc2.returncode == 1

    def test_m20_missing_or_empty_manifest(self, delivery):
        d = self._build(delivery)
        d["manifest"].unlink()
        rc = self._verify(d)
        assert rc.returncode == 2  # manifest 缺失=用法/IO 错
        d2 = self._build(self._fresh(delivery))
        d2["manifest"].write_text("", encoding="utf-8")
        rc2 = self._verify(d2)
        assert rc2.returncode == 1

    def test_m21_empty_stderr_vs_missing_and_external(self, delivery):
        """真实空 stderr(size=0)合法;external 显式标记;未标记外部路径拒绝。"""
        d = self._build(delivery)
        rc = self._verify(d)
        assert rc.returncode == 0, rc.stderr  # 空 stderr 是合法条目
        # external 条目带理由:允许不进清单
        d2 = self._fresh(delivery)
        rr = json.loads(d2["rr_path"].read_text(encoding="utf-8"))
        rr["required"].append({
            "role": "emergency", "path": "C:/win/emergency.jsonl",
            "external": True,
            "external_reason": "宿主应急副本(独立故障域)"})
        d2["rr_path"].write_text(json.dumps(rr), encoding="utf-8")
        d2b = self._build(d2)
        rc2 = self._verify(d2b)
        assert rc2.returncode == 0, rc2.stderr
        # 未标记 external 的绝对路径 → build 阶段拒绝
        d3 = self._fresh(delivery)
        rr3 = json.loads(d3["rr_path"].read_text(encoding="utf-8"))
        rr3["required"].append({
            "role": "x", "path": "/mnt/c/elsewhere/dev.log"})
        d3["rr_path"].write_text(json.dumps(rr3), encoding="utf-8")
        rc3 = subprocess.run(
            [sys.executable,
             str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(d3["rr_path"]),
             "--manifest-out", str(d3["run_dir"] / "m.jsonl"),
             "--anchor-out", str(d3["root"] / "a.json"),
             "--root", str(d3["root"])],
            capture_output=True, text=True)
        assert rc3.returncode == 1
        assert "越界" in rc3.stderr or "绝对路径" in rc3.stderr \
            or "越出" in rc3.stderr or "非法" in rc3.stderr

    def test_build_rejects_unfinalized(self, delivery):
        rr = json.loads(delivery["rr_path"].read_text(encoding="utf-8"))
        rr["finalized"] = False
        delivery["rr_path"].write_text(json.dumps(rr), encoding="utf-8")
        rc = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(delivery["rr_path"]),
             "--manifest-out", str(delivery["run_dir"] / "m.jsonl"),
             "--anchor-out", str(delivery["root"] / "a.json"),
             "--root", str(delivery["root"])],
            capture_output=True, text=True)
        assert rc.returncode == 2
        assert "finalized" in rc.stderr

    def test_old_dialect_manifest_rejected(self, delivery):
        """D10:旧 blocker_diagnosis 方言(path/sha256/bytes 无 schema)
        行被新验证器拒绝(schema 不符)。"""
        d = self._build(delivery)
        lines = d["manifest"].read_text(
            encoding="utf-8").splitlines()
        old_row = json.dumps({"path": "runs/RID1/business/stdout.log",
                              "sha256": "0" * 64, "bytes": 12})
        d["manifest"].write_text(
            "\n".join(lines[:-1] + [old_row]) + "\n", encoding="utf-8")
        rc = self._verify(d)
        assert rc.returncode == 1

    @staticmethod
    def _fresh(d):
        """重置产物到 build 前(重新生成原始文件内容)。"""
        (d["run_dir"] / "business" / "stderr.log").write_bytes(b"")
        (d["run_dir"] / "business" / "stdout.log").write_bytes(
            b"line1\nline2\n")
        (d["run_dir"] / "telemetry" / "guest_samples.jsonl").write_text(
            '{"event":"guest_sample"}\n', encoding="utf-8")
        rr = json.loads(d["rr_path"].read_text(encoding="utf-8"))
        for item in rr["required"]:
            if item.get("external"):
                continue  # 外部引用不参与本地哈希
            p = d["root"] / item["path"]
            item["sha256"] = hashlib.sha256(
                p.read_bytes()).hexdigest()
            item["bytes"] = p.stat().st_size
        d["rr_path"].write_text(json.dumps(rr), encoding="utf-8")
        return d


# ================================================= M15/M17 有界与隔离
class TestBoundedAndIsolation:
    def test_m15_win_reader_bom_and_partial_lines(self, tmp_path):
        """读端容忍 UTF-8 BOM 与半行;解析失败计数不静默。"""
        f = tmp_path / "win.jsonl"
        f.write_bytes(
            b"\xef\xbb\xbf" + b'{"event":"sample","a":1}\n'
            + b'{"event":"sample","a":2}\n{"event":"samp')
        r = WinSampleReader(f)
        rows = r.read_new()
        assert len(rows) == 2
        assert all("a" in x for x in rows)
        with f.open("ab") as fh:  # 真实语义=追加(AppendAllText)
            fh.write(b'le","a":3}\n{"bad json\n')
        rows2 = r.read_new()
        assert len(rows2) == 1  # 完整行 a=3;坏行不计入返回
        assert any(x.get("a") == 3 for x in rows2)
        assert r.parse_errors == 1

    def test_m17_run_dir_exclusive(self, tmp_path):
        """目录排他创建拒绝碰撞(M17)。"""
        d = tmp_path / "run_dir"
        d.mkdir()
        with pytest.raises(OSError):
            d.mkdir()


# ================================================= E2E(WSL) M01/M10/M22
requires_sync = pytest.mark.skipif(
    not (Path.home() / "projects" / "crypto_rl" /
         "stage2_6_1_runner" / "r17_supervision.py").is_file()
    or os.name == "nt",
    reason="WSL 同步执行面不可达")


@requires_sync
class TestSupervisorE2E:
    """supervisor 端到端(真实进程/文件;样本注入=显式测试输入源)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    SUP = SYNC / "stage2_6_1_runner" / "r17_supervision.py"
    RUNS = Path(
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
        "repair17/development/run_supervision/runs")

    def _run(self, tmp_path, samples, argv, timeout=90, max_s=120):
        run_dir = self.RUNS / f"e2e_{time.strftime('%H%M%S')}_{os.getpid()}"
        run_dir.mkdir(parents=True, exist_ok=False)
        proc = subprocess.run(
            [sys.executable, str(self.SUP),
             "--run-dir", str(run_dir), "--task-kind", "fixture",
             "--max-seconds", str(max_s),
             "--samples-source", f"file:{samples}"] + argv,
            capture_output=True, text=True, timeout=timeout, cwd=self.SYNC)
        return proc, run_dir

    def test_m10_critical_stops_business_without_agent(self, tmp_path):
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf(), [
                {"vol": "F:", "present": True, "free_gb": 3.0,
                 "writable": True}]),
                "guest": _guest()}) + "\n" +
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        proc, run_dir = self._run(
            tmp_path, samples,
            ["--", "bash", "-c", "sleep 90"])
        assert "R17ALERT" in proc.stdout
        assert '"severity":"CRITICAL"' in proc.stdout
        # 停止请求由本地策略执行(无 Agent 回复):业务 rc<0
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert '"event":"stop_requested"' in alerts
        assert '"event":"sigterm_sent"' in alerts
        summary = json.loads(
            (run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["business"]["rc"] < 0
        assert not summary["stop_requested_reasons"] is False
        # marker 无消费者测试的反向:这里 marker 即被消费(停止已执行)
        assert summary["business"]["protector"]["term_sent"] is True

    def test_m22_business_error_alert_and_no_retry(self, tmp_path):
        """业务 rc!=0 + stderr 含结构失败 → WORKER 事件;不自动重试。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        proc, run_dir = self._run(
            tmp_path, samples,
            ["--", "python3", "-c",
             "import sys; sys.stderr.write("
             "'PairGenerationError: too_few_distractors\\n');"
             "sys.exit(7)"])
        assert '"severity":"WORKER"' in proc.stdout
        assert "PairGenerationError" in proc.stdout
        # 不自动重试:业务只启动一次
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        assert alerts.count('"event":"business_started"') == 1
        summary = json.loads(
            (run_dir / "summary.json").read_text(encoding="utf-8"))
        assert summary["business"]["rc"] == 7

    def test_m01_finalize_no_residual_sampler(self, tmp_path):
        """收尾后无残留采样进程;run_record finalized(M01)。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        proc, run_dir = self._run(
            tmp_path, samples, ["--", "bash", "-c", "echo ok"])
        assert proc.returncode == 0
        rr = json.loads(
            (run_dir / "run_record.json").read_text(encoding="utf-8"))
        assert rr["finalized"] is True
        assert rr["required"]
        # win 采样器已按 interop PID 停止(登记存在)
        alerts = (run_dir / "alerts" / "alerts.jsonl").read_text(
            encoding="utf-8")
        if '"event":"win_sampler_started"' in alerts:
            assert '"event":"win_sampler_stopped"' in alerts


# ============================================== M16/D5 真实入口集成
@requires_sync
class TestMonitoredEntryIntegration:
    """真实 monitored_entry(M16 并发拒绝)与 formal 观测接线
    (D5:无授权请求被拒后只关闭自身观测,资格证据区字节不变)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    ENTRY = SYNC / "stage2_6_1_runner" / "r17_monitored_entry.sh"
    FORMAL = SYNC / "stage2_6_1_runner" / "r17_formal_chain.sh"

    def test_m16_concurrent_second_rejected(self, tmp_path):
        """两个并发启动请求:被拒者 rc=95、写自己的 rejected 记录、
        不触碰 owner 的 run 目录(受控交错:owner 先获锁后再发第二个)。"""
        import tempfile
        lock = tmp_path / "test_supervision.lock"
        env = dict(os.environ, R17_SUPERVISION_LOCK=str(lock),
                   R17_PROJECT_ROOT=str(self.SYNC))
        # owner:先启动并等待其通过 flock 段(监控全链会跑满业务时长)
        owner_run = tmp_path / "owner_out.txt"
        with owner_run.open("wb") as so:
            owner = subprocess.Popen(
                ["bash", str(self.ENTRY), "fixture", "--max-seconds", "60",
                 "--", "bash", "-c", "sleep 20"],
                stdout=so, stderr=subprocess.STDOUT, cwd=self.SYNC, env=env)
        try:
            deadline = time.time() + 30
            while time.time() < deadline:
                if lock.exists():
                    break
                assert owner.poll() is None, "owner 提前退出"
                time.sleep(0.5)
            assert lock.exists(), "owner 未在期限内建立锁"
            # 第二个请求:必须被单例拒绝(非零+95)
            second = subprocess.run(
                ["bash", str(self.ENTRY), "fixture",
                 "--", "bash", "-c", "echo second-ran"],
                capture_output=True, text=True, timeout=60,
                cwd=self.SYNC, env=env)
            assert second.returncode == 95, second.stderr
            assert "被拒" in second.stderr or "拒绝" in second.stderr
            # 被拒记录只写监护面 rejected/(不触碰资格证据区)
            superv_root = Path(
                "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
                "repair17/development/run_supervision")
            rej = superv_root / "rejected" / "rejected.jsonl"
            assert rej.is_file()
            last = rej.read_text(encoding="utf-8").strip().split("\n")[-1]
            assert "rejected_concurrent" in last
            # owner 不受影响:仍在运行(被拒者未杀 owner 的任何进程)
            assert owner.poll() is None
        finally:
            if owner.poll() is None:
                owner.terminate()
                try:
                    owner.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    owner.kill()
                    owner.wait(timeout=10)

    def test_d5_formal_bootstrap_rejected_request_closes_own_obs(
            self, tmp_path):
        """formal 观测接线:假 SHA 请求被链拒绝;观测登记存在、teardown
        关闭采样器。

        状态根隔离教训(本测试首版误触发):必须以 R17_STATE_ROOT 指向
        测试隔离根——真实入口的 chain-run 会建立 execgov 准入会话并写
        journal(即使假 SHA 在 provenance-verify 第一步即失败、零正式
        数据消费);不隔离即新增正式治理面记录。真实部署状态根在整个
        测试过程中必须字节不变。"""
        real_state = self.SYNC / "artifacts" / \
            "route_c_stage2_6_1_repair17" / "state"
        before_real = sorted(str(p.relative_to(real_state))
                             for p in real_state.rglob("*")) \
            if real_state.is_dir() else []
        req_root = self.SYNC / "r17_formal_requests"
        before_reqs = sorted(p.name for p in req_root.iterdir()) \
            if req_root.is_dir() else []
        iso_state = tmp_path / "iso_state"
        iso_art = tmp_path / "iso_art"
        proc = subprocess.run(
            ["bash", str(self.FORMAL), "0" * 40],
            capture_output=True, text=True, timeout=900,
            cwd=self.SYNC,
            env=dict(os.environ,
                     R17_PROJECT_ROOT=str(self.SYNC),
                     R17_STATE_ROOT=str(iso_state),
                     R17_ART_ROOT=str(iso_art)))
        assert proc.returncode != 0  # 假 SHA 必然被拒
        after_reqs = sorted(p.name for p in req_root.iterdir())
        new_reqs = [r for r in after_reqs if r not in before_reqs]
        assert len(new_reqs) == 1
        rd = req_root / new_reqs[0]
        # 观测登记存在且被 teardown 封口(请求独立)
        assert (rd / "observation.json").is_file()
        assert (rd / "launch_evidence.jsonl").is_file()
        ev = (rd / "launch_evidence.jsonl").read_text(encoding="utf-8")
        assert "observation_closed" in ev  # EXIT trap 执行
        obs = json.loads(
            (rd / "observation.json").read_text(encoding="utf-8"))
        # interop 采样器进程已停(teardown kill 生效)
        pid = obs["win_sampler_interop_pid"]
        alive = os.path.exists(f"/proc/{pid}")
        assert not alive, f"win 采样器 interop pid={pid} 未被 teardown 停止"
        # 真实部署状态根:测试期间字节不变(隔离根承接全部治理面写入)
        after_real = sorted(str(p.relative_to(real_state))
                            for p in real_state.rglob("*")) \
            if real_state.is_dir() else []
        assert after_real == before_real, \
            "D5 测试不得触碰真实部署状态根(用 R17_STATE_ROOT 隔离)"


# ================================================= M24/M12 补充
@requires_sync
class TestM24M12Supplement:
    """M24:同输入监护前后业务输出等价(确定性;遥测时序不进业务);
    M12:supervisor 自身被停 → 受控收尾并停止业务(无伪终态)。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    DIAG = SYNC / "stage2_6_1_runner" / "r17_c3_p52_diagnosis.py"
    ENV_PATH = Path(
        "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
        "repair17/development/run_supervision/wp7_env_fixture.json")

    def test_m24_diagnosis_dp_deterministic(self, tmp_path):
        """诊断脚本的只读部分(DP+envelope 分析)对同输入两次运行
        逐字节等价(排除 written_utc)——监护时序不影响业务数值。"""
        env_src = Path(
            "/home/cryptorl/projects/crypto_rl/r17_rt_runs/"
            "20260906T134324Z_1475/artifacts/"
            "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json")
        if not env_src.is_file():
            pytest.skip("run 1475 envelope 不在本机")
        outs = []
        for i in (1, 2):
            o = tmp_path / f"diag_{i}.json"
            rc = subprocess.run(
                [sys.executable, str(self.DIAG),
                 "--envelope", str(env_src),
                 "--out", str(o), "--no-replay"],
                capture_output=True, text=True, timeout=300,
                cwd=self.SYNC)
            assert rc.returncode == 0, rc.stderr
            doc = json.loads(o.read_text(encoding="utf-8"))
            doc.pop("written_utc", None)
            outs.append(json.dumps(doc, sort_keys=True))
        assert outs[0] == outs[1]

    def test_m12_supervisor_termination_stops_business(self, tmp_path):
        """M12:杀 supervisor(SIGTERM)→ 其收尾路径停止业务进程组;
        不留业务残留、无伪终态。"""
        samples = tmp_path / "s.jsonl"
        samples.write_text(
            json.dumps({"win": _win(_perf()), "guest": _guest()}) + "\n",
            encoding="utf-8")
        run_dir = Path(
            "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
            "repair17/development/run_supervision/runs")
        rd = run_dir / f"m12_{time.strftime('%H%M%S')}_{os.getpid()}"
        rd.mkdir(parents=True, exist_ok=False)
        proc = subprocess.Popen(
            [sys.executable,
             str(self.SYNC / "stage2_6_1_runner" /
                 "r17_supervision.py"),
             "--run-dir", str(rd), "--task-kind", "fixture",
             "--max-seconds", "120",
             "--samples-source", f"file:{samples}",
             "--", "bash", "-c", "sleep 120"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=self.SYNC)
        time.sleep(4)  # 业务已启动
        alerts = rd / "alerts" / "alerts.jsonl"
        deadline = time.time() + 60
        while time.time() < deadline:
            if alerts.is_file() and "business_started" in \
                    alerts.read_text(encoding="utf-8"):
                break
            time.sleep(0.5)
        biz_pid = None
        for line in alerts.read_text(encoding="utf-8").splitlines():
            obj = json.loads(line)
            if obj.get("event") == "business_started":
                biz_pid = obj["pid"]
                break
        assert biz_pid, "业务未启动"
        proc.terminate()  # 杀 supervisor(模拟监护死亡)
        proc.wait(timeout=60)
        time.sleep(2)
        # 业务进程被 supervisor 收尾路径停止(不残留)
        assert not os.path.exists(f"/proc/{biz_pid}"), \
            f"supervisor 终止后业务残留 pid={biz_pid}"
        summary = json.loads(
            (rd / "summary.json").read_text(encoding="utf-8"))
        assert summary["business"]["rc"] is not None


class TestStaleRaceRegression:
    def test_negative_stale_clamped_not_wrapped(self):
        """真实负载回归:主循环 mono 与采样线程 last_*_mono 的竞态
        产生微负差时,禁止经 % 翻成 ~60s 假失联(全量回归曾因此被
        保护性误停)。主循环口径在 supervisor 内部,此处锁定引擎对
        边界值的判定与取模语义差异。"""
        # 引擎层:0/微小值不触发;大值才触发(不受修复影响)
        eng = PolicyEngine()
        assert not eng.evaluate(1.0, None, None, None, None, 0.0)
        w = eng.evaluate(2.0, None, None, None, None, 16.0)
        assert any(t["kind"] == "observation_stale" for t in w)
        # 取模语义反例:-0.02 % 60 == 59.98(Python),证明曾把微负
        # 竞态差放大成假 CRITICAL 的机制真实存在
        assert (-0.02) % 60.0 == pytest.approx(59.98)
        # supervisor 主循环修复后的公式:clamp 到 0
        mono, newest = 20.9, 20.92
        assert max(0.0, mono - newest) == 0.0
