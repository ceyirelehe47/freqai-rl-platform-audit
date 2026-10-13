#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 bank 生成(prequal/train/dev;confirm/hz32/hz96 锁定)。

用法:
    python psc_p0_banks.py --purpose prequal|train|dev \
        [--ledger <jsonl>] [--banks-dir <dir>] [--force-unlock]

confirmation/horizon 分区默认锁定:须 runs/psc_p0_confirm_lock.json
(六最终 checkpoint 哈希+分折代码身份)在场。输出 create-only。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.skill_p0.p0banks import build_p0_bank  # noqa: E402
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, open_ledger)
from rl_posctl.skill_p0.p0spec import LOCKED_PURPOSES  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--purpose", required=True)
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--banks-dir", default=str(RUNS_DIR / "banks"))
    ap.add_argument("--force-unlock", action="store_true",
                    help="仅在确认锁文件在场且核对通过时有效")
    args = ap.parse_args()
    purpose = args.purpose
    out_root = Path(args.banks_dir) / purpose
    if out_root.exists() and any(out_root.iterdir()):
        write_rejection(out_root.parent, "psc_p0_banks",
                        f"输出目录已非空:{out_root}", sys.argv)
        return 2
    ledger = open_ledger(args.ledger)
    run_id = f"psc_p0_banks_{purpose}"
    with RunLog(out_root, meta_extra={"runner": run_id}) as rl:
        rec = build_p0_bank(
            purpose, runs_dir=RUNS_DIR, task_ledger=ledger,
            out_dir=out_root, force_unlock=args.force_unlock)
        rec["locked_purposes"] = list(LOCKED_PURPOSES)
        rec["ledger"] = str(ledger.path)
        ev = evidence_kib_settle(ledger, tag=f"banks_{purpose}")
        rec["evidence_kib"] = ev
        (out_root / "bank_record.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps(rec, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
