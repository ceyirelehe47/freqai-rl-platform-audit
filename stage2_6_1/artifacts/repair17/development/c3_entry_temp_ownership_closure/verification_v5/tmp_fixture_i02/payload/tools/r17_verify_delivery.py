#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""R17 交付验证器(任务书 WP6;替代 blocker_diagnosis/observers/
cold_read_check.py 的"验证前重建清单"缺陷路径;旧脚本原样保留为
历史证据,不再用于新交付)。

设计合同(实现前审查修正记录 §7-11):
- build 与 verify 彻底分离:build 只由显式组包命令在该批原始流关闭后
  调用一次;必需集合来自 run_record.json(schema=r17-run-record-v1,
  finalized:true),绝不枚举磁盘现存文件重建清单——验证前被删/被改的
  登记文件必须被 verify 检出,这是旧缺陷的精确反例(M19/M20)。
- verify 只读已声明清单 + 外部身份锚点:
  * 锚文件在交付集合之外,含 manifest_sha256 + run_record_sha256
    双锚(两者任一被改动都会撞锚);
  * 可选 git 锚 = 记录在案 commit 的 blob id(git cat-file),绝不锚
    工作树字节摘要——core.autocrlf 与 .gitattributes 未覆盖面
    (*.ps1/artifacts)下工作树与 blob 字节不同,字节摘要必失配;
- 空 stderr/空文件合法(bytes=0 + 空 sha256);缺失/篡改/重复路径/
  路径越界/引用不闭合/夹带/未 external 的外部路径一律非零退出;
- verify 只写独立回执区(--receipt-dir),manifest 与被检文件只读。

用法:
  r17_verify_delivery.py build --run-record <run_record.json> \
      --manifest-out <delivery_manifest_v2.jsonl> \
      --anchor-out <anchor.json>
  r17_verify_delivery.py register-git --anchor <anchor.json> \
      --repo <repo> --commit <sha> --manifest-repo-path <rel>
  r17_verify_delivery.py verify --root <交付根> \
      --manifest <manifest路径> --anchor-file <anchor.json> \
      [--run-record <run_record路径>] [--receipt-dir <dir>] \
      [--anchor-git <commit>:<repo相对manifest路径> --repo <repo>]
退出码:0=PASS;1=内容 FAIL;2=用法/IO 错误。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

MANIFEST_SCHEMA = "r17-delivery-manifest-v2"
ANCHOR_SCHEMA = "r17-delivery-anchor-v1"
RUN_RECORD_SCHEMAS = ("r17-run-record-v1", "r17-run-record-v2")
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def digest_file(p: Path) -> tuple[str, int]:
    """分块 sha256(不整读大文件)。"""
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


def utc_now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class VerifyError(Exception):
    """内容 FAIL(rc=1)。"""


class UsageError(Exception):
    """用法/IO 错误(rc=2)。"""


# ---------------------------------------------------------------- build
def cmd_build(args: argparse.Namespace) -> int:
    run_record_path = Path(args.run_record).resolve()
    manifest_out = Path(args.manifest_out).resolve()
    anchor_out = Path(args.anchor_out).resolve()
    if not run_record_path.is_file():
        raise UsageError(f"run_record 不存在: {run_record_path}")
    try:
        rr = json.loads(run_record_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"run_record 解析失败: {exc}") from exc
    if rr.get("schema") not in RUN_RECORD_SCHEMAS:
        raise UsageError(f"run_record schema 不符: {rr.get('schema')!r}")
    if not rr.get("finalized"):
        raise UsageError("run_record finalized!=true;原始流仍在写入时禁止组包")
    required = rr.get("required")
    if not isinstance(required, list) or not required:
        raise UsageError("run_record.required 缺失或为空")
    # S5(v2):缺件保留为缺件——build 允许组包(清单反映现实),
    # 但 evidence_incomplete 如实透传,verify 据此 FAIL;缺口集合
    # 记入交付锚(B5:清单反映现实,不以跳过/external/optional 恢复
    # 完整)。WP2-B:publish_failed/unreadable 同为非 present 状态,
    # 自动计入缺口(键名沿用 missing_roles,语义=必要角色未有效
    # 交付,不限于"文件不存在")。
    missing_roles = [str(i.get("role"))
                     for i in required if isinstance(i, dict)
                     and str(i.get("status", "present")) != "present"
                     and not i.get("external")]
    root = Path(args.root).resolve() if args.root else run_record_path.parent.parent
    # run_record 内 path 以 run_supervision 根为相对基准(E4 合同)
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in required:
        if not isinstance(item, dict):
            raise VerifyError(f"required 条目非对象: {item!r}")
        role = str(item.get("role", ""))
        rel = str(item.get("path", ""))
        if item.get("external"):
            continue  # 显式 external:不进入交付清单(verify 侧核引用)
        if not role or not rel:
            raise VerifyError(f"required 条目缺 role/path: {item!r}")
        _check_rel(rel)
        if str(item.get("status", "present")) in (
                "missing", "publish_failed", "unreadable"):
            # 运行前登记、结束时缺失/发布失败/不可读:不进清单文件行
            # (无有效文件可锚——publish_failed 的残片/旧件、
            # unreadable 的无哈希文件都不能以"存在字节"冒充有效
            # 角色;WP2-B fail-closed),缺口以 manifest 头行如实
            # 记录(verify FAIL)
            continue
        p = (root / rel).resolve()
        if not p.is_file():
            raise VerifyError(f"必需文件缺失: {rel}")
        sha, n = digest_file(p)
        if "sha256" in item and str(item["sha256"]) != sha:
            raise VerifyError(
                f"哈希不符(文件与 run_record 矛盾): {rel} "
                f"record={item['sha256']} actual={sha}")
        if "bytes" in item and int(item["bytes"]) != n:
            raise VerifyError(
                f"长度不符(文件与 run_record 矛盾): {rel} "
                f"record={item['bytes']} actual={n}")
        if rel in seen:
            raise VerifyError(f"重复路径: {rel}")
        seen.add(rel)
        rows.append({"schema": MANIFEST_SCHEMA, "run_id": rr.get("run_id"),
                     "role": role, "path": rel, "sha256": sha, "bytes": n})
    # run_record 自身作为 role=record 行(其哈希同时入锚,双锚闭环)
    rr_rel = _rel_within(root, run_record_path)
    rr_sha, rr_bytes = digest_file(run_record_path)
    if rr_rel in seen:
        raise VerifyError(f"run_record 路径与 required 冲突: {rr_rel}")
    rows.append({"schema": MANIFEST_SCHEMA, "run_id": rr.get("run_id"),
                 "role": "record", "path": rr_rel,
                 "sha256": rr_sha, "bytes": rr_bytes})
    manifest_out.parent.mkdir(parents=True, exist_ok=True)
    with manifest_out.open("w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False,
                                separators=(",", ":")) + "\n")
    man_sha, man_bytes = digest_file(manifest_out)
    anchor = {
        "schema": ANCHOR_SCHEMA, "run_id": rr.get("run_id"),
        "manifest_path": str(manifest_out), "manifest_sha256": man_sha,
        "manifest_bytes": man_bytes,
        "run_record_path": str(run_record_path),
        "run_record_sha256": rr_sha,
        "root": str(root), "built_utc": utc_now(),
        "git_commit": None, "manifest_blob_id": None,
        # B5:运行前登记但结束时缺失的角色集合(清单反映现实;
        # verify 对 v2 缺件 FAIL evidence_incomplete)
        "missing_roles": missing_roles,
    }
    anchor_out.parent.mkdir(parents=True, exist_ok=True)
    anchor_out.write_text(json.dumps(anchor, ensure_ascii=False, indent=1),
                          encoding="utf-8")
    print(f"build: {len(rows)} 行 -> {manifest_out}")
    print(f"anchor(交付集合外): {anchor_out}")
    return 0


# ----------------------------------------------------------- register-git
def cmd_register_git(args: argparse.Namespace) -> int:
    anchor_path = Path(args.anchor).resolve()
    try:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"锚文件解析失败: {exc}") from exc
    if anchor.get("schema") != ANCHOR_SCHEMA:
        raise UsageError("锚文件 schema 不符")
    repo = Path(args.repo).resolve()
    blob_id = git_output(repo, ["rev-parse",
                                f"{args.commit}:{args.manifest_repo_path}"])
    blob_sha = git_blob_sha(repo, blob_id)
    if blob_sha != anchor["manifest_sha256"]:
        raise VerifyError(
            f"git blob 内容摘要与锚不符: blob={blob_sha} "
            f"anchor={anchor['manifest_sha256']}(manifest 未提交或提交后又被改)")
    anchor["git_commit"] = args.commit
    anchor["manifest_blob_id"] = blob_id
    anchor_path.write_text(json.dumps(anchor, ensure_ascii=False, indent=1),
                           encoding="utf-8")
    print(f"register-git: commit={args.commit} blob={blob_id}")
    return 0


# ---------------------------------------------------------------- verify
def git_output(repo: Path, argv: list[str]) -> str:
    try:
        out = subprocess.run(["git", "-C", str(repo)] + argv,
                             capture_output=True, check=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        raise UsageError(f"git 调用失败: {exc}") from exc
    return out.stdout.decode("utf-8", "replace").strip()


def git_blob_sha(repo: Path, blob_id: str) -> str:
    """blob 内容的 sha256(与文件摘要同口径)。"""
    out = subprocess.run(["git", "-C", str(repo), "cat-file", "blob", blob_id],
                         capture_output=True, check=True, timeout=120)
    return hashlib.sha256(out.stdout).hexdigest()


def _check_rel(rel: str) -> None:
    if not rel or rel.startswith(("/", "\\")) or rel.startswith("~"):
        raise VerifyError(f"非法绝对路径: {rel}")
    parts = Path(rel).parts
    if ".." in parts:
        raise VerifyError(f"路径含 ..: {rel}")
    if Path(rel).drive or Path(rel).root:
        raise VerifyError(f"路径非纯相对: {rel}")


def _rel_within(root: Path, p: Path) -> str:
    try:
        return str(p.relative_to(root)).replace("\\", "/")
    except ValueError as exc:
        raise VerifyError(f"路径越出交付根 {root}: {p}") from exc


def cmd_verify(args: argparse.Namespace) -> int:
    root = Path(args.root).resolve()
    manifest_path = Path(args.manifest).resolve()
    anchor_path = Path(args.anchor_file).resolve()
    problems: list[str] = []
    # 1) 锚(只读)
    try:
        anchor = json.loads(anchor_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UsageError(f"锚文件读取失败: {exc}") from exc
    if anchor.get("schema") != ANCHOR_SCHEMA:
        problems.append(f"锚 schema 不符: {anchor.get('schema')!r}")
    # 2) manifest 自身对照锚(防清单被改;绝不重建)
    if not manifest_path.is_file():
        raise UsageError(f"manifest 缺失: {manifest_path}")
    man_sha, man_bytes = digest_file(manifest_path)
    if man_sha != anchor.get("manifest_sha256"):
        problems.append(
            f"manifest 哈希与锚不符: actual={man_sha} "
            f"anchor={anchor.get('manifest_sha256')}")
    elif man_bytes != anchor.get("manifest_bytes"):
        problems.append("manifest 长度与锚不符")
    # 3) 可选 git blob 锚
    if args.anchor_git:
        commit, _, repo_rel = args.anchor_git.partition(":")
        if not commit or not repo_rel:
            raise UsageError("--anchor-git 需 <commit>:<repo相对路径>")
        repo = Path(args.repo).resolve() if args.repo else None
        if repo is None:
            raise UsageError("--anchor-git 需要 --repo")
        blob_id = git_output(repo, ["rev-parse", f"{commit}:{repo_rel}"])
        blob_sha = git_blob_sha(repo, blob_id)
        if blob_sha != man_sha:
            problems.append(
                f"git blob 内容摘要与工作树 manifest 不符: "
                f"blob={blob_sha} manifest={man_sha}")
        if anchor.get("manifest_blob_id") and \
                anchor["manifest_blob_id"] != blob_id:
            problems.append(
                f"git blob id 与锚不符: blob={blob_id} "
                f"anchor={anchor['manifest_blob_id']}")
    # 4) run_record 对照(锚内含其哈希时必须提供)
    rr: dict[str, Any] | None = None
    if args.run_record:
        rr_path = Path(args.run_record).resolve()
        if not rr_path.is_file():
            raise UsageError(f"run_record 缺失: {rr_path}")
        try:
            rr = json.loads(rr_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise UsageError(f"run_record 解析失败: {exc}") from exc
        if rr.get("schema") not in RUN_RECORD_SCHEMAS:
            problems.append(f"run_record schema 不符: {rr.get('schema')!r}")
        rr_sha, _ = digest_file(rr_path)
        if anchor.get("run_record_sha256") and \
                rr_sha != anchor["run_record_sha256"]:
            problems.append("run_record 哈希与锚不符")
    elif anchor.get("run_record_sha256"):
        problems.append("锚含 run_record_sha256 但未提供 --run-record")
    # 5) 解析 manifest(真实 json.loads;损坏行=FAIL,不宽松跳过)
    rows: list[dict[str, Any]] = []
    with manifest_path.open("r", encoding="utf-8") as fh:
        for ln, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                problems.append(f"manifest 第 {ln} 行 JSON 损坏: {exc}")
                continue
            if row.get("schema") != MANIFEST_SCHEMA:
                problems.append(f"manifest 第 {ln} 行 schema 不符")
                continue
            rows.append(row)
    if not rows:
        problems.append("manifest 为空(空清单不允许)")
    seen: dict[str, int] = {}
    for row in rows:
        rel = str(row.get("path", ""))
        try:
            _check_rel(rel)
        except VerifyError as exc:
            problems.append(str(exc))
            continue
        if rel in seen:
            problems.append(f"重复路径: {rel}")
            continue
        seen[rel] = 1
        p = (root / rel)
        try:
            resolved = p.resolve()
            resolved.relative_to(root)
        except (OSError, ValueError):
            problems.append(f"路径越出交付根: {rel}")
            continue
        if not resolved.is_file():
            problems.append(f"缺失: {rel}")
            continue
        sha, n = digest_file(resolved)
        if n != row.get("bytes"):
            problems.append(
                f"长度不符: {rel} manifest={row.get('bytes')} actual={n}")
        if sha != row.get("sha256"):
            problems.append(f"哈希不符(篡改?): {rel}")
    # 6) 必需集合闭合(防漏报/防夹带)
    if rr is not None:
        manifest_pairs = {(str(r.get("role")), str(r.get("path")))
                          for r in rows}
        for item in rr.get("required", []):
            if not isinstance(item, dict):
                problems.append(f"required 条目非对象: {item!r}")
                continue
            rel = str(item.get("path", ""))
            if item.get("external"):
                # external:允许不进清单,但引用必须显式标记且可解释
                if not item.get("external_reason"):
                    problems.append(
                        f"external 条目缺 external_reason: {rel}")
                continue
            if (str(item.get("role")), rel) not in manifest_pairs:
                problems.append(f"必需文件未入清单: {rel}")
        record_pairs = {(str(r.get("role")), str(r.get("path")))
                        for r in rows
                        if r.get("role") == "record"}
        if len(record_pairs) != 1:
            problems.append(
                f"role=record 行数异常: {len(record_pairs)}(应为 1)")
        # S5(v2):缺件=交付不完整(finalized 可成立,evidence 不完整
        # 必 FAIL;事后补文件也过不了——missing 行不在清单,补了即
        # "必需文件未入清单",删 run_record 行则与锚哈希矛盾)
        # WP2-B(fail-closed):publish_failed(必要发布失败,残片/旧件
        # 不抵消)与 unreadable(存在但不可读,无哈希身份)同样拒绝
        if rr.get("schema") == "r17-run-record-v2":
            for item in rr.get("required", []):
                if isinstance(item, dict) and \
                        str(item.get("status", "present")) == "missing":
                    problems.append(
                        f"evidence_incomplete: 角色 "
                        f"{item.get('role')} 登记后缺失"
                        f"({item.get('path')})")
                if isinstance(item, dict) and str(
                        item.get("status", "present")) == "publish_failed":
                    problems.append(
                        f"evidence_incomplete: 角色 "
                        f"{item.get('role')} 发布失败(必要结果证据"
                        f"无效;残片/存在字节不构成有效已发布角色;"
                        f"{item.get('path')})")
                if isinstance(item, dict) and str(
                        item.get("status", "present")) == "unreadable":
                    problems.append(
                        f"evidence_incomplete: 角色 "
                        f"{item.get('role')} 内容不可读(无哈希身份,"
                        f"不能按有效角色验收;{item.get('path')})")
                if isinstance(item, dict) and item.get("live_writers"):
                    # §5.5:写者未确认关闭的文件不得按完整证据验收
                    problems.append(
                        f"evidence_incomplete: 角色 "
                        f"{item.get('role')} 写者未确认关闭"
                        f"(live_writers;最终哈希不确定)")
            # WP1(fc-integrity):控制失败事实非空=本记录是一次控制
            # 能力失效的终结证据,不是完整运行通过(失败证据完整≠
            # 运行成功;读者不得反向解释)
            if rr.get("control_failures"):
                problems.append(
                    f"control_failure: run_record.control_failures 非空"
                    f"({len(rr['control_failures'])} 条;控制能力失效"
                    f"的失败记录,不得按完整运行交付验收)")
            # WP2 §5.5:验证器消费完成性——文件哈希一致不能覆盖
            # 写入未完成/失败/未关闭(缺 evidence_complete 的旧记录
            # 按 v2 合同应为 true;非 v2 不在此路径)。
            if rr.get("evidence_complete") is not True:
                problems.append(
                    "evidence_incomplete: run_record."
                    "evidence_complete!=true(缺件/写动作失败/"
                    "封口未确认/io 丢关键)")
    # 7) 回执(独立输出区;manifest/原文件只读)
    receipt = {
        "schema": "r17-delivery-verify-receipt-v1",
        "verified_utc": utc_now(), "root": str(root),
        "manifest": str(manifest_path), "anchor": str(anchor_path),
        "manifest_sha256": man_sha,
        "n_rows": len(rows), "n_problems": len(problems),
        "problems": problems, "rc": 1 if problems else 0,
    }
    receipt_dir = Path(args.receipt_dir).resolve() if args.receipt_dir \
        else manifest_path.parent / "verify_receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    rp = receipt_dir / f"verify_{stamp}.json"
    rp.write_text(json.dumps(receipt, ensure_ascii=False, indent=1),
                  encoding="utf-8")
    print(json.dumps({"rc": receipt["rc"], "rows": len(rows),
                      "problems": len(problems),
                      "receipt": str(rp)}, ensure_ascii=False))
    for msg in problems:
        print(f"FAIL: {msg}", file=sys.stderr)
    return 1 if problems else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--run-record", required=True)
    b.add_argument("--manifest-out", required=True)
    b.add_argument("--anchor-out", required=True)
    b.add_argument("--root", default=None,
                   help="required.path 的相对基准(缺省=run_record.parent.parent)")
    b.set_defaults(func=cmd_build)
    g = sub.add_parser("register-git")
    g.add_argument("--anchor", required=True)
    g.add_argument("--repo", required=True)
    g.add_argument("--commit", required=True)
    g.add_argument("--manifest-repo-path", required=True)
    g.set_defaults(func=cmd_register_git)
    v = sub.add_parser("verify")
    v.add_argument("--root", required=True)
    v.add_argument("--manifest", required=True)
    v.add_argument("--anchor-file", required=True)
    v.add_argument("--run-record", default=None)
    v.add_argument("--receipt-dir", default=None)
    v.add_argument("--anchor-git", default=None,
                   help="<commit>:<repo相对manifest路径>")
    v.add_argument("--repo", default=None)
    v.set_defaults(func=cmd_verify)
    args = ap.parse_args()
    try:
        return args.func(args)
    except VerifyError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1
    except UsageError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
