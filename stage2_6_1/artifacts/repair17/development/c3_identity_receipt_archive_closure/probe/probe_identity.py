#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""WP1 前置探针:健康件四层哈希关系 + 权威 digest 复算 + p52 身份体对照。
只在 WSL 部署树(有权威模块)运行;只读,不写任何源目录。"""
import json, sys
from pathlib import Path

sys.path.insert(0, "/home/cryptorl/projects/crypto_rl/src")
from rl_curriculum.curriculum261_generation_envelope import (
    canonical_json, stable_digest, _digest_body,
    ENVELOPE_DIGEST_PREFIX, CALL_ENVELOPE_DIGEST_PREFIX)

BASE = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development")
ES = BASE / "c3_evidence_generation_slice" / "engineering_slice"
P52_ENV = BASE / "blocker_diagnosis" / "runs" / "20260906T134324Z_1475" / \
    "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"

out = {}

def recompute(env, prefix):
    body = _digest_body(env)
    return stable_digest(body, prefix), body

# --- 1. 八坐标健康件 ---
per_pair = {}
for rung in ("D0","D1","D2","D3"):
    for idx in (0,1):
        doc = json.loads((ES / "pairs" / f"{rung}_p{idx}.json").read_text(encoding="utf-8"))
        pr = doc["pair_record"]
        log = pr["attempt_log"]
        sel = log["selected_attempt"]
        envs = doc["attempt_envelopes"]
        top = doc["episode_hashes"]
        outh = log["output_episode_hashes"]
        ev_eps = {e["side"]: e for e in doc["evaluation"]["episodes"]}
        row = {
            "selected": sel, "n_env": len(envs), "n_attempts": len(log["attempts"]),
            "eval_keys": sorted(doc["evaluation"].keys()),
            "episode_keys": sorted(ev_eps["A"].keys()),
        }
        # 四层哈希实测
        four = {}
        for side in ("A","B"):
            four[side] = {
                "env_selected": envs[sel]["event_table"][side]["episode_content_hash"],
                "log_output": outh[side],
                "top": top[side],
                "eval": ev_eps[side]["episode_hash"],
            }
            row[f"four_layer_closed_{side}"] = len(set(four[side].values())) == 1
        row["four"] = four
        # digest 复算(每条 envelope)
        dig = []
        for i, e in enumerate(envs):
            calc, _ = recompute(e, ENVELOPE_DIGEST_PREFIX)
            dig.append({"i": i, "saved": e.get("digest"), "calc": calc,
                        "match": calc == e.get("digest")})
        row["digest_recompute_all_match"] = all(d["match"] for d in dig)
        row["digests"] = dig
        # envelope 键清单(首条)
        row["env_keys"] = sorted(envs[0].keys())
        row["log_keys"] = sorted(log.keys())
        row["attempt_keys"] = sorted(log["attempts"][0].keys())
        row["pair_record_keys"] = sorted(pr.keys())
        # base_params vs recipe rung_params 的关系(键集合示例)
        row["base_params_keys_A"] = sorted(envs[0]["base_params"]["A"].keys())
        row["generator_keys"] = sorted(envs[0]["generator"].keys())
        per_pair[f"{rung}_p{idx}"] = row
out["pairs"] = per_pair

# --- 2. p52 原件 vs 负例件 ---
orig = json.loads(P52_ENV.read_text(encoding="utf-8"))
neg = json.loads((ES / "p52_negative.json").read_text(encoding="utf-8"))
oc = orig["call_envelope"]
cdig_calc, cbody = recompute(oc, CALL_ENVELOPE_DIGEST_PREFIX)
out["p52_call"] = {
    "saved_digest": oc.get("digest"), "calc_digest": cdig_calc,
    "match": cdig_calc == oc.get("digest"),
    "call_keys": sorted(oc.keys()),
}
oenvs, nenvs = orig["attempt_envelopes"], neg["attempt_envelopes"]
prows = []
for i, (oe, ne) in enumerate(zip(oenvs, nenvs)):
    ocalc, obody = recompute(oe, ENVELOPE_DIGEST_PREFIX)
    ncalc, nbody = recompute(ne, ENVELOPE_DIGEST_PREFIX)
    # 身份体逐字段差异(剔除 runtime 后)
    diffs = []
    for k in sorted(set(obody) | set(nbody)):
        if obody.get(k) != nbody.get(k):
            diffs.append(k)
    prows.append({
        "i": i,
        "orig_digest_match": ocalc == oe.get("digest"),
        "neg_digest_match": ncalc == ne.get("digest"),
        "saved_digest_equal": oe.get("digest") == ne.get("digest"),
        "identity_body_equal": canonical_json(obody) == canonical_json(nbody),
        "diff_fields": diffs,
    })
out["p52_attempts"] = prows
out["p52_neg_keys"] = sorted(neg.keys())
out["p52_orig_top_keys"] = sorted(orig.keys())

# --- 3. recipe 参数身份 ---
recipe = json.loads((ES / "recipe.json").read_text(encoding="utf-8"))
out["recipe_keys"] = sorted(recipe.keys())
out["recipe_generator_keys"] = sorted(recipe["generator_identity"].keys())
out["recipe_rung_params_D0"] = recipe["rung_params"]["D0"]

print(json.dumps(out, ensure_ascii=False, indent=1, default=str))
