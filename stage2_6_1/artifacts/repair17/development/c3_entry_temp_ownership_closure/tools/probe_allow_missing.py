#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开工能力实测:Python 3.11.16 os.path.ALLOW_MISSING 存在性与行为。

任务书 §4.2 要求:开工在实际 Conda 解释器确认能力存在和行为,
不因旧印象认定 Python 3.11 没有它。探测项(全部在 /tmp 可写副本):
  1. hasattr(os.path, "ALLOW_MISSING") 与取值;
  2. strict=False / strict=True / ALLOW_MISSING 三模式对"纯缺失后缀";
  3. 非目录祖先(f/new.json)在 ALLOW_MISSING 下是否抛 NotADirectoryError;
  4. file/../new.json 折叠形态在 ALLOW_MISSING 下的行为;
  5. 循环链接在 ALLOW_MISSING 下的行为;
  6. 权限不可访问祖先(EACCES,非 root)在 ALLOW_MISSING 下的行为;
  7. 跨目录悬空末端链接 realpath 三模式行为(区分末端条目 vs 解析错误)。
"""
from __future__ import annotations

import json
import os
import os.path
import shutil
import sys
import tempfile

out: dict = {"python": sys.version.split()[0],
             "platform": sys.platform, "uid": os.getuid(),
             "has_ALLOW_MISSING": hasattr(os.path, "ALLOW_MISSING")}
if out["has_ALLOW_MISSING"]:
    out["ALLOW_MISSING_value"] = repr(os.path.ALLOW_MISSING)

base = tempfile.mkdtemp(prefix="am_probe_")
try:
    os.makedirs(os.path.join(base, "d"))
    with open(os.path.join(base, "f"), "w", encoding="utf-8") as fh:
        fh.write("x")

    def probe(label: str, path: str, strict) -> None:
        try:
            r = os.path.realpath(path, strict=strict)
            out[label] = {"result": r}
        except OSError as exc:
            out[label] = {"raised": type(exc).__name__,
                          "errno": exc.errno, "msg": str(exc)}

    # 纯缺失后缀(目录 d 存在,后续缺失)
    probe("missing_strict_false", os.path.join(base, "d/m1/m2.json"), False)
    probe("missing_strict_true", os.path.join(base, "d/m1/m2.json"), True)
    if out["has_ALLOW_MISSING"]:
        am = os.path.ALLOW_MISSING
        probe("missing_ALLOW_MISSING",
              os.path.join(base, "d/m1/m2.json"), am)
        # 非目录祖先
        probe("notdir_file_new", os.path.join(base, "f/new.json"), am)
        # file/../new.json: 词法上折叠成 base/new.json,但 f 是普通文件
        probe("notdir_file_dotdot_new", os.path.join(base, "f/../n.json"), am)
        # 循环链接
        lp = os.path.join(base, "loop")
        os.symlink(lp, lp)
        probe("loop_ALLOW_MISSING", lp, am)
        # 权限不可访问祖先(仅非 root 有效)
        if os.getuid() != 0:
            lock = os.path.join(base, "lockd")
            os.makedirs(lock)
            inner = os.path.join(lock, "x.json")
            with open(inner, "w", encoding="utf-8") as fh:
                fh.write("x")
            os.chmod(lock, 0o000)
            try:
                probe("eacces_ancestor", inner, am)
            finally:
                os.chmod(lock, 0o755)
        else:
            out["eacces_ancestor"] = {"skipped": "root 下 chmod 000 不生效"}
        # 跨目录悬空末端链接:receipts/result.json -> ../elsewhere/missing.json
        receipts = os.path.join(base, "receipts")
        os.makedirs(receipts)
        os.makedirs(os.path.join(base, "elsewhere"))
        dangling = os.path.join(receipts, "result.json")
        os.symlink("../elsewhere/missing.json", dangling)
        probe("dangling_end_ALLOW_MISSING", dangling, am)
        probe("dangling_end_strict_false", dangling, False)
        # 对照:目标存在且为普通文件
        with open(os.path.join(base, "elsewhere", "present.json"), "w",
                  encoding="utf-8") as fh:
            fh.write("x")
        ok_link = os.path.join(receipts, "ok.json")
        os.symlink("../elsewhere/present.json", ok_link)
        probe("live_end_ALLOW_MISSING", ok_link, am)
finally:
    shutil.rmtree(base, ignore_errors=True)

print(json.dumps(out, ensure_ascii=False, indent=1))
