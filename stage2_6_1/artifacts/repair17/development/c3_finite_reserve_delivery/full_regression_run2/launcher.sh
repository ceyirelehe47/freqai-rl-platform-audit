#!/usr/bin/env bash
# R17 C3 有限备援：受监护全量回归 第 2 次执行（仅用于补齐 entry rc 证据）。
# 测试集合与顺序与第 1 次（r17c3fr_full_20260910T051610）完全一致：
# R17 系前置、其余在后，显式排除 test_curriculum261_r17_c3_reserve_batch.py
# （其 sys.path 探测在部署树位置无法命中实现；69 项已单独从仓库位置执行）。
# 相对第 1 次的唯一变化是 rc 落盘加固：trap EXIT/TERM/HUP + 双写外部路径，
# 避免再出现「业务 rc=0 但启动器 rc 未落盘」的证据缺口。
set -uo pipefail
OUT=/mnt/e/trading/r17_c3_fr_closure
mkdir -p "$OUT"
: > "$OUT/full2_entry.rc.txt"

finish() {
  local rc=$?
  echo "$rc" > "$OUT/full2_entry.rc.txt"
  printf '{"schema":"r17-full-regression-launcher-v2","entry_rc":%s,"finished_utc":"%s","trap":"%s"}\n' \
    "$rc" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$1" >> "$OUT/full2_launcher_evidence.jsonl"
}
trap 'finish EXIT' EXIT
trap 'finish TERM; exit 143' TERM
trap 'finish HUP; exit 129' HUP

cd /home/cryptorl/projects/crypto_rl
R=tests/route_c_stage2_6_1
R17="$(ls "$R"/test_curriculum261_r17_*.py | grep -v 'c3_reserve_batch' | sort | tr '\n' ' ')"
REST="$(ls "$R"/test_*.py | grep -v '/test_curriculum261_r17_' | sort | tr '\n' ' ')"
SUPERV=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/run_supervision
RID=r17c3fr_full2_$(date -u +%Y%m%dT%H%M%S)
RD=$SUPERV/runs/$RID
export R17_RUN_DIR="$RD"
printf '%s\n' "$RD" > "$OUT/full2_run_path.txt"
printf '{"rid":"%s","run_dir":"%s","started_utc":"%s","git_head":"%s","launcher_sha256":"%s","test_selection":"R17-first; reserve_batch ignored"}\n' \
  "$RID" "$RD" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  "$(cd /mnt/f/trading/freqai-rl-audit && git rev-parse HEAD)" \
  "$(sha256sum "${BASH_SOURCE[0]}" | cut -d' ' -f1)" > "$OUT/full2_launch.json"
# shellcheck disable=SC2086
bash /home/cryptorl/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh pytest --max-seconds 3600 -- \
  python -m pytest $R17 $REST -q --no-header \
    --ignore=$R/test_curriculum261_r17_c3_reserve_batch.py \
    --junitxml=$RD/junit.xml \
  > "$OUT/full2_entry.stdout.log" 2> "$OUT/full2_entry.stderr.log"
RC=$?
echo "$RC" > "$OUT/full2_entry.rc.txt"
echo "FULL2_RC=$RC"
exit $RC
