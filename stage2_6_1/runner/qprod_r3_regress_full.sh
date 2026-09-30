#!/usr/bin/env bash
# QProd R3 R01:当前候选完整 261/262 回归原件(R17-first collection)。
# 产出:每 suite 完整 stdout/stderr/argv/cwd/interpreter/rc/junit +
# 候选与部署绑定(source-map:候选 commit ↔ 部署树关键文件 sha256)+
# auditor/lifecycle 声明。E02 七步不是 261 回归;本件才是。
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=/home/cryptorl/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
EVD=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qprod_v1/repair_round3_notclosed/evidence/regress
mkdir -p "$EVD"
cd "$DEPLOY"
CANDIDATE=$(git -C /mnt/f/trading/freqai-rl-audit rev-parse HEAD 2>/dev/null || echo "unresolved")
{
  echo "argv: $0"
  echo "cwd: $(pwd)"
  echo "interpreter: $PY ($($PY --version 2>&1))"
  echo "candidate_commit: $CANDIDATE"
  echo "started_utc: $(date -u +%FT%TZ)"
} > "$EVD/META.txt"

# ---- source-map:候选↔部署绑定(关键改动文件 sha256 对照) ----
{
  echo "# source-map: repo blob (candidate $CANDIDATE) vs deploy tree"
  for f in \
    stage2_6_1/src/rl_curriculum/curriculum261_qprod_levela.py \
    stage2_6_1/src/rl_curriculum/curriculum261_qprod_coordinate.py \
    stage2_6_1/src/rl_curriculum/curriculum261_qprod_aggregate.py \
    stage2_6_1/src/rl_curriculum/curriculum261_r17_cue_contract.py \
    stage2_6_2/src/rl_curriculum/ppo262_qprod_export.py \
    stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r3_fixes.py \
    stage2_6_1/tests/route_c_stage2_6_1/test_curriculum261_qprod_r2_fixes.py; do
    blob=$(git -C /mnt/f/trading/freqai-rl-audit show "$CANDIDATE:$f" 2>/dev/null | sha256sum | cut -d' ' -f1)
    dep=$(sha256sum "$DEPLOY/src/rl_curriculum/$(basename "$f")" 2>/dev/null | cut -d' ' -f1)
    [ -z "$dep" ] && dep=$(sha256sum "$DEPLOY/tests/route_c_stage2_6_1/$(basename "$f")" 2>/dev/null | cut -d' ' -f1)
    if [ "$blob" = "$dep" ]; then st=MATCH; else st=MISMATCH; fi
    echo "$st $(basename "$f") repo=$blob deploy=$dep"
  done
} > "$EVD/SOURCE_MAP.txt"

run_suite() {
  local name="$1"; shift
  local junit="$1"; shift
  {
    echo "argv: $PY -m pytest $*"
    echo "cwd: $(pwd)"
    echo "interpreter: $PY"
    echo "junit: $junit"
  } > "$EVD/${name}.meta.txt"
  "$PY" -m pytest "$@" -q --junitxml="$junit" \
    > "$EVD/${name}.stdout.txt" 2> "$EVD/${name}.stderr.txt"
  local rc=$?
  echo "rc=$rc" >> "$EVD/${name}.meta.txt"
  echo "[$name] rc=$rc"
}

# 261 全量(R17-first:全部 route_c_stage2_6_1)
run_suite regress261_v10 /home/cryptorl/qprod_regress261_v10_junit.xml \
  tests/route_c_stage2_6_1
# 262 全量
run_suite regress262_v7 /home/cryptorl/qprod_regress262_v7_junit.xml \
  tests/route_c_stage2_6_2

cp /home/cryptorl/qprod_regress261_v10_junit.xml "$EVD/"
cp /home/cryptorl/qprod_regress262_v7_junit.xml "$EVD/"
{
  echo "auditor: main-agent (independent reviewer re-runs their own probes)"
  echo "lifecycle: R3 candidate C12=$CANDIDATE full 261/262 on deploy bytes"
  echo "finished_utc: $(date -u +%FT%TZ)"
} > "$EVD/COLLECTION.json"
tail -2 "$EVD/regress261_v10.stdout.txt"
tail -2 "$EVD/regress262_v7.stdout.txt"
