# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R12:full-scale shadow rehearsal(工作包 C)。

R10 确认输入(tiny rehearsal 未覆盖正式 C3 supervised 生成规模,
无法捕获正式失败):R10 的 preplan rehearsal 是微样本(4 pairs/
rung),正式 supervised 的 10 pairs/rung × 全 family × 全 rung ×
C3 D0-D3 全部 pair index 从未在冻结前被完整执行过。

R12 修复(§C):implementation freeze 之前,以专门的 shadow
namespace 执行接近正式规模的全链 rehearsal:
- 与正式流程相同的 orchestrator(orchestrate_calibration_stage_
  r12)与核心(execute_final_core_r12);禁止 monkeypatch 正式函数;
- generation cardinality 不缩小(见 SHADOW_CARDINALITY);
- 可以缩短的只有纯训练计算(MLP epoch 与 model seed 数量),
  不减少任何会改变生成调用路径覆盖的 family/rung/pair 坐标;
- 至少两次独立 cold-process rehearsal(每次一个全新 python 进程,
  由 CLI shadow-run 逐次调用);除声明为非身份的字段(时间戳等)
  外:invocation digests / episode hashes / gate 输入 / artifact
  canonical digests 必须一致(compare_full_scale_shadow_runs)。

若 full-scale shadow 出现任何异常,必须在 freeze 前修复并重新
执行;不得带着未解释异常进入正式 namespace。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
from rl_curriculum.curriculum261_generation_envelope import (
    ledger_rows_digest,
    read_envelope_ledger,
    stable_digest,
)
from rl_curriculum.curriculum261_pairs import family_specs
from rl_curriculum.curriculum261_r12_routing import build_routing_r12

SHADOW_FORMAT = "cur261-r12-full-scale-shadow-rehearsal-v1"

#: shadow 的 C2 matched block 数:FORMAL_BLOCK_OPTIONS={10,15,20} 的
#: 最大值 —— 无论 R12 机械选出哪个 n,shadow 的生成坐标都是其超集。
SHADOW_C2_BLOCKS = 20
#: shadow 的 supervised 训练削减(仅纯训练计算;不改变生成覆盖)。
SHADOW_MODEL_SEEDS: tuple[int, ...] = (20270121,)
SHADOW_TRAINING_CONFIG: dict[str, Any] = {"epochs": 2}

#: 双跑一致性比较中声明为**非身份**的字段(时间戳/临时目录等)。
SHADOW_NON_IDENTITY_KEY_SUFFIXES = (
    "_utc", "_started", "_duration", "_elapsed", "_timestamp")
SHADOW_NON_IDENTITY_KEYS = (
    "started", "written_utc", "completed_utc", "aborted_utc",
    "run_tag", "started_utc")
#: 声明为非身份的**路径**:每次运行自己的摘要文件(文件名含 run_tag,
#: 内容为运行日志;两次运行的对应关系为 shadow_rehearsal_A.json
#: <-> shadow_rehearsal_B.json)。
SHADOW_NON_IDENTITY_PATH_SUFFIXES = (
    "shadow_rehearsal_A.json", "shadow_rehearsal_B.json")


def _is_non_identity_path(rel: str) -> bool:
    return any(rel.endswith(sfx)
               for sfx in SHADOW_NON_IDENTITY_PATH_SUFFIXES)


def _shadow_pack() -> dict[str, Any]:
    """full-scale shadow 工程 pack(historical control ladder;非正式)。

    不携带任何正式 digest(工程;不进入参数选择)。c2 matched block
    数取 20(见 SHADOW_C2_BLOCKS)。
    """
    from rl_curriculum.curriculum261_r12_param_pack import (
        ladder_pack_payload_r12,
        pack_digest_r12,
        r12_candidate_grid,
    )

    grid = r12_candidate_grid()
    ladder = grid["c2l_historical_control"]
    pack = ladder_pack_payload_r12(
        selected_c2_candidate="c2l_historical_control",
        c2_ladder=ladder,
        selected_block_count=SHADOW_C2_BLOCKS,
        design_plan_digest="r12dp-shadow-engineering",
        matched_contract_identity="shadow-engineering",
        block_integrity_identity="shadow-engineering",
        cue_semantic_contract_digest="r12cue-shadow-engineering",
        cue_semantic_rule_identity="shadow-engineering",
        cue_audit_digest="r12ca-shadow-engineering",
        p_contract=0.9504,
        recall_floor_value=0.9304,
        noninferiority_delta=0.02,
        semantic_blocks_per_corpus=160,
        baseline_commit="shadow",
    )
    pack["digest"] = pack_digest_r12(pack)
    return pack


def _shadow_override_fn(family: str, pack: dict[str, Any]):
    """与正式 r12_override_for 同构的覆盖函数(shadow 工程 pack)。"""
    d3 = pack.get("d3_overrides", {})
    if family in d3:
        return {"D3": dict(d3[family])}
    return None


def _shadow_final_plan_stub(pack: dict[str, Any]) -> dict[str, Any]:
    """final-like shadow 的 plan stub(仅提供 core 需要的字段)。"""
    return {
        "final_sample_counts": {
            "c2_matched_blocks": SHADOW_C2_BLOCKS, "c1_pairs": 40,
            "c3_pairs": 40, "independent": 80, "semantic_blocks": 160,
            "semantic_episodes": 1280, "core": 80 + 4 * SHADOW_C2_BLOCKS,
            "total": 2 * (80 + 4 * SHADOW_C2_BLOCKS) + 2 * 80 + 1280},
        "recall_floor": float(pack["recall_floor"]),
        "reference_thresholds_by_family": {
            f: dict(family_specs()[f].reference_defaults)
            for f in CURRICULUM261_FAMILIES},
    }


def run_full_scale_shadow_r12(out_dir: Path, *, run_tag: str) -> dict:
    """full-scale shadow rehearsal(每次调用应运行在一个独立冷进程)。

    产物写入 out_dir(含 generation_invocation_ledger.jsonl);摘要写
    shadow_rehearsal_{run_tag}.json。任何异常如实向上抛出 —— shadow
    异常必须在 freeze 前修复,不得带着未解释异常进入正式 namespace。
    """
    from rl_curriculum.curriculum261_r12_calibration import (
        fit_preprocessor_v2_from_bank_r12,
        generate_fit_bank_r12,
    )
    from rl_curriculum.curriculum261_r12_final import (
        execute_final_core_r12,
    )
    from rl_curriculum.curriculum261_r12_orchestrator import (
        shadow_holdout_profile_r12,
        shadow_main_profile_r12,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")
    pack = _shadow_pack()
    summary: dict[str, Any] = {
        "format": SHADOW_FORMAT,
        "iteration": "r12",
        "run_tag": str(run_tag),
        "started_utc": started,
        "monkeypatch_used": False,
        "engineering_pack_digest": pack["digest"],
        "cardinality": {
            "c13_pairs_per_rung": 10,
            "equivalence_pairs_per_rung": 3,
            "supervised_pairs_per_rung": 10,
            "supervised_coverage":
                "全部三 family × 全部 rung × 全部 pair index(含 C3 "
                "D0-D3)",
            "semantic_blocks": 160,
            "c2_matched_blocks": SHADOW_C2_BLOCKS,
            "c2_independent_pairs_per_rung": 20,
            "roles": ["main", "holdout"],
            "formal_order_held": (
                "preprocessing robustness/reference-equivalence 电池先于 "
                "supervised(orchestrate_calibration_stage_r12 正式顺序)"),
            "training_reduction": (
                "仅纯训练计算:1 model seed + epochs=2(不改变任何生成"
                "调用路径覆盖)"),
        },
    }

    # ---- 1) main/holdout fit(shadow namespace;全量 fit bank)----
    routings: dict[str, Any] = {}
    records: dict[str, list] = {}
    bundles: dict[str, Any] = {}
    for role, fit_ns in (("main", "shadow_fit_main_r12"),
                         ("holdout", "shadow_fit_holdout_r12")):
        bank = generate_fit_bank_r12(fit_ns, pack)
        v2, _manifest = fit_preprocessor_v2_from_bank_r12(
            fit_ns, pack, records=bank,
            parameter_pack_identity=pack["digest"])
        routings[role] = build_routing_r12(role, v2, shadow=True)
        bundles[role] = v2
        records[role] = bank
        (out_dir / f"shadow_fit_manifest_{role}.json").write_text(
            json.dumps([e.canonical() for e in v2.entries],
                       ensure_ascii=False, indent=1), encoding="utf-8")
    summary["bundle_hashes"] = {k: v.bundle_hash
                                for k, v in bundles.items()}

    # ---- 2) 共享 orchestration(shadow profiles;正式顺序)----
    stage = orchestrate_stage(
        out_dir, pack, routings, records)
    summary["orchestration_stage_completed"] = True
    summary["orchestration_gate_pass"] = stage.get("pass")
    summary["stage_pass_field_note"] = (
        "工程 rehearsal:gate 数值不作正式判定;identity 一致性由 "
        "compare_full_scale_shadow_runs 判定")

    # ---- 3) final-like 核心(全规模;shadow namespace;临时 exposure)----
    final_dir = out_dir / "shadow_final"
    exposure_dir = out_dir / "shadow_exposure_tmp"
    final_result = execute_final_core_r12(
        final_dir, _shadow_final_plan_stub(pack), pack,
        profile_name="shadow_final",
        final_namespace="shadow_calibration_main_r12",
        fit_namespace="shadow_fit_main_r12",
        c13_pairs_per_rung=10,
        c2_blocks=SHADOW_C2_BLOCKS,
        semantic_block_count=160,
        independent_pairs_per_rung=20,
        exposure_dir=exposure_dir,
        rehearsal=False, shadow=True,
        independent_namespace="shadow_c2_independent_main_r12",
        semantic_namespace_override="shadow_semantic_final_r12",
        semantic_out_dir=out_dir,
        supervised_namespace_override="shadow_supervised_main_r12",
        supervised_model_seeds_override=SHADOW_MODEL_SEEDS,
        supervised_training_config=dict(SHADOW_TRAINING_CONFIG),
        conditioning_fit_namespace="shadow_fit_main_r12")
    summary["final_like_executed"] = True
    summary["final_like_verdict"] = final_result.get("verdict")

    summary["completed_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    (out_dir / f"shadow_rehearsal_{run_tag}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return summary


def orchestrate_stage(out_dir: Path, pack: dict[str, Any],
                      routings: dict[str, Any],
                      records: dict[str, list]) -> dict[str, Any]:
    """shadow 的 calibration stage(共享正式 orchestrator)。"""
    from rl_curriculum.curriculum261_r12_orchestrator import (
        shadow_holdout_profile_r12,
        shadow_main_profile_r12,
    )

    return orchestrate_stage_inner(
        out_dir, pack, routings, records,
        shadow_main_profile_r12(), shadow_holdout_profile_r12())


def orchestrate_stage_inner(out_dir: Path, pack: dict[str, Any],
                            routings: dict[str, Any],
                            records: dict[str, list],
                            profile_main, profile_holdout,
                            ) -> dict[str, Any]:
    from rl_curriculum.curriculum261_r12_orchestrator import (
        orchestrate_calibration_stage_r12,
    )

    return orchestrate_calibration_stage_r12(
        out_dir, pack,
        n_blocks=SHADOW_C2_BLOCKS,
        recall_floor_value=float(pack["recall_floor"]),
        routing_main=routings["main"],
        routing_holdout=routings["holdout"],
        records_main=records["main"], records_holdout=records["holdout"],
        profile_main=profile_main, profile_holdout=profile_holdout,
        override_fn=_shadow_override_fn,
        design_digest=None, write_artifacts=True)


# ------------------------------------------------ 双跑一致性比较(§C.7)
def _strip_non_identity(obj: Any) -> Any:
    """递归剥离声明为非身份的字段(其余字段全部参与一致性比较)。"""
    if isinstance(obj, dict):
        return {
            k: _strip_non_identity(v)
            for k, v in obj.items()
            if not (k in SHADOW_NON_IDENTITY_KEYS
                    or any(k.endswith(sfx)
                           for sfx in SHADOW_NON_IDENTITY_KEY_SUFFIXES))}
    if isinstance(obj, list):
        return [_strip_non_identity(v) for v in obj]
    return obj


def _artifact_identity_digest(path: Path) -> str:
    """单个 JSON artifact 的身份摘要(剥离非身份字段后规范化)。"""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return stable_digest(_strip_non_identity(payload), "r12art-")


def compare_full_scale_shadow_runs(dir_a: Path,
                                   dir_b: Path) -> dict[str, Any]:
    """两次独立 cold-process shadow 的一致性判定(工作包 C §7)。

    比较:invocation ledger digests(逐 attempt envelope digest 的
    序列)、全部 JSON artifact 的规范化身份 digest(episode hashes
    与 gate 输入均包含于 artifacts)、final-like 执行完成状态。
    除声明非身份字段外必须全部一致。
    """
    dir_a, dir_b = Path(dir_a), Path(dir_b)

    def _ledgers(d: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in sorted(d.rglob("generation_invocation_ledger.jsonl")):
            rows = read_envelope_ledger(p)
            out[str(p.relative_to(d))] = ledger_rows_digest(rows)
        return out

    def _artifacts(d: Path) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in sorted(d.rglob("*.json")):
            rel = str(p.relative_to(d))
            if _is_non_identity_path(rel):
                continue
            try:
                out[rel] = _artifact_identity_digest(p)
            except (json.JSONDecodeError, OSError):
                out[rel] = "unreadable"
        return out

    la, lb = _ledgers(dir_a), _ledgers(dir_b)
    aa, ab = _artifacts(dir_a), _artifacts(dir_b)
    ledger_keys_ok = sorted(la) == sorted(lb)
    ledger_diffs = sorted(k for k in la if k in lb and la[k] != lb[k])
    artifact_only_a = sorted(set(aa) - set(ab))
    artifact_only_b = sorted(set(ab) - set(aa))
    artifact_diffs = sorted(
        k for k in aa if k in ab and aa[k] != ab[k])
    return {
        "format": "cur261-r12-full-scale-shadow-comparison-v1",
        "iteration": "r12",
        "dir_a": str(dir_a), "dir_b": str(dir_b),
        "non_identity_declaration": {
            "key_suffixes": list(SHADOW_NON_IDENTITY_KEY_SUFFIXES),
            "keys": list(SHADOW_NON_IDENTITY_KEYS),
            "path_suffixes": list(SHADOW_NON_IDENTITY_PATH_SUFFIXES),
            "path_note": (
                "每次运行自己的摘要文件(shadow_rehearsal_{tag}.json;"
                "文件名含 run_tag,内容为运行日志)不参与身份比较"),},
        "ledger_files": {"a": len(la), "b": len(lb)},
        "ledger_identity_digests_identical": bool(
            ledger_keys_ok and not ledger_diffs),
        "ledger_digest_diffs": ledger_diffs[:20],
        "n_artifacts": {"a": len(aa), "b": len(ab)},
        "artifact_only_in_a": artifact_only_a[:20],
        "artifact_only_in_b": artifact_only_b[:20],
        "artifact_identity_digest_diffs": artifact_diffs[:20],
        "gate_inputs_covered": (
            "artifact 身份 digest 覆盖 supervised/curriculum/semantic/"
            "marginal/routing 全部 gate 输入字段(剥离非身份字段后;"
            "invocation/episode 身份由 ledger digest 覆盖)"),
        "pass": bool(
            ledger_keys_ok and not ledger_diffs
            and not artifact_only_a and not artifact_only_b
            and not artifact_diffs),
    }


__all__ = [
    "run_full_scale_shadow_r12", "compare_full_scale_shadow_runs",
    "SHADOW_C2_BLOCKS", "SHADOW_MODEL_SEEDS", "SHADOW_TRAINING_CONFIG",
]
