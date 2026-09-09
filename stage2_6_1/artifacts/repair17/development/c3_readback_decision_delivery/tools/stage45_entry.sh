#!/usr/bin/env bash
# 冷读工作根证据归档 + 阶段五受监护全量回归(E04)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DELIV="$REPO/stage2_6_1/artifacts/repair17/development/c3_readback_decision_delivery"
VER="$DELIV/verification"
RUN_NAME=c3rdd_full_20260909
WORK=/home/cryptorl/r17rdd_full

# 1) 冷读工作根证据(unshare stderr 的 FAIL 行=负例具体检出原因)
mkdir -p "$VER/cold_read/workroot_logs"
for c in coldcopy neg_missing neg_tamper neg_semantic; do
  for f in unshare_stdout.log unshare_stderr.log inner.json; do
    p="/home/cryptorl/r17rdd_cold3/$c/$f"
    [ -f "$p" ] && cp "$p" "$VER/cold_read/workroot_logs/${c}_${f}"
  done
done
echo "cold-read workroot logs archived"

# 2) 阶段五全量:复制 c3eg 排序入口到新工作根
if [ -e "$WORK" ]; then echo "FATAL: $WORK 已存在" >&2; exit 2; fi
mkdir -p "$WORK"
tr -d '\r' < "$REPO/stage2_6_1/artifacts/repair17/development/c3_evidence_generation_slice/tools/full_run_ordered.sh" \
  | sed 's|r17c3eg_dev|r17rdd_full|g' > "$WORK/full_run_ordered.sh"
mkdir -p "$DELIV/full_run"

cat > "$WORK/full_entry.sh" <<'EOS'
#!/usr/bin/env bash
# 阶段五受监护全量入口(R17 系先跑排序;c3rdd_full_20260909)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
RUN_DIR_REL="stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3rdd_full_20260909"
if [ -e "$REPO/$RUN_DIR_REL" ]; then
  echo "FATAL: run 目录已存在(一次性): $RUN_DIR_REL" >&2; exit 2
fi
export R17_RUN_DIR="$REPO/$RUN_DIR_REL"
bash ~/projects/crypto_rl/stage2_6_1_runner/r17_monitored_entry.sh pytest \
  --max-seconds 3600 -- bash /home/cryptorl/r17rdd_full/full_run_ordered.sh \
  --junitxml="$REPO/$RUN_DIR_REL/junit.xml"
rc=$?
echo "OUTER_RC=$rc"
exit $rc
EOS

bash "$WORK/full_entry.sh" > "$DELIV/full_run/entry_stdout.log" 2> "$DELIV/full_run/entry_stderr.log"
RC=$?
echo "OUTER_RC=$RC" > "$DELIV/full_run/outer_rc.txt"
echo "FULL_RC=$RC"
exit $RC
