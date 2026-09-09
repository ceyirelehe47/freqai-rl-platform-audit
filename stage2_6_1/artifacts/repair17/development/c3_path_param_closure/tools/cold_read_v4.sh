#!/usr/bin/env bash
# R17 c3-path-param-closure:本轮 v4 包隔离冷读(矩阵 E01/E02)。
# 用法(WSL): cold_read_v4.sh <package_dir> <work_root> <out_report_json>
# 一次性合同:work_root 须不存在。
# K 系副本篡改(digest 权威重算)在 unshare 外完成;隔离内只做只读验证。
set -uo pipefail

PKG="$1"; WORK="$2"; REPORT="$3"
PY=/usr/bin/python3
CONDA_PY="$HOME/miniforge3/envs/freqtrade-rl/bin/python"
# 注:本脚本常经 `tr -d '\r' | bash -s`(stdin)执行,$0 不可用,路径硬编码
HERE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_path_param_closure/tools
[ -d "$PKG/payload" ] || { echo "FATAL: 非 v4 包目录: $PKG" >&2; exit 2; }
[ -e "$WORK" ] && { echo "FATAL: work 已存在(一次性): $WORK" >&2; exit 2; }
mkdir -p "$WORK"
COPY="$WORK/cold_copy"
cp -r "$PKG" "$COPY"

receipts="$WORK/receipts_outer"
mkdir -p "$receipts"

# payload 快照:文件(sha256,size,mtime)与目录集合
snap_payload() {
  (cd "$1" && find . -type f | LC_ALL=C sort | while read -r f; do
     sha256sum "$f" | cut -d' ' -f1
     stat -c '%s %Y' "$f"
   done) | sha256sum | cut -d' ' -f1
}
dirs_payload() {
  (cd "$1" && find . -type d | LC_ALL=C sort) | sha256sum | cut -d' ' -f1
}

BEFORE_SNAP=$(snap_payload "$COPY/payload")
BEFORE_DIRS=$(dirs_payload "$COPY/payload")

# 隔离执行:tmpfs 遮蔽原证据根(/mnt/f/trading/freqai-rl-audit)与开发
# 代码根(/home/cryptorl/projects);副本在 /tmp(隔离范围外)。
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

run_isolated "$COPY" "$WORK/unshare_inner.log"
UNSHARE_RC=$?
VERIFY_RC=$(cat "$COPY/verify_rc" 2>/dev/null || echo missing)
READER_RC=$(cat "$COPY/reader_rc" 2>/dev/null || echo missing)
AFTER_SNAP=$(snap_payload "$COPY/payload")

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

# ---- 负例 P01:目录 symlink 后接 .. 的组合目标指向源内 recipe ----
NEGP1="$WORK/neg_p01"; cp -r "$PKG" "$NEGP1"
mkdir -p "$NEGP1/outside"
ln -s ../payload/engineering_slice "$NEGP1/outside/alias"
P1_BEFORE=$(snap_payload "$NEGP1/payload"); P1_DIRS=$(dirs_payload "$NEGP1/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP1"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report outside/alias/../engineering_slice/recipe.json \
    --protect-root payload > negp1.log 2>&1; echo $? > negp1_rc
' >/dev/null 2>&1
NEGP1_RC=$(cat "$NEGP1/negp1_rc" 2>/dev/null || echo missing)
P1_AFTER=$(snap_payload "$NEGP1/payload"); P1_DIRS_AFTER=$(dirs_payload "$NEGP1/payload")

# ---- 负例 P02:同一组合,目标为源内原先不存在的嵌套新文件 ----
NEGP2="$WORK/neg_p02"; cp -r "$PKG" "$NEGP2"
mkdir -p "$NEGP2/outside"
ln -s ../payload/engineering_slice "$NEGP2/outside/alias"
P2_BEFORE=$(snap_payload "$NEGP2/payload"); P2_DIRS=$(dirs_payload "$NEGP2/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP2"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report outside/alias/../engineering_slice/new/deep/r.json \
    --protect-root payload > negp2.log 2>&1; echo $? > negp2_rc
' >/dev/null 2>&1
NEGP2_RC=$(cat "$NEGP2/negp2_rc" 2>/dev/null || echo missing)
P2_AFTER=$(snap_payload "$NEGP2/payload"); P2_DIRS_AFTER=$(dirs_payload "$NEGP2/payload")

# ---- 负例 P04:已存在外部回执不被覆盖 ----
NEGP4="$WORK/neg_p04"; cp -r "$PKG" "$NEGP4"
mkdir -p "$NEGP4/receipts_inner"
printf '{"format":"historical","keep":true}' > "$NEGP4/receipts_inner/old.json"
P4_OLD_SHA=$(sha256sum "$NEGP4/receipts_inner/old.json" | cut -d' ' -f1)
P4_OLD_MTIME=$(stat -c '%Y' "$NEGP4/receipts_inner/old.json")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP4"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report receipts_inner/old.json \
    --protect-root payload > negp4.log 2>&1; echo $? > negp4_rc
' >/dev/null 2>&1
NEGP4_RC=$(cat "$NEGP4/negp4_rc" 2>/dev/null || echo missing)
P4_NEW_SHA=$(sha256sum "$NEGP4/receipts_inner/old.json" | cut -d' ' -f1)
P4_NEW_MTIME=$(stat -c '%Y' "$NEGP4/receipts_inner/old.json")

# ---- 负例 K01/K02:必要键删除/置 null(权威重算,字节自洽) ----
NEGK1="$WORK/neg_k01"; cp -r "$PKG" "$NEGK1"
"$CONDA_PY" "$HERE/tamper_k_params.py" drop --pkg "$NEGK1" \
  --authority-src "$HOME/projects/crypto_rl/src" \
  > "$WORK/tamper_k1.log" 2>&1 || echo "tamper_k1_failed" > "$WORK/tamper_k1.log"
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGK1"'"
  '"$PY"' payload/tools/r17_verify_delivery.py verify --root payload \
    --manifest manifest.jsonl --anchor-file anchor.json \
    --receipt-dir '"$receipts"' > negk1v.log 2>&1; echo $? > negk1_vrc
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report receipts_inner/k1.json --protect-root payload \
    > negk1r.log 2>&1; echo $? > negk1_rrc
' >/dev/null 2>&1
NEGK1_VRC=$(cat "$NEGK1/negk1_vrc" 2>/dev/null || echo missing)
NEGK1_RRC=$(cat "$NEGK1/negk1_rrc" 2>/dev/null || echo missing)

NEGK2="$WORK/neg_k02"; cp -r "$PKG" "$NEGK2"
"$CONDA_PY" "$HERE/tamper_k_params.py" null --pkg "$NEGK2" \
  --authority-src "$HOME/projects/crypto_rl/src" \
  > "$WORK/tamper_k2.log" 2>&1 || echo "tamper_k2_failed" > "$WORK/tamper_k2.log"
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGK2"'"
  '"$PY"' payload/tools/r17_verify_delivery.py verify --root payload \
    --manifest manifest.jsonl --anchor-file anchor.json \
    --receipt-dir '"$receipts"' > negk2v.log 2>&1; echo $? > negk2_vrc
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report receipts_inner/k2.json --protect-root payload \
    > negk2r.log 2>&1; echo $? > negk2_rrc
' >/dev/null 2>&1
NEGK2_VRC=$(cat "$NEGK2/negk2_vrc" 2>/dev/null || echo missing)
NEGK2_RRC=$(cat "$NEGK2/negk2_rrc" 2>/dev/null || echo missing)

"$PY" - "$REPORT" \
  "$UNSHARE_RC" "$VERIFY_RC" "$READER_RC" "$SEM_OK" \
  "$BEFORE_SNAP" "$AFTER_SNAP" \
  "$NEGP1_RC" "$P1_BEFORE" "$P1_AFTER" "$P1_DIRS" "$P1_DIRS_AFTER" \
  "$NEGP2_RC" "$P2_BEFORE" "$P2_AFTER" "$P2_DIRS" "$P2_DIRS_AFTER" \
  "$NEGP4_RC" "$P4_OLD_SHA" "$P4_NEW_SHA" "$P4_OLD_MTIME" "$P4_NEW_MTIME" \
  "$NEGK1_VRC" "$NEGK1_RRC" "$NEGK1/receipts_inner/k1.json" \
  "$NEGK2_VRC" "$NEGK2_RRC" "$NEGK2/receipts_inner/k2.json" <<'PYEOF'
import json, sys
(a, unshare_rc, verify_rc, reader_rc, sem_ok, before, after,
 p1, p1b, p1a, p1db, p1da, p2, p2b, p2a, p2db, p2da,
 p4, p4b, p4a, p4mt0, p4mt1, k1v, k1r, k1rj, k2v, k2r, k2rj) = sys.argv[1:29]
def iv(x):
    try: return int(x)
    except ValueError: return None
def receipt_checks(path):
    try:
        d = json.load(open(path, encoding="utf-8"))
        return sorted({p.get("check") for p in d.get("problems", [])})
    except Exception:
        return None
k1_checks = receipt_checks(k1rj)
k2_checks = receipt_checks(k2rj)
isolated_ok = (iv(unshare_rc) == 0 and iv(verify_rc) == 0
               and iv(reader_rc) == 0 and sem_ok == "ok"
               and before == after)
negs = {
  "neg_p01_symlink_dotdot_rc2_zero_changes": (
      iv(p1) == 2 and p1b == p1a and p1db == p1da),
  "neg_p02_new_nested_rc2_no_dir_created": (
      iv(p2) == 2 and p2b == p2a and p2db == p2da),
  "neg_p04_existing_receipt_not_clobbered": (
      iv(p4) == 2 and p4b == p4a and p4mt0 == p4mt1),
  "neg_k01_missing_key_verifier0_reader1": (
      iv(k1v) == 0 and iv(k1r) == 1 and k1_checks is not None
      and "envelope_base_params_required_keys" in k1_checks),
  "neg_k02_null_value_verifier0_reader1": (
      iv(k2v) == 0 and iv(k2r) == 1 and k2_checks is not None
      and "envelope_base_params_matches_rung" in k2_checks),
}
doc = {"schema": "c3-pp-cold-read-v4",
       "isolated": {"unshare_rc": iv(unshare_rc),
                    "verify_rc": iv(verify_rc),
                    "reader_rc": iv(reader_rc),
                    "semantic_receipt_ok": sem_ok == "ok",
                    "payload_snapshot_identical": before == after,
                    "ok": isolated_ok},
       "negatives": {"neg_p01_rc": iv(p1),
                     "neg_p02_rc": iv(p2),
                     "neg_p04_rc": iv(p4),
                     "neg_k01": {"verifier": iv(k1v), "reader": iv(k1r),
                                 "problem_checks": k1_checks},
                     "neg_k02": {"verifier": iv(k2v), "reader": iv(k2r),
                                 "problem_checks": k2_checks},
                     "ok": negs},
       "ok": bool(isolated_ok and all(negs.values()))}
open(a, "w", encoding="utf-8").write(
    json.dumps(doc, ensure_ascii=False, indent=1))
print("cold_read_ok=" + str(doc["ok"]).lower())
sys.exit(0 if doc["ok"] else 1)
PYEOF
exit $?
