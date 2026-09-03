#!/usr/bin/env bash
# R13 Commit A 组装:WSL 工程 artifacts -> 发布仓库
# (实现冻结点:接口修复 + 审计 + 测试 + R13RealArtifactCliRoundTrip-v1
#  rehearsal 全部通过的工程证据)
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair13"
DST="$REPO/stage2_6_1/artifacts/repair13"

cd "$REPO"
git checkout route-c-stage2-6-1-repair13

# 1) 确定性矩阵(冻结前工程命令)
mkdir -p "$DST/determinism"
cp "$ART"/determinism/*.json "$DST/determinism/" 2>/dev/null || true

# 2) R13RealArtifactCliRoundTrip-v1(真实 CLI + 真实落盘 artifacts;
#    Commit A 前必须 PASS —— §五)
mkdir -p "$DST/real_artifact_rehearsal"
if [ -d "$ART/real_artifact_rehearsal" ]; then
  # 只拷贝摘要与审计(逐 step 的大型 corpus artifact 不进入发布树;
  # 摘要内含逐步 argv/rc/digest)
  for f in real_artifact_cli_roundtrip.json artifact_interface_audit.json; do
    [ -f "$ART/real_artifact_rehearsal/$f" ] && \
      cp "$ART/real_artifact_rehearsal/$f" "$DST/real_artifact_rehearsal/"
  done
  # 关键边界 artifact 的身份证据(锁定 plan/pack/sealed/result/smoke)
  for f in qualification_plan_r13.json qualification_plan_digest_r13.txt \
           r13_parameter_pack.json r13_parameter_pack_digest.txt \
           r13_design_plan_digest.txt sealed_final_preflight_digest.txt \
           robustness_gate.json calibration_evidence.json \
           preprocessor_bundle_calibration.json \
           preprocessor_bundle_holdout.json \
           generation_evidence_completeness.json; do
    [ -f "$ART/real_artifact_rehearsal/$f" ] && \
      cp "$ART/real_artifact_rehearsal/$f" "$DST/real_artifact_rehearsal/"
  done
fi

# 3) preplan 工程 + release rehearsal(继承的工程证据)
mkdir -p "$DST/preplan"
cp "$ART"/preplan/*.json "$DST/preplan/" 2>/dev/null || true
cp "$ART"/preplan/*.jsonl "$DST/preplan/" 2>/dev/null || true
cp "$ART"/preplan_engineering_smoke.json "$DST/" 2>/dev/null || true
cp "$ART"/preplan_full_pipeline_rehearsal.json "$DST/" 2>/dev/null || true
cp "$ART"/pre_freeze_release_rehearsal.json "$DST/" 2>/dev/null || true

# 4) 静态接口审计(独立命令产物)
cp "$ART"/artifact_interface_audit.json "$DST/" 2>/dev/null || true

# 5) raw logs 占位(工程命令输出)
mkdir -p "$DST/raw_logs"

echo "assemble_r13_a: done -> $DST"
