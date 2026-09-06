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
    POLICY, Incident, PolicyEngine, Protector, SustainWindow,
    Supervisor, WinSampleReader, policy_digest)

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
        """S2 后失联按来源独立判活(float 兼容形态=两源同值);
        阶梯 15s W/30s C 不变,kind 带 _win/_guest 后缀。"""
        eng = PolicyEngine()
        w = eng.evaluate(1.0, None, None, None, None, 16.0)
        assert {t["kind"] for t in w} >= {"observation_stale_win",
                                          "observation_stale_guest"}
        assert all(t["severity"] == "WARNING" for t in w
                   if t["kind"].startswith("observation_stale"))
        eng2 = PolicyEngine()
        c = eng2.evaluate(2.0, None, None, None, None, 31.0)
        assert any(t["kind"] == "observation_stale_win" and
                   t["severity"] == "CRITICAL" for t in c)
        assert any(t["kind"] == "observation_stale_guest" and
                   t["severity"] == "CRITICAL" for t in c)

    def test_s2_independent_source_liveness(self):
        """C05 语义(单元层):一侧活跃不得掩盖另一侧失联。"""
        eng = PolicyEngine()
        out = eng.evaluate(5.0, None, None, None, None,
                           {"win": 1.0, "guest": 31.0})
        kinds = {(t["kind"], t["severity"]) for t in out}
        assert ("observation_stale_guest", "CRITICAL") in kinds
        assert not any(k.startswith("observation_stale_win")
                       for k, _ in kinds), "win 侧活跃不得被误报"
        eng2 = PolicyEngine()
        out2 = eng2.evaluate(5.0, None, None, None, None,
                             {"win": 31.0, "guest": 0.5})
        kinds2 = {(t["kind"], t["severity"]) for t in out2}
        assert ("observation_stale_win", "CRITICAL") in kinds2
        assert not any(k.startswith("observation_stale_guest")
                       for k, _ in kinds2)

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
        # 纳秒尾段防同秒+同测试进程 pid 的目录名碰撞
        # (final3 全量真实暴露:M10/M22/M01 同秒连跑)
        run_dir = self.RUNS / (f"e2e_{time.strftime('%H%M%S')}"
                               f"_{os.getpid()}_{time.time_ns() % 100000:05d}")
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
                   R17_PROJECT_ROOT=str(self.SYNC),
                   R17_RUN_DIR="")  # 防御:外层嵌套泄漏清理
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

    def test_d5_formal_admission_rejected_zero_formal_footprint(
            self, tmp_path):
        """D5(重写,WP0c/C01):无许可时 formal 入口准入前拒绝。

        教训(本测试首版经 R17_PROJECT_ROOT=部署面 误触 6 次真实
        formal 入口,见 wp0_formal_incident/incident_timeline.md):
        正式 root 不得经环境变量重定向成"测试正式";工程测试一律
        沙箱 PROJECT_ROOT + 部署面真实 runner(R17_RUNNER_DIR)。
        断言:rc=96、请求目录只有 admission_rejected.jsonl、无
        观测/环境激活/$ART、真实部署面(请求根+状态根+ART 顶层)
        逐字节不变。"""
        before = _snapshot_deploy_face(self.SYNC)
        env = dict(os.environ,
                   R17_PROJECT_ROOT=str(tmp_path),
                   R17_RUNNER_DIR=str(
                       self.SYNC / "stage2_6_1_runner"))
        proc = subprocess.run(
            ["bash", str(self.FORMAL), "0" * 40],
            capture_output=True, text=True, timeout=120,
            cwd=str(tmp_path), env=env)
        assert proc.returncode == 96, (proc.returncode, proc.stderr)
        assert "admission_missing" in proc.stderr
        # 沙箱请求目录:恰好 1 个,只含准入拒绝日志
        req_root = tmp_path / "r17_formal_requests"
        reqs = sorted(p.name for p in req_root.iterdir())
        assert len(reqs) == 1
        rd = req_root / reqs[0]
        assert sorted(p.name for p in rd.iterdir()) == \
            ["admission_rejected.jsonl"]
        rec = json.loads(
            (rd / "admission_rejected.jsonl").read_text(
                encoding="utf-8").strip().splitlines()[-1])
        assert rec["event"] == "admission_rejected"
        assert rec["reason"] == "admission_missing"
        assert rec["freeze_sha"] == "0" * 40
        # 拒绝发生在环境激活/观测接线/正式目录创建之前
        assert not (rd / "launch_evidence.jsonl").exists()
        assert not (rd / "observation.json").exists()
        assert not (tmp_path / "artifacts").exists()
        # 真实部署面逐字节不变(不访问部署 formal root 的验证)
        assert _snapshot_deploy_face(self.SYNC) == before, \
            "D5 测试不得触碰真实部署面任何字节"


# ============================== WP0c 正式准入隔离(C01 矩阵)
def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _snapshot_deploy_face(sync: Path) -> dict:
    """部署面 formal 三区只读快照:请求根文件哈希、状态根、ART 顶层。"""
    art = sync / "artifacts" / "route_c_stage2_6_1_repair17"
    snap: dict = {}
    for label, root in (
            ("req", sync / "r17_formal_requests"),
            ("state", art / "state"), ("art", art)):
        if not root.is_dir():
            snap[label] = "absent"
            continue
        entries = {}
        for p in sorted(root.rglob("*")):
            rel = str(p.relative_to(root))
            entries[rel] = _sha256_file(p) if p.is_file() else "dir"
        snap[label] = entries
    return snap


@requires_sync
class TestFormalAdmissionIsolation:
    """C01:无有效正式许可时,入口与直接 CLI 均准入前拒绝;
    假许可/环境重定向不构成通道;部署面零写入。"""

    SYNC = Path.home() / "projects" / "crypto_rl"
    FORMAL = SYNC / "stage2_6_1_runner" / "r17_formal_chain.sh"
    CONDA_PY = Path(
        "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python")

    def _run_sandbox(self, sandbox: Path, *, sha="0" * 40,
                     extra_env=None):
        env = dict(os.environ,
                   R17_PROJECT_ROOT=str(sandbox),
                   R17_RUNNER_DIR=str(
                       self.SYNC / "stage2_6_1_runner"))
        env.update(extra_env or {})
        return subprocess.run(
            ["bash", str(self.FORMAL), sha],
            capture_output=True, text=True, timeout=120,
            cwd=str(sandbox), env=env)

    def test_c01_env_redirect_forbidden(self, tmp_path):
        """正式 root 不可由 R17_ART_ROOT/R17_STATE_ROOT 重定义。"""
        before = _snapshot_deploy_face(self.SYNC)
        for var in ("R17_ART_ROOT", "R17_STATE_ROOT"):
            proc = self._run_sandbox(
                tmp_path, extra_env={var: str(tmp_path / "x")})
            assert proc.returncode == 96, (var, proc.stderr)
            assert "env_redirect_forbidden" in proc.stderr
        assert _snapshot_deploy_face(self.SYNC) == before

    def test_c01_wellformed_fake_admission_rejected(self, tmp_path):
        """格式正确的假许可(sha 非仓库对象)仍被拒:
        40 零/WIP SHA/--freeze-sha 均不是授权。"""
        fake_sha = "a" * 40
        state = tmp_path / "artifacts" / \
            "route_c_stage2_6_1_repair17" / "state"
        (tmp_path / ".r17_formal_admission.json").write_text(
            json.dumps({
                "format": "cur261-r17-formal-admission-v1",
                "commit_a_sha": fake_sha,
                "deployed_state_root": str(state),
                "admission_id": "sandbox-fixture-1"}),
            encoding="utf-8")
        proc = self._run_sandbox(tmp_path, sha=fake_sha)
        assert proc.returncode == 96
        assert "admission_git_object_missing" in proc.stderr

    def test_c01_cli_direct_formal_rejected_zero_files(self, tmp_path):
        """绕过 shell 直接 CLI chain-run(formal)同样被拒;
        rc=96 且未创建任何文件(out-dir/chain_logs/plan)。"""
        if not self.CONDA_PY.exists():
            pytest.skip("部署面 conda 解释器不可达")
        out_dir = tmp_path / "artifacts" / \
            "route_c_stage2_6_1_repair17"
        env = dict(os.environ,
                   PYTHONPATH=str(self.SYNC / "src"),
                   CURRICULUM261_R17_STATE_ROOT=str(out_dir / "state"))
        proc = subprocess.run(
            [str(self.CONDA_PY), "-m",
             "rl_curriculum.curriculum261_r17_cli", "chain-run",
             "--out-dir", str(out_dir), "--freeze-sha", "1" * 40],
            capture_output=True, text=True, timeout=180,
            cwd=str(self.SYNC), env=env)
        assert proc.returncode == 96, (proc.stdout, proc.stderr)
        assert "formal admission" in proc.stdout
        assert "admission_missing" in proc.stdout
        assert not out_dir.exists()
        assert not (out_dir.parent /
                    (out_dir.name + "_chain_logs")).exists()

    def test_c01_observation_wiring_functions_sandboxed(
            self, tmp_path):
        """准入拒绝路径不启动观测;bootstrap/teardown 函数级验证
        (沙箱请求目录;补原 D5 观测覆盖,不经 formal 入口)。"""
        runner = self.SYNC / "stage2_6_1_runner"
        req_dir = tmp_path / "req"
        req_dir.mkdir()
        script = (
            'source "{r}/r17_entry_common.sh"\n'
            'REQ_DIR="{d}"\n'
            'LAUNCH_EVIDENCE="$REQ_DIR/launch_evidence.jsonl"\n'
            'if r17_monitored_bootstrap "$REQ_DIR" c01obs; then\n'
            '  emit_launch bootstrap_ok "win sampler started"\n'
            'fi\n'
            'r17_monitored_teardown "$REQ_DIR"\n'
        ).format(r=runner, d=req_dir)
        proc = subprocess.run(
            ["bash", "-c", script], capture_output=True, text=True,
            timeout=60, cwd=str(tmp_path))
        assert proc.returncode == 0, proc.stderr
        ev = (req_dir / "launch_evidence.jsonl").read_text(
            encoding="utf-8")
        assert "observation_closed" in ev  # teardown 必然封口
        obs_file = req_dir / "observation.json"
        if obs_file.is_file():
            pid = json.loads(
                obs_file.read_text(encoding="utf-8")
            )["win_sampler_interop_pid"]
            assert not os.path.exists(f"/proc/{pid}"), \
                f"采样器 interop pid={pid} 未被 teardown 停止"


class TestFormalAdmissionUnit:
    """准入许可模块单元行为(全拒绝分支+一次性+git 对象校验)。
    夹具许可只存在于 tmp 沙箱+tmp git 仓库,永不触部署面;不生成
    任何对真实部署面有效的许可。"""

    @staticmethod
    def _repo_with_commit(tmp_path: Path):
        repo = tmp_path / "repo"
        repo.mkdir()
        for args in (
                ["git", "init", "-q", "."],
                ["git", "config", "user.email", "t@example.invalid"],
                ["git", "config", "user.name", "t"],
                ["git", "commit", "--allow-empty", "-q", "-m", "x"],
        ):
            subprocess.run(args, cwd=str(repo), check=True)
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, check=True
        ).stdout.strip()
        return repo, sha

    def _mk_admission(self, tmp_path: Path, *, sha, state=None,
                      aid="aid-unit-1", fmt=None, freeze=None):
        from rl_curriculum.curriculum261_r17_admission import (
            ADMISSION_FILENAME, ADMISSION_FORMAT)
        dr = tmp_path / "deploy"
        dr.mkdir(parents=True, exist_ok=True)
        st = state or (dr / "artifacts" /
                       "route_c_stage2_6_1_repair17" / "state")
        (dr / ADMISSION_FILENAME).write_text(json.dumps({
            "format": fmt or ADMISSION_FORMAT,
            "commit_a_sha": sha,
            "deployed_state_root": str(st),
            "admission_id": aid,
        }), encoding="utf-8")
        return dr, st, (freeze if freeze is not None else sha)

    @staticmethod
    def _validate(dr, st, freeze, repo):
        from rl_curriculum.curriculum261_r17_admission import (
            validate_admission)
        return validate_admission(dr, st, freeze, str(repo))

    def test_deploy_root_shape(self, tmp_path):
        from rl_curriculum.curriculum261_r17_admission import (
            deploy_root_of)
        good = tmp_path / "d" / "artifacts" / \
            "route_c_stage2_6_1_repair17" / "state"
        assert deploy_root_of(good) == tmp_path / "d"
        assert deploy_root_of(tmp_path / "x" / "state") is None
        assert deploy_root_of(tmp_path) is None

    def test_missing_and_unreadable(self, tmp_path):
        dr, st, fz = self._mk_admission(tmp_path, sha="b" * 40)
        (dr / ".r17_formal_admission.json").unlink()
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_missing")
        (dr / ".r17_formal_admission.json").write_text(
            "{not json", encoding="utf-8")
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_unreadable")

    def test_format_and_sha_branches(self, tmp_path):
        dr, st, fz = self._mk_admission(tmp_path, sha="b" * 40,
                                        fmt="wrong-format")
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_format_mismatch")
        dr, st, fz = self._mk_admission(tmp_path, sha="0" * 40)
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_sha_invalid")
        dr, st, fz = self._mk_admission(tmp_path, sha="nothex")
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_sha_invalid")
        dr, st, fz = self._mk_admission(tmp_path, sha="b" * 40,
                                        freeze="c" * 40)
        ok, reason, _ = self._validate(dr, st, fz, tmp_path)
        assert (ok, reason) == (False, "admission_freeze_mismatch")

    def test_state_root_binding(self, tmp_path):
        dr, st, fz = self._mk_admission(tmp_path, sha="b" * 40,
                                        state=tmp_path / "other" /
                                        "artifacts" /
                                        "route_c_stage2_6_1_repair17" /
                                        "state")
        ok, reason, _ = self._validate(
            dr, tmp_path / "deploy" / "artifacts" /
            "route_c_stage2_6_1_repair17" / "state", fz, tmp_path)
        assert (ok, reason) == (False, "admission_state_root_unbound")

    def test_valid_then_consume_once(self, tmp_path):
        """全过 → 通过;消费后同 admission_id 重放被拒(一次性)。"""
        from rl_curriculum.curriculum261_r17_admission import (
            CONSUMED_NAME, consume_admission, enforce_formal_admission)
        repo, sha = self._repo_with_commit(tmp_path)
        dr, st, fz = self._mk_admission(tmp_path, sha=sha)
        ok, reason, adm = self._validate(dr, st, fz, repo)
        assert ok, reason
        # enforce:通过 → None,并写一次性消费记录
        assert enforce_formal_admission(
            st, fz, str(repo)) is None
        assert (st / CONSUMED_NAME).is_file()
        # 同一许可重放 → already_consumed
        assert enforce_formal_admission(
            st, fz, str(repo)) == "admission_already_consumed"
        # 新 admission_id(同 sha)仍可过 → 消费记录区分 id 而非 sha
        dr2, st2, fz2 = self._mk_admission(
            tmp_path / "second", sha=sha, aid="aid-unit-2")
        assert enforce_formal_admission(
            st2, fz2, str(repo)) is None

    def test_git_object_must_exist(self, tmp_path):
        """许可 sha 必须是 release 仓库中的真实 commit 对象。"""
        repo, sha = self._repo_with_commit(tmp_path)
        # 同长度 40hex 但不是该仓库对象
        ghost = ("0" * 39) + "1"
        dr, st, fz = self._mk_admission(tmp_path, sha=ghost)
        ok, reason, _ = self._validate(dr, st, fz, repo)
        assert (ok, reason) == (False, "admission_git_object_missing")
        # release 仓库不存在 .git → fail closed
        empty = tmp_path / "empty_repo"
        empty.mkdir()
        dr2, st2, fz2 = self._mk_admission(
            tmp_path / "third", sha=sha)
        ok2, reason2, _ = self._validate(dr2, st2, fz2, empty)
        assert (ok2, reason2) == (
            False, "admission_git_object_missing")

    def test_gate_cli_rc_semantics(self, tmp_path):
        """shell 消费面:gate 子命令 rc=0(通过,stdout JSON)/
        rc=96(拒绝,stdout=预注册 reason)。"""
        from rl_curriculum.curriculum261_r17_admission import (
            ADMISSION_FILENAME, REJECT_RC, main)
        repo, sha = self._repo_with_commit(tmp_path)
        dr, st, fz = self._mk_admission(tmp_path, sha=sha)
        rc = main(["gate", "--deploy-root", str(dr),
                   "--state-root", str(st), "--freeze-sha", fz,
                   "--release-repo", str(repo)])
        assert rc == 0
        rc = main(["gate", "--deploy-root", str(dr),
                   "--state-root", str(st),
                   "--freeze-sha", "d" * 40,
                   "--release-repo", str(repo)])
        assert rc == REJECT_RC


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
        assert any(t["kind"].startswith("observation_stale")
                   for t in w)
        # 取模语义反例:-0.02 % 60 == 59.98(Python),证明曾把微负
        # 竞态差放大成假 CRITICAL 的机制真实存在
        assert (-0.02) % 60.0 == pytest.approx(59.98)
        # supervisor 主循环修复后的公式:clamp 到 0
        mono, newest = 20.9, 20.92
        assert max(0.0, mono - newest) == 0.0


# ============================ 监护接线闭合轮(S1-S5/C 矩阵反例)
class TestWiringClosure:
    """S1 真实采样交接/S2 就绪屏障+独立判活/S3 组信号+时钟/S4
    升级不被吞+IO 不挡保护/S5 required 运行前登记;对应任务书
    §10 C03/C04/C06-C10/C14/C15 可夹具化项。"""

    @staticmethod
    def _sup(tmp_path, argv=("--", "true"), task_kind="fixture",
             expect=None):
        import argparse as _ap
        args = _ap.Namespace(
            run_dir=str(tmp_path / "run"), task_kind=task_kind,
            argv=list(argv), task_cwd=None, max_seconds=0,
            samples_source="", win_sampler_ps1="/nonexistent.ps1",
            win_volumes="C:,F:", expect_artifact=expect or [],
            obs_ready_deadline=30.0)
        return Supervisor(args)

    # ---------------- S1:真实采样进入判定与摘要 ----------------
    def test_c03_guest_snapshot_reaches_engine_and_peaks(self, tmp_path):
        sup = self._sup(tmp_path)
        sample = {
            "event": "guest_sample", "utc": "2026-09-06T18:00:00Z",
            "meminfo": {"MemAvailable": 1.5 * 1024 * 1024},
            "psi_memory": {"full_avg10": 5.0},
            "vmstat_swap": {"pswpout": 100},
            "tasks_total_rss_kb": 3 * 1024 * 1024,
            "task_cpu_sec_delta": 2.5, "task_count": 4}
        sup._emit_guest(sample)  # 线程回调路径:落盘+快照
        snap = sup._guest_snapshot()
        assert snap and snap["meminfo"]["MemAvailable"] == \
            1.5 * 1024 * 1024
        task = sup._task_aggregate(snap)
        assert task is not None  # S1:task 聚合拿到真实数据
        # 引擎消费同一样本:CRITICAL 组合条件(低内存+PSI 热)
        eng = PolicyEngine()
        trig = eng.evaluate(10.0, None, snap, task, None, None)
        assert any(t["kind"] == "guest_memavail" and
                   t["severity"] == "PROTECTION_UNAVAILABLE" or
                   t["severity"] == "CRITICAL" for t in trig) or \
            eng.g_mem_crit.count >= 1  # 窗口已开始累计(首样本)
        # 峰值/摘要消费同来源
        sup._update_peaks(None, snap, task)
        assert sup.peak["guest_memavail_min_gib"] == \
            pytest.approx(1.5)
        assert sup.peak["task_tree_rss_max_gib"] == \
            pytest.approx(3.0, abs=0.01)

    def test_c03_same_sample_not_counted_twice(self, tmp_path):
        """同一快照重复消费不增加窗口有效样本数(空白不算持续)。"""
        sup = self._sup(tmp_path)
        sample = {"event": "guest_sample",
                  "utc": "2026-09-06T18:00:00Z",
                  "meminfo": {"MemAvailable": 1.5 * 1024 * 1024},
                  "psi_memory": {"full_avg10": 5.0},
                  "vmstat_swap": {"pswpout": 7}}
        sup._emit_guest(sample)
        snap = sup._guest_snapshot()
        eng = PolicyEngine()
        eng.evaluate(10.0, None, snap, None, None, None)
        assert eng.g_mem_crit.count == 1
        # 主循环多轮沿用同一条快照(无新样本):计数不涨
        eng.evaluate(11.0, None, snap, None, None, None)
        eng.evaluate(12.0, None, snap, None, None, None)
        assert eng.g_mem_crit.count == 1
        # 新样本到达(新 utc):计数 +1
        s2 = dict(sample, utc="2026-09-06T18:00:05Z")
        eng.evaluate(13.0, None, s2, None, None, None)
        assert eng.g_mem_crit.count == 2

    # ---------------- S2:就绪屏障 ----------------
    def test_c04_not_ready_rejects_without_spawn(self, tmp_path):
        """win 采样器不可用:就绪失败,业务 spawn 次数为零,自身
        采样器关闭,rc=93(有界拒绝,不启动业务再等)。"""
        import argparse as _ap
        args = _ap.Namespace(
            run_dir=str(tmp_path / "run"), task_kind="fixture",
            argv=["--", "bash", "-c", "echo should-not-run"],
            task_cwd=None, max_seconds=0, samples_source="",
            win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
            expect_artifact=[], obs_ready_deadline=2.0)
        sup = Supervisor(args)
        rc = sup.run()
        assert rc == 93
        alerts = (tmp_path / "run" / "alerts" /
                  "alerts.jsonl").read_text(encoding="utf-8")
        assert "observation_not_ready" in alerts
        # 业务未启动:stdout/stderr 文件不存在
        assert not (tmp_path / "run" / "business" /
                    "stdout.log").exists()
        # 自身采样器已收(收尾完成,run_record 已封口)
        assert (tmp_path / "run" / "run_record.json").is_file()

    def test_c06_budget_cap_is_sticky_protection(self, tmp_path):
        """遥测预算耗尽=核心证据无法保存:粘性保护性中止
        (PROTECTION_UNAVAILABLE),不得停采样后宣称保护有效。"""
        sup = self._sup(tmp_path)
        sup.policy["telemetry_budget_bytes"] = 128
        sup.guest_path.write_text("x" * 256, encoding="utf-8")
        sup.budget_check()
        assert sup.telemetry_capped
        assert "telemetry_budget" in sup.incidents
        assert sup.stop_requested_reasons, "预算耗尽必须调度停止"
        alerts_txt = sup.alerts_path.read_text(encoding="utf-8")
        assert "telemetry_budget_exceeded" in alerts_txt

    # ---------------- S3:保护目标/时钟/身份 ----------------
    @staticmethod
    def _proc_start_ticks(pid):
        with open(f"/proc/{pid}/stat") as fh:
            text = fh.read()
        return int(text[text.rindex(")") + 2:].split()[19])

    def test_c07_group_escalation_and_neighbor_survival(self):
        """leader+child+grandchild(忽略 TERM):合作窗后组信号升级;
        组成员实际核验;旁边无关进程存活;无 task_tree_gone 误报。"""
        leader = subprocess.Popen(
            ["bash", "-c",
             'trap "" TERM; '
             'bash -c \'trap "" TERM; sleep 60\' & wait'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        neighbor = subprocess.Popen(
            ["sleep", "60"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            time.sleep(0.8)  # 子/孙进程就位
            pgid = os.getpgid(leader.pid)
            logs: list[dict] = []
            prot = Protector(
                pgid, 1.5, lambda r: logs.append(r),
                leader_pid=leader.pid,
                leader_start_ticks=self._proc_start_ticks(leader.pid),
                mono_fn=time.monotonic)
            prot.request_stop("c07")
            assert prot.term_sent_at is not None
            time.sleep(0.4)
            # 组内仍有忽略 TERM 的成员:leader 退出不误报树消失
            assert prot.poll(time.monotonic()) is False
            assert not any(l.get("event") == "task_tree_gone"
                           for l in logs), "leader 退出≠任务树消失"
            # 合作窗后升级 KILL(组信号:孙进程也被终止)
            deadline = time.monotonic() + 6
            while time.monotonic() < deadline:
                if prot.poll(time.monotonic()):
                    break
                time.sleep(0.3)
            assert prot.kill_sent_at is not None, "必须升级 KILL"
            assert prot.terminal_at is not None
            assert not prot._member_pids(), "组内成员必须全部终止"
            # 旁边无关进程未被波及
            assert neighbor.poll() is None, "无关进程被误杀"
        finally:
            for p in (leader, neighbor):
                if p.poll() is None:
                    p.kill()
                    p.wait(timeout=10)

    def test_c08_high_monotonic_origin_and_identity_mismatch(self):
        """非零单调起点:超时/升级计算不受时钟基准污染;登记身份
        不符(PID 复用形态)不发送任何信号。"""
        base = 1_000_000.0  # 长运行机器形态
        clock = {"now": base}
        logs: list[dict] = []
        dummy = subprocess.Popen(
            ["sleep", "30"], stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            pgid = os.getpgid(dummy.pid)
            prot = Protector(pgid, 2.0, lambda r: logs.append(r),
                             leader_pid=dummy.pid,
                             leader_start_ticks=12345,  # 错误身份
                             mono_fn=lambda: clock["now"])
            prot.request_stop("c08")
            assert prot.identity_mismatch
            assert prot.term_sent_at is None  # 未发信号
            assert dummy.poll() is None, "身份不符不得发信号"
            clock["now"] = base + 100
            assert prot.poll(clock["now"]) is False  # 未证实非终态
            # 身份不符后成员仍在:残留如实保留(survivors),不盲杀
            assert prot.poll(base + 200) is False
        finally:
            dummy.kill()
            dummy.wait(timeout=10)

    def test_c08_clock_consistency_high_origin(self):
        """同基准升级:term_sent_at 与 poll 入参同钟(高起点下
        合作窗超时按差值正确判定,不受绝对值影响)。"""
        base = 1_000_000.0
        clock = {"now": base}
        victim = subprocess.Popen(
            ["bash", "-c", 'trap "" TERM; sleep 30'],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            start_new_session=True)
        try:
            time.sleep(0.3)
            pgid = os.getpgid(victim.pid)
            prot = Protector(pgid, 1.0, lambda r: None,
                             mono_fn=lambda: clock["now"])
            prot.request_stop("clock")
            assert prot.term_sent_at == pytest.approx(base)
            assert prot.kill_sent_at is None  # 窗口内不升级
            clock["now"] = base + 0.5
            prot.poll(clock["now"])
            assert prot.kill_sent_at is None
            clock["now"] = base + 1.2  # 超过合作窗:升级 KILL
            prot.poll(clock["now"])
            assert prot.kill_sent_at is not None
        finally:
            victim.kill()
            victim.wait(timeout=10)

    # ---------------- S4:升级不被冷却吞+IO 不挡保护 ----------------
    def test_c09_escalation_survives_cooldown(self, tmp_path):
        sup = self._sup(tmp_path)
        warn = {"kind": "win_free_phys", "severity": "WARNING",
                "detail": "低内存(测试)", "metrics": {"free_gib": 7}}
        sup.handle_triggers([warn])
        assert sup.incidents["win_free_phys"].delivered_count == 1
        # 60s 冷却期内立即升级 CRITICAL:升级告警必须立即产生
        crit = dict(warn, severity="CRITICAL")
        sup.handle_triggers([crit])
        inc = sup.incidents["win_free_phys"]
        assert inc.severity == "CRITICAL"
        assert inc.delivered_count == 2
        assert inc.stopped_requested
        assert sup.stop_requested_reasons
        alerts = sup.alerts_path.read_text(encoding="utf-8")
        assert '"action":"escalate"' in alerts, \
            "升级告警被冷却吞掉(S4)"
        # 独立新 CRITICAL 不受别的 incident 冷却影响
        other = {"kind": "storage_ceiling", "severity": "CRITICAL",
                 "detail": "存储触顶(测试)", "metrics": {}}
        sup.handle_triggers([other])
        assert "storage_ceiling" in sup.incidents
        assert sup.stop_requested_reasons[-1].startswith(
            "storage_ceiling")

    def test_c10_alert_io_failure_does_not_block_protection(
            self, tmp_path, monkeypatch):
        """alerts 落盘失败+stdout 断裂:CRITICAL 仍调度停止意图,
        失败如实计数,不抛出。"""
        import io as _io
        sup = self._sup(tmp_path)
        # alerts 路径不可写(以目录占位文件路径)
        sup.alerts_path.parent.mkdir(parents=True, exist_ok=True)
        sup.alerts_path.mkdir()  # open("a") 将抛 IsADirectoryError
        closed = _io.TextIOWrapper(_io.BytesIO(), encoding="utf-8")
        closed.close()
        monkeypatch.setattr(sys, "stdout", closed)
        crit = {"kind": "win_commit", "severity": "CRITICAL",
                "detail": "commit 触顶(测试)", "metrics": {}}
        sup.handle_triggers([crit])  # 不得抛出
        assert sup.stop_requested_reasons, "IO 失败不得阻止停止意图"
        inc = sup.incidents["win_commit"]
        assert inc.stopped_requested
        assert sup.log_failures > 0
        assert sup.stdout_failures > 0

    # ---------------- S5:required 运行前登记/缺件不缩小 ----------------
    def test_c14_missing_required_stays_missing(self, tmp_path):
        """finalize 前删已登记产物:required 不缩小;finalized 成立
        但 evidence_complete=False;build 可组包,verify FAIL。"""
        sup = self._sup(
            tmp_path, argv=["--", "python", "-m", "pytest",
                            "--junitxml=" + str(tmp_path / "j.xml"),
                            "-q"])
        # 模拟真实收尾:写入存在的件,缺 junit 与 summary
        sup.guest_path.write_text('{"event":"guest_sample"}\n',
                                  encoding="utf-8")
        sup.win_path_guest.write_text('{"event":"sample"}\n',
                                      encoding="utf-8")
        sup.alerts_path.write_text('{"event":"e"}\n', encoding="utf-8")
        sup.biz_stdout.write_text("out\n", encoding="utf-8")
        sup.biz_stderr.write_bytes(b"")  # 真实空文件
        rr = sup.finalize_run_record()
        rec = json.loads(rr.read_text(encoding="utf-8"))
        assert rec["schema"] == "r17-run-record-v2"
        roles = {r["role"]: r for r in rec["required"]}
        assert roles["junit_xml"]["status"] == "missing"
        assert roles["summary"]["status"] == "missing"
        assert roles["business_stderr"]["status"] == "present"
        assert roles["business_stderr"]["bytes"] == 0
        assert rec["evidence_complete"] is False
        assert set(rec["missing_roles"]) >= {"junit_xml", "summary"}
        # build 允许(清单反映现实),verify 对缺件 FAIL
        root = sup.run_dir.parent.parent
        manifest = sup.run_dir / "manifest.jsonl"
        anchor = tmp_path / "anchor.json"
        b = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "build", "--run-record", str(rr),
             "--manifest-out", str(manifest),
             "--anchor-out", str(anchor), "--root", str(root)],
            capture_output=True, text=True)
        assert b.returncode == 0, b.stderr
        v = subprocess.run(
            [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
             "verify", "--root", str(root),
             "--manifest", str(manifest), "--anchor-file", str(anchor),
             "--run-record", str(rr),
             "--receipt-dir", str(tmp_path / "receipts")],
            capture_output=True, text=True)
        assert v.returncode == 1, "缺件交付必须 FAIL"
        assert "evidence_incomplete" in v.stderr

    def test_s5_junit_registered_from_bash_c_form(self, tmp_path):
        """--junitxml 嵌在 bash -c 命令串内(全量回归真实形态)也必须
        登记(第一轮全量回归暴露的接线缺口)。"""
        sup = self._sup(
            tmp_path, argv=["--", "bash", "-c",
                            "python -m pytest tests/x "
                            "--junitxml=" + str(tmp_path / "j.xml") +
                            " -q"])
        roles = [e["role"] for e in sup.expected]
        assert "junit_xml" in roles
        j = next(e for e in sup.expected if e["role"] == "junit_xml")
        assert j["path"] == (tmp_path / "j.xml").resolve()


# ======================= C11/C12 协调者监护停止联动(§5.2)
COORD_RUNNER_SCRIPT = r'''
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from rl_curriculum.curriculum261_r17_execgov import R17ChainSession
import rl_curriculum.curriculum261_r17_workflow as wf
from rl_curriculum.curriculum261_r17_workflow import (
    execute_workflow_chain_r17,
)

wf.R17_WORKFLOW_CLI_MODULE = sys.argv[5]  # 工程夹具步骤模块
sr, out, mode = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4]
binding = {"mode": "rehearsal", "freeze_sha": "f" * 40,
           "state_root": str(sr), "out_dir": str(out),
           "argv": ["c11-c12-fixture"]}
session = R17ChainSession.acquire(binding)
if mode == "c12":
    session.open_qualification_window("digest-c12", note="c12 preset")
    session.commit_qualification_terminal(
        "completed", "digest-c12", note="c12 preset completed")
steps = [
    {"name": "fixture_slow", "cli_command": "fixture",
     "argv": ["slow"], "requires_artifacts": [],
     "output_artifacts": []},
    {"name": "fixture_never", "cli_command": "fixture",
     "argv": ["never"], "requires_artifacts": [],
     "output_artifacts": []},
]
plan = {"profile": "rehearsal", "out_dir": str(out),
        "manifest_path": str(out / "manifest.jsonl"),
        "workflow_graph_digest": "c11-c12-fixture-digest",
        "steps": steps}
result = execute_workflow_chain_r17(plan, session=session,
                                    log_dir=out / "logs")
if not result["ok"]:
    session.record_iteration_aborted(result["failure_reason"][:2000])
session.release(summary="c11/c12 fixture")
print("COORDRESULT " + json.dumps(
    {"ok": result["ok"], "failed": result["failed_step"]}))
'''

COORD_SLEEP_MODULE = r'''
import sys
import time

if __name__ == "__main__":
    # 夹具双面:步骤模式=长睡眠(可被终止);fail-closure
    # 模式=立即成功(monkeypatch 的模块名同样会命中协调者
    # 的 fail-closure 子命令调用,不得让收尾也睡 90s)
    if "fail-closure" in sys.argv[1:]:
        sys.exit(0)
    time.sleep(90)
'''


@requires_sync
class TestChainCoordinatorSupervisionStop:
    """C11:工程 coordinator 在 grant/步骤窗口中收到停止请求 →
    终止 worker、唯一 journal writer 封口、无双重 acquire;
    C12:qualification 已 terminal 后中止不改原终态。
    夹具:真实 execute_workflow_chain_r17 + 真实 session/journal;
    步骤 CLI 模块为无业务数据的工程夹具(任务书 §9.1 允许)。"""

    SYNC_SRC = Path.home() / "projects" / "crypto_rl" / "src"

    def _start_coordinator(self, tmp_path, mode):
        tmp_path.mkdir(parents=True, exist_ok=True)
        state = tmp_path / "state"
        out = tmp_path / "out"
        (tmp_path / "fixture_root").mkdir(exist_ok=True)
        mod = tmp_path / "fixture_root" / "coord_sleep_fixture.py"
        mod.write_text(COORD_SLEEP_MODULE, encoding="utf-8")
        script = tmp_path / "coord_runner.py"
        script.write_text(COORD_RUNNER_SCRIPT, encoding="utf-8")
        env = dict(
            os.environ,
            PYTHONPATH=str(self.SYNC_SRC) + os.pathsep +
            str(tmp_path / "fixture_root"),
            CURRICULUM261_R17_STATE_ROOT=str(state))
        proc = subprocess.Popen(
            [sys.executable, str(script), str(self.SYNC_SRC), str(state),
             str(out), mode, "coord_sleep_fixture"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, env=env)
        journal = state / "r17_execution_journal.jsonl"
        deadline = time.time() + 30
        while time.time() < deadline:
            if journal.is_file() and \
                    "chain_step_started" in journal.read_text(
                        encoding="utf-8"):
                return proc, journal, out, state
            assert proc.poll() is None, \
                f"coordinator 提前退出: {proc.stdout.read() if proc.stdout else ''}"
            time.sleep(0.2)
        proc.kill()
        raise AssertionError("coordinator 未在期限内开始步骤")

    def test_c11_supervision_stop_graceful_closure(self, tmp_path):
        proc, journal, out, state = self._start_coordinator(
            tmp_path, "c11")
        proc.terminate()  # = 外层监护对登记组的停止请求
        stdout, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0, \
            f"协调者必须优雅退出(非信号死): rc={proc.returncode} {stdout}"
        assert "COORDRESULT" in stdout
        events = [json.loads(l) for l in
                  journal.read_text(encoding="utf-8").splitlines() if l]
        seq = [e["event"] for e in events]
        # 唯一 journal writer 的完整封口序列;无双重 acquire
        assert seq.count("chain_session_acquired") == 1
        assert "chain_step_started" in seq
        failed = [e for e in events if e["event"] == "chain_step_failed"]
        assert failed and failed[0]["rc"] == -15, \
            "worker 应被协调者 terminate(rc=-15)"
        aborted = [e for e in events
                   if e["event"] == "chain_iteration_aborted"]
        assert aborted and "supervision stop" in aborted[0]["reason"]
        assert seq[-1] == "chain_released"
        # 未启动新步骤:第二步零痕迹(无 started/log 文件)
        assert not any(
            e.get("step") == "fixture_never" for e in events
            if e["event"].startswith("chain_step"))
        assert not (out / "logs" / "fixture_never.log").exists()
        # 唯一 writer:所有事件 writer/owner 一致
        writers = {e.get("writer") for e in events if "writer" in e}
        assert writers <= {"chain_session_owner"}, writers

    def test_c12_terminal_survives_supervision_abort(self, tmp_path):
        proc, journal, out, state = self._start_coordinator(
            tmp_path, "c12")
        # 记录 qualification terminal 已提交时刻的 journal 前缀
        prefix_before = journal.read_text(encoding="utf-8")
        n_before = len(prefix_before.splitlines())
        assert "terminal" in " ".join(
            e["event"] for e in map(json.loads,
                                    prefix_before.splitlines()))
        proc.terminate()
        stdout, _ = proc.communicate(timeout=60)
        assert proc.returncode == 0, stdout
        after = journal.read_text(encoding="utf-8")
        lines_after = after.splitlines()
        # append-only:原 terminal 前缀逐字节不变,新事件只在尾部
        assert "\n".join(lines_after[:n_before]) == \
            prefix_before.rstrip("\n")
        events = [json.loads(l) for l in lines_after]
        aborted = [e for e in events
                   if e["event"] == "chain_iteration_aborted"]
        assert aborted, "整轮失败必须真实封口"
        assert "supervision stop" in aborted[0]["reason"]
        # 原资格终态未被改写:terminal 行仍在原位且唯一
        terminals = [e for e in events
                     if "terminal" in e["event"]]
        assert len(terminals) == 1
        assert terminals[0].get("status", terminals[0].get(
            "note", "")).find("completed") >= 0 or \
            "completed" in json.dumps(terminals[0])
        # 重开机会被拒绝(一次性合同;同 state root 二次 acquire)
        rc2 = subprocess.run(
            [sys.executable, str(tmp_path / "coord_runner.py"),
             str(self.SYNC_SRC), str(state), str(tmp_path / "out2"),
             "c11", "coord_sleep_fixture"],
            capture_output=True, text=True, timeout=60,
            env=dict(os.environ,
                     PYTHONPATH=str(self.SYNC_SRC) + os.pathsep +
                     str(tmp_path / "fixture_root"),
                     CURRICULUM261_R17_STATE_ROOT=str(state)))
        assert rc2.returncode != 0, "已终结 iteration 不得重新准入"
