#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 confirmation + horizon-check + 行为门/经济门/bootstrap。

流程(顺序固定,一次执行):
  1. 核对六个最终 checkpoint 在场且与 run_record 一致 → 写确认锁;
  2. 生成 confirmation/hz32/hz96 bank(此前锁定);
  3. 六最终模型 × {确定性,采样} × confirmation bank 逐 episode 评估;
     基线(flat/±1/±0.5)+ sign 规则 + 数值参考同 bank 重放;
  4. 行为门(反事实网格,独立积分/原子质量 + 固定采样核对);
  5. horizon-check:H=32/96 分组评估 + 恒时间模板反例(输入钳制);
  6. 经济门与配对 bootstrap(pair 内镜像聚合 → 三模型聚合,
     10,000 次/项);逐 seed 与臂级结论;
  7. 分层出口汇总(工程/表示/题目/学习/期限/正式资格 NOT_RUN)。

用法:
    python psc_p0_confirm.py [--ledger <jsonl>]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import numpy as np
import torch as th

from rl_posctl.curriculum import reference_policy
from rl_posctl.runlog import RunLog, write_rejection  # noqa: E402
from rl_posctl.skill_p0.p0banks import (  # noqa: E402
    bank_ref_sha, build_p0_bank, load_p0_bank)
from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv  # noqa: E402
from rl_posctl.skill_p0.p0eval import (  # noqa: E402
    behavior_gate, bootstrap_results_all_valid_positive,
    constant_action_fn, eval_on_bank, hold_action_fn, make_env,
    model_action_fn, pair_advantage_matrix, paired_bootstrap,
    reference_action_fn, sign_action_fn)
from rl_posctl.skill_p0.p0policy import (  # noqa: E402
    expected_main_checkpoint, load_p0_model, p0_code_digest,
    verify_final_checkpoint,  # noqa: F401  R1 自洽层(R2 槽位绑定在其上)
    verify_final_checkpoint_for_slot)
from rl_posctl.skill_p0.p0run import (  # noqa: E402
    RUNS_DIR, evidence_kib_settle, make_bootstrap_meter,
    make_sampler_meter, open_ledger)
from rl_posctl.skill_p0.p0spec import (  # noqa: E402
    ARMS, BOOTSTRAP_DRAWS, C1_HORIZON, PPO_SEEDS, p0_seed)
from rl_posctl.skill_p0.p0task import BASELINE_NAMES, baseline_fns

FINAL_STEP = 131_072


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ledger", default=None)
    ap.add_argument("--out", default=str(RUNS_DIR / "confirm"))
    args = ap.parse_args()
    th.set_num_threads(1)
    out_root = Path(args.out)
    gate_path = out_root / "confirm_report.json"
    if gate_path.exists():
        print(f"已有 confirm_report.json:{gate_path}", file=sys.stderr)
        return 2
    # ---- 1. 六最终 checkpoint 在场 + 槽位绑定核验(R1/F1 自洽
    # + R2/C1 预期用途/完成度绑定:期望来自 p0spec 冻结计划与在场
    # train bank 原件,不取自待验 record 自述)在任何账本打开/
    # bank 生成/评估资源之前。旧 pre-update 档、RUN_INVALID、
    # 工程 smoke 冒充 main、放错槽位、重复模型身份、过期代码/
    # 错输入、缺字段、零更新/少步数、错误优化器证据在此拒绝,
    # 不消费任何资源。
    train_bank_path = RUNS_DIR / "banks" / "train" / "train_bank.json"
    if not train_bank_path.exists():
        write_rejection(
            out_root, "psc_p0_confirm",
            f"缺 train bank 原件,无法独立确定输入身份:"
            f"{train_bank_path}", sys.argv)
        return 2
    expected_bank_ref = bank_ref_sha(train_bank_path)
    finals = {}
    verifications = {}
    seen_sha: dict = {}
    for arm in ARMS:
        for seed in PPO_SEEDS:
            rd = RUNS_DIR / "main" / f"{arm}_{seed}"
            rec_p = rd / "run_record.json"
            ck = rd / f"ck{FINAL_STEP}.zip"
            if not rec_p.exists() or not ck.exists():
                write_rejection(out_root, "psc_p0_confirm",
                                f"缺最终模型:{rd}", sys.argv)
                return 2
            run_record = json.loads(
                rec_p.read_text(encoding="utf-8"))
            expected = expected_main_checkpoint(
                arm, seed, bank_ref=expected_bank_ref)
            try:
                verifications[f"{arm}_{seed}"] = (
                    verify_final_checkpoint_for_slot(
                        ck, run_record, expected))
            except RuntimeError as exc:
                write_rejection(
                    out_root, "psc_p0_confirm",
                    f"最终检查点槽位绑定核验失败(未消费资源):"
                    f"{arm}_{seed}\n{exc}", sys.argv)
                return 2
            sha = hashlib.sha256(ck.read_bytes()).hexdigest()
            if sha in seen_sha:
                write_rejection(
                    out_root, "psc_p0_confirm",
                    f"重复模型身份:{arm}_{seed} 与 "
                    f"{seen_sha[sha]} 为同一文件(sha256={sha});"
                    "同一检查点不得重复占用多个 main 槽位",
                    sys.argv)
                return 2
            seen_sha[sha] = f"{arm}_{seed}"
            finals[f"{arm}_{seed}"] = {
                "path": str(ck),
                "sha256": sha,
                "run_record": str(rec_p)}
    lock = {
        "locked_utc": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).isoformat(),
        "final_checkpoints": finals,
        "final_ck_verified": {
            k: {kk: v[kk] for kk in (
                "stage", "adam_steps", "policy_digest",
                "optimizer_digest", "sha256", "slot_bound")}
            for k, v in verifications.items()},
        "slot_binding": {
            "train_bank_path": str(train_bank_path),
            "train_bank_sha256": expected_bank_ref,
            "per_slot_expected": {
                k: v.get("expected")
                for k, v in verifications.items()},
        },
        "analysis_code_digest": p0_code_digest(),
    }
    lock_path = RUNS_DIR / "psc_p0_confirm_lock.json"
    if lock_path.exists():
        print(f"确认锁已存在(一次性):{lock_path}", file=sys.stderr)
        return 2
    ledger = open_ledger(args.ledger)
    meter = make_sampler_meter(ledger, "confirm")
    bmeter = make_bootstrap_meter(ledger, "confirm")
    # R1/F3a:原始行/逐 pair 输入先于聚合落盘(create-only JSONL;
    # 每 episode/每 bootstrap 输入即时 append + flush,中断不丢)。
    raw_dir = out_root / "raw"
    if raw_dir.exists():
        print(f"raw 目录已存在(create-only):{raw_dir}",
              file=sys.stderr)
        return 2
    raw_dir.mkdir(parents=True)

    def _raw_writer(name: str):
        fh = (raw_dir / f"{name}.jsonl").open(
            "x", encoding="utf-8")

        def sink(row: dict) -> None:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            fh.flush()
        return sink, fh
    with RunLog(out_root, meta_extra={"runner": "psc_p0_confirm"}):
        lock_path.write_text(json.dumps(lock, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
        # ---- 2. 确认/期限 bank(解锁后生成)
        banks = {}
        for purpose in ("confirm", "hz32", "hz96"):
            rec = build_p0_bank(
                purpose, runs_dir=RUNS_DIR, task_ledger=ledger,
                out_dir=RUNS_DIR / "banks" / purpose,
                force_unlock=True)
            banks[purpose] = rec
        # ---- 3. confirmation 评估
        items = load_p0_bank(
            RUNS_DIR / "banks" / "confirm" / "confirm_bank.json")
        model_rows = {}
        behavior = {}
        for name in sorted(finals):
            arm = name.split("_")[0]
            seed = int(name.split("_")[1])
            train_rec = json.loads(Path(
                finals[name]["run_record"]).read_text(
                encoding="utf-8"))
            if train_rec.get("status") != "OK":
                model_rows[name] = None
                behavior[name] = None
                continue
            env = P0EpisodeBankEnv(items)
            model = load_p0_model(
                finals[name]["path"], env, arm=arm,
                bank_ref=train_rec["bank_ref"], horizon=C1_HORIZON)
            rows = {}
            for mode in ("deterministic", "sampled"):
                if mode == "sampled":
                    th.manual_seed(p0_seed("evalsample", seed, 2, 1))
                sink_m, fh_m = _raw_writer(
                    f"model_{name}_{mode}")
                rows[mode] = eval_on_bank(
                    items, model_action_fn(
                        model, deterministic=(mode
                                              == "deterministic")),
                    ledger=ledger,
                    tag=f"confirm:{name}:{mode}",
                    raw_sink=sink_m)
                fh_m.close()
            model_rows[name] = rows
            behavior[name] = behavior_gate(
                model, meter=meter, sampled_check=12)
        baselines = {}
        for bname, fn in baseline_fns().items():
            sink_b, fh_b = _raw_writer(f"baseline_{bname}")
            baselines[bname] = eval_on_bank(
                items, fn, ledger=ledger,
                tag=f"confirm:base:{bname}", raw_sink=sink_b)
            fh_b.close()
        spec = __import__(
            "rl_posctl.skill_p0.p0spec", fromlist=[""]).c1_spec(
            "confirm", 0)
        ref = reference_policy(spec)
        sink_r, fh_r = _raw_writer("baseline_reference")
        baselines["reference"] = eval_on_bank(
            items, reference_action_fn(ref, spec),
            ledger=ledger, tag="confirm:base:reference",
            raw_sink=sink_r)
        fh_r.close()
        sink_s, fh_s = _raw_writer("baseline_sign_rule")
        baselines["sign_rule"] = eval_on_bank(
            items, sign_action_fn(), ledger=ledger,
            tag="confirm:base:sign", raw_sink=sink_s)
        fh_s.close()
        # ---- 4/6. 逐 seed 经济门 + 臂级 bootstrap
        per_seed = {}
        for name in sorted(model_rows):
            if model_rows[name] is None:
                per_seed[name] = {"valid": False,
                                  "reason": "训练 RUN_INVALID"}
                continue
            arm = name.split("_")[0]
            seed_rec = {"behavior": behavior[name]}
            econ = {}
            for mode in ("deterministic", "sampled"):
                vals = [r["net_log_return"] for r in
                        model_rows[name][mode]
                        if r["net_log_return"] is not None]
                fail = sum(1 for r in model_rows[name][mode]
                           if r["economic_failure"])
                econ[mode] = {
                    "mean": float(np.mean(vals)) if vals else None,
                    "n_valid": len(vals), "n_failure": fail}
            seed_rec["economics"] = econ
            seed_rec["no_economic_failure"] = all(
                v["n_failure"] == 0 for v in econ.values())
            beats = {}
            for bname in BASELINE_NAMES:
                per_mode = {}
                for mode in ("deterministic", "sampled"):
                    a2 = pair_advantage_matrix(
                        {name: model_rows[name][mode]},
                        baselines[bname])
                    per_mode[mode] = (
                        float(np.mean(a2["pair_values"]))
                        if a2.get("valid") else None)
                beats[bname] = per_mode
            seed_rec["beats_baselines_both_modes"] = bool(
                all(all(v[m] is not None and v[m] > 0
                        for m in ("deterministic", "sampled"))
                    for v in beats.values()))
            seed_rec["paired_mean_vs_baselines"] = beats
            seed_rec["seed_gate_pass"] = bool(
                seed_rec["behavior"] and
                seed_rec["behavior"].get("pass")
                and seed_rec["beats_baselines_both_modes"])
            per_seed[name] = seed_rec
        arm_level = {}
        for arm in ARMS:
            names = [f"{arm}_{s}" for s in PPO_SEEDS]
            ok = [n for n in names
                  if per_seed.get(n, {}).get("seed_gate_pass")]
            no_fail = all(
                per_seed.get(n, {}).get("no_economic_failure")
                is True for n in names)
            boot = {}
            # 计划口径:逐模式分别 bootstrap(确定性/采样两套都须
            # 下界>0);pair 值 = 3 模型 × 2 端点平均的逐基线差。
            # R2/C2:矩阵必须拿到**全部预注册 seed 行**;缺失种子
            # 的 None 行在配对前拒绝(不得宽松遍历在场结果)。
            for bname in BASELINE_NAMES:
                boot[bname] = {}
                for mode in ("deterministic", "sampled"):
                    mat = pair_advantage_matrix(
                        {n: model_rows.get(n, {}).get(mode)
                         if isinstance(model_rows.get(n), dict)
                         else model_rows.get(n)
                         for n in names},
                        baselines[bname])
                    if not mat.get("valid"):
                        boot[bname][mode] = {
                            "valid": False,
                            "reason": mat.get("reason")}
                        continue
                    sink_p, fh_p = _raw_writer(
                        f"bootstrap_{arm}_{bname}_{mode}")
                    boot[bname][mode] = paired_bootstrap(
                        mat["pair_values"], seed=p0_seed(
                            "bootstrap", 0, ord(arm),
                            1 + 2 * list(BASELINE_NAMES).index(bname)
                            + (0 if mode == "deterministic" else 1)),
                        draws=BOOTSTRAP_DRAWS, meter=bmeter,
                        raw_sink=sink_p)
                    fh_p.close()
            arm_level[arm] = {
                "n_seed_gate_pass": len(ok),
                "no_economic_failure_all_seeds": no_fail,
                "bootstrap_vs_baselines": boot,
                "arm_gate_pass": bool(
                    len(ok) >= 2 and no_fail
                    and bootstrap_results_all_valid_positive(
                        boot))}
        # ---- 5. horizon-check(R2/C2:12 次 H=32/96 模型评估
        # 实际调用全部接通 raw_sink;恒时间探针实际调用接通
        # raw_sink_factory,不再只留未使用的可选参数)
        horizon = {}
        for purpose in ("hz32", "hz96"):
            items_h = load_p0_bank(
                RUNS_DIR / "banks" / purpose / f"{purpose}_bank.json")
            per_model = {}
            for name in sorted(finals):
                if model_rows.get(name) is None:
                    per_model[name] = None
                    continue
                arm = name.split("_")[0]
                seed = int(name.split("_")[1])
                train_rec = json.loads(Path(
                    finals[name]["run_record"]).read_text(
                    encoding="utf-8"))
                env = P0EpisodeBankEnv(items_h)
                model = load_p0_model(
                    finals[name]["path"], env, arm=arm,
                    bank_ref=train_rec["bank_ref"],
                    horizon=C1_HORIZON)
                th.manual_seed(p0_seed("evalsample", seed, 3, 1))
                sink_h, fh_h = _raw_writer(f"{purpose}_{name}")
                try:
                    per_model[name] = eval_on_bank(
                        items_h, model_action_fn(
                            model, deterministic=False),
                        ledger=ledger, tag=f"{purpose}:{name}",
                        raw_sink=sink_h)
                finally:
                    fh_h.close()
            # 恒时间模板反例:把 remaining 输入钳制在初始值
            # (R2/C2:探针逐 episode 原件先于聚合落盘,
            # 含 pair/variant/模型/模式/成本/失败身份)
            probe_fhs = []

            def _probe_sink_factory(nm, _p=purpose, _fhs=probe_fhs):
                sink_p, fh_p = _raw_writer(
                    f"hzprobe_{_p}_{nm}")
                _fhs.append(fh_p)
                return sink_p

            try:
                probe = constant_time_template_probe(
                    finals, items_h, ledger, purpose,
                    raw_sink_factory=_probe_sink_factory)
            finally:
                for fh_p in probe_fhs:
                    fh_p.close()
            horizon[purpose] = {"per_model": {
                k: (None if v is None else float(np.mean(
                    [r["net_log_return"] for r in v
                     if r["net_log_return"] is not None]))
                    if any(r["net_log_return"] is not None
                           for r in v) else None)
                for k, v in per_model.items()},
                "constant_time_template_probe": probe}
        report = {
            "banks": banks, "per_seed": per_seed,
            "arm_level": arm_level, "horizon": horizon,
            "baselines_means": {
                k: float(np.mean([r["net_log_return"]
                                  for r in v
                                  if r["net_log_return"] is not None]))
                for k, v in baselines.items()
                if any(r["net_log_return"] is not None
                       for r in v)},
            "finals": finals,
        }
        b_established = any(
            arm_level[a]["arm_gate_pass"] for a in ARMS)
        report["layered_exit"] = {
            "c1_learning_evidence_established": b_established,
            "formal_qualification": "NOT_RUN",
            "c2_c3_c4_teaching": "NOT_RUN",
            "horizon_transfer": (
                "MIXED" if all(
                    isinstance(h["per_model"], dict)
                    for h in horizon.values()) else "NOT_RUN"),
        }
        ev = evidence_kib_settle(ledger, tag="confirm")
        report["evidence_kib"] = ev
        gate_path.write_text(json.dumps(report, ensure_ascii=False,
                                        indent=1), encoding="utf-8")
        print(json.dumps({
            "arm_level": {a: arm_level[a]["arm_gate_pass"]
                          for a in ARMS},
            "per_seed_pass": {k: v.get("seed_gate_pass")
                              for k, v in per_seed.items()}},
            ensure_ascii=False, indent=1))
    return 0


def constant_time_template_probe(finals, items_h, ledger, purpose,
                                 raw_sink_factory=None):
    """恒时间模板反例:remaining 维钳制为 episode 初始值(其余观察
    原样),确定性重放对照——期限模板依赖诊断(不改题、不训新模)。

    取 2 个最终模型诊断样本;R1/F2:每模型先按步数上界唯一预约
    eval_steps,重放后按实际结算(旧版逐 episode 先执行后预约);
    R2/C2:main 实际调用接通 raw_sink_factory(不再只留未使用的
    可选参数);逐 episode 原件先于聚合落盘,行携带 pair/variant/
    模型/模式/bank/成本/失败身份(不只留均值或无身份收益数)。"""
    from rl_posctl.evalreport import summarize
    results = {}
    ub = sum(max(0, len(it[0]) - 1) for it in items_h)
    for name in sorted(finals)[:2]:
        arm = name.split("_")[0]
        rec = json.loads(Path(
            finals[name]["run_record"]).read_text(encoding="utf-8"))
        env_m = P0EpisodeBankEnv(items_h[:1])
        model = load_p0_model(
            finals[name]["path"], env_m, arm=arm,
            bank_ref=rec["bank_ref"], horizon=C1_HORIZON)
        sink = (raw_sink_factory(name)
                if raw_sink_factory else None)
        rid = ledger.reserve(
            f"hzprobe:{purpose}:{name}", eval_steps=int(ub))
        rows = []
        observed = 0
        try:
            for i, item in enumerate(items_h):
                env = make_env(item)
                obs, _ = env.reset()
                fixed_remaining = float(obs[6])
                done = False
                infos = []
                while not done:
                    o = obs.copy()
                    o[6] = fixed_remaining     # 时间维钳制反例
                    act, _ = model.predict(
                        o[None, :], deterministic=True)
                    obs, r, term, trunc, info = env.step(act[0])
                    infos.append(info)
                    done = term or trunc
                summ = summarize(infos)
                observed += int(summ["n_steps"])
                row = {"episode": i,
                       "model": name,
                       "mode": "constant_time_template",
                       "bank_purpose": purpose,
                       "pair_index": item[2]["pair_index"],
                       "variant": item[2]["variant"],
                       "net_log_return": summ["net_log_return"],
                       "n_steps": summ["n_steps"],
                       "n_failure": int(summ["economic_failure"]),
                       "summary": summ}
                if sink is not None:
                    sink(row)
                rows.append(row)
        except BaseException as exc:
            ledger.abandon(rid, f"hzprobe:{purpose}:{name}", note=(
                "期限探针异常中断,保守保留预约;"
                f"observed_steps={observed},ub={int(ub)},"
                f"exc={exc!r}"))
            raise
        ledger.commit(rid, f"hzprobe:{purpose}:{name}",
                      eval_steps=int(observed))
        results[name] = rows
    return results


if __name__ == "__main__":
    raise SystemExit(main())
