"""阶段 2.6.1 工作包 I:Final Qualification 运行器(120 pairs,一次性)。

前置:qualification plan 已锁定(本模块只消费锁定 plan,绝不修改)。
输出全部 artifacts:结构性/pair 完整性/因果/复现/新 seed/基线矩阵/
参考与 oracle/难度排序/尝试统计/最终判定。

纪律:final qualification 一经执行,其结果即为本阶段最终结果;失败
如实报告 FAIL,不做事后调参美化(修复由下一轮任务处理)。
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_api import CURRICULUM261_FAMILIES
from rl_curriculum.curriculum261_pairs import (
    attempt_statistics,
    generate_pair,
)
from rl_curriculum.curriculum261_plan import load_locked_plan, plan_digest
from rl_curriculum.curriculum261_production_obs import (
    production_observation_identity,
)
from rl_curriculum.curriculum261_qualification import (
    check_fresh_seed_validity,
    check_latent_isolation,
    check_observation_causality,
    check_production_feature_equivalence,
    check_reference_causality,
    check_reproducibility,
    rung_report,
)


def _frozen_contract_integrity() -> dict[str, Any]:
    """Route C 六项冻结合同未修改 + 代码树哈希。"""
    import hashlib

    from rl_platform import versions as v
    expected = {
        "env_core": "RouteCEnvCore-v1.0.0",
        "observation_spec": "ObservationSpec-v1",
        "action_spec": "BinaryLongFlatAction-v1",
        "reward_spec": "NetLogEquityReward-v1",
        "execution": "MarketOpenCausalExecution-v1",
        "terminal_liquidation": "TerminalLiquidation-v1",
    }
    actual = {
        "env_core": v.ENV_CORE_VERSION,
        "observation_spec": v.OBSERVATION_SPEC_VERSION,
        "action_spec": v.ACTION_SPEC_VERSION,
        "reward_spec": v.REWARD_SPEC_VERSION,
        "execution": v.EXECUTION_CONTRACT_VERSION,
        "terminal_liquidation": v.TERMINAL_LIQUIDATION_VERSION,
    }
    import rl_platform

    root = Path(rl_platform.__file__).parent
    files = {}
    for f in sorted(root.rglob("*.py")):
        files[f.name] = hashlib.sha256(f.read_bytes()).hexdigest()
    tree = hashlib.sha256(json.dumps(files, sort_keys=True).encode()
                          ).hexdigest()
    return {
        "expected": expected, "actual": actual,
        "unchanged": expected == actual,
        "rl_platform_tree_hash": "rp-" + tree,
        "pass": expected == actual,
    }


def _upstream_integrity(vendor_dir: Path) -> dict[str, Any]:
    """Freqtrade vendor SHA 未漂移且 clean。"""
    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=str(vendor_dir),
        capture_output=True, text=True, timeout=30).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"], cwd=str(vendor_dir),
        capture_output=True, text=True, timeout=30).stdout.strip()
    return {
        "vendor_path": str(vendor_dir),
        "sha": sha,
        "clean": status == "",
        "status_porcelain": status[:500],
    }


def run_final_qualification(plan_dir: Path, out_dir: Path,
                            vendor_dir: Path) -> dict[str, Any]:
    """执行一次性 final qualification(120 pairs)并写出全部 artifacts。"""
    plan, digest = load_locked_plan(plan_dir)
    started = datetime.now(timezone.utc).isoformat(timespec="seconds")

    # 0) 冻结合同 + vendor 完整性 + production observation identity +
    #    plan code_identity 复核(repair R1:防止旧 plan 目录配新代码
    #    静默混跑)
    frozen = _frozen_contract_integrity()
    upstream = _upstream_integrity(vendor_dir)
    upstream_ok = (upstream["sha"] == plan["vendor_pin"]
                   and upstream["clean"])
    prod_ident = production_observation_identity()
    prod_ok = (prod_ident["schema_hash"]
               == plan["production_observation_identity"]["schema_hash"]
               and prod_ident["strategy_file_sha256"]
               == plan["production_observation_identity"][
                   "strategy_file_sha256"]
               and prod_ident["feature_engineering_standard_sha256"]
               == plan["production_observation_identity"][
                   "feature_engineering_standard_sha256"])
    from rl_curriculum.curriculum261_plan import _code_identity
    current_ids = _code_identity()
    code_ok = all(
        plan["code_identity"].get(k) == v for k, v in current_ids.items()) \
        and set(plan["code_identity"]) == set(current_ids)

    # 1) 120 pairs(qualification namespace,锁定参数)
    thresholds = {f: plan["families"][f]["reference_thresholds"]
                  for f in CURRICULUM261_FAMILIES}
    rung_params = {f: plan["families"][f]["rung_params"]
                   for f in CURRICULUM261_FAMILIES}
    n_pairs = plan["pair_plan"]["pairs_per_rung"]
    family_reports: dict[str, Any] = {}
    pair_records_summary: dict[str, Any] = {}
    all_records_by_family: dict[str, list] = {}
    for family in CURRICULUM261_FAMILIES:
        records = []
        for rung in ("D0", "D1", "D2", "D3"):
            for idx in range(n_pairs):
                records.append(generate_pair(
                    family, rung, idx, namespace="qualification"))
        all_records_by_family[family] = records
        family_reports[family] = rung_report(
            records, family, rung_params[family], thresholds)
        family_reports[family]["attempt_stats"] = attempt_statistics(records)
        family_reports[family]["pair_integrity_pass_ratio"] = float(
            sum(1 for r in records if r.integrity_ok) / len(records))
        family_reports[family]["integrity_failures"] = [
            r.canonical() for r in records if not r.integrity_ok]
        pair_records_summary[family] = {
            "n_pairs": len(records),
            "first_pass_rate": family_reports[family][
                "attempt_stats"]["first_pass_rate"],
            "attempt_histogram": family_reports[family][
                "attempt_stats"]["attempts_histogram"],
            "rejection_reasons": family_reports[family][
                "attempt_stats"]["rejection_reasons"],
            "integrity_pass_ratio": family_reports[family][
                "pair_integrity_pass_ratio"],
        }

    # 2) 因果矩阵 / 复现 / 新 seed / latent isolation
    #    repair R1:旧 htf resample 检查替换为 production observation
    #    identity 检查(episode 特征与真实 RouteCStrategy 路径逐位对拍)
    causality: dict[str, Any] = {"observation_causality": [],
                                 "production_feature_equivalence": [],
                                 "reference_causality": []}
    for family in CURRICULUM261_FAMILIES:
        causality["observation_causality"].append(
            check_observation_causality(family, "D2", 0))
        causality["production_feature_equivalence"].append(
            check_production_feature_equivalence(family, "D2", 0))
        causality["reference_causality"].append(
            check_reference_causality(
                family, rung_params[family]["D2"], thresholds[family]))
    repro = [check_reproducibility(f, r, 0, "qualification")
             for f in CURRICULUM261_FAMILIES for r in ("D1", "D3")]
    latent = check_latent_isolation(
        [r for recs in all_records_by_family.values() for r in recs])
    fresh = check_fresh_seed_validity(10)

    causality_pass = (
        all(c["pass"] for c in causality["observation_causality"])
        and all(c["pass"]
                for c in causality["production_feature_equivalence"])
        and all(c["pass"] for c in causality["reference_causality"]))
    repro_pass = all(r["pass"] for r in repro)

    # 3) 判定(全部依据锁定阈值)
    th = plan["verdict_thresholds"]
    checks = {
        "frozen_contracts_unchanged": frozen["pass"],
        "vendor_pin_unchanged_and_clean": bool(upstream_ok),
        "production_observation_identity": bool(prod_ok),
        "plan_code_identity_matches_tree": bool(code_ok),
        "pair_integrity_all": all(
            family_reports[f]["pair_integrity_pass_ratio"]
            >= th["pair_integrity_pass_ratio"]
            for f in CURRICULUM261_FAMILIES),
        "causality_all": bool(causality_pass),
        "reproducibility_all": bool(repro_pass),
        "latent_isolation": bool(latent["pass"]),
        "fresh_seed_validity": bool(
            fresh["n_valid"] / fresh["n_checks"]
            >= th["fresh_seed_valid_ratio_min"]),
        "difficulty_ordering_all": all(
            family_reports[f]["ordering_ok"]
            for f in CURRICULUM261_FAMILIES),
        "d3_positive_all": all(
            family_reports[f]["d3_metric_positive"]
            for f in CURRICULUM261_FAMILIES),
        "reference_beats_required_all": all(
            family_reports[f]["reference_beats_required_all_rungs"]
            for f in CURRICULUM261_FAMILIES),
        "oracle_positive_all": all(
            family_reports[f]["oracle_positive_all_rungs"]
            for f in CURRICULUM261_FAMILIES),
    }
    overall_pass = all(checks.values())
    result = {
        "format": "cur261-qualification-result-v2",
        "stage": "stage2_6_1",
        "plan_digest": digest,
        "started_utc": started,
        "finished_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "seed_namespace": "qualification",
        "n_pairs_total": sum(
            pair_records_summary[f]["n_pairs"]
            for f in CURRICULUM261_FAMILIES),
        "frozen_contract_integrity": frozen,
        "upstream_integrity": upstream,
        "production_observation_identity": prod_ident,
        "checks": checks,
        "families": family_reports,
        "causality_matrix": causality,
        "reproducibility": repro,
        "latent_isolation": latent,
        "fresh_seed": fresh,
        "pair_attempt_summary": pair_records_summary,
        "verdict": "PASS" if overall_pass else "FAIL",
    }

    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "qualification_result.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    raw = {
        fam: [r.canonical() for r in recs]
        for fam, recs in all_records_by_family.items()}
    (out_dir / "qualification_raw.json").write_text(
        json.dumps(raw, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    # 拆分 artifacts(等价证据)
    (out_dir / "frozen_contract_integrity.json").write_text(
        json.dumps(frozen, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "production_observation_identity.json").write_text(
        json.dumps(prod_ident, indent=2, ensure_ascii=False),
        encoding="utf-8")
    (out_dir / "upstream_integrity.json").write_text(
        json.dumps(upstream, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "pair_integrity_summary.json").write_text(
        json.dumps(pair_records_summary, indent=2, ensure_ascii=False,
                   default=float), encoding="utf-8")
    (out_dir / "causality_matrix.json").write_text(
        json.dumps(causality, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "latent_isolation_matrix.json").write_text(
        json.dumps(latent, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "generator_reproducibility.json").write_text(
        json.dumps(repro, indent=2, ensure_ascii=False), encoding="utf-8")
    (out_dir / "oracle_reference_matrix.json").write_text(
        json.dumps({f: {
            "by_rung": {r: family_reports[f]["by_rung"][r]["policy_means"]
                        for r in ("D0", "D1", "D2", "D3")},
        } for f in CURRICULUM261_FAMILIES}, indent=2, ensure_ascii=False,
            default=float), encoding="utf-8")
    (out_dir / "degenerate_baseline_matrix.json").write_text(
        json.dumps({f: {
            r: {k: v for k, v in
                family_reports[f]["by_rung"][r]["policy_means"].items()
                if k != "oracle"}
            for r in ("D0", "D1", "D2", "D3")}
            for f in CURRICULUM261_FAMILIES},
            indent=2, ensure_ascii=False, default=float), encoding="utf-8")
    (out_dir / "difficulty_ordering.json").write_text(
        json.dumps({f: {
            "ladder": family_reports[f]["difficulty_metric_ladder"],
            "ordering_ok": family_reports[f]["ordering_ok"],
            "d3_positive": family_reports[f]["d3_metric_positive"],
        } for f in CURRICULUM261_FAMILIES}, indent=2, ensure_ascii=False,
            default=float), encoding="utf-8")
    (out_dir / "generation_attempt_summary.json").write_text(
        json.dumps({f: family_reports[f]["attempt_stats"]
                    for f in CURRICULUM261_FAMILIES},
                   indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    (out_dir / "curriculum_family_summary.json").write_text(
        json.dumps({f: {
            "family_version": plan["families"][f]["family_version"],
            "reference_thresholds": thresholds[f],
            "rung_params": rung_params[f],
            "verdict": {
                "ordering_ok": family_reports[f]["ordering_ok"],
                "d3_positive": family_reports[f]["d3_metric_positive"],
                "reference_beats_required":
                    family_reports[f]["reference_beats_required_all_rungs"],
                "oracle_positive": family_reports[f][
                    "oracle_positive_all_rungs"],
            },
        } for f in CURRICULUM261_FAMILIES}, indent=2, ensure_ascii=False),
        encoding="utf-8")
    return result
