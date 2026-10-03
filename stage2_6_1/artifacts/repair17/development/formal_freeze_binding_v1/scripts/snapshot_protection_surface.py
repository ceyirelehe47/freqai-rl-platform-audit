#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""RouteC_FormalFreeze_ApprovalBinding_v1 — 生产保护面只读快照。

零写入生产面:只读取在场事实(存在性/摘要/形态),不创建任何
正式配置、许可、状态或 exposure 对象;敏感值不记录(只记键名/
摘要/形态字段)。输出 JSON 到本准备目录 protection_surface/。

用法(WSL 部署树解释器,只读):
  python3 snapshot_protection_surface.py <phase: before|after> <out.json>
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

DEPLOY = Path("/home/cryptorl/projects/crypto_rl")
REPO = Path("/mnt/f/trading/freqai-rl-audit")
PY = "/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python"


def _sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_out(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args],
                         capture_output=True, text=True, timeout=120)
    return out.stdout.strip()


def _dir_manifest(root: Path, limit_notes: bool = True) -> dict:
    if not root.is_dir():
        return {"present": False}
    files = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            rel = str(p.relative_to(root))
            files[rel] = _sha256_file(p)
    return {"present": True, "file_count": len(files),
            "files_sha256": files}


def capture() -> dict:
    snap: dict = {
        "format": "cur261-ffab-protection-surface-snapshot-v1",
        "captured_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ",
                                      time.gmtime()),
        "deploy_root": str(DEPLOY),
        "interpreter": {
            "path": PY,
            "exists": Path(PY).is_file(),
            "version": subprocess.run(
                [PY, "--version"], capture_output=True, text=True
            ).stdout.strip() if Path(PY).is_file() else None,
        },
        "repo": {
            "path": str(REPO),
            "branch": _git_out("rev-parse", "--abbrev-ref", "HEAD"),
            "head": _git_out("rev-parse", "HEAD"),
            "remote_head": _git_out("rev-parse",
                                    "origin/route-c-stage2-6-1-repair17"),
            "status_porcelain_counts": {},
        },
        "deploy_config": {
            "path": str(DEPLOY / "qprod_deploy_config.json"),
            "present": (DEPLOY / "qprod_deploy_config.json").is_file(),
            "note": "受信任部署配置缺失 = 正式面未激活(fail closed;"
                    "不以创建配置获得绿色预检)",
        },
        "formal_root_env_redirects": {
            var: bool(os.environ.get(var)) for var in (
                "CURRICULUM261_QPROD_ART_ROOT",
                "CURRICULUM261_QPROD_STATE_ROOT",
                "CURRICULUM261_R17_DEPLOYED_STATE_ROOT",
                "R17_ART_ROOT", "R17_STATE_ROOT",
                "CURRICULUM261_R17_STATE_ROOT")
        },
        "admission_surface": {},
        "old_formal_state_roots": {},
        "formal_iteration_roots_registered": None,
    }

    # git 未提交面分类(只计数,不触碰;porcelain 可由外部预采集
    # 传入(FFAB_PORCELAIN_FILE),避免在 /mnt 驱动器上慢速重跑)
    pfile = os.environ.get("FFAB_PORCELAIN_FILE")
    if pfile:
        st = [ln.rstrip("\n") for ln in
              Path(pfile).read_text(encoding="utf-8").splitlines()
              if ln.strip()]
    else:
        st = subprocess.run(
            ["git", "-C", str(REPO), "status", "--porcelain"],
            capture_output=True, text=True).stdout.splitlines()
    counts: dict[str, int] = {}
    for line in st:
        code = line[:2].strip() or "??"
        counts[code] = counts.get(code, 0) + 1
    snap["repo"]["status_porcelain_counts"] = counts

    # 准入面(历史一次性授权;只读)
    adm = DEPLOY / ".r17_formal_admission.json"
    entry = {"path": str(adm), "present": adm.is_file()}
    if adm.is_file():
        raw = adm.read_bytes()
        doc = json.loads(raw)
        entry.update({
            "sha256": hashlib.sha256(raw).hexdigest(),
            "bytes": len(raw),
            "format": doc.get("format"),
            "admission_id": doc.get("admission_id"),
            "commit_a_sha": doc.get("commit_a_sha"),
            "iteration": doc.get("iteration"),
            "issued_utc": doc.get("issued_utc"),
            "deployed_state_root": doc.get("deployed_state_root"),
            "note": "历史 R18/R19 一次性准入已在位(2026-09 前消费);"
                    "本任务零触碰零消费;未来 A 链须由未来受信任部署根"
                    "另行签发(现根 admission 文件在场即拒新签发)",
        })
    snap["admission_surface"]["admission_file"] = entry
    log = DEPLOY / "r17_admission_issued.jsonl"
    lg = {"path": str(log), "present": log.is_file()}
    if log.is_file():
        raw = log.read_bytes()
        lines = [json.loads(x) for x in raw.decode("utf-8").splitlines()
                 if x.strip()]
        lg.update({"sha256": hashlib.sha256(raw).hexdigest(),
                   "records": [{"admission_id": r.get("admission_id"),
                                "commit_a_sha": r.get("commit_a_sha"),
                                "issued_utc": r.get("issued_utc")}
                               for r in lines]})
    snap["admission_surface"]["issuance_log"] = lg

    # 旧正式状态根(保护面;逐文件摘要只读)
    for name in ("route_c_stage2_6_1_repair17",
                 "route_c_stage2_6_1_repair18",
                 "route_c_stage2_6_1_repair19"):
        snap["old_formal_state_roots"][name] = _dir_manifest(
            DEPLOY / "artifacts" / name)

    # 正式迭代根登记:唯一合法来源是受信任部署配置;配置缺失即未登记
    snap["formal_iteration_roots_registered"] = (
        "none:qprod_deploy_config.json absent(fail closed)")

    # 业务运行实例/exposure:QProd 正式 journal 只会在正式根内;
    # 正式根不存在 ⇒ 无正式运行实例。记录请求目录在场事实。
    req = DEPLOY / "r17_formal_requests"
    snap["formal_request_dirs"] = (
        sorted(p.name for p in req.iterdir()) if req.is_dir() else [])
    return snap


def main() -> int:
    phase, out_path = sys.argv[1], sys.argv[2]
    snap = capture()
    snap["phase"] = phase
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(snap, ensure_ascii=False, indent=1,
                              sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"snapshot": str(out), "phase": phase,
                      "deploy_config_present":
                          snap["deploy_config"]["present"],
                      "admission_present":
                          snap["admission_surface"]["admission_file"]
                          ["present"]},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
