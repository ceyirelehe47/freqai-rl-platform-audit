#!/usr/bin/env python3
"""同口径受保护路径差分:基线(全仓库误收)按五个受保护根前缀过滤后
与 after(只扫受保护根)比对;telemetry 单列。"""
import json

W = ('/home/cryptorl/projects/crypto_rl/work/'
     'R17V2C13GovernanceAuthorityEvidenceAndC2PrepClosure-v2')
PROTECTED = (
    'stage2_6_1/artifacts/repair17/development/v2_c13_engineering_delivery',
    'stage2_6_1/artifacts/repair17/development/'
    'v2_c13_engineering_v2_delivery',
    'stage2_6_1/artifacts/repair17/development/'
    'v2_c13_postrun_governance_closure',
    'stage2_6_1/artifacts/repair17/development/'
    'c2_calibration_launch_preparation',
    'stage2_6_1/artifacts/repair17/development/v2_c13_engineering_claim',
)


def load(path, kind):
    files, telem = {}, {}
    for line in open(path, encoding='utf-8'):
        parts = line.split()
        if len(parts) >= 4 and parts[0] == 'FILE':
            rel, size, sha = parts[1], parts[2], parts[3]
            if rel.startswith('stage2_6_1/artifacts/repair17/development/'
                              'run_supervision'):
                continue
            if any(rel == p or rel.startswith(p + '/') for p in PROTECTED):
                files[rel] = (size, sha)
        elif len(parts) >= 4 and parts[0] == 'TELEM':
            telem[parts[1]] = (parts[2], parts[3])
    return files, telem


base_f, base_t = load(f'{W}/protected_snapshots/baseline_protected.manifest',
                      'base')
after_f, after_t = load(f'{W}/protected_snapshots/after_protected.manifest',
                        'after')
changed = {k for k in base_f if base_f[k] != after_f.get(k)}
added = set(after_f) - set(base_f)
removed = set(base_f) - set(after_f)
doc = {
    'scope_note': '基线 manifest 误收全仓库;本差分按五个受保护根前缀'
                  '过滤后同口径比对;run_supervision 遥测区单列不判失败。',
    'protected_files_base': len(base_f),
    'protected_files_after': len(after_f),
    'changed': sorted(changed),
    'added': sorted(added),
    'removed': sorted(removed),
    'protected_unchanged': not (changed or added or removed),
    'telemetry_base': len(base_t),
    'telemetry_after': len(after_t),
    'telemetry_changed': len([k for k in base_t
                              if base_t[k] != after_t.get(k)]),
    'telemetry_added': len(set(after_t) - set(base_t)),
    'telemetry_removed': len(set(base_t) - set(after_t)),
}
open(f'{W}/protected_snapshots/diff_summary.json', 'w').write(
    json.dumps(doc, indent=2, ensure_ascii=False))
print(json.dumps(doc, indent=2, ensure_ascii=False)[:1200])
