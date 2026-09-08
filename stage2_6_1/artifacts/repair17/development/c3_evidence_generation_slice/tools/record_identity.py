#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 证据轮:执行身份清单(实际 import 来源+SHA-256)。"""
import hashlib
import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")

MODS = [
    "rl_curriculum.curriculum261_api",
    "rl_curriculum.curriculum261_c3",
    "rl_curriculum.curriculum261_pairs",
    "rl_curriculum.curriculum261_generation_envelope",
    "rl_curriculum.curriculum261_qualification",
    "rl_curriculum.curriculum261_production_obs",
    "rl_curriculum.evaluator",
    "rl_curriculum.generator_api",
]

out = {"format": "r17-c3-evidence-identity-v1",
       "python": sys.version,
       "platform": platform.platform(),
       "modules": {}}
for name in MODS:
    mod = __import__(name, fromlist=["x"])
    p = Path(mod.__file__).resolve()
    out["modules"][name] = {
        "file": str(p),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "size": p.stat().st_size}
for extra_name, extra_path in (
    ("runner.r17_c3_p52_diagnosis",
     "/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/"
     "r17_c3_p52_diagnosis.py"),
    ("runner.r17_c3_engineering_slice",
     "/home/cryptorl/projects/crypto_rl/stage2_6_1_runner/"
     "r17_c3_engineering_slice.py"),
):
    p = Path(extra_path)
    out["modules"][extra_name] = {
        "file": str(p),
        "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
        "size": p.stat().st_size}

dst = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/"
           "repair17/development/c3_evidence_generation_slice/"
           "c3_evidence/execution_identity.json")
dst.parent.mkdir(parents=True, exist_ok=True)
dst.write_text(json.dumps(out, ensure_ascii=False, indent=1),
               encoding="utf-8")
print(f"written: {dst}")
for k, v in out["modules"].items():
    print(f"{k}: {v['sha256'][:16]}... {v['file']}")
