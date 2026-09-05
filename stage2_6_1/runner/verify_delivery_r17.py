#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 交付层:manifest 驱动组包 + 脱离开发目录的冷读核验(F4/WP5)。

组包(assemble 子命令):从 run manifest(r17_formal_log_manifest
.jsonl)取真实源文件清单,逐文件存在性+sha256+字节数校验后复制
到预声明发布布局,产出 delivery manifest(源绝对路径 → 交付相对
路径映射)。必需文件缺失/哈希不符/路径冲突/复制失败 = 显式失败
退出;禁止 || true、空 glob 静默成功。

冷读(cold-read 子命令):仅依靠 delivery manifest 与交付副本
核验(不读开发机绝对路径);用于发布目录的独立验收。

T20 反例复现:R16 组包从少一层 artifacts/ 的猜测目录复制并静默
跳过;本工具从 manifest 的 stdout_path 字段取真实路径,精确
复现"manifest 指向 $P/artifacts/<name>_chain_logs、猜测路径不
存在"的场景时应成功;真实必需文件被删时必须失败。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load_run_manifest(manifest_path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def required_sources(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """manifest → (源绝对路径, 期望 sha, 期望 bytes, 步骤, 类型)。"""
    out = []
    for r in rows:
        for kind in ("stdout", "stderr"):
            p = r.get(f"{kind}_path")
            if not p:
                continue
            out.append({
                "step": r["step"], "kind": kind, "source": p,
                "expected_sha256": r[f"{kind}_sha256"],
                "expected_bytes": r[f"{kind}_bytes"],
            })
    return out


def assemble(manifest_path: Path, delivery_dir: Path,
             extra_files: list[tuple[Path, str]] = ()) -> int:
    rows = load_run_manifest(manifest_path)
    sources = required_sources(rows)
    delivery_dir.mkdir(parents=True, exist_ok=True)
    raw_dir = delivery_dir / "raw_logs" / "chain"
    raw_dir.mkdir(parents=True, exist_ok=True)
    delivery: list[dict[str, Any]] = []
    problems: list[str] = []
    seen_names: dict[str, str] = {}
    for s in sources:
        src = Path(s["source"])
        name = src.name
        if not src.is_file():
            problems.append(f"缺失必需源文件({s['step']}/{s['kind']}):"
                            f"{src}")
            continue
        got_sha = _sha256_file(src)
        got_bytes = src.stat().st_size
        if got_sha != s["expected_sha256"] or \
                got_bytes != s["expected_bytes"]:
            problems.append(
                f"源文件与 manifest 不符({s['step']}/{s['kind']}):"
                f"{src} sha={got_sha[:12]}.. bytes={got_bytes} "
                f"(期望 sha={s['expected_sha256'][:12]}.. "
                f"bytes={s['expected_bytes']})")
            continue
        if name in seen_names:
            problems.append(f"交付路径冲突:{name} 已来自 "
                            f"{seen_names[name]}")
            continue
        dst = raw_dir / name
        shutil.copyfile(src, dst)
        if _sha256_file(dst) != got_sha:
            problems.append(f"复制后哈希不符:{dst}")
            continue
        seen_names[name] = f"{s['step']}/{s['kind']}"
        delivery.append({
            "step": s["step"], "kind": s["kind"],
            "source_absolute": str(src),
            "delivery_relative": str(
                dst.relative_to(delivery_dir)),
            "sha256": got_sha, "bytes": got_bytes})
    for src_path, rel in extra_files:
        src = Path(src_path)
        if not src.is_file():
            problems.append(f"缺失附加交付文件:{src}")
            continue
        dst = delivery_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        delivery.append({
            "step": "(extra)", "kind": "file",
            "source_absolute": str(src),
            "delivery_relative": rel,
            "sha256": _sha256_file(src),
            "bytes": src.stat().st_size})
    doc = {
        "format": "r17-delivery-manifest-v1",
        "run_manifest": str(manifest_path),
        "delivery_root": str(delivery_dir),
        "files": delivery,
        "n_files": len(delivery),
        "problems": problems,
        "evidence_complete": not problems,
    }
    (delivery_dir / "delivery_manifest.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1, sort_keys=True),
        encoding="utf-8")
    if problems:
        print(f"[assemble] FAIL: {len(problems)} 处问题")
        for p in problems:
            print("  -", p)
        return 1
    print(f"[assemble] OK: {len(delivery)} 文件,布局 "
          f"{delivery_dir}")
    return 0


def cold_read(delivery_dir: Path) -> int:
    """交付目录冷读:不依赖开发机绝对路径的独立核验。"""
    dm_path = delivery_dir / "delivery_manifest.json"
    if not dm_path.is_file():
        print("[cold-read] FAIL: delivery_manifest.json 缺失")
        return 1
    doc = json.loads(dm_path.read_text(encoding="utf-8"))
    problems: list[str] = []
    for f in doc.get("files", []):
        rel = f["delivery_relative"]
        p = delivery_dir / rel
        if not p.is_file():
            problems.append(f"交付文件缺失:{rel}")
            continue
        got_sha = _sha256_file(p)
        got_bytes = p.stat().st_size
        if got_sha != f.get("sha256") or got_bytes != f.get("bytes"):
            problems.append(
                f"交付文件与 delivery manifest 不符:{rel} "
                f"sha={got_sha[:12]}.. bytes={got_bytes}")
        if str(delivery_dir.resolve()) not in str(p.resolve()):
            problems.append(f"交付文件逃逸交付根:{rel}")
    # JSON 可解析性
    for f in doc.get("files", []):
        if f["delivery_relative"].endswith(".json"):
            try:
                json.loads((delivery_dir /
                            f["delivery_relative"]).read_text(
                                encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"JSON 不可解析:{f['delivery_relative']}"
                                f":{exc}")
    receipt = {
        "format": "r17-delivery-cold-read-receipt-v1",
        "delivery_root": str(delivery_dir),
        "n_files": len(doc.get("files", [])),
        "problems": problems,
        "evidence_complete": not problems,
    }
    (delivery_dir / "cold_read_receipt.json").write_text(
        json.dumps(receipt, ensure_ascii=False, indent=1,
                   sort_keys=True), encoding="utf-8")
    if problems:
        print(f"[cold-read] FAIL: {len(problems)} 处问题")
        for p in problems:
            print("  -", p)
        return 1
    print(f"[cold-read] OK: {len(doc.get('files', []))} 文件核验通过"
          f"(仅依赖交付映射)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="verify-delivery-r17")
    sub = parser.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("assemble")
    a.add_argument("--manifest", required=True)
    a.add_argument("--delivery-dir", required=True)
    a.add_argument("--extra", action="append", default=None,
                   help="附加文件 src=rel(可重复)")
    c = sub.add_parser("cold-read")
    c.add_argument("--delivery-dir", required=True)
    args = parser.parse_args(argv)
    if args.cmd == "assemble":
        extra = []
        for item in (args.extra or []):
            src, _, rel = item.partition("=")
            if not rel:
                print(f"[assemble] FAIL: --extra 格式应为 src=rel:"
                      f"{item}")
                return 1
            extra.append((Path(src), rel))
        return assemble(Path(args.manifest), Path(args.delivery_dir),
                        extra)
    return cold_read(Path(args.delivery_dir))


if __name__ == "__main__":
    sys.exit(main())
