#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 dev 评估(独立进程只读 checkpoint;确定性+采样两种执行)。

- 4 个预定 dev 点 × 2 模式 × 6 模型 × dev bank(64 eps × H=64);
- 评估采样 RNG 与训练流隔离(seed=p0_seed("evalsample",...));
- 不据 dev 挑最赚钱 checkpoint(主结论用 131,072 步最终模型;
  中间曲线只作学习曲线证据);
- eval_steps/dist_sample_actions 计量;模型初始网络(dev ck0)与
  初始随机网络变化对照一并产出。

用法:
    python psc_p0_eval.py --stage dev [--ledger <jsonl>]
        [--banks-dir <dir>] [--out <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import torch as th

from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.skill_p0.p0banks import bank_ref_sha, load_p0_bank  # noqa: E402
from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv  # noqa: E402
from rl_posctl.skill_p0.p0eval import (  # noqa: E402
    eval_on_bank, model_action_fn)
from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    load_p0_model, make_p0_ppo)
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, make_sampler_meter, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    ARMS, C1_HORIZON, CHECKPOINT_STEPS, PPO_SEEDS, p0_seed)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="dev", choices=("dev",))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--banks-dir", default=str(RUNS_DIR / "banks"))
    ap.add_argument("--runs-root", default=str(RUNS_DIR / "main"))
    ap.add_argument("--out", default=str(RUNS_DIR / "eval_dev"))
    args = ap.parse_args()
    th.set_num_threads(1)
    out_root = Path(args.out)
    gate_path = out_root / "dev_eval.json"
    if gate_path.exists():
        print(f"已有 dev_eval.json:{gate_path}", file=sys.stderr)
        return 2
    bank_path = Path(args.banks_dir) / "dev" / "dev_bank.json"
    if not bank_path.exists():
        write_rejection(out_root, "psc_p0_eval",
                        f"缺少 dev bank:{bank_path}", sys.argv)
        return 2
    runs = {}
    missing = []
    for arm in ARMS:
        for seed in PPO_SEEDS:
            rd = Path(args.runs_root) / f"{arm}_{seed}"
            if not (rd / "run_record.json").exists():
                missing.append(str(rd))
                continue
            runs[f"{arm}_{seed}"] = rd
    if missing:
        write_rejection(out_root, "psc_p0_eval",
                        f"缺少主运行:{missing}", sys.argv)
        return 2
    ledger = open_ledger(args.ledger)
    bank_ref = bank_ref_sha(bank_path)
    items = load_p0_bank(bank_path)
    meter = make_sampler_meter(ledger, "dev_eval")
    report = {"stage": "dev", "bank_ref": bank_ref,
              "n_episodes": len(items), "models": {}}
    with RunLog(out_root, meta_extra={"runner": "psc_p0_eval"}):
        for name, rd in sorted(runs.items()):
            arm, seed = name.split("_")
            train_rec = json.loads(
                (rd / "run_record.json").read_text(encoding="utf-8"))
            train_bank_ref = train_rec["bank_ref"]
            env = P0EpisodeBankEnv(items)
            per_ckpt = {}
            for ck in CHECKPOINT_STEPS:
                ck_path = rd / f"ck{ck}.zip"
                if not ck_path.exists():
                    raise RuntimeError(f"缺 checkpoint:{ck_path}")
                model = load_p0_model(
                    ck_path, env, arm=arm, bank_ref=train_bank_ref,
                    horizon=C1_HORIZON)
                for mode in ("deterministic", "sampled"):
                    if mode == "sampled":
                        th.manual_seed(p0_seed(
                            "evalsample", int(seed), 1, 1))
                    rows = eval_on_bank(
                        items, model_action_fn(
                            model, deterministic=(mode
                                                  == "deterministic")),
                        ledger=ledger,
                        tag=f"dev:{name}:ck{ck}:{mode}")
                    vals = [r["net_log_return"] for r in rows
                            if r["net_log_return"] is not None]
                    per_ckpt[f"ck{ck}_{mode}"] = {
                        "mean_net_log_return": (
                            float(np.mean(vals)) if vals else None),
                        "n_valid": len(vals),
                        "n_failure": sum(
                            1 for r in rows if r["economic_failure"]),
                        "rows_file": None,
                    }
                    rp = out_root / f"{name}_ck{ck}_{mode}_rows.json"
                    if rp.exists():
                        raise RuntimeError(f"已存在:{rp}")
                    rp.write_text(json.dumps(
                        rows, ensure_ascii=False, indent=1),
                        encoding="utf-8")
                    per_ckpt[f"ck{ck}_{mode}"][
                        "rows_file"] = str(rp)
            report["models"][name] = per_ckpt
            print(name, {k: v["mean_net_log_return"]
                         for k, v in per_ckpt.items()})
        ev = evidence_kib_settle(ledger, tag="eval_dev")
        report["evidence_kib"] = ev
        gate_path.write_text(json.dumps(report, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
