#!/usr/bin/env bash
set -u
REPO=/mnt/f/trading/freqai-rl-audit
DEPLOY=/home/cryptorl/projects/crypto_rl
C3=611966b28bc0d2baeff396e8f42e91ddb1729e4e
FILES="ppo262_entry_specs.py ppo262_qualified_input.py ppo262_eng_profile.py ppo262_cli.py ppo262_smoke.py ppo262_eng_fixture.py ppo262_namespaces.py ppo262_banks.py ppo262_env.py ppo262_train.py ppo262_diag_train.py ppo262_config.py"
fail=0
for f in $FILES; do
  blob=$(git -C "$REPO" show "$C3:stage2_6_2/src/rl_curriculum/$f" | sha256sum | cut -d' ' -f1)
  dep=$(sha256sum "$DEPLOY/src/rl_curriculum/$f" | cut -d' ' -f1)
  if [ "$blob" = "$dep" ]; then echo "OK   $f"; else echo "MISMATCH $f blob=$blob deploy=$dep"; fail=1; fi
done
for t in test_ppo262e_review_fixes.py test_ppo262e_qualified_input.py test_ppo262e_env_bank.py; do
  t1=$(git -C "$REPO" show "$C3:stage2_6_2/tests/route_c_stage2_6_2/$t" | sha256sum | cut -d' ' -f1)
  t2=$(sha256sum "$DEPLOY/tests/route_c_stage2_6_2/$t" | cut -d' ' -f1)
  if [ "$t1" = "$t2" ]; then echo "OK   $t"; else echo "MISMATCH $t"; fail=1; fi
done
echo "SYNC_FAIL=$fail"
