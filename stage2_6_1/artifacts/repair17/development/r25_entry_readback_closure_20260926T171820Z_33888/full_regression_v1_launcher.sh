set -e
export R17_PROJECT_ROOT=$HOME/projects/crypto_rl
bash $HOME/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh engineering --max-seconds 3600 -- \
  /home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r21_full_collection_regression.py \
  --repo /mnt/f/trading/freqai-rl-audit \
  --commit-a 48939c0ab73b160464f677f826fbfb2a6cc2ac98 \
  --deploy-root /home/cryptorl/projects/crypto_rl \
  --out-dir /mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/r25_entry_readback_closure_20260926T171820Z_33888/full_regression_v1
