# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:final 前两级 preflight(§26)。

A. Pre-Lock Static Preflight(plan lock 前执行;不触碰任何 final data):
   - 全部 R5 模块 import / final runner 依赖;
   - vendor 路径解析(R4 事故根因:parents[3] 错路径)+ vendor SHA/clean;
   - Route C identity / R5 code identity(无 MISSING);
   - 输出目录写权限;
   - V2 serialize/reload + outer env + SB3 check_env + PPO smoke
     (全部使用非 final namespace:ppo_smoke_r5);
   - final runner 静态路径 / 文件锁 / 原子 marker 行为(临时目录验证)。

B. Post-Lock Sealed Preflight(plan lock 后、final 前执行):
   - plan digest 重算、code identity、parameter pack、robustness
     evidence、vendor、输出权限、final runner 依赖;
   - **不派生任何 preprocess_fit_qualification_r5 / qualification_r5
     seed、不写 exposure marker**(本模块不调用 derive261_seed);
   - 生成 final_preflight_attestation(绑定 plan digest/code/vendor/
     runtime/时间/attestation digest);final runner 必须验证 attestation。
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


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def vendor_dir_default() -> Path:
    """final runner 使用的 vendor 目录(R4 事故修复后的正确路径)。"""
    return Path(__file__).resolve().parents[2] / "vendor" / "freqtrade"


def _vendor_state(vendor_dir: Path) -> dict[str, Any]:
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(vendor_dir),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        status = subprocess.run(
            ["git", "status", "--porcelain"], cwd=str(vendor_dir),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
        return {"path": str(vendor_dir), "exists": vendor_dir.is_dir(),
                "sha": sha, "clean": status == ""}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"path": str(vendor_dir), "exists": vendor_dir.is_dir(),
                "sha": "", "clean": False, "error": str(exc)[:200]}


def _runtime_identity() -> dict[str, str]:
    import platform

    import numpy as np
    import sklearn

    return {
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": np.__version__,
        "scikit_learn": sklearn.__version__,
    }


def _imports_ok() -> dict[str, Any]:
    """final runner 静态依赖 import 检查(不生成任何数据)。"""
    modules = [
        "rl_curriculum.curriculum261_r5_namespaces",
        "rl_curriculum.curriculum261_r5_param_pack",
        "rl_curriculum.curriculum261_r5_pairs",
        "rl_curriculum.curriculum261_r5_calibration",
        "rl_curriculum.curriculum261_r5_plan",
        "rl_curriculum.curriculum261_r5_final",
        "rl_curriculum.curriculum261_r5_smoke",
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


def _route_c_identity() -> dict[str, str]:
    from rl_platform.versions import (
        ENV_CORE_VERSION, OBSERVATION_SPEC_VERSION)

    return {"env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION}


def _code_identity_digest() -> dict[str, Any]:
    from rl_curriculum.curriculum261_r5_plan import _code_identity_r5

    ident = _code_identity_r5()
    missing = [k for k, v in ident.items() if v == "MISSING"]
    return {
        "identity": ident,
        "missing": missing,
        "digest": "r5ci-" + hashlib.sha256(
            _canonical(ident).encode("utf-8")).hexdigest(),
        "pass": not missing,
    }


# ---------------------------------------------------------- A: pre-lock
def run_prelock_static_preflight(out_dir: Path,
                                 vendor_pin: str) -> dict[str, Any]:
    """§26A:plan lock 前静态 preflight(只用非 final namespace)。"""
    out_dir = Path(out_dir)
    checks: dict[str, Any] = {}
    checks["imports"] = _imports_ok()

    vendor = _vendor_state(vendor_dir_default())
    checks["vendor"] = {
        **vendor,
        "pin_matches": bool(vendor.get("sha") == vendor_pin),
    }
    checks["vendor_ok"] = bool(
        vendor["exists"] and vendor["clean"]
        and vendor.get("sha") == vendor_pin)

    checks["route_c_identity"] = _route_c_identity()
    checks["code_identity"] = _code_identity_digest()

    # 写权限
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        probe = out_dir / ".preflight_write_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink()
        checks["output_write_permission"] = True
    except OSError:
        checks["output_write_permission"] = False

    # V2 + outer env + check_env + PPO smoke(ppo_smoke_r5,非 final)
    try:
        from rl_curriculum.curriculum261_r5_smoke import run_ppo_smoke_r5

        smoke = run_ppo_smoke_r5()
        checks["ppo_smoke_static"] = smoke
        checks["v2_serialize_reload_and_outer_env"] = bool(
            smoke["pass"]
            and smoke["checks"]["observation_space_unbounded"])
    except Exception as exc:  # noqa: BLE001
        checks["ppo_smoke_static"] = {"pass": False,
                                      "error": str(exc)[:300]}
        checks["v2_serialize_reload_and_outer_env"] = False

    # marker 原子行为 + 文件锁(临时目录,不触碰真实 lock dir)
    marker_ok = False
    lock_ok = False
    with tempfile.TemporaryDirectory() as td:
        import os

        old = os.environ.get("CURRICULUM261_R5_LOCK_DIR")
        os.environ["CURRICULUM261_R5_LOCK_DIR"] = td
        try:
            from rl_curriculum.curriculum261_r5_namespaces import (
                QualificationR5FileLock,
                write_qualification_r5_exposure,
            )

            write_qualification_r5_exposure("r5dp-preflight-probe",
                                            "running")
            try:
                write_qualification_r5_exposure("r5dp-preflight-probe",
                                                "running")
                double_create_rejected = False
            except RuntimeError:
                double_create_rejected = True
            marker_ok = bool(double_create_rejected)
            try:
                with QualificationR5FileLock(blocking=False):
                    with QualificationR5FileLock(blocking=False):
                        pass
                concurrent_lock_rejected = False
            except RuntimeError:
                concurrent_lock_rejected = True
            lock_ok = bool(concurrent_lock_rejected)
        finally:
            if old is None:
                os.environ.pop("CURRICULUM261_R5_LOCK_DIR", None)
            else:
                os.environ["CURRICULUM261_R5_LOCK_DIR"] = old
    checks["marker_atomic_exclusive"] = marker_ok
    checks["concurrent_final_lock_rejected"] = lock_ok

    result = {
        "format": "cur261-r5-prelock-static-preflight-v1",
        "iteration": "r5",
        "executed_utc": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "namespaces_touched": ["ppo_smoke_r5"],
        "final_namespaces_touched": [],
        "vendor_pin_expected": vendor_pin,
        "checks": checks,
        "pass": bool(
            checks["imports"]["pass"] and checks["vendor_ok"]
            and checks["code_identity"]["pass"]
            and checks["output_write_permission"]
            and checks["v2_serialize_reload_and_outer_env"]
            and marker_ok and lock_ok),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "prelock_static_preflight.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8")
    return result


# ---------------------------------------------------------- B: sealed
def sealed_preflight_digest(att: dict[str, Any]) -> str:
    payload = {k: v for k, v in att.items() if k != "digest"}
    return "r5fa-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def run_postlock_sealed_preflight(out_dir: Path,
                                  vendor_pin: str,
                                  ) -> dict[str, Any]:
    """§26B:plan lock 后 sealed preflight。

    不得派生任何 final namespace seed(本函数不调用 derive261_seed;
    由测试 monkeypatch 锁定);不得写 exposure marker。
    """
    from rl_curriculum.curriculum261_r5_namespaces import (
        qualification_r5_plan_path,
        qualification_r5_digest_path,
        r5_parameter_pack_path,
    )
    from rl_curriculum.curriculum261_r5_plan import (
        _code_identity_r5,
        load_locked_plan_r5,
    )
    from rl_curriculum.curriculum261_r5_param_pack import (
        load_selected_pack,
        verify_r4_inheritance,
    )

    checks: dict[str, Any] = {}
    plan, plan_digest = load_locked_plan_r5()
    checks["plan_digest_recompute"] = True
    checks["plan_iteration_r5"] = bool(plan.get("iteration") == "r5")
    checks["robustness_gate_pass_recorded"] = bool(
        (plan.get("robustness_gate") or {}).get("pass") is True)

    pack = load_selected_pack(Path(out_dir))
    checks["parameter_pack_bound"] = bool(
        pack["digest"] == plan["parameter_pack"]["digest"])
    checks["r4_inheritance_verified"] = verify_r4_inheritance(pack)

    # robustness evidence 文件存在且 pass
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

    ident = _code_identity_r5()
    missing = [k for k, v in ident.items() if v == "MISSING"]
    checks["code_identity_matches_plan"] = bool(
        not missing and plan["code_identity"] == ident)
    code_digest = "r5ci-" + hashlib.sha256(
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

    checks["final_runner_dependencies"] = _imports_ok()["pass"]
    checks["plan_path_resolves"] = bool(
        qualification_r5_plan_path().is_file()
        and qualification_r5_digest_path().is_file()
        and r5_parameter_pack_path().is_file())

    att_pass = bool(all(
        v is True for k, v in checks.items()
        if isinstance(v, bool)))

    attestation = {
        "format": "cur261-r5-sealed-final-preflight-v1",
        "iteration": "r5",
        "pass": att_pass,
        "plan_digest": plan_digest,
        "parameter_pack_digest": pack["digest"],
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


def verify_sealed_attestation(out_dir: Path) -> dict[str, Any]:
    """final runner 用的 attestation 验证(digest 复算 + plan 绑定)。"""
    from rl_curriculum.curriculum261_r5_namespaces import (
        sealed_preflight_path,
        sealed_preflight_digest_path,
    )

    path = sealed_preflight_path()
    digest_path = sealed_preflight_digest_path()
    if not path.is_file() or not digest_path.is_file():
        return {"pass": False,
                "error": "sealed preflight attestation 不存在"}
    att = json.loads(path.read_text(encoding="utf-8"))
    digest_ok = sealed_preflight_digest(att) == att.get("digest")
    file_ok = digest_path.read_text(encoding="utf-8").strip() \
        == att.get("digest")
    pass_ok = att.get("pass") is True
    clean_ok = (att.get("final_seed_derivations_performed") == 0
                and not att.get("final_namespaces_touched"))
    return {
        "pass": bool(digest_ok and file_ok and pass_ok and clean_ok),
        "digest_recompute": bool(digest_ok),
        "digest_file_match": bool(file_ok),
        "attestation_pass": bool(pass_ok),
        "no_final_seed_access": bool(clean_ok),
        "attestation": att,
    }
