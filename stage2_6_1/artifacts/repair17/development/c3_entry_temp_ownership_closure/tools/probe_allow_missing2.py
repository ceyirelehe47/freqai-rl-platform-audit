#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开工能力实测第二轮:链接变体组合 + realpath 实现源码确认。

在 probe_allow_missing.py 基础上补充:
  1. link_to_file/new.json 与 link_to_file/../new.json(链接指向普通文件);
  2. link_to_dir/missing/new.json(链接指向目录下缺失——正常场景);
  3. 悬空祖先链接下 new.json 与 ../new.json;
  4. realpath(strict=True) 对 f/../n.json 的行为;
  5. 末端为 .. (d/.. basename)与末端斜杠(d/)行为;
  6. inspect 读取本解释器 posixpath.realpath 源码(确认 .. 语义与
     ALLOW_MISSING 错误传播)。
"""
from __future__ import annotations

import inspect
import json
import os
import os.path
import shutil
import sys
import tempfile

out: dict = {"python": sys.version.split()[0]}
am = os.path.ALLOW_MISSING

base = tempfile.mkdtemp(prefix="am_probe2_")
try:
    os.makedirs(os.path.join(base, "d"))
    with open(os.path.join(base, "f"), "w", encoding="utf-8") as fh:
        fh.write("x")
    os.symlink(base + "/f", base + "/lf")           # 链接→普通文件
    os.symlink(base + "/d", base + "/ld")           # 链接→目录
    os.symlink(base + "/nope", base + "/dang")      # 悬空祖先链接

    def probe(label: str, path: str, strict) -> None:
        try:
            r = os.path.realpath(path, strict=strict)
            out[label] = {"result": r}
        except OSError as exc:
            out[label] = {"raised": type(exc).__name__,
                          "errno": exc.errno}

    probe("lf_new", base + "/lf/new.json", am)
    probe("lf_dotdot_new", base + "/lf/../n2.json", am)
    probe("ld_missing_new", base + "/ld/m1/m2.json", am)
    probe("dang_new", base + "/dang/new.json", am)
    probe("dang_dotdot_new", base + "/dang/../n3.json", am)
    probe("file_dotdot_strict_true", base + "/f/../n.json", True)
    probe("end_dotdot", base + "/d/..", am)
    probe("end_slash", base + "/d/", am)
    probe("double_dotdot_file", base + "/f/../f/x.json", am)
    # realpath(parent) + lexists 原末端条目检查姿势验证
    receipts = os.path.join(base, "receipts")
    os.makedirs(receipts)
    os.makedirs(os.path.join(base, "elsewhere"))
    os.symlink("../elsewhere/missing.json",
               os.path.join(receipts, "result.json"))
    parent_real = os.path.realpath(receipts, strict=am)
    entry = os.path.join(parent_real, "result.json")
    out["orig_entry_check"] = {
        "resolved_parent": parent_real,
        "entry": entry,
        "lexists": os.path.lexists(entry),
        "islink": os.path.islink(entry),
    }
    # 实现源码(截关键片段)
    try:
        src = inspect.getsource(os.path.realpath)
        out["realpath_impl_head"] = src[:1200]
    except OSError:
        out["realpath_impl_head"] = "unavailable"
finally:
    shutil.rmtree(base, ignore_errors=True)

print(json.dumps(out, ensure_ascii=False, indent=1))
