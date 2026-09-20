# -*- coding: utf-8 -*-
"""G5c:G5b 修复结论的预算匹配机制对照(GOAL G5 授权;非正式诊断)。

G5b 的 standard vs margin 双臂在损失形态与优化预算两维共变
(30ep/3e-4 vs 300ep/1e-3),不能区分「hinge 形态因果」与
「充分优化的 BC 因果」。本对照在**独立开发坐标**(全新命名空间/
种子族)上补齐预算匹配对照:

- C0_std30:  加权 CE 30ep/3e-4(= G5b 失败对照同预算,失败复现)
- C1_std300: 加权 CE 300ep/1e-3(**预算匹配**——决定性对照)
- C2_margin300: hinge margin 300ep/1e-3/m2.0(= B2 同配方复现)

每臂 3 seeds;同 27,552 steps 分段微调;判定规则与 G5b 逐字相同
(preserved: drop≤0.05 ≥2/3;selective: det gap ≥ 0.5×bc_gap
≥2/3;sanity: C0 复现摧毁 ≥2/3)。

预注册读法(预测无关):
- C1 preserved ≈ C2 => 因果变量是「BC 优化充分性/边际宽度」,
  hinge 非必要手段;G5b 干预归因收窄;
- C1 失败且边际未拉宽而 C2 成功 => CE 在该预算下不能达宽度,
  hinge 作为「高效达宽」手段成立;
- C1 边际拉宽但仍失败 => 宽度单独不足,hinge 结构另有作用。

非正式声明:不构成正式 Stage 2.6.2 输入;official namespace/seed
零接触;ppo_final_eval_262/qualification_* 零接触;正式使用须
G4 有效资格与原训练门禁。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import curriculum261_eval_config
from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_g5 import (
    G5_FAMILY, actor_state_hash, critic_state_hash,
)
from rl_curriculum.ppo262_g5b import (
    _CKPT_TAGS, _MARGIN, _PAIRS_EVAL, _PAIRS_TRAIN, _RUNGS_EVAL,
    _RUNGS_TRAIN, _STEPS_FINETUNE, _bank_eval, _gen_bank, _kl,
    _match, bc_train_actor_margin, g5b_finetune_run, margin_stats,
)
from rl_curriculum.ppo262_r2_train import (
    R2CheckpointStore, bc_train_actor_weighted, build_diagnosed_ppo2,
    collect_family_bc_dataset,
)
DIAG262G5C_ITERATION_ID = "s262_diag_g5c"
DIAG262G5C_NS_PREFIX = "diag262g5c"
G5C_SEEDS = (29301, 29302, 29303)
G5C_BASE_CANDIDATE = "cand_a_center"

DIAG262G5C_NAMESPACES = tuple(
    f"{DIAG262G5C_NS_PREFIX}_{'bc_train' if k < 3 else 'bc_eval'}"
    f"_c3_s{k % 3}" for k in range(6))


def _gen_bank(namespace: str, rungs, pairs: int, base: int,
              rung_params):
    keys = [EpisodeKey(namespace, G5_FAMILY, r, base + p, v)
            for r in rungs for p in range(pairs)
            for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=rung_params,
        derive_seed_fn=derive262g5c_seed)


#: 三臂(loss, epochs, lr, margin):C1 与 C2 预算逐字相同。
G5C_ARMS = {
    "C0_std30": {"loss": "ce", "epochs": 30, "lr": 3e-4},
    "C1_std300": {"loss": "ce", "epochs": 300, "lr": 1e-3},
    "C2_margin300": {"loss": "hinge", "epochs": 300, "lr": 1e-3,
                     "margin": _MARGIN},
}

_BUDGET_NOTE = (
    "G5b 的 B0/B2 双臂共变(损失形态×预算);C1_std300 与 "
    "C2_margin300 预算逐字相同(300ep/1e-3),隔离损失形态;"
    "C0_std30 与 G5b B0 同预算,失败复现 sanity。")


def derive262g5c_seed(namespace: str, family: str, rung: str,
                      pair_index: int, attempt: int) -> int:
    if namespace not in DIAG262G5C_NAMESPACES:
        raise ValueError(
            f"seed namespace {namespace!r} 不在 "
            f"{DIAG262G5C_ITERATION_ID} 诊断集合")
    payload = json.dumps(
        ["stage2_6_2", DIAG262G5C_ITERATION_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


def build_g5c_plan() -> dict[str, Any]:
    src = Path(__file__).read_bytes()
    return {
        "format": "cur261-ppo262-g5c-diagnostic-plan-v1",
        "iteration": DIAG262G5C_ITERATION_ID,
        "non_formal_declaration": (
            "本诊断不构成正式 Stage 2.6.2 输入;不进入 official "
            "namespace/seed;不触碰 ppo_final_eval_262/qualification_*"),
        "family": G5_FAMILY,
        "rationale": (
            "G5b 因果范围审查(route_c_stage2_6_2_g5b_causal_scope_"
            "review.md):standard vs margin 双臂损失形态与预算共变,"
            "干预归因超界;本对照补预算匹配 CE 臂。"),
        "arms": {k: dict(v) for k, v in G5C_ARMS.items()},
        "budget_note": _BUDGET_NOTE,
        "fine_tune": {"steps": _STEPS_FINETUNE,
                      "segments": 12, "rehearsal": False},
        "seeds": list(G5C_SEEDS),
        "bank_spec": {
            "train_per_slot": {"rungs": list(_RUNGS_TRAIN),
                               "pairs_per_rung": _PAIRS_TRAIN,
                               "pair_base_rule": "slot*32"},
            "eval_per_slot": {"rungs": list(_RUNGS_EVAL),
                              "pairs_per_fr": _PAIRS_EVAL,
                              "pair_base_rule": "256 + slot*32"},
        },
        "decision_rule": (
            "与 G5b 逐字相同:preserved = drop<=0.05 于 >=2/3 seeds;"
            "selective = det_behavior_gap >= 0.5*bc_std_gap 于 >=2/3;"
            "sanity = C0_std30 摧毁复现(drop>0.1)于 >=2/3"),
        "g5c_code_sha256": hashlib.sha256(src).hexdigest(),
    }


def lock_g5c_plan(out_dir: Path) -> tuple[Path, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    plan = build_g5c_plan()
    digest = "g5cdp-" + hashlib.sha256(json.dumps(
        plan, sort_keys=True, ensure_ascii=False,
        default=float).encode("utf-8")).hexdigest()
    plan["g5c_plan_digest"] = digest
    path = out_dir / "g5c_plan.json"
    if path.is_file():
        raise RuntimeError("g5c_plan.json 已存在(一次且仅一次)")
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False)
                    + "\n", encoding="utf-8")
    return path, digest


def load_g5c_plan(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "g5c_plan.json"
    if not path.is_file():
        raise RuntimeError("g5c_plan.json 缺失(先 lock)")
    plan = json.loads(path.read_text(encoding="utf-8"))
    stored = plan.get("g5c_plan_digest")
    core = {k: v for k, v in plan.items() if k != "g5c_plan_digest"}
    recomputed = "g5cdp-" + hashlib.sha256(json.dumps(
        core, sort_keys=True, ensure_ascii=False,
        default=float).encode("utf-8")).hexdigest()
    if stored != recomputed \
            or plan.get("g5c_code_sha256") != build_g5c_plan()[
                "g5c_code_sha256"]:
        raise RuntimeError("g5c plan 校验失败(digest 或代码身份漂移)")
    return plan


def run_g5c(out_dir: Path) -> dict[str, Any]:
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_r2_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )

    out_dir = Path(out_dir)
    plan = load_g5c_plan(out_dir)
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg261 = curriculum261_eval_config()
    base_cfg = dict(PPO262_CANDIDATES[G5C_BASE_CANDIDATE])
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "format": "cur261-ppo262-g5c-diagnostic-results-v1",
        "iteration": DIAG262G5C_ITERATION_ID,
        "g5c_plan_digest": plan["g5c_plan_digest"],
        "arms": {}, "per_seed_bc": {}, "sanity": {},
    }

    def _eval(model, eval_bank, adapter):
        return _bank_eval(model, eval_bank, rung_params, thresholds,
                          adapter)

    for slot, seed in enumerate(G5C_SEEDS):
        train_bank = _gen_bank(
            f"{DIAG262G5C_NS_PREFIX}_bc_train_c3_s{slot}",
            _RUNGS_TRAIN, _PAIRS_TRAIN, slot * 32, rung_params)
        eval_bank = _gen_bank(
            f"{DIAG262G5C_NS_PREFIX}_bc_eval_c3_s{slot}",
            _RUNGS_EVAL, _PAIRS_EVAL, 256 + slot * 32, rung_params)
        dtr = collect_family_bc_dataset(
            train_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        dev = collect_family_bc_dataset(
            eval_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        adapter = _identity_adapter(dtr)

        bc_results: dict[str, Any] = {}
        bc_models: dict[str, Any] = {}
        bc_states: dict[str, Any] = {}
        for arm_name, arm in G5C_ARMS.items():
            from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
            env = CurriculumMultiEpisodeEnv(train_bank)
            model = build_diagnosed_ppo2(base_cfg, seed, env)
            actor_before = actor_state_hash(model)
            critic_before = critic_state_hash(model)
            if arm["loss"] == "ce":
                info = bc_train_actor_weighted(
                    model, dtr, epochs=arm["epochs"], lr=arm["lr"],
                    adapter=adapter, rng_seed=seed, class_weighted=True)
            else:
                info = bc_train_actor_margin(
                    model, dtr, epochs=arm["epochs"], lr=arm["lr"],
                    adapter=adapter, rng_seed=seed,
                    margin=arm["margin"])
            bc_results[arm_name] = {
                "arm_spec": dict(arm),
                "actor_changed": actor_before != actor_state_hash(model),
                "critic_unchanged": critic_before == critic_state_hash(
                    model),
                "heldout": _match(model, dev, adapter),
                "margin_stats": margin_stats(model, dev, adapter),
                "bank_eval": _eval(model, eval_bank, adapter),
                "train_tail": info["history"][-1],
            }
            bc_models[arm_name] = model
            bc_states[arm_name] = {k: v.clone() for k, v in
                                   model.policy.state_dict().items()}
            bal = bc_results[arm_name]["heldout"]["balanced_accuracy"]
            mgn = bc_results[arm_name]["margin_stats"][
                "mean_abs_diff"]
            print(f"[g5c] BC {arm_name} seed={seed} "
                  f"bal={bal:.3f} margin={mgn:.2f}", flush=True)
        results["per_seed_bc"][str(seed)] = bc_results

        for arm_name in G5C_ARMS:
            store = R2CheckpointStore(
                models_dir, f"g5c_{arm_name}_seed{seed}",
                family=G5_FAMILY, arm=f"g5c:{arm_name}", seed=seed,
                expected_tags=_CKPT_TAGS)
            run = g5b_finetune_run(
                train_bank, config=base_cfg, model_seed=seed,
                bc_state=bc_states[arm_name], adapter=adapter,
                store=store, run_label=f"g5c/{arm_name}/seed{seed}",
                rehearsal=False, rehearsal_dataset=dtr, rng_seed=seed)
            ft = run["model"]
            rec = {
                "arm_spec": dict(G5C_ARMS[arm_name]),
                "heldout_before": bc_results[arm_name]["heldout"][
                    "balanced_accuracy"],
                "heldout_after": _match(ft, dev, adapter)[
                    "balanced_accuracy"],
                "margin_before": bc_results[arm_name]["margin_stats"],
                "margin_after": margin_stats(ft, dev, adapter),
                "kl_ft_to_bc": _kl(ft, bc_models[arm_name], dev,
                                   adapter),
                "bank_eval": _eval(ft, eval_bank, adapter),
                "run_pass": run["pass"],
                "n_update_records": run["n_update_records"],
                "checkpoint_verification": run["checkpoint_verification"],
            }
            rec["drop"] = (rec["heldout_before"]
                           - rec["heldout_after"])
            results["arms"].setdefault(arm_name, {})[str(seed)] = rec
            print(f"[g5c] {arm_name} seed={seed} "
                  f"bal {rec['heldout_before']:.3f}->"
                  f"{rec['heldout_after']:.3f} drop={rec['drop']:.3f} "
                  f"kl={rec['kl_ft_to_bc']:.4f} "
                  f"margin={rec['margin_after']['mean_abs_diff']:.2f}",
                  flush=True)
            del ft

    stats, verdicts = {}, {}
    bc_gap = float(np.mean([
        r["C0_std30"]["bank_eval"]["behavior"].get("det_behavior_gap")
        for r in results["per_seed_bc"].values()
        if r["C0_std30"]["bank_eval"]["behavior"].get(
            "det_behavior_gap") is not None]))
    for a, seeds in results["arms"].items():
        drops = [x["drop"] for x in seeds.values()]
        gaps = [x["bank_eval"]["behavior"].get("det_behavior_gap")
                for x in seeds.values()]
        preserved = sum(d <= 0.05 for d in drops) >= 2
        selective = (sum(g is not None and g >= 0.5 * bc_gap
                         for g in gaps) >= 2)
        stats[a] = {"drops": drops, "det_behavior_gaps": gaps,
                    "bc_std30_mean_gap": bc_gap}
        verdicts[a] = {"preserved": preserved,
                       "preserved_and_selective": preserved and selective}
    results["sanity"] = {
        "c0_control_reproduced_destroy":
            sum(d > 0.1 for d in stats["C0_std30"]["drops"]) >= 2}
    results["arm_stats"] = stats
    results["verdicts"] = verdicts
    results["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())
    (out_dir / "g5c_diagnostic_results.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False, default=str)
        + "\n", encoding="utf-8")
    print(json.dumps({"verdicts": verdicts,
                      "sanity": results["sanity"]},
                     ensure_ascii=False))
    return results


def _identity_adapter(dtr):
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    return ObsAdapter.identity(dtr["X"].shape[1])


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    lk = sub.add_parser("lock")
    lk.add_argument("--out-dir", type=Path, required=True)
    rn = sub.add_parser("run")
    rn.add_argument("--out-dir", type=Path, required=True)
    args = ap.parse_args(argv)
    if args.cmd == "lock":
        path, digest = lock_g5c_plan(args.out_dir)
        print(f"locked {path} digest={digest}")
        return 0
    run_g5c(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
