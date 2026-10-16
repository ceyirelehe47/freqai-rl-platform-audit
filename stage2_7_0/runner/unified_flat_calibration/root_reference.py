# -*- coding: utf-8 -*-
"""root_reference v2 — 冻结 L2 延续表下根积分独立参考(PREPARED_NOT_RUN)。

唯一 CLI:root_reference.py <evidence_dir> <locked_manifest> <out_dir>
v2(审查方 3747):CONFIG 双重身份绑定(SHA+参数digest);JobBudget
实装限额(wall/cpu/rss)且 phase 遇 why 立即 raise 保首错,覆盖
验SHA/读V/P/每臂每片/两次写后;CONFIG 载入与 report 初始化在
try 内,失败=权威 failed+FAILED 无悬挂 RUNNING;输出补 input/
config/helper SHA、每根 state/remaining/si、series_branch、
gl48_second_minus_hold 与三对 gap 相对原基准变化。
"""
import hashlib
import json
import math
import os
import resource
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import root_integrals as RI  # noqa

STATUS = "PREPARED_NOT_RUN"
CONFIG_NAME = "CONFIG_rootref.json"
CONFIG_SHA256 = "653f4141930a25d5ef21ecadd60b9d2ec01e8a8bd874534551889b46745dbab7"
PARAM_DIGEST_FIELDS = ("kernel_frozen", "calib_frozen", "domains_frozen", "caps", "budget_planned")


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _param_digest(cfg):
    blob = json.dumps({k: cfg[k] for k in PARAM_DIGEST_FIELDS},
                      sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class JobBudget:
    """实装限额 guard(clock 可注入,仅测试)。"""

    def __init__(self, limits, clock=None):
        self.limits = limits
        if clock is not None:
            self.nw, self.nc = clock
        else:
            self.nw = time.perf_counter
            self.nc = time.process_time
        self.t0 = self.nw()
        self.c0 = self.nc()

    def checkpoint(self):
        wall = self.nw() - self.t0
        cpu = self.nc() - self.c0
        rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        why = None
        if wall > float(self.limits["wall_s"]):
            why = "wall_clock"
        elif cpu > float(self.limits["cpu_s"]):
            why = "cpu"
        elif rss > float(self.limits["rss_kib"]):
            why = "rss"
        return why, {"wall_s": wall, "cpu_s": cpu, "rss_kib": rss}


def build_P(kernel):
    """60×60 联合转移(分量积,同 adapter 公式;纯 numpy)。"""

    def comp_matrix(k):
        vals = k["values"]
        n = len(vals)
        if "fresh_p" in k:
            fresh = np.array(k["fresh_p"], float)
            fresh = fresh / fresh.sum()
            m = 0.2 * np.tile(fresh, (n, 1))
            idx = np.arange(n)
            m[idx, idx] += float(k["hold_p"])
            return vals, m
        m = np.full((n, n), float(k["resample_p"]) / n)
        idx = np.arange(n)
        m[idx, idx] += float(k["hold_p"])
        return vals, m

    sv, ms = comp_matrix(kernel["s"])
    cv, mc = comp_matrix(kernel["c"])
    qv, mq = comp_matrix(kernel["q"])
    gv, mg = comp_matrix(kernel["g"])
    states = [(a, b, cq, d) for a in sv for b in cv for cq in qv for d in gv]
    si = {v: i for i, v in enumerate(sv)}
    ci = {v: i for i, v in enumerate(cv)}
    qi = {v: i for i, v in enumerate(qv)}
    gi = {v: i for i, v in enumerate(gv)}
    P = np.ones((60, 60))
    for a, st0 in enumerate(states):
        for b, st1 in enumerate(states):
            P[a, b] = (ms[si[st0[0]], si[st1[0]]]
                       * mc[ci[st0[1]], ci[st1[1]]]
                       * mq[qi[st0[2]], qi[st1[2]]]
                       * mg[gi[st0[3]], gi[st1[3]]])
    assert np.allclose(P.sum(axis=1), 1.0)
    return states, P


def _interp_row(acc, row, e):
    i = int(np.searchsorted(acc, e, side="right")) - 1
    i = max(0, min(i, len(acc) - 2))
    fr = (e - acc[i]) / (acc[i + 1] - acc[i])
    fr = min(1.0, max(0.0, fr))
    return float(row[i] * (1 - fr) + row[i + 1] * fr), i


def rebal_reference(w, mu, sigma, fee, acc, row,
                    dense_domain, seg_cap, bud=None):
    """一个 REBAL 臂:真实账户结点切段独立参考(每片 checkpoint)。"""
    k = math.sqrt(3) * sigma
    x_lo, x_hi = mu - k, mu + k
    for xe in (x_lo, x_hi):
        if 1.0 + w * xe <= 0.0:
            raise ValueError("support violated at x=%r (w=%r)" % (xe, w))
    if w == 0.0:
        v0, i0 = _interp_row(acc, row, 0.0)
        return v0, [{"kind": "w0_degenerate",
                     "x_lo": x_lo, "x_hi": x_hi,
                     "account_index": i0, "a": v0, "b": 0.0,
                     "series_branch": False, "post_bound": 0.0}], 0.0
    e2_lo = RI.exposure_after(w, x_lo)
    e2_hi = RI.exposure_after(w, x_hi)
    pmin, pmax = min(e2_lo, e2_hi), max(e2_lo, e2_hi)
    if pmin < -dense_domain or pmax > dense_domain:
        raise ValueError("post outside dense domain: [%r,%r]" % (pmin, pmax))
    cuts = []
    for E in acc:
        if pmin < E < pmax:
            try:
                xc = RI.solve_x_at_exposure(w, float(E))
            except ValueError:
                continue
            if x_lo < xc < x_hi:
                cuts.append(xc)
    cuts.sort()
    dedup = []
    for x in cuts:
        if not dedup or x - dedup[-1] > 1e-12:
            dedup.append(x)
    if len(dedup) + 1 > seg_cap:
        raise ValueError("segment cap exceeded: %d" % (len(dedup) + 1))
    bounds = [x_lo] + dedup + [x_hi]
    xm = max(abs(x_lo), abs(x_hi))
    branch = bool(abs(w) * xm < RI.SERIES_EPS)
    segs = []
    total = 0.0
    bound_sum = 0.0
    for i in range(len(bounds) - 1):
        if bud is not None:
            why, _m = bud.checkpoint()
            if why:
                raise RuntimeError("budget(piece): %s" % why)
        xl, xh = bounds[i], bounds[i + 1]
        if xh - xl <= 0.0:
            raise ValueError("empty piece at %d" % i)
        pm = RI.exposure_after(w, 0.5 * (xl + xh))
        _v_at, ai = _interp_row(acc, row, pm)
        b = float((row[ai + 1] - row[ai]) / (acc[ai + 1] - acc[ai]))
        a = float(row[ai] - b * acc[ai])
        val, bnd = RI.seg_integral_bounded(a, b, w, None, None,
                                           fee=fee, k=k, x_lo=xl, x_hi=xh)
        total += val
        bound_sum += bnd
        segs.append({"x_lo": xl, "x_hi": xh,
                     "account_index": ai, "a": a, "b": b,
                     "node_row_value": float(row[ai]),
                     "series_branch": branch, "post_bound": bnd})
    return total, segs, bound_sum


def run(evidence_dir, manifest_path, out_dir,
        cfg_path=None, loader_np=None, clock=None):
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir, "RUNNING.marker")
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "root_reference.json")
    report = {"status": "running", "title": None,
              "certified_total_error": "not_certified",
              "course_gate": "not_frozen",
              "items": [], "root_diffs": {}, "root_meta": {}}
    bud = None
    try:
        cpath = cfg_path or os.path.join(HERE, CONFIG_NAME)
        got_cfg = _sha256_file(cpath)
        if got_cfg != CONFIG_SHA256:
            raise ValueError("CONFIG SHA mismatch: %s" % got_cfg)
        config = json.load(open(cpath, encoding="utf-8"))
        pd = _param_digest(config)
        if config.get("param_digest") != pd:
            raise ValueError("param digest mismatch")
        report["config_sha256"] = got_cfg
        report["param_digest"] = pd
        report["title"] = config["semantics"]["title"]
        pins = config["pins"]
        bud = JobBudget(config["budget_planned"], clock)
        got_man = _sha256_file(manifest_path)
        if got_man != pins["locked_manifest_sha256"]:
            raise ValueError("manifest SHA mismatch")
        tier_path = os.path.join(evidence_dir, "tier_L2.json")
        got_tier = _sha256_file(tier_path)
        if got_tier != pins["tier_L2_sha256"]:
            raise ValueError("tier SHA mismatch")
        man = json.load(open(manifest_path, encoding="utf-8"))
        v_sha = man["v_l2"]["sha256"]
        v_path = os.path.join(evidence_dir, "V_L2.npy")
        got_v = _sha256_file(v_path)
        if got_v != v_sha:
            raise ValueError("V_L2 SHA mismatch")
        got_ri = _sha256_file(os.path.join(HERE, "root_integrals.py"))
        if got_ri != pins["root_integrals_sha256"]:
            raise ValueError("root_integrals SHA mismatch")
        report["input_shas"] = {"locked_manifest": got_man,
                                "tier_L2": got_tier,
                                "V_L2": got_v,
                                "root_integrals": got_ri}
        tier = json.load(open(tier_path, encoding="utf-8"))
        tm = tier["tier_meta"]
        if (tm["dp_key"] != pins["dp_key"] or tm["gl"] != pins["gl"]
                or tm.get("budget", {}).get("tier") != pins["tier"]):
            raise ValueError("tier meta pin mismatch")
        acc = np.array(tm["accounts"], float)
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError("budget(post-sha): %s" % why)
        load = loader_np or np.load
        V = load(v_path)
        v_shape = tuple(pins.get("v_shape", (33, 60, 449)))
        if V.shape != v_shape:
            raise ValueError("V shape %r != %r" % (V.shape, v_shape))
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError("budget(post-V): %s" % why)
        states, P = build_P(config["kernel_frozen"])
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError("budget(post-P): %s" % why)
        qrows = {e["id"]: e for e in tier["questions"]}
        caps = config["caps"]
        seg_total = 0
        for qid in sorted(man["per_root"]):
            e = qrows[qid]
            state = (e["s"], e["c"], float(e["q"]), e["g"])
            si = states.index(state)
            t = e["remaining"]
            report["root_meta"][qid] = {"state": list(state),
                                        "remaining": t,
                                        "total": e["total"],
                                        "si": si}
            row = (P @ V[t - 1])[si]
            mu = e["s"] * e["c"] * float(e["q"]) * config["calib_frozen"]["mu"]
            sigma = config["calib_frozen"]["sigma_by_g"][str(e["g"])]
            fee = config["calib_frozen"]["fee"]
            v_hold, i0 = _interp_row(acc, row, 0.0)
            report["items"].append({
                "root": qid, "kind": "HOLD",
                "action_index": None, "action_value": None,
                "gl48_q": float(e["q_hold"]),
                "reference_value": v_hold,
                "diff": v_hold - float(e["q_hold"]),
                "segments": [{"kind": "hold_no_trade",
                              "account_index": i0, "lg": 0.0}]})
            why, _m = bud.checkpoint()
            if why:
                raise RuntimeError("budget(root-hold): %s" % why)
            for kind in ("best", "second"):
                lk = man["per_root"][qid][kind]
                w = float(lk["action"])
                val, segs, bsum = rebal_reference(
                    w, mu, sigma, fee, acc, row,
                    config["domains_frozen"]["dense_domain"],
                    caps["per_rebal_segments_max"], bud=bud)
                seg_total += len(segs)
                if seg_total > caps["total_segments_max"]:
                    raise ValueError("total seg cap")
                report["items"].append({
                    "root": qid, "kind": kind,
                    "action_index": lk["index"],
                    "action_value": w,
                    "gl48_q": lk["q"],
                    "reference_value": val,
                    "diff": val - lk["q"],
                    "post_bound_sum": bsum,
                    "segments": segs})
        for qid in sorted(man["per_root"]):
            items = {it["kind"]: it for it in report["items"]
                     if it["root"] == qid}
            rb = (items["best"]["reference_value"]
                  - items["HOLD"]["reference_value"])
            rs = (items["second"]["reference_value"]
                  - items["HOLD"]["reference_value"])
            rbs = (items["best"]["reference_value"]
                   - items["second"]["reference_value"])
            gb = (items["best"]["gl48_q"]
                  - items["HOLD"]["gl48_q"])
            gs = (items["second"]["gl48_q"]
                  - items["HOLD"]["gl48_q"])
            gbs = (items["best"]["gl48_q"]
                   - items["second"]["gl48_q"])
            report["root_diffs"][qid] = {
                "ref_best_minus_hold": rb,
                "ref_second_minus_hold": rs,
                "ref_best_minus_second": rbs,
                "gl48_best_minus_hold": gb,
                "gl48_second_minus_hold": gs,
                "gl48_best_minus_second": gbs,
                "delta_best_hold_vs_gl48": rb - gb,
                "delta_second_hold_vs_gl48": rs - gs,
                "delta_best_second_vs_gl48": rbs - gbs}
        report["n_items"] = len(report["items"])
        report["total_segments"] = seg_total
        report["status"] = "completed"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why, m = bud.checkpoint()
        if why:
            # 首个写后 why:立即记录并 raise(进现有失败收尾)
            report["budget_final"] = m
            report["measurement_point"] = "after_initial_main_save_guard1"
            raise RuntimeError("budget(post-save-guard1): %s" % why)
        report["budget_final"] = m
        report["measurement_point"] = "after_initial_main_save"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why2, m2 = bud.checkpoint()
        if why2:
            report["budget_final"] = m2
            report["measurement_point"] = "after_initial_main_save_guard2"
            raise RuntimeError("budget(post-save-guard2): %s" % why2)
        os.replace(marker, os.path.join(out_dir, "DONE.marker"))
        return report
    except BaseException as exc:
        orig = exc
        meas_err = None
        m_fin = None
        if bud is not None:
            try:
                _w, m_fin = bud.checkpoint()
            except Exception as e2:
                meas_err = repr(e2)
        try:
            report["status"] = "failed"
            report.setdefault("fail_reason", repr(orig))
            if m_fin:
                report["budget_final"] = m_fin
            if meas_err:
                report["measurement_error"] = meas_err
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1, allow_nan=False)
        except Exception:
            pass
        try:
            os.replace(marker, os.path.join(out_dir, "FAILED.marker"))
        except Exception:
            pass
        raise orig


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("usage: root_reference.py <evidence_dir> "
                         "<locked_manifest> <out_dir>")
    run(sys.argv[1], sys.argv[2], sys.argv[3])
