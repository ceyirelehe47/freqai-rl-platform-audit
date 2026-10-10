# -*- coding: utf-8 -*-
"""Extra scenarios vs upstream 17-row matrix (existing domain)."""
import json
import subprocess
import sys
from pathlib import Path

BASE = Path("/home/cryptorl/tmp_fr2_review/fr2_dom")
OUT = Path("/mnt/f/trading/local/fr2_review/fr2_extra_results.json")
R11 = "stage2_6_1/artifacts/repair11"
R13 = "stage2_6_1/artifacts/repair13"
pin = BASE / "release_pin"
project = BASE / "project"
sys.path.insert(0, str(project / "src"))
import rl_curriculum.curriculum261_qaf_provenance_guard as guard  # noqa

guard_head = subprocess.run(
    ["git", "rev-parse", "HEAD"], cwd=str(pin), capture_output=True,
    text=True).stdout.strip()

results = []


def preflight():
    saved = guard.R17_PIN_EXPECTED_ROOT
    guard.R17_PIN_EXPECTED_ROOT = str(pin)
    try:
        return guard.runtime_dependency_preflight(
            repo=pin, project_dir=project, candidate_sha=guard_head)
    finally:
        guard.R17_PIN_EXPECTED_ROOT = saved


def scenario(name, rel, mode):
    f = pin / rel
    data = f.read_bytes()
    if mode == "delete":
        f.unlink()
    elif mode == "append":
        f.write_bytes(data + b"\n")
    try:
        rd = preflight()
        probs = " | ".join(str(x) for x in (rd.get("problems") or []))
        bs = rd.get("bind_states") or {}
        exp = "r11" if rel.startswith(R11) else "r13"
        rec = {
            "name": name, "refused": rd.get("ok") is False,
            "bind_states": bs,
            "target_false": bs.get(exp) is False,
            "others_true": all(v is True for k, v in bs.items()
                               if k != exp),
            "historical_bindings": "historical_bindings" in probs,
            "no_other_markers": not any(m in probs for m in (
                "vendor_static", "historical_digests", "branch_lineage")),
            "head_is_A": rd.get("repo_head_commit") == guard_head,
        }
        rec["pass"] = all(rec[k] is True for k in (
            "refused", "target_false", "others_true",
            "historical_bindings", "no_other_markers", "head_is_A"))
        results.append(rec)
        print(("PASS " if rec["pass"] else "FAIL ") + name)
        if not rec["pass"]:
            print(json.dumps(rec, ensure_ascii=False)[:500])
    finally:
        f.write_bytes(data)


scenario("r13_result_file_missing",
         R13 + "/qualification_result.json", "delete")
scenario("r13_abort_marker_bytes_changed",
         R13 + "/r13_iteration_aborted.json", "append")
scenario("r11_abort_marker_missing",
         R11 + "/r11_iteration_aborted.json", "delete")

rd = preflight()
results.append({"name": "final_restore_ok", "ok": rd.get("ok"),
                "bind_states": rd.get("bind_states"),
                "pass": bool(rd.get("ok")) and all(
                    (rd.get("bind_states") or {}).values())})
print(("PASS " if results[-1]["pass"] else "FAIL ") + "final_restore_ok")

ok = all(r["pass"] for r in results)
OUT.write_text(json.dumps({"verdict": "ALL_PASS" if ok else "HAS_FAILURE",
                           "results": results}, ensure_ascii=False,
                          indent=1), encoding="utf-8")
print("VERDICT " + ("ALL_PASS" if ok else "HAS_FAILURE"))
