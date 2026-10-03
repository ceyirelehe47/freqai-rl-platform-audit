# -*- coding: utf-8 -*-
"""FLP v1 修复轮 R4 测试夹具:构建**完整合法**的坐标终态目录。

与 aggregate 测试的 _build_coordinate 同构:真实 cue_contract_
audit_digest / coordinate_audit_plan_digest / derive261_block_seed
/ publish_coordinate_seal(原子发布)。昂贵统计核心不做——
生成的是结构化负结果夹具(audit_pass=False),供后继门消费。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from rl_curriculum.curriculum261_qprod_coordinate import (  # noqa: E402
    QPROD_BLOCK_SEED_LOG_NAME, coordinate_audit_plan_digest,
    publish_coordinate_seal,
)
from rl_curriculum.curriculum261_r17_cue_contract import (  # noqa: E402
    ABSOLUTE_MINIMUM_RECALL, AUDIT_RNG_SEED,
    C2_CUE_SEMANTIC_CONTRACT_VERSION, NONINFERIORITY_DELTA,
    cue_contract_audit_digest,
)
from rl_curriculum.curriculum261_r6_tape import (  # noqa: E402
    derive261_block_seed,
)


def build_valid_coordinate(
        art_dir: Path, subdir: str, *, coordinate_id: str,
        plan_digest: str, model_ns: str, validation_ns: str,
        blocks: int = 2) -> Path:
    """构建完整合法坐标目录(结构化负结果;audit_pass=False)。"""
    coord_dir = Path(art_dir) / subdir
    coord_dir.mkdir(parents=True, exist_ok=True)
    # 事件表(结构即可;后继门不复算统计)
    events = [{"corpus": c, "block_index": i,
               "cue_bar_index": 0, "event": "cue"}
              for c in ("model", "validation")
              for i in range(blocks)]
    trace = coord_dir / "cue_event_trace.jsonl"
    trace.write_text("\n".join(json.dumps(e, sort_keys=True)
                               for e in events) + "\n",
                     encoding="utf-8")
    report = {
        "format": "cur261-r17-cue-contract-audit-v1",
        "contract_version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
        "audit_namespaces": {"model": model_ns,
                             "validation": validation_ns},
        "audit_blocks_per_corpus": blocks,
        "audit_rng_seed": AUDIT_RNG_SEED,
        "audit_n_events_mc": 4096,
        "frozen_detector": {
            "cue_thr": 0.0105, "wick_dir_thr": 0.0,
            "wick_width_thr": 0.0, "feature": "%-ret-1",
            "vol_bps": 26.0, "pulse_bps": 30.0, "episode_bars": 288},
        "mirror_bound_v2": {"formula": "fixture",
                            "r7_bug": "fixture",
                            "authority": "fixture"},
        "margin_log": 0.5,
        "p_contract": 0.94,
        "analytic_weights_source": "synthetic fixture",
        "analytic_terms": [],
        "monte_carlo": {"n_events": 4096, "p_hat": 0.9405,
                        "se": 0.0036, "abs_diff_vs_analytic": 0.0001,
                        "tolerance": 0.001, "pass": True},
        "noninferiority": {
            "delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "recall_floor": max(ABSOLUTE_MINIMUM_RECALL,
                                0.94 - NONINFERIORITY_DELTA)},
        "direct_generator": {
            "model": {
                "n_unique_positive_cues": 2 * blocks,
                "empirical_recall": 0.94,
                "block_cluster": {"point": 0.94, "se": 0.01,
                                  "lcb95": 0.91, "ci95": [0.9, 0.99]},
                "analytic_conditional": 0.94,
                "tail": {"n_events": 8, "empirical_recall": 0.94,
                         "analytic_conditional": 0.939},
                "max_replay_abs_error": 0.0},
            "validation": {
                "n_unique_positive_cues": 2 * blocks,
                "empirical_recall": 0.94,
                "block_cluster": {"point": 0.94, "se": 0.01,
                                  "lcb95": 0.91, "ci95": [0.9, 0.99]},
                "analytic_conditional": 0.94,
                "tail": {"n_events": 8, "empirical_recall": 0.94,
                         "analytic_conditional": 0.939},
                "max_replay_abs_error": 0.0}},
    }
    report["audit_digest"] = cue_contract_audit_digest(report)
    (coord_dir / "cue_contract_audit.json").write_text(
        json.dumps(report), encoding="utf-8")
    log = []
    for i in range(blocks):
        log.append({"kind": "once", "namespace": model_ns,
                    "block_seed": int(derive261_block_seed(
                        model_ns, i, 0))})
        log.append({"kind": "attempts", "namespace": validation_ns,
                    "block_index": i,
                    "block_seed": int(derive261_block_seed(
                        validation_ns, i, 0)),
                    "selected_attempt": 0, "attempts_made": 1})
    (coord_dir / QPROD_BLOCK_SEED_LOG_NAME).write_text(
        "\n".join(json.dumps(e, sort_keys=True) for e in log) + "\n",
        encoding="utf-8")
    qcap_payload = {
        "format": "cur261-qprod-coordinate-audit-plan-v1",
        "coordinate_id": coordinate_id,
        "research_plan_digest": plan_digest,
        "profile": "engineering",
        "budgets": {"blocks_per_corpus": blocks, "mc_events": 4096,
                    "engineering_only": True},
        "namespaces": {"model": model_ns,
                       "validation": validation_ns},
        "block_range": {"start_index": 0, "count": blocks},
        "generation_mode": {"model": "once",
                            "validation": "attempts"},
        "code_identity": {},
    }
    qcap_digest = coordinate_audit_plan_digest(qcap_payload)
    qcap_payload["coordinate_audit_plan_digest"] = qcap_digest
    (coord_dir / "qprod_coordinate_audit_plan.json").write_text(
        json.dumps(qcap_payload), encoding="utf-8")
    (coord_dir / "qprod_coordinate_audit_plan_digest.txt").write_text(
        qcap_digest + "\n", encoding="utf-8")
    members = {}
    for name in ("cue_contract_audit.json", "cue_event_trace.jsonl",
                 QPROD_BLOCK_SEED_LOG_NAME):
        members[name] = hashlib.sha256(
            (coord_dir / name).read_bytes()).hexdigest()
    seal = {
        "format": "cur261-qprod-coordinate-seal-v1",
        "coordinate_id": coordinate_id,
        "research_plan_digest": plan_digest,
        "coordinate_audit_plan_digest": qcap_digest,
        "audit_digest": report["audit_digest"],
        "members_sha256": members,
        "summary": {"recall_validation": 0.94, "se_validation": 0.01,
                    "p_contract_local": 0.94, "audit_pass": False},
        "generation": {"episode_leaf_calls": 8 * blocks},
        "sealed_utc": "2026-10-03T00:00:00+00:00",
    }
    publish_coordinate_seal(coord_dir, seal)
    return coord_dir
