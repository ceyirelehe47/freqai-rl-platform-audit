#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 smoke 后续小额真实验证(ENGINEERING_ONLY)。

在 engsmoke 训练完成后执行,真实验证 F2/F3 新入口的"先约后用"与
正常路径(恰足、只计一次):
1. 冷载 final 模型(load_p0_model,engsmoke 几何);
2. eval_on_bank(确定性)重放手工 bank(2 eps × 64 步 = 128 eval
   步,R1 面唯一预约→执行→实结;raw 行落盘);
3. behavior_gate sampled_check=8(8 次分布采样,meter 前置);
4. 结果与账本快照写入 smoke_summary.json(create-only)。

不重放 confirmation/hz bank,不做科学 bootstrap;总经济步 =
PPO 128 + eval 128 = 256(=R1 面 economic_total 上限)。

用法:
    python psc_p0_r1_smoke.py --run-dir <engsmoke run dir> \
        --ledger <jsonl> --out <summary path>
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch as th  # noqa: E402

from rl_posctl.skill_p0.p0banks import (  # noqa: E402
    bank_ref_sha, load_p0_bank)
from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv  # noqa: E402
from rl_posctl.skill_p0.p0eval import (  # noqa: E402
    behavior_gate, eval_on_bank, model_action_fn)
from rl_posctl.skill_p0.p0policy import load_p0_model  # noqa: E402
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    make_sampler_meter, open_ledger)
from rl_posctl.versions import (  # noqa: E402
    POSCTL_PSC_P0_R1_TASK_ID)

ENG_BATCH = 64
ENG_EPOCHS = 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-dir", required=True)
    ap.add_argument("--banks-dir", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    th.set_num_threads(1)
    out_path = Path(args.out)
    if out_path.exists():
        print(f"已存在(create-only):{out_path}", file=sys.stderr)
        return 2
    rd = Path(args.run_dir)
    rec = json.loads((rd / "run_record.json").read_text(
        encoding="utf-8"))
    bank_path = Path(args.banks_dir) / "train" / "train_bank.json"
    items = load_p0_bank(bank_path)
    bank_ref = bank_ref_sha(bank_path)
    env = P0EpisodeBankEnv(items)
    model = load_p0_model(
        rd / f"ck{rec['actual_steps']}.zip", env,
        arm=rec["arm"], bank_ref=rec["bank_ref"], horizon=64,
        n_steps=128, batch_size=ENG_BATCH,
        n_epochs=ENG_EPOCHS)
    ledger = open_ledger(args.ledger)
    assert ledger.task_id == POSCTL_PSC_P0_R1_TASK_ID
    meter = make_sampler_meter(ledger, "r1_smoke")
    raw_dir = out_path.parent / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_file = raw_dir / (
        f"eval_{rec['run_name']}_deterministic.jsonl")
    if raw_file.exists():
        print(f"raw 已存在:{raw_file}", file=sys.stderr)
        return 2
    fh = raw_file.open("x", encoding="utf-8")

    def sink(row):
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()

    t0 = time.time()
    rows = eval_on_bank(
        items, model_action_fn(model, deterministic=True),
        ledger=ledger, tag=f"r1smoke:{rec['run_name']}",
        raw_sink=sink)
    fh.close()
    gate = behavior_gate(model, meter=meter, sampled_check=8)
    snap = ledger.snapshot()
    summary = {
        "engineering_only": True,
        "run_dir": str(rd), "bank_ref": bank_ref,
        "n_episodes": len(items),
        "eval": {
            "mode": "deterministic",
            "steps_total": sum(r["steps"] for r in rows),
            "mean_net_log_return": (
                sum(r["net_log_return"] for r in rows
                    if r["net_log_return"] is not None)
                / max(1, sum(1 for r in rows
                             if r["net_log_return"] is not None))),
            "n_economic_failure": sum(
                1 for r in rows if r["economic_failure"]),
            "raw_file": str(raw_file)},
        "behavior_gate_sampled_check": {
            k: gate[k] for k in (
                "n_conditions", "long_min", "short_min",
                "neutral_min", "pass",
                "sampled_check_conditions")},
        "ledger_snapshot": snap,
        "elapsed_s": round(time.time() - t0, 2),
    }
    out_path.write_text(json.dumps(summary, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
    # evidence 结算只认本轮根(不把旧 P0 树计量进 R1 账本)
    from rl_posctl.skill_p0.p0run import evidence_kib_settle
    r1_root = Path(args.ledger).resolve().parents[1]
    summary["evidence_kib"] = evidence_kib_settle(
        ledger, tag="r1_smoke", roots=[r1_root])
    out_path.write_text(json.dumps(summary, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
    print(json.dumps({
        "eval_steps": summary["eval"]["steps_total"],
        "sampled_conditions":
            gate["sampled_check_conditions"],
        "committed": snap["committed"],
        "derived": {k: v["effective"] for k, v in
                    snap.get("derived_totals", {}).items()}},
        ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
