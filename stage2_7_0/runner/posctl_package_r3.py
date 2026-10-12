#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R3 封包(FiniteRepair R3;取代 posctl_package_r2 的 R3 轮)。

R2 遗留缺陷(reviewer F4)在本工具修正:
- 根 SHA256SUMS **只排除根级清单自身**(R2 打包器按 basename 排除
  所有 SHA256SUMS.txt,漏覆盖嵌套同名清单——旧包 162 普通文件只
  记 160 条,漏 evidence/task_pkg_in/SHA256SUMS.txt);
- 打包内含 acceptance INDEX.md/LATEST.md **实际快照**(标明快照
  时刻与指向;快照在封包前拍摄,指向 R2 旧版,避免包内自引用
  新包自身 SHA 的循环;新版本的索引更新由
  posctl_r3_delivery_root.py 在封包后执行,回执在包外绑定新 ZIP);
- 精确集合校验不依赖本工具自身过滤条件——独立冷读用
  posctl_r3_pack_verify.py(枚举 ZIP 全部普通成员双向核对)。

出口约定:staging 在 delivery 外;delivery 只四件;
zip 用 WSL /usr/bin/zip(正斜杠成员)。
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

DEFAULT_ROOT = Path("/mnt/f/trading/acceptance/PosCtl_R3_20261013")
DEFAULT_ACCEPTANCE = Path("/mnt/f/trading/acceptance")
ZIP_NAME = "RouteC_PositionControl_FiniteRepair_R3_RETURN_TO_CHATGPT"


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


def snapshot_acceptance(stage: Path, acceptance: Path) -> dict:
    """拍摄 INDEX.md/LATEST.md 实际快照(封包前;只读拷贝)。"""
    snap_dir = stage / "acceptance_snapshot"
    snap_dir.mkdir(parents=True, exist_ok=True)
    meta = {"snapshot_utc": time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "note": ("封包前只读快照;此时 LATEST/INDEX 指向 R2 旧版"
                 "(避免包内自引用新包 SHA 的循环);本包交付后的"
                 "索引更新见包外 DELIVERY_RECEIPT 与 delivery_root"
                 " update 输出"),
        "files": {}}
    for name in ("INDEX.md", "LATEST.md"):
        src = acceptance / name
        if not src.exists():
            raise SystemExit(f"缺少 acceptance 索引原件:{src}")
        dst = snap_dir / name
        shutil.copy2(src, dst)
        meta["files"][name] = {
            "sha256": sha256_file(dst),
            "bytes": dst.stat().st_size,
            "source": str(src)}
    (snap_dir / "snapshot_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return meta


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default="/mnt/f/trading/freqai-rl-audit")
    ap.add_argument("--root", default=str(DEFAULT_ROOT))
    ap.add_argument("--acceptance", default=str(DEFAULT_ACCEPTANCE))
    ap.add_argument("--zip-name", default=ZIP_NAME)
    args = ap.parse_args()
    repo = Path(args.repo)
    root = Path(args.root)
    acceptance = Path(args.acceptance)
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

    # ---- acceptance INDEX/LATEST 实际快照(R3-04) ----
    snap_meta = snapshot_acceptance(stage, acceptance)

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

    # ---- SHA256SUMS(R3-04:只排除**根级**清单自身;嵌套同名
    #      清单照常覆盖——按相对路径判等,不按 basename 过滤) ----
    sums = []
    root_manifest_rel = "SHA256SUMS.txt"
    for p in sorted(stage.rglob("*")):
        if not p.is_file():
            continue
        rel = p.relative_to(stage).as_posix()
        if rel == root_manifest_rel:
            continue
        sums.append(f"{sha256_file(p)}  {rel}")
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
        "acceptance_snapshot": snap_meta,
        "manifest_exclusion": (
            "仅根级 SHA256SUMS.txt 自身(按相对路径);嵌套同名"
            "清单一律覆盖;独立冷读见 posctl_r3_pack_verify.py"),
        "note": ("staging/ 目录在 delivery 外;delivery 只放四件"
                 "(zip/sidecar/DELIVERY_RECEIPT.md/"
                 "REVIEWER_FINAL_RECEIPT.md);回执包外绑定 ZIP;"
                 "未终验不标 ChatGPT PASS"),
    }
    (stage_parent / "pack_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
