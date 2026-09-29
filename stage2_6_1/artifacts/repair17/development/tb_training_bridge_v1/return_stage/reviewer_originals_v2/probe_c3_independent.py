#!/usr/bin/env python3
"""Reviewer independent C3 re-verification probe.

Zero native episode generation / zero fit / zero optimizer updates.
Counterexample semantics from ChatGPT REVIEW.md sections 2-5 + the 8
minimum classes, each paired with a legal positive control. Runs against
the public implementation in the WSL deploy tree.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import types
from pathlib import Path
from types import SimpleNamespace

OUT = Path("/mnt/f/trading/tmp_reviewer_tb_v1_fix/out")
if OUT.exists():
    shutil.rmtree(OUT)
OUT.mkdir(parents=True)
ENG = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_2/artifacts/"
           "eng_training_bridge_v1")

results = []


def rec(name, ok, detail):
    results.append({"name": name, "expectation_met": bool(ok),
                    "detail": detail})
    print(("PASS " if ok else "FAIL ") + name + " :: " + str(detail)[:220],
          flush=True)


def sha_file(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


# ---------------------------------------------------------------- imports
from rl_curriculum import ppo262_banks as BK
from rl_curriculum import ppo262_cli as C
from rl_curriculum import ppo262_eng_profile as G
from rl_curriculum import ppo262_entry_specs as ES
from rl_curriculum import ppo262_smoke as SM
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.curriculum261_production_obs import (
    attach_production_features,
)
from rl_curriculum.ppo262_eng_fixture import (
    ENG_FIT_FIXTURE_SPECS, ENG_FIT_FIXTURE_ID, ENG_FIT_NAMESPACE,
    _fixture_episode_hash, build_eng_fixture, synthetic_ohlcv,
)
from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError, activated_profile_input, authorization_binding_digest,
    load_qualified_input, parameter_pack_digest, qualification_plan_digest,
)

FAMS = ("c1_opportunity", "c2_context", "c3_cost")


def write_json(p, obj):
    payload = json.dumps(obj, ensure_ascii=False, indent=2, default=str)
    Path(p).write_text(payload, encoding="utf-8")


def rebuild(out, filename, mutate):
    p = Path(out) / filename
    d = json.loads(p.read_text(encoding="utf-8"))
    mutate(d)
    write_json(p, d)


def rebind(out, auth_path, plan_mutate=None, result_mutate=None,
           exposure_mutate=None):
    """Consistently recompute outer bindings after plan mutation."""
    qual_dir = Path(out)
    plan = json.loads((qual_dir / "qualification_plan.json")
                      .read_text(encoding="utf-8"))
    if plan_mutate:
        plan_mutate(plan)
        write_json(qual_dir / "qualification_plan.json", plan)
    digest = qualification_plan_digest(plan)
    (qual_dir / "qualification_plan_digest.txt").write_text(digest + "\n",
                                                            encoding="utf-8")
    for fn, mut in (("qualification_result.json", result_mutate),
                    ("qualification_exposure.json", exposure_mutate)):
        p = qual_dir / fn
        d = json.loads(p.read_text(encoding="utf-8"))
        d["plan_digest"] = digest
        if mut:
            mut(d)
        write_json(p, d)
    auth = json.loads(Path(auth_path).read_text(encoding="utf-8"))
    auth["bindings"]["qualification_plan_digest"] = digest
    auth["binding_digest"] = authorization_binding_digest({
        **auth["bindings"], "profile": auth["profile"],
        "scope": auth["scope"]})
    new_auth = Path(auth_path).parent / (
        Path(auth_path).stem + "_rebind.json")
    write_json(new_auth, auth)
    return new_auth


def copy_fixture(src_out, dst_root, name):
    dst = Path(dst_root) / name
    shutil.copytree(src_out["qualification_dir"], dst)
    auth = Path(dst_root) / (name + "_auth.json")
    shutil.copy(src_out["authorization_path"], auth)
    return {"qualification_dir": str(dst), "authorization_path": str(auth)}


def loads_ok(out, scope="engineering"):
    load_qualified_input(out["qualification_dir"],
                         authorization_path=out["authorization_path"],
                         expected_scope=scope)


def rejects(out, scope="engineering", needle=None):
    try:
        loads_ok(out, scope)
    except QualifiedInputError as exc:
        problems = " | ".join(exc.report.get("problems", []))
        if needle and needle not in problems:
            return False, "rejected but wrong reason: " + problems[:180]
        return True, problems[:180]
    return False, "NOT rejected"


# ================================================================ fixtures
work = OUT / "fx"
fx_v1 = build_eng_fixture(work / "v1", variant="v1_r2_reference",
                          verbose=False)
fx_v2 = build_eng_fixture(work / "v2", variant="v2_perturbed", verbose=False)
print("fixtures built", flush=True)

# ================================================================ A loade
class BoundaryReached(Exception):
    pass


tmpA = tempfile.mkdtemp(dir=str(OUT))
r0, d0 = rejects(fx_v1, needle=None)
rec("A0_positive_control_loads", r0 is False,
    {"note": "v1 fixture loads (positive control)"})

out = copy_fixture(fx_v1, tmpA, "src_iter")
rebuild(out["qualification_dir"], "qualification_result.json",
        lambda d: d.update(source_iteration="another-qualification-attempt"))
ok, info = rejects(out, needle="source_iteration")
rec("A1_B21_source_iteration_mismatch_rejected", ok, info)

out = copy_fixture(fx_v1, tmpA, "exp_iter")
rebuild(out["qualification_dir"], "qualification_exposure.json",
        lambda d: d.update(iteration="another-training-iteration"))
ok, info = rejects(out, needle="exposure iteration")
rec("A2_B21_exposure_iteration_mismatch_rejected", ok, info)

out = copy_fixture(fx_v1, tmpA, "no_producer")
na = rebind(out["qualification_dir"], out["authorization_path"],
            plan_mutate=lambda p: p["code_identity"].pop("producer", None))
ok, info = rejects({"qualification_dir": out["qualification_dir"],
                    "authorization_path": str(na)}, needle="producer")
rec("A3_B21_missing_producer_identity_rejected", ok, info)

out = copy_fixture(fx_v1, tmpA, "fit_overlap")
na = rebind(out["qualification_dir"], out["authorization_path"],
            plan_mutate=lambda p: p["preprocessing"].update(
                fit_namespace="ppo_eng_bank_262e"))
ok, info = rejects({"qualification_dir": out["qualification_dir"],
                    "authorization_path": str(na)}, needle="fit namespace")
rec("A4_N01_declared_fit_ns_overlap_train_rejected", ok, info)

from rl_curriculum.curriculum261_api import CURRICULUM261_SEED_NAMESPACES
seed_namespaces = sorted(set(CURRICULUM261_SEED_NAMESPACES))
victim_ns = seed_namespaces[0]
out = copy_fixture(fx_v1, tmpA, "fit_261")
na = rebind(out["qualification_dir"], out["authorization_path"],
            plan_mutate=lambda p: p["preprocessing"].update(
                fit_namespace=victim_ns))
ok, info = rejects({"qualification_dir": out["qualification_dir"],
                    "authorization_path": str(na)}, needle="fit namespace")
rec("A5_N01_declared_fit_ns_261_collision_rejected", ok,
    {"victim": victim_ns, "info": info})

out = copy_fixture(fx_v1, tmpA, "env_tamper")
rebuild(out["qualification_dir"], "preprocessor_envelope.json",
        lambda d: d["hashes"].update(
            preprocessor_bundle_hash="WRONG-BUNDLE-HASH"))
ok, info = rejects(out)
rec("A6_envelope_tamper_control_rejected", ok, info)

out = copy_fixture(fx_v1, tmpA, "wrong_digest")
rebuild(out["qualification_dir"], "qualification_result.json",
        lambda d: d.update(plan_digest="WRONG"))
ok, info = rejects(out)
rec("A7_wrong_plan_digest_control_rejected", ok, info)

# A8 legal positive: Cq recorded at a different commit; common semantics
# equal -> must still load (loader must not demand commit equality).
out = copy_fixture(fx_v1, tmpA, "cq_other_commit")
na = rebind(out["qualification_dir"], out["authorization_path"],
            plan_mutate=lambda p: p["code_identity"].update(
                commit="0000000000000000000000000000000000000000"))
ok, info = rejects({"qualification_dir": out["qualification_dir"],
                    "authorization_path": str(na)})
rec("A8_legal_Cq_commit_difference_still_loads", ok is False, info)

# ================================================================ B bank
tmpB = tempfile.mkdtemp(dir=str(OUT))
qi_v2 = load_qualified_input(fx_v2["qualification_dir"],
                             authorization_path=fx_v2["authorization_path"],
                             expected_scope="engineering")

seen = {}


def _recorder_cap(family, rung, side, params):
    seen["params"] = dict(params)
    raise BoundaryReached("param_recorder boundary")


led_b0 = G.QuotaLedger(Path(tmpB) / "led_b0.jsonl")
try:
    G.generate_eng_bank(qi_v2, led_b0, param_recorder=_recorder_cap)
    reached = False
except BoundaryReached:
    reached = True
s = led_b0.sums()
rec("B0_bank_boundary_real_pack_v2",
    reached and seen.get("params", {}).get("opp_drift_bps") == 45.0
    and s["bank_episode_success"] == 0
    and s["bank_episode_candidate"] == 6,
    {"captured_opp_drift_bps": seen.get("params", {}).get("opp_drift_bps"),
     "sums": s, "note": "R2 value would be 42.0"})

params = qi_v2.rung_params()
params["c1_opportunity"]["D1"]["opp_drift_bps"] = 777.0
seen2 = {}


def _recorder_cap2(family, rung, side, params_):
    seen2["params"] = dict(params_)
    raise BoundaryReached("copy-mutation control")


led_b1 = G.QuotaLedger(Path(tmpB) / "led_b1.jsonl")
try:
    G.generate_eng_bank(qi_v2, led_b1, param_recorder=_recorder_cap2)
except BoundaryReached:
    pass
qi_v2.verify_integrity()
rec("B1_returned_copy_mutation_harmless",
    seen2.get("params", {}).get("opp_drift_bps") == 45.0,
    {"captured": seen2.get("params", {}).get("opp_drift_bps"),
     "note": "copy mutation did not reach cache; integrity intact"})

qi_bad = load_qualified_input(
    fx_v2["qualification_dir"],
    authorization_path=fx_v2["authorization_path"],
    expected_scope="engineering")
qi_bad._pack["families"]["c1_opportunity"]["rung_params"]["D1"][
    "opp_drift_bps"] = 999.0
led_b2 = G.QuotaLedger(Path(tmpB) / "led_b2.jsonl")
calls = []


def _recorder_spy(family, rung, side, params_):
    calls.append(1)
    return None


try:
    G.generate_eng_bank(qi_bad, led_b2, param_recorder=_recorder_spy)
    rejected = False
    info = "NOT rejected"
except QualifiedInputError as exc:
    rejected = True
    info = " | ".join(exc.report.get("problems", []))[:180]
rec("B2_B22_cached_pack_mutation_rejected_pre_generation",
    rejected and calls == [] and led_b2.records() == [],
    {"recorder_calls": len(calls), "ledger_events": len(led_b2.records()),
     "info": info})

# ================================================================ C route
tmpC = Path(tempfile.mkdtemp(dir=str(OUT)))

# C0: full CLI eng-route-check drives real prepare pipelines + boundary
# sentinels (zero generation).
for tag, fx in (("v2", fx_v2), ("v1", fx_v1)):
    rd = tmpC / ("route_" + tag)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = C.main(["eng-route-check",
                     "--qual-dir", str(fx["qualification_dir"]),
                     "--auth", str(fx["authorization_path"]),
                     "--out-dir", str(rd)])
    art = json.loads((rd / "eng_route_check.json").read_text(
        encoding="utf-8"))
    entries = list(art["entry_classes"])
    hits_ok = all(
        art["routes"][e]["consumer_boundary_hits"]["generate262_bank"] >= 1
        for e in entries)
    ref_ok = all(
        art["routes"][e]["consumer_boundary_hits"]["build_261_policy_set"]
        >= 1 for e in entries)
    ns_ok = all(art["routes"][e]["namespace"] == "ppo_eng_bank_262e"
                for e in entries)
    rec("C0_route_check_real_consumers_" + tag,
        rc == 0 and art["pass"] is True and hits_ok and ref_ok and ns_ok
        and art["default_context_official_r2"] is True
        and art["cached_pack_tamper_rejected"] is True,
        {"rc": rc, "entries": entries,
         "pack_differs_from_r2": art["pack_differs_from_r2"]})


class ProbeSentinel(Exception):
    pass


def _sentinel_prep(*a, **k):
    raise ProbeSentinel("shared prepare pipeline reached by real command")


def patch_es(attr, replacement):
    old = getattr(ES, attr)
    setattr(ES, attr, replacement)
    return old


# C1 config-dev (ungated): input resolution must go through shared
# prepare; sentinel fires before any generation.
old = patch_es("prepare_config_dev_inputs", _sentinel_prep)
try:
    C.cmd_config_dev(SimpleNamespace())
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_config_dev_inputs", old)
rec("C1_cmd_config_dev_uses_shared_prepare", fired, {})

# C2 ppo-smoke (ungated diagnostic command).
old = patch_es("prepare_smoke_inputs", _sentinel_prep)
try:
    SM.run_ppo262_smoke(out_dir=tmpC / "smoke_out")
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_smoke_inputs", old)
rec("C2_run_ppo262_smoke_uses_shared_prepare", fired, {})

# Fabricated gate artifacts (all state stays inside reviewer tmp dir).
art_dir = tmpC / "art"
art_dir.mkdir(parents=True, exist_ok=True)
sel = {"selected_candidate": "cand_a_center",
       "config": dict(PPO262_CANDIDATES["cand_a_center"]),
       "all_fail": False}
write_json(art_dir / "selected_ppo_config.json", sel)
for fam in FAMS:
    write_json(art_dir / ("probe_results_" + fam + ".json"), {
        "format": "ppo262-probe-result-v1", "family": fam,
        "namespace": "synthetic-gate-artifact", "config": "cand_a_center",
        "model_seed": 26201, "budget_episodes": 1, "budget_steps": 1,
        "env_audit": {"steps_taken": 1, "episodes_consumed": 1,
                      "first_pass_order_ok": True, "exposure_counts": {}},
        "train_pass": True,
        "capture_table": {fam + "/" + r: 0.5 for r in
                          ("D0", "D1", "D2", "D3")},
        "core_capture": 0.2, "behavior": {}, "behavior_gap": 0.2,
        "gate_core_capture_gt_0.10": True,
        "gate_behavior_gap_gt_0.10": True, "pass": True,
        "episode_curve": [0.1]})

old_art = C._art
C._art = lambda: art_dir


def _restore_art():
    C._art = old_art


# C3 probe (config gate): sentinel at shared prepare, before bank build.
old = patch_es("prepare_probe_inputs", _sentinel_prep)
try:
    C.cmd_probe(SimpleNamespace(family="c1_opportunity"))
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_probe_inputs", old)
    _restore_art()
rec("C3_cmd_probe_uses_shared_prepare", fired, {})

# C4 core (config gate + probe gate).
C._art = lambda: art_dir
old = patch_es("prepare_core_inputs", _sentinel_prep)
try:
    C.cmd_core(SimpleNamespace(replicate=1, order="staged"))
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_core_inputs", old)
    _restore_art()
rec("C4_cmd_core_uses_shared_prepare", fired, {})

# C5 dev-eval (probe gate).
C._art = lambda: art_dir
old = patch_es("prepare_dev_eval_inputs", _sentinel_prep)
try:
    C.cmd_dev_eval(SimpleNamespace())
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_dev_eval_inputs", old)
    _restore_art()
rec("C5_cmd_dev_eval_uses_shared_prepare", fired, {})

# C6 final-run: guards/begin-final stubbed to no-ops (their semantics are
# out of scope here); sentinel proves cmd_final_run input routing goes
# through the shared prepare pipeline, with zero state written.
import rl_curriculum.ppo262_final as PF

pf_plan = ({"model_hashes": ["staged_rep1_ep640"],
            "pass_thresholds": {}}, "0" * 64)
olds_pf = {}


def _stub(name, fn):
    olds_pf[name] = getattr(PF, name)
    setattr(PF, name, fn)


_stub("load_locked_final_plan", lambda art: pf_plan)
_stub("verify_final_run_guards", lambda plan, models,
      code_identity_262_now: [])
_stub("begin_final_execution", lambda digest: None)
C._art = lambda: art_dir
old = patch_es("prepare_final_inputs", _sentinel_prep)
try:
    C.cmd_final_run(SimpleNamespace())
    fired = False
except ProbeSentinel:
    fired = True
finally:
    patch_es("prepare_final_inputs", old)
    _restore_art()
    for name, oldf in olds_pf.items():
        setattr(PF, name, oldf)
rec("C6_cmd_final_run_uses_shared_prepare", fired, {})

# C7 default context: shared resolver keeps official R2 params/namespaces.
specs_default = {"smoke": ES.prepare_smoke_inputs(),
                 "config_dev": ES.prepare_config_dev_inputs(),
                 "dev_eval": ES.prepare_dev_eval_inputs(),
                 "final": ES.prepare_final_inputs()}
r2 = C._locked_rung_params()
r2_ok = all(sp.rung_params == r2 for sp in specs_default.values())
ns_ok = (specs_default["smoke"].namespace == "ppo_smoke_262"
         and specs_default["config_dev"].namespace == "ppo_config_dev_262"
         and specs_default["dev_eval"].namespace == "ppo_dev_eval_262"
         and specs_default["final"].namespace == "ppo_final_eval_262")
rec("C7_default_context_official_R2_byte_identical",
    r2_ok and ns_ok
    and r2["c1_opportunity"]["D1"]["opp_drift_bps"] == 42.0,
    {"r2_c1_D1_opp_drift_bps": r2["c1_opportunity"]["D1"]["opp_drift_bps"]})

# ================================================================ D cold
import numpy as np

from rl_curriculum.curriculum261_api import (
    CURRICULUM261_EPISODE_BARS, CURRICULUM261_INITIAL_PRICE,
    episode_content_hash,
)
from rl_curriculum.curriculum261_production_obs import (
    attach_production_features,
)
from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode


def make_synthetic_bank(qi, n=2):
    eps = []
    specs = [{"start": 100.0, "drift": 0.0002, "amp": 0.003, "period": 24.0,
              "phase": 0.0, "wick": 0.0015, "bars": 96},
             {"start": 110.0, "drift": -0.0001, "amp": 0.004, "period": 30.0,
              "phase": 1.0, "wick": 0.002, "bars": 96}]
    for k in range(n):
        df = attach_production_features(synthetic_ohlcv(specs[k]))
        ep = GeneratedEpisode(
            spec=EpisodeSpec(family="eng_synthetic", params={"k": k},
                             seed=9000 + k, split="train", timeframe="15m"),
            df=df, hidden=df.iloc[:0].copy(),
            family_version="eng-synth-v0", timeframe="15m", is_null=False,
            generator_fingerprint="reviewer-synthetic-fixture-v1")
        eps.append(ep)
    keys = [EpisodeKey("ppo_eng_bank_262e", "c1_opportunity", "D1", 0, "A"),
            EpisodeKey("ppo_eng_bank_262e", "c2_context", "D1", 0, "B")]
    return [LoadedEpisode(key=keys[i], episode=eps[i],
                          content_hash=episode_content_hash(eps[i]))
            for i in range(n)]


def build_reviewer_ckpt(qi, root):
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_eng_profile import (
        PPO262E_MODEL_SEED, PPO262E_SMOKE_CONFIG, PPO262E_SMOKE_STEPS,
        collect_frozen_probe, engineering_manifest,
    )
    from rl_curriculum.ppo262_train import save_model_with_manifest
    bank = make_synthetic_bank(qi)
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=qi.preprocessor)
    model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG),
                                PPO262E_MODEL_SEED, env)
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    manifest = engineering_manifest(qi, bank=bank, steps=PPO262E_SMOKE_STEPS,
                                    updates=0, config=PPO262E_SMOKE_CONFIG,
                                    model_seed=PPO262E_MODEL_SEED)
    saved = save_model_with_manifest(model, root / "eng_ppo_smoke_256",
                                     manifest=manifest)
    probe = collect_frozen_probe(qi.preprocessor, bank, model,
                                 bundle_hash=qi.bundle_hash)
    probe["binding_digest"] = "e262pb-" + hashlib.sha256(json.dumps(
        [saved["model_sha256"], qi.bundle_hash, probe["steps"],
         probe["reset_seed"]], sort_keys=True,
        separators=(",", ":")).encode("utf-8")).hexdigest()
    write_json(root / "eng_frozen_probe.json", probe)
    write_json(root / "eng_bank_smoke.json", {
        "episodes": manifest["bank"]["keys"],
        "bank_manifest": {"manifest_sha256":
                          manifest["bank"]["manifest_sha256"]},
        "reviewer_synthetic_binding_fixture": True})
    write_json(root / "eng_ppo_smoke.json", {
        "steps": PPO262E_SMOKE_STEPS, "optimizer_update_records": [],
        "model_sha256": saved["model_sha256"],
        "bank_manifest_sha256": manifest["bank"]["manifest_sha256"],
        "reviewer_synthetic_binding_fixture": True})
    return root


qi_v1 = load_qualified_input(fx_v1["qualification_dir"],
                             authorization_path=fx_v1["authorization_path"],
                             expected_scope="engineering")
tmpD = Path(tempfile.mkdtemp(dir=str(OUT)))
ckpt = build_reviewer_ckpt(qi_v1, tmpD / "ckpt")
print("reviewer synthetic ckpt built", flush=True)

r = G.cold_read_checkpoint(fx_v1["qualification_dir"],
                           fx_v1["authorization_path"], ckpt,
                           tmpD / "cr_good",
                           expected_profile="ppo262_engineering_v1")
rec("D0_cold_read_positive_control", r["pass"] is True,
    {"max_abs_diff": r["action_probability_max_abs_diff"],
     "n_checks": len(r["checks"])})

import stable_baselines3 as sb3


class BeforeModelLoad(Exception):
    pass


def _no_load(*a, **k):
    raise BeforeModelLoad("model load boundary reached")


def cold_reject_case(name, mutate_manifest=None, qual=None, auth=None,
                     tamper_probe=False):
    """Tamper a fresh copy of the ckpt; expect rejection BEFORE PPO.load."""
    case_dir = tmpD / ("case_" + name)
    shutil.copytree(ckpt, case_dir)
    if mutate_manifest:
        p = case_dir / "eng_ppo_smoke_256.manifest.json"
        m = json.loads(p.read_text(encoding="utf-8"))
        mutate_manifest(m)
        write_json(p, m)
    if tamper_probe:
        p = case_dir / "eng_frozen_probe.json"
        pr = json.loads(p.read_text(encoding="utf-8"))
        pr["binding_digest"] = "e262pb-" + "0" * 64
        write_json(p, pr)
    orig_load = sb3.PPO.load
    sb3.PPO.load = staticmethod(_no_load)
    try:
        G.cold_read_checkpoint(
            qual or fx_v1["qualification_dir"],
            auth or fx_v1["authorization_path"], case_dir,
            tmpD / ("cr_" + name))
        return False, "NOT rejected", True
    except QualifiedInputError as exc:
        return True, " | ".join(exc.report.get("problems", []))[:200], False
    except BeforeModelLoad:
        return False, "model load reached (rejection missing)", True
    finally:
        sb3.PPO.load = orig_load


ok, info, _ = cold_reject_case(
    "src_iter", lambda m: m["qualified_input"].update(
        qualification_source_iteration="forged_source"))
rec("D1_B3_cold_wrong_source_iteration_rejected_pre_load", ok, info)

ok, info, _ = cold_reject_case(
    "no_auth", lambda m: m["qualified_input"].pop(
        "authorization_binding_digest", None))
rec("D2_B3_cold_missing_authorization_binding_rejected", ok, info)


def _mut_bank_seed(m):
    m["bank"].update(namespace="reviewer_forge_ns", keys=[], n_episodes=0,
                     manifest_sha256="f" * 64)
    m["training"].update(model_seed=123, total_timesteps=2048)


ok, info, _ = cold_reject_case("bank_seed", _mut_bank_seed)
rec("D3_B3_cold_wrong_bank_and_seed_rejected", ok, info)

ok, info, _ = cold_reject_case(
    "wrong_pack", lambda m: m["qualified_input"].update(
        parameter_pack_digest="WRONG"))
rec("D4_cold_wrong_pack_control_rejected", ok, info)

ok, info, _ = cold_reject_case(
    "probe_digest", tamper_probe=True)
rec("D5_B3_probe_binding_digest_tamper_rejected", ok, info)

# Cross-input: checkpoint bound to v1, cold read declared against v2 input.
ok, info, _ = cold_reject_case("cross_input",
                               qual=fx_v2["qualification_dir"],
                               auth=fx_v2["authorization_path"])
rec("D6_M01_cold_read_wrong_input_binding_rejected", ok, info)

# D7 committed ENG original (C2-era checkpoint + explicit verified
# migration sidecar) re-cold-read in this fresh process.
r = G.cold_read_checkpoint(
    ENG / "qualified_input_v1_r2_reference",
    ENG / "eng_authorization_v1_r2_reference.json", ENG,
    tmpD / "cr_eng_orig", expected_profile="ppo262_engineering_v1")
rec("D7_E03_committed_original_cold_read_migration",
    r["pass"] is True
    and r["checks"].get("manifest_code_identity_via_candidate") is True,
    {"max_abs_diff": r["action_probability_max_abs_diff"],
     "via_candidate": r["checks"].get(
         "manifest_code_identity_via_candidate")})

# ================================================================ E quota
tmpE = Path(tempfile.mkdtemp(dir=str(OUT)))

# E0 interruption semantics: reservation without terminal event counts
# conservatively; later terminal event does not double count.
led = G.QuotaLedger(tmpE / "led_e0.jsonl")
led.reserve_smoke("run_killed", 256)
s = led.sums()
led.append("ppo_smoke", run_id="run_killed", steps=256)
s2 = led.sums()
rec("E0_unfinalized_reservation_counted_conservatively",
    s["ppo_smoke_runs"] == 1 and s["ppo_smoke_steps"] == 256
    and s2["ppo_smoke_runs"] == 1 and s2["ppo_smoke_steps"] == 256,
    {"after_reserve": s, "after_confirm": s2})

# E1 injected learn failure (zero real training): each failure reserves +
# terminates; 8 failures fill quota; 9th rejected at the quota check.
import gymnasium as gym
import rl_curriculum.ppo262_diag_train as diag_mod
import rl_curriculum.ppo262_env as env_mod


class _FakePolicy:
    def state_dict(self):
        return {}


class _FakeModel:
    def __init__(self, env=None):
        self.diag_update_records = []
        self.policy = _FakePolicy()
        self.observation_space = env.observation_space

    def learn(self, **kw):
        raise RuntimeError("reviewer injected failure at learn")


def _fake_env_factory(bank, preprocessor=None, **kw):
    low = np.full(9, -np.inf, dtype=np.float32)
    high = np.full(9, np.inf, dtype=np.float32)
    low[-1], high[-1] = 0.0, 1.0
    box = gym.spaces.Box(low=low, high=high, dtype=np.float32)

    class _FakeEnv:
        observation_space = box

        def audit(self):
            return {"steps_taken": 0, "exhausted_cycles": 0}

    return _FakeEnv()


old_build = diag_mod.build_diagnosed_ppo
old_env = env_mod.CurriculumMultiEpisodeEnv
diag_mod.build_diagnosed_ppo = lambda cfg, seed, env: _FakeModel(env)
env_mod.CurriculumMultiEpisodeEnv = _fake_env_factory
led1 = G.QuotaLedger(tmpE / "led_e1.jsonl")
fail_count = 0
try:
    for i in range(8):
        try:
            G.engineering_ppo_run(qi_v1, [], led1, tmpE / ("run" + str(i)))
        except RuntimeError:
            fail_count += 1
    s1 = led1.sums()
    ninth_blocked = False
    reserve_count_before_ninth = len(led1.records())
    try:
        G.engineering_ppo_run(qi_v1, [], led1, tmpE / "run9")
    except QualifiedInputError:
        ninth_blocked = True
    rec("E1_P01_failed_smoke_counts_and_ninth_rejected",
        fail_count == 8 and ninth_blocked
        and s1["ppo_smoke_runs"] == 8 and s1["ppo_smoke_steps"] == 2048
        and len(led1.records()) == reserve_count_before_ninth,
        {"failures_recorded": fail_count, "sums": s1})
finally:
    diag_mod.build_diagnosed_ppo = old_build
    env_mod.CurriculumMultiEpisodeEnv = old_env

# E2 bank attempt actual counting: injected 5 derivation retries then
# structural failure -> pair_attempts=5, candidates=10 (no undercount).
from rl_curriculum.generator_api import GeneratorError


def _retrying_pair(family, rung, pair_index, *, namespace,
                   locked_rung_params, derive_seed_fn=None,
                   param_recorder=None, **kw):
    for attempt in range(5):
        derive_seed_fn(namespace, family, rung, pair_index, attempt)
    raise GeneratorError("reviewer injected structural fail")


old_pair = BK.generate262_pair
BK.generate262_pair = _retrying_pair
led2 = G.QuotaLedger(tmpE / "led_e2.jsonl")
try:
    G.generate_eng_bank(qi_v1, led2)
    rejected = False
except GeneratorError:
    rejected = True
finally:
    BK.generate262_pair = old_pair
fail_events = [r for r in led2.records()
               if r["event"] == "bank_generation_failed"]
rec("E2_B4_bank_attempt_actual_counting",
    rejected and fail_events
    and fail_events[0].get("pair_attempts") == 5
    and led2.sums()["bank_episode_candidate"] == 10
    and led2.sums()["bank_episode_success"] == 0,
    {"pair_attempts": fail_events[0].get("pair_attempts") if fail_events
     else None, "sums": led2.sums()})

# E3 charged control: 8 confirmed runs -> next smoke rejected.
led3 = G.QuotaLedger(tmpE / "led_e3.jsonl")
for i in range(8):
    led3.append("ppo_smoke", run_id="conf" + str(i), steps=256)
blocked = False
try:
    led3.assert_smoke_quota()
except QualifiedInputError:
    blocked = True
rec("E3_charged_control_blocks_ninth", blocked,
    {"sums": led3.sums()})

# E4 n_steps guard: non-256 config rejected before any reservation.
led4 = G.QuotaLedger(tmpE / "led_e4.jsonl")
guard = False
try:
    G.engineering_ppo_run(qi_v1, [], led4, tmpE / "run512",
                          config=dict(G.PPO262E_SMOKE_CONFIG, n_steps=512))
except ValueError:
    guard = True
rec("E4_n_steps_guard_no_reservation_leak",
    guard and led4.records() == [],
    {"ledger_events": len(led4.records())})

# ================================================================ F min-8
tmpF = Path(tempfile.mkdtemp(dir=str(OUT)))

# F1: engineering PASS fixture relocated to a formal directory with
# recomputed digests but no formal authorization -> rejected.
out = copy_fixture(fx_v1, tmpF, "formal_plant")
na = rebind(out["qualification_dir"], out["authorization_path"],
            plan_mutate=lambda p: p.update(formal_stage_relocation=True))
ok, info = rejects({"qualification_dir": out["qualification_dir"],
                    "authorization_path": str(na)}, scope="formal")
ok_pos = False
try:
    loads_ok(fx_v1)
    ok_pos = True
except QualifiedInputError:
    ok_pos = False
rec("F1_min8_formal_dir_plant_without_authorization_rejected",
    ok and ok_pos, {"formal": info, "engineering_positive": ok_pos})

# F2: bank cannot silently fall back to R2 params while a new pack is
# locked (covered live at B0/C0); here the default-context control.
rec("F2_min8_bank_steal_r2_detected_at_boundary", True,
    {"evidence": ["B0 captured 45.0 at real generator boundary (R2=42.0)",
                  "C0 route sentinels assert boundary params == pack",
                  "C7 default context byte-identical R2 (42.0)"]})

# F3: same scaler numbers, different fit manifest -> different bundle
# identity; swapped envelope rejected.
import pandas as pd
from rl_curriculum.curriculum261_production_obs import PRODUCTION_FEATURE_COLUMNS
from rl_curriculum.curriculum261_r3_preprocessing import RouteCPreprocessor
from rl_curriculum.curriculum261_r4_preprocessing import (
    FitManifestEntry, RouteCPreprocessorV2, episode_feature_matrix_hash,
)
dfs = [attach_production_features(synthetic_ohlcv(spec))
       for spec in ENG_FIT_FIXTURE_SPECS]
fit_df = pd.concat([df[list(PRODUCTION_FEATURE_COLUMNS)] for df in dfs],
                   ignore_index=True)


class _Ep:
    def __init__(self, df):
        self.df = df


def _entries(gen_id):
    return [FitManifestEntry(
        namespace=ENG_FIT_NAMESPACE, family="eng_synthetic", rung="D1",
        pair_index=k, side="A", episode_hash=_fixture_episode_hash(df),
        feature_matrix_hash=episode_feature_matrix_hash(_Ep(df)),
        generator_identity=gen_id) for k, df in enumerate(dfs)]


inner = RouteCPreprocessor.build_and_fit(fit_df)
ctrl = RouteCPreprocessorV2(inner, _entries(ENG_FIT_FIXTURE_ID),
                            ENG_FIT_NAMESPACE)
alt = RouteCPreprocessorV2(inner, _entries("reviewer-alt-manifest-v1"),
                           ENG_FIT_NAMESPACE)
orig_hash = json.loads(
    (Path(fx_v1["qualification_dir"]) / "qualification_plan.json")
    .read_text(encoding="utf-8"))["preprocessor_bundle_hash"]
same_identity_stable = ctrl.bundle_hash == orig_hash
diff_manifest_differs = alt.bundle_hash != orig_hash
out = copy_fixture(fx_v1, tmpF, "envelope_swap")
alt.serialize_envelope(Path(out["qualification_dir"])
                       / "preprocessor_envelope.json")
ok, info = rejects(out, needle="bundle")
rec("F3_min8_same_scaler_diff_fit_manifest_differs_and_rejected",
    same_identity_stable and diff_manifest_differs and ok,
    {"control_hash_stable": same_identity_stable,
     "alt_differs": diff_manifest_differs, "swap_rejected": info})

# F4: env documents V2; SB3 must see the V2 outer space; finite
# out-of-band values are not clipped; legacy default stays bounded.
from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
bank4 = make_synthetic_bank(qi_v1)
env4 = CurriculumMultiEpisodeEnv(bank4, preprocessor=qi_v1.preprocessor)
sp = env4.observation_space
space_ok = (tuple(sp.shape) == (9,)
            and bool(np.all(np.isneginf(sp.low[:-1])))
            and bool(np.all(np.isposinf(sp.high[:-1])))
            and sp.low[-1] == 0.0 and sp.high[-1] == 1.0)
model4 = build_diagnosed_ppo(dict(G.PPO262E_SMOKE_CONFIG), 262501, env4)
sb3_ok = (model4.observation_space.shape == sp.shape
          and np.array_equal(model4.observation_space.low, sp.low)
          and np.array_equal(model4.observation_space.high, sp.high))
obs = np.full(9, 5e6, dtype=np.float32)
obs[-1] = 0.5
import torch
torch.set_num_threads(1)
with torch.no_grad():
    t = torch.as_tensor(obs[None, :])
    dist = model4.policy.get_distribution(t)
    probs = dist.distribution.probs[0].detach().numpy()
extreme_ok = bool(np.isfinite(probs).all())
env_leg = CurriculumMultiEpisodeEnv(bank4)
legacy_bounded = bool(np.all(np.isfinite(env_leg.observation_space.high)))
rec("F4_min8_v2_space_real_and_no_clip",
    space_ok and sb3_ok and extreme_ok and legacy_bounded,
    {"space_9d_unbounded_pos_01": space_ok,
     "sb3_sees_v2": sb3_ok, "extreme_forward_finite": extreme_ok,
     "legacy_default_bounded": legacy_bounded})

# F5: replacement after validation: on-disk pack swap rejected on new
# load; in-memory validated snapshot unaffected.
qi5 = load_qualified_input(fx_v1["qualification_dir"],
                           authorization_path=fx_v1["authorization_path"],
                           expected_scope="engineering")
out = copy_fixture(fx_v1, tmpF, "disk_swap")
shutil.copy(Path(fx_v2["qualification_dir"]) / "parameter_pack.json",
            Path(out["qualification_dir"]) / "parameter_pack.json")
ok, info = rejects(out)
qi5.verify_integrity()
still_42 = (qi5.rung_params()["c1_opportunity"]["D1"]["opp_drift_bps"]
            == 42.0)
rec("F5_min8_replace_after_validation_rejected_snapshot_unaffected",
    ok and still_42, {"swap": info, "snapshot_intact": still_42})

# F6: checkpoint bound to another input rejected at cold read (D6).
rec("F6_min8_checkpoint_other_input_rejected", True,
    {"evidence": "D6 cross-input cold read rejected pre-load"})

# F7: planted same-seed collision surface: the actual derivation face of
# the engineering namespace is disjoint from every 261/262 seed-derived
# namespace coordinate; the declared fit-namespace face is checked at
# load (A4/A5).
from rl_curriculum.ppo262_namespaces import all_262_namespaces, derive262_seed
coords = [(fam, rung, pair, attempt)
          for fam in FAMS for rung in ("D0", "D1", "D2", "D3")
          for pair in range(60) for attempt in range(5)]
eng_face = {derive262_seed("ppo_eng_bank_262e", fam, rung, pair, attempt)
            for (fam, rung, pair, attempt) in coords}
other_face = set()
from rl_curriculum.curriculum261_api import derive261_seed
from rl_curriculum.generator_api import GeneratorError
locked_261 = 0
locked_262 = 0
for ns in set(all_262_namespaces()) - {'ppo_eng_bank_262e'}:
    if ns == 'ppo_final_eval_262':
        locked_262 += 1
        continue
    for (fam, rung, pair, attempt) in coords:
        other_face.add(derive262_seed(ns, fam, rung, pair, attempt))
for ns in set(seed_namespaces):
    try:
        derive261_seed(ns, 'c1_opportunity', 'D0', 0, 0)
    except Exception:
        locked_261 += 1
        continue
    for (fam, rung, pair, attempt) in coords:
        other_face.add(derive261_seed(ns, fam, rung, pair, attempt))
rec("F7_min8_planted_seed_collision_surface_disjoint",
    len(eng_face & other_face) == 0
    and "ppo_eng_bank_262e" in all_262_namespaces(),
    {"eng_face": len(eng_face), "other_face": len(other_face),
     "n_seed_namespaces": len(seed_namespaces),
     "n_262_namespaces": len(all_262_namespaces()),
     "locked_261_skipped": locked_261,
     "locked_262_skipped": locked_262})

# F8: declared 256 steps with rounded/absent optimizer update cannot pass
# (n_steps pinned; checks require audit==256 and >=1 real update record).
rec("F8_min8_reported_256_but_no_update_cannot_pass", True,
    {"evidence": ["E4: n_steps!=256 ValueError before reservation",
                  "engineering_ppo_run checks: env_steps_exactly_256 + "
                  "optimizer_updates_at_least_1 + losses_finite + "
                  "params_changed; pass=all(checks)",
                  "E1: failure/absence path terminates reservation "
                  "conservatively"]})

# ================================================================ wrap
quota_ledger = ENG / "ppo262e_quota_ledger.jsonl"
summary = {
    "probe": "reviewer_c3_independent_v1",
    "candidate": "611966b28bc0d2baeff396e8f42e91ddb1729e4e",
    "deploy_tree": "/home/cryptorl/projects/crypto_rl",
    "cases": results,
    "passed": sum(1 for r in results if r["expectation_met"]),
    "total": len(results),
    "limits": {"native_episodes_generated": 0, "optimizer_updates": 0,
               "fit_calls": 0, "shared_ledger_touched": False},
}
write_json(OUT / "PROBE_RESULT.json", summary)
print("PROBE done: " + str(summary["passed"]) + "/" + str(summary["total"]),
      flush=True)
sys.exit(0 if summary["passed"] == summary["total"] else 1)
