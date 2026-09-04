#!/usr/bin/env bash
# R14 §十-1:全量测试证据(JUnit XML + 完整 stdout/stderr + 环境
# 身份 + collected/passed/failed/skipped + 输出 digest)。
# 精确 pytest command 与完整输出落盘,不得只保存 tail。
set -uo pipefail
cd "$HOME/projects/crypto_rl"
source activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$HOME/projects/crypto_rl/src"
EV="$HOME/projects/crypto_rl/r14_test_evidence"
LOG="$HOME/projects/crypto_rl/r14_test_evidence.log"
mkdir -p "$EV"
rm -f "$EV"/*.json "$EV"/*.xml "$EV"/*.txt 2>/dev/null || true

PYTEST_ARGS=(-q tests/route_c_stage2_6_1
             --junitxml="$EV/r14_full_tests.junit.xml")

{
  date -u +"start %Y-%m-%dT%H:%M:%SZ"
  echo "pytest command: python -m pytest ${PYTEST_ARGS[*]}"
  python -m pytest "${PYTEST_ARGS[@]}"
  RC=$?
  echo "pytest rc=$RC"
  date -u +"end %Y-%m-%dT%H:%M:%SZ"
} > "$LOG" 2>&1
RC=$(grep -o 'pytest rc=[0-9]*' "$LOG" | tail -1 | cut -d= -f2)

# 环境身份 + 汇总 + digest(机械生成)
python - "$EV" "$LOG" <<'PYEOF'
import hashlib, json, platform, sys
from pathlib import Path

ev = Path(sys.argv[1])
log = Path(sys.argv[2])
text = log.read_text(encoding="utf-8")
try:
    import numpy
    numpy_ver = numpy.__version__
except Exception:
    numpy_ver = "unavailable"
try:
    import torch
    torch_ver = torch.__version__
except Exception:
    torch_ver = "unavailable"
summary = {}
for token in ("passed", "failed", "skipped", "xfailed", "error"):
    for line in text.splitlines():
        if line.startswith("=") and token in line:
            summary["tail_line"] = line.strip()
counts = {}
import re
m = re.search(
    r"([0-9]+) passed|passed", text)
tail = text.strip().splitlines()[-1] if text.strip() else ""
counts["tail"] = tail
junit = ev / "r14_full_tests.junit.xml"
payload = {
    "format": "cur261-r14-test-evidence-v1",
    "pytest_command": "python -m pytest -q tests/route_c_stage2_6_1 "
                      "--junitxml=r14_full_tests.junit.xml",
    "environment": {
        "python": platform.python_version(),
        "numpy": numpy_ver, "torch": torch_ver,
        "platform": platform.platform(),
        "conda_env": "freqtrade-rl",
    },
    "summary_tail": tail,
    "full_log_sha256": hashlib.sha256(
        log.read_bytes()).hexdigest(),
    "junit_present": junit.is_file(),
    "junit_sha256": (hashlib.sha256(junit.read_bytes()).hexdigest()
                     if junit.is_file() else None),
}
(ev / "r14_test_evidence_summary.json").write_text(
    json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
print("test evidence summary written")
PYEOF

tail -4 "$LOG"
exit "${RC:-1}"
