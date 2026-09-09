#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 r3 必要字节只读检查(audit_run_bytes.py 未随包交付的等价实现)。

只读取证:不导入项目、不启停进程、不产生课程、不创建输出文件,
只在 stdout 输出 JSON。变更(CRLF↔LF)仅发生在内存、仅用于定位,
不把变换后匹配当作原件匹配。

用法:
  python r17_audit_run_bytes_equiv.py --root <run_supervision 目录> \
      --record <run_record.json 绝对路径> [--telemetry-hints]

退出码:0=逐项 required 当前字节全部匹配;1=缺件/状态/大小/摘要/读取
稳定性不符;2=参数或 record 读取等错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def read_stable(path: Path) -> tuple[bytes | None, bool]:
    """读两次,返回(字节, 两次一致)。"""
    try:
        b1 = path.read_bytes()
        b2 = path.read_bytes()
    except OSError:
        return None, False
    return b1, b1 == b2


def check(root: Path, record_path: Path, hints: bool) -> tuple[int, dict]:
    try:
        rec = json.loads(record_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return 2, {"error": f"record 读取失败: {exc}"}
    required = rec.get("required") or []
    if not isinstance(required, list) or not required:
        return 2, {"error": "record.required 缺失或为空"}

    times = {k: rec.get(k) for k in (
        "sealed_utc", "finalized_utc", "completed_utc", "started_utc",
        "business_started_utc", "shutdown_utc") if rec.get(k) is not None}

    items = []
    all_ok = True
    for r in required:
        role = r.get("role")
        rel = r.get("path")
        reg_bytes = r.get("bytes")
        reg_sha = r.get("sha256")
        item: dict = {"role": role, "path": rel,
                      "registered_bytes": reg_bytes,
                      "registered_sha256": reg_sha}
        p = (root / rel) if not Path(rel).is_absolute() else Path(rel)
        item["resolved"] = str(p)
        if not p.is_file():
            item.update(exists=False, ok=False,
                        problem="缺件")
            items.append(item)
            all_ok = False
            continue
        data, stable = read_stable(p)
        cur_sha = sha_bytes(data)
        cur_bytes = len(data)
        ok = (cur_bytes == reg_bytes and cur_sha == reg_sha and stable)
        item.update(exists=True, current_bytes=cur_bytes,
                    current_sha256=cur_sha, read_stable=stable,
                    bytes_match=cur_bytes == reg_bytes,
                    sha_match=cur_sha == reg_sha, ok=ok)
        if not ok:
            all_ok = False
            probs = []
            if cur_bytes != reg_bytes:
                probs.append(f"大小 {cur_bytes} != 登记 {reg_bytes}"
                             f" (delta {cur_bytes - (reg_bytes or 0)})")
            if cur_sha != reg_sha:
                probs.append("sha256 不匹配登记")
            if not stable:
                probs.append("两次读取不一致(仍在写入?)")
            item["problem"] = "; ".join(probs)

        if hints and ("telemetry" in str(role)):
            # 原字节与两种行尾形态的整文件摘要 + 登记长度前缀摘要
            forms = {
                "original": data,
                "crlf_to_lf": data.replace(b"\r\n", b"\n"),
                "lf_to_crlf": data.replace(b"\n", b"\r\n")
                if b"\r\n" not in data else data,
            }
            hint: dict = {}
            for name, blob in forms.items():
                entry = {"bytes": len(blob), "sha256": sha_bytes(blob)}
                if isinstance(reg_bytes, int) and 0 < reg_bytes <= len(blob):
                    prefix = blob[:reg_bytes]
                    entry["prefix_registered_len_sha256"] = sha_bytes(prefix)
                    entry["prefix_registered_len_bytes"] = len(prefix)
                    entry["prefix_matches_registered_sha"] = (
                        sha_bytes(prefix) == reg_sha)
                hint[name] = entry
            # 登记值本身若对应某种形态整文件
            hint["registered_matches_form"] = {
                n: (f["sha256"] == reg_sha) for n, f in hint.items()
                if isinstance(f, dict)}
            item["telemetry_hints"] = hint
        items.append(item)

    doc = {
        "schema": "r17-run-bytes-audit-equiv-v1",
        "record": str(record_path),
        "root": str(root),
        "record_times": times,
        "n_required": len(items),
        "all_match": all_ok,
        "items": items,
        "note": "只读检查;行尾变换仅在内存用于定位,不作原件匹配依据;"
                "不修改任何文件或锚",
    }
    return (0 if all_ok else 1), doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--root", required=True)
    ap.add_argument("--record", required=True)
    ap.add_argument("--telemetry-hints", action="store_true")
    args = ap.parse_args(argv)
    rc, doc = check(Path(args.root), Path(args.record),
                    args.telemetry_hints)
    print(json.dumps(doc, ensure_ascii=False, indent=1))
    return rc


if __name__ == "__main__":
    sys.exit(main())
