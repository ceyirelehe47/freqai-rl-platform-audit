#!/usr/bin/env python3
"""R17 诊断交付冷读(任务书 §12-6):manifest 驱动,脱离开发绝对路径。
用法: python3 cold_read_check.py <blocker_diagnosis_dir>
步骤: 1) 对目录生成 manifest(相对路径→sha256/bytes)
      2) 复制整目录到临时位置(脱离开发树)
      3) 在副本上按 manifest 逐文件重算哈希/长度比对
      4) 篡改反例(改动一个字节后必须检出)"""
import hashlib
import shutil
import sys
import tempfile
from pathlib import Path


def digest(p: Path):
    h = hashlib.sha256()
    n = 0
    with p.open("rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
            n += len(b)
    return h.hexdigest(), n


def build_manifest(root: Path):
    rows = []
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.name != "delivery_manifest.jsonl":
            sha, n = digest(p)
            rows.append((str(p.relative_to(root)), sha, n))
    return rows


def verify(root: Path, rows):
    bad = []
    for rel, sha, n in rows:
        p = root / rel
        if not p.is_file():
            bad.append(f"missing {rel}")
            continue
        s2, n2 = digest(p)
        if s2 != sha or n2 != n:
            bad.append(f"mismatch {rel}")
    return bad


def main():
    src = Path(sys.argv[1]).resolve()
    rows = build_manifest(src)
    manifest = src / "delivery_manifest.jsonl"
    with manifest.open("w", encoding="utf-8") as fh:
        for rel, sha, n in rows:
            fh.write(f'{{"path": {rel!r}, "sha256": "{sha}", "bytes": {n}}}\n'
                     .replace("'", '"'))
    print(f"manifest: {len(rows)} files -> {manifest}")
    with tempfile.TemporaryDirectory() as td:
        copy = Path(td) / "cold_read_copy"
        shutil.copytree(src, copy)
        # 冷读:在副本上重算(排除 manifest 自身的自引用)
        rows2 = [(r, s, n) for r, s, n in rows]
        bad = verify(copy, rows2)
        assert not bad, f"cold read FAIL: {bad}"
        # 篡改反例:改动副本一个字节必须被检出
        victim = copy / rows[0][0]
        data = bytearray(victim.read_bytes())
        data[len(data) // 2] ^= 0x01
        victim.write_bytes(bytes(data))
        bad2 = verify(copy, rows2)
        assert any("mismatch" in b for b in bad2), "tamper NOT detected"
        print(f"cold read PASS: {len(rows)} files verified in isolated copy;"
              " tamper detected as expected")
        # 缺件反例:删除副本一个文件必须被检出
        (copy / rows[-1][0]).unlink()
        bad3 = verify(copy, rows2)
        assert any("missing" in b for b in bad3), "missing NOT detected"
        print("missing-file detection PASS")


if __name__ == "__main__":
    main()
