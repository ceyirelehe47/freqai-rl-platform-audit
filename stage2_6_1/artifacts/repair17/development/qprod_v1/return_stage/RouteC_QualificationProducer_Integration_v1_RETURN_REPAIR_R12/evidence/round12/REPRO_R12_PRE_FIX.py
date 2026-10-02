# R12 pre-fix repro (C23=9dcb5a54 bytes): Q1 gate-vs-declaration dependency
# New regression introduced by R11 fix: the K-consistency GATE (recompute
# real |k_m-k_v| vs bound) sits inside `k_abs_diff is not None` condition.
# Full support present (model 110xK=1, validation 110xK=4, ova means 1/4,
# frozen tol 0.05, real diff 3) but deleting the redundant k_abs_diff copy
# (and/or declared k_tolerance) must NOT turn a real gate failure into
# consistent=True. C22 rejected these; C23 passes -> regression.
# Also: same deletions on legal 1/1 (real diff 0) must still PASS.
import importlib.util
import sys

sys.path.insert(0, "/tmp")
from repro_r10 import base_report

DEPLOY = ("/home/cryptorl/projects/crypto_rl/src/rl_curriculum/"
          "curriculum261_r17_cue_contract.py")
C22 = "/tmp/r12_c22_cue_contract.py"


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


rec_c23 = load(DEPLOY, "cue_c23").recompute_audit_semantics_from_report
rec_c22 = load(C22, "cue_c22").recompute_audit_semantics_from_report


def prep(kv_val, kad, del_kad, del_kt):
    r = base_report()
    ova = r["once_vs_attempts"]
    dgm = r["direct_generator"]["model"]["aggregate"]
    dgv = r["direct_generator"]["validation"]["aggregate"]
    ova["k_mean_model"], ova["k_mean_validation"] = 1.0, kv_val
    dgm["k_mean"], dgv["k_mean"] = 1.0, kv_val
    dgm["k_histogram"] = {"1": 110}
    dgv["k_histogram"] = {str(int(kv_val)) if float(kv_val).is_integer()
                          else str(kv_val): 110}
    if kad is not None:
        ova["k_abs_diff"] = kad
    else:
        ova.pop("k_abs_diff", None)
    if del_kad:
        ova.pop("k_abs_diff", None)
    if del_kt:
        ova.pop("k_tolerance", None)
    r["engineering_fixture"] = True
    return r


def run(tag, kv_val, kad, del_kad=False, del_kt=False):
    r = prep(kv_val, kad, del_kad, del_kt)
    o23 = rec_c23(r)
    r2 = prep(kv_val, kad, del_kad, del_kt)
    o22 = rec_c22(r2)
    print("%-44s C23=%-5s C22=%-5s %s" % (
        tag, o23["all_consistent"], o22["all_consistent"],
        o23["threshold_discrepancies"][:1]
        if not o23["all_consistent"] else ""))


print("=== 1/4 (real diff 3 > 0.05): all three must REJECT ===")
run("G1a complete kad=3", 4, 3)
run("G1b del k_abs_diff", 4, None)
run("G1c del k_abs_diff + del k_tolerance", 4, None, True, True)
print("=== 4/1 symmetric: all three must REJECT ===")
run("G2a complete kad=3 (km=4)", 4, 3)  # placeholder, real 4/1 below
r = base_report()
ova = r["once_vs_attempts"]
ova["k_mean_model"], ova["k_mean_validation"] = 4.0, 1.0
r["direct_generator"]["model"]["aggregate"].update(
    k_mean=4.0, k_histogram={"4": 110})
r["direct_generator"]["validation"]["aggregate"].update(
    k_mean=1.0, k_histogram={"1": 110})
r["engineering_fixture"] = True
print("%-44s C23=%-5s C22=%-5s" % (
    "G2a' full 4/1", rec_c23(r)["all_consistent"],
    rec_c22(r)["all_consistent"]))
ova.pop("k_abs_diff")
r2 = base_report()
o2 = r2["once_vs_attempts"]
o2["k_mean_model"], o2["k_mean_validation"] = 4.0, 1.0
r2["direct_generator"]["model"]["aggregate"].update(
    k_mean=4.0, k_histogram={"4": 110})
r2["direct_generator"]["validation"]["aggregate"].update(
    k_mean=1.0, k_histogram={"1": 110})
r2["engineering_fixture"] = True
o2.pop("k_abs_diff")
print("%-44s C23=%-5s C22=%-5s" % (
    "G2b' del k_abs_diff", rec_c23(r2)["all_consistent"],
    rec_c22(r2)["all_consistent"]))
print("=== legal 1/1 diff 0: same deletions must PASS ===")
run("L1a complete kad=0", 1, 0.0)
run("L1b del k_abs_diff", 1, None)
run("L1c del k_abs_diff + del k_tolerance", 1, None, True, True)
