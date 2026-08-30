"""阶段 2.6.1 CLI:calibrate / lock-plan / qualify / smoke / integrity。

用法(WSL,激活 conda env 后):
  python -m rl_curriculum.curriculum261_cli calibrate [--pairs 10]
  python -m rl_curriculum.curriculum261_cli lock-plan --baseline <sha>
  python -m rl_curriculum.curriculum261_cli qualify
  python -m rl_curriculum.curriculum261_cli smoke
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_ART = Path.home() / "projects" / "crypto_rl" / "artifacts" / \
    "route_c_stage2_6_1"
VENDOR = Path.home() / "projects" / "crypto_rl" / "vendor" / "freqtrade"

#: 基线 commit(阶段任务书确认的 2.6.0j HEAD)
BASELINE_COMMIT = "cd585f4acff6170a2b592d11418066b0c0714b02"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"


def main() -> int:
    ap = argparse.ArgumentParser(prog="curriculum261")
    ap.add_argument("command", choices=["calibrate", "lock-plan", "qualify",
                                        "smoke"])
    ap.add_argument("--out", default=str(DEFAULT_ART))
    ap.add_argument("--pairs", type=int, default=10)
    ap.add_argument("--baseline", default=BASELINE_COMMIT)
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.command == "calibrate":
        from rl_curriculum.curriculum261_qualification import run_calibration
        summary = run_calibration(pairs_per_rung=args.pairs, out_dir=out)
        ok = all(
            summary["families"][f]["ordering_ok"]
            and summary["families"][f]["d3_metric_positive"]
            and summary["families"][f]["reference_beats_required_all_rungs"]
            for f in summary["families"])
        print(json.dumps({
            "command": "calibrate", "all_families_ok": ok,
            "ladders": {f: summary["families"][f]["difficulty_metric_ladder"]
                        for f in summary["families"]}},
            indent=2, ensure_ascii=False))
        return 0 if ok else 1

    if args.command == "lock-plan":
        from rl_curriculum.curriculum261_plan import build_plan, lock_plan
        frozen = {
            "env_core": "RouteCEnvCore-v1.0.0",
            "observation_spec": "ObservationSpec-v1",
            "action_spec": "BinaryLongFlatAction-v1",
            "reward_spec": "NetLogEquityReward-v1",
            "execution": "MarketOpenCausalExecution-v1",
            "terminal_liquidation": "TerminalLiquidation-v1",
        }
        plan = build_plan(baseline_commit=args.baseline,
                          vendor_pin=VENDOR_PIN, frozen_contracts=frozen,
                          pairs_per_rung=args.pairs)
        digest = lock_plan(plan, out)
        print(json.dumps({"command": "lock-plan", "digest": digest,
                          "out": str(out)}, ensure_ascii=False))
        return 0

    if args.command == "qualify":
        from rl_curriculum.curriculum261_final import \
            run_final_qualification
        result = run_final_qualification(plan_dir=out, out_dir=out,
                                         vendor_dir=VENDOR)
        print(json.dumps({
            "command": "qualify",
            "verdict": result["verdict"],
            "checks": result["checks"],
            "n_pairs_total": result["n_pairs_total"],
            "ladders": {f: result["families"][f]["difficulty_metric_ladder"]
                        for f in result["families"]}},
            indent=2, ensure_ascii=False))
        return 0 if result["verdict"] == "PASS" else 1

    if args.command == "smoke":
        from rl_curriculum.curriculum261_smoke import run_ppo_smoke
        result = run_ppo_smoke(out_dir=out)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0 if result["pass"] else 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
