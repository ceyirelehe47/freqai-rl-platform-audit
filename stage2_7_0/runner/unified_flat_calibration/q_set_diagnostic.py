# -*- coding: utf-8 -*-
"""q_set_diagnostic v3 — 离散近优集合区分幅度(纯 JSON,未运行)。

v3 修正:事前固定 EXPECTED_MANIFEST(SHA 逐件比较,含实际消费
的 analysis_v2);纯 JSON 加载(不读 V、不 import 后端);先验
原始列表(64 题 ID/重复/规范身份)再建 dict;根 Q 全有限;
按已验证 actions 逐键取 Q(不依赖 dict 顺序);公共 41 点按
索引/坐标显式对齐(不用 set 交集隐藏缺点);尾题实际核
HOLD/REBAL0 零 regret、非零动作正 regret;输出
course_gate=not_frozen 与离散界限。
"""
import hashlib
import json
import math
import os
import resource
import sys
import time

STATUS = "PREPARED_NOT_RUN"
BUDGET = {"wall_s": 60.0, "cpu_s": 30.0,
          "rss_gib": 0.5}
COURSE_GATE = "not_frozen"

# 事前固定 expected manifest(取自已验收官方运行的
# files_sha.txt;A 实际消费=三份 tier JSON+analysis+
# analysis_v2;纯 JSON,不读 V)
EXPECTED_MANIFEST = {
    "tier_L0.json":
        "44ac553071540b77c03596b317d3d53a3a5472be0c89dbd4d4715a1b9c6d52bd",
    "tier_L1.json":
        "67eca43493b006980582a061e771ab07e642ff4155c45b8f230be850a68575b6",
    "tier_L2.json":
        "124eb67c5f63cd3cc8fd5dfe83ac8e71fab54dd1e907755202413de0fa3277c7",
    "analysis.json":
        "a1cf968723171810b9e6167f9c0f170c8c7bc3f00f4d6ed02d5386bd5299778e",
    "analysis_v2.json":
        "edfdc25efccdde40c0329b7925f74b98b49e87fe961390c8a140b999ad6bef64",
}
CONSUMED = tuple(EXPECTED_MANIFEST)

PAIRS = {
    "s_minus_g0_q075_vs_q100":
        ("G017", "G019"),
    "s_minus_g1_q075_vs_q100":
        ("G018", "G020"),
    "s_plus_g0_q075_vs_q100":
        ("G057", "G059"),
    "s_plus_g1_q075_vs_q100":
        ("G058", "G060")}
TAIL_IDS = ("T061", "T062", "T063",
            "T064")

# 规范 64 题(嵌入冻结常量;不 import 后端)
def _canonical_questions():
    qs = []
    for s in (-1, 0, 1):
        for c in (0, 1):
            for q in (0.0, 0.25, 0.5,
                      0.75, 1.0):
                for g in (0, 1):
                    qs.append({
                        "id": "G%03d"
                        % (len(qs) + 1),
                        "s": s, "c": c,
                        "q": q, "g": g,
                        "remaining": 32,
                        "total": 32})
    for s in (-1, 1):
        for g in (0, 1):
            qs.append({
                "id": "T%03d"
                % (len(qs) + 1),
                "s": s, "c": 1,
                "q": 1.0, "g": g,
                "remaining": 1,
                "total": 32})
    return tuple(
        tuple(sorted(q.items(),
                     key=lambda kv:
                     kv[0]))
        for q in qs)


CANONICAL = _canonical_questions()
CANONICAL_IDS = [dict(c)["id"]
                 for c in CANONICAL]

class JobBudget:
    """每 job 实例隔离预算(时钟可注入)。"""

    def __init__(self, clock=None):
        self.nw, self.nc = (
            clock if clock
            is not None
            else (time.perf_counter,
                  time.process_time))
        self.wall0 = self.nw()
        self.cpu0 = self.nc()

    def checkpoint(self):
        wall = (self.nw()
                - self.wall0)
        cpu = (self.nc()
               - self.cpu0)
        rss = (resource
               .getrusage(
                   resource
                   .RUSAGE_SELF)
               .ru_maxrss
               / (1024 * 1024))
        why = None
        if wall > BUDGET[
                "wall_s"]:
            why = "wall_clock"
        elif cpu > BUDGET[
                "cpu_s"]:
            why = "cpu"
        elif rss > BUDGET[
                "rss_gib"]:
            why = "rss"
        return why, {
            "wall_s": wall,
            "cpu_s": cpu,
            "rss_gib": rss}


_now_rss_gib = None  # (由 JobBudget 承担)


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(
                lambda: f.read(1 << 20),
                b""):
            h.update(chunk)
    return h.hexdigest()


def verify_manifest(evidence_dir):
    """事前固定 manifest 逐件比较(错配即拒)。"""
    bad = []
    for name, want in \
            EXPECTED_MANIFEST.items():
        got = _sha256_file(
            os.path.join(
                evidence_dir, name))
        if got != want:
            bad.append((name, got,
                        want))
    if bad:
        raise ValueError(
            "manifest mismatch: %r"
            % bad)


def load_tier_json(evidence_dir, tier):
    """纯 JSON 加载;先验原始列表再建 dict。"""
    with open(os.path.join(
            evidence_dir,
            "tier_%s.json" % tier),
            encoding="utf-8") as f:
        d = json.load(f)
    tm = d["tier_meta"]
    raw = d["questions"]

    def dec(x):
        if x == "+inf":
            return math.inf
        if x == "-inf":
            return -math.inf
        return float(x)

    rows = []
    for e in raw:
        rows.append({
            "id": e["id"], "s": e["s"],
            "c": e["c"], "q": e["q"],
            "g": e["g"],
            "remaining":
                e["remaining"],
            "total": e["total"],
            "q_hold": dec(e["q_hold"]),
            "q_rebals": {
                float(k): dec(v)
                for k, v in
                e["q_rebals"].items()}})
    return tm, rows


def validate_rows(raw_rows):
    """先验原始列表:64 题 ID 精确序/无重复/规范身份。"""
    if len(raw_rows) != 64:
        raise ValueError(
            "not 64 questions: %d"
            % len(raw_rows))
    ids = [r["id"] for r in raw_rows]
    if ids != CANONICAL_IDS:
        dups = len(ids) - len(
            set(ids))
        missing = [i for i in
                   CANONICAL_IDS
                   if i not in ids]
        raise ValueError(
            "id order/duplicates "
            "broken: missing=%r "
            "dups=%d"
            % (missing[:4], dups))
    for r, canon in zip(
            raw_rows, CANONICAL):
        c = dict(canon)
        for f in ("s", "c", "q",
                  "g", "remaining",
                  "total"):
            if r[f] != c[f]:
                raise ValueError(
                    "canonical identity "
                    "mismatch %s.%s=%r "
                    "want %r"
                    % (r["id"], f,
                       r[f], c[f]))
        # 根 Q 全有限
        if not math.isfinite(
                r["q_hold"]):
            raise ValueError(
                "non-finite q_hold %s"
                % r["id"])
        for w, v in r[
                "q_rebals"].items():
            if not math.isfinite(v):
                raise ValueError(
                    "non-finite Q %s@%r"
                    % (r["id"], w))


def q_by_action(row, actions):
    """按已验证 actions 逐键取 Q(不依赖 dict 顺序)。"""
    out = []
    for w in actions:
        if w not in row["q_rebals"]:
            raise ValueError(
                "action %r missing in "
                "%s" % (w, row["id"]))
        out.append(
            row["q_rebals"][w])
    return out


def regret_row(q_hold, q_list):
    vals = list(q_list) + [q_hold]
    if not all(math.isfinite(v)
               for v in vals):
        raise ValueError(
            "non-finite Q in regret")
    maxq = max(vals)
    return ([maxq - v
             for v in q_list],
            maxq - q_hold)


def common_align(actions_by_tier):
    """公共 41 点按索引显式对齐:i↔2i↔4i,坐标逐点相等。"""
    ns = {t: len(a) for t, a in
          actions_by_tier.items()}
    if ns != {"L0": 41, "L1": 81,
              "L2": 161}:
        raise ValueError(
            "grid sizes %r" % ns)
    for i in range(41):
        cs = [actions_by_tier[t][
                  {"L0": i,
                   "L1": 2 * i,
                   "L2": 4 * i}[t]]
              for t in ("L0", "L1",
                        "L2")]
        want = -1.0 + 2.0 * i / 40.0
        for c in cs:
            if abs(c - want) > 1e-15:
                raise ValueError(
                    "common coord "
                    "misalign i=%d %r"
                    % (i, cs))


def pair_taus(R_a, R_b):
    if not R_a or not R_b:
        return {"window": None,
                "reason":
                    "empty regret set"}
    keys = sorted(set(R_a)
                  & set(R_b))
    if not keys:
        return {"window": None,
                "reason":
                    "no common points"}
    min_a = min(R_a[k]
                for k in keys)
    min_b = min(R_b[k]
                for k in keys)
    tau_n = max(min_a, min_b)
    best_k = min(
        keys, key=lambda k:
        max(R_a[k], R_b[k]))
    tau_o = max(R_a[best_k],
                R_b[best_k])
    window = ([tau_n, tau_o]
              if tau_n < tau_o
              else None)
    return {
        "tau_nonempty": tau_n,
        "tau_overlap": tau_o,
        "window": window,
        "lower_closed": True,
        "upper_closed": False,
        "first_overlap_point":
            best_k,
        "reason": None if window
        else "nonempty>=overlap"}


def tail_nonzero_summary(per_tier, zero_indices):
    """Exclude REBAL0 by action index, never by the regret value."""
    values = [v for tier in ("L0", "L1", "L2")
              for j, v in enumerate(per_tier[tier])
              if j != zero_indices[tier]]
    return {
        "all_nonzero_positive": bool(values) and all(
            math.isfinite(v) and v > 0.0 for v in values),
        "min_nonzero_regret": min(values) if values else None,
        "nonzero_action_count": len(values)}


def run(evidence_dir, out_dir):
    """真实诊断入口(准备段**不调用**)。"""
    os.makedirs(out_dir,
                exist_ok=False)
    marker = os.path.join(
        out_dir, "RUNNING.marker")
    fd = os.open(marker,
                 os.O_CREAT | os.O_EXCL
                 | os.O_WRONLY)
    os.close(fd)
    bud = JobBudget()
    partial = {"regrets": {},
               "tails": {},
               "pairs": {}}
    report = None
    report_path = os.path.join(out_dir, "q_set_report.json")
    try:
        verify_manifest(evidence_dir)
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError(
                "budget: %s" % why)
        tiers = {}
        actions_by_tier = {}
        for tier in ("L0", "L1",
                     "L2"):
            tm, rows = load_tier_json(
                evidence_dir, tier)
            validate_rows(rows)
            tiers[tier] = {
                r["id"]: r
                for r in rows}
            actions_by_tier[
                tier] = [
                float(x) for x in
                tm["actions"]]
        common_align(
            actions_by_tier)
        why, _m = bud.checkpoint()
        if why:
            raise RuntimeError(
                "budget: %s" % why)
        regrets = {}
        for qid in CANONICAL_IDS:
            per = {}
            hold = {}
            for tier in ("L0",
                         "L1", "L2"):
                row = tiers[
                    tier][qid]
                qs = q_by_action(
                    row,
                    actions_by_tier[
                        tier])
                reg, reg_h = \
                    regret_row(
                        row["q_hold"],
                        qs)
                per[tier] = reg
                hold[tier] = reg_h
            common = [
                max(per["L0"][i],
                    per["L1"][2 * i],
                    per["L2"][
                        4 * i])
                for i in range(41)]
            regrets[qid] = {
                "common_R": common,
                "discrete_bounds":
                    [min(common),
                     max(common)],
                "per_tier": per,
                "hold": hold}
            partial["regrets"][
                qid] = {
                "common_R":
                    common,
                "discrete_bounds":
                    [min(common),
                     max(common)]}
            why, _m = (
                bud.checkpoint())
            if why:
                raise RuntimeError(
                    "budget: %s"
                    % why)
        # 尾题负控(实际核):每个非零格点 regret 都为正
        tail_check = {}
        for qid in TAIL_IDS:
            r = regrets[qid]
            zero_ok = all(
                abs(r["hold"][t])
                < 1e-15 for t in
                ("L0", "L1", "L2"))
            z_idx = {"L0": 20,
                     "L1": 40,
                     "L2": 80}
            rebal0_ok = all(
                abs(r["per_tier"][
                        t][z_idx[t]])
                < 1e-15
                for t in ("L0", "L1",
                          "L2"))
            nonzero = tail_nonzero_summary(r["per_tier"], z_idx)
            all_pos = nonzero["all_nonzero_positive"]
            tail_check[qid] = {
                "hold_zero_regret":
                    zero_ok,
                "rebal0_zero_regret":
                    rebal0_ok,
                "all_nonzero_positive":
                    all_pos,
                "min_nonzero_regret":
                    nonzero["min_nonzero_regret"],
                "nonzero_action_count":
                    nonzero["nonzero_action_count"]}
            partial["tails"][
                qid] = \
                tail_check[qid]
            if not (zero_ok
                    and rebal0_ok
                    and all_pos):
                raise ValueError(
                    "tail negative "
                    "control failed "
                    "%s: %r"
                    % (qid,
                       tail_check[
                           qid]))
        pairs_out = {}
        for name, (qa, qb) in \
                PAIRS.items():
            Ra = dict(enumerate(
                regrets[qa]
                ["common_R"]))
            Rb = dict(enumerate(
                regrets[qb]
                ["common_R"]))
            pairs_out[name] = {
                "a": qa, "b": qb,
                **pair_taus(Ra, Rb)}
            partial["pairs"][
                name] = \
                pairs_out[name]
        with open(os.path.join(
                evidence_dir,
                "analysis_v2.json"),
                encoding="utf-8") as f:
            v2 = json.load(f)
        report = {
            "status": "completed",
            "course_gate":
                COURSE_GATE,
            "regrets": regrets,
            "pairs": pairs_out,
            "tails": tail_check,
            "proxy_passthrough": {
                qid: {
                    k: v2[
                        "analysis_v2"][
                        qid].get(k)
                    for k in
                    ("status",
                     "margin_final",
                     "uncertainty_q_units",
                     "suboptimal_gap_final")}
                for qid in
                CANONICAL_IDS}}
        report_path = os.path.join(
            out_dir,
            "q_set_report.json")
        with open(report_path,
                  "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        # 真实 post-save(主报告已落盘)
        why, meters = (
            bud.checkpoint())
        if why:
            report["fail_reason"] = "post_save:%s" % why
            raise RuntimeError("budget(post-save): %s" % why)
        report["budget_final"] = meters
        report["budget_measurement"] = "after_initial_main_save"
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why, _ = bud.checkpoint()
        if why:
            raise RuntimeError("budget(final-metadata-save): %s" % why)
        os.replace(marker,
                   os.path.join(
                       out_dir,
                       "DONE.marker"))
        return report
    except BaseException as exc:
        try:
            _why, meters = bud.checkpoint()
        except BaseException as measurement_exc:
            # Failure reporting must not lose the original error if measurement fails.
            meters = dict((report or {}).get("budget_final", {}))
            meters["measurement_error"] = repr(measurement_exc)
            meters["measurement_point"] = "failure_read_unavailable"
        failure = {"status": "failed", "reason": repr(exc),
                   "budget_final": meters, **partial}
        try:
            with open(os.path.join(out_dir, "FAIL_STATE.json"),
                      "w", encoding="utf-8") as f:
                json.dump(failure, f, indent=1, allow_nan=False)
        except Exception:
            pass
        if report is not None:
            report.update(status="failed", fail_reason=report.get("fail_reason", repr(exc)),
                          budget_final=meters)
            try:
                with open(report_path, "w", encoding="utf-8") as f:
                    json.dump(report, f, indent=1, allow_nan=False)
            except Exception:
                pass
        try:
            if os.path.exists(marker):
                os.replace(marker, os.path.join(out_dir, "FAILED.marker"))
        except Exception:
            pass
        raise


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: q_set_diagnostic"
            ".py <evidence_dir> "
            "<out_dir>")
    run(sys.argv[1], sys.argv[2])
