#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteC_PositionControl_IntegratedUpgrade_v1 最终交付封包。

组装 RETURN ZIP(WSL /usr/bin/zip,正斜杠路径;SHA256SUMS 用
find ! -path 排除自身;不含符号链接/绝对路径/..)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path

REPO = Path("/mnt/f/trading/freqai-rl-audit")
EXP = Path("/home/cryptorl/posctl_experiments")
REG = Path("/home/cryptorl/regress_posctl_final_v1")
REVIEW_SRC = Path("/mnt/f/trading/task_pkg_inbox/posctl_v1")


def copy_tree_into(src: Path, dst_root: Path, prefix: str) -> int:
    n = 0
    if not src.exists():
        return 0
    for p in sorted(src.rglob("*")):
        if p.is_file() and not p.is_symlink():
            rel = prefix + "/" + str(p.relative_to(src)).replace(
                "\\", "/")
            target = dst_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, target)
            n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", required=True,
                    help="staging dir (must not pre-contain zip)")
    ap.add_argument("--zip-out", required=True)
    args = ap.parse_args()
    stage = Path(args.stage)
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    pkg = stage / "RouteC_PositionControl_IntegratedUpgrade_v1_RETURN"
    pkg.mkdir()

    # 1) 报告
    reports = REPO / "stage2_7_0" / "report"
    for f in reports.glob("*.md"):
        shutil.copy2(f, pkg / f.name)
    shutil.copy2(REPO / "README.md", pkg / "README_repo_route.md")

    # 2) 源码投影(新域全部 + W0 受影响 261 文件)
    n = copy_tree_into(REPO / "stage2_7_0" / "src",
                       pkg, "source/stage2_7_0/src")
    n += copy_tree_into(REPO / "stage2_7_0" / "tests",
                        pkg, "source/stage2_7_0/tests")
    n += copy_tree_into(REPO / "stage2_7_0" / "runner",
                        pkg, "source/stage2_7_0/runner")
    for f in (
            REPO / "stage2_6_1" / "src" / "rl_curriculum" /
                "curriculum261_r17_cue_contract.py",
            REPO / "stage2_6_1" / "runner" / "qaf_child_watcher.py",
            REPO / "stage2_6_1" / "runner" / "qaf_v2_operator_entry.py",
            REPO / "stage2_6_1" / "runner" / "ci_multiset_compare.py",
            REPO / "stage2_6_1" / "tests" / "route_c_stage2_6_1" /
                "test_curriculum261_cic_r1_repairs.py",
            REPO / "stage2_6_1" / "tests" / "route_c_stage2_6_1" /
                "test_curriculum261_r17_cue_formal_identity.py"):
        if "tests" in f.parts:
            target = (pkg / "source" / "stage2_6_1" / "tests"
                      / "route_c_stage2_6_1" / f.name)
        elif f.parent.name == "runner":
            target = (pkg / "source" / "stage2_6_1"
                      / "runner" / f.name)
        else:
            target = (pkg / "source" / "stage2_6_1" / "src"
                      / "rl_curriculum" / f.name)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, target)
        n += 1

    # 3) 实验工件
    keep = [
        "usage_ledger.jsonl", "gen_quota.jsonl", "param_stats.json",
        "bc_diagnostic.json", "report_curriculum_eval.json",
        "demo_trajectory.json", "device_snapshot.json"]
    (pkg / "experiments").mkdir(parents=True, exist_ok=True)
    for k in keep:
        p = EXP / k
        if p.exists():
            shutil.copy2(p, pkg / "experiments" / k)
    if (EXP / "perf" / "perf_results.json").exists():
        shutil.copy2(EXP / "perf" / "perf_results.json",
                     pkg / "experiments" / "perf_results.json")
    for sub in ("smoke", "capacity", "series"):
        copy_tree_into(EXP / sub, pkg / "experiments", sub)

    # 4) 最终回归证据
    if REG.exists():
        copy_tree_into(REG, pkg / "final_regression", "final_regression")
        # A9 基线(只读拷贝)
        a9 = Path("/home/cryptorl/regress_cue_identity_v1")
        for f in ("summary.json", "audit_manifest.json"):
            if (a9 / f).exists():
                shutil.copy2(a9 / f,
                             pkg / "final_regression" / ("a9_" + f))

    # 5) git 身份
    head = subprocess.run(
        ["git", "-C", str(REPO), "rev-parse", "HEAD"],
        capture_output=True, text=True, check=True).stdout.strip()
    log = subprocess.run(
        ["git", "-C", str(REPO), "log", "--oneline",
         "0b6b94d9..HEAD"], capture_output=True, text=True,
        check=True).stdout
    ls = subprocess.run(
        ["git", "-C", str(REPO), "ls-tree", "-r", "--name-only",
         "HEAD", "stage2_7_0"],
        capture_output=True, text=True, check=True).stdout
    (pkg / "git_identity.json").write_text(json.dumps({
        "head": head,
        "commits_since_0b6b94d9": log.strip().splitlines(),
        "stage2_7_0_tree_files": ls.strip().splitlines()},
        ensure_ascii=False, indent=1), encoding="utf-8")

    # 6) SHA256SUMS(排除自身;先建空文件防自引用)
    sums = pkg / "SHA256SUMS.txt"
    sums.write_text("", encoding="utf-8")
    lines = []
    for p in sorted(pkg.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            h = hashlib.sha256(p.read_bytes()).hexdigest()
            lines.append(f"{h}  {p.relative_to(pkg).as_posix()}")
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # 7) zip(WSL zip;正斜杠)
    zip_path = Path(args.zip_out)
    if zip_path.exists():
        raise RuntimeError(f"zip 已存在,拒绝覆盖:{zip_path}")
    subprocess.run(["zip", "-r", "-q", str(zip_path),
                    pkg.name], cwd=stage, check=True)
    zh = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    print(json.dumps({
        "zip": str(zip_path), "bytes": zip_path.stat().st_size,
        "sha256": zh, "files": len(lines)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
