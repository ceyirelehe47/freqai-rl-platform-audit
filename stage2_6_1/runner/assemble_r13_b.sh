#!/usr/bin/env bash
# R13 Commit B 组装:正式执行 artifacts -> 发布仓库
# 文件清单与 R13 正式 producer 的实际产物名逐一对齐(修复 R12 组装
# 脚本中约 12 个无 producer 文件名的静默缺件问题)。
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair13"
DST="$REPO/stage2_6_1/artifacts/repair13"

cd "$REPO"
git checkout route-c-stage2-6-1-repair13 2>/dev/null || true

mkdir -p "$DST/raw_logs"
for f in \
  baseline_ancestry.json historical_evidence_binding.json \
  historical_evidence_binding_digest.txt historical_binding.json \
  r11_abort_binding.json r11_cue_failure_binding.json \
  r12_abort_binding.json r12_iteration_failure_binding.json \
  r8_abort_binding.json r9_abort_binding.json r10_abort_binding.json \
  dependency_resolution.json \
  delegation_signature_audit.json delegation_ast_checks.json \
  calibration_call_contract.json \
  bundle_routing_contract.json bundle_routing_contract_digest.txt \
  official_entrypoint_validation.json production_preprocessing_audit.json \
  preprocessing_v2_contract.json preprocessing_v2_contract_digest.txt \
  production_equivalence.json seed_namespace_integrity_pre_design.json \
  generation_determinism_binding.json route_c_integrity.json \
  r13_code_freeze.json \
  cue_semantic_contract.json cue_semantic_contract_digest.txt \
  cue_audit_plan.json cue_audit_plan_digest.txt \
  cue_contract_audit.json once_vs_attempts_audit.json \
  cue_k_distribution.json cue_event_trace.jsonl \
  cue_global_k_result.json cue_global_k_null_summary.json \
  cue_global_k_cell_diagnostics.json \
  tail_mirror_bound_integrity.json tail_mirror_validation.json \
  noise_replay_validation.json \
  preplan_engineering_smoke.json preplan_full_pipeline_rehearsal.json \
  pre_freeze_release_rehearsal.json \
  full_supervised_release_rehearsal.json \
  full_supervised_rehearsal_main.json full_supervised_rehearsal_holdout.json \
  plan_roundtrip_validation.json \
  r13_design_plan.json r13_design_plan_digest.txt \
  semantic_design_main.json semantic_design_validation.json \
  r13_candidate_results.json r13_power_analysis.json \
  r13_sample_size_selection.json r13_design_decision.json \
  c2_independent_marginal_design.json \
  r13_parameter_pack.json r13_parameter_pack_digest.txt \
  preprocessing_v2_requalification.json \
  observation_space_validation.json bundle_routing_validation.json \
  supervised_learnability_main.json supervised_learnability_holdout.json \
  supervised_label_alignment_main.json supervised_label_alignment_holdout.json \
  supervised_dataset_identity_main.json supervised_dataset_identity_holdout.json \
  pair_evidence_table_main.json pair_evidence_table_holdout.json \
  c2_block_evidence_table_main.json c2_block_evidence_table_holdout.json \
  cue_semantic_calibration.json cue_semantic_calibration.jsonl \
  cue_semantic_holdout.json cue_semantic_holdout.jsonl \
  c2_independent_marginal_main.json c2_independent_marginal_holdout.json \
  c2_density_diagnostics.json \
  generation_evidence_completeness.json generation_invocation_ledger.jsonl \
  fit_manifest_calibration.json fit_manifest_holdout.json \
  preprocessor_bundle_calibration.json preprocessor_bundle_holdout.json \
  fit_eval_isolation.json \
  conditioning_profile.json generator_stress.json \
  frozen_parameter_identity.json \
  robustness_gate.json calibration_evidence.json \
  prelock_static_preflight.json \
  qualification_plan_r13.json qualification_plan_digest_r13.txt \
  sealed_final_preflight.json sealed_final_preflight_digest.txt \
  qualification_result.json qualification_raw.json \
  qualification_pair_evidence_table.json \
  qualification_c2_block_evidence_table.json \
  qualification_c2_independent_marginal.json \
  qualification_fit_manifest.json \
  qualification_preprocessor_state.json \
  qualification_preprocessor_bundle.json \
  qualification_reference.json qualification_reference_mismatches.json \
  qualification_cue_semantics.json \
  qualification_exposure_r13.json qualification_exposure_ledger_r13.jsonl \
  seed_namespace_integrity_post_final.json seed_namespace_integrity.json \
  ppo_256step_smoke.json \
  r13_iteration_aborted.json r13_iteration_events.jsonl \
  pass_path_cleanliness.json fail_path_cleanliness.json \
  lock_plan_failure_traceback.json qualification_crash_traceback.log; do
  [ -f "$ART/$f" ] && cp "$ART/$f" "$DST/$f" || true
done

# preplan 子目录与 raw logs
mkdir -p "$DST/preplan" "$DST/raw_logs"
cp "$ART"/preplan/*.json "$DST/preplan/" 2>/dev/null || true
cp "$SRC"/r13_*.log "$DST/raw_logs/" 2>/dev/null || true

echo "assemble_r13_b: done"
