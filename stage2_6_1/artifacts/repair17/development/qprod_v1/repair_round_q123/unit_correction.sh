#!/usr/bin/env bash
# Q2 账本单位更正:E01 run1/run2 原账本行保持原样(18=外层 block
# 调用),追加 unit_correction 行给出 episode 叶调用复算
# (1 block 调用=8 episode;含 attempts 重试与 bitwise 完整性重放)。
# 零生成/零 fit/零 optimizer;append-only,不改既有行。
set -euo pipefail
export PYTHONDONTWRITEBYTECODE=1
cd /home/cryptorl/projects/crypto_rl
export PYTHONPATH=src
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python - <<'PYEOF'
import json
from pathlib import Path

ROOT = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts"
            "/repair17/development/qprod_v1")
for run in ("native_smoke_run1", "native_smoke_run2"):
    lp = (ROOT / run / "qprod_level_b_qprod_b_eng_v1" /
          "qprod_quota_ledger.jsonl")
    if not lp.is_file():
        print(f"skip {run}: ledger absent")
        continue
    rows = [json.loads(x) for x in lp.read_text().splitlines() if x]
    if any(r.get("action") == "unit_correction" for r in rows):
        print(f"skip {run}: correction already present (idempotent)")
        continue
    corrections = []
    for r in rows:
        if r.get("action") in ("complete", "interrupted",
                               "quota_exceeded"):
            kinds = r.get("leaf_calls_by_kind") or {}
            block_calls = r.get("leaf_calls_total",
                                sum(kinds.values()))
            corrections.append({
                "action": "unit_correction",
                "corrects_action_of": r.get("action"),
                "coordinate_id": r.get("coordinate_id"),
                "original_row_leaf_calls_total": block_calls,
                "original_unit": "外层 block 调用(once/attempts/"
                                 "bitwise_replay 各计 1)",
                "episode_leaf_calls_recomputed":
                    block_calls * 8,
                "episode_unit_rule": "SCOPE_AND_BUDGET §3:底层候选"
                                     "episode 调用含失败尝试与完整"
                                     "性检查重放;1 block 调用=8 "
                                     "episode(4 rung×A/B)",
                "quota_basis": {"per_execution_max": 320,
                                "total_max": 640},
                "within_budget": block_calls * 8 <= 320,
                "note": "原行保持不变;本行为单位更正与复算"
                        "(不悄悄改账)",
            })
    with open(lp, "a", encoding="utf-8") as fh:
        for c in corrections:
            fh.write(json.dumps(c, ensure_ascii=False,
                                sort_keys=True) + "\n")
    total_ep = sum(c["episode_leaf_calls_recomputed"]
                   for c in corrections)
    print(json.dumps({
        "run": run, "corrected_rows": len(corrections),
        "episode_leaf_calls_total_in_run": total_ep,
        "global_budget": {"two_runs_episode_total_max": 640}},
        ensure_ascii=False))
PYEOF
echo "unit corrections appended"
