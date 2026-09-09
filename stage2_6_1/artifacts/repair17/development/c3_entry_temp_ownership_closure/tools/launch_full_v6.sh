#!/usr/bin/env bash
# 阶段四:受监护稳定候选全量(run=c3eto_full_20260909_r3;交接包候选)。
set -uo pipefail
REPO=/mnt/f/trading/freqai-rl-audit
DEP=/home/cryptorl/projects/crypto_rl
RUN_DIR="$REPO/stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eto_full_20260909_r3"
if [ -e "$RUN_DIR" ]; then
  echo "FATAL: run 目录已存在(一次性): $RUN_DIR" >&2
  exit 2
fi
mkdir -p /home/cryptorl/r17eto_full
cat > /home/cryptorl/r17eto_full/full_run_ordered.sh <<'EOS'
#!/usr/bin/env bash
# 稳定候选全量(R17 系先跑排序;与 c3ppc/c3rdd/c3irac full 同款)。
set -euo pipefail
source /home/cryptorl/projects/crypto_rl/activate-freqtrade.sh
cd /home/cryptorl/projects/crypto_rl
R=tests/route_c_stage2_6_1
R17="$(ls "$R"/test_curriculum261_r17_*.py | sort | tr '\n' ' ')"
REST="$(ls "$R"/test_*.py | grep -v '/test_curriculum261_r17_' | sort | tr '\n' ' ')"
# shellcheck disable=SC2086
python -m pytest $R17 $REST -q --no-header "$@"
EOS
chmod +x /home/cryptorl/r17eto_full/full_run_ordered.sh
export R17_PROJECT_ROOT="$DEP"
export R17_RUN_DIR="$RUN_DIR"
bash "$REPO/stage2_6_1/runner/r17_monitored_entry.sh" pytest \
  --max-seconds 5400 -- \
  bash /home/cryptorl/r17eto_full/full_run_ordered.sh \
  --junitxml="$RUN_DIR/junit.xml"
echo "OUTER_RC=$?"
