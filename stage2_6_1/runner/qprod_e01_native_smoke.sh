#!/usr/bin/env bash
# QProd E01:小规模原生坐标烟测(SCOPE_AND_BUDGET §3 配额内原生执行)。
# run1 = native_smoke_run1(c01 成功;c02 因 runner 逐坐标重复消费
# 一次性许可的缺陷被拒——零叶调用,原件保留;缺陷已修复:许可消费
# 移至执行集开始一次)。本脚本 = run2:同固定输入集完整双坐标执行,
# 原生执行预算 2/2 用满;两次合计远低于 640 叶调用/128 正文/16384 MC。
# 2 坐标 × (2 blocks/corpus × 8 episodes) = 64 成功正文 episode;
# 底层候选调用(含 attempts 重试与逐位一致性重放)逐调用计入
# qprod_quota_ledger.jsonl;原始 OHLCV/hidden/trace 归档于各坐标
# raw_episodes/(零生成只读复算)。固定输入集,不换坐标/参数择优。
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=$HOME/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
RUNNER=$DEPLOY/stage2_6_1_runner
ART=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/qprod_v1/native_smoke_run2
BASE=$ART
AUTH=$ART/authority
if [ -e "$ART" ]; then
  echo "run2 目录已存在(不得覆盖既有运行): $ART"; exit 96
fi
mkdir -p "$ART"
cd "$DEPLOY"
export PYTHONPATH=src

echo "=== [1/8] authority init + level_b permit ==="
$PY "$RUNNER/qprod_eng_authority.py" init --dir "$AUTH"
CTXDIR=$BASE/qprod_level_b_qprod_b_eng_v1
ROOTS=$($PY - <<PYEOF
import importlib.util
spec = importlib.util.spec_from_file_location(
    'e', '$RUNNER/qprod_level_b_entry.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
class A:
    base_dir = '$BASE'
    authority_dir = '$AUTH'
ctx = m._context(A())
print(ctx.artifact_root, ctx.state_root, ctx.code_freeze_sha)
PYEOF
)
set -- $ROOTS
$PY "$RUNNER/qprod_eng_authority.py" issue-permit --dir "$AUTH" \
  --task-level level_b --iteration-id qprod_b_eng_v1 \
  --code-freeze-sha "$3" --artifact-root "$1" --state-root "$2" \
  --namespaces cue_qprod_v1_c01_model cue_qprod_v1_c01_validation \
               cue_qprod_v1_c02_model cue_qprod_v1_c02_validation \
  --coordinate-ids c01 c02 || exit 96

echo "=== [2/8] research plan freeze (pre-data) ==="
$PY "$RUNNER/qprod_level_b_entry.py" plan-freeze --base-dir "$BASE" \
  --authority-dir "$AUTH" --stop-mode collect_all_k || exit 96
echo "=== [3/8] coordinate audit plan locks ==="
$PY "$RUNNER/qprod_level_b_entry.py" lock-coordinates --base-dir "$BASE" \
  --authority-dir "$AUTH" || exit 96
echo "=== [4/8] consume-permit (execution set starts; one-shot) ==="
$PY "$RUNNER/qprod_level_b_entry.py" consume-permit --base-dir "$BASE" \
  --authority-dir "$AUTH" || exit 96
echo "=== [5/8] run coordinate c01 (native) ==="
$PY "$RUNNER/qprod_level_b_entry.py" run-coordinate --base-dir "$BASE" \
  --authority-dir "$AUTH" --coordinate-id c01
rc_c01=$?
echo "rc_c01=$rc_c01"
echo "=== [6/8] run coordinate c02 (native) ==="
$PY "$RUNNER/qprod_level_b_entry.py" run-coordinate --base-dir "$BASE" \
  --authority-dir "$AUTH" --coordinate-id c02
rc_c02=$?
echo "rc_c02=$rc_c02"
echo "=== [7/8] aggregate (expect: 2 < planned_k=11 -> not decided) ==="
$PY "$RUNNER/qprod_level_b_entry.py" aggregate --base-dir "$BASE" \
  --authority-dir "$AUTH"
echo "rc_agg=$?"
echo "=== [8/8] cold read (fresh aggregation reproduces) ==="
$PY "$RUNNER/qprod_level_b_entry.py" cold-read --base-dir "$BASE" \
  --authority-dir "$AUTH"
echo "rc_cold=$?"
echo "=== quota ledger ==="
cat "$CTXDIR/qprod_quota_ledger.jsonl"
echo "=== leaf call totals vs budget (both runs combined) ==="
$PY - <<PYEOF
import json
from pathlib import Path
root = Path("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts"
            "/repair17/development/qprod_v1")
rows = []
for run in ("native_smoke_run1", "native_smoke_run2"):
    p = root / run / "qprod_level_b_qprod_b_eng_v1" / \
        "qprod_quota_ledger.jsonl"
    if p.is_file():
        rows += [json.loads(x) for x in p.read_text().splitlines()
                 if x.strip()]
complete = [r for r in rows if r.get("action") == "complete"]
total = sum(r.get("leaf_calls_total", 0) for r in complete)
episodes = sum(r.get("successful_episodes", 0) for r in complete)
mc = sum(r.get("mc_events", 0) for r in complete)
print(json.dumps({
    "runs": ["native_smoke_run1", "native_smoke_run2"],
    "leaf_calls_total": total, "successful_episodes": episodes,
    "mc_events_total": mc,
    "budgets": {"leaf_calls_max": 640, "episodes_max": 128,
                "mc_max": 16384, "native_executions_max": 2}},
    ensure_ascii=False))
assert total <= 640 and episodes <= 128 and mc <= 16384, "QUOTA EXCEEDED"
print("WITHIN BUDGET")
PYEOF
exit $(( rc_c01 != 0 || rc_c02 != 0 ? 3 : 0 ))
