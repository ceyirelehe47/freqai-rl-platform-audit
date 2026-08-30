#!/usr/bin/env python3
"""阶段 2.6.0i 统一 regression runner(补充任务书:性能优化)。

模式:
  quick       2.6.0i 新测试 + 指定测试,fail-fast。**不得用于宣布
              PASS**(输出中显式标注)。
  affected    相对最后已验证基线(.regression_state/baseline.json,
              由 full-cold 成功后写入)的内容 diff 选择相关测试;
              路径影响不明确或触及 Route C 冻结核心时自动升级 full。
              选择规则见 regression_selection_rules.md(可审计)。
  full        全部历史目录 + 2.6.0i;逐目录独立 pytest(避免 conftest
              冲突);目录级受控并行(默认 2 worker,--workers N);
              每 worker 独立 TMPDIR/pytest cache/日志;固定线程环境;
              汇总保留每目录退出码/计数/起止时间/原始日志。
  full-cold   最终验收:清理开发缓存(pytest cache/__pycache__)后从
              干净状态执行 full;不复用任何通过记录;成功后刷新基线。
              **只有本模式零失败/零 skipped/零 xfailed/零 error 才能报
              PASS**。

用法:
  python regression_runner.py quick [--tests a.py::t,b.py]
  python regression_runner.py affected [--workers 2]
  python regression_runner.py full [--workers 2]
  python regression_runner.py full-cold [--workers 2]
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / "src"
STATE = ROOT / ".regression_state"
ART = ROOT / "artifacts" / "route_c_stage2_6_1"

#: 全量 pytest test-target 目录(逐目录独立 pytest;全部必须 exit 0)
#: 2.6.0j 修复:tests/freqai_rl_platform_audit 是**诊断脚本目录**
#: (assemble_repo.sh/make_evidence.sh/env_vs_backtest.py,无 pytest
#: 用例)——按任务书十三方案 1 从 pytest test-target manifest 移除,
#: 单列 DIAGNOSTIC_DIRS;pytest exit 5(未收集)不再被当作绿色。
ALL_DIRS = [
    "tests/freqai_rl_stage2_5",
    "tests/freqai_rl_stage2_5_1",
    "tests/freqai_rl_stage2_5_2",
    "tests/freqai_rl_stage2_5_2a",
    "tests/route_c_stage2_6_0",
    "tests/route_c_stage2_6_0a",
    "tests/route_c_stage2_6_0b",
    "tests/route_c_stage2_6_0c",
    "tests/route_c_stage2_6_0d",
    "tests/route_c_stage2_6_0e",
    "tests/route_c_stage2_6_0f",
    "tests/route_c_stage2_6_0g",
    "tests/route_c_stage2_6_0h",
    "tests/route_c_stage2_6_0i",
    "tests/route_c_stage2_6_0j",
    "tests/route_c_stage2_6_1",
]

#: 诊断目录(无 pytest 用例;不计入 test targets,不参与绿色判定;
#: 内容为发布/证据组装脚本,由发布流程直接调用)
DIAGNOSTIC_DIRS = ["tests/freqai_rl_platform_audit"]

#: 互斥目录(修改共享 conda env 状态的用例:0h 真实 env 篡改矩阵、
#: 0i 硬链接别名 TOCTOU、0j 密封计算攻击矩阵)。这些目录必须**独占**
#: 运行:其余目录的 bundle 组装/挂载视图复验会读取 env 文件,并发就地
#: 篡改会造成跨目录互扰(full-cold 首轮实测:0h 32 errors 由并发 0i
#: 的 env 就地写引发)。运行顺序:普通目录并行完成后,互斥目录逐个
#: 独占执行。
EXCLUSIVE_DIRS = {"tests/route_c_stage2_6_0h", "tests/route_c_stage2_6_0i",
                  "tests/route_c_stage2_6_0j"}

#: Route C 冻结核心(触及即升级 full;见任务书冻结边界)
FROZEN_CORE = [
    "src/rl_platform/",
    "src/rl_curriculum/env.py",
    "src/rl_curriculum/ledger.py",
    "src/rl_curriculum/market_execution.py",
    "src/rl_curriculum/ppo_params.py",
    "src/rl_curriculum/price_clamp.py",
    "src/rl_curriculum/signal_convert.py",
]

#: 影响选择规则(与 regression_selection_rules.md 同步维护)
RULES = [
    ("src/rl_builder_runtime/", ["tests/route_c_stage2_6_0f",
                                 "tests/route_c_stage2_6_0g",
                                 "tests/route_c_stage2_6_0h",
                                 "tests/route_c_stage2_6_0i",
                                 "tests/route_c_stage2_6_0j"]),
    ("src/rl_curriculum/builder_", ["tests/route_c_stage2_6_0f",
                                     "tests/route_c_stage2_6_0g",
                                     "tests/route_c_stage2_6_0h",
                                     "tests/route_c_stage2_6_0i",
                                     "tests/route_c_stage2_6_0j"]),
    ("src/rl_curriculum/access_guard.py",
     ["tests/route_c_stage2_6_0h", "tests/route_c_stage2_6_0i",
      "tests/route_c_stage2_6_0j"]),
    # 2.6.1 课程生成器:定向到本阶段目录(其余 rl_curriculum 改动
    # 仍走承诺链全目录的保守规则)
    ("src/rl_curriculum/curriculum261_",
     ["tests/route_c_stage2_6_1"]),
]
#: 证据/承诺/CLI 链(改动影响全部承诺通道目录)
COMMITMENT_CHAIN = ["tests/route_c_stage2_6_0" + s for s in
                    ("", "a", "b", "c", "d", "e", "f", "g", "h", "i", "j")] +                    ["tests/route_c_stage2_6_1"]
COMMITMENT_SRCS = (
    "src/rl_curriculum/sealed_exam.py",
    "src/rl_curriculum/formal_exam.py",
    "src/rl_curriculum/hidden_exam_cli.py",
    "src/rl_curriculum/mock_sealed_exam.py",
    "src/rl_curriculum/exam_pack.py",
    "src/rl_curriculum/builder_evidence.py",
    "src/rl_curriculum/builder_provenance.py",
)

#: 测试目录间 conftest 依赖(改 X/conftest.py 影响 importer)
CONFTEST_IMPORTERS = {
    "tests/route_c_stage2_6_0c": ["tests/route_c_stage2_6_0h",
                                  "tests/route_c_stage2_6_0i",
                                  "tests/route_c_stage2_6_0j"],
    "tests/route_c_stage2_6_0f": ["tests/route_c_stage2_6_0g",
                                  "tests/route_c_stage2_6_0h",
                                  "tests/route_c_stage2_6_0i",
                                  "tests/route_c_stage2_6_0j"],
    "tests/route_c_stage2_6_0i": ["tests/route_c_stage2_6_0j"],
    "tests/route_c_stage2_6_0g": [],
}

THREAD_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
    "PYTHONHASHSEED": "0",
    "PYTHONDONTWRITEBYTECODE": "1",
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _tree_manifest() -> dict[str, str]:
    """src/tests 的内容清单(path -> sha256;排除 __pycache__/缓存)。"""
    out: dict[str, str] = {}
    for base in (SRC, ROOT / "tests"):
        for p in sorted(base.rglob("*")):
            if not p.is_file() or "__pycache__" in p.parts:
                continue
            if p.suffix not in (".py", ".sh", ".md"):
                continue
            rel = p.relative_to(ROOT).as_posix()
            out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


def _parse_summary(line: str) -> dict:
    counts = {k: 0 for k in
              ("passed", "failed", "skipped", "xfailed", "error")}
    for k in counts:
        m = re.search(rf"([0-9]+) {k}", line)
        if m:
            counts[k] = int(m.group(1))
    return counts


def _run_dir(d: str, run_dir: Path, worker: int, *, fail_fast: bool = False,
             durations: bool = True) -> dict:
    """单目录独立 pytest(per-worker 隔离 TMPDIR/cache/日志)。"""
    log = run_dir / "logs" / f"{d.replace('/', '__')}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    # TMPDIR 必须是中性路径(不含 /home 与项目名):候选沙箱的
    # mountinfo 反泄漏断言要求临时目录路径不可识别评估方身份;
    # 用 /var/tmp(避开 systemd 对 /tmp 的清理,且不在项目树内)
    tmp = Path("/var/tmp/rl-regression") / run_dir.name / \
        f"w{worker}" / d.replace("/", "__")
    cache = run_dir / f"pytest-cache-w{worker}" / d.replace("/", "__")
    tmp.mkdir(parents=True, exist_ok=True)
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SRC)
    env.update(THREAD_ENV)
    env["TMPDIR"] = str(tmp)
    args = [sys.executable, "-m", "pytest", d, "-q",
            "-p", "no:cacheprovider"]
    if fail_fast:
        args.append("-x")
    if durations:
        args.append("--durations=50")
    started = _now()
    t0 = time.monotonic()
    proc = subprocess.run(args, cwd=str(ROOT), env=env,
                          capture_output=True, text=True, timeout=5400)
    elapsed = time.monotonic() - t0
    out = proc.stdout + proc.stderr
    log.write_text(out, encoding="utf-8")
    tail = [ln for ln in out.splitlines() if ln.strip()][-1:] or [""]
    counts = _parse_summary(tail[0])
    return {
        "dir": d, "exit_code": proc.returncode,
        **counts,
        "started": started, "ended": _now(),
        "duration_seconds": round(elapsed, 1),
        "log": str(log.relative_to(ROOT)),
        "summary_line": tail[0],
    }


def _run_all(dirs: list[str], mode: str, workers: int) -> dict:
    run_id = f"{mode}-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    run_dir = STATE / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    results = []
    worker_seq = list(range(workers))
    next_worker = 0
    print(f"[{mode}] dirs={len(dirs)} workers={workers} -> {run_dir}")
    t0 = time.monotonic()
    normal = [d for d in dirs if d not in EXCLUSIVE_DIRS]
    exclusive = [d for d in dirs if d in EXCLUSIVE_DIRS]

    def _mark(r):
        return "OK" if (r["exit_code"] == 0 and r["failed"] == 0
                        and r["error"] == 0 and r["skipped"] == 0
                        and r["xfailed"] == 0) else "BAD"

    # 阶段 1:普通目录受控并行
    with cf.ThreadPoolExecutor(max_workers=workers) as pool:
        futs = {}
        for d in normal:
            w = worker_seq[next_worker % workers]
            next_worker += 1
            futs[pool.submit(_run_dir, d, run_dir, w)] = d
        for fut in cf.as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"  [{_mark(r)}] {r['dir']}: {r['summary_line']} "
                  f"({r['duration_seconds']}s)")
    # 阶段 2:互斥目录(修改共享 env 状态)逐个独占运行,避免与
    # 任何目录的 bundle 组装/挂载视图复验并发互扰
    for d in exclusive:
        r = _run_dir(d, run_dir, 0)
        results.append(r)
        print(f"  [EXCL:{_mark(r)}] {r['dir']}: {r['summary_line']} "
              f"({r['duration_seconds']}s)")
    wall = time.monotonic() - t0
    results.sort(key=lambda r: dirs.index(r["dir"]))
    total = {k: sum(r[k] for r in results) for k in
             ("passed", "failed", "skipped", "xfailed", "error")}
    def _dir_ok(r):
        # 2.6.0j:exit 5(未收集)不再当作绿色——诊断目录已从
        # test targets 移除,全部 test targets 必须 exit 0 零异常
        return r["exit_code"] == 0 and r["failed"] == 0 \
            and r["error"] == 0 and r["skipped"] == 0 \
            and r["xfailed"] == 0

    ok = all(_dir_ok(r) for r in results)
    report = {
        "mode": mode, "run_id": run_id, "started_dirs": len(dirs),
        "workers": workers, "wall_seconds": round(wall, 1),
        "totals": total, "all_green": ok,
        "dirs": results,
        "tree_manifest_digest": hashlib.sha256(json.dumps(
            _tree_manifest(), sort_keys=True).encode()).hexdigest(),
        "note": "full-cold 模式零失败/零 skipped/零 xfailed/零 error "
                "才允许报告 PASS",
    }
    (run_dir / "summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[{mode}] wall={wall:.0f}s totals={total} "
          f"all_green={ok} summary={run_dir / 'summary.json'}")
    return report


# ------------------------------------------------------------ affected
def _select_affected() -> tuple[list[str], list[str], str]:
    """返回 (dirs, reasons, mode):影响不明确/冻结核心 -> full。"""
    baseline_path = STATE / "baseline.json"
    if not baseline_path.is_file():
        return ALL_DIRS, ["无基线(先执行 full-cold)"], "full"
    baseline = json.loads(baseline_path.read_text())
    current = _tree_manifest()
    changed = sorted(set(current) ^ set(baseline.get("tree", {}))
                     | {k for k in set(current) & set(baseline["tree"])
                        if current[k] != baseline["tree"][k]})
    if not changed:
        return (["tests/route_c_stage2_6_1"],
                ["无变更:默认跑 2.6.1 目录"], "affected")
    reasons: list[str] = []
    dirs: set[str] = set()
    escalate = False
    for path in changed:
        if any(path.startswith(f) or path == f for f in FROZEN_CORE):
            reasons.append(f"{path}: Route C 冻结核心 -> full")
            escalate = True
            continue
        matched = False
        for prefix, ds in RULES:
            if path.startswith(prefix):
                dirs.update(ds)
                reasons.append(f"{path} -> {ds}")
                matched = True
                break
        if matched:
            continue
        if path in COMMITMENT_SRCS or path.startswith(
                "src/rl_curriculum/null_") or path.startswith(
                "src/rl_curriculum/"):
            dirs.update(COMMITMENT_CHAIN)
            reasons.append(f"{path} -> 承诺/课程链(全部 route_c 目录)")
            continue
        m = re.match(r"(tests/[^/]+)/", path)
        if m:
            d = m.group(1)
            dirs.update([d])
            if path.endswith("conftest.py"):
                dirs.update(CONFTEST_IMPORTERS.get(d, []))
                reasons.append(
                    f"{path}: conftest -> {d} + importers "
                    f"{CONFTEST_IMPORTERS.get(d, [])}")
            else:
                reasons.append(f"{path} -> {d}")
            continue
        if path.startswith(("tests/null_qual_cache.py",
                            "tests/compat_stage2_6_0f.py")):
            dirs.update(COMMITMENT_CHAIN)
            reasons.append(f"{path}: 跨目录共享夹具 -> 全部 route_c")
            continue
        reasons.append(f"{path}: 影响不明确 -> full")
        escalate = True
    if escalate:
        return ALL_DIRS, reasons, "full"
    return sorted(dirs), reasons, "affected"


# ------------------------------------------------------------ 模式入口
def mode_quick(extra: str | None) -> int:
    targets = ["tests/route_c_stage2_6_1"]
    if extra:
        targets.extend(t for t in extra.split(",") if t.strip())
    print("[quick] 快速反馈模式(fail-fast)——**不得用于宣布 PASS**")
    run_dir = STATE / f"quick-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    bad = 0
    for t in targets:
        r = _run_dir(t, run_dir, 0, fail_fast=True, durations=False)
        mark = "OK" if r["exit_code"] == 0 else "BAD"
        bad += 0 if r["exit_code"] == 0 else 1
        print(f"  [{mark}] {t}: {r['summary_line']}")
    print("[quick] 结果仅供开发反馈;宣布 PASS 必须执行 full-cold")
    return 1 if bad else 0


def mode_affected(workers: int) -> int:
    dirs, reasons, eff = _select_affected()
    print("[affected] 选择规则输出(可审计):")
    for r in reasons:
        print("   -", r)
    print(f"[affected] 生效模式: {eff};目录: {dirs}")
    report = _run_all(dirs if eff == "affected" else ALL_DIRS,
                      eff, workers)
    return 0 if report["all_green"] else 1


def _clean_dev_caches() -> list[str]:
    cleaned = []
    for p in [ROOT / ".pytest_cache"]:
        if p.exists():
            shutil.rmtree(p, ignore_errors=True)
            cleaned.append(str(p))
    for sub in [ROOT / "tests"]:
        for p in sub.rglob("__pycache__"):
            shutil.rmtree(p, ignore_errors=True)
            cleaned.append(str(p))
    for p in (ROOT / "src").rglob("__pycache__"):
        shutil.rmtree(p, ignore_errors=True)
        cleaned.append(str(p))
    return cleaned


def mode_full(workers: int, cold: bool) -> int:
    if cold:
        cleaned = _clean_dev_caches()
        print(f"[full-cold] 已清理开发缓存 {len(cleaned)} 处"
              f"(pytest cache/__pycache__);不复用任何通过记录")
    report = _run_all(ALL_DIRS, "full-cold" if cold else "full", workers)
    # 汇总与原始日志进入 artifacts(最终验收材料)
    ART.mkdir(parents=True, exist_ok=True)
    (ART / "regression_fullcold_summary.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    logs_dir = ART / "regression_logs"
    if logs_dir.exists():
        shutil.rmtree(logs_dir)
    src = ROOT / ".regression_state" / report["run_id"] / "logs"
    if src.is_dir():
        shutil.copytree(src, logs_dir)
    raw = ART / "regression_raw.log"
    with raw.open("w", encoding="utf-8") as fh:
        fh.write(f"# {report['mode']} {report['run_id']} "
                 f"workers={workers}\n")
        for d in report["dirs"]:
            fh.write(f"\n===== {d['dir']} "
                     f"(exit={d['exit_code']}, {d['started']} ~ "
                     f"{d['ended']}, {d['duration_seconds']}s) =====\n")
            log_path = ROOT / d["log"]
            fh.write(log_path.read_text(encoding="utf-8")
                     if log_path.is_file() else "<log missing>")
    # 汇总 markdown
    md = ["# 阶段 2.6.0i 全量回归摘要(full-cold)", "",
          "| 目录 | exit | passed | failed | skipped | xfailed | error "
          "| 用时(s) |", "|---|---|---|---|---|---|---|---|"]
    for d in report["dirs"]:
        md.append(
            f"| `{d['dir']}` | {d['exit_code']} | {d['passed']} "
            f"| {d['failed']} | {d['skipped']} | {d['xfailed']} "
            f"| {d['error']} | {d['duration_seconds']} |")
    t = report["totals"]
    md += ["",
           f"**总计: {t['passed']} passed / {t['failed']} failed / "
           f"{t['skipped']} skipped / {t['xfailed']} xfailed / "
           f"{t['error']} error;wall={report['wall_seconds']}s;workers="
           f"{workers}**",
           "",
           f"all_green={report['all_green']}(仅 full-cold 零失败/零"
           "skipped/零 xfailed/零 error 允许报告 PASS)",
           "",
           "原始日志: regression_raw.log;逐目录日志: "
           "regression_logs/;机器可读: regression_fullcold_summary.json"]
    (ART / "regression_test_summary.md").write_text(
        "\n".join(md), encoding="utf-8")
    if cold and report["all_green"]:
        (STATE / "baseline.json").write_text(json.dumps({
            "created": _now(),
            "run_id": report["run_id"],
            "tree": _tree_manifest(),
        }, sort_keys=True), encoding="utf-8")
        print("[full-cold] 基线已刷新(.regression_state/baseline.json)")
    return 0 if report["all_green"] else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["quick", "affected", "full",
                                     "full-cold"])
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--tests", default=None,
                    help="quick 模式附加测试(a.py::t,b.py)")
    args = ap.parse_args()
    STATE.mkdir(exist_ok=True)
    if args.mode == "quick":
        return mode_quick(args.tests)
    if args.mode == "affected":
        return mode_affected(args.workers)
    return mode_full(args.workers, cold=args.mode == "full-cold")


if __name__ == "__main__":
    raise SystemExit(main())
