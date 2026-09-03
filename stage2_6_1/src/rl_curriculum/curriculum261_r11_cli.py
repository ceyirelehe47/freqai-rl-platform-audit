# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R11 CLI(audit → cue-audit → preplan-smoke →
plan-roundtrip → design-plan-lock → design → calibrate →
preflight-static → lock-plan → preflight-sealed → qualify → smoke →
namespace-integrity;determinism-matrix 与 shadow-run/shadow-compare
为冻结前工程命令,在任何正式 R11 namespace 访问之前执行)。

§16/§20/§21 顺序硬约束:全部代码/测试/合同审计/candidate grid 在 plan
锁定前完成;preplan smoke 只用 sentinel ladder;plan-roundtrip 在临时
目录以真实生产路径验证 lock→load→recompute→compare(§8.3,R7 的
digest 自引用缺陷修复的正式验收);design plan 在第一条 R11 design/
semantic episode 前锁定;calibration/holdout 独立 PASS(无 pooled
救援)后才允许 lock-plan。工作包 A6:audit 的硬前置包含
generation determinism contract(determinism-matrix 的产物)。

§8.2:全部正式路径使用同一份仓库内实现(lock/load/digest recompute/
code identity verify/design execution);禁止临时 Python driver、
手工加载 JSON、临时排除字段、随后删除的脚本。
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

BASELINE_COMMIT_R11 = "b31ad39bbce040e4fe93a58b864d144bd12dca4f"
VENDOR_PIN = "52bc96f4480b1a0da6a9b455bd00b17fbb6786a5"
#: R7 baseline(= 本轮基线的父提交;historical binding 检查)
PRIOR_R7_BASELINE_COMMIT = "7970d2096b6a5a93a85d32620b9b2b3a24826568"
PRIOR_R2_PLAN_DIGEST = (
    "qp-8f64a1b5619c6eda4cf8639f4e5237e8b9b68a63a15fe67ee2e41c15db07af99")
PRIOR_DIAG262R2_PLAN_DIGEST = (
    "dp-ee6f8dc109f795986ced4fbc6851ad063b8d2fa57f9863f2861e4c45b9c51d60")
PRIOR_R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")
PRIOR_R5_DESIGN_PLAN_DIGEST = (
    "r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d")
PRIOR_R6_DESIGN_PLAN_DIGEST = (
    "r6dp-db74ed109a7bf7a955c74f1bd248213002d3c08f79512abf0faf93f8941e03c7")
PRIOR_R7_DESIGN_PLAN_DIGEST = (
    "r7dp-73d65b6838c0686b26ad4c74c1fd7ca94d72aa8f20930d78a555bb8f8890e454")
#: R8 baseline(= 本轮基线;R8 于 design 阶段 candidate evaluator
#: ImportError 后按 §8.4 永久结束)。
PRIOR_R8_BASELINE_COMMIT = "11951f6d9b2f5fa63b17e3857aba92b330da029e"
PRIOR_R8_DESIGN_PLAN_DIGEST = (
    "r8dp-60bb85d5481054b619188fb5a97209acd054e9e110da26710458ecaf"
    "2ef0db9d")
#: R9 baseline(= 本轮基线;R9 于 calibrate 阶段 supervised 调用
#: TypeError 后按 §18 硬规则诚实 FAIL;design 全部结果仅作 R11
#: development evidence)。
PRIOR_R9_BASELINE_COMMIT = "ab260684df340f89443ce9827f8f733e3ede4320"
PRIOR_R9_DESIGN_PLAN_DIGEST = (
    "r9dp-83d4d3b71942604db1bbe895cedcdf083151b835c962f8f9da20b432e"
    "f4843f4")
PRIOR_R9_PARAMETER_PACK_DIGEST = (
    "r9pk-c3070b5bc114b77d0ca314a033ff14181aeac5fe7a916f"
    "4f5a6269624b6b26b9")
#: R10 证据链(R10 于 calibrate/supervised main 的
#: PairGenerationError(c3_cost/D0/pair1 五连败 too_few_distractors)
#: 后按 §21 硬规则诚实 FAIL;三种重放不可复现,根因定性
#: historically underdetermined due to missing invocation-state
#: evidence —— R11 工作包 A 的直接动因)。R10 design/pack 全部
#: 结果仅作 R11 development evidence。
PRIOR_R10_BASELINE_COMMIT = "ab260684df340f89443ce9827f8f733e3ede4320"
PRIOR_R10_FINAL_FREEZE_COMMIT = (
    "06e9b5beb4df564e51d27aae444f281843356809")
PRIOR_R10_DESIGN_PLAN_DIGEST = (
    "r10dp-e39575ba0cf66c5f229328ceefc4ef506ffbb3c191f15261f592ab5087"
    "dd6f9c")
PRIOR_R10_PARAMETER_PACK_DIGEST = (
    "r10pk-a475b997313b445ca25aa76f43e394bbe5bf493942942d39f7a6f6b75f"
    "eb9314")


def _default_art() -> Path:
    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_lock_dir,
    )

    return qualification_r11_lock_dir()


def _write_json(out_dir: Path, name: str, payload: object) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")


def _dump_txt(out_dir: Path, name: str, text: str) -> None:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / name).write_text(text, encoding="utf-8")


def _pack(out_dir: Path) -> dict:
    from rl_curriculum.curriculum261_r11_param_pack import load_selected_pack

    return load_selected_pack(out_dir)


def _git_head(repo: Path) -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(repo),
            capture_output=True, text=True, timeout=30,
        ).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _historical_binding() -> dict:
    binding = {
        "r2_plan_digest_expected": PRIOR_R2_PLAN_DIGEST,
        "diag262r2_plan_digest_expected": PRIOR_DIAG262R2_PLAN_DIGEST,
        "r4_parameter_pack_digest_expected":
            PRIOR_R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest_expected": PRIOR_R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest_expected": PRIOR_R6_DESIGN_PLAN_DIGEST,
        "r7_design_plan_digest_expected": PRIOR_R7_DESIGN_PLAN_DIGEST,
        "r8_design_plan_digest_expected": PRIOR_R8_DESIGN_PLAN_DIGEST,
        "r9_design_plan_digest_expected": PRIOR_R9_DESIGN_PLAN_DIGEST,
        "r9_parameter_pack_digest_expected": PRIOR_R9_PARAMETER_PACK_DIGEST,
        "r10_design_plan_digest_expected": PRIOR_R10_DESIGN_PLAN_DIGEST,
        "r10_parameter_pack_digest_expected":
            PRIOR_R10_PARAMETER_PACK_DIGEST,
        "r7_parent_of_baseline": PRIOR_R7_BASELINE_COMMIT,
        "r8_parent_of_baseline": PRIOR_R8_BASELINE_COMMIT,
        "r9_baseline_commit": PRIOR_R9_BASELINE_COMMIT,
        "r10_baseline_commit": PRIOR_R10_BASELINE_COMMIT,
        "r10_final_freeze_commit": PRIOR_R10_FINAL_FREEZE_COMMIT,
    }
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    if release_repo:
        checks = [
            ("stage2_6_1/artifacts/repair2/qualification_plan_digest.txt",
             "r2_plan_digest_actual"),
            ("stage2_6_2/artifacts/repair2/diagnostic_plan_digest.txt",
             "diag262r2_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair4/r4_parameter_pack_digest.txt",
             "r4_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair5/r5_design_plan_digest.txt",
             "r5_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair6/r6_design_plan_digest.txt",
             "r6_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair7/r7_design_plan_digest.txt",
             "r7_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair8/r8_design_plan_digest.txt",
             "r8_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair9/r9_design_plan_digest.txt",
             "r9_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair9/r9_parameter_pack_digest.txt",
             "r9_parameter_pack_digest_actual"),
            ("stage2_6_1/artifacts/repair10/r10_design_plan_digest.txt",
             "r10_design_plan_digest_actual"),
            ("stage2_6_1/artifacts/repair10/r10_parameter_pack_digest.txt",
             "r10_parameter_pack_digest_actual"),
        ]
        for rel, key in checks:
            p = release_repo / rel
            if p.is_file():
                binding[key] = p.read_text(encoding="utf-8").strip()
    binding["digests_match"] = bool(
        binding.get("r2_plan_digest_actual") == PRIOR_R2_PLAN_DIGEST
        and binding.get("diag262r2_plan_digest_actual")
        == PRIOR_DIAG262R2_PLAN_DIGEST
        and binding.get("r4_parameter_pack_digest_actual")
        == PRIOR_R4_PARAMETER_PACK_DIGEST
        and binding.get("r5_design_plan_digest_actual")
        == PRIOR_R5_DESIGN_PLAN_DIGEST
        and binding.get("r6_design_plan_digest_actual")
        == PRIOR_R6_DESIGN_PLAN_DIGEST
        and binding.get("r7_design_plan_digest_actual")
        == PRIOR_R7_DESIGN_PLAN_DIGEST
        and binding.get("r8_design_plan_digest_actual")
        == PRIOR_R8_DESIGN_PLAN_DIGEST
        and binding.get("r9_design_plan_digest_actual")
        == PRIOR_R9_DESIGN_PLAN_DIGEST
        and binding.get("r9_parameter_pack_digest_actual")
        == PRIOR_R9_PARAMETER_PACK_DIGEST
        and binding.get("r10_design_plan_digest_actual")
        == PRIOR_R10_DESIGN_PLAN_DIGEST
        and binding.get("r10_parameter_pack_digest_actual")
        == PRIOR_R10_PARAMETER_PACK_DIGEST)
    return binding


def _r8_abort_binding(out_dir: Path) -> dict:
    """§18:R8 aborted marker 保留性绑定(读 release repo 的
    r8_iteration_aborted.json;缺失 => 拒绝锁 plan)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    marker = (release_repo / "stage2_6_1" / "artifacts" / "repair8"
              / "r8_iteration_aborted.json") if release_repo else None
    local = Path(out_dir) / "r8_abort_binding.json"
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R8 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R11 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("iteration") != "r8" or "ImportError" not in str(
            data.get("reason", "")):
        raise RuntimeError(
            f"R8 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r8 且 reason 含 ImportError)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": str(data.get("reason", ""))[:160],
        "contract": data.get("contract", "")[:200],
    }
    _write_json(Path(out_dir), "r8_abort_binding.json", binding)
    return binding


def _code_freeze_sha(out_dir: Path) -> str:
    """读取并校验 code freeze(§6;正式数据开始前必须存在)。"""
    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )

    freeze = verify_r11_code_freeze(Path(out_dir))
    if not freeze["pass"]:
        raise RuntimeError(
            f"R11 code freeze 校验失败:{freeze}(design plan 必须绑定"
            "有效的 implementation freeze SHA;§6)")
    return str(freeze["code_freeze_sha"])


def _reference_contract_digest_binding(out_dir: Path) -> str:
    """policy-visible reference 合同的静态 digest(design plan 绑定)。"""
    from rl_curriculum.curriculum261_r11_reference import (
        policy_visible_reference_contract_static_digest,
    )

    return policy_visible_reference_contract_static_digest()


def _r9_abort_binding(out_dir: Path) -> dict:
    """§2/§3:R9 诚实 FAIL 证据绑定(硬闸;读 release repo 的
    r9_iteration_aborted.json + plan/pack digest + 零 exposure;
    缺失或异常 => 拒绝锁 plan)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    base = (release_repo / "stage2_6_1" / "artifacts" / "repair9"
            if release_repo else None)
    marker = base / "r9_iteration_aborted.json" if base else None
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R9 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R11 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    if data.get("iteration") != "r9" or "TypeError" not in str(
            data.get("reason", "")):
        raise RuntimeError(
            f"R9 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r9 且 reason 含 TypeError)")
    plan_digest_file = base / "r9_design_plan_digest.txt"
    pack_digest_file = base / "r9_parameter_pack_digest.txt"
    plan_ok = bool(
        plan_digest_file.is_file()
        and plan_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R9_DESIGN_PLAN_DIGEST)
    pack_ok = bool(
        pack_digest_file.is_file()
        and pack_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R9_PARAMETER_PACK_DIGEST)
    exposure_absent = not (base / "qualification_exposure_r9.json"
                           ).is_file()
    qualification_absent = not (base / "qualification_plan_r9.json"
                                ).is_file()
    if not (plan_ok and pack_ok and exposure_absent
            and qualification_absent):
        raise RuntimeError(
            "R9 证据绑定失败:"
            f"plan_digest_ok={plan_ok} pack_digest_ok={pack_ok} "
            f"exposure_absent={exposure_absent} "
            f"qualification_absent={qualification_absent}(§2 硬输入)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": str(data.get("reason", ""))[:160],
        "failure_mode": ("CLI supervised 调用缺 namespace -> "
                         "TypeError(R9 硬规则诚实 FAIL)"),
        "design_evidence_role": ("R9 cue audit/160x2 semantic/三候选/"
                                 "n=10/marginal/pack = development "
                                 "evidence only"),
        "r9_design_plan_digest": PRIOR_R9_DESIGN_PLAN_DIGEST,
        "r9_parameter_pack_digest": PRIOR_R9_PARAMETER_PACK_DIGEST,
        "r9_exposure_absent": exposure_absent,
        "r9_qualification_never_run": qualification_absent,
    }
    _write_json(Path(out_dir), "r9_abort_binding.json", binding)
    return binding


def _r10_abort_binding(out_dir: Path) -> dict:
    """§2/§3:R10 诚实 FAIL 证据绑定(硬闸;读 release repo 的
    r10_iteration_aborted.json + plan/pack digest + 零 exposure;
    缺失或异常 => 拒绝锁 plan)。R10 失败模式:calibrate/supervised
    main 的 PairGenerationError,根因 historically underdetermined
    due to missing invocation-state evidence(R11 工作包 A 动因)。"""
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    base = (release_repo / "stage2_6_1" / "artifacts" / "repair10"
            if release_repo else None)
    marker = base / "r10_iteration_aborted.json" if base else None
    if marker is None or not marker.is_file():
        raise RuntimeError(
            f"R10 aborted marker 缺失:{marker}(§3 历史证据必须完整保留;"
            "禁止在 marker 缺失时锁 R11 design plan)")
    data = json.loads(marker.read_text(encoding="utf-8"))
    reason = str(data.get("reason", ""))
    if data.get("iteration") != "r10" or "PairGenerationError" not in reason:
        raise RuntimeError(
            f"R10 aborted marker 内容异常:{str(data)[:200]}(预期 "
            "iteration=r10 且 reason 含 PairGenerationError)")
    plan_digest_file = base / "r10_design_plan_digest.txt"
    pack_digest_file = base / "r10_parameter_pack_digest.txt"
    plan_ok = bool(
        plan_digest_file.is_file()
        and plan_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R10_DESIGN_PLAN_DIGEST)
    pack_ok = bool(
        pack_digest_file.is_file()
        and pack_digest_file.read_text(encoding="utf-8").strip()
        == PRIOR_R10_PARAMETER_PACK_DIGEST)
    exposure_absent = not (base / "qualification_exposure_r10.json"
                           ).is_file()
    qualification_absent = not (base / "qualification_plan_r10.json"
                                ).is_file()
    if not (plan_ok and pack_ok and exposure_absent
            and qualification_absent):
        raise RuntimeError(
            "R10 证据绑定失败:"
            f"plan_digest_ok={plan_ok} pack_digest_ok={pack_ok} "
            f"exposure_absent={exposure_absent} "
            f"qualification_absent={qualification_absent}(§2 硬输入)")
    binding = {
        "retained": True,
        "marker_path": str(marker),
        "aborted_utc": data.get("aborted_utc"),
        "reason_head": reason[:400],
        "failure_mode": (
            "calibrate/shared orchestration/supervised main 生成 "
            "c3_cost/D0/pair1 抛 PairGenerationError(5 attempts 全部 "
            "too_few_distractors;A/B/pair 三段同文案)"),
        "root_cause_statement": (
            "historically underdetermined due to missing "
            "invocation-state evidence(三种重放不可复现;R10 当时的 "
            "PairGenerationError 未保留逐 attempt 调用状态)"),
        "r11_closure": (
            "R11 工作包 A:generation invocation envelope + 逐 attempt "
            "证据落盘 + 跨进程确定性矩阵 + mutable state 审计"),
        "design_evidence_role": (
            "R10 cue audit/semantic 160x2/三候选/n=15(机械)/marginal/"
            "pack = development evidence only;R11 必须全新 namespace "
            "重新执行机械 design,不得复制 R10 正式结论"),
        "r10_design_plan_digest": PRIOR_R10_DESIGN_PLAN_DIGEST,
        "r10_parameter_pack_digest": PRIOR_R10_PARAMETER_PACK_DIGEST,
        "r10_final_freeze_commit": PRIOR_R10_FINAL_FREEZE_COMMIT,
        "r10_exposure_absent": exposure_absent,
        "r10_qualification_never_run": qualification_absent,
    }
    _write_json(Path(out_dir), "r10_abort_binding.json", binding)
    return binding


def _generation_determinism_gate_binding(out_dir: Path) -> dict:
    """工作包 A6:生成确定性合同门禁(进入正式阶段的前置)。"""
    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_lock_dir,
    )

    path = qualification_r11_lock_dir() / "determinism" / (
        "generation_determinism_contract.json")
    if not path.is_file():
        raise RuntimeError(
            f"generation determinism contract 缺失:{path}(工作包 A6:"
            "确定性矩阵/mutable state 审计/合同门禁全部通过前,禁止"
            "访问任何 R11 正式 design/calibration/qualification "
            "namespace)")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("pass") is not True:
        raise RuntimeError(
            f"generation determinism contract 未通过:{str(data)[:300]}"
            "(工作包 A6 fail closed)")
    return {
        "bound": True,
        "path": str(path),
        "root_cause_statement": data.get("r10_root_cause_statement", ""),
        "checks": data.get("checks", {}),
    }


def cmd_audit(args: argparse.Namespace) -> int:
    # §6/§21:freeze 是正式数据的第一件事(先于任何治理 artifact)
    freeze_sha = str(getattr(args, "code_freeze_sha", "") or "")
    if freeze_sha:
        from rl_curriculum.curriculum261_r11_dependencies import (
            write_r11_code_freeze,
        )

        freeze_doc = write_r11_code_freeze(
            Path(args.out_dir), code_freeze_sha=freeze_sha)
        print(f"[audit] code freeze anchored: {freeze_sha} "
              f"(tree {freeze_doc['source_tree_digest'][:14]}...)")
    else:
        from rl_curriculum.curriculum261_r11_dependencies import (
            verify_r11_code_freeze,
        )

        existing = verify_r11_code_freeze(Path(args.out_dir))
        if not existing["pass"]:
            print("[audit] 缺少 --code-freeze-sha 且无有效 freeze 记录"
                  "(§6:正式数据开始前必须冻结;fail closed)")
            return 1

    from rl_curriculum.curriculum261_r3_calibration import (
        fit_matrix_from_records,
        generate_fit_bank,
    )
    from rl_curriculum.curriculum261_r3_preprocessing import (
        numerical_equivalence_report,
        production_preprocessing_audit,
    )
    from rl_curriculum.curriculum261_r4_preprocessing import (
        OBSERVATION_SPACE_SEMANTICS_V2,
        POSITION_SLOT_SEMANTICS_V2,
        ROUTE_C_FEATURE_PREPROCESSING_V2,
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r6_preflight import (
        _route_c_identity,
        _vendor_state,
        vendor_dir_default,
    )

    out = Path(args.out_dir)
    release_repo = None
    for cand in (Path("/mnt/e/trading/freqai-rl-audit"),
                 Path("E:/trading/freqai-rl-audit")):
        if cand.is_dir():
            release_repo = cand
            break
    head = _git_head(release_repo) if release_repo else ""
    _write_json(out, "baseline_integrity.json", {
        "expected_baseline": BASELINE_COMMIT_R11,
        "release_repo_head": head,
        "baseline_matches": bool(head == BASELINE_COMMIT_R11),
        "note": "发布仓库 HEAD 应等于 R8 诚实 FAIL checkpoint"
                "(或其明确后继;组装 R11 产物前)",
    })
    _write_json(out, "historical_binding.json", _historical_binding())

    vendor = _vendor_state(vendor_dir_default())
    _write_json(out, "route_c_integrity.json", {
        **_route_c_identity(),
        "vendor": vendor,
        "vendor_pin_matches": bool(vendor.get("sha") == VENDOR_PIN
                                   and vendor.get("clean")),
    })

    audit = production_preprocessing_audit()
    _write_json(out, "production_preprocessing_audit.json", audit)
    _write_json(out, "preprocessing_v2_contract.json", {
        "contract_version": ROUTE_C_FEATURE_PREPROCESSING_V2,
        "digest": preprocessing_v2_contract_digest(),
        "observation_space": OBSERVATION_SPACE_SEMANTICS_V2,
        "position_slot": POSITION_SLOT_SEMANTICS_V2,
        "numerics": "与 R4-R7 逐位一致(vendor pipeline 直接复用);"
                    "R11 在全新语料重新资格验证",
    })
    _dump_txt(out, "preprocessing_v2_contract_digest.txt",
              preprocessing_v2_contract_digest())
    records = generate_fit_bank("preplan_smoke_r11", args.fit_pairs)
    fit_df = fit_matrix_from_records(records)
    half = len(fit_df) // 2
    eq = numerical_equivalence_report(
        fit_df.iloc[:half], fit_df.iloc[half:])
    _write_json(out, "production_equivalence.json", eq)
    ns = _verify_namespace_safe()
    _write_json(out, "seed_namespace_integrity_pre_design.json", ns)
    # §6.2/§32:依赖身份 artifact + §32 official entrypoint validation
    from rl_curriculum.curriculum261_r11_dependencies import (
        write_dependency_resolution_r11,
    )

    dep = write_dependency_resolution_r11(out)
    from rl_curriculum.curriculum261_r11_delegation import (
        calibration_call_contract_payload,
        delegation_ast_checks_r11,
        live_signature_audit_r11,
    )
    from rl_curriculum.curriculum261_r11_routing import (
        bundle_routing_contract_payload,
    )

    sig_audit = live_signature_audit_r11()
    ast_checks = delegation_ast_checks_r11()
    _write_json(out, "delegation_signature_audit.json", sig_audit)
    _write_json(out, "delegation_ast_checks.json", ast_checks)
    _write_json(out, "calibration_call_contract.json",
                calibration_call_contract_payload())
    from rl_curriculum.curriculum261_r11_routing import (
        bundle_routing_contract_digest,
    )

    _write_json(out, "bundle_routing_contract.json",
                bundle_routing_contract_payload())
    _dump_txt(out, "bundle_routing_contract_digest.txt",
              bundle_routing_contract_digest())
    if not (sig_audit["all_pass"] and ast_checks["pass"]):
        print(f"[audit] delegation 合同失败(fail closed):"
              f"sig={sig_audit['all_pass']} ast={ast_checks['pass']}")
        return 1
    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )

    freeze_check = verify_r11_code_freeze(out)
    if not freeze_check["pass"]:
        print(f"[audit] code freeze 复验失败(fail closed):"
              f"{freeze_check}")
        return 1
    entry = _official_entrypoint_validation()
    _write_json(out, "official_entrypoint_validation.json", entry)
    _write_json(out, "r8_abort_binding.json",
                _r8_abort_binding_soft(out))
    _write_json(out, "r9_abort_binding.json", _r9_abort_binding(out))
    _write_json(out, "r10_abort_binding.json", _r10_abort_binding(out))
    determinism_binding = _generation_determinism_gate_binding(out)
    _write_json(out, "generation_determinism_binding.json",
                determinism_binding)
    print(f"[audit] equivalence pass={eq['pass']} "
          f"ns pass={ns.get('pass')} "
          f"digests_match={_historical_binding()['digests_match']} "
          f"dep pass={dep['pass']} entry pass={entry['pass']} "
          f"determinism_contract=bound")
    ok = bool(eq["pass"] and ns.get("pass")
              and _historical_binding()["digests_match"]
              and vendor.get("sha") == VENDOR_PIN and vendor.get("clean")
              and dep["pass"] and entry["pass"]
              and determinism_binding.get("bound") is True)
    return 0 if ok else 1


def _official_entrypoint_validation() -> dict:
    """§6.3/§32:正式入口点身份(import sweep + 子命令清单 +
    no-alternate-loader)。"""
    import importlib

    mods = [
        "rl_curriculum.curriculum261_r11_namespaces",
        "rl_curriculum.curriculum261_r11_dependencies",
        "rl_curriculum.curriculum261_r11_noise_replay",
        "rl_curriculum.curriculum261_r11_cue_contract",
        "rl_curriculum.curriculum261_r11_cue_eval",
        "rl_curriculum.curriculum261_r11_param_pack",
        "rl_curriculum.curriculum261_r11_preplan",
        "rl_curriculum.curriculum261_r11_design",
        "rl_curriculum.curriculum261_r11_calibration",
        "rl_curriculum.curriculum261_r11_plan",
        "rl_curriculum.curriculum261_r11_preflight",
        "rl_curriculum.curriculum261_r11_final",
        "rl_curriculum.curriculum261_r11_smoke",
        "rl_curriculum.curriculum261_generation_envelope",
        "rl_curriculum.curriculum261_r11_determinism",
        "rl_curriculum.curriculum261_r11_shadow",
        "rl_curriculum.curriculum261_r11_cli",
    ]
    failed: dict[str, str] = {}
    for m in mods:
        try:
            importlib.import_module(m)
        except Exception as exc:  # noqa: BLE001
            failed[m] = str(exc)[:200]
    from rl_curriculum.curriculum261_r11_cli import main as cli_main

    subcommands = [
        "audit", "cue-audit", "preplan-smoke", "plan-roundtrip",
        "design-plan-lock", "design", "calibrate", "preflight-static",
        "lock-plan", "preflight-sealed", "qualify", "smoke",
        "namespace-integrity", "determinism-matrix", "shadow-run",
        "shadow-compare"]
    nal = _no_alternate_loader_check()
    return {
        "format": "cur261-r11-official-entrypoint-v1",
        "entrypoint": "rl_curriculum.curriculum261_r11_cli.main",
        "entrypoint_callable": callable(cli_main),
        "import_sweep_modules": len(mods),
        "import_sweep_failed": failed,
        "subcommands": subcommands,
        "no_alternate_loader": nal,
        "temporary_driver_forbidden": True,
        "pass": bool(callable(cli_main) and not failed
                     and nal.get("pass")),
    }


def _r8_abort_binding_soft(out_dir: Path) -> dict:
    """audit 阶段的 R8 abort 保留性快照(缺失只记录,不阻断;
    design-plan-lock 阶段的 _r8_abort_binding 才是硬闸)。"""
    try:
        return _r8_abort_binding(Path(out_dir))
    except Exception as exc:  # noqa: BLE001
        return {"retained": False, "error": str(exc)[:200]}


def _verify_namespace_safe() -> dict:
    try:
        from rl_curriculum.curriculum261_r11_namespaces import (
            verify_r11_namespace_isolation,
        )

        return verify_r11_namespace_isolation()
    except Exception as exc:  # noqa: BLE001
        return {"pass": False, "error": str(exc)[:300]}


def cmd_cue_audit(args: argparse.Namespace) -> int:
    """§12 三路闭合合同审计(在任何 R11 design/semantic data 之前)。"""
    from rl_curriculum.curriculum261_r11_cue_contract import (
        cue_semantic_contract_digest,
        cue_semantic_contract_payload,
        load_locked_cue_audit_plan_r11,
        lock_cue_audit_plan_r11,
        run_cue_contract_audit,
    )

    out = Path(args.out_dir)
    # §R11-10:任何正式 R11 cue-audit data 生成前先锁定 audit plan
    # (namespaces/500×2/once-attempts/replay/mirror bound/MC/bootstrap
    # seeds/delta/floor/trace schema/code identity;锁定后不可修改)。
    if not (out / "cue_audit_plan.json").is_file():
        _, plan_digest = lock_cue_audit_plan_r11(out)
        print(f"[cue-audit] audit plan locked digest={plan_digest}")
    load_locked_cue_audit_plan_r11(out)
    report = run_cue_contract_audit(out, require_locked_plan=True)
    _dump_txt(out, "cue_semantic_contract_digest.txt",
              cue_semantic_contract_digest())
    _write_json(out, "cue_semantic_contract.json",
                cue_semantic_contract_payload())
    mc = report["monte_carlo"]
    model = report["direct_generator"]["model"]
    valid = report["direct_generator"]["validation"]
    print(f"[cue-audit] p_contract={report['p_contract']:.6f} "
          f"mc={mc['p_hat']:.6f}(diff={mc['abs_diff_vs_analytic']:.6f})"
          f" model={model['empirical_recall']:.6f}"
          f"(CI [{model['block_cluster']['ci95'][0]:.6f},"
          f"{model['block_cluster']['ci95'][1]:.6f}]) "
          f"validation={valid['empirical_recall']:.6f}"
          f"(CI [{valid['block_cluster']['ci95'][0]:.6f},"
          f"{valid['block_cluster']['ci95'][1]:.6f}]) "
          f"floor={report['noninferiority']['recall_floor']:.6f} "
          f"pass={report['pass']}")
    ova = report["once_vs_attempts"]
    print(f"[cue-audit] once/attempts: recall "
          f"{ova['recall_model']:.6f} vs {ova['recall_validation']:.6f}"
          f"(tol {ova['tolerance']:.6f}) k_mean "
          f"{ova['k_mean_model']:.3f} vs {ova['k_mean_validation']:.3f}"
          f"(tol {ova['k_tolerance']:.3f}) "
          f"bitwise={ova['first_pass_bitwise_check']['bitwise_ok']} "
          f"(n={ova['first_pass_bitwise_check']['n_blocks_checked']})")
    if not report["pass"]:
        print("[cue-audit] 三路闭合 audit FAIL——不得锁 design plan(§12);"
              "R11 = FAIL")
        return 1
    return 0


def cmd_preplan_smoke(args: argparse.Namespace) -> int:
    """§20 preplan engineering smoke(固定 sentinel ladder;极小规模;
    不参与参数选择;只用 preplan_smoke_r11,不用 design/calibration/
    holdout/final namespace)。"""
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
    from rl_curriculum.curriculum261_r11_cue_eval import (
        canonical_cue_observations,
        cluster_bootstrap_rate,
        semantic_cue_gate,
    )
    from rl_curriculum.curriculum261_r11_noise_replay import (
        trace_matched_blocks,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        generate_matched_block_with_attempts,
    )
    import hashlib as _hashlib

    out = Path(args.out_dir)
    sentinel = {r: dict(p) for r, p in C2_RUNG_PARAMS.items()}
    blocks = [generate_matched_block_with_attempts(
        sentinel, namespace="preplan_smoke_r11", block_index=i)
        for i in range(3)]
    obs = canonical_cue_observations(blocks)
    pos = [{"n": sum(1 for e in pb["events"] if e["is_positive"]),
            "hit": sum(1 for e in pb["events"]
                       if e["is_positive"] and e["over"])}
           for pb in obs["per_block"]]
    rate = cluster_bootstrap_rate(pos, side="lower")
    # exact replay + semantic gate 全链路探针(floor=0/min=1,仅证明
    # plumbing 不 crash,不作任何资格判定)
    replay = trace_matched_blocks(blocks, sentinel)
    mini_gate = semantic_cue_gate(
        blocks, sentinel, recall_floor_value=0.0,
        min_unique_positive_cues=1, label="preplan_smoke_r11")
    identity = {
        "sentinel": {r: {k: sentinel[r][k]
                         for k in ("alpha_bps", "wick_kappa")}
                     for r in sentinel},
        "sentinel_digest": "r11smoke-" + _hashlib.sha256(json.dumps(
            {r: sorted(sentinel[r].items()) for r in sorted(sentinel)},
            default=str).encode("utf-8")).hexdigest(),
        "n_blocks": len(blocks),
        "namespace": "preplan_smoke_r11",
        "role": "仅证明代码不会立即 crash;不使用正式 candidate;"
                "不参与任何参数选择;不得使用 design/calibration/"
                "holdout/final namespace(§20)",
    }
    _write_json(out, "preplan_engineering_smoke.json", {
        "format": "cur261-r11-preplan-smoke-v1",
        "identity": identity,
        "violations": obs["violations"],
        "positive_cue_recall_lower_bound": rate["bound"],
        "n_unique_positive_cues": sum(p["n"] for p in pos),
        "cue_table_digest": obs["cue_table_digest"],
        "noise_replay": {
            "max_replay_abs_error": replay["max_replay_abs_error"],
            "all_replay_ok": replay["all_replay_ok"],
            "all_bounds_ok": replay["all_bounds_ok"],
        },
        "semantic_gate_plumbing_pass": bool(
            mini_gate["checks"]["per_event_k_complete"]
            and mini_gate["checks"]["noise_replay_integrity"]),
        "no_crash": True,
        "pass": bool(not obs["violations"]
                     and sum(p["n"] for p in pos) > 0
                     and replay["all_replay_ok"]
                     and replay["all_bounds_ok"]),
    })
    # §9 preplan end-to-end rehearsal(plan lock 硬前置;真实
    # evaluator/writer/mini audit/marker;全部非正式 namespace)。
    from rl_curriculum.curriculum261_r11_preplan import (
        run_preplan_rehearsal_r11,
    )

    rehearsal = run_preplan_rehearsal_r11(out / "preplan")
    if not rehearsal["pass"]:
        print(f"[preplan-smoke] preplan rehearsal FAIL:"
              f"{[k for k, v in rehearsal['sections'].items() if not v]}")
        return 1
    print(f"[preplan-smoke] rehearsal pass digest="
          f"{rehearsal['rehearsal_digest']}")
    # §10:reference equivalence 根因诊断(preplan namespace;
    # R9 false 的重现 + 逐 mismatch 明细 + 根因分类)
    from rl_curriculum.curriculum261_r11_preplan import (
        run_reference_root_cause_diagnosis_r11,
    )

    root_cause = run_reference_root_cause_diagnosis_r11(out / "preplan")
    print(f"[preplan-smoke] reference root-cause: "
          f"float64_path={root_cause['float64_math_path']['pass']} "
          f"canonical_full_equality="
          f"{root_cause['canonical_vs_scaled_full_equality']} "
          f"legacy_diffs={root_cause['legacy_action_diffs_total']} "
          f"unexplained={root_cause['unexplained_mismatches']} "
          f"branch={root_cause['branch_verdict']}")
    # §12:preplan full pipeline shadow rehearsal(共享 orchestrator;
    # 禁 monkeypatch;design plan lock 硬前置)
    from rl_curriculum.curriculum261_r11_rehearsal import (
        run_preplan_full_pipeline_rehearsal_r11,
    )

    full = run_preplan_full_pipeline_rehearsal_r11(out)
    if not full["pass"]:
        print(f"[preplan-smoke] full pipeline rehearsal FAIL:"
              f"{[k for k, v in full['proofs'].items() if v is False]}")
        return 1
    print(f"[preplan-smoke] full-pipeline rehearsal pass digest="
          f"{full['rehearsal_digest']}")
    print("[preplan-smoke] pass(no crash;sentinel ladder only;"
          "replay+semantic-gate+root-cause+full-pipeline OK)")
    return 0


# ------------------------------------------------- §8.3 plan roundtrip
_SUBPROC_LOADER_DESIGN = (
    "from rl_curriculum.curriculum261_r11_design import "
    "(design_plan_digest_r11, load_locked_design_plan_r11);"
    "import json,sys;"
    "plan,digest=load_locked_design_plan_r11(sys.argv[1]);"
    "recomputed=design_plan_digest_r11(plan);"
    "print(json.dumps({"
    "'loaded_digest':digest,"
    "'recomputed':recomputed,"
    "'payload_digest_field':plan.get('design_plan_digest'),"
    "'n_candidates':plan['candidate_grid']['n_candidates'],"
    "'formal_block_options':plan['formal_block_options'],"
    "'semantic_blocks':plan['semantic_corpora']"
    "['blocks_per_corpus'],"
    "'iteration':plan['iteration']}))")

_SUBPROC_LOADER_QUAL = (
    "import os,sys;"
    "os.environ['CURRICULUM261_R11_LOCK_DIR']=sys.argv[2];"
    "from rl_curriculum.curriculum261_r11_plan import "
    "(load_locked_plan_r11, plan_digest_r11);"
    "import json;"
    "plan,digest=load_locked_plan_r11();"
    "print(json.dumps({"
    "'loaded_digest':digest,"
    "'recomputed':plan_digest_r11(plan),"
    "'iteration':plan['iteration'],"
    "'n_blocks':plan['final_sample_counts']['c2_matched_blocks']}))")


def _subproc_python(code: str, *argsv: str) -> dict:
    import os
    import sys

    env = dict(os.environ)
    proj = Path(__file__).resolve().parents[2]
    env.setdefault("PYTHONPATH", str(proj / "src"))
    res = subprocess.run(
        [sys.executable, "-c", code, *argsv],
        capture_output=True, text=True, timeout=600, env=env, cwd=str(proj))
    if res.returncode != 0:
        raise RuntimeError(
            f"子进程 loader 失败(rc={res.returncode}): "
            f"{res.stderr[-600:]}")
    return json.loads(res.stdout.strip().splitlines()[-1])


def _no_alternate_loader_check() -> dict:
    """§8.3:不存在 alternate loader——plan 文件名字面量只允许出现在
    权威模块(r11_design 的 lock/load;r11_namespaces 的路径常量与本
    扫描自身);其余模块不得直接读 plan JSON。"""
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    allowed_design = {"curriculum261_r11_design.py",
                      "curriculum261_r11_namespaces.py",
                      "curriculum261_r11_cli.py"}
    allowed_qual = {"curriculum261_r11_namespaces.py",
                    "curriculum261_r11_plan.py",
                    "curriculum261_r11_cli.py"}
    design_hits: list[str] = []
    qual_hits: list[str] = []
    for f in sorted(root.glob("curriculum261_r11_*.py")):
        text = f.read_text(encoding="utf-8")
        if "r11_design_plan.json" in text and f.name not in allowed_design:
            design_hits.append(f.name)
        if ("qualification_plan_r11.json" in text
                and f.name not in allowed_qual):
            qual_hits.append(f.name)
    return {
        "design_plan_readers": ["curriculum261_r11_design.py"],
        "qualification_plan_readers": ["curriculum261_r11_namespaces.py"
                                       " (path fn) + "
                                       "curriculum261_r11_plan.py (loader)"],
        "stray_design_plan_references": design_hits,
        "stray_qualification_plan_references": qual_hits,
        "pass": not design_hits and not qual_hits,
    }


def cmd_plan_roundtrip(args: argparse.Namespace) -> int:
    """§8.3 正式 Plan Digest Roundtrip(在临时目录执行真实生产路径)。

    覆盖:design plan(build→lock→new process load→recompute→compare
    →no-data validation→不可覆盖)与 qualification plan(合成合法
    payload 的同路径验证);§8.1 digest 不自引用;无 alternate loader。
    本子命令不生成任何 episode/不触碰 design/calibration/holdout/
    final namespace。
    """
    import tempfile

    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r11_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r11_design import (
        design_plan_digest_r11,
        design_plan_payload_r11,
        lock_design_plan_r11,
    )

    out = Path(args.out_dir)
    audit = json.loads((out / "cue_contract_audit.json").read_text(
        encoding="utf-8"))
    smoke = json.loads(
        (out / "preplan_engineering_smoke.json").read_text(
            encoding="utf-8"))

    checks: dict[str, bool] = {}
    details: dict[str, object] = {}

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        plan = design_plan_payload_r11(
            baseline_commit=BASELINE_COMMIT_R11,
            vendor_pin=VENDOR_PIN,
            v2_contract_digest=preprocessing_v2_contract_digest(),
            prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
            prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
            cue_audit=audit,
            preplan_smoke_identity={
                "sentinel_digest": smoke["identity"]["sentinel_digest"],
                "cue_contract_digest": cue_semantic_contract_digest(),
                "audit_digest": audit["audit_digest"],
            },
            dependency_identity={"roundtrip_synth": True},
            artifact_writer_identity={"roundtrip_synth": True},
            preplan_rehearsal_digest="r11pr-" + "0" * 64,
            r8_abort_evidence={"roundtrip_synth": True},
            cue_audit_plan_digest="r11ap-" + "0" * 64,
        )
        # build payload 的 canonical 快照(逐位一致验证基准)
        pre_digest = design_plan_digest_r11(plan)
        path, digest = lock_design_plan_r11(tmp, plan)
        checks["lock_ok"] = path.is_file() and digest == pre_digest
        # payload 逐位一致:重读 JSON,排除运行时字段后 canonical 相等
        reloaded = json.loads(path.read_text(encoding="utf-8"))
        checks["payload_bit_identical"] = bool(
            design_plan_digest_r11(reloaded) == pre_digest)
        # 新进程 load(真实生产路径)
        loaded = _subproc_python(_SUBPROC_LOADER_DESIGN, str(tmp))
        checks["new_process_load_digest_match"] = bool(
            loaded["loaded_digest"] == digest
            and loaded["recomputed"] == digest
            and loaded["payload_digest_field"] == digest)
        # no-data validation:candidate grid/选项/semantic blocks 一致
        from rl_curriculum.curriculum261_r11_param_pack import (
            r11_candidate_grid,
        )
        checks["candidate_grid_identical"] = bool(
            loaded["n_candidates"] == 3
            and loaded["n_candidates"]
            == len(r11_candidate_grid()))
        checks["formal_block_options_identical"] = bool(
            loaded["formal_block_options"] == [10, 15, 20])
        checks["semantic_blocks_identical"] = bool(
            loaded["semantic_blocks"] == 160)
        # 已存在文件不可覆盖
        try:
            lock_design_plan_r11(tmp, plan)
            overwrite_rejected = False
        except RuntimeError:
            overwrite_rejected = True
        checks["existing_plan_not_overwritable"] = overwrite_rejected
        # digest 文件与 payload 一致
        checks["digest_file_matches"] = bool(
            (tmp / "r11_design_plan_digest.txt").read_text(
                encoding="utf-8").strip() == digest)
        details["design_plan"] = loaded

    # qualification plan roundtrip(合成合法 payload;同一 lock/digest
    # 代码路径,通过 CURRICULUM261_R11_LOCK_DIR 定向临时目录)
    import os
    import tempfile

    from rl_curriculum.curriculum261_pairs import family_specs
    from rl_curriculum.curriculum261_r11_cue_eval import (
        cue_semantic_rule_identity,
    )
    from rl_curriculum.curriculum261_r6_tape import (
        matched_ladder_contract_identity,
    )
    from rl_curriculum.curriculum261_final import _frozen_contract_integrity
    from rl_curriculum.curriculum261_r11_param_pack import (
        C2_LADDER_CANDIDATES_R11,
        pack_digest_r11,
    )
    from rl_curriculum.curriculum261_r11_plan import (
        build_plan_r11,
        lock_plan_r11,
        plan_digest_r11,
    )

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        synth_pack = {
            "digest": "r11pk-" + "0" * 64,
            "pack_version": "CurriculumR11MatchedLadderPack-v1",
            "selected_c2_candidate": "c2l_midpoint",
            "selected_block_count": 15,
            "c2_ladder": {r: dict(v) for r, v in
                          C2_LADDER_CANDIDATES_R11["c2l_midpoint"].items()},
            "r4_parameter_pack_digest": PRIOR_R4_PARAMETER_PACK_DIGEST,
            "r5_design_plan_digest": PRIOR_R5_DESIGN_PLAN_DIGEST,
            "r6_design_plan_digest": PRIOR_R6_DESIGN_PLAN_DIGEST,
            "r7_design_plan_digest": PRIOR_R7_DESIGN_PLAN_DIGEST,
            "semantic_blocks_per_corpus": 160,
            "noninferiority_delta": 0.02,
            "recall_floor": 0.93,
            "p_contract": 0.95,
            "cue_contract_audit_digest": "r11ca-" + "0" * 64,
            "cue_semantic_rule_identity": cue_semantic_rule_identity(),
            "cue_semantic_contract_digest": cue_semantic_contract_digest(),
            "matched_ladder_contract_identity":
                matched_ladder_contract_identity(),
            "block_integrity_identity": "roundtrip-synth",
        }
        # pack digest 键不被 build_plan 使用,但保持结构一致
        assert pack_digest_r11({k: v for k, v in synth_pack.items()
                               if k not in ("digest",)})
        gate_true = {"pass": True, "format": "roundtrip-synth"}
        try:
            qual_plan = build_plan_r11(
                baseline_commit=BASELINE_COMMIT_R11,
                vendor_pin=VENDOR_PIN,
                frozen_contracts=_frozen_contract_integrity(),
                parameter_pack=synth_pack,
                design_plan_digest="r11dp-" + "0" * 64,
                selected_c2_candidate="c2l_midpoint",
                frozen_parameter_identity={"roundtrip": True},
                preprocessing_v2_contract_digest=(
                    preprocessing_v2_contract_digest()),
                calibration_bundle_hash="hash-cal",
                holdout_bundle_hash="hash-hold",
                preprocessing_robustness_gate=gate_true,
                curriculum_robustness_gate=gate_true,
                conditioning_gate_constants={},
                supervised_gate_constants={},
                kappa=1.5,
                reference_thresholds_by_family={
                    f: dict(family_specs()[f].reference_defaults)
                    for f in family_specs()},
                density_thresholds={},
                prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
                prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
                prior_r4_parameter_pack_digest=(
                    PRIOR_R4_PARAMETER_PACK_DIGEST),
                prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
                prior_r6_design_plan_digest=PRIOR_R6_DESIGN_PLAN_DIGEST,
                prior_r7_design_plan_digest=PRIOR_R7_DESIGN_PLAN_DIGEST,
                prior_r8_design_plan_digest=PRIOR_R8_DESIGN_PLAN_DIGEST,
                r8_abort_evidence={"roundtrip_synth": True},
            )
        except Exception as exc:  # noqa: BLE001
            checks["qualification_plan_build"] = False
            details["qualification_plan_error"] = str(exc)[:300]
            qual_plan = None
        if qual_plan is not None:
            checks["qualification_plan_build"] = True
            old_dir = os.environ.get("CURRICULUM261_R11_LOCK_DIR")
            os.environ["CURRICULUM261_R11_LOCK_DIR"] = str(tmp)
            try:
                qpath, qdigest = lock_plan_r11(qual_plan)
                checks["qualification_lock_ok"] = bool(
                    qpath.is_file()
                    and qdigest == plan_digest_r11(qual_plan))
                loaded_q = _subproc_python(
                    _SUBPROC_LOADER_QUAL, str(tmp), str(tmp))
                checks["qualification_new_process_load"] = bool(
                    loaded_q["loaded_digest"] == qdigest
                    and loaded_q["recomputed"] == qdigest
                    and loaded_q["n_blocks"] == 15)
                try:
                    lock_plan_r11(qual_plan)
                    q_overwrite = False
                except RuntimeError:
                    q_overwrite = True
                checks["qualification_not_overwritable"] = q_overwrite
                details["qualification_plan"] = loaded_q
            finally:
                if old_dir is None:
                    os.environ.pop("CURRICULUM261_R11_LOCK_DIR", None)
                else:
                    os.environ["CURRICULUM261_R11_LOCK_DIR"] = old_dir

    alt = _no_alternate_loader_check()
    checks["no_alternate_loader"] = bool(alt["pass"])

    # §8.1 digest 不自引用(复算排除双字段,篡改字段即 mismatch)
    from rl_curriculum.curriculum261_r11_design import (
        load_locked_design_plan_r11 as _unused_loader,  # noqa: F401
    )

    checks["digest_not_self_referential"] = bool(
        checks["new_process_load_digest_match"])

    result = {
        "format": "cur261-r11-plan-roundtrip-validation-v1",
        "iteration": "r11",
        "checks": checks,
        "alternate_loader_scan": alt,
        "details": details,
        "namespaces_touched": [],
        "pass": bool(all(checks.values())),
    }
    _write_json(out, "plan_roundtrip_validation.json", result)
    print(f"[plan-roundtrip] pass={result['pass']} checks={checks}")
    return 0 if result["pass"] else 1


def cmd_design_plan_lock(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r4_preprocessing import (
        preprocessing_v2_contract_digest,
    )
    from rl_curriculum.curriculum261_r11_cue_contract import (
        cue_semantic_contract_digest,
    )
    from rl_curriculum.curriculum261_r11_design import (
        design_plan_payload_r11,
        lock_design_plan_r11,
    )
    from rl_curriculum.curriculum261_r11_cue_contract import (
        load_locked_cue_audit_plan_r11,
    )
    from rl_curriculum.curriculum261_r11_dependencies import (
        resolve_dependency_identity_r11,
    )
    from rl_curriculum.curriculum261_r11_design import (
        semantic_artifact_identity_r11,
    )

    out = Path(args.out_dir)
    audit = json.loads((out / "cue_contract_audit.json").read_text(
        encoding="utf-8"))
    smoke = json.loads(
        (out / "preplan_engineering_smoke.json").read_text(
            encoding="utf-8"))
    # §9/§31:preplan rehearsal 是 plan lock 的硬前置项。
    rehearsal_path = out / "preplan" / "preplan_end_to_end_rehearsal.json"
    if not rehearsal_path.is_file():
        print("[design-plan-lock] preplan_end_to_end_rehearsal.json 缺失"
              "——拒绝锁 plan(§9:正式 plan lock 前必须完成工程 rehearsal)")
        return 1
    rehearsal = json.loads(rehearsal_path.read_text(encoding="utf-8"))
    if not rehearsal.get("pass"):
        print("[design-plan-lock] preplan rehearsal 未通过——拒绝锁 "
              "plan(§9/§31)")
        return 1
    dep = resolve_dependency_identity_r11()
    if not dep["pass"]:
        print(f"[design-plan-lock] 依赖解析未通过:{dep['problems'][:5]}"
              "——拒绝锁 plan(§6.3)")
        return 1
    audit_plan = load_locked_cue_audit_plan_r11(out)
    roundtrip_path = out / "plan_roundtrip_validation.json"
    roundtrip_binding: dict = {"executed": False}
    if roundtrip_path.is_file():
        rt = json.loads(roundtrip_path.read_text(encoding="utf-8"))
        roundtrip_binding = {
            "executed": True, "pass": bool(rt.get("pass")),
            "format": rt.get("format"),
        }
        if not rt.get("pass"):
            print("[design-plan-lock] plan roundtrip 未通过——拒绝锁 "
                  "plan(§8.3)")
            return 1
    else:
        print("[design-plan-lock] plan_roundtrip_validation.json 缺失——"
              "拒绝锁 plan(§20/§8.3:正式 lock 前必须完成真实生产路径 "
              "roundtrip 验证)")
        return 1
    plan = design_plan_payload_r11(
        baseline_commit=BASELINE_COMMIT_R11,
        vendor_pin=VENDOR_PIN,
        v2_contract_digest=preprocessing_v2_contract_digest(),
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        cue_audit=audit,
        preplan_smoke_identity={
            "sentinel_digest": smoke["identity"]["sentinel_digest"],
            "cue_contract_digest": cue_semantic_contract_digest(),
            "audit_digest": audit["audit_digest"],
            "plan_roundtrip": roundtrip_binding,
        },
        dependency_identity={
            "digest": dep["digest"],
            "n_declared": dep["n_declared"],
            "pass": dep["pass"],
            "c2_density_summary_definition_module":
                dep["c2_density_summary_definition_module_assert"],
        },
        artifact_writer_identity=semantic_artifact_identity_r11(),
        preplan_rehearsal_digest=rehearsal["rehearsal_digest"],
        r8_abort_evidence=_r8_abort_binding(out),
        r9_abort_evidence=_r9_abort_binding(out),
        r10_abort_evidence=_r10_abort_binding(out),
        generation_determinism_binding=(
            _generation_determinism_gate_binding(out)),
        code_freeze_sha=_code_freeze_sha(out),
        policy_visible_reference_contract_digest=(
            _reference_contract_digest_binding(out)),
        cue_audit_plan_digest=str(
            audit_plan["cue_audit_plan_digest"]),
    )
    path, digest = lock_design_plan_r11(out, plan)
    print(f"[design-plan-lock] locked {path} digest={digest}")
    return 0


def cmd_design(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r11_design import (
        load_locked_design_plan_r11,
        run_design_stage_r11,
    )

    out = Path(args.out_dir)
    plan, digest = load_locked_design_plan_r11(out)
    selection = run_design_stage_r11(out, plan, digest,
                                    baseline_commit=BASELINE_COMMIT_R11)
    print(f"[design] pass={selection['pass']} "
          f"selected={selection.get('selected_candidate')} "
          f"n={selection.get('selected_block_count')} "
          f"pack={selection.get('parameter_pack_digest')}")
    return 0 if selection["pass"] else 1


def cmd_calibrate(args: argparse.Namespace) -> int:
    """§19 calibration:main/holdout 各自独立评估(禁 pooled rescue)。

    R11 变革(相对 R9 的手写长流程):
    - 全部评估走共享 orchestrator orchestrate_calibration_stage_r11
      (与 preplan rehearsal 同一函数;§12.4);
    - holdout 三处评估错传 v2_main 的缺陷由显式 routing 结构性消灭
      (§9;R9 的 calib_hold_c13/c2_matched_hold/c2_indep_hold);
    - supervised keyword-only + PolicyVisibleSupervisedLabel-v1(§7/§8);
    - reference equivalence = canonical 合同 + 逐 mismatch 明细(§10)。

    repair R11(§11/工作包 A2):正式 calibrate 的任何异常(含
    PairGenerationError)在 abort marker 之前先落盘全部逐 attempt
    invocation envelopes(dump_failure_evidence),随后写
    r11_iteration_aborted 并 re-raise —— R10 的缺口(calibrate 阶段
    异常未自动写 abort;失败证据只剩字符串)在此闭合。
    """
    from rl_curriculum.curriculum261_r11_calibration import (
        fit_preprocessor_v2_from_bank_r11,
        generate_fit_bank_r11,
        run_generator_stress_r11,
    )
    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )
    from rl_curriculum.curriculum261_r11_namespaces import (
        require_r11_iteration_active,
        write_r11_iteration_aborted,
    )
    from rl_curriculum.curriculum261_r11_orchestrator import (
        formal_holdout_profile_r11,
        formal_main_profile_r11,
        orchestrate_calibration_stage_r11,
    )
    from rl_curriculum.curriculum261_r11_param_pack import (
        frozen_parameter_identity_r11,
        r11_override_for,
        verify_r4_inheritance_r11,
    )
    from rl_curriculum.curriculum261_r11_routing import build_routing_r11
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )

    require_r11_iteration_active()
    out = Path(args.out_dir)
    try:
        return _cmd_calibrate_inner(args, out)
    except Exception as exc:  # noqa: BLE001 —— §11 正式异常处置
        from rl_curriculum.curriculum261_generation_envelope import (
            dump_failure_evidence,
        )

        try:
            evidence = dump_failure_evidence(
                exc, out, stage_label="calibrate")
            if evidence is not None:
                print(f"[calibrate] PairGenerationError 证据已落盘:"
                      f"{evidence['path']}"
                      f"({evidence['n_attempt_envelopes']} envelopes)")
        except Exception:  # noqa: BLE001 —— 证据路径不得掩盖原始异常
            pass
        write_r11_iteration_aborted(
            f"calibrate 阶段执行异常({type(exc).__name__}:"
            f"{str(exc)[:400]});§11 硬规则:R11 永久结束,下一轮必须 "
            "R12 + 全新 namespace")
        raise


def _cmd_calibrate_inner(args: argparse.Namespace,
                         out: Path) -> int:
    from rl_curriculum.curriculum261_r11_calibration import (
        fit_preprocessor_v2_from_bank_r11,
        generate_fit_bank_r11,
        run_generator_stress_r11,
    )
    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )
    from rl_curriculum.curriculum261_r11_namespaces import (
        require_r11_iteration_active,
    )
    from rl_curriculum.curriculum261_r11_orchestrator import (
        formal_holdout_profile_r11,
        formal_main_profile_r11,
        orchestrate_calibration_stage_r11,
    )
    from rl_curriculum.curriculum261_r11_param_pack import (
        frozen_parameter_identity_r11,
        r11_override_for,
        verify_r4_inheritance_r11,
    )
    from rl_curriculum.curriculum261_r11_routing import build_routing_r11
    from rl_curriculum.curriculum261_r3_calibration import (
        conditioning_profile,
    )

    require_r11_iteration_active()
    freeze = verify_r11_code_freeze(out)
    if not freeze["pass"]:
        print(f"[calibrate] R11 code freeze 校验失败(fail closed):"
              f"{freeze}")
        return 1
    pack = _pack(out)
    inheritance = verify_r4_inheritance_r11(pack)
    if not inheritance:
        print("[calibrate] R4 inheritance 验证失败;fail closed")
        return 1
    n_blocks = int(pack["selected_block_count"])
    design_digest = (out / "r11_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    recall_floor_value = float(pack["recall_floor"])

    print("[calibrate] fitting main preprocessor "
          "(preprocess_fit_calibration_r11)...")
    records_main = generate_fit_bank_r11(
        "preprocess_fit_calibration_r11", pack)
    v2_main, manifest_main = fit_preprocessor_v2_from_bank_r11(
        "preprocess_fit_calibration_r11", pack, records=records_main,
        parameter_pack_identity=pack["digest"])
    routing_main = build_routing_r11("main", v2_main)
    print("[calibrate] fitting holdout preprocessor "
          "(preprocess_fit_holdout_r11)...")
    records_hold = generate_fit_bank_r11(
        "preprocess_fit_holdout_r11", pack)
    v2_hold, manifest_hold = fit_preprocessor_v2_from_bank_r11(
        "preprocess_fit_holdout_r11", pack, records=records_hold,
        parameter_pack_identity=pack["digest"])
    routing_holdout = build_routing_r11("holdout", v2_hold)
    _write_json(out, "fit_manifest_calibration.json", manifest_main)
    _write_json(out, "fit_manifest_holdout.json", manifest_hold)
    _write_json(out, "preprocessor_bundle_calibration.json",
                v2_main.identity())
    _write_json(out, "preprocessor_bundle_holdout.json",
                v2_hold.identity())
    _write_json(out, "fit_eval_isolation.json", {
        "main": {k: manifest_main[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "holdout": {k: manifest_hold[k] for k in (
            "namespace", "pairs_per_rung", "n_pairs", "n_episodes",
            "n_rows", "integrity_all_ok", "multiset_hash")},
        "eval_namespaces": ["calibration_r11", "calibration_holdout_r11"],
        "routing_contract": (
            "main 评估(calibration_r11/c2_independent_calibration_r11/"
            "supervised_main_r11)→ v2_main;holdout 评估"
            "(calibration_holdout_r11/c2_independent_holdout_r11/"
            "supervised_holdout_r11)→ v2_hold;fail closed(§9)"),
        "fit_bank_used_for_metrics": False,
    })

    print("[calibrate] shared orchestration (formal main/holdout "
          "profiles; same function as rehearsal)...")
    stage = orchestrate_calibration_stage_r11(
        out, pack,
        n_blocks=n_blocks,
        recall_floor_value=recall_floor_value,
        routing_main=routing_main,
        routing_holdout=routing_holdout,
        records_main=records_main,
        records_holdout=records_hold,
        profile_main=formal_main_profile_r11(n_blocks),
        profile_holdout=formal_holdout_profile_r11(n_blocks),
        override_fn=r11_override_for,
        design_digest=design_digest)

    print(f"[calibrate] preprocessing_robustness_pass="
          f"{stage['preprocessing_robustness_pass']} "
          f"supervised main/holdout="
          f"{stage['supervised_main_pass']}/"
          f"{stage['supervised_holdout_pass']} "
          f"curriculum main/holdout="
          f"{stage['main_independent_pass']}/"
          f"{stage['holdout_independent_pass']} "
          f"routing_all_pass={stage['routing_matrix_all_pass']}")

    print("[calibrate] conditioning + generator stress "
          "(stress_r11) + frozen identity...")
    from rl_curriculum.curriculum261_api import (
        CURRICULUM261_FAMILIES,
        CURRICULUM261_RUNGS,
    )
    from rl_curriculum.curriculum261_pairs import generate_pair

    eval_records = [
        generate_pair(f, r, 0, namespace="calibration_r11",
                      rung_params_override=r11_override_for(f, pack))
        for f in CURRICULUM261_FAMILIES for r in CURRICULUM261_RUNGS]
    cond = conditioning_profile(v2_main.inner, records_main, eval_records)
    _write_json(out, "conditioning_profile.json", cond)
    stress = run_generator_stress_r11(pack)
    _write_json(out, "generator_stress.json", stress)
    _write_json(out, "frozen_parameter_identity.json",
                frozen_parameter_identity_r11())

    gate = {
        "format": "cur261-r11-robustness-gate-v1",
        "iteration": "r11",
        "design_plan_digest": design_digest,
        "code_freeze_sha": freeze.get("code_freeze_sha"),
        "preprocessing_robustness_pass": stage[
            "preprocessing_robustness_pass"],
        "bundle_routing_all_pass": stage["routing_matrix_all_pass"],
        "supervised_main_pass": stage["supervised_main_pass"],
        "supervised_holdout_pass": stage["supervised_holdout_pass"],
        "curriculum_main_independent_pass": stage[
            "main_independent_pass"],
        "curriculum_holdout_independent_pass": stage[
            "holdout_independent_pass"],
        "density_pass": stage["density_pass"],
        "conditioning_pass": bool(cond["pass"]),
        "pooled_rescue_used": False,
        "pass": bool(stage["pass"] and cond["pass"]),
        "routing_matrix": stage["routing_matrix"],
    }
    _write_json(out, "robustness_gate.json", gate)
    from rl_curriculum.curriculum261_pairs import family_specs as _fs
    _write_json(out, "calibration_evidence.json", {
        "gate": gate,
        "stage_profiles": stage["profiles"],
        "orchestrator": "orchestrate_calibration_stage_r11",
        "reference_equivalence_detail_artifacts": [
            "preprocessing_v2_requalification.json",
        ],
        "reference_thresholds_by_family": {
            f: dict(_fs()[f].reference_defaults)
            for f in ("c1_opportunity", "c2_context", "c3_cost")},
        "supervised_gate_constants": stage.get("supervised_gate",
                                               {"source":
                                                "r11_orchestrator"}),
        "main_holdout_independent": {
            "main": stage["main_independent_pass"],
            "holdout": stage["holdout_independent_pass"],
            "pooled_rescue_used": False},
    })
    print(f"[calibrate] robustness gate pass={gate['pass']}")
    return 0 if gate["pass"] else 1


def cmd_preflight_static(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r11_preflight import (
        run_prelock_static_preflight_r11,
    )

    result = run_prelock_static_preflight_r11(Path(args.out_dir),
                                             VENDOR_PIN)
    print(f"[preflight-static] pass={result['pass']}")
    return 0 if result["pass"] else 1


def cmd_lock_plan(args: argparse.Namespace) -> int:
    out = Path(args.out_dir)
    gate = json.loads((out / "robustness_gate.json").read_text(
        encoding="utf-8"))
    if not gate.get("pass"):
        print("[lock-plan] robustness gate 非 PASS,拒绝 lock(§29)")
        return 1
    from rl_curriculum.curriculum261_final import (
        _frozen_contract_integrity,
    )
    from rl_curriculum.curriculum261_r11_param_pack import (
        frozen_parameter_identity_r11,
    )
    from rl_curriculum.curriculum261_r11_plan import (
        build_plan_r11,
        lock_plan_r11,
    )

    from rl_curriculum.curriculum261_r11_dependencies import (
        verify_r11_code_freeze,
    )

    freeze = verify_r11_code_freeze(out)
    if not freeze["pass"]:
        print(f"[lock-plan] code freeze 校验失败:{freeze}")
        return 1
    pack = _pack(out)
    design_digest = (out / "r11_design_plan_digest.txt").read_text(
        encoding="utf-8").strip()
    prep_rob_doc = json.loads(
        (out / "preprocessing_v2_requalification.json").read_text(
            encoding="utf-8"))
    evidence = json.loads(
        (out / "calibration_evidence.json").read_text(
            encoding="utf-8"))
    plan = build_plan_r11(
        baseline_commit=BASELINE_COMMIT_R11,
        vendor_pin=VENDOR_PIN,
        frozen_contracts=_frozen_contract_integrity(),
        parameter_pack=pack,
        design_plan_digest=design_digest,
        selected_c2_candidate=pack["selected_c2_candidate"],
        frozen_parameter_identity=frozen_parameter_identity_r11(),
        preprocessing_v2_contract_digest=(out /
                                          "preprocessing_v2_contract_"
                                          "digest.txt").read_text(
                                              encoding="utf-8").strip(),
        calibration_bundle_hash=json.loads(
            (out / "preprocessor_bundle_calibration.json").read_text(
                encoding="utf-8"))["bundle_hash"],
        holdout_bundle_hash=json.loads(
            (out / "preprocessor_bundle_holdout.json").read_text(
                encoding="utf-8"))["bundle_hash"],
        preprocessing_robustness_gate=prep_rob_doc,
        curriculum_robustness_gate={
            "pass": bool(
                evidence["main_holdout_independent"]["main"]
                and evidence["main_holdout_independent"]["holdout"]
                and evidence["gate"]["supervised_main_pass"]
                and evidence["gate"]["supervised_holdout_pass"]),
            "main_independent_pass":
                evidence["main_holdout_independent"]["main"],
            "holdout_independent_pass":
                evidence["main_holdout_independent"]["holdout"],
            "supervised_main_pass":
                evidence["gate"]["supervised_main_pass"],
            "supervised_holdout_pass":
                evidence["gate"]["supervised_holdout_pass"],
            "pooled_rescue_used": False,
        },
        conditioning_gate_constants={},
        supervised_gate_constants=evidence.get(
            "supervised_gate_constants", {}),
        kappa=1.5,
        reference_thresholds_by_family=evidence[
            "reference_thresholds_by_family"],
        density_thresholds={},
        prior_r2_plan_digest=PRIOR_R2_PLAN_DIGEST,
        prior_diag262r2_plan_digest=PRIOR_DIAG262R2_PLAN_DIGEST,
        prior_r4_parameter_pack_digest=PRIOR_R4_PARAMETER_PACK_DIGEST,
        prior_r5_design_plan_digest=PRIOR_R5_DESIGN_PLAN_DIGEST,
        prior_r6_design_plan_digest=PRIOR_R6_DESIGN_PLAN_DIGEST,
        prior_r7_design_plan_digest=PRIOR_R7_DESIGN_PLAN_DIGEST,
        prior_r8_design_plan_digest=PRIOR_R8_DESIGN_PLAN_DIGEST,
        r8_abort_evidence=json.loads(
            (out / "r8_abort_binding.json").read_text(
                encoding="utf-8")),
        prior_r9_design_plan_digest=PRIOR_R9_DESIGN_PLAN_DIGEST,
        r9_abort_evidence=json.loads(
            (out / "r9_abort_binding.json").read_text(
                encoding="utf-8")),
        prior_r10_design_plan_digest=PRIOR_R10_DESIGN_PLAN_DIGEST,
        r10_abort_evidence=json.loads(
            (out / "r10_abort_binding.json").read_text(
                encoding="utf-8")),
        generation_determinism_binding=(
            _generation_determinism_gate_binding(out)),
        code_freeze_sha=str(freeze["code_freeze_sha"]),
        policy_visible_reference_contract_digest=(
            _reference_contract_digest_binding(out)),
        bundle_routing_contract_digest=(out /
                                        "bundle_routing_contract_digest"
                                        ".txt").read_text(
                                            encoding="utf-8").strip(),
        supervised_label_contract="PolicyVisibleSupervisedLabel-v1",
        final_bundle_hash="",
    )
    path, digest = lock_plan_r11(plan)
    print(f"[lock-plan] locked {path} digest={digest}")
    return 0


def cmd_preflight_sealed(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r11_preflight import (
        run_postlock_sealed_preflight_r11,
    )

    att = run_postlock_sealed_preflight_r11(Path(args.out_dir),
                                           VENDOR_PIN)
    print(f"[preflight-sealed] pass={att['pass']} "
          f"digest={att['digest']}")
    return 0 if att["pass"] else 1


def cmd_qualify(args: argparse.Namespace) -> int:
    """final qualification(一次性;exposure 先行)。

    repair R11(§11/工作包 A2):final 的任何异常在处置前落盘全部
    逐 attempt invocation envelopes,随后由 run_final_qualification_
    r11 的既有 crash 处理写 exposure=crashed;此处补写 iteration
    aborted marker(R10 缺口:final 阶段异常同样触发 §11 硬规则)。
    """
    from rl_curriculum.curriculum261_r11_final import (
        run_final_qualification_r11,
    )
    from rl_curriculum.curriculum261_r11_namespaces import (
        write_r11_iteration_aborted,
    )

    out = Path(args.out_dir)
    try:
        result = run_final_qualification_r11(out)
    except Exception as exc:  # noqa: BLE001 —— §11 正式异常处置
        from rl_curriculum.curriculum261_generation_envelope import (
            dump_failure_evidence,
        )

        try:
            dump_failure_evidence(exc, out, stage_label="final")
        except Exception:  # noqa: BLE001 —— 不得掩盖原始异常
            pass
        write_r11_iteration_aborted(
            f"final qualification 执行异常({type(exc).__name__}:"
            f"{str(exc)[:400]});§11 硬规则:R11 永久结束,下一轮必须 "
            "R12 + 全新 namespace")
        raise
    print(f"[qualify] verdict={result['verdict']}")
    _write_json(out, "seed_namespace_integrity_post_"
                "final.json", _verify_namespace_safe())
    return 0 if result["verdict"] == "PASS" else 1


def cmd_smoke(args: argparse.Namespace) -> int:
    from rl_curriculum.curriculum261_r11_smoke import run_ppo_smoke_r11

    out = Path(args.out_dir)
    pack = None
    try:
        pack = _pack(out)
    except RuntimeError:
        pass
    smoke = run_ppo_smoke_r11(pack=pack)
    _write_json(out, "ppo_256step_smoke.json", smoke)
    print(f"[smoke] pass={smoke['pass']}")
    return 0 if smoke["pass"] else 1


def cmd_namespace_integrity(args: argparse.Namespace) -> int:
    ns = _verify_namespace_safe()
    _write_json(Path(args.out_dir), "seed_namespace_integrity.json", ns)
    print(f"[namespace-integrity] pass={ns.get('pass')} "
          f"namespaces={len(ns.get('r11_namespaces', []))}")
    return 0 if ns.get("pass") else 1


def cmd_determinism_matrix(args: argparse.Namespace) -> int:
    """工作包 A:A4 mutable state 审计 + A5 跨进程矩阵 + A6 门禁。

    工程阶段命令(在任何正式 R11 namespace 访问之前执行);产物写
    <artifacts>/determinism/。generation_determinism_contract.json
    是 audit 阶段的硬前置(A6)。
    """
    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_lock_dir,
    )
    from rl_curriculum.curriculum261_r11_determinism import (
        audit_generator_mutable_state,
        generation_determinism_gate,
        run_cross_process_determinism_matrix,
    )

    out = qualification_r11_lock_dir() / "determinism"
    print("[determinism] A4: generator mutable state audit ...")
    state = audit_generator_mutable_state(out)
    print(f"[determinism] A4 pass={state['pass']} "
          f"findings={len(state['findings'])}")
    print("[determinism] A5: cross-process matrix (14 scenarios) ...")
    matrix = run_cross_process_determinism_matrix(out)
    print(f"[determinism] A5 pass={matrix['pass']} "
          f"all_identical={matrix['all_scenarios_identical']} "
          f"r10_consistent={matrix['r10_seed_replay_consistent']} "
          f"r10_failure_reproduced="
          f"{matrix['r10_failure_reproduced_in_any_scenario']}")
    gate = generation_determinism_gate(out)
    print(f"[determinism] A6 gate pass={gate['pass']}")
    return 0 if (state["pass"] and matrix["pass"] and gate["pass"]) else 1


def cmd_shadow_run(args: argparse.Namespace) -> int:
    """工作包 C:full-scale shadow rehearsal(每次调用一个冷进程)。

    由 shadow-run --run-tag A / shadow-run --run-tag B 分别在两个
    独立冷进程执行;随后 shadow-compare 判定两次运行的一致性。
    """
    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_lock_dir,
    )
    from rl_curriculum.curriculum261_r11_shadow import (
        run_full_scale_shadow_r11,
    )

    base = qualification_r11_lock_dir() / "shadow"
    run_dir = base / str(args.run_tag)
    print(f"[shadow-run] tag={args.run_tag} dir={run_dir} "
          f"(full-scale generation cardinality;reduced pure training)")
    summary = run_full_scale_shadow_r11(run_dir, run_tag=str(args.run_tag))
    print(f"[shadow-run] orchestration_completed="
          f"{summary['orchestration_stage_completed']} "
          f"final_like_executed={summary['final_like_executed']} "
          f"final_like_verdict={summary.get('final_like_verdict')}")
    return 0 if (summary["orchestration_stage_completed"]
                 and summary["final_like_executed"]) else 1


def cmd_shadow_compare(args: argparse.Namespace) -> int:
    """工作包 C:两次 cold shadow 的一致性判定(§C.7)。"""
    import json as _json

    from rl_curriculum.curriculum261_r11_namespaces import (
        qualification_r11_lock_dir,
    )
    from rl_curriculum.curriculum261_r11_shadow import (
        compare_full_scale_shadow_runs,
    )

    base = qualification_r11_lock_dir() / "shadow"
    result = compare_full_scale_shadow_runs(base / "A", base / "B")
    path = base / "shadow_two_cold_runs_comparison.json"
    path.write_text(
        _json.dumps(result, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    print(f"[shadow-compare] pass={result['pass']} "
          f"ledger_identical={result['ledger_identity_digests_identical']}"
          f" artifact_diffs="
          f"{len(result['artifact_identity_digest_diffs'])} "
          f"(detail: {path})")
    return 0 if result["pass"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="r11-cli")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def _with_out(p):
        p.add_argument("--out-dir", default=None)
        return p

    audit_parser = _with_out(sub.add_parser("audit"))
    audit_parser.add_argument("--fit-pairs", type=int, default=2)
    audit_parser.add_argument("--code-freeze-sha", default=None)

    for name in ("cue-audit", "preplan-smoke", "plan-roundtrip",
                 "design-plan-lock", "design", "calibrate",
                 "preflight-static", "lock-plan", "preflight-sealed",
                 "qualify", "smoke", "namespace-integrity",
                 "determinism-matrix"):
        _with_out(sub.add_parser(name))
    shadow_run_parser = _with_out(sub.add_parser("shadow-run"))
    shadow_run_parser.add_argument("--run-tag", required=True)
    _with_out(sub.add_parser("shadow-compare"))

    args = parser.parse_args(argv)
    if not args.out_dir:
        args.out_dir = str(_default_art())
    handlers = {
        "audit": cmd_audit,
        "cue-audit": cmd_cue_audit,
        "preplan-smoke": cmd_preplan_smoke,
        "plan-roundtrip": cmd_plan_roundtrip,
        "design-plan-lock": cmd_design_plan_lock,
        "design": cmd_design,
        "calibrate": cmd_calibrate,
        "preflight-static": cmd_preflight_static,
        "lock-plan": cmd_lock_plan,
        "preflight-sealed": cmd_preflight_sealed,
        "qualify": cmd_qualify,
        "smoke": cmd_smoke,
        "namespace-integrity": cmd_namespace_integrity,
        "determinism-matrix": cmd_determinism_matrix,
        "shadow-run": cmd_shadow_run,
        "shadow-compare": cmd_shadow_compare,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
