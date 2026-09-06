#!/usr/bin/env bash
# C11 调试:复现 pytest 形态(Popen PIPE+terminate),观察卡点
set -uo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1
D=/tmp/c11dbg2
rm -rf $D && mkdir -p $D/fixture_root
cp /tmp/c11dbg/fixture_root/coord_sleep_fixture.py $D/fixture_root/
cp /tmp/c11dbg/coord_runner.py $D/
export PYTHONPATH=/home/cryptorl/projects/crypto_rl/src:$D/fixture_root
export CURRICULUM261_R17_STATE_ROOT=$D/state
python $D/coord_runner.py /home/cryptorl/projects/crypto_rl/src $D/state $D/out c11 coord_sleep_fixture > $D/coord.out 2>&1 &
CPID=$!
J=$D/state/r17_execution_journal.jsonl
for i in $(seq 1 60); do
  [ -f "$J" ] && grep -q chain_step_started "$J" && break
  sleep 0.5
done
echo "=== 发 TERM 前 journal:"; cat "$J" 2>/dev/null | head -5
kill -TERM $CPID
sleep 5
echo "=== TERM 后 5s 进程树( коord 及后代):"
ps -o pid,ppid,pgid,stat,wchan:30,cmd --pid $CPID 2>/dev/null
for c in $(ls /proc/$CPID/task 2>/dev/null >/dev/null && cat /proc/$CPID/task/*/children 2>/dev/null); do
  ps -o pid,ppid,pgid,stat,wchan:30,cmd --pid $c 2>/dev/null | tail -1
done
echo "=== journal 此刻:"; cat "$J" 2>/dev/null | tail -4
echo "=== coord.out:"; cat $D/coord.out
# 再等最多 20s
for i in $(seq 1 40); do
  kill -0 $CPID 2>/dev/null || break
  sleep 0.5
done
echo "=== 最终 rc/输出:"; wait $CPID; echo "rc=$?"; cat $D/coord.out
cat "$J" | tail -4
