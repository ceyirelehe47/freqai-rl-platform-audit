# -*- coding: utf-8 -*-
"""Stage 2.6.2 — G5b 诊断:BC 边际脆弱性的保留干预(G5 后续合同)。

非正式诊断合同:**不构成正式 Stage 2.6.2 输入**;不进入 official
namespace/seed;ppo_final_eval_262 / qualification_* 零接触。

前序证据(G5,s262_diag_g5):PPO 摧毁与更新幅度无关——lr×0.1 与
advnorm-off 的 KL(π_ft‖π_BC)≈0.008-0.13 仍全毁;机制 = BC 选择性
存活于亚阈值概率边际(argmax 级联翻转)。

本合同冻结的假说(在生成任何 G5b 独立开发数据之前锁定):
- B0(对照):标准加权 CE BC → r2 原配 fine-tune(预期复现摧毁);
- B2_margin_bc:边际 BC(加权 softplus-margin 损失,目标
  |z_long − z_flat| ≥ margin=2.0 全样本推宽)→ r2 原配 fine-tune;
- B3_rehearsal:标准 BC → fine-tune 每 bank 周期后 1 epoch BC
  复训(lr=1e-4,同加权 CE;行间排练式抗遗忘);
- B4_margin_rehearsal:边际 BC → fine-tune + 同款复训。

变量范围:仅 BC 损失形态与复训钩子;bank/评估/seed/步数与 G5-1
同构冻结(27,552 steps;12 × 8-episode bank 周期)。

评价指标:G5-1 全套(heldout bal acc、cost_selectivity_gap、
probability gap、capture、KL(π_ft‖π_BC))+ 新增边际统计
(dev 集 mean |z_long−z_flat| 与 |diff|<0.5 占比,BC 后/微调后)。

判定规则(预注册):
- B0 成立要求 ≥2/3 seeds drop > 0.1(否则本轮无效);
- arm preserved:≥2/3 seeds drop ≤ 0.05;
- arm preserved_and_selective:preserved 且 ≥2/3 seeds
  ft cost_selectivity_gap ≥ 0.5 × BC 后值。

停止规则:4 arms × 3 seeds × 27,552 steps 固定;不延长不换配。
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_SEED_NAMESPACES as _NS261,
    curriculum261_eval_config,
)
from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_diag_metrics import probability_metrics_on_bank
from rl_curriculum.ppo262_diag_train import (
    DiagnosisCallback,
    ObsAdapter,
    latent_label_series,
)
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
    policy_state_hash,
)

from rl_curriculum.ppo262_g5 import (
    DIAG262G5_NAMESPACES as _NS_G5,
    G5_FAMILY,
)

# ---------------------------------------------------------------- 身份
DIAG262G5B_ITERATION_ID = "s262_diag_g5b"
DIAG262G5B_NS_PREFIX = "diag262g5b"
G5B_BC_SEEDS = (29201, 29202, 29203)
G5B_BASE_CANDIDATE = "cand_a_center"

DIAG262G5B_NAMESPACES = tuple(
    f"{DIAG262G5B_NS_PREFIX}_{name}" for name in (
        "bc_train_c3_s0", "bc_train_c3_s1", "bc_train_c3_s2",
        "bc_eval_c3_s0", "bc_eval_c3_s1", "bc_eval_c3_s2"))

assert not set(DIAG262G5B_NAMESPACES) & set(_NS261)
assert not set(DIAG262G5B_NAMESPACES) & set(_NS_R2)
assert not set(DIAG262G5B_NAMESPACES) & set(_NS_G5)
assert len(set(DIAG262G5B_NAMESPACES)) == len(DIAG262G5B_NAMESPACES)

_RUNGS_TRAIN = ("D0", "D1")
_RUNGS_EVAL = ("D0", "D1", "D2")
_PAIRS_TRAIN = 2
_PAIRS_EVAL = 4
_BC_EPOCHS = 30
_BC_LR = 3e-4
_BC_EPOCHS_MARGIN = 300
_BC_LR_MARGIN = 1e-3
_MARGIN = 2.0
_REHEARSAL_LR = 1e-4
_STEPS_FINETUNE = 8 * 287 * 12        # 27,552;segment = 8*287 = 2,296
_SEGMENT_STEPS = 8 * 287
_CKPT_TAGS = ("after_bc_before_ppo", "ep16", "ep48", "ep96")

G5B_ARMS: dict[str, dict[str, Any]] = {
    "B0_control": {"bc": "standard", "rehearsal": False},
    "B2_margin_bc": {"bc": "margin", "rehearsal": False},
    "B3_rehearsal": {"bc": "standard", "rehearsal": True},
    "B4_margin_rehearsal": {"bc": "margin", "rehearsal": True},
}


def derive262g5b_seed(namespace: str, family: str, rung: str,
                      pair_index: int, attempt: int) -> int:
    if namespace not in DIAG262G5B_NAMESPACES:
        raise ValueError(
            f"seed namespace {namespace!r} 不在 "
            f"{DIAG262G5B_ITERATION_ID} 诊断集合")
    payload = json.dumps(
        ["stage2_6_2", DIAG262G5B_ITERATION_ID, namespace, family, rung,
         int(pair_index), int(attempt)],
        sort_keys=True, separators=(",", ":"))
    return int.from_bytes(
        hashlib.sha256(payload.encode("utf-8")).digest()[:8], "big")


# ---------------------------------------------------------------- BC
def balanced_weights(y: np.ndarray) -> dict[int, float]:
    counts = {int(c): float((y == c).sum()) for c in (0, 1)}
    total = float(len(y))
    return {c: total / (2.0 * max(n, 1.0)) for c, n in counts.items()}


def bc_train_actor_margin(model, dataset, *, epochs: int, lr: float,
                          adapter, rng_seed: int, margin: float,
                          ) -> dict[str, Any]:
    """边际 BC:加权 hinge-margin 损失(relu(margin − s·(z1−z0)),
    全样本推宽 |z1−z0| ≥ margin)。

    dry-run 实测:softplus 变体在 deficit≈margin 处梯度衰减
    (~σ(2)≈0.12),30 epoch 边际仅 0.05,达不到干预目的;改用
    hinge(违反样本梯度恒定)。与 r2 的加权 CE 同数据/同 actor
    参数面/同类权重;唯一差异 = 损失形态。
    """
    import torch
    policy = model.policy
    actor_params = (list(policy.mlp_extractor.policy_net.parameters())
                    + list(policy.action_net.parameters()))
    opt = torch.optim.Adam(actor_params, lr=lr)
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dataset["X"]]), dtype=torch.float32)
    y = np.asarray(dataset["y"], dtype=np.int64)
    s = torch.as_tensor(2.0 * y - 1.0, dtype=torch.float32)
    wmap = balanced_weights(y)
    w = torch.as_tensor([wmap[int(c)] for c in y], dtype=torch.float32)
    w = w / w.mean()
    history = []
    for epoch in range(epochs):
        opt.zero_grad()
        dist = policy.get_distribution(X)
        diff = (dist.distribution.logits[:, 1]
                - dist.distribution.logits[:, 0])
        per = torch.relu(margin - s * diff)
        loss = (w * per).mean()
        loss.backward()
        opt.step()
        with torch.no_grad():
            match = float((diff.sign() == s).float().mean())
            margins = float(per.mean())
            violating = float((per > 1e-9).float().mean())
        history.append({"epoch": epoch + 1, "loss": float(loss.item()),
                        "match_rate": match, "mean_hinge": margins,
                        "violating_frac": violating})
    return {"epochs": epochs, "lr": lr, "margin": margin,
            "history": history}


def margin_stats(model, dev: dict, adapter) -> dict:
    """dev 集边际统计:mean|z1−z0|、<0.5 占比、argmax 精度。"""
    import torch
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dev["X"]]), dtype=torch.float32)
    y = np.asarray(dev["y"], dtype=np.int64)
    with torch.no_grad():
        logits = model.policy.get_distribution(X).distribution.logits
    diff = (logits[:, 1] - logits[:, 0]).numpy()
    s = 2.0 * y - 1.0
    return {
        "mean_abs_diff": float(np.mean(np.abs(diff))),
        "frac_below_0p5": float(np.mean(np.abs(diff) < 0.5)),
        "frac_below_2p0": float(np.mean(np.abs(diff) < 2.0)),
        "mean_signed_diff": float(np.mean(s * diff)),
        "argmax_match": float(np.mean(np.sign(diff) == s)),
    }


# ---------------------------------------------------------------- plan
def build_g5b_plan() -> dict[str, Any]:
    return {
        "format": "cur261-ppo262-g5b-diagnostic-plan-v1",
        "iteration": DIAG262G5B_ITERATION_ID,
        "non_formal_declaration": (
            "本诊断不构成正式 Stage 2.6.2 输入;不进入 official "
            "namespace/seed;不触碰 ppo_final_eval_262/qualification_*"),
        "family": G5_FAMILY,
        "prior_evidence": (
            "s262_diag_g5:更新幅度被排除(KL≈0.008-0.13 仍全毁);"
            "机制 = 亚阈值边际 argmax 脆弱性"),
        "margin_bc_optimization": {
            "loss": "weighted hinge relu(margin - s*(z1-z0))",
            "margin": _MARGIN, "epochs": _BC_EPOCHS_MARGIN,
            "lr": _BC_LR_MARGIN,
            "calibration_note": (
                "GOAL G5 允许研究性超参来自开发集。标定在锁定前于"
                "diag262g5b_bc_train_c3_s0 train bank(dev 数据)上"
                "进行:softplus 30ep/3e-4 仅达 mean|diff|≈0.05(梯度"
                "衰减),hinge 300ep/1e-3/margin2.0 达 mean|diff|=5.46、"
                "frac<0.5=1.1%、match=0.988;优化预算差异是干预的"
                "一部分,如实声明而非隐藏"),
        },
        "arms": {k: dict(v) for k, v in G5B_ARMS.items()},
        "margin": _MARGIN,
        "rehearsal": {"per_cycle_epochs": 1, "lr": _REHEARSAL_LR},
        "seeds": {"bc_finetune": list(G5B_BC_SEEDS)},
        "bank_spec": {
            "train_per_slot": {"rungs": list(_RUNGS_TRAIN),
                               "pairs_per_rung": _PAIRS_TRAIN,
                               "pair_base_rule": "slot*32",
                               "adapter": "unscaled"},
            "eval_per_slot": {"rungs": list(_RUNGS_EVAL),
                              "pairs_per_fr": _PAIRS_EVAL,
                              "pair_base_rule": "256 + slot*32"},
            "bc_epochs": _BC_EPOCHS, "bc_lr": _BC_LR,
            "steps_finetune": _STEPS_FINETUNE,
            "segment_steps": _SEGMENT_STEPS,
            "checkpoint_tags": list(_CKPT_TAGS),
        },
        "metrics": [
            "heldout balanced_accuracy(bc/ft)",
            "cost_selectivity_gap / probability gap / capture",
            "KL(pi_ft || pi_BC)",
            "margin stats(mean|z1-z0| / frac<0.5 / frac<2.0, bc 后与 ft 后)",
        ],
        "decision": {
            "b0_valid_requires": ">=2/3 seeds drop > 0.1",
            "preserved_requires": ">=2/3 seeds drop <= 0.05",
            "preserved_selective_requires":
                "preserved 且 >=2/3 seeds ft gap >= 0.5*bc gap",
        },
        "stop_rule": "4 arms × 3 seeds × 27,552 steps 固定",
        "g5b_code_sha256": hashlib.sha256(
            Path(__file__).read_bytes()).hexdigest(),
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
    }

def g5b_plan_digest(plan: dict[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("locked_utc", None)
    payload.pop("g5b_plan_digest", None)
    return "g5bdp-" + hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False,
        separators=(",", ":")).encode("utf-8")).hexdigest()


def lock_g5b_plan(out_dir: Path) -> tuple[Path, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "g5b_diagnostic_plan.json"
    if path.exists():
        raise RuntimeError(f"G5b 计划已存在,禁止重锁: {path}")
    plan = build_g5b_plan()
    digest = g5b_plan_digest(plan)
    plan["g5b_plan_digest"] = digest
    path.write_text(json.dumps(plan, indent=1, ensure_ascii=False,
                               default=str) + "\n", encoding="utf-8")
    return path, digest


def load_g5b_plan(out_dir: Path) -> dict[str, Any]:
    path = Path(out_dir) / "g5b_diagnostic_plan.json"
    if not path.is_file():
        raise RuntimeError(f"G5b 计划未锁定: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if g5b_plan_digest(plan) != plan.get("g5b_plan_digest"):
        raise RuntimeError("G5b 计划 digest 不一致")
    return plan


# ---------------------------------------------------------------- run
def _gen_bank(namespace: str, rungs, pairs: int, base: int, rung_params):
    keys = [EpisodeKey(namespace, G5_FAMILY, r, base + p, v)
            for r in rungs for p in range(pairs)
            for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=rung_params,
        derive_seed_fn=derive262g5b_seed)


def _match(model, dev, adapter) -> dict:
    import torch
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dev["X"]]), dtype=torch.float32)
    with torch.no_grad():
        logits = model.policy.get_distribution(X).distribution.logits
    p = torch.softmax(logits, dim=-1)[:, 1].numpy()
    return extended_binary_metrics(dev["y"], p)


def _kl(model_a, model_b, dev, adapter) -> float:
    import torch
    X = torch.as_tensor(np.stack(
        [adapter.apply(x) for x in dev["X"]]), dtype=torch.float32)
    with torch.no_grad():
        la = model_a.policy.get_distribution(X).distribution.logits
        lb = model_b.policy.get_distribution(X).distribution.logits
    return float(torch.nn.functional.kl_div(
        torch.log_softmax(la, dim=-1), torch.softmax(lb, dim=-1),
        reduction="batchmean"))


def _bank_eval(model, eval_bank, rung_params, thresholds, adapter):
    prob = probability_metrics_on_bank(model, eval_bank, adapter=adapter)
    ev = evaluate_single_family_bank(
        model, eval_bank, rung_params, thresholds, adapter=adapter)
    return {
        "probability": family_probability_summary(prob, G5_FAMILY),
        "capture": family_eval_capture(G5_FAMILY, ev["cells"]),
        "behavior": family_behavior_gap(ev.get("behavior", {}), G5_FAMILY),
    }


def g5b_finetune_run(bank, *, config, model_seed, bc_state, adapter,
                     store: R2CheckpointStore, run_label: str,
                     rehearsal: bool, rehearsal_dataset, rng_seed: int,
                     ) -> dict[str, Any]:
    """分段 fine-tune(12 × 8-episode bank 周期;可选周期末 BC 复训)。

    与 r2_diag_train_run 的差异显式化:learn 按 bank 周期分段
    (每段 2,296 steps = 4 个 n_steps rollout,与整段调用的 rollout
    边界逐位对齐);rehearsal 段间执行 1 epoch 加权 CE BC
    (bc_train_actor_weighted,lr=1e-4,actor-only)。梯度/rollout
    记录来自同一 DiagnosedPPO2 插桩,跨段累积。
    """
    inner_env = CurriculumMultiEpisodeEnv(bank)
    train_env = inner_env
    latent_labels = {i: latent_label_series(
        loaded, loaded.key.family) for i, loaded in enumerate(bank)}

    def _save(n_done: int, model, tag: str | None = None):
        # 仅显式 tag 边界落盘;callback 逐 episode 的 tag=None 调用
        # 只走诊断收集(不产生计划外 checkpoint,verify_expected 干净)
        if tag is not None:
            store.save(n_done, model, tag=tag)

    cb = DiagnosisCallback(
        inner_env, latent_labels=latent_labels, on_episode_done=_save)
    model = build_diagnosed_ppo2(config, model_seed, train_env)
    model._diag2_detail_every = 8
    model.policy.load_state_dict(bc_state)
    _save(0, model, tag="after_bc_before_ppo")
    init_hash = policy_state_hash(model)

    t0 = time.time()
    episodes_done = 0
    rehearsal_log = []
    for cycle in range(_STEPS_FINETUNE // _SEGMENT_STEPS):
        model.learn(total_timesteps=_SEGMENT_STEPS,
                    callback=cb.as_callback(), progress_bar=False,
                    reset_num_timesteps=(cycle == 0))
        episodes_done += len(bank)
        if cycle in (1, 5, 11):
            _save(episodes_done, model,
                  tag=f"ep{episodes_done}")
        if rehearsal:
            info = bc_train_actor_weighted(
                model, rehearsal_dataset, epochs=1, lr=_REHEARSAL_LR,
                adapter=adapter, rng_seed=rng_seed, class_weighted=True)
            rehearsal_log.append({
                "cycle": cycle + 1,
                "match_rate": info["history"][-1]["match_rate"]})
    elapsed = time.time() - t0
    audit = inner_env.audit()
    problems = []
    if audit["steps_taken"] != _STEPS_FINETUNE:
        problems.append(f"steps {audit['steps_taken']}")
    if audit["episodes_consumed"] != 12 * len(bank):
        problems.append(f"episodes {audit['episodes_consumed']}")
    return {
        "model": model,
        "initial_policy_state_sha256": init_hash,
        "elapsed_seconds": round(elapsed, 1),
        "audit": audit,
        "audit_problems": problems,
        "pass": not problems,
        "n_update_records": len(model.diag2_update_records),
        "checkpoint_verification": store.verify_expected(),
        "rehearsal_log": rehearsal_log,
        "run_label": run_label,
    }


def run_g5b(out_dir: Path) -> dict[str, Any]:
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_schema,
    )
    from rl_curriculum.ppo262_r2_cli import (
        _locked_reference_thresholds, _locked_rung_params,
    )

    out_dir = Path(out_dir)
    plan = load_g5b_plan(out_dir)
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    schema = production_observation_schema()
    cfg261 = curriculum261_eval_config()
    base_cfg = dict(PPO262_CANDIDATES[G5B_BASE_CANDIDATE])
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    results: dict[str, Any] = {
        "format": "cur261-ppo262-g5b-diagnostic-results-v1",
        "iteration": DIAG262G5B_ITERATION_ID,
        "g5b_plan_digest": plan["g5b_plan_digest"],
        "arms": {}, "per_seed_bc": {}, "sanity": {},
    }

    def _eval(model, eval_bank, adapter):
        return _bank_eval(model, eval_bank, rung_params, thresholds,
                          adapter)

    for slot, seed in enumerate(G5B_BC_SEEDS):
        train_bank = _gen_bank(
            f"{DIAG262G5B_NS_PREFIX}_bc_train_c3_s{slot}",
            _RUNGS_TRAIN, _PAIRS_TRAIN, slot * 32, rung_params)
        eval_bank = _gen_bank(
            f"{DIAG262G5B_NS_PREFIX}_bc_eval_c3_s{slot}",
            _RUNGS_EVAL, _PAIRS_EVAL, 256 + slot * 32, rung_params)
        dtr = collect_family_bc_dataset(
            train_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        dev = collect_family_bc_dataset(
            eval_bank, G5_FAMILY, rung_params, thresholds,
            schema, cfg261)
        adapter = ObsAdapter.identity(dtr["X"].shape[1])

        bc_results: dict[str, Any] = {}
        bc_models: dict[str, Any] = {}
        bc_states: dict[str, Any] = {}
        for bc_kind in ("standard", "margin"):
            env = CurriculumMultiEpisodeEnv(train_bank)
            model = build_diagnosed_ppo2(base_cfg, seed, env)
            actor_before = actor_state_hash(model)
            critic_before = critic_state_hash(model)
            if bc_kind == "standard":
                info = bc_train_actor_weighted(
                    model, dtr, epochs=_BC_EPOCHS, lr=_BC_LR,
                    adapter=adapter, rng_seed=seed, class_weighted=True)
            else:
                info = bc_train_actor_margin(
                    model, dtr, epochs=_BC_EPOCHS_MARGIN,
                    lr=_BC_LR_MARGIN,
                    adapter=adapter, rng_seed=seed, margin=_MARGIN)
            bc_results[bc_kind] = {
                "actor_changed": actor_before != actor_state_hash(model),
                "critic_unchanged": critic_before == critic_state_hash(
                    model),
                "heldout": _match(model, dev, adapter),
                "margin_stats": margin_stats(model, dev, adapter),
                "bank_eval": _eval(model, eval_bank, adapter),
                "train_tail": info["history"][-1],
            }
            bc_models[bc_kind] = model
            bc_states[bc_kind] = {k: v.clone() for k, v in
                                  model.policy.state_dict().items()}
        results["per_seed_bc"][str(seed)] = bc_results

        for arm_name, arm in G5B_ARMS.items():
            bc_kind = arm["bc"]
            store = R2CheckpointStore(
                models_dir, f"g5b_{arm_name}_seed{seed}",
                family=G5_FAMILY, arm=f"g5b:{arm_name}", seed=seed,
                expected_tags=_CKPT_TAGS)
            run = g5b_finetune_run(
                train_bank, config=base_cfg, model_seed=seed,
                bc_state=bc_states[bc_kind], adapter=adapter,
                store=store, run_label=f"g5b/{arm_name}/seed{seed}",
                rehearsal=arm["rehearsal"], rehearsal_dataset=dtr,
                rng_seed=seed)
            ft = run["model"]
            rec = {
                "bc_kind": bc_kind,
                "rehearsal": arm["rehearsal"],
                "heldout_before": bc_results[bc_kind]["heldout"][
                    "balanced_accuracy"],
                "heldout_after": _match(ft, dev, adapter)[
                    "balanced_accuracy"],
                "margin_before": bc_results[bc_kind]["margin_stats"],
                "margin_after": margin_stats(ft, dev, adapter),
                "kl_ft_to_bc": _kl(ft, bc_models[bc_kind], dev, adapter),
                "bank_eval": _eval(ft, eval_bank, adapter),
                "run_pass": run["pass"],
                "n_update_records": run["n_update_records"],
                "checkpoint_verification": run["checkpoint_verification"],
                "rehearsal_log": run["rehearsal_log"],
            }
            rec["drop"] = (rec["heldout_before"]
                           - rec["heldout_after"])
            results["arms"].setdefault(arm_name, {})[str(seed)] = rec
            print(f"[g5b] {arm_name} seed={seed} "
                  f"bal {rec['heldout_before']:.3f}->"
                  f"{rec['heldout_after']:.3f} drop={rec['drop']:.3f} "
                  f"kl={rec['kl_ft_to_bc']:.4f} "
                  f"margin={rec['margin_after']['mean_abs_diff']:.2f}",
                  flush=True)
            del ft

    # ---- 判定
    stats, verdicts = {}, {}
    bc_gap = float(np.mean([
        r[k]["bank_eval"]["behavior"].get("det_behavior_gap")
        for r in results["per_seed_bc"].values()
        for k in ("standard",)
        if r[k]["bank_eval"]["behavior"].get("det_behavior_gap")
        is not None]))
    for a, seeds in results["arms"].items():
        drops = [x["drop"] for x in seeds.values()]
        gaps = [x["bank_eval"]["behavior"].get("det_behavior_gap")
                for x in seeds.values()]
        preserved = sum(d <= 0.05 for d in drops) >= 2
        selective = (sum(g is not None and g >= 0.5 * bc_gap
                         for g in gaps) >= 2)
        stats[a] = {"drops": drops, "det_behavior_gaps": gaps,
                    "bc_standard_mean_gap": bc_gap}
        verdicts[a] = {"preserved": preserved,
                       "preserved_and_selective": preserved and selective}
    results["sanity"] = {
        "b0_control_reproduced_destroy":
            sum(d > 0.1 for d in stats["B0_control"]["drops"]) >= 2}
    results["arm_stats"] = stats
    results["verdicts"] = verdicts
    results["completed_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                             time.gmtime())
    (out_dir / "g5b_diagnostic_results.json").write_text(
        json.dumps(results, indent=1, ensure_ascii=False, default=str)
        + "\n", encoding="utf-8")
    print(json.dumps({"verdicts": verdicts,
                      "sanity": results["sanity"]},
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
        path, digest = lock_g5b_plan(args.out_dir)
        print(f"locked {path} digest={digest}")
        return 0
    run_g5b(args.out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
