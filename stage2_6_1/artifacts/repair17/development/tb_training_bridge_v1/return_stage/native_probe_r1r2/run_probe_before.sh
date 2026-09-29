#!/bin/bash
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEPLOY=/home/cryptorl/projects/crypto_rl
OUT=/mnt/f/trading/tmp_probe_native/out_c5_before
rm -rf "$OUT"
# 临时以 C5(7c5fcc4f) 的两文件替换部署树(修复前状态)
cp "$DEPLOY/src/rl_curriculum/ppo262_eng_profile.py" /tmp/c6_eng_profile.bak
cp "$DEPLOY/src/rl_curriculum/ppo262_qualified_input.py" /tmp/c6_qualified_input.bak
trap 'cp /tmp/c6_eng_profile.bak "$DEPLOY/src/rl_curriculum/ppo262_eng_profile.py"; cp /tmp/c6_qualified_input.bak "$DEPLOY/src/rl_curriculum/ppo262_qualified_input.py"' EXIT
git -C "$REPO" show 7c5fcc4f:stage2_6_2/src/rl_curriculum/ppo262_eng_profile.py > "$DEPLOY/src/rl_curriculum/ppo262_eng_profile.py"
git -C "$REPO" show 7c5fcc4f:stage2_6_2/src/rl_curriculum/ppo262_qualified_input.py > "$DEPLOY/src/rl_curriculum/ppo262_qualified_input.py"
cd "$DEPLOY"
source activate-freqtrade.sh >/dev/null 2>&1 || true
/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python \
  /mnt/f/trading/trading/goal_incoming/RouteC_TrainingBridge_FinalReview_2575deb2/probes/reproduce_remaining_native.py \
  --project /home/cryptorl/projects/crypto_rl \
  --repo /mnt/f/trading/freqai-rl-audit \
  --return-root /mnt/f/trading/tmp_probe_native/ret/RouteC_QualifiedInput_TrainingBridge_v1_RETURN \
  --out "$OUT" > /mnt/f/trading/tmp_probe_native/probe_c5_before_stdout.txt 2> /mnt/f/trading/tmp_probe_native/probe_c5_before_stderr.txt
rc=$?
echo "before_probe_rc=$rc(expect 1: gap present)"
python3 - <<'PY'
import json
d=json.load(open('/mnt/f/trading/tmp_probe_native/out_c5_before/RESULT.json'))
for c in d['cases']:
    print(c['name'],'met=',c['expectation_met'],'rejected=',c.get('rejected'),'load=',c.get('model_load_reached'))
print('pass',d['pass'])
PY
# 确认恢复 C6
md5sum "$DEPLOY/src/rl_curriculum/ppo262_eng_profile.py" /tmp/c6_eng_profile.bak | awk '{print $1}' | uniq -c
