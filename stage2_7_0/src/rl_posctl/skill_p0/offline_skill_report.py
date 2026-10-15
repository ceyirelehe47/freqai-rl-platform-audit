# -*- coding: utf-8 -*-
"""离线技能验收入口(纯数据;零模型前向/环境 step/训练)。

输入:已授权 train bank + 既有 grid/raw JSON(全 SHA 预核)。
输出:独占目录内统一 JSON 报告(新文件;拒绝覆盖)。

rc 语义:0=全部 pass;1=存在技能 fail(有效证据不达标);
3=invalid(格式/身份/版本/SHA 错误——非零退出,报告仍落盘)。
不改生产 registry 毕业状态;不改续训入口/经济环境。
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


def utc():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def parse_grid_spec(spec, pos):
    parts = spec.split("|")
    if len(parts) != 4:
        raise cc.ContractError(
            "grid spec #%d must be "
            "tier|path|sha|ckpt_sha (got %r)"
            % (pos, spec))
    tier, path, s, ck = parts
    if not Path(path).is_file():
        raise cc.ContractError("grid missing: %s" % path)
    return tier, Path(path), s, ck


def raw_coverage(raw_path, want_sha, *, label):
    """轨迹覆盖(行/episode/基础 pair/镜像;不增样本)。"""
    got = sha(raw_path)
    if got != want_sha:
        raise cc.ContractError(
            "raw %s SHA drift %s" % (label, got))
    rows = [json.loads(l) for l in
            raw_path.read_text(encoding="utf-8").splitlines()]
    for r in rows:
        for f in ("equity_end", "s"):
            v = r.get(f)
            if not (isinstance(v, (int, float))
                    and math.isfinite(float(v))):
                raise cc.ContractError(
                    "raw %s non-finite %s" % (label, f))
    models = sorted({r["model"] for r in rows})
    eps = {(r["model"], r["pair_index"], r["variant"])
           for r in rows}
    steps = sorted({r["step"] for r in rows})
    base_pairs = sorted({r["pair_index"] for r in rows})
    variants = sorted({r["variant"] for r in rows})
    per_model = {}
    for m in models:
        mr = [r for r in rows if r["model"] == m]
        per_model[m] = {
            "episodes": len({(r["pair_index"],
                              r["variant"]) for r in mr}),
            "steps_per_episode": sorted(
                {r["step"] for r in mr})[-1] + 1}
    return {
        "label": label, "sha256": got, "rows": len(rows),
        "models": models, "episodes_total": len(eps),
        "base_pairs": base_pairs, "variants": variants,
        "per_model": per_model,
        "mirror_relation": ("variant0/variant1 同基础 pair "
                            "互为镜像(s→−s);独立市场单位="
                            "基础 pair 数 %d,非 episodes"
                            % len(base_pairs)),
        "sample_count_note": ("镜像与多 checkpoint 不增加"
                              "独立样本数;轨迹覆盖≠grid"
                              " 覆盖(grid=108 反事实条件,"
                              "轨迹=已实现路径)")}, rows


def main(argv=None) -> int:
    t0 = utc()
    ap = argparse.ArgumentParser()
    ap.add_argument("--contract", default=(
        cc.CONTRACT_VERSION))
    ap.add_argument("--bank", required=True)
    ap.add_argument("--bank-sha", required=True)
    ap.add_argument("--grid", action="append", default=[],
                    help="tier|path|sha|ckpt_sha")
    ap.add_argument("--raw", action="append", default=[],
                    help="label|path|sha")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    out = Path(args.out)
    rep = {"utc_start": t0, "contract_version": args.contract}
    rc = RC_PASS
    owned = False
    try:
        out.mkdir(parents=True)
        fd = os.open(str(out / "offline_report.marker"),
                     os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, (b"course_contract_offline v1\n"))
        os.close(fd)
        owned = True
        if args.contract != cc.CONTRACT_VERSION:
            raise cc.ContractError(
                "unknown contract version %r"
                % args.contract)
        contract = cc.build_contract()
        rep["contract"] = contract

        # ---- bank:SHA + 列序(只读) ------------------------
        bsha = sha(args.bank)
        if bsha != args.bank_sha:
            raise cc.ContractError(
                "bank SHA drift %s" % bsha)
        sys.path.insert(0, "src")
        from rl_posctl.skill_p0.p0banks import load_p0_bank
        items = load_p0_bank(Path(args.bank))
        cols = {tuple(str(c) for c in it[1].columns)
                for it in items}
        if cols != {tuple(contract["c1"][
                "feature_order"])}:
            raise cc.ContractError(
                "bank feature order != contract cgqs: %r"
                % sorted(cols))
        rep["source_binding"] = {
            "bank": {"path": args.bank,
                     "sha256": bsha,
                     "episodes": len(items)},
            "candidate_commit": cc.CANDIDATE_COMMIT}

        # ---- grids ------------------------------------------
        skills = {}
        for pos, spec_s in enumerate(args.grid):
            tier, path, want, ck_sha = parse_grid_spec(
                spec_s, pos)
            g = sha(path)
            if g != want:
                raise cc.ContractError(
                    "grid %s SHA drift %s" % (tier, g))
            rows = json.loads(
                path.read_text(encoding="utf-8"))
            expect_model = ("new" if "new" in path.name
                            or tier in ("ck163840",
                                        "ck262144",
                                        "ck524288")
                            else "baseline")
            info = cc.validate_grid_rows(
                rows, contract_version=args.contract,
                expect_model=expect_model)
            ev = cc.skill_eval(rows)
            aux = {
                "mean_p_neutral_band": sum(
                    float(r["p_neutral_band"])
                    for r in rows
                    if float(r["s"]) == 0.0) / 36,
                "role": "auxiliary only(不作门)"}
            skills[tier] = {
                "grid_sha256": g,
                "checkpoint_sha256": ck_sha,
                "grid_info": info, "skills": ev,
                "auxiliary": aux}
            if any(v["status"] == "fail"
                   for v in ev.values()
                   if isinstance(v, dict)):
                rc = max(rc, RC_FAIL)
        rep["tiers"] = skills

        # ---- raws(轨迹覆盖+辅助收益) -----------------------
        cov = []
        for pos, rspec in enumerate(args.raw):
            parts = rspec.split("|")
            if len(parts) != 3:
                raise cc.ContractError(
                    "raw spec #%d must be label|path|sha"
                    % pos)
            label, path, want = parts
            info, rows = raw_coverage(
                Path(path), want, label=label)
            aux = {}
            for m in info["models"]:
                eps = {}
                prev = {}
                for r in rows:
                    if r["model"] != m:
                        continue
                    k = (r["pair_index"], r["variant"])
                    a = eps.setdefault(k, {"prev": 100.0,
                                           "log": 0.0})
                    a["log"] += math.log(
                        r["equity_end"] / a["prev"])
                    a["prev"] = r["equity_end"]
                aux[m] = round(sum(v["log"]
                                   for v in eps.values())
                               / len(eps), 6)
            info["auxiliary_mean_net_log_eq"] = aux
            cov.append(info)
        rep["coverage"] = {
            "market_state_grid": {
                "conditions": contract["c1"][
                    "grid_conditions"],
                "neutral": contract["c1"][
                    "neutral_conditions"],
                "covered_by": sorted(skills)},
            "trajectory": cov,
            "account_state": {
                "gate_initial_state": "flat "
                "(counterfactual;obs[4]==0 已逐行校验)",
                "held_position_axis": "not_specified"}}
        rep["not_specified_items"] = [
            "held_position_neutral(带仓中性处理)",
            "c2/c3/c4 全部门与晋级",
            "账户状态带仓轴"]

        if rc == RC_PASS:
            rep["status"] = "pass"
        else:
            rep["status"] = "fail"
        rep["rc"] = rc
        rep["utc_end"] = utc()
        (out / "offline_skill_report.json").write_text(
            json.dumps(rep, ensure_ascii=False, indent=1),
            encoding="utf-8")
        print("OFFLINE_%s rc=%d" % (rep["status"], rc))
        return rc
    except cc.ContractError as exc:
        rc = RC_INVALID
        rep["status"] = "invalid"
        rep["error"] = str(exc)
        rep["rc"] = rc
        try:
            if owned and out.is_dir():
                (out / "offline_skill_report.json").write_text(
                    json.dumps(rep, ensure_ascii=False,
                               indent=1), encoding="utf-8")
        except BaseException:
            pass
        print("OFFLINE_INVALID %s" % exc, file=sys.stderr)
        return rc
    except BaseException as exc:
        rc = RC_INVALID
        rep["status"] = "invalid"
        rep["error"] = "unexpected: %r" % exc
        rep["traceback"] = traceback.format_exc()
        rep["rc"] = rc
        try:
            if owned and out.is_dir():
                (out / "offline_skill_report.json").write_text(
                    json.dumps(rep, ensure_ascii=False,
                               indent=1), encoding="utf-8")
        except BaseException:
            pass
        print("OFFLINE_INVALID %r" % exc, file=sys.stderr)
        return rc


if __name__ == "__main__":
    sys.exit(main())
