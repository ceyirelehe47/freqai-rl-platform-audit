#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组装 RouteC_R25_FinalClosure_TrainingReadiness_v1 RETURN ZIP。

规则(对齐 RUNBOOK §6 与随包 verify_bundle 的安全检查):
- 每成员为普通文件、无重复成员、无路径穿越/绝对路径/反斜杠;
- SHA256SUMS.txt 覆盖除自身外的全部成员(精确一致);
- 上轮原 ZIP 原样嵌套携带(不改一字节);
- 组装后自检:CRC、安全成员、摘要覆盖。
"""
from __future__ import annotations
import hashlib
import json
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path, PurePosixPath

ROUND = Path(__file__).resolve().parent
REPO = ROUND.parents[4]  # .../freqai-rl-audit
ROOT = "RouteC_R25_FinalClosure_TrainingReadiness_v1_RETURN_TO_CHATGPT"
STAGE = ROUND / "return_stage" / ROOT
OUT_ZIP = Path(r"F:\trading\trading\outgoing") / f"{ROOT}.zip"

PREV_ZIP = Path(r"F:\trading\trading\outgoing"
                r"\RouteC_R25_BindingAndDescendantClosure_v1_RETURN_TO_CHATGPT.zip")
PREV_SHA = PREV_ZIP.with_suffix(".zip.sha256.txt")

REG = ROUND / "full_regression_v1"
RUNS = REPO / "stage2_6_1/artifacts/repair17/development/run_supervision/runs"


def copy(rel_src: Path, rel_dst: str) -> None:
    dst = STAGE / rel_dst
    dst.parent.mkdir(parents=True, exist_ok=True)
    if rel_src.is_dir():
        for p in sorted(rel_src.rglob("*")):
            if p.is_file():
                target = dst / p.relative_to(rel_src).as_posix()
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(p, target)
    else:
        shutil.copyfile(rel_src, dst)


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    if STAGE.parent.exists():
        shutil.rmtree(STAGE.parent)
    STAGE.mkdir(parents=True)

    # 1) 轮次文档与记录
    for name in ("SUMMARY.md", "F_FINALCLOSURE_RECORD.md",
                 "protection_before.txt", "protection_after.txt",
                 "candidate_C_push_receipt.txt",
                 "repro_driver_stdout.txt", "repro_driver_stderr.txt"):
        p = ROUND / name
        if p.exists():
            copy(p, name)
    copy(REPO / "stage2_6_1/report"
         "/route_c_stage2_6_1_qualification_to_training_proposal.md",
         "TRAINING_TRANSITION_PROPOSAL.md")

    # 2) 候选代码(与 commit 7e9e5470 相同字节)
    copy(REPO / "stage2_6_1/runner/r25_worker_probe.py",
         "candidate_code/r25_worker_probe.py")
    copy(REPO / "stage2_6_1/tests/route_c_stage2_6_1"
         "/test_curriculum261_r25_probe_registry.py",
         "candidate_code/test_curriculum261_r25_probe_registry.py")

    # 3) 定向测试与旧缺陷复现原件
    copy(ROUND / "old_baseline_characterization",
         "old_baseline_characterization")

    # 4) I01 集成原件
    copy(ROUND / "i01_probe", "i01_probe")
    copy(ROUND / "full_regression_v1_launcher.sh",
         "full_regression_v1_launcher.sh")
    for n in ("full_regression_v1_detached_stdout.log",
              "full_regression_v1_detached_stderr.log"):
        p = ROUND / n
        if p.exists():
            copy(p, n)

    # 5) 全量回归完整目录
    copy(REG, "full_regression_v1")
    copy(ROUND / "full_regression_v1.launcher_rc.txt",
         "full_regression_v1.launcher_rc.txt")

    # 6) 本轮两个监护 run 完整目录
    for run in ("20260928T160626_7004_367", "20260928T160934_4301_1088"):
        copy(RUNS / run, f"run_supervision_runs/{run}")

    # 7) 上轮原 ZIP 原样携带 + 成员定位
    prev_dst = STAGE / "previous_round" / PREV_ZIP.name
    prev_dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PREV_ZIP, prev_dst)
    shutil.copyfile(PREV_SHA,
                    STAGE / "previous_round" / PREV_SHA.name)
    with zipfile.ZipFile(PREV_ZIP) as z:
        names = z.namelist()
    (STAGE / "previous_round" / "previous_zip_members.txt").write_text(
        "\n".join(names) + "\n", encoding="utf-8")

    # 8) SHA256SUMS(精确覆盖除自身外全部成员)
    records = []
    for p in sorted(STAGE.rglob("*")):
        if p.is_file():
            records.append((sha256(p),
                            p.relative_to(STAGE).as_posix()))
    manifest = "".join(f"{d}  {r}\n" for d, r in records)
    (STAGE / "SHA256SUMS.txt").write_text(manifest, encoding="utf-8")

    # 9) 打包(普通 deflate,成员按排序)
    OUT_ZIP.parent.mkdir(parents=True, exist_ok=True)
    if OUT_ZIP.exists():
        OUT_ZIP.unlink()
    with zipfile.ZipFile(OUT_ZIP, "w", zipfile.ZIP_DEFLATED) as z:
        for p in sorted(STAGE.rglob("*")):
            if p.is_file():
                z.write(p, f"{ROOT}/{p.relative_to(STAGE).as_posix()}")

    # 10) 自检(安全成员/重复/CRC/摘要覆盖)
    with zipfile.ZipFile(OUT_ZIP) as z:
        entries = z.infolist()
        names = [i.filename for i in entries]
        assert len(names) == len(set(names)), "duplicate members"
        for e in entries:
            p = PurePosixPath(e.filename)
            assert not p.is_absolute() and "\\" not in e.filename
            assert not any(x in ("", ".", "..")
                           for x in e.filename.split("/"))
            assert p.parts[0] == ROOT
            mode = (e.external_attr >> 16) & 0xFFFF
            assert not e.is_dir() and not stat.S_ISLNK(mode)
            assert stat.S_IFMT(mode) in (0, stat.S_IFREG)
        assert z.testzip() is None, "CRC error"
        man = z.read(f"{ROOT}/SHA256SUMS.txt").decode("utf-8")
        rec = {}
        for line in man.splitlines():
            m = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
            assert m, f"bad row: {line!r}"
            rec[m.group(2)] = m.group(1)
        expected = {n[len(ROOT) + 1:] for n in names
                    if n != f"{ROOT}/SHA256SUMS.txt"}
        assert set(rec) == expected, "manifest coverage mismatch"
        for rel, d in rec.items():
            assert hashlib.sha256(
                z.read(f"{ROOT}/{rel}")).hexdigest() == d, rel
        report = {"zip": str(OUT_ZIP), "members": len(names),
                  "uncompressed": sum(i.file_size for i in entries),
                  "zip_sha256": sha256(OUT_ZIP),
                  "selfcheck": "PASS"}
    print(json.dumps(report, ensure_ascii=False, indent=1))
    (ROUND / "return_selfcheck.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
