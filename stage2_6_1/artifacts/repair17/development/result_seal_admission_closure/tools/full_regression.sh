#!/usr/bin/env bash
# R17 result-seal closure 稳定候选全量回归(受监护,串行)
set -u
SYNC="$HOME/projects/crypto_rl"
RUNNER_F="/mnt/f/trading/freqai-rl-audit/stage2_6_1/runner"
ART="/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/result_seal_admission_closure/full_regression/runs"
STAMP="$(date -u +%Y%m%dT%H%M%S)"
RUN="$ART/final_${STAMP}"
mkdir -p "$ART"   # 只建父目录;RUN 由 monitored_entry 排他创建
cd "$SYNC"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export R17_RUN_DIR="$RUN"
bash "$SYNC/stage2_6_1_runner/r17_monitored_entry.sh" pytest \
  --max-seconds 3000 -- \
  python3 -m pytest tests/route_c_stage2_6_1 -q --no-header \
  -p no:cacheprovider --junitxml="$RUN/junit.xml"
rc=$?
echo "MONITORED_RC=$rc"
echo "RUN_DIR=$RUN"
# JUnit 汇总
python3 - "$RUN/junit.xml" << 'PYEOF'
import sys, xml.etree.ElementTree as ET
try:
    root = ET.parse(sys.argv[1]).getroot()
    suites = root if root.tag == "testsuites" else [root]
    tot = fail = err = skip = 0
    for s in suites.iter("testsuite"):
        tot += int(s.get("tests", 0))
        fail += int(s.get("failures", 0))
        err += int(s.get("errors", 0))
        skip += int(s.get("skipped", 0))
    print(f"JUNIT total={tot} failures={fail} errors={err} skipped={skip}")
except Exception as exc:
    print("JUNIT_PARSE_ERR", exc)
PYEOF
echo "FULL_REGRESSION_DONE"
