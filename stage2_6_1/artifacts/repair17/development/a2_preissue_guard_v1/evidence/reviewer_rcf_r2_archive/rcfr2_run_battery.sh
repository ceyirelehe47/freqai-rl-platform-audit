#!/bin/bash
# RCF R2 re-verification battery on candidate d705c494 (crypto_rl_qaf_v2 test tree)
set -u
cd /home/cryptorl/projects/crypto_rl_qaf_v2
export PYTHONDONTWRITEBYTECODE=1
PYBIN=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
R=/mnt/f/trading/local/rcf_r2_review
{
echo "##### P1 $(date -u +%H:%M:%S)"; $PYBIN $R/p1_guard_links.py; echo "P1_RC=$?"
echo "##### P1B"; $PYBIN $R/p1b_cli.py; echo "P1B_RC=$?"
echo "##### P2"; $PYBIN $R/p2_operator.py; echo "P2_RC=$?"
echo "##### P4"; $PYBIN $R/p4_gate.py; echo "P4_RC=$?"
echo "##### closure suite"; $PYBIN -m pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_reviewclosure.py -q --timeout=900 -p no:cacheprovider 2>&1 | tail -4
echo "##### guard+launch suites"; $PYBIN -m pytest tests/route_c_stage2_6_1/test_curriculum261_qaf_v2_preissue_guard.py tests/route_c_stage2_6_1/test_curriculum261_qprod_formal_launch.py -q --timeout=900 -p no:cacheprovider 2>&1 | tail -4
echo "##### DONE $(date -u +%H:%M:%S)"
} 2>&1 | tee $R/reverify_d705c494.log
