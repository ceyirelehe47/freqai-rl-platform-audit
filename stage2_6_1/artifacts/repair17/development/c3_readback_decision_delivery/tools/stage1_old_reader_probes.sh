#!/usr/bin/env bash
# 阶段一:只读核对与最小反例——证明旧 reader(HEAD 7977178 版)被
# R02/R03/R04/R05 反例击中(必需语义不进 verdict → 误 PASS)。
#
# 只操作副本;发布树原件零改动。输出 JSON 到 stdout 末行。
set -euo pipefail

SRC_ROOT=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
SLICE="$SRC_ROOT/c3_evidence_generation_slice/engineering_slice"
DEPLOY=~/projects/crypto_rl
OLD_READER="$DEPLOY/stage2_6_1_runner/r17_c3_engineering_slice.py"
WORKROOT=/home/cryptorl/r17rdd_dev
CASES="$WORKROOT/stage1_cases"
OUT_JSON="$WORKROOT/stage1_old_reader_probes.json"

# 0) 一次性工作根
if [ -e "$WORKROOT" ]; then
  echo "FATAL: $WORKROOT 已存在(一次性合同)" >&2; exit 2
fi
mkdir -p "$WORKROOT" "$CASES"

# 1) 部署树旧 reader 身份核验(必须与 git HEAD 7977178 工作树一致)
OLD_SHA=$(sha256sum "$OLD_READER" | cut -d' ' -f1)
GIT_SHA=$(cd /mnt/f/trading/freqai-rl-audit && git show 7977178:stage2_6_1/runner/r17_c3_engineering_slice.py | sha256sum | cut -d' ' -f1)
if [ "$OLD_SHA" != "$GIT_SHA" ]; then
  echo "FATAL: 部署树旧 reader 与 HEAD 不一致: $OLD_SHA vs $GIT_SHA" >&2
  exit 3
fi

mk_case() {  # $1=case 目录名 → 复制健康切片产物
  cp -r "$SLICE" "$CASES/$1"
  rm -f "$CASES/$1/readback_report.json"   # 副本内旧回执不作为输入
}

# 2) 健康对照 + 反例构造(全部在副本上)
mk_case health

mk_case r02_rows_reordered
python3 - "$CASES/r02_rows_reordered/slice_results.jsonl" <<'PY'
import sys, json
p = sys.argv[1]
lines = [l for l in open(p, encoding="utf-8").read().splitlines() if l.strip()]
lines[1], lines[2] = lines[2], lines[1]   # 交换 D0/p1 与 D1/p0
open(p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
PY

mk_case r03a_p52_file_deleted
rm "$CASES/r03a_p52_file_deleted/p52_negative.json"

mk_case r03b_recipe_negative_removed
python3 - "$CASES/r03b_recipe_negative_removed/recipe.json" <<'PY'
import sys, json
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d.pop("negative_control", None)
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
PY

mk_case r04_p52_tampered_accepted
python3 - "$CASES/r04_p52_tampered_accepted/p52_negative.json" <<'PY'
import sys, json, hashlib
p = sys.argv[1]
d = json.load(open(p, encoding="utf-8"))
d["accepted"] = True                      # 意外接受被伪装
d["downstream_sentinel"]["evaluator_started"] = True
d["downstream_sentinel"]["evaluator_invocations"] = 3
json.dump(d, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
# recipe/results 未引用 p52 文件哈希 → 无需同步索引
PY

mk_case r05_cross_coord_detail
python3 - "$CASES/r05_cross_coord_detail/slice_results.jsonl" <<'PY'
import sys, json, hashlib
from pathlib import Path
p = Path(sys.argv[1])
rows_dir = p.parent
lines = [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]
for row in lines:
    if row["coord"] == "D1/p0":
        # 指向 D0/p0 的正确文件与正确哈希(字节校验成立,身份错配)
        row["detail"] = "D0_p0.json"
        row["detail_sha256"] = hashlib.sha256(
            (rows_dir / "pairs" / "D0_p0.json").read_bytes()).hexdigest()
p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in lines) + "\n",
             encoding="utf-8")
PY

# 3) 旧 reader 逐 case --readback(部署树形态:激活环境)
source ~/projects/crypto_rl/activate-freqtrade.sh >/dev/null 2>&1 || true
export PYTHONPATH="$DEPLOY/src"
RESULT='{}'
for c in health r02_rows_reordered r03a_p52_file_deleted \
         r03b_recipe_negative_removed r04_p52_tampered_accepted \
         r05_cross_coord_detail; do
  set +e
  ( cd "$DEPLOY" && timeout 300 python3 "$OLD_READER" \
      --readback "$CASES/$c" ) \
      > "$WORKROOT/rc_$c.stdout" 2> "$WORKROOT/rc_$c.stderr"
  rc=$?
  set -e
  v=$(python3 -c "import json,sys;print(json.load(open(sys.argv[1])).get('readback_verdict'))" \
      "$CASES/$c/readback_report.json" 2>/dev/null || echo NO_REPORT)
  RESULT=$(python3 - "$RESULT" "$c" "$rc" "$v" <<'PY'
import json, sys
d = json.loads(sys.argv[1]); d[sys.argv[2]] = {"rc": int(sys.argv[3]), "verdict": sys.argv[4]}
print(json.dumps(d, sort_keys=True))
PY
)
done

python3 - "$RESULT" "$WORKROOT" "$CASES" "$OLD_SHA" <<'PY' > "$OUT_JSON"
import json, sys, datetime
result, workroot, cases, old_sha = sys.argv[1:5]
doc = {
  "format": "r17rdd-stage1-old-reader-probes-v1",
  "old_reader_sha256": old_sha,
  "old_reader_commit": "797717830543d11b1f674f49f07a7ef0353ea4a1",
  "source_slice": "c3_evidence_generation_slice/engineering_slice",
  "probe_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
  "cases": json.loads(result),
  "expectation": "health=PASS;五个反例若也 PASS 即旧 reader 缺陷实证(必需语义未进 verdict)",
}
print(json.dumps(doc, ensure_ascii=False, indent=1))
PY
cat "$OUT_JSON"
echo "WORKROOT=$WORKROOT"
