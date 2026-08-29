#!/usr/bin/env bash
# §24 最终:lookahead-analysis 前台短区间运行(注意:该工具会 rmtree freqai identifier 目录)
set -uo pipefail
PROJ="$HOME/projects/crypto_rl"
LOGDIR="$PROJ/logs/freqai_rl_platform_audit"
ART="$PROJ/artifacts/freqai_rl_platform_audit"
EXPCFG="$PROJ/experiments/freqai_rl_platform_audit/configs"
exec > >(tee -a "$LOGDIR/11c_lookahead_foreground.log") 2>&1
echo "===== 11c_lookahead_foreground 开始 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
source "$PROJ/activate-freqtrade.sh"
source "$PROJ/scripts/proxy-on.sh"

timeout 1500 freqtrade lookahead-analysis \
  --config "$EXPCFG/config_lookahead_variant.json" \
  --userdir "$PROJ/user_data" \
  --strategy AuditLongOnlyRLStrategy \
  --freqaimodel AuditBase3RLModel \
  --timerange 20260601-20260603 \
  --lookahead-analysis-exportfilename "$ART/lookahead_analysis_result.json" 2>&1 | tail -45
RC=$?
echo "lookahead-analysis 退出码/超时码: $RC"
ls -la "$ART/lookahead_analysis_result.json" 2>/dev/null || echo "未生成导出文件"
echo "===== 11c_lookahead_foreground 完成 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
