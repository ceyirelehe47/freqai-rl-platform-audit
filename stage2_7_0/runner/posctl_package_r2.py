#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R2 封包(FiniteRepair R2;取代 posctl_package_r1)。

R1 缺陷(reviewer §8):--acceptance/--delivery 手填;_stage 与
_pack_manifest.json 写进 delivery(交付目录不只四件);无统一默认
入口。R2:
- 默认出口 = F:/trading/acceptance/PosCtl_R2_20261012(
  staging/evidence/reviews 平级于 delivery;delivery **只放四件**);
- staging 写在同轮 staging/ 目录(不残留 delivery);
- 源(只读拷贝):repo stage2_7_0 四面 + acceptance evidence/reviews;
- SHA256SUMS 精确覆盖除自身全部普通文件(正斜杠;无 .pyc/__pycache__);
- WSL /usr/bin/zip 重打(正斜杠成员);
- 回执在包外绑定 ZIP 实际哈希;INDEX/LATEST 更新由
  posctl_r2_delivery_root.py 提供(本脚本只封包+sidecar)。
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

DEFAULT_ROOT = Path("/mnt/f/trading/acceptance/PosCtl_R2_20261012")


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path,
              exclude_names=("__pycache__",)) -> int:
    n = 0
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
        n += 1
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/mnt/f/trading/freqai-rl-audit")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--zip-name", default=(
        "RouteC_PositionControl_FiniteRepair_R2_RETURN_TO_CHATGPT"))
    args = ap.parse_args()
    repo = Path(args.repo)
    root = Path(args.root)
    delivery = root / "delivery"
    staging = root / "staging"
    top = args.zip_name
    stage_parent = staging / time.strftime("%Y%m%dT%H%M%S")
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
        (root / "evidence", stage / "evidence"),
        (root / "reviews", stage / "reviews"),
    ]
    counts = {}
    for src, dst in jobs:
        if not src.exists():
            raise SystemExit(f"缺少源:{src}")
        counts[str(src.relative_to(root) if root in src.parents
                   else src)] = copy_tree(src, dst)

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

    # ---- SHA256SUMS(R3 修正:只排除**根级**清单自身——按相对
    #      路径判等,不按 basename 过滤;嵌套同名清单照常覆盖) ----
    sums = []
    for p in sorted(stage.rglob("*")):
        if not p.is_file():
            continue
        if p.relative_to(stage).as_posix() == "SHA256SUMS.txt":
            continue
        sums.append(f"{sha256_file(p)}  "
                    f"{p.relative_to(stage).as_posix()}")
    (stage / "SHA256SUMS.txt").write_text(
        "\n".join(sums) + "\n", encoding="utf-8", newline="\n")

    # ---- zip(WSL /usr/bin/zip 正斜杠;写入 delivery) ----
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
        "note": ("staging/ 目录在 delivery 外;delivery 只放四件"
                 "(zip/sidecar/DELIVERY_RECEIPT.md/"
                 "REVIEWER_FINAL_RECEIPT.md);回执包外绑定 ZIP"),
    }
    (stage_parent / "pack_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
