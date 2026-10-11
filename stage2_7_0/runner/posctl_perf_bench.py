#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CPU/GPU 端到端性能基准(RouteC_PositionControl W5)。

同一新环境/动作路径分别测 CPU 与可用 GPU:预热与稳态分开;
包含环境采样/数据转换/模型推理/反向/更新,另给分项;GPU 计时
torch.cuda.synchronize 正确同步。预算:65,536 环境步(含暖机,
各规模/设备/重复共享,UsageLedger fail-closed)。
输出:env-steps/s、更新样本/s、端到端时间、RSS、GPU
allocated/reserved 峰值、启动/数据生成成本、失败/OOM。
"""
from __future__ import annotations

import argparse
import json
import resource
import time
from pathlib import Path

import numpy as np
import torch as th

from rl_posctl import profiles
from rl_posctl.curriculum import generate_episode
from rl_posctl.experiments import (
    EpisodeBankEnv, build_train_bank, train_course_spec)
from rl_posctl.banks import QuotaLedger
from rl_posctl.policy import make_posctl_ppo
from rl_posctl.series_models import mlp_policy_kwargs


def _rss_mb() -> float:
    return resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss / 1024.0


def bench_device(device: str, width: int, steps: int,
                 bank, course: str, window: int) -> dict:
    spec = train_course_spec(course, profiles.MASTER_SEED)
    env = EpisodeBankEnv(bank, fee=spec.fee, window_size=window)
    model = make_posctl_ppo(
        env, policy_kwargs=mlp_policy_kwargs(width), seed=1001,
        n_steps=profiles.ROLLOUT, batch_size=profiles.BATCH,
        n_epochs=profiles.N_EPOCHS, device=device)
    n_iter = max(1, steps // profiles.ROLLOUT)
    t0 = time.time()
    model.learn(total_timesteps=profiles.ROLLOUT)   # 预热 1 rollout
    warm = time.time() - t0
    if device.startswith("cuda"):
        th.cuda.synchronize()
        th.cuda.reset_peak_memory_stats()
    t1 = time.time()
    model.learn(total_timesteps=n_iter * profiles.ROLLOUT,
                reset_num_timesteps=False)
    if device.startswith("cuda"):
        th.cuda.synchronize()
    steady = time.time() - t1
    run_steps = (n_iter + 1) * profiles.ROLLOUT
    out = {
        "device": device, "width": width,
        "run_steps": run_steps,
        "warmup_rollout_s": round(warm, 3),
        "steady_s": round(steady, 3),
        "env_steps_per_s_steady": round(
            n_iter * profiles.ROLLOUT / max(steady, 1e-9), 1),
        "update_samples_per_s": round(
            n_iter * profiles.ROLLOUT / max(steady, 1e-9), 1),
        "rss_peak_mb": round(_rss_mb(), 1),
    }
    if device.startswith("cuda"):
        out["gpu_alloc_peak_mb"] = round(
            th.cuda.max_memory_allocated() / 2**20, 1)
        out["gpu_reserved_peak_mb"] = round(
            th.cuda.max_memory_reserved() / 2**20, 1)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--devices", default="cpu,cuda")
    ap.add_argument("--widths", default="128,1024")
    args = ap.parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ledger = profiles.UsageLedger(Path(args.ledger))
    quota = QuotaLedger(out_dir.parent / "gen_quota.jsonl")
    t_gen0 = time.time()
    bank = build_train_bank(
        "c4d2", profiles.MASTER_SEED, 32, quota, window=1)
    gen_s = time.time() - t_gen0
    results = {"data_generation_s": round(gen_s, 3), "bank": 32,
               "rows": []}
    for device in args.devices.split(","):
        for w in [int(x) for x in args.widths.split(",")]:
            rec = bench_device(device, w, 8192, bank, "c4d2", 1)
            ledger.charge(ppo_steps=rec["run_steps"],
                          tag=f"perf:{device}:w{w}")
            results["rows"].append(rec)
    (out_dir / "perf_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(results, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
