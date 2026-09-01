# -*- coding: utf-8 -*-
"""阶段 2.6.1 Repair R5:版本化 ladder 参数包(CurriculumR5LadderPack-v1)。

R4 final FAIL 的根因:C2-D2/D3 的设计间距相对 10-pair 抽样不确定性
不足(final 语料 D2 0.006998 < D3 0.008450 排序翻转)。R5 显式授权:

- C1-D3 / C3-D3:继承 R4 选定候选(参数逐位等于 R4 parameter pack,
  本模块常量 + R4 pack digest 双重绑定;R5 不重新搜索,只在新语料上
  重新资格验证);
- C2-D3:R5 重新设计(Tier A,仅 D3);
- 若 Tier A 全部 candidate 无法建立足够功效,机械升级到
  C2-D2 + C2-D3 联合调整(Tier B);
- C2-D0/D1 与 C1/C3 的 D0-D2 逐位冻结(禁止修改)。

版本化纪律:
- R0-R4 namespace 继续使用历史参数(本模块不修改任何
  C1/C2/C3_RUNG_PARAMS 值);
- R5 corpus 生成经 generate_pair(rung_params_override=...) 注入
  (C1/C3 的 D3 + C2 的 D3[, Tier B 时含 D2]);
- candidate grid(Tier A + Tier B)在生成任何 design episode 前预注册
  锁定(本模块常量 -> r5_design_plan);
- 选定 pack 以独立 artifact(r5_parameter_pack.json + digest)固化,
  calibration/qualification 只从 artifact 读取(fail closed)。

C2 活旋钮分析(cur261-c2-v9):
- alpha_bps(注入幅值):reference 每笔对齐交易净 edge ≈ alpha − 摩擦
  (2×10bps);下调直接压低 D3 难度均值,是拉开 D2-D3 gap 的主杠杆;
- vol_bps(配对噪声):reference 持仓 ~6-7 根 payoff bar,难度 pair
  方差 ≈ vol×sqrt(n_held);下调是压缩 D3 抽样方差的主杠杆;
- wick_kappa(上下文判定 SNR):保持 ladder 单调(D3 <= 0.38)前提下的
  次级杠杆(上调减少误判方差);
- cue_rate(机会密度):不动(下调同时压低均值与样本比,恶化
  mean/sd 比并触碰密度门槛);
- payoff_bars/dir_len_range/width_len_range/pulse_bps/wick 几何:
  结构冻结(v9 语义按 H=1 设计)。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

R5_PACK_VERSION = "CurriculumR5LadderPack-v1"

#: R4 parameter pack digest(R5 继承 C1/C3 D3 候选的来源绑定)。
R4_PARAMETER_PACK_DIGEST = (
    "r4pk-eca9ed55e0a51d1f2732dd61c14c19829b677c6b45e9d722ac5aac8e6d764f99")

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


def _c2_d3_variant(**changes: Any) -> dict[str, Any]:
    """历史 C2-D3 完整参数字典 + 指定键覆盖(键集保持一致)。"""
    params = _historical_c2_rung("D3")
    for k in changes:
        if k not in params:
            raise RuntimeError(f"C2-D3 不存在参数键 {k!r}")
    params.update(changes)
    return params


def _c2_d2_variant(**changes: Any) -> dict[str, Any]:
    params = _historical_c2_rung("D2")
    for k in changes:
        if k not in params:
            raise RuntimeError(f"C2-D2 不存在参数键 {k!r}")
    params.update(changes)
    return params


#: Tier A —— C2-D3-only 候选网格(预注册;生成任何 design episode 前
#: 锁定进 r5_design_plan)。全部候选键集与历史 D3 完全一致;只动
#: alpha_bps / vol_bps / wick_kappa(wick_kappa <= 0.38 保持 ladder 单调;
#: alpha < 40.0(D2)保持 D3 明显难于 D2)。
C2_TIER_A_CANDIDATES: dict[str, dict[str, Any]] = {
    "c2_a_alpha26_vol16": _c2_d3_variant(
        alpha_bps=26.0, vol_bps=16.0, wick_kappa=0.25),
    "c2_b_alpha27_vol18": _c2_d3_variant(
        alpha_bps=27.0, vol_bps=18.0, wick_kappa=0.25),
    "c2_c_alpha24_vol16": _c2_d3_variant(
        alpha_bps=24.0, vol_bps=16.0, wick_kappa=0.25),
    "c2_d_alpha26_vol13": _c2_d3_variant(
        alpha_bps=26.0, vol_bps=13.0, wick_kappa=0.25),
    "c2_e_alpha27_kappa30_vol16": _c2_d3_variant(
        alpha_bps=27.0, vol_bps=16.0, wick_kappa=0.30),
    "c2_f_alpha25_vol20": _c2_d3_variant(
        alpha_bps=25.0, vol_bps=20.0, wick_kappa=0.25),
}

#: Tier B —— C2-D2+D3 联合候选网格(预注册;仅当 Tier A 全部 candidate
#: 不满足全部 design 硬门槛时才允许访问 design_r5_tier_b_* namespace)。
#: D2 上调幅度受 D1 约束(alpha < 54.0、kappa < 0.55),保护 D1-D2 gap。
C2_TIER_B_CANDIDATES: dict[str, dict[str, dict[str, Any]]] = {
    "c2b_1_d2up42_d3down25": {
        "D2": _c2_d2_variant(alpha_bps=42.0),
        "D3": _c2_d3_variant(alpha_bps=25.0, vol_bps=15.0, wick_kappa=0.25),
    },
    "c2b_2_d2up44_d3down24": {
        "D2": _c2_d2_variant(alpha_bps=44.0),
        "D3": _c2_d3_variant(alpha_bps=24.0, vol_bps=14.0, wick_kappa=0.25),
    },
    "c2b_3_d2up42k40_d3down26": {
        "D2": _c2_d2_variant(alpha_bps=42.0, wick_kappa=0.40),
        "D3": _c2_d3_variant(alpha_bps=26.0, vol_bps=16.0, wick_kappa=0.25),
    },
}


def r5_candidate_grid() -> dict[str, Any]:
    """预注册 candidate 网格的深拷贝(design plan 锁定用)。"""
    import copy

    return {
        "tier_a_c2_d3_only": copy.deepcopy(C2_TIER_A_CANDIDATES),
        "tier_b_c2_joint": copy.deepcopy(C2_TIER_B_CANDIDATES),
    }


#: R5 允许覆盖的 (family, rung) 白名单。
R5_OVERRIDE_FAMILIES = ("c1_opportunity", "c2_context", "c3_cost")
R5_C2_D3_RUNG = "D3"
R5_C2_D2_RUNG = "D2"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def ladder_pack_payload(
        *, tier: str, selected_c2_candidate: str,
        c2_d3_params: dict[str, Any],
        c2_d2_params: dict[str, Any] | None = None,
        design_plan_digest: str,
        candidate_evidence: dict[str, Any] | None = None,
        baseline_commit: str = "",
) -> dict[str, Any]:
    """构造 R5 ladder pack payload。

    - tier == "A":仅 C2-D3 覆盖(C2-D2 冻结);
    - tier == "B":C2-D2 + C2-D3 联合覆盖(必须提供 D2 参数);
    - C1/C3 的 D3 恒为 R4 继承值(与 R4 pack digest 双重绑定)。
    """
    if tier not in ("A", "B"):
        raise RuntimeError(f"非法 tier {tier!r}(必须 A/B)")
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    hist_c2_d3 = dict(specs["c2_context"].rung_params["D3"])
    if set(c2_d3_params) != set(hist_c2_d3):
        raise RuntimeError(
            f"C2-D3 覆盖参数键集与历史不一致:{sorted(c2_d3_params)} vs "
            f"{sorted(hist_c2_d3)}")
    d3_overrides: dict[str, dict[str, Any]] = {
        "c1_opportunity": dict(R4_SELECTED_C1_D3),
        "c2_context": dict(c2_d3_params),
        "c3_cost": dict(R4_SELECTED_C3_D3),
    }
    for family in ("c1_opportunity", "c3_cost"):
        historical = dict(specs[family].rung_params["D3"])
        if set(d3_overrides[family]) != set(historical):
            raise RuntimeError(
                f"{family} D3 继承参数键集与历史不一致")
    c2_d2_override: dict[str, Any] | None = None
    if tier == "B":
        if c2_d2_params is None:
            raise RuntimeError("Tier B pack 必须提供 C2-D2 参数")
        hist_c2_d2 = dict(specs["c2_context"].rung_params["D2"])
        if set(c2_d2_params) != set(hist_c2_d2):
            raise RuntimeError(
                f"C2-D2 覆盖参数键集与历史不一致:{sorted(c2_d2_params)} "
                f"vs {sorted(hist_c2_d2)}")
        c2_d2_override = dict(c2_d2_params)
    return {
        "format": "cur261-r5-ladder-pack-v1",
        "pack_version": R5_PACK_VERSION,
        "iteration": "r5",
        "baseline_commit": baseline_commit,
        "r4_parameter_pack_digest": R4_PARAMETER_PACK_DIGEST,
        "tier": tier,
        "override_scope": {
            "families": list(R5_OVERRIDE_FAMILIES),
            "c2_rungs": ["D3"] if tier == "A" else ["D2", "D3"],
            "rules": "C1/C3 D3 = R4 选定候选(逐位继承);C2-D3 经 R5 "
                     "design 选出;Tier B 时 C2-D2 联合调整;C2-D0/D1 与"
                     " C1/C3 D0-D2 逐位等于历史(family_specs)值;R0-R4 "
                     "namespace 不受影响",
        },
        "selected_c2_candidate": selected_c2_candidate,
        "d3_overrides": d3_overrides,
        "c2_d2_override": c2_d2_override,
        "design_plan_digest": design_plan_digest,
        "candidate_evidence": candidate_evidence or {},
    }


def pack_digest(pack: dict[str, Any]) -> str:
    """pack digest(canonical JSON;排除运行时间与 digest 自身字段)。"""
    payload = dict(pack)
    payload.pop("created_utc", None)
    payload.pop("digest", None)
    return "r5pk-" + hashlib.sha256(
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
    path = out_dir / "r5_parameter_pack.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r5_parameter_pack_digest.txt").write_text(
        pack["digest"], encoding="utf-8")
    return path


def load_selected_pack(out_dir: Path) -> dict[str, Any]:
    """读取已锁定 pack 并复算 digest(fail closed;篡改即拒)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r5_parameter_pack.json"
    if not path.is_file():
        raise RuntimeError(
            f"R5 parameter pack 不存在: {path}(design 阶段合格并锁定后"
            "才允许 calibration/final)")
    pack = json.loads(path.read_text(encoding="utf-8"))
    stored = pack.get("digest")
    if not stored or pack_digest(pack) != stored:
        raise RuntimeError("R5 parameter pack digest 复算不一致(fail closed)")
    digest_path = out_dir / "r5_parameter_pack_digest.txt"
    if digest_path.is_file() and \
            digest_path.read_text(encoding="utf-8").strip() != stored:
        raise RuntimeError("R5 parameter pack digest 文件与 payload 不一致")
    return pack


def r5_override_for(
        family: str,
        pack: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """pack -> generate_pair 的 rung_params_override(rung 键控)。

    C1/C3:{"D3": 继承参数};C2 Tier A:{"D3": 选定参数};
    C2 Tier B:{"D2": ..., "D3": ...}。
    """
    if family not in R5_OVERRIDE_FAMILIES:
        raise RuntimeError(f"R5 pack 不覆盖 {family}")
    override: dict[str, dict[str, Any]] = {}
    d3 = pack.get("d3_overrides", {}).get(family)
    if d3 is not None:
        override["D3"] = dict(d3)
    if family == "c2_context":
        d2 = pack.get("c2_d2_override")
        if d2 is not None:
            override["D2"] = dict(d2)
    return override or None


def apply_r5_override(
        family: str, rung_params_by_rung: dict[str, dict[str, Any]],
        pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out = {r: dict(v) for r, v in rung_params_by_rung.items()}
    override = r5_override_for(family, pack) or {}
    for rung, params in override.items():
        out[rung] = dict(params)
    return out


def r5_family_rung_params(
        family: str, pack: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """某 family 在 R5 pack 下的完整逐 rung 参数(历史 + 覆盖)。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    spec = family_specs()[family]
    base = {r: dict(spec.rung_params[r]) for r in CURRICULUM261_RUNGS}
    return apply_r5_override(family, base, pack)


def frozen_parameter_identity_r5(tier: str) -> dict[str, Any]:
    """R5 冻结参数面身份哈希(进入 plan;final 复算比对)。

    Tier A:C1/C3 的 D0-D2 + C2 的 D0/D1/D2(C2-D3 由 pack 覆盖);
    Tier B:C1/C3 的 D0-D2 + C2 的 D0/D1(D2/D3 均由 pack 覆盖)。
    """
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    frozen: dict[str, Any] = {}
    for family in R5_OVERRIDE_FAMILIES:
        if family == "c2_context":
            rungs = ["D0", "D1"] if tier == "B" else ["D0", "D1", "D2"]
        else:
            rungs = ["D0", "D1", "D2"]
        rungs = [r for r in CURRICULUM261_RUNGS if r in rungs]
        frozen[family] = {r: dict(specs[family].rung_params[r])
                          for r in rungs}
    scope = ("C1/C3 D0-D2 + C2 D0/D1"
             if tier == "B" else
             "C1/C3 D0-D2 + C2 D0/D1/D2(逐位等于历史)")
    payload = {"frozen_scope": scope, "tier": tier,
               "frozen_params": frozen}
    return {
        "frozen_scope": scope,
        "tier": tier,
        "frozen": frozen,
        "identity": "r5fp-" + hashlib.sha256(
            _canonical(payload).encode("utf-8")).hexdigest(),
    }


def verify_r4_inheritance(pack: dict[str, Any]) -> dict[str, Any]:
    """验证 pack 的 C1/C3 D3 继承值与 R4 常量/任务书/R4 artifact 一致。

    若 R4 lock dir(默认 repair4 artifacts 或 CURRICULUM261_R4_LOCK_DIR)
    存在 r4_parameter_pack.json,则额外复算其 digest 并逐位比对参数。
    """
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
        "format": "cur261-r5-r4-inheritance-verification-v1",
        "checks": checks,
        "pass": bool(checks["c1_matches_r4_constants"]
                     and checks["c3_matches_r4_constants"]
                     and checks["r4_pack_digest_bound"] and artifact_ok),
    }


def param_distance_from_historical(params: dict[str, Any],
                                   historical: dict[str, Any],
                                   keys: tuple[str, ...] = (
                                       "alpha_bps", "vol_bps",
                                       "wick_kappa"),
) -> float:
    """tie-breaker:参数相对历史值的归一化偏离(Σ|new-hist|/hist)。

    只对预注册的可调数值键计距(design plan 锁定;越小越保守)。
    """
    total = 0.0
    for k in keys:
        if k in params and k in historical:
            base = abs(float(historical[k])) or 1.0
            total += abs(float(params[k]) - float(historical[k])) / base
    return float(total)
