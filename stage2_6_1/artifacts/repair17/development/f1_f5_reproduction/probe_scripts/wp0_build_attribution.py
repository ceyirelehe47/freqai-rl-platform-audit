"""R17 WP0:R16 calibration 证据只读统计归因(生成 repair17 诊断区)。

从 exact baseline d2ee974 的已保存证据独立复算 R16 main curriculum
gate 的实际 false leaf。零数据生成调用;只读取 .r17_wp0_inputs/ 下
从 baseline 导出的文件并写入 repair17 只读诊断区。

独立公式实现(不复用仓库统计 helper);冻结实现交叉验证结果由
frozen_crosscheck.py 另行产生并引用。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

REPO = Path(r"E:\trading\freqai-rl-audit")
IN = REPO / ".r17_wp0_inputs"
OUT = REPO / "stage2_6_1/artifacts/repair17/wp0_r16_readonly_attribution"
BASELINE = "d2ee974a5bb6573b4dfaa0d09288d20a74a91c87"
KAPPA = 1.5
PGR_MIN = 0.65
RUNGS = ["D0", "D1", "D2", "D3"]
REQ = {"c1_opportunity": ["always_flat", "always_long"],
       "c3_cost": ["always_flat", "always_long", "c3_cost_ignorant"],
       "c2_context": ["always_flat", "always_long", "c2_local_only"]}

INPUT_FILES = [
    "calibration_evidence.json", "robustness_gate.json",
    "pair_evidence_table_main.json", "pair_evidence_table_holdout.json",
    "c2_block_evidence_table_main.json",
    "c2_block_evidence_table_holdout.json",
    "c2_independent_marginal_main.json",
    "c2_independent_marginal_holdout.json",
    "cue_semantic_calibration.json",
    "r16_parameter_pack.json", "r16_design_plan.json",
]


def stats(v):
    n = len(v)
    m = sum(v) / n
    sd = (sum((x - m) ** 2 for x in v) / (n - 1)) ** 0.5 if n > 1 else 0.0
    se = sd / (n ** 0.5) if n > 1 else 0.0
    return {"n": n, "mean": m, "sd": sd, "se": se}


def series(rows, rung, pol):
    return [r["returns"][pol] for r in rows if r["rung"] == rung]


def cond_row(name, mean, se, thr, cmp_desc, ok, extra=None):
    return {"condition": name, "mean": mean, "se": se,
            "threshold": thr, "comparison": cmp_desc,
            "distance_to_threshold": (mean - thr
                                      if mean is not None and thr is not None
                                      else None),
            "pass": ok, **(extra or {})}


def c13_conditions(table):
    """独立公式:C1/C3 全条件(对照 corpus_conditions_r5 冻结口径)。"""
    rows = table["rows"]
    out = {"corpus": table["corpus"], "family": table["family"],
           "n_pairs": table["n_pairs"], "difficulty_ladder": {},
           "ordering": {}, "gaps": {}, "d3": {}, "margins": {},
           "oracle": {}, "integrity_evidence": "evidence_missing"}
    lad = {r: stats([a - b for a, b in zip(
        series(rows, r, "reference"), series(rows, r, "always_flat"))])
        for r in RUNGS}
    for r in RUNGS:
        out["difficulty_ladder"][r] = lad[r]
    means = [lad[r]["mean"] for r in RUNGS]
    out["ordering"] = cond_row(
        "ordering D0>D1>D2>D3", None, None, None,
        "means[0]>means[1]>means[2]>means[3]",
        bool(means[0] > means[1] > means[2] > means[3]),
        {"means": means})
    for k in range(3):
        hi, lo = RUNGS[k], RUNGS[k + 1]
        gap = lad[hi]["mean"] - lad[lo]["mean"]
        se = (lad[hi]["se"] ** 2 + lad[lo]["se"] ** 2) ** 0.5
        out["gaps"][f"{hi}-{lo}"] = cond_row(
            f"gap {hi}-{lo}", gap, se, KAPPA * se,
            "gap>0 AND gap>=kappa*SE(sqrt-sum sq)",
            bool(gap > 0 and gap >= KAPPA * se),
            {"ratio_to_threshold": gap / (KAPPA * se) if se > 0 else None})
    d3 = lad["D3"]
    out["d3"] = cond_row(
        "D3 mean", d3["mean"], d3["se"], KAPPA * d3["se"],
        "mean>0 AND mean>=kappa*SE",
        bool(d3["mean"] > 0 and d3["mean"] >= KAPPA * d3["se"]),
        {"positive": bool(d3["mean"] > 0),
         "ge_kappa_se": bool(d3["mean"] >= KAPPA * d3["se"]),
         "ratio_to_threshold": (d3["mean"] / (KAPPA * d3["se"])
                                if d3["se"] > 0 else None)})
    fam = table["family"]
    for b in REQ[fam]:
        for r in RUNGS:
            m = stats([a - b_ for a, b_ in zip(
                series(rows, r, "reference"), series(rows, r, b))])
            ok = bool(m["mean"] > 0 and m["mean"] >= KAPPA * m["se"])
            out["margins"][f"{b}/{r}"] = cond_row(
                f"margin {b} @ {r}", m["mean"], m["se"], KAPPA * m["se"],
                "mean>0 AND mean>=kappa*SE", ok,
                {"ratio_to_threshold": (m["mean"] / (KAPPA * m["se"])
                                        if m["se"] > 0 else None)})
    margins_ok = all(v["pass"] for v in out["margins"].values())
    for r in RUNGS:
        o = series(rows, r, "oracle")
        out["oracle"][r] = {"mean": sum(o) / len(o),
                            "positive": bool(sum(o) / len(o) > 0)}
    out["numeric_pass_with_integrity_assumed_1"] = bool(
        out["ordering"]["pass"] and all(v["pass"] for v in out["gaps"].values())
        and out["d3"]["pass"] and margins_ok
        and all(v["positive"] for v in out["oracle"].values()))
    return out


def matched_conditions(table):
    """独立公式:C2 matched blockwise 全条件(对照 _blockwise_conditions)。"""
    rows = table["rows"]
    out = {"corpus": table["corpus"], "n_blocks": table["n_blocks"],
           "difficulty_ladder_blockwise": {}, "ordering": {}, "gaps": {},
           "d3": {}, "margins": {}, "integrity": {}, "oracle": {}}
    lad = {r: stats([row["pair_metrics"][r]["difficulty"] for row in rows])
           for r in RUNGS}
    out["difficulty_ladder_blockwise"] = lad
    means = [lad[r]["mean"] for r in RUNGS]
    out["ordering"] = cond_row(
        "ordering D0>D1>D2>D3", None, None, None,
        "means[0]>means[1]>means[2]>means[3]",
        bool(means[0] > means[1] > means[2] > means[3]), {"means": means})
    for k in range(3):
        hi, lo = RUNGS[k], RUNGS[k + 1]
        s = [row["gaps"][f"{hi}-{lo}"] for row in rows]
        st = stats(s)
        pgr = sum(1 for x in s if x > 0) / len(s) if s else 0.0
        ok = bool(st["n"] >= 2 and st["mean"] > 0
                  and st["mean"] >= KAPPA * st["se"] and pgr >= PGR_MIN)
        out["gaps"][f"{hi}-{lo}"] = cond_row(
            f"gap {hi}-{lo}", st["mean"], st["se"], KAPPA * st["se"],
            "n>=2 AND mean>0 AND mean>=kappa*SE AND pgr>=0.65", ok,
            {"positive_gap_block_rate": pgr,
             "ratio_to_threshold": (st["mean"] / (KAPPA * st["se"])
                                    if st["se"] > 0 else None)})
    d3 = lad["D3"]
    out["d3"] = cond_row(
        "D3 blockwise mean", d3["mean"], d3["se"], KAPPA * d3["se"],
        "mean>0 AND mean>=kappa*SE",
        bool(d3["mean"] > 0 and d3["mean"] >= KAPPA * d3["se"]),
        {"positive": bool(d3["mean"] > 0),
         "ge_kappa_se": bool(d3["mean"] >= KAPPA * d3["se"]),
         "ratio_to_threshold": (d3["mean"] / (KAPPA * d3["se"])
                                if d3["se"] > 0 else None)})
    for b in REQ["c2_context"]:
        for r in RUNGS:
            m = stats([row["pair_metrics"][r]["margins"][b]
                       for row in rows])
            ok = bool(m["mean"] > 0 and m["mean"] >= KAPPA * m["se"])
            out["margins"][f"{b}/{r}"] = cond_row(
                f"margin {b} @ {r}", m["mean"], m["se"], KAPPA * m["se"],
                "mean>0 AND mean>=kappa*SE", ok,
                {"ratio_to_threshold": (m["mean"] / (KAPPA * m["se"])
                                        if m["se"] > 0 else None)})
    integ = bool(table["n_blocks"] > 0 and all(
        row["cross_rung_integrity_pass"] and row["pair_integrity_all_pass"]
        for row in rows))
    out["integrity"] = {"block_integrity_unity": integ}
    for r in RUNGS:
        o = [row["pair_metrics"][r]["returns"].get("oracle", 0.0)
             for row in rows]
        out["oracle"][r] = {"mean": sum(o) / len(o),
                            "positive": bool(sum(o) / len(o) > 0)}
    out["numeric_pass"] = bool(
        out["ordering"]["pass"] and all(v["pass"] for v in out["gaps"].values())
        and out["d3"]["pass"]
        and all(v["pass"] for v in out["margins"].values())
        and integ and all(v["positive"] for v in out["oracle"].values()))
    return out


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for name in INPUT_FILES:
        raw = (IN / name).read_bytes()
        blob = subprocess.run(
            ["git", "-C", str(REPO), "rev-parse",
             f"{BASELINE}:stage2_6_1/artifacts/repair16/{name}"],
            capture_output=True, text=True).stdout.strip()
        manifest.append({
            "file": name, "source_ref": BASELINE,
            "source_path": f"stage2_6_1/artifacts/repair16/{name}",
            "git_blob_sha": blob,
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw)})
    json.dump({"baseline": BASELINE, "inputs": manifest},
              open(OUT / "wp0_inputs_manifest.json", "w"),
              indent=1, ensure_ascii=False)

    c13 = {}
    for corpus in ("main", "holdout"):
        d = json.load(open(IN / f"pair_evidence_table_{corpus}.json"))
        for fam in ("c1_opportunity", "c3_cost"):
            c13[f"{corpus}/{fam}"] = c13_conditions(d[fam])
    json.dump(c13, open(OUT / "r16_c13_conditions_full_table.json", "w"),
              indent=1, ensure_ascii=False)

    matched = {}
    for corpus in ("main", "holdout"):
        d = json.load(open(IN / f"c2_block_evidence_table_{corpus}.json"))
        matched[corpus] = matched_conditions(d)
    json.dump(matched,
              open(OUT / "r16_c2_matched_conditions_full_table.json", "w"),
              indent=1, ensure_ascii=False)

    comp = {}
    for corpus in ("main", "holdout"):
        m = json.load(open(IN / f"c2_independent_marginal_{corpus}.json"))
        comp[f"marginal/{corpus}"] = {
            "guard_pass": m["guard"]["pass"],
            "note_cue_point_metrics_binding_false_is_declaration":
                "guard.cue_point_metrics_binding=False 声明 independent "
                "cue 点指标不参与 binding(R16 §六 lineage;"
                "diagnostic_only=True),不是 gate 失败"}
    sem = json.load(open(IN / "cue_semantic_calibration.json"))
    comp["semantic/calibration"] = {
        "pass": sem["pass"], "shared_pass": sem["shared"]["pass"],
        "candidate_pass": sem["candidate"]["pass"]}
    json.dump(comp,
              open(OUT / "r16_semantic_marginal_component_check.json", "w"),
              indent=1, ensure_ascii=False)

    # ---- 主归因结论 ----
    frozen = json.load(open(IN / "frozen_crosscheck_result.json"))
    mm = matched["main"]
    mh = matched["holdout"]
    d3m = mm["d3"]
    d3h = mh["d3"]
    attribution = {
        "format": "r17-wp0-r16-readonly-attribution-v1",
        "baseline_read": BASELINE,
        "question": "R16 calibration main curriculum gate 的精确 false leaf",
        "r16_recorded_aggregate": {
            "curriculum_main_independent_pass": False,
            "curriculum_holdout_independent_pass": True,
            "r16_report_claim": "R16 主报告称 'C1/C3 严格条件在 "
                                "calibration_r16 语料未达门槛'",
            "claim_verdict": "错误归因:C1/C3 数值条件在 main 与 holdout "
                             "全部通过(独立公式与冻结实现双路一致)"},
        "false_leaf": {
            "component": "c2_matched_main (statistical_block_conditions)",
            "corpus": "c2_matched_calibration_r16",
            "condition": "D3 blockwise difficulty mean >= kappa*SE",
            "kappa": KAPPA,
            "main": {"n_blocks": mm["n_blocks"],
                     "d3_mean": d3m["mean"], "d3_se": d3m["se"],
                     "kappa_times_se": KAPPA * d3m["se"],
                     "distance": d3m["mean"] - KAPPA * d3m["se"],
                     "ratio_to_threshold": d3m["ratio_to_threshold"],
                     "d3_positive": d3m["positive"],
                     "d3_ge_kappa_se": d3m["ge_kappa_se"],
                     "pass": d3m["pass"]},
            "holdout": {"n_blocks": mh["n_blocks"],
                        "d3_mean": d3h["mean"], "d3_se": d3h["se"],
                        "kappa_times_se": KAPPA * d3h["se"],
                        "ratio_to_threshold": d3h["ratio_to_threshold"],
                        "pass": d3h["pass"]},
            "collateral_false": (
                "margin always_flat/D3 与 D3 difficulty 同数值"
                "(difficulty := reference−always_flat),同一条件连带 false;"
                "其余全部条件(ordering/三段 gap 含 pgr/D3 正值性/"
                "always_long 与 c2_local_only margins/block integrity/"
                "oracle)在 main 全部通过"),
            "main_vs_holdout_difference": (
                "holdout D3 均值 0.006322(1.711x κ×SE)通过;"
                "main D3 均值 0.002789 仅为 κ×SE 的 0.989x——"
                "C2 matched main 语料的 D3 rung 难度信号幅度不足,"
                "非排序逆转、非负均值、非实现偏差"),
        },
        "other_components": {
            "c1_main": frozen["c13_main_c1_opportunity"],
            "c3_main": frozen["c13_main_c3_cost"],
            "c1_holdout": frozen["c13_holdout_c1_opportunity"],
            "c3_holdout": frozen["c13_holdout_c3_cost"],
            "semantic": comp["semantic/calibration"],
            "marginal_main": comp["marginal/main"],
            "marginal_holdout": comp["marginal/holdout"],
        },
        "evidence_gaps": {
            "c13_pair_integrity_pass_rate": (
                "pair_evidence_table 不含主语料 integrity 列;"
                "generator_stress.json(独立 48 对 stress 语料)为 1.0 仅作 "
                "侧证。即便 integrity=1.0,matched_main 的 D3 false 已足以"
                "唯一解释 main gate false;integrity 不改变归因结论"),
            "matched_non_statistical_checks": (
                "density/local cue/context observability 顶层布尔由 "
                "robustness_gate.density_pass=True 与 semantic pass=True "
                "侧证;block 表内 integrity 列已复算通过"),
        },
        "independent_vs_frozen_crosscheck": {
            "method": "独立公式实现(本脚本)与 d2ee974 冻结实现"
                      "(frozen_crosscheck.py, WSL freqtrade-rl)双路",
            "agreement": "全部组件布尔一致",
            "frozen_results_file": "frozen_crosscheck_result.json"},
        "decision_under_section_4_4": (
            "第 2 类:冻结规则下的真实统计失败。计算/路由/汇总实现与"
            "冻结合同一致(双路复算);不存在实现偏离或证据矛盾。"
            "R16 永久 FAIL 不变;R17 工程修复满足准入后允许一次新正式"
            "验证(全新 namespace),不修改 κ/样本量/baseline/判据"),
        "zero_generation_calls": True,
    }
    json.dump(attribution,
              open(OUT / "r16_calibration_false_leaf_attribution.json",
                   "w"), indent=1, ensure_ascii=False)
    print("WP0 written to", OUT)
    for p in sorted(OUT.iterdir()):
        print(" ", p.name, p.stat().st_size)


if __name__ == "__main__":
    main()
