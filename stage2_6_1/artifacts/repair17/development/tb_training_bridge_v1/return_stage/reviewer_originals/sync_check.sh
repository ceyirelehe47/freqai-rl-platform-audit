#!/usr/bin/env bash
set -u
DEPLOY=/home/cryptorl/projects/crypto_rl
REPO=/mnt/f/trading/freqai-rl-audit
norm() { tr -d '\r' < "$1" | sha256sum | cut -d' ' -f1; }
fail=0
check() {
  a=$(norm "$REPO/$1"); b=$(norm "$2")
  if [ "$a" = "$b" ]; then echo "OK   $3"; else echo "DIFF $3 repo=$a deploy=$b"; fail=1; fi
}
S=stage2_6_2/src/rl_curriculum
T=stage2_6_2/tests/route_c_stage2_6_2
for f in ppo262_qualified_input.py ppo262_eng_fixture.py ppo262_eng_profile.py ppo262_env.py ppo262_banks.py ppo262_namespaces.py ppo262_cli.py ppo262_input_lock.py; do
  check "$S/$f" "$DEPLOY/src/rl_curriculum/$f" "src/$f"
done
check "stage2_6_1/src/rl_curriculum/ppo262_input_lock.py" "$DEPLOY/src/rl_curriculum/ppo262_input_lock.py" "mirror-input_lock==deploy"
for f in test_ppo262e_qualified_input.py test_ppo262e_env_bank.py; do
  check "$T/$f" "$DEPLOY/tests/route_c_stage2_6_2/$f" "tests/$f"
done
echo "PY: $(/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -V 2>&1)"
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python -c "import stable_baselines3,torch;print('sb3',stable_baselines3.__version__,'torch',torch.__version__)"
exit $fail
