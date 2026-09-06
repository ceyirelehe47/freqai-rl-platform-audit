#!/usr/bin/env bash
# R17 阶段 D:design 停点受控运行(guest 采样器 + 完整 rt rehearsal)
# 用法: bash run_design_probe.sh <freeze_sha>
# 采样器 5s 间隔;任务树 = pids.txt 登记的 launcher 及其全部后代。
set -u
SHA="${1:?need sha}"
D="$HOME/projects/crypto_rl"
DIAG="$HOME/r17_diag"
mkdir -p "$DIAG"
cp /mnt/f/r17_diagnosis/guest_sampler.py "$DIAG/" 2>/dev/null || true
rm -f "$DIAG/pids.txt"
# guest 采样器(系统级+任务树追踪)
python3 "$DIAG/guest_sampler.py" "$DIAG/guest_samples.jsonl" 5 "$DIAG/pids.txt" &
SPID=$!
sleep 1
# launcher 后台运行(输出重定向,不与采样器混流);pid 登记供追踪
cd "$D"
bash stage2_6_1_runner/r17_rt_rehearsal.sh "$SHA" \
    > "$DIAG/rehearsal_stdout.log" 2>&1 &
LPID=$!
echo "$LPID" > "$DIAG/pids.txt"
wait $LPID
RC=$?
kill "$SPID" 2>/dev/null
wait "$SPID" 2>/dev/null
echo "REHEARSAL_RC=$RC"
echo "DESIGN_PROBE_DONE $(date -u +%Y-%m-%dT%H:%M:%SZ)"
exit $RC
