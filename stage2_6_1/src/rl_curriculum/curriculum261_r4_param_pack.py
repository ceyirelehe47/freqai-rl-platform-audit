"""阶段 2.6.1 Repair R4:版本化 D3-only 课程参数包(CurriculumR4D3Pack-v1)。

R3 FAIL 的根因之一是 C1/C3 的 D3 设计余量与 pair-cluster 采样不确定性
同量级;R4 显式授权对 C1-D3 / C3-D3 做"仅来自现有 generator 已支持
参数集合"的有限重校准(任务书 §5)。

版本化纪律(§6):
- R0/R1/R2/R3 namespace 继续使用历史参数(本模块不修改
  C1_RUNG_PARAMS / C2_RUNG_PARAMS / C3_RUNG_PARAMS 任何值);
- R4 corpus 生成时经 generate_pair(rung_params_override={"D3": ...})
  注入(仅 C1/C3 的 D3 档;C2 与全部 D0-D2 逐位等于历史值);
- candidate grid 在生成 design episodes 前预注册锁定(本模块常量);
- 选定的 pack 以独立 artifact(r4_parameter_pack.json + digest)固化,
  calibration/qualification 只从 artifact 读取(fail closed)。

C1-D3 活旋钮分析(cur261-c1-v5 固定段模式):
- opp_drift_bps(机会段漂移):A 侧可捕获 edge 的直接来源;
- vol_bps(噪声):同时缩放 pmr 阈值(闭式 k×vol×2.740)与噪声,
  影响段内 ret-4 动量确认的翻转率(2×opp/vol 主导段内 churn);
- neg_drift_bps 在精确平衡合同下惰性(neg_eff = n_opp×opp/n_neg);
- seg_len_range 受 v5 合同约束(固定 24,12 段 = 288 bar)不可动;
- distractor_rate 历史为 0(结构休眠),保持 0。
候选方向:漂移上调 / 噪声下调 / 组合;上限约束 opp < D2 的 34.0,
保持 D3 明显难于 D2。

C3-D3 活旋钮分析(cur261-c3-v4):
- alpha_bps(每单位强度毛 edge):直接抬高 above-cost 事件占比与
  参考每次交易净 edge(约束 alpha < D2 的 54.0);
- mixture(strong/marginal/weak):strong 份额上调(约束 < D2 的
  0.34),marginal/weak 仍须保有大量亚成本诱饵;
- distractor_rate / cue_rate:churn 诱饵密度与事件密度;
- payoff_bars / vol_bps 冻结。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

R4_PACK_VERSION = "CurriculumR4D3Pack-v1"

#: C1-D3 候选网格(预注册;生成 design episodes 前锁定)。
#: 全部候选保持 seg_len_range/state_weights/distractor_rate/neg_drift_bps
#: 逐位等于 R3 值(结构冻结),只动 opp_drift_bps / vol_bps。
C1_D3_CANDIDATES: dict[str, dict[str, Any]] = {
    "c1_a_edge_up": {
        "opp_drift_bps": 24.5, "neg_drift_bps": 16.0, "vol_bps": 26.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
    "c1_b_edge_up2": {
        "opp_drift_bps": 28.0, "neg_drift_bps": 16.0, "vol_bps": 26.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
    "c1_c_vol_down": {
        "opp_drift_bps": 21.0, "neg_drift_bps": 16.0, "vol_bps": 21.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
    "c1_d_edge_vol": {
        "opp_drift_bps": 24.5, "neg_drift_bps": 16.0, "vol_bps": 22.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
    "c1_e_edge_vol2": {
        "opp_drift_bps": 28.0, "neg_drift_bps": 16.0, "vol_bps": 21.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
    "c1_f_edge_vol3": {
        "opp_drift_bps": 31.0, "neg_drift_bps": 16.0, "vol_bps": 20.0,
        "seg_len_range": [24, 24], "state_weights": [0.36, 0.28, 0.36],
        "distractor_rate": 0.000},
}

#: C3-D3 候选网格(预注册)。payoff_bars/vol_bps 冻结;alpha < 54.0
#: (D2),strong 份额 < 0.34(D2),weak+marginal 合计 >= 0.62。
C3_D3_CANDIDATES: dict[str, dict[str, Any]] = {
    "c3_a_alpha_up": {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.14, 0.36, 0.50],
        "distractor_rate": 0.060},
    "c3_b_strong_up": {
        "alpha_bps": 46.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.22, 0.36, 0.42],
        "distractor_rate": 0.060},
    "c3_c_alpha_strong": {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.20, 0.36, 0.44],
        "distractor_rate": 0.060},
    "c3_d_alpha_strong2": {
        "alpha_bps": 52.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.24, 0.34, 0.42],
        "distractor_rate": 0.060},
    "c3_e_mild_dis_down": {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.230, "mixture": [0.18, 0.36, 0.46],
        "distractor_rate": 0.050},
    "c3_f_density_up": {
        "alpha_bps": 50.0, "payoff_bars": 1, "vol_bps": 18.0,
        "cue_rate": 0.260, "mixture": [0.18, 0.38, 0.44],
        "distractor_rate": 0.060},
}


def r4_candidate_grid() -> dict[str, dict[str, dict[str, Any]]]:
    """预注册 candidate 网格的深拷贝(design plan 锁定用)。"""
    import copy

    return {
        "c1_opportunity": copy.deepcopy(C1_D3_CANDIDATES),
        "c3_cost": copy.deepcopy(C3_D3_CANDIDATES),
    }


#: 允许 R4 覆盖的 (family, rung) 白名单(仅 C1/C3 的 D3)。
R4_OVERRIDE_FAMILIES = ("c1_opportunity", "c3_cost")
R4_OVERRIDE_RUNG = "D3"


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False)


def pack_payload(selected: dict[str, dict[str, Any]],
                 evidence: dict[str, Any] | None = None) -> dict[str, Any]:
    """构造 pack payload(selected: {family: {"candidate": id, "params": …}})。"""
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    overrides: dict[str, dict[str, Any]] = {}
    for family, sel in selected.items():
        if family not in R4_OVERRIDE_FAMILIES:
            raise RuntimeError(f"pack 不允许覆盖 {family}(仅 C1/C3 的 D3)")
        params = dict(sel["params"])
        historical = dict(specs[family].rung_params[R4_OVERRIDE_RUNG])
        if set(params) != set(historical):
            raise RuntimeError(
                f"{family} D3 覆盖参数键集与历史不一致:{sorted(params)} vs "
                f"{sorted(historical)}")
        overrides[family] = params
    return {
        "format": "cur261-r4-parameter-pack-v1",
        "pack_version": R4_PACK_VERSION,
        "iteration": "r4",
        "override_scope": {
            "families": list(R4_OVERRIDE_FAMILIES),
            "rung": R4_OVERRIDE_RUNG,
            "rules": "仅 C1/C3 的 D3 覆盖;C2 与全部 D0-D2 逐位等于"
                     "历史(family_specs)值;R0-R3 namespace 不受影响",
        },
        "selected": {f: {"candidate": selected[f]["candidate"],
                         "params": dict(selected[f]["params"])}
                     for f in sorted(selected)},
        "d3_overrides": {f: overrides[f] for f in sorted(overrides)},
        "evidence": evidence or {},
    }


def pack_digest(pack: dict[str, Any]) -> str:
    """pack digest(canonical JSON;排除运行时间与 digest 自身字段)。"""
    payload = dict(pack)
    payload.pop("created_utc", None)
    payload.pop("digest", None)
    return "r4pk-" + hashlib.sha256(
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
    path = out_dir / "r4_parameter_pack.json"
    path.write_text(json.dumps(pack, indent=2, ensure_ascii=False,
                               default=str), encoding="utf-8")
    (out_dir / "r4_parameter_pack_digest.txt").write_text(
        pack["digest"], encoding="utf-8")
    return path


def load_selected_pack(out_dir: Path) -> dict[str, Any]:
    """读取已锁定 pack 并复算 digest(fail closed;篡改即拒)。"""
    out_dir = Path(out_dir)
    path = out_dir / "r4_parameter_pack.json"
    if not path.is_file():
        raise RuntimeError(
            f"R4 parameter pack 不存在: {path}(design 阶段合格并锁定后"
            "才允许 calibration/final)")
    pack = json.loads(path.read_text(encoding="utf-8"))
    stored = pack.get("digest")
    if not stored or pack_digest(pack) != stored:
        raise RuntimeError("R4 parameter pack digest 复算不一致(fail closed)")
    digest_path = out_dir / "r4_parameter_pack_digest.txt"
    if digest_path.is_file() and \
            digest_path.read_text(encoding="utf-8").strip() != stored:
        raise RuntimeError("R4 parameter pack digest 文件与 payload 不一致")
    return pack


def r4_override_for(family: str,
                    pack: dict[str, Any]) -> dict[str, dict[str, Any]] | None:
    """pack -> generate_pair 的 rung_params_override(仅 C1/C3 有值)。

    generate_pair 的 override 形态是 {rung: params}(rung 键控);
    C2 不适用 override(冻结),返回 None。
    """
    override = pack.get("d3_overrides", {}).get(family)
    if override is None:
        return None
    return {R4_OVERRIDE_RUNG: dict(override)}


def apply_r4_override(
        family: str, rung_params_by_rung: dict[str, dict[str, Any]],
        pack: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """把 pack 的 D3 覆盖应用到某 family 的逐 rung 参数(返回新 dict)。"""
    out = {r: dict(v) for r, v in rung_params_by_rung.items()}
    override = pack.get("d3_overrides", {}).get(family)
    if override is not None:
        out[R4_OVERRIDE_RUNG] = dict(override)
    return out


def r4_family_rung_params(family: str,
                          pack: dict[str, Any],
                          ) -> dict[str, dict[str, Any]]:
    """某 family 在 R4 下的完整逐 rung 参数(历史 + D3 覆盖)。"""
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    spec = family_specs()[family]
    base = {r: dict(spec.rung_params[r]) for r in CURRICULUM261_RUNGS}
    return apply_r4_override(family, base, pack)


def frozen_parameter_identity() -> dict[str, Any]:
    """冻结参数面(C2 全部 + C1/C3 的 D0-D2)的身份哈希。

    这些档位 R4 不得漂移;identity 进入 plan 并在 final 复算比对。
    """
    from rl_curriculum.curriculum261_api import CURRICULUM261_RUNGS
    from rl_curriculum.curriculum261_pairs import family_specs

    specs = family_specs()
    frozen: dict[str, Any] = {}
    for family in ("c1_opportunity", "c2_context", "c3_cost"):
        rungs = [r for r in CURRICULUM261_RUNGS
                 if not (family in R4_OVERRIDE_FAMILIES
                         and r == R4_OVERRIDE_RUNG)]
        frozen[family] = {r: dict(specs[family].rung_params[r])
                          for r in rungs}
    payload = {
        "frozen_scope": "C2 全部 rung + C1/C3 的 D0-D2(逐位等于 R3)",
        "frozen_params": frozen,
    }
    return {
        "frozen": frozen,
        "identity": "r4fp-" + hashlib.sha256(
            _canonical(payload).encode("utf-8")).hexdigest(),
    }
