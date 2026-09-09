#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旧 reader(接手版 dfb36445)缺陷实证:I02/I03/P01。
在 WSL 部署树运行;只操作隔离副本,不改任何原件。"""
import json, shutil, subprocess, sys, hashlib
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
from rl_curriculum.curriculum261_generation_envelope import (
    stable_digest, _digest_body, ENVELOPE_DIGEST_PREFIX)

BASE = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development")
ES = BASE / "c3_evidence_generation_slice" / "engineering_slice"
P52_ENV = BASE / "blocker_diagnosis" / "runs" / "20260906T134324Z_1475" / \
    "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"
READER = "/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_c3_engineering_slice.py"
WORK = Path("/home/cryptorl/tmp_r17irac_ce")
OUT = BASE / "c3_identity_receipt_archive_closure" / "counterexamples"

def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()

def fresh_copy(name):
    d = WORK / name
    if d.exists(): shutil.rmtree(d)
    shutil.copytree(ES, d)
    return d

def fix_index_digest(case, new_sha):
    """重写 slice_results.jsonl 首行 detail_sha256(其余行不变)。"""
    p = case / "slice_results.jsonl"
    lines = p.read_text(encoding="utf-8").splitlines()
    row = json.loads(lines[0])
    assert row["detail"] == "D0_p0.json"
    row["detail_sha256"] = new_sha
    lines[0] = json.dumps(row, ensure_ascii=False)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")

def run_reader(case, report):
    r = subprocess.run(
        [sys.executable, READER, "--readback", str(case),
         "--p52-envelope", str(P52_ENV), "--report", str(report)],
        capture_output=True, text=True, timeout=300)
    return {"rc": r.returncode, "stdout_tail": r.stdout.strip().splitlines()[-3:],
            "stderr_tail": r.stderr.strip().splitlines()[-3:]}

results = {}

# ---------- I02:三下游一起改,selected envelope 不动 ----------
c2 = fresh_copy("i02")
d = json.loads((c2 / "pairs" / "D0_p0.json").read_text(encoding="utf-8"))
new_h = {s: "ce-" + hashlib.sha256(f"i02-{s}".encode()).hexdigest()
         for s in ("A", "B")}
d["episode_hashes"] = dict(new_h)
d["pair_record"]["attempt_log"]["output_episode_hashes"] = dict(new_h)
for ep in d["evaluation"]["episodes"]:
    ep["episode_hash"] = new_h[ep["side"]]
(c2 / "pairs" / "D0_p0.json").write_text(
    json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
fix_index_digest(c2, sha(c2 / "pairs" / "D0_p0.json"))
rep2 = WORK / "receipts" / "i02_report.json"
rep2.parent.mkdir(parents=True, exist_ok=True)
results["I02"] = {
    "scenario": "三下游(top/log/eval)同 side 一起改为一致新哈希;"
                "selected envelope 输出不动;外层 detail_sha256 已更新",
    "old_reader": run_reader(c2, rep2),
    "expected_after_fix": "FAIL(selected_envelope_output_binding)",
}

# ---------- I03:selected envelope 输出改+digest 正确重算;下游不动 ----------
c3 = fresh_copy("i03")
d = json.loads((c3 / "pairs" / "D0_p0.json").read_text(encoding="utf-8"))
env = d["attempt_envelopes"][0]
env["event_table"]["A"]["episode_content_hash"] = (
    "ce-" + hashlib.sha256(b"i03-tampered-A").hexdigest())
env["digest"] = stable_digest(_digest_body(env), ENVELOPE_DIGEST_PREFIX)
(c3 / "pairs" / "D0_p0.json").write_text(
    json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
fix_index_digest(c3, sha(c3 / "pairs" / "D0_p0.json"))
rep3 = WORK / "receipts" / "i03_report.json"
results["I03"] = {
    "scenario": "selected envelope A 侧 episode_content_hash 改动并按权威"
                "合同重算 envelope digest;三下游保留原值;detail_sha256 已更新",
    "old_reader": run_reader(c3, rep3),
    "digest_recomputed_correctly": True,
    "expected_after_fix": "FAIL(selected_envelope_output_binding)",
}

# ---------- P01:--report 指向源内历史回执 ----------
c4 = fresh_copy("p01")
hist = c4 / "readback_report.json"
assert hist.is_file(), "历史回执应在副本内"
before_sha, before_size = sha(hist), hist.stat().st_size
r4 = run_reader(c4, hist)  # 直接指向历史回执
after_sha = sha(hist)
doc = json.loads(hist.read_text(encoding="utf-8"))
results["P01"] = {
    "scenario": "--report 指向源目录内历史 readback_report.json",
    "before_sha256": before_sha, "after_sha256": after_sha,
    "overwritten": before_sha != after_sha,
    "new_file_format": doc.get("format"),
    "snapshot_claimed_identical": doc.get("checks", {}).get(
        "source_snapshot_identical"),
    "old_reader": r4,
    "expected_after_fix": "写前拒绝(零源写入,非零退出)",
}

# ---------- 健康对照(同批运行,证明副本环境本身无问题) ----------
c1 = fresh_copy("health_control")
rep1 = WORK / "receipts" / "health_report.json"
results["health_control"] = {"old_reader": run_reader(c1, rep1)}

OUT.mkdir(parents=True, exist_ok=True)
(OUT / "old_reader_counterexamples.json").write_text(
    json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(results, ensure_ascii=False, indent=1))
