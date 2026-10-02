#!/usr/bin/env bash
# QProd E02/E03:Level A 工程排练 + 导出 + 新进程消费冷读(零原生
# 生成/零 fit/零 optimizer;bank=标注夹具替身)。两套预定 pack
# (v1_r2_reference / v2_perturbed)各走一遍,变更在真实参数边界可见。
set -uo pipefail
export PYTHONDONTWRITEBYTECODE=1
DEPLOY=$HOME/projects/crypto_rl
PY=/home/cryptorl/miniforge3/envs/freqtrade-rl/bin/python
RUNNER=$DEPLOY/stage2_6_1_runner
ART=/mnt/f/trading/tmp_r12/reviewer/e02_run
rm -rf "$ART"
mkdir -p "$ART"
cd "$DEPLOY"
export PYTHONPATH=src

for VARIANT in v1_r2_reference v2_perturbed; do
  echo "=== [$VARIANT] authority + level_a permit ==="
  BASE=$ART/$VARIANT
  AUTH=$ART/authority_$VARIANT
  $PY "$RUNNER/qprod_eng_authority.py" init --dir "$AUTH"
  ROOTS=$($PY - <<PYEOF
import importlib.util
spec = importlib.util.spec_from_file_location(
    'e', '$RUNNER/qprod_level_a_entry.py')
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
    --task-level level_a --iteration-id qprod_a_eng_v1 \
    --code-freeze-sha "$3" --artifact-root "$1" --state-root "$2" \
    --namespaces none || exit 96
  echo "=== [$VARIANT] rehearse (17-step ledger; fixtures marked) ==="
  $PY "$RUNNER/qprod_level_a_entry.py" rehearse --base-dir "$BASE" \
    --authority-dir "$AUTH" --pack-variant "$VARIANT"
  rc=$?
  echo "rc_rehearse=$rc"; [ $rc -ne 0 ] && exit $rc
  echo "=== [$VARIANT] export (verify originals -> six-file bundle) ==="
  $PY "$RUNNER/qprod_level_a_entry.py" export --base-dir "$BASE" \
    --authority-dir "$AUTH" --pack-variant "$VARIANT"
  rc=$?
  echo "rc_export=$rc"; [ $rc -ne 0 ] && exit $rc
  echo "=== [$VARIANT] authority consumption auth (isolated issuer) ==="
  RECEIPT=$BASE/qprod_level_a_qprod_a_eng_v1/delivery_$VARIANT/qprod_export_receipt.json
  $PY "$RUNNER/qprod_eng_authority.py" issue-consumption-auth \
    --dir "$AUTH" --receipt "$RECEIPT" || exit 96
  echo "=== [$VARIANT] consumption cold read (new process; formal reject first) ==="
  AUTHF=$AUTH/qprod_consumption_auth_delivery_$VARIANT.json
  $PY - <<PYEOF
from rl_curriculum.ppo262_qualified_input import (
    QualifiedInputError, load_qualified_input)
try:
    load_qualified_input(
        "$BASE/qprod_level_a_qprod_a_eng_v1/delivery_$VARIANT",
        authorization_path="$AUTHF", expected_scope="formal")
    raise SystemExit("formal scope unexpectedly loaded")
except QualifiedInputError:
    print("formal-scope rejection OK (engineering input cannot get formal permission)")
PYEOF
  $PY "$RUNNER/qprod_level_a_entry.py" consumption-cold-read \
    --base-dir "$BASE" --authority-dir "$AUTH" \
    --pack-variant "$VARIANT" --auth "$AUTHF"
  rc=$?
  echo "rc_cold_read=$rc"; [ $rc -ne 0 ] && exit $rc
done
echo "ALL E02/E03 PASS (two preset packs)"
