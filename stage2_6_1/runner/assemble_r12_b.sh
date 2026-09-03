#!/usr/bin/env bash
# R12 Commit B 组装:正式执行 artifacts -> 发布仓库
set -euo pipefail
SRC="$HOME/projects/crypto_rl"
REPO="${RELEASE_REPO:-/mnt/e/trading/freqai-rl-audit}"
ART="$SRC/artifacts/route_c_stage2_6_1_repair12"
DST="$REPO/stage2_6_1/artifacts/repair12"

cd "$REPO"
git checkout route-c-stage2-6-1-repair12 2>/dev/null || true

# 正式阶段顶层 artifacts(audit/cue-audit/design/calibrate/abort/cleanliness)
mkdir -p "$DST/raw_logs"
for f in baseline_ancestry.json historical_evidence_binding.json \
         historical_evidence_binding_digest.txt historical_binding.json \
         r11_abort_binding.json r11_cue_failure_binding.json \
         r8_abort_binding.json r9_abort_binding.json r10_abort_binding.json \
         dependency_resolution.json vendor_integrity.json \
         delegation_signature_audit.json delegation_ast_checks.json \
         official_entrypoint_validation.json production_preprocessing_audit.json \
         preprocessing_v2_contract.json preprocessing_v2_contract_digest.txt \
         production_equivalence.json seed_namespace_integrity_pre_design.json \
         generation_determinism_binding.json route_c_integrity.json \
         r12_code_freeze.json r12_source_tree_manifest.json \
         cue_audit_plan.json cue_audit_plan_digest.txt \
         cue_contract_audit.json cue_event_trace.jsonl cue_k_distribution.json \
         cue_global_k_result.json cue_global_k_null_summary.json \
         cue_global_k_cell_diagnostics.json \
         tail_mirror_bound_integrity.json once_vs_attempts_audit.json \
         noise_replay_validation.json tail_mirror_validation.json \
         r12_design_plan.json r12_design_plan_digest.txt \
         semantic_design_main.json semantic_design_validation.json \
         r12_candidate_results.json r12_power_analysis.json \
         r12_sample_size_selection.json c2_independent_marginal_design.json \
         r12_parameter_pack.json r12_parameter_pack_digest.txt \
         plan_roundtrip_validation.json \
         preprocessing_v2_requalification.json \
         bundle_routing_validation.json observation_space_validation.json \
         supervised_learnability_main.json supervised_learnability_holdout.json \
         supervised_label_alignment_main.json supervised_label_alignment_holdout.json \
         supervised_dataset_identity_main.json supervised_dataset_identity_holdout.json \
         supervised_distinct_seed_gate_main.json supervised_distinct_seed_gate_holdout.json \
         pair_evidence_table_main.json pair_evidence_table_holdout.json \
         c2_block_evidence_table_main.json c2_block_evidence_table_holdout.json \
         cue_semantic_calibration.json cue_semantic_calibration.jsonl \
         cue_semantic_holdout.json cue_semantic_holdout.jsonl \
         c2_independent_marginal_main.json c2_independent_marginal_holdout.json \
         generation_evidence_completeness.json generation_invocation_ledger.jsonl \
         c2_density_diagnostics.json \
         calibration_evidence.json robustness_gate.json \
         preprocessing_robustness_gate.json curriculum_robustness_gate.json \
         preprocessor_bundle_calibration.json preprocessor_bundle_holdout.json \
         fit_manifest_calibration.json fit_manifest_holdout.json \
         reference_equivalence_main.json reference_equivalence_holdout.json \
         reference_equivalence_mismatches.json \
         conditioning_report.json generator_stress_r12.json \
         preflight_static.json \
         r12_iteration_aborted.json r12_iteration_events.jsonl \
         lock_plan_failure_traceback.json fail_path_cleanliness.json; do
  [ -f "$ART/$f" ] && cp "$ART/$f" "$DST/$f" || true
done

# raw log
cp "$SRC"/lockplan_out.txt "$DST/raw_logs/lockplan_traceback.log" 2>/dev/null || true

echo "assemble_r12_b: done"
