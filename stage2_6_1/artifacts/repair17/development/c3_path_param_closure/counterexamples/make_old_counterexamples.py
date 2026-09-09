#!/usr/bin/env python
"""R17 C3 路径/回执/参数三缺陷旧行为反例(阶段一;修复后同脚本复跑翻转)。

三个反例均只在 /tmp 可写副本上执行,原件只读复制:

- PATH-01: report 传入 ``outside/alias/../recipe.json``(绝对路径)。
  旧 ``_resolve_target_strict`` 先 ``os.path.abspath`` 词法折叠 alias/..,
  准入判定的是外部不存在的 outside/recipe.json;写者继续用原始路径,
  mkdir/open/os.replace 经 OS 真实解析跟随 alias 进入 source ——
  预期旧行为:源内 recipe.json 被回执替换(源污染)。
- PATH-02: report 指向已存在外部历史回执(普通 JSON 文件)。
  旧 ``_atomic_write_receipt`` 最终 ``os.replace(tmp, path)`` 无条件替换
  —— 预期旧行为:历史回执字节/身份被替换。
- PARAM-01: 副本 pairs/D0_p0.json 的 env0.base_params.A 删除 alpha_bps,
  权威 canonical 合同重算该 envelope digest 并同步索引详情 SHA-256,
  selected 输出与三层下游哈希保持不变 —— 预期旧行为:内部摘要与外层
  哈希校验全部成立,参数交集比较跳过缺失键,读回 PASS(缺键漏检)。

每个反例先跑同输入的健康对照(安全外部全新 report 路径),排除环境
因素;全部原始 rc/stdout/stderr/文件前后身份写入输出 JSON 留档。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _fid(p: Path) -> list:
    st = p.stat()
    return [st.st_dev, st.st_ino, st.st_size, st.st_mtime_ns]


def _tree(root: Path) -> dict:
    out = {}
    for p in sorted(root.rglob("*")):
        rel = str(p.relative_to(root))
        if p.is_symlink():
            out[rel] = ["symlink", os.readlink(p)]
        elif p.is_dir():
            out[rel] = ["dir"]
        else:
            out[rel] = ["file", _sha(p), p.stat().st_size]
    return out


def _run_reader(reader: Path, src_dir: Path, case: Path, report: Path,
                p52: Path) -> subprocess.CompletedProcess:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(src_dir)
    return subprocess.run(
        [sys.executable, str(reader), "--readback", str(case),
         "--p52-envelope", str(p52), "--report", str(report)],
        capture_output=True, text=True, timeout=300, env=env,
        cwd=str(src_dir.parent))


def _read_receipt(report: Path) -> dict:
    try:
        return json.loads(report.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 —— 留档原始形态
        return {"_unparsable": f"{type(exc).__name__}: {exc}",
                "_bytes_head": report.read_bytes()[:80].decode(
                    "utf-8", "replace")}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reader", required=True, type=Path)
    ap.add_argument("--orig-slice", required=True, type=Path)
    ap.add_argument("--p52", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    ap.add_argument("--authority-src", type=Path,
                    help="生产权威模块所在 src(重算 envelope digest)")
    args = ap.parse_args()

    reader = args.reader.resolve()
    orig = args.orig_slice.resolve()
    p52 = args.p52.resolve()
    src_dir = reader.parent.parent / "src"
    results = {
        "schema": "r17-c3-path-param-old-counterexamples-v1",
        "reader": str(reader),
        "reader_sha256": _sha(reader),
        "orig_slice": str(orig),
        "p52": str(p52),
        "cases": {},
    }

    # ---------------- 反例 1: symlink+.. 组合,目标为源内 recipe.json
    with tempfile.TemporaryDirectory(prefix="c3pp_ce1_") as td:
        tdp = Path(td)
        case = tdp / "case"
        (case / "outside").mkdir(parents=True)
        shutil.copytree(orig, case / "source")
        os.symlink("../source/child", case / "outside" / "alias")
        (case / "source" / "child").mkdir(exist_ok=True)
        target = case / "source" / "recipe.json"
        before_sha, before_fid = _sha(target), _fid(target)
        before_tree = _tree(case)
        # 显式构造源内 child 以完整复刻任务书 §3.1 目录形态
        r = _run_reader(reader, src_dir, case / "source",
                        case / "outside" / "alias" / ".." / "recipe.json",
                        p52)
        after_sha, after_fid = _sha(target), _fid(target)
        after_tree = _tree(case)
        c1 = {
            "scenario": "PATH-01 symlink+.. report target is in-source "
                        "recipe.json (absolute path, CLI)",
            "report_arg": str(case / "outside" / "alias" / ".."
                              / "recipe.json"),
            "rc": r.returncode,
            "stdout_tail": r.stdout[-400:],
            "stderr_tail": r.stderr[-400:],
            "source_recipe_sha_before": before_sha,
            "source_recipe_sha_after": after_sha,
            "source_recipe_identity_before": before_fid,
            "source_recipe_identity_after": after_fid,
            "tree_changed_paths": sorted(
                set(before_tree) ^ set(after_tree)),
            "tree_changed_files": {
                k: [before_tree.get(k), after_tree.get(k)]
                for k in set(before_tree) | set(after_tree)
                if before_tree.get(k) != after_tree.get(k)},
            "receipt_if_overwritten": (
                _read_receipt(target) if after_sha != before_sha else None),
        }
        c1["old_defect_reproduced"] = bool(
            after_sha != before_sha
            and "readback_verdict" in (
                c1["receipt_if_overwritten"] or {}))
        results["cases"]["path01_symlink_dotdot"] = c1

    # ---------------- 反例 2: 已存在外部历史回执被替换
    with tempfile.TemporaryDirectory(prefix="c3pp_ce2_") as td:
        tdp = Path(td)
        case = tdp / "case" / "slice"
        case.parent.mkdir(parents=True)
        shutil.copytree(orig, case)
        old = tdp / "outside" / "receipt_old.json"
        old.parent.mkdir(parents=True)
        old.write_text(
            '{"format": "historical-receipt", "payload": "DO NOT TOUCH"}',
            encoding="utf-8")
        before = [_sha(old), _fid(old)]
        r = _run_reader(reader, src_dir, case, old, p52)
        after = [_sha(old), _fid(old)]
        c2 = {
            "scenario": "PATH-02 pre-existing external receipt target "
                        "(plain JSON file) replaced by os.replace",
            "rc": r.returncode,
            "stdout_tail": r.stdout[-400:],
            "stderr_tail": r.stderr[-400:],
            "old_sha_before": before[0], "old_sha_after": after[0],
            "old_identity_before": before[1], "old_identity_after": after[1],
            "receipt_now": _read_receipt(old),
        }
        c2["old_defect_reproduced"] = bool(
            before[0] != after[0]
            and "readback_verdict" in c2["receipt_now"])
        results["cases"]["path02_existing_receipt_replaced"] = c2

    # ---------------- 反例 3: A 侧删必要课程键后仍 PASS
    with tempfile.TemporaryDirectory(prefix="c3pp_ce3_") as td:
        tdp = Path(td)
        case = tdp / "case" / "slice"
        outside = tdp / "outside"
        case.parent.mkdir(parents=True)
        outside.mkdir()
        shutil.copytree(orig, case)
        det = case / "pairs" / "D0_p0.json"
        doc = json.loads(det.read_text(encoding="utf-8"))
        env0 = doc["attempt_envelopes"][0]
        env0["base_params"]["A"].pop("alpha_bps")
        if args.authority_src:
            asrc = str(args.authority_src)
        else:
            asrc = str(src_dir)
        sys.path.insert(0, asrc)
        try:
            from rl_curriculum.curriculum261_generation_envelope import (  # noqa: E402
                _digest_body, stable_digest)
            env0["digest"] = stable_digest(_digest_body(env0), "r11env-")
        finally:
            sys.path.remove(asrc)
        det.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        rows_path = case / "slice_results.jsonl"
        rows = [json.loads(l) for l in rows_path.read_text(
            encoding="utf-8").splitlines() if l.strip()]
        for row in rows:
            if row.get("coord") == "D0/p0":
                row["detail_sha256"] = hashlib.sha256(
                    det.read_bytes()).hexdigest()
        rows_path.write_text(
            "\n".join(json.dumps(rw, ensure_ascii=False)
                      for rw in rows) + "\n", encoding="utf-8")
        rep = outside / "receipt.json"
        r = _run_reader(reader, src_dir, case, rep, p52)
        receipt = _read_receipt(rep)
        checks = receipt.get("checks", {})
        prob_checks = sorted({p.get("check")
                              for p in receipt.get("problems", [])})
        c3 = {
            "scenario": "PARAM-01 base_params.A drops alpha_bps "
                        "(envelope digest recomputed by authority; "
                        "index detail_sha256 resynced)",
            "rc": r.returncode,
            "verdict": receipt.get("readback_verdict"),
            "envelope_digest_checks": checks.get("envelope_digest"),
            "problem_checks": prob_checks,
            "stdout_tail": r.stdout[-400:],
        }
        c3["old_defect_reproduced"] = bool(
            r.returncode == 0
            and receipt.get("readback_verdict") == "PASS"
            and not any("base_params" in c or "required" in c
                        for c in prob_checks))
        results["cases"]["param01_missing_required_key_pass"] = c3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    ok = all(c["old_defect_reproduced"]
             for c in results["cases"].values())
    print(f"old_defects_reproduced: {ok}")
    for k, c in results["cases"].items():
        print(f"  {k}: rc={c['rc']} reproduced={c['old_defect_reproduced']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
