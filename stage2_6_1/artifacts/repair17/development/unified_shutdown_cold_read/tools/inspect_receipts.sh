#!/usr/bin/env bash
R=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/receipts/r17u_supplement_final_140907
echo "== receipts dir =="
ls "$R"
echo "== inner =="
cat "$R"/inner_*.json 2>/dev/null
echo
echo "== cold_read json =="
cat "$R"/cold_read_*.json 2>/dev/null
echo
echo "== negative =="
cat "$R"/negative_*.json 2>/dev/null
