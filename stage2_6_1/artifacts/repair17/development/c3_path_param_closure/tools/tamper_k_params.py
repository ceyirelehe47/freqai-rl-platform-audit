#!/usr/bin/env python
"""K 系负例副本篡改(共享):必要课程键删除/置 null。

按生产权威 canonical 合同重算该条 envelope digest,并同步索引行
detail_sha256、manifest 行与 anchor(字节层自洽)——使字节 verifier
通过,拒绝只能来自 reader 参数语义层。

用法:
  tamper_k_params.py drop --pkg <pkg_dir> [--authority-src <src>]
  tamper_k_params.py null --pkg <pkg_dir> [--authority-src <src>]

- drop:payload/engineering_slice/pairs/D0_p0.json 的 env0.base_params.A
  删除 alpha_bps(矩阵 K01 形态);
- null:同位置 vol_bps 置 null(矩阵 K02 形态:存在但不一致)。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("drop", "null"))
    ap.add_argument("--pkg", required=True, type=Path)
    ap.add_argument("--authority-src", type=Path)
    args = ap.parse_args()
    pkg = args.pkg.resolve()
    # 生产权威模块完整 src(部署树;发布树 stage2_6_1/src 是子集)
    asrc = args.authority_src or (Path.home() / "projects" / "crypto_rl"
                                  / "src")
    if str(asrc) not in sys.path:
        sys.path.insert(0, str(asrc))
    from rl_curriculum.curriculum261_generation_envelope import (
        _digest_body, stable_digest)

    dpath = pkg / "payload" / "engineering_slice" / "pairs" / "D0_p0.json"
    doc = json.loads(dpath.read_text(encoding="utf-8"))
    env0 = doc["attempt_envelopes"][0]
    if args.mode == "drop":
        env0["base_params"]["A"].pop("alpha_bps")
    else:
        env0["base_params"]["A"]["vol_bps"] = None
    env0["digest"] = stable_digest(_digest_body(env0), "r11env-")
    dpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                     encoding="utf-8")

    # 索引行同步
    rows_path = (pkg / "payload" / "engineering_slice"
                 / "slice_results.jsonl")
    rows = [json.loads(l) for l in rows_path.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    for row in rows:
        if row.get("coord") == "D0/p0":
            row["detail_sha256"] = sha256_file(dpath)
    rows_path.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
        encoding="utf-8")

    # manifest 行与 anchor 重锚(字节层自洽)
    mp = pkg / "manifest.jsonl"
    mrows = [json.loads(l) for l in mp.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    for r in mrows:
        if r.get("role") == "slice_pair_D0_p0":
            r["sha256"] = sha256_file(dpath)
            r["bytes"] = dpath.stat().st_size
        elif r.get("role") == "slice_index":
            r["sha256"] = sha256_file(rows_path)
            r["bytes"] = rows_path.stat().st_size
    mp.write_text("\n".join(json.dumps(r, ensure_ascii=False,
                                       separators=(",", ":"))
                            for r in mrows) + "\n", encoding="utf-8")
    anchor = json.loads((pkg / "anchor.json").read_text(encoding="utf-8"))
    anchor["manifest_sha256"] = sha256_file(mp)
    anchor["manifest_bytes"] = mp.stat().st_size
    (pkg / "anchor.json").write_text(
        json.dumps(anchor, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"tampered mode={args.mode} pkg={pkg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
