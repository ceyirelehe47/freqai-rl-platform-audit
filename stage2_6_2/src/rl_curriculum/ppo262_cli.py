"""阶段 2.6.2 CLI:input-lock / seed-integrity / smoke / config-dev /
probe / core / dev-eval / final-lock / final-run / summarize。

每个子命令独立进程执行;artifacts 统一写 artifacts/route_c_stage2_6_2/
(可用 PPO262_ARTIFACTS_DIR 覆盖);模型文件写 models/(git 外,
manifest 进 git)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_FAMILIES, CURRICULUM261_RUNGS,
    qualification_r2_lock_marker,
)
from rl_curriculum.ppo262_namespaces import (
    PPO262_ITERATION_ID, PPO262_MODEL_SEEDS, PPO262_STAGE_ID,
    core_train_namespace, ppo262_artifacts_dir,
)
from rl_curriculum.ppo262_config import (
    PPO262_CANDIDATES, PPO262_CONFIG_DEV_EPISODES_PER_FAMILY,
    PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY, PPO262_CONFIG_DEV_EVAL_PAIR_BASE,
    PPO262_CONFIG_DEV_FAMILIES, PPO262_CONFIG_DEV_RUNG,
    PPO262_CONFIG_DEV_TOTAL_STEPS, PPO262_CONFIG_DEV_TRAIN_PAIR_BASE,
    PPO262_PROBE_BUDGETS, PPO262_CHECKPOINT_EPISODES,
    PPO262_DEV_EVAL_PAIRS_PER_RUNG, PPO262_FINAL_EVAL_PAIRS_PER_RUNG,
    PPO262_CONFIG_SELECTION_RULE,
)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MODELS_DIR = PROJECT_ROOT / "models" / "ppo262"


def _art() -> Path:
    return ppo262_artifacts_dir()


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=False,
                   default=_np_default),
        encoding="utf-8")


def _np_default(o):
    import numpy as np
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, np.floating):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(f"不可序列化: {type(o)}")


def _locked_plan():
    from rl_curriculum.curriculum261_plan import load_locked_plan
    return load_locked_plan(qualification_r2_lock_marker().parent)


def _locked_rung_params() -> dict[str, Any]:
    plan, _ = _locked_plan()
    return {fam: fp["rung_params"] for fam, fp in plan["families"].items()}


def _locked_reference_thresholds() -> dict[str, Any]:
    plan, _ = _locked_plan()
    return {fam: fp["reference_thresholds"]
            for fam, fp in plan["families"].items()}


# ================================================================ 子命令
def cmd_input_lock(args) -> int:
    from rl_curriculum.ppo262_input_lock import run_input_lock
    art = run_input_lock()
    _write_json(_art() / "input_lock.json", art)
    # 分项 artifacts(报告结构需要)
    _write_json(_art() / "upstream_integrity.json", art["vendor"])
    _write_json(_art() / "route_c_integrity.json", {
        "rl_platform_tree_hash": art["rl_platform_tree_hash"],
        "frozen_versions": art["route_c_frozen_versions"],
        "pass": art["checks"].get("route_c_tree_hash_unchanged", False)
        and art["checks"].get("route_c_frozen_versions_unchanged", False)})
    _write_json(_art() / "curriculum_input_identity.json", {
        "r2_plan_digest": art["r2_plan_digest"],
        "family_versions": art["family_versions"],
        "curriculum_source_identity": art["curriculum_source_identity"],
        "pass": art["checks"].get("stage261_source_unchanged", False)
        and art["checks"].get("family_versions_consistent", False)})
    _write_json(_art() / "preprocessing_boundary.json", {
        "boundary": "real RouteCStrategy feature semantics + frozen Route "
                    "C observation layout + causal unscaled curriculum "
                    "feature values(与 R2 完全同一 adapter)",
        "production_observation_identity_unchanged": art["checks"].get(
            "production_obs_identity_unchanged", False),
        "registered_future_domain_gap": (
            "FreqAI MinMaxScaler / production preprocessing transfer "
            "登记为后续 G5 domain gap;本阶段结果不等价于真实行情 "
            "production PPO 表现")})
    print(json.dumps({"pass": art["pass"], "problems": art["problems"]},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


def cmd_seed_integrity(args) -> int:
    from rl_curriculum.ppo262_namespaces import verify_namespace_isolation
    art = verify_namespace_isolation(
        pair_range_262=range(0, 20000), pair_range_261=range(0, 20000))
    _write_json(_art() / "seed_namespace_integrity.json", art)
    print(json.dumps({"pass": art["pass"], "problems": art["problems"][:5]},
                     ensure_ascii=False))
    return 0 if art["pass"] else 2


def cmd_ppo_smoke(args) -> int:
    from rl_curriculum.ppo262_smoke import run_ppo262_smoke
    res = run_ppo262_smoke(out_dir=_art())
    print(json.dumps({"pass": res["pass"],
                      "failed_checks": [k for k, v in res["checks"].items()
                                        if not v]}, ensure_ascii=False))
    return 0 if res["pass"] else 2


def cmd_config_dev_plan(args) -> int:
    plan = {
        "format": "ppo262-config-development-plan-v1",
        "stage": PPO262_STAGE_ID,
        "iteration": PPO262_ITERATION_ID,
        "candidates": PPO262_CANDIDATES,
        "budget_per_candidate_steps": PPO262_CONFIG_DEV_TOTAL_STEPS,
        "corpus": {
            "namespace": "ppo_config_dev_262",
            "scope": [f"{f}/D1" for f in PPO262_CONFIG_DEV_FAMILIES],
            "train_episodes_per_family": (
                PPO262_CONFIG_DEV_EPISODES_PER_FAMILY),
            "eval_pairs_per_family": PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY,
            "train_pair_base": PPO262_CONFIG_DEV_TRAIN_PAIR_BASE,
            "eval_pair_base": PPO262_CONFIG_DEV_EVAL_PAIR_BASE,
        },
        "selection_rule": PPO262_CONFIG_SELECTION_RULE,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    _write_json(_art() / "ppo_config_development_plan.json", plan)
    print("config development plan 写入(运行前锁定)")
    return 0


def _mini_bank_keys(family: str, n_episodes: int, *, namespace: str,
                    rung: str, pair_base: int) -> list:
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    n_pairs = n_episodes // 2
    for j in range(n_pairs):
        for variant in ("A", "B"):
            keys.append(EpisodeKey(
                namespace, family, rung, pair_base + j, variant))
    assert len(keys) == n_episodes
    return keys


def cmd_config_dev(args) -> int:
    """3 candidates x 3 family mini-runs + 评估 + 选择(§9/§10)。"""
    from rl_curriculum.ppo262_banks import (
        generate262_bank, staged_order,
    )
    from rl_curriculum.ppo262_train import (
        model_manifest_base, save_model_with_manifest, train_run,
    )
    from rl_curriculum.ppo262_metrics import (
        aggregate_capture, build_261_policy_set, capture_table,
        evaluate_policy_on_bank, family_core_capture, load_sb3_policy,
    )

    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    ns = "ppo_config_dev_262"
    steps_per_family = (
        PPO262_CONFIG_DEV_EPISODES_PER_FAMILY * 287)

    results: dict[str, Any] = {"candidates": {}, "eval_bank": {}}
    # 评估 bank(三族 D1 各 4 pairs)
    eval_keys = []
    for fam in PPO262_CONFIG_DEV_FAMILIES:
        eval_keys.extend(_mini_bank_keys(
            fam, PPO262_CONFIG_DEV_EVAL_PAIRS_PER_FAMILY * 2,
            namespace=ns, rung=PPO262_CONFIG_DEV_RUNG,
            pair_base=PPO262_CONFIG_DEV_EVAL_PAIR_BASE))
    eval_bank = generate262_bank(
        eval_keys, locked_plan_rung_params=rung_params)
    results["eval_bank"] = [e.key.canonical() for e in eval_bank]

    # reference + required baselines 在评估集上重跑(口径与 core/final 一致)
    ref_rows_all: list[dict[str, Any]] = []
    baseline_rows: dict[str, list[dict[str, Any]]] = {}
    for fam in PPO262_CONFIG_DEV_FAMILIES:
        fam_bank = [e for e in eval_bank if e.key.family == fam]
        pols = build_261_policy_set(
            fam, rung_params[fam][PPO262_CONFIG_DEV_RUNG],
            thresholds[fam])
        ref_rows_all.extend(evaluate_policy_on_bank(
            pols["reference"], fam_bank, collect_actions=False))
        for bname, pol in pols.items():
            if bname == "reference":
                continue
            baseline_rows.setdefault(bname, []).extend(
                evaluate_policy_on_bank(pol, fam_bank,
                                        collect_actions=False))

    for cand_name, cfg in PPO262_CANDIDATES.items():
        cand_result: dict[str, Any] = {"family_runs": {}}
        fam_tables = {}
        for fam in PPO262_CONFIG_DEV_FAMILIES:
            keys = staged_order(_mini_bank_keys(
                fam, PPO262_CONFIG_DEV_EPISODES_PER_FAMILY,
                namespace=ns, rung=PPO262_CONFIG_DEV_RUNG,
                pair_base=PPO262_CONFIG_DEV_TRAIN_PAIR_BASE))
            bank = generate262_bank(
                keys, locked_plan_rung_params=rung_params)
            mp = MODELS_DIR / f"configdev_{cand_name}_{fam}"
            run = train_run(
                bank, config_name=cand_name, config=cfg, model_seed=26201,
                total_timesteps=steps_per_family, order_name="staged",
                run_label=f"configdev/{cand_name}/{fam}",
                checkpoint_episodes=None)
            save_model_with_manifest(
                run["model"], mp, manifest=model_manifest_base(
                    config_name=cand_name, config=cfg, model_seed=26201,
                    order_name="staged",
                    run_label=f"configdev/{cand_name}/{fam}"))
            policy = load_sb3_policy(mp, f"{cand_name}/{fam}")
            rows = evaluate_policy_on_bank(
                policy, [e for e in eval_bank if e.key.family == fam])
            table = capture_table(
                rows,
                [r for r in ref_rows_all if r["family"] == fam],
                {k: [x for x in v if x["family"] == fam]
                 for k, v in baseline_rows.items()})
            fam_tables[fam] = table
            cand_result["family_runs"][fam] = {
                "audit": run["env_audit"],
                "pass": run["pass"],
                "fps": run["fps"],
            }
        cand_result["family_core_captures"] = {
            fam: family_core_capture(fam_tables[fam], fam)
            for fam in PPO262_CONFIG_DEV_FAMILIES}
        cand_result["aggregate_capture"] = aggregate_capture(fam_tables)
        cand_result["capture_tables"] = fam_tables
        results["candidates"][cand_name] = cand_result

    # 选择(锁定规则:主指标 aggregate capture;并列取方差小者;
    # 全部无 capture 区分时 fallback 中心候选——不影响 probe FAIL
    # 判定,只决定 probe 用哪份超参数跑,选择理由完整记录)
    scores = {
        name: res["aggregate_capture"]
        for name, res in results["candidates"].items()}
    results["candidate_scores"] = scores
    valid = {n: s for n, s in scores.items() if s is not None}
    selection_notes: dict[str, Any] = {}
    if valid:
        best = max(valid, key=valid.get)
        near = [n for n, s in valid.items()
                if abs(s - valid[best]) < 0.02]
        if len(near) > 1:
            import numpy as np
            best = min(
                near, key=lambda n: float(np.std([
                    v for v in results["candidates"][n][
                        "family_core_captures"].values()
                    if v is not None])) if any(
                    v is not None for v in results["candidates"][n][
                        "family_core_captures"].values()) else -9)
        results["selected_candidate"] = best
    else:
        results["selected_candidate"] = "cand_a_center"
        selection_notes["fallback_applied"] = (
            "三 candidate 的 aggregate capture 全部无区分(评估集上"
            "均坍塌为退化策略,capture <= 0);按仓库路线 fallback 选择"
            "中心候选 cand_a_center 供 probe 使用。诊断证据:三个"
            "candidate 在延长训练下同样坍塌(Always Long -> Always "
            "Flat),该选择不影响 probe 的 FAIL 判定。")
    results["selection_notes"] = selection_notes
    results["all_fail"] = all(
        (s is None or s <= 0) for s in scores.values()) or not scores
    _write_json(_art() / "ppo_config_development_result.json", results)
    sel = results["selected_candidate"]
    from rl_curriculum.ppo262_config import candidate_digest
    _write_json(_art() / "selected_ppo_config.json", {
        "selected_candidate": sel,
        "config": PPO262_CANDIDATES[sel] if sel else None,
        "config_digest": candidate_digest(sel) if sel else None,
        "candidates_tested": sorted(PPO262_CANDIDATES),
    })
    if sel:
        (_art() / "selected_ppo_config_digest.txt").write_text(
            candidate_digest(sel) + "\n", encoding="utf-8")
    print(json.dumps({
        "selected": sel, "scores": scores,
        "all_fail": results["all_fail"]}, ensure_ascii=False))
    return 0 if sel else 2


_MODEL_HOLDER: dict[str, Any] = {}


def cmd_probe(args) -> int:
    """单 family probe(§13):selected config + model seed 26201。"""
    from rl_curriculum.ppo262_banks import (
        EpisodeKey, generate262_bank, staged_order,
    )
    from rl_curriculum.ppo262_train import train_run
    from rl_curriculum.ppo262_metrics import (
        SB3PPOPolicy, aggregate_capture, build_261_policy_set,
        behavior_metrics, capture_table, evaluate_policy_on_bank,
        family_core_capture, load_sb3_policy,
    )

    family = args.family
    sel = json.loads((_art() / "selected_ppo_config.json").read_text(
        encoding="utf-8"))
    if not sel.get("selected_candidate"):
        print("错误:config dev 未选出 candidate", file=sys.stderr)
        return 2
    cand_name = sel["selected_candidate"]
    cfg = sel["config"]

    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    from rl_curriculum.ppo262_namespaces import PPO262_PROBE_NAMESPACES
    ns = PPO262_PROBE_NAMESPACES[family]

    layout = PPO262_PROBE_BUDGETS[family]
    keys = []
    for rung, n in ((r, layout[r]) for r in CURRICULUM261_RUNGS):
        n_pairs = n // 2
        for j in range(n_pairs):
            for variant in ("A", "B"):
                keys.append(EpisodeKey(ns, family, rung, j, variant))
    keys = staged_order(keys)
    total_eps = sum(layout.values())
    bank = generate262_bank(keys, locked_plan_rung_params=rung_params)

    mp = MODELS_DIR / f"probe_{family.split('_')[0]}"
    run = train_run(
        bank, config_name=cand_name, config=cfg, model_seed=26201,
        total_timesteps=total_eps * 287, order_name="staged(probe)",
        run_label=f"probe/{family}",
        checkpoint_episodes=None)
    from rl_curriculum.ppo262_train import (
        model_manifest_base, save_model_with_manifest,
    )
    save_model_with_manifest(
        run["model"], mp, manifest=model_manifest_base(
            config_name=cand_name, config=cfg, model_seed=26201,
            order_name="staged(probe)", run_label=f"probe/{family}"))

    # probe eval bank(该族 4 rung x 4 pairs,独立 namespace)
    eval_keys = []
    for rung in CURRICULUM261_RUNGS:
        for j in range(4):
            for variant in ("A", "B"):
                eval_keys.append(EpisodeKey(
                    "ppo_probe_eval_262", family, rung, j, variant))
    eval_bank = generate262_bank(
        eval_keys, locked_plan_rung_params=rung_params)

    policy = load_sb3_policy(mp, f"probe/{family}")
    rows = evaluate_policy_on_bank(policy, eval_bank)
    ref_rows, baseline_rows = _family_reference_rows(
        family, eval_bank, rung_params, thresholds)
    table = capture_table(rows, ref_rows, baseline_rows)
    core = family_core_capture(table, family)
    beh = behavior_metrics(rows, eval_bank)

    gaps = {
        "c1_opportunity": "selectivity_gap",
        "c2_context": "gating_gap",
        "c3_cost": "cost_selectivity_gap",
    }
    beh_gap = beh.get(family, {}).get(gaps[family])
    gate_capture = core is not None and core > 0.10
    gate_beh = beh_gap is not None and beh_gap > 0.10
    result = {
        "format": "ppo262-probe-result-v1",
        "family": family, "namespace": ns,
        "config": cand_name, "model_seed": 26201,
        "budget_episodes": total_eps,
        "budget_steps": total_eps * 287,
        "env_audit": run["env_audit"], "train_pass": run["pass"],
        "capture_table": table,
        "core_capture": core,
        "behavior": beh,
        "behavior_gap": beh_gap,
        "gate_core_capture_gt_0.10": gate_capture,
        "gate_behavior_gap_gt_0.10": gate_beh,
        "pass": bool(gate_capture and gate_beh and run["pass"]),
        "episode_curve": run["episode_curve"],
    }
    _write_json(_art() / f"probe_results_{family}.json", result)
    print(json.dumps({"family": family, "core_capture": core,
                      "behavior_gap": beh_gap, "pass": result["pass"]},
                     ensure_ascii=False))
    return 0 if result["pass"] else 2


def _family_reference_rows(family, bank, rung_params, thresholds):
    from rl_curriculum.ppo262_metrics import (
        build_261_policy_set, evaluate_policy_on_bank,
    )
    ref_rows: list[dict[str, Any]] = []
    baseline_rows: dict[str, list[dict[str, Any]]] = {}
    by_rung: dict[str, list] = {}
    for e in bank:
        by_rung.setdefault(e.key.rung, []).append(e)
    for rung, eps in by_rung.items():
        pols = build_261_policy_set(
            family, rung_params[family][rung], thresholds[family])
        ref_rows.extend(evaluate_policy_on_bank(
            pols["reference"], eps, collect_actions=False))
        for bname, pol in pols.items():
            if bname == "reference":
                continue
            baseline_rows.setdefault(bname, []).extend(
                evaluate_policy_on_bank(pol, eps, collect_actions=False))
    return ref_rows, baseline_rows


def cmd_core(args) -> int:
    """core run:replicate k x (staged|mixed)(§15-§18)。"""
    from rl_curriculum.ppo262_banks import (
        core_bank_keys, generate262_bank, manifest_equality, mixed_order,
        staged_order, bank_manifest,
    )
    from rl_curriculum.ppo262_train import (
        model_manifest_base, save_model_with_manifest, train_run,
    )

    replicate = int(args.replicate)
    order = args.order  # staged | mixed
    if order not in ("staged", "mixed"):
        print("order 必须是 staged|mixed", file=sys.stderr)
        return 2
    sel = json.loads((_art() / "selected_ppo_config.json").read_text(
        encoding="utf-8"))
    cand_name = sel["selected_candidate"]
    cfg = sel["config"]
    model_seed = PPO262_MODEL_SEEDS[replicate - 1]

    rung_params = _locked_rung_params()
    base_keys = core_bank_keys(replicate)
    keys = staged_order(base_keys) if order == "staged" else mixed_order(
        base_keys, model_seed=model_seed)
    if order == "mixed":
        eq = manifest_equality(staged_order(base_keys), keys)
        _write_json(
            _art() / f"manifest_pairing_integrity_rep{replicate}.json", eq)
        if not eq["pass"]:
            print(f"manifest equality 失败: {eq}", file=sys.stderr)
            return 2

    bank = generate262_bank(
        keys, locked_plan_rung_params=rung_params, progress=True)
    total_steps = len(bank) * 287

    prefix = MODELS_DIR / f"core_rep{replicate}_{order}"

    def saver(n_done, model):
        return save_model_with_manifest(
            model, Path(f"{prefix}_ep{n_done}"), manifest=model_manifest_base(
                config_name=cand_name, config=cfg, model_seed=model_seed,
                order_name=order,
                run_label=f"core/rep{replicate}/{order}/ep{n_done}"))

    run = train_run(
        bank, config_name=cand_name, config=cfg, model_seed=model_seed,
        total_timesteps=total_steps, order_name=order,
        run_label=f"core/rep{replicate}/{order}",
        checkpoint_episodes=PPO262_CHECKPOINT_EPISODES,
        checkpoint_saver=saver)
    if not run["pass"]:
        _write_json(_art() / f"training_run_summary_rep{replicate}_"
                    f"{order}.json",
                    {k: v for k, v in run.items() if k != "model"})
        print(f"训练审计失败: {run['audit_problems']}", file=sys.stderr)
        return 2
    # 模型侧车(bank manifest hash 绑定)
    summary = {k: v for k, v in run.items()
               if k not in ("episode_curve", "rollout_curve", "model",
                            "checkpoints")}
    summary["checkpoints_saved"] = sorted(run["checkpoints"])
    summary["bank_manifest_sha256"] = run["bank_manifest"][
        "manifest_sha256"]
    _write_json(
        _art() / f"training_run_summary_rep{replicate}_{order}.json",
        summary)
    _write_json(_art() / f"training_learning_curves_rep{replicate}_"
                f"{order}.json",
                {"episode_curve": run["episode_curve"],
                 "rollout_curve": run["rollout_curve"]})
    _write_json(
        _art() / f"{'staged' if order == 'staged' else 'mixed'}"
        f"_training_manifest_rep{replicate}.json",
        run["bank_manifest"])
    print(json.dumps({
        "replicate": replicate, "order": order,
        "steps": run["total_timesteps"], "fps": run["fps"],
        "manifest_sha256": summary["bank_manifest_sha256"],
        "pass": True}, ensure_ascii=False))
    return 0


def _dev_eval_bank_keys():
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    for fam in CURRICULUM261_FAMILIES:
        for rung in CURRICULUM261_RUNGS:
            for j in range(PPO262_DEV_EVAL_PAIRS_PER_RUNG):
                for variant in ("A", "B"):
                    keys.append(EpisodeKey(
                        "ppo_dev_eval_262", fam, rung, j, variant))
    return keys


def _final_eval_bank_keys():
    from rl_curriculum.ppo262_banks import EpisodeKey
    keys = []
    for fam in CURRICULUM261_FAMILIES:
        for rung in CURRICULUM261_RUNGS:
            for j in range(PPO262_FINAL_EVAL_PAIRS_PER_RUNG):
                for variant in ("A", "B"):
                    keys.append(EpisodeKey(
                        "ppo_final_eval_262", fam, rung, j, variant))
    return keys


def _reference_and_baselines(bank):
    """全部 family 的 reference + required baselines 在 bank 上重跑。"""
    from rl_curriculum.ppo262_metrics import evaluate_policy_on_bank
    rung_params = _locked_rung_params()
    thresholds = _locked_reference_thresholds()
    ref_rows: list[dict[str, Any]] = []
    baseline_rows: dict[str, list[dict[str, Any]]] = {}
    by_fr: dict[tuple, list] = {}
    for e in bank:
        by_fr.setdefault((e.key.family, e.key.rung), []).append(e)
    for (fam, rung), eps in sorted(by_fr.items()):
        from rl_curriculum.ppo262_metrics import build_261_policy_set
        pols = build_261_policy_set(
            fam, rung_params[fam][rung], thresholds[fam])
        ref_rows.extend(evaluate_policy_on_bank(
            pols["reference"], eps, collect_actions=False))
        for bname, pol in pols.items():
            if bname == "reference":
                continue
            baseline_rows.setdefault(bname, []).extend(
                evaluate_policy_on_bank(pol, eps, collect_actions=False))
    return ref_rows, baseline_rows


def _eval_matrix(bank, model_paths: dict[str, Path],
                 with_actions: bool = True):
    """在 bank 上评估全部模型 + reference/baselines,返回逐模型行集。"""
    from rl_curriculum.ppo262_metrics import (
        evaluate_policy_on_bank, load_sb3_policy,
    )
    out: dict[str, Any] = {}
    for label, path in model_paths.items():
        policy = load_sb3_policy(path, label)
        out[label] = evaluate_policy_on_bank(
            policy, bank, collect_actions=with_actions)
    ref_rows, baseline_rows = _reference_and_baselines(bank)
    out["__reference__"] = ref_rows
    out["__baselines__"] = baseline_rows
    return out


def cmd_dev_eval(args) -> int:
    """core 训练后的 development evaluation(可重复使用,非 sealed)。"""
    from rl_curriculum.ppo262_banks import generate262_bank
    from rl_curriculum.ppo262_metrics import (
        aggregate_capture, behavior_metrics, capture_table,
        family_core_capture,
    )
    rung_params = _locked_rung_params()
    bank = generate262_bank(
        _dev_eval_bank_keys(), locked_plan_rung_params=rung_params,
        progress=True)
    model_paths: dict[str, Path] = {}
    for rep in (1, 2, 3):
        for order in ("staged", "mixed"):
            for n in PPO262_CHECKPOINT_EPISODES:
                p = MODELS_DIR / f"core_rep{rep}_{order}_ep{n}.zip"
                if p.is_file():
                    model_paths[f"{order}_rep{rep}_ep{n}"] = p
    if not model_paths:
        print("错误:core 模型不存在", file=sys.stderr)
        return 2
    matrix = _eval_matrix(bank, model_paths)
    ref_rows = matrix.pop("__reference__")
    baseline_rows = matrix.pop("__baselines__")
    summary: dict[str, Any] = {"models": {}, "bank_size": len(bank)}
    for label, rows in matrix.items():
        table = capture_table(rows, ref_rows, baseline_rows)
        summary["models"][label] = {
            "capture_table": table,
            "core_captures": {
                fam: family_core_capture(table, fam)
                for fam in CURRICULUM261_FAMILIES},
            "aggregate_capture": aggregate_capture(table),
            "behavior": behavior_metrics(rows, bank),
            "mean_net_return": float(np.mean(
                [r["net_return"] for r in rows])),
        }
    _write_json(_art() / "dev_evaluation_results.json", summary)
    print(json.dumps({
        m: v["aggregate_capture"] for m, v in summary["models"].items()
        if "ep640" in m}, ensure_ascii=False))
    return 0


def _code_identity_262_now() -> dict[str, str]:
    import hashlib
    out = {}
    for f in sorted((PROJECT_ROOT / "src" / "rl_curriculum").glob(
            "ppo262_*.py")):
        out[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    return out


def cmd_final_lock(args) -> int:
    """锁定 final plan(模型/阈值/seed schedule;锁定后 corpus 才可生成)。"""
    from rl_curriculum.ppo262_input_lock import (
        PPO262_EXPECTED_VENDOR_SHA, run_input_lock,
    )
    from rl_curriculum.ppo262_final import (
        FINAL_PASS_THRESHOLDS, build_final_plan, lock_final_plan,
    )
    il = run_input_lock()
    if not il["pass"]:
        print(f"输入锁失败,禁止锁 final plan: {il['problems']}",
              file=sys.stderr)
        return 2
    sel = json.loads((_art() / "selected_ppo_config.json").read_text(
        encoding="utf-8"))
    # 训练 manifest hash + final model hash(必须已存在)
    training_manifest_hashes: dict[str, str] = {}
    model_hashes: dict[str, str] = {}
    import hashlib
    for rep in (1, 2, 3):
        for order in ("staged", "mixed"):
            mf = _art() / (f"{'staged' if order == 'staged' else 'mixed'}"
                           f"_training_manifest_rep{rep}.json")
            if not mf.is_file():
                print(f"缺少训练 manifest: {mf.name}", file=sys.stderr)
                return 2
            man = json.loads(mf.read_text(encoding="utf-8"))
            training_manifest_hashes[f"{order}_rep{rep}"] = man[
                "manifest_sha256"]
            for n in PPO262_CHECKPOINT_EPISODES:
                p = MODELS_DIR / f"core_rep{rep}_{order}_ep{n}.zip"
                if not p.is_file():
                    print(f"缺少模型: {p.name}", file=sys.stderr)
                    return 2
                model_hashes[f"{order}_rep{rep}_ep{n}"] = \
                    hashlib.sha256(p.read_bytes()).hexdigest()
    plan = build_final_plan(
        r2_plan_digest=il["r2_plan_digest"],
        stage261_code_identity=il["curriculum_source_identity"][
            "r2_code_identity"],
        code_identity_262=_code_identity_262_now(),
        selected_config_name=sel["selected_candidate"],
        selected_config=sel["config"],
        selected_config_digest=sel["config_digest"],
        training_manifest_hashes=training_manifest_hashes,
        model_hashes=model_hashes,
        model_seeds=list(PPO262_MODEL_SEEDS),
        final_seed_schedule={
            "namespace": "ppo_final_eval_262",
            "iteration": PPO262_ITERATION_ID,
            "pairs_per_rung": PPO262_FINAL_EVAL_PAIRS_PER_RUNG,
            "families": list(CURRICULUM261_FAMILIES),
            "rungs": list(CURRICULUM261_RUNGS),
            "pair_index_base": 0,
            "variants": ["A", "B"],
            "episode_seed_derivation": (
                "derive262_seed(namespace, family, rung, pair_index, "
                "attempt=0..4 first_pass)"),
        },
        metric_definitions={
            "capture": "(P - B) / (R - B),B=best required baseline mean,"
                       "R=reference mean,同 bank 重跑,不 clip",
            "family_core_capture": "0.20*D0 + 0.30*D1 + 0.50*D2",
            "aggregate_capture": "mean(C1,C2,C3 core capture)",
            "behavior_gaps": "C1 selectivity / C2 gating / C3 cost "
                             "selectivity(latent sidecar 事后打标签)",
            "retention": "staged final / phase capture(分母<=0 视为"
                         "从未学会)",
            "uncertainty": "pair-cluster bootstrap 90% pilot interval"
                           "(A/B 为单一 cluster)",
        },
        pass_thresholds=FINAL_PASS_THRESHOLDS,
        observation_identity=_observation_identity_snapshot(),
        preprocessing_boundary_name=(
            "real RouteCStrategy feature semantics + frozen Route C "
            "observation layout + causal unscaled curriculum feature "
            "values"),
        route_c_identities={
            "rl_platform_tree_hash": il["rl_platform_tree_hash"]["now"],
            "frozen_versions": il["route_c_frozen_versions"],
        },
        vendor_sha=PPO262_EXPECTED_VENDOR_SHA,
        git_baseline=_git_baseline(),
        schedule_comparison_rule={
            "delta_definition": "mean over 3 replicates of paired "
                                "(staged - mixed) aggregate capture",
            "prefer_staged_if": "delta >= 0.05 且 staged retention 通过",
            "prefer_mixed_if": "delta <= -0.05",
            "tie_band": "|delta| < 0.05 比较 seed 方差/retention/churn/"
                        "cost/worst-seed;无清晰优势报 both viable",
        })
    digest = lock_final_plan(plan, _art())
    (_art() / "final_evaluation_plan_digest.txt").write_text(
        digest + "\n", encoding="utf-8")
    print(json.dumps({"locked": True, "digest": digest,
                      "models_bound": len(model_hashes)},
                     ensure_ascii=False))
    return 0


def _observation_identity_snapshot() -> dict[str, Any]:
    from rl_curriculum.curriculum261_production_obs import (
        production_observation_identity,
    )
    return json.loads(json.dumps(
        production_observation_identity(), default=_np_default))


def _git_baseline() -> str:
    """本轮 baseline(主 git 仓库在 Windows 侧;WSL 侧记录常量)。"""
    return "1927faa647d34e4f45ed9c46d100f500081560b8"


# ---------------------------------------------------------------- final-run
def cmd_final_run(args) -> int:
    """one-shot sealed final evaluation(§6/§20)。

    guards(model hash/code identity/exposure)通过后:写 exposure ->
    生成 final bank -> 评估全部模型 + reference + baselines ->
    按锁定阈值判定 -> 写 raw/summary -> exposure 置 completed。
    """
    import hashlib
    from rl_curriculum.ppo262_banks import generate262_bank
    from rl_curriculum.ppo262_final import (
        begin_final_execution, load_locked_final_plan,
        verify_final_run_guards, write_final_eval_status_completed,
    )
    from rl_curriculum.ppo262_metrics import (
        aggregate_capture, behavior_metrics, capture_table,
        family_core_capture, pair_cluster_bootstrap_ci, retention_ratio,
    )

    plan, digest = load_locked_final_plan(_art())
    # 重建模型路径(键形如 staged_rep1_ep640)
    model_paths = {}
    for label in plan["model_hashes"]:
        order, rep, ep = label.split("_")
        rep_n = rep.replace("rep", "")
        ep_n = ep.replace("ep", "")
        model_paths[label] = (MODELS_DIR /
                              f"core_rep{rep_n}_{order}_ep{ep_n}.zip")
    problems = verify_final_run_guards(
        plan, models=model_paths, code_identity_262_now=_code_identity_262_now())
    if problems:
        print(json.dumps({"guards_failed": problems}, ensure_ascii=False),
              file=sys.stderr)
        return 2

    begin_final_execution(digest)

    rung_params = _locked_rung_params()
    bank = generate262_bank(
        _final_eval_bank_keys(), locked_plan_rung_params=rung_params,
        progress=True)
    matrix = _eval_matrix(bank, model_paths, with_actions=True)
    ref_rows = matrix.pop("__reference__")
    baseline_rows = matrix.pop("__baselines__")

    thresholds = plan["pass_thresholds"]
    raw: dict[str, Any] = {
        "format": "ppo262-final-raw-v1", "plan_digest": digest,
        "bank": [e.key.canonical() for e in bank],
        "models": {k: [dict(r, actions=None) for r in v]
                   for k, v in matrix.items()},
        "reference": ref_rows,
        "baselines": baseline_rows,
    }
    _write_json(_art() / "final_evaluation_raw.json", raw)

    # ---- 汇总与判定(只使用 locked thresholds)
    summary: dict[str, Any] = {
        "format": "ppo262-final-summary-v1", "plan_digest": digest,
        "n_pairs": len({(e.key.family, e.key.rung, e.key.pair_index)
                        for e in bank}),
        "n_episodes": len(bank), "schedules": {}}
    fam_capture_final: dict[str, dict[str, list[float]]] = {
        "staged": {f: [] for f in CURRICULUM261_FAMILIES},
        "mixed": {f: [] for f in CURRICULUM261_FAMILIES}}
    agg_by_schedule: dict[str, list[float]] = {"staged": [], "mixed": []}
    beh_by_schedule: dict[str, dict[str, list[float]]] = {
        "staged": {"c1": [], "c2": [], "c3": []},
        "mixed": {"c1": [], "c2": [], "c3": []}}
    churn_by_schedule: dict[str, list[float]] = {"staged": [], "mixed": []}
    model_summaries: {}
    for label, rows in matrix.items():
        table = capture_table(rows, ref_rows, baseline_rows)
        cores = {fam: family_core_capture(table, fam)
                 for fam in CURRICULUM261_FAMILIES}
        agg = aggregate_capture(table)
        beh = behavior_metrics(rows, bank)
        model_summaries[label] = {
            "capture_table": table, "core_captures": cores,
            "aggregate_capture": agg,
            "mean_net_return": float(np.mean(
                [r["net_return"] for r in rows])),
            "behavior": beh,
            "churn_per_100": _churn(rows),
        }
    summary["models"] = model_summaries

    # 每 schedule 聚合(3 seeds)
    for order in ("staged", "mixed"):
        s = summary["schedules"].setdefault(order, {})
        finals = [f"{order}_rep{r}_ep640" for r in (1, 2, 3)]
        per_family_means = {}
        for fam in CURRICULUM261_FAMILIES:
            vals = [model_summaries[m]["core_captures"][fam]
                    for m in finals]
            vals_f = [v for v in vals if v is not None]
            fam_capture_final[order][fam] = vals
            per_family_means[fam] = (
                float(np.mean(vals_f)) if len(vals_f) == 3 else None)
        s["family_core_capture_mean"] = per_family_means
        aggs = [model_summaries[m]["aggregate_capture"] for m in finals]
        agg_by_schedule[order] = aggs
        s["aggregate_capture_mean"] = (
            float(np.mean(aggs)) if all(a is not None for a in aggs)
            else None)
        s["aggregate_capture_by_seed"] = aggs
        # 行为 gap 聚合(三 seed)
        gaps = {
            "c1": [model_summaries[m]["behavior"]["c1_opportunity"][
                "selectivity_gap"] for m in finals],
            "c2": [model_summaries[m]["behavior"]["c2_context"][
                "gating_gap"] for m in finals],
            "c3": [model_summaries[m]["behavior"]["c3_cost"][
                "cost_selectivity_gap"] for m in finals]}
        for g, vals in gaps.items():
            vv = [v for v in vals if v is not None]
            beh_by_schedule[order][g] = vals
            s[f"{g}_behavior_gap_mean"] = (
                float(np.mean(vv)) if len(vv) == 3 else None)
        churn_by_schedule[order] = [
            model_summaries[m]["churn_per_100"] for m in finals]

        # A. 三族可学习
        fam_ok = all(
            (per_family_means[f] is not None
             and per_family_means[f] > thresholds[
                 "family_core_capture_mean_gt"])
            for f in CURRICULUM261_FAMILIES)
        seeds_positive = {
            f: sum(1 for v in fam_capture_final[order][f]
                   if v is not None and v > 0)
            for f in CURRICULUM261_FAMILIES}
        fam_seed_ok = all(
            n >= thresholds["family_seeds_positive_min"]
            for n in seeds_positive.values())
        s["checks"] = {"A_family_learnable": bool(fam_ok and fam_seed_ok),
                       "A_family_means": per_family_means,
                       "A_seeds_positive": seeds_positive}
        # B. 全局学习(pair-cluster bootstrap on paired rows)
        all_final_rows = [r for m in finals for r in matrix[m]]
        ci = pair_cluster_bootstrap_ci(all_final_rows)
        s["aggregate_ci90"] = ci
        s["checks"]["B_aggregate"] = bool(
            s["aggregate_capture_mean"] is not None
            and s["aggregate_capture_mean"] > thresholds[
                "aggregate_capture_mean_gt"]
            and ci["ci90_low"] > thresholds["aggregate_ci90_low_gt"])
        # C. 行为
        bg = thresholds["behavior_gap_gt"]
        s["checks"]["C_behavior"] = bool(
            s["c1_behavior_gap_mean"] is not None
            and s["c1_behavior_gap_mean"] > bg["c1_selectivity"]
            and s["c2_behavior_gap_mean"] is not None
            and s["c2_behavior_gap_mean"] > bg["c2_gating"]
            and s["c3_behavior_gap_mean"] is not None
            and s["c3_behavior_gap_mean"] > bg["c3_cost_selectivity"])
        # D. baseline superiority(按 family 聚合 D0-D2 / C3 用 D1-D3)
        s["checks"]["D_baseline_superiority"] = _baseline_superiority(
            matrix, finals, baseline_rows, raw)
        # E. 非退化
        s["checks"]["E_non_degenerate"] = _non_degenerate(
            matrix, finals)
        # F. retention(仅 staged 需要)
        if order == "staged":
            s["checks"]["F_retention"] = _staged_retention(
                model_summaries, thresholds)
        else:
            s["checks"]["F_retention"] = {"status": "not_applicable"}
        s["candidate_pass"] = all(
            v for k, v in s["checks"].items()
            if k != "F_retention") and (
            True if order == "mixed" else s["checks"][
                "F_retention"].get("pass", False))

    # staged vs mixed 比较(§25)
    delta = None
    if all(a is not None for a in agg_by_schedule["staged"]) and all(
            a is not None for a in agg_by_schedule["mixed"]):
        paired = [s - m for s, m in zip(agg_by_schedule["staged"],
                                        agg_by_schedule["mixed"])]
        delta = float(np.mean(paired))
    summary["schedule_comparison"] = {
        "delta_staged_minus_mixed": delta,
        "staged_aggregate_by_seed": agg_by_schedule["staged"],
        "mixed_aggregate_by_seed": agg_by_schedule["mixed"],
        "churn": churn_by_schedule,
        "staged_candidate_pass": summary["schedules"]["staged"][
            "candidate_pass"],
        "mixed_candidate_pass": summary["schedules"]["mixed"][
            "candidate_pass"],
    }
    summary["stage_pass"] = bool(
        summary["schedules"]["staged"]["candidate_pass"]
        or summary["schedules"]["mixed"]["candidate_pass"])
    _write_json(_art() / "final_evaluation_summary.json", summary)
    write_final_eval_status_completed(digest)
    print(json.dumps({
        "stage_pass": summary["stage_pass"],
        "staged": summary["schedules"]["staged"]["candidate_pass"],
        "mixed": summary["schedules"]["mixed"]["candidate_pass"],
        "delta": delta}, ensure_ascii=False))
    return 0


def _churn(rows) -> float:
    import numpy as np
    total_changes, total_steps = 0, 0
    for r in rows:
        if r["actions"] is None:
            continue
        a = np.asarray(r["actions"])
        total_changes += int(np.sum(np.diff(a) != 0))
        total_steps += len(a)
    return 100.0 * total_changes / total_steps if total_steps else None


def _baseline_superiority(matrix, finals, baseline_rows, raw) -> dict:
    """§23 D:family 聚合上 PPO 优于 required baselines。"""
    fams = {
        "c1_opportunity": ("D0", "D1", "D2"),
        "c2_context": ("D0", "D1", "D2"),
        "c3_cost": ("D1", "D2", "D3")}
    out = {}
    for fam, rungs in fams.items():
        ppo_vals = [r["net_return"] for m in finals for r in matrix[m]
                    if r["family"] == fam and r["rung"] in rungs]
        res = {"ppo_mean": float(np.mean(ppo_vals)) if ppo_vals else None}
        ok = ppo_vals is not None and bool(ppo_vals)
        for bname, brows in baseline_rows.items():
            bvals = [r["net_return"] for r in brows
                     if r["family"] == fam and r["rung"] in rungs]
            res[bname] = float(np.mean(bvals)) if bvals else None
            if bvals and res["ppo_mean"] is not None:
                ok = ok and res["ppo_mean"] > res[bname]
            elif not bvals:
                ok = False
        res["pass"] = bool(ok)
        out[fam] = res
    out["pass"] = all(v["pass"] for v in out.values()
                      if isinstance(v, dict))
    return out


def _non_degenerate(matrix, finals) -> bool:
    """§23 E:不得全 Flat / 全 Long;必须有 observation-dependent 变化。"""
    import numpy as np
    all_acts = []
    for m in finals:
        for r in matrix[m]:
            if r["actions"] is not None:
                all_acts.extend(r["actions"])
    a = np.asarray(all_acts)
    if len(a) == 0:
        return False
    all_flat = bool(np.all(a == 0))
    all_long = bool(np.all(a == 1))
    varies = any(
        len(set(r["actions"])) > 1 for m in finals
        for r in matrix[m] if r["actions"])
    return (not all_flat) and (not all_long) and varies


def _staged_retention(model_summaries, thresholds) -> dict:
    """§22/§23 F:staged C1/C2 retention(分母<=0 = 从未学会)。"""
    out = {"c1": None, "c2": None}
    for rep in (1, 2, 3):
        final = model_summaries.get(f"staged_rep{rep}_ep640")
        after_c1 = model_summaries.get(f"staged_rep{rep}_ep160")
        after_c2 = model_summaries.get(f"staged_rep{rep}_ep400")
        if not (final and after_c1 and after_c2):
            continue
        for fam_key, phase_model, gate in (
                ("c1", after_c1, "c1_opportunity"),
                ("c2", after_c2, "c2_context")):
            rr = retention_ratio(
                final["core_captures"].get(gate),
                phase_model["core_captures"].get(gate))
            out.setdefault(f"{fam_key}_per_rep", {})[f"rep{rep}"] = rr
    ok = True
    for fam_key, min_r in thresholds["staged_retention_min"].items():
        pers = out.get(f"{fam_key}_per_rep", {})
        ratios = [v["ratio"] for v in pers.values()
                  if v.get("ratio") is not None]
        never = [v for v in pers.values()
                 if str(v.get("status", "")).startswith("never_learned")]
        # retention gate:三 replicate 均值 >= min(且无 never_learned 掩盖)
        if never or not ratios:
            ok = False
            out[f"{fam_key}_mean_ratio"] = None
        else:
            m = float(np.mean(ratios))
            out[f"{fam_key}_mean_ratio"] = m
            ok = ok and m >= min_r
    out["pass"] = bool(ok)
    return out


# ---------------------------------------------------------------- summarize
def cmd_summarize(args) -> int:
    """汇总全部 2.6.2 artifacts -> 汇总判定(报告的机器可读底稿)。"""
    art_dir = _art()
    summary: dict[str, Any] = {"format": "ppo262-regression-summary-v1",
                               "stage": "stage2_6_2"}
    checks = {}
    for name, fname in (
            ("input_lock", "input_lock.json"),
            ("seed_namespace_integrity", "seed_namespace_integrity.json"),
            ("ppo_smoke", "ppo_smoke.json")):
        p = art_dir / fname
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            checks[name] = bool(d.get("pass"))
        else:
            checks[name] = None
    probes = {}
    for fam in CURRICULUM261_FAMILIES:
        p = art_dir / f"probe_results_{fam}.json"
        probes[fam] = (bool(json.loads(p.read_text(encoding="utf-8"))[
            "pass"]) if p.is_file() else None)
    checks["probes_all_pass"] = (
        all(v is True for v in probes.values())
        if probes else None)
    core_runs = {}
    for rep in (1, 2, 3):
        for order in ("staged", "mixed"):
            p = art_dir / f"training_run_summary_rep{rep}_{order}.json"
            core_runs[f"{order}_rep{rep}"] = (
                bool(json.loads(p.read_text(encoding="utf-8"))["pass"])
                if p.is_file() else None)
    checks["core_runs_all_pass"] = (
        all(v is True for v in core_runs.values())
        if core_runs else None)
    final = art_dir / "final_evaluation_summary.json"
    if final.is_file():
        fs = json.loads(final.read_text(encoding="utf-8"))
        checks["final_executed_once"] = True
        checks["stage_pass_final"] = bool(fs["stage_pass"])
        summary["final"] = {
            "staged_candidate_pass": fs["schedules"]["staged"][
                "candidate_pass"],
            "mixed_candidate_pass": fs["schedules"]["mixed"][
                "candidate_pass"],
            "delta": fs["schedule_comparison"][
                "delta_staged_minus_mixed"]}
    else:
        checks["final_executed_once"] = False
    summary["checks"] = checks
    summary["probes"] = probes
    summary["core_runs"] = core_runs
    summary["stage_verdict"] = (
        "PASS" if all(v is True for v in checks.values()) else "FAIL")
    _write_json(art_dir / "regression_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, default=_np_default))
    return 0


def cmd_config_dev_select(args) -> int:
    """从已有 config dev result 重新执行选择(不重训练)。

    第一轮选择规则的 tie-break 未覆盖"全部 capture 无区分"的实测
    情形;本命令应用补充 fallback 并把理由写入 result。
    """
    rp = _art() / "ppo_config_development_result.json"
    results = json.loads(rp.read_text(encoding="utf-8"))
    scores = results.get("candidate_scores", {})
    valid = {n: s for n, s in scores.items() if s is not None}
    notes: dict[str, Any] = {}
    if valid:
        best = max(valid, key=valid.get)
        near = [n for n, s in valid.items() if abs(s - valid[best]) < 0.02]
        if len(near) > 1:
            import numpy as np
            best = min(
                near, key=lambda n: float(np.std([
                    v for v in results["candidates"][n][
                        "family_core_captures"].values()
                    if v is not None])) if any(
                    v is not None for v in results["candidates"][n][
                        "family_core_captures"].values()) else -9)
        selected = best
    else:
        selected = "cand_a_center"
        notes["fallback_applied"] = (
            "三 candidate 的 aggregate capture 全部无区分(评估集上均"
            "坍塌为退化策略,capture <= 0);按仓库路线 fallback 选择中心"
            "候选 cand_a_center 供 probe 使用。诊断证据:三个 candidate "
            "在延长训练下同样坍塌(Always Long -> Always Flat),该选择"
            "不影响 probe 的 FAIL 判定。")
    results["selected_candidate"] = selected
    results["selection_notes"] = notes
    results["all_fail"] = all(
        (s is None or s <= 0) for s in scores.values()) or not scores
    _write_json(rp, results)
    from rl_curriculum.ppo262_config import candidate_digest
    _write_json(_art() / "selected_ppo_config.json", {
        "selected_candidate": selected,
        "config": PPO262_CANDIDATES[selected],
        "config_digest": candidate_digest(selected),
        "candidates_tested": sorted(PPO262_CANDIDATES),
        "selection_notes": notes,
    })
    (_art() / "selected_ppo_config_digest.txt").write_text(
        candidate_digest(selected) + "\n", encoding="utf-8")
    print(json.dumps({"selected": selected, "all_fail": results["all_fail"],
                      "notes": notes}, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="ppo262")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("input-lock").set_defaults(func=cmd_input_lock)
    sub.add_parser("seed-integrity").set_defaults(func=cmd_seed_integrity)
    sub.add_parser("ppo-smoke").set_defaults(func=cmd_ppo_smoke)
    sub.add_parser("config-dev-plan").set_defaults(func=cmd_config_dev_plan)
    sub.add_parser("config-dev").set_defaults(func=cmd_config_dev)
    sub.add_parser("config-dev-select").set_defaults(func=cmd_config_dev_select)
    p = sub.add_parser("probe")
    p.add_argument("family", choices=list(CURRICULUM261_FAMILIES))
    p.set_defaults(func=cmd_probe)
    p = sub.add_parser("core")
    p.add_argument("replicate", type=int, choices=[1, 2, 3])
    p.add_argument("order", choices=["staged", "mixed"])
    p.set_defaults(func=cmd_core)
    sub.add_parser("dev-eval").set_defaults(func=cmd_dev_eval)
    sub.add_parser("final-lock").set_defaults(func=cmd_final_lock)
    sub.add_parser("final-run").set_defaults(func=cmd_final_run)
    sub.add_parser("summarize").set_defaults(func=cmd_summarize)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
