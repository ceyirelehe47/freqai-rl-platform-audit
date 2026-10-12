#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 课程有效性评估(FiniteRepair R2;取代 posctl_curriculum_eval_r1)。

R1 缺陷(reviewer F1/eval_runner 反例):课程名/基线名在 tier/c123
与 replay 全部跑完**之后**才校验(错 baseline 7 次工作叶后才
KeyError;额度 0 也要 9 次工作叶后才 BudgetExceeded;账本入账代码
在函数末段,崩溃即漏账——两次 5,632 步事故根因)。

R2 顺序(fail closed):
  1. 参数校验(课程/基线名/正整数;账本绑定)在任何工作前;拒绝
     写 rejected_* 目录(零额度消耗);
  2. 计算整套运行的上界(episode×步/生成),**先预约后执行**;
  3. RunLog 从启动起原字节保全 stdout/stderr/argv/时序/rc;
  4. 异常 → abandon 保守保留 + 原样抛出;正常 → 实结(实耗 ≤ 预约)。
误差声明:tier 统计带 dp_initial_value(数值)与 err_bound
(error_report 收敛差;qualified = value−err>0)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import rl_posctl.curriculum as _currmod  # noqa: E402
import rl_posctl.env as _envmod  # noqa: E402
from rl_posctl import profiles  # noqa: E402
from rl_posctl.banks import QuotaLedger  # noqa: E402
from rl_posctl.budget import open_task_ledger  # noqa: E402
from rl_posctl.curriculum import (  # noqa: E402
    baseline_policies, error_report, spec_for, tier_validity,
    validate_refinements)
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402

TIERS = ("c4d0", "c4d1", "c4d2", "c4d3")
C123 = ("c1", "c2", "c3")
STEPS_PER_EPISODE = 64 * 2      # 参考 64 + flat 对照 64(有效性口径)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-root", required=True)
    ap.add_argument("--ledger", required=True)
    ap.add_argument("--tier-episodes", type=int, default=4)
    ap.add_argument("--c123-episodes", type=int, default=2)
    ap.add_argument("--replay-episodes", type=int, default=4)
    ap.add_argument("--baseline", action="append", default=None)
    ap.add_argument("--err-refinements", default="81,16,12;161,32,24;"
                    "321,64,40")
    args = ap.parse_args()
    out_root = Path(args.out_root)
    ledger_path = Path(args.ledger)

    # ---- 1) 前置校验(R3:全部参数含 refinements/输出在场,零工作叶;
    #         拒绝留痕,不消耗额度)----
    problems = []
    bases_all = baseline_policies()
    for b in (args.baseline or []):
        if b not in bases_all:
            problems.append(
                f"未知基线 {b!r};可用={sorted(bases_all)}")
    for name in ("tier_episodes", "c123_episodes", "replay_episodes"):
        v = getattr(args, name)
        if not isinstance(v, int) or v <= 0:
            problems.append(f"--{name.replace('_', '-')} 必须为正整数")
    if not ledger_path.exists():
        problems.append(f"任务账本不存在:{ledger_path}")
    # R3-01/F1-d:refinement 语法/规格在**预约之前**解析校验
    # (旧:总预约后才 int() 解析,零工作却留下未闭合预约)
    refinements = None
    try:
        refinements = [
            tuple(int(x) for x in s.split(","))
            for s in args.err_refinements.split(";")]
        refinements = validate_refinements(refinements)
    except ValueError as exc:
        problems.append(f"--err-refinements 非法({args.err_refinements!r}):"
                        f"{exc}")
    # R3-02:输出目录在场先拒绝(不混写旧 run;预约前检查)
    out_dir = out_root / time.strftime("curriculum_eval_%Y%m%dT%H%M%S")
    if out_dir.exists():
        problems.append(f"运行目录已存在,拒绝覆盖输出:{out_dir}")
    if problems:
        d = write_rejection(out_root, "posctl_r2_eval",
                            "; ".join(problems), sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    try:
        # R3-01/F1-a:按账本头部任务身份打开(face 与代码注册表核对)
        led = open_task_ledger(ledger_path)
    except RuntimeError as exc:
        d = write_rejection(out_root, "posctl_r2_eval",
                            f"账本绑定校验失败:{exc}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2

    # ---- 2) 上界计算 + 先预约(授权;崩溃保守保留) ----
    n_base = len(args.baseline) if args.baseline else len(bases_all)
    n_eval_eps = (len(TIERS) * args.tier_episodes
                  + len(C123) * args.c123_episodes)
    n_replay_eps = args.replay_episodes * (1 + n_base)
    eval_ub = (n_eval_eps * STEPS_PER_EPISODE
               + n_replay_eps * 64)          # replay 每 episode 64 步
    gen_ub = n_eval_eps + n_replay_eps       # 重放逐集重建计生成
    eff_before = led.effective()
    try:
        rid = led.reserve("posctl_r2_eval",
                          eval_steps=int(eval_ub),
                          gen_calls=int(gen_ub),
                          episodes=int(gen_ub))
    except Exception as exc:
        # 预约被拒 = 零工作叶前拒绝(额度不足/超限;留痕不消耗额度)
        d = write_rejection(
            out_root, "posctl_r2_eval",
            f"预约被拒(先于任何生成/评估):{exc}",
            sys.argv,
            extra={"ledger_effective": eff_before,
                   "eval_ub": eval_ub, "gen_ub": gen_ub})
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2

    # ---- 3) 运行目录(create-only;预约后创建但工作前,同秒冲突
    #     释放零工作预约后拒绝,不留未闭合占用)----
    try:
        out_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        led.release(rid, "posctl_r2_eval",
                    note=f"输出目录竞争冲突(零工作退还):{exc}")
        d = write_rejection(out_root, "posctl_r2_eval",
                            f"运行目录已存在:{out_dir}", sys.argv)
        print(f"REJECTED {d}/rejection.json", flush=True)
        return 2
    # R3-01:总预约=授权 grant;叶级经 QuotaLedger.draw 划拨,不双计
    quota = QuotaLedger(out_dir / "gen_quota.jsonl", task_ledger=led,
                        grant_rid=rid)
    env0 = int(_envmod.ENV_STEP_COUNT)
    gen0 = int(_currmod.GEN_CALL_COUNT)
    # 执行中硬限(cap 之内的工作才发生;不是事后 commit 才发现)
    _envmod.ENV_STEP_LIMIT = env0 + int(eval_ub)
    _currmod.GEN_CALL_LIMIT = gen0 + int(gen_ub)
    try:
        with RunLog(out_dir, argv=sys.argv,
                    meta_extra={"runner": "posctl_r2_eval",
                                "reserve": {
                                    "eval_ub": eval_ub,
                                    "gen_ub": gen_ub,
                                    "grant_rid": rid}}) as rl:
            result = {"run": "posctl_r2_eval", "tiers": {}, "c123": {},
                      "baselines_c4d2": {},
                      "reserve_upper_bounds": {
                          "eval_steps": eval_ub,
                          "gen_calls": gen_ub}}
            try:
                for course in TIERS:
                    spec = spec_for(course, seed=profiles.MASTER_SEED,
                                    horizon=64,
                                    **profiles.TRAIN_SPEC_OVERRIDES)
                    rep = error_report(spec, refinements=refinements)
                    st = tier_validity(spec,
                                       n_episodes=args.tier_episodes,
                                       quota=quota,
                                       err_bound=rep)
                    st["dp_error_report"] = rep
                    result["tiers"][course] = st
                for course in C123:
                    spec = spec_for(course,
                                    seed=profiles.MASTER_SEED,
                                    horizon=64,
                                    **profiles.TRAIN_SPEC_OVERRIDES)
                    st = tier_validity(spec,
                                       n_episodes=args.c123_episodes,
                                       quota=quota)
                    result["c123"][course] = st

                # 参考 vs 基线(c4d2 训练面;同 seed 域重建=生成计调用;
                # R3:调用必计、成功才结 episode)
                from rl_posctl.curriculum import reference_action
                from rl_posctl.env import HybridPositionEnv
                from rl_posctl.evalreport import (
                    run_policy, summarize)
                from rl_posctl.experiments import train_course_spec

                spec = train_course_spec(profiles.TRAIN_COURSE,
                                         profiles.MASTER_SEED)

                def replay_stats(policy_fn):
                    tot, rows = 0.0, []
                    for i in range(args.replay_episodes):
                        quota.record(
                            gen_calls=1, bank="posctl_c4d2_replay",
                            domain="eval")
                        prices, feats, _ = _currmod.generate_episode(
                            spec, 5000 + i)
                        quota.record_episode(bank="posctl_c4d2_replay",
                                             domain="eval")
                        env = HybridPositionEnv(
                            features=feats, prices=prices, fee=spec.fee,
                            window_size=1)
                        infos = run_policy(env, policy_fn)
                        s = summarize(infos)
                        tot += (s["net_log_return"] or 0.0)
                        rows.append({
                            "episode": i,
                            "net_log": (s["net_log_return"] if
                                        s["net_log_return_valid"]
                                        else None),
                            "fees": s["total_fees"],
                            "failure": s["economic_failure"]})
                    return tot, rows

                def ref(row, w, sl):
                    return reference_action(spec, row, w, steps_left=sl)

                bases = ({k: bases_all[k] for k in args.baseline}
                         if args.baseline else bases_all)
                ref_tot, ref_rows = replay_stats(ref)
                result["baselines_c4d2"]["reference"] = {
                    "total_net_log": ref_tot, "rows": ref_rows}
                for name, fn in bases.items():
                    tot, _ = replay_stats(fn)
                    result["baselines_c4d2"][name] = {
                        "total_net_log": tot}
            except BaseException as exc:
                # 未划拨余额保守保留;已划拨实测已入账(不混类)
                led.abandon(rid, "posctl_r2_eval",
                            note=f"运行异常中止(保守保留余额):"
                                 f"{exc!r}")
                raise

            # ---- 实结(实际总量 ≤ 授权;已划拨部分不重复入账) ----
            eval_actual = int(_envmod.ENV_STEP_COUNT) - env0
            gen_actual = quota.gen_calls
            episodes_actual = quota.episodes
            led.commit(rid, "posctl_r2_eval",
                       eval_steps=eval_actual,
                       gen_calls=gen_actual,
                       episodes=episodes_actual)
            result["env_steps_actual"] = eval_actual
            result["gen_quota_cum"] = {
                "gen_calls": quota.gen_calls,
                "episodes": quota.episodes}
            result["budget_snapshot"] = led.snapshot()
            (out_dir / "posctl_r2_eval.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=1),
                encoding="utf-8")
            print(json.dumps(
                {k: {"dp_initial_value": v["dp_initial_value"],
                     "qualified": v.get("qualified")}
                 for k, v in result["tiers"].items()},
                ensure_ascii=False, indent=1))
            rl.rc = 0
            return 0
    finally:
        # 进程内守卫不外泄(套件/后续运行按自身授权重设)
        _envmod.ENV_STEP_LIMIT = None
        _currmod.GEN_CALL_LIMIT = None


if __name__ == "__main__":
    raise SystemExit(main())
