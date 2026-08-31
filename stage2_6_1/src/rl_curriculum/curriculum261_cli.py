"""阶段 2.6.1 CLI:calibrate / lock-plan / qualify / smoke / integrity。

用法(WSL,激活 conda env 后):
  python -m rl_curriculum.curriculum261_cli calibrate [--pairs 10]
  python -m rl_curriculum.curriculum261_cli lock-plan --baseline <sha>
  python -m rl_curriculum.curriculum261_cli qualify
  python -m rl_curriculum.curriculum261_cli smoke
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

DEFAULT_ART = Path.home() / "projects" / "crypto_rl" / "artifacts" / \
    "route_c_stage2_6_1_repair2"
VENDOR = Path.home() / "projects" / "crypto_rl" / "vendor" / "freqtrade"

#: 基线 commit(阶段任务书确认的 2.6.0j HEAD)
BASELINE_COMMIT = "a9fff65c01910e254564d7c96059a87fe56894a8"
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
        # repair R2 Layer A:calibration_r2 + holdout_r2 + stress +
        # C2 双诊断 + namespace integrity + robustness gate(v2 八条件);
        # gate FAIL -> 非零退出,不生成 plan,qualification_r2 保持封闭
        from rl_curriculum.curriculum261_qualification import (
            calibration_robustness_gate,
            run_c2_diagnostics,
            run_calibration,
            run_calibration_holdout,
            run_generator_stress,
            seed_namespace_integrity_report,
        )
        main_summary = run_calibration(
            pairs_per_rung=args.pairs, out_dir=out)
        holdout_summary = run_calibration_holdout(
            pairs_per_rung=args.pairs, out_dir=out)
        stress = run_generator_stress(pairs_per_rung=12, out_dir=out)
        c2_diag = run_c2_diagnostics(
            pairs_per_rung=args.pairs, out_dir=out)
        ns_integrity = seed_namespace_integrity_report()
        (out / "seed_namespace_integrity.json").write_text(
            json.dumps(ns_integrity, indent=2, ensure_ascii=False),
            encoding="utf-8")
        gate = calibration_robustness_gate(
            main_summary, holdout_summary,
            stress=stress, c2_diagnostics=c2_diag)
        gate["seed_namespace_integrity_pass"] = ns_integrity["pass"]
        gate["pass"] = bool(gate["pass"] and ns_integrity["pass"])
        (out / "robustness_gate.json").write_text(
            json.dumps(gate, indent=2, ensure_ascii=False, default=float),
            encoding="utf-8")
        print(json.dumps({
            "command": "calibrate",
            "robustness_gate_pass": gate["pass"],
            "families_gate": {f: gate["families"][f]["pass"]
                              for f in gate["families"]},
            "seed_namespace_integrity": ns_integrity["pass"],
            "ladders": {f: main_summary["families"][f][
                "difficulty_metric_ladder"]
                for f in main_summary["families"]}},
            indent=2, ensure_ascii=False))
        return 0 if gate["pass"] else 1

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
        # repair R2 Layer B:gate FAIL / 缺失 -> 拒绝 lock(非零退出)
        gate_path = out / "robustness_gate.json"
        if not gate_path.is_file():
            print(json.dumps({
                "command": "lock-plan", "error": "robustness_gate.json "
                "不存在——必须先 calibrate 且 gate PASS 才能锁定 plan"},
                ensure_ascii=False))
            return 1
        robustness_gate = json.loads(
            gate_path.read_text(encoding="utf-8"))
        if robustness_gate.get("pass") is not True:
            print(json.dumps({
                "command": "lock-plan",
                "error": "robustness gate FAIL,禁止锁定 qualification "
                         "plan(repair R2 硬合同)",
                "gate_pass": robustness_gate.get("pass")},
                ensure_ascii=False))
            return 1
        gate_digest = hashlib.sha256(
            gate_path.read_bytes()).hexdigest()
        main_path = out / "calibration_summary.json"
        hold_path = out / "calibration_holdout_summary.json"
        calibration_evidence = {
            "calibration_summary": json.loads(
                main_path.read_text(encoding="utf-8"))
            if main_path.is_file() else None,
            "calibration_holdout_summary": json.loads(
                hold_path.read_text(encoding="utf-8"))
            if hold_path.is_file() else None,
        }
        plan = build_plan(baseline_commit=args.baseline,
                          vendor_pin=VENDOR_PIN, frozen_contracts=frozen,
                          pairs_per_rung=args.pairs,
                          calibration_evidence=calibration_evidence,
                          robustness_gate=robustness_gate,
                          gate_artifact_digest=gate_digest)
        digest = lock_plan(plan, out)
        print(json.dumps({"command": "lock-plan", "digest": digest,
                          "out": str(out),
                          "robustness_gate_digest": gate_digest},
                         ensure_ascii=False))
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
