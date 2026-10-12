#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""独立 ZIP 冷读校验器(FiniteRepair R3-04;reviewer/主 Agent 共用)。

**不复制打包器的过滤条件**:用 zipfile 独立枚举 ZIP 的全部成员,
自行得到"普通文件集合",与包内根 SHA256SUMS.txt 双向核对
(缺/多/重复/哈希错),并检查:
- 成员路径安全(无绝对路径/.. 段/反斜杠);
- 成员均为普通文件模式(无符号链接/无目录多余项——zip 目录项
  允许存在但不计入文件集合);
- CRC(zipfile.testzip 全量校验);
- 嵌套同名清单(任意深度的 SHA256SUMS.txt)必须在根清单中有条目
  (R2 缺陷的定向检查:旧包漏 evidence/task_pkg_in/SHA256SUMS.txt);
- acceptance_snapshot 快照在场且带 snapshot_meta;
- sidecar(.zip.sha256.txt)与实际 ZIP 哈希一致。

用法:python posctl_r3_pack_verify.py --zip <zip> [--sidecar <txt>]
     退出码 0=通过;1=失败(输出 JSON 报告)。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path, PurePosixPath


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True)
    ap.add_argument("--sidecar", default=None)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    zp = Path(args.zip)
    if not zp.exists():
        print(json.dumps({"error": f"zip 不存在:{zp}"}))
        return 1
    report = {"zip": str(zp), "zip_bytes": zp.stat().st_size,
              "problems": [], "stats": {}}

    # 实际 ZIP 哈希(与 sidecar 核对)
    h = hashlib.sha256()
    with zp.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    zip_sha = h.hexdigest()
    report["zip_sha256"] = zip_sha
    if args.sidecar:
        sc = Path(args.sidecar).read_text(encoding="utf-8").strip()
        expect = sc.split()[0] if sc else ""
        report["sidecar_matches"] = (expect == zip_sha)
        if expect != zip_sha:
            report["problems"].append(
                f"sidecar 哈希不符:{expect} != {zip_sha}")

    with zipfile.ZipFile(zp) as zf:
        infos = zf.infolist()
        seen = {}
        dup = []
        for info in infos:
            name = info.filename
            if name in seen:
                dup.append(name)
            seen[name] = True
            # 路径安全:正斜杠、相对、无 .. 段
            pp = PurePosixPath(name)
            if (name.startswith("/") or "\\" in name or ".." in
                    pp.parts):
                report["problems"].append(f"不安全成员路径:{name}")
            # 模式:只允许普通文件(0o644/0o600 等)与目录项
            mode = (info.external_attr >> 16) & 0xFFFF
            is_dir = name.endswith("/")
            if not is_dir and mode != 0 and (
                    mode & 0o170000) not in (0o100000, 0):
                report["problems"].append(
                    f"非普通文件模式成员:{name}(mode="
                    f"{oct(mode)})")
        if dup:
            report["problems"].append(f"重复成员:{sorted(set(dup))}")
        # CRC 全量校验
        bad = zf.testzip()
        if bad is not None:
            report["problems"].append(f"CRC 校验失败:{bad}")
        # 独立枚举普通文件集合(不复制打包器过滤条件);条目按
        # 包内顶层目录归一(根清单条目相对顶层目录,成员名带前缀)
        tops = {i.filename.split("/")[0] for i in infos
                if not i.filename.endswith("/")}
        top = sorted(tops)[0] if len(tops) == 1 else ""
        prefix = (top + "/") if top else ""
        actual_files = {}
        for info in infos:
            if info.filename.endswith("/"):
                continue
            name = info.filename
            rel = (name[len(prefix):] if name.startswith(prefix)
                   else name)
            data = zf.read(name)
            actual_files[rel] = sha256_bytes(data)
        # 根清单(顶层目录下的 SHA256SUMS.txt)
        manifest_name = prefix + "SHA256SUMS.txt"
        if manifest_name not in zf.namelist():
            report["problems"].append(
                f"缺根清单:{manifest_name or 'SHA256SUMS.txt'}")
            manifest_entries = {}
        else:
            manifest_entries = {}
            for line in zf.read(manifest_name).decode(
                    "utf-8").splitlines():
                if not line.strip():
                    continue
                sha, _, rel = line.partition("  ")
                manifest_entries[rel.strip()] = sha.strip()
        mf = set(manifest_entries)
        af = set(actual_files) - {"SHA256SUMS.txt"}
        missing = sorted(af - mf)        # 实有而清单无(漏覆盖)
        extra = sorted(mf - af)          # 清单有而实无
        wrong = sorted(
            rel for rel in (mf & af)
            if manifest_entries[rel] != actual_files[rel])
        if missing:
            report["problems"].append(
                f"清单漏覆盖 {len(missing)} 项:{missing[:10]}")
        if extra:
            report["problems"].append(
                f"清单多余 {len(extra)} 项:{extra[:10]}")
        if wrong:
            report["problems"].append(
                f"哈希不符 {len(wrong)} 项:{wrong[:10]}")
        # 定向:嵌套同名清单必须被根清单覆盖(R2 缺陷)
        nested = sorted(
            n for n in actual_files
            if n != "SHA256SUMS.txt"
            and PurePosixPath(n).name == "SHA256SUMS.txt")
        report["nested_manifests"] = nested
        uncovered = [n for n in nested if n not in manifest_entries]
        if uncovered:
            report["problems"].append(
                f"嵌套清单未被根清单覆盖:{uncovered}")
        # 快照在场
        snaps = sorted(
            n for n in actual_files
            if n.startswith("acceptance_snapshot/")
            and (n.endswith("INDEX.md") or n.endswith("LATEST.md")
                 or n.endswith("snapshot_meta.json")))
        report["acceptance_snapshot_members"] = snaps
        if len(snaps) < 3:
            report["problems"].append(
                "acceptance_snapshot 缺 INDEX/LATEST/snapshot_meta"
                f"(实得 {snaps})")
        report["stats"] = {
            "members_total": len(infos),
            "regular_files": len(actual_files),
            "manifest_entries": len(manifest_entries),
            "dirs": sum(1 for i in infos if i.filename.endswith("/")),
            "nested_manifests": len(nested),
        }
    report["pass"] = not report["problems"]
    text = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(text, encoding="utf-8")
    print(text)
    return 0 if report["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
