# RV1 probe 4: exporter rejection paths on mutated COPIES of e2e originals.
import json
import shutil
import sys
from pathlib import Path
SRC = "/home/cryptorl/projects/crypto_rl/src"
if SRC not in sys.path:
    sys.path.insert(0, SRC)
from rl_curriculum.ppo262_qprod_export import (
    QProdExportError, export_qualification_delivery,
)

E2E = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/"
           "development/qprod_v1/level_a_e2e/v1_r2_reference/"
           "qprod_level_a_qprod_a_eng_v1")
WORK = Path("/tmp/rv1_probes/p4_export")


def fresh_copy(tag):
    d = WORK / tag
    if d.exists():
        shutil.rmtree(d)
    d.mkdir(parents=True)
    shutil.copytree(E2E / "artifacts", d / "artifacts")
    shutil.copytree(E2E / "state", d / "state")
    return d


def attempt(tag, mutate=None, **kwargs):
    d = fresh_copy(tag)
    if mutate:
        mutate(d)
    try:
        export_qualification_delivery(
            d / "artifacts", d / "state", d / "out", **kwargs)
        print("FAIL " + tag + ": export unexpectedly succeeded")
    except QProdExportError as exc:
        rej = d / "out" / "export_rejected.json"
        six = [p.name for p in (d / "out").iterdir()
               if p.name != "export_rejected.json"]
        zero = len(six) == 0
        print(("PASS " if rej.is_file() and zero else "FAIL ") + tag +
              " :: " + str(exc)[:120] + " :: zero_bundle=" + str(zero))


attempt("EN1.formal-scope", expected_scope="formal")


def tamper_pack(d):
    p = d / "artifacts" / "parameter_pack.json"
    pack = json.loads(p.read_text(encoding="utf-8"))
    pack["families"]["c1_opportunity"]["rung_params"]["D0"][
        "opp_drift_bps"] = 999.0
    p.write_text(json.dumps(pack), encoding="utf-8")


attempt("EN2.tampered-pack", mutate=tamper_pack,
        expected_scope="engineering")


def drop_raw(d):
    (d / "artifacts" / "qprod_qualification_raw.json").unlink()


attempt("EN3.missing-raw-evidence", mutate=drop_raw,
        expected_scope="engineering")


def fake_pass(d):
    # evidence fails gate, result still claims PASS (PASS-string only)
    rg = d / "artifacts" / "robustness_gate.json"
    g = json.loads(rg.read_text(encoding="utf-8"))
    g["pass"] = False
    rg.write_text(json.dumps(g), encoding="utf-8")


attempt("EN4.pass-string-vs-failing-evidence", mutate=fake_pass,
        expected_scope="engineering")
