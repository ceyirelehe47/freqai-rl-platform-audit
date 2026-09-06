#!/usr/bin/env bash
# WP0a 只读收集 2:ART 顶层文件+state 细节+obs。仅读取。
set -uo pipefail
A=/home/cryptorl/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair17
for f in r17_bootstrap_accepted.json r17_chain_result.json r17_fail_closure_summary.json fail_path_cleanliness.json r17_formal_log_manifest.jsonl state/r17_iteration_aborted.json state/pending_abort_requests/abort_request_18394_1788710448121.json state/rejected_requests/1788710473510_19630_123911a4.json state/rejected_requests/1788710507087_20874_9277e126.json; do
  echo "=== FILE $f ==="
  cat "$A/$f" 2>&1
  echo
done
echo "=== PLAN head(前 40 行) ==="
head -40 "$A/r17_workflow_plan_formal.json"
echo
echo "=== LOCK ==="
cat "$A/state/r17_chain_session.lock" 2>&1
echo
echo "=== OBS dirs ==="
for d in /home/cryptorl/projects/crypto_rl/r17_formal_requests/*/obs; do
  echo "--- $d"; ls -la "$d" 2>&1
done
