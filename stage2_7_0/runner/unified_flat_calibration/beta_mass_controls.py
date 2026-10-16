# -*- coding: utf-8 -*-
"""beta_mass_controls v4 — B 纯概率接口核验(p0policy 对齐,未运行整表)。

v4 局部修(审查方 3313):
- Ieps 精确:a==b==1→eps;a==1→−expm1(b·log1p(−eps));
  b==1→eps^a;其余 scipy betainc(CDF),无新造近似;
- decode/内部代表最终 float(np.float32(w));nudge 保留;
- case 参数用 inverse-softplus:raw=log(expm1(target−1))
  (target>1;target==1→raw=−100),softplus 稳定式
  max(x,0)+log1p(exp(−|x|));
- 严格校验:有限/branch 恰2/mix 恰4/αβ∈[1,500];
  allowed_atoms 去重;内部带正控/A 负控 allow_hold=False;
- 逐 case 完整记录(αβ/p/m/目标/allow/总概率+质量分解/
  P0 动作与命中/CDF/双档积分/差/状态);核镜像、同带
  matched vs opposite、A≤.5、不允许原子/HOLD 不计;
- 表工作前 digest 冻结;区间只计一次;节点逐档计;
  预算=每 job 实例隔离(JobBudget,不共享全局);主报告
  与终态一致(post-save 超限→主报告 failed 重写);
  唯一 CLI。
course_gate 恒 not_frozen。
"""
import hashlib
import json
import math
import os
import resource
import sys
import time

import numpy as np

STATUS = "PREPARED_NOT_RUN"
BUDGET = {"wall_s": 60.0, "cpu_s": 30.0,
          "rss_gib": 0.5}
EPS = 2.0 ** -25
NUDGE = 2.0 ** -149
TOL_INTEGRAL = 1e-6
TOL_ALGEBRA = 1e-12
AB_DOMAIN = (1.0, 500.0)
COURSE_GATE = "not_frozen"
QUAD_NODES = (4097, 8193)
QUAD_NODE_CAP = 786560
SEG_CAP = 64


def softplus(x):
    """稳定式 max(x,0)+log1p(exp(-|x|))。"""
    return (max(x, 0.0)
            + math.log1p(
                math.exp(-abs(x))))


def inv_softplus(target):
    """softplus(raw)=target−1 的 raw(target>1)。"""
    if target <= 1.0:
        return -100.0     # softplus→0 ⇒ 参数=1
    return math.log(
        math.expm1(target - 1.0))


def _log_softmax(logits):
    m = max(logits)
    ex = [math.exp(x - m)
          for x in logits]
    s = sum(ex)
    return [x - m - math.log(s)
            for x in logits]


def log_beta_ab(a, b):
    return (math.lgamma(a)
            + math.lgamma(b)
            - math.lgamma(a + b))


def _require_scipy():
    try:
        from scipy.stats import (
            beta as beta_dist)
        return beta_dist
    except Exception as exc:
        raise RuntimeError(
            "dependency unavailable: scipy "
            "required; no silent fallback "
            "(err=%r)" % (exc,)) from exc


def incbeta_eps(a, b):
    """I_ε(a,b) 精确分支(无新造近似)。"""
    if a == 1.0 and b == 1.0:
        return EPS
    if a == 1.0:
        return -math.expm1(
            b * math.log1p(-EPS))
    if b == 1.0:
        return EPS ** a
    return float(_require_scipy().cdf(
        EPS, a, b))


def log_incbeta_eps(a, b):
    return math.log(incbeta_eps(a, b))


def beta_interval_mass(a, b, lo, hi):
    """Fixed lower/upper-tail evaluation, with no adaptive integration."""
    if not (0.0 <= lo < hi <= 1.0):
        raise ValueError("invalid beta interval")
    if a == 1.0 and b == 1.0:
        return hi - lo
    dist = _require_scipy()
    c_lo = float(dist.cdf(lo, a, b))
    c_hi = float(dist.cdf(hi, a, b))
    if c_lo >= 0.5:
        value = float(dist.sf(lo, a, b) - dist.sf(hi, a, b))
    else:
        value = c_hi - c_lo
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("unreliable beta interval mass: %r" % value)
    return value


class JobBudget:
    """每 job 实例隔离的预算(时钟可注入;节点/段逐档计)。"""

    def __init__(self, clock=None):
        self.nw, self.nc = (
            clock if clock is not None
            else (time.perf_counter,
                  time.process_time))
        self.wall0 = self.nw()
        self.cpu0 = self.nc()
        self.nodes = 0
        self.segs = 0

    def add_quad(self, nodes):
        if nodes not in QUAD_NODES:
            raise ValueError(
                "nodes must be %r"
                % (QUAD_NODES,))
        self.nodes += nodes

    def add_segment(self):
        self.segs += 1

    def checkpoint(self):
        wall = self.nw() - self.wall0
        cpu = self.nc() - self.cpu0
        rss = resource.getrusage(
            resource.RUSAGE_SELF
        ).ru_maxrss / (1024 * 1024)
        why = None
        if wall > BUDGET["wall_s"]:
            why = "wall_clock"
        elif cpu > BUDGET["cpu_s"]:
            why = "cpu"
        elif rss > BUDGET["rss_gib"]:
            why = "rss"
        elif self.nodes > QUAD_NODE_CAP:
            why = "node_cap"
        elif self.segs > SEG_CAP:
            why = "segment_cap"
        return why, {
            "wall_s": wall, "cpu_s": cpu,
            "rss_gib": rss,
            "nodes": self.nodes,
            "segments": self.segs}


class BAsymMixture:
    """单非对称 Beta 策略混合(独立 α,β;softplus+1)。"""

    def __init__(self, branch_logits,
                 mix_logits, alpha_raw,
                 beta_raw):
        if len(branch_logits) != 2:
            raise ValueError(
                "branch dim must be 2")
        if len(mix_logits) != 4:
            raise ValueError(
                "mix dim must be 4")
        vals = list(branch_logits) + list(
            mix_logits) + [alpha_raw,
                           beta_raw]
        if not all(
                math.isfinite(float(v))
                for v in vals):
            raise ValueError(
                "non-finite inputs")
        self.p_hold, self.p_rebal = [
            math.exp(v) for v in
            _log_softmax(
                [float(v) for v in
                 branch_logits])]
        self.m = [math.exp(v)
                  for v in _log_softmax(
                      [float(v) for v in
                       mix_logits])]
        self.alpha = softplus(
            float(alpha_raw)) + 1.0
        self.beta = softplus(
            float(beta_raw)) + 1.0
        for nm, v in (("alpha",
                       self.alpha),
                      ("beta",
                       self.beta)):
            if not (AB_DOMAIN[0]
                    <= v
                    <= AB_DOMAIN[1]):
                raise ValueError(
                    "%s=%r outside [%g,%g]"
                    % (nm, v, *AB_DOMAIN))
        if abs(sum(self.m) - 1.0) \
                > TOL_ALGEBRA:
            raise ValueError(
                "mix not normalized")
        if abs(self.p_hold
               + self.p_rebal - 1.0) \
                > TOL_ALGEBRA:
            raise ValueError(
                "branch not normalized")
        self.Qlo = incbeta_eps(
            self.alpha, self.beta)
        self.Qhi = incbeta_eps(
            self.beta, self.alpha)
        self.b0 = math.exp(
            -(self.alpha + self.beta
              - 2.0) * math.log(2.0)
            - log_beta_ab(self.alpha,
                          self.beta)
            - 150.0 * math.log(2.0))
        self.Z = max(
            1.0 - self.Qlo - self.Qhi
            - self.b0, 1e-12)
        m3 = self.m[3]
        self.C = [
            self.m[0] + m3 * self.Qlo,
            self.m[1] + m3 * self.b0,
            self.m[2] + m3 * self.Qhi,
            m3 * self.Z]

    def interior_representative(self):
        denom = (self.alpha
                 + self.beta - 2.0)
        u = (0.5 if denom <= 1e-12
             else (self.alpha - 1.0)
             / denom)
        u = min(1.0 - EPS,
                max(EPS, u))
        w = 2.0 * u - 1.0
        if float(np.float32(w)) \
                == 0.0:
            w = (NUDGE if u >= 0.5
                 else -NUDGE)
        return float(np.float32(w))

    def decode(self):
        if self.p_hold >= \
                self.p_rebal:
            return ("HOLD", 0.0)
        idx = self.C.index(
            max(self.C))
        if idx == 3:
            return ("REBAL",
                    self.
                    interior_representative())
        return ("REBAL",
                (-1.0, 0.0, 1.0)[idx])

    def band_decomposition(
            self, w_lo, w_hi,
            allow_hold=True,
            allowed_atoms=()):
        if not (-1.0 < w_lo
                < w_hi < 1.0):
            raise ValueError(
                "band inside (-1,1)")
        if w_lo * w_hi <= 0.0:
            raise ValueError(
                "single-side band")
        atoms = sorted(set(
            float(a)
            for a in allowed_atoms))
        for a in atoms:
            if a not in (-1.0, 0.0,
                         1.0):
                raise ValueError(
                    "bad atom %r"
                    % (a,))
        u_lo = (w_lo + 1.0) / 2.0
        u_hi = (w_hi + 1.0) / 2.0
        if not (EPS < u_lo < u_hi
                < 1.0 - EPS):
            raise ValueError(
                "band outside "
                "interior zone")
        hold_p = (self.p_hold
                  if allow_hold
                  else 0.0)
        atom_idx = {-1.0: 0,
                    0.0: 1, 1.0: 2}
        atoms_p = sum(
            self.p_rebal * self.C[
                atom_idx[a]]
            for a in atoms)
        cont = beta_interval_mass(self.alpha, self.beta, u_lo, u_hi)
        interior_p = (self.p_rebal
                      * self.m[3]
                      * cont)
        return {
            "total": (hold_p
                      + atoms_p
                      + interior_p),
            "hold": hold_p,
            "atoms": atoms_p,
            "atoms_list": atoms,
            "interior": interior_p,
            "band_cont_mass":
                cont}


def build_case_table():
    """匹配正控 κ∈{32,128}(α=1+κu*,β=1+κ(1−u*),
    **经 inverse-softplus raw**);镜像=换 α/β+m−/m++
    翻带;相反负控=仅换参数不翻带;A 对称负控单列;
    内部带正控/A 负控 allow_hold=False。"""
    cases = []
    for kappa in (32.0, 128.0):
        for w in (0.3, 0.55,
                  -0.45, -0.62):
            u = (1.0 + w) / 2.0
            a = 1.0 + kappa * u
            b = 1.0 + kappa * (1 - u)
            lo, hi = (u - 0.08,
                      u + 0.08)
            band = (2 * lo - 1,
                    2 * hi - 1)
            common = {
                "branch": [-8, 8],
                "mix": [-6, -8, -9, 8],
                "kappa": kappa,
                "allow_hold": False}
            cases.append({
                "kind": "matched_pos",
                "alpha_raw":
                    inv_softplus(a),
                "beta_raw":
                    inv_softplus(b),
                "band": list(band),
                **common})
            cases.append({
                "kind": "mirror",
                "alpha_raw":
                    inv_softplus(b),
                "beta_raw":
                    inv_softplus(a),
                "mix": [-9, -8, -6, 8],
                "band": [-band[1],
                         -band[0]],
                "branch": [-8, 8],
                "kappa": kappa,
                "allow_hold": False})
            cases.append({
                "kind": "opposite_neg",
                "alpha_raw":
                    inv_softplus(b),
                "beta_raw":
                    inv_softplus(a),
                "band": list(band),
                **common})
    for kappa in (32.0, 128.0):
        cases.append({
            "kind": "sym_A_neg",
            "alpha_raw":
                inv_softplus(
                    1.0 + kappa / 2),
            "beta_raw":
                inv_softplus(
                    1.0 + kappa / 2),
            "branch": [-8, 8],
            "mix": [-6, -8, -9, 8],
            "band": [0.42, 0.58],
            "kappa": kappa,
            "allow_hold": False})
    for ah in (True, False):
        for atoms in ((), (1.0,),
                      (1.0, 0.0)):
            cases.append({
                "kind": "allow_config",
                "alpha_raw":
                    inv_softplus(4.0),
                "beta_raw":
                    inv_softplus(6.0),
                "branch": [-8, 8],
                "mix": [-6, -8, -9, 8],
                "band": [0.5, 0.7],
                "allow_hold": ah,
                "allowed_atoms":
                    list(atoms)})
    return cases


CASE_TABLE = build_case_table()


def table_digest():
    """工作前冻结表 digest(结构化序列化)。"""
    blob = json.dumps(
        CASE_TABLE, sort_keys=True,
        separators=(",", ":"))
    return hashlib.sha256(
        blob.encode()).hexdigest()


def table_stats():
    return {"cases":
                len(CASE_TABLE),
            "segments":
                len(CASE_TABLE)}


def validate_case_table():
    st = table_stats()
    assert st["segments"] \
        <= SEG_CAP
    plan = st["segments"] * sum(
        QUAD_NODES)
    assert plan <= QUAD_NODE_CAP
    kinds = {}
    for c in CASE_TABLE:
        kinds[c["kind"]] = \
            kinds.get(c["kind"],
                      0) + 1
    return {**st, "kinds": kinds,
            "planned_nodes": plan,
            "digest": table_digest()}


def pair_control_diagnostics(results):
    """Only the eight declared triples; no fitted probability threshold."""
    pairs = []
    for start in range(0, 24, 3):
        matched, mirror, opposite = results[start:start + 3]
        if [r["kind"] for r in (matched, mirror, opposite)] != [
                "matched_pos", "mirror", "opposite_neg"]:
            raise ValueError("fixed control triple changed")
        mirror_diff = abs(matched["total"] - mirror["total"])
        delta = matched["total"] - opposite["total"]
        pairs.append({
            "ids": [matched["id"], mirror["id"], opposite["id"]],
            "matched_total": matched["total"],
            "mirror_total": mirror["total"],
            "opposite_same_band_total": opposite["total"],
            "mirror_absdiff": mirror_diff,
            "mirror_within_numeric_tol": mirror_diff <= TOL_ALGEBRA,
            "matched_minus_opposite": delta,
            "ordering_positive": delta > 0.0,
            "all_numerically_valid": all(
                r["within_tol"] for r in (matched, mirror, opposite)),
            "interpretation": "diagnostic only; no curriculum gate"})
    return pairs


def run_diagnostics(out_dir,
                    loader=None,
                    integrator=None,
                    budget=None,
                    post_save_probe=None):
    """整份固定表诊断(准备段**不调用**)。每 job 独立
    JobBudget;post-save 真实在写主报告**之后**检查;超限
    →主报告权威改写 failed(与终态一致)+PARTIAL 保留。"""
    os.makedirs(out_dir,
                exist_ok=False)
    marker = os.path.join(
        out_dir, "RUNNING.marker")
    fd = os.open(marker,
                 os.O_CREAT | os.O_EXCL
                 | os.O_WRONLY)
    os.close(fd)
    bud = budget or JobBudget()
    results = []
    main_path = os.path.join(
        out_dir, "beta_diag.json")
    out = None
    try:
        digest = table_digest()
        stats = validate_case_table()
        load = loader or (
            lambda c:
                BAsymMixture(
                    c["branch"],
                    c["mix"],
                    c["alpha_raw"],
                    c["beta_raw"]))
        integ = integrator or (
            lambda m, lo, hi, n, b:
                m.quad_band(
                    lo, hi, n, b))

        def mass(m, case):
            return m.band_decomposition(
                case["band"][0],
                case["band"][1],
                allow_hold=case.get(
                    "allow_hold",
                    True),
                allowed_atoms=tuple(
                    case.get(
                        "allowed_atoms",
                        ())))

        for i, case in enumerate(
                CASE_TABLE):
            bud.add_segment()
            why, _m = bud.checkpoint()
            if why:
                raise RuntimeError("budget: %s" % why)
            mix = load(case)
            decomp = mass(mix, case)
            tag, w = mix.decode()
            in_band = (case["band"][0]
                       <= w
                       <= case["band"][1])
            row = {
                "id": i,
                "kind": case["kind"],
                "alpha": mix.alpha,
                "beta": mix.beta,
                "p": [mix.p_hold,
                      mix.p_rebal],
                "m": mix.m,
                "band":
                    case["band"],
                "allow_hold":
                    case.get(
                        "allow_hold",
                        True),
                "allowed_atoms":
                    sorted(set(
                        case.get(
                            "allowed_atoms",
                            ()), )),
                "total":
                    decomp["total"],
                "mass_split": {
                    "hold":
                        decomp["hold"],
                    "atoms":
                        decomp["atoms"],
                    "interior":
                        decomp[
                            "interior"]},
                "p0_action":
                    [tag, w],
                "hit_band": in_band,
                "cdf":
                    decomp[
                        "band_cont_mass"]}
            for nodes in QUAD_NODES:
                q = integ(mix,
                          case["band"][0],
                          case["band"][1],
                          nodes, bud)
                row["quad_%d"
                    % nodes] = q
                row["absdiff_%d"
                    % nodes] = abs(
                    q - row["cdf"])
            row["quad_level_diff"] = abs(
                row["quad_4097"] - row["quad_8193"])
            if not all(math.isfinite(v) for v in (
                    row["total"], row["cdf"], row["quad_4097"],
                    row["quad_8193"], *row["mass_split"].values())):
                raise ValueError("non-finite probability result in case %d" % i)
            row["within_tol"] = all(
                row["absdiff_%d" % n]
                <= TOL_INTEGRAL
                for n in QUAD_NODES) and row["quad_level_diff"] <= TOL_INTEGRAL
            # 类级校验
            k = case["kind"]
            checks = {}
            if k == "sym_A_neg":
                checks["a_le_half"] \
                    = (decomp["total"]
                       <= 0.5
                       + TOL_INTEGRAL)
            if not case.get(
                    "allow_hold",
                    True):
                checks[
                    "hold_"
                    "not_counted"] = (
                    decomp["hold"]
                    == 0.0)
            if not row["allowed_atoms"]:
                checks["atoms_not_counted"] = decomp["atoms"] == 0.0
            checks["atoms_explicit"] = (
                decomp["atoms_list"] == row["allowed_atoms"])
            checks["mass_decomposition"] = abs(
                row["total"] - sum(row["mass_split"].values())) <= TOL_ALGEBRA
            checks["probability_range"] = 0.0 <= row["total"] <= 1.0
            row["checks"] = checks
            results.append(row)
            why, _m = (
                bud.checkpoint())
            if why:
                raise RuntimeError(
                    "budget: %s" % why)
        why, meters = (
            bud.checkpoint())
        if why:
            raise RuntimeError(
                "budget(pre-save):"
                " %s" % why)
        out = {
            "status": "completed",
            "results": results,
            "pair_controls": pair_control_diagnostics(results),
            "stats": stats,
            "table_digest": digest,
            "budget_final":
                meters,
            "course_gate":
                COURSE_GATE}
        with open(main_path, "w",
                  encoding="utf-8") \
                as f:
            json.dump(out, f,
                      indent=1,
                      allow_nan=False)
        # 真实 post-save(主报告已落盘)
        if post_save_probe:
            post_save_probe()
        why, meters = (
            bud.checkpoint())
        if why:
            out["fail_reason"] = "post_save:%s" % why
            raise RuntimeError("budget(post-save): %s" % why)
        out["budget_final"] = meters
        out["budget_measurement"] = "after_initial_main_save"
        with open(main_path, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=1, allow_nan=False)
        why, _ = bud.checkpoint()
        if why:
            raise RuntimeError("budget(final-metadata-save): %s" % why)
        os.replace(marker,
                   os.path.join(
                       out_dir,
                       "DONE.marker"))
        return out
    except BaseException as exc:
        try:
            _why, meters = bud.checkpoint()
        except BaseException as measurement_exc:
            # Failure reporting must not lose the original error if measurement fails.
            meters = dict((out or {}).get("budget_final", {}))
            meters["measurement_error"] = repr(measurement_exc)
            meters["measurement_point"] = "failure_read_unavailable"
        failure = {"status": "failed", "reason": repr(exc),
                   "budget_final": meters, "partial_results": results}
        try:
            with open(os.path.join(out_dir, "PARTIAL.json"),
                      "w", encoding="utf-8") as f:
                json.dump(failure, f, indent=1, allow_nan=False)
        except Exception:
            pass
        if out is not None:
            out.update(status="failed", fail_reason=out.get("fail_reason", repr(exc)),
                       budget_final=meters)
            try:
                with open(main_path, "w", encoding="utf-8") as f:
                    json.dump(out, f, indent=1, allow_nan=False)
            except Exception:
                pass
        try:
            if os.path.exists(marker):
                os.replace(marker, os.path.join(out_dir, "FAILED.marker"))
        except Exception:
            pass
        raise


class _QuadCompat:
    """占位说明:quad_band 由实例方法承担(见下)。"""


def _quad_band(self, w_lo, w_hi,
               nodes, budget):
    if nodes not in QUAD_NODES:
        raise ValueError(
            "nodes must be %r"
            % (QUAD_NODES,))
    u_lo = (w_lo + 1.0) / 2.0
    u_hi = (w_hi + 1.0) / 2.0
    budget.add_quad(nodes)
    why, _m = budget.checkpoint()
    if why:
        raise RuntimeError(
            "budget/node guard:"
            " %s" % why)
    if self.alpha == 1.0 \
            and self.beta == 1.0:
        return u_hi - u_lo
    dist = _require_scipy()
    grid = np.linspace(
        u_lo, u_hi, nodes)
    pdf = np.exp(
        dist.logpdf(
            grid, self.alpha,
            self.beta))
    return float(np.trapezoid(
        pdf, grid))


BAsymMixture.quad_band = \
    _quad_band


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: beta_mass_"
            "controls.py <out_dir>")
    run_diagnostics(sys.argv[1])
