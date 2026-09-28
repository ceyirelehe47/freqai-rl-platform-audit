#!/usr/bin/env python3
"""RouteC_QualifiedInput_TrainingBridge_v1 RETURN 打包(主 Agent 用)。

显式 root_name 前缀(R25 坑位:Path.relative_to(parent) 会把根目录吃掉)。
打包内容在 review 通过后固定;SHA256SUMS 精确覆盖全部普通文件,不自哈希。
"""
from __future__ import annotations

import hashlib
import sys
import zipfile
from pathlib import Path

REPO = Path("F:/trading/freqai-rl-audit")
TB = REPO / "stage2_6_1/artifacts/repair17/development/tb_training_bridge_v1"
ENG = REPO / "stage2_6_2/artifacts/eng_training_bridge_v1"
ROOT_NAME = "RouteC_QualifiedInput_TrainingBridge_v1_RETURN"
OUT = Path("F:/trading/trading/outgoing")

#: (source_path, archive_relpath) —— review 后固定
MEMBERS: list[tuple[Path, str]] = []


def add_dir(src: Path, rel: str, *, skip: tuple[str, ...] = ()) -> None:
    for p in sorted(src.rglob("*")):
        if p.is_dir():
            continue
        if any(part in skip for part in p.parts):
            continue
        MEMBERS.append((p, f"{rel}/{p.relative_to(src).as_posix()}"))


def add_file(src: Path, rel: str) -> None:
    MEMBERS.append((src, rel))


def build() -> None:
    import json
    manifest = {
        "format": "tb_v1_return_manifest",
        "root": ROOT_NAME,
        "members": [{"path": rel, "sha256": hashlib.sha256(
            src.read_bytes()).hexdigest(), "bytes": src.stat().st_size}
            for src, rel in MEMBERS],
    }
    stage = TB / "return_stage"
    (stage / "RETURN_MANIFEST.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    zip_path = OUT / f"{ROOT_NAME}_TO_CHATGPT.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for src, rel in MEMBERS:
            zf.write(src, f"{ROOT_NAME}/{rel}")
    h = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    (OUT / f"{ROOT_NAME}_TO_CHATGPT.zip.sha256.txt").write_text(
        f"{h}  {zip_path.name}\n", encoding="utf-8")
    print(json.dumps({"zip": str(zip_path), "sha256": h,
                      "bytes": zip_path.stat().st_size,
                      "members": len(MEMBERS)}, indent=2))


if __name__ == "__main__":
    # 成员清单由 assemble_members 注入(review 通过后固定字节)
    from tb_v1_return_members import assemble_members
    assemble_members(add_dir, add_file)
    build()
