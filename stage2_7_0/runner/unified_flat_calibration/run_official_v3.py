# -*- coding: utf-8 -*-
"""UNIFIED_FLAT_CALIBRATION_V1 正式首包 runner v3(静态交付,未执行)。

v2→v3(审查方 3071,仅失败路径,后端零改动):
1) 每档 solve 前清 current;solve **一返还**即按真实 tier 注册
   per_tier(先于 completed/validate/query);删 save_failure 里按
   current 字符串补救的第二套 fallback,统一 tier→tables 保存;
   V=None 如实记录;登记键=tiers_returned,完成度按 table
   completed 且 64 行另判。
2) 每个返还 table 保存 partial_meta(缺字段写 None,不重建补证)。
3) 唯一中央 BaseException 收尾:先写权威 failed/partial(含
   completed 已落盘后的 KI/打印失败),再抢救数组;保留原异常与
   非零 rc;写失败单独落 FAIL_SAVE_ERROR,不静默声称已改写;
   内层重复 save 删除——注册后 raise 交中央。
4) import 成功即 ACTIVE["ur"];except 不重新 import;_JOB 为
   None 时 snapshot 记 job_started=False、wall/cpu=None 与既有
   _RUNS,不调用会启动新时钟的 _job_elapsed。
"""
import copy
import datetime
import hashlib
import json
import math
import os
import sys
import time
import traceback

import numpy as np

SRC = "/mnt/f/trading/freqai-rl-audit/stage2_7_0/src"
sys.path.insert(0, SRC)

OUT = sys.argv[1]
ADAPTER = os.path.join(
    SRC, "rl_posctl/skill_p0/unified_ref_adapter.py")
EXPECT_SHA = ("e1eb33e568ad20697213c584e77e240a1"
              "8497cf1c43a779fef9de5aa96897773")

META = {"stage": "official_first_package_attempt3",
        "command": " ".join(sys.argv),
        "python": sys.executable,
        "numpy_version": np.__version__,
        "thread_env": {k: os.environ.get(k)
                       for k in
                       ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS",
                        "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS")},
        "adapter_sha256": hashlib.sha256(
            open(ADAPTER, "rb").read()).hexdigest()}

# solve 一返还即按真实 tier 注册(先于一切判定)
ACTIVE = {"ur": None,          # import 成功即存句柄
          "per_tier": {},      # tier -> 返还的 tables(原样)
          "rows": {}}          # tier -> 已查 rows 列表


def utcnow():
    return datetime.datetime.now(
        datetime.timezone.utc).isoformat()


def _job_snapshot(ur):
    """_JOB None → job_started=False,wall/cpu=None,
    不调用会启动新时钟的 _job_elapsed。"""
    runs = dict(ur._RUNS) if ur is not None else None
    if ur is None or ur._JOB is None:
        return {"job_started": False,
                "wall_s": None, "cpu_s": None,
                "rss_gib": (ur._now_rss_gib()
                            if ur is not None else None),
                "runs": runs}
    wall, cpu = ur._job_elapsed()
    return {"job_started": True,
            "wall_s": wall, "cpu_s": cpu,
            "rss_gib": ur._now_rss_gib(),
            "runs": runs,
            "open_run": (dict(ur._RUNS["open"])
                         if ur._RUNS["open"] else None)}


def _tier_partial_meta(tier, tables, rows):
    """返还 table 的 partial_meta;缺字段写 None,不重建。"""
    V = tables.get("V") if tables else None
    q_rows = rows.get(tier) or []
    return {
        "tier": tier,
        "budget": tables.get("budget") if tables
        else None,
        "stop_reason": tables.get("stop_reason")
        if tables else None,
        "bars_done": tables.get("bars_done")
        if tables else None,
        "partial": tables.get("partial") if tables
        else None,
        "completed": tables.get("completed")
        if tables else None,
        "solver": tables.get("solver") if tables
        else None,
        "dp_key": tables.get("dp_key") if tables
        else None,
        "H": tables.get("bars") if tables else None,
        "bars": tables.get("bars") if tables else None,
        "GL": tables.get("gl") if tables else None,
        "actions": ([float(x) for x in
                     tables["actions"]]
                    if tables and tables.get(
                        "actions") is not None
                    else None),
        "accounts": ([float(x) for x in
                      tables["accounts"]]
                     if tables and tables.get(
                         "accounts") is not None
                     else None),
        "V_shape": (list(np.shape(V))
                    if V is not None else None),
        "V_is_none": V is None,
        "rows_count": len(q_rows),
        "tier_complete_64": bool(
            tables is not None
            and tables.get("completed") is True
            and len(q_rows) == 64)}


def _authoritative_fail(reason, err_text):
    """中央收尾第一步:权威 failed/partial(先于抢救数组;
    含 completed 已落盘后的失败→改写 official_meta)。"""
    ur = ACTIVE["ur"]
    snap = _job_snapshot(ur)
    if META.get("status") == "completed":
        META["status"] = "failed_after_save"
        META["fail_reason"] = reason
        META["utc_fail"] = utcnow()
        META["job"] = snap
        jdump(META, os.path.join(
            OUT, "official_meta.json"))
    state = {
        "status": "failed",
        "reason": reason,
        "utc": utcnow(),
        "job": snap,
        "tiers_returned": sorted(ACTIVE[
            "per_tier"]),
        "tiers_meta": {
            t: _tier_partial_meta(
                t, tb, ACTIVE["rows"])
            for t, tb in ACTIVE[
                "per_tier"].items()},
        "rows_counts": {t: len(r) for t, r
                        in ACTIVE["rows"].items()},
        "error": (err_text or "")[-4000:]}
    jdump(state, os.path.join(
        OUT, "FAIL_STATE.json"))


def _salvage_arrays():
    """中央收尾第二步:抢救数组(仅已返还 tables 与已查 rows)。"""
    for tier, tables in ACTIVE[
            "per_tier"].items():
        V = tables.get("V")
        if V is not None:
            np.save(os.path.join(
                OUT, "partial_V_%s.npy" % tier),
                np.asarray(V))
        else:
            with open(os.path.join(
                    OUT,
                    "partial_V_%s.NONE" % tier),
                    "w") as f:
                f.write("V is None\n")
        with open(os.path.join(
                OUT,
                "partial_meta_%s.json" % tier),
                "w", encoding="utf-8") as f:
            json.dump(_tier_partial_meta(
                tier, tables, ACTIVE["rows"]),
                f, indent=1)
    for tier, rows in ACTIVE["rows"].items():
        with open(os.path.join(
                OUT, "partial_rows_%s.json" % tier),
                "w", encoding="utf-8") as f:
            json.dump(enc_rows(rows), f, indent=1)


def enc_float(x):
    if x == math.inf:
        return "+inf"
    if x == -math.inf:
        return "-inf"
    return float(x)


def dec_float(x):
    if x == "+inf":
        return math.inf
    if x == "-inf":
        return -math.inf
    return float(x)


def enc_rows(rows):
    out = []
    for r in rows:
        e = {k: v for k, v in r.items()
             if k not in ("q_rebals", "account")}
        e["account"] = {
            k: ("+inf" if v == math.inf else v)
            for k, v in r["account"].items()}
        e["q_hold"] = enc_float(r["q_hold"])
        e["q_rebals"] = {
            "%.17g" % float(w): enc_float(v)
            for w, v in r["q_rebals"].items()}
        out.append(e)
    return out


def dec_rows(rows):
    out = []
    for e in rows:
        r = {k: v for k, v in e.items()
             if k != "q_rebals"}
        r["account"] = {
            k: (math.inf if v == "+inf" else v)
            for k, v in e["account"].items()}
        r["q_hold"] = dec_float(e["q_hold"])
        r["q_rebals"] = {
            float(k): dec_float(v)
            for k, v in e["q_rebals"].items()}
        out.append(r)
    return out


def jdump(obj, path):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1,
                  allow_nan=False)


def main():
    from rl_posctl.skill_p0 import (
        unified_ref_adapter as ur)
    ACTIVE["ur"] = ur           # import 成功即存句柄
    assert META["adapter_sha256"] == EXPECT_SHA, \
        "adapter SHA drifted"
    ur._verify_binding()
    assert ur._RUNS == {"used": 0, "open": None,
                        "tiers_used": []}
    assert ur._JOB is None
    META["utc_start"] = utcnow()
    per_tier = {}
    tier_meta = {}
    for tier in ("L0", "L1", "L2"):
        tables = ur.solve_reference(tier)
        # 一返还即按真实 tier 注册(先于 completed/validate/query)
        ACTIVE["per_tier"][tier] = tables
        ACTIVE["rows"].setdefault(tier, [])
        if tables.get("completed") is not True:
            # 注册后 raise,收尾交中央(无内层 save)
            raise RuntimeError(
                "tier %s not completed: %r"
                % (tier, tables.get("stop_reason")))
        ur.validate_dp_tables(tier, tables)
        rows = ACTIVE["rows"][tier]
        for q in copy.deepcopy(ur.QUESTIONS):
            r = ur.query_Q(q, tier, tables)
            assert r["dp_key"] == tables["dp_key"]
            assert r["state"] == [
                q["s"], q["c"], float(q["q"]), q["g"]]
            assert (r["remaining"] == q["remaining"]
                    and r["total"] == q["total"])
            merged = {k: v for k, v in q.items()}
            merged.update({
                "q_hold": r["q_hold"],
                "q_rebals": r["q_rebals"],
                "qid_state": r["qid_state"],
                "grid": r["grid"],
                "dp_key": r["dp_key"]})
            rows.append(merged)
        tables["questions"] = rows
        per_tier[tier] = tables
        tier_meta[tier] = {
            "dp_key": tables["dp_key"],
            "budget": tables["budget"],
            "actions": [float(x) for x in
                        tables["actions"]],
            "accounts": [float(x) for x in
                         tables["accounts"]],
            "gl": tables["gl"], "bars": tables["bars"],
            "completed": tables["completed"],
            "V_shape": list(np.shape(tables["V"]))}
        ur._budget_gate()
        np.save(os.path.join(
            OUT, "V_%s.npy" % tier),
            np.asarray(tables["V"],
                       dtype=np.float64))
        jdump({"tier": tier,
               "questions": enc_rows(rows),
               "tier_meta": tier_meta[tier]},
              os.path.join(
                  OUT, "tier_%s.json" % tier))
        ur._budget_gate()
        print("tier %s done rows=%d V=%s" % (
            tier, len(rows),
            tier_meta[tier]["V_shape"]), flush=True)
    analysis = ur.analyze_tiers(per_tier)
    ur._budget_gate()
    jdump({"analysis": analysis,
           "codec": {
               "float_inf": ("'+inf'/'-inf' strings -> "
                             "math.inf on decode"),
               "action_keys": ("'%.17g' repr -> float "
                               "on decode")},
           "boundary": ur.last_bar_fee_boundary(),
           "tail_ids": [q["id"] for q in ur.QUESTIONS
                        if q["id"].startswith("T")]},
          os.path.join(OUT, "analysis.json"))
    for tier in ("L0", "L1", "L2"):
        with open(os.path.join(
                OUT, "tier_%s.json" % tier),
                encoding="utf-8") as f:
            dec = json.load(f)
        back = dec_rows(dec["questions"])
        orig = per_tier[tier]["questions"]
        for a, b in zip(orig, back):
            assert a["q_hold"] == b["q_hold"]
            assert a["account"] == b["account"]
            assert set(a["q_rebals"]) == set(
                b["q_rebals"])
            for w in a["q_rebals"]:
                assert (a["q_rebals"][w]
                        == b["q_rebals"][w])
    ur._budget_gate()
    wall, cpu = ur._job_elapsed()
    rss = ur._now_rss_gib()
    META.update({
        "utc_end": utcnow(),
        "wall_s": wall, "cpu_s": cpu, "rss_gib": rss,
        "runs": dict(ur._RUNS),
        "budget": ur.BUDGET,
        "tiers": tier_meta,
        "solver": ur.SOLVER_VERSION})
    ur._budget_gate()
    META["status"] = "completed"
    jdump(META, os.path.join(
        OUT, "official_meta.json"))
    # 写出后再 gate:越限→raise,中央改写权威 failed
    ur._budget_gate()
    print("OFFICIAL_DONE wall=%.1fs cpu=%.1fs "
          "rss=%.3fGiB" % (wall, cpu, rss),
          flush=True)


if __name__ == "__main__":
    try:
        main()
    except BaseException as exc:
        # 唯一中央收尾:先权威 failed,再抢救数组;
        # 任何保存失败单独落 FAIL_SAVE_ERROR,
        # 不静默声称已改写;原异常保留、非零 rc。
        try:
            _authoritative_fail(
                "exception:%r" % (exc,),
                traceback.format_exc())
        except Exception:
            with open(os.path.join(
                    OUT, "FAIL_SAVE_ERROR.txt"), "w",
                    encoding="utf-8") as f:
                f.write(traceback.format_exc())
        try:
            _salvage_arrays()
        except Exception:
            with open(os.path.join(
                    OUT, "FAIL_SAVE_ERROR.txt"), "a",
                    encoding="utf-8") as f:
                f.write("\n---salvage---\n")
                f.write(traceback.format_exc())
        with open(os.path.join(
                OUT, "ERROR_TRACEBACK.txt"), "w",
                encoding="utf-8") as f:
            f.write(traceback.format_exc())
        raise
