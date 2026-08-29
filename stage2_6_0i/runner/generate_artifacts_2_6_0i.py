"""阶段 2.6.0i artifacts 生成(18 项)。

在项目根运行:python generate_artifacts_2_6_0i.py
输出:artifacts/route_c_stage2_6_0i/*.json(+ 回归脚本填充的
regression_test_summary.md / regression_raw.log / upstream_integrity.txt)

清单(对应任务书第十四节):
 1. runtime_environment_bundle_manifest.json
 2. runtime_bundle_tree_digest.json
 3. actual_import_file_closure.json
 4. namespace_package_owner_matrix.json
 5. package_data_access_matrix.json
 6. record_extra_file_attack.json
 7. clock_attack_matrix.json
 8. entropy_attack_matrix.json
 9. host_file_visibility_matrix.json
10. seccomp_arch_x32_matrix.json
11. thread_quiescence_report.json
12. runtime_bundle_toctou_matrix.json
13. builder_evidence_v3.json
14. legacy_2_6_0h_material_rejection.json
15. full_private_pipeline_next_protocol.json
16-18. regression_test_summary.md / regression_raw.log /
    upstream_integrity.txt(由回归脚本填充)
"""

from __future__ import annotations

import copy
import json
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(ROOT / "tests"))
sys.path.insert(0, str(ROOT / "tests" / "route_c_stage2_6_0i"))

OUT = ROOT / "artifacts" / "route_c_stage2_6_0i"
OUT.mkdir(parents=True, exist_ok=True)

FAMS = ["probe_null_sign", "probe_null_volstate", "probe_null_stochvol"]

results: dict[str, dict] = {}


def _write(name: str, payload) -> None:
    if not isinstance(payload, dict):
        payload = {"result": payload}
    (OUT / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    print("OK", name)


def _attack_run(body, tmp, *, label="artifact", external_dependencies=None,
                profile=None):
    from conftest import write_attack_builder
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
    )
    from rl_curriculum.builder_runner import (
        BuilderRunnerProfile,
        run_isolated_builder_run,
    )
    from rl_curriculum.mock_sealed_exam import assemble_mock_hidden_pack
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )

    root = write_attack_builder(
        tmp / label, body, max_attempts=1,
        external_dependencies=external_dependencies
        if external_dependencies is not None else [], label=label)
    provider = private_provider_from_root(root)
    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        seed, required_families=FAMS)
    request = provider.frozen_build_request(seed, dc)
    try:
        return {"ok": True, "run": run_isolated_builder_run(
            provider.builder_identity(), request, builder_root=root,
            profile=profile or BuilderRunnerProfile())}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error_type": type(exc).__name__,
                "error": str(exc)[:400]}


def main() -> None:  # noqa: C901(审计生成器,分支即清单)
    import hashlib

    tmp = Path(tempfile.mkdtemp(prefix="artifacts-0i-"))
    try:
        # ------------------------------------------------ 1/2 bundle manifest
        from rl_builder_runtime.bundle import (
            assemble_runtime_bundle,
            bundle_manifest_digest,
            deterministic_entropy_bytes,
            load_bundle_manifest,
            load_bundle_meta,
            verify_runtime_bundle,
        )
        import rl_builder_runtime

        staging = Path.home() / ".cache" / "rl_builder_bundles" / \
            f"artifact-chain-{int(__import__('time').monotonic()*1000)}"
        staging.parent.mkdir(parents=True, exist_ok=True)
        if staging.exists():
            shutil.rmtree(staging)
        pkg = tmp / "bp"
        pkg.mkdir()
        (pkg / "builder_x.py").write_text("def build_pack(r):\n"
                                          "    return 1\n")
        info = assemble_runtime_bundle(
            env_root=Path(sys.executable).parent.parent,
            staging_root=staging,
            runtime_src=Path(rl_builder_runtime.__file__).parent,
            builder_pkg_root=pkg, jobs=4)
        manifest = info["manifest"]
        entry_stats = {
            "files": sum(1 for e in manifest["entries"]
                         if e.get("type") == "file"),
            "symlinks": sum(1 for e in manifest["entries"]
                            if e.get("type") == "symlink"),
            "dirs": sum(1 for e in manifest["entries"]
                        if e.get("type") == "dir"),
        }
        _write("runtime_environment_bundle_manifest.json", {
            "format": "runtime-environment-bundle-manifest-artifact",
            "manifest_digest": info["digest"],
            "entry_stats": entry_stats,
            "syslib_sonames": manifest["syslib_sonames"],
            "rpath_resolved_names": manifest["rpath_resolved_names"],
            "deterministic_entropy_sha256": hashlib.sha256(
                deterministic_entropy_bytes()).hexdigest(),
            "excludes": {
                "dirs": ["__pycache__"], "suffixes": [".pyc", ".pyo"],
            },
            "manifest_entries_sample": manifest["entries"][:8],
            "manifest_entries_count": len(manifest["entries"]),
            "note": "完整逐文件 manifest 见同目录 manifest.full.json.gz",
        })
        full = (OUT / "manifest.full.json.gz")
        import gzip

        with gzip.open(full, "wt", encoding="utf-8") as fh:
            json.dump(manifest, fh, ensure_ascii=False)
        verify = verify_runtime_bundle(
            staging, {k: v for k, v in manifest.items()
                      if k != "manifest_digest"}, jobs=4,
            expect_digest=info["digest"])
        _write("runtime_bundle_tree_digest.json", {
            "digest": info["digest"],
            "verify_after_assembly": verify,
            "verify_after_run_pending": "见 toctou 矩阵",
        })

        # ------------------------------------------------ 3 导入闭包(numpy)
        import numpy

        r = _attack_run(
            "    import numpy as np\n"
            "    v = float(np.random.default_rng(7).random())\n"
            "    notes = {'v': v}\n",
            tmp, label="np-closure",
            external_dependencies=[{"module": "numpy",
                                    "version": numpy.__version__}])
        assert r["ok"], r
        lock = r["run"]["runtime_lock"]
        closure = lock["import_closure"]
        _write("actual_import_file_closure.json", {
            "format": "actual-import-file-closure-artifact",
            "modules_bound": len(closure),
            "file_backed": sum(1 for e in closure
                               if e.get("origin_kind") == "file"),
            "distributions": [
                {"module": d["module"], "distribution": d["distribution"],
                 "version": d["version"], "file": d["file"],
                 "sha256": d["sha256"]} for d in lock["distributions"]],
            "native_libraries_count": len(lock["native_libraries"]),
            "native_origin": sorted({n["origin"] for n in
                                     lock["native_libraries"]}),
            "closure_sample": closure[:10],
            "environment_identity": lock.get("environment_identity"),
        })

        # ------------------------------------------------ 4 namespace owner
        meta = info["meta"]
        _write("namespace_package_owner_matrix.json", {
            "format": "namespace-owner-matrix-artifact",
            "by_path_ownership_entries": len(meta["dist_ownership"]),
            "ambiguous_paths": meta["ambiguous_dist_paths"],
            "ownership_sample": dict(sorted(
                meta["dist_ownership"].items())[:12]),
            "note": "owner 由实际文件路径决定(RECORD 为辅助元数据;"
                    "多义路径在导入闭包 fail closed)",
        })

        # ------------------------------------------------ 5 package data
        r2 = _attack_run(
            "    import os\n"
            "    data = open('/lib/python3.11/site-packages/numpy"
            "/version.py').read()\n"
            "    notes = {'len': len(data)}\n",
            tmp, label="pkg-data",
            external_dependencies=[{"module": "numpy",
                                    "version": numpy.__version__}])
        assert r2["ok"], r2
        _write("package_data_access_matrix.json", {
            "format": "package-data-access-artifact",
            "numpy_version_py_readable_inside_bundle": True,
            "pack_hash": r2["run"]["pack_hash"],
            "bundle_digest": r2["run"]["runtime_bundle_hash"],
            "note": "bundle 内 package data 可读且全部进入 manifest;"
                    "bundle 外 data 因 pivot 不可命名(见可见性矩阵)",
        })

        # ------------------------------------------------ 6 E1 RECORD 外文件
        # (a) 组装前加入 env -> 进 manifest(绑定)
        staging2 = staging.parent / (staging.name + "-e1")
        hidden_rel = "lib/python3.11/site-packages/numpy/_hidden_test.py"
        hidden_src = Path(sys.executable).parent.parent / hidden_rel
        wrote = False
        try:
            if not hidden_src.exists():
                hidden_src.write_text("HIDDEN = 1\n")
                wrote = True
            info2 = assemble_runtime_bundle(
                env_root=Path(sys.executable).parent.parent,
                staging_root=staging2,
                runtime_src=Path(rl_builder_runtime.__file__).parent,
                builder_pkg_root=pkg, jobs=4)
            bound = any(e["path"] == hidden_rel
                        for e in info2["manifest"]["entries"])
            digest_changed = info2["digest"] != info["digest"]
        finally:
            if wrote and hidden_src.exists():
                hidden_src.unlink()
        # (b) 组装后加入 staging -> 复验拒绝
        (staging / "lib/python3.11/site-packages" /
         "_extra_after_assembly.py").write_text("X = 1\n")
        try:
            verify_extra = verify_runtime_bundle(
                staging, {k: v for k, v in manifest.items()
                          if k != "manifest_digest"}, jobs=4)
            extra_rejected = False
        except Exception as exc:  # noqa: BLE001
            verify_extra = str(exc)[:200]
            extra_rejected = True
        (staging / "lib/python3.11/site-packages" /
         "_extra_after_assembly.py").unlink()
        _write("record_extra_file_attack.json", {
            "before_assembly_added_to_env": {
                "bound_in_manifest": bound,
                "digest_changed": digest_changed},
            "after_assembly_added_to_staging": {
                "rejected": extra_rejected,
                "detail": verify_extra},
        })

        # ------------------------------------------------ 7 E5 时钟矩阵
        clock_matrix = {}
        for name, body in (
            ("time_time", "    import time\n"
             "    notes = {'t': time.time()}\n"),
            ("datetime_now", "    import datetime\n"
             "    notes = {'y': datetime.datetime.now().year}\n"),
            ("monotonic", "    import time\n"
             "    notes = {'m': time.monotonic()}\n"),
            ("perf_counter", "    import time\n"
             "    notes = {'p': time.perf_counter()}\n"),
        ):
            rr = _attack_run(body, tmp, label=f"clk-{name}")
            clock_matrix[name] = {
                "run_ok": rr["ok"],
                "frozen_time": rr["run"]["deterministic_input_report"]
                ["clock"]["behavior"]["time_time"] if rr["ok"] else None,
                "frozen_year": rr["run"]["deterministic_input_report"]
                ["clock"]["behavior"]["datetime_now_year"]
                if rr["ok"] else None}
        for name, body in (
            ("raw_clock_gettime",
             "    import ctypes\n"
             "    libc = ctypes.CDLL(None, use_errno=True)\n"
             "    rc = libc.syscall(228, 0, 0)\n"
             "    raise RuntimeError('denied' if rc != 0 else 'LEAK')\n"),
            ("rdtsc",
             "    import ctypes\n"
             "    libc = ctypes.CDLL(None, use_errno=True)\n"
             "    libc.mmap.restype = ctypes.c_void_p\n"
             "    page = libc.mmap(None, 4096, 7, 0x22, -1, 0)\n"
             "    ctypes.memmove(page, b'\\x0f\\x31\\xc3', 3)\n"
             "    fn = ctypes.CFUNCTYPE(ctypes.c_uint64)(page)\n"
             "    notes = {'tsc': fn()}\n"),
        ):
            rr = _attack_run(body, tmp, label=f"clk-{name}")
            clock_matrix[name] = {
                "run_ok": rr["ok"],
                "rejected": (not rr["ok"])
                and rr.get("error_type") in (
                    "BuilderRunnerError", "BuilderProvenanceError"),
                "error_stage": rr.get("error", "")[:120]}
        vdso_sample = _attack_run("    pass\n", tmp, label="clk-vdso")
        clock_matrix["vdso_stub"] = vdso_sample["run"][
            "deterministic_input_report"]["clock"]["vdso"] \
            if vdso_sample["ok"] else None
        _write("clock_attack_matrix.json", clock_matrix)

        # ------------------------------------------------ 8 E6 熵矩阵
        entropy_matrix = {}
        for name, body in (
            ("os_urandom", "    import os\n"
             "    notes = {'u': os.urandom(16).hex()}\n"),
            ("secrets", "    import secrets\n"
             "    notes = {'s': secrets.token_hex(8)}\n"),
            ("systemrandom", "    import random\n"
             "    notes = {'r': random.SystemRandom().random()}\n"),
            ("numpy_unseeded", "    import numpy as np\n"
             "    notes = {'v': float(np.random.default_rng()"
             ".random())}\n"),
        ):
            rA = _attack_run(body, tmp, label=f"ent-{name}-a",
                             external_dependencies=[
                                 {"module": "numpy",
                                  "version": numpy.__version__}
                                 if "numpy" in body else None][0:1]
             if "numpy" in body else None)
            rB = _attack_run(body, tmp, label=f"ent-{name}-b",
                             external_dependencies=[
                                 {"module": "numpy",
                                  "version": numpy.__version__}]
             if "numpy" in body else None)
            entropy_matrix[name] = {
                "run_ok": rA["ok"] and rB["ok"],
                "deterministic_across_processes":
                    rA["run"]["pack_hash"] == rB["run"]["pack_hash"]
                    if rA["ok"] and rB["ok"] else None,
                "getrandom": rA["run"]["deterministic_input_report"]
                ["entropy"]["getrandom"] if rA["ok"] else None,
                "dev_urandom_deterministic":
                    rA["run"]["deterministic_input_report"]["entropy"]
                    ["dev_urandom_deterministic"] if rA["ok"] else None}
        rr = _attack_run(
            "    import ctypes\n"
            "    libc = ctypes.CDLL(None, use_errno=True)\n"
            "    buf = ctypes.create_string_buffer(8)\n"
            "    rc = libc.syscall(318, buf, 8, 0)\n"
            "    raise RuntimeError('denied' if rc != 0 else 'LEAK')\n",
            tmp, label="ent-getrandom")
        entropy_matrix["getrandom_raw"] = {
            "rejected": not rr["ok"],
            "error": rr.get("error", "")[:120]}
        _write("entropy_attack_matrix.json", entropy_matrix)

        # ------------------------------------------------ 9 E7 宿主可见性
        host_matrix = {}
        for path in ("/etc/hostname", "/usr", "/home", "/sys",
                     "/proc/self/status", "/etc/beacon-not-exist",
                     str(Path(sys.executable).resolve()),
                     str(Path.home() / ".bashrc")):
            probe = "ENOENT"
            try:
                Path(path).stat()
                probe = "HOST_EXISTS"
            except FileNotFoundError:
                pass
            except OSError:
                probe = "HOST_ERR"
            host_matrix[path] = probe
        hv = _attack_run("    pass\n", tmp, label="host-vis")
        edic = hv["run"]["deterministic_input_report"]
        _write("host_file_visibility_matrix.json", {
            "worker_side_probes": edic["probes"],
            "proc": edic["proc"], "dev": edic["dev"],
            "hostname": edic["uts_hostname"],
            "host_side_reference": host_matrix,
            "environment_identity": edic["environment"],
            "note": "Worker 内全部 ENOENT(pivot 后不可命名);"
                    "HOST_EXISTS 表示宿主确有该路径(对照)",
        })

        # ------------------------------------------------ 10 E8 seccomp 矩阵
        from rl_builder_runtime.runner import (
            canonical_seccomp_filter,
            install_seccomp_filter,
            seccomp_filter_digest,
        )
        _write("seccomp_arch_x32_matrix.json", {
            "filter_digest": seccomp_filter_digest(),
            "filter_instructions": len(canonical_seccomp_filter()),
            "arch_check": canonical_seccomp_filter()[1]["k"] == 0xC000003E,
            "x32_check": "见 tests/route_c_stage2_6_0i/"
                         "test_seccomp_arch_x32.py(raw syscall 实测)",
            "x32_native_kernel_support": "本内核原生支持 x32 fork"
            "(无 filter 基线实测创建孙进程;filter 后 EPERM)",
            "policy": "builder-seccomp-policy-v2",
        })

        # ------------------------------------------------ 11 E9 线程静止
        tq = _attack_run(
            "    import threading\n"
            "    try:\n"
            "        threading.Thread(target=lambda: None).start()\n"
            "    except (RuntimeError, OSError):\n"
            "        pass\n",
            tmp, label="thread-swallow")
        assert tq["ok"], tq
        edic_tq = tq["run"]["deterministic_input_report"]
        _write("thread_quiescence_report.json", {
            "thread_policy": edic_tq["thread_policy"],
            "clone_probe": edic_tq["probes"]["clone_thread_denied"],
            "threads_at_quiesce": edic_tq["supervisor"]["thread_count"],
            "task_comms": edic_tq["supervisor"]["task_comms"],
            "child_processes": edic_tq["supervisor"][
                "child_process_count"],
        })

        # ------------------------------------------------ 12 E10 TOCTOU
        victim = staging / "lib/python3.11/os.py"
        original = victim.read_bytes()
        toctou = {}
        try:
            victim.write_bytes(original + b"# tamper\n")
            try:
                verify_runtime_bundle(
                    staging, {k: v for k, v in manifest.items()
                              if k != "manifest_digest"}, jobs=4)
                toctou["content_tamper_detected"] = False
            except Exception as exc:  # noqa: BLE001
                toctou["content_tamper_detected"] = True
                toctou["content_tamper_detail"] = str(exc)[:160]
        finally:
            victim.write_bytes(original)
        # 硬链接别名:改源 env 文件(同 inode)
        src_os = Path(sys.executable).parent.parent / \
            "lib/python3.11/os.py"
        if src_os.stat().st_ino == (staging / "lib/python3.11/os.py") \
                .stat().st_ino:
            orig_src = src_os.read_bytes()
            try:
                src_os.write_bytes(orig_src + b"# alias\n")
                try:
                    verify_runtime_bundle(
                        staging,
                        {k: v for k, v in manifest.items()
                         if k != "manifest_digest"}, jobs=4)
                    toctou["hardlink_alias_tamper_detected"] = False
                except Exception:  # noqa: BLE001
                    toctou["hardlink_alias_tamper_detected"] = True
            finally:
                src_os.write_bytes(orig_src)
        else:
            toctou["hardlink_alias_tamper_detected"] = \
                "staging-not-hardlinked(skipped)"
        toctou["restore_verify"] = verify_runtime_bundle(
            staging, {k: v for k, v in manifest.items()
                      if k != "manifest_digest"}, jobs=4,
            expect_digest=info["digest"])
        _write("runtime_bundle_toctou_matrix.json", toctou)

        # --------------------------------------- 13/14/15 完整链路材料
        _write_pipeline_artifacts(tmp)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
        for s in (staging, staging2):
            shutil.rmtree(s, ignore_errors=True)
    print("ALL ARTIFACTS DONE")


def _write_pipeline_artifacts(tmp: Path) -> None:
    """13 evidence v3 / 14 旧材料拒绝 / 15 完整链路摘要。"""
    from rl_curriculum.attestation import (
        Ed25519KeyPair,
        TrustedIssuerConfig,
    )
    from rl_curriculum.builder_evidence import (
        BuilderProvenanceError,
        builder_run_evidence_hash,
        precommit_builder_runs,
        verify_builder_run_evidence,
    )
    from rl_curriculum.mock_sealed_exam import (
        assemble_mock_hidden_pack,
        build_mock_commitment,
    )
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract,
    )
    from tests.route_c_stage2_6_0c.conftest import (
        MOCK_TRAINING_RUNNER_HASH,
    )
    from tests.route_c_stage2_6_0f.conftest import (
        private_provider_from_root,
        write_private_builder,
    )

    d = tmp / "chain"
    root = write_private_builder(d / "private_builder_40",
                                 label="private-builder-40")
    cfgj = json.loads((root / "provider_config.json").read_text())
    cfgj["pair_count_per_family"] = 40
    cfgj["max_attempts"] = 5
    (root / "provider_config.json").write_text(json.dumps(cfgj))
    provider = private_provider_from_root(root)
    seed = assemble_mock_hidden_pack()
    dc = derive_global_null_duration_contract(
        seed, required_families=FAMS)
    probe_req = provider.frozen_build_request(seed, dc)
    _ev, probe_runs = precommit_builder_runs(
        provider, probe_req, builder_root=provider.root)
    pack = probe_runs[0]["pack"]
    dc = derive_global_null_duration_contract(pack, required_families=FAMS)
    req = provider.frozen_build_request(pack, dc)
    evidence, runs = precommit_builder_runs(
        provider, req, builder_root=provider.root)
    _write("builder_evidence_v3.json", {
        "format": "builder-run-evidence-v3-artifact",
        "evidence_hash": evidence["evidence_hash"],
        "core": {k: evidence[k] for k in (
            "mode", "deterministic_input_hash", "runtime_bundle_hash",
            "thread_policy", "process_tree_policy", "child_process_count",
            "exec_count", "runner_isolation", "output_pack_hash",
            "runtime_lock_hash", "attempt_log_hash")},
        "runs_consistency": evidence["runs"],
        "pack_hash": runs[0]["pack_hash"],
    })
    # 14:旧 0h 材料重签拒绝
    legacy = copy.deepcopy(evidence)
    legacy.pop("deterministic_input_hash", None)
    legacy.pop("runtime_bundle_hash", None)
    legacy.pop("thread_policy", None)
    legacy["effective_sandbox_hash"] = "esb-" + "9" * 64
    legacy["detail"].pop("deterministic_input_report", None)
    legacy["detail"]["sandbox_report"] = {"seccomp_mode": 2}
    legacy["evidence_hash"] = builder_run_evidence_hash(legacy)
    from rl_curriculum.sealed_exam import SealedExamCommitment

    summary = {k: v for k, v in legacy.items()
               if k not in ("detail", "evidence_hash")}
    rejected = None
    try:
        verify_builder_run_evidence(
            legacy, commitment=type(
                "C", (), {"builder_run_evidence": summary,
                          "pack_hash": legacy["output_pack_hash"]})(),
            identity=type("I", (), {"manifest_hash": "",
                                    "tree_hash": "",
                                    "manifest": {}})(),
            request_hash=legacy["frozen_request_hash"])
        rejected = False
    except BuilderProvenanceError as exc:
        rejected = str(exc)[:200]
    _write("legacy_2_6_0h_material_rejection.json", {
        "reshaped_v2_evidence_rejected": rejected is not False,
        "rejection": rejected,
    })
    # 15:完整链路(承诺 v10 绑定)
    from rl_curriculum.probe_charter import audit_probe_charter
    from rl_curriculum.verdict_spec import probe_course_verdict_spec
    from rl_curriculum.mock_sealed_exam import default_eval_config
    from rl_curriculum.probe_charter import probe_observation_schema
    from rl_curriculum.sandbox import default_sandbox_profile
    from rl_curriculum.null_qualification import (
        build_null_qualification_bindings,
    )
    from null_qual_cache import cached_null_qual_chain

    schema = probe_observation_schema()
    cfg = default_eval_config()
    nq = cached_null_qual_chain(schema, cfg)
    from rl_curriculum.null_pack_validation import (
        build_spec_for_pack, validate_null_pack,
    )
    from rl_curriculum.null_duration_contract import (
        derive_global_null_duration_contract as _dg,
    )
    contract = _dg(pack, required_families=FAMS)
    spec = build_spec_for_pack(
        cfg, timeframe=contract["timeframe"],
        episode_bars=int(contract["resolved_bars"]))
    by_family = {}
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    for s in pack.episodes:
        if s.split == "null_control":
            by_family.setdefault(s.family, []).append(
                R[s.family].generate(dict(s.params), s.seed,
                                     split=s.split,
                                     timeframe=s.timeframe))
    pv = validate_null_pack(
        by_family, cfg=cfg, schema=schema, spec=spec,
        pack_hash=pack.pack_hash(),
        builder_identity=provider.builder_identity(),
        duration_contract=contract)
    assert pv["verdict"] == "PACK_VALID", pv.get("reasons", [])[:2]
    keypair = Ed25519KeyPair.generate("mock-issuer-0i-artifact")
    issuer = TrustedIssuerConfig.from_keypair(
        keypair, required_training_runner_hash=MOCK_TRAINING_RUNNER_HASH,
        allow_smoke=False)
    ev_path = d / "builder_evidence.json"
    from rl_curriculum.builder_evidence import write_builder_run_evidence

    write_builder_run_evidence(ev_path, evidence)
    commitment = build_mock_commitment(
        pack=pack, charter=audit_probe_charter(), schema=schema,
        verdict_spec=probe_course_verdict_spec(), eval_config=cfg,
        sandbox_profile=default_sandbox_profile(),
        trusted_issuer=issuer,
        null_qualification_bindings=build_null_qualification_bindings(
            nq["reports"]),
        power_analysis_report=nq["power_report"],
        pack_validity_report=pv,
        builder_provider=provider,
        evidence_path=str(ev_path))
    _write("full_private_pipeline_next_protocol.json", {
        "commitment_protocol": json.loads(commitment.to_json())
                        ["protocol_version"],
        "cli_version": "hidden-exam-cli-v11",
        "pack_hash": commitment.pack_hash,
        "builder_attempt_policy": commitment.builder_attempt_policy,
        "evidence_hash": evidence["evidence_hash"],
        "runtime_bundle_hash": evidence["runtime_bundle_hash"],
        "deterministic_input_hash": evidence["deterministic_input_hash"],
        "pair_count_per_family": 40, "max_attempts": 5,
        "note": "完整 256-step PPO 考试链路由 "
                "tests/route_c_stage2_6_0i/test_full_private_pipeline_"
                "v10.py 驱动(正式 FAIL + 篡改 EXAM_INVALID)",
    })


if __name__ == "__main__":
    main()
