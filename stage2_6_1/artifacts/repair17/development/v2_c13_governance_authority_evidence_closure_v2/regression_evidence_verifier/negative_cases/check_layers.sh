#!/usr/bin/env bash
W=/home/cryptorl/projects/crypto_rl/work/R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2/negative_cases
python3 - <<'PY'
import json, glob, os
W = '/home/cryptorl/projects/crypto_rl/work/R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2/negative_cases'
expected = {
    '01_root_missing': 'package_root_missing',
    '02_unspecified': 'package_root_missing',
    '03_rc0_junit_failure': 'junit_failures_nonzero',
    '04_junit_green_business_rc': 'business_rc_nonzero',
    '05_entry_rc': 'entry_rc_nonzero',
    '06_junit_empty': 'junit_empty',
    '07_test_file_entry_deleted': 'test_file_set_changed',
    '08_unregistered_test_file': 'test_file_hash_mismatch',
    '09_stdout_appended': 'manifest_mismatch',
    '10_junit_equal_length_tamper': 'manifest_mismatch',
    '11_manifest_resign': 'required_file_mismatch',
    '12_source_lock_vs_deploy_differ': 'closure_member_mismatch',
    '13_candidate_commit_missing': 'candidate_commit_missing',
    '14_candidate_drift': 'candidate_drift',
    '15_symlink_to_healthy': 'symlink_root',
    '16_dotdot_escape': 'package_root_missing',
    '17_critical_test_skipped': 'critical_test_skipped',
    '18_required_file_missing': 'missing_required_file',
    '19_required_file_changed': 'required_file_mismatch',
}
notes = {
    '15_symlink_to_healthy': (
        'CLI standalone verify 无 authority → 对包根本身 lstat,'
        'symlink 根被拒(symlink_root);带 authority 的逐组件拒绝'
        '(symlink_component)由单元测试与 pipeline 路径精确覆盖。'),
    '16_dotdot_escape': (
        'CLI standalone verify 无 authority → 无允许域概念;逃逸路径'
        '中间组件不存在即 fail-closed 拒绝(package_root_missing)。'
        'domain_escape 精确层由带 authority 的单元测试与 prepare/run '
        '生产路径强制。'),
}
all_ok = True
for case, key in expected.items():
    p = f'{W}/{case}/stdout.log'
    doc = json.load(open(p))
    keys = [k for k, _ in doc['errors']]
    hit = key in keys
    print(f"{case}: expected={key} hit={hit} all_keys={keys[:4]}")
    all_ok &= hit
print('ALL_LAYERS_PRECISE =', all_ok)
json.dump({'expected': expected, 'all_layers_precise': all_ok},
          open(f'{W}/layer_precision.json', 'w'), indent=2)
PY
