set -u
for p in /mnt /home/cryptorl/projects; do
  if [ -d "$p" ]; then mount -t tmpfs none "$p" 2>/dev/null; fi
done
if [ -n "${CASE_SHADOW:-}" ]; then
  [ -e /mnt/f/trading ] && echo "SHADOW_FAIL_MNT" || echo "mnt_shadow_ok"
  [ -e /home/cryptorl/projects/crypto_rl ] && echo "SHADOW_FAIL_PRJ" || echo "projects_shadow_ok"
fi
cd "$WORK_DIR" || exit 99
PYTHONPATH="$WORK_DIR/src_isolated" python3 stage2_6_1_runner_isolated/r17_v2_c13_pipeline.py verify --root "$TARGET_ROOT"
