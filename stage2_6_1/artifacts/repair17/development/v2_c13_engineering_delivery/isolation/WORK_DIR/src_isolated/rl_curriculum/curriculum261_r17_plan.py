# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R17 plan 模块(轻量适配层)。

复用 curriculum261_r15_plan 的纯函数(digest 算法、锁定协议);
仅替换:代码模块清单(增加 R17 治理面模块)、状态路径(r17 状态
根)、iteration 标识。plan 格式版本沿用 cur261-r17-qualification-
plan 系列,digest 计算不变——R17 的 plan 以 iteration=="r17"
与 R15 区分。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r15_plan import (
    PLAN_CODE_MODULES_R15,
    lock_qualification_plan_r15,
    plan_digest_r15,
)
from rl_curriculum.curriculum261_r17_registry import (
    CURRICULUM261_ITERATION_ID_R17,
    qualification_r17_digest_path,
    qualification_r17_plan_path,
)
from rl_curriculum.curriculum261_r17_registry import (  # noqa: F401
    r17_state_root,
)

#: R17 代码身份模块清单 = R15 冻结清单 + R17 新治理/适配模块。
PLAN_CODE_MODULES_R17 = PLAN_CODE_MODULES_R15 + (
    "curriculum261_r17_calibration.py",
    "curriculum261_r17_cli.py",
    "curriculum261_r17_cue_contract.py",
    "curriculum261_r17_cue_eval.py",
    "curriculum261_r17_delegation.py",
    "curriculum261_r17_dependencies.py",
    "curriculum261_r17_design.py",
    "curriculum261_r17_determinism.py",
    "curriculum261_r17_execgov.py",
    "curriculum261_r17_fail_closure.py",
    "curriculum261_r17_final.py",
    "curriculum261_r17_final_core.py",
    "curriculum261_r17_full_cold.py",
    "curriculum261_r17_gate_topology.py",
    "curriculum261_r17_generation_evidence.py",
    "curriculum261_r17_global_k.py",
    "curriculum261_r17_historical.py",
    "curriculum261_r17_labels.py",
    "curriculum261_r17_registry.py",
    "curriculum261_r17_noise_replay.py",
    "curriculum261_r17_orchestrator.py",
    "curriculum261_r17_param_pack.py",
    "curriculum261_r17_plan.py",
    "curriculum261_r17_preflight.py",
    "curriculum261_r17_preplan.py",
    "curriculum261_r17_provenance.py",
    "curriculum261_r17_reference.py",
    "curriculum261_r17_rehearsal.py",
    "curriculum261_r17_routing.py",
    "curriculum261_r17_shadow.py",
    "curriculum261_r17_smoke.py",
    "curriculum261_r17_workflow.py",
)


def _code_identity_r17() -> dict[str, str]:
    """R17 冻结代码身份(模块 sha256 清单 + RouteCStrategy 身份)。"""
    import rl_curriculum
    from rl_curriculum.curriculum261_production_obs import (
        route_c_strategy_identity,
    )

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in PLAN_CODE_MODULES_R17:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    ident = route_c_strategy_identity()
    out["RouteCStrategy.py"] = ident["strategy_file_sha256"]
    out["RouteCStrategy.feature_engineering_standard"] = ident[
        "feature_engineering_standard_sha256"]
    return out


def load_locked_plan_r17(
        lock_dir: Path | None = None) -> tuple[dict[str, Any], str]:
    """加载锁定的 R17 qualification plan(digest 复算;fail closed)。

    lock_dir 缺省 = r17 状态根;显式传入时从该目录读取(rehearsal
    的临时 plan 目录用法)。
    """
    root = Path(lock_dir) if lock_dir is not None else r17_state_root()
    path = root / "qualification_plan_r17.json"
    dpath = root / "qualification_plan_digest_r17.txt"
    if not path.is_file() or not dpath.is_file():
        raise RuntimeError("R17 qualification plan 未锁定")
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R17:
        raise RuntimeError(
            f"plan iteration {plan.get('iteration')!r} != "
            f"{CURRICULUM261_ITERATION_ID_R17!r}(fail closed)")
    stored = plan.pop("plan_digest", None)
    digest = plan_digest_r15(plan)
    # 正式锁(R15 语义)的 plan JSON 不含 plan_digest 字段——digest
    # 权威在独立 txt;rehearsal 锁写入该字段,二者都与复算比对。
    if (stored is not None and stored != digest) or (
            dpath.read_text(encoding="utf-8").strip() != digest):
        raise RuntimeError("R17 plan digest 复算不一致(fail closed)")
    return plan, digest


def lock_qualification_plan_r17(
        lock_dir: Path, plan: dict[str, Any]) -> tuple[Path, str]:
    """把 R17 plan 锁进指定目录(O_EXCL 协议;禁覆盖;r17 文件名)。"""
    import json as _json
    import os as _os

    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R17:
        raise RuntimeError(
            "只允许锁定 iteration=r17 的 plan"
            f"(得到 {plan.get('iteration')!r})")
    lock_dir = Path(lock_dir)
    lock_dir.mkdir(parents=True, exist_ok=True)
    path = lock_dir / "qualification_plan_r17.json"
    digest = plan_digest_r15(plan)
    plan = dict(plan)
    plan["plan_digest"] = digest
    try:
        fd = _os.open(str(path), _os.O_CREAT | _os.O_EXCL | _os.O_WRONLY,
                      0o644)
    except FileExistsError as exc:
        raise RuntimeError(
            "rehearsal plan 已存在;禁止删除/覆盖/重锁(§21)") from exc
    try:
        _os.write(fd, _json.dumps(
            plan, indent=1, ensure_ascii=False,
            default=str).encode("utf-8"))
    finally:
        _os.close(fd)
    (lock_dir / "qualification_plan_digest_r17.txt").write_text(
        digest, encoding="utf-8")
    return path, digest


def build_rehearsal_qualification_plan_r17(
        *, pack: dict[str, Any], stage_summary: dict[str, Any],
        final_namespace: str,
        fit_namespace: str) -> tuple[dict[str, Any], str]:
    """§12 R17 rehearsal 精简 plan(临时目录;rt namespace;非正式)。"""
    plan = {
        "format": "cur261-r17-rehearsal-qualification-plan-v1",
        "iteration": CURRICULUM261_ITERATION_ID_R17,
        "rehearsal": True,
        "final_namespace": final_namespace,
        "fit_namespace": fit_namespace,
        "pack_digest": pack.get("digest"),
        "orchestrator": "orchestrate_calibration_stage_r17",
        "calibration_stage_pass": bool(stage_summary.get("pass")),
        "profiles": stage_summary.get("profiles"),
        "routing_matrix_all_pass": stage_summary.get(
            "routing_matrix_all_pass"),
        "supervised_main_pass": stage_summary.get("supervised_main_pass"),
        "supervised_holdout_pass": stage_summary.get(
            "supervised_holdout_pass"),
        "namespaces_preplan_only": True,
    }
    return plan, plan_digest_r15(plan)


#: re-export(机械转换后的 r17_cli 调用;领域实现复用 r15)。
from rl_curriculum.curriculum261_r15_plan import (  # noqa: E402,F401
    read_preprocessor_bundle_hash,
)


def build_plan_r17(**kwargs: Any) -> dict[str, Any]:
    """构建 R17 final qualification plan(复用 build_plan_r15 的
    全部构造与双 strict gate 前置;iteration 覆盖为 r17,
    code_identity 由调用方传入 _code_identity_r17() 结果)。"""
    from rl_curriculum.curriculum261_r15_plan import build_plan_r15

    plan = build_plan_r15(**kwargs)
    plan["iteration"] = CURRICULUM261_ITERATION_ID_R17
    # code_identity 覆盖为 R17 模块清单(31 个 r17 模块;
    # build_plan_r15 内部硬编码的是 R15 清单)
    plan["code_identity"] = _code_identity_r17()
    return plan


def lock_plan_r17(plan: dict[str, Any]) -> tuple[Path, str]:
    """正式锁(R15 lock_plan_r15 语义对齐:plan JSON 不含
    plan_digest 字段,digest 只存独立 txt;O_EXCL 禁覆盖)。"""
    import json as _json
    from datetime import datetime, timezone

    if plan.get("iteration") != CURRICULUM261_ITERATION_ID_R17:
        raise RuntimeError(
            "只允许锁定 iteration=r17 的 plan"
            f"(得到 {plan.get('iteration')!r})")
    plan = dict(plan)
    plan.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = r17_state_root() / "qualification_plan_r17.json"
    if path.is_file():
        raise RuntimeError(
            "R17 qualification plan 已存在;plan lock 后禁止重写(§16.2/"
            "§26:任何修改须新 iteration)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_json.dumps(plan, indent=2, ensure_ascii=False,
                                default=str), encoding="utf-8")
    digest = plan_digest_r15(plan)
    (r17_state_root() / "qualification_plan_digest_r17.txt").write_text(
        digest, encoding="utf-8")
    return path, digest


#: 别名(机械转换后的模块名)。
plan_digest_r17 = plan_digest_r15


def load_locked_qualification_plan_r17(
        lock_dir: Path) -> tuple[dict[str, Any], str]:
    """rehearsal loader(R15 语义:返回 plan 含 plan_digest 字段,
    供 payload_bit_identical 检查;正式路径用 load_locked_plan_r17)。"""
    plan, digest = load_locked_plan_r17(lock_dir)
    plan["plan_digest"] = digest
    return plan, digest


__all__ = [
    "PLAN_CODE_MODULES_R17",
    "_code_identity_r17",
    "load_locked_plan_r17",
    "lock_qualification_plan_r17",
    "build_rehearsal_qualification_plan_r17",
    "plan_digest_r15",
]
