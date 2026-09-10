#!/usr/bin/env bash
# 启动 R17 原生采样器验证C setsid 脱离终端链
tr -d '\r' < /mnt/f/trading/r17_native_smoke_logs/launch_c.sh > /tmp/launch_c2.sh
setsid bash /tmp/launch_c2.sh setsid > /tmp/r17ns_setsid.log 2>&1 < /dev/null &
echo "SETSID_STARTED pid=$!"
