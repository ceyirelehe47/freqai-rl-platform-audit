set -uo pipefail
ps -o pid,ppid,etime,stat,cmd -p 298 2>/dev/null || echo "(298 gone)"
ls -l /proc/402/fd 2>/dev/null | head -12
