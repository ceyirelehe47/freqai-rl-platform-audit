#!/usr/bin/env bash
# R17 c3-identity-receipt-archive-closure:本轮 v3 包隔离冷读(E02/E03)。
# 用法(WSL): cold_read_v3.sh <package_dir> <work_root> <out_report_json>
# 一次性合同:work_root 须不存在。
set -uo pipefail

PKG="$1"; WORK="$2"; REPORT="$3"
PY=/usr/bin/python3
[ -d "$PKG/payload" ] || { echo "FATAL: 非 v3 包目录: $PKG" >&2; exit 2; }
[ -e "$WORK" ] && { echo "FATAL: work 已存在(一次性): $WORK" >&2; exit 2; }
mkdir -p "$WORK"
COPY="$WORK/cold_copy"
cp -r "$PKG" "$COPY"

receipts="$WORK/receipts_outer"
mkdir -p "$receipts"

# payload 只读快照(sha256,size,mtime_ns)
snap_payload() {
  (cd "$1" && find . -type f | LC_ALL=C sort | while read -r f; do
     sha256sum "$f" | cut -d' ' -f1
     stat -c '%s %Y' "$f"
   done) | sha256sum | cut -d' ' -f1
}

BEFORE_SNAP=$(snap_payload "$COPY/payload")

# 隔离执行:tmpfs 遮蔽原证据根(/mnt/f/trading/freqai-rl-audit)与开发
# 代码根(/home/cryptorl/projects);副本在 /tmp(隔离范围外);unshare
# 子进程 stdout/stderr 重定向到副本根日志,不污染函数返回值。
run_isolated() {
  local copy="$1" inner_log="$2"
  unshare --user --map-root-user --mount bash -c '
    mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
    mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
    ls /mnt/f/trading/freqai-rl-audit >/dev/null 2>&1 && [ -n "$(ls -A /mnt/f/trading/freqai-rl-audit 2>/dev/null)" ] && exit 98
    [ -n "$(ls -A /home/cryptorl/projects 2>/dev/null)" ] && exit 98
    cd "'"$copy"'"
    '"$PY"' payload/tools/r17_verify_delivery.py verify \
      --root payload --manifest manifest.jsonl \
      --anchor-file anchor.json --receipt-dir '"$receipts"' \
      > '"$copy"'/verify_stdout.log 2> '"$copy"'/verify_stderr.log
    echo $? > '"$copy"'/verify_rc
    '"$PY"' payload/tools/r17_c3_engineering_slice.py \
      --readback payload/engineering_slice \
      --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
      --report '"$copy"'/receipts_inner/semantic_readback.json \
      --protect-root payload \
      > '"$copy"'/reader_stdout.log 2> '"$copy"'/reader_stderr.log
    echo $? > '"$copy"'/reader_rc
  ' > "$inner_log" 2>&1
}

NEGS_RC=0
run_isolated "$COPY" "$WORK/unshare_inner.log"
UNSHARE_RC=$?
VERIFY_RC=$(cat "$COPY/verify_rc" 2>/dev/null || echo missing)
READER_RC=$(cat "$COPY/reader_rc" 2>/dev/null || echo missing)
AFTER_SNAP=$(snap_payload "$COPY/payload")

# 健康语义回执断言字段
SEM_OK=$("$PY" - "$COPY/receipts_inner/semantic_readback.json" <<'PYEOF'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    ok = (d.get("readback_verdict") == "PASS"
          and all(v is True for v in d.get("checks", {}).get(
              "envelope_digest", {}).values())
          and all(v is True for v in d.get("checks", {}).get(
              "p52_identity_body", {}).values())
          and d.get("report_target_admission", {}).get("admitted") is True)
    print("ok" if ok else "bad")
except Exception:
    print("bad")
PYEOF
)

# ---- 负例 1:缺关键件(verifier 拒) ----
NEG1="$WORK/neg_missing"; cp -r "$PKG" "$NEG1"
rm "$NEG1/payload/engineering_slice/p52_negative.json"
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEG1"'"
  '"$PY"' payload/tools/r17_verify_delivery.py verify --root payload \
    --manifest manifest.jsonl --anchor-file anchor.json \
    --receipt-dir '"$receipts"' > neg1.log 2>&1; echo $? > neg1_rc
' >/dev/null 2>&1
NEG1_RC=$(cat "$NEG1/neg1_rc" 2>/dev/null || echo missing)

# ---- 负例 2:字节篡改(verifier 拒) ----
NEG2="$WORK/neg_tamper"; cp -r "$PKG" "$NEG2"
printf 'X' >> "$NEG2/payload/engineering_slice/recipe.json"
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEG2"'"
  '"$PY"' payload/tools/r17_verify_delivery.py verify --root payload \
    --manifest manifest.jsonl --anchor-file anchor.json \
    --receipt-dir '"$receipts"' > neg2.log 2>&1; echo $? > neg2_rc
' >/dev/null 2>&1
NEG2_RC=$(cat "$NEG2/neg2_rc" 2>/dev/null || echo missing)

# ---- 负例 3:I02 自洽错配(verifier 字节过 + 新 reader 语义拒) ----
NEG3="$WORK/neg_i02"; cp -r "$PKG" "$NEG3"
"$PY" - "$NEG3" <<'PYEOF'
import hashlib, json, sys
from pathlib import Path
neg = Path(sys.argv[1])
dpath = neg / "payload/engineering_slice/pairs/D0_p0.json"
doc = json.loads(dpath.read_text(encoding="utf-8"))
new_h = {s: "ce-" + hashlib.sha256(f"i02-{s}".encode()).hexdigest()
         for s in ("A", "B")}
doc["episode_hashes"] = dict(new_h)
doc["pair_record"]["attempt_log"]["output_episode_hashes"] = dict(new_h)
for ep in doc["evaluation"]["episodes"]:
    ep["episode_hash"] = new_h[ep["side"]]
dpath.write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                 encoding="utf-8")
sha = hashlib.sha256(dpath.read_bytes()).hexdigest()
# manifest 行内哈希同步改写并重锚(字节层自洽)
rows = [json.loads(l) for l in (neg / "manifest.jsonl").read_text(
    encoding="utf-8").splitlines() if l.strip()]
for r in rows:
    if r.get("role") == "slice_pair_D0_p0":
        r["sha256"] = sha
        r["bytes"] = dpath.stat().st_size
mp = neg / "manifest.jsonl"
mp.write_text("\n".join(json.dumps(r, ensure_ascii=False,
                                   separators=(",", ":"))
                        for r in rows) + "\n", encoding="utf-8")
anchor = json.loads((neg / "anchor.json").read_text(encoding="utf-8"))
anchor["manifest_sha256"] = hashlib.sha256(
    mp.read_bytes()).hexdigest()
anchor["manifest_bytes"] = mp.stat().st_size
(neg / "anchor.json").write_text(
    json.dumps(anchor, ensure_ascii=False, indent=1), encoding="utf-8")
PYEOF
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEG3"'"
  '"$PY"' payload/tools/r17_verify_delivery.py verify --root payload \
    --manifest manifest.jsonl --anchor-file anchor.json \
    --receipt-dir '"$receipts"' > neg3v.log 2>&1; echo $? > neg3_vrc
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report receipts_inner/r.json --protect-root payload \
    > neg3r.log 2>&1; echo $? > neg3_rrc
' >/dev/null 2>&1
NEG3_VRC=$(cat "$NEG3/neg3_vrc" 2>/dev/null || echo missing)
NEG3_RRC=$(cat "$NEG3/neg3_rrc" 2>/dev/null || echo missing)

# ---- 负例 4:非法 report 目标(reader 写前拒,零源写入) ----
NEG4="$WORK/neg_report"; cp -r "$PKG" "$NEG4"
BEFORE4=$(snap_payload "$NEG4/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEG4"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report payload/engineering_slice/recipe.json \
    --protect-root payload > neg4.log 2>&1; echo $? > neg4_rc
' >/dev/null 2>&1
NEG4_RC=$(cat "$NEG4/neg4_rc" 2>/dev/null || echo missing)
AFTER4=$(snap_payload "$NEG4/payload")

"$PY" - "$REPORT" "$UNSHARE_RC" "$VERIFY_RC" "$READER_RC" "$SEM_OK" \
  "$BEFORE_SNAP" "$AFTER_SNAP" "$NEG1_RC" "$NEG2_RC" "$NEG3_VRC" \
  "$NEG3_RRC" "$NEG4_RC" "$BEFORE4" "$AFTER4" <<'PYEOF'
import json, sys
(args, unshare_rc, verify_rc, reader_rc, sem_ok, before, after,
 neg1, neg2, neg3v, neg3r, neg4, before4, after4) = sys.argv[1:15]
def iv(x):
    try: return int(x)
    except ValueError: return None
isolated_ok = (iv(unshare_rc) == 0 and iv(verify_rc) == 0
               and iv(reader_rc) == 0 and sem_ok == "ok"
               and before == after)
negs_ok = {"neg_missing_verify_rc1": iv(neg1) == 1,
           "neg_tamper_verify_rc1": iv(neg2) == 1,
           "neg_i02_verifier0_reader1": (iv(neg3v) == 0
                                         and iv(neg3r) == 1),
           "neg_report_target_rc2_zero_writes": (
               iv(neg4) == 2 and before4 == after4)}
doc = {"schema": "c3-irac-cold-read-v3",
       "isolated": {"unshare_rc": iv(unshare_rc),
                    "verify_rc": iv(verify_rc),
                    "reader_rc": iv(reader_rc),
                    "semantic_receipt_ok": sem_ok == "ok",
                    "payload_snapshot_identical": before == after,
                    "ok": isolated_ok},
       "negatives": {"neg1_missing": iv(neg1),
                     "neg2_tamper": iv(neg2),
                     "neg3_i02": {"verifier": iv(neg3v),
                                  "reader": iv(neg3r)},
                     "neg4_report": {"rc": iv(neg4),
                                     "payload_unchanged":
                                         before4 == after4},
                     "ok": negs_ok},
       "ok": bool(isolated_ok and all(negs_ok.values()))}
open(args, "w", encoding="utf-8").write(
    json.dumps(doc, ensure_ascii=False, indent=1))
print("cold_read_ok=" + str(doc["ok"]).lower())
sys.exit(0 if doc["ok"] else 1)
PYEOF
exit $?
