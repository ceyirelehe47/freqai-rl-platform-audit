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
    make_p0_ppo, p0_code_digest, policy_digest, save_p0_model_staged,
    trunk_digest, wrap_optimizer_counter)
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    CheckpointLifecycle, P0LearnGate, RUNS_DIR,
    bind_lifecycle_model, evidence_kib_settle, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    ARMS, CHECKPOINT_STEPS, C1_HORIZON, MAIN_TOTAL_STEPS,
    OPT_STEPS_MAIN_UB, PPO_SEEDS, SMOKE_STEPS_SINGLE,
    TECHRETRY_OPT_STEPS_UB, TECHRETRY_STEPS_SINGLE)

# R1 工程 smoke 几何(ENGINEERING_ONLY;RUNBOOK_AND_BUDGET.md):
# n_envs=1, n_steps=128, batch=64, n_epochs=1 → 2 次 minibatch 更新;
# 固定手工序列 bank,不调用课程生成器;不得当 P0 主结果消费。
ENGSMOKE_STEPS = 128
ENGSMOKE_N_STEPS = 128
ENGSMOKE_BATCH = 64
ENGSMOKE_EPOCHS = 1
ENGSMOKE_OPT_UB = 2


class P0TrainCallbacks(BaseCallback):
    """per-rollout 日志 + 逐 episode 终态记录 + 检查点采集登记。

    R1/F1:本回调不再直接写检查点(旧版在采集到门槛步数时立即
    写盘,彼时该 rollout 的优化尚未发生,produced pre-update 档)。
    采集期只调用 lifecycle.record_collect 登记;真正落盘在
    train() 正常返回后(after_train)与 learn 返回后(finalize)。
    """

    def __init__(self, model, out_dir: Path, checkpoints: tuple,
                 opt_box: dict, n_bank: int,
                 lifecycle: CheckpointLifecycle) -> None:
        super().__init__()
        self.model = model
        self.out_dir = Path(out_dir)
        self.opt_box = opt_box
        self.n_bank = int(n_bank)
        self.lifecycle = lifecycle
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
        self.lifecycle.record_collect(int(self.num_timesteps))
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


def wrap_train_flush(model, lifecycle: CheckpointLifecycle,
                     opt_box: dict):
    """包 model.train:train() 正常返回后 flush post-update 中间档。

    (learn 内每次 rollout 采集完成后才调 train;此处是"更新已完成"
    的唯一可靠回调点。异常路径不 flush——悬置目标由 finalize 拒绝
    或随 RUN_INVALID 不产 final 如实暴露。)
    """
    orig_train = model.train

    def _train_then_flush(*args, **kwargs):
        result = orig_train(*args, **kwargs)
        lifecycle.after_train(int(model.num_timesteps),
                              int(opt_box["n"]))
        return result

    model.train = _train_then_flush
    return orig_train


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
                    choices=("main", "smoke", "techretry",
                             "engsmoke"))
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--banks-dir", default=str(RUNS_DIR / "banks"))
    ap.add_argument("--out-root", default=str(RUNS_DIR))
    ap.add_argument("--evidence-roots", default=None,
                    help=("evidence_kib 结算根(逗号分隔;缺省 = P0 "
                          "runs/+evidence/。R1 工程 smoke 必须显式"
                          "指向本轮根,不得把旧 P0 树计量进新账本)"))
    args = ap.parse_args()
    th.set_num_threads(1)
    geometry_override = None
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
    elif args.kind == "engsmoke":
        # ENGINEERING_ONLY(R1 有限修复轮唯一工程 smoke):几何
        # 显式覆盖且 header 摘要随实际几何计算;不进入任何 P0
        # 科学结论。预期 optimizer 步数 = ENGSMOKE_OPT_UB。
        total_steps = ENGSMOKE_STEPS
        checkpoints = (0,)
        n_steps = ENGSMOKE_N_STEPS
        opt_ub = ENGSMOKE_OPT_UB
        geometry_override = (ENGSMOKE_BATCH, ENGSMOKE_EPOCHS)
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
        if geometry_override is None:
            model = make_p0_ppo(env, arm=args.arm, seed=args.seed,
                                bank_ref=bank_ref,
                                horizon=C1_HORIZON, n_steps=n_steps)
        else:
            bs, ep = geometry_override
            model = make_p0_ppo(env, arm=args.arm, seed=args.seed,
                                bank_ref=bank_ref,
                                horizon=C1_HORIZON, n_steps=n_steps,
                                batch_size=bs, n_epochs=ep)
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
        if geometry_override is not None:
            meta["engineering_only"] = {
                "flag": "ENGINEERING_ONLY", "batch_size": bs,
                "n_epochs": ep,
                "note": ("R1 FiniteRepair 工程 smoke;几何覆盖,"
                         "非 P0 主结果;不得进入科学结论")}
        bind_lifecycle_model(model)
        life = CheckpointLifecycle(out_dir, checkpoints,
                                   total_steps, run_name)
        # 初始档:learn 之前(0 采集/0 更新;阶段=initial)
        init_meta = save_p0_model_staged(
            model, out_dir / "ck0.zip", stage="initial",
            target_step=0, optimizer_steps=0, run_name=run_name)
        meta["initial_ck"] = {
            k: init_meta[k] for k in (
                "stage", "policy_digest", "optimizer_digest")}
        opt_box = wrap_optimizer_counter(model)
        cb = P0TrainCallbacks(model, out_dir, checkpoints, opt_box,
                              len(items), lifecycle=life)
        wrap_train_flush(model, life, opt_box)
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
        # R1/F1:learn 正常返回后唯一 final 保存(存在即拒,绝不
        # 因同名旧文件静默跳过);RUN_INVALID/learn 异常不产 final。
        if status == "OK":
            final_rec = life.finalize(int(rec["actual_steps"]),
                                      int(opt_box["n"]))
            final_ck = out_dir / f"ck{rec['actual_steps']}.zip"
            # 独立核验:冷读存档,对阶段声明/Adam 步/权重摘要复验
            from rl_posctl.skill_p0.p0policy import (
                inspect_p0_archive)
            info = inspect_p0_archive(final_ck)
            problems = []
            if any(info["stage"].get(k) != final_rec.get(k)
                   for k in ("stage", "num_timesteps",
                             "optimizer_steps", "policy_digest",
                             "optimizer_digest")):
                problems.append("冷读阶段元数据与保存记录不符")
            if info["adam_steps"] != int(opt_box["n"]):
                problems.append(
                    f"冷读 Adam 步 {info['adam_steps']} != 实计 "
                    f"{opt_box['n']}")
            if info["policy_digest"] != policy_digest(model):
                problems.append("冷读权重摘要 != 活动模型摘要")
            if problems:
                raise RuntimeError(
                    "final 检查点独立核验失败:" + "; ".join(problems))
            meta["final_ck_verify"] = {
                "path": str(final_ck),
                "stage": info["stage"]["stage"],
                "num_timesteps": info["stage"]["num_timesteps"],
                "optimizer_steps": info["stage"]["optimizer_steps"],
                "adam_steps": info["adam_steps"],
                "policy_digest": info["policy_digest"],
                "verified": True}
        else:
            meta["final_ck_verify"] = {
                "verified": False,
                "reason": f"status={status}:不签 final,"
                          "不产最终档"}
        meta["checkpoint_manifest"] = [
            {"stage": "initial", "target": 0,
             "num_timesteps": 0, "optimizer_steps": 0,
             "policy_digest": init_meta["policy_digest"],
             "optimizer_digest":
                 init_meta["optimizer_digest"]}] + [
            {k: r.get(k) for k in (
                "stage", "target", "num_timesteps", "optimizer_steps",
                "policy_digest", "optimizer_digest")}
            for r in life.saved]
        (out_dir / "rollout_log.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in cb.rollout_log) + "\n", encoding="utf-8")
        (out_dir / "episode_log.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in cb.episode_log) + "\n",
            encoding="utf-8")
        ev_roots = ([Path(x) for x in
                     args.evidence_roots.split(",") if x]
                    if args.evidence_roots else None)
        ev = evidence_kib_settle(ledger, tag=f"train_{run_name}",
                                 roots=ev_roots)
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
