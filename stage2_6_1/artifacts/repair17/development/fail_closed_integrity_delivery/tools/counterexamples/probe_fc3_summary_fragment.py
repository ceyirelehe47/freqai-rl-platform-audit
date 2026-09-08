# -*- coding: utf-8 -*-
"""反例FC-3(SPSC-02B/WP2-B):summary 部分写入残片被 present/哈希抵消。

接手实现事实假设(待证实):
  1) 真实文件边界注入:summary.json 写出首字节 '{' 后 I/O 失败
     (真实 open+write+flush,不替换 write_summary 函数体);
  2) 残片留在最终路径;_summary_publish_failed=True 仅进
     control_outcome(→6),不进 _evidence_ok;
  3) run_record 中 summary 条目 status=present + 残片哈希;
     evidence_complete=true(残片被当有效已发布角色);
  4) 实际 verifier 只看 missing/live_writers/evidence_complete——
     残片包 verify rc=0(必要发布失败被文件存在抵消)。
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

snap = sys.argv[1]
base = sys.argv[2]
sys.path.insert(0, snap)
from r17_supervision import Supervisor  # noqa: E402

RUNNER = os.path.dirname(os.path.abspath(
    os.path.join(snap, "r17_supervision.py")))
TARGET = os.path.join(base, "run", "summary.json")

import datetime as _dt


def utc_now():
    return _dt.datetime.now(_dt.timezone.utc).isoformat(
        timespec="seconds").replace("+00:00", "Z")


perf = {"phys_avail_gb": 39.0, "commit_total_gb": 38.0,
        "commit_limit_gb": 83.0, "phys_total_gb": 63.0}
vols = [
    {"vol": "F:", "present": True, "free_gb": 100.0,
     "size_gb": 500.0, "serial": "CFA1", "identity_match": True},
    {"vol": "C:", "present": True, "free_gb": 200.0,
     "size_gb": 900.0, "serial": "CCA1", "identity_match": True}]
win = {"event": "sample", "seq": 1, "utc": utc_now(), "perf": perf,
       "vols": vols, "telemetry_out_writable": True}
guest = {"event": "guest_sample", "utc": utc_now(),
         "meminfo": {"MemTotal": 40_000_000, "MemAvailable": 39_000_000},
         "psi_memory": {"full_avg10": 0.0},
         "vmstat_swap": {"pswpout": 0}}
samples_path = os.path.join(base, "samples.jsonl")
with open(samples_path, "w", encoding="utf-8") as fh:
    for _ in range(40):
        fh.write(json.dumps({"win": win, "guest": guest}) + "\n")

# ---- 真实文件边界注入(新发布边界:tmp 写 / os.replace) ----
# stage=tmp_write:私有临时文件写出首字节后 I/O 失败(部分写入形态)
# stage=replace:临时件完整写完后替换失败(发布动作失败形态)
STAGE = "replace"
for a in sys.argv[3:]:
    if a.startswith("--stage="):
        STAGE = a.split("=", 1)[1]
TMP_TARGET = os.path.join(base, "run", ".summary.json.tmp")
FINAL_TARGET = os.path.join(base, "run", "summary.json")
_orig_write_text = pathlib.Path.write_text
_orig_replace = pathlib.Path.replace
_orig_open = pathlib.Path.open


def write_text_patched(self, data, *a, **kw):
    # 兼容旧行为对照:直接对最终路径 write_text 的注入点在原子
    # 发布后不再被 write_summary 触达(证明"直接写最终路径"的
    # 故障面已消失);保留分支用于 fixed 行为的负对照
    if os.fspath(self) == FINAL_TARGET and STAGE == "legacy_final":
        with open(FINAL_TARGET, "w", encoding="utf-8") as fh:
            fh.write("{")
            fh.flush()
        raise OSError(5, "Input/output error")
    return _orig_write_text(self, data, *a, **kw)


def open_patched(self, *a, **kw):
    if STAGE == "tmp_write" and os.fspath(self) == TMP_TARGET and \
            len(a) >= 1 and "w" in str(a[0]):
        fh = _orig_open(self, *a, **kw)
        orig_write = fh.write

        def write_then_fail(data):
            orig_write(data[:1])
            fh.flush()
            raise OSError(5, "Input/output error")
        fh.write = write_then_fail
        return fh
    return _orig_open(self, *a, **kw)


def replace_patched(self, target, *a, **kw):
    if STAGE == "replace" and os.fspath(self) == TMP_TARGET and \
            os.fspath(target) == FINAL_TARGET:
        raise OSError(1, "Operation not permitted")
    return _orig_replace(self, target, *a, **kw)


pathlib.Path.write_text = write_text_patched
pathlib.Path.open = open_patched
pathlib.Path.replace = replace_patched

args = argparse.Namespace(
    run_dir=os.path.join(base, "run"), task_kind="fixture",
    argv=["bash", "-c", "sleep 1"], task_cwd=None, max_seconds=0,
    samples_source="file:" + samples_path,
    win_sampler_ps1="/nonexistent.ps1", win_volumes="C:,F:",
    expect_artifact=[], obs_ready_deadline=30.0)
sup = Supervisor(args)
rc = sup.run()
pathlib.Path.write_text = _orig_write_text
pathlib.Path.open = _orig_open
pathlib.Path.replace = _orig_replace

print(f"PROBE_STAGE={STAGE}", flush=True)
print(f"PROBE_RUN_RC={rc}", flush=True)
print(f"PROBE_SUMMARY_FAILED_FLAG={sup._summary_publish_failed!r}",
      flush=True)
print(f"PROBE_EVIDENCE_COMPLETE_FLAG={sup._evidence_complete!r}",
      flush=True)
if os.path.exists(TARGET):
    raw = open(TARGET, "rb").read()
    print(f"PROBE_SUMMARY_BYTES={len(raw)}", flush=True)
    print(f"PROBE_SUMMARY_HEAD={raw[:16]!r}", flush=True)
else:
    print("PROBE_SUMMARY_MISSING=True", flush=True)
if os.path.exists(TMP_TARGET):
    raw = open(TMP_TARGET, "rb").read()
    print(f"PROBE_TMP_RESIDUE_BYTES={len(raw)}", flush=True)
    print(f"PROBE_TMP_RESIDUE_HEAD={raw[:16]!r}", flush=True)
rr_p = os.path.join(base, "run", "run_record.json")
if os.path.isfile(rr_p):
    d = json.loads(open(rr_p, encoding="utf-8").read())
    sm = [r for r in d.get("required", [])
          if r.get("role") == "summary"]
    print(f"PROBE_RR_SUMMARY_ENTRY={sm[0] if sm else None}", flush=True)
    print(f"PROBE_RR_EVIDENCE={d.get('evidence_complete')!r}", flush=True)
    print(f"PROBE_RR_MISSING={d.get('missing_roles')!r}", flush=True)
    # 实际 verifier 消费:残片包是否被接受为完整交付
    # root=run_supervision 根(run_record 内 path 相对基准,显式传入)
    SUP_ROOT = os.path.dirname(base)
    man = os.path.join(base, "fc3_manifest.jsonl")
    anchor = os.path.join(base, "fc3_anchor.json")
    vrun = subprocess.run(
        [sys.executable, os.path.join(RUNNER, "r17_verify_delivery.py"),
         "build", "--run-record", rr_p, "--manifest-out", man,
         "--anchor-out", anchor, "--root", SUP_ROOT],
        capture_output=True, text=True, timeout=120)
    print(f"PROBE_BUILD_RC={vrun.returncode}", flush=True)
    if vrun.returncode != 0:
        print("PROBE_BUILD_ERR=" + vrun.stderr.strip()[:300], flush=True)
    else:
        vrun2 = subprocess.run(
            [sys.executable, os.path.join(RUNNER,
                                          "r17_verify_delivery.py"),
             "verify", "--root", SUP_ROOT,
             "--manifest", man, "--anchor-file", anchor,
             "--run-record", rr_p],
            capture_output=True, text=True, timeout=120)
        print(f"PROBE_VERIFY_RC={vrun2.returncode}", flush=True)
        print("PROBE_VERIFY_STDOUT=" + vrun2.stdout.strip()[:300],
              flush=True)
sys.exit(rc if 0 <= rc < 256 else 0)
