#!/usr/bin/env bash
# 手动复现 supervisor 的 ps1 调用(保留 stderr;10 秒样本)
set -u
OUT=/tmp/ps1_probe_out.jsonl
rm -f "$OUT"
PS=/mnt/c/Windows/System32/WindowsPowerShell/v1.0/powershell.exe
PS1_G=/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner/r17_win_sampler.ps1
PS1_W=$($PS -NoProfile -Command 'wslpath' 2>/dev/null; true)
PS1_WIN=$(wslpath -w "$PS1_G")
OUT_WIN=$(wslpath -w "$OUT")
echo "PS1_WIN=$PS1_WIN"
echo "OUT_WIN=$OUT_WIN"
timeout 12 "$PS" -NoProfile -ExecutionPolicy Bypass \
  -File "$PS1_WIN" -RunId probe -OutFile "$OUT_WIN" \
  -MaxSeconds 8 -Volumes "C:,F:" -IntervalSeconds 5 \
  > /tmp/ps1_stdout.txt 2> /tmp/ps1_stderr.txt
echo "PS1_RC=$?"
echo "--- stderr ---"
head -10 /tmp/ps1_stderr.txt
echo "--- out 前 3 行 ---"
head -3 "$OUT" 2>/dev/null || echo "(无输出文件)"
