#!/usr/bin/env bash
# INFRA_REPRO_V1 离线链路可复现 runner(纯离线;零模型/训练/confirm)
# 用法: bash run_infra_repro.sh <EVIDENCE_ROOT>
# 唯一 run_id 目录(O_EXCL 语义:mkdir 无 -p,存在即拒);失败保留。
set -u
set -o pipefail
set -o noclobber

ROOT=${1:?usage: run_infra_repro.sh EVIDENCE_ROOT}
PY=${PY:-/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python}
HERE=$(cd "$(dirname "$0")" && pwd)
STAGE=$(cd "$HERE/../.." && pwd)          # stage2_7_0
SRC="$STAGE/src"

G=/mnt/f/trading
GOLDEN_MANIFEST="$G/c1_course_offline_v1_20261015/manifest_v1.json"
GOLDEN_DEPS="$G/acceptance/PSC_P0_v1/runs/banks/train/train_bank.json \
 $G/c1_train_contrast_20261015/eval/grid_baseline.json \
 $G/c1_train_contrast_20261015/eval/grid_new.json \
 $G/c1_train_contrast_20261015/eval/raw_episodes.jsonl \
 $G/c1_scale_diag_s1_run_20261015/eval/grid_new.json \
 $G/c1_scale_diag_s1_run_20261015/eval/raw_episodes.jsonl \
 $G/c1_scale_diag_s2_run_20261015/eval/grid_new.json \
 $G/c1_scale_diag_s2_run_20261015/eval/raw_episodes.jsonl"

RUN_ID="run_$(date -u +%Y%m%dT%H%M%SZ)_$$"
RUN="$ROOT/$RUN_ID"
mkdir "$ROOT" 2>/dev/null || :
if ! mkdir "$RUN"; then
  echo "RUN_DIR_EXISTS: $RUN — refusing (no cleanup)" >&2
  exit 96
fi
echo "RUN_ID=$RUN_ID" | tee "$RUN/run_rc.txt"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$RUN/pycache_iso"
export PYTHONPATH="$SRC"

sha() { sha256sum "$1" | awk '{print $1}'; }

# ---- 0) 环境与源码身份 ------------------------------------------
{
  echo "utc_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "python=$($PY --version 2>&1)"
  for m in course_contract offline_skill_report; do
    echo "sha[skill_p0/$m.py]=$(sha "$SRC/rl_posctl/skill_p0/$m.py")"
  done
  echo "sha[trusted_manifests.json]=$(sha "$SRC/rl_posctl/skill_p0/trusted_manifests.json")"
  echo "sha[p0spec.py]=$(sha "$SRC/rl_posctl/skill_p0/p0spec.py")"
  echo "sha[p0banks.py]=$(sha "$SRC/rl_posctl/skill_p0/p0banks.py")"
  echo "sha[test_course_contract_offline.py]=$(sha "$HERE/test_course_contract_offline.py")"
  echo "sha[run_infra_repro.sh]=$(sha "$HERE/run_infra_repro.sh")"
  echo "git_head=$(git -C "$STAGE/.." rev-parse HEAD 2>&1)"
  $PY - <<'PYEOF' 2>&1
import importlib, sys
sys.path.insert(0, ".")
for name in ("pandas", "numpy"):
    try:
        m = importlib.import_module(name)
        print(f"pkg[{name}]={m.__version__}")
    except Exception as exc:
        print(f"pkg[{name}]=ERROR:{exc}")
PYEOF
} > "$RUN/env_and_sources.txt" 2>&1

# ---- 1) 无模型/无 confirm 静态扫描 ------------------------------
SCAN_RC=0
{
  for f in course_contract offline_skill_report; do
    echo "== $f.py =="
    for pat in 'stable_baselines' 'load_p0_model_archive' '\.predict(' \
               '\.learn(' 'env\.step' 'PSC_P0_v1/runs/banks/confirm' \
               'confirm_bank'; do
      if grep -nE "$pat" "$SRC/rl_posctl/skill_p0/$f.py"; then
        echo "FORBIDDEN_HIT: $pat"; SCAN_RC=1
      fi
    done
  done
  echo "scan_rc=$SCAN_RC"
} > "$RUN/no_model_scan.txt" 2>&1 || true

# ---- 2) 外部 golden 输入前 SHA ----------------------------------
: > "$RUN/inputs_sha_before.txt"
GOLDEN_MISSING=0
for f in $GOLDEN_MANIFEST $GOLDEN_DEPS; do
  if [ -f "$f" ]; then
    echo "$(sha "$f")  $f" >> "$RUN/inputs_sha_before.txt"
  else
    echo "MISSING  $f" >> "$RUN/inputs_sha_before.txt"
    GOLDEN_MISSING=1
  fi
done

# ---- 3) 纯离线测试入口(合成 fixture;无仓外依赖) -----------------
cd "$STAGE" || exit 98
$PY -m pytest tests/route_c_posctl/test_course_contract_offline.py \
  -p no:cacheprovider -q \
  > "$RUN/pytest_stdout.log" 2> "$RUN/pytest_stderr.log"
PYTEST_RC=$?
echo "PYTEST_RC=$PYTEST_RC" >> "$RUN/run_rc.txt"
cp "$STAGE"/tests/route_c_posctl/.junit* "$RUN/" 2>/dev/null || :
# (junit 由下一命令显式产出)
$PY -m pytest tests/route_c_posctl/test_course_contract_offline.py \
  -p no:cacheprovider -q --junitxml="$RUN/junit.xml" \
  > "$RUN/pytest_junit_stdout.log" 2>&1
PYTEST_JUNIT_RC=$?
echo "PYTEST_JUNIT_RC=$PYTEST_JUNIT_RC" >> "$RUN/run_rc.txt"

# ---- 4) golden 真实离线回归(仓外件;缺失=明确失败不静默) -------
if [ "$GOLDEN_MISSING" -eq 0 ]; then
  GOLDEN_OUT="$RUN/golden_offline"
  $PY -m rl_posctl.skill_p0.offline_skill_report \
    --manifest "$GOLDEN_MANIFEST" --out "$GOLDEN_OUT" \
    > "$RUN/golden_stdout.log" 2> "$RUN/golden_stderr.log"
  GOLDEN_RC=$?
else
  GOLDEN_RC=4  # GOLDEN_MISSING
  printf '%s\n' "status=GOLDEN_MISSING" \
    "external inputs missing — see inputs_sha_before.txt" \
    > "$RUN/golden_stdout.log"
fi
echo "GOLDEN_RC=$GOLDEN_RC" >> "$RUN/run_rc.txt"

# ---- 5) 输入后 SHA(不变性) --------------------------------------
: > "$RUN/inputs_sha_after.txt"
for f in $GOLDEN_MANIFEST $GOLDEN_DEPS; do
  if [ -f "$f" ]; then
    echo "$(sha "$f")  $f" >> "$RUN/inputs_sha_after.txt"
  else
    echo "MISSING  $f" >> "$RUN/inputs_sha_after.txt"
  fi
done
if cmp -s "$RUN/inputs_sha_before.txt" "$RUN/inputs_sha_after.txt"; then
  echo "INPUTS_UNCHANGED=yes" >> "$RUN/run_rc.txt"
else
  echo "INPUTS_UNCHANGED=NO" >> "$RUN/run_rc.txt"
fi

# ---- 6) 汇总 -----------------------------------------------------
OVERALL=$PYTEST_RC
[ "$SCAN_RC" -ne 0 ] && OVERALL=5
[ "$GOLDEN_RC" -eq 3 ] && OVERALL=3
[ "$GOLDEN_RC" -eq 4 ] && OVERALL=4
echo "utc_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$RUN/run_rc.txt"
echo "OVERALL_RC=$OVERALL" >> "$RUN/run_rc.txt"
cat "$RUN/run_rc.txt"
exit "$OVERALL"
