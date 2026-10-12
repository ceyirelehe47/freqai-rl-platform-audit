#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R3 统一验收入口(R3-04):INDEX/LATEST 维护与定位。

- status:打印统一根/四件/INDEX/LATEST 实际状态(默认入口);
- update:封包后更新 acceptance 根 INDEX.md/LATEST.md(保留 R1/R2
  历史;**最新 ≠ 已终验通过**,未终验不标 ChatGPT PASS)。

与 R2 脚本(posctl_r2_delivery_root)的区别:R3 目录、R3 四件名、
INDEX 新条目滚动追加(不重复追加同轮)。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ACCEPTANCE = Path("/mnt/f/trading/acceptance")
ROOT = ACCEPTANCE / "PosCtl_R3_20261013"
FOUR = (
    "RouteC_PositionControl_FiniteRepair_R3_RETURN_TO_CHATGPT.zip",
    "RouteC_PositionControl_FiniteRepair_R3_RETURN_TO_CHATGPT"
    ".zip.sha256.txt",
    "DELIVERY_RECEIPT.md", "REVIEWER_FINAL_RECEIPT.md")


def status() -> int:
    rows = {
        "root": str(ROOT),
        "root_exists": ROOT.is_dir(),
        "delivery": str(ROOT / "delivery"),
        "delivery_files": sorted(
            p.name for p in (ROOT / "delivery").glob("*"))
        if (ROOT / "delivery").is_dir() else [],
        "four_complete": all(
            (ROOT / "delivery" / f).exists() for f in FOUR),
        "index": str(ACCEPTANCE / "INDEX.md"),
        "latest": str(ACCEPTANCE / "LATEST.md"),
    }
    print(json.dumps(rows, ensure_ascii=False, indent=1))
    return 0


def update(zip_sha: str, git_commit: str,
           status_line: str) -> int:
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    marker = "## PosCtl_R3_20261013(FiniteRepair R3)"
    idx = ACCEPTANCE / "INDEX.md"
    txt = idx.read_text(encoding="utf-8") if idx.exists() else (
        "# acceptance INDEX\n")
    if marker not in txt:
        entry = (
            f"\n{marker}\n"
            f"- 更新:{now};git 候选 {git_commit}\n"
            f"- 四件:{ROOT / 'delivery'}"
            f"(ZIP sha256 {zip_sha})\n"
            f"- 状态:{status_line}\n"
            "- 最新 ≠ 已终验通过;待 ChatGPT/用户终验(未代签)\n")
        txt += entry
        idx.write_text(txt, encoding="utf-8", newline="\n")
    latest = (
        "# LATEST\n\n"
        "- 轮次:RouteC PositionControl FiniteRepair R3"
        "(2026-10-13)\n"
        "- 出口:`PosCtl_R3_20261013/delivery/` 四件:\n"
        "  - RouteC_PositionControl_FiniteRepair_R3_RETURN_TO_"
        "CHATGPT.zip\n"
        f"    (SHA256 {zip_sha})\n"
        "  - .zip.sha256.txt / DELIVERY_RECEIPT.md / "
        "REVIEWER_FINAL_RECEIPT.md\n"
        f"- 状态:{status_line}\n"
        f"- git:route-c-stage2-6-1-repair17 @ {git_commit}\n"
        "- 历史:PosCtl_R2_20261012 / PosCtl_R1_20261012 四件原样"
        "保留(见 INDEX 旧条目;旧 ZIP SHA 原字节不动)\n"
        "- 说明:最新 ≠ 已终验通过;INDEX/LATEST 为包外不可变定位,"
        "RETURN 包内 acceptance_snapshot 为封包前旧版快照(防自引用"
        "循环)\n")
    (ACCEPTANCE / "LATEST.md").write_text(
        latest, encoding="utf-8", newline="\n")
    print("updated INDEX/LATEST")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["status", "update"])
    ap.add_argument("--zip-sha256")
    ap.add_argument("--git-commit")
    ap.add_argument("--status-line", default=(
        "实现完成+独立 reviewer 验收中;未终验不标 ChatGPT PASS"))
    args = ap.parse_args()
    if args.action == "status":
        return status()
    if not args.zip_sha256 or not args.git_commit:
        print("update 需要 --zip-sha256/--git-commit", file=sys.stderr)
        return 2
    return update(args.zip_sha256, args.git_commit,
                  args.status_line)


if __name__ == "__main__":
    raise SystemExit(main())
