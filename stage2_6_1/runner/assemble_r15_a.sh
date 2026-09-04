#!/usr/bin/env bash
# R15 Commit A 组装:WSL 工程 artifacts -> 发布仓库
# (实现冻结点:单一权威 workflow + 传递性 binding lineage +
#  阶段精确 fail closure + provenance v2 + 测试证据 +
#  R15RealArtifactCliRoundTrip-v1 rehearsal 全部通过的工程证据)
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair15"
DST="$REPO/stage2_6_1/artifacts/repair15"

cd "$REPO"
git checkout route-c-stage2-6-1-repair15 2>/dev/null || true

# 1) 确定性矩阵(冻结前工程命令)
mkdir -p "$DST/determinism"
cp "$ART"/determinism/*.json "$DST/determinism/" 2>/dev/null || true

# 2) GateTopologyReconciliation-v2(§五/§六:任何正式数据前锁定)
for f in gate_topology_reconciliation.json \
         gate_topology_reconciliation_digest.txt; do
  [ -f "$ART/$f" ] && cp "$ART/$f" "$DST/" || true
done

# 3) 测试证据(§十-1:JUnit XML + 完整 stdout/stderr + 环境身份 + digest)
mkdir -p "$DST/test_evidence"
for f in "$SRC"/r15_test_evidence/*; do
  [ -f "$f" ] && cp "$f" "$DST/test_evidence/" || true
done

# 4) R15RealArtifactCliRoundTrip-v1(同一权威 workflow executor;
#    含 workflow plan/chain 记录/full-cold reader/report reader/
#    fail-closure writer 边界)
mkdir -p "$DST/real_artifact_rehearsal"
if [ -d "$ART/real_artifact_rehearsal" ]; then
  for f in real_artifact_cli_roundtrip.json \
           r15_workflow_plan_rehearsal.json \
           r15_workflow_validation.json \
           r15_chain_result.json \
           r15_formal_log_manifest.jsonl \
           r15_formal_log_verification.json \
           artifact_interface_audit.json; do
    [ -f "$ART/real_artifact_rehearsal/$f" ] && \
      cp "$ART/real_artifact_rehearsal/$f" "$DST/real_artifact_rehearsal/"
  done
  for f in qualification_plan_r15.json qualification_plan_digest_r15.txt \
           r15_parameter_pack.json r15_parameter_pack_digest.txt \
           r15_design_plan_digest.txt sealed_final_preflight_digest.txt \
           robustness_gate.json calibration_evidence.json \
           preprocessor_bundle_calibration.json \
           preprocessor_bundle_holdout.json \
           generation_evidence_completeness.json \
           full_cold_reader_check.json rt_report_values.json \
           r15_fail_closure_summary.json; do
    [ -f "$ART/real_artifact_rehearsal/$f" ] && \
      cp "$ART/real_artifact_rehearsal/$f" "$DST/real_artifact_rehearsal/"
  done
fi

# 5) preplan 工程 + 静态接口审计(继承的工程证据)
mkdir -p "$DST/preplan"
cp "$ART"/preplan/*.json "$DST/preplan/" 2>/dev/null || true
cp "$ART"/preplan/*.jsonl "$DST/preplan/" 2>/dev/null || true
cp "$ART"/preplan_engineering_smoke.json "$DST/" 2>/dev/null || true
cp "$ART"/preplan_full_pipeline_rehearsal.json "$DST/" 2>/dev/null || true
cp "$ART"/pre_freeze_release_rehearsal.json "$DST/" 2>/dev/null || true
cp "$ART"/artifact_interface_audit.json "$DST/" 2>/dev/null || true

# 6) rehearsal/determinism raw logs(工程命令输出)
mkdir -p "$DST/raw_logs"
for f in "$SRC"/r15_rt_rehearsal.log "$SRC"/r15_determinism.log \
         "$SRC"/r15_test_evidence.log; do
  [ -f "$f" ] && cp "$f" "$DST/raw_logs/" || true
done

echo "assemble_r15_a: done -> $DST"
