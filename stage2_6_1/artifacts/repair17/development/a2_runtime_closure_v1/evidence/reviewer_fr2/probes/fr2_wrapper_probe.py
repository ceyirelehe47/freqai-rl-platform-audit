# -*- coding: utf-8 -*-
"""FR2-03 probe: binder wrapper semantics (write/re-raise verbatim,
original exception passthrough) in isolated domain."""
import json
import shutil
import sys
from pathlib import Path

BASE = Path("/home/cryptorl/tmp_fr2_review/fr2_dom")
R11 = "stage2_6_1/artifacts/repair11"
R13 = "stage2_6_1/artifacts/repair13"
WOUT = BASE / "wrapper_out"
if WOUT.exists():
    shutil.rmtree(WOUT)
WOUT.mkdir(parents=True)

pin = BASE / "release_pin"
project = BASE / "project"
sys.path.insert(0, str(project / "src"))
import rl_curriculum.curriculum261_r17_dependencies as dep  # noqa
dep.R17_RELEASE_PIN_ROOT = pin
import rl_curriculum.curriculum261_r17_cli as cli  # noqa

results = {"cases": []}


def resolved():
    for c in dep.release_repo_candidates():
        if c.is_dir():
            return c
    raise RuntimeError("no release repo")


assert str(resolved()) == str(pin), str(resolved())

r11m = pin / R11 / "r11_iteration_aborted.json"
trace = pin / R11 / "cue_event_trace.jsonl"
r13r = pin / R13 / "qualification_result.json"

# A: r11 hard missing -> RuntimeError BEFORE write
saved = r11m.read_bytes()
r11m.unlink()
try:
    d = WOUT / "a"
    d.mkdir()
    try:
        cli._r11_abort_binding(d)
        raised = None
    except Exception as exc:
        raised = exc
    results["cases"].append({
        "name": "r11_hard_missing_raise_before_write",
        "type": type(raised).__name__,
        "msg_head": str(raised)[:60],
        "file_written": (d / "r11_abort_binding.json").exists(),
        "pass": (isinstance(raised, RuntimeError)
                 and "R11 aborted marker 缺失" in str(raised)
                 and not (d / "r11_abort_binding.json").exists())})
finally:
    r11m.write_bytes(saved)

# B: r11 trace missing -> computed binding fail -> write THEN raise
saved = trace.read_bytes()
trace.unlink()
try:
    d = WOUT / "b"
    d.mkdir()
    try:
        cli._r11_abort_binding(d)
        raised = None
    except Exception as exc:
        raised = exc
    results["cases"].append({
        "name": "r11_trace_missing_write_then_raise",
        "type": type(raised).__name__,
        "msg_head": str(raised)[:60],
        "file_written": (d / "r11_abort_binding.json").exists(),
        "pass": (isinstance(raised, RuntimeError)
                 and str(raised).startswith(
                     "R11 abort binding 验证失败(fail closed)")
                 and (d / "r11_abort_binding.json").exists())})
finally:
    trace.write_bytes(saved)

# C: r13 result corrupt JSON -> original JSONDecodeError passthrough
saved = r13r.read_bytes()
r13r.write_bytes(b'{"broken": tru')
try:
    d = WOUT / "c"
    d.mkdir()
    try:
        cli._r13_failure_binding(d)
        raised = None
    except Exception as exc:
        raised = exc
    results["cases"].append({
        "name": "r13_corrupt_json_original_type_passthrough",
        "type": type(raised).__name__,
        "file_written": (d / "r13_iteration_failure_binding.json").exists(),
        "pass": (isinstance(raised, json.JSONDecodeError)
                 and not (d / "r13_iteration_failure_binding.json").exists())})
finally:
    r13r.write_bytes(saved)

# D: r13 tampered valid -> write THEN fail-closed raise
saved = r13r.read_bytes()
obj = json.loads(r13r.read_text(encoding="utf-8"))
obj["fr2_wrapper_tamper"] = True
r13r.write_text(json.dumps(obj, ensure_ascii=False, indent=1) + "\n",
                encoding="utf-8")
try:
    d = WOUT / "d"
    d.mkdir()
    try:
        cli._r13_failure_binding(d)
        raised = None
    except Exception as exc:
        raised = exc
    results["cases"].append({
        "name": "r13_tampered_write_then_raise",
        "type": type(raised).__name__,
        "msg_head": str(raised)[:60],
        "file_written": (d / "r13_iteration_failure_binding.json").exists(),
        "pass": (isinstance(raised, RuntimeError)
                 and str(raised).startswith(
                     "R13 failure binding 验证失败(fail closed)")
                 and (d / "r13_iteration_failure_binding.json").exists())})
finally:
    r13r.write_bytes(saved)

# E: healthy domain -> binder writes and returns pass=True
d = WOUT / "e"
d.mkdir()
b = cli._r13_failure_binding(d)
results["cases"].append({
    "name": "r13_healthy_pass_write",
    "pass_state": b.get("pass"),
    "file_written": (d / "r13_iteration_failure_binding.json").exists(),
    "pass": (b.get("pass") is True
             and (d / "r13_iteration_failure_binding.json").exists())})

ok = all(c["pass"] for c in results["cases"])
results["verdict"] = "ALL_PASS" if ok else "HAS_FAILURE"
(Path("/mnt/f/trading/local/fr2_review") / "fr2_wrapper_probe_results.json"
 ).write_text(json.dumps(results, ensure_ascii=False, indent=1),
              encoding="utf-8")
for c in results["cases"]:
    print(("PASS " if c["pass"] else "FAIL ") + c["name"])
    if not c["pass"]:
        print(json.dumps(c, ensure_ascii=False)[:600])
print("VERDICT " + results["verdict"])
