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


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def load_manifest(path) -> dict:
    m = json.loads(Path(path).read_text(encoding="utf-8"))
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
    per_model = {}
    for m in models:
        sub = [r for r in rows if r["model"] == m]
        seen = set()
        eps = {}
        for r in sub:
            for f, chk in (
                    ("pair_index",
                     lambda v: isinstance(v, int)
                     and 0 <= v <= 3),
                    ("variant",
                     lambda v: isinstance(v, int)
                     and v in (0, 1)),
                    ("step",
                     lambda v: isinstance(v, int)
                     and not isinstance(v, bool)
                     and 0 <= v <= 63)):
                v = r.get(f)
                if not chk(v):
                    raise cc.ContractError(
                        "raw %s model %s bad %s=%r"
                        % (label, m, f, v))
            for f in ("equity_end",
                      "fee_increment_all_fills", "s"):
                v = r.get(f)
                if not (isinstance(v, (int, float))
                        and math.isfinite(float(v))):
                    raise cc.ContractError(
                        "raw %s model %s non-finite %s"
                        % (label, m, f))
            key = (r["pair_index"], r["variant"],
                   r["step"])
            if key in seen:
                raise cc.ContractError(
                    "raw %s model %s duplicate row %r"
                    % (label, m, key))
            seen.add(key)
            eps.setdefault((r["pair_index"],
                            r["variant"]),
                           {"steps": set(),
                            "last": None}).setdefault(
                "steps", set()).add(r["step"])
            eps[(r["pair_index"], r["variant"])][
                "last"] = r
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
            last = ep["last"]
            if not (last.get("terminated")
                    or last.get("truncated")):
                raise cc.ContractError(
                    "raw %s model %s ep %r last step not "
                    "terminal" % (label, m, k))
        if len(sub) != 512:
            raise cc.ContractError(
                "raw %s model %s rows %d != 512"
                % (label, m, len(sub)))
        flat = sum(1 for r in sub
                   if abs(float(r.get(
                       "exposure_before", 0.0)))
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


def main(argv=None) -> int:
    t0 = utc()
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
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
        man = load_manifest(args.manifest)
        rep["manifest_path"] = args.manifest
        rep["manifest_contract_version"] = man[
            "contract_version"]
        contract = cc.build_contract()
        rep["contract"] = contract
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
            ev = cc.skill_eval(rows)
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
