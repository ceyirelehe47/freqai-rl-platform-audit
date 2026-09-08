#!/usr/bin/env bash
# 冷读负例(fail-closed-integrity-delivery 轮;一次性副本;原件不动;
# 不回退原根;不重建清单)。复用 unified_shutdown_cold_read 同型流程,
# 隔离面与本轮 cold_read_isolated_fc.sh 一致(/mnt+/home/cryptorl/
# projects 双原根遮蔽)。
# 用法: bash cold_read_negative_fc.sh <正例copy_root> <receipt_dir>
# 形态:
#   N1=缺一件(原根仍有该文件——验证进程看不到原根,必须因内容
#      错误失败,不得补读);
#   N2=篡改一字节(追加;哈希矛盾失败);
#   N3=故障包(控制失败 run 的独立副本——verify 必须因 control_
#      failures 非空拒绝,不得因隔离/崩溃失败;由调用方预先用
#      build_cold_copy 对故障 run 组包,路径经 N3_ROOT 传入)。
set -uo pipefail
GOOD="$(readlink -f "${1:?用法: cold_read_negative_fc.sh <copy_root> <receipt_dir> [故障包copy_root]}")"
RECEIPTS="$(readlink -f "${2:?缺少 receipt_dir}")"
N3_ROOT="${3:-}"
HERE=/home/cryptorl/r17fc_dev
mkdir -p "$RECEIPTS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RESULT="$RECEIPTS/negative_${STAMP}.json"

run_case() {  # <name> <copy_root> <receipt_dir>
  bash "$HERE/cold_read_isolated_fc.sh" "$2" "$3" >/dev/null 2>&1
  echo $?
}

declare -A OUT
# N1 缺件:删 manifest 中一件(原根文件仍在——验证进程看不到原根)
N1_ROOT="$(readlink -f "$GOOD/../neg_missing_${STAMP}")"
cp -r "$GOOD" "$N1_ROOT"
VICTIM="$(cd "$N1_ROOT/payload" && find . -type f | sort | head -1)"
rm -f "$N1_ROOT/payload/$VICTIM"
OUT[n1_missing_rc]="$(run_case n1 "$N1_ROOT" "$RECEIPTS/n1")"

# N2 篡改:对一件已复制文件追加 1 字节(副本内;原件不动)
N2_ROOT="$(readlink -f "$GOOD/../neg_tamper_${STAMP}")"
cp -r "$GOOD" "$N2_ROOT"
VICTIM2="$(cd "$N2_ROOT/payload" && find . -type f | sort | tail -1)"
printf 'X' >> "$N2_ROOT/payload/$VICTIM2"
OUT[n2_tamper_rc]="$(run_case n2 "$N2_ROOT" "$RECEIPTS/n2")"

# N3 故障包:控制失败 run 的固定诊断记录(verify 因 control_failures
# 拒绝;失败证据完整≠运行通过)
N3_RC="-1"
if [ -n "$N3_ROOT" ] && [ -d "$N3_ROOT" ]; then
  N3_RC="$(run_case n3 "$N3_ROOT" "$RECEIPTS/n3")"
fi

python3 - "$RESULT" "$N1_ROOT" "$N2_ROOT" "$N3_ROOT" \
  "${OUT[n1_missing_rc]}" "${OUT[n2_tamper_rc]}" "$N3_RC" <<'PYEOF'
import json, sys
rp, n1, n2, n3, r1, r2, r3 = sys.argv[1:8]
rec = {
    "schema": "r17-cold-read-negative-fc-v1",
    "n1_missing_copy": n1, "n1_isolated_verify_rc": int(r1),
    "n2_tamper_copy": n2, "n2_isolated_verify_rc": int(r2),
    "n3_control_failure_copy": n3 or None,
    "n3_isolated_verify_rc": int(r3) if r3 != "-1" else None,
    "rc": (0 if int(r1) != 0 and int(r2) != 0
           and (r3 == "-1" or int(r3) != 0) else 1),
    "note": "缺件/篡改/控制失败包都必须在只见新根时失败(内容错误,"
            "不是脚本崩溃或隔离权限错误;不补读/不重算/不重建清单)",
}
open(rp, "w", encoding="utf-8").write(
    json.dumps(rec, ensure_ascii=False, indent=1))
print(json.dumps(rec, ensure_ascii=False))
PYEOF
python3 -c "import json,sys;sys.exit(json.load(open('$RESULT',encoding='utf-8'))['rc'])"
