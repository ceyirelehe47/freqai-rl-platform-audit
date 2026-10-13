#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PSC_P0_v1 封包(镜像已接受 R4 流程;jobs 扩展 P0 runs/plan)。

规则同 posctl_package_r4:根清单只排除根级自身;acceptance
INDEX/LATEST 封包前实际快照;staging 在 delivery 外;delivery 只四件;
WSL zip 正斜杠。P0 附加:runs/(banks 记录/主运行记录与检查点模型/
repr/BC/prequal/confirm 证据)与 plan/ 入包(512MiB 预算内)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

DEFAULT_ROOT = Path("/mnt/f/trading/acceptance/PSC_P0_v1")
DEFAULT_ACCEPTANCE = Path("/mnt/f/trading/acceptance")
ZIP_NAME = "RouteC_ProgressiveSkillCurriculum_P0_v1_RETURN_TO_CHATGPT"


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path,
              exclude_names=("__pycache__",)) -> int:
    n = 0
    for item in sorted(src.rglob("*")):
        if any(part in exclude_names
               for part in item.relative_to(src).parts):
            continue
        if item.is_file():
            target = dst / item.relative_to(src)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, target)
            n += 1
    return n


def snapshot_acceptance(stage: Path, acceptance: Path) -> dict:
    snap_dir = stage / "acceptance_snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {}
    for name in ("INDEX.md", "LATEST.md"):
        p = acceptance / name
        if p.exists():
            shutil.copy2(p, snap_dir / name)
            meta[name] = {"sha256": sha256_file(p),
                          "note": "Pre-packaging snapshot (old version, "
                                  "avoiding self-reference)"}
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo",
                    default="/mnt/f/trading/freqai-rl-audit")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--acceptance", default=str(DEFAULT_ACCEPTANCE))
    ap.add_argument("--zip-name", default=ZIP_NAME)
    args = ap.parse_args()
    repo = Path(args.repo)
    root = Path(args.root)
    jobs = [
        (repo / "stage2_7_0" / "src" / "rl_posctl",
         stage / "source" / "stage2_7_0" / "src" / "rl_posctl"),
        (repo / "stage2_7_0" / "tests" / "route_c_posctl",
         stage / "source" / "stage2_7_0" / "tests" / "route_c_posctl"),
        (repo / "stage2_7_0" / "runner",
         stage / "source" / "stage2_7_0" / "runner"),
        (root / "evidence", stage / "evidence"),
        (root / "reviews", stage / "reviews"),
        (root / "plan", stage / "plan"),
        (root / "runs" / "banks", stage / "runs" / "banks"),
        (root / "runs" / "main", stage / "runs" / "main"),
        (root / "runs" / "prequal", stage / "runs" / "prequal"),
        (root / "runs" / "repr", stage / "runs" / "repr"),
        (root / "runs" / "bc", stage / "runs" / "bc"),
        (root / "runs" / "smoke", stage / "runs" / "smoke"),
        (root / "runs" / "eval_dev", stage / "runs" / "eval_dev"),
        (root / "runs" / "confirm", stage / "runs" / "confirm"),
        (root / "runs" / "confirm_v2", stage / "runs" / "confirm_v2"),
        (root / "runs" / "prequal_failed_001",
         stage / "runs" / "prequal_failed_001"),
        (root / "runs" / "repr_failed_001",
         stage / "runs" / "repr_failed_001"),
        (root / "runs" / "repr_invalid_S160",
         stage / "runs" / "repr_invalid_S160"),
    ]
    runs_root_files = [
        "psc_p0_v1_ledger.jsonl", "psc_p0_confirm_lock.json",
        "w1_tests_junit.xml", "main6_driver.log",
    ]
    for fname in runs_root_files:
        src = root / "runs" / fname
        if src.exists():
            jobs.append((src, stage / "runs" / fname))
        else:
            print(f"[skip] 缺少 runs 根文件:{src}")
    counts = {}
    for src, dst in jobs:
        if not src.exists():
            print(f"[skip] 缺少源(如实跳过,阶段未运行):{src}")
            counts[str(src)] = None
            continue
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)
            counts[str(src)] = 1
            continue
        counts[str(src)] = copy_tree(src, dst)

    snap_meta = snapshot_acceptance(stage, acceptance)

    git_id = {}
    for key, cmd in (
            ("commit", ["git", "rev-parse", "HEAD"]),
            ("branch", ["git", "rev-parse", "--abbrev-ref", "HEAD"]),
            ("status_clean", ["git", "status", "--porcelain",
                              "stage2_7_0"])):
        r = subprocess.run(cmd, cwd=repo, capture_output=True,
                           text=True)
        git_id[key] = r.stdout.strip()
    (stage / "git_identity.json").write_text(
        json.dumps(git_id, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")

    sums = []
    for p in sorted(stage.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(stage).as_posix()
        if rel == "SHA256SUMS.txt":
            continue
        sums.append(f"{sha256_file(p)}  {rel}")
    (stage / "SHA256SUMS.txt").write_text(
        "\n".join(sums) + "\n", encoding="utf-8", newline="\n")

    delivery.mkdir(parents=True, exist_ok=True)
    zip_path = delivery / f"{top}.zip"
    if zip_path.exists():
        raise SystemExit("zip 已存在,拒绝覆盖")
    r = subprocess.run(
        ["zip", "-q", "-r", "-X", str(zip_path), top],
        cwd=stage_parent, capture_output=True, text=True)
    if r.returncode != 0:
        raise SystemExit("zip 失败:" + (r.stderr or "")[-500:])
    zip_sha = sha256_file(zip_path)
    sidecar = delivery / f"{top}.zip.sha256.txt"
    sidecar.write_text(f"{zip_sha}  {top}.zip\n",
                       encoding="utf-8", newline="\n")

    manifest = {
        "zip": str(zip_path), "zip_sha256": zip_sha,
        "zip_bytes": zip_path.stat().st_size,
        "members_sums": len(sums), "copied": counts, "git": git_id,
        "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                     time.gmtime()),
        "stage_dir": str(stage_parent),
        "acceptance_snapshot": snap_meta,
        "manifest_exclusion": (
            "仅根级 SHA256SUMS.txt 自身(按相对路径);嵌套同名"
            "清单一律覆盖"),
        "note": ("staging/ 在 delivery 外;delivery 只放四件;回执"
                 "包外绑定 ZIP;未终验不标 ChatGPT PASS"),
    }
    (stage_parent / "pack_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
