# -*- coding: utf-8 -*-
"""tau_sensitivity v2 — A 结果条件敏感性(生产终版)。

相对 v1 的收尾修正(审查方 3417 组3):
- report/rp **尽早初始化**;输入 SHA **核验并写入报告**;
- 初次主报告写后保存 budget_final 与
  **after_initial_main_save** 测量点,元数据重写后再检查;
- 通用 except:已写主报告→权威改 failed 并保留 roots/pairs;
  收尾预算读取再失败→记 **measurement_error** 且保留原异常;
  主报告/失败文件/marker 各自 best-effort,最终 raise 原错;
- 生产钉 SHA(EXPECTED_SHAS)不变;测试只替换 verify_inputs。

语义不变:条件敏感性(Q 误差≤ε⇒regret 误差≤2ε;proxy 未证
明为上界);L=max(0,R−2ε)/U=R+2ε;对窗下=max(minU)上=min maxL,
下闭上开,空窗有效;仅 ε=0 与每根 proxy;course_gate=not_frozen。
STATUS=PREPARED_NOT_RUN(预算 10s/5s/128MiB)。
"""
import hashlib
import json
import math
import os
import resource
import sys
import time

STATUS = "PREPARED_NOT_RUN"
BUDGET = {"wall_s": 10.0, "cpu_s": 5.0,
          "rss_gib": 0.125}
COURSE_GATE = "not_frozen"

EXPECTED_SHAS = {
    "q_set_report.json":
        "8ab7211951145cc681cd57098c"
        "b89b175cc04a8318a0ceaa2525"
        "3c0ae8767660",
    "analysis_v2.json":
        "edfdc25efccdde40c0329b7925"
        "f74b98b49e87fe961390c8a140"
        "b999ad6bef64"}

PAIRS = {
    "s_minus_g0_q075_vs_q100":
        ("G017", "G019"),
    "s_minus_g1_q075_vs_q100":
        ("G018", "G020"),
    "s_plus_g0_q075_vs_q100":
        ("G057", "G059"),
    "s_plus_g1_q075_vs_q100":
        ("G058", "G060")}
ROOTS = sorted(
    {r for p in PAIRS.values()
     for r in p})
N_POINTS = 41


def _sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(
                lambda: f.read(1 << 20),
                b""):
            h.update(chunk)
    return h.hexdigest()


def verify_inputs(a_report_path,
                  analysis_v2_path):
    """核验并返回两输入 SHA(不匹配即拒)。"""
    got_a = _sha256_file(
        a_report_path)
    got_v = _sha256_file(
        analysis_v2_path)
    if got_a != EXPECTED_SHAS[
            "q_set_report.json"]:
        raise ValueError(
            "input SHA mismatch: %s"
            % a_report_path)
    if got_v != EXPECTED_SHAS[
            "analysis_v2.json"]:
        raise ValueError(
            "input SHA mismatch: %s"
            % analysis_v2_path)
    return got_a, got_v


def lu_bounds(R, eps):
    if eps < 0 or not math.isfinite(
            eps):
        raise ValueError(
            "eps invalid: %r" % (eps,))
    return ([max(0.0, r - 2 * eps)
             for r in R],
            [r + 2 * eps for r in R])


def robust_window(R_a, R_b, eps_a,
                  eps_b):
    L_a, U_a = lu_bounds(R_a,
                         eps_a)
    L_b, U_b = lu_bounds(R_b,
                         eps_b)
    lower = max(min(U_a), min(U_b))
    upper = min(
        max(la, lb)
        for la, lb in
        zip(L_a, L_b))
    return {
        "lower": lower,
        "upper": upper,
        "nonempty": lower < upper,
        "lower_closed": True,
        "upper_closed": False,
        "L_a": L_a, "U_a": U_a,
        "L_b": L_b, "U_b": U_b}


class JobBudget:
    def __init__(self):
        self.t0 = (
            time.perf_counter())
        self.c0 = (
            time.process_time())

    def checkpoint(self):
        wall = (time
                .perf_counter()
                - self.t0)
        cpu = (time
               .process_time()
               - self.c0)
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


def run(a_report_path,
        analysis_v2_path,
        out_dir):
    """唯一生产入口(准备段**不调用**真实输入)。"""
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
        "tau_sensitivity.json")
    report = {
        "status": "running",
        "semantics": (
            "conditional: Q error "
            "<= eps => regret error "
            "<= 2eps; proxy NOT "
            "proven as Q error "
            "bound"),
        "course_gate":
            COURSE_GATE,
        "roots": {},
        "pairs": {}}
    # 空容器即刻挂到 report:中途预算失败时
    # 已算项随权威 failed 报告保留
    main_written = False
    try:
        sha_a, sha_v = \
            verify_inputs(
                a_report_path,
                analysis_v2_path)
        report["inputs"] = {
            "q_set_report_sha256":
                sha_a,
            "analysis_v2_sha256":
                sha_v,
            "verified": True}
        with open(a_report_path,
                  encoding="utf-8") as f:
            a = json.load(f)
        with open(analysis_v2_path,
                  encoding="utf-8") as f:
            v2 = json.load(f)
        proxies = {
            qid: v2[
                "analysis_v2"][qid][
                "uncertainty_q_units"]
            for qid in ROOTS}
        roots_out = {}
        pairs_out = {}
        for qid in ROOTS:
            R = a["regrets"][qid][
                "common_R"]
            if len(R) != N_POINTS:
                raise ValueError(
                    "root %s not %d pts"
                    % (qid,
                       N_POINTS))
            rec = {}
            for name, eps in (
                    ("eps_zero",
                     0.0),
                    ("eps_proxy",
                     proxies[qid])):
                L, U = lu_bounds(
                    R, eps)
                rec[name] = {
                    "eps": eps,
                    "L": L, "U": U}
            roots_out[qid] = {
                "R": R,
                "proxy":
                    proxies[qid],
                "scenarios": rec}
            report["roots"][
                qid] = \
                roots_out[qid]
            why, _m = (
                bud.checkpoint())
            if why:
                raise RuntimeError(
                    "budget: %s"
                    % why)
        for name, (qa, qb) in \
                PAIRS.items():
            for scn in ("eps_zero",
                        "eps_proxy"):
                w = robust_window(
                    a["regrets"][qa][
                        "common_R"],
                    a["regrets"][qb][
                        "common_R"],
                    roots_out[qa][
                        "scenarios"][
                        scn]["eps"],
                    roots_out[qb][
                        "scenarios"][
                        scn]["eps"])
                pairs_out.setdefault(
                    name, {})[
                    scn] = {
                    k: w[k] for k in
                    ("lower", "upper",
                     "nonempty",
                     "lower_closed",
                     "upper_closed")}
            report["pairs"][
                name] = \
                pairs_out[name]
            why, _m = (
                bud.checkpoint())
            if why:
                raise RuntimeError(
                    "budget: %s"
                    % why)
        report["roots"] = \
            roots_out
        report["pairs"] = \
            pairs_out
        # 初次主报告写(Completed);
        # 写失败但文件已存在→尽力改 failed 后抛原错
        report["status"] = (
            "completed")
        try:
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=False)
        except Exception as werr:
            if os.path.exists(rp):
                report[
                    "status"] = \
                    "failed"
                report.setdefault(
                    "fail_reason",
                    repr(werr))
                try:
                    with open(rp, "w",
                              encoding="utf-8") as f:
                        json.dump(
                            report, f,
                            indent=1,
                            allow_nan=False)
                except Exception:
                    pass
            raise
        main_written = True
        # 写后:budget_final+测量点,元数据重写,再检查
        why, m = bud.checkpoint()
        report["budget_final"] = m
        report[
            "measurement_point"] = \
            ("after_initial_main_"
             "save")
        with open(rp, "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        why2, m2 = (
            bud.checkpoint())
        if why2:
            report["status"] = \
                "failed"
            report[
                "fail_reason"] = (
                "post_save:%s"
                % why2)
            report[
                "budget_final"] = m2
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=False)
            with open(os.path.join(
                    out_dir,
                    "PARTIAL.json"),
                    "w",
                    encoding="utf-8") as f:
                json.dump({
                    "status": "failed",
                    "reason":
                        "post_save:%s"
                        % why2,
                    "roots":
                        roots_out,
                    "pairs":
                        pairs_out},
                    f, indent=1,
                    allow_nan=False)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED.marker"))
            raise RuntimeError(
                "budget(post-save):"
                " %s" % why2)
        os.replace(
            marker,
            os.path.join(
                out_dir,
                "DONE.marker"))
        return report
    except BaseException as exc:
        orig = exc
        meas_err = None
        m_fin = None
        try:
            _why, m_fin = (
                bud.checkpoint())
        except Exception as e2:
            meas_err = repr(e2)
        try:
            if main_written:
                report[
                    "status"] = \
                    "failed"
                # 保留首次 why:已有 fail_reason
                # 不被收尾异常覆盖
                report.setdefault(
                    "fail_reason",
                    repr(orig))
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
                        repr(orig),
                    **({
                           "measurement"
                           "_error":
                               meas_err}
                       if meas_err
                       else {}),
                    "roots": report
                    .get("roots",
                         {}),
                    "pairs": report
                    .get("pairs",
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
        raise orig


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit(
            "usage: tau_"
            "sensitivity.py "
            "<a_report.json> "
            "<analysis_v2.json>"
            " <out_dir>")
    run(sys.argv[1],
        sys.argv[2],
        sys.argv[3])
