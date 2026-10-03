#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFAB v1 — A1/A2/B 计划身份与预算语义全量核验(只读)。

输入: 本准备目录 plans/ 下三份真实构建器产物 + 旧 R4 草案 + Commit A。
输出: evidence/plan_identity/report.json。

核验面:
 1. 三份快照 code_freeze_sha == Commit A;
 2. research_plan_digest 独立复算(本脚本自实现 canonical-json sha256)
    == 存储值;并用部署树公共函数(同源)二次复算;
 3. code_identity 全部成员 vs Commit A git blobs(CR 规范化 sha256);
 4. A1/A2 停止边界×模型更新授权语义 + 分项预算 vs R4 已验值;
 5. B 草案参数(K=11/P0/margin/alpha/r_analysis/500/8/1e6);
 6. 旧草案差异说明(逐成员)+ 旧 digest 复算与拒绝对照;
 7. 身份分层:commit sha / git_tree_digest / 三 qbpl digest 互不相等,
    qualification_plan_r17 全部署树不存在。
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEPLOY = Path("/home/cryptorl/projects/crypto_rl")
REPO = Path("/mnt/f/trading/freqai-rl-audit")
PREP = REPO / "stage2_6_1/artifacts/repair17/development" \
    "/formal_freeze_binding_v1"
COMMIT_A = "de81aba2b3cdcc2c0febe2b3c439027496ab9d05"

R4_BUDGET = {
    "A1": {"stop_after": "qualify",
           "typical": 28798, "upper": 113030, "v2": 9, "mlp": 85,
           "learn": 1, "rollout": 256, "opt": 40, "val": 50,
           "check": 10, "save": 1, "model_update": False},
    "A2": {"stop_after": "verify-formal-logs",
           "typical": 28944, "upper": 113176, "v2": 10, "mlp": 85,
           "learn": 2, "rollout": 512, "opt": 80, "val": 100,
           "check": 20, "save": 2, "model_update": True},
}


def _canon(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _digest_independent(payload: dict) -> str:
    body = {k: v for k, v in payload.items()
            if k not in ("research_plan_digest", "locked_utc")}
    return "qbpl-" + hashlib.sha256(
        _canon(body).encode("utf-8")).hexdigest()


def _git(*args: str) -> bytes:
    p = subprocess.run(["git", "-C", str(REPO), *args],
                       capture_output=True, timeout=120)
    if p.returncode != 0:
        raise SystemExit("git failed: " + " ".join(args[:2]))
    return p.stdout


def _member_sha_at_commit(module: str) -> str:
    blob = _git("show", f"{COMMIT_A}:stage2_6_1/src/rl_curriculum/{module}")
    return hashlib.sha256(blob.replace(b"\r", b"")).hexdigest()


def main() -> int:
    sys.path.insert(0, str(DEPLOY / "src"))
    from rl_curriculum.curriculum261_qprod_plan import research_plan_digest

    report: dict = {
        "format": "cur261-ffab-plan-identity-v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "commit_a": COMMIT_A,
        "plans": {}, "old_drafts": {}, "identity_layers": {},
        "checks": [],
    }

    def check(name: str, ok: bool, detail=None) -> None:
        report["checks"].append({"name": name, "pass": bool(ok),
                                 "detail": detail if detail is not None
                                 else {}})

    plans = {}
    for tag, rel in (
            ("A1", "plans/A1/qprod_formal_level_a_draft_plan.json"),
            ("A2", "plans/A2/qprod_formal_level_a_draft_plan.json"),
            ("B", "plans/B_UNAPPROVED/qprod_formal_level_b_draft_plan.json")):
        doc = json.loads((PREP / rel).read_text(encoding="utf-8"))
        plans[tag] = doc
        payload = doc["payload"]
        entry = {
            "file": rel,
            "stored_digest": doc["research_plan_digest"],
            "code_freeze_sha": doc["code_freeze_sha"],
            "status": doc["status"],
            "independent_recompute": _digest_independent(payload),
            "common_function_recompute": research_plan_digest(payload),
            "code_identity_members": len(payload["code_identity"]),
            "identity_mismatch_vs_commit_a": [],
        }
        check(f"{tag}.code_freeze_sha==CommitA",
              doc["code_freeze_sha"] == COMMIT_A,
              {"got": doc["code_freeze_sha"]})
        check(f"{tag}.digest.independent",
              entry["independent_recompute"] == doc["research_plan_digest"])
        check(f"{tag}.digest.common_function",
              entry["common_function_recompute"]
              == doc["research_plan_digest"])
        for module, sha in sorted(payload["code_identity"].items()):
            want = _member_sha_at_commit(module)
            if want != sha:
                entry["identity_mismatch_vs_commit_a"].append(
                    {module: {"plan": sha[:16], "commit_a": want[:16]}})
        check(f"{tag}.code_identity.all_members==CommitA_blobs",
              not entry["identity_mismatch_vs_commit_a"],
              entry["identity_mismatch_vs_commit_a"])
        report["plans"][tag] = entry

    # ---- A1/A2 语义与预算 ----
    for tag in ("A1", "A2"):
        p = plans[tag]["payload"]
        b = p["run_scope"]["budget"]
        rules = p["rules"]
        exp = R4_BUDGET[tag]
        mism = []
        if b["stop_after"] != exp["stop_after"]:
            mism.append("stop_after")
        for key, want in (("generation_episodes_typical", exp["typical"]),
                          ("generation_episodes_worst_upper", exp["upper"]),
                          ("authorization_cap_generation_episodes",
                           exp["upper"]),
                          ("v2_preprocessor_fits", exp["v2"]),
                          ("supervised_mlp_fits", exp["mlp"]),
                          ("ppo_learn_calls", exp["learn"]),
                          ("ppo_rollout_env_steps", exp["rollout"]),
                          ("ppo_optimizer_steps_upper", exp["opt"]),
                          ("ppo_validation_env_steps", exp["val"]),
                          ("ppo_check_env_interactions_bound",
                           exp["check"]),
                          ("model_save_load_pairs", exp["save"]),
                          ("mc_events_total", 1000000),
                          ("bootstrap_resamples_upper", 7500000),
                          ("global_k_null_draws_tier1", 50000),
                          ("global_k_null_draws_tier2_upper", 200000)):
            if b[key] != want:
                mism.append({key: {"got": b[key], "want": want}})
        check(f"{tag}.budget_face==R4_verified_values", not mism, mism)
        check(f"{tag}.model_update_authorized=={exp['model_update']}",
              rules["model_update_authorized"] is exp["model_update"])
        check(f"{tag}.post_qualification_smoke_authorized"
              f"=={exp['model_update']}",
              rules["post_qualification_smoke_authorized"]
              is exp["model_update"])
        check(f"{tag}.embedded_preflight_smoke.authorized==True",
              p["run_scope"]["embedded_preflight_smoke"]["authorized"]
              is True)

    # 互斥候选:同 A、digest 不同、quota 不等
    check("A1_A2.same_commit_a",
          plans["A1"]["code_freeze_sha"]
          == plans["A2"]["code_freeze_sha"] == COMMIT_A)
    check("A1_A2.digest_distinct",
          plans["A1"]["research_plan_digest"]
          != plans["A2"]["research_plan_digest"])
    q1, q2 = (plans["A1"]["payload"]["quota"],
              plans["A2"]["payload"]["quota"])
    check("A1_A2.quota_faces_distinct", q1 != q2)

    # ---- B 草案参数 ----
    br = plans["B"]["payload"]["rules"]
    bq = br.get("audit_budgets", {})
    bexp = {"p0_fixed_reference": 0.950431552876822, "margin": 0.003,
            "alpha": 0.05, "r_analysis": 1.5, "planned_k": 11,
            "blocks": 500, "mc": 1000000, "episodes_per_block": 8}
    bmis = []
    if br.get("p0_fixed_reference") != bexp["p0_fixed_reference"]:
        bmis.append("p0")
    if br.get("margin") != bexp["margin"]:
        bmis.append("margin")
    if br.get("alpha") != bexp["alpha"]:
        bmis.append("alpha")
    if br.get("r_analysis") != bexp["r_analysis"]:
        bmis.append("r_analysis")
    if br.get("planned_k") != bexp["planned_k"]:
        bmis.append("planned_k")
    if bq.get("blocks_per_corpus") != bexp["blocks"]:
        bmis.append("blocks_per_corpus")
    if bq.get("mc_events") != bexp["mc"]:
        bmis.append("mc_events")
    if bq.get("episodes_per_block") != bexp["episodes_per_block"]:
        bmis.append("episodes_per_block")
    check("B.rules==frozen_R4_semantics", not bmis, bmis)
    check("B.status==DRAFT_PENDING_USER_APPROVAL",
          plans["B"]["status"] == "DRAFT_PENDING_USER_APPROVAL")
    cm = plans["B"]["payload"].get("coordinate_manifest") or []
    check("B.coordinate_manifest.k==11", len(cm) == 11,
          {"k": len(cm)})

    # ---- 旧草案差异与拒绝对照 ----
    old_dir = REPO / "stage2_6_1/artifacts/repair17/development" \
        "/formal_launch_prep_v1/drafts"
    for lv, newtag in (("a", "A1"), ("b", "B")):
        old = json.loads(
            (old_dir / f"qprod_formal_level_{lv}_draft_plan.json")
            .read_text(encoding="utf-8"))
        oldp = old["payload"]
        newci = plans[newtag]["payload"]["code_identity"]
        oldci = oldp["code_identity"]
        member_diff = []
        for m in sorted(set(oldci) | set(newci)):
            if oldci.get(m) != newci.get(m):
                member_diff.append({
                    "module": m,
                    "old": (oldci.get(m) or "MISSING")[:16],
                    "new": (newci.get(m) or "MISSING")[:16],
                    "new_matches_commit_a":
                        newci.get(m) == _member_sha_at_commit(m)})
        recomputed = _digest_independent(oldp)
        report["old_drafts"][lv] = {
            "stored_digest": old["research_plan_digest"],
            "recomputed_from_old_payload": recomputed,
            "recompute_matches_stored":
                recomputed == old["research_plan_digest"],
            "code_freeze_sha": old.get("code_freeze_sha"),
            "member_diff_old_vs_new": member_diff,
            "old_identity_matches_commit_a": not member_diff,
        }
        check(f"old_{lv}.digest_reproduces_from_old_identity",
              recomputed == old["research_plan_digest"])
        check(f"old_{lv}.identity_rejected_for_commit_a"
              f"(_members_differ_or_freeze_empty)",
              bool(member_diff) and not old.get("code_freeze_sha"))
        check(f"old_{lv}.stored_digest!=new_{newtag}_digest",
              old["research_plan_digest"]
              != plans[newtag]["research_plan_digest"])

    # ---- 身份分层 ----
    commit_sha = _git("rev-parse", COMMIT_A).decode().strip()
    tree_sha = _git("rev-parse", COMMIT_A + "^{tree}").decode().strip()
    from rl_curriculum.curriculum261_r17_admission_substance import (
        git_tree_digest,
    )
    adm_tree_digest = git_tree_digest(REPO, COMMIT_A)
    digests = {
        "git_commit_sha": commit_sha,
        "git_tree_sha": tree_sha,
        "admission_git_tree_digest": adm_tree_digest,
        "qbpl_A1": plans["A1"]["research_plan_digest"],
        "qbpl_A2": plans["A2"]["research_plan_digest"],
        "qbpl_B": plans["B"]["research_plan_digest"],
    }
    vals = [commit_sha, tree_sha, digests["qbpl_A1"],
            digests["qbpl_A2"], digests["qbpl_B"]]
    check("identity_layers.four_identity_classes_distinct",
          len(set(vals)) == len(vals), digests)
    # admission plan_digest_method=git_tree_digest 的定义即 Commit A 的
    # git tree 对象 id(唯一接受口径)——与 tree sha 相等是构造事实,
    # 不是混用;混用防线 = 它不得等于 commit sha/qbpl 摘要,且
    # admission 侧只接受该口径、qbpl 校验只接受 qbpl 前缀摘要。
    check("admission_tree_digest==commit_a_tree_sha(by_definition)",
          adm_tree_digest == tree_sha)
    check("admission_tree_digest.not_commit_sha_and_not_any_qbpl",
          adm_tree_digest not in (commit_sha, digests["qbpl_A1"],
                                  digests["qbpl_A2"], digests["qbpl_B"]))
    # qualification_plan_r17 是未来链内 lock-plan(校准后)产物:
    # 正式受保护状态根内必须不存在;未来正式根未登记(配置缺失)。
    # 工程彩排根(_rt 面)的历史件如实分类记录,不冒充正式件,
    # 也不得用作"缺失字段"补位。
    formal_hits, engineering_hits = [], []
    for p in (DEPLOY / "artifacts").rglob("qualification_plan_r17.json"):
        rel = str(p.relative_to(DEPLOY))
        if any(f"route_c_stage2_6_1_repair{n}/" in rel + "/"
               for n in (17, 18, 19)):
            formal_hits.append(rel)
        else:
            engineering_hits.append({
                "path": rel,
                "sha256": hashlib.sha256(
                    p.read_bytes()).hexdigest(),
                "classified": ("historical engineering rehearsal artifact"
                               "(_rt preplan temp face;非正式状态根)" )})
    check("qualification_plan_r17.absent_in_formal_state_roots",
          not formal_hits, {"formal_hits": formal_hits})
    check("no_future_formal_roots_registered(deploy_config_absent)",
          not (DEPLOY / "qprod_deploy_config.json").is_file())
    report["qualification_plan_hits"] = {
        "formal": formal_hits,
        "engineering_rehearsal": engineering_hits}
    report["identity_layers"] = digests

    report["pass"] = all(c["pass"] for c in report["checks"])
    out = PREP / "evidence/plan_identity/report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1,
                              sort_keys=True) + "\n", encoding="utf-8")
    for c in report["checks"]:
        print(("PASS " if c["pass"] else "FAIL ") + c["name"])
    print("OVERALL", report["pass"])
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
