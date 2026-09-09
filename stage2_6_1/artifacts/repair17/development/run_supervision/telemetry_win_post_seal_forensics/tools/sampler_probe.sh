#!/usr/bin/env bash
# 短 sampler 开始—停止—封口检查(一次性新 run;不覆盖旧记录)。
# 业务=1 秒 python;观察 seal 事件、seal 前后文件大小增长、写者进程。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
RUN_DIR="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eto_sampler_probe_20260909"
[ -e "$RUN_DIR" ] && { echo "FATAL: run 目录已存在(一次性)" >&2; exit 2; }
export R17_PROJECT_ROOT=/home/cryptorl/projects/crypto_rl
export R17_RUN_DIR="$RUN_DIR"

WIN_REL="stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eto_sampler_probe_20260909/telemetry/win_samples.jsonl"
WIN_F="F:\\trading\\freqai-rl-audit\\$WIN_REL"
WIN_GUEST="$REPO/$WIN_REL"

probe_size() { stat -c "%s %Y" "$WIN_GUEST" 2>/dev/null || echo "absent"; }

echo "[probe] 启动受监护短任务 $(date -u +%H:%M:%SZ)"
bash "$REPO/stage2_6_1/runner/r17_monitored_entry.sh" pytest \
  --max-seconds 180 -- \
  python3 -c "print('sampler_probe_ok')" > /tmp/probe_outer.log 2>&1
echo "[probe] OUTER_RC=$? $(date -u +%H:%M:%SZ)"
tail -3 /tmp/probe_outer.log
grep -E "win_sampler_(started|ready|stopped|stop_unconfirmed)|sampler_end|finalize|run_record" \
  "$RUN_DIR/alerts/alerts.jsonl" 2>/dev/null | head -10
echo "[probe] seal 后立即: $(probe_size)"
sleep 45
echo "[probe] +45s:        $(probe_size)"
sleep 45
echo "[probe] +90s:        $(probe_size)"
echo "[probe] run_record required:"
python3 -c "
import json
rec = json.load(open('$RUN_DIR/run_record.json', encoding='utf-8'))
for r in rec.get('required', []):
    if 'telemetry_win' in r.get('role',''):
        print(' ', r.get('role'), r.get('bytes'), r.get('sha256','')[:16])
" 2>&1
