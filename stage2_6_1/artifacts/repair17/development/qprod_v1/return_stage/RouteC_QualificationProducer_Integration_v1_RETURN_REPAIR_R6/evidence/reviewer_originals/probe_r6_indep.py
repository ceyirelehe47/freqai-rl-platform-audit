# 独立 reviewer 探针(R6 内容验收):自构报告,与提交的 REPRO_R6_PRE_FIX.py
# 数值不同源,直调 pure helper,零生成/零 fixture(除显式 fixture 变体)。
import sys, json, math
sys.path.insert(0, "src")
from rl_curriculum.curriculum261_r17_cue_contract import (
    AUDIT_REQUIRED_CHECK_NAMES, cue_contract_audit_digest,
    recompute_audit_semantics_from_report as rec)

SE = 0.02
RECALL_TOL = max(3.0 * math.sqrt(2 * SE * SE), 0.005)  # 0.0848528...

def legal():
    dgc = {}
    for n in ("model", "validation"):
        dgc[n] = {
            "block_cluster": {"se": SE, "ci95": [0.5, 0.7]},
            "empirical_recall": 0.6, "analytic_conditional": 0.6,
            "diff_tolerance": 0.06,
            "replay_ok": True, "bounds_ok": True,
            "cue_table_consistent_across_rungs": True,
            "max_replay_abs_error": 0.0,
            "aggregate": {"k_mean": 3.0, "n_detected": 6, "n_events": 10},
            "tail": {"n_events": 0}}
    return {
        "p_contract": 0.6,
        "monte_carlo": {"p_hat": 0.6, "tolerance": 0.001},
        "direct_generator": dgc,
        "tail_mirror_bound_integrity": {
            "pass": True,
            "per_corpus": {
                n: {"ok": True, "violations": [], "n_violations": 0,
                    "exact_noise_replay_ok": True,
                    "bounds_ok_all_positions": True}
                for n in ("model", "validation")}},
        "global_k_audit": {
            "contract_version": "v1", "contract_digest": "d",
            "graph_integrity_ok": True, "n_eligible_cells": 4,
            "T_obs": 1.5, "argmax_cell": "m/v1",
            "final": {"tier": "tier2", "verdict": "PASS",
                      "indeterminate": False},
            "verdict": "PASS", "pass": True},
        "once_vs_attempts": {
            "model_mode": "once", "validation_mode": "attempts",
            "first_pass_bitwise_check": {"n_blocks_checked": 3,
                                         "n_mismatches": 0,
                                         "bitwise_ok": True},
            "recall_model": 0.6, "recall_validation": 0.6,
            "abs_diff": 0.0, "tolerance": RECALL_TOL,
            "recall_modes_consistent": True,
            "k_mean_model": 3.0, "k_mean_validation": 3.0,
            "k_abs_diff": 0.0, "k_tolerance": 0.05,
            "k_modes_consistent": True},
        "aggregate_recompute_ok": True,
        "checks": {k: True for k in AUDIT_REQUIRED_CHECK_NAMES}}

def run(tag, mutate=None, fixture=False, expect=None):
    r = legal()
    if fixture:
        r["engineering_fixture"] = True
    if mutate:
        mutate(r)
    out = rec(r)
    gates_false = [k for k, v in out["recomputed"].items() if v is False]
    verdict = "True" if out["all_consistent"] else "False"
    ok = "?" if expect is None else ("OK" if verdict == expect else "UNEXPECTED")
    print(f"[{ok}] {tag}: all_consistent={verdict} gates_false={gates_false} "
          f"fixture_mode={out['fixture_mode']}")
    for d in out["threshold_discrepancies"]:
        print("    disc:", d[:150])
    if out["fixture_delegated"]:
        print("    delegated:", out["fixture_delegated"])
    return out

run("ctl legal-complete", expect="True")
run("ctl-fixture legal+fixture-flag", fixture=True, expect="True")

# addendum 原型:来源 1/1、派生声明 1/4、差值 0
def c1ex(r):
    o = r["once_vs_attempts"]
    o["k_mean_model"] = 0.25
run("C1EX k-source 1/1 vs derived 1/4 diff0", c1ex, expect="False")

# N1 仅 validation 侧来源不符,派生自洽(k_abs_diff=0.5)
def n1(r):
    o = r["once_vs_attempts"]
    o["k_mean_validation"] = 2.5
    o["k_abs_diff"] = 0.5
run("N1 k-source-mismatch-validation-side", n1, expect="False")

# N2 recall abs_diff 派生矛盾
def n2(r):
    r["once_vs_attempts"]["abs_diff"] = 0.01
run("N2 recall-abs_diff-derived-mismatch", n2, expect="False")

# N3 gk final 层与顶层矛盾(镜像方向)
def n3(r):
    r["global_k_audit"]["final"]["verdict"] = "FAIL"
run("N3 gk-final-vs-top-mismatch", n3, expect="False")

# N4 tail per_corpus 空缺件
def n4(r):
    r["tail_mirror_bound_integrity"]["per_corpus"] = {}
run("N4 tail-per-corpus-empty", n4, expect="False")

# N5 bitwise_ok 在场=False
def n5(r):
    r["once_vs_attempts"]["first_pass_bitwise_check"]["bitwise_ok"] = False
run("N5 bitwise-false-present", n5, expect="False")

# N6 fixture 下 gk 缺 verdict/pass(fail-closed 观察)
def n6(r):
    del r["global_k_audit"]["verdict"]
    del r["global_k_audit"]["pass"]
run("N6 fixture-gk-missing-verdict-pass", n6, fixture=True)

# N7 INDETERMINATE + pass=True 双重矛盾
def n7(r):
    g = r["global_k_audit"]
    g["verdict"] = "INDETERMINATE"; g["pass"] = True
    g["final"]["verdict"] = "INDETERMINATE"
run("N7 gk-indeterminate-pass-true", n7, expect="False")

# N8 K tolerance 自带值抬高攻击(派生/来源自洽)
def n8(r):
    o = r["once_vs_attempts"]
    r["direct_generator"]["validation"]["aggregate"]["k_mean"] = 2.5
    o["k_mean_validation"] = 2.5
    o["k_abs_diff"] = 0.5
    o["k_tolerance"] = 1.0
run("N8 k-tolerance-inflation", n8)

# N9 仅缺 tolerance 一个必需键
def n9(r):
    del r["once_vs_attempts"]["tolerance"]
run("N9 ova-missing-tolerance-only", n9, expect="False")

# N10 ova 整块缺失且无 fixture
def n10(r):
    del r["once_vs_attempts"]
run("N10 ova-block-absent-no-fixture", n10, expect="False")

# N11 fixture 下在场 K 矛盾仍拒(委托不掩盖)
def n11(r):
    r["once_vs_attempts"]["k_mean_model"] = 2.0
run("N11 fixture-present-k-contradiction", n11, fixture=True, expect="False")

# N12 fixture 下 ova 缺件如实标注并保持通过(工程排练路径)
def n12(r):
    del r["once_vs_attempts"]["k_mean_model"]
    del r["once_vs_attempts"]["recall_model"]
run("N12 fixture-missing-keys-honest-delegation", n12, fixture=True)

# digest 正确重算自证:合法报告 digest 可重算一致;篡改 ova 不影响 digest
# 但被重算层捕获(digest 不绑定 ova —— 重算层是独立防线)
r = legal()
r["audit_digest"] = cue_contract_audit_digest(r)
ok = r["audit_digest"] == cue_contract_audit_digest(r)
r["once_vs_attempts"]["k_mean_model"] = 0.25
out = rec(r)
print(f"[{'OK' if ok else 'FAIL'}] digest-recompute-legal={ok}; "
      f"tampered-ova caught={not out['all_consistent']}")
