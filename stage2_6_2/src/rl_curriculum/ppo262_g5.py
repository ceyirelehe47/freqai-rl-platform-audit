# -*- coding: utf-8 -*-
"""Stage 2.6.2 — G5 诊断:C3 Branch D 的 PPO 更新损伤机制(GOAL G5)。

非正式诊断合同:**不构成正式 Stage 2.6.2 输入**;不进入 official
namespace/seed 空间;不触碰 ppo_final_eval_262 / qualification_*。

问题锚(r2 诊断,s262_diag_r2_1):C3 = Branch D —— BC 三 seed 全部
学会成本选择性(bal acc 0.866-0.923),真实 PPO fine-tune 三 seed
全部摧毁(drop 0.246-0.498)。已排除假说(不重走):表示能力
(supervised 全族可学)、预处理(C3 无需 scaling)、预算(probe 4×
无救援)、reward/时序(禁改项)。

本合同冻结的假说与对照(在生成任何 G5 独立开发数据之前锁定):
- H0(对照复现):r2 原配置 fine-tune 再次摧毁(若不复现,合同无效);
- H1 更新幅度(learning_rate 3e-4→3e-5);
- H2 每 rollout 更新量(n_epochs 10→2);
- H3 advantage normalization(逐 minibatch 归一化移除);
- H4 critic 耦合(vf_coef 0.5→0.05);
- H5 信任域(clip_range 0.2→0.05)。

变量范围:仅 PPO 超参 overlay;bank/BC/评估/seed/步数全部与 r2 BC
路径同构冻结。评价指标(全部沿用 r2 同一实现):held-out balanced
accuracy(BC 前/后、fine-tune 后)、C3 cost_selectivity_gap、
probability gap、family-aware capture(窄 denominator 口径如实记录)、
KL(π_ft ‖ π_BC)(BC dev 观测集)、梯度摘要(DiagnosedPPO2 原件)。

停止规则:固定预算(每 arm-run 27,552 steps = 8 episodes × 12
cycles;3 seeds × 6 arms);不延长、不中途换配置、不看结果加 arm。

判定规则(预注册):
- H0 成立要求 ≥2/3 seeds drop > 0.1(destroy 复现;否则本轮无效);
- arm "保留" 要求 ≥2/3 seeds drop ≤ 0.05;
- arm "保留且改善" 另要求该 arm ≥2/3 seeds fine-tune 后
  cost_selectivity_gap ≥ 0.5 × BC 后值(如实记录 probability gap)。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES,
    CURRICULUM261_SEED_NAMESPACES as _NS261,
)
from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_r2_evaluator import (
    evaluate_single_family_bank,
    family_behavior_gap,
    family_eval_capture,
    family_probability_summary,
)
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_NAMESPACES as _NS_R2,
)
from rl_curriculum.ppo262_r2_supervised import extended_binary_metrics
from rl_curriculum.ppo262_r2_train import (
    R2CheckpointStore,
    actor_state_hash,
    bc_train_actor_weighted,
    build_diagnosed_ppo2,
    collect_family_bc_dataset,
    critic_state_hash,
    r2_diag_train_run,
)
from rl_curriculum.ppo262_diag_metrics import probability_metrics_on_bank
from rl_curriculum.ppo262_diag_train import ObsAdapter

try:
    from rl_curriculum.ppo262_diag_namespaces import (
        DIAG_NAMESPACES as _NS_R1,
    )
except ImportError:  # pragma: no cover - 历史模块名防御
    _NS_R1 = ()

# ---------------------------------------------------------------- 身份
DIAG262G5_ITERATION_ID = "s262_diag_g5"
DIAG262G5_NS_PREFIX = "diag262g5"
G5_FAMILY = "c3_cost"
G5_BASE_CANDIDATE = "cand_a_center"

#: G5 BC/fine-tune model seeds(2910x;与 official 26201-3、R1
#: 2710x/2720x/2730x、被废止 r2 2810x?、r2_1 2840x/2850x/2860x、
#: prob RNG 262311 全部整数级不相交;r2_1 使用的全部 seed 块在
#: ppo262_r2_namespaces 内枚举)。
G5_BC_SEEDS = (29101, 29102, 29103)

DIAG262G5_NAMESPACES = tuple(
    f"{DIAG262G5_NS_PREFIX}_{name}" for name in (
        "bc_train_c3_s0", "bc_train_c3_s1", "bc_train_c3_s2",
        "bc_eval_c3_s0", "bc_eval_c3_s1", "bc_eval_c3_s2"))

#: 隔离合同(fail closed,构造期断言):
assert not set(DIAG262G5_NAMESPACES) & set(_NS261)
assert not set(DIAG262G5_NAMESPACES) & set(_NS_R2)
assert not set(DIAG262G5_NAMESPACES) & set(_NS_R1)
assert len(set(DIAG262G5_NAMESPACES)) == len(DIAG262G5_NAMESPACES)

_RUNGS_TRAIN = ("D0", "D1")
_RUNGS_EVAL = ("D0", "D1", "D2")
_PAIRS_TRAIN = 2          # r2 bc: 8-episode train bank/slot
_PAIRS_EVAL = 4           # r2 bc: 24-episode eval bank/slot
_BC_EPOCHS = 30
_BC_LR = 3e-4
_STEPS_FINETUNE = 8 * 287 * 12   # 27,552(与 r2 bc 完全一致)
_CKPT_EPS = (16, 48, 96)
_CKPT_TAGS = ("after_bc_before_ppo", "ep16", "ep48", "ep96")

#: 冻结的 arms(顺序即报告顺序;overlay 键必须是 PPO 超参)。
G5_ARMS: dict[str, dict[str, Any]] = {
    "A0_control": {
        "hypothesis": "r2 原配置复现 Branch D 摧毁(对照)",
        "overlay": {}},
    "A1_lr_low": {
        "hypothesis": "更新幅度:learning_rate 3e-4 → 3e-5",
        "overlay": {"learning_rate": 3e-5}},
    "A2_epochs_low": {
        "hypothesis": "每 rollout 更新量:n_epochs 10 → 2",
        "overlay": {"n_epochs": 2}},
    "A3_advnorm_off": {
        "hypothesis": "移除逐 minibatch advantage normalization",
        "overlay": {},
        "model_kwargs": {"normalize_advantage": False}},
    "A4_vf_low": {
        "hypothesis": "critic 耦合:vf_coef 0.5 → 0.05",
        "overlay": {"vf_coef": 0.05}},
    "A5_clip_low": {
        "hypothesis": "信任域:clip_range 0.2 → 0.05",
        "overlay": {"clip_range": 0.05}},
}

_DECISION = {
    "h0_valid_requires": ">=2/3 seeds drop > 0.1(control 复现摧毁)",
    "arm_preserved_requires": ">=2/3 seeds drop <= 0.05",
    "arm_preserved_improved_requires":
        "preserved 且 >=2/3 seeds ft cost_selectivity_gap "
        ">= 0.5 * bc cost_selectivity_gap",
    "invalid_if": "A0_control 未复现摧毁(>=2/3 drop>0.1)则本轮无效",
}


def derive262g5_seed(namespace: str, family: str, rung: str,
                     pair_index: int, attempt: int) -> int:
    """G5 诊断确定性 seed 派生(单一来源;拒绝一切非 G5 namespace)。"""
    if namespace not in DIAG262G5_NAMESPACES:
        raise ValueError(
            f"seed namespace {namespace!r} 不在 {DIAG262G5_ITERATION_ID} "
            f"诊断集合({len(DIAG262G5_NAMESPACES)} 个;official 262 / "
            f"diag r1 / diag r2_1 / 2.6.1 namespace 一律拒绝)")
    payload = json.dumps(
        ["stage2_6_2", DIAG262G5_ITERATION_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


# ---------------------------------------------------------------- plan
def build_g5_plan() -> dict[str, Any]:
    base = dict(PPO262_CANDIDATES[G5_BASE_CANDIDATE])
    return {
        "format": "cur261-ppo262-g5-diagnostic-plan-v1",
        "iteration": DIAG262G5_ITERATION_ID,
        "non_formal_declaration": (
            "本诊断不构成正式 Stage 2.6.2 输入;不进入 official "
            "namespace/seed;不触碰 ppo_final_eval_262 / qualification_*;"
            "结果仅用于 GOAL G5 的修复/诊断结论"),
        "family": G5_FAMILY,
        "problem_anchor": (
            "r2 s262_diag_r2_1: C3 Branch D — BC 3/3 学会"
            "(bal 0.866-0.923),PPO fine-tune 3/3 摧毁(drop 0.246-0.498)"),
        "excluded_hypotheses": [
            "representation capacity(supervised 全族可学)",
            "preprocessing(C3 无需 scaling;r2 §6/§11)",
            "budget(s262_r0 probe 4× 无救援)",
        ],
        "base_candidate": G5_BASE_CANDIDATE,
        "base_config": base,
        "arms": {k: dict(v) for k, v in G5_ARMS.items()},
        "seeds": {"bc_finetune": list(G5_BC_SEEDS)},
        "g5_code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "supersedes_note": (
            "锁 #1(g5dp-0a851816…)/#2(g5dp-14818f23…)零数据期废止"
            "(EpisodeKey 参数序 / env 导入缺失);锁 #3(g5dp-423ec7bc…)"
            "在首个 BC 训练完成后、任何持久化(checkpoint/results)之前"
            "中止于 BC 参照深拷贝 API 误用——模型状态仅存在于已崩溃"
            "进程内存,磁盘零 G5 模型/计划外证据;各次废止均以新 "
            "g5_code_sha256 重锁"),

        "bank_spec": {
            "train_per_slot": {"rungs": list(_RUNGS_TRAIN),
                               "pairs_per_rung": _PAIRS_TRAIN,
                               "pair_base_rule": "slot*32",
                               "adapter": "unscaled(C3 BC arm,r2 规则)"},
            "eval_per_slot": {"rungs": list(_RUNGS_EVAL),
                              "pairs_per_fr": _PAIRS_EVAL,
                              "pair_base_rule": "256 + slot*32"},
            "bc_epochs": _BC_EPOCHS, "bc_lr": _BC_LR,
            "class_weighted": True,
            "steps_finetune": _STEPS_FINETUNE,
            "checkpoint_episodes": list(_CKPT_EPS),
            "checkpoint_tags": list(_CKPT_TAGS),
        },
        "metrics": [
            "heldout balanced_accuracy(bc_before/bc_after/ft)",
            "cost_selectivity_gap(deterministic behavior)",
            "probability gap(c3 above_cost vs below_cost)",
            "family_eval_capture(窄 denominator 如实记录)",
        ],
        "stage261_code_anchor": {
            "declaration": (
                "本诊断在 R17 框架演进后的 2.6.1 源码上运行;"
                "r2 诊断结论保持其自身 input lock 身份(9305c773…);"
                "当前 api.py 漂移经 ppo262_input_lock 的 R17 框架轮"
                "登记精确锚定(repo 92818db2);G5 复用的 r2 训练/"
                "评估实现语义等价由其测试面覆盖"),
        },
        "decision": dict(_DECISION),
        "stop_rule": (
            "固定预算 6 arms × 3 seeds × 27,552 steps;不延长、不换配、"
            "不看结果加 arm;任何 arm 失败即如实记录为该 arm 结果"),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
    }


def g5_plan_digest(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("locked_utc", None)
    payload.pop("g5_plan_digest", None)
    return "g5dp-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def lock_g5_plan(out_dir: Path) -> tuple[Path, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "g5_diagnostic_plan.json"
    if path.exists():
        raise RuntimeError(f"G5 计划已存在,禁止重锁: {path}")
    plan = build_g5_plan()
    digest = g5_plan_digest(plan)
    plan["g5_plan_digest"] = digest
    plan["locked_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime())
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False,
                               default=str) + "\n", encoding="utf-8")
    return path, digest


def load_g5_plan(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "g5_diagnostic_plan.json"
    if not path.is_file():
        raise RuntimeError(f"G5 计划未锁定(先运行 lock): {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if g5_plan_digest(plan) != plan.get("g5_plan_digest"):
        raise RuntimeError("G5 计划 digest 不一致(锁定后不得修改)")
    return plan


# ---------------------------------------------------------------- bank
def _bank_keys(namespace: str, rungs, pairs: int, base: int):
    return [EpisodeKey(
        namespace, G5_FAMILY, r, base + p, v)
        for r in rungs for p in range(pairs)
        for v in ("A", "B")]


def _gen(namespace: str, rungs, pairs: int, base: int,
         rung_params: dict) -> list:
    return generate262_bank(
        _bank_keys(namespace, rungs, pairs, base),
        locked_plan_rung_params=rung_params,
        derive_seed_fn=derive262g5_seed)

# ---------------------------------------------------------------- run
def _match_metrics(model, dev: dict, adapter) -> dict:
    import torch
    xt = torch.as_tensor(np.stack(
        [adapter.apply(o) for o in dev["X"]]), dtype=torch.float32)
    with torch.no_grad():
        logits = model.policy.get_distribution(xt).distribution.logits
    p = torch.softmax(logits, dim=-1)[:, 1].numpy()
    return extended_binary_metrics(dev["y"], p)


def _kl_to_bc(model, bc_model, dev: dict, adapter) -> float:
    import torch
    xt = torch.as_tensor(np.stack(
        [adapter.apply(o) for o in dev["X"]]), dtype=torch.float32)
    with torch.no_grad():
        logp = model.policy.get_distribution(xt).distribution.logits
        logq = bc_model.policy.get_distribution(xt).distribution.logits
    kl = torch.nn.functional.kl_div(
        torch.log_softmax(logp, dim=-1),
        torch.softmax(logq, dim=-1),
        reduction="batchmean", log_target=False)
    return float(kl)


def run_g5(out_dir: Path) -> dict[str, Any]:
    """执行 G5 诊断(计划必须已锁定;全部 arm/seed 真实执行)。"""
    from rl_curriculum.curriculum261_api import (
        curriculum261_eval_config,
    )
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_r2_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )

    out_dir = Path(out_dir)
    plan = load_g5_plan(out_dir)
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg261 = curriculum261_eval_config()
    base_cfg = dict(PPO262_CANDIDATES[G5_BASE_CANDIDATE])
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "format": "cur261-ppo262-g5-diagnostic-results-v1",
        "iteration": DIAG262G5_ITERATION_ID,
        "g5_plan_digest": plan["g5_plan_digest"],
        "arms": {}, "per_seed_bc": {}, "sanity": {},
    }

    def _eval_bank_metrics(model, eval_bank, adapter):
        prob = probability_metrics_on_bank(
            model, eval_bank, adapter=adapter)
        prob_sum = family_probability_summary(prob, G5_FAMILY)
        ev = evaluate_single_family_bank(
            model, eval_bank, rung_params, thresholds, adapter=adapter)
        cap = family_eval_capture(G5_FAMILY, ev["cells"])
        beh = family_behavior_gap(ev.get("behavior", {}), G5_FAMILY)
        return {"probability": prob_sum, "capture": cap,
                "behavior": beh}

    for slot, seed in enumerate(G5_BC_SEEDS):
        train_bank = _gen(
            f"{DIAG262G5_NS_PREFIX}_bc_train_c3_s{slot}",
            _RUNGS_TRAIN, _PAIRS_TRAIN, slot * 32, rung_params)
        eval_bank = _gen(
            f"{DIAG262G5_NS_PREFIX}_bc_eval_c3_s{slot}",
            _RUNGS_EVAL, _PAIRS_EVAL, 256 + slot * 32, rung_params)
        dtr = collect_family_bc_dataset(
            train_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        dev = collect_family_bc_dataset(
            eval_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        adapter = ObsAdapter.identity(dtr["X"].shape[1])

        env = CurriculumMultiEpisodeEnv(train_bank)
        model = build_diagnosed_ppo2(base_cfg, seed, env)
        actor_before = actor_state_hash(model)
        critic_before = critic_state_hash(model)
        bc_info = bc_train_actor_weighted(
            model, dtr, epochs=_BC_EPOCHS, lr=_BC_LR, adapter=adapter,
            rng_seed=seed, class_weighted=True)
        actor_after = actor_state_hash(model)
        critic_after = critic_state_hash(model)
        bc_match = _match_metrics(model, dev, adapter)

        # 冻结 BC 参照(KL 参照 + bc_init 源)
        import copy as _copy
        bc_model = build_diagnosed_ppo2(base_cfg, seed, env)
        bc_model.policy.load_state_dict(
            _copy.deepcopy(model.policy.state_dict()))
        bc_state = {k: v.clone() for k, v in
                    model.policy.state_dict().items()}


        bc_bank_eval = _eval_bank_metrics(bc_model, eval_bank, adapter)
        results["per_seed_bc"][str(seed)] = {
            "slot": slot,
            "actor_changed": actor_before != actor_after,
            "critic_unchanged": critic_before == critic_after,
            "bc_train_info": {k: bc_info[k] for k in bc_info
                              if isinstance(bc_info[k], (int, float))},
            "heldout": bc_match,
            "bank_eval": bc_bank_eval,
            "kl_bc_to_self": _kl_to_bc(model, bc_model, dev, adapter),
        }

        for arm_name, arm in G5_ARMS.items():
            cfg = dict(base_cfg)
            cfg.update(arm["overlay"])
            store = R2CheckpointStore(
                models_dir, f"g5_{arm_name}_seed{seed}",
                family=G5_FAMILY, arm=f"g5:{arm_name}", seed=seed,
                expected_tags=_CKPT_TAGS)
            run = r2_diag_train_run(
                train_bank, config=cfg, model_seed=seed,
                total_timesteps=_STEPS_FINETUNE,
                run_label=f"g5/{arm_name}/seed{seed}",
                adapter=None, checkpoint_store=store,
                checkpoint_episodes=_CKPT_EPS,
                gradient_detail_every=8, bc_init_state=bc_state,
                model_extra_kwargs=arm.get("model_kwargs"))
            ft_model = run["model"]
            ft_match = _match_metrics(ft_model, dev, adapter)
            ft_bank_eval = _eval_bank_metrics(ft_model, eval_bank,
                                              adapter)
            drop = bc_match["balanced_accuracy"] - \
                ft_match["balanced_accuracy"]
            rec = {
                "config_overlay": arm["overlay"],
                "heldout_before": bc_match["balanced_accuracy"],
                "heldout_after": ft_match["balanced_accuracy"],
                "drop": drop,
                "kl_ft_to_bc": _kl_to_bc(ft_model, bc_model, dev,
                                         adapter),
                "bank_eval": ft_bank_eval,
                "n_update_records": len(run.get("update_records", [])),
                "n_minibatch_records": len(
                    run.get("minibatch_records", [])),
                "checkpoint_verification": run.get(
                    "checkpoint_verification"),
                "run_pass": run.get("pass"),
            }
            results["arms"].setdefault(arm_name, {})[str(seed)] = rec
            print(f"[g5] {arm_name} seed={seed} "
                  f"bal {rec['heldout_before']:.3f}->"
                  f"{rec['heldout_after']:.3f} drop={drop:.3f} "
                  f"kl={rec['kl_ft_to_bc']:.4f}", flush=True)
            del ft_model

    # ---- 判定(预注册规则)
    def _arm_stats(arm_name: str) -> dict:
        recs = results["arms"][arm_name]
        drops = [r["drop"] for r in recs.values()]
        beh0 = np.mean([r["bank_eval"]["behavior"]["det_behavior_gap"]
                        for r in results["per_seed_bc"].values()
                        if r["bank_eval"]["behavior"].get(
                            "det_behavior_gap") is not None])
        behs = [r["bank_eval"]["behavior"].get("det_behavior_gap")
                for r in recs.values()]
        return {
            "drops": drops,
            "n_drop_gt_01": int(sum(d > 0.1 for d in drops)),
            "n_drop_le_005": int(sum(d <= 0.05 for d in drops)),
            "det_behavior_gaps": behs,
            "bc_mean_det_behavior_gap": float(beh0) if beh0 else None,
        }

    stats = {a: _arm_stats(a) for a in G5_ARMS}
    control = stats["A0_control"]
    h0_valid = control["n_drop_gt_01"] >= 2
    verdicts = {}
    for a in G5_ARMS:
        s = stats[a]
        preserved = s["n_drop_le_005"] >= 2
        beh_vals = [b for b in s["det_behavior_gaps"]
                    if b is not None]
        beh_ok = (len(beh_vals) >= 2
                  and s["bc_mean_det_behavior_gap"] is not None
                  and sum(b >= 0.5 * s["bc_mean_det_behavior_gap"]
                          for b in beh_vals) >= 2)
        verdicts[a] = {
            "preserved": preserved,
            "preserved_and_improved": preserved and beh_ok,
            **s}
    results["sanity"] = {"h0_control_reproduced_destroy": h0_valid,
                         "invalid_if_not": _DECISION["invalid_if"]}
    results["arm_stats"] = stats
    results["verdicts"] = verdicts
    results["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())

    out = out_dir / "g5_diagnostic_results.json"
    out.write_text(json.dumps(results, indent=1, ensure_ascii=False,
                              default=str) + "\n", encoding="utf-8")
    print(json.dumps({"h0_valid": h0_valid,
                      "verdicts": {a: {
                          "preserved": v["preserved"],
                          "improved": v["preserved_and_improved"]}
                          for a, v in verdicts.items()}},
                     ensure_ascii=False))
    return results


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
        path, digest = lock_g5_plan(args.out_dir)
        print(f"locked {path} digest={digest}")
        return 0
    run_g5(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
