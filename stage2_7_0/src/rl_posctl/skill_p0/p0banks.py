# -*- coding: utf-8 -*-
"""PSC_P0_v1 数据域:固定 bank 生成、镜像端点、哈希与确认区锁定。

- pair = original(1 次真实生成调用)+ mirror(确定性变换,0 次调用);
  两端点各计 1 个物化 episode(计划 832 eps/416 gen_calls)。
- mirror:s'=−s,c/q/g 不变,r'=−r(重构算术收益取负 ⇒ u'=−u 同
  |噪声|,mu_eff' = −mu_eff),价格链按 r' 重算;不做倒数价格。
- confirmation/horizon bank 默认锁定:须 runs/psc_p0_confirm_lock.json
  (六最终 checkpoint 哈希+分折代码身份)在场才可生成。
- 同 seed 重建 = 新生成调用(banks v3 语义);reset 只读 bank。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from rl_posctl.banks import QuotaLedger, generate_counted
from rl_posctl.curriculum import spec_fingerprint
from rl_posctl.skill_p0.p0spec import (
    BANK_SIZES, LOCKED_PURPOSES, PLANNED_EPISODES, bank_horizon, c1_spec,
    p0_seed)

LOCK_FILE_NAME = "psc_p0_confirm_lock.json"


def mirror_episode(prices: pd.DataFrame, feats: pd.DataFrame,
                   hidden: dict):
    """确定性镜像端点(s 翻转,算术收益取负;费用/期限规则不变)。"""
    close = prices["close"].to_numpy(dtype=np.float64)
    r = close[1:] / close[:-1] - 1.0
    r_m = -r
    if np.any(1.0 + r_m <= 0.0):
        raise RuntimeError("镜像收益越界(价格非正;结构非法)")
    close_m = 100.0 * np.cumprod(
        np.concatenate([[0.0], r_m]) + 1.0)
    open_m = np.empty_like(close_m)
    open_m[0] = 100.0
    open_m[1:] = close_m[:-1]
    feats_m = feats.copy()
    feats_m["s"] = -feats["s"]
    hidden_m = dict(hidden)
    hidden_m["mu_eff"] = -np.asarray(hidden["mu_eff"])
    hidden_m["s"] = -np.asarray(hidden["s"])
    return (pd.DataFrame({"open": open_m, "close": close_m}),
            feats_m, hidden_m)


def _episode_blob(prices, feats) -> bytes:
    pay = {
        "open": [float(x) for x in prices["open"].to_numpy()],
        "close": [float(x) for x in prices["close"].to_numpy()],
        "feats": {c: [float(x) for x in feats[c].to_numpy()]
                  for c in feats.columns},
    }
    return json.dumps(pay, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def confirm_lock_ok(runs_dir: Path) -> tuple[bool, str]:
    lock = Path(runs_dir) / LOCK_FILE_NAME
    if not lock.exists():
        return False, f"缺少 {lock}(confirmation/horizon 未解锁)"
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return False, f"锁文件不可读 {lock}:{exc}"
    ck = data.get("final_checkpoints") or {}
    if len(ck) != 6:
        return False, f"锁内最终 checkpoint 数 {len(ck)} != 6"
    for name, meta in ck.items():
        if not isinstance(meta, dict) or not meta.get("sha256"):
            return False, f"锁内 {name} 缺 sha256"
        p = Path(meta.get("path", ""))
        if not p.exists() or hashlib.sha256(
                p.read_bytes()).hexdigest() != meta["sha256"]:
            return False, f"锁内 {name} 与实际字节不一致"
    if not data.get("analysis_code_digest"):
        return False, "锁内缺 analysis_code_digest"
    return True, "ok"


def build_p0_bank(purpose: str, *, runs_dir: Path,
                  task_ledger, out_dir: Path,
                  force_unlock: bool = False) -> dict:
    """生成一个 P0 数据分区 bank(create-only 输出)。"""
    if purpose not in BANK_SIZES:
        raise ValueError(f"未知分区 {purpose!r}")
    pairs, variants = BANK_SIZES[purpose]
    if variants != 2:
        raise ValueError("P0 bank 设计为 original+mirror 两端点")
    H = bank_horizon(purpose)
    if purpose in LOCKED_PURPOSES and not force_unlock:
        ok, why = confirm_lock_ok(runs_dir)
        if not ok:
            raise RuntimeError(
                f"分区 {purpose} 默认锁定:{why}(须六最终模型与分折"
                "代码锁定后显式解锁)")
    out_dir = Path(out_dir)
    bank_path = out_dir / f"{purpose}_bank.json"
    if bank_path.exists():
        raise RuntimeError(f"bank 已存在,拒绝覆盖:{bank_path}")
    out_dir.mkdir(parents=True, exist_ok=True)
    journal = QuotaLedger(
        out_dir / f"{purpose}_gen_journal.jsonl",
        task_ledger=task_ledger)
    rows = []
    for i in range(pairs):
        spec = c1_spec(purpose, i, horizon=H)
        gen_seed = p0_seed(purpose, i, 0, 1)
        prices, feats, hidden = generate_counted(
            spec, gen_seed, ledger=journal,
            bank=f"psc_p0_{purpose}", domain=purpose)
        for variant in (0, 1):
            if variant == 1:
                prices_v, feats_v, hidden_v = mirror_episode(
                    prices, feats, hidden)
                journal.record_episode(
                    bank=f"psc_p0_{purpose}", domain=purpose)
            else:
                prices_v, feats_v, hidden_v = prices, feats, hidden
            blob = _episode_blob(prices_v, feats_v)
            rows.append({
                "pair_index": i, "variant": variant,
                "seed_pair": [int(spec.seed), int(gen_seed)],
                "horizon": int(H),
                "spec_fingerprint": spec_fingerprint(spec),
                "sha256": hashlib.sha256(blob).hexdigest(),
                "episode": json.loads(blob.decode("utf-8")),
            })
    manifest = {
        "task": "PSC_P0_v1", "purpose": purpose, "horizon": int(H),
        "pairs": int(pairs), "episodes": len(rows),
        "spec": {"mu_max": 0.004, "sigma_lo": 0.006, "sigma_hi": 0.006,
                 "fee": 0.001, "slippage_bps": 0.0,
                 "s_switch_p": 0.10, "c_hold_p": 0.85, "g_hold_p": 0.85,
                 "q_hold_p": 0.80, "sigma_regime": False,
                 "initial_cash": 100.0, "maintenance_margin": 0.05,
                 "funding": "explicit empty plan {}"},
        "items": rows,
    }
    text = json.dumps(manifest, ensure_ascii=False)
    bank_path.write_text(text, encoding="utf-8")
    return {
        "purpose": purpose, "path": str(bank_path),
        "sha256": hashlib.sha256(
            bank_path.read_bytes()).hexdigest(),
        "episodes": len(rows), "gen_calls": pairs,
    }


def load_p0_bank(path: Path) -> list:
    """读 bank -> [(prices, feats, meta)](重放不重复计生成)。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    out = []
    for it in data["items"]:
        ep = it["episode"]
        prices = pd.DataFrame(
            {"open": ep["open"], "close": ep["close"]})
        feats = pd.DataFrame(ep["feats"])
        out.append((prices, feats, {
            "pair_index": it["pair_index"], "variant": it["variant"],
            "horizon": it["horizon"], "sha256": it["sha256"],
            "seed_pair": it["seed_pair"]}))
    return out


def bank_ref_sha(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()
