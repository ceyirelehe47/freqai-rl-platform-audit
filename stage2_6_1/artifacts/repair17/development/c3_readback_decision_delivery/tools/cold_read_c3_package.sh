#!/usr/bin/env bash
# C3 关联交付包隔离冷读 + 三负例(E01/E02/E03 冷读侧)。
#
# 输入布局:verification/package/{payload/, manifest.jsonl, anchor.json}
#   payload 内含 engineering_slice/、c3_evidence/、p52_envelope/、
#   tools/(reader+verifier)、runs/<run1>/...
#
# 流程:
#   1) build_cold_copy:按 finalize 后的 manifest/anchor 物理复制
#      payload/metadata/verifier 到一次性副本根
#   2) 隔离冷读(unshare+tmpfs 遮蔽 /mnt 与 /home/cryptorl/projects):
#      副本内 verifier verify(字节)+ 新 reader 只读读回(语义)+
#      原根不可达断言 + payload 前后快照不变
#   3) 负例(独立副本):缺件/篡改字节(verify 检出)/语义错配
#      (manifest+锚自洽重签的夹具副本:verify 通过、reader 拒绝)
#
# 用法: bash cold_read_c3_package.sh <repo> <deliver_out> <workroot>
# 返回: 0=健康冷读通过且负例全部按预期;1=任何失败;2=环境/用法错误
set -uo pipefail
REPO="$(readlink -f "${1:?用法: cold_read_c3_package.sh <repo> <deliver_out> <workroot>}")"
DELIV="$(readlink -f "${2:?缺少 deliver_out}")"
WORK="$(readlink -f "${3:?缺少 workroot}")"
VER="$DELIV/verification"
BCC="$REPO/stage2_6_1/artifacts/repair17/development/unified_shutdown_cold_read/tools/build_cold_copy.py"
_SL_REL="engineering_slice"
_ENV_REL="p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json"
_READER_REL="tools/r17_c3_engineering_slice.py"
RECEIPTS="$VER/cold_read"

if [ -e "$WORK" ]; then
  echo "FATAL: workroot 已存在(一次性): $WORK" >&2; exit 2
fi
mkdir -p "$WORK" "$RECEIPTS"

RECORD_REL="$(python3 -c "import json;print(json.load(open('$VER/finalize_report.json',encoding='utf-8'))['record_rel_in_payload'])")"
[ -n "$RECORD_REL" ] || { echo "FATAL: finalize_report 无 record_rel"; exit 2; }

# 1) 冷副本(逐项物理复制+哈希核对)
python3 "$BCC" --source-root "$VER/package/payload" \
  --manifest "$VER/package/manifest.jsonl" \
  --anchor "$VER/package/anchor.json" \
  --record-rel "$RECORD_REL" \
  --verifier "$VER/package/payload/tools/r17_verify_delivery.py" \
  --dest "$WORK/coldcopy" || { echo "build_cold_copy FAILED"; exit 1; }

# 2) 隔离冷读(健康副本):verify(字节)+reader(语义)+快照+遮蔽断言
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

run_isolated() {  # $1=副本根 $2=yes/no 是否跑 reader 语义
  local copy="$1" with_reader="$2"
  local before after
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
rrc=0
if [ "$2" = "yes" ]; then
  python3 "payload/'"$_READER_REL"'" --readback \
    "payload/'"$_SL_REL"'" \
    --p52-envelope "payload/'"$_ENV_REL"'" \
    --report receipts_inner/semantic_readback.json
  rrc=$?
fi
printf "%s" "{\"mnt_f_visible\":\"$mnt_no\",\"projects_visible\":\"$proj_no\",\"verify_rc\":$vrc,\"reader_rc\":$rrc}" > inner.json
[ "$vrc" -eq 0 ] || exit "$vrc"
exit "$rrc"
'
  unshare --user --map-root-user --mount bash -c "$INNER" _ "$copy" \
    "$with_reader" > "$copy/unshare_stdout.log" \
    2> "$copy/unshare_stderr.log"
  local rc=$?
  after="$(py_tree "$copy/payload")"
  local ro="yes"; [ "$before" = "$after" ] || ro="no"
  echo "$rc $ro"
  return 0
}

read_inner() { python3 -c "import json;print(json.dumps(json.load(open('$1/inner.json',encoding='utf-8'))))" 2>/dev/null || echo '{}'; }

read_out=$(run_isolated "$WORK/coldcopy" yes)
HEALTH_RC="${read_out%% *}"; HEALTH_RO="${read_out##* }"
INNER_JSON="$(read_inner "$WORK/coldcopy")"
mkdir -p "$RECEIPTS/isolated"
if [ -d "$WORK/coldcopy/receipts_inner" ]; then
  cp -r "$WORK/coldcopy/receipts_inner"/. "$RECEIPTS/isolated/" 2>/dev/null || true
fi
rm -f "$WORK/coldcopy/inner.json"

# 3) 负例
NEGS="{}"

# N1 缺件:删 p52_negative.json → verify 必须 rc=1(具体内容错误)
cp -r "$WORK/coldcopy" "$WORK/neg_missing"
rm "$WORK/neg_missing/payload/$_SL_REL/p52_negative.json"
o=$(run_isolated "$WORK/neg_missing" no); N1_RC="${o%% *}"
NEGS=$(NEGS="$NEGS" N1_RC="$N1_RC" python3 -c '
import json, os
d = json.loads(os.environ["NEGS"])
d["neg_missing"] = {"verify_rc": int(os.environ["N1_RC"]), "expected": 1}
print(json.dumps(d))')

# N2 篡改字节:recipe.json 尾部一字节翻转 → verify rc=1
cp -r "$WORK/coldcopy" "$WORK/neg_tamper"
python3 - "$WORK/neg_tamper/payload/$_SL_REL/recipe.json" <<'PYEOF'
import sys
p = sys.argv[1]
b = bytearray(open(p, "rb").read())
b[-8] ^= 0x01
open(p, "wb").write(bytes(b))
PYEOF
o=$(run_isolated "$WORK/neg_tamper" no); N2_RC="${o%% *}"
NEGS=$(NEGS="$NEGS" N2_RC="$N2_RC" python3 -c '
import json, os
d = json.loads(os.environ["NEGS"])
d["neg_tamper"] = {"verify_rc": int(os.environ["N2_RC"]), "expected": 1}
print(json.dumps(d))')

# N3 语义错配(自洽夹具副本):R05 式跨坐标引用+行哈希+manifest 行 sha
#    同步改写+副本内重锚 → verify rc=0(字节自洽)且 reader rc=1(语义拒绝)。
#    该夹具只作用于 neg_semantic 副本自身的 metadata,健康交付的
#    manifest/anchor 从未被修改或重新签署。
cp -r "$WORK/coldcopy" "$WORK/neg_semantic"
python3 - "$WORK/neg_semantic" <<'PYEOF'
import hashlib, json, sys
from pathlib import Path
copy = Path(sys.argv[1])
es = copy / "payload" / "engineering_slice"
rows_p = es / "slice_results.jsonl"
rows = [json.loads(l) for l in rows_p.read_text(encoding="utf-8").splitlines() if l.strip()]
for row in rows:
    if row["coord"] == "D1/p0":
        row["detail"] = "D0_p0.json"
        row["detail_sha256"] = hashlib.sha256(
            (es / "pairs" / "D0_p0.json").read_bytes()).hexdigest()
rows_p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n",
                  encoding="utf-8")
new_sha = hashlib.sha256(rows_p.read_bytes()).hexdigest()
man_p = copy / "metadata" / "manifest.jsonl"
lines = []
for l in man_p.read_text(encoding="utf-8").splitlines():
    if l.strip():
        row = json.loads(l)
        if row["path"].endswith("slice_results.jsonl"):
            row["sha256"] = new_sha
            row["bytes"] = rows_p.stat().st_size
        lines.append(json.dumps(row, ensure_ascii=False, separators=(",", ":")))
man_p.write_text("\n".join(lines) + "\n", encoding="utf-8")
anc_p = copy / "metadata" / "anchor.json"
anc = json.loads(anc_p.read_text(encoding="utf-8"))
anc["manifest_sha256"] = hashlib.sha256(man_p.read_bytes()).hexdigest()
anc["manifest_bytes"] = man_p.stat().st_size
anc["note"] = "semantic-fixture re-anchored copy (test-only; healthy delivery anchor untouched)"
anc_p.write_text(json.dumps(anc, ensure_ascii=False, indent=1), encoding="utf-8")
PYEOF
o=$(run_isolated "$WORK/neg_semantic" yes); N3_RC="${o%% *}"
N3_INNER="$(read_inner "$WORK/neg_semantic")"
NEGS=$(NEGS="$NEGS" N3_RC="$N3_RC" N3_INNER="$N3_INNER" python3 -c '
import json, os
d = json.loads(os.environ["NEGS"])
inner = json.loads(os.environ["N3_INNER"] or "{}")
d["neg_semantic"] = {"verify_rc": inner.get("verify_rc"), "reader_rc": inner.get("reader_rc"),
                     "expected": {"verify_rc": 0, "reader_rc": 1},
                     "outer_rc": int(os.environ["N3_RC"])}
print(json.dumps(d))')

# 汇总
NEGS="$NEGS" HEALTH_RC="$HEALTH_RC" HEALTH_RO="$HEALTH_RO" \
INNER_JSON="$INNER_JSON" python3 - "$RECEIPTS" <<'PYEOF'
import json, os, sys, datetime
receipts = sys.argv[1]
negs = json.loads(os.environ["NEGS"])
inner = json.loads(os.environ["INNER_JSON"] or "{}")
hrc, hro = int(os.environ["HEALTH_RC"]), os.environ["HEALTH_RO"]
ok_negs = (
    negs["neg_missing"]["verify_rc"] == 1
    and negs["neg_tamper"]["verify_rc"] == 1
    and negs["neg_semantic"]["verify_rc"] == 0
    and negs["neg_semantic"]["reader_rc"] == 1)
isolated_ok = (hrc == 0 and hro == "yes"
               and inner.get("mnt_f_visible") == "no"
               and inner.get("projects_visible") == "no"
               and inner.get("verify_rc") == 0
               and inner.get("reader_rc") == 0)
rec = {
    "format": "r17rdd-c3-package-cold-read-v1",
    "receipts_dir": receipts,
    "written_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
    "isolated_health": {"outer_rc": hrc, "payload_readonly": hro == "yes",
                        "original_root_visible": {"mnt_f": inner.get("mnt_f_visible"),
                                                  "projects": inner.get("projects_visible")},
                        "verify_rc": inner.get("verify_rc"),
                        "reader_rc": inner.get("reader_rc")},
    "negatives": negs,
    "rc": 0 if (isolated_ok and ok_negs) else 1,
}
p = receipts + "/cold_read_report.json"
open(p, "w", encoding="utf-8").write(json.dumps(rec, ensure_ascii=False, indent=1) + "\n")
print(json.dumps(rec, ensure_ascii=False))
PYEOF
python3 -c "import json,sys;sys.exit(json.load(open('$RECEIPTS/cold_read_report.json',encoding='utf-8'))['rc'])"
