# -*- coding: utf-8 -*-
"""five_point — 固定 continuation 单状态单区间五点局部离散诊断
(PREPARED_NOT_RUN;真实 V/积分零运行,测试仅手写假表)。

数学(审查方 3817):
- C(w)=E[log(1+w·x)+R(post(w))],R=固定 [P@V30] si16 行插值,
  x=mu+√3σu;**费用每 (e,w) 重算**:denom=w>e?1+w·fee:1−w·fee,
  fee_frac=fee·|w−e|/denom;Q_REBAL(e,w)=C(w)+log1p(−fee_frac);
  Q_HOLD(e)=C(e)(w=e 零费);w=0 关仓(post=0);
  flat 恢复:Q_flat(w)=C(w)+log1p(−fee_frac(0,w))
  (等价 C=Q_flat_helper+log1p(fee·|w|));
- 161 C(w)+5 HOLD ≤166 唯一臂;五点各 162 动作=810 标量;
- F(e)=max 全臂;端点差 rL=V31(eL)−F(eL),rR 同;
  恒等式 I<e|V31>−F(e)=(1−λ)rL+λ·rR+[(1−λ)F(eL)+λF(eR)−F(e)]
  逐点核对;粗插值(仅端点)/细插值(端点+中点)在两四分点
  (未参与构造)评估有符号/绝对缺陷与比值;分母 0=不可比;
  中点构造恰零不算收敛;禁预设二阶/Richardson/经验上界认证。
缓存键绑输入 SHA/t/si/参数/P/网格/w/helper SHA;实例隔离。
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
CONFIG_NAME = "CONFIG_fivepoint.json"
CONFIG_SHA256 = "291a42af6d44b43ab767c4a941875fe3bb42b31b1ff6849afc81246fdfbfae56"


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def fee_frac(e, w, fee):
    denom = (1.0 + w * fee) if w > e else (1.0 - w * fee)
    return fee * abs((w - e) / denom)


class JobBudget:
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
    def comp(k):
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

    sv, ms = comp(kernel["s"])
    cv, mc = comp(kernel["c"])
    qv, mq = comp(kernel["q"])
    gv, mg = comp(kernel["g"])
    states = [(a, b, cq, d) for a in sv for b in cv
              for cq in qv for d in gv]
    si = {v: i for i, v in enumerate(sv)}
    ci = {v: i for i, v in enumerate(cv)}
    qi = {v: i for i, v in enumerate(qv)}
    gi = {v: i for i, v in enumerate(gv)}
    P = np.ones((60, 60))
    for a, s0 in enumerate(states):
        for b, s1 in enumerate(states):
            P[a, b] = (ms[si[s0[0]], si[s1[0]]]
                       * mc[ci[s0[1]], ci[s1[1]]]
                       * mq[qi[s0[2]], qi[s1[2]]]
                       * mg[gi[s0[3]], gi[s1[3]]])
    assert np.allclose(P.sum(axis=1), 1.0)
    return states, P


def _interp_row(acc, row, e):
    i = int(np.searchsorted(acc, e, side="right")) - 1
    i = max(0, min(i, len(acc) - 2))
    fr = (e - acc[i]) / (acc[i + 1] - acc[i])
    fr = min(1.0, max(0.0, fr))
    return float(row[i] * (1 - fr) + row[i + 1] * fr), i


def c_of_w(w, mu, sigma, acc, row,
           dense_domain, seg_cap,
           bud=None, consume_piece=None):
    """C(w)=E[log(1+wx)+R(post)](无费用;fee=0 纯 helper)。
    consume_piece:每次 RI 积分调用前预占计数(w0 计 1)。"""
    def _take_piece():
        if consume_piece is not None:
            consume_piece()
    k = math.sqrt(3) * sigma
    x_lo, x_hi = mu - k, mu + k
    for xe in (x_lo, x_hi):
        if 1.0 + w * xe <= 0.0:
            raise ValueError("support violated w=%r x=%r" % (w, xe))
    if w == 0.0:
        _take_piece()      # w0 常数贡献也计 1
        v0, i0 = _interp_row(acc, row, 0.0)
        return v0, [{"kind": "w0_degenerate",
                     "account_index": i0,
                     "series_branch": False,
                     "post_bound": 0.0,
                     "value": v0}], 0.0
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
    branch = bool(abs(w) * max(abs(x_lo), abs(x_hi)) < RI.SERIES_EPS)
    segs = []
    total = 0.0
    bsum = 0.0
    for i in range(len(bounds) - 1):
        if bud is not None:
            why, _m = bud.checkpoint()
            if why:
                raise RuntimeError("budget(piece): %s" % why)
        xl, xh = bounds[i], bounds[i + 1]
        pm = RI.exposure_after(w, 0.5 * (xl + xh))
        _v, ai = _interp_row(acc, row, pm)
        b = float((row[ai + 1] - row[ai]) / (acc[ai + 1] - acc[ai]))
        a = float(row[ai] - b * acc[ai])
        _take_piece()
        val, bnd = RI.seg_integral_bounded(a, b, w, None, None,
                                           fee=0.0, k=k,
                                           x_lo=xl, x_hi=xh)
        total += val
        bsum += bnd
        segs.append({"x_lo": xl, "x_hi": xh,
                     "account_index": ai, "a": a, "b": b,
                     "series_branch": branch,
                     "post_bound": bnd,
                     "value": val})
    return total, segs, bsum


class Ops:
    """操作前预留计数(arms/pieces/assembly):take 先检查
    used+1>cap 抛错再增 1;hit 不耗 arms/pieces。"""

    def __init__(self, caps):
        self.caps = caps
        self.used = {"arms": 0, "pieces": 0,
                     "assembly": 0}

    KEY = {"arms": "unique_arms_max",
           "pieces": "total_pieces_cap",
           "assembly": "assembly_scalars_cap"}

    def take(self, kind):
        cap = int(self.caps[self.KEY[kind]])
        if self.used[kind] + 1 > cap:
            raise ValueError(
                "%s cap exceeded: %d"
                % (kind, self.used[kind]))
        self.used[kind] += 1


class CCache:
    """C(w) 缓存:键绑身份元组;实例隔离。"""

    def __init__(self, ident):
        self.ident = json.dumps(
            ident, sort_keys=True,
            default=str)
        self.store = {}
        self.hits = 0
        self.miss = 0

    def key(self, w):
        return (self.ident, float(w))

    def get(self, w, compute):
        k = self.key(w)
        if k in self.store:
            self.hits += 1
            return self.store[k]
        self.miss += 1
        v = compute()
        self.store[k] = v
        return v


def evaluate_point(e, actions, hold_ws,
                   mu, sigma, acc, row,
                   dense_domain, seg_cap,
                   fee, cache, bud=None,
                   ops=None):
    """一个点 e:162 臂,逐臂显式 C/log_fee/片和闭包(可验算)。
    ops:每臂 emit 第一行先 take assembly(操作前预留)。"""
    out = {"e": e, "arms": {}}

    def cc(w):
        # 计数由 run 层 counting_get/cache 视图接管
        return cache.get(w, lambda: c_of_w(
            w, mu, sigma, acc, row,
            dense_domain, seg_cap, bud))

    def emit(key, w, e_ref):
        if ops is not None:
            ops.take("assembly")   # 先于取 C/组装
        Cw, segs, bsum = cc(float(w))
        ssum = sum(sg.get("value", 0.0)
                   for sg in segs)
        closure = abs(ssum - Cw)
        if closure > 1e-9:
            raise ValueError(
                "piece-sum closure %r" % closure)
        log_fee = (math.log1p(
                       -fee_frac(e_ref,
                                 float(w), fee))
                   if key.startswith("rebal")
                   else 0.0)   # w=e 零费
        q = Cw + log_fee
        out["arms"][key] = {
            "w": float(w), "q": q,
            "C": Cw, "log_fee": log_fee,
            "segments_sum": ssum,
            "closure": closure,
            "segments": segs,
            "post_bound_sum": bsum}
        return q

    for w in actions:
        emit("rebal:%d" % int(
            np.searchsorted(actions, w)),
            w, e)
    for we in hold_ws:
        emit("hold:%r" % we, we, we)
    qs = [(k, v["q"]) for k, v in
          out["arms"].items()]
    fmax = max(q for _k, q in qs)
    winners = sorted(k for k, q in qs
                     if q == fmax)
    out["F"] = fmax
    out["winners"] = winners
    return out


def interp_analysis(points, F, V31,
                    eL, eR):
    """端点差+恒等式+粗/细插值缺陷(四分点)。"""
    rL = V31[0] - F[0]
    rR = V31[4] - F[4]
    lam = [(e - eL) / (eR - eL)
           for e in points]
    ident = []
    for i, e in enumerate(points):
        iv = (1 - lam[i]) * V31[0] + lam[i] * V31[4]
        lhs = iv - F[i]
        rhs = ((1 - lam[i]) * rL + lam[i] * rR
               + ((1 - lam[i]) * F[0]
                  + lam[i] * F[4] - F[i]))
        ident.append({"e": e,
                      "lhs": lhs,
                      "rhs": rhs,
                      "closure": abs(lhs - rhs)})
    mid = points[2]
    res = {"rL": rL, "rR": rR,
           "identity": ident,
           "quartiles": []}
    for qi in (1, 3):
        eq = points[qi]
        lq = (eq - eL) / (eR - eL)
        coarse = (1 - lq) * F[0] + lq * F[4]
        if eq <= mid:
            lf = (eq - eL) / (mid - eL)
            fine = (1 - lf) * F[0] + lf * F[2]
        else:
            lf = (eq - mid) / (eR - mid)
            fine = (1 - lf) * F[2] + lf * F[4]
        dc = coarse - F[qi]
        dfn = fine - F[qi]
        if abs(dfn) == 0.0:
            ratio = "incomparable_zero_fine"
        elif abs(dc) == 0.0:
            ratio = "incomparable_zero_coarse"
        else:
            ratio = dc / dfn
        res["quartiles"].append({
            "e": eq, "coarse_minus_F": dc,
            "fine_minus_F": dfn,
            "abs_coarse": abs(dc),
            "abs_fine": abs(dfn),
            "ratio": ratio,
            "note": ("fine==0 at RETAINED "
                     "quartile: observation only; "
                     "only midpoint fine==0 is a "
                     "construction artifact — "
                     "neither is convergence "
                     "evidence" if dfn == 0.0
                     else "")})
    return res


class _CountingCacheView:
    """视图:计数 get 包裹真缓存(hits/miss 透传真缓存)。"""

    def __init__(self, get_fn, inner):
        self._get = get_fn
        self._inner = inner

    def get(self, w, compute):
        return self._get(w, compute)

    @property
    def hits(self):
        return self._inner.hits

    @property
    def miss(self):
        return self._inner.miss


def run(evidence_dir, lock_path,
        out_dir, cfg_path=None,
        loader_np=None, clock=None,
        evaluator=None):
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir, "RUNNING.marker")
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "five_point.json")
    report = {"status": "running",
              "course_gate": "not_frozen",
              "certified_total_error": "not_certified",
              "points": [], "analysis": None}
    bud = None
    try:
        cpath = cfg_path or os.path.join(HERE, CONFIG_NAME)
        got_cfg = _sha256_file(cpath)
        if got_cfg != CONFIG_SHA256:
            raise ValueError("CONFIG SHA mismatch: %s" % got_cfg)
        config = json.load(open(cpath, encoding="utf-8"))
        blob = json.dumps({k: config[k] for k in (
            "kernel_frozen", "calib_frozen",
            "domains_frozen", "caps",
            "budget_planned")},
            sort_keys=True, separators=(",", ":"),
            ensure_ascii=False)
        if config["param_digest"] != hashlib.sha256(
                blob.encode()).hexdigest():
            raise ValueError("param digest mismatch")
        report["config_sha256"] = got_cfg
        lock = json.load(open(lock_path, encoding="utf-8"))
        if _sha256_file(lock_path) != config["pins"]["lock_sha256"]:
            raise ValueError("lock SHA mismatch")
        tier_path = os.path.join(evidence_dir, "tier_L2.json")
        if _sha256_file(tier_path) != config["pins"]["tier_sha256"]:
            raise ValueError("tier SHA mismatch")
        v_path = os.path.join(evidence_dir, "V_L2.npy")
        if _sha256_file(v_path) != lock["v_sha256"]:
            raise ValueError("V SHA mismatch")
        got_ri = _sha256_file(os.path.join(HERE, "root_integrals.py"))
        if got_ri != config["pins"]["helper_sha256"]:
            raise ValueError("helper SHA mismatch")
        report["input_shas"] = {
            "lock": _sha256_file(lock_path),
            "tier": config["pins"]["tier_sha256"],
            "V": lock["v_sha256"],
            "helper": got_ri}
        bud = JobBudget(config["budget_planned"], clock)
        meta = json.load(open(tier_path,
                              encoding="utf-8"))["tier_meta"]
        if (meta["dp_key"] != config["pins"]["dp_key"]
                or len(meta["actions"]) != lock["n_actions"]
                or len(meta["accounts"]) != lock["n_accounts"]):
            raise ValueError("tier meta pin mismatch")
        actions = [float(x) for x in meta["actions"]]
        acc = np.array(meta["accounts"], float)
        load = loader_np or np.load
        V = load(v_path)
        if V.shape != tuple(config["pins"]["v_shape"]):
            raise ValueError("V shape %r" % (V.shape,))
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError("budget(post-load): %s" % why)
        states, P = build_P(config["kernel_frozen"])
        si = lock["si"]
        t = lock["t"]
        tf = lock["t_future"]
        # 仅形成 P[si]@V[tf] 这一行(不算全 P@V)
        row30 = P[si] @ V[tf]
        row31 = V[t][si]
        eL = lock["interval"]["eL"]
        eR = lock["interval"]["eR"]
        iL = lock["interval"]["iL"]
        iR = lock["interval"]["iR"]
        V31e = [float(row31[iL]), float(row31[iR])]
        cache = CCache({"inputs": report["input_shas"],
                        "t": t, "si": si,
                        "params": config["param_digest"],
                        "grid": (lock["n_actions"],
                                 lock["n_accounts"]),
                        "helper": got_ri})
        pts = lock["five_points"]
        caps = config["caps"]
        ops = Ops(caps)
        F = []
        ev = evaluator or c_of_w
        import inspect as _insp
        _ev_takes_consume = (
            "consume_piece"
            in _insp.signature(ev).parameters)
        base_get = cache.get

        def counting_get(w, compute):
            def counted():
                # 只在 cache miss 闭包先 take arms
                ops.take("arms")
                if _ev_takes_consume:
                    return ev(w, lock["mu"],
                              lock["sigma"], acc,
                              row30,
                              config["domains_frozen"]["dense_domain"],
                              caps["per_arm_segments_max"],
                              bud,
                              consume_piece=lambda:
                                  ops.take("pieces"))
                return ev(w, lock["mu"],
                          lock["sigma"], acc,
                          row30,
                          config["domains_frozen"]["dense_domain"],
                          caps["per_arm_segments_max"], bud)
            return base_get(w, counted)
        cview = _CountingCacheView(counting_get, cache)
        for e in pts:
            pt = evaluate_point(
                e, actions, [e],
                lock["mu"], lock["sigma"], acc,
                row30,
                config["domains_frozen"]["dense_domain"],
                caps["per_arm_segments_max"],
                config["calib_frozen"]["fee"],
                cview, bud, ops=ops)
            F.append(pt["F"])
            report["points"].append(pt)
            why, _m = bud.checkpoint()
            if why:
                raise RuntimeError("budget(point): %s" % why)
        report["cache_stats"] = {
            "hits": cache.hits, "miss": cache.miss}
        report["ops_used"] = dict(ops.used)
        report["ops_semantics"] = (
            "counts are pre-op reservations "
            "and completed amounts; cache hits "
            "consume neither arms nor pieces")
        an = interp_analysis(
            pts, F, [V31e[0]] + [None] * 3 + [V31e[1]],
            eL, eR)
        an["V31_endpoints"] = V31e
        # 逐点存 I[V31] 与粗/细插值值(可验算)
        for i, e in enumerate(pts):
            lam_i = (e - eL) / (eR - eL)
            report["points"][i]["I_V31"] = (
                (1 - lam_i) * V31e[0]
                + lam_i * V31e[1])
            report["points"][i]["coarse_at_e"] = (
                (1 - lam_i) * F[0] + lam_i * F[4])
            mid = pts[2]
            if e <= mid:
                lf = ((e - eL) / (mid - eL)
                      if mid > eL else 0.0)
                fine = (1 - lf) * F[0] + lf * F[2]
            else:
                lf = ((e - eR) / (mid - eR)
                      if eR > mid else 0.0)
                fine = (1 - lf) * F[4] + lf * F[2]
            report["points"][i]["fine_at_e"] = fine
        report["analysis"] = an
        report["n_assembled"] = ops.used["assembly"]
        report["total_pieces"] = ops.used["pieces"]
        report["status"] = "completed"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why, m = bud.checkpoint()
        if why:
            report["budget_final"] = m
            report["measurement_point"] = "guard1"
            raise RuntimeError("budget(post-save-guard1): %s" % why)
        report["budget_final"] = m
        report["measurement_point"] = "after_initial_main_save"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why2, m2 = bud.checkpoint()
        if why2:
            report["budget_final"] = m2
            report["measurement_point"] = "guard2"
            raise RuntimeError("budget(post-save-guard2): %s" % why2)
        os.replace(marker, os.path.join(out_dir, "DONE.marker"))
        return report
    except BaseException as exc:
        orig = exc
        try:
            report["status"] = "failed"
            report.setdefault("fail_reason", repr(orig))
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
        raise SystemExit("usage: five_point.py "
                         "<evidence_dir> <lock> <out_dir>")
    run(sys.argv[1], sys.argv[2], sys.argv[3])
