#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 行为门重算(修订 D:反事实观察列序修正;零经济步)。

confirm_report.json 的经济评估/基线/bootstrap 不受列序影响(训练与
评估同一 env 布局);仅行为门的反事实构造错列。本 runner 以最终
checkpoint 只读载入、按 env.feature_names([c,g,q,s])重建反事实
网格重算行为门,并把逐 seed/臂级结论合并为 confirm_report_v2.json
(原 report 原样保留)。计量:dist_sample_actions(采样核对≤72/模型)。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch as th

from rl_posctl.runlog import RunLog  # noqa: E402
from rl_posctl.skill_p0.p0banks import load_p0_bank  # noqa: E402
from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv  # noqa: E402
from rl_posctl.skill_p0.p0eval import (  # noqa: E402
    behavior_gate, bootstrap_results_all_valid_positive)
from rl_posctl.skill_p0.p0policy import load_p0_model  # noqa: E402
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, make_sampler_meter, open_ledger)
from rl_posctl.skill_p0.p0spec import ARMS, PPO_SEEDS  # noqa: E402

FINAL_STEP = 131_072


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=None)
    args = ap.parse_args()
    th.set_num_threads(1)
    old_path = RUNS_DIR / "confirm" / "confirm_report.json"
    if not old_path.exists():
        print(f"缺少原报告:{old_path}", file=sys.stderr)
        return 2
    out_path = RUNS_DIR / "confirm" / "confirm_report_v2.json"
    if out_path.exists():
        print(f"已存在:{out_path}", file=sys.stderr)
        return 2
    report = json.loads(old_path.read_text(encoding="utf-8"))
    out_dir = RUNS_DIR / "confirm_v2"
    out_path = out_dir / "confirm_report_v2.json"
    items = load_p0_bank(
        RUNS_DIR / "banks" / "confirm" / "confirm_bank.json")
    env = P0EpisodeBankEnv(items[:1])
    feature_names = list(env._inner.feature_names)   # noqa: SLF001
    print("env feature order:", feature_names)
    ledger = open_ledger(args.ledger)
    meter = make_sampler_meter(ledger, "bgate_v2")
    with RunLog(out_dir,
                meta_extra={"runner": "psc_p0_bgate_v2"}):
        for name in sorted(report["finals"]):
            arm = name.split("_")[0]
            rec = json.loads(Path(
                report["finals"][name]["run_record"]).read_text(
                encoding="utf-8"))
            model = load_p0_model(
                report["finals"][name]["path"], env, arm=arm,
                bank_ref=rec["bank_ref"], horizon=64)
            gate = behavior_gate(
                model, meter=meter, sampled_check=12,
                feature_names=feature_names)
            old = report["per_seed"].get(name, {})
            if old.get("behavior"):
                old["behavior_invalid_order_v1"] = old["behavior"]
            old["behavior"] = gate
            if "seed_gate_pass" in old:
                old["seed_gate_pass"] = bool(
                    gate.get("pass")
                    and old.get("beats_baselines_both_modes"))
            report["per_seed"][name] = old
            print(name, "pass=", gate["pass"],
                  "long_min=", round(gate["long_min"], 3),
                  "short_min=", round(gate["short_min"], 3),
                  "neu_min=", round(gate["neutral_min"], 3))
        for arm in ARMS:
            names = [f"{arm}_{s}" for s in PPO_SEEDS]
            ok = [n for n in names if report["per_seed"].get(
                n, {}).get("seed_gate_pass")]
            no_fail = all(report["per_seed"].get(n, {}).get(
                "no_economic_failure") is True for n in names)
            boot_ok = bootstrap_results_all_valid_positive(
                report["arm_level"][arm][
                    "bootstrap_vs_baselines"])
            report["arm_level"][arm]["n_seed_gate_pass"] = len(ok)
            report["arm_level"][arm]["arm_gate_pass"] = bool(
                len(ok) >= 2 and no_fail and boot_ok)
        report["layered_exit"]["c1_learning_evidence_established"] = (
            any(report["arm_level"][a]["arm_gate_pass"]
                for a in ARMS))
        report["revision_d_note"] = (
            "行为门 v2:反事实观察按 env.feature_names="
            f"{feature_names} 构造(v1 错用计划声明序 [s,c,q,g],"
            "信号进 c 槽位致门全数失真;经济评估不受影响——训练与"
            "评估同用本 env 布局;原行为门结果存 "
            "behavior_invalid_order_v1)。计划修订 D 记录列序。")
        ev = evidence_kib_settle(ledger, tag="bgate_v2")
        report["evidence_kib"] = ev
        out_path.write_text(json.dumps(report, ensure_ascii=False,
                                       indent=1), encoding="utf-8")
        print(json.dumps({
            "arm_gate": {a: report["arm_level"][a]["arm_gate_pass"]
                         for a in ARMS},
            "seed_pass": {k: v.get("seed_gate_pass")
                          for k, v in report["per_seed"].items()}},
            ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
