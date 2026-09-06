#!/usr/bin/env bash
# §9 正向回放素材探测(只读)
set -uo pipefail
R=/home/cryptorl/projects/crypto_rl/r17_rt_runs
echo "=== rt_runs 目录:"; ls "$R" 2>/dev/null | head -10
echo "=== 各 run 的 chain_result.ok:"
for f in "$R"/*/artifacts/r17_chain_result.json; do
  [ -f "$f" ] || continue
  ok=$(python3 -c 'import json,sys;print(json.load(open(sys.argv[1])).get("ok"))' "$f" 2>/dev/null)
  echo "$ok $f"
done | head -15
echo "=== run 目录内结构示例(最新):"
latest=$(ls -t "$R" 2>/dev/null | head -1)
[ -n "$latest" ] && find "$R/$latest" -maxdepth 2 | head -15
