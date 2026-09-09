#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 c3-entry-temp-ownership-closure:本轮新验证包构建(v5 包)。

用相同旧业务字节(BASE=24eaa81 git blob + 工作树双核验)加本轮新
reader(v5:末端条目判定/解析错误分类/临时件所有权)建独立验证包;
不替换、不重签此前任何轮次的旧包(v3/v4 均保持历史)。

v5 新增夹具(在本轮两个工作包语义上):
  PE01:跨目录悬空末端链接 report 目标 → reader 写前拒绝(rc=2),
       悬空目标不被创建,链接条目原样;
  TO01:固定 datetime 强制临时名碰撞,预置外部普通文件占位 →
       创建失败不删除外部对象(字节/身份不变),ReceiptWriteError。
保留 v4 夹具(I02 四处闭合/K01 必要键缺失)防参数身份回归。

用法(WSL 或发布树):
  build_v5_package.py build --repo <repo> --out <pkg_dir>

一次性合同:out 非空即拒绝(rc=2),不覆盖任何历史产物。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_COMMIT = "24eaa81cf36b1bfa8755145ba56d1996653e9d50"
RUN_ID = "c3-eto-package-v5"

#: (role, repo 相对路径, payload 相对路径);git blob 与工作树双核验
SOURCES: tuple[tuple[str, str, str], ...] = (
    ("slice_recipe", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/engineering_slice/recipe.json",
     "engineering_slice/recipe.json"),
    ("slice_index", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/engineering_slice/slice_results.jsonl",
     "engineering_slice/slice_results.jsonl"),
    ("slice_summary", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/engineering_slice/slice_summary.json",
     "engineering_slice/slice_summary.json"),
    ("slice_p52_negative", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/engineering_slice/p52_negative.json",
     "engineering_slice/p52_negative.json"),
    ("slice_readback_historical", "stage2_6_1/artifacts/repair17/"
     "development/c3_evidence_generation_slice/engineering_slice/"
     "readback_report.json",
     "engineering_slice/readback_report.json"),
    *[("slice_pair_D%d_p%d" % (di, pi),
       "stage2_6_1/artifacts/repair17/development/"
       "c3_evidence_generation_slice/engineering_slice/pairs/D%d_p%d.json"
       % (di, pi),
       "engineering_slice/pairs/D%d_p%d.json" % (di, pi))
      for di in range(4) for pi in range(2)],
    ("p52_diagnosis_v2", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/c3_evidence/p52_diagnosis_v2.json",
     "c3_evidence/p52_diagnosis_v2.json"),
    ("execution_identity", "stage2_6_1/artifacts/repair17/development/"
     "c3_evidence_generation_slice/c3_evidence/execution_identity.json",
     "c3_evidence/execution_identity.json"),
    ("p52_original_envelope", "stage2_6_1/artifacts/repair17/development/"
     "blocker_diagnosis/runs/20260906T134324Z_1475/"
     "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json",
     "p52_envelope/generation_failure_envelopes_calibrate_c3_cost_"
     "D0_p52.json"),
    # 本轮新 reader:工作树执行候选(无 BASE blob,登记实际 sha)
    ("reader_v5", "stage2_6_1/runner/r17_c3_engineering_slice.py",
     "tools/r17_c3_engineering_slice.py"),
    # 字节 verifier:BASE 锚定
    ("verifier_tool", "stage2_6_1/runner/r17_verify_delivery.py",
     "tools/r17_verify_delivery.py"),
)


def utc_now() -> str:
    import time
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True,
        text=True, check=True).stdout.strip()


def git_blob_bytes(repo: Path, blob: str) -> bytes:
    """二进制读 blob 内容(不做任何行尾归一,字节级对照工作树)。"""
    return subprocess.run(
        ["git", "-C", str(repo), "cat-file", "blob", blob],
        capture_output=True, check=True).stdout


def run_reader(reader: Path, slice_dir: Path, envelope: Path,
               report: Path, protect: Path | None = None,
               timeout: int = 600) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(reader), "--readback", str(slice_dir),
            "--p52-envelope", str(envelope), "--report", str(report)]
    if protect is not None:
        argv += ["--protect-root", str(protect)]
    return subprocess.run(argv, capture_output=True, text=True,
                          timeout=timeout)


def run_verifier(verifier: Path, root: Path, manifest: Path,
                 anchor: Path, receipt_dir: Path,
                 timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(verifier), "verify", "--root", str(root),
         "--manifest", str(manifest), "--anchor-file", str(anchor),
         "--receipt-dir", str(receipt_dir)],
        capture_output=True, text=True, timeout=timeout)


def write_manifest_anchor(pkg: Path, rows: list[dict]) -> None:
    manifest = pkg / "manifest.jsonl"
    with manifest.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    anchor = {
        "schema": "r17-delivery-anchor-v1", "run_id": RUN_ID,
        "manifest_path": str(manifest),
        "manifest_sha256": sha256_file(manifest),
        "manifest_bytes": manifest.stat().st_size,
        "run_record_path": None, "run_record_sha256": None,
        "root": str(pkg / "payload"), "built_utc": utc_now(),
        "git_commit": BASE_COMMIT, "manifest_blob_id": None,
        "missing_roles": [],
    }
    (pkg / "anchor.json").write_text(
        json.dumps(anchor, ensure_ascii=False, indent=1), encoding="utf-8")


def fixture_pe01(reader: Path, payload: Path, receipts: Path) -> dict:
    """PE01 夹具:跨目录悬空末端链接 report 目标(独立 tmp;不动包)。"""
    work = receipts.parent / "tmp_fixture_pe01"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    (work / "receipts").mkdir()
    (work / "elsewhere").mkdir()
    link = work / "receipts" / "result.json"
    os.symlink("../elsewhere/missing.json", link)
    missing = work / "elsewhere" / "missing.json"
    r = run_reader(reader, payload / "engineering_slice",
                   payload / "p52_envelope/"
                   "generation_failure_envelopes_calibrate_c3_cost_"
                   "D0_p52.json", link)
    return {
        "step": "fixture_pe01_crossdir_dangling_end_link",
        "reader_rc": r.returncode,
        "expected": {"reader_rc": 2},
        "missing_target_created": missing.exists(),
        "link_entry_intact": link.is_symlink()
        and os.readlink(link) == "../elsewhere/missing.json",
        "stderr_has_original_entry": str(link) in (r.stderr or ""),
    }


def fixture_to01(reader: Path) -> dict:
    """TO01 夹具:固定 datetime 强制临时名碰撞(函数级,本进程)。"""
    work = reader.parent.parent / "artifacts" / "repair17" / \
        "development" / "c3_entry_temp_ownership_closure" / \
        "verification_v5" / "tmp_fixture_to01"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    out = work / "out"
    out.mkdir()
    target = out / "result.json"
    stamp = "20260909T120000000000"
    spec = importlib.util.spec_from_file_location("eto_reader_v5", reader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    when = datetime.strptime(stamp, "%Y%m%dT%H%M%S%f").replace(
        tzinfo=timezone.utc)

    class _FixedDT:
        @staticmethod
        def now(tz):
            return when

    mod.datetime = _FixedDT
    tmp = target.with_name(
        f".{target.name}.{os.getpid()}.{stamp}.tmp")
    tmp.write_text("PREEXISTING_FOREIGN_TEMP", encoding="utf-8")
    b0 = tmp.read_bytes()
    st0 = tmp.stat()
    err = None
    try:
        mod._atomic_write_receipt(target, {"k": "v"})
    except Exception as exc:  # noqa: BLE001 —— 留档原始异常
        err = f"{type(exc).__name__}"
    st1 = tmp.stat()
    return {
        "step": "fixture_to01_temp_collision_ownership",
        "error": err,
        "expected": {"error": "ReceiptWriteError"},
        "foreign_bytes_unchanged": tmp.read_bytes() == b0,
        "foreign_identity_unchanged": (st1.st_ino, st1.st_mtime_ns)
        == (st0.st_ino, st0.st_mtime_ns),
        "final_target_created": target.exists(),
    }


def cmd_build(repo: Path, out: Path, authority_src: Path) -> int:
    if out.exists() and any(out.iterdir()):
        print(f"refusing: {out} 非空(一次性合同)", file=sys.stderr)
        return 2
    payload = out / "payload"
    receipts = out.parent / "receipts_v5"
    receipts.mkdir(parents=True, exist_ok=True)

    rows: list[dict] = []
    report: dict = {"run_id": RUN_ID, "base_commit": BASE_COMMIT,
                    "sources": [], "steps": []}
    for role, repo_rel, payload_rel in SOURCES:
        wt = repo / repo_rel
        if not wt.is_file():
            print(f"FATAL 缺工作树文件: {wt}", file=sys.stderr)
            return 1
        wt_sha = sha256_file(wt)
        if role == "reader_v5":
            blob = None  # 本轮新文件,无 BASE blob
        else:
            blob = git(repo, "ls-tree", BASE_COMMIT, "--", repo_rel)
            blob = blob.split()[2] if blob else None
            if blob is None:
                print(f"FATAL BASE 缺 blob: {repo_rel}", file=sys.stderr)
                return 1
            content_sha = hashlib.sha256(
                git_blob_bytes(repo, blob)).hexdigest()
            if content_sha != wt_sha:
                print(f"FATAL 工作树与 BASE blob 不一致: {repo_rel}"
                      f" ({wt_sha[:12]} vs {content_sha[:12]})",
                      file=sys.stderr)
                return 1
        dst = payload / payload_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(wt, dst)
        got = sha256_file(dst)
        assert got == wt_sha, f"复制不一致: {dst}"
        rows.append({"schema": "r17-delivery-manifest-v2",
                     "run_id": RUN_ID, "role": role,
                     "path": payload_rel, "sha256": got,
                     "bytes": dst.stat().st_size})
        report["sources"].append(
            {"role": role, "repo_path": repo_rel,
             "payload_path": payload_rel, "sha256": got,
             "base_blob": blob, "bytes": dst.stat().st_size})

    write_manifest_anchor(out, rows)
    # 包内字节自检(锚→manifest→逐行)
    vr = run_verifier(payload / "tools" / "r17_verify_delivery.py",
                      payload, out / "manifest.jsonl",
                      out / "anchor.json", receipts / "build_verify")
    report["steps"].append({"step": "build_verify",
                            "rc": vr.returncode,
                            "stdout_tail": vr.stdout.strip()[-400:]})
    if vr.returncode != 0:
        print("FATAL 构建包字节自检失败", file=sys.stderr)

    # 语义正例:新 reader 对 repo 原件(=包内字节)
    reader = repo / "stage2_6_1" / "runner" / "r17_c3_engineering_slice.py"
    sem = run_reader(
        reader,
        repo / "stage2_6_1/artifacts/repair17/development/"
        "c3_evidence_generation_slice/engineering_slice",
        repo / "stage2_6_1/artifacts/repair17/development/"
        "blocker_diagnosis/runs/20260906T134324Z_1475/"
        "generation_failure_envelopes_calibrate_c3_cost_D0_p52.json",
        receipts / "semantic_health.json")
    sem_doc = {}
    try:
        sem_doc = json.loads(receipts.joinpath(
            "semantic_health.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        pass
    report["steps"].append({
        "step": "semantic_health", "rc": sem.returncode,
        "verdict": sem_doc.get("readback_verdict"),
        "reader_sha256": sem_doc.get("reader_sha256"),
        "n_problems": sem_doc.get("n_problems")})
    if sem.returncode != 0 or sem_doc.get("readback_verdict") != "PASS":
        print("FATAL 语义正例未过", file=sys.stderr)

    def run_fixture(name: str, tamper) -> dict:
        """整包复制→tamper(mutate pkg)→verifier+reader;自洽修改后
        字节层必须过,拒绝只能来自语义层。"""
        fixture = out.parent / f"tmp_fixture_{name}"
        if fixture.exists():
            shutil.rmtree(fixture)
        fixture.mkdir(parents=True)
        shutil.copytree(payload, fixture / "payload")
        tamper(fixture, rows)
        fv = run_verifier(fixture / "payload" / "tools"
                          / "r17_verify_delivery.py",
                          fixture / "payload", fixture / "manifest.jsonl",
                          fixture / "anchor.json",
                          receipts / f"fixture_verify_{name}")
        fr = run_reader(reader, fixture / "payload" / "engineering_slice",
                        fixture / "payload" / "p52_envelope/"
                        "generation_failure_envelopes_calibrate_c3_cost_"
                        "D0_p52.json",
                        receipts / f"fixture_{name}_reader.json")
        fdoc = {}
        try:
            fdoc = json.loads(receipts.joinpath(
                f"fixture_{name}_reader.json").read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
        checks = {p.get("check") for p in fdoc.get("problems", [])}
        return {"verifier_rc": fv.returncode, "reader_rc": fr.returncode,
                "expected": {"verifier_rc": 0, "reader_rc": 1},
                "reader_problem_checks": sorted(checks)}

    def tamper_i02(fixture: Path, rows: list[dict]) -> None:
        """I02:三下游自洽错配(selected envelope 不动)——字节层
        自洽,reader 必须以四处闭合拒绝。"""
        new_h = {s: "ce-" + hashlib.sha256(
            f"i02-{s}".encode()).hexdigest() for s in ("A", "B")}
        dpath = (fixture / "payload" / "engineering_slice" / "pairs"
                 / "D0_p0.json")
        doc = json.loads(dpath.read_text(encoding="utf-8"))
        doc["episode_hashes"] = dict(new_h)
        doc["pair_record"]["attempt_log"]["output_episode_hashes"] = dict(
            new_h)
        for ep in doc["evaluation"]["episodes"]:
            ep["episode_hash"] = new_h[ep["side"]]
        dpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        resync_manifest(fixture, rows,
                        {"slice_pair_D0_p0": dpath})

    def tamper_k01(fixture: Path, rows: list[dict]) -> None:
        """K01:A 侧删 alpha_bps,权威合同重算 digest,索引/manifest/
        anchor 重锚——内部与外层摘要均成立,拒绝只能来自必要键缺失。"""
        dpath = (fixture / "payload" / "engineering_slice" / "pairs"
                 / "D0_p0.json")
        doc = json.loads(dpath.read_text(encoding="utf-8"))
        env0 = doc["attempt_envelopes"][0]
        sys.path.insert(0, str(authority_src))
        try:
            from rl_curriculum.curriculum261_generation_envelope import (
                _digest_body, stable_digest)
        finally:
            sys.path.remove(str(authority_src))
        env0["base_params"]["A"].pop("alpha_bps")
        env0["digest"] = stable_digest(_digest_body(env0), "r11env-")
        dpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        resync_manifest(fixture, rows,
                        {"slice_pair_D0_p0": dpath})

    def resync_manifest(fixture: Path, rows: list[dict],
                        role_paths: dict) -> None:
        """篡改后的索引/manifest/anchor 重锚(字节层自洽)。"""
        idx = (fixture / "payload" / "engineering_slice"
               / "slice_results.jsonl")
        lines = [json.loads(l) for l in idx.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in lines:
            for role, dpath in role_paths.items():
                coord = role.replace("slice_pair_", "").replace("_p", "/p")
                if row.get("coord") == coord:
                    row["detail_sha256"] = sha256_file(dpath)
        idx.write_text(
            "\n".join(json.dumps(r, ensure_ascii=False)
                      for r in lines) + "\n", encoding="utf-8")
        frows = [dict(r) for r in rows]
        for r in frows:
            if r["role"] in role_paths:
                dpath = role_paths[r["role"]]
                r["sha256"] = sha256_file(dpath)
                r["bytes"] = dpath.stat().st_size
            elif r["role"] == "slice_index":
                r["sha256"] = sha256_file(idx)
                r["bytes"] = idx.stat().st_size
        write_manifest_anchor(fixture, frows)

    st_i02 = run_fixture("i02", tamper_i02)
    st_i02["expected_check"] = "selected_envelope_output_binding"
    st_i02["ok"] = (st_i02["verifier_rc"] == 0
                    and st_i02["reader_rc"] == 1
                    and "selected_envelope_output_binding"
                    in st_i02["reader_problem_checks"])
    report["steps"].append({"step": "fixture_i02_self_consistent",
                            **st_i02})
    st_k01 = run_fixture("k01", tamper_k01)
    st_k01["expected_check"] = "envelope_base_params_required_keys"
    st_k01["ok"] = (st_k01["verifier_rc"] == 0
                    and st_k01["reader_rc"] == 1
                    and "envelope_base_params_required_keys"
                    in st_k01["reader_problem_checks"])
    report["steps"].append({"step": "fixture_k01_required_key_missing",
                            **st_k01})

    # v5 夹具:跨目录悬空末端链接 / 临时名碰撞所有权
    st_pe01 = fixture_pe01(reader, payload, receipts)
    st_pe01["ok"] = (st_pe01["reader_rc"] == 2
                     and not st_pe01["missing_target_created"]
                     and st_pe01["link_entry_intact"]
                     and st_pe01["stderr_has_original_entry"])
    report["steps"].append(st_pe01)
    st_to01 = fixture_to01(reader)
    st_to01["ok"] = (st_to01["error"] == "ReceiptWriteError"
                     and st_to01["foreign_bytes_unchanged"]
                     and st_to01["foreign_identity_unchanged"]
                     and not st_to01["final_target_created"])
    report["steps"].append(st_to01)

    ok = (vr.returncode == 0 and sem.returncode == 0
          and st_i02["ok"] and st_k01["ok"]
          and st_pe01["ok"] and st_to01["ok"])
    report["build_ok"] = bool(ok)
    (out.parent / "build_report_v5.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"build_ok": ok, "run_id": RUN_ID,
                      "n_sources": len(SOURCES)},
                     ensure_ascii=False))
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--repo", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--authority-src", type=Path, default=Path.home()
                   / "projects" / "crypto_rl" / "src",
                   help="生产权威模块完整 src(部署树;发布树 src 是子集)")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        return cmd_build(Path(args.repo), Path(args.out),
                         Path(args.authority_src))
    return 2


if __name__ == "__main__":
    sys.exit(main())
