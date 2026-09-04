# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R15:clean matched-ladder design(dedicated semantic
corpus 先行 + corrected plan digest roundtrip + §21/§22 流程 + §18
一次性硬规则)。

R15 相对 R8 的工程修复(规范 §5/§6/§8;统计合同零修改):
- c2_density_summary 从 curriculum261_r5_pairs 导入(R8 误写
  r6_pairs,函数体延迟 import 使 ImportError 逃过 plan 锁前全部
  静态检查,在第一个 candidate 真实评估时爆发 → R8 按 §8.4 永久
  结束);
- evaluator/marginal guard 全部关键依赖提升到模块 import 时解析;
- semantic main/validation artifact 改为显式穷尽映射 + exclusive
  create + reload 校验 + 双文件哈希不同检查(R8 的
  endswith("main") 使 main artifact 被 validation 覆盖);
- matched-ladder 核心身份对拍源从 R7 plan 改为 R8 plan(R8 为最新
  冻结声明;冻结模块未变,记录值必须一致)。

R7 教训(R15 硬输入):
- R7 design plan 的 digest 自引用缺陷:lock 把 design_plan_digest
  写回 payload,而 digest 复算只排除 locked_utc → 正式 loader 永远
  mismatch → R7 design 只能靠未入库的临时 driver 执行(development
  evidence)。R15 修复(§8):digest 复算排除 (locked_utc,
  design_plan_digest) 双字段;payload 自带 digest 同时可经正式
  load_locked_design_plan_r15 复算——正式 lock/load/digest recompute/
  code identity verify/design execution 全部走同一份仓库内实现,
  禁止任何临时 driver;
- R7 shared cue gate 直接用 40-block candidate design corpus,SE
  ≈0.007-0.0085 → 单侧 LCB 偶然失败概率过高(main LCB 0.912 <
  floor 0.930)。R15(§14/§15)把 candidate-independent cue 语义拆到
  预注册 160-block dedicated semantic corpus(每 corpus 独立 gate,
  FAIL 即 R15 design FAIL,不进入 candidate 设计);
- R7 的 R6 marginal-guard semantics 键错配(cue_semantics vs R6 冻结
  实现要求的 cue_payoff_separation;R7 calibration 未执行故未暴露)
  ——R15 显式组装:R6 统计条件 + 本模块语义条件(local cue ∧
  context ∧ v2 independent cue semantics)。

§8.4 一次性硬规则:正式 R15 design plan 锁定后发生任何 loader/代码
缺陷 => write_r15_iteration_aborted + R15 永久结束(保留 plan、不重锁、
不复用 namespace、下一轮 R15);run_design_stage_r15 内部任何
异常都会转 aborted(fail closed)。

matched-ladder 核心(R6 冻结实现,零修改复用):generate_matched_
block_with_attempts / build_c2_block_evidence_table / matched_gap_
stats / simulate_formal_gate_pass_r6_matched / scrambled_gap_control
全部 import 自 curriculum261_r6_tape / curriculum261_r6_pairs;
§7 要求:R15 在 plan lock 前验证这些模块与 R7 baseline 的 SHA256
一致(verify_matched_core_identity_r7)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np

from rl_platform.versions import (
    ENV_CORE_VERSION,
    OBSERVATION_SPEC_VERSION,
)

from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
from rl_curriculum.curriculum261_c2 import FAMILY_C2
from rl_curriculum.curriculum261_pairs import family_specs, generate_pair
from rl_curriculum.curriculum261_r6_pairs import (
    C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
    C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6,
    FORMAL_BLOCK_OPTIONS,
    R6_POSITIVE_GAP_RATE_MIN,
    block_difficulty_series,
    block_gap_series,
    block_margin_series,
    build_c2_block_evidence_table,
    c2_marginal_guard_conditions,
    check_c2_cue_payoff_separation,
    scrambled_gap_control,
    simulate_formal_gate_pass_r6_matched,
)
from rl_curriculum.curriculum261_r6_param_pack import (
    R4_PARAMETER_PACK_DIGEST,
    R5_DESIGN_PLAN_DIGEST,
    ladder_distance_from_historical,
    validate_ladder_semantics,
)
from rl_curriculum.curriculum261_r6_tape import (
    block_attempt_statistics,
    generate_matched_block_with_attempts,
    matched_block_corpus_summary,
    matched_ladder_contract_identity,
)
from rl_curriculum.curriculum261_r5_pairs import (
    c2_density_summary,
    corpus_conditions_r5,
    density_gate_r5,
)
from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
from rl_curriculum.curriculum261_qualification import (
    check_c2_context_observability,
    check_c2_local_cue_independence,
)
from rl_curriculum.curriculum261_r4_pairs import (
    evaluate_pair_corpus_r4,
    rung_report_r4,
)
from rl_curriculum.curriculum261_r6_design import (
    _reference_long_label_rate as _reference_long_label_rate_impl,
)
from rl_curriculum.curriculum261_r15_cue_contract import (
    ABSOLUTE_MINIMUM_RECALL,
    C2_CUE_PRECISION_MIN,
    C2_NON_CUE_FALSE_POSITIVE_MAX,
    C2_PAYOFF_BAR_FALSE_CUE_MAX,
    C2_CUE_SEMANTIC_CONTRACT_VERSION,
    MIN_UNIQUE_POSITIVE_CUES,
    NONINFERIORITY_DELTA,
    cue_semantic_contract_digest,
    recall_floor,
)
from rl_curriculum.curriculum261_r15_cue_eval import (
    candidate_cue_semantics,
    cue_semantic_rule_identity,
    independent_cue_semantics,
    semantic_cue_gate,
)
from rl_curriculum.curriculum261_r15_namespaces import (
    design_data_started,
    mark_design_data_started,
    require_r15_iteration_active,
    write_r15_iteration_aborted,
)
from rl_curriculum.curriculum261_r15_param_pack import (
    C2_LADDER_CANDIDATES_R15,
    R6_DESIGN_PLAN_DIGEST,
    R7_DESIGN_PLAN_DIGEST,
    R8_DESIGN_PLAN_DIGEST,
    R15_PACK_VERSION,
    ladder_pack_payload_r15,
    ladder_distance_from_historical_r15,
    load_selected_pack,
    pack_digest_r15,
    r15_candidate_grid,
    validate_r15_grid_semantics,
    write_selected_pack_r15,
)

DESIGN_FORMAT_R15 = "cur261-r15-design-plan-v1"
DESIGN_BLOCKS_PER_CORPUS_R15 = 40
DESIGN_NAMESPACES_R15 = ("design_r15_matched_main",
                        "design_r15_matched_validation")
DESIGN_INDEPENDENT_NAMESPACE_R15 = "design_r15_independent_marginal"
DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R15 = 20

#: §14/§15 dedicated semantic corpus(candidate-independent;在任何
#: R15 design data 生成前锁定;数据后禁止 160→240 扩样/第三 corpus/
#: 合并/删除)。
SEMANTIC_BLOCKS_PER_CORPUS_R15 = 160
SEMANTIC_NAMESPACES_R15 = ("cue_semantic_design_main_r15",
                          "cue_semantic_design_validation_r15")

#: §R15-8 semantic artifact 显式穷尽映射(禁止 endswith/后缀启发式;
#: R8 的 endswith("main") 使 main artifact 被 validation 覆盖)。
SEMANTIC_ARTIFACT_MAP_R15 = {
    "cue_semantic_design_main_r15": "semantic_design_main.json",
    "cue_semantic_design_validation_r15":
        "semantic_design_validation.json",
}
#: calibration/holdout/final 三阶段的 semantic artifact 显式映射。
SEMANTIC_STAGE_ARTIFACT_MAP_R15 = {
    "cue_semantic_calibration_r15": "cue_semantic_calibration.json",
    "cue_semantic_holdout_r15": "cue_semantic_holdout.json",
    "cue_semantic_qualification_r15":
        "qualification_cue_semantics.json",
    # preplan full pipeline rehearsal(§12;非正式;同一 writer)
    "preplan_semantic_main_r15": "preplan_semantic_main.json",
    "preplan_semantic_validation_r15":
        "preplan_semantic_validation.json",
    # full-scale shadow(工程;R15 工作包 C)
    "shadow_semantic_main_r15": "shadow_semantic_main.json",
    "shadow_semantic_validation_r15": "shadow_semantic_validation.json",
    "shadow_semantic_final_r15": "shadow_semantic_final.json",
    # R15RealArtifactCliRoundTrip-v1(rehearsal-only;§四-4)
    "rt_semantic_design_main_r15": "rt_semantic_design_main.json",
    "rt_semantic_design_validation_r15":
        "rt_semantic_design_validation.json",
    "rt3_semantic_main_r15": "rt_semantic_main.json",
    "rt3_semantic_validation_r15": "rt_semantic_validation.json",
    "rt3_semantic_final_r15": "rt_semantic_final.json",
}
SEMANTIC_CORPUS_ROLE_R15 = {
    "cue_semantic_design_main_r15": "main",
    "cue_semantic_design_validation_r15": "validation",
    "cue_semantic_calibration_r15": "calibration",
    "cue_semantic_holdout_r15": "holdout",
    "cue_semantic_qualification_r15": "qualification",
    "preplan_semantic_main_r15": "preplan_main",
    "preplan_semantic_validation_r15": "preplan_validation",
    "shadow_semantic_main_r15": "shadow_main",
    "shadow_semantic_validation_r15": "shadow_validation",
    "shadow_semantic_final_r15": "shadow_final",
    "rt_semantic_design_main_r15": "rt_design_main",
    "rt_semantic_design_validation_r15": "rt_design_validation",
    "rt3_semantic_main_r15": "rt_main",
    "rt3_semantic_validation_r15": "rt_validation",
    "rt3_semantic_final_r15": "rt_final",
}


def semantic_artifact_filename_r15(namespace: str) -> str:
    """§R15-8:namespace → 文件名的唯一合法路径(穷尽映射)。"""
    for table in (SEMANTIC_ARTIFACT_MAP_R15,
                  SEMANTIC_STAGE_ARTIFACT_MAP_R15):
        if namespace in table:
            return table[namespace]
    known = sorted(set(SEMANTIC_ARTIFACT_MAP_R15)
                   | set(SEMANTIC_STAGE_ARTIFACT_MAP_R15))
    raise RuntimeError(
        f"semantic namespace {namespace} 不在显式映射表(§R15-8:禁止 "
        f"endswith/后缀启发式;已知 namespace: {known})")


def semantic_artifact_identity_r15() -> dict[str, Any]:
    """§R15-8 artifact writer 身份(进入 design plan code identity)。"""
    return {
        "design_mapping": dict(SEMANTIC_ARTIFACT_MAP_R15),
        "stage_mapping": dict(SEMANTIC_STAGE_ARTIFACT_MAP_R15),
        "roles": dict(SEMANTIC_CORPUS_ROLE_R15),
        "heuristic_suffix_match_forbidden": True,
        "write_mode": "exclusive-create(O_CREAT|O_EXCL;已存在即拒)",
        "reload_check": "embedded namespace/corpus_role 与显式映射一致",
        "dual_file_gate": "design main+validation 同时存在且 sha256 "
                          "不同,才允许生成 candidate blocks",
    }


def write_semantic_artifact_r15(out_dir: Path, namespace: str,
                               payload: dict[str, Any],
                               plan_digest: str,
                               event_rows: list[dict[str, Any]] | None
                               = None,
                               ) -> Path:
    """§R15-8:exclusive-create 写 semantic artifact(json + jsonl),
    内嵌 namespace/corpus_role/plan_digest/event_count,写完立即
    reload 校验 embedded namespace 与显式映射一致。"""
    import os

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = semantic_artifact_filename_r15(namespace)
    path = out_dir / fname
    body = dict(payload)
    body["namespace"] = namespace
    body["corpus_role"] = SEMANTIC_CORPUS_ROLE_R15[namespace]
    body["design_plan_digest"] = plan_digest
    body["event_count"] = len(event_rows or [])
    blob = json.dumps(body, indent=2, ensure_ascii=False, default=float)
    fd = os.open(str(path),
                 os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    try:
        os.write(fd, blob.encode("utf-8"))
    finally:
        os.close(fd)
    back = json.loads(path.read_text(encoding="utf-8"))
    if (back.get("namespace") != namespace
            or back.get("corpus_role")
            != SEMANTIC_CORPUS_ROLE_R15[namespace]):
        raise RuntimeError(
            f"semantic artifact reload 校验失败:{fname} 内嵌 "
            f"namespace/role 与写入值不一致")
    if event_rows:
        jpath = out_dir / fname.replace(".json", ".jsonl")
        with open(jpath, "w", encoding="utf-8") as fh:
            for e in event_rows:
                fh.write(json.dumps({"corpus": namespace, **e},
                                    ensure_ascii=False) + "\n")
    return path

DESIGN_TARGET_GAP_FACTOR = 3.0
DESIGN_TARGET_D3_FACTOR = 2.5
DESIGN_TARGET_MARGIN_FACTOR = 2.5
DESIGN_TARGET_GATE_PROB = 0.90

#: §16.1/§21 code identity 覆盖面(R15 全部实现 + 冻结复用模块 +
#: 合同依赖;design data 生成开始后任何漂移 => iteration aborted)。
DESIGN_CODE_MODULES_R15 = (
    "curriculum261_api.py",
    "curriculum261_c2.py",
    "curriculum261_pairs.py",
    "curriculum261_qualification.py",
    "curriculum261_r4_pairs.py",
    "curriculum261_r5_pairs.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r6_param_pack.py",
    "curriculum261_r6_namespaces.py",
    "curriculum261_r6_pairs.py",
    "curriculum261_r15_noise_replay.py",
    "curriculum261_r15_cue_contract.py",
    "curriculum261_r15_cue_eval.py",
    "curriculum261_r15_dependencies.py",
    "curriculum261_r15_routing.py",
    "curriculum261_r15_reference.py",
    "curriculum261_r15_labels.py",
    "curriculum261_r15_orchestrator.py",
    "curriculum261_r15_delegation.py",
    "curriculum261_r15_rehearsal.py",
    "curriculum261_r15_namespaces.py",
    "curriculum261_r15_param_pack.py",
    "curriculum261_r15_preplan.py",
    "curriculum261_r15_design.py",
    "curriculum261_r15_calibration.py",
    "curriculum261_r15_plan.py",
    "curriculum261_r15_preflight.py",
    "curriculum261_r15_final.py",
    "curriculum261_r15_smoke.py",
    "curriculum261_r15_cli.py",
)

#: §7 matched-ladder 核心 + C2 generator 模块(必须与 R7 baseline 的
#: SHA256 一致;R7 design plan 的 code_identity 记录值对拍)。
MATCHED_CORE_MODULES_R15 = (
    "curriculum261_c2.py",
    "curriculum261_r6_tape.py",
    "curriculum261_r6_pairs.py",
)


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def _code_identity_design() -> dict[str, str]:
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    out: dict[str, str] = {}
    for name in DESIGN_CODE_MODULES_R15:
        f = root / name
        out[name] = hashlib.sha256(
            f.read_bytes()).hexdigest() if f.is_file() else "MISSING"
    return out


def _r10_design_plan_path() -> Path:
    return (Path(__file__).resolve().parents[2] / "artifacts"
            / "route_c_stage2_6_1_repair10" / "r10_design_plan.json")


def verify_matched_core_identity_r10() -> dict[str, Any]:
    """§7:matched-ladder 核心模块与 R10 baseline 的 SHA256 一致。

    R10 的 design plan 在 lock 时记录了全部依赖模块的 sha256;R15
    不修改 c2 generator / matched tape / matched pairs 三个模块,
    当前哈希必须与 R10 记录值逐位一致(R15 对 api.py 的改动仅限
    R15 namespace 白名单、解锁守卫与被动 recorder 钩子的追加,
    paired_noise/seed 派生行为由 exact replay 测试逐位锁定)。对拍
    源从 R9 plan 升级为 R10 plan(R10 为最新冻结声明;R10 design
    阶段完整通过后于 calibrate/supervised main 诚实 FAIL)。
    """
    import rl_curriculum

    root = Path(rl_curriculum.__file__).parent
    path = _r10_design_plan_path()
    if not path.is_file():
        return {
            "pass": False,
            "error": f"R10 design plan 不存在: {path}(无法对拍 "
                     "matched-ladder 模块身份)",
            "modules": {},
        }
    r10_plan = json.loads(path.read_text(encoding="utf-8"))
    r10_identity = r10_plan.get("code_identity", {})
    rows: dict[str, Any] = {}
    ok = True
    for name in MATCHED_CORE_MODULES_R15:
        current = (hashlib.sha256((root / name).read_bytes()).hexdigest()
                   if (root / name).is_file() else "MISSING")
        locked = r10_identity.get(name)
        match = bool(current == locked and current != "MISSING")
        ok = ok and match
        rows[name] = {"r10_locked": locked, "r15_current": current,
                      "match": match}
    return {"r10_design_plan_digest": r10_plan.get("design_plan_digest"),
            "modules": rows, "pass": bool(ok)}


# ------------------------------------------------------------- plan
def design_plan_payload_r15(*, baseline_commit: str, vendor_pin: str,
                           v2_contract_digest: str,
                           prior_r2_plan_digest: str,
                           prior_diag262r2_plan_digest: str,
                           cue_audit: dict[str, Any],
                           preplan_smoke_identity: dict[str, Any],
                           dependency_identity: dict[str, Any],
                           artifact_writer_identity: dict[str, Any],
                           preplan_rehearsal_digest: str,
                           r8_abort_evidence: dict[str, Any],
                           r9_abort_evidence: dict[str, Any] | None = None,
                           r10_abort_evidence: dict[str, Any] | None = None,
                           r11_abort_evidence: dict[str, Any] | None = None,
                           r12_abort_evidence: dict[str, Any] | None = None,
                           r13_abort_evidence: dict[str, Any] | None = None,
                           generation_determinism_binding: dict[str, Any]
                           | None = None,
                           code_freeze_sha: str = "",
                           policy_visible_reference_contract_digest: str = "",
                           cue_audit_plan_digest: str = "",
                           design_namespaces: tuple[str, ...]
                           | list[str] | None = None,
                           semantic_namespaces: tuple[str, ...]
                           | list[str] | None = None,
                           blocks_per_candidate_per_corpus: int | None = None,
                           semantic_blocks: int | None = None,
                           independent_namespace: str | None = None,
                           independent_pairs_per_rung: int | None = None,
                           rehearsal: bool = False,
                           ) -> dict[str, Any]:
    """构建并返回 R15 design plan payload(锁定后不得修改任何字段)。

    §21 绑定清单全集:baseline/vendor/R4 pack/R5+R6+R7 historical
    digests/V2 contract/matched contract(+R10 baseline 模块身份对拍)/
    cue semantic contract v2/corrected p_contract/noninferiority
    delta/recall floor/semantic block count 160/candidate grid(恰好
    3)/formal block options/design block count 40/全部阈值/selection
    rule/independent marginal guard(点护栏)/code identity/Route C
    identity/preplan smoke identity/plan digest roundtrip 合同/R9+R10+
    R11+R12 abort evidence/generation determinism contract(工作包 A6)。

    namespace/scale 覆盖参数默认为正式值;R15RealArtifactCliRoundTrip
    -v1 的 --rehearsal 路径以 rt_* rehearsal-only namespace 与
    rehearsal=True 标记调用(样本量与正式一致;只允许 rehearsal 改
    namespace 与标记,§四-4)。rehearsal plan 不得用于正式阶段。
    """
    grid = r15_candidate_grid()
    problems = validate_r15_grid_semantics()
    if problems:
        raise RuntimeError(f"R15 candidate grid 语义非法: {problems}")
    matched_core = verify_matched_core_identity_r10()
    if not matched_core["pass"]:
        raise RuntimeError(
            f"matched-ladder 核心模块与 R10 baseline 身份不一致(§7): "
            f"{matched_core}")
    p_contract = float(cue_audit["p_contract"])
    floor = recall_floor(p_contract)
    eff_design_namespaces = tuple(design_namespaces
                                  or DESIGN_NAMESPACES_R15)
    eff_semantic_namespaces = tuple(semantic_namespaces
                                    or SEMANTIC_NAMESPACES_R15)
    eff_blocks = int(blocks_per_candidate_per_corpus
                     or DESIGN_BLOCKS_PER_CORPUS_R15)
    eff_semantic_blocks = int(semantic_blocks
                              or SEMANTIC_BLOCKS_PER_CORPUS_R15)
    eff_independent_namespace = (independent_namespace
                                 or DESIGN_INDEPENDENT_NAMESPACE_R15)
    eff_independent_pairs = int(independent_pairs_per_rung
                                or DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R15)
    if len(eff_design_namespaces) != 2 or len(eff_semantic_namespaces) != 2:
        raise RuntimeError(
            "design/semantic corpora 必须各为 2(main/validation;"
            f"实际 design={eff_design_namespaces} semantic="
            f"{eff_semantic_namespaces})")
    return {
        "format": DESIGN_FORMAT_R15,
        "iteration": "r15",
        "rehearsal": bool(rehearsal),
        "rehearsal_contract": (
            "R15RealArtifactCliRoundTrip-v1(rehearsal-only namespace;"
            "不进入正式阶段;正式 plan 必须无本标记)" if rehearsal else ""),
        "baseline_commit": baseline_commit,
        "vendor_pin": vendor_pin,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest": R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest": R6_DESIGN_PLAN_DIGEST,
        "r7_design_plan_digest": R7_DESIGN_PLAN_DIGEST,
        "r8_design_plan_digest": R8_DESIGN_PLAN_DIGEST,
        "preprocessing_v2_contract_digest": v2_contract_digest,
        "prior_digests": {
            "stage2_6_1_r2_qualification_plan_digest": prior_r2_plan_digest,
            "stage2_6_2_r2_diagnostic_plan_digest":
                prior_diag262r2_plan_digest,
        },
        "route_c_identities": {
            "env_core_version": ENV_CORE_VERSION,
            "observation_spec_version": OBSERVATION_SPEC_VERSION,
        },
        "dependency_resolution_identity": dependency_identity,
        "artifact_writer_identity": artifact_writer_identity,
        "preplan_rehearsal_digest": preplan_rehearsal_digest,
        "r8_abort_evidence": r8_abort_evidence,
        "r9_abort_evidence": r9_abort_evidence or {},
        "r10_abort_evidence": r10_abort_evidence or {},
        "r11_abort_evidence": r11_abort_evidence or {},
        "r12_abort_evidence": r12_abort_evidence or {},
        "r13_abort_evidence": r13_abort_evidence or {},
        "generation_determinism_binding": generation_determinism_binding
        or {},
        "code_freeze_sha": code_freeze_sha,
        "policy_visible_reference_contract_digest": (
            policy_visible_reference_contract_digest),
        "cue_audit_plan_digest": cue_audit_plan_digest,
        "plan_digest_contract": {
            "digest_fields_excluded": ["locked_utc",
                                       "design_plan_digest"],
            "self_reference_free": True,
            "roundtrip": "build -> lock(O_CREAT 语义:已存在即拒) -> "
                         "load_locked_design_plan_r15(独立进程) -> "
                         "recompute -> compare -> no-data validation;"
                         "design_plan_digest 写入 payload 但被复算排除"
                         "(与 pack digest 同一模式,经 plan-roundtrip "
                         "子命令在临时目录真实验证)",
            "one_shot_rule": "§8.4:正式 plan 锁定后任何 loader/代码"
                             "缺陷 => R15 永久结束(aborted;不删不重锁;"
                             "不复用 namespace;下一轮 R15)",
        },
        "matched_ladder": {
            "contract_version": "C2MatchedLadderBlock-v1",
            "contract_identity": matched_ladder_contract_identity(),
            "implementation": "R6 冻结实现零修改复用(import,不复制);"
                              "R6 tape/pairs + C2 generator 模块 sha256 "
                              "进入 code_identity 且与 R8 baseline 记录"
                              "值对拍(verify_matched_core_identity_r9)",
            "matched_core_identity_r8": matched_core,
            "shared_components": [
                "cue_time_table", "cue_direction_table",
                "wick_direction_context_chain",
                "wick_width_context_chain", "volume_path",
                "base_noise_innovations", "wick_jitter",
                "initial_price", "episode_duration", "bar_timestamps",
                "ab_variant_structure"],
            "rung_varying": ["alpha_bps", "wick_kappa"],
            "block_attempt_semantics": {
                "max_attempts": 5,
                "unit": "完整四-rung block",
            },
        },
        "cue_semantic_contract": {
            "version": C2_CUE_SEMANTIC_CONTRACT_VERSION,
            "contract_digest": cue_semantic_contract_digest(),
            "rule_identity": cue_semantic_rule_identity(),
            "audit_digest": cue_audit["audit_digest"],
            "audit_pass": bool(cue_audit.get("pass")),
            "p_contract": p_contract,
            "noninferiority_delta": NONINFERIORITY_DELTA,
            "absolute_minimum_recall": ABSOLUTE_MINIMUM_RECALL,
            "recall_floor": floor,
            "recall_floor_formula": "max(absolute_minimum_recall, "
                                    "p_contract - noninferiority_delta)",
            "mirror_bound": "lo = max(1, t-16); hi = min(t-8, n-17)",
            "cluster_unit": "matched_block",
            "canonical_observation": "D0/A",
            "cluster_bootstrap": {
                "resamples": 20000, "seed": 20261010,
                "method": "重采样完整 matched block;cluster 内 pooled "
                          "聚合;lower = α 分位(单侧 95% LCB),upper = "
                          "1-α 分位(单侧 95% UCB)",
            },
            "shared_gate_candidate_independent": True,
            "candidate_specific": ["payoff-bar false-cue UCB",
                                   "cue precision LCB"],
            "thresholds": {
                "cue_precision_min": C2_CUE_PRECISION_MIN,
                "non_cue_false_positive_max":
                    C2_NON_CUE_FALSE_POSITIVE_MAX,
                "payoff_bar_false_cue_max": C2_PAYOFF_BAR_FALSE_CUE_MAX,
                "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
            },
        },
        "semantic_corpora": {
            "blocks_per_corpus": eff_semantic_blocks,
            "namespaces": list(eff_semantic_namespaces),
            "ladder": "冻结 sentinel ladder(cur261-c2-v9 默认 D0-D3;"
                      "candidate-independent;与任何 R15 candidate 数值"
                      "无依赖)",
            "sample_size_rationale": "R7 40 blocks 的 bootstrap SE "
                                     "≈0.0069-0.0085,point≈0.95/"
                                     "floor≈0.93 时单侧 LCB 偶然失败概率"
                                     "过高;40→160 使 block-cluster SE "
                                     "理论上减半,LCB 有明确余量(§14;"
                                     "数据后禁止扩样/第三 corpus/合并/"
                                     "删除)",
            "min_unique_positive_cues": MIN_UNIQUE_POSITIVE_CUES,
            "gate": "每 corpus 独立:unique-event coverage ≥3600 / "
                    "canonical consistency / recall LCB ≥ recall_floor /"
                    " non-cue FP UCB ≤0.01 / per-event K 完整 / noise "
                    "replay 完整性;任一 FAIL => R15 design FAIL(§15)",
            "candidate_decoupling": "shared cue 指标不进入 candidate "
                                    "maximin score;candidate-specific "
                                    "precision/false-cue 在 40-block "
                                    "candidate corpus 评估(§16)",
        },
        "candidate_grid": {
            "candidates": {k: {r: dict(v[r])
                               for r in ("D0", "D1", "D2", "D3")}
                           for k, v in grid.items()},
            "n_candidates": len(grid),
            "allowed_axes": ["alpha_bps", "wick_kappa"],
            "historical_control": "c2l_historical_control(冻结默认;"
                                  "非选择性 control,不达标不得被选中)",
            "grid_bounds": "§17:数量恰好 3(禁止第四个);非历史 "
                           "candidate 的 D3 alpha∈[28,32];严格单调;"
                           "三候选覆盖 D3 28/30/32",
        },
        "design_data": {
            "blocks_per_candidate_per_corpus": eff_blocks,
            "corpora": list(eff_design_namespaces),
            "corpora_role": "main/validation 均为参数开发数据,不得称为"
                            "holdout",
            "evaluation_mode": "raw(preproc=None)",
            "block_schedule_sharing": "不同 candidate 的同 block_index "
                                      "结构带逐位一致(seed 派生不含难度"
                                      "参数)",
        },
        "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
        "statistics": {
            "pair_table": "R4 唯一 pair 证据表(evaluate_pair_corpus_r4)",
            "block_table": "唯一 C2 block 证据表(r6bt schema)",
            "difficulty": "reference_pair - always_flat_pair",
            "gap_se": "std(blockwise gap, ddof=1)/sqrt(n_blocks);禁止 "
                      "sqrt(SE_hi^2+SE_lo^2)",
            "power_targets": {
                "gap_ge": f"{DESIGN_TARGET_GAP_FACTOR}x expected block SE",
                "d3_ge": f"{DESIGN_TARGET_D3_FACTOR}x expected block SE",
                "margins_d2_d3_ge": f"{DESIGN_TARGET_MARGIN_FACTOR}x "
                                    "expected block SE",
                "positive_gap_block_rate_min": R6_POSITIVE_GAP_RATE_MIN,
                "formal_gate_probability_min": DESIGN_TARGET_GATE_PROB,
            },
            "formal_gate_simulation": {
                "n_sim": 20000, "seed": 20260922,
                "resample_unit": "完整 block(bootstrap 不拆块)",
            },
            "scrambled_control": "仅诊断(permute 后 unpaired SE 对比;"
                                 "不参与任何 PASS 判定)",
        },
        "independent_marginal_guard": {
            "namespace": eff_independent_namespace,
            "pairs_per_rung": eff_independent_pairs,
            "conditions": "marginal ordering / D3 positive / 基线 margins"
                          ">0 / integrity=1.0 / oracle / 密度 / local "
                          "cue independence / context observability / "
                          "independent cue 语义;cue recall 只用点估计 ≥ "
                          "0.90 的灾难性退化护栏(正式 cluster gate 由 "
                          "160-block dedicated semantic corpus 承担;§26)"
                          ";matched PASS 不可覆盖 FAIL;失败 → R15 = FAIL",
            "timing": "design 选定 candidate 后、pack 锁定前",
        },
        "selection_rule": {
            "qualification": "(candidate, n) 在两个 design corpus 均满足"
                             "全部 matched power 硬门槛 + candidate-"
                             "specific 语义(§23/§24);shared cue gate "
                             "在 dedicated semantic corpus 独立完成"
                             "(§15)",
            "order": ["最小 formal block count n(10→15→20)",
                      "maximin score 最大(该 n 下)",
                      "参数偏离历史最小", "candidate id 稳定排序"],
            "maximin_score": "min over {gap/SE ×3, d3/SE, d3 margin/SE "
                             "×2, pos_rate/0.65, 密度比, payoff-fc UCB "
                             "余量 1-fc/0.06, precision LCB 余量 "
                             "prec/0.85} × 两 corpus(不含 shared recall;"
                             "§16)",
            "hard_rule": "先选最小 n,再选该 n 下 score 最高者;平局取 "
                         "distance 最小;禁止事后扩大 block 数;禁止删除"
                         "失败 candidate;不得用 R6/R7 的 n=15 结果预指定"
                         "(§18 全新 data 机械选择)",
        },
        "fail_path": {
            "on_cue_audit_fail": "cue audit FAIL → 不得锁 design plan"
                                 "(§12)",
            "on_semantic_gate_fail": "任一 semantic corpus gate FAIL → "
                                     "R15 design FAIL(不生成 candidate "
                                     "blocks;§15/§25)",
            "on_no_qualified_combination": "R15 = FAIL;自动 power/semantic "
                                           "summary;保留 block tables;"
                                           "报告 binding condition;不生成"
                                           " pack;不访问 marginal/"
                                           "calibration/final namespace;"
                                           "不写 exposure marker;不运行 "
                                           "full-cold(§25)",
            "no_rescue": "不得通过修改 recall floor/delta/candidate/n/"
                         "semantic block count 救援;不得追加 blocks 或换"
                         "语料救援",
        },
        "preplan_smoke_identity": preplan_smoke_identity,
        "code_identity": _code_identity_design(),
    }


def design_plan_digest_r15(plan: dict[str, Any]) -> str:
    """§8.1 修复:digest 复算排除 locked_utc 与 design_plan_digest
    (R7 的自引用缺陷:digest 写回 payload 而复算不排除该字段)。"""
    payload = dict(plan)
    payload.pop("locked_utc", None)
    payload.pop("design_plan_digest", None)
    return "r15dp-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def lock_design_plan_r15(out_dir: Path, plan: dict[str, Any],
                        ) -> tuple[Path, str]:
    """锁定 design plan(已存在即拒——不删旧重锁)。"""
    from datetime import datetime, timezone

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "r15_design_plan.json"
    if path.exists():
        raise RuntimeError(
            f"R15 design plan 已存在: {path}(§8.4 禁止删除/覆盖/重锁;"
            "重锁必须换新 iteration R15)")
    digest = design_plan_digest_r15(plan)
    plan = dict(plan)
    plan["design_plan_digest"] = digest
    plan["locked_utc"] = datetime.now(timezone.utc).isoformat(
        timespec="seconds")
    path.write_text(json.dumps(plan, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r15_design_plan_digest.txt").write_text(
        digest, encoding="utf-8")
    return path, digest


def load_locked_design_plan_r15(out_dir: Path,
                               ) -> tuple[dict[str, Any], str]:
    """正式 loader(唯一读取路径;与 lock 同一 digest 语义)。

    digest 复算排除 (locked_utc, design_plan_digest) —— 与 lock 写入
    的字段对称,R7 的 roundtrip 断裂在此修复;复算失败 fail closed。
    """
    out_dir = Path(out_dir)
    path = out_dir / "r15_design_plan.json"
    if not path.is_file():
        raise RuntimeError(f"R15 design plan 未锁定: {path}")
    plan = json.loads(path.read_text(encoding="utf-8"))
    digest = design_plan_digest_r15(plan)
    if plan.get("design_plan_digest") != digest:
        raise RuntimeError("R15 design plan digest 复算不一致(fail closed)")
    digest_path = out_dir / "r15_design_plan_digest.txt"
    if not digest_path.is_file() or \
            digest_path.read_text(encoding="utf-8").strip() != digest:
        raise RuntimeError("R15 design plan digest 文件与 payload 不一致")
    return plan, digest


def verify_design_code_identity(plan: dict[str, Any]) -> dict[str, Any]:
    """§8.4:design data 已生成后 code identity 漂移 => aborted。"""
    current = _code_identity_design()
    locked = plan.get("code_identity", {})
    drift = {k: {"locked": locked.get(k), "current": current[k]}
             for k in current
             if locked.get(k) != current[k]}
    if drift and design_data_started():
        write_r15_iteration_aborted(
            f"design data 已生成后 code identity 漂移: {sorted(drift)}")
    return {
        "current": current,
        "drift": drift,
        "pass": not drift,
    }


# ------------------------------------------------- candidate 评估
def _se_at_n(sd: float, n: int) -> float:
    return float(sd) / float(np.sqrt(n))


def _reference_long_label_rate(records: list[Any], rung_params: dict,
                               thresholds: dict) -> float:
    # R15:依赖在模块 import 时解析(§6.2;R8 的函数内延迟 import 使
    # ImportError 逃过 plan 锁前的全部静态检查)。
    return _reference_long_label_rate_impl(
        records, rung_params, thresholds)


def _evaluate_candidate_matched_r15(
        candidate_id: str, ladder: dict[str, dict[str, Any]],
        corpus_ns: str, thresholds: dict,
        blocks: list[Any] | None = None,
        n_blocks: int = DESIGN_BLOCKS_PER_CORPUS_R15,
) -> dict[str, Any]:
    """单 candidate 在单 design corpus:matched blocks(可注入已生成的
    blocks)→ 唯一 pair 表 → 唯一 block 表 → 全部 n 选项硬门槛 +
    R15 candidate-specific 语义(§23;precision LCB ≥0.85 / payoff
    false-cue UCB ≤0.06 按 rung × side)。"""
    if blocks is None:
        blocks = [generate_matched_block_with_attempts(
            ladder, namespace=corpus_ns, block_index=i)
            for i in range(n_blocks)]
    records = [blk.pair_records[rung]
               for blk in blocks for rung in CURRICULUM261_RUNGS]
    ev = evaluate_pair_corpus_r4(
        records, FAMILY_C2, ladder, thresholds,
        preproc=None, corpus=corpus_ns)
    block_table = build_c2_block_evidence_table(
        ev["pair_table"], blocks, corpus_ns)

    rungs = CURRICULUM261_RUNGS
    baselines = ("always_long", "c2_local_only")
    gap_series = {
        f"{rungs[k]}-{rungs[k + 1]}": _gap_series(
            block_table, rungs[k], rungs[k + 1])
        for k in range(3)}

    per_n: dict[str, Any] = {}
    for n in FORMAL_BLOCK_OPTIONS:
        gap_checks: dict[str, Any] = {}
        gaps_ok = True
        for name, series in gap_series.items():
            sd = float(np.std(series, ddof=1))
            se = _se_at_n(sd, n)
            mean = float(np.mean(series))
            rate = float(np.mean(series > 0))
            ok = bool(mean > 0 and mean >= DESIGN_TARGET_GAP_FACTOR * se
                      and rate >= R6_POSITIVE_GAP_RATE_MIN)
            gaps_ok = gaps_ok and ok
            gap_checks[name] = {
                "mean": mean, "sd_blockwise": sd, "se_at_n": se,
                "ratio": float(mean / se) if se > 0 else None,
                "positive_gap_block_rate": rate, "ok": ok}
        d3_series = _difficulty(block_table, "D3")
        d3_mean = float(np.mean(d3_series))
        d3_se = _se_at_n(float(np.std(d3_series, ddof=1)), n)
        d3_ok = bool(d3_mean > 0
                     and d3_mean >= DESIGN_TARGET_D3_FACTOR * d3_se)
        margin_checks: dict[str, Any] = {}
        margins_ok = True
        for b in baselines:
            for r in rungs:
                series = _margin(block_table, r, b)
                mean = float(np.mean(series))
                if r in ("D2", "D3"):
                    ok = bool(mean > 0 and mean
                              >= DESIGN_TARGET_MARGIN_FACTOR
                              * _se_at_n(float(np.std(series, ddof=1)), n))
                else:
                    ok = bool(mean > 0)
                margins_ok = margins_ok and ok
                margin_checks[f"{b}_{r}"] = {
                    "mean": mean, "ok": ok,
                    "requires_factor_se": r in ("D2", "D3")}
        sim = simulate_formal_gate_pass_r6_matched(
            block_table, n_formal_blocks=n)
        diff_means = {r: float(np.mean(_difficulty(block_table, r)))
                      for r in rungs}
        reasons = {
            "ordering_ok": bool(diff_means["D0"] > diff_means["D1"]
                                > diff_means["D2"] > diff_means["D3"]),
            "gaps_ge_3x_se_and_positive_rate": gaps_ok,
            "d3_ge_2p5x_se": d3_ok,
            "margins_positive_and_d2_d3_ge_2p5x_se": margins_ok,
            "formal_gate_probability_ge_0p90": bool(
                sim["gate_pass_probability"] >= DESIGN_TARGET_GATE_PROB),
        }
        per_n[str(n)] = {
            "n_formal_blocks": n,
            "gap_checks": gap_checks,
            "d3_check": {"mean": d3_mean, "se_at_n": d3_se,
                         "ratio": float(d3_mean / d3_se),
                         "ok": d3_ok},
            "margin_checks": margin_checks,
            "formal_gate_simulation": sim,
            "reasons": reasons,
            "qualified": bool(all(reasons.values())),
        }

    # 密度(R6 冻结 gate)+ R15 candidate-specific cue 语义 + 独立性/
    # 可观察性(冻结公共实现;全部依赖模块级解析——R8 的
    # c2_density_summary 错误导入已修复为 r5_pairs 来源)
    density_summaries: dict[str, Any] = {}
    for r in rungs:
        d = c2_density_summary(
            [row for row in ev["episodes"] if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [blk.pair_records[r] for blk in blocks], ladder[r],
            thresholds)
        density_summaries[r] = density_gate_r5(d)
    cue_sem = candidate_cue_semantics(blocks, candidate_id, thresholds)
    semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            records),
        "context_observability": check_c2_context_observability(
            records),
        "candidate_cue_semantics_r15_cluster_aware": cue_sem,
        "cue_payoff_confusion": {
            k: v for k, v in cue_sem["per_rung"]["D0"]["sides"]["A"][
                "confusion"].items()},
        # R6 点阈值分离检查仅作诊断对照(绝不进入 R15 资格判定)
        "r6_point_separation_diagnostic_only": {
            k: v for k, v in check_c2_cue_payoff_separation(
                records).items() if k != "per_rung"},
    }
    density_ok = all(d["pass"] for d in density_summaries.values())
    semantics_ok = bool(
        semantics["local_cue_independence"]["pass"]
        and semantics["context_observability"]["pass"]
        and cue_sem["pass"])
    integrity_ok = bool(all(rec.integrity_ok for rec in records))
    scrambled = scrambled_gap_control(block_table)
    return {
        "candidate": candidate_id,
        "corpus": corpus_ns,
        "n_blocks": int(block_table["n_blocks"]),
        "block_corpus_summary": matched_block_corpus_summary(blocks),
        "block_attempt_stats": block_attempt_statistics(blocks),
        "block_table": block_table,
        "pair_table_rows": ev["pair_table"]["rows"],
        "difficulty_means": {r: float(np.mean(
            _difficulty(block_table, r))) for r in rungs},
        "per_formal_block_count": per_n,
        "density_gates": density_summaries,
        "semantics": semantics,
        "semantics_pass": semantics_ok,
        "density_pass": density_ok,
        "pair_integrity_unity": integrity_ok,
        "oracle_positive": bool(all(
            float(np.mean([row["oracle"] for row in ev["episodes"]
                           if row["rung"] == r])) > 0 for r in rungs)),
        "scrambled_control_diagnostic": scrambled,
    }


def _gap_series(block_table: dict[str, Any], hi: str, lo: str):
    # R15:block_gap_series 模块级解析(§6.2)。
    return block_gap_series(block_table, hi, lo)


def _difficulty(block_table: dict[str, Any], rung: str):
    return block_difficulty_series(block_table, rung)


def _margin(block_table: dict[str, Any], rung: str, baseline: str):
    return block_margin_series(block_table, rung, baseline)


def _qualified_at_n(corpus_results: list[dict[str, Any]], n: int) -> bool:
    return all(
        res["per_formal_block_count"][str(n)]["qualified"]
        and res["semantics_pass"] and res["density_pass"]
        and res["pair_integrity_unity"] and res["oracle_positive"]
        for res in corpus_results)


def _maximin_score_r15(corpus_results: list[dict[str, Any]],
                      n: int) -> float:
    """§16 maximin(不含 shared recall——由 dedicated semantic corpus
    独立承担)。"""
    vals: list[float] = []
    pos_rate_min = 1.0
    fc_ucb_worst = 0.0
    prec_lcb_worst = float("inf")
    trades_ratio_min = float("inf")
    for res in corpus_results:
        block_table = res["block_table"]
        rungs = CURRICULUM261_RUNGS
        for k in range(3):
            hi, lo = rungs[k], rungs[k + 1]
            series = _gap_series(block_table, hi, lo)
            se = _se_at_n(float(np.std(series, ddof=1)), n)
            mean = float(np.mean(series))
            if se > 0:
                vals.append(mean / se)
            pos_rate_min = min(pos_rate_min, float(np.mean(series > 0)))
        d3 = _difficulty(block_table, "D3")
        d3_se = _se_at_n(float(np.std(d3, ddof=1)), n)
        if d3_se > 0:
            vals.append(float(np.mean(d3)) / d3_se)
        for b in ("always_long", "c2_local_only"):
            m = _margin(block_table, "D3", b)
            mse = _se_at_n(float(np.std(m, ddof=1)), n)
            if mse > 0:
                vals.append(float(np.mean(m)) / mse)
        for d in res["density_gates"].values():
            trades_ratio_min = min(
                trades_ratio_min,
                d["median_reference_trades_per_episode"]
                / C2_DENSITY_MIN_MEDIAN_REFERENCE_TRADES_R6,
                d["reference_long_label_rate"]
                / C2_DENSITY_MIN_REFERENCE_LONG_RATE_R6)
        for per_rung in res["semantics"][
                "candidate_cue_semantics_r15_cluster_aware"][
                "per_rung"].values():
            for side in per_rung["sides"].values():
                fc_ucb_worst = max(
                    fc_ucb_worst,
                    side["payoff_false_cue"]["bound"])
                prec_lcb_worst = min(
                    prec_lcb_worst, side["cue_precision"]["bound"])
    vals.append(pos_rate_min / R6_POSITIVE_GAP_RATE_MIN)
    vals.append(trades_ratio_min)
    vals.append(max(0.0, 1.0 - fc_ucb_worst / C2_PAYOFF_BAR_FALSE_CUE_MAX))
    vals.append(max(0.0, prec_lcb_worst / C2_CUE_PRECISION_MIN))
    return float(min(vals))


# ------------------------------------------------- 主流程
def run_design_stage_r15(out_dir: Path, plan: dict[str, Any],
                        design_digest: str,
                        baseline_commit: str = "") -> dict[str, Any]:
    """R15 design 主流程:治理检查 → semantic corpora(160×2)+ gate
    (FAIL 即短路)→ 3 candidate × 2 corpus blocks → candidate 评估 →
    机械选择 → marginal guard → pack。

    §8.4:plan 锁定后本函数内部任何异常都转 write_r15_iteration_aborted
    + re-raise(R15 永久结束;不删 plan、不重锁、不复用 namespace)。
    """
    require_r15_iteration_active()
    out_dir = Path(out_dir)
    try:
        return _run_design_stage_inner_r15(
            out_dir, plan, design_digest, baseline_commit)
    except Exception as exc:  # noqa: BLE001 - §8.4 一次性硬规则
        write_r15_iteration_aborted(
            f"design plan 锁定后执行异常({type(exc).__name__}: "
            f"{str(exc)[:300]});按 §8.4 R15 永久结束")
        raise


def _run_design_stage_inner_r15(out_dir: Path, plan: dict[str, Any],
                               design_digest: str,
                               baseline_commit: str,
                               ) -> dict[str, Any]:
    identity = verify_design_code_identity(plan)
    if not identity["pass"]:
        raise RuntimeError(
            f"R15 design plan code identity 与当前代码不一致:"
            f"{sorted(identity['drift'])}(§8.4)")
    thresholds = dict(
        family_specs()[FAMILY_C2].reference_defaults)
    grid = plan["candidate_grid"]["candidates"]
    n_blocks = plan["design_data"]["blocks_per_candidate_per_corpus"]
    floor = float(plan["cue_semantic_contract"]["recall_floor"])
    cue_rule = cue_semantic_rule_identity()
    if cue_rule != plan["cue_semantic_contract"]["rule_identity"]:
        raise RuntimeError("cue semantic rule identity 与 plan 不一致")

    # 第一条 R15 design/semantic episode 生成前记录 started(§8.4)
    mark_design_data_started()

    # ---- §15 dedicated semantic corpora(160 × 2,sentinel)----
    semantic_cfg = plan["semantic_corpora"]
    sentinel = {rung: dict(params)
                for rung, params in C2_RUNG_PARAMS.items()}
    semantic_gates: dict[str, Any] = {}
    semantic_pass = True
    semantic_summaries: dict[str, Any] = {}
    for corpus_ns in semantic_cfg["namespaces"]:
        blocks = [generate_matched_block_with_attempts(
            sentinel, namespace=corpus_ns, block_index=i)
            for i in range(int(semantic_cfg["blocks_per_corpus"]))]
        gate = semantic_cue_gate(
            blocks, sentinel, thresholds,
            recall_floor_value=floor,
            min_unique_positive_cues=int(
                semantic_cfg["min_unique_positive_cues"]),
            label=f"sentinel@{corpus_ns}")
        gate["block_attempt_stats"] = block_attempt_statistics(blocks)
        gate["block_corpus_summary"] = matched_block_corpus_summary(
            blocks)
        semantic_gates[corpus_ns] = gate
        semantic_pass = semantic_pass and gate["pass"]
        semantic_summaries[corpus_ns] = {
            "n_blocks": gate["n_blocks"],
            "n_unique_positive_cues": gate["n_unique_positive_cues"],
            "recall_point": gate["recall"]["point"],
            "recall_lcb": gate["recall"]["bound"],
            "recall_floor": gate["recall_floor"],
            "noncue_fp_ucb": gate["noncue_false_positive"]["bound"],
            "checks": gate["checks"],
            "pass": gate["pass"],
        }
        # R15:显式穷尽映射 + exclusive create + reload 校验
        # (R8 的 endswith("main") 使 main artifact 被 validation 覆盖)
        trace_rows = gate.pop("event_trace", [])
        gate_out = dict(gate)
        gate_out["event_count"] = len(trace_rows)
        write_semantic_artifact_r15(
            out_dir, corpus_ns, gate_out, design_digest,
            event_rows=trace_rows)
        gate["event_trace"] = trace_rows
    # §R15-8:main/validation 两个 semantic artifact 必须同时存在且
    # sha256 不同(任一不满足 => 工程缺陷 => §18 一次性硬规则,
    # 禁止生成 candidate blocks)。
    semantic_paths = [out_dir / semantic_artifact_filename_r15(ns)
                      for ns in semantic_cfg["namespaces"]]
    if not all(p.is_file() for p in semantic_paths):
        raise RuntimeError(
            "semantic main/validation artifact 未同时落盘(§R15-8;"
            "禁止生成 candidate blocks)")
    semantic_hashes = [hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in semantic_paths]
    if len(set(semantic_hashes)) != len(semantic_hashes):
        raise RuntimeError(
            "semantic main/validation artifact 哈希相同(疑似互相覆盖;"
            "§R15-8 禁止生成 candidate blocks)")
    if not semantic_pass:
        summary = {
            "format": "cur261-r15-design-stage-v1",
            "iteration": "r15",
            "design_plan_digest": design_digest,
            "n_candidates": len(grid),
            "semantic_gate_pass": False,
            "semantic_corpora": semantic_summaries,
            "pass": False,
            "verdict": "R15 design FAIL:dedicated semantic corpus gate "
                       "未在全部 semantic corpus 通过(§15);不生成 "
                       "candidate blocks;不生成 parameter pack;不访问"
                       " marginal/calibration/final namespace;不写 "
                       "exposure marker;不运行 full-cold(§25)",
        }
        (out_dir / "r15_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- §16/§23 candidate corpora(3 candidate × 2 corpus × 40)----
    blocks_by: dict[str, dict[str, list[Any]]] = {}
    for corpus_ns in plan["design_data"]["corpora"]:
        blocks_by[corpus_ns] = {}
        for cand_id, ladder in grid.items():
            blocks_by[corpus_ns][cand_id] = [
                generate_matched_block_with_attempts(
                    ladder, namespace=corpus_ns, block_index=i)
                for i in range(n_blocks)]

    # ---- candidate × corpus 评估(复用已生成的 blocks)----
    candidate_results: dict[str, Any] = {}
    for cand_id, ladder in grid.items():
        corpora = [
            _evaluate_candidate_matched_r15(
                cand_id, ladder, ns, thresholds,
                blocks=blocks_by[ns][cand_id], n_blocks=n_blocks)
            for ns in plan["design_data"]["corpora"]]
        qualified_ns: dict[str, bool] = {}
        scores: dict[str, float] = {}
        for n in FORMAL_BLOCK_OPTIONS:
            qualified_ns[str(n)] = _qualified_at_n(corpora, n)
            if qualified_ns[str(n)]:
                scores[str(n)] = _maximin_score_r15(corpora, n)
        candidate_results[cand_id] = {
            "candidate_params": ladder,
            "corpora": corpora,
            "qualified_by_block_count": qualified_ns,
            "maximin_score_by_qualified_n": scores,
            "qualified_any": any(qualified_ns.values()),
            "param_distance_from_historical": (
                ladder_distance_from_historical_r15(ladder)),
        }
    (out_dir / "r15_candidate_results.json").write_text(json.dumps(
        candidate_results, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    # ---- §18 机械选择:最小 n → maximin → distance → id ----
    selected_n: int | None = None
    selected_id: str | None = None
    for n in FORMAL_BLOCK_OPTIONS:
        combos = [(cid, res) for cid, res in candidate_results.items()
                  if res["qualified_by_block_count"][str(n)]]
        if combos:
            ranked = sorted(
                combos,
                key=lambda kv: (-kv[1]["maximin_score_by_qualified_n"][
                                    str(n)],
                                kv[1]["param_distance_from_historical"],
                                kv[0]))
            selected_id, _selected = ranked[0]
            selected_n = n
            break

    power = _build_power_summary_r15(
        candidate_results, semantic_summaries, selected_id, selected_n,
        design_digest)
    (out_dir / "r15_power_analysis.json").write_text(json.dumps(
        power, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")

    if selected_id is None:
        summary = {
            "format": "cur261-r15-design-stage-v1",
            "iteration": "r15",
            "design_plan_digest": design_digest,
            "n_candidates": len(candidate_results),
            "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
            "semantic_gate_pass": True,
            "semantic_corpora": semantic_summaries,
            "qualified_combinations": 0,
            "weakest_binding_condition": power[
                "weakest_binding_condition"],
            "pass": False,
            "verdict": "R15 FAIL:candidate × block count 无合格组合"
                       "(§25);保留 block tables;不生成 parameter pack;"
                       "不访问 marginal/calibration/final namespace;"
                       "不写 exposure marker;不运行 full-cold",
        }
        (out_dir / "r15_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- §26 独立-rung marginal guard(选定后、pack 前)----
    ladder = candidate_results[selected_id]["candidate_params"]
    marginal_artifact = _run_independent_marginal_guard(
        out_dir, ladder, selected_id, thresholds)
    if not marginal_artifact["guard"]["pass"]:
        summary = {
            "format": "cur261-r15-design-stage-v1",
            "iteration": "r15",
            "design_plan_digest": design_digest,
            "selected_candidate": selected_id,
            "selected_block_count": selected_n,
            "marginal_guard_pass": False,
            "marginal_guard": marginal_artifact["guard"],
            "pass": False,
            "verdict": "R15 FAIL:选定 ladder 的独立-rung marginal guard "
                       "未通过(§26:matched PASS 不可覆盖);不生成 pack,"
                       "禁止进入 calibration",
        }
        (out_dir / "r15_sample_size_selection.json").write_text(
            json.dumps(summary, indent=2, ensure_ascii=False,
                       default=float), encoding="utf-8")
        return summary

    # ---- §27 parameter pack ----
    matched_integrity = candidate_results[selected_id]["corpora"][0][
        "block_corpus_summary"]
    integrity_ok_all = matched_integrity[
        "all_rung_pair_integrity_pass"]
    cross_ok_all = matched_integrity["all_cross_rung_matching_pass"]
    block_integrity_identity = (
        matched_integrity["block_contract"]
        + f"|n={matched_integrity['n_blocks']}"
        + f"|tapes={matched_integrity['distinct_shared_tape_count']}"
        + f"|integrity={integrity_ok_all}"
        + f"|cross={cross_ok_all}")
    pack = ladder_pack_payload_r15(
        selected_c2_candidate=selected_id,
        c2_ladder=ladder,
        selected_block_count=selected_n,
        design_plan_digest=design_digest,
        matched_contract_identity=matched_ladder_contract_identity(),
        block_integrity_identity=block_integrity_identity,
        cue_semantic_contract_digest=cue_semantic_contract_digest(),
        cue_semantic_rule_identity=cue_rule,
        cue_audit_digest=plan["cue_semantic_contract"]["audit_digest"],
        p_contract=plan["cue_semantic_contract"]["p_contract"],
        recall_floor_value=floor,
        noninferiority_delta=NONINFERIORITY_DELTA,
        semantic_blocks_per_corpus=SEMANTIC_BLOCKS_PER_CORPUS_R15,
        code_freeze_sha=str(plan.get("code_freeze_sha", "")),
        policy_visible_reference_contract_digest=str(
            plan.get("policy_visible_reference_contract_digest", "")),
        bundle_routing_contract_digest=str(
            plan.get("bundle_routing_contract_digest", "")),
        candidate_evidence={
            "maximin_score": candidate_results[selected_id][
                "maximin_score_by_qualified_n"][str(selected_n)],
            "param_distance": candidate_results[selected_id][
                "param_distance_from_historical"],
            "corpora": [c["corpus"] for c in
                        candidate_results[selected_id]["corpora"]],
            "gate_probability_at_n": [
                c["per_formal_block_count"][str(selected_n)][
                    "formal_gate_simulation"]["gate_pass_probability"]
                for c in candidate_results[selected_id]["corpora"]],
            "semantic_gate_recall_lcb": {
                ns: g["recall"]["bound"]
                for ns, g in semantic_gates.items()},
        },
        marginal_guard_evidence={
            "namespace": marginal_artifact["namespace"],
            "pairs_per_rung": marginal_artifact["pairs_per_rung"],
            "cue_semantics_pass": marginal_artifact["cue_semantics"][
                "pass"],
        },
        baseline_commit=baseline_commit,
    )
    write_selected_pack_r15(out_dir, pack)
    # write 为副本补 digest 落盘;重新 load 保证 selection 引用的
    # digest 与盘上 artifact 逐位一致(fail closed;模块级解析 §6.2)
    pack = load_selected_pack(out_dir)

    selection = {
        "format": "cur261-r15-sample-size-selection-v1",
        "iteration": "r15",
        "design_plan_digest": design_digest,
        "selected_candidate": selected_id,
        "selected_block_count": selected_n,
        "formal_block_options": list(FORMAL_BLOCK_OPTIONS),
        "selection_order": ["min formal block count", "maximin score",
                            "min param distance", "candidate id"],
        "maximin_score": candidate_results[selected_id][
            "maximin_score_by_qualified_n"][str(selected_n)],
        "param_distance_from_historical": candidate_results[
            selected_id]["param_distance_from_historical"],
        "qualified_combinations": int(sum(
            1 for res in candidate_results.values()
            for q in res["qualified_by_block_count"].values() if q)),
        "semantic_gate_pass": True,
        "semantic_corpora": {
            ns: {
                "recall_lcb": g["recall"]["bound"],
                "recall_floor": g["recall_floor"],
                "recall_point": g["recall"]["point"],
                "noncue_fp_ucb": g["noncue_false_positive"]["bound"],
                "n_unique_positive_cues": g[
                    "n_unique_positive_cues"],
            } for ns, g in semantic_gates.items()},
        "marginal_guard_pass": True,
        "parameter_pack_digest": pack["digest"],
        "pass": True,
    }
    (out_dir / "r15_sample_size_selection.json").write_text(json.dumps(
        selection, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return selection


def _run_independent_marginal_guard(
        out_dir: Path, ladder: dict[str, dict[str, Any]],
        selected_id: str, thresholds: dict) -> dict[str, Any]:
    """§26:design_r15_independent_marginal 语料的 marginal guard。

    R15 语义组装修正:R6 冻结的 c2_marginal_guard_conditions 检查的
    semantics 键为 cue_payoff_separation(R7 误传 cue_semantics——
    R7 calibration 未执行故未暴露);R15 以 semantics=None 调用 R6 统计
    条件,再显式 AND 本模块语义条件(local cue ∧ context ∧ v2
    independent cue semantics:point recall ≥0.90 灾难护栏)。
    """
    indep_records: list[Any] = []
    for rung in CURRICULUM261_RUNGS:
        for idx in range(DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R15):
            indep_records.append(generate_pair(
                FAMILY_C2, rung, idx,
                namespace=DESIGN_INDEPENDENT_NAMESPACE_R15,
                rung_params_override={rung: dict(ladder[rung])}))
    indep_report = rung_report_r4(
        indep_records, FAMILY_C2, ladder, thresholds,
        preproc=None, corpus=DESIGN_INDEPENDENT_NAMESPACE_R15)
    indep_density: dict[str, Any] = {}
    for r in CURRICULUM261_RUNGS:
        d = c2_density_summary(
            [row for row in indep_report["by_rung"][r]["episodes"]
             if row["rung"] == r], r)
        d["reference_long_label_rate"] = _reference_long_label_rate(
            [rec for rec in indep_records if rec.rung == r],
            ladder[r], thresholds)
        indep_density[r] = density_gate_r5(d)
    indep_cue = independent_cue_semantics(
        indep_records, selected_id, thresholds)
    indep_semantics = {
        "local_cue_independence": check_c2_local_cue_independence(
            indep_records),
        "context_observability": check_c2_context_observability(
            indep_records),
        "cue_semantics": indep_cue,
    }
    base = c2_marginal_guard_conditions(
        indep_report,
        density={"pass": all(d["pass"] for d in indep_density.values())},
        semantics=None)
    r15_semantics_ok = bool(
        indep_semantics["local_cue_independence"]["pass"]
        and indep_semantics["context_observability"]["pass"]
        and indep_cue["pass"])
    marginal = dict(base)
    marginal["format"] = "cur261-r15-c2-marginal-guard-v1"
    marginal["r15_semantics_rule"] = (
        "local cue ∧ context observability ∧ independent cue semantics"
        "(point recall ≥ 0.90 灾难护栏 + canonical + non-cue FP;§26)")
    marginal["r15_semantics_pass"] = r15_semantics_ok
    marginal["semantics_pass"] = r15_semantics_ok
    marginal["pass"] = bool(base["pass"] and r15_semantics_ok)
    artifact = {
        "format": "cur261-r15-independent-marginal-design-v1",
        "namespace": DESIGN_INDEPENDENT_NAMESPACE_R15,
        "pairs_per_rung": DESIGN_INDEPENDENT_PAIRS_PER_RUNG_R15,
        "candidate": selected_id,
        "guard": marginal,
        "density_gates": indep_density,
        "cue_semantics": indep_cue,
        "semantics": {k: {kk: vv for kk, vv in v.items()
                          if kk not in ("per_rung", "per_quadrant")}
                      for k, v in indep_semantics.items()},
    }
    (out_dir / "c2_independent_marginal_design.json").write_text(
        json.dumps(artifact, indent=2, ensure_ascii=False, default=float),
        encoding="utf-8")
    return artifact


def _build_power_summary_r15(candidate_results: dict[str, Any],
                            semantic_summaries: dict[str, Any],
                            selected_id: str | None,
                            selected_n: int | None,
                            design_digest: str) -> dict[str, Any]:
    """§25 自动 power/semantic summary(含最弱 binding condition)。"""
    weakest: dict[str, Any] = {}
    global_fail_counts: dict[str, int] = {}
    for cand_id, res in candidate_results.items():
        cand_weak: dict[str, Any] = {}
        for n_str, n_res in res["corpora"][0][
                "per_formal_block_count"].items():
            for name, ok in n_res["reasons"].items():
                if not ok:
                    cand_weak.setdefault(n_str, {})[name] = False
                    key = f"n={n_str}:{name}"
                    global_fail_counts[key] = (
                        global_fail_counts.get(key, 0) + 1)
        if not all(c["semantics_pass"] for c in res["corpora"]):
            cand_weak["semantics"] = False
            global_fail_counts["semantics"] = (
                global_fail_counts.get("semantics", 0) + 1)
        if not all(c["density_pass"] for c in res["corpora"]):
            cand_weak["density"] = False
            global_fail_counts["density"] = (
                global_fail_counts.get("density", 0) + 1)
        weakest[cand_id] = cand_weak
    ranked = sorted(global_fail_counts.items(), key=lambda kv: -kv[1])
    gate_margins = {
        ns: {
            "recall_lcb_minus_floor": g["recall_lcb"]
            - g["recall_floor"],
            "noncue_max_minus_ucb": C2_NON_CUE_FALSE_POSITIVE_MAX
            - g["noncue_fp_ucb"],
        } for ns, g in semantic_summaries.items()}
    return {
        "format": "cur261-r15-power-analysis-v1",
        "design_plan_digest": design_digest,
        "selected_candidate": selected_id,
        "selected_block_count": selected_n,
        "semantic_gate_margins": gate_margins,
        "per_candidate_weakest": weakest,
        "global_fail_counts": dict(ranked),
        "weakest_binding_condition": (
            ranked[0][0] if ranked else "none(all qualified)"
            if selected_id else ranked[0][0] if ranked else "none"),
    }
