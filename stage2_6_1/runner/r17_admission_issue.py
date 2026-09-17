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
import hashlib
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ISSUANCE_LOG = "r17_admission_issued.jsonl"
ADMISSION_FORMAT = "cur261-r17-formal-admission-v1"
_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_REFUSED = ("0" * 40, "1" * 40)


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
    )
    if tuple(state_root.parts[-3:]) not in tails \
            or state_root.parent.parent.parent != deploy_root:
        raise SystemExit("refused: deployed state root shape unbound")
    required = {"admission_id", "iteration", "plan_digest", "authorization"}
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
    admission = {
        "format": ADMISSION_FORMAT,
        "commit_a_sha": commit_a,
        "deployed_state_root": str(state_root),
        "admission_id": admission_id,
        "iteration": preregistration["iteration"],
        "plan_digest": preregistration["plan_digest"],
        "authorization": preregistration["authorization"],
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
