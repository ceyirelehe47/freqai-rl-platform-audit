#!/usr/bin/env bash
# D3 反例:同副本 config 上 legacy 单独运行(预期 PASS rc=0)+ wrapper 退出码复核
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
AGG=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure/tools/aggregate_v6.py
python "$AGG" --config /mnt/f/trading/r17_native_smoke_logs/aggregate_config_neg_append.json \
  --out /mnt/f/trading/r17_native_smoke_logs/legacy_standalone_neg_append.json
echo "LEGACY_STANDALONE_RC=$?"
python -c "import json;d=json.load(open('/mnt/f/trading/r17_native_smoke_logs/legacy_standalone_neg_append.json'));print('legacy ok=',d.get('ok'));print('problems:',d.get('problems'))"
python /mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_verified_aggregate.py \
  --root /mnt/f/trading/r17_native_smoke_logs/copy_root \
  --record /mnt/f/trading/r17_native_smoke_logs/copy_root/runs/r17ns_dpos_20260909T170033/run_record.json \
  --legacy-script "$AGG" \
  --config /mnt/f/trading/r17_native_smoke_logs/aggregate_config_neg_append.json \
  --out /mnt/f/trading/r17_native_smoke_logs/verified_aggregate_neg_append2.json
echo "WRAPPER_RC=$?"
