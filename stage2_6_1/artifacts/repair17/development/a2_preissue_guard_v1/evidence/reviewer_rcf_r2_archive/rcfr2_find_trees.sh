#!/bin/bash
# find work trees containing the candidate QAFv2 files
set -u
echo "=== all project dirs ==="
ls -d /home/cryptorl/projects/*/ 2>/dev/null
echo
echo "=== trees containing qaf_v2_operator_entry.py ==="
find /home/cryptorl/projects -maxdepth 4 -name qaf_v2_operator_entry.py 2>/dev/null | head -20
echo
echo "=== trees containing qaf guard ==="
find /home/cryptorl/projects -maxdepth 5 -name curriculum261_qaf_provenance_guard.py 2>/dev/null | head -20
echo
echo "=== trees containing reviewclosure test ==="
find /home/cryptorl/projects -maxdepth 6 -name test_curriculum261_qaf_v2_reviewclosure.py 2>/dev/null | head -20
echo
echo "=== also check /mnt f-side staging trees ==="
find /mnt/f/trading -maxdepth 3 -name qaf_v2_operator_entry.py 2>/dev/null | head
find /mnt/f/trading -maxdepth 2 -type d -name "*qaf*" 2>/dev/null | head
