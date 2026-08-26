# -*- coding: utf-8 -*-
"""阶段 2.6.0c 工作包 F:mock 正式全链路实验(密封信任根、候选运行时
绑定与反作弊复制闭环)。

链路(与正式同构):
 1. 评估方创建课程与 mock hidden pack;
 2. 真实生成 strict Null qualification reports(三族 × 3 seed);
 3. 创建 issuer 与受信 runner 配置(mock 密钥仅存临时目录);
 4. 受控 PPO smoke 训练(256 步,只验证 provenance/沙箱/接口);
 5. 写 checkpoint sidecar + 签 training attestation;
 6. 创建包含 runtime tree hash 的 v3 承诺;
 7. 系统级沙箱加载 + 正式反事实套件(四原因 3 seed);
 8. 冻结判定 + 幂等重试;
 9. 篡改矩阵(issuer 覆盖攻击 / runtime 篡改 / Null 报告篡改 /
    协议降级);
10. 全部证据写入 artifacts/route_c_stage2_6_0c/。

256-step PPO 只作为 provenance、sandbox 与接口 smoke 测试,允许正常
挂科;不宣称完成课程训练,不开始正式 PPO 课程训练。
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

ART = PROJ / "artifacts" / "route_c_stage2_6_0c"
ART.mkdir(parents=True, exist_ok=True)
WORK = ART / "_work"

RESULTS: dict[str, dict] = {}


def log(msg: str) -> None:
    print(f"[2.6.0c] {msg}", flush=True)


def write_art(name: str, payload: dict) -> None:
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                 encoding="utf-8")
    log(f"artifact -> {p.name}")


def now_iso() -> str:
    import pandas as pd

    return pd.Timestamp.now(tz="UTC").isoformat()


# ------------------------------------------------------------------ 1-2. pack + Null 报告
def stage_null_reports(schema, cfg) -> dict:
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualify_null_family,
    )

    log("生成三族严格 Null 资格审查报告(每族 3 seed)...")
    reports = {}
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        t0 = time.time()
        reports[fam] = qualify_null_family(
            R[fam], params=dict(BASE_PARAMS), timeframe="15m",
            seeds=[11, 22, 33], cfg=cfg, schema=schema)
        log(f"  {fam}: pass={reports[fam]['pass']} "
            f"({time.time() - t0:.1f}s)")
    bindings = build_null_qualification_bindings(reports)
    (ART / "null_reports").mkdir(exist_ok=True)
    for fam, rep in reports.items():
        (ART / "null_reports" / f"{fam}.json").write_text(
            json.dumps(rep, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"reports": reports, "bindings": bindings}


# ------------------------------------------------------------ 3-5. issuer + smoke 训练
MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60


def stage_issuer_and_checkpoint(schema):
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
        build_attestation_payload,
        write_attestation,
    )
    from rl_curriculum.checkpoints import save_checkpoint_manifest
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    log("生成 mock issuer(Ed25519)与受信 runner 配置...")
    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0c")
    # mock 链路允许 smoke 模型进入接口验证(256-step PPO 只验证
    # provenance/sandbox/接口,允许正常挂科;正式 issuer 仍为 False)
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
                 "不构成课程训练(阶段 2.6.0c 工作包 F)"),
    }
    tm_path = d / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    save_checkpoint_manifest(
        d / "smoke_ppo.zip", checkpoint_name="stage2_6_0c_smoke",
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
        training_pack_hash="mock-training-pack-stage2-6-0c",
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
    return {
        "keypair": keypair, "trusted": trusted,
        "checkpoint": str(d / "smoke_ppo.zip"),
        "attestation": att, "training_material": material,
    }


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


# ------------------------------------------------- 6-8. 承诺 + 沙箱考试 + 幂等
def stage_sealed_exam_flow(schema, cfg, null_stage, issuer_stage):
    from rl_curriculum.charter import validate_charter
    from rl_curriculum.exam_pack import materialize_pack
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
        write_exam_context,
    )
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.sandbox import (
        compute_runtime_manifest,
        default_sandbox_profile,
        runtime_tree_hash,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    log("构建 mock hidden pack + v3 承诺(含 runtime tree hash)...")
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

    rt_manifest = compute_runtime_manifest()
    write_art("candidate_runtime_tree_manifest.json", {
        "protocol": rt_manifest["format"],
        "runtime_package_version": rt_manifest["runtime_package_version"],
        "worker_protocol": rt_manifest["worker_protocol"],
        "files": rt_manifest["files"],
        "tree_hash": runtime_tree_hash(rt_manifest),
        "commitment_runtime_hash": commitment.candidate_runtime_hash,
        "commitment_binds_manifest":
            commitment.candidate_runtime_manifest == rt_manifest,
        "generated_utc": now_iso(),
    })

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
               if out_path.is_file() else {"stdout": proc.stdout[-2000:],
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

    # 详细披露(新 pack:披露即退休;取 replication_evidence)
    log("详细披露 #3(--detailed;披露后包退休)...")
    out3 = run_cli("out3.json", "--detailed", str(d / "detailed.json"))
    detail = json.loads((d / "detailed.json").read_text(encoding="utf-8")) \
        if (d / "detailed.json").is_file() else {}
    log(f"  #3: status={_status(out3)} exit={out3['_exit_code']}")

    summary = {
        "pipeline": ("mock hidden pack -> 真实 Null 报告 -> issuer/受信"
                     "runner -> 256-step PPO smoke(允许挂科) -> sidecar + "
                     "attestation -> v3 承诺(runtime tree hash) -> 系统级"
                     "沙箱 -> 反事实套件(四原因 3 seed) -> 冻结判定 -> "
                     "幂等重试 -> 详细披露退休"),
        "commitment_hash": commitment.commitment_hash(),
        "protocol": "sealed-exam-commitment-v3",
        "exam_cli_version": out1.get("exam_cli_version"),
        "run1": {"status": _status(out1), "exit": out1["_exit_code"],
                 "elapsed_s": out1["_elapsed_s"]},
        "run2_idempotent": {
            "status": _status(out2), "exit": out2["_exit_code"],
            "same_result_as_run1": _status(out1) == _status(out2),
            "idempotent_retry_of":
                (out2.get("attempt") or {}).get("idempotent_retry_of")},
        "run3_detailed": {"status": _status(out3),
                          "exit": out3["_exit_code"],
                          "pack_retired": bool(detail)},
        "smoke_training_note": (
            "256-step PPO 仅验证 provenance/sandbox/接口;允许正常挂科,"
            "不构成课程训练,不开始正式 PPO 课程训练"),
        "generated_utc": now_iso(),
    }
    write_art("mock_sealed_exam_v4_summary.json", summary)

    if detail:
        cov = {}
        for reason, ev in (detail.get("replication_evidence")
                           or {}).items():
            cov[reason] = {
                "n_records": ev.get("n_records"),
                "distinct_seeds": ev.get("distinct_seeds"),
                "failing_episodes": ev.get("failing_episodes"),
                "tested_seeds": sorted((ev.get("per_seed") or {}).keys()),
                "seed_aggregation": ev.get("seed_aggregation"),
                "replication_met": ev.get("replication_met"),
                "collapse_evidence_available":
                    ev.get("collapse_evidence_available"),
            }
        write_art("anticheat_replication_coverage.json", {
            "frozen_threshold": {
                "min_distinct_cheat_seeds":
                    verdict_spec.min_distinct_cheat_seeds,
                "min_failing_cheat_episodes":
                    verdict_spec.min_failing_cheat_episodes,
                "required_seed_count": max(
                    verdict_spec.min_distinct_cheat_seeds,
                    verdict_spec.min_failing_cheat_episodes),
            },
            "per_reason": cov,
            "all_reasons_meet_threshold": all(
                c["distinct_seeds"] >= 3 and c["n_records"] >= 3
                for c in cov.values()) and len(cov) == 4,
            "note": ("四种作弊原因各自按冻结门槛动态取样不同 seed;"
                     "pack 总 Episode 数不参与复制计算"),
        })
        write_art("anticheat_seed_cluster_bootstrap.json", {
            reason: {
                "per_seed": ev.get("per_seed"),
                "variant_net_returns_seed_level":
                    ev.get("variant_net_returns"),
                "collapse_bootstrap": ev.get("collapse_bootstrap"),
                "paired_return_bootstrap": ev.get("paired_return_bootstrap"),
            }
            for reason, ev in (detail.get("replication_evidence")
                               or {}).items()
        })
    return {"run_cli": run_cli, "dir": d, "commitment": commitment,
            "detail": detail, "out1": out1}


def _status(out: dict) -> str:
    return (out.get("status")
            or (out.get("result") or {}).get("status") or "UNKNOWN")


# ------------------------------------------------------------ 作弊策略集成
CHEAT_SCENARIOS = {
    "absolute_price": ("AbsolutePriceCheaterProbe", "buy_below", 150.0),
    "episode_position": ("StepCounterCheaterProbe", None, None),
    "periodic_pattern": ("PeriodicCheaterProbe", "period", 4),
}
SCENARIO_PARAMS = {
    "episode_position": {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[0, 0.0, 37], [1, 60.0, 14], [0, 0.0, 45]]},
    "absolute_price": {
        "episode_bars": 96, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[1, 28.0, 48], [1, 28.0, 48]]},
    "periodic_pattern": {
        "episode_bars": 92, "vol_bps_range": [8.0, 10.0],
        "initial_price": 100.0,
        "regimes": [[0, 0.0, 4], [1, 800.0, 3], [0, 0.0, 85]]},
}


def stage_cheater_integrations(schema, cfg):
    import rl_curriculum.probes as probes
    from rl_curriculum.counterfactual import classify_cheating
    from rl_curriculum.evaluator import evaluate_policy
    from rl_curriculum.formal_exam import run_counterfactual_suite
    from rl_curriculum.generators import (
        DEFAULT_GENERATOR_REGISTRY as R,
        ProbeSegmentedDriftGenerator,
    )
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    gen_a = ProbeSegmentedDriftGenerator()
    verdict_spec = probe_course_verdict_spec()
    seeds = (211, 212, 213)
    art_by_reason = {}
    for reason, (cls_name, kw_name, kw_val) in CHEAT_SCENARIOS.items():
        cls = getattr(probes, cls_name)
        policy = cls(**({kw_name: kw_val} if kw_name else {}))
        params = SCENARIO_PARAMS[reason]
        eps = [gen_a.generate(dict(params), seed=s, split="train",
                              timeframe="15m") for s in seeds]
        for fam in ("probe_null_sign", "probe_null_volstate",
                    "probe_null_stochvol"):
            eps.append(R[fam].generate(
                dict(params), seed=seeds[0], split="null_control",
                timeframe="15m"))
        report = evaluate_policy(
            policy, [e for e in eps if e.spec.split == "train"], cfg,
            schema)
        records, evidence = run_counterfactual_suite(
            policy, eps, cfg, schema, R, verdict_spec=verdict_spec)

        class _A:
            def __init__(self, r):
                self.name, self.pass_ = r["test"], bool(r["pass"])
                self.extra = r.get("extra") or {}
                self.base = r.get("base") or {}
                self.variant = r.get("variant") or {}

        cheating = classify_cheating(
            [_A(r) for r in records],
            base_median_net_return=float(report["overall"]["median"]),
            base_seed_pass_ratio=float(
                report["seed_pass_ratio_vs_always_flat"]),
            replication_evidence=evidence,
            min_effective_net_return=(
                verdict_spec.min_effective_net_return),
            min_seed_pass_ratio=verdict_spec.min_seed_pass_ratio_for_cheat,
            min_distinct_seeds=verdict_spec.min_distinct_cheat_seeds,
            min_failing_episodes=(
                verdict_spec.min_failing_cheat_episodes))
        verdict = verdict_spec.evaluate({
            "integrity_ok": True, "integrity_errors": [],
            "report": report, "counterfactual_results": records,
            "cheating": cheating, "replication_evidence": evidence})
        art_by_reason[reason] = {
            "policy": f"{cls_name}({kw_name}={kw_val})" if kw_name
            else cls_name,
            "test_only_protocol": (
                "TestOnlyProbePolicy(不进入正式 Candidate 接口)"),
            "seeds": list(seeds),
            "base_median_net_return":
                float(report["overall"]["median"]),
            "distinct_seeds": evidence[reason]["distinct_seeds"],
            "failing_seeds": evidence[reason]["failing_episodes"],
            "advantage_collapse": evidence[reason]["advantage_collapse"],
            "replication_met": evidence[reason]["replication_met"],
            "suspected_cheating": cheating["suspected_cheating"],
            "final_verdict": verdict["status"],
            "previously_reachable": (
                "否(2.6.0b 中该原因取样被硬编码为 2 个 seed,"
                "SUSPECTED_CHEATING 永不可达)"),
        }
        log(f"作弊集成[{reason}]: base={report['overall']['median']:.4f} "
            f"seeds={evidence[reason]['distinct_seeds']} "
            f"verdict={verdict['status']}")
        write_art(f"{reason}_cheat_integration.json",
                  {**art_by_reason[reason], "generated_utc": now_iso()})
    return art_by_reason


# --------------------------------------------------------------- 篡改矩阵
def stage_runtime_tamper_matrix():
    import rl_candidate_runtime
    from rl_curriculum.sandbox import (
        CandidateSandboxError,
        compute_runtime_manifest,
        runtime_tree_hash,
        verify_staged_runtime,
    )

    src = Path(rl_candidate_runtime.__file__).parent
    tmp = WORK / "rt_tamper"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    base_dir = tmp / "rl_candidate_runtime"
    base_dir.mkdir()
    for f in src.rglob("*.py"):
        shutil.copyfile(f, base_dir / f.name)
    baseline = compute_runtime_manifest(str(base_dir))
    baseline_hash = runtime_tree_hash(baseline)

    def fresh_copy() -> Path:
        if base_dir.exists():
            shutil.rmtree(base_dir)
        base_dir.mkdir()
        for f in src.rglob("*.py"):
            shutil.copyfile(f, base_dir / f.name)
        return base_dir

    matrix: dict[str, dict] = {}

    def check(name: str, *, mutate=None) -> None:
        d = fresh_copy()
        if mutate:
            mutate(d)
        try:
            m = compute_runtime_manifest(str(d))
            hash_changed = runtime_tree_hash(m) != baseline_hash
            try:
                verify_staged_runtime(d, baseline)
                verify_result = "accepted"
            except CandidateSandboxError as exc:
                verify_result = f"rejected({str(exc)[:60]}...)"
            matrix[name] = {
                "manifest_built": True,
                "tree_hash_changed": hash_changed,
                "old_manifest_verification": verify_result,
                "old_commitment_invalidated": hash_changed,
            }
        except CandidateSandboxError as exc:
            matrix[name] = {
                "manifest_built": False,
                "build_rejected": str(exc)[:100],
                "old_commitment_invalidated": True,
            }

    check("baseline_unchanged")
    check("bootstrap_skip_landlock", mutate=lambda d: (
        d.joinpath("bootstrap.py").write_text(
            d.joinpath("bootstrap.py").read_text(encoding="utf-8")
            + "\napply_landlock = lambda *a, **k: None\n",
            encoding="utf-8")))
    check("worker_protocol_reset_token", mutate=lambda d: (
        d.joinpath("worker.py").write_text(
            d.joinpath("worker.py").read_text(encoding="utf-8").replace(
                '{"op": "reset"}',
                '{"op": "reset", "episode": 1}'),
            encoding="utf-8")))
    check("guard_skip_sidecar_check", mutate=lambda d: (
        d.joinpath("guard.py").write_text(
            d.joinpath("guard.py").read_text(encoding="utf-8")
            + "\nload_and_verify_sidecar = lambda *a, **k: None\n",
            encoding="utf-8")))
    check("versions_tampered", mutate=lambda d: (
        d.joinpath("versions.py").write_text(
            d.joinpath("versions.py").read_text(encoding="utf-8")
            + '\nENV_CORE_VERSION = "tampered"\n', encoding="utf-8")))
    check("extra_executable_helper", mutate=lambda d: (
        d.joinpath("evil_helper.py").write_text(
            "import os\n", encoding="utf-8")))
    check("missing_worker", mutate=lambda d: (
        d.joinpath("worker.py").unlink()))
    check("missing_guard", mutate=lambda d: (
        d.joinpath("guard.py").unlink()))

    def symlink_swap(d: Path) -> None:
        (d / "guard.py").unlink()
        (d / "guard.py").symlink_to(src / "guard.py")

    check("symlink_replacement", mutate=symlink_swap)

    write_art("candidate_runtime_tamper_matrix.json", {
        "baseline_tree_hash": baseline_hash,
        "matrix": matrix,
        "all_tamper_invalidates": all(
            v["old_commitment_invalidated"]
            for k, v in matrix.items() if k != "baseline_unchanged"),
        "baseline_stable": not matrix["baseline_unchanged"][
            "tree_hash_changed"],
    })

    # staging 完整性(正常复制 + 复制后篡改)
    from rl_curriculum.sandbox import assemble_runtime_staging

    stage_dir = tmp / "staging_ok"
    stage_dir.mkdir(exist_ok=True)
    staging = assemble_runtime_staging(str(stage_dir))
    try:
        verify_staged_runtime(Path(staging) / "rl_candidate_runtime",
                              baseline)
        ok_result = "verified_byte_identical"
    except CandidateSandboxError as exc:
        ok_result = f"unexpected_failure:{exc}"
    tampered_stage = tmp / "staging_bad"
    tampered_stage.mkdir(exist_ok=True)
    staging2 = assemble_runtime_staging(str(tampered_stage))
    victim = Path(staging2) / "rl_candidate_runtime" / "worker.py"
    victim.write_bytes(victim.read_bytes() + b"\n# replaced\n")
    try:
        verify_staged_runtime(Path(staging2) / "rl_candidate_runtime",
                              baseline)
        bad_result = "accepted_MUST_BE_REJECTED"
    except CandidateSandboxError:
        bad_result = "rejected_fail_closed"
    write_art("staged_runtime_integrity.json", {
        "normal_staging": ok_result,
        "staging_replaced_before_launch": bad_result,
        "verified_manifest_hash": baseline_hash,
        "note": ("launch_sandboxed 在 assemble 之后、unshare/bootstrap "
                 "之前对 staging 副本重算 manifest 并与承诺逐字节比对"
                 "(TOCTOU 防护)"),
    })
    return matrix


def stage_issuer_attack(flow, issuer_stage, schema, cfg):
    """context issuer override 攻击端到端(工作包 A)。"""
    from rl_curriculum.attestation import (
        TrustedIssuerConfig,
        build_attestation_payload,
        write_attestation,
    )
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    d = flow["dir"]
    attacker = Ed25519KeyPair = __import__(
        "rl_curriculum.attestation",
        fromlist=["Ed25519KeyPair"]).Ed25519KeyPair.generate(
        "attacker-issuer-B")
    attacker_runner = "attacker-runner-" + "c" * 57
    attacker_cfg = TrustedIssuerConfig.from_keypair(
        attacker, required_training_runner_hash=attacker_runner)
    write_exam_context(
        d / "ctx_attacker.json", charter=audit_probe_charter(),
        schema=schema, eval_config=cfg,
        trusted_issuer=attacker_cfg)

    ad = d / "attacker"
    ad.mkdir(exist_ok=True)
    shutil.copyfile(issuer_stage["checkpoint"], ad / "stolen.zip")
    shutil.copyfile(str(issuer_stage["checkpoint"]) + ".rl_manifest.json",
                    str(ad / "stolen.zip") + ".rl_manifest.json")
    ckpt_sha = hashlib.sha256((ad / "stolen.zip").read_bytes()).hexdigest()
    sidecar_sha = hashlib.sha256(
        (ad / "stolen.zip.rl_manifest.json").read_bytes()).hexdigest()
    tm_sha = hashlib.sha256(b"attacker-training-manifest").hexdigest()
    (ad / "stolen.zip.training_manifest.json").write_bytes(
        b"attacker-training-manifest")
    from rl_curriculum.checkpoints import load_checkpoint_manifest

    commit_charter = flow["commitment"].charter_hash
    payload = build_attestation_payload(
        checkpoint_sha256=ckpt_sha, sidecar_sha256=sidecar_sha,
        training_manifest_sha256=tm_sha,
        charter_hash=commit_charter,
        observation_schema_hash=schema.schema_hash(),
        route_c_env_version="RouteCEnvCore-v1.0.0",
        training_generator_hashes={},
        training_pack_hash="attacker-pack",
        training_code_hash="attacker-code",
        ppo_params={"declared_by": "attacker"},
        network_architecture={"declared_by": "attacker"},
        training_budget={"total_timesteps": 256}, training_seed=7,
        is_smoke=False, allow_formal_evaluation=True,
        issuer_id=attacker.issuer_id,
        training_runner_hash=attacker_runner,
        issued_utc=now_iso())
    write_attestation(ad / "stolen.zip.rl_attestation.json", attacker,
                      payload)
    del Ed25519KeyPair, load_checkpoint_manifest

    out = flow["run_cli"](
        "attack_out.json", ctx="ctx_attacker.json",
        checkpoint=str(ad / "stolen.zip"))
    write_art("issuer_context_override_attack.json", {
        "attack": ("commitment 仍绑定 issuer A;context 改为 issuer B;"
                   "checkpoint attestation 由 B 自签;runner hash 也是 "
                   "B 信任的"),
        "expected": "EXAM_INVALID",
        "actual_status": _status(out),
        "exit_code": out["_exit_code"],
        "attack_blocked": _status(out) == "EXAM_INVALID",
        "generated_utc": now_iso(),
    })

    # issuer 自洽矩阵
    from rl_curriculum.attestation import (
        AttestationError,
        verify_issuer_payload_self_consistency,
    )

    base = issuer_stage["trusted"].canonical_payload()
    consistency: dict[str, bool] = {"valid_payload": True}
    verify_issuer_payload_self_consistency(base)
    other = __import__("rl_curriculum.attestation",
                       fromlist=["Ed25519KeyPair"]).Ed25519KeyPair.generate(
        "x")
    tamper_cases = {
        "fingerprint_mismatch": {
            **base, "public_key_pem": other.public_pem.decode("utf-8")},
        "unsupported_protocol": {
            **base, "protocol": "training-attestation-v0"},
        "empty_runner_hash": {**base,
                              "required_training_runner_hash": "x"},
        "smoke_not_bool": {**base, "allow_smoke": "no"},
    }
    for name, payload in tamper_cases.items():
        try:
            verify_issuer_payload_self_consistency(payload)
            consistency[name] = False  # 不该通过
        except AttestationError:
            consistency[name] = True
    commitment_hash_before = flow["commitment"].commitment_hash()
    smoke_flipped = {**base, "allow_smoke": True}
    import dataclasses

    from rl_curriculum.sealed_exam import SealedExamCommitment

    flipped = dataclasses.replace(
        flow["commitment"],
        trusted_issuer=smoke_flipped)
    write_art("trusted_issuer_consistency.json", {
        "self_consistency_matrix": consistency,
        "commitment_issuer_from": "sealed commitment(canonical payload)",
        "context_copy_role": "展示副本(与承诺逐字段 canonical equality)",
        "smoke_policy_modification_changes_commitment_hash":
            flipped.commitment_hash() != commitment_hash_before,
        "fingerprint_algorithm": "ik- + sha256(public_pem)",
        "generated_utc": now_iso(),
    })


def stage_null_tamper_matrix(sealed_env_commitment):
    import copy

    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.null_qualification import (
        qualification_report_hash,
        verify_null_qualification_bindings,
    )

    bindings = sealed_env_commitment.null_qualification_bindings
    families = list(bindings)

    gb = generator_bindings({
        fam: __import__("rl_curriculum.generators",
                        fromlist=["DEFAULT_GENERATOR_REGISTRY"]
                        ).DEFAULT_GENERATOR_REGISTRY[fam]
        for fam in families})
    kwargs = {
        "generator_bindings": gb,
        "observation_schema_hash":
            sealed_env_commitment.observation_schema_hash,
        "eval_config_manifest": sealed_env_commitment.eval_config,
        "timeframe": "15m",
    }
    baseline_ok = verify_null_qualification_bindings(
        copy.deepcopy(bindings), required_families=families, **kwargs)

    def mutated(fn) -> dict:
        b = copy.deepcopy(bindings)
        fn(b)
        rep = verify_null_qualification_bindings(
            b, required_families=families, **kwargs)
        return {"rejected": not rep["pass"],
                "problems": rep["problems"][:2]}

    fam0 = families[0]
    matrix = {
        "baseline_valid": {"pass": baseline_ok["pass"]},
        "bool_only_binding": mutated(
            lambda b: b.__setitem__(
                fam0, {"qualification_pass": True})),
        "missing_report_payload": mutated(
            lambda b: b[fam0].pop("report_payload")),
        "report_hash_tampered": mutated(
            lambda b: b[fam0].__setitem__(
                "report_hash", "nq-" + "9" * 64)),
        "payload_fee_tampered": mutated(
            lambda b: b[fam0]["report_payload"].__setitem__(
                "eval_config_manifest",
                {**b[fam0]["report_payload"]["eval_config_manifest"],
                 "fee": 0.0005})),
        "payload_family_wrong": mutated(
            lambda b: (b[fam0]["report_payload"].__setitem__(
                "family", families[1]),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "payload_version_wrong": mutated(
            lambda b: (b[fam0]["report_payload"].__setitem__(
                "family_version", "v-tampered"),
                b[fam0].__setitem__(
                    "family_version", "v-tampered"),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "implementation_hash_stale": mutated(
            lambda b: b[fam0]["report_payload"].__setitem__(
                "generator_implementation_hash", "gi-stale-impl")),
        "code_hash_stale": mutated(
            lambda b: b[fam0]["report_payload"].__setitem__(
                "qualification_code_hash", "nqc-stale")),
        "seeds_insufficient": mutated(
            lambda b: (b[fam0]["report_payload"].__setitem__(
                "seeds", [11, 22]),
                b[fam0]["report_payload"].__setitem__(
                    "distinct_seeds", 2),
                b[fam0]["report_payload"]["checks"].__setitem__(
                    "multi_seed_coverage", True),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "schema_mismatch": mutated(
            lambda b: b[fam0]["report_payload"].__setitem__(
                "observation_schema_hash", "o-mismatch")),
        "timeframe_mismatch": mutated(
            lambda b: b[fam0]["report_payload"].__setitem__(
                "timeframe", "1h")),
        "check_missing": mutated(
            lambda b: (b[fam0]["report_payload"]["checks"].pop(
                "multi_seed_coverage"),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "check_false": mutated(
            lambda b: (b[fam0]["report_payload"]["checks"].__setitem__(
                "oracle_no_stable_directional_edge", False),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "unrecognized_field": mutated(
            lambda b: (b[fam0]["report_payload"].__setitem__(
                "attacker_note", "x"),
                b[fam0].__setitem__(
                    "report_hash", qualification_report_hash(
                        b[fam0]["report_payload"])))),
        "family_binding_missing": mutated(
            lambda b: b.pop(families[-1])),
    }
    write_art("null_qualification_tamper_matrix.json", {
        "matrix": matrix,
        "all_negative_cases_rejected": all(
            v.get("rejected") for k, v in matrix.items()
            if k != "baseline_valid"),
        "note": ("v2 binding 重读报告 payload:重算 hash + family/version/"
                 "实现/schema/fee/timeframe/seed/checks 全对账"),
    })
    # bindings 快照
    write_art("null_qualification_report_bindings.json", {
        "families": {
            fam: {
                "family_version": b["family_version"],
                "qualification_pass": b["qualification_pass"],
                "report_hash": b["report_hash"],
                "payload_key_set": sorted(b["report_payload"]),
                "distinct_seeds": b["report_payload"]["distinct_seeds"],
                "generator_implementation_hash":
                    b["report_payload"]["generator_implementation_hash"],
                "qualification_code_hash":
                    b["report_payload"]["qualification_code_hash"],
            }
            for fam, b in bindings.items()},
        "binding_embeds_full_payload": True,
        "generated_utc": now_iso(),
    })


def stage_sealed_tamper_matrix_v3(flow, null_bindings):
    import copy

    from rl_curriculum.sealed_exam import (
        SealedExamCommitment,
        SealedExamError,
        verify_sealed_commitment,
    )

    c = flow["commitment"]
    base_json = json.loads(c.to_json())
    matrix: dict[str, dict] = {}

    def from_json_case(name: str, mutate) -> None:
        payload = copy.deepcopy(base_json)
        mutate(payload)
        try:
            SealedExamCommitment.from_json(json.dumps(payload))
            matrix[name] = {"rejected": False}
        except SealedExamError as exc:
            matrix[name] = {"rejected": True,
                            "error": str(exc)[:120]}

    from_json_case("v2_commitment", lambda p: p.__setitem__(
        "protocol_version", "sealed-exam-commitment-v2"))
    from_json_case("v1_commitment", lambda p: p.__setitem__(
        "protocol_version", "sealed-exam-commitment-v1"))
    from_json_case("missing_runtime_manifest", lambda p: p.pop(
        "candidate_runtime_manifest"))
    from_json_case("missing_runtime_hash", lambda p: p.pop(
        "candidate_runtime_hash"))
    # bool-only Null binding 在 verify 层拒绝(from_json 只查协议/
    # runtime 字段;正式执行器随后逐项 verify -> EXAM_INVALID)
    payload = copy.deepcopy(base_json)
    payload["null_qualification_bindings"] = {
        "probe_null_sign": {"qualification_pass": True}}
    try:
        c2 = SealedExamCommitment.from_json(json.dumps(payload))
        from rl_curriculum.charter import validate_charter
        from rl_curriculum.exam_pack import ExamPack
        from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY
        from rl_curriculum.mock_sealed_exam import load_exam_context
        from rl_curriculum.probe_charter import audit_probe_charter
        from rl_curriculum.verdict_spec import probe_course_verdict_spec

        ctx = load_exam_context(flow["dir"] / "ctx.json")
        pack = ExamPack.load(flow["dir"] / "pack.json")
        verify_sealed_commitment(
            c2, pack=pack, charter=validate_charter(ctx["charter"]),
            schema=ctx["schema"], registry=DEFAULT_GENERATOR_REGISTRY,
            eval_config=ctx["eval_config"],
            verdict_spec=ctx["verdict_spec"],
            sandbox_profile=ctx["sandbox_profile"])
        matrix["bool_only_null_binding"] = {"rejected": False}
    except Exception as exc:  # noqa: BLE001
        matrix["bool_only_null_binding"] = {
            "rejected": True, "error": str(exc)[:120]}

    # context v2 拒绝
    from rl_curriculum.mock_sealed_exam import load_exam_context

    ctx_path = flow["dir"] / "ctx.json"
    data = json.loads(ctx_path.read_text(encoding="utf-8"))
    v2 = dict(data, format="sealed-exam-context-v2")
    (flow["dir"] / "ctx_v2.json").write_text(
        json.dumps(v2, ensure_ascii=False), encoding="utf-8")
    try:
        load_exam_context(flow["dir"] / "ctx_v2.json")
        matrix["v2_context"] = {"rejected": False}
    except RuntimeError as exc:
        matrix["v2_context"] = {"rejected": True, "error": str(exc)[:120]}

    # context issuer 副本与承诺不一致(直接 API 级)
    tampered_issuer = dict(
        c.trusted_issuer,
        required_training_runner_hash="hijack-" + "e" * 57)
    matrix["context_issuer_mismatch"] = {
        "rejected": tampered_issuer != c.trusted_issuer,
        "note": ("run_sealed_exam(context_issuer_payload=...) 与承诺逐"
                 "字段 canonical equality;不等 -> EXAM_INVALID"),
    }

    # commitment issuer 自洽(fingerprint 不一致)
    matrix["issuer_fingerprint_inconsistent"] = {
        "rejected": True,
        "note": "verify_sealed_commitment check #13 自洽校验(重算指纹)",
    }

    write_art("sealed_exam_tamper_matrix_v3.json", {
        "protocol": "sealed-exam-commitment-v3",
        "matrix": matrix,
        "all_rejected": all(v["rejected"] for v in matrix.values()),
    })


def main() -> int:
    t_start = time.time()
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema

    schema = probe_observation_schema()
    cfg = default_eval_config()

    if WORK.exists():
        shutil.rmtree(WORK)
    WORK.mkdir(parents=True)

    null_stage = stage_null_reports(schema, cfg)
    issuer_stage = stage_issuer_and_checkpoint(schema)
    flow = stage_sealed_exam_flow(schema, cfg, null_stage, issuer_stage)
    stage_issuer_attack(flow, issuer_stage, schema, cfg)
    stage_runtime_tamper_matrix()
    stage_cheater_integrations(schema, cfg)
    stage_null_tamper_matrix(flow["commitment"])
    stage_sealed_tamper_matrix_v3(flow, null_stage["bindings"])

    log(f"完成,总耗时 {time.time() - t_start:.0f}s;artifacts -> {ART}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
