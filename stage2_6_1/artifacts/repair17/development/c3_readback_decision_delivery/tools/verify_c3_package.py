#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 关联交付验证 driver(WP3:现存业务证据进实际验证集合)。

交付布局(物理组包;单一验证根=package/payload):
    package/payload/engineering_slice/...   八坐标切片+p52 负例+历史回执
    package/payload/c3_evidence/...         p52 诊断 v2 + 执行身份
    package/payload/p52_envelope/...        原 p52 调用依据(run 1475)
    package/payload/tools/...               新 reader + verifier 代码副本
    package/payload/runs/<run1>/...         监护验证 run 产物(finalize
                                            阶段复制;path 与 run_record
                                            .required 逐字一致)
    package/manifest.jsonl + anchor.json    (package 根之外置于 package/)

两个阶段:

--build(受监护 engineering run 的业务):
  1) 来源清单**预登记**(SOURCES:基线 commit 7977178 的 git blob id),
     逐项核对 git blob==预登记、blob 内容 sha==工作树文件 sha;
  2) 物理复制到 payload 分组目录并生成 manifest/anchor(record 与
     runs 行留待 finalize;manifest path 相对 payload);
  3) 语义正例:新 reader 只读读回发布树原件(零生成/零评估);
  4) 负例(语义错配自洽夹具,E03):tmp 副本 R05 式跨坐标引用+行哈希
     重算+夹具自身 manifest'/anchor'重锚——verifier 字节自洽通过、
     reader 语义拒绝;健康交付的 manifest/anchor 不被触碰;
  5) 业务监护 run 原件来源核对(c3diag/c3slice/c3readback;缺件如实
     记为历史缺口,不重跑制造)。

--finalize-record <rel>(监护 run 关闭后调用):
  复制 run1 产物到 payload/runs/<name>/,追加 role=record 行与全部
  required present 角色行(path 用 run_record 原始相对路径),重锚,
  并以 payload 为根直接 verifier verify(健康包字节验证)。

rc:0=全部通过;1=任何核对/验证失败;2=用法/IO 错误。
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

BASE_COMMIT = "797717830543d11b1f674f49f07a7ef0353ea4a1"
RUN_ID = "c3-rdd-package-v1"
_SL = ("stage2_6_1/artifacts/repair17/development/"
       "c3_evidence_generation_slice")
_ORIG_ENV_REL = (
    "stage2_6_1/artifacts/repair17/development/blocker_diagnosis/"
    "runs/20260906T134324Z_1475/"
    "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json")

#: 预登记来源清单(role, git blob@7977178|None, repo 相对路径,
#: payload 相对路径)。reader_tool 是本轮执行候选(工作树新代码),
#: 无已提交 blob——如实标注,不把未产生提交追填为旧身份。
SOURCES: list[tuple[str, str | None, str, str]] = [
    ("slice_recipe", "a5b368c84b0114e851395c5312e967a90bfc1187",
     f"{_SL}/engineering_slice/recipe.json",
     "engineering_slice/recipe.json"),
    ("slice_index", "00d03f204f466e2568b4329a40f2f1893cff42c2",
     f"{_SL}/engineering_slice/slice_results.jsonl",
     "engineering_slice/slice_results.jsonl"),
    ("slice_summary", "592d7212ee9645435dcb712b0c3c4e4d40376359",
     f"{_SL}/engineering_slice/slice_summary.json",
     "engineering_slice/slice_summary.json"),
    ("slice_p52_negative", "28edece380aade4f166f00628747c6d8b9fcd09b",
     f"{_SL}/engineering_slice/p52_negative.json",
     "engineering_slice/p52_negative.json"),
    ("slice_readback_historical",
     "9da35962ea89a0a4997717efcc7a40b1f45f6833",
     f"{_SL}/engineering_slice/readback_report.json",
     "engineering_slice/readback_report.json"),
    ("slice_pair_D0_p0", "9976e9648ffd00ef463e8075107fe0b7b123fda2",
     f"{_SL}/engineering_slice/pairs/D0_p0.json",
     "engineering_slice/pairs/D0_p0.json"),
    ("slice_pair_D0_p1", "63d4d245b1bff5dfa2d5ac9cedd34011fd9d54a3",
     f"{_SL}/engineering_slice/pairs/D0_p1.json",
     "engineering_slice/pairs/D0_p1.json"),
    ("slice_pair_D1_p0", "9a061db54bd9566d614adf5e2bb2852aca425aa8",
     f"{_SL}/engineering_slice/pairs/D1_p0.json",
     "engineering_slice/pairs/D1_p0.json"),
    ("slice_pair_D1_p1", "9d6c8deee69c722f3a04fe9ade2c31ba5377913f",
     f"{_SL}/engineering_slice/pairs/D1_p1.json",
     "engineering_slice/pairs/D1_p1.json"),
    ("slice_pair_D2_p0", "e8c0a1e5695783cc19f5b3a060f813b7c4e58579",
     f"{_SL}/engineering_slice/pairs/D2_p0.json",
     "engineering_slice/pairs/D2_p0.json"),
    ("slice_pair_D2_p1", "d4fa828a135e3c7700b70497be35ffbb17bb4f47",
     f"{_SL}/engineering_slice/pairs/D2_p1.json",
     "engineering_slice/pairs/D2_p1.json"),
    ("slice_pair_D3_p0", "e21a75fc8aa51b7b7f0768051f243b59d5dd62c4",
     f"{_SL}/engineering_slice/pairs/D3_p0.json",
     "engineering_slice/pairs/D3_p0.json"),
    ("slice_pair_D3_p1", "f75f28850de7dc1841cd703b5beb31f9545432f9",
     f"{_SL}/engineering_slice/pairs/D3_p1.json",
     "engineering_slice/pairs/D3_p1.json"),
    ("p52_diagnosis_v2", "b4e4fecb1481369f06c2d136001f1bfd6e39156a",
     f"{_SL}/c3_evidence/p52_diagnosis_v2.json",
     "c3_evidence/p52_diagnosis_v2.json"),
    ("execution_identity", "dd2b06264d06c8a62e70ae9e44aeb7740d4b1ae3",
     f"{_SL}/c3_evidence/execution_identity.json",
     "c3_evidence/execution_identity.json"),
    ("p52_original_envelope", "4bf0fb9b1dd6dd1c68da0671dc6ace566ee6ff1c",
     _ORIG_ENV_REL,
     "p52_envelope/generation_failure_envelopes_calibrate_c3_cost_"
     "D0_p52.json"),
    ("reader_tool", None,
     "stage2_6_1/runner/r17_c3_engineering_slice.py",
     "tools/r17_c3_engineering_slice.py"),
    ("verifier_tool", "bc33e9ca7bbeebf64ad446328f4f20f37df65003",
     "stage2_6_1/runner/r17_verify_delivery.py",
     "tools/r17_verify_delivery.py"),
]

#: 曾引用的业务监护 run(来源核对对象;不在 git 内,只登记原件事实)
MONITORED_RUNS = ("c3diag_p52_v2_20260908", "c3slice_20260908",
                  "c3readback_20260908")


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git_out(repo: Path, args: list[str]) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def run_reader(repo: Path, slice_dir: Path, envelope: Path,
               report: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable,
         str(repo / "stage2_6_1" / "runner"
            / "r17_c3_engineering_slice.py"),
         "--readback", str(slice_dir),
         "--p52-envelope", str(envelope),
         "--report", str(report)],
        capture_output=True, text=True, timeout=600)


def run_verifier(repo: Path, root: Path, manifest: Path, anchor: Path,
                 run_record: Path | None,
                 receipt_dir: Path) -> subprocess.CompletedProcess:
    argv = [sys.executable,
            str(repo / "stage2_6_1" / "runner"
                / "r17_verify_delivery.py"),
            "verify", "--root", str(root),
            "--manifest", str(manifest), "--anchor-file", str(anchor),
            "--receipt-dir", str(receipt_dir)]
    if run_record is not None:
        argv += ["--run-record", str(run_record)]
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=600)


def _write_manifest_anchor(pkg: Path, rows: list[dict],
                           run_record: Path | None,
                           run_record_sha: str | None) -> None:
    manifest = pkg / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    payload = pkg / "payload"
    anchor = {
        "schema": "r17-delivery-anchor-v1", "run_id": RUN_ID,
        "manifest_path": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "manifest_bytes": manifest.stat().st_size,
        "run_record_path": (str(run_record) if run_record else None),
        "run_record_sha256": run_record_sha,
        "root": str(payload), "built_utc": utc_now(),
        "git_commit": None, "manifest_blob_id": None,
        "missing_roles": [],
    }
    (pkg / "anchor.json").write_text(
        json.dumps(anchor, ensure_ascii=False, indent=1),
        encoding="utf-8")


def cmd_build(repo: Path, out: Path) -> int:
    pkg = out / "package"
    payload = pkg / "payload"
    receipts = out / "receipts"
    payload.mkdir(parents=True, exist_ok=True)
    receipts.mkdir(parents=True, exist_ok=True)
    report: dict = {
        "format": "r17rdd-c3-package-build-v2",
        "run_id": RUN_ID,
        "base_commit": BASE_COMMIT,
        "repo": str(repo),
        "built_utc": utc_now(),
        "source_verification": [],
        "monitored_run_sources": [],
        "payload_layout": "package/payload(单一验证根;runs/ 留待 finalize)",
    }
    problems: list[str] = []

    # 1) 来源逐项核对 + 物理复制到 payload 分组
    rows: list[dict] = []
    for role, blob, repo_rel, payload_rel in SOURCES:
        wt = repo / repo_rel
        entry: dict = {"role": role, "source_repo_path": repo_rel,
                       "payload_path": payload_rel}
        if not wt.is_file():
            problems.append(f"{role}: 工作树文件缺失 {repo_rel}")
            report["source_verification"].append(entry)
            continue
        wt_sha = sha256_file(wt)
        entry["source_sha256"] = wt_sha
        entry["bytes"] = wt.stat().st_size
        if blob is None:
            entry["source_note"] = ("working-tree execution candidate "
                                    "(this round's new reader; no "
                                    "committed blob at build time)")
        else:
            got = git_out(repo, ["ls-tree", BASE_COMMIT, "--", repo_rel])
            got_blob = got.split()[2] if got else "MISSING"
            if got_blob != blob:
                problems.append(
                    f"{role}: git blob {got_blob} != 预登记 {blob}")
                entry["git_blob"] = got_blob
                report["source_verification"].append(entry)
                continue
            entry["git_blob"] = got_blob
            blob_sha = hashlib.sha256(subprocess.run(
                ["git", "-C", str(repo), "cat-file", "blob", blob],
                capture_output=True, check=True).stdout).hexdigest()
            if blob_sha != wt_sha:
                problems.append(
                    f"{role}: blob 内容 sha != 工作树 sha({blob_sha[:12]}"
                    f" vs {wt_sha[:12]})")
        dst = payload / payload_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wt, dst)
        if sha256_file(dst) != wt_sha:
            problems.append(f"{role}: 复制后哈希不一致 {payload_rel}")
        report["source_verification"].append(entry)
        rows.append({"schema": "r17-delivery-manifest-v2",
                     "run_id": RUN_ID, "role": role,
                     "path": payload_rel, "sha256": wt_sha,
                     "bytes": wt.stat().st_size})

    _write_manifest_anchor(pkg, rows, None, None)

    # 2) 监护 run 原件来源核对(不重跑;缺件=历史缺口)
    for name in MONITORED_RUNS:
        d = (repo / "stage2_6_1/artifacts/repair17/development/"
             f"run_supervision/runs/{name}")
        item = {"run": name}
        if d.is_dir():
            item["present"] = True
            for f in ("run_record.json", "summary.json"):
                p = d / f
                item[f] = ({"sha256": sha256_file(p),
                            "bytes": p.stat().st_size}
                           if p.is_file() else "missing")
        else:
            item["present"] = False
            item["note"] = "历史缺口(原件不在本机;不重跑制造)"
        report["monitored_run_sources"].append(item)

    # 3) 语义正例:reader 只读读回发布树原件
    if not problems:
        r = run_reader(repo,
                       repo / f"{_SL}/engineering_slice",
                       repo / _ORIG_ENV_REL,
                       receipts / "semantic_health.json")
        verdict = None
        hp = receipts / "semantic_health.json"
        if hp.is_file():
            try:
                verdict = json.loads(
                    hp.read_text(encoding="utf-8")).get(
                        "readback_verdict")
            except (json.JSONDecodeError, OSError):
                verdict = None
        report["semantic_health"] = {"rc": r.returncode,
                                     "verdict": verdict}
        if r.returncode != 0:
            problems.append("语义正例 reader 未 PASS")
    else:
        report["semantic_health"] = "skipped: 来源核对已失败"

    # 4) 负例:语义错配自洽夹具(E03;健康锚不被触碰)
    if not problems:
        fixture = out / "tmp_semantic_mismatch"
        slice_copy = fixture / "payload" / "engineering_slice"
        slice_copy.parent.mkdir(parents=True)
        src_payload = payload / "engineering_slice"
        shutil.copytree(src_payload, slice_copy)
        rows_path = slice_copy / "slice_results.jsonl"
        lines = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in lines:
            if row["coord"] == "D1/p0":
                row["detail"] = "D0_p0.json"
                row["detail_sha256"] = sha256_file(
                    slice_copy / "pairs" / "D0_p0.json")
        rows_path.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        frows = []
        for p in sorted(slice_copy.rglob("*")):
            if p.is_file():
                frows.append({
                    "schema": "r17-delivery-manifest-v2",
                    "run_id": f"{RUN_ID}-semantic-fixture",
                    "role": f"fixture:{p.relative_to(slice_copy)}",
                    "path": str(p.relative_to(fixture / "payload")),
                    "sha256": sha256_file(p),
                    "bytes": p.stat().st_size})
        fman = fixture / "manifest.jsonl"
        with fman.open("w", encoding="utf-8", newline="\n") as fh:
            for row in frows:
                fh.write(json.dumps(row, ensure_ascii=False,
                                    separators=(",", ":")) + "\n")
        fanchor = {
            "schema": "r17-delivery-anchor-v1",
            "run_id": f"{RUN_ID}-semantic-fixture",
            "manifest_path": str(fman),
            "manifest_sha256": sha256_file(fman),
            "manifest_bytes": fman.stat().st_size,
            "run_record_path": None, "run_record_sha256": None,
            "root": str(fixture / "payload"),
            "built_utc": utc_now(),
            "git_commit": None, "manifest_blob_id": None,
            "missing_roles": [],
        }
        (fixture / "anchor.json").write_text(
            json.dumps(fanchor, ensure_ascii=False, indent=1),
            encoding="utf-8")
        v = run_verifier(repo, fixture / "payload", fman,
                         fixture / "anchor.json", None,
                         receipts / "semantic_mismatch_neg")
        env_copy = fixture / "payload" / "p52_envelope.json"
        shutil.copyfile(repo / _ORIG_ENV_REL, env_copy)
        vr = run_reader(repo, slice_copy, env_copy,
                        receipts / "semantic_mismatch_neg"
                        / "reader_receipt.json")
        report["semantic_mismatch_fixture"] = {
            "note": ("自洽夹具只作用于夹具目录(payload 副本+夹具自身"
                     "manifest'/anchor');不修改或重新签署健康交付的"
                     "manifest/anchor"),
            "verifier_rc": v.returncode,
            "verifier_note": "verifier 字节自洽应通过(外层哈希不检出"
                             "该语义错配)",
            "reader_rc": vr.returncode,
            "reader_note": "reader 必须拒绝(内层语义关系失败)",
        }
        if v.returncode != 0:
            problems.append("夹具 verifier 未自洽通过(构造错误)")
        if vr.returncode != 1:
            problems.append("夹具 reader 未按语义拒绝")

    report["n_problems"] = len(problems)
    report["problems"] = problems
    report["build_verdict"] = "PASS" if not problems else "FAIL"
    (out / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1),
        encoding="utf-8")
    print(json.dumps({"build_verdict": report["build_verdict"],
                      "n_problems": len(problems),
                      "out": str(out)}, ensure_ascii=False))
    return 0 if not problems else 1


def cmd_finalize_record(repo: Path, out: Path, rr_repo_rel: str) -> int:
    """复制 run1 产物到 payload/runs/,追加 record+required 角色行
    (path 用 run_record 原始相对路径,与 required 逐字一致),重锚,
    以 payload 为根直接 verifier verify。"""
    pkg = out / "package"
    payload = pkg / "payload"
    manifest = pkg / "manifest.jsonl"
    rr = repo / rr_repo_rel
    if not rr.is_file():
        print(f"FATAL: run_record 不存在: {rr}", file=sys.stderr)
        return 2
    rows = [json.loads(l) for l in manifest.read_text(
        encoding="utf-8").splitlines() if l.strip()]
    if any(r.get("role") == "record" for r in rows):
        print("FATAL: record 行已存在(一次性合同)", file=sys.stderr)
        return 2
    rr_doc = json.loads(rr.read_text(encoding="utf-8"))
    rs_root = (repo / "stage2_6_1/artifacts/repair17/development"
               / "run_supervision")

    def copy_into_payload(rr_path: str) -> Path:
        src = rs_root / rr_path
        dst = payload / rr_path
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)
        if sha256_file(dst) != sha256_file(src):
            raise RuntimeError(f"复制哈希不一致: {rr_path}")
        return dst

    # record 行(path=run_record 在 payload 内的 runs/ 相对路径)
    rr_rel_in_payload = rr_doc.get("argv_run_rel") or str(
        Path(rr_repo_rel).relative_to(
            "stage2_6_1/artifacts/repair17/development/run_supervision"))
    rr_dst = copy_into_payload(rr_rel_in_payload)
    rr_sha = sha256_file(rr_dst)
    rows.append({"schema": "r17-delivery-manifest-v2",
                 "run_id": RUN_ID, "role": "record",
                 "path": rr_rel_in_payload, "sha256": rr_sha,
                 "bytes": rr_dst.stat().st_size})
    # required 角色(path 逐字=run_record 原始 path)
    n_roles = 0
    for item in rr_doc.get("required", []):
        if not isinstance(item, dict) or item.get("external"):
            continue
        if str(item.get("status", "present")) != "present":
            continue
        dst = copy_into_payload(str(item["path"]))
        rows.append({"schema": "r17-delivery-manifest-v2",
                     "run_id": RUN_ID, "role": str(item["role"]),
                     "path": str(item["path"]),
                     "sha256": sha256_file(dst),
                     "bytes": dst.stat().st_size})
        n_roles += 1

    _write_manifest_anchor(pkg, rows, rr_dst, rr_sha)
    v = run_verifier(repo, payload, pkg / "manifest.jsonl",
                     pkg / "anchor.json", rr_dst,
                     out / "receipts")
    doc = {
        "format": "r17rdd-c3-package-finalize-v1",
        "record_rel_in_payload": rr_rel_in_payload,
        "n_required_roles_appended": n_roles,
        "verifier_rc": v.returncode,
        "verifier_stdout_tail": v.stdout[-500:],
        "finalized_utc": utc_now(),
    }
    (out / "finalize_report.json").write_text(
        json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(doc, ensure_ascii=False))
    return v.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", required=True,
                    help="发布树根(如 /mnt/f/trading/freqai-rl-audit)")
    ap.add_argument("--out", required=True, help="本轮验证输出目录")
    sub = ap.add_mutually_exclusive_group(required=True)
    sub.add_argument("--build", action="store_true")
    sub.add_argument("--finalize-record", metavar="REPO_REL",
                    help="追加 run_record 行并直接验证(监护 run 关闭后)")
    args = ap.parse_args()
    repo = Path(args.repo).resolve()
    out = Path(args.out).resolve()
    if args.build:
        if out.exists() and any(out.iterdir()):
            print(f"FATAL: {out} 非空(一次性合同)", file=sys.stderr)
            return 2
        out.mkdir(parents=True, exist_ok=True)
        return cmd_build(repo, out)
    return cmd_finalize_record(repo, out, args.finalize_record)


if __name__ == "__main__":
    sys.exit(main())
