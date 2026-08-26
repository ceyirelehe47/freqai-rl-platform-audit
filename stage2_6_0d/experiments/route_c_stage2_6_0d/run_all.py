# -*- coding: utf-8 -*-
"""阶段 2.6.0d:Strict Null 统计资格与经济等价闭环实验。

链路(与正式同构):
 1. 三族严格 Null 的 v3 三态资格报告(64 seed cluster x 8 episodes,
    共享确定性缓存;全部必须 QUALIFIED);
 2. 3-seed 小样本反例复现(2.6.0c 审查发现:stochvol Always Long
    中位 ~+2.40% / sign ~+0.75% 仍被旧实现判 PASS)——新协议下必须
    INSUFFICIENT_EVIDENCE,不得进入正式考试;
 3. 经济等价:单侧 TOST 无条件多头优势带(上界 <= 0.5%)/不对称
    episode 累计漂移带(+0.5% / -1.0%);漂移伪 Null -> INVALID_NULL;
 4. cluster 统计单位审计:bootstrap n == distinct independent
    clusters(四统计块 x 三族);同 seed 9 episode 只算 1 cluster;
 5. mock issuer + 256-step PPO smoke(允许挂科,不构成课程训练)
    + sidecar + attestation;
 6. v3 承诺(候选运行时绑定 + 真实 v3 Null 报告绑定);
 7. 系统级沙箱正式考试 + 幂等重试 + 详细披露退休;
 8. Null 资格篡改矩阵(v2/v1 格式、非 QUALIFIED 三态、统计单位、
    预注册参数、bool-only);
 9. 2.6.0c 闭环保留守卫(issuer 信任根/运行时绑定/反作弊复制);
10. 上游与冻结合同完整性;全部证据写入 artifacts/route_c_stage2_6_0d。
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

RESULTS: dict[str, dict] = {}


def _null_verify_kwargs() -> dict:
    """verify_null_qualification_bindings 的完整对账材料(与正式
    考试同源:真实生成器绑定/schema/EvalConfig/timeframe)。"""
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.probe_charter import probe_observation_schema

    from rl_curriculum.mock_sealed_exam import default_eval_config

    return {
        "generator_bindings": generator_bindings(dict(R)),
        "observation_schema_hash": probe_observation_schema().schema_hash(),
        "eval_config_manifest": default_eval_config().manifest(),
        "timeframe": "15m",
    }


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


# ------------------------------------------------------ 1. v3 资格报告(64x8)
def stage_null_reports_v3(schema, cfg) -> dict:
    from null_qual_cache import cached_null_qual_reports
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    log("生成三族严格 Null 的 v3 三态资格报告(64 cluster x 8 ep)...")
    t0 = time.time()
    reports = cached_null_qual_reports(schema, cfg)
    log(f"  缓存/生成耗时 {time.time() - t0:.1f}s")
    ok = True
    summary = {}
    for fam in FAMILIES:
        rep = reports[fam]
        lf = rep["always_long_vs_flat"]["excess_bootstrap"]
        dr = rep["episode_net_drift"]["bootstrap"]
        summary[fam] = {
            "verdict": rep["verdict"],
            "n_clusters": rep["n_clusters"],
            "n_episodes_tested": rep["n_episodes_tested"],
            "always_long_vs_flat_CI": [lf["ci_low"], lf["ci_high"]],
            "episode_net_drift_CI": [dr["ci_low"], dr["ci_high"]],
            "checks_all_true": all(rep["checks"].values()),
        }
        ok = ok and rep["verdict"] == "QUALIFIED"
        log(f"  {fam}: {rep['verdict']} "
            f"lf_CI=[{lf['ci_low']:+.5f},{lf['ci_high']:+.5f}] "
            f"drift_CI=[{dr['ci_low']:+.5f},{dr['ci_high']:+.5f}]")
    (ART / "null_reports").mkdir(exist_ok=True)
    for fam, rep in reports.items():
        (ART / "null_reports" / f"{fam}.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False),
            encoding="utf-8")
    write_art("null_qualification_v3_full_sample.json", {
        "protocol": "null-qualification-v3",
        "sample": "64 seed clusters x 8 episodes x 3 families",
        "all_qualified": ok,
        "per_family": summary,
        "generated_utc": now_iso(),
    })
    assert ok, "全样本三族必须 QUALIFIED(mock 链路资格来源)"
    return {"reports": reports,
            "bindings": build_null_qualification_bindings(reports)}


# ------------------------------------------------- 2. 3-seed 反例(不再 PASS)
def stage_small_sample_counterexample(schema, cfg) -> dict:
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import (
        qualify_null_family,
        verify_null_qualification_bindings,
    )

    log("复现 2.6.0c 审查反例(3 seed x 1 episode)...")
    reports = {}
    for fam in FAMILIES:
        reports[fam] = qualify_null_family(
            R[fam], params=dict(BASE_PARAMS), timeframe="15m",
            seeds=[11, 22, 33], cfg=cfg, schema=schema,
            episodes_per_seed=1)
    none_qualified = all(r["verdict"] != "QUALIFIED"
                         for r in reports.values())
    stoch = reports["probe_null_stochvol"]
    sign = reports["probe_null_sign"]
    # INSUFFICIENT 报告送入承诺链 -> verify 拒绝
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )

    verdict = verify_null_qualification_bindings(
        build_null_qualification_bindings(reports),
        required_families=list(FAMILIES), **_null_verify_kwargs())
    write_art("null_qualification_small_sample_counterexample.json", {
        "finding_2_6_0c_review": (
            "2.6.0c 的 3-seed 资格样本中 stochvol Always Long 中位 "
            "~+2.40% / sign ~+0.75% 且 Always Flat 中位 0,仍被判 "
            "always_flat_strong_baseline=true 并整体 PASS;旧实现把 bar "
            "当独立 bootstrap 样本(n=288),per-bar 容差 0.0008 折算 "
            "累计 7.68%"),
        "small_sample": {
            fam: {
                "verdict": r["verdict"],
                "always_flat_median": r["always_flat_median"],
                "always_long_median": r["always_long_median"],
                "lf_ci": [r["always_long_vs_flat"]["excess_bootstrap"]
                          ["ci_low"],
                          r["always_long_vs_flat"]["excess_bootstrap"]
                          ["ci_high"]],
                "checks": r["checks"],
            }
            for fam, r in reports.items()
        },
        "counterexamples_no_longer_qualified": none_qualified,
        "stochvol_median_reproduced": stoch["always_long_median"],
        "sign_median_reproduced": sign["always_long_median"],
        "insufficient_rejected_by_commitment_verify":
            not verdict["pass"],
        "reject_problems_head": verdict["problems"][:2],
        "generated_utc": now_iso(),
    })
    assert none_qualified, "3-seed 样本必须不再 QUALIFIED(任务书要求)"
    assert stoch["always_long_median"] > 0.02
    assert sign["always_long_median"] > 0.007
    assert not verdict["pass"]
    log(f"  stochvol 中位 {stoch['always_long_median']:+.5f} / "
        f"sign {sign['always_long_median']:+.5f} -> 三族全部 "
        f"INSUFFICIENT_EVIDENCE,verify 拒绝进入考试")


# ------------------------------------------------------ 3. 经济等价与反证
def stage_economic_equivalence(schema, cfg) -> dict:
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import (
        MAX_NEGATIVE_DRIFT,
        MAX_TRADABLE_DRIFT,
        MAX_UNCONDITIONAL_LONG_EDGE,
        MIN_QUALIFICATION_CLUSTERS,
        qualify_null_family,
    )

    log("经济等价:漂移伪 Null(64 cluster)必须 INVALID_NULL...")
    params = dict(BASE_PARAMS)
    params["direction_weights"] = [0.0, 0.9, 0.1]
    t0 = time.time()
    disproof = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=params, timeframe="15m",
        seeds=list(range(11, 75)), cfg=cfg, schema=schema,
        episodes_per_seed=2)
    lf = disproof["always_long_vs_flat"]["excess_bootstrap"]
    dr = disproof["episode_net_drift"]["bootstrap"]
    write_art("null_qualification_economic_disproof.json", {
        "scenario": "direction_weights=[0.0,0.9,0.1] 的漂移伪 Null",
        "sample": "64 cluster x 2 episodes",
        "verdict": disproof["verdict"],
        "lf_CI": [lf["ci_low"], lf["ci_high"]],
        "drift_CI": [dr["ci_low"], dr["ci_high"]],
        "lf_ci_low_above_band": lf["ci_low"] > MAX_UNCONDITIONAL_LONG_EDGE,
        "drift_ci_low_above_band": dr["ci_low"] > MAX_TRADABLE_DRIFT,
        "reasons": disproof["reasons"],
        "elapsed_s": round(time.time() - t0, 1),
        "generated_utc": now_iso(),
    })
    assert disproof["verdict"] == "INVALID_NULL"
    assert lf["ci_low"] > MAX_UNCONDITIONAL_LONG_EDGE

    write_art("economic_band_registration.json", {
        "registered_bands": {
            "max_unconditional_long_edge": MAX_UNCONDITIONAL_LONG_EDGE,
            "max_tradable_drift": MAX_TRADABLE_DRIFT,
            "max_negative_drift": MAX_NEGATIVE_DRIFT,
            "min_qualification_clusters": MIN_QUALIFICATION_CLUSTERS,
            "episodes_per_seed": 8,
        },
        "semantics": {
            "always_flat_strong_baseline": (
                "Always Long - Flat 的 cluster 级 bootstrap CI 上界 <= "
                "0.005(单侧 TOST:证明无可交易无条件多头优势)"),
            "episode_net_drift_nonexploitable": (
                "每 episode 累计 log drift 的 cluster 级 CI:上界 <= "
                "+0.005(正漂移可被 Long/Flat 现货利用),下界 >= -0.010"
                "(负漂移不可利用,仅结构性非中心证据拒绝)"),
            "abolished": (
                "v2 per-bar 容差 0.0008 x 96 bar = 7.68% 累计漂移容差"
                "与 bar 级 bootstrap(n=288 假样本)全部废除"),
            "power_derivation": (
                "每 episode Always Long 净收益 std 实测约 3%;K=8 "
                "episode/seed 的 cluster std 约 1.1%;n=64 时 bootstrap "
                "CI 半宽约 0.27%,足以在单侧 TOST 下覆盖 0.005 带"
                "(实测三族 CI 上界 +0.0008/-0.0013/-0.0015 全部带内)"),
        },
        "generated_utc": now_iso(),
    })
    return {}


# ------------------------------------------------------ 4. cluster 单位审计
def stage_cluster_unit_audit(schema, cfg, full_reports) -> dict:
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import (
        CLUSTER_AGGREGATION,
        BOOTSTRAP_UNIT,
        qualify_null_family,
    )

    log("cluster 统计单位审计(bootstrap n == distinct clusters)...")
    blocks = {
        "oracle": "excess_bootstrap",
        "rule_trend": "excess_bootstrap",
        "always_long_vs_flat": "excess_bootstrap",
        "episode_net_drift": "bootstrap",
    }
    audit = {"full_sample": {}, "nine_episodes_one_seed": {},
             "recorded_fields": ["n_episodes_tested", "n_clusters",
                                 "distinct_seeds", "cluster_aggregation",
                                 "bootstrap_unit", "episodes_per_seed"],
             "cluster_aggregation": CLUSTER_AGGREGATION,
             "bootstrap_unit": BOOTSTRAP_UNIT}
    all_ok = True
    for fam in FAMILIES:
        rep = full_reports[fam]
        fam_audit = {}
        for block, boot_key in blocks.items():
            boot = rep[block][boot_key]
            cv = rep[block]["cluster_values"]
            consistent = (boot["n"] == rep["n_clusters"]
                          == rep["distinct_seeds"] == len(cv))
            fam_audit[block] = {"bootstrap_n": boot["n"],
                                "cluster_values_len": len(cv),
                                "consistent": consistent}
            all_ok = all_ok and consistent
        fam_audit["episode_count_formula_ok"] = (
            rep["n_episodes_tested"]
            == rep["n_clusters"] * rep["episodes_per_seed"])
        all_ok = all_ok and fam_audit["episode_count_formula_ok"]
        audit["full_sample"][fam] = fam_audit
    # 同 seed 9 个关联 episode -> 1 cluster
    rep9 = qualify_null_family(
        ProbeSegmentedDriftGenerator(), params=dict(BASE_PARAMS),
        timeframe="15m", seeds=[777], cfg=cfg, schema=schema,
        episodes_per_seed=9)
    n_ok = (rep9["n_episodes_tested"] == 9 and rep9["n_clusters"] == 1
            and all(rep9[b][k]["n"] == 1 for b, k in blocks.items()))
    audit["nine_episodes_one_seed"] = {
        "n_episodes_tested": rep9["n_episodes_tested"],
        "n_clusters": rep9["n_clusters"],
        "distinct_seeds": rep9["distinct_seeds"],
        "all_bootstrap_n_equal_one": n_ok,
    }
    all_ok = all_ok and n_ok
    audit["bootstrap_n_equals_distinct_clusters"] = all_ok
    write_art("cluster_bootstrap_unit_audit.json", audit)
    assert all_ok, "bootstrap 单位必须是 seed cluster"
    log(f"  全部统计块 n == clusters(9 ep/1 seed 用例 n_clusters=1)")


# ------------------------------------------- 5. issuer + smoke 训练(2.6.0c 模式)
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

    log("生成 mock issuer(Ed25519)与受信 runner 配置...")
    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0d")
    trusted = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=True)

    d = WORK / "ckpt"
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    log("受控 PPO smoke 训练(256 步,允许挂科;非课程训练)...")
    material = _train_smoke_ppo(d / "smoke_ppo.zip", n_steps=256)
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": 256,
        "seed": material["training_seed"],
        "note": ("256-step PPO smoke:仅验证 provenance/sandbox/接口;"
                 "不构成课程训练(阶段 2.6.0d)"),
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
    ckpt_sha = hashlib.sha256((d / "smoke_ppo.zip").read_bytes()).hexdigest()
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
            "checkpoint": str(d / "smoke_ppo.zip"),
            "attestation": att, "training_material": material}


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


# --------------------------------------- 6-7. 承诺 + 沙箱考试 + 幂等 + 披露
def _status(out: dict) -> str:
    return (out.get("status")
            or (out.get("result") or {}).get("status") or "UNKNOWN")


def stage_sealed_exam_flow(schema, cfg, null_stage, issuer_stage) -> dict:
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
        write_exam_context,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import verify_sealed_commitment
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    log("构建 mock hidden pack + v3 承诺(v3 Null 绑定)...")
    charter = audit_probe_charter()
    pack = build_mock_hidden_pack()
    verdict_spec = probe_course_verdict_spec()
    profile = default_sandbox_profile()
    commitment = build_mock_commitment(
        pack=pack, charter=charter, schema=schema,
        verdict_spec=verdict_spec, eval_config=cfg,
        sandbox_profile=profile,
        trusted_issuer=issuer_stage["trusted"],
        null_qualification_bindings=null_stage["bindings"])

    # 完整承诺验证(v3 Null 报告全部对账)
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY

    report = verify_sealed_commitment(
        commitment, pack=pack, charter=charter, schema=schema,
        registry=DEFAULT_GENERATOR_REGISTRY, eval_config=cfg,
        verdict_spec=verdict_spec, sandbox_profile=profile)
    write_art("sealed_commitment_verification_v3.json", {
        "commitment_hash": commitment.commitment_hash(),
        "protocol": "sealed-exam-commitment-v3",
        "null_qualification_format": "null-qualification-v3",
        "verify_pass": report["pass"],
        "checks": report["checks"],
        "problems": report["problems"],
        "generated_utc": now_iso(),
    })
    assert report["pass"], "v3 承诺必须通过完整验证"

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
            argv, capture_output=True, text=True, timeout=900,
            cwd=str(PROJ), env=env)
        out_path = d / out_name
        out = (json.loads(out_path.read_text(encoding="utf-8"))
               if out_path.is_file()
               else {"stdout": proc.stdout[-2000:],
                     "stderr": proc.stderr[-2000:]})
        out["_exit_code"] = proc.returncode
        out["_elapsed_s"] = round(time.time() - t0, 1)
        return out

    log("正式密封考试 #1(系统级沙箱 + 反事实套件)...")
    out1 = run_cli("out1.json")
    log(f"  #1: status={_status(out1)} exit={out1['_exit_code']}"
        f" ({out1['_elapsed_s']}s)")
    log("幂等重试 #2(同 checkpoint+pack)...")
    out2 = run_cli("out2.json")
    log(f"  #2: status={_status(out2)} exit={out2['_exit_code']}"
        f" ({out2['_elapsed_s']}s)")
    log("详细披露 #3(--detailed;披露后包退休)...")
    out3 = run_cli("out3.json", "--detailed", str(d / "detailed.json"))
    detail = json.loads(
        (d / "detailed.json").read_text(encoding="utf-8")) \
        if (d / "detailed.json").is_file() else {}
    log(f"  #3: status={_status(out3)} exit={out3['_exit_code']}")

    flow_ok = (_status(out1) == _status(out2)
               and _status(out1) in ("FAIL", "PASS"))
    write_art("mock_sealed_exam_flow_v3_nulls.json", {
        "pipeline": ("mock hidden pack -> v3 Null 资格(64 cluster 三态 "
                     "QUALIFIED)-> issuer/受信 runner -> 256-step PPO "
                     "smoke(允许挂科)-> sidecar + attestation -> v3 承诺"
                     "(runtime tree hash + 真实 v3 Null 报告)-> 系统级"
                     "沙箱 -> 反事实套件 -> 冻结判定 -> 幂等重试 -> "
                     "详细披露退休"),
        "commitment_hash": commitment.commitment_hash(),
        "protocol": "sealed-exam-commitment-v3",
        "null_qualification_format": "null-qualification-v3",
        "exam_cli_version": out1.get("exam_cli_version"),
        "run1": {"status": _status(out1), "exit": out1["_exit_code"],
                 "elapsed_s": out1["_elapsed_s"]},
        "run2_idempotent": {
            "status": _status(out2), "exit": out2["_exit_code"],
            "same_result_as_run1": _status(out1) == _status(out2)},
        "run3_detailed": {"status": _status(out3),
                          "exit": out3["_exit_code"],
                          "pack_retired": bool(detail)},
        "flow_ok": flow_ok,
        "smoke_training_note": (
            "256-step PPO 仅验证 provenance/sandbox/接口;允许正常挂科,"
            "不构成课程训练,不开始正式 PPO 课程训练"),
        "generated_utc": now_iso(),
    })
    assert flow_ok, "考试链路必须正常完成(挂科合法,EXAM_INVALID 不合法)"
    return {"run_cli": run_cli, "dir": d, "commitment": commitment}


# ------------------------------------------------------ 8. Null 篡改矩阵
def stage_null_tamper_matrix(full_reports) -> dict:
    import copy as _copy

    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualification_report_hash,
        verify_null_qualification_bindings,
    )

    log("Null 资格篡改矩阵(全部负面用例必须被拒)...")
    base = build_null_qualification_bindings(full_reports)
    kwargs = _null_verify_kwargs()

    def _case(bindings_mutation=None, payload_mutation=None, rehash=True):
        """bindings_mutation 直接改绑定结构;payload_mutation 改报告
        payload(默认随后重算 hash 保持自洽,模拟攻击者重新打包)。"""
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
                "problem_head": r["problems"][0][:110]
                if r["problems"] else None}

    def _b_only(b):
        b["probe_null_sign"] = {"qualification_pass": True}

    def _no_payload(b):
        b["probe_null_sign"] = {
            "family_version": "x", "qualification_pass": True,
            "report_hash": "nq-" + "0" * 64}

    def _hash_only(b):
        b["probe_null_sign"]["report_hash"] = "nq-" + "9" * 64

    def _fmt_v2(p, b):
        p["format"] = "null-qualification-v2"

    def _fmt_v1(p, b):
        p["format"] = "null-qualification-v1"

    def _verdict_insufficient(p, b):
        p["verdict"] = "INSUFFICIENT_EVIDENCE"
        p["pass"] = False
        b["probe_null_sign"]["qualification_pass"] = False

    def _verdict_illegal(p, b):
        p["verdict"] = "PASS"

    def _pass_verdict_conflict(p, b):
        p["verdict"] = "INSUFFICIENT_EVIDENCE"
        p["pass"] = True  # 与 verdict 自相矛盾

    def _unit_bar(p, b):
        p["bootstrap_unit"] = "bar"

    def _aggr_wrong(p, b):
        p["cluster_aggregation"] = "mean-of-all-episodes"

    def _nclusters_wrong(p, b):
        p["n_clusters"] = 63

    def _truncate_cv(p, b):
        p["always_long_vs_flat"]["cluster_values"] = \
            p["always_long_vs_flat"]["cluster_values"][:32]

    def _params_band_widened(p, b):
        p["qualification_params"]["max_unconditional_long_edge"] = 0.9

    def _seeds_few(p, b):
        p["seeds"] = [11, 22]
        p["distinct_seeds"] = 2

    def _check_false(p, b):
        p["checks"]["always_flat_strong_baseline"] = False

    def _check_missing(p, b):
        del p["checks"]["episode_net_drift_nonexploitable"]

    def _field_extra(p, b):
        p["attacker_note"] = "trust me"

    def _field_missing(p, b):
        del p["verdict"]

    def _impl_stale(p, b):
        p["generator_implementation_hash"] = "gi-stale-" + "5" * 50

    def _fee_changed(p, b):
        p["eval_config_manifest"] = {
            **p["eval_config_manifest"], "fee": 0.0005}

    cases = {
        "bool_only_binding": _case(bindings_mutation=_b_only),
        "missing_report_payload": _case(bindings_mutation=_no_payload),
        "report_hash_tampered": _case(bindings_mutation=_hash_only),
        "format_v2_deprecated": _case(payload_mutation=_fmt_v2),
        "format_v1_deprecated": _case(payload_mutation=_fmt_v1),
        "verdict_insufficient": _case(payload_mutation=_verdict_insufficient),
        "verdict_illegal_value": _case(payload_mutation=_verdict_illegal),
        "pass_verdict_conflict": _case(
            payload_mutation=_pass_verdict_conflict),
        "bootstrap_unit_bar": _case(payload_mutation=_unit_bar),
        "cluster_aggregation_wrong": _case(payload_mutation=_aggr_wrong),
        "n_clusters_inconsistent": _case(payload_mutation=_nclusters_wrong),
        "cluster_values_truncated": _case(payload_mutation=_truncate_cv),
        "params_band_widened": _case(payload_mutation=_params_band_widened),
        "seeds_insufficient": _case(payload_mutation=_seeds_few),
        "required_check_false": _case(payload_mutation=_check_false),
        "required_check_missing": _case(payload_mutation=_check_missing),
        "unrecognized_field": _case(payload_mutation=_field_extra),
        "required_field_missing": _case(payload_mutation=_field_missing),
        "implementation_hash_stale": _case(payload_mutation=_impl_stale),
        "eval_config_fee_changed": _case(payload_mutation=_fee_changed),
    }
    # baseline 必须通过
    baseline = verify_null_qualification_bindings(
        _copy.deepcopy(base), required_families=list(FAMILIES), **kwargs)
    all_rejected = all(c["rejected"] for c in cases.values())
    write_art("null_qualification_tamper_matrix_v3.json", {
        "protocol": "null-qualification-v3",
        "baseline_valid": baseline["pass"],
        "cases": cases,
        "all_negative_cases_rejected": all_rejected,
        "note": ("篡改例均重算报告 hash 保持自洽(模拟重新打包);"
                 "全部必须被完整对账拒绝"),
        "generated_utc": now_iso(),
    })
    assert baseline["pass"] and all_rejected
    log(f"  {len(cases)} 例篡改全部被拒(baseline 通过)")


# --------------------------------------------- 9. 2.6.0c 闭环保留守卫
def stage_2_6_0c_guards(sealed_stage) -> dict:
    import inspect
    import re

    log("2.6.0c 闭环保留守卫(issuer/runtime/反作弊)...")
    import rl_curriculum.formal_exam as fe

    commitment = sealed_stage["commitment"]
    # issuer 信任根 API 面:run_sealed_exam 不得重新出现 issuer 覆盖参数
    from rl_curriculum.formal_exam import run_sealed_exam

    sig = inspect.signature(run_sealed_exam)
    issuer_api_clean = not any(
        p in sig.parameters
        for p in ("trusted_issuer", "issuer", "issuer_payload"))
    src = Path(fe.__file__).read_text(encoding="utf-8")
    guards = {
        "issuer_override_param_absent": issuer_api_clean,
        "no_replication_hardcoded_slice": not re.search(
            r"replication_eps\[:\d+\]", src),
        "commitment_binds_runtime": (
            commitment.candidate_runtime_hash.startswith("rt-")
            or len(commitment.candidate_runtime_hash) > 16),
        "commitment_binds_real_null_reports": all(
            set(b) == {"family_version", "qualification_pass",
                       "report_hash", "report_payload"}
            for b in commitment.null_qualification_bindings.values()),
        "null_reports_all_v3_qualified": all(
            b["report_payload"]["format"] == "null-qualification-v3"
            and b["report_payload"]["verdict"] == "QUALIFIED"
            for b in commitment.null_qualification_bindings.values()),
    }
    write_art("stage2_6_0c_guards_preserved.json", {
        "guards": guards,
        "all_preserved": all(guards.values()),
        "note": ("阶段 2.6.0c 的 issuer 信任根/候选运行时绑定/反作弊"
                 "复制闭环/Null 报告内容绑定必须完整保留;2.6.0d 只改"
                 "资格统计语义"),
        "generated_utc": now_iso(),
    })
    assert all(guards.values()), guards


# ------------------------------------------------------ 10. 上游完整性
def stage_upstream_integrity() -> dict:
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
    assert payload["vendor_clean"]
    assert head == payload["vendor_expected"]
    assert payload["frozen_unchanged"]
    return payload


def main() -> None:
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    t_start = time.time()
    schema = probe_observation_schema()
    cfg = default_eval_config()

    null_stage = stage_null_reports_v3(schema, cfg)
    stage_small_sample_counterexample(schema, cfg)
    stage_economic_equivalence(schema, cfg)
    stage_cluster_unit_audit(schema, cfg, null_stage["reports"])
    issuer_stage = stage_issuer_and_checkpoint(schema)
    sealed_stage = stage_sealed_exam_flow(
        schema, cfg, null_stage, issuer_stage)
    stage_null_tamper_matrix(null_stage["reports"])
    stage_2_6_0c_guards(sealed_stage)
    stage_upstream_integrity()

    log(f"全部阶段完成({time.time() - t_start:.0f}s);artifacts -> {ART}")


if __name__ == "__main__":
    main()
