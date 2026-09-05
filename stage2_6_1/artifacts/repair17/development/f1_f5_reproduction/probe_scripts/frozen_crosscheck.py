"""WP0 冻结实现交叉验证(只读;WSL conda freqtrade-rl)。

用 d2ee974 冻结实现复算 R16 已保存 pair/block 表的 C1/C3 与 C2 matched
条件,与独立公式实现(独立脚本)互为对照。不生成任何数据。
"""
import sys, json
from pathlib import Path

REPO = Path("/mnt/e/trading/freqai-rl-audit")
PROJ = Path.home() / "projects" / "crypto_rl"
sys.path.insert(0, str(PROJ / "src"))

import numpy as np  # noqa: E402
from rl_curriculum.curriculum261_r5_pairs import corpus_conditions_r5  # noqa: E402
from rl_curriculum.curriculum261_r6_pairs import _blockwise_conditions  # noqa: E402
from rl_curriculum.curriculum261_qualification import (  # noqa: E402
    REQUIRED_BASELINES,
)
from rl_curriculum.curriculum261_r4_pairs import (  # noqa: E402
    cluster_stats, difficulty_series, margin_series, table_series,
)

RUNGS = ["D0", "D1", "D2", "D3"]
IN = REPO / ".r17_wp0_inputs"

out = {}
for corpus in ("main", "holdout"):
    d = json.load(open(IN / f"pair_evidence_table_{corpus}.json"))
    for fam in ("c1_opportunity", "c3_cost"):
        table = d[fam]
        ladder = {r: cluster_stats(difficulty_series(table, r))
                  for r in RUNGS}
        margins = {b: {r: cluster_stats(margin_series(table, r, b))
                       for r in RUNGS}
                   for b in REQUIRED_BASELINES[fam]}
        gaps = {}
        for k in range(3):
            hi, lo = RUNGS[k], RUNGS[k + 1]
            gap = ladder[hi]["mean"] - ladder[lo]["mean"]
            se = float(np.sqrt(ladder[hi]["se"] ** 2 + ladder[lo]["se"] ** 2))
            gaps[f"{hi}-{lo}"] = {"gap": float(gap), "se_pair_cluster": se}
        oracle_pos = bool(all(
            float(np.mean(table_series(table, r, "oracle"))) > 0
            for r in RUNGS))
        _pad = {"bootstrap_ci": {"ci_low": None, "ci_high": None}}
        fr = {"difficulty_ladder": {r: {**ladder[r], **_pad}
                                    for r in RUNGS},
              "fixed_baseline_margins": {
                  b: {r: {**margins[b][r], **_pad} for r in RUNGS}
                  for b in REQUIRED_BASELINES[fam]},
              "adjacent_rung_gaps": gaps,
              "oracle_positive_all_rungs": oracle_pos,
              "pair_integrity_pass_rate": 1.0}  # evidence_missing;隔离数值
        cond = corpus_conditions_r5(fr, 1.5)
        out[f"c13_{corpus}_{fam}"] = {
            "pass_with_integrity_assumed_1": cond["pass"],
            "ordering_ok": cond["ordering_ok"],
            "gaps_ge_kappa_se": cond["gaps_ge_kappa_se"],
            "d3_positive": cond["d3_positive"],
            "d3_mean_ge_kappa_se": cond["d3_mean_ge_kappa_se"],
            "margins_ok": cond["margins_ok"],
            "d3_mean": cond["d3_mean"], "d3_se": cond["d3_se"],
        }

for corpus in ("main", "holdout"):
    d = json.load(open(IN / f"c2_block_evidence_table_{corpus}.json"))
    cond = _blockwise_conditions(d, 1.5)
    out[f"matched_{corpus}"] = {
        "pass": cond["pass"],
        "ordering_ok": cond["ordering_ok"],
        "gaps_ge_kappa_block_se": cond["gaps_ge_kappa_block_se"],
        "d3_positive": cond["d3_positive"],
        "d3_mean_ge_kappa_se": cond["d3_mean_ge_kappa_se"],
        "margins_ok": cond["margins_ok"],
        "block_integrity_unity": cond["block_integrity_unity"],
        "d3_mean": cond["d3_mean"], "d3_block_se": cond["d3_block_se"],
        "margin_always_flat_D3_mean": cond["fixed_baseline_margins"][
            "always_flat"]["D3"]["mean"],
        "margin_always_flat_D3_ok": cond["fixed_baseline_margins"][
            "always_flat"]["D3"]["ok"],
    }

dst = IN / "frozen_crosscheck_result.json"
json.dump(out, open(dst, "w"), indent=1, ensure_ascii=False)
for k, v in out.items():
    print(k, "->", {kk: vv for kk, vv in v.items() if isinstance(vv, bool)})
print("written:", dst)
