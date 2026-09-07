#!/usr/bin/env bash
# 冷读负例(一次性副本上;原件不动;不回退原根;不重建清单)。
# 用法: bash cold_read_negative.sh <正例copy_root> <receipt_dir>
# 形态: C03=缺一件(原根仍有该文件);C04=篡改一字节。
set -uo pipefail
GOOD="$(readlink -f "${1:?用法: cold_read_negative.sh <copy_root> <receipt_dir>}")"
RECEIPTS="$(readlink -f "${2:?缺少 receipt_dir}")"
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$RECEIPTS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT="$RECEIPTS/negative_${STAMP}.json"

run_case() {  # <name> <copy_root> <receipt_dir>
  bash "$HERE/cold_read_isolated.sh" "$2" "$3" >/dev/null 2>&1
  echo $?
}

declare -A OUT
# C03 缺件:删 manifest 中一件(原根文件仍在——验证进程看不到原根)
C03_ROOT="$(readlink -f "$GOOD/../neg_missing_${STAMP}")"
cp -r "$GOOD" "$C03_ROOT"
VICTIM="$(cd "$C03_ROOT/payload" && find . -type f | sort | head -1)"
rm -f "$C03_ROOT/payload/$VICTIM"
OUT[c03_missing_rc]="$(run_case c03 "$C03_ROOT" "$RECEIPTS/c03")"

# C04 篡改:对一件已复制文件追加 1 字节(副本内;原件不动)
C04_ROOT="$(readlink -f "$GOOD/../neg_tamper_${STAMP}")"
cp -r "$GOOD" "$C04_ROOT"
VICTIM2="$(cd "$C04_ROOT/payload" && find . -type f | sort | tail -1)"
printf 'X' >> "$C04_ROOT/payload/$VICTIM2"
OUT[c04_tamper_rc]="$(run_case c04 "$C04_ROOT" "$RECEIPTS/c04")"

python3 - "$RESULT" "$C03_ROOT" "$C04_ROOT" "${OUT[c03_missing_rc]}" "${OUT[c04_tamper_rc]}" <<'PYEOF'
import json, sys
rp, c03, c04, r3, r4 = sys.argv[1:6]
rec = {
    "schema": "r17-cold-read-negative-v1",
    "c03_missing_copy": c03, "c03_isolated_verify_rc": int(r3),
    "c04_tamper_copy": c04, "c04_isolated_verify_rc": int(r4),
    "rc": (0 if int(r3) != 0 and int(r4) != 0 else 1),
    "note": "缺件/篡改必须在只见新根时失败(无回退/无重算/无重建清单)",
}
open(rp, "w", encoding="utf-8").write(
    json.dumps(rec, ensure_ascii=False, indent=1))
print(json.dumps(rec, ensure_ascii=False))
PYEOF
python3 -c "import json,sys;sys.exit(json.load(open('$RESULT',encoding='utf-8'))['rc'])"
