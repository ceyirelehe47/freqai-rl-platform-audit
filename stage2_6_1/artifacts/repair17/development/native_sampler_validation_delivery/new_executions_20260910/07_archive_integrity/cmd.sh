#!/usr/bin/env bash
# [新执行 2026-09-10] 归档完整性核验(只读):
# A. 归档副本包/追加副本 与 原始执行位置 逐文件 sha256 一致
# B. 包内嵌 run 的遥测与包内 terminal.json 一致;内嵌 run 与仓库已跟踪 run 抽样一致
# C. cold_config 全部路径在包内(原根不可见);neg_append config 的 --root/--record 一致性记录
# D. 工具副本 sha256 与补丁包 SHA256SUMS 一致;应用补丁 sha256=2abf178b...
# E. dpos 遥测双份(runs/ 原始 vs copy_root 追加后)哈希登记
# F. r3 telemetry 三态(记录锚/HEAD blob/工作树)登记,证明其工作树增长保持不入库
set -uo pipefail
BASE=/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development
DELIV=$BASE/native_sampler_validation_delivery
NEW=$DELIV/new_executions_20260910
REPO=/mnt/f/trading/freqai-rl-audit
OUT=$NEW/07_archive_integrity/check.json

R3PATH=stage2_6_1/artifacts/repair17/development/run_supervision/runs/c3eto_full_20260909_r3/telemetry/win_samples.jsonl
git -C "$REPO" show "HEAD:$R3PATH" | sha256sum | awk '{print "r3_head_blob_sha256="$1}' > "$NEW/07_archive_integrity/r3_head_blob.sha256"
git -C "$REPO" cat-file -s "HEAD:$R3PATH" | awk '{print "r3_head_blob_bytes="$1}' >> "$NEW/07_archive_integrity/r3_head_blob.sha256"

python3 - "$OUT" <<'PYEOF'
import json, hashlib, os, sys

def sha(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()

def tree(root):
    m = {}
    for dp, _, fs in os.walk(root):
        for f in fs:
            p = os.path.join(dp, f)
            m[os.path.relpath(p, root).replace(os.sep, "/")] = sha(p)
    return m

BASE = "/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development"
DELIV = BASE + "/native_sampler_validation_delivery"
SMOKE = "/mnt/f/trading/r17_native_smoke_logs"
res = {"scope": "archive integrity checks (read-only, NEW execution 2026-09-10)"}

a = tree(DELIV + "/originals/05_copy_root_dpos_appended"); b = tree(SMOKE + "/copy_root")
res["A_copy_root_archived_equals_original"] = {"same": a == b, "files": len(a)}
a = tree(DELIV + "/originals/04_full2_pkg"); b = tree(SMOKE + "/full2_pkg")
res["A_full2_pkg_archived_equals_original"] = {"same": a == b, "files": len(a)}

pkg = DELIV + "/originals/04_full2_pkg"
rid = "r17ns_full2_20260909T174348"
tel = f"{pkg}/runs/{rid}/telemetry/win_samples.jsonl"
term = json.load(open(f"{pkg}/runs/{rid}/native_sampler/terminal.json", encoding="utf-8"))
res["B_pkg_embedded_telemetry_matches_terminal"] = {
    "bytes_ok": os.path.getsize(tel) == term["bytes"], "sha256_ok": sha(tel) == term["sha256"]}
tracked = BASE + "/run_supervision/runs/" + rid
res["B_pkg_embedded_run_equals_tracked"] = {
    rel: sha(f"{pkg}/runs/{rid}/{rel}") == sha(f"{tracked}/{rel}")
    for rel in ["run_record.json", "telemetry/win_samples.jsonl", "telemetry/guest_samples.jsonl",
                "junit.xml", "business/stdout.log", "native_sampler/terminal.json"]}

cfg = json.load(open(SMOKE + "/full2_pkg/cold_config.json", encoding="utf-8"))
vals = [v for v in cfg.values() if isinstance(v, str)]
res["C_cold_config_all_paths_inside_pkg_original_location"] = all(
    v.startswith(SMOKE + "/full2_pkg/") for v in vals)
res["C_cold_config_paths_escape_count"] = sum(
    0 if v.startswith(SMOKE + "/full2_pkg/") else 1 for v in vals)
ncfg = json.load(open(DELIV + "/originals/03_aggregate/aggregate_config_neg_append.json", encoding="utf-8"))
res["C_neg_append_config_full_run_record"] = ncfg["full_run_record"]
res["C_neg_append_record_matches_root"] = ncfg["full_run_record"] == (
    SMOKE + "/copy_root/runs/r17ns_dpos_20260909T170033/run_record.json")

exp = {"windows_smoke.ps1": "88ba9822e103f6bb91676c2241a6f1795849f85fb59e6713e0e920fcf371f6b5",
       "native_test_writer.ps1": "8ca2acddfeb065a23099f58e7403de9b836251d2af09a2992f32a1591e9e38fe",
       "audit_run_bytes.py": "9fbef693869774c92185df4898a5d1d5047c862cdf281b998fba02c982517daa"}
res["D_tools_match_pack_sha256sums"] = {
    n: sha(f"{DELIV}/originals/01_windows_smoke/tools/{n}") == h for n, h in exp.items()}
psha = sha(DELIV + "/originals/02_wsl_chains/applied_patch_r17_native_sampler_NEW.patch")
res["D_applied_patch_sha256"] = psha
res["D_applied_patch_is_2abf178b"] = psha == "2abf178b021907d21734ac2221c43fd924e9e118b95f2853029b2d89c212caca"

d_tel = BASE + "/run_supervision/runs/r17ns_dpos_20260909T170033/telemetry/win_samples.jsonl"
c_tel = DELIV + "/originals/05_copy_root_dpos_appended/runs/r17ns_dpos_20260909T170033/telemetry/win_samples.jsonl"
lines = open(c_tel, "rb").read().splitlines()
res["E_dpos_telemetry_dual"] = {
    "runs_original": {"bytes": os.path.getsize(d_tel), "sha256": sha(d_tel)},
    "copy_root_appended": {"bytes": os.path.getsize(c_tel), "sha256": sha(c_tel)},
    "copy_root_appended_line": lines[-1].decode("utf-8", "replace"),
    "original_is_strict_prefix": open(d_tel, "rb").read() == b"\n".join(lines[:-1]) + b"\n"}

head = {}
for ln in open("/mnt/f/trading/freqai-rl-audit/stage2_6_1/artifacts/repair17/development/native_sampler_validation_delivery/new_executions_20260910/07_archive_integrity/r3_head_blob.sha256"):
    k, v = ln.strip().split("=", 1); head[k] = v
r3w = BASE + "/run_supervision/runs/c3eto_full_20260909_r3/telemetry/win_samples.jsonl"
res["F_r3_telemetry_three_states"] = {
    "record_anchor": {"bytes": 264179, "sha256": "f502a49f3dc8b785c87419b84c1009e72ece754dd3131b53ea113242410db4dc"},
    "head_blob": {"bytes": int(head["r3_head_blob_bytes"]), "sha256": head["r3_head_blob_sha256"]},
    "worktree": {"bytes": os.path.getsize(r3w), "sha256": sha(r3w)},
    "note": "工作树增长系 r3 事故登记现象;本次交付不提交该文件,git 中 r3 内容保持原状"}

checks = [res["A_copy_root_archived_equals_original"]["same"],
          res["A_full2_pkg_archived_equals_original"]["same"],
          res["B_pkg_embedded_telemetry_matches_terminal"]["bytes_ok"],
          res["B_pkg_embedded_telemetry_matches_terminal"]["sha256_ok"],
          all(res["B_pkg_embedded_run_equals_tracked"].values()),
          res["C_cold_config_all_paths_inside_pkg_original_location"],
          res["C_neg_append_record_matches_root"],
          all(res["D_tools_match_pack_sha256sums"].values()),
          res["D_applied_patch_is_2abf178b"],
          res["E_dpos_telemetry_dual"]["original_is_strict_prefix"]]
res["all_ok"] = all(checks)
json.dump(res, open(sys.argv[1], "w", encoding="utf-8"), indent=1)
print("ARCHIVE_INTEGRITY_OK" if res["all_ok"] else "ARCHIVE_INTEGRITY_PROBLEM")
sys.exit(0 if res["all_ok"] else 1)
PYEOF
RC=$?
echo "ARCHIVE_INTEGRITY_RC=$RC"
exit "$RC"
