#!/usr/bin/env bash
# 组装 GitHub 发布目录(报告+证据+复现+日志)
set -euo pipefail
PROJ="$HOME/projects/crypto_rl"
DEST="/mnt/e/trading/freqai-rl-audit"

rm -rf "$DEST"
mkdir -p "$DEST/report" "$DEST/artifacts" "$DEST/reproduction/configs" "$DEST/reproduction/scripts" "$DEST/logs"

cp "$PROJ/reports/freqai_rl_phase1_2_audit.md" "$DEST/report/"
cp "$PROJ/artifacts/freqai_rl_platform_audit/"* "$DEST/artifacts/"
cp "$PROJ/tests/freqai_rl_platform_audit/"*.py "$DEST/reproduction/scripts/" 2>/dev/null || true
cp "$PROJ/tests/freqai_rl_platform_audit/"*.sh "$DEST/reproduction/scripts/" 2>/dev/null || true
cp "$PROJ/experiments/freqai_rl_platform_audit/configs/"*.json "$DEST/reproduction/configs/"
cp "$PROJ/experiments/freqai_rl_platform_audit/README.md" "$DEST/reproduction/README.md"
cp "$PROJ/logs/freqai_rl_platform_audit/"*.log "$DEST/logs/"

echo "--- 组装完成 ---"
find "$DEST" -type f | wc -l
du -sh "$DEST"
echo "--- 最终敏感扫描(应无输出) ---"
grep -rniE 'github_pat|ghp_[A-Za-z0-9]{10}|gho_[A-Za-z0-9]{10}|password[[:space:]]*[:=][[:space:]]*[^[:space:]]+' "$DEST" | head -5 || true
echo "--- 空密钥占位确认 ---"
grep -rn '"key"' "$DEST/reproduction/configs/" | head -4
