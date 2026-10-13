#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 题目有效性门(prequal;参考三级细化+基线回放+探针)。

用法:
    python psc_p0_prequal.py [--ledger <jsonl>] [--banks-dir <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.runlog import RunLog  # noqa: E402
from rl_posctl.skill_p0.p0banks import load_p0_bank  # noqa: E402
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, open_ledger)
from rl_posctl.skill_p0.p0task import (  # noqa: E402
    counterfactual_probes, mirror_probe, task_validity_gate)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--banks-dir", default=str(RUNS_DIR / "banks"))
    args = ap.parse_args()
    bank = Path(args.banks_dir) / "prequal" / "prequal_bank.json"
    if not bank.exists():
        print(f"缺少 prequal bank:{bank}", file=sys.stderr)
        return 2
    out_root = RUNS_DIR / "prequal"
    if (out_root / "task_gate.json").exists():
        print(f"已有 task_gate.json(create-only):{out_root}",
              file=sys.stderr)
        return 2
    ledger = open_ledger(args.ledger)
    items = load_p0_bank(bank)
    with RunLog(out_root, meta_extra={
            "runner": "psc_p0_prequal"}):
        gate = task_validity_gate(items, ledger=ledger)
        probes = {"counterfactual": counterfactual_probes(items[0]),
                  "counterfactual_mid": counterfactual_probes(
                      items[7], t_check=32),
                  "mirror": mirror_probe(items[0], items[1])}
        gate["probes"] = probes
        gate["gate_status_with_probes"] = (
            gate["gate_status"] if all(
                v.get("pass", True) for v in probes.values())
            else "NOT_ESTABLISHED")
        ev = evidence_kib_settle(ledger, tag="prequal")
        gate["evidence_kib"] = ev
        (out_root / "task_gate.json").write_text(
            json.dumps(gate, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps({"gate_status": gate["gate_status"],
                          "value64": gate.get("value64"),
                          "advantage": gate.get(
                              "reference_advantage_vs_best"),
                          "probes": probes},
                         ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
