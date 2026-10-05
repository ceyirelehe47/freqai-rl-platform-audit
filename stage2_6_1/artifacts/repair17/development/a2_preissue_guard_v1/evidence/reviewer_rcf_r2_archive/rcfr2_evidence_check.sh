#!/bin/bash
set -u
echo "=== probe evidence files ==="
ls -la /mnt/f/trading/local/rcf_r2_review/ | grep -v "^d" | awk '{print $5, $9}'
echo "=== result jsons ==="
for f in p1_results p1b_results p2_results p4_results; do
  printf '%s: %s\n' "$f" "$(/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -c "import json;d=json.load(open('/mnt/f/trading/local/rcf_r2_review/$f.json'));print(len(d),'scenarios,', sum(1 for x in d if not x['ok']), 'failed')" 2>/dev/null || echo MISSING)"
done
echo "=== a6 corrupted report sample ==="
ls -la /mnt/f/trading/local/rcf_r2_review/p1_work/a6/diag.json /mnt/f/trading/local/rcf_r2_review/p1_work/a6p/diag_parent.json 2>/dev/null
echo "=== work tree protected-dir test side effects (author suite ran) ==="
ls /home/cryptorl/projects/crypto_rl_qaf_v2/artifacts/route_c_stage2_6_1_repair17/ 2>/dev/null | head -20
echo "=== real deploy tree untouched? (mtimes) ==="
ls -la /home/cryptorl/projects/crypto_rl/ | head -3
stat -c '%y %n' /home/cryptorl/projects/crypto_rl/.r17_formal_admission.json /home/cryptorl/projects/crypto_rl/r17_admission_issued.jsonl 2>/dev/null
echo "=== work tree one-shot markers (must be absent) ==="
ls /home/cryptorl/projects/crypto_rl_qaf_v2/.r17_formal_admission.json /home/cryptorl/projects/crypto_rl_qaf_v2/r17_admission_issued.jsonl 2>/dev/null || echo "absent (ok)"
