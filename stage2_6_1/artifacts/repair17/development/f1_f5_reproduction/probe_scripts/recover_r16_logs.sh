#!/usr/bin/env bash
# R17 WP0 §4.3:R16 原始链日志只读找回(historical_recovered)。
# 逐文件与 R16 原 manifest 的 sha256/bytes 比对;一致才复制;
# 不一致或缺失则记录,不伪造。只读源,不改 R16 任何文件。
set -euo pipefail
SRC="$HOME/projects/crypto_rl/artifacts/route_c_stage2_6_1_repair16_chain_logs"
MANIFEST="/mnt/e/trading/freqai-rl-audit/.r17_wp0_inputs/r16_formal_log_manifest.jsonl"
DST="/mnt/e/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/historical_recovered/r16_chain_logs"
mkdir -p "$DST"
python3 - "$MANIFEST" "$SRC" "$DST" <<'PY'
import hashlib, json, shutil, sys
from pathlib import Path

manifest, src, dst = (Path(a) for a in sys.argv[1:4])
report = []
for line in open(manifest):
    if not line.strip():
        continue
    e = json.loads(line)
    step = e["step"]
    for kind in ("stdout", "stderr"):
        p = Path(e[f"{kind}_path"])
        want_sha = e[f"{kind}_sha256"]
        want_bytes = e[f"{kind}_bytes"]
        name = p.name
        f = src / name
        row = {"step": step, "kind": kind, "manifest_path": str(p),
               "manifest_sha256": want_sha,
               "manifest_bytes": want_bytes}
        if not f.exists():
            row.update(status="missing_on_executor",
                       note="执行机上不存在;如实记录,不伪造")
        else:
            raw = f.read_bytes()
            got = hashlib.sha256(raw).hexdigest()
            if got == want_sha and len(raw) == want_bytes:
                out = dst / name
                out.write_bytes(raw)
                row.update(status="recovered", copied_to=str(out),
                           recovered_sha256=got, recovered_bytes=len(raw))
            else:
                row.update(status="hash_mismatch",
                           found_sha256=got, found_bytes=len(raw),
                           note="与 R16 manifest 不一致;不复制")
        report.append(row)
entries2 = [json.loads(l) for l in open(manifest) if l.strip()]
known = set()
for e in entries2:
    for k in ("stdout", "stderr"):
        known.add(Path(e[k + "_path"]).name)
extra = sorted(p.name for p in src.iterdir()
               if p.is_file() and p.name not in known)
json.dump({"format": "r17-historical-recovered-r16-chain-logs-v1",
           "source": str(src), "note": "迟交原始证据;未在 R16 Commit B "
           "中提交;按 R16 原 manifest sha256/bytes 校验后只读复制",
           "files": report,
           "executor_files_not_in_manifest": extra},
          open(dst.parent / "r16_chain_logs_recovery_report.json", "w"),
          indent=1, ensure_ascii=False)
for r in report:
    print(r["step"], r["kind"], r["status"])
print("extra(not in manifest):", extra)
PY
