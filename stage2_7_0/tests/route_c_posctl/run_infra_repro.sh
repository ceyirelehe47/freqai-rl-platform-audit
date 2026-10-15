#!/usr/bin/env bash
# INFRA_REPRO_V1 离线链路可复现 runner v4(纯离线;零模型/训练/confirm)
# 用法: run_infra_repro.sh EVIDENCE_ROOT --mode synthetic|golden
#       run_infra_repro.sh EVIDENCE_ROOT synthetic|golden   (位置式同义)
#   synthetic = 仅合成 fixture 测试(干净树可用,零仓外依赖)
#   golden    = 合成 + 仓外 golden 回归(需仓外 9 件在场)
# 参数严格解析:未知模式/未知选项/多余参数 → rc97 拒绝。
# 正式运行(无任何 INFRA_REPRO_* 环境钩子)拒绝全部故障钩子(rc11);
# 故障注入仅在包装进程显式 INFRA_REPRO_ALLOW_HOOKS=1 的 TEST_SESSION
# 下生效,该会话在 run_rc/env 明 stamp,不得作为正式证据。
# 正式模式核验 JUnit 测试身份/数量与 --collect-only 精确一致(非仅零失败)。
# 唯一 run_id 目录(mkdir 拒已存在;失败保留)。OVERALL 汇总真实子退出码:
#   pytest 非零 | JUnit 不一致(8) | 扫描命中/错误(5) | 输入变化(9) |
#   golden 有效完成仅 rc0/1,其余(10) | 补充检查失败(6) | 钩子(11) |
#   参数错(97)。
set -u
set -o pipefail
set -o noclobber

usage() { echo "usage: run_infra_repro.sh EVIDENCE_ROOT --mode synthetic|golden (或位置式)" >&2; }
ROOT=""; MODE=""
case $# in
  2) ROOT=$1
     case "$2" in
       synthetic|golden) MODE=$2 ;;
       *) usage; exit 97 ;;
     esac ;;
  3) [ "$2" = "--mode" ] || { usage; exit 97; }
     ROOT=$1
     case "$3" in
       synthetic|golden) MODE=$3 ;;
       *) usage; exit 97 ;;
     esac ;;
  *) usage; exit 97 ;;
esac
PY=${PY:-/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python}
HERE=$(cd "$(dirname "$0")" && pwd)
STAGE=$(cd "$HERE/../.." && pwd)          # stage2_7_0
SRC="$STAGE/src"

G=/mnt/f/trading
GOLDEN_MANIFEST=${INFRA_REPRO_GOLDEN_MANIFEST:-$G/c1_course_offline_v1_20261015/manifest_v1.json}
GOLDEN_DEPS="$G/acceptance/PSC_P0_v1/runs/banks/train/train_bank.json \
 $G/c1_train_contrast_20261015/eval/grid_baseline.json \
 $G/c1_train_contrast_20261015/eval/grid_new.json \
 $G/c1_train_contrast_20261015/eval/raw_episodes.jsonl \
 $G/c1_scale_diag_s1_run_20261015/eval/grid_new.json \
 $G/c1_scale_diag_s1_run_20261015/eval/raw_episodes.jsonl \
 $G/c1_scale_diag_s2_run_20261015/eval/grid_new.json \
 $G/c1_scale_diag_s2_run_20261015/eval/raw_episodes.jsonl"

HOOK_VARS="INFRA_REPRO_EXTRA_TESTS INFRA_REPRO_SCAN_TARGET INFRA_REPRO_AFTER_HOOK INFRA_REPRO_GOLDEN_MANIFEST INFRA_REPRO_EXTRA_INPUTS"
PRESENT_HOOKS=""
for hv in $HOOK_VARS; do
  [ -n "${!hv:-}" ] && PRESENT_HOOKS="$PRESENT_HOOKS $hv"
done
TEST_SESSION=0
if [ -n "$PRESENT_HOOKS" ]; then
  if [ "${INFRA_REPRO_ALLOW_HOOKS:-}" = "1" ]; then
    TEST_SESSION=1                        # 仅包装进程测试会话
  else
    echo "OFFICIAL_RUN_REFUSES_HOOKS:$PRESENT_HOOKS" >&2
    exit 11
  fi
fi

RUN_ID="run_$(date -u +%Y%m%dT%H%M%SZ)_$$"
RUN="$ROOT/$RUN_ID"
mkdir "$ROOT" 2>/dev/null || :
if ! mkdir "$RUN"; then
  echo "RUN_DIR_EXISTS: $RUN — refusing (no cleanup)" >&2
  exit 96
fi
echo "RUN_ID=$RUN_ID MODE=$MODE TEST_SESSION=$TEST_SESSION" | tee "$RUN/run_rc.txt"

export PYTHONDONTWRITEBYTECODE=1
export PYTHONPYCACHEPREFIX="$RUN/pycache_iso"
export PYTHONPATH="$SRC"

sha() { sha256sum "$1" 2>/dev/null | awk '{print $1}' || echo SHA_ERR; }

# ---- 0) 环境与源码身份 ------------------------------------------
{
  echo "utc_start=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "mode=$MODE"
  echo "python=$($PY --version 2>&1) py=$PY"
  echo "stage_root=$STAGE"
  echo "git_head=$(git -C "$STAGE/.." rev-parse HEAD 2>&1)"
  for f in skill_p0/course_contract.py skill_p0/offline_skill_report.py \
           skill_p0/trusted_manifests.json skill_p0/p0spec.py \
           skill_p0/p0banks.py; do
    echo "sha[$f]=$(sha "$SRC/rl_posctl/$f")"
  done
  echo "sha[test_course_contract_offline.py]=$(sha "$HERE/test_course_contract_offline.py")"
  echo "sha[run_infra_repro.sh]=$(sha "$HERE/run_infra_repro.sh")"
  for fx in "$HERE"/fixtures_course_contract/*; do
    echo "sha[fixture:$(basename "$fx")]=$(sha "$fx")"
  done
  $PY - <<'PYEOF' 2>&1
import importlib
for name in ("pandas", "numpy"):
    try:
        m = importlib.import_module(name)
        print(f"pkg[{name}]={m.__version__}")
    except Exception as exc:
        print(f"pkg[{name}]=ERROR:{exc}")
PYEOF
} > "$RUN/env_and_sources.txt" 2>&1

# ---- 1) 无模型/无 confirm 扫描(grep -F 固定串;错误即失败) ----
SCAN_STATUS=0   # 0=clean 1=hit 2=error
{
  TGT=${INFRA_REPRO_SCAN_TARGET:-}
  [ -z "$TGT" ] && TGT="$SRC/rl_posctl/skill_p0"
  echo "scan_target=$TGT"
  for pat in 'stable_baselines' 'load_p0_model_archive' '.predict(' \
             '.learn(' 'env.step' 'banks/confirm' 'confirm_bank'; do
    for f in "$TGT"/course_contract.py "$TGT"/offline_skill_report.py; do
      [ -f "$f" ] || { echo "SCAN_ERROR: missing $f"; SCAN_STATUS=2; continue; }
      if grep -qF "$pat" "$f" 2>/dev/null; then
        echo "FORBIDDEN_HIT: $pat in $f"
        [ "$SCAN_STATUS" -lt 1 ] && SCAN_STATUS=1
      elif [ $? -eq 2 ]; then
        echo "SCAN_ERROR: grep failed on $f (pat=$pat)"
        SCAN_STATUS=2
      fi
    done
  done
  echo "scan_status=$SCAN_STATUS (0 clean/1 hit/2 error)"
} > "$RUN/no_model_scan.txt" 2>&1 || SCAN_STATUS=${SCAN_STATUS:-2}
grep -q "scan_status=2" "$RUN/no_model_scan.txt" && SCAN_STATUS=2
grep -q "scan_status=0" "$RUN/no_model_scan.txt" && [ "$SCAN_STATUS" -eq 0 ] || true

# ---- 2) 前置 SHA(源码/信任表/测试/fixture+golden 仓外件) -------
input_list() {
  for f in ${INFRA_REPRO_EXTRA_INPUTS:-}; do echo "$f"; done
  for f in "$SRC/rl_posctl/skill_p0/course_contract.py" \
           "$SRC/rl_posctl/skill_p0/offline_skill_report.py" \
           "$SRC/rl_posctl/skill_p0/trusted_manifests.json" \
           "$SRC/rl_posctl/skill_p0/p0spec.py" \
           "$SRC/rl_posctl/skill_p0/p0banks.py" \
           "$HERE/test_course_contract_offline.py" \
           "$HERE/run_infra_repro.sh" \
           "$HERE"/fixtures_course_contract/*; do
    echo "$f"
  done
  if [ "$MODE" = golden ]; then
    echo "$GOLDEN_MANIFEST"; for f in $GOLDEN_DEPS; do echo "$f"; done
  fi
}
: > "$RUN/inputs_sha_before.txt"
GOLDEN_MISSING=0
while IFS= read -r f; do
  if [ -f "$f" ] && [ -r "$f" ]; then
    echo "$(sha "$f")  $f" >> "$RUN/inputs_sha_before.txt"
  else
    echo "MISSING  $f" >> "$RUN/inputs_sha_before.txt"
    case "$f" in "$GOLDEN_MANIFEST"|/mnt/f/trading/c1_*|/mnt/f/trading/acceptance/*) GOLDEN_MISSING=1;; esac
  fi
done < <(input_list)

# ---- 3) 单次 pytest:stdout+stderr+JUnit 同时 --------------------
cd "$STAGE" || exit 98
EXTRA=""
[ -n "${INFRA_REPRO_EXTRA_TESTS:-}" ] && EXTRA="$INFRA_REPRO_EXTRA_TESTS"
$PY -m pytest tests/route_c_posctl/test_course_contract_offline.py $EXTRA \
  -p no:cacheprovider -q --junitxml="$RUN/junit.xml" \
  > "$RUN/pytest_stdout.log" 2> "$RUN/pytest_stderr.log"
PYTEST_RC=$?

# 官方模式:先 collect-only 取预期测试身份
COLLECT_FILE=""
if [ "$TEST_SESSION" -eq 0 ]; then
  COLLECT_FILE="$RUN/collect_only.txt"
  $PY -m pytest tests/route_c_posctl/test_course_contract_offline.py     -p no:cacheprovider -q --collect-only     > "$COLLECT_FILE" 2>/dev/null
fi
# JUnit 一致性:rc↔零失败 + (官方)测试身份/数量与 collect-only 精确一致
JUNIT_BAD=0
JF="$RUN/junit.xml" PRC=$PYTEST_RC TS=$TEST_SESSION \
CF="$COLLECT_FILE" $PY - <<'PYEOF' > "$RUN/junit_consistency.log" 2>&1
import os, sys, xml.etree.ElementTree as ET
jf, prc = os.environ["JF"], int(os.environ["PRC"])
ts_flag = int(os.environ["TS"]); cf = os.environ["CF"]
t = ET.parse(jf).getroot()
suite = t.findall(".//testsuite")[-1]
fe = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
got = {"%s::%s" % (tc.get("classname", ""), tc.get("name", ""))
       for tc in suite.iter("testcase")}
print(f"junit tests={len(got)} failures+errors={fe} pytest_rc={prc}")
ok = (fe == 0) == (prc == 0)
if ts_flag == 0 and ok:
    want = set()
    for ln in open(cf, encoding="utf-8", errors="replace"):
        ln = ln.strip()
        if ln.endswith("::") or "::" not in ln or ln.startswith(("=", "collected", "tests/")):
            continue
        want.add(ln.split("::", 1)[0].rsplit("/", 1)[-1]
                 + "::" + ln.split("::", 1)[1] if "::" in ln else ln)
    # collect-only 行含全程 nodeid(tests/...py::cls::test);归一到
    # junit 的 file-stem::test 形状不可靠 → 改比对数量+nodeid 后缀集合
    want_nodes = {ln for ln in open(
        cf, encoding="utf-8", errors="replace").read().splitlines()
        if "::" in ln and not ln.startswith(("=", "collected "))
        and not ln.startswith("tests/") is False}
    want_nodes = {ln for ln in open(
        cf, encoding="utf-8", errors="replace").read().splitlines()
        if "::" in ln and ln.startswith("tests/")}
    want_last = {"::".join(ln.split("::")[1:]) for ln in want_nodes}
    got_last = {"::".join(g.split("::")[1:]) if "::" in g else g
                for g in got}
    print(f"collect_only nodes={len(want_last)} junit nodes={len(got_last)}")
    if want_last != got_last:
        miss = sorted(want_last - got_last)[:3]
        extra = sorted(got_last - want_last)[:3]
        print(f"IDENTITY_MISMATCH missing={miss} extra={extra}")
        ok = False
print("junit_consistency=" + ("OK" if ok else "BAD"))
sys.exit(0 if ok else 1)
PYEOF
[ $? -ne 0 ] && JUNIT_BAD=1

# ---- 4) golden(仅 golden 模式;有效完成=rc 0|1) ------------------
GOLDEN_RC=-1
if [ "$MODE" = golden ]; then
  if [ "$GOLDEN_MISSING" -eq 0 ]; then
    $PY -m rl_posctl.skill_p0.offline_skill_report \
      --manifest "$GOLDEN_MANIFEST" --out "$RUN/golden_offline" \
      > "$RUN/golden_stdout.log" 2> "$RUN/golden_stderr.log"
    GOLDEN_RC=$?
  else
    GOLDEN_RC=4
    echo "status=GOLDEN_MISSING (explicit failure, no silent skip)" \
      > "$RUN/golden_stdout.log"
  fi
fi

# ---- 5) 补充检查(导入路径/生产拒合成候选) ----------------------
$PY - "$RUN" <<'PYEOF' > "$RUN/supplement_checks.log" 2>&1
import json, subprocess, sys, tempfile
from pathlib import Path
run = Path(sys.argv[1])
print("[import_paths]")
import rl_posctl.skill_p0.course_contract as cc
import rl_posctl.skill_p0.offline_skill_report as osr
import rl_posctl.skill_p0.p0spec as spec
import rl_posctl.skill_p0.p0banks as banks
for m in (cc, osr, spec, banks):
    print(m.__name__, "=", m.__file__)
tmp = Path(tempfile.mkdtemp())
m = {"contract_version": cc.CONTRACT_VERSION,
     "bank": {"path": __file__, "sha": "0"*64},
     "grids": [], "raws": [],
     "manifest_schema": "MANIFEST_C1_V1", "course_id": "c1"}
mp = tmp/"cand.json"; mp.write_text(json.dumps(m))
r = subprocess.run(
    [sys.executable, "-m", "rl_posctl.skill_p0.offline_skill_report",
     "--manifest", str(mp), "--out", str(tmp/"o")],
    capture_output=True, text=True)
print("[production_rejects_synthetic] rc=%d expect=3 %s"
      % (r.returncode, "OK" if r.returncode == 3 else "FAIL"))
sys.exit(0 if r.returncode == 3 else 1)
PYEOF
SUPP_RC=$?

# ---- 6) 后置 SHA(TEST-ONLY 钩子在前后之间执行)+不变性 ----------
if [ -n "${INFRA_REPRO_AFTER_HOOK:-}" ]; then
  eval "$INFRA_REPRO_AFTER_HOOK" > "$RUN/after_hook.log" 2>&1
fi
: > "$RUN/inputs_sha_after.txt"
while IFS= read -r f; do
  if [ -f "$f" ] && [ -r "$f" ]; then
    echo "$(sha "$f")  $f" >> "$RUN/inputs_sha_after.txt"
  else
    echo "MISSING  $f" >> "$RUN/inputs_sha_after.txt"
  fi
done < <(input_list)
INPUTS_CHANGED=0
cmp -s "$RUN/inputs_sha_before.txt" "$RUN/inputs_sha_after.txt" \
  && echo "INPUTS_UNCHANGED=yes" \
  || { echo "INPUTS_UNCHANGED=NO"; INPUTS_CHANGED=1; }
echo "INPUTS_CHANGED=$INPUTS_CHANGED"

# ---- 7) 汇总(真实子退出码聚合) ----------------------------------
OVERALL=0
[ "$PYTEST_RC" -ne 0 ] && OVERALL=$PYTEST_RC
[ "$JUNIT_BAD" -ne 0 ] && OVERALL=8
[ "$SCAN_STATUS" -ne 0 ] && OVERALL=5
[ "$INPUTS_CHANGED" -ne 0 ] && OVERALL=9
if [ "$MODE" = golden ]; then
  case "$GOLDEN_RC" in
    0|1) : ;;  # 有效完成(1=技能 fail=有效证据结论)
    *) OVERALL=10 ;;
  esac
fi
[ "$SUPP_RC" -ne 0 ] && OVERALL=6
{
  echo "PYTEST_RC=$PYTEST_RC"
  echo "JUNIT_BAD=$JUNIT_BAD SCAN_STATUS=$SCAN_STATUS"
  echo "GOLDEN_RC=$GOLDEN_RC(mode=$MODE)"
  echo "SUPP_RC=$SUPP_RC INPUTS_CHANGED=$INPUTS_CHANGED"
  echo "utc_end=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "OVERALL_RC=$OVERALL"
} >> "$RUN/run_rc.txt"
cat "$RUN/run_rc.txt"
exit "$OVERALL"
