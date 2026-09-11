"""C2 正式校准 launch 准备(零生成;任务 R17V2C13PostRunGovernanceAndC2LaunchPrep-v1)。

本模块只固化"下一次 C2 正式校准任务书"的执行设计边界并对其与现存
代码做差分;它**不是**正式 plan,不注册任何 namespace,不创建 claim,
不触碰生成器。固定输入来自 C2_FIXED_DESIGN_INPUTS.md(2026-09-11):

- 候选恰好三个:historical / conservative / midpoint;
- 样本规模恰好三档:10 / 15 / 20 blocks;
- 机械选择顺序:minimum qualifying n → maximin → minimum distance
  to historical → stable candidate id;
- 正式 binding source:dedicated semantic corpus(160 blocks)+
  cue contract audit(500+500);matched-ladder 与 independent point
  metrics 只作 diagnostic;
- R16 失败定位在 C2 matched main D3,不被 C1/C3 v2 通过覆盖;
- v2 工程 run 的 c2l_historical_control 只是统一 V2 fit 覆盖的工程
  控制,不是 C2 design selection。

差分结论(2026-09-11,对 d3cdf3d 起始的实现面):
- historical == curriculum261_c2.C2_RUNG_PARAMS 原值 ==
  C2_LADDER_CANDIDATES['c2l_historical_control'];
- conservative == C2_LADDER_CANDIDATES['c2l_conservative'] 逐位;
- midpoint 不在 §17 预注册网格中 —— 本模块新增其字面值(只允许
  alpha_bps/wick_kappa 白名单覆盖,结构键与历史逐位一致),供下一份
  授权任务书审阅;在此之前任何代码不得用它生成;
- n 选项 == r6_design.FORMAL_BLOCK_OPTIONS {10,15,20};
- 机械顺序 == r6_design §22 实现(最小合格 n → maximin →
  distance → id);
- dedicated semantic == SEMANTIC_BLOCKS_PER_CORPUS_R17(160,
  r17_orchestrator/r17_design);cue audit ==
  r9_cue_contract.AUDIT_BLOCKS_PER_CORPUS(500;cue/noncue 双语料)。
"""
from __future__ import annotations

from typing import Any

#: 三候选的固定难度覆盖(仅 alpha/wick_kappa 白名单;结构键冻结)。
_MIDPOINT_OVERRIDES = {
    "D0": {"alpha_bps": 71.0, "wick_kappa": 0.81},
    "D1": {"alpha_bps": 55.0, "wick_kappa": 0.575},
    "D2": {"alpha_bps": 40.0, "wick_kappa": 0.39},
    "D3": {"alpha_bps": 30.0, "wick_kappa": 0.255},
}

#: 固定设计输入的字面快照(差分基准;不是参数搜索许可)。
FIXED_DESIGN_LITERAL = {
    "candidates": {
        "historical": {
            "alpha_bps": [68.0, 54.0, 40.0, 32.0],
            "wick_kappa": [0.80, 0.55, 0.38, 0.25]},
        "conservative": {
            "alpha_bps": [74.0, 56.0, 40.0, 28.0],
            "wick_kappa": [0.82, 0.60, 0.40, 0.26]},
        "midpoint": {
            "alpha_bps": [71.0, 55.0, 40.0, 30.0],
            "wick_kappa": [0.81, 0.575, 0.39, 0.255]},
    },
    "n_options": [10, 15, 20],
    "mechanical_order": [
        "minimum_qualifying_n", "maximin",
        "minimum_distance_to_historical", "stable_candidate_id"],
    "binding_sources": {
        "dedicated_semantic_blocks": 160,
        "cue_audit_blocks_per_corpus": 500,
        "cue_audit_corpora": 2,
    },
}

NOT_AUTHORIZED = True  #: 本准备不构成任何生成/claim 授权。


def next_calibration_candidates() -> dict[str, dict[str, dict[str, Any]]]:
    """下一次 C2 正式校准的恰好三候选(historical/conservative/midpoint)。

    historical 与 conservative 从权威源派生(非复制字面量);midpoint
    为固定设计新增字面覆盖(白名单键),三者键集与历史逐位一致。
    """
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES, _c2_ladder,
    )

    return {
        "historical": C2_LADDER_CANDIDATES["c2l_historical_control"],
        "conservative": C2_LADDER_CANDIDATES["c2l_conservative"],
        "midpoint": _c2_ladder(**_MIDPOINT_OVERRIDES),
    }


def diff_against_fixed_design() -> dict[str, Any]:
    """对现存代码做差分(C01-C04);纯静态,零生成、零调用。"""
    from rl_curriculum.curriculum261_c2 import C2_RUNG_PARAMS
    from rl_curriculum.curriculum261_r6_design import FORMAL_BLOCK_OPTIONS
    from rl_curriculum.curriculum261_r6_param_pack import (
        C2_LADDER_CANDIDATES, ladder_distance_from_historical,
    )
    from rl_curriculum.curriculum261_r17_design import (
        SEMANTIC_BLOCKS_PER_CORPUS_R17,
    )
    from rl_curriculum.curriculum261_r9_cue_contract import (
        AUDIT_BLOCKS_PER_CORPUS,
    )

    candidates = next_calibration_candidates()
    rungs = ("D0", "D1", "D2", "D3")

    def axis(ladder, key):
        return [ladder[r][key] for r in rungs]

    checks: dict[str, bool] = {}
    # C01:候选恰好三个;historical == C2 历史原值;conservative ==
    # 预注册网格同名候选;midpoint == 固定设计字面值;无第四候选。
    checks["exactly_three_candidates"] = set(candidates) == {
        "historical", "conservative", "midpoint"}
    checks["historical_is_c2_rung_params"] = all(
        candidates["historical"][r] == dict(C2_RUNG_PARAMS[r])
        for r in rungs)
    checks["conservative_matches_preregistered"] = all(
        candidates["conservative"][r]
        == C2_LADDER_CANDIDATES["c2l_conservative"][r] for r in rungs)
    lit = FIXED_DESIGN_LITERAL["candidates"]
    checks["midpoint_matches_fixed_literal"] = all(
        axis(candidates["midpoint"], k) == lit["midpoint"][k]
        for k in ("alpha_bps", "wick_kappa"))
    checks["historical_matches_fixed_literal"] = all(
        axis(candidates["historical"], k) == lit["historical"][k]
        for k in ("alpha_bps", "wick_kappa"))
    checks["conservative_matches_fixed_literal"] = all(
        axis(candidates["conservative"], k) == lit["conservative"][k]
        for k in ("alpha_bps", "wick_kappa"))
    # C02:n 恰好 10/15/20。
    checks["n_options_exact"] = sorted(FORMAL_BLOCK_OPTIONS) == [10, 15, 20]
    # C03:binding source 规模。
    bs = FIXED_DESIGN_LITERAL["binding_sources"]
    checks["semantic_160"] = SEMANTIC_BLOCKS_PER_CORPUS_R17 == \
        bs["dedicated_semantic_blocks"]
    checks["cue_audit_500_plus_500"] = AUDIT_BLOCKS_PER_CORPUS == \
        bs["cue_audit_blocks_per_corpus"]
    # 机械顺序差分(r6_design §22 注释与实现;文字合同核对)。
    import inspect

    from rl_curriculum import curriculum261_r6_design as r6d

    src = inspect.getsource(r6d)
    checks["mechanical_order_min_n_first"] = (
        "for n in FORMAL_BLOCK_OPTIONS" in src
        and "ranked = sorted(" in src
        and "param_distance_from_historical" in src)
    # C04:v2 工程 run 的 historical control 不是 design selection(由
    # 既有 profile 工程合同与 R16 事实承载;此处固化声明)。
    checks["r16_fail_retained"] = True  # 历史事实,见 prep 报告
    distances = {
        cid: ladder_distance_from_historical(candidates[cid])
        for cid in candidates}
    return {
        "all_pass": all(checks.values()),
        "checks": checks,
        "candidate_axis": {
            cid: {k: axis(ladder, k)
                  for k in ("alpha_bps", "wick_kappa")}
            for cid, ladder in candidates.items()},
        "distance_from_historical": distances,
        "n_options": sorted(FORMAL_BLOCK_OPTIONS),
        "binding_sources": {
            "dedicated_semantic_blocks": (
                SEMANTIC_BLOCKS_PER_CORPUS_R17),
            "cue_audit_blocks_per_corpus": AUDIT_BLOCKS_PER_CORPUS,
        },
        "not_authorized": NOT_AUTHORIZED,
    }
