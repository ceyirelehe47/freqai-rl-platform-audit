#!/bin/bash
# 阶段一:用接手版(0bb0279)部署树 reader 跑三个旧行为反例。
# 修复后同脚本以 --reader 指向新 reader 复跑翻转(fixed_reader_flip.json)。
# 注:本脚本经 `tr -d '\r' | bash`(stdin)执行,$0/BASH_SOURCE 不可用,路径硬编码。
set -u
HERE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_path_param_closure/counterexamples
READER="${1:-$HOME/projects/crypto_rl/stage2_6_1_runner/r17_c3_engineering_slice.py}"
OUT="${2:-$HERE/old_reader_counterexamples.json}"
source "$HOME/projects/crypto_rl/activate-freqtrade.sh" >/dev/null 2>&1
python "$HERE/make_old_counterexamples.py" \
  --reader "$READER" \
  --orig-slice /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_evidence_generation_slice/engineering_slice \
  --p52 /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/blocker_diagnosis/runs/20260906T134324Z_1475/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
  --authority-src "$HOME/projects/crypto_rl/src" \
  --out "$OUT"
rc=$?
echo "CE_RC=$rc"
exit $rc
