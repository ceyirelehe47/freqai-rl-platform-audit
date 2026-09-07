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
