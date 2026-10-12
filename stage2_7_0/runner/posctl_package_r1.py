#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R1 最终封包:统一验收入口 delivery/ 四件(ZIP 外置回执)。

源(全部只读拷贝):repo 报告面 + acceptance 工作区。排除 .pyc/
__pycache__/临时缓存;SHA256SUMS 精确覆盖除自身外全部普通文件;
回执在包外绑定 ZIP 实际哈希。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path, exclude_names=(
        "__pycache__",)) -> list[Path]:
    copied = []
    if src.is_file():
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        return [dst]
    for p in sorted(src.rglob("*")):
        if any(part in exclude_names for part in p.parts):
            continue
        if p.suffix == ".pyc":
            continue
        rel = p.relative_to(src)
        target = dst / rel
        if p.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, target)
        copied.append(target)
    return copied


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--acceptance", required=True)
    ap.add_argument("--delivery", required=True)
    ap.add_argument("--zip-name", required=True)
    args = ap.parse_args()
    repo = Path(args.repo)
    acc = Path(args.acceptance)
    delivery = Path(args.delivery)
    top = args.zip_name
    stage_parent = delivery / "_stage"
    if stage_parent.exists():
        raise SystemExit("stage 已存在,拒绝覆盖(create-only)")
    stage = stage_parent / top
    stage.mkdir(parents=True)

    # ---- 源清单(全部只读拷贝进 stage) ----
    jobs = [
        (repo / "stage2_7_0" / "src" / "rl_posctl",
         stage / "source" / "stage2_7_0" / "src" / "rl_posctl"),
        (repo / "stage2_7_0" / "tests" / "route_c_posctl",
         stage / "source" / "stage2_7_0" / "tests" / "route_c_posctl"),
        (repo / "stage2_7_0" / "runner",
         stage / "source" / "stage2_7_0" / "runner"),
        (repo / "stage2_7_0" / "report",
         stage / "source" / "stage2_7_0" / "report"),
        (acc / "evidence", stage / "evidence"),
        (acc / "reviews", stage / "reviews"),
        (acc / "workspace_cleanup", stage / "workspace_cleanup"),
    ]
    for src, dst in jobs:
        if not src.exists():
            raise SystemExit(f"缺少源:{src}")
        copy_tree(src, dst)

    # ---- git 身份 ----
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

    # ---- SHA256SUMS ----
    sums = []
    for p in sorted(stage.rglob("*")):
        if p.is_file() and p.name != "SHA256SUMS.txt":
            sums.append(f"{sha256_file(p)}  {p.relative_to(stage)}")
    (stage / "SHA256SUMS.txt").write_text(
        "\n".join(sums) + "\n", encoding="utf-8", newline="\n")

    # ---- zip(WSL /usr/bin/zip,正斜杠路径) ----
    zip_path = delivery / f"{top}.zip"
    if zip_path.exists():
        raise SystemExit("zip 已存在,拒绝覆盖")
    def wsl_path(p: Path) -> str:
        s = str(p.resolve()).replace("\\", "/")
        if len(s) > 1 and s[1] == ":":
            return "/mnt/" + s[0].lower() + s[2:]
        return s
    r = subprocess.run(
        ["wsl.exe", "-e", "bash", "-c",
         f"cd '{wsl_path(stage_parent)}' && /usr/bin/zip -q -r -X "
         f"'../{top}.zip' '{top}' && sha256sum '{wsl_path(zip_path)}'"],
        capture_output=True, text=True, encoding="utf-8",
        errors="replace")
    if r.returncode != 0:
        raise SystemExit("zip 失败:" + (r.stderr or "")[-500:])
    if not zip_path.exists():
        raise SystemExit("zip 未出现在 delivery(WSL drvfs 延迟?)")
    zip_sha = r.stdout.strip().split()[0]
    sidecar = delivery / f"{top}.zip.sha256.txt"
    sidecar.write_text(
        f"{zip_sha}  {top}.zip\n", encoding="utf-8", newline="\n")

    manifest = {
        "zip": str(zip_path), "zip_sha256": zip_sha,
        "zip_bytes": zip_path.stat().st_size,
        "members_sums": len(sums),
        "git": git_id, "created_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                                    time.gmtime()),
    }
    (delivery / "_pack_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
