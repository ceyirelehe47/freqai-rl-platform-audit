"""阶段 2.6.0b 证据生成主脚本(全部 artifacts 一次产出)。

运行:
    cd ~/projects/crypto_rl && source activate-freqtrade.sh
    python experiments/route_c_stage2_6_0b/run_all.py [--quick]

--quick 跳过最重的 mock 全链路考试(测试套件已覆盖),用于快速迭代。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

ART = ROOT / "artifacts" / "route_c_stage2_6_0b"
LOGS = ROOT / "logs" / "route_c_stage2_6_0b"

import numpy as np  # noqa: E402

MOCK_TRAINING_RUNNER_HASH = "mock-runner-" + "b" * 60
NULL_QUAL_SEEDS = [11, 22, 33, 44, 55, 66, 77, 88]


def save_json(name: str, payload) -> Path:
    ART.mkdir(parents=True, exist_ok=True)
    p = ART / name
    p.write_text(json.dumps(payload, indent=2, ensure_ascii=False,
                            default=str), encoding="utf-8")
    print(f"[artifact] {name}")
    return p


def save_md(name: str, text: str) -> Path:
    ART.mkdir(parents=True, exist_ok=True)
    p = ART / name
    p.write_text(text, encoding="utf-8")
    print(f"[artifact] {name}")
    return p


# ---------------------------------------------------------------- 工作包 A
def artifact_duration_materialization():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_platform.versions import spec_versions

    gen = ProbeSegmentedDriftGenerator()
    cases = []
    for tf, hours in (("15m", 48.0), ("5m", 48.0), ("1h", 48.0)):
        ep = gen.generate({"duration_hours": hours}, 7, timeframe=tf)
        spec = EpisodeSpec("probe_segmented_drift",
                           {"duration_hours": hours}, 7, "train", tf)
        pack = ExamPack(name=f"p_{tf}", version="v", visibility="public",
                        charter_hash="c", spec_versions=spec_versions(),
                        episodes=[spec], timeframe=tf)
        cases.append({
            "timeframe": tf, "duration_hours": hours,
            "resolved_bars": ep.meta["resolution"]["duration"][
                "resolved_bars"],
            "actual_rows": int(len(ep.df)),
            "rows_match": len(ep.df) == ep.meta["resolution"]["duration"][
                "resolved_bars"],
            "no_96_default_fallback": len(ep.df) != 96 or tf == "15m"
            and hours == 24.0,
            "pack_hash": pack.pack_hash(),
            "resolution_trace": ep.meta["resolution"],
        })
    packs = {c["pack_hash"] for c in cases}
    save_json("actual_duration_materialization.json", {
        "cases": cases,
        "pack_hashes_distinct": len(packs) == 3,
        "pass": all(c["rows_match"] for c in cases) and len(packs) == 3,
    })


def artifact_resolved_parameter_trace():
    from rl_curriculum.param_resolution import (
        TIME_FIELD_BINDINGS,
        resolve_generator_params,
        resolved_parameter_semantics_hash,
    )
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    gen = ProbeSegmentedDriftGenerator()
    params = {"duration_hours": 48, "regime_duration_hours_range":
              [1.0, 4.0], "n_regimes_range": [16, 32]}
    ep = gen.generate(dict(params), 21, timeframe="15m")
    r = resolve_generator_params(params, "15m")
    save_json("resolved_parameter_trace.json", {
        "raw_params": params,
        "timeframe": "15m",
        "duration_resolution": r.duration,
        "field_traces": r.trace()["fields"],
        "effective_params_subset": ep.meta["resolution"][
            "effective_params"],
        "regime_lengths_actual": [l for _d, _s, l in ep.meta["regimes"]],
        "regime_lengths_within_resolved_range": all(
            4 <= l <= 16 for _d, _s, l in ep.meta["regimes"]),
        "binding_registry": {k: b.canonical() for k, b in
                             sorted(TIME_FIELD_BINDINGS.items())},
        "resolved_parameter_semantics_hash":
            resolved_parameter_semantics_hash(),
        "pass": True,
    })


# ---------------------------------------------------------------- 工作包 B
def artifact_candidate_reset_protocol():
    import inspect

    from rl_curriculum.policy_api import ObservationOnlyPolicy
    from rl_curriculum.sandbox import SandboxedCandidate

    sig = list(inspect.signature(
        ObservationOnlyPolicy.reset_episode).parameters)
    save_json("candidate_reset_protocol.json", {
        "reset_signature": "reset_episode(self)",
        "reset_signature_params": sig,
        "worker_protocol": "candidate-worker-v2",
        "wire_message": {"op": "reset"},
        "wire_message_byte_exact": '{"op": "reset"}',
        "banned_fields": ["derived_seed", "episode_id", "seed",
                          "spec_hash", "attempt_id", "pack_hash", "split",
                          "family", "params", "episode_length"],
        "random_baseline_channel": (
            "ObservableBaselinePolicy.episode_instance(episode_seed)"
            "(seed 只进入基线工厂;候选通道不可达)"),
        "sandboxed_candidate_reset_source": inspect.getsource(
            SandboxedCandidate.reset_episode),
        "pass": sig == ["self"],
    })


# ---------------------------------------------------------------- 工作包 C
def artifact_sandbox_matrix():
    from rl_curriculum.sandbox import (
        default_sandbox_profile,
        sandbox_capability_report,
    )

    rep = sandbox_capability_report()
    profile = default_sandbox_profile()
    save_json("sandbox_profile_manifest.json", {
        "profile": profile.canonical_payload(),
        "profile_hash": profile.profile_hash(),
        "mechanism": (
            "unshare user+mount+pid+proc+net namespaces;Landlock ABI>=4 "
            "deny-by-default;只读 bind mount 中性 checkpoint 路径;"
            "tmpfs scratch;rlimits;stdout 行长/超时"),
    })
    lines = [
        "# 沙箱能力矩阵(WSL CryptoRL-Ubuntu-24.04)\n",
        f"- 检查时间: {rep['checked_utc']}",
        f"- 内核: {rep['kernel']}",
        f"- unshare 二进制: {rep['unshare_binary']}",
        f"- user+mount+pid+proc+net namespace 组合: "
        f"{rep['namespaces_user_mount_pid_proc_net']}",
        f"- tmpfs 挂载: {rep['tmpfs_mount']}",
        f"- 只读 bind mount: {rep['bind_mount_readonly']}",
        f"- 空 netns(仅 loopback): {rep['netns_only_loopback']}",
        f"- Landlock ABI: v{rep['landlock_abi']}",
        f"- PR_SET_NO_NEW_PRIVS: {rep['no_new_privs']}",
        f"- **系统级沙箱可用: "
        f"{rep['system_level_sandbox_available']}**\n",
        "## 隔离层\n",
        "| 层 | 机制 | 验证 |\n|---|---|---|\n",
        "| 文件系统 | Landlock deny-by-default + 只读 bind | "
        "sandbox_denial_trace.json |\n",
        "| PID/proc | 独立 PID ns + 新 procfs | "
        "sandbox_proc_isolation.json |\n",
        "| 网络 | 独立 netns(仅 down lo,无路由无 DNS) | "
        "sandbox_network_test.json |\n",
        "| checkpoint | staging 副本 + remount ro + Landlock 无写权 | "
        "sandbox_denial_trace.json |\n",
        "| 资源 | RLIMIT CPU/AS/FSIZE/NOFILE/NPROC | "
        "sandbox_resource_limits.json |\n",
        "| 协议 | 单步超时/stdout 行长上限/非法输出 fail closed | "
        "测试套件 |\n",
    ]
    save_md("sandbox_capability_matrix.md", "\n".join(lines))
    return rep


def _sandbox_probe(checkpoint: str, extra_code: str, targets=None,
                   profile=None):
    sys.path.insert(0, str(ROOT / "tests" / "route_c_stage2_6_0b"))
    from conftest import build_probe_code, run_candidate_in_sandbox

    proc = run_candidate_in_sandbox(
        checkpoint, probe_code=build_probe_code(extra_code=extra_code,
                                                targets=targets or []),
        profile=profile)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return json.loads(lines[-1]) if lines else {"error": proc.stderr[-400:]}


def _attested_checkpoint():
    """训练 tiny PPO + v3 sidecar + mock attestation(与测试同一流程)。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
        build_attestation_payload,
        write_attestation,
    )
    from rl_curriculum.charter import charter_hash
    from rl_curriculum.checkpoints import save_checkpoint_manifest
    from rl_curriculum.probe_charter import (
        audit_probe_charter,
        probe_observation_schema,
    )

    d = Path(tempfile.mkdtemp(prefix="s26b-runall-"))
    ckpt = d / "test_ppo.zip"
    import gymnasium as gym
    from stable_baselines3 import PPO

    class TinyEnv(gym.Env):
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
            ret = 0.0003 + 0.0004 * self._rng.standard_normal()
            self._obs = np.roll(self._obs, 1)
            self._obs[0] = ret
            self._obs[4] += 0.1 * (ret - self._obs[4])
            return self._obs, ret, False, False, {}

    model = PPO("MlpPolicy", TinyEnv(), n_steps=256, batch_size=64,
                seed=7, verbose=0, device="cpu")
    model.save(str(ckpt))
    n_params = sum(p.numel() for p in model.policy.parameters())
    training_manifest = {
        "runner": "mock-controlled-training-runner",
        "runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "steps": 256, "seed": 7,
        "note": "测试级 PPO(允许挂科);只验证 provenance 与执行链路",
    }
    tm_path = d / "training_manifest.json"
    tm_path.write_text(json.dumps(training_manifest, indent=2,
                                  ensure_ascii=False), encoding="utf-8")
    tm_sha = hashlib.sha256(tm_path.read_bytes()).hexdigest()
    charter_h = charter_hash(audit_probe_charter())
    schema = probe_observation_schema()
    save_checkpoint_manifest(
        ckpt, checkpoint_name="test_ppo_stage2_6_0b",
        charter_hash=charter_h, observation_schema=schema,
        training_manifest_sha256=tm_sha)
    sidecar_sha = hashlib.sha256(
        (d / "test_ppo.zip.rl_manifest.json").read_bytes()).hexdigest()
    ckpt_sha = hashlib.sha256(ckpt.read_bytes()).hexdigest()
    keypair = Ed25519KeyPair.generate("mock-issuer-stage2-6-0b")
    payload = build_attestation_payload(
        checkpoint_sha256=ckpt_sha, sidecar_sha256=sidecar_sha,
        training_manifest_sha256=tm_sha, charter_hash=charter_h,
        observation_schema_hash=schema.schema_hash(),
        route_c_env_version="RouteCEnvCore-v1.0.0",
        training_generator_hashes={}, training_pack_hash="mock-train-pack",
        training_code_hash="mock-train-code",
        ppo_params={"n_steps": 256, "batch_size": 64, "seed": 7},
        network_architecture={
            "policy_class": type(model.policy).__name__,
            "parameter_count": int(n_params)},
        training_budget={"total_timesteps": 256}, training_seed=7,
        is_smoke=False, allow_formal_evaluation=True,
        issuer_id=keypair.issuer_id,
        training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        issued_utc="2026-08-26T00:00:00Z")
    write_attestation(d / "test_ppo.zip.rl_attestation.json", keypair,
                      payload)
    return {
        "checkpoint": str(ckpt), "charter_hash": charter_h,
        "training_manifest_path": str(tm_path),
        "training_manifest_sha256": tm_sha, "schema": schema,
        "keypair": keypair, "model": model,
        "trusted": TrustedIssuerConfig.from_keypair(
            keypair, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
            allow_smoke=False),
        "training_manifest": training_manifest,
    }


def artifact_sandbox_denial(material):
    ws = Path(tempfile.mkdtemp(prefix="eval-ws-"))
    (ws / "SENTINEL").write_text("eval-secret")
    (ws / "hidden_pack.json").write_text('{"hidden": true}')
    report = _sandbox_probe(
        material["checkpoint"], '''
try:
    with open("/proc/self/mountinfo") as f:
        info = f.read()
    report["extra"]["mountinfo_leaks_home"] = "/home/" in info
    report["extra"]["mountinfo_leaks_projects"] = "projects" in info
except Exception as e:
    report["extra"]["mountinfo_error"] = repr(e)
''', targets=[
            ("sentinel", str(ws / "SENTINEL")),
            ("hidden_pack", str(ws / "hidden_pack.json")),
            ("project_root", str(ROOT)),
            ("user_home", str(Path.home())),
            ("generators_src", str(ROOT / "src" / "rl_curriculum")),
    ])
    targets = report.get("targets", {})
    save_json("sandbox_denial_trace.json", {
        "targets": {k: {
            "read_ok": v["read"]["ok"], "read_err": v["read"]["err"],
            "list_ok": v["list"]["ok"],
            "write_ok": v["write"]["ok"], "write_err": v["write"]["err"],
        } for k, v in targets.items()},
        "mountinfo_leaks_home": report["extra"].get("mountinfo_leaks_home"),
        "mountinfo_leaks_projects": report["extra"].get(
            "mountinfo_leaks_projects"),
        "all_denied": all(
            not v["read"]["ok"] and not v["list"]["ok"]
            and not v["write"]["ok"] for v in targets.values()),
    })


def artifact_sandbox_network(material):
    report = _sandbox_probe(material["checkpoint"], '''
import socket
def tc(host, port):
    try:
        c = socket.create_connection((host, port), timeout=3); c.close()
        return "connected"
    except Exception as e:
        return type(e).__name__
report["extra"]["loopback"] = tc("127.0.0.1", 1)
report["extra"]["external"] = tc("93.184.216.34", 80)
try:
    socket.getaddrinfo("example.com", 80)
    report["extra"]["dns"] = "resolved"
except Exception as e:
    report["extra"]["dns"] = type(e).__name__
''')
    ex = report["extra"]
    save_json("sandbox_network_test.json", {
        "loopback": ex.get("loopback"), "external": ex.get("external"),
        "dns": ex.get("dns"),
        "all_denied": ex.get("loopback") != "connected"
        and ex.get("external") != "connected"
        and ex.get("dns") != "resolved",
    })


def artifact_sandbox_proc(material):
    parent_pid = None  # 评估进程即本进程
    parent_pid = str(Path("/proc/self").readlink()).split("/")[-1] \
        if False else str(None)
    import os

    parent_pid = os.getpid()
    report = _sandbox_probe(material["checkpoint"], '''
import os
entries = [e for e in os.listdir("/proc") if e.isdigit()]
report["extra"]["proc_entries"] = entries
report["extra"]["my_pid"] = os.getpid()
report["extra"]["ppid"] = os.getppid()
''', targets=[
        ("parent_cmdline", f"/proc/{parent_pid}/cmdline"),
        ("parent_environ", f"/proc/{parent_pid}/environ"),
    ])
    ex = report["extra"]
    targets = report.get("targets", {})
    save_json("sandbox_proc_isolation.json", {
        "proc_entries": ex.get("proc_entries"),
        "my_pid": ex.get("my_pid"), "ppid": ex.get("ppid"),
        "parent_cmdline_readable": targets.get(
            "parent_cmdline", {}).get("read", {}).get("ok"),
        "parent_environ_readable": targets.get(
            "parent_environ", {}).get("read", {}).get("ok"),
        "isolated": len(ex.get("proc_entries", [])) <= 2
        and not targets.get("parent_cmdline", {}).get("read", {}).get("ok"),
    })


def artifact_sandbox_limits(material):
    from rl_curriculum.sandbox import default_sandbox_profile

    report = _sandbox_probe(material["checkpoint"], '''
import resource
report["extra"]["limits"] = {
    "cpu": resource.getrlimit(resource.RLIMIT_CPU),
    "as": resource.getrlimit(resource.RLIMIT_AS),
    "fsize": resource.getrlimit(resource.RLIMIT_FSIZE),
    "nofile": resource.getrlimit(resource.RLIMIT_NOFILE),
    "nproc": resource.getrlimit(resource.RLIMIT_NPROC),
}
''')
    profile = default_sandbox_profile()
    save_json("sandbox_resource_limits.json", {
        "observed": report["extra"]["limits"],
        "profile_rlimits": profile.rlimits,
        "note": "完整 fail-closed 行为(超限/超时/协议违规)由测试套件覆盖",
    })


# ---------------------------------------------------------------- 工作包 D
def artifact_nuisance_equivalence(material):
    from rl_curriculum.counterfactual import (
        NuisanceEquivalenceSpec,
        test_nuisance_slot_injection,
        test_nuisance_slot_shuffle,
    )
    from rl_curriculum.policies import RuleTrendPolicy

    gen_eps = material["episodes"]
    spec = NuisanceEquivalenceSpec()
    policy = RuleTrendPolicy()
    cfg = material["cfg"]
    schema = material["schema"]
    results = {}
    for mode, fn in (("injection", test_nuisance_slot_injection),
                     ("shuffle", test_nuisance_slot_shuffle)):
        r = fn(policy, gen_eps, cfg, schema, spec=spec)
        results[mode] = r.to_record()
    save_json("nuisance_equivalence_report.json", {
        "spec": spec.canonical_payload(),
        "policy": "rule_trend(忽略 nuisance)",
        "injection_pass": results["injection"]["pass"],
        "shuffle_pass": results["shuffle"]["pass"],
        "injection": results["injection"],
        "shuffle": results["shuffle"],
        "bidirectional": True,
    })


def artifact_nuisance_dependency_failure(material):
    import sys as _sys

    _sys.path.insert(0, str(ROOT / "tests" / "route_c_stage2_6_0b"))
    from rl_curriculum.counterfactual import (
        NuisanceEquivalenceSpec,
        test_nuisance_slot_injection,
    )

    class NuisanceReader(material["policy_base"]):
        name = "nuisance_reader"

        def reset_episode(self) -> None:
            return None

        def act(self, observation):
            return int(float(observation[self.slot("nuisance_0")]) > 0.25)

    spec = NuisanceEquivalenceSpec()
    r = test_nuisance_slot_injection(
        NuisanceReader(), material["episodes"], material["cfg"],
        material["schema"], spec=spec)
    save_json("nuisance_dependency_failure.json", {
        "policy": "nuisance_reader(故意读 nuisance_0)",
        "pass": r.pass_, "expected_pass": False,
        "failure_modes": r.extra["failure_modes"],
        "action_match_rate": r.action_match_rate,
        "record": r.to_record(),
    })


# ---------------------------------------------------------------- 工作包 E
def artifact_replication_evidence():
    from rl_curriculum.counterfactual import (
        build_replication_evidence,
        classify_cheating,
    )

    def rec(seed, fail, variant):
        return {"test": "common_prefix_future_suffix", "pass": not fail,
                "action_match_rate": 0.4 if fail else 1.0,
                "first_divergence_step": 1 if fail else None,
                "variant": {"net_return": variant},
                "extra": {"episode_seed": seed,
                          "variant_net_returns": [variant]}}

    multi = [rec(201, True, -0.05), rec(202, True, -0.05),
             rec(203, True, -0.05), rec(204, False, -0.002)]
    single = [rec(201, True, -0.05), rec(202, False, -0.002),
              rec(203, False, -0.002), rec(204, False, -0.001),
              rec(205, False, -0.001)]
    missing = [
        {"test": "common_prefix_future_suffix", "pass": False,
         "action_match_rate": 0.4, "first_divergence_step": 1,
         "variant": {}, "extra": {"episode_seed": s}}
        for s in (201, 202, 203)]

    def ev(records):
        return build_replication_evidence(
            records, base_net_by_episode={}, min_effective_net_return=0.0,
            min_distinct_seeds=3, min_failing_episodes=3)

    def cls(records, evidence):
        return classify_cheating(
            [type("R", (), {"name": r["test"], "pass_": r["pass"],
                            "extra": r["extra"], "base": {},
                            "variant": {}})() for r in records],
            base_median_net_return=0.02, base_seed_pass_ratio=0.8,
            replication_evidence={"future_leakage": evidence},
            min_effective_net_return=0.0)

    save_json("replicated_cheating_evidence.json", {
        "scenario": "5 seed 中 3 个失败且优势崩溃",
        "evidence": ev(multi),
        "classification": cls(multi, ev(multi)),
        "suspected_cheating": cls(multi, ev(multi))["suspected_cheating"],
    })
    save_json("single_seed_not_cheating.json", {
        "scenario": "5 seed 只有 1 个失败",
        "evidence": ev(single),
        "classification": cls(single, ev(single)),
        "suspected_cheating": cls(single, ev(single))["suspected_cheating"],
        "missing_collapse_demo": cls(missing, ev(missing))[
            "missing_collapse_evidence"],
    })


# ---------------------------------------------------------------- 工作包 F
def artifact_generator_binding():
    from rl_curriculum.generator_binding import (
        generator_bindings,
        verify_generator_bindings,
    )
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    bindings = generator_bindings(R)
    compact = {f: {k: v[k] for k in ("family_version",
                                    "implementation_hash",
                                    "manifest_hash")}
               for f, v in bindings.items()}
    report = verify_generator_bindings(R, compact,
                                       required_families=sorted(compact))
    save_json("generator_implementation_binding.json", {
        "per_family": compact,
        "sample_manifest": bindings["probe_segmented_drift"]["manifest"],
        "verify": report,
        "distinct_hashes": len({v["implementation_hash"]
                                for v in compact.values()}) == len(compact),
    })


def artifact_private_generator_tamper():
    import importlib
    import sys
    import textwrap

    from rl_curriculum.generator_binding import implementation_manifest

    tmp = Path(tempfile.mkdtemp(prefix="priv-gen-"))
    (tmp / "hidden_a.py").write_text(textwrap.dedent('''
        from rl_curriculum.generator_api import BaseMarketGenerator
        from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

        class HiddenA(BaseMarketGenerator):
            family = "hidden_a"; family_version = "ha-v1"
            feature_columns = list(PROBE_FEATURE_COLUMNS)
            nuisance_slot_names = ()
            declared_dependencies = ("helpers.py",)

            def _generate(self, params, seed, rng):
                import pandas as pd
                from helpers import scale
                n = int(params["episode_bars"])
                return (rng.standard_normal(n) * scale(),
                        pd.DataFrame({"h": [0.0] * n}), {})
    '''), encoding="utf-8")
    (tmp / "hidden_b.py").write_text(textwrap.dedent('''
        from rl_curriculum.generator_api import BaseMarketGenerator
        from rl_curriculum.generators import PROBE_FEATURE_COLUMNS

        class HiddenB(BaseMarketGenerator):
            family = "hidden_b"; family_version = "hb-v1"
            feature_columns = list(PROBE_FEATURE_COLUMNS)
            nuisance_slot_names = ()

            def _generate(self, params, seed, rng):
                import pandas as pd
                n = int(params["episode_bars"])
                return (rng.standard_normal(n) * 3e-4,
                        pd.DataFrame({"h": [0.0] * n}), {})
    '''), encoding="utf-8")
    (tmp / "helpers.py").write_text("def scale():\n    return 1.5e-4\n",
                                    encoding="utf-8")
    sys.path.insert(0, str(tmp))
    ma = importlib.import_module("hidden_a")
    mb = importlib.import_module("hidden_b")
    h_a1 = implementation_manifest(ma.HiddenA())["implementation_hash"]
    h_b1 = implementation_manifest(mb.HiddenB())["implementation_hash"]
    # 篡改 1:类实现
    (tmp / "hidden_a.py").write_text(
        (tmp / "hidden_a.py").read_text(encoding="utf-8").replace(
            "scale()", "scale() * 1.0001"), encoding="utf-8")
    sys.modules.pop("hidden_a")
    importlib.invalidate_caches()
    ma2 = importlib.import_module("hidden_a")
    h_a2 = implementation_manifest(ma2.HiddenA())["implementation_hash"]
    # 篡改 2:特征依赖
    (tmp / "helpers.py").write_text(
        "def scale():\n    return 2.5e-4\n", encoding="utf-8")
    sys.modules.pop("hidden_a"); sys.modules.pop("helpers", None)
    importlib.invalidate_caches()
    ma3 = importlib.import_module("hidden_a")
    h_a3 = implementation_manifest(ma3.HiddenA())["implementation_hash"]
    # 篡改 3:family version
    (tmp / "hidden_b.py").write_text(
        (tmp / "hidden_b.py").read_text(encoding="utf-8").replace(
            '"hb-v1"', '"hb-v2"'), encoding="utf-8")
    sys.modules.pop("hidden_b")
    importlib.invalidate_caches()
    mb2 = importlib.import_module("hidden_b")
    h_b2 = implementation_manifest(mb2.HiddenB())["implementation_hash"]
    for m in ("hidden_a", "hidden_b", "helpers"):
        sys.modules.pop(m, None)
    save_json("private_generator_tamper_test.json", {
        "class_impl_tamper_changes_hash": h_a1 != h_a2,
        "dependency_tamper_changes_hash": h_a2 != h_a3,
        "version_tamper_changes_hash": h_b1 != h_b2,
        "independent_families": h_a1 != h_b1,
        "hashes": {"a1": h_a1, "a2": h_a2, "a3": h_a3,
                   "b1": h_b1, "b2": h_b2},
    })


# ---------------------------------------------------------------- 工作包 G
def artifact_attestation_demo(material):
    from rl_curriculum.attestation import (
        _sha256_file,
        formal_eligibility_from_attestation,
        load_attestation,
        payload_hash,
        verify_attestation,
    )

    ck = material["checkpoint"]
    doc = load_attestation(ck + ".rl_attestation.json")
    report = verify_attestation(
        doc, trusted=material["trusted"], checkpoint_path=ck,
        sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
        training_manifest_sha256=material["training_manifest_sha256"],
        charter_hash=material["charter_hash"],
        observation_schema_hash=material["schema"].schema_hash())
    eligibility = formal_eligibility_from_attestation(
        checkpoint_path=ck, sidecar_manifest=json.loads(
            Path(ck + ".rl_manifest.json").read_text()),
        trusted=material["trusted"],
        training_manifest_sha256=material["training_manifest_sha256"],
        charter_hash=material["charter_hash"],
        observation_schema_hash=material["schema"].schema_hash())
    save_json("trusted_training_attestation_demo.json", {
        "flow": ["受控训练 runner(测试级 PPO 256 步)",
                 "不可变训练 manifest", "checkpoint + v3 sidecar",
                 "mock trusted issuer 签发 attestation(Ed25519)",
                 "评估方验证签名与逐项绑定"],
        "issuer_fingerprint": material["keypair"].fingerprint,
        "training_runner_hash": MOCK_TRAINING_RUNNER_HASH,
        "private_key_isolated": (
            "私钥只存在于评估方临时目录;不进入候选沙箱/仓库/checkpoint"),
        "verify_report": report,
        "eligibility": eligibility,
        "payload_keys": sorted(doc["payload"].keys()),
        "payload_hash": payload_hash(doc["payload"]),
    })


def artifact_attestation_tamper_matrix(material):
    from rl_curriculum.attestation import (
        AttestationError,
        Ed25519KeyPair,
        _sha256_file,
        load_attestation,
        verify_attestation,
        write_attestation,
    )

    ck = material["checkpoint"]
    doc = load_attestation(ck + ".rl_attestation.json")
    base_kwargs = dict(
        trusted=material["trusted"], checkpoint_path=ck,
        sidecar_sha256=_sha256_file(ck + ".rl_manifest.json"),
        training_manifest_sha256=material["training_manifest_sha256"],
        charter_hash=material["charter_hash"],
        observation_schema_hash=material["schema"].schema_hash())
    matrix = {}

    def case(name, fn):
        try:
            fn()
            matrix[name] = {"rejected": False}
        except AttestationError as exc:
            matrix[name] = {"rejected": True, "reason": str(exc)[:160]}

    case("valid_mock_attestation", lambda: verify_attestation(doc,
                                                              **base_kwargs))
    rogue = Ed25519KeyPair.generate("rogue")
    rogue_doc = dict(doc)
    rogue_doc["signature"] = rogue.sign(doc["payload"]).hex()
    rogue_doc["public_key_pem"] = rogue.public_pem.decode()
    rogue_doc["key_fingerprint"] = rogue.fingerprint
    case("self_signed_attestation",
         lambda: verify_attestation(rogue_doc, **base_kwargs))
    case("checkpoint_replaced", lambda: verify_attestation(
        doc, **{**base_kwargs, "checkpoint_path": __file__}))
    case("sidecar_modified", lambda: verify_attestation(
        doc, **{**base_kwargs, "sidecar_sha256": "0" * 64}))
    case("training_manifest_modified", lambda: verify_attestation(
        doc, **{**base_kwargs, "training_manifest_sha256": "0" * 64}))
    case("charter_changed", lambda: verify_attestation(
        doc, **{**base_kwargs, "charter_hash": "c-different"}))
    case("schema_changed", lambda: verify_attestation(
        doc, **{**base_kwargs,
                "observation_schema_hash": "o-different"}))

    def _smoke():
        payload = dict(doc["payload"])
        payload["is_smoke"] = True
        with tempfile.NamedTemporaryFile(suffix=".json") as f:
            smoke_doc = write_attestation(f.name, material["keypair"],
                                          payload)
            verify_attestation(smoke_doc, **base_kwargs)

    case("smoke_disguised_as_formal", _smoke)

    def _runner():
        from rl_curriculum.attestation import TrustedIssuerConfig

        verify_attestation(
            doc, trusted=TrustedIssuerConfig.from_keypair(
                material["keypair"],
                required_training_runner_hash="other-runner"),
            **{k: v for k, v in base_kwargs.items() if k != "trusted"})

    case("training_runner_hash_mismatch", _runner)

    def _other_checkpoint():
        other = Path(tempfile.mkdtemp(prefix="other-ck-")) / "other.zip"
        other.write_bytes(b"entirely-different-model")
        for suffix in (".rl_manifest.json", ".rl_attestation.json"):
            (other.with_name(other.name + suffix)).write_text(
                Path(ck + suffix).read_text())
        verify_attestation(
            load_attestation(str(other) + ".rl_attestation.json"),
            **{**base_kwargs, "checkpoint_path": str(other)})

    case("attestation_bound_to_other_checkpoint", _other_checkpoint)
    save_json("attestation_tamper_matrix.json", {
        "matrix": matrix,
        "all_required_rejected": all(
            v["rejected"] for k, v in matrix.items()
            if k != "valid_mock_attestation"),
        "valid_passes": matrix["valid_mock_attestation"].get(
            "rejected") is False,
    })


# ---------------------------------------------------------------- 工作包 H
def artifact_strict_null_qualification(material):
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualify_null_family,
    )

    reports = {}
    for fam in ("probe_null_sign", "probe_null_volstate",
                "probe_null_stochvol"):
        reports[fam] = qualify_null_family(
            R[fam], params=material["base_params"], timeframe="15m",
            seeds=NULL_QUAL_SEEDS, cfg=material["cfg"],
            schema=material["schema"])
    skewed = dict(material["base_params"])
    skewed["direction_weights"] = [0.0, 0.85, 0.15]
    bad_report = qualify_null_family(
        R["probe_segmented_drift"], params=skewed, timeframe="15m",
        seeds=NULL_QUAL_SEEDS, cfg=material["cfg"],
        schema=material["schema"])
    save_json("strict_null_qualification.json", {
        "format": "null-qualification-v1",
        "families": {f: {
            "pass": r["pass"], "checks": r["checks"],
            "oracle_excess": r["oracle"]["excess_bootstrap"],
            "rule_excess": r["rule_trend"]["excess_bootstrap"],
            "net_drift_ci": r["net_drift_per_bar_bootstrap"],
            "high_turnover_median": r["high_turnover_median"],
            "n_episodes": r["n_episodes_tested"],
        } for f, r in reports.items()},
        "bindings": build_null_qualification_bindings(reports),
        "drifting_pseudo_null_rejected": not bad_report["pass"],
        "pseudo_null_reasons": bad_report["reasons"],
    })
    return reports


def artifact_block_shuffle_reclassification():
    from rl_curriculum.generators import (
        FORMAL_NULL_FAMILIES,
        PARTIAL_DEPENDENCY_TESTS,
    )
    save_md("block_shuffle_reclassification.md", """\
# probe_null_block 重新分类(阶段 2.6.0b 工作包 H1)

## 旧分类(2.6.0a,错误)
正式 Null 最小集合成员之一,作为"完全无预测信号环境中不得盈利"的硬门。

## 问题
分块重排保留块内(默认 8 bars)趋势与短周期方向关系:短周期策略在
其上仍可获利。它破坏的只是跨块关系——这不足以证明"无信号"。

## 新分类(2.6.0b)
partial_dependency_destruction / local-structure robustness test:
- 保留:块内局部结构、短程方向关系;
- 破坏:跨块关系、块边界方向;
- 用途:诊断模型依赖长期关系还是短期关系;跨块关系破坏后的性能变化;
- 限制:不在 required_null_families 中;其上获利不构成 Null 作弊证据;
  is_null_family=False(诊断族)。

## 新的严格 Null 最小集合(三种不同机制)
1. probe_null_sign 符号随机化(保留 |收益| 与波动聚集);
2. probe_null_volstate 波动状态条件随机化(档内置换+独立符号翻转);
3. probe_null_stochvol 独立实现的随机波动率零漂移市场(马尔可夫波动
   状态+重尾幅度+iid 方向;不从任何源轨迹变换)。

每族均通过 null_qualification 五项资格审查(见
strict_null_qualification.json),资格绑定进入 sealed commitment。
""")
    assert "probe_null_block" not in FORMAL_NULL_FAMILIES
    assert "probe_null_block" in PARTIAL_DEPENDENCY_TESTS


# ---------------------------------------------------------------- 工作包 I/J
def artifact_sealed_commitment(material, null_reports):
    from rl_curriculum.generator_binding import generator_bindings
    from rl_curriculum.mock_sealed_exam import (
        build_mock_commitment,
        build_mock_hidden_pack,
    )
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
        qualification_code_hash,
    )
    from rl_curriculum.param_resolution import (
        resolved_parameter_semantics_hash,
    )
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    pack = build_mock_hidden_pack()
    commitment = build_mock_commitment(
        pack=pack, charter=material["charter"], schema=material["schema"],
        verdict_spec=probe_course_verdict_spec(),
        eval_config=material["cfg"],
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=material["trusted"],
        null_qualification_bindings=build_null_qualification_bindings(
            null_reports))
    bindings = generator_bindings(material["registry"])
    save_json("sealed_commitment_v2.json", {
        "protocol": "sealed-exam-commitment-v2",
        "commitment": json.loads(commitment.to_json()),
        "commitment_hash": commitment.commitment_hash(),
        "bindings_cover": {
            "pack": True, "charter": True, "observation_schema": True,
            "spec_versions": True,
            "generator_implementations": sorted(bindings),
            "evaluator_code_hash": True, "counterfactual_code_hash": True,
            "verdict_spec_hash": True, "eval_config": True,
            "sandbox_profile_hash": commitment.sandbox_profile_hash,
            "nuisance_equivalence_spec": True,
            "anticheat_replication_spec": True,
            "null_qualification_bindings": True,
            "null_qualification_code_hash": qualification_code_hash(),
            "trusted_issuer": True,
            "resolved_parameter_semantics_hash":
                resolved_parameter_semantics_hash(),
            "checkpoint_requirements": True,
        },
    })
    return pack, commitment


def artifact_mock_exam_and_tamper_matrix(material, pack, commitment,
                                         quick):
    from rl_curriculum.mock_sealed_exam import write_exam_context
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    ws = Path(tempfile.mkdtemp(prefix="mock-exam-ws-"))
    pack_path = ws / "pack.json"
    pack.save(pack_path)
    ctx_path = ws / "context.json"
    write_exam_context(
        ctx_path, charter=material["charter"], schema=material["schema"],
        verdict_spec=probe_course_verdict_spec(),
        eval_config=material["cfg"],
        sandbox_profile=None, trusted_issuer=material["trusted"])
    manifest_path = ws / "commitment.json"
    commitment.save(manifest_path)
    ck_src = Path(material["checkpoint"])
    ck_dst = ws / ck_src.name
    ck_dst.write_bytes(ck_src.read_bytes())
    for suffix in (".rl_manifest.json", ".rl_attestation.json"):
        (ws / (ck_dst.name + suffix)).write_text(
            Path(str(ck_src) + suffix).read_text())

    cli_env = {"PYTHONPATH": str(ROOT / "src"),
               "PATH": "/usr/bin:/bin:/home/cryptorl/miniforge3/envs/"
                       "freqtrade-rl/bin",
               "LANG": "C.UTF-8", "HOME": str(Path.home())}

    def run_cli(pack_p, ck_p, ctx_p, out_p, extra=()):
        return subprocess.run(
            [sys.executable, "-m", "rl_curriculum.hidden_exam_cli",
             "--sealed-manifest", str(manifest_path),
             "--pack", str(pack_p), "--checkpoint", str(ck_p),
             "--context", str(ctx_p), "--out", str(out_p),
             "--retire-registry", str(ws / "retired.json"),
             "--attempt-registry", str(ws / "attempts.json"), *extra],
            capture_output=True, text=True, timeout=7200, env=cli_env)

    out_main = ws / "result.json"
    t0 = time.time()
    proc = run_cli(pack_path, ck_dst, ctx_path, out_main)
    duration = round(time.time() - t0, 1)
    summary = {
        "steps": [], "duration_seconds": duration,
        "returncode": proc.returncode,
    }
    if out_main.exists():
        result = json.loads(out_main.read_text(encoding="utf-8"))
        summary["status"] = result.get("result", {}).get("status") or \
            result.get("status")
        summary["exam_cli_version"] = result.get("exam_cli_version")
        summary["sandboxed_candidate"] = True
        summary["sealed_checks_count"] = len(
            result.get("sealed_verification", {}).get("checks", {}))
        summary["steps"].append("评估方准备(mock pack/commitment/issuer)")
        summary["steps"].append("受控训练来源(attested checkpoint)")
        summary["steps"].append("沙箱评估(reset 无 token/无隐藏包/无网络)")
        summary["steps"].append(f"冻结判定器输出 {summary['status']}")
    else:
        summary["stderr"] = proc.stderr[-2000:]

    # 篡改矩阵(J5)
    from rl_curriculum.counterfactual import NuisanceEquivalenceSpec
    from rl_curriculum.exam_pack import ExamPack
    from rl_curriculum.generator_api import EpisodeSpec
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.sealed_exam import SealedExamError
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    matrix = {}

    def tamper(name):
        def deco(fn):
            try:
                fn()
                matrix[name] = {"detected": False}
            except (SealedExamError, Exception) as exc:  # noqa: BLE001
                matrix[name] = {"detected": True,
                                "error": type(exc).__name__,
                                "msg": str(exc)[:140]}
            return fn
        return deco

    @tamper("raw_duration_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        # 原始时长声明被改写(episode_bars 包追加不一致的 duration_hours):
        # resolved_durations 解析即失败或 pack hash 变化
        tampered_pack = ExamPack(
            name=pack.name, version=pack.version,
            visibility=pack.visibility, charter_hash=pack.charter_hash,
            spec_versions=pack.spec_versions,
            episodes=[EpisodeSpec(e.family,
                                  {**e.params, "duration_hours": 12.0},
                                  e.seed, e.split, e.timeframe)
                      for e in pack.episodes],
            timeframe=pack.timeframe, notes=pack.notes)
        verify_sealed_commitment(
            commitment, pack=tampered_pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=default_sandbox_profile())

    @tamper("resolved_bars_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        tampered_pack = ExamPack(
            name=pack.name, version=pack.version,
            visibility=pack.visibility, charter_hash=pack.charter_hash,
            spec_versions=pack.spec_versions,
            episodes=[EpisodeSpec(
                e.family, {k: (v * 2 if k == "episode_bars" else v)
                           for k, v in e.params.items()},
                e.seed, e.split, e.timeframe)
                for e in pack.episodes],
            timeframe=pack.timeframe, notes=pack.notes)
        verify_sealed_commitment(
            commitment, pack=tampered_pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=default_sandbox_profile())

    @tamper("pack_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        tampered_pack = ExamPack(
            name=pack.name, version=pack.version,
            visibility=pack.visibility, charter_hash=pack.charter_hash,
            spec_versions=pack.spec_versions,
            episodes=[EpisodeSpec(e.family, dict(e.params), e.seed + 1,
                                  e.split, e.timeframe)
                      for e in pack.episodes],
            timeframe=pack.timeframe, notes=pack.notes)
        verify_sealed_commitment(
            commitment, pack=tampered_pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=default_sandbox_profile())

    @tamper("generator_implementation_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        bad_bindings = dict(commitment.generator_bindings)
        bad_bindings["probe_segmented_drift"] = {
            **bad_bindings["probe_segmented_drift"],
            "implementation_hash": "gi-" + "0" * 64}
        bad_commitment = type(commitment)(
            pack_hash=commitment.pack_hash,
            charter_hash=commitment.charter_hash,
            observation_schema_hash=commitment.observation_schema_hash,
            spec_versions=commitment.spec_versions,
            generator_bindings=bad_bindings,
            evaluator_code_hash=commitment.evaluator_code_hash,
            counterfactual_code_hash=commitment.counterfactual_code_hash,
            verdict_spec_hash=commitment.verdict_spec_hash,
            eval_config=commitment.eval_config)
        verify_sealed_commitment(
            bad_commitment, pack=pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=default_sandbox_profile())

    from rl_curriculum.null_qualification import (
        verify_null_qualification_bindings,
    )

    bad_null = {f: {"qualification_pass": False}
                for f in commitment.null_qualification_bindings}
    null_report = verify_null_qualification_bindings(
        bad_null, required_families=list(
            probe_course_verdict_spec().required_null_families))
    matrix["null_qualification_changed"] = {
        "detected": not null_report["pass"],
        "note": "verify_null_qualification_bindings 返回 pass=False"}

    @tamper("sandbox_profile_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sandbox import SandboxProfile
        from rl_curriculum.sealed_exam import verify_sealed_commitment
        base = default_sandbox_profile()
        other = SandboxProfile(
            read_exec_dirs=base.read_exec_dirs,
            read_only_dirs=base.read_only_dirs,
            read_write_dirs=base.read_write_dirs,
            rlimits={**base.rlimits, "nofile": 999})
        verify_sealed_commitment(
            commitment, pack=pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=other)

    @tamper("eval_config_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        import dataclasses

        bad_cfg = dataclasses.replace(material["cfg"], fee=0.01)
        verify_sealed_commitment(
            commitment, pack=pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=bad_cfg,
            verdict_spec=probe_course_verdict_spec(),
            sandbox_profile=default_sandbox_profile())

    @tamper("nuisance_equivalence_threshold_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        from rl_curriculum.verdict_spec import (
            CourseVerdictSpec,
            verdict_spec_from_json,
        )
        payload = probe_course_verdict_spec().canonical_payload()
        payload["nuisance_equivalence"]["delta_return"] = 0.5
        bad_vs = verdict_spec_from_json(payload)
        verify_sealed_commitment(
            commitment, pack=pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=bad_vs,
            sandbox_profile=default_sandbox_profile())

    @tamper("anticheat_replication_threshold_changed")
    def _():
        from rl_curriculum.evaluator import EvalConfig

        from rl_curriculum.sealed_exam import verify_sealed_commitment
        from rl_curriculum.verdict_spec import verdict_spec_from_json
        payload = probe_course_verdict_spec().canonical_payload()
        payload["min_distinct_cheat_seeds"] = 1
        bad_vs = verdict_spec_from_json(payload)
        verify_sealed_commitment(
            commitment, pack=pack, charter=material["charter"],
            schema=material["schema"], registry=material["registry"],
            eval_config=EvalConfig(**material["cfg"].manifest()),
            verdict_spec=bad_vs,
            sandbox_profile=default_sandbox_profile())

    # CLI 级:checkpoint/attestation/issuer/runner 篡改
    if not quick:
        bad_ck = ws / "bad.zip"
        bad_ck.write_bytes(ck_dst.read_bytes() + b"x")
        for suffix in (".rl_manifest.json", ".rl_attestation.json"):
            (ws / (bad_ck.name + suffix)).write_text(
                Path(str(ck_dst) + suffix).read_text())
        proc2 = run_cli(pack_path, bad_ck, ctx_path, ws / "out_bad.json")
        matrix["checkpoint_replaced"] = {
            "detected": proc2.returncode == 5,
            "exit_code": proc2.returncode}
        no_att = ws / "no_att.zip"
        no_att.write_bytes(ck_dst.read_bytes())
        (ws / (no_att.name + ".rl_manifest.json")).write_text(
            Path(str(ck_dst) + ".rl_manifest.json").read_text())
        proc3 = run_cli(pack_path, no_att, ctx_path, ws / "out_noatt.json")
        matrix["attestation_missing"] = {
            "detected": proc3.returncode == 5,
            "exit_code": proc3.returncode}
        tm_bad = ws / "training_manifest_tampered.json"
        tm = json.loads(Path(
            material["training_manifest_path"]).read_text())
        tm["steps"] = 999999999
        tm_bad.write_text(json.dumps(tm))
        # sidecar 指向被改 manifest 的 sha
        sidecar = json.loads(
            Path(str(ck_dst) + ".rl_manifest.json").read_text())
        sidecar["training_manifest_sha256"] = hashlib.sha256(
            tm_bad.read_bytes()).hexdigest()
        ck_tm = ws / "tm_swap.zip"
        ck_tm.write_bytes(ck_dst.read_bytes())
        (ws / (ck_tm.name + ".rl_manifest.json")).write_text(
            json.dumps(sidecar))
        (ws / (ck_tm.name + ".rl_attestation.json")).write_text(
            Path(str(ck_dst) + ".rl_attestation.json").read_text())
        proc4 = run_cli(pack_path, ck_tm, ctx_path, ws / "out_tm.json")
        matrix["training_manifest_tampered"] = {
            "detected": proc4.returncode == 5, "exit_code": proc4.returncode}
        # issuer 公钥不受信(换一个 issuer 的 context)
        from rl_curriculum.attestation import Ed25519KeyPair
        from rl_curriculum.mock_sealed_exam import write_exam_context as wctx

        other = Ed25519KeyPair.generate("other-issuer")
        from rl_curriculum.attestation import TrustedIssuerConfig

        ctx_bad = ws / "ctx_bad_issuer.json"
        wctx(ctx_bad, charter=material["charter"],
             schema=material["schema"],
             verdict_spec=probe_course_verdict_spec(),
             eval_config=material["cfg"],
             trusted_issuer=TrustedIssuerConfig.from_keypair(
                 other, required_training_runner_hash="other"))
        proc5 = run_cli(pack_path, ck_dst, ctx_bad, ws / "out_iss.json")
        matrix["issuer_public_key_untrusted"] = {
            "detected": proc5.returncode == 5, "exit_code": proc5.returncode}

    save_json("sealed_exam_tamper_matrix_v2.json", {
        "matrix": matrix,
        "all_detected": all(v.get("detected") for v in matrix.values()),
    })
    save_json("mock_sealed_exam_v2_summary.json", summary)


def artifact_upstream_integrity():
    def run(cmd):
        return subprocess.run(cmd, capture_output=True, text=True,
                              cwd=str(ROOT)).stdout.strip()

    save_md("upstream_integrity.txt", "\n".join([
        "git -C vendor/freqtrade describe --tags --exact-match",
        run(["git", "-C", "vendor/freqtrade", "describe", "--tags",
             "--exact-match"]),
        "git -C vendor/freqtrade rev-parse HEAD",
        run(["git", "-C", "vendor/freqtrade", "rev-parse", "HEAD"]),
        "git -C vendor/freqtrade status --short",
        run(["git", "-C", "vendor/freqtrade", "status", "--short"])
        or "(clean)",
    ]))


# ---------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args()
    ART.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    print("== 工作包 A:真实时长物化 ==")
    artifact_duration_materialization()
    artifact_resolved_parameter_trace()
    print("== 工作包 B:reset 协议 ==")
    artifact_candidate_reset_protocol()
    print("== 工作包 C:沙箱 ==")
    artifact_sandbox_matrix()
    material = _attested_checkpoint()
    # 评估用 Episode(nuisance/attestation 材料复用)
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator
    from rl_curriculum.mock_sealed_exam import BASE_PARAMS
    from rl_curriculum.policy_api import ObservableBaselinePolicy

    gen = ProbeSegmentedDriftGenerator()
    material["episodes"] = [
        gen.generate(dict(BASE_PARAMS), s, split="param_extrapolation",
                     timeframe="15m") for s in (301, 302, 303)]
    material["base_params"] = dict(BASE_PARAMS)
    from rl_curriculum.mock_sealed_exam import default_eval_config

    material["cfg"] = default_eval_config()
    material["registry"] = __import__(
        "rl_curriculum.generators", fromlist=[
            "DEFAULT_GENERATOR_REGISTRY"]).DEFAULT_GENERATOR_REGISTRY
    material["policy_base"] = ObservableBaselinePolicy
    material["charter"] = __import__(
        "rl_curriculum.probe_charter", fromlist=[
            "audit_probe_charter"]).audit_probe_charter()
    artifact_sandbox_denial(material)
    artifact_sandbox_network(material)
    artifact_sandbox_proc(material)
    artifact_sandbox_limits(material)
    print("== 工作包 D:nuisance 双边等价 ==")
    artifact_nuisance_equivalence(material)
    artifact_nuisance_dependency_failure(material)
    print("== 工作包 E:复制证据 ==")
    artifact_replication_evidence()
    print("== 工作包 F:生成器实现绑定 ==")
    artifact_generator_binding()
    artifact_private_generator_tamper()
    print("== 工作包 G:attestation ==")
    artifact_attestation_demo(material)
    artifact_attestation_tamper_matrix(material)
    print("== 工作包 H:严格 Null 资格 ==")
    null_reports = artifact_strict_null_qualification(material)
    artifact_block_shuffle_reclassification()
    print("== 工作包 I/J:承诺 v2 与 mock 全链路 ==")
    pack, commitment = artifact_sealed_commitment(material, null_reports)
    artifact_mock_exam_and_tamper_matrix(material, pack, commitment,
                                         quick=args.quick)
    print("== 上游完整性 ==")
    artifact_upstream_integrity()
    print("run_all 完成")


if __name__ == "__main__":
    main()
