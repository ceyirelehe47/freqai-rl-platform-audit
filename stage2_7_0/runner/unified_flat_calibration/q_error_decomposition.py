# -*- coding: utf-8 -*-
"""q_error_decomposition v2 — 8 根 Q 漂移来源分解(准备段,未运行)。

结构(审查方 3532):
- 固定 **16 行** = 8 根 × (L0−L2, L1−L2);公共 41 点 i/2i/4i;
- 逐点:delta=Q_t−Q_L2;base=HOLD_t−HOLD_L2(每行常数);
  shape=delta−base;R_t=max(HOLD_t,**该档完整 REBAL 集**)−Q_t
  (档内最大用该档全网格,不用 common 41 近似);
  regret_shape=R_t−R_L2;行摘要 max_abs_raw/signed_base/
  max_abs_shape/signed_delta_min·max/max_abs_regret_shape;
  闭合检查 raw=base+shape;
- **原 proxy 逐根原样重现**:margin_t=max 全部 REBAL(Q_t−HOLD_t);
  cross=max−min;margin 外 val_dev=max(|raw 漂移|@公共点);
  proxy=max(cross,val_dev,1e-12);读 analysis_v2
  uncertainty_q_units 对照原值并保留组件;
- **不**用 shape 替换原 proxy 重判 τ;raw/base/shape 是**代数分解
  非三个独立因果来源**;三档同时多网格变化不能唯一归因(声明)。
STATUS=PREPARED_NOT_RUN;course_gate=not_frozen;预算 10/5/128MiB。
"""
import hashlib
import json
import os
import resource
import sys
import time

STATUS = "PREPARED_NOT_RUN"
BUDGET = {"wall_s": 10.0, "cpu_s": 5.0,
          "rss_gib": 0.125}
COURSE_GATE = "not_frozen"
N_COMMON = 41
ROOTS = ["G017", "G018", "G019",
         "G020", "G057", "G058",
         "G059", "G060"]
TIER_MAP = {"L0": lambda i: i,
            "L1": lambda i: 2 * i,
            "L2": lambda i: 4 * i}
TIER_LEN = {"L0": 41, "L1": 81,
            "L2": 161}

EXPECTED_SHAS = {
    "tier_L0.json":
        "44ac553071540b77c03596b317d3d53a"
        "3a5472be0c89dbd4d4715a1b9c6d52bd",
    "tier_L1.json":
        "67eca43493b006980582a061e771ab07"
        "e642ff4155c45b8f230be850a68575b6",
    "tier_L2.json":
        "124eb67c5f63cd3cc8fd5dfe83ac8e71"
        "fab54dd1e907755202413de0fa3277c7",
    "analysis_v2.json":
        "edfdc25efccdde40c0329b7925f74b98"
        "b49e87fe961390c8a140b999ad6bef64"}


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(
                lambda: f.read(1 << 20),
                b""):
            h.update(chunk)
    return h.hexdigest()


def verify_inputs(evidence_dir):
    """三 tier+analysis_v2 事前 SHA 逐件比较;返回实际 SHA。"""
    if not os.path.isdir(evidence_dir):
        raise ValueError(
            "evidence dir missing: %r"
            % (evidence_dir,))
    actual = {}
    for name, want in \
            EXPECTED_SHAS.items():
        p = os.path.join(
            evidence_dir, name)
        if not os.path.exists(p):
            raise ValueError(
                "input missing: %s"
                % name)
        got = _sha256_file(p)
        if got != want:
            raise ValueError(
                "SHA mismatch %s" % name)
        actual[name] = got
    return actual


def align_common(actions_by_tier):
    """小对齐:长度恰 41/81/161;坐标 i/2i/4i 逐点相等;
    拒绝坏长度或坐标;**不插值**。"""
    for t, n in TIER_LEN.items():
        if len(actions_by_tier[t]) != n:
            raise ValueError(
                "%s len %d!=%d"
                % (t,
                   len(actions_by_tier[t]),
                   n))
    for i in range(N_COMMON):
        want = -1.0 + 2.0 * i / 40.0
        for t in TIER_LEN:
            c = actions_by_tier[t][
                TIER_MAP[t](i)]
            if abs(c - want) > 1e-15:
                raise ValueError(
                    "coord misalign %s"
                    " i=%d %r"
                    % (t, i, c))


def decompose_row(qs_t, qs_2, h_t, h_2,
                  full_t, full_2,
                  h_full_max_t,
                  h_full_max_2):
    """一行(t vs L2)分解:逐点 delta/base/shape +
    regret_shape;base 每行常数(HOLD 差)。
    full_*: 该档完整 REBAL Q 列表(求档内 max);
    h_full_max_*: 该档 max(HOLD, 完整 REBAL)。"""
    base = h_t - h_2
    pts = []
    for qt, q2 in zip(qs_t, qs_2):
        delta = qt - q2
        shape = delta - base
        pts.append({
            "delta": delta,
            "base": base,
            "shape": shape})
    r_t = [h_full_max_t - q
           for q in full_t]
    r_2 = [h_full_max_2 - q
           for q in full_2]
    # 公共点 regret_shape(按档内索引映射取 regret)
    reg_shape = []
    for i in range(len(qs_t)):
        # 行内公共点序即 i(tier 索引由调用方给出)
        reg_shape.append(None)  # 占位,见下
    return base, pts, r_t, r_2


def row_report(tier, qid, base, pts,
               r_t_common, r_2_common,
               full_t, full_2,
               h_max_t, h_max_2):
    """16 行之一的完整记录(含摘要+闭合)。"""
    deltas = [p["delta"]
              for p in pts]
    shapes = [p["shape"]
              for p in pts]
    reg_shape = [
        rt - r2 for rt, r2 in
        zip(r_t_common,
            r_2_common)]
    closure = max(
        abs(p["delta"]
            - (p["base"]
               + p["shape"]))
        for p in pts)
    return {
        "row": "%s_%s_vs_L2"
               % (qid, tier),
        "root": qid,
        "tier": tier,
        "n_points": len(pts),
        # 逐点 signed delta/base/shape 原样落盘(供逐点复核)
        "points": pts,
        "common_coords": [
            -1.0 + 2.0 * i / 40.0
            for i in range(len(pts))],
        # 该行 tier 公共索引(i 或 2i)+L2 索引(4i)
        "tier_common_indices": [
            TIER_MAP[tier](i)
            for i in range(len(pts))],
        "L2_common_indices": [
            TIER_MAP["L2"](i)
            for i in range(len(pts))],
        "signed_base": base,
        "max_abs_raw": max(
            abs(d) for d in deltas),
        "signed_delta_min":
            min(deltas),
        "signed_delta_max":
            max(deltas),
        "max_abs_shape": max(
            abs(s) for s in shapes),
        "max_abs_regret_shape":
            max(abs(rs)
                for rs in reg_shape),
        "regret_shape_common":
            reg_shape,
        "identity_closure":
            closure,
        "tier_max_rebal_used":
            {"tier_max_action_value":
                 max(h_max_t,
                     max(full_t)),
             "L2_max_action_value":
                 max(h_max_2,
                     max(full_2))}}


def original_proxy(root_qs):
    """原 proxy 逐根重现(全部组件保留)。
    root_qs: {tier: {"all_Q": [...], "hold": h}}
    margin_t= max 全部 REBAL(Q_t−H_t);
    cross= max−min;margin;
    val_dev= max 公共点 |Q_t−Q_L2|(t=L0/L1)。"""
    margins = {}
    for t, d in root_qs.items():
        margins[t] = max(
            q - d["hold"]
            for q in d["all_Q"])
    cross = (max(
        margins.values())
        - min(margins.values()))
    val_dev = 0.0
    for t in ("L0", "L1"):
        qs_t = root_qs[t][
            "common_Q"]
        qs_2 = root_qs["L2"][
            "common_Q"]
        val_dev = max(
            val_dev,
            max(abs(a - b)
                for a, b in
                zip(qs_t, qs_2)))
    proxy = max(cross, val_dev,
                1e-12)
    return {
        "margins": margins,
        "cross": cross,
        "val_dev": val_dev,
        "floor": 1e-12,
        "proxy": proxy}


class JobBudget:
    """时钟可注入(self.nw/self.nc),便于故障桩。"""

    def __init__(self):
        self.nw = \
            time.perf_counter
        self.nc = \
            time.process_time
        self.t0 = self.nw()
        self.c0 = self.nc()

    def checkpoint(self):
        wall = self.nw() - self.t0
        cpu = self.nc() - self.c0
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


def load_tier(evidence_dir, tier):
    """纯 JSON:全网格 Q(actions 全长)+HOLD+公共 41 点
    (按已验 actions 索引 i/2i/4i)。"""
    with open(os.path.join(
            evidence_dir,
            "tier_%s.json" % tier),
            encoding="utf-8") as f:
        d = json.load(f)
    tm = d["tier_meta"]
    actions = [float(x)
               for x in
               tm["actions"]]

    def dec(x):
        if x == "+inf":
            return None
        if x == "-inf":
            return None
        return float(x)

    out = {}
    for e in d["questions"]:
        if e["id"] not in ROOTS:
            continue
        qr = {}
        for k, v in e[
                "q_rebals"].items():
            qr[float(k)] = dec(v)
        out[e["id"]] = {
            "hold": dec(
                e["q_hold"]),
            "all_Q": [
                qr[a]
                for a in actions],
            "common_Q": [
                qr[actions[
                    TIER_MAP[
                        tier](i)]]
                for i in range(
                    N_COMMON)]}
    return actions, out


def run(evidence_dir, out_dir):
    """真实入口(准备段**不调用**)。"""
    os.makedirs(out_dir,
                exist_ok=False)
    marker = os.path.join(
        out_dir, "RUNNING.marker")
    fd = os.open(
        marker, os.O_CREAT
        | os.O_EXCL
        | os.O_WRONLY)
    os.close(fd)
    bud = JobBudget()
    rp = os.path.join(
        out_dir,
        "q_error_decomp.json")
    report = {
        "status": "running",
        "semantics": (
            "algebraic "
            "decomposition only; "
            "NOT three independent "
            "causal sources; tiers "
            "change multiple grids "
            "simultaneously — no "
            "unique attribution; "
            "original proxy kept "
            "as-is (no tau "
            "re-judgement)"),
        "course_gate":
            COURSE_GATE,
        "verified": False,
        "roots": {},
        "rows": [],
        "proxy": {}}
    try:
        actual = verify_inputs(
            evidence_dir)
        report["actual_shas"] = \
            actual
        report["verified"] = True
        tiers = {}
        actions = {}
        for t in ("L0", "L1",
                  "L2"):
            actions[t], tiers[t] = \
                load_tier(
                    evidence_dir, t)
        align_common(actions)
        report["root_ids"] = \
            list(ROOTS)
        report[
            "tier_lengths"] = {
                t: len(actions[t])
                for t in actions}
        report[
            "coord_mapping"] = \
            {"L0": "i",
             "L1": "2i",
             "L2": "4i"}
        with open(os.path.join(
                evidence_dir,
                "analysis_v2.json"),
                encoding="utf-8") as f:
            v2 = json.load(f)
        for qid in ROOTS:
            root_qs = {}
            for t in ("L0",
                      "L1", "L2"):
                root_qs[t] = {
                    "all_Q": tiers[
                        t][qid][
                        "all_Q"],
                    "hold": tiers[
                        t][qid][
                        "hold"],
                    "common_Q": tiers[
                        t][qid][
                        "common_Q"]}
            # 原 proxy 重现+对照
            px = original_proxy(
                root_qs)
            orig = v2[
                "analysis_v2"][
                qid][
                "uncertainty_q_units"]
            px["analysis_v2_value"] \
                = orig
            px["matches_original"] = \
                abs(px["proxy"]
                    - orig) <= 1e-15
            report["proxy"][
                qid] = px
            report["roots"][
                qid] = True
            # 16 行:两 tier 各一行
            h2 = root_qs["L2"][
                "hold"]
            f2 = root_qs["L2"][
                "all_Q"]
            m2 = max(
                [h2] + f2)
            r2_full = [
                m2 - q for q in f2]
            for t in ("L0", "L1"):
                ht = root_qs[t][
                    "hold"]
                ft = root_qs[t][
                    "all_Q"]
                mt = max(
                    [ht] + ft)
                base = ht - h2
                pts = []
                for qt, q2 in zip(
                        root_qs[t][
                            "common_Q"],
                        root_qs["L2"][
                            "common_Q"]):
                    delta = qt - q2
                    pts.append({
                        "delta":
                            delta,
                        "base": base,
                        "shape":
                            delta
                            - base})
                # 公共点 regret:
                # R_t 用该档完整集 max
                r_t_common = [
                    mt - root_qs[t][
                        "common_Q"][i]
                    for i in range(
                        N_COMMON)]
                r_2_common = [
                    m2 - root_qs[
                        "L2"][
                        "common_Q"][i]
                    for i in range(
                        N_COMMON)]
                row = row_report(
                    t, qid, base,
                    pts,
                    r_t_common,
                    r_2_common,
                    ft, f2, mt, m2)
                report["rows"].\
                    append(row)
                why, _m = (
                    bud.checkpoint())
                if why:
                    raise RuntimeError(
                        "budget: %s"
                        % why)
        report["n_rows"] = \
            len(report["rows"])
        report[
            "status"] = \
            "completed"
        with open(rp, "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        # 写后 guard 1:命中即记**首个**原因并立即
        # raise(进通用失败收尾;不做第二次测量,
        # 避免二次异常掩盖首次已知超限)
        why, m = bud.checkpoint()
        if why:
            report["budget_final"] = m
            report["measurement_point"] = (
                "after_initial_main_save_guard1")
            raise RuntimeError(
                "budget(post-save-guard1): %s" % why)
        report["budget_final"] = m
        report["measurement_point"] = (
            "after_initial_main_save")
        with open(rp, "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        # 写后 guard 2:元数据后再查(独立首因)
        why2, m2b = bud.checkpoint()
        if why2:
            report["budget_final"] = m2b
            report["measurement_point"] = (
                "after_initial_main_save_guard2")
            raise RuntimeError(
                "budget(post-save-guard2): %s" % why2)
        os.replace(
            marker,
            os.path.join(
                out_dir,
                "DONE.marker"))
        return report
    except BaseException as exc:
        orig_exc = exc
        meas_err = None
        m_fin = None
        try:
            _w, m_fin = (
                bud.checkpoint())
        except Exception as e2:
            meas_err = repr(e2)
        try:
            report[
                "status"] = \
                "failed"
            report.setdefault(
                "fail_reason",
                repr(orig_exc))
            if m_fin:
                report[
                    "budget_"
                    "final"] = \
                    m_fin
            if meas_err:
                report[
                    "measurement_"
                    "error"] = \
                    meas_err
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=False)
        except Exception:
            pass
        try:
            with open(os.path.join(
                    out_dir,
                    "FAIL_STATE.json"),
                    "w",
                    encoding="utf-8") as f:
                json.dump({
                    "status": "failed",
                    "reason":
                        repr(orig_exc),
                    **({
                           "measurement"
                           "_error":
                               meas_err}
                       if meas_err
                       else {}),
                    "rows":
                        report
                        .get("rows",
                             []),
                    "proxy":
                        report
                        .get("proxy",
                             {})},
                    f, indent=1,
                    allow_nan=False)
        except Exception:
            pass
        try:
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED.marker"))
        except Exception:
            pass
        raise orig_exc


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(
            "usage: q_error_"
            "decomposition.py "
            "<evidence_dir> "
            "<out_dir>")
    run(sys.argv[1],
        sys.argv[2])
