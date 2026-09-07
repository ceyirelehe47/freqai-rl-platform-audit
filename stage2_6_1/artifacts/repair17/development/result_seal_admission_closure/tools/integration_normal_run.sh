#!/usr/bin/env bash
# 集成验证:真实 supervisor(live 采样)→coordinator→qualify worker
# (normal)→writer seal→run_record/manifest/anchor→verify 冷读
# 一切输出在交付目录 integration/ 下;不触正式面。
set -euo pipefail
SYNC="$HOME/projects/crypto_rl"
SRC="$SYNC/src"
RUNNER_F="/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"
ART="/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/result_seal_admission_closure/integration"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="$ART/runs/normal_${STAMP}"
STATE="$RUN_DIR/state"
OUT="$RUN_DIR/out"
DELIV="$ART/delivery/normal_${STAMP}"
mkdir -p "$RUN_DIR" "$STATE" "$OUT" "$DELIV"
cd "$SYNC"
source activate-freqtrade.sh >/dev/null 2>&1 || true

# ---- 协调者脚本(真实 execute_workflow_chain_r17+normal worker) ----
cat > "$RUN_DIR/cf_runner.py" << 'PYEOF'
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1])
from rl_curriculum.curriculum261_r17_execgov import R17ChainSession
from rl_curriculum.curriculum261_r17_workflow import (
    execute_workflow_chain_r17,
)
import rl_curriculum.curriculum261_r17_workflow as wf

sr = Path(sys.argv[2])
out = Path(sys.argv[3])
wf.R17_WORKFLOW_CLI_MODULE = "r17_control_fixture_worker"
binding = {"mode": "rehearsal", "freeze_sha": "f" * 40,
           "state_root": str(sr), "out_dir": str(out),
           "argv": ["cf-integration"]}
session = R17ChainSession.acquire(binding)
os.environ["R17_CF_BEHAVIOR"] = "normal"
os.environ.setdefault("R17_CF_NAMESPACES", "cf_ns_a")
steps = [
    {"name": "qualify", "cli_command": "cfqualify",
     "argv": ["--behavior", "normal"],
     "requires_artifacts": [], "output_artifacts": []},
    {"name": "fixture_sentinel", "cli_command": "fixture",
     "argv": ["sentinel"], "requires_artifacts": [],
     "output_artifacts": []},
]
plan = {"profile": "rehearsal", "out_dir": str(out),
        "manifest_path": str(out / "manifest.jsonl"),
        "workflow_graph_digest": "cf-integration-digest",
        "qualify_grant_namespaces": ["cf_ns_a"],
        "steps": steps}
result = execute_workflow_chain_r17(
    plan, session=session, log_dir=out / "logs")
print("CFINTEG " + json.dumps(
    {"ok": result["ok"], "failed": result["failed_step"],
     "term": result.get("qualification_terminal_status")}))
if not result["ok"]:
    session.record_iteration_aborted(result["failure_reason"][:2000])
session.release(summary="cf integration normal")
PYEOF

# ---- live supervisor(真实 ps1 win 采样+guest 线程+真实准入) ----
export CURRICULUM261_R17_STATE_ROOT="$STATE"
export PYTHONPATH="$SRC:$SYNC/stage2_6_1_runner"
python3 "$RUNNER_F/r17_supervision.py" \
  --run-dir "$RUN_DIR/run" --task-kind engineering --max-seconds 300 \
  -- python3 "$RUN_DIR/cf_runner.py" "$SRC" "$STATE" "$OUT" \
  > "$RUN_DIR/supervisor_stdout.log" 2> "$RUN_DIR/supervisor_stderr.log"
MONITORED_RC=$?
echo "MONITORED_RC=$MONITORED_RC"
tail -4 "$RUN_DIR/supervisor_stdout.log" || true

# ---- 交付组包(build) ----
RR="$RUN_DIR/run/run_record.json"
python3 "$RUNNER_F/r17_verify_delivery.py" build \
  --run-record "$RR" \
  --manifest-out "$DELIV/manifest.jsonl" \
  --anchor-out "$DELIV/final.anchor.json" \
  --root "$(dirname "$RUN_DIR")" > "$DELIV/build.log" 2>&1
echo "BUILD_RC=$?"

# ---- 冷读验证(独立副本,脱离开发路径) ----
COLD="$ART/cold_read/normal_${STAMP}"
mkdir -p "$COLD"
cp -r "$DELIV/." "$COLD/"
python3 "$RUNNER_F/r17_verify_delivery.py" verify \
  --root "$(dirname "$RUN_DIR")" --manifest "$COLD/manifest.jsonl" \
  --anchor-file "$COLD/final.anchor.json" --run-record "$RR" \
  --receipt-dir "$COLD/verify_receipts" > "$COLD/verify.log" 2>&1
echo "VERIFY_RC=$?"

# ---- 摘要 ----
python3 - "$RUN_DIR" "$STATE" << 'PYEOF'
import json, sys
from pathlib import Path
run, state = Path(sys.argv[1]), Path(sys.argv[2])
s = json.loads((run / "run/summary.json").read_text())
rr = json.loads((run / "run/run_record.json").read_text())
print("biz_rc:", s["business"]["rc"])
print("admission_ok:", (s.get("admission") or {}).get("ok"),
      (s.get("admission") or {}).get("reasons"))
print("evidence_complete:", rr["evidence_complete"])
print("io:", json.dumps({k: v for k, v in (rr.get("io") or {}).items()
                         if k != "failures"}))
print("optional_degraded:",
      (s.get("admission") or {}).get("optional_degraded"))
j = state / "r17_execution_journal.jsonl"
evs = [json.loads(l) for l in j.read_text().splitlines() if l]
seq = [e["event"] for e in evs]
print("journal:", "grant_issued" in seq, seq.count("grant_revoked"),
      [e["event"] for e in evs if e["event"] == "qualification_terminal"])
mf = run / "out/manifest.jsonl"
recs = [json.loads(l) for l in mf.read_text().splitlines() if l]
print("steps:", [(r["step"], r["rc"], r.get("effective_result"))
                 for r in recs])
PYEOF
echo "INTEGRATION_DONE"
