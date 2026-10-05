#!/bin/bash
# RCF R2: run author's claimed-green suites on the deployed candidate tree
set -u
cd /home/cryptorl/projects/crypto_rl_qaf_v2
export PYTHONDONTWRITEBYTECODE=1
PYBIN=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
echo "=== closure suite (26) ==="
$PYBIN -m pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py -q --timeout=900 -p no:cacheprovider 2>&1 | tail -25
echo "=== guard+launch suites ==="
$PYBIN -m pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_preissue_guard.py tests/route_c_stage2_6_1/test_curriculum261_qprod_formal_launch.py -q --timeout=900 -p no:cacheprovider 2>&1 | tail -15
