#!/usr/bin/env bash
# §24:lookahead / recursive 实际运行尝试(短区间)
set -uo pipefail
PROJ="$HOME/projects/crypto_rl"
LOGDIR="$PROJ/logs/freqai_rl_platform_audit"
ART="$PROJ/artifacts/freqai_rl_platform_audit"
EXPCFG="$PROJ/experiments/freqai_rl_platform_audit/configs"
exec > >(tee -a "$LOGDIR/11_lookahead_run.log") 2>&1
echo "===== 11_lookahead_run 开始 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
source "$PROJ/activate-freqtrade.sh"
source "$PROJ/scripts/proxy-on.sh"

echo "=== lookahead-analysis(14天短区间) ==="
timeout 600 freqtrade lookahead-analysis \
  --config "$EXPCFG/config_freqai-rl-platform-audit-2026-7.json" \
  --userdir "$PROJ/user_data" \
  --strategy AuditLongOnlyRLStrategy \
  --freqaimodel AuditBase3RLModel \
  --timerange 20260601-20260615 \
  --lookahead-analysis-exportfilename "$ART/lookahead_analysis_result.json" 2>&1 | tail -30
RC=$?
echo "lookahead-analysis 退出码/超时码: $RC"
ls -la "$ART/lookahead_analysis_result.json" 2>/dev/null || echo "未生成导出文件"

echo
echo "=== recursive-analysis(最小 startup 列表) ==="
timeout 600 freqtrade recursive-analysis \
  --config "$EXPCFG/config_freqai-rl-platform-audit-2026-7.json" \
  --userdir "$PROJ/user_data" \
  --strategy AuditLongOnlyRLStrategy \
  --freqaimodel AuditBase3RLModel \
  --timerange 20260601-20260608 \
  --startup-candle 10 20 2>&1 | tail -25
RC=$?
echo "recursive-analysis 退出码/超时码: $RC"
echo "===== 11_lookahead_run 完成 ====="
