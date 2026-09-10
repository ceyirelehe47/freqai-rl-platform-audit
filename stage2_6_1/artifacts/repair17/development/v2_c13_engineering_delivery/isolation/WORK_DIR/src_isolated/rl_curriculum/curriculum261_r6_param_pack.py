# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R6:版本化 matched-ladder 参数包
(CurriculumR6MatchedLadderPack-v1)。

R5 证明 D2/D3 局部修补不可行:上调 D2 压缩 D1-D2、下调 D3 有下限、
冻结 D0-D1 是瓶颈(独立 gap 0.0054-0.0061 vs κ×SE(n=10)
0.0063-0.0070)。R6 显式授权全局重分配 C2 D0-D3 的难度间距:

- 只允许修改现有难度轴 alpha_bps / wick_kappa(§7);
- payoff_bars / vol_bps / cue_rate / dir_len_range / width_len_range /
  pulse_bps / wick 几何全部 rung 固定(键集与历史逐位一致);
- C1-D3 / C3-D3 继承 R4 选定候选(R4 pack digest 双重绑定;R6 不
  重新搜索,只在新语料上重新资格验证);
- C1/C3 的 D0-D2 与全部 R0-R5 namespace 逐位冻结。

统计修复(§9-§15):C2 ladder 的统计单位从 independent rung pair
升级为 matched-ladder block(同 block 四 rung 共享结构随机带,
blockwise gap 只含参数效应);block 证据表是 ladder ordering/gap
SE/formal simulation 的唯一来源。

版本化纪律:
- candidate grid(8 个完整 ladder,含 1 个历史非选择性 control)在
  生成任何 R6 design episode 前预注册锁定(本模块常量 ->
  r6_design_plan);
- 选定 pack 独立 artifact(r6_parameter_pack.json + digest)固化,
  calibration/qualification 只从 artifact 读取(fail closed)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

R6_PACK_VERSION = "CurriculumR6MatchedLadderPack-v1"

#: R4 parameter pack digest(R6 继承 C1/C3 D3 候选的来源绑定)。
R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")

#: R5 design plan digest(R5 诚实 FAIL 的治理证据链绑定)。
R5_DESIGN_PLAN_DIGEST = (
    "r5dp-0c1eb69f95336f7d649192bc4293eaf768b37508f47c8c21c919009eb3afe52d")

#: R4 选定 C1-D3 参数(任务书 §6;必须与 R4 pack artifact 逐位一致)。
R4_SELECTED_C1_D3: dict[str, Any] = {
    "opp_drift_bps": 24.5, "neg_drift_bps": 16.0, "vol_bps": 26.0,
    "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
    "distractor_rate": 0.000,
}

#: R4 选定 C3-D3 参数(任务书 §6;必须与 R4 pack artifact 逐位一致)。
R4_SELECTED_C3_D3: dict[str, Any] = {
    "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
    "cue_rate": 0.230, "mixture": [0.20, 0.36, 0.44],
    "distractor_rate": 0.060,
}


def _historical_c2_rung(rung: str) -> dict[str, Any]:
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS

    return dict(C2_RUNG_PARAMS[rung])


def _c2_ladder(**rung_changes: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """完整四档 ladder:历史各 rung 键集 + 指定覆盖(键集保持一致)。

    只允许覆盖 alpha_bps / wick_kappa(§7 难度轴白名单);其它键
    逐位等于历史(结构参数冻结)。
    """
    ladder: dict[str, dict[str, Any]] = {}
    for rung in ("D0", "D1", "D2", "D3"):
        params = _historical_c2_rung(rung)
        changes = rung_changes.get(rung, {})
        for k in changes:
            if k not in ("alpha_bps", "wick_kappa"):
                raise RuntimeError(
                    f"C2 ladder 候选只允许修改难度键 alpha_bps/"
                    f"wick_kappa,收到 {k!r}(§7)")
        params.update(changes)
        ladder[rung] = params
    return ladder


#: §17 预注册完整 ladder candidate 网格(生成任何 R6 design episode
#: 前锁定进 r6_design_plan)。设计边界:alpha D0≈74-82 / D1≈48-58 /
#: D2≈34-42 / D3≈22-29;kappa D0≈0.82-0.95 / D1≈0.50-0.65 /
#: D2≈0.32-0.42 / D3≈0.20-0.28(边界不是最终固定值;语义/分离 gate
#: 机械裁决)。c2l_historical 是 R5 ladder 的非选择性 control
#: (不达标不得被选中,§17)。
C2_LADDER_CANDIDATES: dict[str, dict[str, dict[str, Any]]] = {
    "c2l_balanced": _c2_ladder(
        D0={"alpha_bps": 78.0, "wick_kappa": 0.88},
        D1={"alpha_bps": 50.0, "wick_kappa": 0.58},
        D2={"alpha_bps": 35.0, "wick_kappa": 0.34},
        D3={"alpha_bps": 23.0, "wick_kappa": 0.22}),
    "c2l_alpha_wide": _c2_ladder(
        D0={"alpha_bps": 80.0, "wick_kappa": 0.85},
        D1={"alpha_bps": 52.0, "wick_kappa": 0.60},
        D2={"alpha_bps": 36.0, "wick_kappa": 0.38},
        D3={"alpha_bps": 24.0, "wick_kappa": 0.24}),
    "c2l_kappa_wide": _c2_ladder(
        D0={"alpha_bps": 76.0, "wick_kappa": 0.92},
        D1={"alpha_bps": 54.0, "wick_kappa": 0.62},
        D2={"alpha_bps": 40.0, "wick_kappa": 0.36},
        D3={"alpha_bps": 27.0, "wick_kappa": 0.21}),
    "c2l_conservative": _c2_ladder(
        D0={"alpha_bps": 74.0, "wick_kappa": 0.82},
        D1={"alpha_bps": 56.0, "wick_kappa": 0.60},
        D2={"alpha_bps": 40.0, "wick_kappa": 0.40},
        D3={"alpha_bps": 28.0, "wick_kappa": 0.26}),
    "c2l_alpha_edge": _c2_ladder(
        D0={"alpha_bps": 82.0, "wick_kappa": 0.85},
        D1={"alpha_bps": 48.0, "wick_kappa": 0.55},
        D2={"alpha_bps": 34.0, "wick_kappa": 0.36},
        D3={"alpha_bps": 22.0, "wick_kappa": 0.24}),
    "c2l_mid_flat": _c2_ladder(
        D0={"alpha_bps": 78.0, "wick_kappa": 0.86},
        D1={"alpha_bps": 48.0, "wick_kappa": 0.55},
        D2={"alpha_bps": 38.0, "wick_kappa": 0.38},
        D3={"alpha_bps": 26.0, "wick_kappa": 0.23}),
    "c2l_d0_high": _c2_ladder(
        D0={"alpha_bps": 80.0, "wick_kappa": 0.90},
        D1={"alpha_bps": 54.0, "wick_kappa": 0.62},
        D2={"alpha_bps": 38.0, "wick_kappa": 0.40},
        D3={"alpha_bps": 23.0, "wick_kappa": 0.22}),
    "c2l_historical_control": _c2_ladder(),
}


def r6_candidate_grid() -> dict[str, Any]:
    """预注册 ladder 网格深拷贝(design plan 锁定用)。"""
    import copy

    return copy.deepcopy(C2_LADDER_CANDIDATES)


def validate_ladder_semantics(ladder: dict[str, dict[str, Any]],
                              ) -> list[str]:
    """§8 ladder 语义校验(返回问题清单,空即合法)。

    - alpha_D0 > alpha_D1 > alpha_D2 > alpha_D3 > 0
    - kappa_D0 > kappa_D1 > kappa_D2 > kappa_D3 > 0
    - 键集与历史逐位一致(结构参数冻结)
    """
    issues: list[str] = []
    alphas = [float(ladder[r]["alpha_bps"]) for r in ("D0", "D1", "D2", "D3")]
    kappas = [float(ladder[r]["wick_kappa"])
              for r in ("D0", "D1", "D2", "D3")]
    if not all(a > 0 for a in alphas):
        issues.append(f"alpha 非正:{alphas}")
    if not all(k > 0 for k in kappas):
        issues.append(f"kappa 非正:{kappas}")
    if not (alphas[0] > alphas[1] > alphas[2] > alphas[3]):
        issues.append(f"alpha 非严格递减:{alphas}")
    if not (kappas[0] > kappas[1] > kappas[2] > kappas[3]):
        issues.append(f"kappa 非严格递减:{kappas}")
    for r in ("D0", "D1", "D2", "D3"):
        if set(ladder[r]) != set(_historical_c2_rung(r)):
            issues.append(f"{r} 键集与历史不一致")
    return issues


#: R6 允许覆盖的 (family, rung) 白名单。
R6_OVERRIDE_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def ladder_pack_payload(
        *, selected_c2_candidate: str,
        c2_ladder: dict[str, dict[str, Any]],
        selected_block_count: int,
        design_plan_digest: str,
        matched_contract_identity: str,
        block_integrity_identity: str,
        candidate_evidence: dict[str, Any] | None = None,
        baseline_commit: str = "",
) -> dict[str, Any]:
    """构造 R6 matched-ladder pack payload。

    - C2:四档全量覆盖(选定 ladder);
    - C1/C3 的 D3 恒为 R4 继承值(与 R4 pack digest 双重绑定);
    - selected_block_count ∈ {10,15,20}(design 机械选出,§19)。
    """
    if int(selected_block_count) not in (10, 15, 20):
        raise RuntimeError(
            f"selected_block_count 必须 ∈ {{10,15,20}},"
            f"收到 {selected_block_count!r}(§19)")
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
        "format": "cur261-r6-matched-ladder-pack-v1",
        "pack_version": R6_PACK_VERSION,
        "iteration": "r6",
        "baseline_commit": baseline_commit,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "r5_design_plan_digest": R5_DESIGN_PLAN_DIGEST,
        "override_scope": {
            "families": list(R6_OVERRIDE_FAMILIES),
            "c2_rungs": ["D0", "D1", "D2", "D3"],
            "rules": "C1/C3 D3 = R4 选定候选(逐位继承);C2 四档全量"
                     "经 R6 design 选出(只动 alpha_bps/wick_kappa);"
                     "C1/C3 D0-D2 逐位等于历史(family_specs)值;"
                     "R0-R5 namespace 不受影响",
        },
        "selected_c2_candidate": selected_c2_candidate,
        "c2_ladder": {r: dict(c2_ladder[r])
                      for r in ("D0", "D1", "D2", "D3")},
        "d3_overrides": d3_overrides,
        "selected_block_count": int(selected_block_count),
        "matched_ladder_contract_identity": matched_contract_identity,
        "block_integrity_identity": block_integrity_identity,
        "design_plan_digest": design_plan_digest,
        "candidate_evidence": candidate_evidence or {},
    }


def pack_digest(pack: dict[str, Any]) -> str:
    """pack digest(canonical JSON;排除运行时间与 digest 自身字段)。"""
    payload = dict(pack)
    payload.pop("created_utc", None)
    payload.pop("digest", None)
    return "r6pk-" + hashlib.sha256(
        _canonical(payload).encode("utf-8")).hexdigest()


def write_selected_pack(out_dir: Path, pack: dict[str, Any]) -> Path:
    from datetime import datetime, timezone

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pack = dict(pack)
    pack["digest"] = pack_digest(pack)
    pack.setdefault(
        "created_utc",
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    path = out_dir / "r6_parameter_pack.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r6_parameter_pack_digest.txt").write_text(
        pack["digest"], encoding="utf-8")
    return path


def load_selected_pack(out_dir: Path) -> dict[str, Any]:
    """读取已锁定 pack 并复算 digest(fail closed;篡改即拒)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r6_parameter_pack.json"
    if not path.is_file():
        raise RuntimeError(
            f"R6 parameter pack 不存在: {path}(design 阶段合格并锁定后"
            "才允许 calibration/final)")
    pack = json.loads(path.read_text(encoding="utf-8"))
    stored = pack.get("digest")
    if not stored or pack_digest(pack) != stored:
        raise RuntimeError("R6 parameter pack digest 复算不一致(fail closed)")
    digest_path = out_dir / "r6_parameter_pack_digest.txt"
    if digest_path.is_file() and \
            digest_path.read_text(encoding="utf-8").strip() != stored:
        raise RuntimeError("R6 parameter pack digest 文件与 payload 不一致")
    return pack


def r6_override_for(
        family: str,
        pack: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """pack -> generate_pair 的 rung_params_override(rung 键控)。

    C1/C3:{"D3": 继承参数};C2:四档全量。
    """
    if family not in R6_OVERRIDE_FAMILIES:
        raise RuntimeError(f"R6 pack 不覆盖 {family}")
    override: dict[str, dict[str, Any]] = {}
    d3 = pack.get("d3_overrides", {}).get(family)
    if d3 is not None:
        override["D3"] = dict(d3)
    if family == "c2_context":
        ladder = pack.get("c2_ladder")
        if ladder:
            for rung in ("D0", "D1", "D2", "D3"):
                override[rung] = dict(ladder[rung])
    return override or None


def apply_r6_override(
        family: str, rung_params_by_rung: dict[str, dict[str, Any]],
        pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {r: dict(v) for r, v in rung_params_by_rung.items()}
    override = r6_override_for(family, pack) or {}
    for rung, params in override.items():
        out[rung] = dict(params)
    return out


def r6_family_rung_params(
        family: str, pack: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """某 family 在 R6 pack 下的完整逐 rung 参数(历史 + 覆盖)。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    spec = family_specs()[family]
    base = {r: dict(spec.rung_params[r]) for r in CURRICULUM261_RUNGS}
    return apply_r6_override(family, base, pack)


def frozen_parameter_identity_r6() -> dict[str, Any]:
    """R6 冻结参数面身份哈希(进入 plan;final 复算比对)。

    R6 只冻结 C1/C3 的 D0-D2(C2 四档与 C1/C3 D3 均由 pack 承载)。
    """
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    frozen: dict[str, Any] = {}
    for family in ("c1_opportunity", "c3_cost"):
        frozen[family] = {
            r: dict(specs[family].rung_params[r])
            for r in CURRICULUM261_RUNGS if r in ("D0", "D1", "D2")}
    scope = "C1/C3 D0-D2(逐位等于历史;C2 四档与 C1/C3 D3 由 pack 承载)"
    payload = {"frozen_scope": scope, "iteration": "r6",
               "frozen_params": frozen}
    return {
        "frozen_scope": scope,
        "frozen": frozen,
        "identity": "r6fp-" + hashlib.sha256(
            _canonical(payload).encode("utf-8")).hexdigest(),
    }


def verify_r4_inheritance(pack: dict[str, Any]) -> dict[str, Any]:
    """验证 pack 的 C1/C3 D3 继承值与 R4 常量/任务书/R4 artifact 一致。"""
    from rl_curriculum.curriculum261_r4_param_pack import (
        pack_digest as r4_pack_digest,
    )
    from rl_curriculum.curriculum261_r4_namespaces import (
        r4_parameter_pack_path,
    )

    c1 = pack.get("d3_overrides", {}).get("c1_opportunity")
    c3 = pack.get("d3_overrides", {}).get("c3_cost")
    checks = {
        "c1_matches_r4_constants": bool(c1 is not None
                                        and c1 == R4_SELECTED_C1_D3),
        "c3_matches_r4_constants": bool(c3 is not None
                                        and c3 == R4_SELECTED_C3_D3),
        "r4_pack_digest_bound": bool(
            pack.get("r4_parameter_pack_digest")
            == R4_PARAMETER_PACK_DIGEST),
        "r5_design_plan_digest_bound": bool(
            pack.get("r5_design_plan_digest") == R5_DESIGN_PLAN_DIGEST),
    }
    artifact_check: dict[str, Any] = {"present": False}
    try:
        r4_path = r4_parameter_pack_path()
        if r4_path.is_file():
            r4_pack = json.loads(r4_path.read_text(encoding="utf-8"))
            artifact_check = {
                "present": True,
                "digest_recompute_matches_bound": bool(
                    r4_pack_digest(r4_pack) == R4_PARAMETER_PACK_DIGEST),
                "c1_bitwise_equal": bool(
                    r4_pack["d3_overrides"]["c1_opportunity"] == c1),
                "c3_bitwise_equal": bool(
                    r4_pack["d3_overrides"]["c3_cost"] == c3),
            }
    except (OSError, json.JSONDecodeError, KeyError, RuntimeError):
        artifact_check = {"present": True, "error": "R4 pack 读取/解析失败"}
    checks["r4_pack_artifact"] = artifact_check
    artifact_ok = (not artifact_check.get("present")
                   or ("error" not in artifact_check
                       and artifact_check["digest_recompute_matches_bound"]
                       and artifact_check["c1_bitwise_equal"]
                       and artifact_check["c3_bitwise_equal"]))
    return {
        "format": "cur261-r6-r4-inheritance-verification-v1",
        "checks": checks,
        "pass": bool(checks["c1_matches_r4_constants"]
                     and checks["c3_matches_r4_constants"]
                     and checks["r4_pack_digest_bound"]
                     and checks["r5_design_plan_digest_bound"]
                     and artifact_ok),
    }


def ladder_distance_from_historical(
        ladder: dict[str, dict[str, Any]],
) -> float:
    """tie-breaker:ladder 相对历史值的归一化偏离(四档 Σ,越小越保守)。"""
    total = 0.0
    for rung in ("D0", "D1", "D2", "D3"):
        hist = _historical_c2_rung(rung)
        for k in ("alpha_bps", "wick_kappa"):
            base = abs(float(hist[k])) or 1.0
            total += abs(float(ladder[rung][k]) - float(hist[k])) / base
    return float(total)
