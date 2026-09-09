#!/usr/bin/env bash
# E05 汇总入口实际执行:正例(全部证据成立)+负例(缺 C3 语义回执,
# pytest/全量子包回执仍齐全 → 整体必须 FAIL)。
# 用法: bash run_e05.sh <repo>   (在全量冷读完成后执行)
set -uo pipefail
REPO="$(readlink -f "${1:?用法: run_e05.sh <repo>}")"
D="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
VER="$D/verification"
AGG="$D/tools/aggregate_verdict.py"
OUT="$VER/aggregate"
mkdir -p "$OUT"

FULL_RR="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3rdd_full_20260909/run_record.json"
FULL_VR="$(ls "$VER"/full_cold_read/verify_*.json 2>/dev/null | head -1)"
[ -n "$FULL_VR" ] || { echo "FATAL: 全量冷读 verify 回执缺失"; exit 2; }

cat > "$OUT/agg_config.json" <<EOF
{
  "full_run_record": "$FULL_RR",
  "full_verify_receipt": "$FULL_VR",
  "c3_finalize_report": "$VER/finalize_report.json",
  "c3_semantic_receipt": "$VER/receipts/semantic_health.json",
  "c3_cold_receipt": "$VER/cold_read/cold_read_report.json"
}
EOF

# 正例
python3 "$AGG" --config "$OUT/agg_config.json" --report "$OUT/aggregate_report.json"
POS_RC=$?
echo "E05 positive rc=$POS_RC"

# 负例:临时目录复制六输入,仅删 C3 语义回执(全量子包证据不动)
NEG="$OUT/neg_missing_semantic"
rm -rf "$NEG"; mkdir -p "$NEG"
python3 - "$OUT/agg_config.json" "$NEG" <<'PYEOF'
import json, shutil, sys
from pathlib import Path
cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
neg = Path(sys.argv[2])
for key, p in cfg.items():
    if key == "c3_semantic_receipt":
        # 该子包回执缺失(负例构造):指向不存在的路径
        cfg[key] = str(neg / "semantic_receipt_MISSING.json")
        continue
    dst = neg / f"{key}.json"
    shutil.copyfile(Path(p), dst)
    cfg[key] = str(dst)
(neg / "config.json").write_text(
    json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
PYEOF
python3 "$AGG" --config "$NEG/config.json" --report "$NEG/aggregate_report.json"
NEG_RC=$?
echo "E05 negative rc=$NEG_RC (expect 1:pytest/全量子包齐全也不能整体通过)"

[ "$POS_RC" -eq 0 ] && [ "$NEG_RC" -eq 1 ] && echo "E05_OK" || { echo "E05_FAIL"; exit 1; }
