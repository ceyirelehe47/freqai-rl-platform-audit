#!/usr/bin/env bash
# WP0b 误触事故归档:部署面证据只读复制到发布仓库归档区。
# 原位置原字节保留;归档副本只新增,不写回;清单含 sha256/size/mtime。
set -euo pipefail
P=/home/cryptorl/projects/crypto_rl
A="$P/artifacts/route_c_stage2_6_1_repair17"
OUT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/supervision_closure/wp0_formal_incident
mkdir -p "$OUT/archive"

# 1) 复制(cp -p 保留 mtime;先拷目录树)
cp -a "$P/r17_formal_requests" "$OUT/archive/r17_formal_requests"
mkdir -p "$OUT/archive/art_route_c_stage2_6_1_repair17"
# ART 顶层单文件(不含 state 目录,单独拷)
for f in fail_path_cleanliness.json r17_bootstrap_accepted.json r17_chain_result.json \
         r17_fail_closure_summary.json r17_formal_log_manifest.jsonl r17_workflow_plan_formal.json; do
  [ -f "$A/$f" ] && cp -p "$A/$f" "$OUT/archive/art_route_c_stage2_6_1_repair17/$f"
done
cp -a "$A/state" "$OUT/archive/art_route_c_stage2_6_1_repair17/state"

# 2) 清单(逐文件 sha256+size+mtime,归档与原位对照)
( cd "$OUT/archive" && find . -type f -print0 | sort -z | xargs -0 sha256sum ) > "$OUT/archive_sha256.txt"
( cd "$P" && find r17_formal_requests -type f -print0 | sort -z | xargs -0 sha256sum ) > "$OUT/origin_req_sha256.txt"
( cd "$A" && find . -type f -print0 | sort -z | xargs -0 sha256sum ) > "$OUT/origin_art_sha256.txt"
# size+mtime
( cd "$OUT/archive" && find . -type f -printf '%s %TY-%Tm-%TdT%TH:%TM:%TS %p\n' | sort -k3 ) > "$OUT/archive_stat.txt"

# 3) 部署身份快照(boot_id 对照 journal owner_identity)
cat /proc/sys/kernel/random/boot_id > "$OUT/boot_id_now.txt"

# 4) 归档密封摘要
{
  echo "archived_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "origin_project_root=$P"
  echo "origin_art=$A"
  echo "files_archived=$(find "$OUT/archive" -type f | wc -l)"
  echo "archive_tree_sha256_top=$(sha256sum "$OUT/archive_sha256.txt" | cut -d' ' -f1)"
} > "$OUT/archive_seal.txt"

echo OK
wc -l "$OUT/archive_sha256.txt" "$OUT/origin_req_sha256.txt" "$OUT/origin_art_sha256.txt"
