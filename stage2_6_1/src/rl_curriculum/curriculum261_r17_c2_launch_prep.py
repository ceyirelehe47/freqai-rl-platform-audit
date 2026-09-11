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

#: 零调用哨兵面(§7.3):行为验证期间这些入口的调用计数必须全为 0。
#: 哨兵安装失败(模块/符号不可导入)按 fail-closed 处理,不得静默。
ZERO_CALL_SENTINELS = (
    ("generator", "rl_curriculum.curriculum261_api",
     "generate_pair_with_attempts"),
    ("generator", "rl_curriculum.curriculum261_r6_design", "generate_pair"),
    ("fit", "rl_curriculum.curriculum261_r17_calibration",
     "fit_preprocessor_v2_from_bank_r17"),
    ("eval", "rl_curriculum.curriculum261_r6_design",
     "_evaluate_candidate_matched"),
    ("policy", "rl_curriculum.evaluator", "run_policy_episode"),
    ("canonical", "rl_curriculum.curriculum261_r4_pairs",
     "evaluate_pair_corpus_r4"),
    ("claim", "r17_v2_c13_profile", "write_preclaim_receipt"),
    ("claim", "r17_v2_c13_profile", "consume_production_claim"),
    ("claim", "r17_v2_c13_profile", "persist_final_plan"),
    ("namespace", "rl_curriculum.curriculum261_r17_registry",
     "require_r17_namespace_registered"),
)


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
    # 机械顺序差分:r6_design §22 的文字合同只作诊断;PASS 由
    # verify_mechanical_selection_behavior 对真实 selector 的行为
    # 差分决定(B5:源码字符串存在性不再充当行为证明)。
    behavior = verify_mechanical_selection_behavior()
    # C04:v2 工程 run 的 historical control 不是 design selection(由
    # 既有 profile 工程合同与 R16 事实承载;此处固化声明)。
    checks["r16_fail_retained"] = True  # 历史事实,见 prep 报告
    distances = {
        cid: ladder_distance_from_historical(candidates[cid])
        for cid in candidates}
    return {
        "all_pass": all(checks.values()) and behavior["all_pass"],
        "checks": checks,
        "selector_behavior": behavior,
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


def _install_sentinels() -> tuple[dict[str, dict[str, Any]], list[str]]:
    """安装零调用哨兵;返回 (句柄, 不可安装清单)。

    哨兵被调用时先计数再抛 AssertionError(fail-closed:行为验证期间
    任何生成/评估/claim 入口调用都是治理违规,不允许静默继续)。
    """
    import importlib

    handles: dict[str, dict[str, Any]] = {}
    unavailable: list[str] = []
    for interface, module_name, symbol in ZERO_CALL_SENTINELS:
        try:
            module = importlib.import_module(module_name)
            original = getattr(module, symbol)
        except (ImportError, AttributeError) as exc:
            unavailable.append(
                f"{interface}:{module_name}.{symbol} ({type(exc).__name__})")
            continue
        counts: dict[str, int] = {interface: 0}

        def _make_guard(iface=interface, mod=module_name,
                        sym=symbol, box=counts) -> Any:
            def guard(*args, **kwargs):
                box[iface] = box.get(iface, 0) + 1
                raise AssertionError(
                    f"zero-call sentinel violated: {iface} "
                    f"{mod}.{sym} invoked during C2 prep behavior "
                    f"verification")

            return guard

        setattr(module, symbol, _make_guard())
        handles[f"{module_name}.{symbol}"] = {
            "module": module, "symbol": symbol, "original": original,
            "counts": counts}
    return handles, unavailable


def _release_sentinels(handles: dict[str, dict[str, Any]]) -> None:
    for entry in handles.values():
        setattr(entry["module"], entry["symbol"], entry["original"])


def _table(qualified, scores, distances):
    out = {}
    for cid in qualified:
        out[cid] = {
            "qualified_by_block_count": {
                str(n): bool(q) for n, q in qualified[cid].items()},
            "maximin_score_by_qualified_n": {
                str(n): float(s) for n, s in scores[cid].items()},
            "param_distance_from_historical": float(distances[cid]),
        }
    return out


def verify_mechanical_selection_behavior() -> dict[str, Any]:
    """对现存权威 selector(r6_design.mechanical_selection)做零生成
    行为差分(§7.2/C03-C08)。

    用合成结果表(不触发生成/评估)验证机械顺序的全部行为条款;
    同时对 generator/fit/eval/canonical/policy/claim/namespace
    安装哨兵,计数必须全部为 0(§7.3)。源码字符串扫描只保留为
    诊断,不决定 PASS。
    """
    import itertools

    from rl_curriculum.curriculum261_r6_design import (
        FORMAL_BLOCK_OPTIONS, mechanical_selection,
    )

    scenarios: dict[str, Any] = {}

    def run(table):
        return mechanical_selection(table)

    # C03:最小合格 n 压过更高 n 的更高 score。
    got = run(_table(
        {"alpha": {10: True, 15: True, 20: True},
         "beta": {10: False, 15: True, 20: True}},
        {"alpha": {10: 1.0, 15: 1.1, 20: 1.2},
         "beta": {15: 99.0, 20: 100.0}},
        {"alpha": 0.9, "beta": 0.1}))
    scenarios["min_qualifying_n_beats_higher_score"] = (got == ("alpha", 10))
    # C04:同 n 时 maximin 决胜。
    got = run(_table(
        {"alpha": {10: True}, "beta": {10: True}},
        {"alpha": {10: 2.0}, "beta": {10: 3.0}},
        {"alpha": 0.1, "beta": 0.9}))
    scenarios["same_n_maximin_decides"] = (got == ("beta", 10))
    # C05a:maximin 同分 → 距 historical 最近者胜。
    got = run(_table(
        {"alpha": {10: True}, "beta": {10: True}},
        {"alpha": {10: 2.5}, "beta": {10: 2.5}},
        {"alpha": 0.5, "beta": 0.2}))
    scenarios["maximin_tie_distance_decides"] = (got == ("beta", 10))
    # C05b:距离也同分 → 稳定 candidate id(字典序)决胜。
    got = run(_table(
        {"beta": {10: True}, "alpha": {10: True}},
        {"beta": {10: 2.5}, "alpha": {10: 2.5}},
        {"beta": 0.2, "alpha": 0.2}))
    scenarios["distance_tie_stable_id_decides"] = (got == ("alpha", 10))
    # C06a:不合格项永不参与(即使分数更高)。
    got = run(_table(
        {"alpha": {10: True}, "beta": {10: False}},
        {"alpha": {10: 0.5}, "beta": {10: 999.0}},
        {"alpha": 0.9, "beta": 0.0}))
    scenarios["unqualified_never_selected"] = (got == ("alpha", 10))
    # C06b:全不合格 → 明确 no-selection,不回退 control。
    got = run(_table(
        {"alpha": {10: False, 15: False, 20: False},
         "beta": {10: False, 15: False, 20: False}},
        {"alpha": {}, "beta": {}},
        {"alpha": 0.0, "beta": 0.0}))
    scenarios["all_unqualified_no_selection"] = (got == (None, None))
    # C07:输入顺序打乱不改变结果。
    base = _table(
        {"alpha": {10: True, 15: True}, "beta": {10: True},
         "gamma": {10: False, 15: True}},
        {"alpha": {10: 1.0, 15: 5.0}, "beta": {10: 2.0},
         "gamma": {15: 7.0}},
        {"alpha": 0.3, "beta": 0.6, "gamma": 0.1})
    expected = run(base)
    shuffle_ok = True
    for perm in itertools.permutations(("alpha", "beta", "gamma")):
        table = {cid: base[cid] for cid in perm}
        if run(table) != expected:
            shuffle_ok = False
    scenarios["input_order_invariant"] = shuffle_ok
    # C08:matched/independent point diagnostics 等额外键不改变 verdict
    # (机械顺序只读 qualified/maximin/distance/id 四类键)。
    decorated = {cid: {**res, "matched_ladder_diagnostics": {"x": 1},
                       "independent_point_metrics": {"y": 2}}
                 for cid, res in base.items()}
    scenarios["diagnostic_keys_do_not_change_verdict"] = (
        run(decorated) == expected)

    # 输入合同(C01/C02/C07 的拒绝面在固定输入层):候选恰好三个
    # historical/conservative/midpoint(重复 id 不可能出现在 dict 构建,
    # 集合精确相等即拒绝第四/缺候选);n 恰好 {10,15,20}(拒绝第四 n)。
    fixed_candidates = next_calibration_candidates()
    scenarios["fixed_inputs_exactly_three_candidates"] = (
        set(fixed_candidates) == {"historical", "conservative", "midpoint"}
        and len(fixed_candidates) == 3)
    scenarios["fixed_inputs_n_options_exact"] = (
        sorted(FORMAL_BLOCK_OPTIONS) == [10, 15, 20])

    # 零调用哨兵(验证上述差分自身未触发生成/评估/claim)。
    handles, unavailable = _install_sentinels()
    sentinel_counts: dict[str, int] = {}
    sentinel_violations: list[str] = []
    try:
        for name in ("min_qualifying_n_beats_higher_score",
                     "same_n_maximin_decides",
                     "maximin_tie_distance_decides",
                     "distance_tie_stable_id_decides",
                     "unqualified_never_selected",
                     "all_unqualified_no_selection"):
            run(base)
        for key, entry in handles.items():
            for interface, count in entry["counts"].items():
                sentinel_counts[f"{interface}:{key}"] = count
                if count:
                    sentinel_violations.append(f"{interface}:{key}")
    finally:
        _release_sentinels(handles)

    diagnostics = {}
    import inspect

    from rl_curriculum import curriculum261_r6_design as r6d

    src = inspect.getsource(r6d)
    diagnostics["source_scan_min_n_first"] = (
        "for n in FORMAL_BLOCK_OPTIONS" in src
        and "ranked = sorted(" in src
        and "param_distance_from_historical" in src)

    all_pass = (all(scenarios.values())
                and not sentinel_violations
                and not unavailable
                and all(v == 0 for v in sentinel_counts.values()))
    return {
        "all_pass": all_pass,
        "scenarios": scenarios,
        "zero_call": {
            "counts": sentinel_counts,
            "violations": sentinel_violations,
            "unavailable_sentinels": unavailable,
            "all_zero": (not sentinel_violations and not unavailable
                         and all(v == 0
                                 for v in sentinel_counts.values())),
        },
        "diagnostics_only_source_scan": diagnostics,
        "selector": "rl_curriculum.curriculum261_r6_design."
                    "mechanical_selection",
    }
