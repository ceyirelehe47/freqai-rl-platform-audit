# -*- coding: utf-8 -*-
"""R13 rehearsal 诊断:R6 matched block 统计条件(从持久化 block_table)。"""
import json

from rl_curriculum.curriculum261_r6_pairs import c2_matched_conditions

B = ("/home/cryptorl/projects/crypto_rl/artifacts/"
     "route_c_stage2_6_1_repair13/real_artifact_rehearsal/")

for role in ("main", "holdout"):
    bt = json.load(open(B + f"c2_block_evidence_table_{role}.json"))
    result = c2_matched_conditions(bt)
    print(f"{role}: pass={result.get('pass')}")
    if not result.get("pass"):
        def _flat(d, prefix=""):
            for k, v in d.items():
                if isinstance(v, bool) and not v:
                    print(f"    FAIL {prefix}{k}")
                elif isinstance(v, dict):
                    _flat(v, prefix + k + ".")
        _flat(result)
