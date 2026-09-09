#!/usr/bin/env bash
# 阶段五全量包冷读(E04):verifier build → 物理冷拷 → 隔离 verify
# → 两负例(缺件/篡改)。等价复用 fail_closed 一条龙,去除已失效的
# WSL HERE 硬编码依赖;全量 run 无 control_failures,故障包不适用。
#
# 用法: bash full_cold_read.sh <repo> <run_name> <workroot> <receipts_dir>
# 返回: 0=健康冷读通过且负例按预期;1=失败;2=用法/环境错误
set -uo pipefail
REPO="$(readlink -f "${1:?用法: full_cold_read.sh <repo> <run_name> <workroot> <receipts_dir>}")"
RUN_NAME="${2:?缺少 run_name}"
WORK="$(readlink -f "${3:?缺少 workroot}")"
RECEIPTS="$(readlink -f "${4:?缺少 receipts_dir}")"
RS_ROOT="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision"
RR="$RS_ROOT/runs/$RUN_NAME/run_record.json"
VERIFIER="$REPO/stage2_6_1/runner/r17_verify_delivery.py"
BCC="$REPO/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/tools/build_cold_copy.py"
RECORD_REL="runs/$RUN_NAME/run_record.json"

[ -f "$RR" ] || { echo "FATAL: run_record 不存在: $RR" >&2; exit 2; }
if [ -e "$WORK" ]; then
  echo "FATAL: workroot 已存在(一次性): $WORK" >&2; exit 2
fi
mkdir -p "$WORK" "$RECEIPTS"

# 1) build(manifest+anchor;必需集合只来自 run_record.required)
python3 "$VERIFIER" build --run-record "$RR" \
  --manifest-out "$WORK/manifest.jsonl" --anchor-out "$WORK/anchor.json" \
  --root "$RS_ROOT" > "$WORK/build.log" 2>&1 || {
  echo "build FAILED"; cat "$WORK/build.log"; exit 1; }

# 2) 冷拷(逐项物理复制+哈希核对)
python3 "$BCC" --source-root "$RS_ROOT" \
  --manifest "$WORK/manifest.jsonl" --anchor "$WORK/anchor.json" \
  --record-rel "$RECORD_REL" --verifier "$VERIFIER" \
  --dest "$WORK/full_coldcopy" > "$WORK/copy.log" 2>&1 || {
  echo "build_cold_copy FAILED"; cat "$WORK/copy.log"; exit 1; }

# 3) 隔离 verify(unshare+tmpfs 遮蔽双原根)
py_tree() {
  python3 - "$1" <<'PYEOF'
import hashlib, json, os, sys
root = sys.argv[1]
out = {}
for dirpath, _d, files in os.walk(root):
    for f in sorted(files):
        p = os.path.join(dirpath, f)
        st = os.stat(p)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[os.path.relpath(p, root)] = [st.st_mtime_ns, st.st_size, h.hexdigest()]
print(json.dumps(out, sort_keys=True))
PYEOF
}

run_isolated_verify() {  # $1=副本根
  local copy="$1" before after
  before="$(py_tree "$copy/payload")" || return 2
  # shellcheck disable=SC2016
  local INNER='
set -u
mount -t tmpfs tmpfs /mnt || exit 9
mount -t tmpfs tmpfs /home/cryptorl/projects || exit 9
mnt_no="no"; [ -d /mnt/f/trading/freqai-rl-audit ] && mnt_no="yes"
proj_no="no"; [ -d /home/cryptorl/projects/crypto_rl ] && proj_no="yes"
cd "$1" || exit 9
mkdir -p receipts_inner
record_rel=$(python3 -c "import json;print(json.load(open(\"metadata/copy_manifest.json\"))[\"record_rel\"])") || exit 9
ver=$(ls verifier/*.py | head -1)
man=$(ls metadata/*.jsonl | grep -v copy_manifest | head -1)
anc=$(ls metadata/anchor.json 2>/dev/null | head -1)
[ -n "$record_rel" ] && [ -n "$ver" ] && [ -n "$man" ] && [ -n "$anc" ] || exit 9
python3 "$ver" verify --root payload --manifest "$man" \
  --anchor-file "$anc" --run-record "payload/$record_rel" \
  --receipt-dir receipts_inner
vrc=$?
printf "%s" "{\"mnt_f_visible\":\"$mnt_no\",\"projects_visible\":\"$proj_no\",\"verify_rc\":$vrc}" > inner.json
exit "$vrc"
'
  unshare --user --map-root-user --mount bash -c "$INNER" _ "$copy" \
    > "$copy/unshare_stdout.log" 2> "$copy/unshare_stderr.log"
  local rc=$?
  after="$(py_tree "$copy/payload")"
  local ro="yes"; [ "$before" = "$after" ] || ro="no"
  echo "$rc $ro"
  return 0
}

o=$(run_isolated_verify "$WORK/full_coldcopy")
HEALTH_RC="${o%% *}"; HEALTH_RO="${o##* }"
INNER_JSON="$(python3 -c "import json;print(json.dumps(json.load(open('$WORK/full_coldcopy/inner.json',encoding='utf-8'))))" 2>/dev/null || echo '{}')"
[ -d "$WORK/full_coldcopy/receipts_inner" ] && cp -r "$WORK/full_coldcopy/receipts_inner"/. "$RECEIPTS/" 2>/dev/null || true
rm -f "$WORK/full_coldcopy/inner.json"

# 4) 负例:N1 缺件 / N2 篡改
cp -r "$WORK/full_coldcopy" "$WORK/neg_missing"
FIRST_PAYLOAD_FILE="$(python3 -c "
import json
rows=[json.loads(l) for l in open('$WORK/manifest.jsonl',encoding='utf-8') if l.strip()]
print(rows[0]['path'])")"
rm "$WORK/neg_missing/payload/$FIRST_PAYLOAD_FILE"
o=$(run_isolated_verify "$WORK/neg_missing"); N1_RC="${o%% *}"

cp -r "$WORK/full_coldcopy" "$WORK/neg_tamper"
python3 - "$WORK/neg_tamper/payload/$FIRST_PAYLOAD_FILE" <<'PYEOF'
import sys
p = sys.argv[1]
b = bytearray(open(p, "rb").read())
b[-8] ^= 0x01
open(p, "wb").write(bytes(b))
PYEOF
o=$(run_isolated_verify "$WORK/neg_tamper"); N2_RC="${o%% *}"

# 5) 汇总
HEALTH_RC="$HEALTH_RC" HEALTH_RO="$HEALTH_RO" INNER_JSON="$INNER_JSON" \
N1_RC="$N1_RC" N2_RC="$N2_RC" python3 - "$RECEIPTS" "$RR" "$FIRST_PAYLOAD_FILE" <<'PYEOF'
import json, os, sys, datetime
receipts, rr, victim = sys.argv[1:4]
inner = json.loads(os.environ["INNER_JSON"] or "{}")
hrc, hro = int(os.environ["HEALTH_RC"]), os.environ["HEALTH_RO"]
n1, n2 = int(os.environ["N1_RC"]), int(os.environ["N2_RC"])
isolated_ok = (hrc == 0 and hro == "yes"
               and inner.get("mnt_f_visible") == "no"
               and inner.get("projects_visible") == "no"
               and inner.get("verify_rc") == 0)
rec = {
    "format": "r17rdd-full-cold-read-v1",
    "run_record": rr,
    "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "isolated_health": {"outer_rc": hrc, "payload_readonly": hro == "yes",
                        "original_root_visible": {"mnt_f": inner.get("mnt_f_visible"),
                                                  "projects": inner.get("projects_visible")},
                        "verify_rc": inner.get("verify_rc")},
    "negatives": {"neg_missing": {"victim": victim, "verify_rc": n1, "expected": 1},
                  "neg_tamper": {"victim": victim, "verify_rc": n2, "expected": 1}},
    "rc": 0 if (isolated_ok and n1 == 1 and n2 == 1) else 1,
}
p = receipts + "/full_cold_read_report.json"
open(p, "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(rec, ensure_ascii=False))
PYEOF
python3 -c "import json,sys;sys.exit(json.load(open('$RECEIPTS/full_cold_read_report.json',encoding='utf-8'))['rc'])"
