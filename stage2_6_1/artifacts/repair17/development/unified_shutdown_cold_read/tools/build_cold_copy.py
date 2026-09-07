# -*- coding: utf-8 -*-
"""构建真正可搬移的冷读副本(WP3/RSS-03 修复面)。

从**已固定的 manifest/anchor**(可信清单,不扫描现存文件缩小集合)
逐项物理复制字节到独立根:
    <dest>/payload/<manifest 相对路径>   完整必要证据字节
    <dest>/metadata/                    固定清单+锚(原样复制)
    <dest>/verifier/r17_verify_delivery.py  与本次验证绑定的只读验证代码
    <dest>/metadata/copy_manifest.json  复制身份(来源声明/计数/哈希)

每项复制后重算 sha256 与 manifest 行核对(复制即校验);
软链接不跟随内容(拒绝 symlinks 作为伪复制)。

用法:
  python3 build_cold_copy.py --source-root <原始相对基准> \
      --manifest <m.jsonl> --anchor <a.json> --record-rel <相对路径> \
      --verifier <r17_verify_delivery.py> --dest <副本根>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from pathlib import Path


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source-root", required=True,
                    help="manifest 相对路径的原始基准(只读取)")
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--record-rel", required=True,
                    help="run_record 在 manifest 布局内的相对路径")
    ap.add_argument("--verifier", required=True,
                    help="r17_verify_delivery.py 路径(复制入副本)")
    ap.add_argument("--dest", required=True)
    args = ap.parse_args()

    src_root = Path(args.source_root).resolve()
    manifest = Path(args.manifest).resolve()
    anchor = Path(args.anchor).resolve()
    verifier = Path(args.verifier).resolve()
    dest = Path(args.dest).resolve()
    if dest.exists():
        print(f"ERROR: dest 已存在(一次性副本,不覆盖): {dest}",
              file=sys.stderr)
        return 2
    payload = dest / "payload"
    meta = dest / "metadata"
    ver_dir = dest / "verifier"
    for d in (payload, meta, ver_dir):
        d.mkdir(parents=True, exist_ok=True)

    rows = []
    for line in manifest.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    copied = 0
    total_bytes = 0
    for row in rows:
        rel = row["path"]
        s = src_root / rel
        if s.is_symlink():
            print(f"FAIL: 清单项是软链接(伪复制不接受): {rel}",
                  file=sys.stderr)
            return 1
        if not s.is_file():
            print(f"FAIL: 清单文件在原根缺失: {rel}", file=sys.stderr)
            return 1
        t = payload / rel
        t.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(s, t)  # 物理字节(非链接)
        got = sha256_file(t)
        if got != row["sha256"]:
            print(f"FAIL: 复制后哈希不符: {rel}", file=sys.stderr)
            return 1
        copied += 1
        total_bytes += row["bytes"]
    # metadata: 清单+锚原样复制(哈希与锚内声明一致)
    shutil.copyfile(manifest, meta / manifest.name)
    shutil.copyfile(anchor, meta / anchor.name)
    # verifier: 绑定本次验证的代码副本
    shutil.copyfile(verifier, ver_dir / verifier.name)
    copy_manifest = {
        "schema": "r17-cold-copy-v1",
        "built_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                   time.gmtime()),
        "source_root_declared": str(src_root),
        "note_source": "历史来源声明(仅 argv 身份;验证进程不回读)",
        "manifest_file": manifest.name,
        "anchor_file": anchor.name,
        "record_rel": args.record_rel,
        "run_id": rows[0].get("run_id") if rows else None,
        "files_copied": copied,
        "bytes_copied": total_bytes,
        "manifest_sha256": sha256_file(manifest),
        "anchor_sha256": sha256_file(anchor),
        "verifier_sha256": sha256_file(verifier),
        "verify_argv_hint": [
            "python3", "verifier/" + verifier.name, "verify",
            "--root", "payload",
            "--manifest", f"metadata/{manifest.name}",
            "--anchor-file", f"metadata/{anchor.name}",
            "--run-record", f"payload/{args.record_rel}"],
    }
    (meta / "copy_manifest.json").write_text(
        json.dumps(copy_manifest, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"rc": 0, "dest": str(dest),
                      "files": copied, "bytes": total_bytes},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
