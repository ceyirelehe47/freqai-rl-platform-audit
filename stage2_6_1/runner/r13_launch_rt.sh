#!/usr/bin/env bash
# R13:以 setsid 后台启动 rehearsal(脱离会话;输出到既有 log)
setsid bash -c "tr -d '\r' < /mnt/e/trading/freqai-rl-audit/stage2_6_1/runner/r13_rt_rehearsal.sh | bash" > /tmp/r13_rt4.log 2>&1 < /dev/null &
echo "launched pid=$!"
