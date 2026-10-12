#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2-06:现存原件移交(FiniteRepair R2)。

- 三个 R1 smoke.zip 原件(WSL ~/posctl_r1_runs/smoke_*)复制到 R2
  evidence + SHA256 + 模型输入身份(cold_spec/eval 域种子链)+ 只读
  冷载记录(load_posctl_model_archive:权重头校验 + 确定性前向;
  不构造新环境、不训练);
- 同 seed 重建 eval 集第 0 集 = 生成调用(入任务账本,先预约后执行);
- R1 三轮 reviewer 原文状态盘点(可取得即复制;摘要则明示);
- 261 审计/绑定原件索引(完整 SHA 可读哈希索引,不重复生成)。
输出:evidence/r2_runs/originals_handover/。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, "/mnt/f/trading/freqai-rl-audit/stage2_7_0/src")

from rl_posctl import profiles  # noqa: E402
from rl_posctl.budget import TaskLedger  # noqa: E402
from rl_posctl.banks import domain_seed, episode_seed  # noqa: E402
from rl_posctl.curriculum import (  # noqa: E402
    generate_episode, spec_for)
from rl_posctl.policy import load_posctl_model_archive  # noqa: E402
from rl_posctl.versions import POSCTL_R2_TASK_ID  # noqa: E402

import numpy as np  # noqa: E402
import torch as th  # noqa: E402

SRC = Path.home() / "posctl_r1_runs"
DEST = Path("/mnt/f/trading/acceptance/PosCtl_R2_20261012/evidence"
            "/r2_runs/originals_handover")
LEDGER = Path.home() / "posctl_r2_runs" / "r2_task_ledger.jsonl"
R1_REVIEWS = Path("/mnt/f/trading/acceptance/PosCtl_R1_20261012"
                  "/reviews")
R1_261 = Path("/mnt/f/trading/acceptance/PosCtl_R1_20261012"
              "/evidence/r1_runs/r21_261_final")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    led = TaskLedger(LEDGER, POSCTL_R2_TASK_ID)
    DEST.mkdir(parents=True, exist_ok=True)
    manifest = {"created_utc": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "smoke_models": [],
        "reviewer_originals": {}, "audit261_index": {}}

    # ---- smoke.zip 原件 + 只读冷载 ----
    spec = spec_for(profiles.TRAIN_COURSE, seed=profiles.MASTER_SEED,
                    horizon=64, **profiles.TRAIN_SPEC_OVERRIDES)
    cold_rebuilds = 0
    for run_dir in sorted(SRC.glob("smoke_2026*")):
        z = run_dir / "smoke.zip"
        if not z.exists():
            continue
        rec_path = run_dir / "smoke_record.json"
        cold_spec = run_dir / "cold_spec.json"
        entry = {
            "run": run_dir.name,
            "source": str(z),
            "bytes": z.stat().st_size,
            "sha256": sha256_file(z),
            "smoke_record_copied": False,
            "cold_spec_copied": False,
            "archive_cold_read": None,
        }
        shutil.copy2(z, DEST / f"{run_dir.name}_smoke.zip")
        if rec_path.exists():
            shutil.copy2(rec_path,
                         DEST / f"{run_dir.name}_smoke_record.json")
            entry["smoke_record_copied"] = True
        if cold_spec.exists():
            shutil.copy2(cold_spec,
                         DEST / f"{run_dir.name}_cold_spec.json")
            entry["cold_spec_copied"] = True
        # 只读冷载:header 校验 + 确定性前向(同 seed 重建=生成计调用)
        try:
            rid = led.reserve(f"cold_rebuild:{run_dir.name}",
                              gen_calls=1, episodes=1)
            try:
                prices, feats, _ = generate_episode(
                    spec, episode_seed(
                        domain_seed(profiles.MASTER_SEED, "eval"), 0))
                cold_rebuilds += 1
                led.commit(rid, f"cold_rebuild:{run_dir.name}",
                           gen_calls=1, episodes=1)
            except BaseException:
                led.abandon(rid, f"cold_rebuild:{run_dir.name}",
                            note="重建异常,保守保留")
                raise
            model, header = load_posctl_model_archive(
                DEST / f"{run_dir.name}_smoke.zip")
            obs0 = np.concatenate([
                feats.iloc[0].to_numpy(dtype=np.float64),
                [0.0, float(np.arcsinh(40.0) / 4.0)]])
            obs = th.as_tensor(obs0, dtype=th.float32).unsqueeze(0)
            with th.no_grad():
                a, v, lp = model.policy(obs, deterministic=True)
            entry["archive_cold_read"] = {
                "status": "OK",
                "header": {k: header.get(k) for k in (
                    "policy_spec", "env_core", "execution_spec",
                    "observation_spec", "ledger", "obs_dim",
                    "account_features")},
                "deterministic_action": [
                    float(x) for x in a[0]],
                "obs_identity": {
                    "episode_seed": episode_seed(domain_seed(
                        profiles.MASTER_SEED, "eval"), 0),
                    "feature_row_0": [
                        float(x) for x in
                        feats.iloc[0].to_numpy()],
                },
                "note": ("env_core/execution 为 R1 v2 身份,原样披露;"
                         "策略网络语义未变,只读冷载核验权重与确定性"
                         "前向;不接新环境不训练"),
            }
        except Exception as exc:
            entry["archive_cold_read"] = {
                "status": "FAILED", "error": repr(exc)}
        manifest["smoke_models"].append(entry)

    # ---- R1 三轮 reviewer 原文状态 ----
    rev = manifest["reviewer_originals"]
    for name in sorted(R1_REVIEWS.iterdir()):
        if name.is_file():
            rev[name.name] = {
                "bytes": name.stat().st_size,
                "sha256": sha256_file(name),
            }
    rev["_status_note"] = (
        "R1 round1 全文原标明在 agent transcript、包内仅摘要"
        "(reviewer_round1_findings.json);round2/round3 送达原文在包内"
        "(reviewer_round2_round3_messages.md)。R2 交付时如实分层")

    # ---- 261 审计/绑定原件索引 ----
    idx = manifest["audit261_index"]
    if R1_261.is_dir():
        for p in sorted(R1_261.rglob("*")):
            if p.is_file() and not any(
                    part in ("__pycache__",) for part in p.parts):
                idx[str(p.relative_to(R1_261))] = {
                    "bytes": p.stat().st_size,
                    "sha256": sha256_file(p),
                    "source": str(p),
                }

    out = DEST / "handover_manifest.json"
    out.write_text(json.dumps(manifest, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print(json.dumps({
        "smoke_models": len(manifest["smoke_models"]),
        "cold_rebuilds_counted": cold_rebuilds,
        "reviewer_files": sorted(
            k for k in rev if not k.startswith("_")),
        "audit261_files": len(idx),
        "manifest": str(out),
        "ledger_effective": led.effective(),
    }, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
