#!/usr/bin/env bash
# §28 最终清理与检查
set -uo pipefail
PROJ="$HOME/projects/crypto_rl"
LOGDIR="$PROJ/logs/freqai_rl_platform_audit"
exec > >(tee -a "$LOGDIR/13_final_check.log") 2>&1
echo "===== 13_final_check 开始 $(date -u +%Y-%m-%dT%H:%M:%SZ) ====="
source "$PROJ/activate-freqtrade.sh"

echo "--- 1. 上游仓库状态 ---"
git -C "$PROJ/vendor/freqtrade" status --short
echo "[exit=$? ; 输出为空=干净]"
git -C "$PROJ/vendor/freqtrade" rev-parse HEAD
git -C "$PROJ/vendor/freqtrade" describe --tags --exact-match

echo "--- 2. 后台进程检查 ---"
ps aux | grep -iE 'freqtrade|tensorboard' | grep -v grep || echo "无 freqtrade/tensorboard 进程"

echo "--- 3. 凭据检查(本任务创建的文件中搜索疑似密钥) ---"
FOUND=$(grep -rliE 'api[_-]?key|secret[\"'"'"']?\s*[:=]\s*[\"'"'"'][A-Za-z0-9]{8,}' \
  "$PROJ/experiments/freqai_rl_platform_audit" \
  "$PROJ/tests/freqai_rl_platform_audit" \
  "$PROJ/user_data/strategies/OfficialRLStrategy5ac.py" \
  "$PROJ/user_data/strategies/AuditLongOnlyRLStrategy.py" \
  "$PROJ/user_data/freqaimodels/AuditBase3RLModel.py" 2>/dev/null || true)
if [ -z "$FOUND" ]; then echo "未发现凭据写入"; else echo "疑似命中: $FOUND"; fi
grep -l '7897' "$PROJ"/experiments/freqai_rl_platform_audit/configs/*.json 2>/dev/null | while read -r f; do
  echo "注意: $f 包含代理端口(无认证信息,仅端口)"; done

echo "--- 4. 固定依赖未被升级(pip check + 运行时包清单对比) ---"
python -m pip check
python -m pip list --format=freeze | grep -iE '^(torch|stable-baselines3|gymnasium|sb3-contrib|freqtrade|tensorboard)=' 

echo "--- 5. 产物完整性 ---"
ls "$PROJ/artifacts/freqai_rl_platform_audit/" | sort
ls "$PROJ/reports/"
echo "--- 6. 数据与 user_data ---"
ls "$PROJ/user_data/data/binanceus/"
ls "$PROJ/user_data/models/"
echo "===== 13_final_check 完成 ====="
