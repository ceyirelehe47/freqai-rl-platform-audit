#!/usr/bin/env bash
# Reviewer independent probe - QProd R5 (C15=1139887e)
set -u
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
REPO=/mnt/f/trading/freqai-rl-audit
OUT=/mnt/f/trading/tmp_r5/reviewer

echo "===== step0: deploy sync identity (repo C15 vs deploy tree) ====="
for f in \
  src/rl_curriculum/curriculum261_r17_cue_contract.py \
  src/rl_curriculum/curriculum261_qprod_levela.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_r5_fixes.py ; do
  a=$(sha256sum "$REPO/stage2_6_1/$f" | cut -d' ' -f1)
  b=$(sha256sum "$DEPLOY/$f" | cut -d' ' -f1)
  if [ "$a" = "$b" ]; then m=YES; else m=NO; fi
  echo "$f"
  echo "  repo_sha=$a"
  echo "  deploy_sha=$b match=$m"
done

echo "===== step1: REPRO probe on C15 bytes (expect 3/3 FAIL) ====="
cd "$DEPLOY"
"$PY" "$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round5_notclosed/REPRO_Q123_ROUND5_PRE_FIX.py" 2>&1
echo "repro_rc=$?"

echo "===== step2: reviewer adversarial variants (probe_r5_adv.py) ====="
cd "$DEPLOY"
"$PY" "$OUT/probe_r5_adv.py" 2>&1
echo "adv_rc=$?"

echo "===== step3: pinned targeted tests ====="
cd "$DEPLOY"
"$PY" -m pytest \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_r5_fixes.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_r4_fixes.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_q123_fixes.py \
  tests/route_c_stage2_6_1/test_curriculum261_qprod_r3_fixes.py \
  tests/route_c_stage2_6_1/test_curriculum261_r9_cue_contract.py \
  tests/route_c_stage2_6_1/test_curriculum261_r9_noise_replay.py \
  tests/route_c_stage2_6_1/test_curriculum261_r10_cue_contract.py \
  -q 2>&1 | tail -12
echo "pytest_rc=${PIPESTATUS[0]}"

echo "===== step4: C14 pre-fix repro (expect 3/3 PASS = holes) ====="
rm -rf "$OUT/c14_snap"; mkdir -p "$OUT/c14_snap"
git -C "$REPO" archive 3d2193e24105647f48419ce401016eb442d2baa1 | tar -x -C "$OUT/c14_snap"
cp "$REPO/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round5_notclosed/REPRO_Q123_ROUND5_PRE_FIX.py" \
   "$OUT/c14_snap/stage2_6_1/"
cd "$OUT/c14_snap/stage2_6_1"
"$PY" REPRO_Q123_ROUND5_PRE_FIX.py 2>&1
echo "c14_repro_rc=$?"
