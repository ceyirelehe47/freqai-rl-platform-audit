# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11:final preflight(§25)。

A. pre-lock static:imports/vendor/Route C identity/code identity/
   V2 serialize+outer env+PPO smoke(ppo_smoke_r11)/matched generator
   + block attempt/unique-event cue evaluator/cluster bootstrap/
   marker 原子性/并发锁/final runner 静态路径——全部只用非 final
   namespace。
B. post-lock sealed:plan/pack/cue 合同/证据文件/code identity/
   vendor/runtime/输出权限;零 final seed(不调用 derive261_seed;
   由测试 monkeypatch 锁定);attestation digest 绑定。
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from rl_curriculum.curriculum261_r6_preflight import (
    _canonical,
    _route_c_identity,
    _runtime_identity,
    _sha256_file,
    _vendor_state,
    vendor_dir_default,
)


def _imports_ok_r11() -> dict[str, Any]:
    modules = [
        "rl_curriculum.curriculum261_r11_namespaces",
        "rl_curriculum.curriculum261_r11_dependencies",
        "rl_curriculum.curriculum261_r11_preplan",
        "rl_curriculum.curriculum261_r11_noise_replay",
        "rl_curriculum.curriculum261_r11_cue_contract",
        "rl_curriculum.curriculum261_r11_cue_eval",
        "rl_curriculum.curriculum261_r11_param_pack",
        "rl_curriculum.curriculum261_r11_design",
        "rl_curriculum.curriculum261_r11_calibration",
        "rl_curriculum.curriculum261_r11_plan",
        "rl_curriculum.curriculum261_r11_final",
        "rl_curriculum.curriculum261_r11_smoke",
        "rl_curriculum.curriculum261_r6_tape",
        "rl_curriculum.curriculum261_r6_pairs",
        "rl_curriculum.curriculum261_r4_preprocessing",
        "rl_curriculum.curriculum261_qualification",
        "rl_platform.env",
        "rl_platform.versions",
        "stable_baselines3",
        "gymnasium",
    ]
    failed: dict[str, str] = {}
    import importlib

    for mod in modules:
        try:
            importlib.import_module(mod)
        except Exception as exc:  # noqa: BLE001
            failed[mod] = str(exc)[:200]
    return {"modules": modules, "failed": failed,
            "pass": not failed}


def _dependency_resolution_ok_r11() -> dict[str, Any]:
    """§6.3:全部声明依赖在 import 时解析 + symbol origin 断言。"""
    from rl_curriculum.curriculum261_r11_dependencies import (
        resolve_dependency_identity_r11,
    )

    return resolve_dependency_identity_r11()


def _code_identity_digest_r11() -> dict[str, Any]:
    from rl_curriculum.curriculum261_r11_plan import _code_identity_r11

    ident = _code_identity_r11()
    missing = [k for k, v in ident.items() if v == "MISSING"]
    return {
        "identity": ident,
        "missing": missing,
        "digest": "r11ci-" + hashlib.sha256(
            _canonical(ident).encode("utf-8")).hexdigest(),
        "pass": not missing,
    }


def _matched_generator_probe_r11() -> dict[str, Any]:
    """matched generator + unique-event evaluator + cluster bootstrap
    小规模验证(ppo_smoke_r11 下 2 个 block;不触碰 design/cal/final)。"""
    try:
        from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
        from rl_curriculum.curriculum261_pairs import family_specs
        from rl_curriculum.curriculum261_c2 import FAMILY_C2
        from rl_curriculum.curriculum261_r6_tape import (
            C2_BLOCK_MAX_ATTEMPTS,
            check_block_attempt_log,
            generate_matched_block_with_attempts,
        )
        from rl_curriculum.curriculum261_r11_cue_eval import (
            candidate_cue_semantics,
            canonical_cue_observations,
            cluster_bootstrap_rate,
        )

        blocks = []
        for idx in range(2):
            blocks.append(generate_matched_block_with_attempts(
                dict(C2_RUNG_PARAMS), namespace="ppo_smoke_r11",
                block_index=idx))
        logs_ok = all(not check_block_attempt_log(b.attempt_log)
                      for b in blocks)
        cross_ok = all(b.cross_rung_integrity.get("pass") for b in blocks)
        integrity_ok = all(
            rec.integrity_ok for b in blocks
            for rec in b.pair_records.values())
        from rl_curriculum.curriculum261_r11_noise_replay import (
            trace_matched_blocks,
        )

        replay = trace_matched_blocks(blocks, dict(C2_RUNG_PARAMS))
        replay_ok = bool(replay["all_replay_ok"]
                         and replay["all_bounds_ok"])
        obs = canonical_cue_observations(blocks)
        dedup_ok = bool(
            not obs["violations"]
            and obs["per_block"][0]["n_positive"] > 0)
        # cluster bootstrap sanity:全命中 -> LCB=1;全不命中 -> LCB=0
        hit_all = cluster_bootstrap_rate(
            [{"n": 10, "hit": 10}, {"n": 10, "hit": 10}], side="lower")
        miss_all = cluster_bootstrap_rate(
            [{"n": 10, "hit": 0}, {"n": 10, "hit": 0}], side="lower")
        bootstrap_ok = bool(
            hit_all["bound"] == 1.0 and miss_all["bound"] == 0.0)
        cand = candidate_cue_semantics(blocks, "preflight_sentinel")
        # R11 §7:真实(非 monkeypatch)candidate evaluator 集成探针
        # ——plan 锁前覆盖 R8 ImportError 的完整函数体路径。
        from rl_curriculum.curriculum261_r11_design import (
            _evaluate_candidate_matched_r11,
        )

        thresholds = dict(family_specs()[FAMILY_C2].reference_defaults)
        eval_result = _evaluate_candidate_matched_r11(
            "preflight_sentinel", dict(C2_RUNG_PARAMS),
            "ppo_smoke_r11", thresholds, blocks=blocks, n_blocks=2)
        evaluator_ok = bool(
            eval_result.get("n_blocks") == 2
            and set(eval_result.get("per_formal_block_count", {}))
            == {"10", "15", "20"}
            and bool(eval_result.get("density_gates"))
            and bool(eval_result.get("semantics"))
            and all(np.isfinite(v) for v in eval_result.get(
                "difficulty_means", {}).values()))
        return {
            "real_candidate_evaluator_runs": evaluator_ok,
            "n_blocks": len(blocks),
            "max_attempts_expected": C2_BLOCK_MAX_ATTEMPTS,
            "attempt_logs_valid": bool(logs_ok),
            "cross_rung_matching_pass": bool(cross_ok),
            "pair_integrity_pass": bool(integrity_ok),
            "unique_event_dedup_valid": dedup_ok,
            "canonical_consistency_violations": obs["violations"],
            "cluster_bootstrap_sanity": bootstrap_ok,
            "candidate_cue_evaluator_runs": bool("pass" in cand),
            "noise_replay_bitwise_ok": replay_ok,
            "max_replay_abs_error": replay["max_replay_abs_error"],
            "pass": bool(logs_ok and cross_ok and integrity_ok
                         and dedup_ok and bootstrap_ok and replay_ok
                         and evaluator_ok),
        }
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def run_prelock_static_preflight_r11(out_dir: Path,
                                    vendor_pin: str) -> dict[str, Any]:
    """§25.1:plan lock 前静态 preflight(只用非 final namespace)。"""
    out_dir = Path(out_dir)
    checks: dict[str, Any] = {}
    checks["imports"] = _imports_ok_r11()
    checks["dependency_resolution"] = _dependency_resolution_ok_r11()

    vendor = _vendor_state(vendor_dir_default())
    checks["vendor"] = {
        **vendor,
        "pin_matches": bool(vendor.get("sha") == vendor_pin),
    }
    checks["vendor_ok"] = bool(
        vendor["exists"] and vendor["clean"]
        and vendor.get("sha") == vendor_pin)

    checks["route_c_identity"] = _route_c_identity()
    checks["code_identity"] = _code_identity_digest_r11()

    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".preflight_write_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        checks["output_write_permission"] = True
    except OSError:
        checks["output_write_permission"] = False

    try:
        from rl_curriculum.curriculum261_r11_smoke import run_ppo_smoke_r11

        smoke = run_ppo_smoke_r11()
        checks["ppo_smoke_static"] = smoke
        checks["v2_serialize_reload_and_outer_env"] = bool(
            smoke["pass"]
            and smoke["checks"]["observation_space_unbounded"])
    except Exception as exc:  # noqa: BLE001
        checks["ppo_smoke_static"] = {"pass": False,
                                      "error": str(exc)[:300]}
        checks["v2_serialize_reload_and_outer_env"] = False

    checks["matched_generator_and_cue_evaluator"] = (
        _matched_generator_probe_r11())

    marker_ok = False
    lock_ok = False
    with tempfile.TemporaryDirectory() as td:
        import os

        old = os.environ.get("CURRICULUM261_R11_LOCK_DIR")
        os.environ["CURRICULUM261_R11_LOCK_DIR"] = td
        try:
            from rl_curriculum.curriculum261_r11_namespaces import (
                QualificationR11FileLock,
                write_qualification_r11_exposure,
            )

            write_qualification_r11_exposure("r11dp-preflight-probe",
                                            "running")
            try:
                write_qualification_r11_exposure("r11dp-preflight-probe",
                                                "running")
                double_create_rejected = False
            except RuntimeError:
                double_create_rejected = True
            marker_ok = bool(double_create_rejected)
            try:
                with QualificationR11FileLock(blocking=False):
                    with QualificationR11FileLock(blocking=False):
                        pass
                concurrent_lock_rejected = False
            except RuntimeError:
                concurrent_lock_rejected = True
            lock_ok = bool(concurrent_lock_rejected)
        finally:
            if old is None:
                os.environ.pop("CURRICULUM261_R11_LOCK_DIR", None)
            else:
                os.environ["CURRICULUM261_R11_LOCK_DIR"] = old
    checks["marker_atomic_exclusive"] = marker_ok
    checks["concurrent_final_lock_rejected"] = lock_ok

    result = {
        "format": "cur261-r11-prelock-static-preflight-v1",
        "iteration": "r11",
        "executed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "namespaces_touched": ["ppo_smoke_r11"],
        "final_namespaces_touched": [],
        "vendor_pin_expected": vendor_pin,
        "checks": checks,
        "pass": bool(
            checks["imports"]["pass"] and checks["vendor_ok"]
            and checks["code_identity"]["pass"]
            and checks["output_write_permission"]
            and checks["v2_serialize_reload_and_outer_env"]
            and checks["matched_generator_and_cue_evaluator"]["pass"]
            and marker_ok and lock_ok),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prelock_static_preflight.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    return result


def sealed_preflight_digest(att: dict[str, Any]) -> str:
    payload = {k: v for k, v in att.items() if k != "digest"}
    return "r11fa-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def run_postlock_sealed_preflight_r11(out_dir: Path,
                                     vendor_pin: str,
                                     ) -> dict[str, Any]:
    """§25.2:plan lock 后 sealed preflight(零 final seed / 零 marker)。"""
    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_plan_path,
        qualification_r11_digest_path,
        r11_parameter_pack_path,
    )
    from rl_curriculum.curriculum261_r11_plan import (
        _code_identity_r11,
        load_locked_plan_r11,
    )
    from rl_curriculum.curriculum261_r11_param_pack import (
        load_selected_pack,
        verify_r4_inheritance_r11,
    )

    checks: dict[str, Any] = {}
    plan, plan_digest = load_locked_plan_r11()
    checks["plan_digest_recompute"] = True
    checks["plan_iteration_r11"] = bool(plan.get("iteration") == "r11")
    checks["robustness_gate_pass_recorded"] = bool(
        (plan.get("robustness_gate") or {}).get("pass") is True)

    pack = load_selected_pack(Path(out_dir))
    checks["parameter_pack_bound"] = bool(
        pack["digest"] == plan["parameter_pack"]["digest"])
    checks["r4_inheritance_verified"] = verify_r4_inheritance_r11(pack)
    checks["selected_block_count_bound"] = bool(
        int(pack["selected_block_count"])
        == int(plan["final_sample_counts"]["c2_matched_blocks"]))
    checks["matched_contract_bound"] = bool(
        pack["matched_ladder_contract_identity"]
        == plan["matched_ladder"]["contract_identity"])
    cue_plan = plan.get("cue_semantic_contract", {})
    checks["cue_semantic_contract_bound"] = bool(
        pack.get("cue_semantic_contract_digest")
        == cue_plan.get("contract_digest")
        and pack.get("cue_semantic_rule_identity")
        == cue_plan.get("rule_identity")
        and pack.get("cue_contract_audit_digest")
        == cue_plan.get("audit_digest")
        and float(pack.get("p_contract", -1))
        == float(cue_plan.get("p_contract", -2))
        and float(pack.get("recall_floor", -1))
        == float(cue_plan.get("recall_floor", -2)))

    out = Path(out_dir)
    for name in ("preprocessing_robustness_gate.json",
                 "curriculum_robustness_gate.json",
                 "supervised_learnability.json",
                 "prelock_static_preflight.json"):
        path = out / name
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            checks[f"evidence_{name}"] = bool(payload.get("pass") is True)
        else:
            checks[f"evidence_{name}"] = False

    ident = _code_identity_r11()
    missing = [k for k, v in ident.items() if v == "MISSING"]
    checks["code_identity_matches_plan"] = bool(
        not missing and plan["code_identity"] == ident)
    code_digest = "r11ci-" + hashlib.sha256(
        _canonical(ident).encode("utf-8")).hexdigest()

    vendor = _vendor_state(vendor_dir_default())
    checks["vendor_ok"] = bool(
        vendor["exists"] and vendor["clean"]
        and vendor.get("sha") == vendor_pin)

    try:
        probe = out / ".sealed_preflight_write_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        checks["output_write_permission"] = True
    except OSError:
        checks["output_write_permission"] = False

    checks["final_runner_dependencies"] = _imports_ok_r11()["pass"]
    checks["plan_path_resolves"] = bool(
        qualification_r11_plan_path().is_file()
        and qualification_r11_digest_path().is_file()
        and r11_parameter_pack_path().is_file())

    att_pass = bool(all(
        v is True for k, v in checks.items()
        if isinstance(v, bool)))

    attestation = {
        "format": "cur261-r11-sealed-final-preflight-v1",
        "iteration": "r11",
        "pass": att_pass,
        "plan_digest": plan_digest,
        "parameter_pack_digest": pack["digest"],
        "selected_block_count": int(pack["selected_block_count"]),
        "matched_ladder_contract_identity":
            pack["matched_ladder_contract_identity"],
        "cue_semantic_contract_digest":
            pack["cue_semantic_contract_digest"],
        "cue_semantic_rule_identity":
            pack["cue_semantic_rule_identity"],
        "cue_contract_audit_digest": pack["cue_contract_audit_digest"],
        "p_contract": float(pack["p_contract"]),
        "recall_floor": float(pack["recall_floor"]),
        "code_identity_digest": code_digest,
        "vendor_sha": vendor.get("sha", ""),
        "vendor_clean": bool(vendor.get("clean")),
        "vendor_pin_expected": vendor_pin,
        "runtime_identity": _runtime_identity(),
        "final_seed_derivations_performed": 0,
        "final_namespaces_touched": [],
        "exposure_marker_written": False,
        "checks": checks,
        "created_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "contract": "本 attestation 证明 final 前静态条件全部成立且 "
                    "sealed preflight 未派生任何 final seed;final "
                    "runner 启动时必须验证本文件 digest 与 plan 绑定",
    }
    attestation["digest"] = sealed_preflight_digest(attestation)
    (out / "sealed_final_preflight.json").write_text(
        json.dumps(attestation, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    (out / "sealed_final_preflight_digest.txt").write_text(
        attestation["digest"], encoding="utf-8")
    return attestation


def write_rehearsal_sealed_preflight_r11(
        out_dir: Path, *, plan_digest: str) -> dict[str, Any]:
    """§12 rehearsal 的 sealed preflight(临时目录;零正式 seed)。

    与正式 run_postlock_sealed_preflight_r11 同构的零 final-seed
    attestation(rehearsal 标志 + preplan namespace 声明)。
    """
    from rl_curriculum.curriculum261_r11_namespaces import (
        R11_SEALED_PREFLIGHT_DIGEST_FILENAME,
        R11_SEALED_PREFLIGHT_FILENAME,
    )

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    att = {
        "format": "cur261-r11-sealed-final-preflight-v1",
        "iteration": "r11",
        "rehearsal": True,
        "pass": True,
        "plan_digest": plan_digest,
        "final_seed_derivations_performed": 0,
        "final_namespaces_touched": [],
        "preplan_namespaces_only": True,
        "exposure_marker_written": False,
    }
    att["digest"] = sealed_preflight_digest(att)
    (out_dir / R11_SEALED_PREFLIGHT_FILENAME).write_text(
        json.dumps(att, indent=1, ensure_ascii=False), encoding="utf-8")
    (out_dir / R11_SEALED_PREFLIGHT_DIGEST_FILENAME).write_text(
        att["digest"], encoding="utf-8")
    return att


def verify_sealed_attestation(out_dir: Path) -> dict[str, Any]:
    out_dir = Path(out_dir)
    path = out_dir / "sealed_final_preflight.json"
    if not path.is_file():
        return {"pass": False, "reason": "sealed preflight 不存在"}
    att = json.loads(path.read_text(encoding="utf-8"))
    try:
        digest_ok = sealed_preflight_digest(att) == att.get("digest")
    except (KeyError, TypeError):
        digest_ok = False
    digest_file = out_dir / "sealed_final_preflight_digest.txt"
    file_ok = (digest_file.is_file()
               and digest_file.read_text(encoding="utf-8").strip()
               == att.get("digest"))
    zero_seed = bool(
        att.get("final_seed_derivations_performed") == 0
        and not att.get("final_namespaces_touched")
        and att.get("exposure_marker_written") is False)
    return {
        "pass": bool(digest_ok and file_ok and zero_seed
                     and att.get("pass") is True),
        "digest_ok": digest_ok,
        "digest_file_ok": file_ok,
        "zero_final_seed": zero_seed,
        "attestation": att,
    }
