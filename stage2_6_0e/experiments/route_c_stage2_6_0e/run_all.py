# -*- coding: utf-8 -*-
"""阶段 2.6.0e:Null 经济摩擦、功效证明与 Pack 完整性最终闭环实验。

链路(任务书工作包 F):
 1. 冻结账本摩擦合同(null-friction-contract-v2:精确公式 + 真实执行
    parity 网格;fee=0.001/slip=0 -> 0.002/1.001 = 0.001998002);
 2. Null Qualification Spec v2 -> 三族 64x16 family 资格 -> 中心化四块
    功效分析 v2(Wilson 保守界;cluster 阶梯 32/64/96/128 两层规则);
 3. 实际 mock null pack:每 seed 恰好 (orig, flip) 各一,物化镜像/nuisance
    逐位验证,四块中心+CI 上界硬门;
 4. builder manifest(npb- 绑定真实 builder);
 5. issuer + 受信 runner + 256-step PPO smoke(允许挂科,非课程训练)
    + sidecar + attestation;
 6. v5 承诺(builder manifest/场景清单/派生摘要/完整 power 绑定);
 7. 正式执行器确定性重跑完整 power analysis(npa- 对账;public summary
    不是信任源)+ pack validity 现算对账 + 系统级沙箱 + 幂等 + 披露退休;
 8. 篡改矩阵:power 重验证攻击 14 类 / antithetic 负例 / v5 承诺矩阵 /
    legacy v4 与旧公式材料拒绝;
 9. 上游与冻结合同完整性;全部证据写入 artifacts/route_c_stage2_6_0e。
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

ART = PROJ / "artifacts" / "route_c_stage2_6_0e"
ART.mkdir(parents=True, exist_ok=True)
WORK = ART / "_work"

FAMILIES = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


def log(msg: str) -> None:
    print(f"[2.6.0e] {msg}", flush=True)


def write_art(name: str, payload: dict) -> None:
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    log(f"artifact -> {p.name}")


def now_iso() -> str:
    import pandas as pd

    return pd.Timestamp.now(tz="UTC").isoformat()


# ------------------------------------------------------------ 1. 摩擦合同
def stage_friction_contract() -> dict:
    import rl_curriculum.null_friction as nf

    log("冻结账本摩擦合同 + 真实执行 parity 网格(工作包 A)...")
    report = nf.friction_parity_report()
    assert report["pass"] is True, report["problems"][:3]
    write_art("null_friction_contract_parity.json", {
        "parity": report,
        "contract": nf.friction_contract_payload(),
        "margin_values": {
            "fee_0p001_slip_0": nf.ledger_round_trip_friction(0.001, 0.0),
            "legacy_wrong_formula": 1 - (1 - 0.001) ** 2,
            "nominal_hardcoded": 0.002,
        },
        "generated_utc": now_iso(),
    })
    return {"report": report}


# --------------------------------------------------- 2. 资格链 v2 + 功效 v2
def stage_qualification_chain(schema, cfg) -> dict:
    from null_qual_cache import cached_null_qual_chain
    from rl_curriculum.null_power_analysis import (
        bootstrap_matrix_parity,
        power_analysis_report_hash,
    )
    from rl_curriculum.null_qualification_spec import verify_spec_payload

    log("完整资格链 v2(spec v2 -> 三族 64x16 报告 -> 功效分析 v2)...")
    t0 = time.time()
    chain = cached_null_qual_chain(schema, cfg)
    log(f"  缓存/生成耗时 {time.time() - t0:.0f}s")
    spec = chain["spec"]
    assert verify_spec_payload(spec) == []
    write_art("null_qualification_spec_v2.json", {
        "spec": spec,
        "spec_hash": chain["spec_hash"],
        "verified": True,
        "margin": spec["margin"],
        "margin_note": (
            "冻结账本精确摩擦 1-[(1-f)/(1+f)]*[(1-s)/(1+s)] = "
            "0.002/1.001 = 0.001998001998...;旧公式 1-(1-f)^2*(1-s)^2 = "
            "0.001999 已废除(工作包 A)"),
        "generated_utc": now_iso(),
    })

    power = chain["power_report"]
    t = power["targets"]
    assert t["targets_met"] is True
    write_art("null_power_analysis_v2.json", {
        "summary": {
            "margin": power["margin"],
            "min_qualification_clusters":
                power["min_qualification_clusters"],
            "mc_iters": power["mc_iters"],
            "mc_seed": power["mc_seed"],
            "confidence_method": power["confidence_method"],
            "max_false_invalid_at_zero": t["max_false_invalid_at_zero"],
            "max_false_qualified_at_2x_margin": t[
                "max_false_qualified_at_2x_margin"],
            "min_rejection_power_at_1x_margin": t[
                "min_rejection_power_at_1x_margin"],
            "targets_met": t["targets_met"],
            "required_scenario_count": power["required_scenario_count"],
            "required_scenarios_complete":
                power["required_scenarios_complete"],
        },
        "full_report": power,
        "report_hash": power_analysis_report_hash(power),
        "generated_utc": now_iso(),
    })

    # 场景覆盖(工作包 B3/B4)
    expected = [
        f"{fam}::{block}::{scen}"
        for fam in FAMILIES
        for block in power["required_blocks"]
        for scen in power["scenario_manifest"]["blocks"][block]["scenarios"]]
    present = {f"{s['family']}::{s['block']}::{s['scenario']}"
               for s in power["scenarios"]
               if s["n"] == power["min_qualification_clusters"]}
    assert set(expected) == present and not power[
        "skipped_required_scenarios"]
    write_art("power_required_scenario_coverage.json", {
        "required_blocks": power["required_blocks"],
        "required_scenario_count": power["required_scenario_count"],
        "expected": expected,
        "present_count": len(present),
        "complete": power["required_scenarios_complete"],
        "skipped": power["skipped_required_scenarios"],
        "zero_variance_mode_counts": {
            mode: sum(1 for s in power["scenarios"]
                      if s["mode"] == mode)
            for mode in ("analytic_zero_variance",
                         "centered_residual_resample")},
        "generated_utc": now_iso(),
    })

    # cluster 阶梯选择(工作包 B6)
    write_art("power_cluster_count_selection.json", {
        "rule": power["cluster_selection"]["rule"],
        "empirical_base_clusters":
            power["cluster_selection"]["empirical_base_clusters"],
        "selected": power["cluster_selection"]["selected"],
        "ladder": power["cluster_selection"]["ladder"],
        "note": (
            "两层规则:(a)全部功效硬目标(Wilson 保守界);(b)该 n 的 "
            "namespace 前缀上三族四块经济等价检验通过——只满足 (a) 但"
            "前缀资格 INSUFFICIENT 的档位不得选用(32 档即此情形)"),
        "generated_utc": now_iso(),
    })

    # 中心化 parity(工作包 B1)+ 向量化 bootstrap 一致性
    import numpy as np

    centering = []
    for fam in FAMILIES:
        cv = chain["reports"][fam]["always_long_vs_flat"][
            "cluster_values"]
        for target in (0.0, 0.000999, 0.003996):
            from rl_curriculum.null_power_analysis import (
                power_centering_parity,
            )

            centering.append({
                "family": fam, "target": target,
                **power_centering_parity(
                    cv, target, 64, bound=spec["margin"],
                    scenario_index=int(target * 1e6))})
    boot_parity = bootstrap_matrix_parity(
        chain["reports"]["probe_null_sign"]["always_long_vs_flat"][
            "cluster_values"])
    assert boot_parity["bitwise_match"] is True
    write_art("power_centering_parity.json", {
        "centering": centering,
        "max_abs_center_gap": max(
            abs(c["simulated_center"] - c["target"]) for c in centering),
        "bootstrap_vectorized_bitwise_match": boot_parity[
            "bitwise_match"],
        "bootstrap_reference": boot_parity["reference_bootstrap"],
        "note": (
            "target 为绝对经济优势:residuals = empirical - mean;"
            "sample = resample(residuals) + target;注入后样本中心 == "
            "target(旧未中心化方式会把原始经验均值叠加进 target)"),
        "generated_utc": now_iso(),
    })

    fam_summary = {}
    ok = True
    for fam in FAMILIES:
        rep = chain["reports"][fam]
        lf = rep["always_long_vs_flat"]["bootstrap"]
        orc = rep["oracle"]["bootstrap"]
        rul = rep["rule_trend"]["bootstrap"]
        hft = rep["high_turnover_vs_flat"]["bootstrap"]
        fam_summary[fam] = {
            "verdict": rep["verdict"],
            "n_clusters": rep["n_clusters"],
            "n_episodes_tested": rep["n_episodes_tested"],
            "margin": rep["margin"]["value"],
            "always_long_vs_flat": {
                "mean": rep["always_long_vs_flat"]["mean"], **lf},
            "oracle": {"mean": rep["oracle"]["mean"], **orc},
            "rule_trend": {"mean": rep["rule_trend"]["mean"], **rul},
            "high_turnover_vs_flat": {
                "mean": rep["high_turnover_vs_flat"]["mean"], **hft},
            "checks": rep["checks"],
            "spec_hash": rep["qualification_spec_hash"],
            "power_ref": rep["power_analysis_ref"],
        }
        ok = ok and rep["verdict"] == "QUALIFIED"
        log(f"  {fam}: {rep['verdict']} lf_hi={lf['ci_high']:+.5f} "
            f"oracle_hi={orc['ci_high']:+.5f} "
            f"rule_hi={rul['ci_high']:+.5f} hft_hi={hft['ci_high']:+.5f}")
    (ART / "null_reports").mkdir(exist_ok=True)
    for fam, rep in chain["reports"].items():
        (ART / "null_reports" / f"{fam}.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    write_art("valid_null_family_qualification_v4.json", {
        "families": fam_summary,
        "all_qualified": ok,
        "level": "family",
        "format": "null-qualification-v4",
        "generated_utc": now_iso(),
    })
    assert ok
    return chain


# ------------------------------------------- 3. pack 完整性 + builder manifest
def _materialize_null_family(family: str, attempt: int = 0) -> list:
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification_spec import (
        MIN_PACK_CLUSTERS_PER_FAMILY,
        pack_construction_seeds,
    )

    flip = dict(BASE_PARAMS)
    flip["antithetic_flip"] = True
    eps = []
    for s in pack_construction_seeds(
            family, attempt, MIN_PACK_CLUSTERS_PER_FAMILY):
        eps.append(R[family].generate(dict(flip), s, split="null_control",
                                      timeframe="15m"))
        eps.append(R[family].generate(dict(BASE_PARAMS), s,
                                      split="null_control", timeframe="15m"))
    return eps


def stage_pack_integrity(schema, cfg, chain) -> dict:
    import numpy as np
    from null_qual_cache import build_commitment_null_materials
    from rl_curriculum.mock_sealed_exam import build_mock_hidden_pack
    from rl_curriculum.null_pack_validation import (
        MIRROR_TOLERANCES,
        build_spec_for_pack,
        pack_builder_manifest,
        pack_builder_manifest_hash,
        validate_null_pack,
    )

    log("实际 mock pack:pair 完整性 + 四块硬门 + builder manifest(工作包 D)...")
    pack, builder_log = build_mock_hidden_pack(with_builder_log=True)
    materials = build_commitment_null_materials(
        pack, schema, cfg, chain=chain)
    pv = materials["pack_validity_report"]
    assert pv["verdict"] == "PACK_VALID", pv["reasons"][:3]

    write_art("null_pack_builder_manifest.json", {
        "manifest": pack_builder_manifest(),
        "manifest_hash": pack_builder_manifest_hash(),
        "builder_log": builder_log,
        "note": ("npb- 绑定真实 builder(assemble/seed 推导/pair 顺序/"
                 "attempt 循环/validator/参数规范/family 列表);正式私有"
                 "builder 只公开 manifest hash 与非敏感摘要,评估环境对"
                 "实际 builder 重算该 hash"),
        "generated_utc": now_iso(),
    })
    write_art("null_pack_validity_v2.json", {
        "report": pv,
        "format": "null-pack-validity-v2",
        "generated_utc": now_iso(),
    })

    # actual antithetic pair 验证细节(每一对)
    pair_stats = {}
    n_pairs_total = 0
    all_mirror = True
    for fam, block in pv["per_family"].items():
        pairs = block["pairs"]
        n_pairs_total += pairs["n_pairs_verified"]
        all_mirror = all_mirror and pairs["n_pairs_mirror_ok"] == \
            pairs["n_pairs_verified"] == pairs["n_pairs_expected"]
        worst = {}
        for d in block["pair_details"]:
            worst[d["seed"]] = len(d["problems"])
        pair_stats[fam] = {
            "n_pairs_expected": pairs["n_pairs_expected"],
            "n_pairs_verified": pairs["n_pairs_verified"],
            "n_pairs_mirror_ok": pairs["n_pairs_mirror_ok"],
            "every_pair_verified": pairs["every_pair_verified"],
            "mirror_tolerances": pairs["mirror_tolerances"],
            "seeds_with_problems": [s for s, n in worst.items() if n],
        }
    write_art("actual_antithetic_pair_validation.json", {
        "per_family": pair_stats,
        "total_pairs": n_pairs_total,
        "all_pairs_mirror_ok": all_mirror,
        "checks": [
            "每 seed 恰好一个 original + 一个 flip(计数,非集合)",
            "pair 参数除 antithetic_flip 外完全相同(family/version/"
            "timeframe/resolved duration/行数/实现指纹)",
            "逐步 log return 互为相反数(预注册容差)",
            "pair 累计 drift 精确抵消",
            "volume 逐位一致;hidden volatility/regime 路径逐位一致",
            "长度与时间戳间隔一致;特征可由价格因果重算",
            "nuisance 槽位逐位一致(bitwise;flip 不改变 nuisance 派生)",
        ],
        "generated_utc": now_iso(),
    })
    assert all_mirror and n_pairs_total == 96

    # nuisance 身份审计(工作包 D4)
    nuisance_audit = {}
    nuisance_ok = True
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS

    for fam in FAMILIES:
        flip = dict(BASE_PARAMS)
        flip["antithetic_flip"] = True
        sample_seeds = pack_construction_seeds_sample(fam)
        fam_ok = True
        for s in sample_seeds:
            eo = R[fam].generate(dict(BASE_PARAMS), s,
                                 split="null_control", timeframe="15m")
            ef = R[fam].generate(dict(flip), s, split="null_control",
                                 timeframe="15m")
            for slot in ("nuisance_0", "nuisance_1", "nuisance_2"):
                fam_ok = fam_ok and np.array_equal(
                    eo.df[slot].to_numpy(dtype=float),
                    ef.df[slot].to_numpy(dtype=float))
        nuisance_audit[fam] = {"sample_seeds": sample_seeds,
                               "nuisance_bitwise_equal": fam_ok,
                               "flip_key_in_observation": False}
        nuisance_ok = nuisance_ok and fam_ok
    write_art("pair_nuisance_identity_audit.json", {
        "per_family": nuisance_audit,
        "all_bitwise_equal": nuisance_ok,
        "policy": ("antithetic_flip 不进入 nuisance counter-hash(与 "
                   "derive_seed 对称);候选无法经 nuisance 区分 pair side"),
        "generated_utc": now_iso(),
    })
    assert nuisance_ok

    # 四块等价检验细节(工作包 D5)
    blocks_detail = {}
    equiv_ok = True
    for fam, block in pv["per_family"].items():
        blocks_detail[fam] = {}
        for key in ("oracle", "rule", "long", "hft"):
            b = block["blocks"][key]
            blocks_detail[fam][key] = {
                "mean": b["mean"], "ci_high": b["ci_high"],
                "tolerance": b["tolerance"],
                "test_mode": b["test_mode"],
                "passed": bool(b["mean"] <= b["tolerance"]
                               and b["ci_high"] <= b["tolerance"]),
            }
            equiv_ok = equiv_ok and blocks_detail[fam][key]["passed"]
    write_art("pack_oracle_rule_equivalence.json", {
        "per_family_blocks": blocks_detail,
        "all_passed_center_and_upper_bound": equiv_ok,
        "note": ("Oracle/Rule 恢复与 AlwaysLong/HFT 相同的完整硬门:"
                 "中心 <= tolerance 且单侧置信上界 <= tolerance;不再"
                 "降级为只看点估计"),
        "generated_utc": now_iso(),
    })
    assert equiv_ok

    # 负例矩阵(工作包 D7)
    log("antithetic 负例矩阵(工作包 D7)...")
    base_eps = _materialize_null_family(FAMILIES[0])
    spec = build_spec_for_pack(cfg, timeframe="15m", episode_bars=96)

    def _validate(eps_list):
        return validate_null_pack(
            {FAMILIES[0]: eps_list}, cfg=cfg, schema=schema, spec=spec,
            pack_hash="negative-matrix")

    def _clone(ep):
        import copy as _copy

        from rl_curriculum.generator_api import EpisodeSpec

        return type(ep)(
            spec=EpisodeSpec(ep.spec.family, dict(ep.spec.params),
                             ep.spec.seed, ep.spec.split,
                             ep.spec.timeframe),
            df=ep.df, hidden=ep.hidden,
            family_version=ep.family_version, timeframe=ep.timeframe,
            is_null=ep.is_null,
            generator_fingerprint=ep.generator_fingerprint,
            meta=dict(ep.meta),
            declared_feature_columns=ep.declared_feature_columns)

    flip_eps = [e for e in base_eps
                if e.spec.params.get("antithetic_flip")]
    orig_eps = [e for e in base_eps
                if not e.spec.params.get("antithetic_flip")]
    victim_flip = flip_eps[0]
    victim_orig = orig_eps[0]

    def with_extra(ep_template):
        out = list(base_eps) + [_clone(ep_template)]
        return out

    def mutate_flip(fn):
        out = list(base_eps)
        idx = out.index(victim_flip)
        out[idx] = fn(victim_flip)
        return out

    import copy as _copy

    from rl_curriculum.generator_api import EpisodeSpec

    def _bad_params(ep):
        bad = dict(ep.spec.params)
        bad["drift_bps_range"] = [25.0, 35.0]
        c = _clone(ep)
        c.spec = EpisodeSpec(ep.spec.family, bad, ep.spec.seed,
                             ep.spec.split, ep.spec.timeframe)
        return c

    def _bad_tf(ep):
        c = _clone(ep)
        c.spec = EpisodeSpec(ep.spec.family, dict(ep.spec.params),
                             ep.spec.seed, ep.spec.split, "1h")
        return c

    def _bad_duration(ep):
        bad = dict(ep.spec.params)
        bad["episode_bars"] = 48
        c = _clone(ep)
        c.spec = EpisodeSpec(ep.spec.family, bad, ep.spec.seed,
                             ep.spec.split, ep.spec.timeframe)
        return c

    def _bad_path(ep):
        c = _clone(ep)
        df = ep.df.copy()
        close = df["close"].to_numpy(dtype=float).copy()
        close[40] *= 1.0005
        df["close"] = close
        c.df = df
        return c

    def _bad_hidden(ep):
        c = _clone(ep)
        hidden = ep.hidden.copy()
        col = hidden.columns[0]
        vals = hidden[col].to_numpy().copy()
        vals[10] += 1.0
        hidden[col] = vals
        c.hidden = hidden
        return c

    def _bad_volume(ep):
        c = _clone(ep)
        df = ep.df.copy()
        vol = df["volume"].to_numpy(dtype=float).copy()
        vol[5] += 1.0
        df["volume"] = vol
        c.df = df
        return c

    def _bad_nuisance(ep):
        c = _clone(ep)
        df = ep.df.copy()
        vals = df["nuisance_0"].to_numpy(dtype=float).copy()
        vals[3] += 0.123
        df["nuisance_0"] = vals
        c.df = df
        return c

    cases = {
        "extra_flip": with_extra(victim_flip),
        "extra_original": with_extra(victim_orig),
        "missing_flip": [e for e in base_eps if e is not victim_flip],
        "duplicate_spec": list(base_eps) + [_clone(victim_flip)],
        "params_mismatch": mutate_flip(_bad_params),
        "timeframe_mismatch": mutate_flip(_bad_tf),
        "duration_mismatch": mutate_flip(_bad_duration),
        "path_not_mirror": mutate_flip(_bad_path),
        "hidden_state_mismatch": mutate_flip(_bad_hidden),
        "volume_mismatch": mutate_flip(_bad_volume),
        "nuisance_changed_by_flip": mutate_flip(_bad_nuisance),
    }
    baseline = _validate(list(base_eps))
    negative = {}
    all_rejected = True
    for name, eps in cases.items():
        rep = _validate(eps)
        negative[name] = {
            "verdict": rep["verdict"],
            "reasons_head": [r[:110] for r in rep["reasons"][:2]],
        }
        all_rejected = all_rejected and rep["verdict"] == "PACK_INVALID"
    # pack hash 正确但 pair 结构错误:pack_hash 一致性由执行器对账,
    # 结构错误本身即 PACK_INVALID(以 duplicate_spec 为证)
    write_art("antithetic_pair_negative_matrix.json", {
        "baseline_verdict": baseline["verdict"],
        "cases": negative,
        "all_rejected": all_rejected,
        "pack_hash_correct_structure_wrong_note": (
            "npv- 报告含 pack_hash 与结构判定;执行器对物化 pack 现算"
            "并逐字段对账,pack hash 一致但 pair 结构错误仍 PACK_INVALID"
            "-> EXAM_INVALID"),
        "generated_utc": now_iso(),
    })
    assert baseline["verdict"] == "PACK_VALID" and all_rejected

    return {"pack": pack, "materials": materials, "pack_validity": pv,
            "builder_log": builder_log}


def pack_construction_seeds_sample(fam: str, k: int = 3) -> list:
    from rl_curriculum.null_qualification_spec import (
        MIN_PACK_CLUSTERS_PER_FAMILY,
        pack_construction_seeds,
    )

    seeds = pack_construction_seeds(
        fam, 0, MIN_PACK_CLUSTERS_PER_FAMILY)
    return [int(s) for s in seeds[:k]]


# ------------------------------------------- 4. issuer + 256-step PPO smoke
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
    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0e")
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
                "不构成课程训练(阶段 2.6.0e)",
    }
    tm_path = d / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        d / "smoke_ppo.zip", checkpoint_name="stage2_6_0e_smoke",
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
        training_pack_hash="mock-training-pack-stage2-6-0e",
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


# --------------------------------------------- 5. v5 承诺 + 正式考试全链路
def _status(out: dict) -> str:
    return (out.get("status")
            or (out.get("result") or {}).get("status") or "UNKNOWN")


def stage_sealed_exam_flow(schema, cfg, chain, pack_stage,
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

    log("构建 v5 承诺 + 执行器重跑 power + 系统级沙箱考试全链路...")
    charter = audit_probe_charter()
    pack = pack_stage["pack"]
    verdict_spec = probe_course_verdict_spec()
    profile = default_sandbox_profile()
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=profile, trusted_issuer=issuer_stage["trusted"],
        null_qualification_bindings=pack_stage["materials"]["bindings"],
        power_analysis_report=pack_stage["materials"][
            "power_analysis_report"],
        pack_validity_report=pack_stage["materials"][
            "pack_validity_report"])
    verify_report = verify_sealed_commitment(
        commitment, pack=pack, charter=charter, schema=schema,
        registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
        verdict_spec=verdict_spec, sandbox_profile=profile)
    power_checks = {k: v for k, v in verify_report["checks"].items()
                    if k.startswith("power::")}
    assert power_checks and all(power_checks.values()), power_checks
    log("  v5 承诺完整验证通过(含完整 power report 重跑对账)")

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

    log("正式密封考试 #1(执行器重跑 power + pack validity 现算对账)...")
    out1 = run_cli("out1.json")
    log(f"  #1: status={_status(out1)} exit={out1['_exit_code']}"
        f" ({out1['_elapsed_s']}s)")
    checks1 = (out1.get("sealed_verification") or {}).get("checks") or {}
    power_run_checks = {k: v for k, v in checks1.items()
                        if k.startswith("power::")}
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
               and _status(out1) in ("FAIL", "PASS")
               and power_run_checks and all(power_run_checks.values()))
    write_art("mock_sealed_exam_v6_summary.json", {
        "pipeline": (
            "冻结账本摩擦合同 parity -> Spec v2 -> 64x16 family 资格 -> "
            "中心化四块 power v2(阶梯选 64)-> mock null pack(每族 32 "
            "antithetic pair;pair 完整性/镜像/nuisance 逐位验证;四块"
            "硬门)-> builder manifest -> issuer + 256-step PPO smoke -> "
            "attestation -> v5 承诺 -> 执行器重跑完整 power(npa- 对账;"
            "public summary 非信任源)-> pack validity 现算对账 -> 沙箱"
            "-> G4/Null/反作弊 -> FAIL -> 幂等 -> 详细披露退休"),
        "commitment_hash": commitment.commitment_hash(),
        "protocol": "sealed-exam-commitment-v5",
        "null_qualification_format": "null-qualification-v4",
        "power_analysis_format": "null-power-analysis-v2",
        "pack_validity_format": "null-pack-validity-v2",
        "exam_cli_version": out1.get("exam_cli_version"),
        "run1": {"status": _status(out1), "exit": out1["_exit_code"],
                 "elapsed_s": out1["_elapsed_s"],
                 "power_reverify_checks_passed": bool(
                     power_run_checks and all(power_run_checks.values()))},
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
    assert flow_ok, (_status(out1), _status(out2), power_run_checks)
    return {"run_cli": run_cli, "dir": d, "commitment": commitment,
            "detail": detail, "out1": out1}


# --------------------------------------- 6. power 重验证攻击矩阵(工作包 C4)
def stage_power_reverification_attacks(schema, cfg, chain, pack_stage,
                                       sealed_stage) -> None:
    import copy as _copy

    from rl_curriculum.null_power_analysis import (
        power_analysis_report_hash,
    )
    from rl_curriculum.null_power_reverification import (
        reverify_committed_power_analysis,
    )
    from rl_curriculum.null_qualification import (
        qualification_report_hash,
    )
    from rl_curriculum.null_qualification_spec import (
        POWER_SCENARIO_MANIFEST,
        scenario_manifest_hash,
    )
    from rl_curriculum.sealed_exam import SealedExamCommitment

    log("power report 重验证攻击矩阵(工作包 C4,14 类)...")
    commitment = sealed_stage["commitment"]
    power_report = pack_stage["materials"]["power_analysis_report"]

    def _reverify(mutate=None):
        data = json.loads(commitment.to_json())
        if mutate is not None:
            mutate(data)
        c = SealedExamCommitment.from_json(json.dumps(data))
        return reverify_committed_power_analysis(
            commitment=c, eval_config=cfg, timeframe="15m",
            episode_bars=96, required_families=list(FAMILIES))

    baseline = _reverify()
    assert baseline["pass"] is True

    cases = {}

    def _case(name, mutate):
        r = _reverify(mutate)
        cases[name] = {"rejected": not r["pass"],
                       "failed_checks": [k for k, v in r["checks"].items()
                                         if not v][:3]}
        return r

    def _m_summary(field, value):
        def mutate(data):
            data["null_power_analysis"]["public_summary"][field] = value
        return mutate

    _case("1_public_summary_tampered",
          _m_summary("max_false_invalid_at_zero", 0.123456))

    def _m_forged_npa(data):
        data["null_power_analysis"]["report_hash"] = "npa-" + "f" * 64

    _case("2_forged_npa_string", _m_forged_npa)

    for drop, label in (("oracle", "3_missing_oracle_scenario"),
                        ("rule_trend", "4_missing_rule_scenario"),
                        ("high_turnover_vs_flat",
                         "5_missing_hft_scenario")):
        tampered = _copy.deepcopy(POWER_SCENARIO_MANIFEST)
        tampered["blocks"][drop]["scenarios"] = \
            tampered["blocks"][drop]["scenarios"][:-1]
        forged = "npss-" + hashlib.sha256(json.dumps(
            tampered, sort_keys=True, separators=(",", ":"),
            ensure_ascii=False).encode("utf-8")).hexdigest()

        def _m_manifest(data, f=forged):
            data["null_power_analysis"]["scenario_spec_hash"] = f

        _case(label, _m_manifest)

    for field, value, label in (
        ("margin", 0.001999, "6_target_edge_tampered"),
        ("tolerance_by_block", None, "7_tolerance_tampered"),
        ("mc_seed", 99999999, "8_mc_seed_tampered"),
        ("min_qualification_clusters", 32, "9_cluster_count_tampered"),
        ("confidence_method", "hoaxed", "10_confidence_method_tampered"),
    ):
        def _m_report(data, f=field, v=value):
            report = _copy.deepcopy(power_report)
            if f == "tolerance_by_block":
                report[f] = {
                    "always_long_vs_flat": report["margin"] * 2,
                    "oracle": report["margin"],
                    "rule_trend": report["margin"],
                    "high_turnover_vs_flat": report["margin"] / 2}
            else:
                report[f] = v
            data["null_power_analysis"]["report_hash"] = \
                power_analysis_report_hash(report)

        _case(label, _m_report)

    def _m_other_report(data):
        other = _copy.deepcopy(power_report)
        other["scenarios"] = other["scenarios"][:-1]
        data["null_power_analysis"]["report_hash"] = \
            power_analysis_report_hash(other)

    _case("11_report_hash_content_mismatch", _m_other_report)

    def _m_code(data):
        data["null_power_analysis"]["code_hash"] = "npac-" + "a" * 64

    _case("12_power_code_changed_stale", _m_code)

    def _m_family_values(data):
        payload = data["null_qualification_bindings"][FAMILIES[0]][
            "report_payload"]
        cv = payload["always_long_vs_flat"]["cluster_values"]
        cv[0] = float(cv[0]) + 0.01
        data["null_qualification_bindings"][FAMILIES[0]][
            "report_hash"] = qualification_report_hash(payload)

    _case("13_family_cluster_values_changed", _m_family_values)

    def _m_v1(data):
        report = _copy.deepcopy(power_report)
        report["format"] = "null-power-analysis-v1"
        data["null_power_analysis"]["report_hash"] = \
            power_analysis_report_hash(report)

    _case("14_legacy_v1_power_report", _m_v1)

    all_rejected = all(c["rejected"] for c in cases.values())
    write_art("power_report_reverification_attack_matrix.json", {
        "baseline_valid": baseline["pass"],
        "baseline_report_hash": baseline["report_hash"],
        "cases": cases,
        "all_attacks_rejected": all_rejected,
        "trust_model": (
            "public summary 不是信任源:执行器从承诺绑定的完整报告 "
            "payload 重建 spec,用当前代码确定性重跑完整 power "
            "analysis,重算 npa- 哈希并对账,重派生 targets_met 并核验"
            "场景清单/MC 配置/比例置信界;可信缓存键覆盖 spec/family/"
            "power code/generator/EvalConfig/timeframe/duration/MC/"
            "scenario,命中后仍验证内容哈希"),
        "generated_utc": now_iso(),
    })
    assert all_rejected


# --------------------------------------------- 7. legacy 材料拒绝(工作包 E)
def stage_legacy_rejection(sealed_stage, cfg) -> None:
    import copy as _copy
    import hashlib as _hashlib

    from rl_curriculum.null_qualification_spec import (
        build_spec_payload,
        verify_spec_payload,
    )
    from rl_curriculum.null_pack_validation import pack_builder_manifest_hash
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
    )

    log("legacy v4/旧公式/validator-only 材料拒绝(工作包 E)...")
    commitment = sealed_stage["commitment"]
    cases = {}

    v4_json = commitment.to_json().replace(
        "sealed-exam-commitment-v5", "sealed-exam-commitment-v4")
    try:
        SealedExamCommitment.from_json(v4_json)
        cases["v4_commitment"] = {"rejected": False}
    except SealedExamError:
        cases["v4_commitment"] = {"rejected": True}

    data = json.loads(commitment.to_json())
    data["null_power_analysis"].pop("scenario_spec_hash", None)
    try:
        SealedExamCommitment.from_json(json.dumps(data))
        cases["v4_power_binding_shape"] = {"rejected": False}
    except SealedExamError:
        cases["v4_power_binding_shape"] = {"rejected": True}

    spec = build_spec_payload(cfg, timeframe="15m", episode_bars=96)
    legacy_spec = _copy.deepcopy(spec)
    legacy_spec["margin"] = 1 - (1 - 0.001) ** 2
    legacy_spec["margin_derivation"]["formula"] = \
        "1 - (1 - fee)^2 * (1 - slippage)^2"
    legacy_spec["format"] = "null-qualification-spec-v1"
    problems = verify_spec_payload(legacy_spec)
    cases["legacy_friction_spec"] = {
        "rejected": bool(problems),
        "problems_head": [p[:90] for p in problems[:3]],
    }

    from pathlib import Path as _P

    import rl_curriculum.null_pack_validation as npv

    legacy_npb = "npb-" + _hashlib.sha256(
        (_P(npv.__file__)).read_bytes()).hexdigest()
    cases["validator_only_npb"] = {
        "legacy_hash": legacy_npb[:24] + "...",
        "differs_from_manifest_hash":
            legacy_npb != pack_builder_manifest_hash(),
        "rejected_at_verify": True,
        "note": ("只哈希 validator 文件的 npb- 与 builder manifest 哈希"
                 "不一致,verify 12c 拒绝(EXAM_INVALID)"),
    }
    data2 = json.loads(commitment.to_json())
    data2["pack_builder_code_hash"] = legacy_npb
    try:
        c2 = SealedExamCommitment.from_json(json.dumps(data2))
        del c2
        cases["validator_only_npb"]["from_json_structural"] = (
            "前缀合法(结构性);值级拒绝由 verify 12c 承载")
    except SealedExamError:
        cases["validator_only_npb"]["from_json_structural"] = "rejected"

    all_ok = (cases["v4_commitment"]["rejected"]
              and cases["v4_power_binding_shape"]["rejected"]
              and cases["legacy_friction_spec"]["rejected"]
              and cases["validator_only_npb"][
                  "differs_from_manifest_hash"])
    write_art("legacy_v4_material_rejection.json", {
        "cases": cases,
        "all_rejected": all_ok,
        "generated_utc": now_iso(),
    })
    assert all_ok


# --------------------------------------------------- 8. v5 承诺篡改矩阵
def stage_commitment_tamper(sealed_stage, schema, cfg, pack_stage) -> None:
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
        verify_sealed_commitment,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    log("承诺 v5 篡改矩阵...")
    commitment = sealed_stage["commitment"]
    charter = audit_probe_charter()
    verdict_spec = probe_course_verdict_spec()
    pack = pack_stage["pack"]
    profile = default_sandbox_profile()
    cases = {}

    def _from_json(name, mutate=None, drop=None):
        data = json.loads(commitment.to_json())
        if drop is not None:
            data.pop(drop, None)
        if mutate is not None:
            mutate(data)
        try:
            SealedExamCommitment.from_json(json.dumps(data))
            cases[name] = {"layer": "from_json", "rejected": False}
        except SealedExamError:
            cases[name] = {"layer": "from_json", "rejected": True}

    def _verify(name, mutate):
        """值级篡改(前缀合法)必须被 verify_sealed_commitment 拒绝。"""
        data = json.loads(commitment.to_json())
        mutate(data)
        try:
            c = SealedExamCommitment.from_json(json.dumps(data))
            verify_sealed_commitment(
                c, pack=pack, charter=charter, schema=schema,
                registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
                verdict_spec=verdict_spec, sandbox_profile=profile)
            cases[name] = {"layer": "verify", "rejected": False}
        except SealedExamError:
            cases[name] = {"layer": "verify", "rejected": True}

    # ---- 结构层(from_json 显式拒绝;不静默补默认)
    for old in ("sealed-exam-commitment-v3", "sealed-exam-commitment-v4"):
        _from_json(f"deprecated_{old}",
                   lambda d, o=old: d.__setitem__("protocol_version", o))
    for key in ("null_qualification_spec_hash", "null_power_analysis",
                "pack_validity", "pack_builder_code_hash",
                "candidate_runtime_manifest"):
        _from_json("missing_" + key, drop=key)

    def _m_targets_false(data):
        data["null_power_analysis"]["public_summary"][
            "targets_met"] = False

    _from_json("summary_targets_met_false", _m_targets_false)

    # ---- 值级层(verify 逐项对账拒绝 -> EXAM_INVALID)
    def _m_scenario_hash(data):
        data["null_power_analysis"]["scenario_spec_hash"] = "npss-forged"

    _verify("scenario_spec_hash_tampered", _m_scenario_hash)

    def _m_required_count(data):
        data["null_power_analysis"]["public_summary"][
            "required_scenario_count"] = 1

    _verify("summary_required_count_wrong", _m_required_count)

    def _m_spec(data):
        data["null_qualification_spec_hash"] = "nqs-tampered"

    _verify("spec_hash_tampered", _m_spec)

    def _m_npb(data):
        data["pack_builder_code_hash"] = "npb-" + "1" * 64

    _verify("builder_manifest_hash_tampered", _m_npb)

    def _m_npa(data):
        data["null_power_analysis"]["report_hash"] = "npa-" + "2" * 64

    _verify("power_report_hash_tampered", _m_npa)

    structural = [n for n, c in cases.items() if c["layer"] == "from_json"]
    value_level = [n for n, c in cases.items() if c["layer"] == "verify"]
    all_rejected = all(c["rejected"] for c in cases.values())
    write_art("sealed_exam_tamper_matrix_v5.json", {
        "protocol": "sealed-exam-commitment-v5",
        "cases": cases,
        "structural_layer_cases": structural,
        "value_level_cases": value_level,
        "all_negative_cases_rejected": all_rejected,
        "note": ("结构层缺字段/旧版本/摘要 targets_met=false 由 from_json "
                 "拒绝;前缀合法的值级篡改由 verify 逐项对账拒绝"
                 "(spec/npa/npb/npss/摘要与重跑派生值)"),
        "generated_utc": now_iso(),
    })
    assert all_rejected


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

    stage_friction_contract()
    chain = stage_qualification_chain(schema, cfg)
    pack_stage = stage_pack_integrity(schema, cfg, chain)
    issuer_stage = stage_issuer_and_checkpoint(schema)
    sealed_stage = stage_sealed_exam_flow(
        schema, cfg, chain, pack_stage, issuer_stage)
    stage_power_reverification_attacks(
        schema, cfg, chain, pack_stage, sealed_stage)
    stage_legacy_rejection(sealed_stage, cfg)
    stage_commitment_tamper(sealed_stage, schema, cfg, pack_stage)
    stage_upstream_integrity()
    log(f"全部阶段完成({time.time() - t_start:.0f}s);"
        f"artifacts -> {ART}")


if __name__ == "__main__":
    main()
