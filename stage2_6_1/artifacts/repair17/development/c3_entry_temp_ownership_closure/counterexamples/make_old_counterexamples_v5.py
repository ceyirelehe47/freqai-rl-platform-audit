#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 C3 末端条目/解析错误分类/临时件所有权三缺陷旧行为反例(阶段一)。

对应任务书 PPC-PATH-ENTRY / PPC-PATH-ERROR / PPC-TEMP-OWNER。
全部只在 /tmp 可写副本上执行,业务原件只读复制:

- CE1(PPC-PATH-ENTRY): report 传入 ``receipts/result.json``,其中
  result.json 是指向 ``../elsewhere/missing.json`` 的跨目录悬空链接
  (elsewhere 存在,missing.json 不存在)。旧代码 final_entry 从解析后
  target.parent(=elsewhere)拼回 basename,检查的是
  elsewhere/result.json —— 真正的链接条目 receipts/result.json 未被
  检查;lexists(elsewhere/missing.json)=False 放行,写者跟随末端链接
  落地 —— 预期旧行为:rc=0,elsewhere/missing.json 被创建(写入跟随
  悬空末端链接),链接条目原样但从未被拒绝。
- CE2(PPC-PATH-ERROR): 普通文件祖先两类形态。
  (a) ``f/../new_receipt.json``:realpath(strict=False) 词法折叠 ..,
  目标变成兄弟位置 new_receipt.json —— 预期旧行为:rc=0,折叠后的
  兄弟文件被创建(非目录错误完全丢失);
  (b) ``f/new_receipt.json``:strict=False 容忍非目录,准入放行,
  写者 mkdir(f) 才 FileExistsError —— 预期旧行为:rc=6(错误分类
  错误;应在写前准入拒绝 rc=2)。
- CE3(PPC-TEMP-OWNER): 函数级。固定 datetime 使临时名可预测,在临时
  名位置预置外部普通文件(变体:链接条目),调用 _atomic_write_receipt:
  open(tmp,'x') 独占创建失败后,旧代码 finally 无条件 unlink(tmp)
  —— 预期旧行为:外部对象被删除(创建失败不拥有清理权仍然删除)。

每个反例保留 rc/stdout/stderr/对象前后字节与身份;修复后同脚本对
新版 reader 复跑,三例 reproduced 全部翻转为 false。
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


def _load_reader(reader: Path):
    spec = importlib.util.spec_from_file_location("ce_reader_v5", reader)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reader", required=True, type=Path)
    ap.add_argument("--orig-slice", required=True, type=Path)
    ap.add_argument("--p52", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()

    reader = args.reader.resolve()
    orig = args.orig_slice.resolve()
    p52 = args.p52.resolve()
    src_dir = reader.parent.parent / "src"
    results = {
        "schema": "r17-c3-entry-temp-old-counterexamples-v1",
        "reader": str(reader),
        "reader_sha256": _sha(reader),
        "orig_slice": str(orig),
        "p52": str(p52),
        "cases": {},
    }

    # ---------------- CE1: 跨目录悬空末端链接(目标目录存在/文件缺失)
    with tempfile.TemporaryDirectory(prefix="c3eto_ce1_") as td:
        tdp = Path(td)
        case = tdp / "case"
        (case / "receipts").mkdir(parents=True)
        (case / "elsewhere").mkdir()
        shutil.copytree(orig, case / "source")
        link = case / "receipts" / "result.json"
        os.symlink("../elsewhere/missing.json", link)
        missing = case / "elsewhere" / "missing.json"
        before_tree = _tree(case)
        r = _run_reader(reader, src_dir, case / "source", link, p52)
        after_tree = _tree(case)
        c1 = {
            "scenario": "CE1 cross-dir dangling end link: "
                        "receipts/result.json -> ../elsewhere/missing.json",
            "report_arg": str(link),
            "rc": r.returncode,
            "stdout_tail": r.stdout[-400:],
            "stderr_tail": r.stderr[-400:],
            "missing_target_created": missing.exists(),
            "link_entry_after": (
                ["symlink", os.readlink(link)] if link.is_symlink()
                else (["file", _sha(link), link.stat().st_size]
                      if link.exists() else None)),
            "tree_changed": {k: [before_tree.get(k), after_tree.get(k)]
                             for k in set(before_tree) | set(after_tree)
                             if before_tree.get(k) != after_tree.get(k)},
        }
        # 直接以客观事实判定:悬空链接的目标文件被创建 = 跟随末端链接写入
        c1["old_defect_reproduced"] = bool(missing.exists())
        results["cases"]["ce1_crossdir_dangling_end_link"] = c1

    # ---------------- CE2: 普通文件祖先(折叠与非折叠两形态)
    with tempfile.TemporaryDirectory(prefix="c3eto_ce2_") as td:
        tdp = Path(td)
        case = tdp / "case"
        case.mkdir()
        shutil.copytree(orig, case / "source")
        (case / "f").write_text("ordinary file, not a directory",
                                encoding="utf-8")
        # 变体 a: file/../new_receipt.json —— 词法折叠成兄弟
        rep_a = case / "f" / ".." / "new_receipt_a.json"
        r_a = _run_reader(reader, src_dir, case / "source", rep_a, p52)
        sibling = case / "new_receipt_a.json"
        # 变体 b: file/new_receipt.json —— 非目录直下
        rep_b = case / "f" / "new_receipt_b.json"
        r_b = _run_reader(reader, src_dir, case / "source", rep_b, p52)
        c2 = {
            "scenario": "CE2 ordinary file as path ancestor",
            "variant_a": {
                "report_arg": str(rep_a),
                "rc": r_a.returncode,
                "stderr_tail": r_a.stderr[-300:],
                "sibling_created_after_collapse": sibling.exists(),
            },
            "variant_b": {
                "report_arg": str(rep_b),
                "rc": r_b.returncode,
                "stderr_tail": r_b.stderr[-300:],
                "under_file_created": (case / "f" / "new_receipt_b.json"
                                       ).exists(),
                "file_f_still_file": (case / "f").is_file(),
            },
        }
        c2["old_defect_reproduced"] = bool(
            sibling.exists()          # 折叠后兄弟被写成(核心缺陷)
            or r_b.returncode == 6)   # 非目录应准入拒绝(rc=2)而非写者失败
        results["cases"]["ce2_notdir_ancestor"] = c2

    # ---------------- CE3: 临时名碰撞,创建失败仍删除外部对象
    with tempfile.TemporaryDirectory(prefix="c3eto_ce3_") as td:
        tdp = Path(td)
        mod = _load_reader(reader)

        class _FakeDT:
            @staticmethod
            def now(tz):
                import datetime as _d
                return _d.datetime(2026, 9, 9, 12, 0, 0, 0, tzinfo=tz)

        mod.datetime = _FakeDT
        stamp = _FakeDT.now(
            __import__("datetime").timezone.utc).strftime(
            "%Y%m%dT%H%M%S%f")

        def _tmpname(target: Path) -> Path:
            return target.with_name(
                f".{target.name}.{os.getpid()}.{stamp}.tmp")

        # 变体 a: 预置外部普通文件占住临时名
        outdir = tdp / "out_a"
        outdir.mkdir()
        target = outdir / "result.json"
        foreign = _tmpname(target)
        foreign.write_text("PREEXISTING_FOREIGN_TEMP", encoding="utf-8")
        fb = [_sha(foreign), _fid(foreign)]
        err_a = None
        try:
            mod._atomic_write_receipt(target, {"k": "v"})
        except Exception as exc:  # noqa: BLE001 —— 留档原始异常
            err_a = f"{type(exc).__name__}: {exc}"
        fa = ([_sha(foreign), _fid(foreign)]
              if foreign.exists() else None)
        # 变体 b: 预置链接条目占住临时名(指向外部既有文件)
        outdir_b = tdp / "out_b"
        outdir_b.mkdir()
        target_b = outdir_b / "result.json"
        victim = tdp / "victim_payload.txt"
        victim.write_text("VICTIM CONTENT", encoding="utf-8")
        foreign_link = _tmpname(target_b)
        os.symlink(victim, foreign_link)
        err_b = None
        try:
            mod._atomic_write_receipt(target_b, {"k": "v"})
        except Exception as exc:  # noqa: BLE001
            err_b = f"{type(exc).__name__}: {exc}"
        link_after = (["symlink", os.readlink(foreign_link)]
                      if foreign_link.is_symlink() else None)
        victim_intact = victim.exists() and _sha(victim) == hashlib.sha256(
            b"VICTIM CONTENT").hexdigest()
        c3 = {
            "scenario": "CE3 forced temp-name collision with foreign "
                        "object; cleanup deletes objects the call never "
                        "created",
            "variant_a_plain_file": {
                "tmp_path": str(foreign),
                "error": err_a,
                "foreign_before": fb,
                "foreign_after": fa,
                "foreign_deleted_by_failed_create": fa is None,
                "final_target_created": target.exists(),
            },
            "variant_b_link_entry": {
                "tmp_path": str(foreign_link),
                "error": err_b,
                "link_after": link_after,
                "victim_intact": victim_intact,
                "final_target_created": target_b.exists(),
            },
        }
        c3["old_defect_reproduced"] = bool(
            fa is None or link_after is None)
        results["cases"]["ce3_temp_collision_deletes_foreign"] = c3

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(results, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    ok = all(c["old_defect_reproduced"]
             for c in results["cases"].values())
    print(f"old_defects_reproduced: {ok}")
    for k, c in results["cases"].items():
        print(f"  {k}: reproduced={c['old_defect_reproduced']}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
