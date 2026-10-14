#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 smoke 只读核验(新进程;零资源消费)。

对 engsmoke 运行目录做冷读核验(F1 验收:保存后在新进程只读检查
"有真实更新、非初始权重、更新计数与实际相符"):
- ck0(initial) 与 ck128(final) 阶段元数据/身份;
- final Adam 步 == run_record.optimizer_steps == 2(engsmoke 几何);
- final 权重摘要 != initial 权重摘要(非初始权重);
- run_record.final_ck_verify/checkpoint_manifest 一致;
- verify_final_checkpoint 全链通过(确认入口同款核验)。

用法:
    python psc_p0_r1_verify.py --run-dir <engsmoke run dir> \
        [--ledger <jsonl>]
不启动 learn、不步 env、不采样;reviewer 可直接复跑本脚本。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    inspect_p0_archive, verify_final_checkpoint)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    args = ap.parse_args()
    rd = Path(args.run_dir)
    rec = json.loads((rd / "run_record.json").read_text(
        encoding="utf-8"))
    out = {"run_dir": str(rd), "run_name": rec["run_name"]}
    problems = []
    ck0 = inspect_p0_archive(rd / "ck0.zip")
    ckf = inspect_p0_archive(rd / f"ck{rec['actual_steps']}.zip")
    out["ck0"] = {"stage": ck0["stage"]["stage"],
                  "adam_steps": ck0["adam_steps"],
                  "policy_digest": ck0["policy_digest"]}
    out["final"] = {"stage": ckf["stage"]["stage"],
                    "adam_steps": ckf["adam_steps"],
                    "policy_digest": ckf["policy_digest"],
                    "num_timesteps":
                        ckf["stage"]["num_timesteps"],
                    "optimizer_steps":
                        ckf["stage"]["optimizer_steps"]}
    if ck0["stage"]["stage"] != "initial":
        problems.append("ck0 阶段非 initial")
    if ck0["adam_steps"] != 0:
        problems.append("初始档 Adam 步非 0")
    if ckf["stage"]["stage"] != "final":
        problems.append("final 档阶段非 final")
    if rec["optimizer_steps"] != 2:
        problems.append(
            f"run_record.optimizer_steps={rec['optimizer_steps']}"
            " != engsmoke 预期 2")
    if ckf["adam_steps"] != rec["optimizer_steps"]:
        problems.append(
            f"final Adam 步 {ckf['adam_steps']} != run_record "
            f"{rec['optimizer_steps']}")
    if ckf["policy_digest"] == ck0["policy_digest"]:
        problems.append("final 权重摘要 == 初始权重摘要(未更新?)")
    if int(ckf["stage"]["num_timesteps"]) != rec["actual_steps"]:
        problems.append("final num_timesteps 与 run_record 不符")
    man = rec.get("checkpoint_manifest") or []
    stages = [m["stage"] for m in man]
    if stages not in (["initial", "final"], ["final"]):
        problems.append(f"manifest 阶段序 {stages} 异常")
    if not rec.get("final_ck_verify", {}).get("verified"):
        problems.append("run_record.final_ck_verify.verified 非真")
    # 确认入口同款核验(资源前拒绝面;此处零资源)
    try:
        v = verify_final_checkpoint(
            rd / f"ck{rec['actual_steps']}.zip", rec)
        out["verify_final_checkpoint"] = {
            "ok": True, "sha256": v["sha256"]}
    except RuntimeError as exc:
        problems.append(f"verify_final_checkpoint 拒绝:{exc}")
        out["verify_final_checkpoint"] = {"ok": False}
    out["problems"] = problems
    out["pass"] = not problems
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
