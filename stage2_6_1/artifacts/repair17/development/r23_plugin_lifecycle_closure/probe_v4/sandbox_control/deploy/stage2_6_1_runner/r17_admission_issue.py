#!/usr/bin/env python3
"""R17 formal admission issuance end (generation side of the WP0c gate).

The consumption side (curriculum261_r17_admission.py) was shipped by the
supervision-closure round with the generation side deliberately left to a
future independent authorization process. The Route C full-roadmap Goal
(Section 0/G4) is that authorization: one formal offline qualification run
for a new iteration, preregistered through the existing governance
mechanisms. This tool implements the issuance contract:

  - Commit A must exist as a real commit in the release repository (never
    a WIP SHA, all-zero or all-one SHAs are refused);
  - the deployed state root must have the frozen admission shape;
  - a preregistration record must bind the one-shot admission_id, the
    iteration/plan identity and the authorization source BEFORE issuance;
  - an admission_id may be issued exactly once per state root (create-only
    issuance log, mirroring the one-time consumption semantics);
  - the admission file is written create-only; re-issuance over an
    existing file is refused.

Placing the file CONSUMES the one-shot formal authorization for the bound
Commit A. This tool never launches the chain, never touches the execgov
journal, and never modifies frozen science.
"""
from __future__ import annotations

import argparse
import os
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ISSUANCE_LOG = "r17_admission_issued.jsonl"
ADMISSION_FORMAT = "cur261-r17-formal-admission-v2"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REFUSED = ("0" * 40, "1" * 40)
_SUBSTANCE_MODULE = (
    "rl_curriculum.curriculum261_r17_admission_substance")


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, timeout=120)


def issue(repo: Path, deploy_root: Path, state_root: Path,
          commit_a: str, preregistration: dict) -> dict:
    if _SHA_RE.match(commit_a) is None or commit_a in _REFUSED:
        raise SystemExit("refused: commit_a_sha is not a real commit id")
    proc = _git(repo, "cat-file", "-e", commit_a + "^{commit}")
    if proc.returncode != 0:
        raise SystemExit("refused: commit does not exist in release repo")
    parents = _git(repo, "rev-parse", commit_a + "^")
    if parents.returncode != 0:
        raise SystemExit("refused: commit has no parent (not a candidate)")
    tails = (
        ("artifacts", "route_c_stage2_6_1_repair17", "state"),
        ("artifacts", "route_c_stage2_6_1_repair18", "state"),
        ("artifacts", "route_c_stage2_6_1_repair19", "state"),
    )
    if tuple(state_root.parts[-3:]) not in tails \
            or state_root.parent.parent.parent != deploy_root:
        raise SystemExit("refused: deployed state root shape unbound")
    required = {"admission_id", "iteration", "plan_digest",
                "authorization", "regression_evidence",
                "plan_digest_method"}
    if not isinstance(preregistration, dict) \
            or not required <= set(preregistration):
        raise SystemExit("refused: preregistration missing " + str(
            required - set(preregistration or {})))
    admission_id = preregistration["admission_id"]
    if not isinstance(admission_id, str) or not (1 <= len(admission_id) <= 128):
        raise SystemExit("refused: admission_id invalid")
    log_path = Path(deploy_root) / ISSUANCE_LOG
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
            except ValueError:
                raise SystemExit("refused: issuance log unreadable")
            if rec.get("admission_id") == admission_id:
                raise SystemExit("refused: admission_id already issued")
    target = Path(deploy_root) / ".r17_formal_admission.json"
    if target.exists():
        raise SystemExit("refused: admission file already present")
    # §4.2 实质绑定(v2):plan digest 实算(Commit A tree digest 重算
    # 比对 preregistration 声明)+ 候选回归证据核验(机读 record,
    # junit 原件重解析计数、0 failures/0 errors、skip 恰为历史允许
    # 表、差分协议 parent/边界)。验证实现唯一存在于发布仓 src 包
    # (签发与消费同源);本签发器保持 stdlib,经子进程调用并要求
    # rc=0。写 digest 字段不构成验证——这里是重算。
    src_root = Path(repo) / "stage2_6_1" / "src"
    if not (src_root / "rl_curriculum" / (
            _SUBSTANCE_MODULE.split(".")[-1] + ".py")).is_file():
        raise SystemExit(
            "refused: admission substance module missing in release repo")
    import tempfile

    with tempfile.NamedTemporaryFile(
            "w", suffix=".json", delete=False,
            encoding="utf-8") as tmp:
        json.dump(preregistration, tmp, ensure_ascii=False,
                  sort_keys=True)
        prereg_tmp = tmp.name
    try:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(src_root) + (
            os.pathsep + env["PYTHONPATH"]
            if env.get("PYTHONPATH") else "")
        proc = subprocess.run(
            [sys.executable, "-m", _SUBSTANCE_MODULE, "verify",
             "--repo", str(repo), "--commit-a", commit_a,
             "--preregistration", prereg_tmp,
             "--deploy-root", str(deploy_root)],
            capture_output=True, text=True, timeout=600, env=env)
    finally:
        os.unlink(prereg_tmp)
    if proc.returncode != 0:
        raise SystemExit(
            "refused: admission substance verification failed: "
            + (proc.stdout or proc.stderr).strip()[:300])
    try:
        verified = json.loads(proc.stdout)
        substance = verified["substance"]
        substance_digest = verified["substance_digest"]
    except (ValueError, KeyError) as exc:
        raise SystemExit(
            "refused: substance verifier output unreadable") from exc
    # v4(2026-09-25/R22):新签发必须绑定有效收集环境受控面证据
    # (运行期审计/最小环境/执行面身份);v3 历史 record 不可用于
    # 新签发(核验器仍接受其历史核验面,父链递归用)。
    # v5(2026-09-25/R23):插件生命周期覆盖——审计器注册通知 +
    # append-only 生命周期流水,临时注册/影响收集/注销不能再以
    # 末尾干净快照获得准入。v4 及更早 record 不可用于新签发。
    evidence_path = Path(preregistration["regression_evidence"])
    try:
        record_doc = json.loads(
            evidence_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SystemExit(
            "refused: regression evidence unreadable") from exc
    if record_doc.get("format") != (
            "cur261-r17-candidate-regression-evidence-v5"):
        raise SystemExit(
            "refused: new issuance requires evidence format v5 "
            "(plugin lifecycle coverage)")
    admission = {
        "format": ADMISSION_FORMAT,
        "commit_a_sha": commit_a,
        "deployed_state_root": str(state_root),
        "admission_id": admission_id,
        "iteration": preregistration["iteration"],
        "plan_digest": preregistration["plan_digest"],
        "authorization": preregistration["authorization"],
        "substance": substance,
        "substance_digest": substance_digest,
        "issued_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    payload = json.dumps(admission, ensure_ascii=False,
                         sort_keys=True, indent=1) + "\n"
    with open(target, "x", encoding="utf-8") as fh:
        fh.write(payload)
        fh.flush()
    with open(log_path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps({
            "admission_id": admission_id,
            "commit_a_sha": commit_a,
            "issued_utc": admission["issued_utc"],
            "substance_digest": substance_digest,
            "preregistration_sha256": hashlib.sha256(
                json.dumps(preregistration, sort_keys=True,
                           ensure_ascii=False).encode("utf-8")
            ).hexdigest()}, ensure_ascii=False) + "\n")
        fh.flush()
    return admission


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--repo", type=Path, required=True)
    ap.add_argument("--deploy-root", type=Path, required=True)
    ap.add_argument("--state-root", type=Path, required=True)
    ap.add_argument("--commit-a", required=True)
    ap.add_argument("--preregistration", type=Path, required=True)
    args = ap.parse_args()
    prereg = json.loads(
        args.preregistration.read_text(encoding="utf-8"))
    admission = issue(args.repo, args.deploy_root, args.state_root,
                      args.commit_a, prereg)
    print(json.dumps(admission, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
