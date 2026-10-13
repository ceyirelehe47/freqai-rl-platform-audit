#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 主训练(单格:--arm A|B × --seed;kind main/smoke/techretry)。

流程:载 train bank → 建 P0 时间环境与 P0 PPO(超参冻结)→ 记初始
checkpoint/trunk 摘要/参数量 → learn 门(预约步数上界+optimizer 上界)
→ 咽喉硬限 + FailureAwareStop + 检查点回调(0/32,768/65,536/131,072)
→ 实结(实际步数+真实 optimizer.step 计数)→ run record。

- dev 评估不在训练进程内执行(独立 eval runner 只读 checkpoint,
  训练 RNG 流零扰动);
- 输出 create-only;经济失败 → RUN_INVALID 停(轨迹保全)。

用法:
    python psc_p0_train.py --arm B --seed 270201 [--kind main]
        [--ledger <jsonl>] [--banks-dir <dir>] [--out-root <dir>]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import torch as th
from stable_baselines3.common.callbacks import BaseCallback

from rl_posctl.experiments import FailureAwareStop  # noqa: E402
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.skill_p0.p0banks import bank_ref_sha, load_p0_bank  # noqa: E402
from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv  # noqa: E402
from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    make_p0_ppo, p0_code_digest, save_p0_model, trunk_digest,
    wrap_optimizer_counter)
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    P0LearnGate, RUNS_DIR, evidence_kib_settle, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    ARMS, CHECKPOINT_STEPS, C1_HORIZON, MAIN_TOTAL_STEPS,
    OPT_STEPS_MAIN_UB, PPO_SEEDS, SMOKE_STEPS_SINGLE,
    TECHRETRY_OPT_STEPS_UB, TECHRETRY_STEPS_SINGLE)


class P0TrainCallbacks(BaseCallback):
    """检查点保存 + per-rollout 日志 + 逐 episode 终态记录。"""

    def __init__(self, model, out_dir: Path, checkpoints: tuple,
                 opt_box: dict, n_bank: int) -> None:
        super().__init__()
        self.model = model
        self.out_dir = Path(out_dir)
        self.checkpoints = list(checkpoints)
        self.opt_box = opt_box
        self.n_bank = int(n_bank)
        self.rollout_log = []
        self.episode_log = []

    def _on_step(self) -> bool:
        for info in self.locals.get("infos") or []:
            if info.get("terminated") or info.get("truncated"):
                self.episode_log.append({
                    "timesteps": int(self.num_timesteps),
                    "reward_valid": bool(info.get("reward_valid")),
                    "equity_end": info.get("equity_end"),
                    "fees_cum": info.get("fees_cum"),
                    "decision_tick": info.get("decision_tick"),
                })
        if self.checkpoints and self.num_timesteps >= (
                self.checkpoints[0]):
            step = self.checkpoints.pop(0)
            path = self.out_dir / f"ck{step}.zip"
            if not path.exists():
                save_p0_model(self.model, path)
                self.rollout_log.append({
                    "event": "checkpoint", "step": int(step),
                    "path": str(path), "ts": time.time()})
        return True

    def _on_rollout_end(self) -> None:
        rec = {"event": "rollout", "timesteps": int(self.num_timesteps),
               "optimizer_steps_cum": int(self.opt_box["n"])}
        nl = dict(self.model.logger.name_to_value)
        for k in ("train/entropy_loss", "train/policy_gradient_loss",
                  "train/value_loss", "train/approx_kl",
                  "train/clip_fraction", "train/explained_variance",
                  "train/loss"):
            if k in nl:
                rec[k.split("/")[-1]] = float(nl[k])
        self.rollout_log.append(rec)


def count_params(model) -> dict:
    pol = model.policy
    total = sum(p.numel() for p in pol.parameters())
    pi = sum(p.numel() for p in pol.mlp_extractor.policy_net.parameters())
    pi += pol.action_net.weight.numel() + pol.action_net.bias.numel()
    vf = sum(p.numel() for p in pol.mlp_extractor.value_net.parameters())
    vf += pol.value_net.weight.numel() + pol.value_net.bias.numel()
    return {"total": int(total), "actor": int(pi), "critic": int(vf)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--arm", required=True, choices=ARMS)
    ap.add_argument("--seed", type=int, required=True)
    ap.add_argument("--kind", default="main",
                    choices=("main", "smoke", "techretry"))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--banks-dir", default=str(RUNS_DIR / "banks"))
    ap.add_argument("--out-root", default=str(RUNS_DIR))
    args = ap.parse_args()
    th.set_num_threads(1)
    if args.kind == "main":
        if args.seed not in PPO_SEEDS:
            write_rejection(RUNS_DIR, "psc_p0_train",
                            f"主实验 seed {args.seed} 不在预注册 "
                            f"{PPO_SEEDS}", sys.argv)
            return 2
        total_steps = MAIN_TOTAL_STEPS
        checkpoints = CHECKPOINT_STEPS
        n_steps = 1024
        opt_ub = OPT_STEPS_MAIN_UB
    elif args.kind == "smoke":
        total_steps = SMOKE_STEPS_SINGLE
        checkpoints = (0, SMOKE_STEPS_SINGLE)
        n_steps = 512
        opt_ub = 20
    else:
        total_steps = TECHRETRY_STEPS_SINGLE
        checkpoints = (0, TECHRETRY_STEPS_SINGLE)
        n_steps = 1024
        opt_ub = TECHRETRY_OPT_STEPS_UB
    run_name = f"{args.arm}_{args.seed}" if args.kind == "main" else (
        f"{args.kind}_{args.arm}_{args.seed}_{int(time.time())}")
    out_dir = Path(args.out_root) / ("main" if args.kind == "main"
                                     else args.kind) / run_name
    if out_dir.exists():
        write_rejection(out_dir.parent, "psc_p0_train",
                        f"运行目录已存在(create-only):{out_dir}",
                        sys.argv)
        return 2
    bank_path = Path(args.banks_dir) / "train" / "train_bank.json"
    if not bank_path.exists():
        write_rejection(out_dir.parent, "psc_p0_train",
                        f"缺少 train bank:{bank_path}", sys.argv)
        return 2
    ledger = open_ledger(args.ledger)
    items = load_p0_bank(bank_path)
    bank_ref = bank_ref_sha(bank_path)
    with RunLog(out_dir, meta_extra={
            "runner": "psc_p0_train", "arm": args.arm,
            "seed": args.seed, "kind": args.kind}):
        env = P0EpisodeBankEnv(items)
        model = make_p0_ppo(env, arm=args.arm, seed=args.seed,
                            bank_ref=bank_ref, horizon=C1_HORIZON,
                            n_steps=n_steps)
        out_dir.mkdir(parents=True, exist_ok=True)
        meta = {
            "run_name": run_name, "arm": args.arm, "seed": args.seed,
            "kind": args.kind, "total_steps": total_steps,
            "n_steps": n_steps, "bank_ref": bank_ref,
            "trunk_digest": trunk_digest(model),
            "params": count_params(model),
            "torch_threads": th.get_num_threads(),
            "code_digest": p0_code_digest(),
        }
        save_p0_model(model, out_dir / "ck0.zip")
        opt_box = wrap_optimizer_counter(model)
        cb = P0TrainCallbacks(model, out_dir, checkpoints, opt_box,
                              len(items))
        stop = FailureAwareStop()
        gate = P0LearnGate(ledger, kind=args.kind)
        t0 = time.time()
        rec = gate.learn(
            model, total_steps, extra_callbacks=[cb, stop.cb],
            optimizer_box=opt_box, opt_ub=opt_ub)
        elapsed = time.time() - t0
        failure = stop.failure
        status = "RUN_INVALID" if failure else "OK"
        n_done = len(cb.episode_log)
        visits = {}
        for k in range(n_done):
            visits[k % len(items)] = visits.get(
                k % len(items), 0) + 1
        meta.update({
            "elapsed_s": round(elapsed, 2),
            "actual_steps": rec["actual_steps"],
            "reserved_ub": rec["reserved_ub"],
            "optimizer_steps": rec["optimizer_steps"],
            "status": status,
            "economic_failure": failure,
            "n_rollouts": len([r for r in cb.rollout_log
                               if r.get("event") == "rollout"]),
            "episode_visits": {
                "n_completed": n_done, "n_bank": len(items),
                "counts": {str(k): v for k, v in sorted(
                    visits.items())},
                "steps_expected_if_full_episodes": n_done * 64,
                "matches_actual_steps": bool(
                    n_done * 64 == rec["actual_steps"])},
        })
        if status == "OK":
            final_ck = out_dir / f"ck{rec['actual_steps']}.zip"
            if not final_ck.exists():
                save_p0_model(model, final_ck)
        (out_dir / "rollout_log.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in cb.rollout_log) + "\n", encoding="utf-8")
        (out_dir / "episode_log.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in cb.episode_log) + "\n",
            encoding="utf-8")
        ev = evidence_kib_settle(ledger, tag=f"train_{run_name}")
        meta["evidence_kib"] = ev
        (out_dir / "run_record.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print(json.dumps({k: meta[k] for k in (
            "run_name", "arm", "seed", "kind", "status",
            "actual_steps", "optimizer_steps", "elapsed_s")},
            ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
