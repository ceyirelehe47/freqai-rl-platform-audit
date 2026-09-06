#!/usr/bin/env bash
# WP0a 只读收集脚本(R17 监护接线闭合轮)。仅读取,不写入现场。
set -uo pipefail
P=/home/cryptorl/projects/crypto_rl
for d in "$P"/r17_formal_requests/*/; do
  echo "=== REQ $d ==="
  ls -la --time-style=full-iso "$d"
  echo "--- launch_evidence.jsonl:"
  cat "$d/launch_evidence.jsonl" 2>/dev/null
  echo "--- chain_run.log (tail 20):"
  tail -20 "$d/chain_run.log" 2>/dev/null
  echo "--- fail_closure.log:"
  cat "$d/fail_closure.log" 2>/dev/null
  echo
done
echo "=== STATE TREE ==="
find "$P/artifacts/route_c_stage2_6_1_repair17/state" | sort
echo
echo "=== JOURNAL ==="
cat "$P/artifacts/route_c_stage2_6_1_repair17/state/r17_execution_journal.jsonl" 2>/dev/null
