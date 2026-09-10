# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:PolicyVisibleSupervisedLabel-v1(§8)。

R9 确认输入(监督标签语义错误):
- R6/R9 的 _collect_supervised_dataset_r6 把 raw reference policy 直接
  运行在 scaled episode 上 —— raw threshold 直接作用于 MinMax-scaled
  feature,标签既不是合法 raw 语义也不是合法 scaled 语义。

R12 修复(§8.1 构造路径):
- 输入 = PPO 实际可见的 scaled float32 observation(8 scaled 特征 +
  position 槽位,生产 env 唯一投影);
- 标签 = 同一 episode、同一 position path 下,合法 causal reference
  在 canonical episode(policy-visible canonicalization,§11 Branch B)
  上的逐步 action;
- 双 env 同步 replay:canonical env 供 reference 决策,scaled env 产出
  dataset observation;两 env 由同一 action 序列驱动 → position 逐位
  一致;
- 禁止 raw reference 直接读取 scaled observation(结构性保证:label
  决策只接收 canonical obs)。

§8.2 action-replay 对齐验证:dataset scaled obs == scaled replay env
obs、dataset position == replay position、label == canonical causal
reference action(独立重跑逐位断言)。
"""

from __future__ import annotations

from typing import Any

import numpy as np

from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_production_obs import (
    PRODUCTION_FEATURE_COLUMNS,
)
from rl_curriculum.curriculum261_qualification import build_policy_set
from rl_curriculum.curriculum261_r3_obs import scaled_episode
from rl_curriculum.curriculum261_r12_reference import (
    SUPERVISED_LABEL_CONTRACT,
    canonical_episode,
)
from rl_curriculum.curriculum261_r4_obs import r4_observation_schema
from rl_curriculum.curriculum261_r4_pairs import EVAL_CFG, RAW_SCHEMA
from rl_curriculum.curriculum261_r6_param_pack import (
    r6_family_rung_params,
)
from rl_curriculum.evaluator import (
    derive_episode_seed,
    run_policy_episode,
    select_features_strict,
)

_LABEL_SOURCE = "canonical_reference_on_canonical_obs"


def _build_env_for(episode: Any, schema: Any) -> Any:
    """与 evaluator._build_env 同构的 env(features 按 schema 严格选)。"""
    from rl_platform.env import AlignedLongFlatEnv

    features = select_features_strict(
        episode.df, schema, context="supervised_label_r12")
    return AlignedLongFlatEnv(
        features=features,
        prices=episode.df[list(("open", "high", "low", "close"))],
        fee=EVAL_CFG.fee, slippage_bps=EVAL_CFG.slippage_bps,
        initial_cash=EVAL_CFG.initial_cash,
        reward_scale=EVAL_CFG.reward_scale,
        window_size=EVAL_CFG.window_size, price_tick=EVAL_CFG.price_tick,
        execution_mode="market_open_causal",
    )


def _replay_canonical_reference(
        reference: Any, canon_ep: Any) -> tuple[list[int], list[np.ndarray]]:
    """canonical episode 上的 causal reference 决策序列 + obs 序列。

    与 evaluator.run_observation_episode 相同的 policy state 语义
    (episode_instance + reset_episode;§10.3 policy state 排查)。
    """
    reference.bind_observation_schema(RAW_SCHEMA)
    ep_pol = reference.episode_instance(
        derive_episode_seed(canon_ep.spec))
    if ep_pol is not reference and hasattr(ep_pol, "bind_observation_schema"):
        ep_pol.bind_observation_schema(RAW_SCHEMA)
    env = _build_env_for(canon_ep, RAW_SCHEMA)
    obs, _ = env.reset(seed=canon_ep.spec.seed)
    ep_pol.reset_episode()
    actions: list[int] = []
    obs_seq: list[np.ndarray] = []
    done = False
    while not done:
        obs_seq.append(np.array(obs))
        action = int(ep_pol.act(obs))  # 只接收 canonical obs(raw 语义)
        obs, _r, terminated, truncated, _i = env.step(action)
        done = terminated or truncated
        actions.append(action)
    return actions, obs_seq


def collect_policy_visible_dataset_r12(
        records: list[Any], family: str,
        rung_params_by_rung: dict[str, dict[str, Any]],
        preproc_v2: Any, *, eval_namespace: str,
        evidence_per_episode: int = 3) -> dict[str, Any]:
    """构造 PolicyVisibleSupervisedLabel-v1 数据集(单 family)。

    返回 rows:family/rung/pair/side/step/obs(scaled float32)/label/
    position;evidence:每 episode 抽 evidence_per_episode 步的全字段
    证据(§8.5);alignment:§8.2 三项对齐断言的聚合结果。
    """
    preproc = (preproc_v2.inner if hasattr(preproc_v2, "inner")
                else preproc_v2)
    inner = preproc
    schema = r4_observation_schema(preproc_v2)
    specs = family_specs()
    thresholds = dict(specs[family].reference_defaults)
    rows: list[dict[str, Any]] = []
    evidence: list[dict[str, Any]] = []
    alignment_failures: list[str] = []
    episode_alignment_records: list[dict[str, Any]] = []
    n_steps_total = 0
    n_rows_expected_total = 0
    n_episodes = 0
    for rec in records:
        rung_params = dict(rung_params_by_rung[rec.rung])
        rung_params["cur261_rung"] = rec.rung
        raw_set = build_policy_set(family, rung_params, thresholds)
        for side in ("A", "B"):
            ep = rec.episodes[side]
            canon_ep = canonical_episode(ep, inner)
            scaled_ep = scaled_episode(ep, inner)
            ep_alignment_ok = True
            # ---- 独立 canonical replay(labels 的唯一来源)----
            label_actions, canon_obs_seq = _replay_canonical_reference(
                raw_set["reference"], canon_ep)
            # ---- 双 env 同步 replay(生产 obs 收集)----
            reference2 = raw_set["reference"]
            reference2.bind_observation_schema(RAW_SCHEMA)
            ep_pol = reference2.episode_instance(
                derive_episode_seed(canon_ep.spec))
            if ep_pol is not reference2 and hasattr(
                    ep_pol, "bind_observation_schema"):
                ep_pol.bind_observation_schema(RAW_SCHEMA)
            env_label = _build_env_for(canon_ep, RAW_SCHEMA)
            env_obs = _build_env_for(scaled_ep, schema)
            obs_l, _ = env_label.reset(seed=ep.spec.seed)
            obs_d, _ = env_obs.reset(seed=ep.spec.seed)
            ep_pol.reset_episode()
            steps: list[dict[str, Any]] = []
            done = False
            while not done:
                if int(obs_l[-1]) != int(obs_d[-1]):
                    alignment_failures.append(
                        f"{family}/{rec.rung}/p{rec.pair_index}/{side}:"
                        f"position 分歧(label={obs_l[-1]},"
                        f"dataset={obs_d[-1]})")
                    ep_alignment_ok = False
                act = int(ep_pol.act(obs_l))  # 只接收 canonical obs
                steps.append({
                    "obs": np.array(obs_d, dtype=np.float32),
                    "action": act,
                    "position": int(obs_l[-1]),
                })
                obs_l, _r1, t1, tr1, _i1 = env_label.step(act)
                obs_d, _r2, t2, tr2, _i2 = env_obs.step(act)
                done = (t1 or tr1) or (t2 or tr2)
                if (t1 or tr1) != (t2 or tr2):
                    alignment_failures.append(
                        f"{family}/{rec.rung}/p{rec.pair_index}/{side}:"
                        f"终止分歧(label={bool(t1 or tr1)},"
                        f"dataset={bool(t2 or tr2)})")
                    ep_alignment_ok = False
            # ---- §8.2 对齐断言 ----
            if len(steps) != len(label_actions):
                alignment_failures.append(
                    f"{family}/{rec.rung}/p{rec.pair_index}/{side}:"
                    f"步数不一致(replay={len(steps)},"
                    f"labels={len(label_actions)})")
                ep_alignment_ok = False
            else:
                for t, (st, la) in enumerate(zip(steps, label_actions)):
                    if st["action"] != la:
                        alignment_failures.append(
                            f"{family}/{rec.rung}/p{rec.pair_index}/"
                            f"{side}@{t}:label != canonical action")
                        ep_alignment_ok = False
                        break
            # canonical replay 与 run_policy_episode 独立对照(确定性;
            # 每 family 前 2 个 episode 全量对照,其余结构保证+抽检)
            n_episodes += 1
            if n_episodes <= 2:
                r_ref = run_policy_episode(
                    raw_set["reference"], canon_ep, EVAL_CFG, RAW_SCHEMA,
                    return_actions=True)
                if list(r_ref[1]) != label_actions:
                    alignment_failures.append(
                        f"{family}/{rec.rung}/p{rec.pair_index}/{side}:"
                        f"canonical replay 与正式评估器 action 序列不一致")
                    ep_alignment_ok = False
            raw_x64 = ep.df[list(PRODUCTION_FEATURE_COLUMNS)].to_numpy(
                dtype=np.float64)
            # ---- repair R12(B1):逐 episode 对齐记录(全量聚合输入)----
            episode_alignment_records.append({
                "rung": rec.rung, "pair": rec.pair_index, "side": side,
                "ok": bool(ep_alignment_ok),
                "n_steps": len(steps),
                "n_label_actions": len(label_actions),
                "steps_eq_labels": len(steps) == len(label_actions),
            })
            n_rows_expected_total += len(steps)
            for t, st in enumerate(steps):
                rows.append({
                    "family": family, "rung": rec.rung,
                    "pair": rec.pair_index, "side": side, "step": t,
                    "obs": st["obs"], "action": st["action"],
                    "position": st["position"],
                })
                n_steps_total += 1
            # ---- label evidence(§8.5)----
            idxs = sorted(set(
                [0, len(steps) // 2, len(steps) - 1]
                + [t for t, st in enumerate(steps)
                   if st["action"] == 1][:1]))[:evidence_per_episode]
            for t in idxs:
                evidence.append({
                    "family": family, "rung": rec.rung,
                    "pair": rec.pair_index, "side": side, "step": t,
                    "raw_feature_summary": raw_x64[min(
                        t, len(raw_x64) - 1)].tolist(),
                    "scaled_input_summary": steps[t]["obs"].tolist(),
                    "position": steps[t]["position"],
                    "label_source": _LABEL_SOURCE,
                    "label": steps[t]["action"],
                    "replay_action": label_actions[min(
                        t, len(label_actions) - 1)],
                    "canonical_obs_summary": np.asarray(
                        canon_obs_seq[min(t, len(canon_obs_seq) - 1)]
                    ).tolist(),
                    "alignment_ok": ep_alignment_ok,
                    "bundle_hash": getattr(preproc_v2, "bundle_hash",
                                        "unbundled-diagnostic"),
                })
    # ---- repair R12(B1):alignment 全量聚合(fail closed)----
    # R10 缺陷:返回的 alignment_ok 取自循环最后一个 episode 的
    # ep_alignment_ok —— 早期 episode 失败、末尾成功时总体仍可能为
    # true。R12 合同:所有 episode 均对齐 AND alignment_failures 为空
    # AND 行数/action 长度账目一致;任一不满足即 False。
    episodes_all_ok = bool(episode_alignment_records) and all(
        r["ok"] for r in episode_alignment_records)
    steps_labels_consistent = all(
        r["steps_eq_labels"] for r in episode_alignment_records)
    row_accounting_ok = bool(
        len(rows) == n_steps_total == n_rows_expected_total)
    alignment_ok_aggregate = bool(
        episodes_all_ok
        and not alignment_failures
        and steps_labels_consistent
        and row_accounting_ok)
    return {
        "format": "cur261-r12-policy-visible-supervised-dataset-v1",
        "label_contract": SUPERVISED_LABEL_CONTRACT,
        "label_source": _LABEL_SOURCE,
        "family": family,
        "eval_namespace": eval_namespace,
        "bundle_hash": getattr(preproc_v2, "bundle_hash",
                                        "unbundled-diagnostic"),
        "rows": rows,
        "n_rows": len(rows),
        "n_steps_total": n_steps_total,
        "n_rows_expected_total": n_rows_expected_total,
        "evidence": evidence,
        "alignment_failures": alignment_failures,
        "alignment_ok": alignment_ok_aggregate,
        "alignment_aggregation": {
            "rule": ("all episodes ok AND alignment_failures empty AND "
                     "steps==labels per episode AND row accounting "
                     "consistent(任何一个 episode 失败 => family "
                     "supervised gate fail closed)"),
            "n_episodes": len(episode_alignment_records),
            "episodes_all_ok": episodes_all_ok,
            "alignment_failures_empty": not alignment_failures,
            "steps_labels_consistent": steps_labels_consistent,
            "row_accounting_ok": row_accounting_ok,
            "episode_alignment_records": episode_alignment_records,
        },
        "raw_policy_reads_scaled_obs": False,
        "pair_identity_split": True,
    }


def supervised_dataset_identity_r12(
        dataset: dict[str, Any]) -> dict[str, Any]:
    """数据集身份摘要(§30 supervised_dataset_identity)。"""
    labels = np.asarray([r["action"] for r in dataset["rows"]],
                        dtype=np.int64)
    obs = (np.stack([r["obs"] for r in dataset["rows"]])
           if dataset["rows"] else np.zeros((0, 9), dtype=np.float32))
    return {
        "format": "cur261-r12-supervised-dataset-identity-v1",
        "label_contract": dataset["label_contract"],
        "family": dataset["family"],
        "eval_namespace": dataset["eval_namespace"],
        "bundle_hash": dataset["bundle_hash"],
        "n_rows": int(dataset["n_rows"]),
        "obs_dtype": "float32",
        "obs_shape": list(obs.shape),
        "obs_finite": bool(np.isfinite(obs.astype(np.float64)).all()),
        "label_counts": {
            "0": int(np.sum(labels == 0)),
            "1": int(np.sum(labels == 1)),
        },
        "long_label_rate": float(np.mean(labels)) if len(labels) else None,
        "pairs": sorted({(r["rung"], r["pair"]) for r in dataset["rows"]}),
        "alignment_ok": dataset["alignment_ok"],
    }
