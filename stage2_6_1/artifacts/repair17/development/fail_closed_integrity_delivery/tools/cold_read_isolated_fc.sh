#!/usr/bin/env bash
# 隔离冷读(fail-closed-integrity-delivery 轮;复用 unified_shutdown_
# cold_read/tools/cold_read_isolated.sh 的机制,按本轮实际源路径适配)。
#
# 与原版的差异(§7.3:按实际路径做最小隔离适配,不机械只遮 /mnt):
#   本轮原件有两处源根——发行证据根 /mnt/f/trading/freqai-rl-audit
#   (run_supervision 原件/verifier 发行副本)与开发项目根
#   /home/cryptorl/projects/crypto_rl(执行树/开发 verifier 代码)。
#   namespace 内同时以 tmpfs 覆盖 /mnt 与 /home/cryptorl/projects,
#   两个原根对验证进程都不可访问;只保留新副本根、系统解释器与
#   标准库。验证证据不依赖课程生成模块(只读 r17_verify_delivery)。
# 只读性:验证前后对 payload 全树 (mtime,size,sha256) 快照必须不变。
#
# 用法: bash cold_read_isolated_fc.sh <copy_root> <receipt_dir>
# 返回: 0=隔离冷读通过;1=验证失败;2=环境/用法错误
set -uo pipefail
COPY_ROOT="$(readlink -f "${1:?用法: cold_read_isolated_fc.sh <copy_root> <receipt_dir>}")"
RECEIPTS="$(readlink -f "${2:?缺少 receipt_dir}")"
mkdir -p "$RECEIPTS"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RECEIPT="$RECEIPTS/cold_read_${STAMP}.json"

py_tree() {  # payload 只读性快照
  python3 - "$1" <<'PYEOF'
import hashlib, json, os, sys
root = sys.argv[1]
out = {}
for dirpath, _dirs, files in os.walk(root):
    for f in sorted(files):
        p = os.path.join(dirpath, f)
        st = os.stat(p)
        h = hashlib.sha256()
        with open(p, "rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out[os.path.relpath(p, root)] = [st.st_mtime_ns, st.st_size,
                                         h.hexdigest()]
print(json.dumps(out, sort_keys=True))
PYEOF
}

BEFORE="$(py_tree "$COPY_ROOT/payload")" || { echo "snapshot_before_failed"; exit 2; }

# 隔离验证(namespace 内执行;回执先落副本内,结束后外层搬运)
# shellcheck disable=SC2016
INNER='
set -u
# 原根不可访问(前置事实,逐根核验):
#   1) tmpfs 覆盖 /mnt(发行证据根 /mnt/f/trading/freqai-rl-audit)
#   2) tmpfs 覆盖 /home/cryptorl/projects(开发项目根/执行树)
mount -t tmpfs tmpfs /mnt || exit 9
mount -t tmpfs tmpfs /home/cryptorl/projects || exit 9
mnt_visible="yes"; [ -d /mnt/f/trading/freqai-rl-audit ] || mnt_visible="no"
proj_visible="yes"; [ -d /home/cryptorl/projects/crypto_rl ] || proj_visible="no"
argv_dump=$(python3 -c "import sys; print(sys.executable); print(sys.argv)" 2>&1 | tr "\n" " " || true)
cd "$1" || exit 9
mkdir -p receipts_inner
record_rel=$(python3 -c "import json;print(json.load(open(\"metadata/copy_manifest.json\"))[\"record_rel\"])" 2>/dev/null) || exit 9
ver=$(ls verifier/*.py | head -1)
man=$(ls metadata/*.jsonl | head -1)
anc=$(ls metadata/*.anchor.json metadata/*anchor*.json 2>/dev/null | head -1)
[ -n "$record_rel" ] && [ -n "$ver" ] && [ -n "$man" ] && [ -n "$anc" ] || exit 9
python3 "$ver" verify --root payload --manifest "$man" \
  --anchor-file "$anc" --run-record "payload/$record_rel" \
  --receipt-dir receipts_inner
rc=$?
printf "%s" "{\"original_root_visible\":{\"mnt_f\":\"$mnt_visible\",\"projects\":\"$proj_visible\"},\"verify_rc\":$rc,\"cwd\":\"$PWD\",\"argv\":\"$argv_dump\"}" > inner_isolation.json
exit $rc
'
unshare --user --map-root-user --mount bash -c "$INNER" _ "$COPY_ROOT" ""
VRC=$?
# 搬运隔离事实+verify 回执到外层 receipts;副本还原纯净
mv "$COPY_ROOT/inner_isolation.json" "$RECEIPTS/inner_${STAMP}.json" 2>/dev/null || true
if [ -d "$COPY_ROOT/receipts_inner" ]; then
  mv "$COPY_ROOT/receipts_inner" "$RECEIPTS/verify_${STAMP}" 2>/dev/null || true
fi
AFTER="$(py_tree "$COPY_ROOT/payload")" || { echo "snapshot_after_failed"; exit 2; }
READONLY_OK="yes"
[ "$BEFORE" = "$AFTER" ] || READONLY_OK="no"

python3 - "$RECEIPT" "$VRC" "$READONLY_OK" "$COPY_ROOT" "$RECEIPTS/inner_${STAMP}.json" <<'PYEOF'
import json, sys
rp, vrc, ro, copy_root, inner = sys.argv[1:6]
inner_data = {}
try:
    inner_data = json.loads(open(inner, encoding="utf-8").read())
except Exception:
    pass
vis = inner_data.get("original_root_visible") or {}
rec = {
    "schema": "r17-cold-read-isolated-fc-v1",
    "copy_root": copy_root,
    "verify_rc": int(vrc),
    "payload_readonly_unchanged": ro == "yes",
    "isolation": {
        "method": "unshare --user --map-root-user --mount + tmpfs "
                  "over /mnt AND /home/cryptorl/projects",
        "original_root_visible": vis,
        "verifier_cwd": inner_data.get("cwd"),
        "verifier_argv_note": inner_data.get("argv"),
    },
    "rc": (0 if (int(vrc) == 0 and ro == "yes"
                 and vis.get("mnt_f") == "no"
                 and vis.get("projects") == "no")
           else 1),
}
open(rp, "w", encoding="utf-8").write(
    json.dumps(rec, ensure_ascii=False, indent=1))
print(json.dumps(rec, ensure_ascii=False))
PYEOF
# 回执 rc:双原根不可访问+verify rc0+只读不变 才是 0
python3 -c "import json,sys;sys.exit(json.load(open('$RECEIPT',encoding='utf-8'))['rc'])"
