#!/usr/bin/env bash
set -u
D=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
echo "== deploy tree file identity =="
sha256sum "$D/src/rl_curriculum/curriculum261_r17_cue_contract.py" 2>&1
sha256sum "$D/src/tests/route_c_stage2_6_1/test_curriculum261_qprod_r9_fixes.py" 2>&1
echo "== expected =="
echo "6b9360965c175e299fa16ac83f076020c0fc894f4180ccc16f737c711d91eb10  cue_contract (C19 8c99d7d3)"
echo "c19aee25da0c071da2a339ee3cfeb3c08f5fd7944b4826989046592c604a43d0  r9 test"
echo "== deploy python =="
"$PY" -c "import sys; print(sys.version)"
