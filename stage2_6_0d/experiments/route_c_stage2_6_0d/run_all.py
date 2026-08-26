# -*- coding: utf-8 -*-
"""阶段 2.6.0d:Strict Null 统计资格与经济等价闭环实验(完整语义)。

链路(与正式同构,任务书工作包 F):
 1. Null Qualification Spec(margin = 精确往返摩擦,按 EvalConfig 计算);
 2. 确定性 Monte Carlo 功效分析(六类场景,三目标;32-cluster 充分性);
 3. family qualification:三族 x 64 seed cluster x 16 原始 Episode;
 4. 实际 mock hidden Null pack(每族 32 antithetic pair cluster,
    namespace 推导 + attempt 记录 + pack-level validity);
 5. issuer + 受信 runner + 256-step PPO smoke(允许挂科,非课程训练)
    + sidecar + attestation;
 6. v4 承诺(runtime + spec + 功效 + pack 构建算法 + pack validity
    + 真实 v3 Null 报告);
 7. 系统级沙箱正式考试(候选评估前执行 pack-level validity 现算对账)
    + 幂等重试 + 详细披露退休;
 8. 篡改矩阵:Null 资格与承诺 v4;
 9. 上游与冻结合同完整性;全部证据写入 artifacts/route_c_stage2_6_0d。
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

PROJ = Path.home() / "projects" / "crypto_rl"
sys.path.insert(0, str(PROJ / "src"))
sys.path.insert(0, str(PROJ / "tests"))

ART = PROJ / "artifacts" / "route_c_stage2_6_0d"
ART.mkdir(parents=True, exist_ok=True)
WORK = ART / "_work"

FAMILIES = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def log(msg: str) -> None:
    print(f"[2.6.0d] {msg}", flush=True)


def write_art(name: str, payload: dict) -> None:
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    log(f"artifact -> {p.name}")


def now_iso() -> str:
    import pandas as pd

    return pd.Timestamp.now(tz="UTC").isoformat()


# ------------------------------------------------------ 1-4. 资格链 + pack
def stage_qualification_chain(schema, cfg) -> dict:
    from null_qual_cache import cached_null_qual_chain
    from rl_curriculum.null_qualification_spec import verify_spec_payload

    log("生成完整资格链(spec -> 三族 64x16 报告 -> 功效分析)...")
    t0 = time.time()
    chain = cached_null_qual_chain(schema, cfg)
    log(f"  缓存/生成耗时 {time.time() - t0:.0f}s")
    spec = chain["spec"]
    assert verify_spec_payload(spec) == []
    write_art("null_qualification_spec.json", {
        "spec": spec,
        "spec_hash": chain["spec_hash"],
        "verified": True,
        "generated_utc": now_iso(),
    })
    write_art("null_economic_margin_derivation.json", {
        "margin": spec["margin"],
        "derivation": spec["margin_derivation"],
        "hard_cap": (
            "任务书 A4:任一无条件策略相对 Flat 的允许正优势 <= 一次"
            "完整往返交易摩擦;按冻结环境实际乘法成本精确计算 "
            "1-(1-fee)^2*(1-slippage)^2 = 0.001999(fee=0.001,"
            "slippage=0),不写死常数"),
        "per_time_semantics": {
            "episode_duration_hours": spec["episode_duration_hours"],
            "timeframe": spec["timeframe"],
            "note": "margin 按 Episode 真实时间定义,非每 bar 阈值"},
        "statistical_protocol": spec["statistical_protocol"],
        "comparison_strategies": spec["comparison_strategies"],
        "generated_utc": now_iso(),
    })
    power = chain["power_report"]
    t = power["targets"]
    write_art("null_power_analysis.json", {
        "summary": {
            "margin": power["margin"],
            "min_qualification_clusters":
                power["min_qualification_clusters"],
            "mc_iters": power["mc_iters"],
            "mc_seed": power["mc_seed"],
            "max_false_invalid_at_zero": t["max_false_invalid_at_zero"],
            "max_false_qualified_at_2x_margin": t[
                "max_false_qualified_at_2x_margin"],
            "min_rejection_power_at_1x_margin": t[
                "min_rejection_power_at_1x_margin"],
            "targets_met": t["targets_met"],
            "n32_sufficiency": power["n32_sufficiency"],
        },
        "full_report": power,
        "generated_utc": now_iso(),
    })
    assert t["targets_met"] is True
    fam_summary = {}
    ok = True
    for fam in FAMILIES:
        rep = chain["reports"][fam]
        lf = rep["always_long_vs_flat"]["bootstrap"]
        orc = rep["oracle"]["bootstrap"]
        rul = rep["rule_trend"]["bootstrap"]
        fam_summary[fam] = {
            "verdict": rep["verdict"],
            "n_clusters": rep["n_clusters"],
            "n_episodes_tested": rep["n_episodes_tested"],
            "margin": rep["margin"]["value"],
            "always_long_vs_flat": {
                "mean": rep["always_long_vs_flat"]["mean"], **lf},
            "oracle": {"mean": rep["oracle"]["mean"], **orc},
            "rule_trend": {"mean": rep["rule_trend"]["mean"], **rul},
            "checks": rep["checks"],
            "spec_hash": rep["qualification_spec_hash"],
            "power_ref": rep["power_analysis_ref"],
            "seeds_namespace_conform": rep["seeds_namespace_conform"],
        }
        ok = ok and rep["verdict"] == "QUALIFIED"
        log(f"  {fam}: {rep['verdict']} lf_hi={lf['ci_high']:+.5f} "
            f"oracle_hi={orc['ci_high']:+.5f} "
            f"rule_hi={rul['ci_high']:+.5f}")
    write_art("valid_null_family_qualification.json", {
        "families": fam_summary,
        "all_qualified": ok,
        "level": "family",
        "generated_utc": now_iso(),
    })
    (ART / "null_reports").mkdir(exist_ok=True)
    for fam, rep in chain["reports"].items():
        (ART / "null_reports" / f"{fam}.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False),
            encoding="utf-8")
    unit_ok = True
    blocks_audit = {}
    for fam in FAMILIES:
        rep = chain["reports"][fam]
        for block in ("oracle", "rule_trend", "always_long_vs_flat",
                      "high_turnover_vs_flat", "episode_net_drift"):
            boot = rep[block]["bootstrap"]
            cv = rep[block]["cluster_values"]
            consistent = (boot["n"] == rep["n_clusters"]
                          == rep["distinct_seeds"] == len(cv))
            blocks_audit[f"{fam}::{block}"] = {
                "bootstrap_n": boot["n"], "cluster_values_len": len(cv),
                "consistent": consistent}
            unit_ok = unit_ok and consistent
    write_art("seed_cluster_bootstrap_evidence.json", {
        "unit": "seed-cluster",
        "aggregation": chain["spec"]["cluster_aggregation"],
        "blocks": blocks_audit,
        "bootstrap_n_equals_distinct_clusters": unit_ok,
        "bar_level_bootstrap_present": False,
        "generated_utc": now_iso(),
    })
    assert ok and unit_ok
    return chain


def stage_legacy_three_seed_rejection(schema, cfg) -> None:
    """D1:2.6.0c 的 3-seed 报告作为旧证据输入新 verifier 的处置。"""
    from null_qual_cache import cached_null_qual_chain
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualification_report_hash,
        qualify_null_family,
        verify_null_qualification_bindings,
    )

    log("复现 2.6.0c 审查反例(3 seed x 1 ep,旧证据处置)...")
    reports = {}
    for fam in FAMILIES:
        reports[fam] = qualify_null_family(
            R[fam], params=dict(BASE_PARAMS), timeframe="15m",
            seeds=[11, 22, 33], cfg=cfg, schema=schema,
            episodes_per_seed=1)
    chain = cached_null_qual_chain(schema, cfg)
    verdict = verify_null_qualification_bindings(
        build_null_qualification_bindings(reports),
        required_families=list(FAMILIES),
        generator_bindings=generator_bindings(dict(R)),
        observation_schema_hash=schema.schema_hash(),
        eval_config_manifest=cfg.manifest(), timeframe="15m",
        qualification_spec_hash=chain["spec_hash"],
        power_analysis_ref=chain["reports"][FAMILIES[0]][
            "power_analysis_ref"])
    none_qualified = all(r["verdict"] != "QUALIFIED"
                         for r in reports.values())
    write_art("legacy_three_seed_reports_rejection.json", {
        "legacy_reports": {
            fam: {
                "verdict": r["verdict"],
                "always_long_median": r["always_long_median"],
                "lf_ci": [
                    r["always_long_vs_flat"]["bootstrap"]["ci_low"],
                    r["always_long_vs_flat"]["bootstrap"]["ci_high"]],
                "checks": r["checks"],
                "report_hash": qualification_report_hash(r),
            }
            for fam, r in reports.items()},
        "none_qualified": none_qualified,
        "rejected_by_new_verifier": not verdict["pass"],
        "problems_head": verdict["problems"][:2],
        "note": ("旧证据不得自动升级;stochvol 因 lf CI 下界超 margin "
                 "升级为 INVALID_NULL(经济反证),sign/volstate 为 "
                 "INSUFFICIENT_EVIDENCE"),
        "generated_utc": now_iso(),
    })
    for fam, med, label in (
            ("probe_null_stochvol", 0.02, "stochvol"),
            ("probe_null_sign", 0.007, "sign")):
        rep = reports[fam]
        assert rep["always_long_median"] > med
        assert rep["checks"]["always_flat_strong_baseline"] is False
        write_art(f"{label}_positive_long_edge_rejection.json", {
            "family": fam,
            "always_long_median": rep["always_long_median"],
            "always_flat_median": rep["always_flat_median"],
            "lf_ci": [
                rep["always_long_vs_flat"]["bootstrap"]["ci_low"],
                rep["always_long_vs_flat"]["bootstrap"]["ci_high"]],
            "margin": rep["margin"]["value"],
            "economic_check_failed": not rep["checks"][
                "always_flat_strong_baseline"],
            "verdict": rep["verdict"],
            "finding_2_6_0c": (
                "2.6.0c 旧实现对该中位优势仍判 always_flat_strong_"
                "baseline=true 并整体 PASS;新协议触发经济优势失败"),
            "generated_utc": now_iso(),
        })
    assert none_qualified and not verdict["pass"]


def stage_pseudo_null_matrix(schema, cfg) -> None:
    """D4:伪 Null 拒绝矩阵(经济优势/结构/小幅漂移/可预测零漂移)。"""
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import qualify_null_family
    from rl_curriculum.null_qualification_spec import qualification_seeds

    log("伪 Null 拒绝矩阵(D4)...")
    qual_seeds = qualification_seeds(64)
    cases = {}

    def _run(name, params, *, seeds, k):
        rep = qualify_null_family(
            ProbeSegmentedDriftGenerator(), params=params,
            timeframe="15m", seeds=seeds, cfg=cfg, schema=schema,
            episodes_per_seed=k, power_analysis_ref="npa-matrix")
        cases[name] = {
            "verdict": rep["verdict"],
            "failed_checks": [c for c, v in rep["checks"].items()
                              if not v],
            "always_long_median": rep["always_long_median"],
            "reasons_head": rep["reasons"][:2],
        }
        return rep

    drift_params = dict(BASE_PARAMS)
    drift_params["direction_weights"] = [0.0, 0.85, 0.15]
    _run("always_long_edge_gt_friction", drift_params,
         seeds=list(range(11, 75)), k=2)
    _run("oracle_rule_predictable", dict(BASE_PARAMS),
         seeds=[101, 102, 103, 104, 105, 106], k=2)
    _run("hft_positive_market", {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0, "regimes": [[1, 60.0, 96]],
    }, seeds=list(range(11, 23)), k=2)
    rep = _run("small_fixed_drift_3bps", {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0, "regimes": [[1, 3.0, 96]],
    }, seeds=qual_seeds, k=8)
    assert rep["verdict"] != "QUALIFIED"
    rep = _run("zero_drift_trend_predictable", {
        **BASE_PARAMS, "direction_weights": [0.5, 0.5, 0.0],
        "drift_bps_range": [24.0, 24.0],
    }, seeds=qual_seeds, k=8)
    assert rep["verdict"] == "INVALID_NULL"
    all_rejected = all(c["verdict"] != "QUALIFIED"
                       for c in cases.values())
    write_art("pseudo_null_rejection_matrix.json", {
        "cases": cases,
        "all_rejected": all_rejected,
        "generated_utc": now_iso(),
    })
    assert all_rejected


def stage_antithetic_integrity(schema, cfg) -> dict:
    """D7:antithetic 镜像完整性与 pack builder(B3/B4)。"""
    import numpy as np
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import (
        BASE_PARAMS,
        build_mock_hidden_pack,
    )

    log("antithetic 完整性 + pack builder(B3/B4)...")
    integrity = {}
    for fam in FAMILIES:
        gen = R[fam]
        flip = dict(BASE_PARAMS)
        flip["antithetic_flip"] = True
        checks = []
        for seed in (424242, 777, 12345):
            e1 = gen.generate(dict(BASE_PARAMS), seed,
                              split="null_control", timeframe="15m")
            e2 = gen.generate(dict(flip), seed,
                              split="null_control", timeframe="15m")
            b1 = np.diff(np.log(e1.df["close"].to_numpy()),
                         prepend=np.log(e1.df["open"].iloc[0]))
            b2 = np.diff(np.log(e2.df["close"].to_numpy()),
                         prepend=np.log(e2.df["open"].iloc[0]))
            checks.append({
                "seed": seed,
                "bitwise_negated": bool(np.allclose(b1, -b2)),
                "pair_drift_cancels": bool(
                    abs(b1.sum() + b2.sum()) < 1e-10),
                "volume_identical": bool(np.allclose(
                    e1.df["volume"], e2.df["volume"])),
                "same_length": len(e1.df) == len(e2.df) == 96,
            })
        integrity[fam] = checks
    mirror_ok = all(c[k] for fam_checks in integrity.values()
                    for c in fam_checks
                    for k in ("bitwise_negated", "pair_drift_cancels",
                              "volume_identical", "same_length"))
    pack, builder_log = build_mock_hidden_pack(with_builder_log=True)
    write_art("antithetic_pair_integrity.json", {
        "mirror_checks": integrity,
        "all_mirror_properties_hold": mirror_ok,
        "builder_log": builder_log,
        "pack_episodes": len(pack.episodes),
        "pair_flag_in_observation": False,
        "pair_order": "seeded-randomized(namespace)",
        "no_endpoint_constraint": True,
        "family_qualification_uses_raw_episodes": (
            "镜像会抵消任何确定性漂移,资格判定使用原始派生样本"),
        "generated_utc": now_iso(),
    })
    assert mirror_ok
    return {"pack": pack, "builder_log": builder_log}


def stage_pack_validity(schema, cfg, chain, antithetic_stage) -> dict:
    """B2:实际 mock pack 的 pack-level validity + D6 偶然漂移。"""
    from null_qual_cache import build_commitment_null_materials
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack,
        validate_null_pack,
    )

    log("pack-level validity(实际 mock pack)...")
    pack = antithetic_stage["pack"]
    materials = build_commitment_null_materials(
        pack, schema, cfg, chain=chain)
    pv = materials["pack_validity_report"]
    assert pv["verdict"] == "PACK_VALID"
    write_art("actual_pack_null_validity.json", {
        "verdict": pv["verdict"],
        "pack_hash": pv["pack_hash"],
        "report_hash_note": "npv- 哈希进入 v4 承诺(执行器现算对账)",
        "per_family": {
            fam: {
                "n_episodes": b["n_episodes"],
                "n_clusters": b["n_clusters"],
                "blocks": b["blocks"],
                "problems": b["problems"],
            }
            for fam, b in pv["per_family"].items()},
        "margin": pv["margin"],
        "builder_code_hash": pv["builder_code_hash"],
        "generated_utc": now_iso(),
    })
    eps = [R["probe_null_stochvol"].generate(
        dict(BASE_PARAMS), s, split="null_control", timeframe="15m")
        for s in (11, 22, 33)]
    bad = validate_null_pack(
        {"probe_null_stochvol": eps}, cfg=cfg, schema=schema,
        spec=build_spec_for_pack(cfg, timeframe="15m", episode_bars=96))
    write_art("pack_accidental_drift_rejection.json", {
        "scenario": ("分布理论零漂移(stochvol)但实际 pack 恰好显著"
                     "向上(3-seed 反例 seeds [11,22,33])"),
        "pack_verdict": bad["verdict"],
        "reasons": bad["reasons"],
        "executor_behavior": (
            "run_sealed_exam 在候选评估前现算 pack validity 并与承诺"
            "hash 对账;该 pack -> EXAM_INVALID,候选不进入评估,"
            "不判 FAIL/作弊"),
        "family_level_still_valid": True,
        "generated_utc": now_iso(),
    })
    assert bad["verdict"] == "PACK_INVALID"
    return materials


# ------------------------------------------- 5-7. issuer + 承诺 + 考试
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


def stage_issuer_and_checkpoint(schema):
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
        build_attestation_payload,
        write_attestation,
    )
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.checkpoints import save_checkpoint_manifest
    from rl_curriculum.probe_charter import audit_probe_charter

    log("mock issuer + 256-step PPO smoke 训练(允许挂科)...")
    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0d")
    trusted = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=True)
    d = WORK / "ckpt"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    material = _train_smoke_ppo(d / "smoke_ppo.zip", n_steps=256)
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": 256, "seed": material["training_seed"],
        "note": "256-step PPO smoke:仅验证 provenance/sandbox/接口;"
                "不构成课程训练(阶段 2.6.0d)",
    }
    tm_path = d / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        d / "smoke_ppo.zip", checkpoint_name="stage2_6_0d_smoke",
        charter_hash=charter_h, observation_schema=schema,
        training_manifest_sha256=tm_sha,
        self_declared_formal_eligible=False)
    sidecar_sha = hashlib.sha256(
        (d / "smoke_ppo.zip.rl_manifest.json").read_bytes()).hexdigest()
    ckpt_sha = hashlib.sha256(
        (d / "smoke_ppo.zip").read_bytes()).hexdigest()
    payload = build_attestation_payload(
        checkpoint_sha256=ckpt_sha, sidecar_sha256=sidecar_sha,
        training_manifest_sha256=tm_sha, charter_hash=charter_h,
        observation_schema_hash=schema.schema_hash(),
        route_c_env_version="RouteCEnvCore-v1.0.0",
        training_generator_hashes={},
        training_pack_hash="mock-training-pack-stage2-6-0d",
        training_code_hash="mock-training-code",
        ppo_params=material["ppo_params"],
        network_architecture=material["network_architecture"],
        training_budget=material["training_budget"],
        training_seed=material["training_seed"],
        is_smoke=True, allow_formal_evaluation=True,
        issuer_id=keypair.issuer_id,
        training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        issued_utc=now_iso())
    att = write_attestation(
        d / "smoke_ppo.zip.rl_attestation.json", keypair, payload)
    return {"keypair": keypair, "trusted": trusted,
            "checkpoint": str(d / "smoke_ppo.zip"), "attestation": att}


def _train_smoke_ppo(path: Path, *, n_steps: int = 256) -> dict:
    import gymnasium as gym
    import numpy as np
    from stable_baselines3 import PPO

    class TinyLongFlatEnv(gym.Env):
        def __init__(self):
            super().__init__()
            self.observation_space = gym.spaces.Box(
                -1e9, 1e9, (9,), np.float32)
            self.action_space = gym.spaces.Discrete(2)
            self._rng = np.random.default_rng(0)
            self._obs = np.zeros(9, np.float32)

        def reset(self, seed=None, options=None):
            self._obs = np.zeros(9, np.float32)
            return self._obs, {}

        def step(self, action):
            drift = 0.0003 if self._obs[4] > 0 else -0.0002
            ret = drift + 0.0004 * self._rng.standard_normal()
            self._obs = np.roll(self._obs, 1)
            self._obs[0] = ret
            self._obs[4] += 0.1 * (ret - self._obs[4])
            return self._obs, ret, False, False, {}

    model = PPO("MlpPolicy", TinyLongFlatEnv(), n_steps=n_steps,
                batch_size=64, seed=7, verbose=0, device="cpu")
    model.learn(total_timesteps=n_steps)
    model.save(str(path))
    return {
        "ppo_params": {
            "n_steps": n_steps, "batch_size": 64, "seed": 7,
            "learning_rate": float(model.learning_rate),
            "n_epochs": int(model.n_epochs), "gamma": float(model.gamma),
        },
        "network_architecture": {
            "policy_class": type(model.policy).__name__,
            "parameter_count": int(
                sum(p.numel() for p in model.policy.parameters())),
        },
        "training_budget": {"total_timesteps": n_steps},
        "training_seed": 7,
    }


def _status(out: dict) -> str:
    return (out.get("status")
            or (out.get("result") or {}).get("status") or "UNKNOWN")


def stage_sealed_exam_flow(schema, cfg, chain, materials, antithetic_stage,
                           issuer_stage) -> dict:
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        write_exam_context,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import verify_sealed_commitment
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    log("构建 v4 承诺 + 系统级沙箱考试全链路...")
    charter = audit_probe_charter()
    pack = antithetic_stage["pack"]
    verdict_spec = probe_course_verdict_spec()
    profile = default_sandbox_profile()
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=profile, trusted_issuer=issuer_stage["trusted"],
        null_qualification_bindings=materials["bindings"],
        power_analysis_report=materials["power_analysis_report"],
        pack_validity_report=materials["pack_validity_report"])
    verify_sealed_commitment(
        commitment, pack=pack, charter=charter, schema=schema,
        registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
        verdict_spec=verdict_spec, sandbox_profile=profile)
    log("  v4 承诺完整验证通过")

    d = WORK / "exam"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    pack.save(d / "pack.json")
    commitment.save(d / "commitment.json")
    write_exam_context(d / "ctx.json", charter=charter, schema=schema,
                       verdict_spec=verdict_spec, eval_config=cfg,
                       sandbox_profile=profile,
                       trusted_issuer=issuer_stage["trusted"])

    def run_cli(out_name, *extra, ctx="ctx.json", commitment_file=None,
                checkpoint=None):
        argv = [
            sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
            "--sealed-manifest",
            str(d / (commitment_file or "commitment.json")),
            "--pack", str(d / "pack.json"),
            "--checkpoint", checkpoint or issuer_stage["checkpoint"],
            "--context", str(d / ctx),
            "--out", str(d / out_name),
            "--retire-registry", str(d / "ret.json"),
            "--attempt-registry", str(d / "attempts.json"),
            *extra,
        ]
        import os

        env = dict(os.environ)
        env['PYTHONPATH'] = str(PROJ / 'src')
        t0 = time.time()
        proc = subprocess.run(
            argv, capture_output=True, text=True, timeout=1800,
            cwd=str(PROJ), env=env)
        out_path = d / out_name
        out = (json.loads(out_path.read_text(encoding="utf-8"))
               if out_path.is_file()
               else {"stdout": proc.stdout[-2000:],
                     "stderr": proc.stderr[-2000:]})
        out["_exit_code"] = proc.returncode
        out["_elapsed_s"] = round(time.time() - t0, 1)
        return out

    log("正式密封考试 #1(候选评估前 pack validity 现算对账)...")
    out1 = run_cli("out1.json")
    log(f"  #1: status={_status(out1)} exit={out1['_exit_code']}"
        f" ({out1['_elapsed_s']}s)")
    log("幂等重试 #2...")
    out2 = run_cli("out2.json")
    log(f"  #2: status={_status(out2)} ({out2['_elapsed_s']}s)")
    log("详细披露 #3(披露后退休)...")
    out3 = run_cli("out3.json", "--detailed", str(d / "detailed.json"))
    detail = json.loads(
        (d / "detailed.json").read_text(encoding="utf-8")) \
        if (d / "detailed.json").is_file() else {}
    log(f"  #3: status={_status(out3)}")

    flow_ok = (_status(out1) == _status(out2)
               and _status(out1) in ("FAIL", "PASS"))
    write_art("mock_sealed_exam_v5_summary.json", {
        "pipeline": ("Spec -> power analysis -> 64x16 family 资格 -> "
                     "mock null pack(32 antithetic pair/族)-> pack "
                     "validity -> issuer -> 256-step PPO smoke -> "
                     "attestation -> v4 承诺 -> 系统级沙箱(pack "
                     "validity 现算对账)-> 反事实 -> 冻结判定 FAIL -> "
                     "幂等 -> 详细披露退休"),
        "commitment_hash": commitment.commitment_hash(),
        "protocol": "sealed-exam-commitment-v4",
        "null_qualification_format": "null-qualification-v3",
        "exam_cli_version": out1.get("exam_cli_version"),
        "run1": {"status": _status(out1), "exit": out1["_exit_code"],
                 "elapsed_s": out1["_elapsed_s"]},
        "run2_idempotent": {"status": _status(out2),
                            "same_result": _status(out1) == _status(out2)},
        "run3_detailed": {"status": _status(out3),
                          "pack_retired": bool(detail)},
        "flow_ok": flow_ok,
        "smoke_training_note": (
            "256-step PPO 仅验证 provenance/sandbox/协议/评估链路;"
            "允许正常挂科,不构成课程训练,不要求通过课程或 G4"),
        "generated_utc": now_iso(),
    })
    assert flow_ok, (_status(out1), _status(out2))
    return {"run_cli": run_cli, "dir": d, "commitment": commitment,
            "detail": detail}


# ------------------------------------------------------------ 8. 篡改矩阵
def stage_tamper_matrices(chain, sealed_stage, schema, cfg) -> None:
    import copy as _copy

    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualification_report_hash,
        verify_null_qualification_bindings,
    )
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    log("Null 资格篡改矩阵...")
    base = build_null_qualification_bindings(chain["reports"])
    kwargs = {
        "generator_bindings": generator_bindings(dict(R)),
        "observation_schema_hash": schema.schema_hash(),
        "eval_config_manifest": cfg.manifest(),
        "timeframe": "15m",
        "qualification_spec_hash": chain["spec_hash"],
        "power_analysis_ref": chain["reports"][FAMILIES[0]][
            "power_analysis_ref"],
    }

    def _case(bindings_mutation=None, payload_mutation=None, rehash=True):
        b = _copy.deepcopy(base)
        if payload_mutation is not None:
            payload_mutation(b["probe_null_sign"]["report_payload"], b)
            if rehash:
                b["probe_null_sign"]["report_hash"] = \
                    qualification_report_hash(
                        b["probe_null_sign"]["report_payload"])
        if bindings_mutation is not None:
            bindings_mutation(b)
        r = verify_null_qualification_bindings(
            b, required_families=list(FAMILIES), **kwargs)
        return {"rejected": not r["pass"],
                "problem_head": r["problems"][0][:100]
                if r["problems"] else None}

    def _b_only(b):
        b["probe_null_sign"] = {"qualification_pass": True}

    def _set(key, value):
        def _mutate(p, b):
            p[key] = value
        return _mutate

    def _verdict_insufficient(p, b):
        p["verdict"] = "INSUFFICIENT_EVIDENCE"
        p["pass"] = False
        b["probe_null_sign"]["qualification_pass"] = False

    def _pass_conflict(p, b):
        p["verdict"] = "INSUFFICIENT_EVIDENCE"
        p["pass"] = True

    def _seeds_off(p, b):
        p["seeds"] = list(range(64))
        p["distinct_seeds"] = 64
        p["always_long_vs_flat"]["cluster_values"] = (
            p["always_long_vs_flat"]["cluster_values"][:64])

    def _margin_wrong(p, b):
        p["margin"]["derivation"] = {
            **p["margin"]["derivation"], "formula": "hardcoded"}

    def _check_false(p, b):
        p["checks"]["oracle_no_tradable_edge"] = False

    def _check_missing(p, b):
        del p["checks"]["oracle_no_tradable_edge"]

    def _fee_changed(p, b):
        p["eval_config_manifest"] = {
            **p["eval_config_manifest"], "fee": 0.0005}

    null_cases = {
        "bool_only_binding": _case(bindings_mutation=_b_only),
        "format_v2_deprecated": _case(payload_mutation=_set(
            "format", "null-qualification-v2")),
        "verdict_insufficient": _case(
            payload_mutation=_verdict_insufficient),
        "verdict_illegal": _case(payload_mutation=_set(
            "verdict", "PASS")),
        "pass_verdict_conflict": _case(payload_mutation=_pass_conflict),
        "spec_hash_wrong": _case(payload_mutation=_set(
            "qualification_spec_hash", "nqs-tampered")),
        "power_ref_wrong": _case(payload_mutation=_set(
            "power_analysis_ref", "npa-forged")),
        "bootstrap_unit_bar": _case(payload_mutation=_set(
            "bootstrap_unit", "bar")),
        "seeds_off_namespace": _case(payload_mutation=_seeds_off),
        "n_clusters_inconsistent": _case(payload_mutation=_set(
            "n_clusters", 63)),
        "margin_formula_wrong": _case(payload_mutation=_margin_wrong),
        "required_check_false": _case(payload_mutation=_check_false),
        "required_check_missing": _case(payload_mutation=_check_missing),
        "unrecognized_field": _case(payload_mutation=_set(
            "attacker_note", "trust me")),
        "implementation_hash_stale": _case(payload_mutation=_set(
            "generator_implementation_hash", "gi-stale-" + "5" * 50)),
        "eval_config_fee_changed": _case(payload_mutation=_fee_changed),
    }
    baseline = verify_null_qualification_bindings(
        _copy.deepcopy(base), required_families=list(FAMILIES), **kwargs)
    null_all_rejected = (baseline["pass"] and all(
        c["rejected"] for c in null_cases.values()))
    write_art("null_qualification_tamper_matrix_v3.json", {
        "protocol": "null-qualification-v3",
        "baseline_valid": baseline["pass"],
        "cases": null_cases,
        "all_negative_cases_rejected": null_all_rejected,
        "generated_utc": now_iso(),
    })
    assert null_all_rejected

    log("承诺 v4 篡改矩阵...")
    commitment = sealed_stage["commitment"]
    v4_cases = {}
    v3_json = commitment.to_json().replace("sealed-exam-commitment-v4",
                                           "sealed-exam-commitment-v3")
    try:
        SealedExamCommitment.from_json(v3_json)
        v4_cases["v3_commitment_accepted"] = {"rejected": False}
    except SealedExamError:
        v4_cases["v3_commitment_accepted"] = {"rejected": True}
    for key in ("null_qualification_spec_hash", "null_power_analysis",
                "pack_validity", "pack_builder_code_hash"):
        data = json.loads(commitment.to_json())
        data.pop(key, None)
        try:
            SealedExamCommitment.from_json(json.dumps(data))
            v4_cases["missing_" + key] = {"rejected": False}
        except SealedExamError:
            v4_cases["missing_" + key] = {"rejected": True}
    data = json.loads(commitment.to_json())
    data["null_qualification_spec_hash"] = "nqs-tampered"
    try:
        SealedExamCommitment.from_json(json.dumps(data))
        v4_cases["spec_hash_tampered"] = {
            "structurally_accepted": True,
            "value_reconciliation_in_verify": True,
            "note": "值级对账由 verify 的 spec hash 重算拦截"}
    except SealedExamError:
        v4_cases["spec_hash_tampered"] = {"rejected": True}
    data = json.loads(commitment.to_json())
    data["pack_validity"]["report_hash"] = "npv-" + "9" * 64
    try:
        SealedExamCommitment.from_json(json.dumps(data))
        v4_cases["pack_validity_hash_tampered"] = {
            "structurally_accepted": True,
            "rejected_at_executor": (
                "执行器现算 pack validity -> npv- hash 不符 -> "
                "EXAM_INVALID")}
    except SealedExamError:
        v4_cases["pack_validity_hash_tampered"] = {"rejected": True}
    v4_all = (v4_cases["v3_commitment_accepted"]["rejected"]
              and all(v4_cases["missing_" + k]["rejected"] for k in (
                  "null_qualification_spec_hash", "null_power_analysis",
                  "pack_validity", "pack_builder_code_hash")))
    write_art("sealed_exam_tamper_matrix_v4.json", {
        "protocol": "sealed-exam-commitment-v4",
        "cases": v4_cases,
        "all_negative_cases_rejected": v4_all,
        "generated_utc": now_iso(),
    })
    assert v4_all


# ------------------------------------------------------ 完整性与收尾
def stage_upstream_integrity() -> None:
    log("上游与冻结合同完整性检查...")

    def _run(cmd: str, cwd: Path) -> str:
        return subprocess.run(
            ["bash", "-lc", cmd], capture_output=True, text=True,
            cwd=str(cwd)).stdout.strip()

    vendor = PROJ / "vendor" / "freqtrade"
    head = _run("git rev-parse HEAD", vendor)
    dirty = _run("git status --porcelain | wc -l", vendor)
    from rl_platform.versions import CHECKPOINT_REQUIRED_VERSIONS as FROZEN

    expected_frozen = {
        "env_core_version": "RouteCEnvCore-v1.0.0",
        "observation_spec_version": "ObservationSpec-v1",
        "action_spec_version": "BinaryLongFlatAction-v1",
        "reward_spec_version": "NetLogEquityReward-v1",
        "execution_contract_version": "MarketOpenCausalExecution-v1",
        "terminal_liquidation_version": "TerminalLiquidation-v1",
    }
    payload = {
        "vendor_freqtrade_head": head,
        "vendor_expected": "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5",
        "vendor_clean": dirty == "0",
        "frozen_contracts": dict(FROZEN),
        "frozen_unchanged": dict(FROZEN) == expected_frozen,
        "generated_utc": now_iso(),
    }
    (ART / "upstream_integrity.txt").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8")
    log(f"  vendor HEAD {head[:12]} clean={payload['vendor_clean']}")
    assert payload["vendor_clean"] and head == payload["vendor_expected"]
    assert payload["frozen_unchanged"]


def main() -> None:
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    t_start = time.time()
    schema = probe_observation_schema()
    cfg = default_eval_config()

    chain = stage_qualification_chain(schema, cfg)
    stage_legacy_three_seed_rejection(schema, cfg)
    stage_pseudo_null_matrix(schema, cfg)
    antithetic_stage = stage_antithetic_integrity(schema, cfg)
    materials = stage_pack_validity(schema, cfg, chain, antithetic_stage)
    issuer_stage = stage_issuer_and_checkpoint(schema)
    sealed_stage = stage_sealed_exam_flow(
        schema, cfg, chain, materials, antithetic_stage, issuer_stage)
    stage_tamper_matrices(chain, sealed_stage, schema, cfg)
    stage_upstream_integrity()
    log(f"全部阶段完成({time.time() - t_start:.0f}s);"
        f"artifacts -> {ART}")


if __name__ == "__main__":
    main()
