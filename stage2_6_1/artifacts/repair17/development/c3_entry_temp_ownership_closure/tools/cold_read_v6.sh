#!/usr/bin/env bash
# R17 c3-entry-temp-ownership-closure:交接包路线 v6 包隔离冷读(矩阵 E01)。
# 用法(WSL): cold_read_v6.sh <package_dir> <work_root> <out_report_json>
# 一次性合同:work_root 须不存在。
# K 系副本篡改(digest 权威重算)在 unshare 外完成;隔离内只做只读验证
# 与 T01 隔离内函数级夹具(系统 python,纯标准库)。
set -uo pipefail

PKG="$1"; WORK="$2"; REPORT="$3"
PY=/usr/bin/python3
CONDA_PY="$HOME/miniforge3/envs/freqtrade-rl/bin/python"
# 注:本脚本常经 `tr -d '\r' | bash -s`(stdin)执行,$0 不可用,路径硬编码
HERE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_entry_temp_ownership_closure/tools
TAMPER=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/c3_path_param_closure/tools/tamper_k_params.py
[ -d "$PKG/payload" ] || { echo "FATAL: 非 v6 包目录: $PKG" >&2; exit 2; }
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

# ---- 负例 P01(本轮矩阵):跨目录悬空末端链接,目标文件缺失 ----
NEGP1="$WORK/neg_p01"; cp -r "$PKG" "$NEGP1"
mkdir -p "$NEGP1/receipts" "$NEGP1/elsewhere"
ln -s ../elsewhere/missing.json "$NEGP1/receipts/result.json"
P1_BEFORE=$(snap_payload "$NEGP1/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP1"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report receipts/result.json \
    --protect-root payload > negp1.log 2>&1; echo $? > negp1_rc
' >/dev/null 2>&1
NEGP1_RC=$(cat "$NEGP1/negp1_rc" 2>/dev/null || echo missing)
P1_AFTER=$(snap_payload "$NEGP1/payload")
P1_MISSING_CREATED=$([ -e "$NEGP1/elsewhere/missing.json" ] && echo yes || echo no)
P1_LINK_INTACT=$([ -L "$NEGP1/receipts/result.json" ] && echo yes || echo no)

# ---- 负例 P03:普通文件祖先两形态(f/new.json 与 f/../new.json) ----
NEGP3="$WORK/neg_p03"; cp -r "$PKG" "$NEGP3"
printf 'ordinary file' > "$NEGP3/f"
P3_BEFORE=$(snap_payload "$NEGP3/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP3"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report f/new.json --protect-root payload > negp3a.log 2>&1; echo $? > negp3a_rc
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report f/../new_receipt.json --protect-root payload > negp3b.log 2>&1; echo $? > negp3b_rc
' >/dev/null 2>&1
NEGP3A_RC=$(cat "$NEGP3/negp3a_rc" 2>/dev/null || echo missing)
NEGP3B_RC=$(cat "$NEGP3/negp3b_rc" 2>/dev/null || echo missing)
P3_AFTER=$(snap_payload "$NEGP3/payload")
P3_SIBLING_CREATED=$([ -e "$NEGP3/new_receipt.json" ] && echo yes || echo no)
P3_UNDER_CREATED=$([ -e "$NEGP3/f/new.json" ] && echo yes || echo no)

# ---- 负例 T01:临时名碰撞,外部对象不删(隔离内函数级,系统 python) ----
NEGT1="$WORK/neg_t01"; cp -r "$PKG" "$NEGT1"
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGT1"'"
  '"$PY"' - <<T1EOF > negt1_result.json 2> negt1_stderr.log
import importlib.util, json, os, sys
from datetime import datetime, timezone
spec = importlib.util.spec_from_file_location(
    "eto_cold_reader", "payload/tools/r17_c3_engineering_slice.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
stamp = "20260909T120000000000"
when = datetime.strptime(stamp, "%Y%m%dT%H%M%S%f").replace(
    tzinfo=timezone.utc)
class _FixedDT:
    @staticmethod
    def now(tz):
        return when
mod.datetime = _FixedDT
os.makedirs("t1_out", exist_ok=True)
target = os.path.join("t1_out", "result.json")
tmp = os.path.join("t1_out", ".result.json.%d.%s.tmp" % (os.getpid(), stamp))
open(tmp, "w", encoding="utf-8").write("PREEXISTING_FOREIGN_TEMP")
b0 = open(tmp, "rb").read()
err = None
try:
    mod._atomic_write_receipt(mod.Path(target), {"k": "v"})
except Exception as exc:
    err = type(exc).__name__
out = {"error": err, "foreign_bytes_unchanged":
       open(tmp, "rb").read() == b0 if os.path.exists(tmp) else False,
       "foreign_exists": os.path.exists(tmp),
       "final_target_created": os.path.exists(target)}
json.dump(out, open("negt1_result.json", "w", encoding="utf-8"))
T1EOF
  echo $? > negt1_rc
' >/dev/null 2>&1
NEGT1_RC=$(cat "$NEGT1/negt1_rc" 2>/dev/null || echo missing)
T1_ERR=$( "$PY" -c "import json;d=json.load(open('$NEGT1/negt1_result.json'));print(d['error'])" 2>/dev/null || echo missing)
T1_BYTES_OK=$( "$PY" -c "import json;d=json.load(open('$NEGT1/negt1_result.json'));print('yes' if d['foreign_bytes_unchanged'] and d['foreign_exists'] else 'no')" 2>/dev/null || echo missing)
T1_TARGET_OK=$( "$PY" -c "import json;d=json.load(open('$NEGT1/negt1_result.json'));print('yes' if not d['final_target_created'] else 'no')" 2>/dev/null || echo missing)

# ---- 负例 P06(防回归):目录 symlink+.. 组合目标指向源内 recipe ----
NEGP6="$WORK/neg_p06"; cp -r "$PKG" "$NEGP6"
mkdir -p "$NEGP6/outside"
ln -s ../payload/engineering_slice "$NEGP6/outside/alias"
P6_BEFORE=$(snap_payload "$NEGP6/payload"); P6_DIRS=$(dirs_payload "$NEGP6/payload")
unshare --user --map-root-user --mount bash -c '
  mount -t tmpfs tmpfs /mnt/f/trading/freqai-rl-audit 2>/dev/null || exit 97
  mount -t tmpfs tmpfs /home/cryptorl/projects 2>/dev/null || exit 97
  cd "'"$NEGP6"'"
  '"$PY"' payload/tools/r17_c3_engineering_slice.py \
    --readback payload/engineering_slice \
    --p52-envelope payload/p52_envelope/generation_failure_envelopes_calibrate_c3_cost_D0_p52.json \
    --report outside/alias/../engineering_slice/recipe.json \
    --protect-root payload > negp6.log 2>&1; echo $? > negp6_rc
' >/dev/null 2>&1
NEGP6_RC=$(cat "$NEGP6/negp6_rc" 2>/dev/null || echo missing)
P6_AFTER=$(snap_payload "$NEGP6/payload"); P6_DIRS_AFTER=$(dirs_payload "$NEGP6/payload")

# ---- 负例 K01(防回归):必要键删除(权威重算,字节自洽) ----
NEGK1="$WORK/neg_k01"; cp -r "$PKG" "$NEGK1"
"$CONDA_PY" "$TAMPER" drop --pkg "$NEGK1" \
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

"$PY" - "$REPORT" \
  "$UNSHARE_RC" "$VERIFY_RC" "$READER_RC" "$SEM_OK" \
  "$BEFORE_SNAP" "$AFTER_SNAP" \
  "$NEGP1_RC" "$P1_BEFORE" "$P1_AFTER" "$P1_MISSING_CREATED" "$P1_LINK_INTACT" \
  "$NEGP3A_RC" "$NEGP3B_RC" "$P3_SIBLING_CREATED" "$P3_UNDER_CREATED" "$P3_BEFORE" "$P3_AFTER" \
  "$NEGT1_RC" "$T1_ERR" "$T1_BYTES_OK" "$T1_TARGET_OK" \
  "$NEGP6_RC" "$P6_BEFORE" "$P6_AFTER" "$P6_DIRS" "$P6_DIRS_AFTER" \
  "$NEGK1_VRC" "$NEGK1_RRC" "$NEGK1/receipts_inner/k1.json" <<'PYEOF'
import json, sys
(a, unshare_rc, verify_rc, reader_rc, sem_ok, before, after,
 p1, p1b, p1a, p1miss, p1link,
 p3a, p3b, p3sib, p3und, p3b_snap, p3a_snap,
 t1rc, t1err, t1bytes, t1target,
 p6, p6b, p6a, p6db, p6da,
 k1v, k1r, k1rj) = sys.argv[1:31]
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
isolated_ok = (iv(unshare_rc) == 0 and iv(verify_rc) == 0
               and iv(reader_rc) == 0 and sem_ok == "ok"
               and before == after)
negs = {
  "neg_p01_crossdir_dangling_rejected_no_target_created": (
      iv(p1) == 2 and p1b == p1a and p1miss == "no"
      and p1link == "yes"),
  "neg_p03_notdir_ancestor_both_forms_rejected": (
      iv(p3a) == 2 and iv(p3b) == 2 and p3sib == "no"
      and p3und == "no" and p3b_snap == p3a_snap),
  "neg_t01_collision_keeps_foreign_object": (
      iv(t1rc) == 0 and t1err == "ReceiptWriteError"
      and t1bytes == "yes" and t1target == "yes"),
  "neg_p06_symlink_dotdot_rejected_zero_changes": (
      iv(p6) == 2 and p6b == p6a and p6db == p6da),
  "neg_k01_missing_key_verifier0_reader1": (
      iv(k1v) == 0 and iv(k1r) == 1 and k1_checks is not None
      and "envelope_base_params_required_keys" in k1_checks),
}
doc = {"schema": "c3-eto-cold-read-v6",
       "isolated": {"unshare_rc": iv(unshare_rc),
                    "verify_rc": iv(verify_rc),
                    "reader_rc": iv(reader_rc),
                    "semantic_receipt_ok": sem_ok == "ok",
                    "payload_snapshot_identical": before == after,
                    "ok": isolated_ok},
       "negatives": {"neg_p01_rc": iv(p1),
                     "neg_p01_missing_created": p1miss,
                     "neg_p01_link_intact": p1link,
                     "neg_p03a_rc": iv(p3a), "neg_p03b_rc": iv(p3b),
                     "neg_p03_sibling_created": p3sib,
                     "neg_p03_under_created": p3und,
                     "neg_t01": {"rc": iv(t1rc), "error": t1err,
                                 "foreign_bytes_unchanged": t1bytes,
                                 "final_target_not_created": t1target},
                     "neg_p06_rc": iv(p6),
                     "neg_k01": {"verifier": iv(k1v), "reader": iv(k1r),
                                 "problem_checks": k1_checks},
                     "ok": negs},
       "ok": bool(isolated_ok and all(negs.values()))}
open(a, "w", encoding="utf-8").write(
    json.dumps(doc, ensure_ascii=False, indent=1))
print("cold_read_ok=" + str(doc["ok"]).lower())
sys.exit(0 if doc["ok"] else 1)
PYEOF
exit $?
