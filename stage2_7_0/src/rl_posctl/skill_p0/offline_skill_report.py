# -*- coding: utf-8 -*-
"""离线技能验收入口 v2(纯数据;manifest 驱动)。

v2(2026-10-16 审查方五组合并修复):
- 预期身份全部来自**固定 manifest**(已验数值;禁止现算
  SHA 当 expected);空集/重复 tier/未知 model/deadbeef
  checkpoint 均 invalid;
- 规范来源=本机实核(course_contract.local_source_binding),
  不冒充旧 candidate;
- raw 逐 model 完整性:pair0–3×variant0/1×step0–63 精确
  集恰 512 行、末步终止、经济字段有限(非 max(step)+1);
- 覆盖按 model 分列,跨镜像/checkpoint 去重基础 pair,
  统计市场/账户状态实际覆盖(无门≠不统计);
- rc:0 pass/1 技能 fail(有效证据)/3 invalid(非零,报告
  仍落盘);独占输出,拒绝覆盖,零删除零重试。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sys
import time
import traceback
from pathlib import Path

from rl_posctl.skill_p0 import course_contract as cc

RC_PASS, RC_FAIL, RC_INVALID = 0, 1, 3
W_FLAT = 0.10  # 账户桶宽(=契约带)

# 受信约束:包内 trusted_manifests.json(同目录,__file__ 定位)
# 生产 CLI 不接受信任表路径/信任 SHA/跳过审批参数;
# 测试注入仅经 main(trusted_entries=...) 内部接口。
TRUSTED_FILE_NAME = "trusted_manifests.json"
GOLDEN_SHA = "a93397117c461be2d81f94a315d2cb46c6971f4f6989528ebfd40253e75e3210"  # noqa: E501  实测(manifest_v1.json)
MANIFEST_SCHEMA_C1 = "MANIFEST_C1_V1"


def _load_trusted_entries(trusted_path=None):
    p = (Path(trusted_path) if trusted_path else
         Path(__file__).resolve().parent / TRUSTED_FILE_NAME)
    if not p.is_file():
        raise cc.ContractError(
            "trusted table missing: %s (fail-closed, no "
            "fallback)" % p)
    try:
        t = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise cc.ContractError(
            "trusted table unreadable/corrupt: %r "
            "(fail-closed)" % exc)
    if (not isinstance(t, dict)
            or t.get("schema") != "TRUSTED_MANIFESTS_V1"
            or not isinstance(t.get("entries"), list)
            or not t["entries"]):
        raise cc.ContractError("trusted table bad structure")
    out, seen = [], set()
    for e in t["entries"]:
        if not isinstance(e, dict):
            raise cc.ContractError(
                "trusted entry not object: %r" % (e,))
        sha = e.get("sha256")
        if not (isinstance(sha, str) and len(sha) == 64
                and all(c in "0123456789abcdef"
                        for c in sha)):
            raise cc.ContractError(
                "trusted entry bad sha %r" % sha)
        if sha in seen:
            raise cc.ContractError(
                "trusted table duplicate sha %s" % sha)
        seen.add(sha)
        for k in ("kind", "course_id"):
            v = e.get(k)
            if not (isinstance(v, str) and v.strip()):
                raise cc.ContractError(
                    "trusted entry %r missing/empty %s"
                    % (sha[:8], k))
        ap = e.get("approved_by")
        if (not isinstance(ap, dict) or len(ap) < 2
                or not isinstance(ap.get("channel"),
                                  str)
                or not ap["channel"].strip()
                or not all(
                    isinstance(v, str) and v.strip()
                    for v in ap.values())):
            raise cc.ContractError(
                "trusted entry %r approved_by missing/"
                "bad structure (need dict>=2 keys with "
                "channel + evidence; non-empty text != "
                "authenticity — 独立审核负责真实性)"
                % sha[:8])
        out.append(e)
    return out
EXPECTED_TIERS = {"ck131072", "ck163840", "ck262144",
                  "ck524288"}
EXPECTED_CKPT = {
    "ck131072": ("1c39017ddc32a1f819cabb86281427351bb"
                 "38e00b33b1cfde2a1672c69e83024"),
    "ck163840": ("d684156dcb3c4ac48fa2d3dcbfc64ac66c7"
                 "9ec61110aa8e178d7a471cef44710"),
    "ck262144": ("f96ed8e45d3ad5699fd0693595e492b77a6"
                 "a4010da1cfe333c899e483cf12b7c"),
    "ck524288": ("b66e7c8b77cd82d385b764b2dc889f0902d"
                 "f21bee5572d6c1d5b5ebb0fcf5d88")}
EXPECTED_RAW_LABELS = {"v5", "s1", "s2"}
EXPECTED_RAW_MODELS = {
    "v5": {"baseline": "ck131072",
           "new": "ck163840"},
    "s1": {"new": "ck262144",
           "source_frozen": "ck163840"},
    "s2": {"new": "ck524288",
           "source_frozen": "ck262144"}}


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_manifest(path, trusted_entries) -> dict:
    actual = sha(path)
    if not any(e["sha256"] == actual
               for e in trusted_entries):
        raise cc.ContractError(
            "manifest SHA %s not in trusted table "
            "(candidate/unapproved — fail-closed)" % actual)
    m = json.loads(Path(path).read_text(encoding="utf-8"))
    # manifest 不得自带信任源
    for bad_key in ("trusted", "trusted_manifest",
                    "trust_source", "trust"):
        if bad_key in m:
            raise cc.ContractError(
                "manifest must not carry trust key %r"
                % bad_key)
    for k in ("contract_version", "bank", "grids", "raws"):
        if k not in m:
            raise cc.ContractError(
                "manifest missing key %r" % k)
    if m["contract_version"] != cc.CONTRACT_VERSION:
        raise cc.ContractError("manifest contract version")
    if not m["grids"] or not m["raws"]:
        raise cc.ContractError(
            "manifest grids/raws must be non-empty (empty "
            "input set cannot pass)")
    tiers = [g["tier"] for g in m["grids"]]
    if len(tiers) != len(set(tiers)):
        raise cc.ContractError(
            "duplicate tiers in manifest: %r" % tiers)
    for g in m["grids"]:
        for k in ("tier", "path", "sha", "model",
                  "ckpt_sha"):
            if not g.get(k):
                raise cc.ContractError(
                    "manifest grid entry missing %r" % k)
    for r in m["raws"]:
        for k in ("label", "path", "sha", "models"):
            if not r.get(k) or not r["models"]:
                raise cc.ContractError(
                    "manifest raw entry missing %r" % k)
    for k in ("path", "sha"):
        if not m["bank"].get(k):
            raise cc.ContractError("manifest bank missing")
    # 结构:新 schema 自包含校验;golden legacy(无 schema 字段)
    # 走内置恰齐映射;其余未知 schema/version invalid。
    def _hex64(v, what):
        if not (isinstance(v, str) and len(v) == 64
                and all(c in "0123456789abcdef"
                        for c in v)):
            raise cc.ContractError(
                "%s not full 64-hex (rejects UNVERIFIED "
                "placeholders): %r" % (what, v))
        return v

    if m.get("untrusted_candidate") is True:
        raise cc.ContractError(
            "manifest is untrusted_candidate proposal "
            "(approval must produce a marker-free list "
            "whose SHA is then registered)")
    grid_tiers = {g["tier"] for g in m["grids"]}
    for g in m["grids"]:
        _hex64(g.get("sha"), "grid %s sha" % g["tier"])
        _hex64(g.get("ckpt_sha"),
               "grid %s ckpt_sha" % g["tier"])
    raw_targets = set()
    for r in m["raws"]:
        _hex64(r.get("sha"), "raw %s sha" % r["label"])
        for mm, tt in r["models"].items():
            if tt not in grid_tiers:
                raise cc.ContractError(
                    "raw %s model %r -> nonexistent grid "
                    "tier %r" % (r["label"], mm, tt))
            raw_targets.add(tt)
    if raw_targets != grid_tiers:
        raise cc.ContractError(
            "raw mapping union %r != grid tiers %r "
            "(must exactly cover; cross-file reuse of "
            "same tier allowed)" % (
                sorted(raw_targets), sorted(grid_tiers)))
    sch = m.get("manifest_schema")
    if sch is None:
        if actual != GOLDEN_SHA:
            raise cc.ContractError(
                "legacy no-schema manifest only allowed "
                "for golden, got %s" % actual)
        exp_tiers = EXPECTED_TIERS
        exp_ckpt = EXPECTED_CKPT
        exp_raws = EXPECTED_RAW_LABELS
        exp_map = EXPECTED_RAW_MODELS
    elif sch == MANIFEST_SCHEMA_C1:
        if m.get("course_id") != "c1":
            raise cc.ContractError(
                "schema %s requires course_id c1, got %r"
                % (sch, m.get("course_id")))
        if m.get("contract_version") != cc.CONTRACT_VERSION:
            raise cc.ContractError(
                "manifest contract_version mismatch")
        exp_tiers = set(m.get("expected_tiers") or ())
        exp_ckpt = dict(m.get("expected_ckpt") or {})
        if not exp_tiers or set(exp_ckpt) != exp_tiers:
            raise cc.ContractError(
                "manifest expected sets missing/conflict")
        exp_raws = set(m.get("expected_raw_labels") or ())
        exp_map = dict(m.get("expected_raw_models") or {})
        if not exp_raws or set(exp_map) != exp_raws:
            raise cc.ContractError(
                "manifest raw mapping missing/conflict")
    else:
        raise cc.ContractError(
            "unknown manifest_schema %r" % sch)
    # 恰齐核验(不得降低覆盖/改门:仍用同一套结构规则)
    if {g["tier"] for g in m["grids"]} != exp_tiers:
        raise cc.ContractError(
            "manifest tiers %r != expected %r"
            % (sorted({g["tier"] for g in m["grids"]}),
               sorted(exp_tiers)))
    for g in m["grids"]:
        if g["ckpt_sha"] != exp_ckpt[g["tier"]]:
            raise cc.ContractError(
                "manifest ckpt for %s not approved mapping"
                % g["tier"])
    labels = [r["label"] for r in m["raws"]]
    if len(labels) != len(set(labels)) or (
            set(labels) != exp_raws):
        raise cc.ContractError(
            "manifest raws %r != expected %r unique"
            % (labels, sorted(exp_raws)))
    for r in m["raws"]:
        if r["models"] != exp_map[r["label"]]:
            raise cc.ContractError(
                "manifest raw %s model->tier mapping not "
                "approved" % r["label"])
    m["_expected"] = {"tiers": exp_tiers, "ckpt": exp_ckpt,
                      "raws": exp_raws, "map": exp_map}
    return m


def validate_raw_file(path, expect_sha, model_tier,
                      label) -> dict:
    """逐 model 完整性+覆盖统计(一文件可两 model)。"""
    got = sha(path)
    if got != expect_sha:
        raise cc.ContractError(
            "raw %s SHA drift %s" % (label, got))
    rows = [json.loads(l) for l in
            path.read_text(encoding="utf-8").splitlines()]
    if not rows:
        raise cc.ContractError("raw %s empty" % label)
    models = sorted({r.get("model") for r in rows})
    if not models or None in models:
        raise cc.ContractError(
            "raw %s missing model field" % label)
    for m in models:
        if m not in model_tier:
            raise cc.ContractError(
                "raw %s pseudo model %r (not in manifest "
                "mapping)" % (label, m))
    if set(models) != set(model_tier):
        raise cc.ContractError(
            "raw %s model set %r != mapping %r "
            "(missing/extra model)" % (
                label, sorted(models),
                sorted(model_tier)))
    per_model = {}
    for m in models:
        sub = [r for r in rows if r["model"] == m]
        seen = set()
        eps = {}
        for r in sub:
            def _int_nb(v):
                return (isinstance(v, int)
                        and not isinstance(v, bool))
            for f, lo, hi in (("pair_index", 0, 3),
                              ("variant", 0, 1),
                              ("step", 0, 63)):
                v = r.get(f)
                if not (_int_nb(v) and lo <= v <= hi):
                    raise cc.ContractError(
                        "raw %s model %s bad %s=%r"
                        % (label, m, f, v))
            for f in ("terminated", "truncated",
                      "economic_failure"):
                if not isinstance(r.get(f), bool):
                    raise cc.ContractError(
                        "raw %s model %s %s not bool: %r"
                        % (label, m, f, r.get(f)))
            if r["economic_failure"] is True:
                raise cc.ContractError(
                    "raw %s model %s economic_failure "
                    "true at step %d" % (
                        label, m, r["step"]))
            eb = r.get("exposure_before", "__missing__")
            if (eb == "__missing__"
                    or isinstance(eb, bool)
                    or not isinstance(eb, (int, float))
                    or not math.isfinite(float(eb))):
                raise cc.ContractError(
                    "raw %s model %s exposure_before "
                    "missing/non-finite=%r (no default)"
                    % (label, m, eb))
            eq = r.get("equity_end")
            if not (isinstance(eq, (int, float))
                    and not isinstance(eq, bool)
                    and math.isfinite(eq) and eq > 0):
                raise cc.ContractError(
                    "raw %s model %s equity_end invalid %r"
                    % (label, m, eq))
            fee = r.get("fee_increment_all_fills")
            if not (isinstance(fee, (int, float))
                    and not isinstance(fee, bool)
                    and math.isfinite(fee) and fee >= 0):
                raise cc.ContractError(
                    "raw %s model %s fee invalid %r"
                    % (label, m, fee))
            sv = r.get("s")
            if not (isinstance(sv, (int, float))
                    and not isinstance(sv, bool)
                    and math.isfinite(sv)
                    and float(sv) in (-1.0, 0.0, 1.0)):
                raise cc.ContractError(
                    "raw %s model %s s invalid (not in "
                    "{-1,0,1}) %r" % (label, m, sv))
            # 终止位置按 step:0..62 不得终止;63 必须终止
            term_now = r["terminated"] or r["truncated"]
            if r["step"] < 63 and term_now:
                raise cc.ContractError(
                    "raw %s model %s early termination at "
                    "step %d" % (label, m, r["step"]))
            if r["step"] == 63 and not term_now:
                raise cc.ContractError(
                    "raw %s model %s no terminal flag at "
                    "step 63" % (label, m))
            key = (r["pair_index"], r["variant"],
                   r["step"])
            if key in seen:
                raise cc.ContractError(
                    "raw %s model %s duplicate row %r"
                    % (label, m, key))
            seen.add(key)
            eps.setdefault((r["pair_index"],
                            r["variant"]),
                           {"steps": set()})[
                "steps"].add(r["step"])
        if len(eps) != 8:
            raise cc.ContractError(
                "raw %s model %s episodes %d != 8"
                % (label, m, len(eps)))
        for k, ep in eps.items():
            if ep["steps"] != set(range(64)):
                raise cc.ContractError(
                    "raw %s model %s ep %r steps not "
                    "exact 0..63 (n=%d)"
                    % (label, m, k, len(ep["steps"])))
            # 终止位置已按 step 逐行核验(step<63 禁终止,
            # step==63 必终止);不依赖文件行序的 last 记录
        if len(sub) != 512:
            raise cc.ContractError(
                "raw %s model %s rows %d != 512"
                % (label, m, len(sub)))
        flat = sum(1 for r in sub
                   if abs(float(
                       r["exposure_before"]))
                   <= W_FLAT)
        per_model[m] = {
            "tier": model_tier[m], "rows": len(sub),
            "episodes": len(eps),
            "base_pairs": sorted({r["pair_index"]
                                  for r in sub}),
            "mirror_pairs": sorted(
                p for p in range(4)
                if (p, 0) in eps and (p, 1) in eps),
            "account_state_rows": {
                "flat_pre": flat,
                "nonflat_pre": len(sub) - flat}}
    return {"label": label, "sha256": got,
            "per_model": per_model}


def emit_candidate(args) -> int:
    """候选清单生成(仅提案):现算哈希;untrusted 水印;
    不写技能报告/不改信任表/独占输出拒绝覆盖。"""
    out = Path(args.out)
    grids = []
    for spec_s in args.grid:
        tier, path, model = spec_s.split("|")
        gsha = sha(path)
        rows = json.loads(Path(path).read_text(
            encoding="utf-8"))
        models = {r.get("model") for r in rows}
        if models != {model}:
            print("CANDIDATE_BAD model set %r" % models,
                  file=sys.stderr)
            return 3
        grids.append({"tier": tier, "path": path,
                      "sha": gsha, "model": model,
                      "ckpt_sha": "UNVERIFIED(review fills)"})
    raws = []
    for spec_s in args.raw:
        parts = spec_s.split("|")
        label, path = parts[0], parts[1]
        models = parts[2].split(",")
        rsha = sha(path)
        rows = [json.loads(l) for l in Path(path)
                .read_text(encoding="utf-8").splitlines()]
        got = sorted({r.get("model") for r in rows})
        if got != sorted(models):
            print("CANDIDATE_BAD raw models %r" % got,
                  file=sys.stderr)
            return 3
        raws.append({"label": label, "path": path,
                     "sha": rsha,
                     "models": {m: "UNVERIFIED"
                                for m in models}})
    cand = {
        "manifest_schema": MANIFEST_SCHEMA_C1,
        "course_id": "c1",
        "contract_version": cc.CONTRACT_VERSION,
        "untrusted_candidate": True,
        "watermark": ("PROPOSAL ONLY — requires "
                      "independent review + trusted-"
                      "manifests commit; NOT approved"),
        "grids": grids, "raws": raws}
    try:
        with out.open("x", encoding="utf-8") as fh:
            fh.write(json.dumps(
                cand, ensure_ascii=False, indent=1))
    except FileExistsError:
        print("CANDIDATE_OUT_EXISTS (refuse overwrite)",
              file=sys.stderr)
        return 3
    print("CANDIDATE_WRITTEN %s (untrusted)" % out)
    return 0


def main(argv=None, trusted_entries=None) -> int:
    """trusted_entries 仅内部测试注入;生产 CLI 无此参数。"""
    t0 = utc()
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest")
    ap.add_argument("--out", required=True)
    ap.add_argument(
        "--emit-candidate", action="store_true",
        help="仅提案:现算哈希生成 candidate manifest,"
             "不写技能报告,不改信任表,不自我批准")
    ap.add_argument("--grid", action="append", default=[],
                    help="candidate 模式:tier|path|model")
    ap.add_argument("--raw", action="append", default=[],
                    help="candidate 模式:label|path|model[,m2]")
    args = ap.parse_args(argv)
    if args.emit_candidate:
        return emit_candidate(args)
    out = Path(args.out)
    rep = {"utc_start": t0}
    rc = RC_PASS
    owned = False
    try:
        out.mkdir(parents=True)
        fd = os.open(str(out / "offline_report.marker"),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, b"course_contract_offline v2\n")
        os.close(fd)
        owned = True
        if not args.manifest:
            raise cc.ContractError("--manifest required")
        if trusted_entries is None:
            trusted_entries = _load_trusted_entries()
        man = load_manifest(args.manifest, trusted_entries)
        entry = next(e for e in trusted_entries
                     if e["sha256"] == sha(args.manifest))
        rep["trusted_manifest"] = {
            "sha256": entry["sha256"],
            "kind": entry.get("kind"),
            "course_id": entry.get("course_id")}
        rep["manifest_path"] = args.manifest
        rep["manifest_contract_version"] = man[
            "contract_version"]
        contract = cc.build_contract()
        rep["contract"] = contract
        non_c1 = (entry.get("course_id") != "c1")
        rep["entry_module_sha256"] = sha(Path(
            __file__).resolve())
        rep["contract_module_sha256"] = sha(Path(
            cc.__file__).resolve())

        # ---- bank:manifest 固定身份(域绑定非仅 cgqs) ----
        bsha = sha(man["bank"]["path"])
        if bsha != man["bank"]["sha"]:
            raise cc.ContractError(
                "bank SHA drift %s" % bsha)
        from rl_posctl.skill_p0.p0banks import (
            load_p0_bank)
        items = load_p0_bank(Path(man["bank"]["path"]))
        cols = {tuple(str(c) for c in it[1].columns)
                for it in items}
        if cols != {tuple(contract["c1"][
                "feature_order"])}:
            raise cc.ContractError(
                "bank feature order != cgqs")
        rep["source_binding"] = {
            "bank": {"path": man["bank"]["path"],
                     "sha256": bsha,
                     "episodes": len(items)},
            "spec_sources": contract["source_binding"]}

        # ---- grids(manifest 期望值;非现算当 expected) --
        skills = {}
        for g in man["grids"]:
            actual = sha(g["path"])
            if actual != g["sha"]:
                raise cc.ContractError(
                    "grid %s SHA drift %s"
                    % (g["tier"], actual))
            rows = json.loads(Path(g["path"]).read_text(
                encoding="utf-8"))
            info = cc.validate_grid_rows(
                rows, contract_version=(
                    man["contract_version"]),
                expect_model=g["model"])
            ev = (cc.skill_eval(rows) if not non_c1 else
                  {"all_skills": "not_specified",
                   "reason": "non-c1 course: no gates "
                             "defined; cannot pass"})
            skills[g["tier"]] = {
                "grid_sha256": actual,
                "checkpoint_sha256": g["ckpt_sha"],
                "model": g["model"],
                "grid_info": info, "skills": ev,
                "auxiliary": {
                    "mean_p_neutral_band": sum(
                        float(r["p_neutral_band"])
                        for r in rows
                        if float(r["s"]) == 0.0) / 36,
                    "role": "auxiliary only"}}
            if any(v["status"] == "fail"
                   for v in ev.values()
                   if isinstance(v, dict)):
                rc = max(rc, RC_FAIL)
            if non_c1:
                # 非 C1 不能整体 pass(无门即无达标)
                rc = max(rc, RC_FAIL)
        rep["tiers"] = skills

        # ---- raws ------------------------------------------
        raw_model_tier = {}
        for r in man["raws"]:
            for m, t in r["models"].items():
                raw_model_tier[m] = t
        cov = [validate_raw_file(
            Path(r["path"]), r["sha"],
            {m: t for m, t in r["models"].items()},
            r["label"]) for r in man["raws"]]
        base_union = sorted({p for c in cov
                             for pm in c[
                                 "per_model"].values()
                             for p in pm["base_pairs"]})
        rep["coverage"] = {
            "market_state_grid": {
                "conditions": contract["c1"][
                    "grid_conditions"],
                "neutral": contract["c1"][
                    "neutral_conditions"],
                "covered_by_tiers": sorted(skills),
                "note": ("设计面反事实条件覆盖"
                         "(s×c×q×g×remaining 全笛卡尔;"
                         "由精确条件集校验保证)")},
            "trajectory": cov,
            "account_state": {
                "pre_position_rows_by_model": {
                    "%s|%s" % (c["label"], m): pm[
                        "account_state_rows"]
                    for c in cov
                    for m, pm in c[
                        "per_model"].items()},
                "dedup_base_pairs_union": base_union,
                "note": ("账户状态=仓前 exposure 桶"
                         "(|e|<=0.10 flat);无门≠不统计")},
            "sample_counting": {
                "independent_market_units": (
                    len(base_union)),
                "rule": ("跨镜像与跨 checkpoint 去重;"
                         "轨迹≠grid 覆盖")}}
        rep["not_specified_items"] = [
            "held_position_neutral(带仓中性处理)",
            "c2/c3/c4 全部门与晋级",
            "账户状态带仓轴(仅统计)"]

        rep["status"] = ("pass" if rc == RC_PASS
                         else "fail")
        rep["rc"] = rc
        rep["utc_end"] = utc()
        (out / "offline_skill_report.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("OFFLINE_%s rc=%d" % (rep["status"], rc))
        return rc
    except cc.ContractError as exc:
        rc = RC_INVALID
        rep.update(status="invalid", error=str(exc),
                   rc=rc)
    except BaseException as exc:
        rc = RC_INVALID
        rep.update(status="invalid",
                   error="unexpected: %r" % exc,
                   traceback=traceback.format_exc(), rc=rc)
    finally:
        if owned and out.is_dir():
            try:
                (out / "offline_skill_report.json").write_text(
                    json.dumps(rep, ensure_ascii=False,
                               indent=1), encoding="utf-8")
            except BaseException:
                pass
    print("OFFLINE_INVALID %s" % rep.get("error", "?"),
          file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
