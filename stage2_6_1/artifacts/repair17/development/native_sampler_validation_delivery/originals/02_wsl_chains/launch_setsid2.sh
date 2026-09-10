#!/usr/bin/env bash
# R17 验证C setsid 脱离终端链:setsid 启动 entry,外层有界等待(会话保活)
tr -d '\r' < /mnt/f/trading/r17_native_smoke_logs/launch_c.sh > /tmp/launch_c2.sh
setsid bash /tmp/launch_c2.sh setsid > /tmp/r17ns_setsid.log 2>&1 < /dev/null &
BGPID=$!
echo "SETSID_STARTED pid=$BGPID"
for i in $(seq 1 240); do
  sleep 1
  kill -0 "$BGPID" 2>/dev/null || break
done
if kill -0 "$BGPID" 2>/dev/null; then
  echo "TIMEOUT_WAITING_SETSID_CHAIN"
  kill "$BGPID" 2>/dev/null || true
  exit 99
fi
wait "$BGPID"
echo "ENTRY_RC=$?"
echo '---log tail---'
tail -8 /tmp/r17ns_setsid.log
