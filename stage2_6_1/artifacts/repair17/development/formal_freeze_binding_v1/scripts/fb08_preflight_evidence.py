#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""FFAB v1 — FB08 真实入口/只读预检/非激活分类/隔离正反例证据。

全部只读或隔离沙盒;零正式副作用(不签发、不 launch、不创建生产
配置;生产侧唯一动作 = 对真实部署根执行只读 preflight)。

输出: evidence/preflight_fb08/{summary.json, *.json}
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEPLOY = Path("/home/cryptorl/projects/crypto_rl")
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"
REPO = Path("/mnt/f/trading/freqai-rl-audit")
PREP = REPO / "stage2_6_1/artifacts/repair17/development" \
    "/formal_freeze_binding_v1"
COMMIT_A = "de81aba2b3cdcc2c0febe2b3c439027496ab9d05"
ENTRY = "stage2_6_1_runner/qprod_formal_level_a_entry.py"
OUT = PREP / "evidence/preflight_fb08"

WRONG_SHA = "0" * 39 + "1"  # 全零/全一之外的 40 位伪 SHA(真实形态)


def run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True,
                          cwd=str(DEPLOY), timeout=300, **kw)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    summary: dict = {
        "format": "cur261-ffab-fb08-preflight-v1",
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                       time.gmtime()),
        "cases": [],
    }
    args_tail: list[str] = ["--help"]

    def case(name: str, proc: subprocess.CompletedProcess,
             expect_rc: int, extra: dict | None = None, *,
             argv_tail: list[str] | None = None) -> dict:
        row = {"name": name,
               "argv_tail": " ".join(argv_tail or args_tail),
               "rc": proc.returncode,
               "stdout_head": (proc.stdout or "")[:600],
               "stderr_head": (proc.stderr or "")[:300],
               "rc_as_expected": proc.returncode == expect_rc}
        if extra:
            row.update(extra)
        summary["cases"].append(row)
        return row

    # ---- 1. parser/--help 对拍 --------------------------------------
    help_all = run([PY, ENTRY, "--help"])
    help_pre = run([PY, ENTRY, "preflight", "--help"])
    help_draft = run([PY, ENTRY, "draft-plan", "--help"])
    (OUT / "help_entry.txt").write_text(help_all.stdout, encoding="utf-8")
    (OUT / "help_preflight.txt").write_text(help_pre.stdout,
                                            encoding="utf-8")
    (OUT / "help_draft_plan.txt").write_text(help_draft.stdout,
                                             encoding="utf-8")
    pre_flags = [ln.strip().split()[0] for ln in
                 help_pre.stdout.splitlines() if ln.startswith("  --")]
    case("parser.preflight_flags_no_model_update", help_pre, 0, {
        "preflight_flags": pre_flags,
        "model_update_absent": not any(
            "model-update" in f for f in pre_flags),
        "draft_plan_flags": [ln.strip().split()[0] for ln in
                             help_draft.stdout.splitlines()
                             if ln.startswith("  --")],
    })
    summary["cases"][-1]["pass"] = (
        summary["cases"][-1]["rc_as_expected"]
        and summary["cases"][-1]["model_update_absent"]
        and "--model-update" in help_draft.stdout)

    # ---- 2. 错组合拒绝(rc=2,零写) --------------------------------
    args_tail = ["draft-plan", "--prep-dir", "/tmp/ffab_must_not_exist_a2",
                 "--code-freeze-sha", COMMIT_A,
                 "--stop-after", "verify-formal-logs"]
    c1 = case("wrongcombo.full_chain_without_model_update",
              run([PY, ENTRY] + args_tail), 2)
    c1["pass"] = c1["rc_as_expected"] and not Path(
        "/tmp/ffab_must_not_exist_a2").exists()
    args_tail = ["draft-plan", "--prep-dir", "/tmp/ffab_must_not_exist_a1",
                 "--code-freeze-sha", COMMIT_A,
                 "--stop-after", "qualify", "--model-update"]
    c2 = case("wrongcombo.qualify_with_model_update",
              run([PY, ENTRY] + args_tail), 2)
    c2["pass"] = c2["rc_as_expected"] and not Path(
        "/tmp/ffab_must_not_exist_a1").exists()

    # ---- 3. 生产真实部署根只读预检(预期非激活) --------------------
    args_tail = ["preflight", "--deploy-root", str(DEPLOY),
                 "--code-freeze-sha", COMMIT_A, "--stop-after", "qualify"]
    real = run([PY, ENTRY] + args_tail)
    (OUT / "preflight_real_deploy.stdout.json").write_text(
        real.stdout, encoding="utf-8")
    try:
        rep = json.loads(real.stdout)
    except ValueError:
        rep = {}
    prod = case("preflight.real_deploy_root_not_activated", real, 1, {
        "status": rep.get("status"),
        "deployment_ok": rep.get("deployment_ok"),
        "deployment_note": rep.get("deployment_note"),
        "findings": rep.get("findings"),
        "business_leaf_calls": rep.get("business_leaf_calls"),
        "plan_digest": rep.get("plan_digest"),
    })
    prod["pass"] = (
        prod["rc_as_expected"]
        and rep.get("status") == "FINDINGS_PRESENT"
        and rep.get("deployment_ok") is False
        and rep.get("business_leaf_calls") == 0
        and any("qprod_deploy_config.json" in f
                for f in rep.get("findings", [])))
    # 预检前后部署根零新增(排除已有目录/时间戳比较:记录目录清单)
    prod["deploy_root_entries_after"] = sorted(
        p.name for p in DEPLOY.iterdir())

    # ---- 4. 错 Commit A 反例(同根不同 SHA → 不同计划身份) --------
    args_tail = ["preflight", "--deploy-root", str(DEPLOY),
                 "--code-freeze-sha", WRONG_SHA, "--stop-after", "qualify"]
    wrong = run([PY, ENTRY] + args_tail)
    wrep = json.loads(wrong.stdout) if wrong.stdout.strip() else {}
    wc = case("preflight.wrong_commit_sha_yields_different_plan_digest",
              wrong, 1, {"plan_digest": wrep.get("plan_digest")})
    wc["pass"] = (wrep.get("plan_digest")
                  and wrep.get("plan_digest") != rep.get("plan_digest"))
    (OUT / "preflight_wrong_sha.stdout.json").write_text(
        wrong.stdout, encoding="utf-8")

    # ---- 5. 隔离沙盒正例(formal_ready + admission 尾形) ----------
    sandbox = PREP / "sandbox_fb08"
    if sandbox.exists():
        shutil.rmtree(sandbox)
    deploy = sandbox / "deploy"
    art = deploy / "artifacts/route_c_stage2_6_1_repair17/artifacts"
    state = deploy / "artifacts/route_c_stage2_6_1_repair17/state"
    authority = deploy / "authority"
    art.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    authority.mkdir(parents=True, exist_ok=True)
    (deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1",
        "mode": "formal_ready",
        "note": "TEST-ONLY isolated sandbox(FFAB FB08 正例;非生产;"
                "位于准备目录,零正式授权)",
        "formal_roots": {
            "qprod_a_formal_v1": {
                "artifact_root": str(art),
                "state_root": str(state),
                "authority_dir": str(authority),
            },
        },
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    args_tail = ["preflight", "--deploy-root", str(deploy),
                 "--code-freeze-sha", COMMIT_A, "--stop-after", "qualify"]
    pos = run([PY, ENTRY] + args_tail)
    (OUT / "preflight_sandbox_positive.stdout.json").write_text(
        pos.stdout, encoding="utf-8")
    prep_rep = json.loads(pos.stdout) if pos.stdout.strip() else {}
    pc = case("preflight.sandbox_positive_prepared", pos, 0, {
        "status": prep_rep.get("status"),
        "deployment_ok": prep_rep.get("deployment_ok"),
        "admission_shape_ok": prep_rep.get("admission_shape_ok"),
        "admission_present": prep_rep.get("admission_present"),
        "plan_digest": prep_rep.get("plan_digest"),
        "sandbox_deploy_root": str(deploy),
        "note": "隔离 TEST 正例:根形态/路径映射/计划身份成立;"
                "不冒充生产 ready;admission_present=false 如实"
                "(未签发,签发在未来授权轮)",
    })
    pc["pass"] = (
        pc["rc_as_expected"]
        and prep_rep.get("status") == "PREPARED_PENDING_USER_APPROVAL"
        and prep_rep.get("deployment_ok") is True
        and prep_rep.get("admission_shape_ok") is True
        and prep_rep.get("admission_present") is False)
    # 沙盒正例与 A1 草案同停止口径 → 计划摘要一致(构建器确定性)
    a1 = json.loads((PREP / "plans/A1/qprod_formal_level_a_draft_plan.json")
                    .read_text(encoding="utf-8"))
    summary["sandbox_plan_digest_matches_A1_draft"] = (
        prep_rep.get("plan_digest") == a1["research_plan_digest"])

    # ---- 6. 错根反例(尾形不符) ------------------------------------
    bad_deploy = sandbox / "deploy_badshape"
    bad_state = bad_deploy / "artifacts/plain_state_root/state"
    bad_art = bad_deploy / "artifacts/plain_state_root/artifacts"
    bad_auth = bad_deploy / "authority"
    bad_art.mkdir(parents=True, exist_ok=True)
    bad_state.mkdir(parents=True, exist_ok=True)
    bad_auth.mkdir(parents=True, exist_ok=True)
    (bad_deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
        "note": "TEST-ONLY 反例:state root 不满足 r17 admission 尾形",
        "formal_roots": {"qprod_a_formal_v1": {
            "artifact_root": str(bad_art), "state_root": str(bad_state),
            "authority_dir": str(bad_auth)}},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    args_tail = ["preflight", "--deploy-root", str(bad_deploy),
                 "--code-freeze-sha", COMMIT_A, "--stop-after", "qualify"]
    neg = run([PY, ENTRY] + args_tail)
    (OUT / "preflight_sandbox_badshape.stdout.json").write_text(
        neg.stdout, encoding="utf-8")
    nrep = json.loads(neg.stdout) if neg.stdout.strip() else {}
    nc = case("preflight.sandbox_wrong_state_tail_shape_rejected",
              neg, 1, {
                  "status": nrep.get("status"),
                  "admission_shape_ok": nrep.get("admission_shape_ok"),
                  "findings": nrep.get("findings")})
    nc["pass"] = (nrep.get("status") == "FINDINGS_PRESENT"
                  and nrep.get("admission_shape_ok") is False)

    # ---- 7. 旧状态反例(state 内预置 run-plan → 非新鲜拒绝) ------
    stale_deploy = sandbox / "deploy_stale"
    s_art = stale_deploy / "artifacts/route_c_stage2_6_1_repair17/artifacts"
    s_state = stale_deploy / "artifacts/route_c_stage2_6_1_repair17/state"
    s_auth = stale_deploy / "authority"
    s_art.mkdir(parents=True, exist_ok=True)
    s_state.mkdir(parents=True, exist_ok=True)
    s_auth.mkdir(parents=True, exist_ok=True)
    (s_state / "qprod_research_plan.json").write_text(
        '{"format": "TEST-ONLY stale placeholder"}', encoding="utf-8")
    (stale_deploy / "qprod_deploy_config.json").write_text(json.dumps({
        "format": "cur261-qprod-deploy-config-v1", "mode": "formal_ready",
        "note": "TEST-ONLY 反例:state 内预置旧 run-plan(非新鲜)",
        "formal_roots": {"qprod_a_formal_v1": {
            "artifact_root": str(s_art), "state_root": str(s_state),
            "authority_dir": str(s_auth)}},
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    args_tail = ["preflight", "--deploy-root", str(stale_deploy),
                 "--code-freeze-sha", COMMIT_A, "--stop-after", "qualify"]
    st = run([PY, ENTRY] + args_tail)
    (OUT / "preflight_sandbox_stale.stdout.json").write_text(
        st.stdout, encoding="utf-8")
    srep = json.loads(st.stdout) if st.stdout.strip() else {}
    sc = case("preflight.sandbox_stale_state_rejected", st, 1, {
        "status": srep.get("status"),
        "stale_state_findings": srep.get("stale_state_findings")})
    sc["pass"] = (srep.get("status") == "FINDINGS_PRESENT"
                  and any("qprod_research_plan.json" in f for f in
                          (srep.get("findings") or [])))

    summary["all_pass"] = (
        all(c.get("pass") for c in summary["cases"])
        and summary["sandbox_plan_digest_matches_A1_draft"])
    (OUT / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True)
        + "\n", encoding="utf-8")
    for c in summary["cases"]:
        print(("PASS " if c.get("pass") else "FAIL ") + c["name"])
    print("sandbox_plan_digest_matches_A1_draft",
          summary["sandbox_plan_digest_matches_A1_draft"])
    print("OVERALL", summary["all_pass"])
    return 0 if summary["all_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
