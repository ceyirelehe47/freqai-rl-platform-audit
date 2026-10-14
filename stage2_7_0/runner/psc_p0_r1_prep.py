#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 工程 smoke 手工 bank(ENGINEERING_ONLY)。

固定手工序列(不调用课程生成器;gen_calls/episodes 计量保持 0):
2 个 episode × 65 行(决策期 64 步),价格/特征为固定常数/交替序列,
结构/load_p0_bank 兼容(purpose=train 仅作路径约定)。本 bank 只供
engsmoke 存取路径验证,不得进入 P0 科学结论。

用法:
    python psc_p0_r1_prep.py --out-root <R1 root>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

N_ROWS = 65            # 决策期 64 步(C1_HORIZON 同形)


def _episode(pair_index: int, variant: int) -> dict:
    """固定手工 episode(零熵价格 + 交替 s 信号;确定性构造)。"""
    open_ = [100.0] * N_ROWS
    close = [100.0] * N_ROWS
    for t in range(1, N_ROWS):
        close[t] = 100.0 + (0.05 if t % 2 == 0 else -0.05)
    feats = {
        "c": [0.0] * N_ROWS,
        "g": [0.0] * N_ROWS,
        "q": [0.75] * N_ROWS,
        "s": [1.0 if t % 4 < 2 else -1.0 for t in range(N_ROWS)],
    }
    blob = json.dumps({"open": open_, "close": close,
                       "feats": feats}, sort_keys=True)
    return {
        "pair_index": pair_index, "variant": variant,
        "seed_pair": [0, 0],          # 手工序列无种子身份
        "horizon": N_ROWS - 1,
        "spec_fingerprint": "ENGINEERING_ONLY_HANDCRAFTED",
        "sha256": hashlib.sha256(blob.encode()).hexdigest(),
        "episode": {"open": open_, "close": close, "feats": feats},
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    args = ap.parse_args()
    out = Path(args.out_root) / "banks_eng" / "train"
    bank = out / "train_bank.json"
    if bank.exists():
        print(f"已存在(create-only):{bank}", file=sys.stderr)
        return 2
    doc = {
        "task": "PSC_P0_v1", "purpose": "train",
        "engineering_only": True,
        "note": ("FiniteRepair R1 手工 bank;固定序列非课程生成;"
                 "仅供 engsmoke 存取路径验证"),
        "horizon": N_ROWS - 1, "pairs": 1, "episodes": 2,
        "spec": {"kind": "handcrafted_fixed_series"},
        "items": [_episode(0, 0), _episode(0, 1)],
    }
    out.mkdir(parents=True, exist_ok=True)
    bank.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    print(json.dumps({"bank": str(bank), "episodes": 2,
                      "sha256": hashlib.sha256(
                          bank.read_bytes()).hexdigest()},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
