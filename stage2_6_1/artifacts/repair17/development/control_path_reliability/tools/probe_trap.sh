#!/usr/bin/env bash
set -uo pipefail
setsid bash -c 'trap "" TERM; sleep 60' < /dev/null &
L=$!
sleep 0.5
PGID=$(ps -o pgid= -p $L | tr -d ' ')
echo "form1 leader=$L pgid=$PGID"
kill -TERM -$PGID 2>/dev/null
sleep 0.6
echo "form1 after TERM members:"
ps -eo pid,pgid,stat,cmd | awk -v g="$PGID" '$2==g {print}'
kill -KILL -$PGID 2>/dev/null; wait $L 2>/dev/null
echo "---form2 loop---"
setsid bash -c 'trap "" TERM; while :; do sleep 1; done' < /dev/null &
L2=$!
sleep 0.5
PG2=$(ps -o pgid= -p $L2 | tr -d ' ')
kill -TERM -$PG2 2>/dev/null
sleep 0.6
echo "form2 after TERM members:"
ps -eo pid,pgid,stat,cmd | awk -v g="$PG2" '$2==g {print}'
kill -KILL -$PG2 2>/dev/null; wait $L2 2>/dev/null
echo done
