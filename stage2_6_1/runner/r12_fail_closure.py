# -*- coding: utf-8 -*-
"""R12 FAIL 收尾:失败证据固化 + fail_path_cleanliness(Commit B 素材)。"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, "src")

ART = Path("artifacts/route_c_stage2_6_1_repair12")

# ---- 1. 原始失败 traceback 固化(机械;来自 /tmp/lockplan_out.txt)----
traceback_path = Path("/tmp/lockplan_out.txt")
if not traceback_path.is_file():
    traceback_path = Path("lockplan_out.txt")
traceback_text = traceback_path.read_text(encoding="utf-8")
if "KeyError: 'bundle_hash'" not in traceback_text:
    raise RuntimeError("traceback 不含预期失败(fail closed)")
failure_evidence = {
    "format": "cur261-r12-failure-evidence-v1",
    "phase": "lock-plan(qualification plan lock)",
    "command": "python -m rl_curriculum.curriculum261_r12_cli lock-plan",
    "exception_type": "KeyError",
    "exception_value": "'bundle_hash'",
    "failing_frame": "curriculum261_r12_cli.py:1717 in cmd_lock_plan",
    "actual_key_in_artifact": "preprocessor_bundle_hash",
    "artifact": "preprocessor_bundle_calibration.json",
    "traceback_sha256": hashlib.sha256(
        traceback_text.encode("utf-8")).hexdigest(),
    "traceback": traceback_text,
}
(ART / "lock_plan_failure_traceback.json").write_text(json.dumps(
    failure_evidence, indent=2, ensure_ascii=False), encoding="utf-8")
print("failure evidence written")

# ---- 2. fail_path_cleanliness(冻结代码的机械 writer)----
from rl_curriculum.curriculum261_r12_cli import write_path_cleanliness_r12

p = write_path_cleanliness_r12(ART, verdict="FAIL")
print("cleanliness written:", p.name)
doc = json.loads(p.read_text(encoding="utf-8"))
print("source_changed_after_freeze:",
      doc["source_changed_after_freeze"])
print("exposure_state:", doc["exposure_state"])
