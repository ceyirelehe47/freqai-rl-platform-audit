#!/usr/bin/env bash
# WP0 只读快照:R17 result-seal-admission closure 接手身份
# (不修改任何正式状态;输出到本交付目录 wp0_identity/)
set -u
REPO=/mnt/f/trading/freqai-rl-audit
OUT="$REPO/stage2_6_1/artifacts/repair17/development/result_seal_admission_closure/wp0_identity"
mkdir -p "$OUT"
cd "$REPO" || exit 1
{
echo "=== 接手时间(UTC) ==="
date -u +%Y-%m-%dT%H:%M:%SZ
echo "=== git HEAD/parent/branch/status ==="
git rev-parse HEAD HEAD^
git branch --show-current
git status --short | head -5
echo "(上方空=工作树干净)"
echo "=== python/import 来源 ==="
which python3
python3 -c "import sys; print('py', sys.version.split()[0]); print('exe', sys.executable)"
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1 || true
python3 -c "import rl_curriculum, os; print('rl_curriculum:', os.path.dirname(rl_curriculum.__file__))" 2>&1 | head -2
echo "=== POLICY 摘要 ==="
python3 - << 'PYEOF' 2>&1 | head -8
import json, sys
sys.path.insert(0, "/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner")
from r17_supervision import POLICY, policy_digest
print("policy_sha256:", policy_digest(POLICY))
print("startup_admission:", json.dumps(POLICY.get("startup_admission")))
print("storage:", json.dumps(POLICY.get("storage")))
PYEOF
echo "=== 正式隔离(只读) ==="
if ls stage2_6_1/.r17_formal_admission.json >/dev/null 2>&1; then
  echo "!! 正式许可存在"
else
  echo "正式许可文件不存在(隔离保持)"
fi
find stage2_6_1 -maxdepth 2 -name ".r17_formal_admission.json" 2>/dev/null | head -3
echo "=== 存活 r17/pytest 任务 ==="
pgrep -af "r17_|pytest|run_supervision" | grep -v "wp0_snapshot\|pgrep" | head -8
echo "(上方空=无存活任务)"
echo "=== 磁盘/存储 ==="
df -BK --output=used / | tail -1
} > "$OUT/wp0_snapshot.txt" 2>&1
echo "WP0_SNAPSHOT_RC=$?"
cat "$OUT/wp0_snapshot.txt"
