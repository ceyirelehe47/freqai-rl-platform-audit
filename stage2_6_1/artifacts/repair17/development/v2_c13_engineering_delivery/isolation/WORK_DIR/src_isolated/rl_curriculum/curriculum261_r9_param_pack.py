# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R9:版本化 clean matched-ladder 参数包
(CurriculumR9MatchedLadderPack-v1)。

R7 诚实 FAIL(shared cue gate main LCB 0.912 < floor 0.930;plan
loader digest 自引用缺陷;mirror 边界错误)。R9 在全新 seed 空间
重做 clean design(§1/§2):

- candidate 网格缩到恰好 3 个(§17;R6/R7 已提供足够 development
  evidence,继续扩网格只增加选择偏差;三个候选覆盖 D3 alpha
  28/30/32):
  * A historical control(冻结 cur261-c2-v9 默认;非选择性 control);
  * B conservative(R6/R7 conservative;D3=28);
  * C midpoint(historical 与 conservative 的中间 ladder;D3=30)。
  禁止第四个 candidate(§17/§39)。
- C1-D3/C3-D3 继续继承 R4 选定候选(R4 pack digest 绑定);
- pack 绑定:cue semantic contract v2 / corrected audit digest /
  p_contract / recall floor / matched-ladder 合同身份 / R7 历史
  design plan digest(治理链)(§27)。

纯函数(_c2_ladder/validate_ladder_semantics/override 机制)直接
复用 curriculum261_r6_param_pack(R9 不复制不修改,实现零语义漂移
由构造保证;R6 模块 sha256 进入 R9 code identity,并与 R7 baseline
的记录值对拍)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from rl_curriculum.curriculum261_r6_param_pack import (
    R4_PARAMETER_PACK_DIGEST,
    R4_SELECTED_C1_D3,
    R4_SELECTED_C3_D3,
    R5_DESIGN_PLAN_DIGEST,
    _c2_ladder,
    _historical_c2_rung,
    apply_r6_override as _apply_override,
    ladder_distance_from_historical,
    r6_family_rung_params as _family_rung_params,
    r6_override_for as _override_for,
    validate_ladder_semantics,
)

R9_PACK_VERSION = "CurriculumR9MatchedLadderPack-v1"

#: R6 design plan digest(R6 诚实 FAIL 的治理证据链绑定)。
R6_DESIGN_PLAN_DIGEST = (
    "r6dp-db74ed109a7bf7a955c74f1bd248213002d3c08f79512abf0faf93f8941e03c7")

#: R7 design plan digest(R7 诚实 FAIL 的治理证据链绑定;R7 的
#: design plan payload 因 digest 自引用缺陷无法经正式 loader 复算,
#: 锁定值 r7dp-73d65b68... 由对称复算验证并完整保留)。
R7_DESIGN_PLAN_DIGEST = (
    "r7dp-73d65b6838c0686b26ad4c74c1fd7ca94d72aa8f20930d78a555bb8f8890e454")

#: R8 design plan digest(R8 于 plan 锁后 candidate evaluator
#: ImportError 按 §8.4 永久结束;治理证据链绑定)。
R8_DESIGN_PLAN_DIGEST = (
    "r8dp-60bb85d5481054b619188fb5a97209acd054e9e110da26710458ecaf"
    "2ef0db9d")

#: §17 预注册 R9 candidate 网格(恰好 3 个;生成任何 R9 design
#: episode 前锁定进 r9_design_plan)。
#: - c2l_historical_control:冻结默认(非选择性 control;D3=32);
#: - c2l_conservative:R6/R7 conservative(D3=28;R7 validation corpus
#:   shared cue LCB 0.9355 已过,R6 power table 双语料 n=15 gateP
#:   0.943/0.947);
#: - c2l_midpoint:historical 与 conservative 的中间 ladder(D3=30;
#:   距离历史最近)。
#: 全部满足 §17 边界:D3 alpha∈[28,32];只动 alpha/wick_kappa;
#: 严格单调;禁止增加第四个 candidate。
C2_LADDER_CANDIDATES_R9: dict[str, dict[str, dict[str, Any]]] = {
    "c2l_historical_control": _c2_ladder(),
    "c2l_conservative": _c2_ladder(
        D0={"alpha_bps": 74.0, "wick_kappa": 0.82},
        D1={"alpha_bps": 56.0, "wick_kappa": 0.60},
        D2={"alpha_bps": 40.0, "wick_kappa": 0.40},
        D3={"alpha_bps": 28.0, "wick_kappa": 0.26}),
    "c2l_midpoint": _c2_ladder(
        D0={"alpha_bps": 71.0, "wick_kappa": 0.81},
        D1={"alpha_bps": 55.0, "wick_kappa": 0.575},
        D2={"alpha_bps": 40.0, "wick_kappa": 0.39},
        D3={"alpha_bps": 30.0, "wick_kappa": 0.255}),
}


def r9_candidate_grid() -> dict[str, Any]:
    """预注册 R9 ladder 网格深拷贝(design plan 锁定用)。"""
    import copy

    return copy.deepcopy(C2_LADDER_CANDIDATES_R9)


def validate_r9_grid_semantics() -> list[str]:
    """§17 网格级校验(数量恰好 3;D3 alpha 边界;单调;键白名单)。"""
    issues: list[str] = []
    ids = list(C2_LADDER_CANDIDATES_R9)
    if len(ids) != 3:
        issues.append(f"candidate 数量必须恰好 3(§17 禁止第四个),"
                      f"收到 {len(ids)}")
    for cid, ladder in C2_LADDER_CANDIDATES_R9.items():
        issues.extend(validate_ladder_semantics(ladder))
        d3_alpha = float(ladder["D3"]["alpha_bps"])
        if cid != "c2l_historical_control" and not 28.0 <= d3_alpha <= 32.0:
            issues.append(
                f"{cid}:非历史 candidate 的 D3 alpha 必须位于 "
                f"[28,32],收到 {d3_alpha}")
    if "c2l_historical_control" not in ids or "c2l_conservative" not in ids:
        issues.append("必须包含 historical control 与 conservative")
    return issues


#: R9 允许覆盖的 family 白名单(与 R6/R7 一致)。
R9_OVERRIDE_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def ladder_pack_payload_r9(
        *, selected_c2_candidate: str,
        c2_ladder: dict[str, dict[str, Any]],
        selected_block_count: int,
        design_plan_digest: str,
        matched_contract_identity: str,
        block_integrity_identity: str,
        cue_semantic_contract_digest: str,
        cue_semantic_rule_identity: str,
        cue_audit_digest: str,
        p_contract: float,
        recall_floor_value: float,
        noninferiority_delta: float,
        semantic_blocks_per_corpus: int,
        candidate_evidence: dict[str, Any] | None = None,
        marginal_guard_evidence: dict[str, Any] | None = None,
        baseline_commit: str = "",
) -> dict[str, Any]:
    """构造 R9 clean matched-ladder pack payload(§27)。

    - C2:四档全量覆盖(选定 ladder;只动 alpha_bps/wick_kappa);
    - C1/C3 的 D3 恒为 R4 继承值(与 R4 pack digest 双重绑定);
    - selected_block_count ∈ {10,15,20}(design 机械选出,§18);
    - 绑定 cue semantic contract v2 / corrected audit digest /
      p_contract / recall floor / noninferiority delta /
      semantic block count 160(§27)。
    """
    if int(selected_block_count) not in (10, 15, 20):
        raise RuntimeError(
            f"selected_block_count 必须 ∈ {{10,15,20}},"
            f"收到 {selected_block_count!r}(§18)")
    if int(semantic_blocks_per_corpus) != 160:
        raise RuntimeError(
            f"semantic_blocks_per_corpus 必须恰好 160(§14 预注册),"
            f"收到 {semantic_blocks_per_corpus!r}")
    problems = validate_ladder_semantics(c2_ladder)
    if problems:
        raise RuntimeError(f"C2 ladder 语义非法: {problems}")
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    for rung in ("D0", "D1", "D2", "D3"):
        hist = dict(specs["c2_context"].rung_params[rung])
        if set(c2_ladder[rung]) != set(hist):
            raise RuntimeError(
                f"C2-{rung} 参数键集与历史不一致:"
                f"{sorted(c2_ladder[rung])} vs {sorted(hist)}")
    d3_overrides: dict[str, dict[str, Any]] = {
        "c1_opportunity": dict(R4_SELECTED_C1_D3),
        "c2_context": dict(c2_ladder["D3"]),
        "c3_cost": dict(R4_SELECTED_C3_D3),
    }
    return {
        "format": "cur261-r9-clean-matched-ladder-pack-v1",
        "pack_version": R9_PACK_VERSION,
        "iteration": "r9",
        "baseline_commit": baseline_commit,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest": R5_DESIGN_PLAN_DIGEST,
        "r6_design_plan_digest": R6_DESIGN_PLAN_DIGEST,
        "r7_design_plan_digest": R7_DESIGN_PLAN_DIGEST,
        "r8_design_plan_digest": R8_DESIGN_PLAN_DIGEST,
        "override_scope": {
            "families": list(R9_OVERRIDE_FAMILIES),
            "c2_rungs": ["D0", "D1", "D2", "D3"],
            "rules": "C1/C3 D3 = R4 选定候选(逐位继承);C2 四档全量"
                     "经 R9 design 选出(只动 alpha_bps/wick_kappa);"
                     "C1/C3 D0-D2 逐位等于历史(family_specs)值;"
                     "R0-R7 namespace 不受影响",
        },
        "selected_c2_candidate": selected_c2_candidate,
        "c2_ladder": {r: dict(c2_ladder[r])
                      for r in ("D0", "D1", "D2", "D3")},
        "d3_overrides": d3_overrides,
        "selected_block_count": int(selected_block_count),
        "semantic_blocks_per_corpus": int(semantic_blocks_per_corpus),
        "matched_ladder_contract_identity": matched_contract_identity,
        "block_integrity_identity": block_integrity_identity,
        "cue_semantic_contract_digest": cue_semantic_contract_digest,
        "cue_semantic_rule_identity": cue_semantic_rule_identity,
        "cue_contract_audit_digest": cue_audit_digest,
        "p_contract": float(p_contract),
        "noninferiority_delta": float(noninferiority_delta),
        "recall_floor": float(recall_floor_value),
        "design_plan_digest": design_plan_digest,
        "candidate_evidence": candidate_evidence or {},
        "marginal_guard_evidence": marginal_guard_evidence or {},
    }


def pack_digest_r9(pack: dict[str, Any]) -> str:
    """pack digest(canonical JSON;排除运行时间与 digest 自身字段)。"""
    payload = dict(pack)
    payload.pop("created_utc", None)
    payload.pop("digest", None)
    return "r9pk-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def write_selected_pack_r9(out_dir: Path, pack: dict[str, Any]) -> Path:
    from datetime import datetime, timezone

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = dict(pack)
    pack["digest"] = pack_digest_r9(pack)
    pack.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = out_dir / "r9_parameter_pack.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r9_parameter_pack_digest.txt").write_text(
        pack["digest"], encoding="utf-8")
    return path


def load_selected_pack(out_dir: Path) -> dict[str, Any]:
    """读取已锁定 pack 并复算 digest(fail closed;篡改即拒)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r9_parameter_pack.json"
    if not path.is_file():
        raise RuntimeError(
            f"R9 parameter pack 不存在: {path}(design + marginal guard "
            "通过并锁定后才允许 calibration/final)")
    pack = json.loads(path.read_text(encoding="utf-8"))
    stored = pack.get("digest")
    if not stored or pack_digest_r9(pack) != stored:
        raise RuntimeError("R9 parameter pack digest 复算不一致(fail closed)")
    digest_path = out_dir / "r9_parameter_pack_digest.txt"
    if digest_path.is_file() and \
            digest_path.read_text(encoding="utf-8").strip() != stored:
        raise RuntimeError("R9 parameter pack digest 文件与 payload 不一致")
    return pack


def r9_override_for(
        family: str,
        pack: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    return _override_for(family, pack)


def apply_r9_override(
        family: str, rung_params_by_rung: dict[str, dict[str, Any]],
        pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return _apply_override(family, rung_params_by_rung, pack)


def r9_family_rung_params(
        family: str, pack: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    return _family_rung_params(family, pack)


def frozen_parameter_identity_r9() -> dict[str, Any]:
    """R9 冻结参数面身份(C1/C3 D0-D2 + C2 结构键;final 复算比对)。"""
    from rl_curriculum.curriculum261_r6_param_pack import (
        frozen_parameter_identity_r6,
    )

    out = frozen_parameter_identity_r6()
    out["r9_note"] = "R9 不修改任何冻结参数面(与 R6/R7 逐位一致)"
    return out


def verify_r4_inheritance_r9(pack: dict[str, Any]) -> dict[str, Any]:
    """C1/C3 D3 继承 R4 的双重验证(数值与 R4 pack artifact 对拍)。"""
    from rl_curriculum.curriculum261_r6_param_pack import (
        verify_r4_inheritance,
    )

    return verify_r4_inheritance(pack)


def ladder_distance_from_historical_r9(
        ladder: dict[str, dict[str, Any]]) -> float:
    return ladder_distance_from_historical(ladder)


__all__ = [
    "R9_PACK_VERSION", "R4_PARAMETER_PACK_DIGEST",
    "R5_DESIGN_PLAN_DIGEST", "R6_DESIGN_PLAN_DIGEST",
    "R7_DESIGN_PLAN_DIGEST",
    "C2_LADDER_CANDIDATES_R9", "r9_candidate_grid",
    "validate_r9_grid_semantics", "R9_OVERRIDE_FAMILIES",
    "ladder_pack_payload_r9", "pack_digest_r9", "write_selected_pack_r9",
    "load_selected_pack", "r9_override_for", "apply_r9_override",
    "r9_family_rung_params", "frozen_parameter_identity_r9",
    "verify_r4_inheritance_r9", "ladder_distance_from_historical_r9",
    "_historical_c2_rung", "validate_ladder_semantics",
]
