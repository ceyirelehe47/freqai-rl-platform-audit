# -*- coding: utf-8 -*-
"""R17 独立冷读(C01-C04):完整必要字节新根复制+原根不可访问验证
+缺件/篡改负例(任务书 WP3 的可夹具化项)。

真实链路:真 run 产出 run_record → r17_verify_delivery build 生成
固定清单/锚 → build_cold_copy 物理复制 → unshare 隔离进程内仅用
新根核验(原根 /mnt/f 对验证进程不可访问)。负例只在一次性副本;
原件不动、不回退、不重建清单。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest


def _find_runner_dir() -> Path:
    here = Path(__file__).resolve()
    for cand in (
            here.parents[3] / "stage2_6_1" / "runner",
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"),
            Path.home() / "projects/crypto_rl/stage2_6_1_runner",
    ):
        if (cand / "r17_supervision.py").is_file():
            return cand
    raise FileNotFoundError("runner 执行面不可达")


def _find_tools_dir() -> Path:
    here = Path(__file__).resolve()
    for cand in (
            here.parents[3] / "stage2_6_1" / "artifacts" / "repair17"
            / "development" / "unified_shutdown_cold_read" / "tools",
            Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
                 "repair17/development/unified_shutdown_cold_read/tools"),
    ):
        if (cand / "build_cold_copy.py").is_file():
            return cand
    pytest.skip("冷读工具目录不可达(发布树布局)")


RUNNER_DIR = _find_runner_dir()
TOOLS_DIR = _find_tools_dir()
sys.path.insert(0, str(RUNNER_DIR))

from r17_supervision import Supervisor  # noqa: E402

requires_linux = pytest.mark.skipif(
    os.name == "nt", reason="冷读执行面只在 Linux/WSL 跑")


def _sha(p: Path) -> str:
    h = hashlib.sha256()
    h.update(Path(p).read_bytes())
    return h.hexdigest()


@pytest.fixture(scope="module")
def tiny_delivery(tmp_path_factory):
    """真实最小交付:干净 run + 固定清单/锚 + 冷读副本(家目录)。"""
    tmp = tmp_path_factory.mktemp("coldcopy")
    samples = tmp / "samples.jsonl"
    utc = _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")
    win = {"event": "sample", "seq": 1, "utc": utc,
           "perf": {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
                    "commit_limit_gb": 83.0, "phys_total_gb": 63.0},
           "vols": [
               {"vol": "F:", "present": True, "free_gb": 100.0,
                "size_gb": 500.0, "serial": "CFA1",
                "identity_match": True},
               {"vol": "C:", "present": True, "free_gb": 200.0,
                "size_gb": 900.0, "serial": "CCA1",
                "identity_match": True}],
           "telemetry_out_writable": True}
    guest = {"event": "guest_sample", "utc": utc,
             "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
             "psi_memory": {"full_avg10": 0.0},
             "vmstat_swap": {"pswpout": 0}}
    with samples.open("w", encoding="utf-8") as fh:
        for _ in range(20):
            fh.write(json.dumps({"win": win, "guest": guest}) + "\n")
    args = argparse.Namespace(
        run_dir=str(tmp / "runsup" / "runs" / "tinyrun"),
        task_kind="fixture", argv=["true"], task_cwd=None,
        max_seconds=0, samples_source="file:" + str(samples),
        win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
        expect_artifact=[], obs_ready_deadline=30.0)
    sup = Supervisor(args)
    assert sup.run() == 0, "干净 run 是冷读夹具前置"
    rr = tmp / "runsup" / "runs" / "tinyrun" / "run_record.json"
    rec = json.loads(rr.read_text(encoding="utf-8"))
    assert rec["evidence_complete"] is True
    root = tmp / "runsup"
    manifest = tmp / "delivery_manifest_v2.jsonl"
    anchor = tmp / "final.anchor.json"
    b = subprocess.run(
        [sys.executable, str(RUNNER_DIR / "r17_verify_delivery.py"),
         "build", "--run-record", str(rr),
         "--manifest-out", str(manifest), "--anchor-out", str(anchor),
         "--root", str(root)],
        capture_output=True, text=True, timeout=60)
    assert b.returncode == 0, b.stderr[-400:]
    # 副本必须在家目录(/mnt 之外——隔离时 tmpdir 也可能落在 /tmp
    # 下不被遮蔽,这里显式建到家目录保证与工具的隔离模型一致)
    copy_root = Path.home() / f"r17u_test_coldcopy_{os.getpid()}"
    if copy_root.exists():
        shutil.rmtree(copy_root)
    c = subprocess.run(
        [sys.executable, str(TOOLS_DIR / "build_cold_copy.py"),
         "--source-root", str(root), "--manifest", str(manifest),
         "--anchor", str(anchor),
         "--record-rel", "runs/tinyrun/run_record.json",
         "--verifier", str(RUNNER_DIR / "r17_verify_delivery.py"),
         "--dest", str(copy_root)],
        capture_output=True, text=True, timeout=120)
    assert c.returncode == 0, c.stderr[-400:]
    yield {"tmp": tmp, "root": root, "manifest": manifest,
           "anchor": anchor, "copy_root": copy_root,
           "receipts": tmp / "receipts"}
    shutil.rmtree(copy_root, ignore_errors=True)


def _isolated_verify(copy_root: Path, receipts: Path) -> dict:
    """跑隔离冷读工具;返回 cold_read 回执 json。"""
    receipts.mkdir(parents=True, exist_ok=True)
    p = subprocess.run(
        ["bash", str(TOOLS_DIR / "cold_read_isolated.sh"),
         str(copy_root), str(receipts)],
        capture_output=True, text=True, timeout=180)
    outs = sorted(receipts.glob("cold_read_*.json"))
    assert outs, f"无回执;rc={p.returncode} {p.stdout[-300:]}"
    return json.loads(outs[-1].read_text(encoding="utf-8"))


@requires_linux
class TestColdCopy:
    def test_c01_full_payload_bytes_copied(self, tiny_delivery):
        """C01:从固定清单复制完整 payload/metadata/verifier——字节
        与相对路径逐项一致;不扫描现存文件缩小集合。"""
        d = tiny_delivery
        rows = [json.loads(l) for l in
                d["manifest"].read_text(encoding="utf-8").splitlines() if l]
        assert len(rows) >= 5, "必要角色集合(双遥测/alerts/业务流/"
        "summary/record)不因测试缩小"
        for row in rows:
            t = d["copy_root"] / "payload" / row["path"]
            s = d["root"] / row["path"]
            assert t.is_file() and not t.is_symlink(), \
                f"物理字节文件(非链接): {row['path']}"
            assert t.stat().st_size == row["bytes"]
            assert _sha(t) == row["sha256"] == _sha(s)
        cm = json.loads((d["copy_root"] / "metadata" /
                         "copy_manifest.json").read_text(encoding="utf-8"))
        assert cm["files_copied"] == len(rows)
        assert (d["copy_root"] / "verifier" /
                "r17_verify_delivery.py").is_file()

    def test_c02_isolated_cold_read_passes(self, tiny_delivery):
        """C02:原根对验证进程不可访问(unshare+tmpfs)的真实冷读——
        只读新根核验通过;回执含隔离事实/argv/只读不变。"""
        rec = _isolated_verify(tiny_delivery["copy_root"],
                               tiny_delivery["receipts"])
        assert rec["verify_rc"] == 0
        assert rec["payload_readonly_unchanged"] is True
        assert rec["isolation"]["original_root_visible"] == "no", \
            "原根必须不可访问(仅换 cwd/清 PYTHONPATH 不算)"
        assert rec["rc"] == 0

    def test_c03_missing_file_fails_no_fallback(self, tiny_delivery):
        """C03:新根缺一件而原根仍有该文件——隔离验证必须失败,
        不回读原根/不重算/不重建清单。"""
        d = tiny_delivery
        neg = Path.home() / f"r17u_test_negmiss_{os.getpid()}"
        shutil.rmtree(neg, ignore_errors=True)
        shutil.copytree(d["copy_root"], neg)
        try:
            victim = sorted((neg / "payload").rglob("*"))
            v = [p for p in victim if p.is_file()][0]
            rel = v.relative_to(neg / "payload")
            v.unlink()
            assert (d["root"] / rel).is_file(), \
                "对照前提:原根该文件仍存在"
            receipts = d["tmp"] / "receipts_c03"
            receipts.mkdir(exist_ok=True)
            out = sorted(receipts.glob("cold_read_*.json"))
            for o in out:
                o.unlink()
            p = subprocess.run(
                ["bash", str(TOOLS_DIR / "cold_read_isolated.sh"),
                 str(neg), str(receipts)],
                capture_output=True, text=True, timeout=180)
            assert p.returncode != 0, "缺件副本不得通过"
        finally:
            shutil.rmtree(neg, ignore_errors=True)

    def test_c04_tamper_detected_original_untouched(
            self, tiny_delivery):
        """C04:副本内文件篡改一字节——按固定清单检出失败;原件与
        正副本字节不变(负例只在一次性副本)。"""
        d = tiny_delivery
        before = {p.relative_to(d["copy_root"]): _sha(p)
                  for p in (d["copy_root"] / "payload").rglob("*")
                  if p.is_file()}
        neg = Path.home() / f"r17u_test_negtamper_{os.getpid()}"
        shutil.rmtree(neg, ignore_errors=True)
        shutil.copytree(d["copy_root"], neg)
        try:
            files = sorted(p for p in (neg / "payload").rglob("*")
                           if p.is_file())
            files[-1].write_bytes(files[-1].read_bytes() + b"X")
            receipts = d["tmp"] / "receipts_c04"
            receipts.mkdir(exist_ok=True)
            for o in receipts.glob("cold_read_*.json"):
                o.unlink()
            p = subprocess.run(
                ["bash", str(TOOLS_DIR / "cold_read_isolated.sh"),
                 str(neg), str(receipts)],
                capture_output=True, text=True, timeout=180)
            assert p.returncode != 0, "篡改副本不得通过"
            after = {p.relative_to(d["copy_root"]): _sha(p)
                     for p in (d["copy_root"] / "payload").rglob("*")
                     if p.is_file()}
            assert before == after, "正副本(原件对照)字节不变"
        finally:
            shutil.rmtree(neg, ignore_errors=True)
