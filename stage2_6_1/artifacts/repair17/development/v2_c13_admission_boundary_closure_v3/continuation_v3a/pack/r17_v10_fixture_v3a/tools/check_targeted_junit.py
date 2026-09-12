#!/usr/bin/env python3
"""Check the actual eight-file JUnit report, counting testcase entities."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
from collections import Counter

EXPECTED_FILES = {
    'test_curriculum261_r17_v2_c13_admission_guard',
    'test_curriculum261_r17_v2_c13_claim_protocol',
    'test_curriculum261_r17_v2_c13_regression_evidence',
    'test_curriculum261_r17_v2_c13_pipeline',
    'test_curriculum261_r17_v2_c13_reader_binding',
    'test_curriculum261_r17_v2_c13_synthetic_chain',
    'test_curriculum261_r17_v2_c13_source_provenance',
    'test_curriculum261_r17_c2_launch_prep',
}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runner', type=Path, required=True)
    ap.add_argument('--junit', type=Path, required=True)
    args = ap.parse_args(argv)
    sys.path.insert(0, str(args.runner.resolve(strict=True)))
    from r17_v2_c13_admission_guard import junit_details, stable_bytes
    totals, cases, errors = junit_details(stable_bytes(args.junit))
    files = Counter(c['classname'].split('.')[2] for c in cases)
    names = [c['name'] for c in cases]
    required_names = (
        'test_v10_one_shot_claim',
        'test_v10_corrupted_claim_is_consumed_not_retried',
        'test_v10_fixture_is_evidence_backed_and_not_production',
    )
    missing = [n for n in required_names if names.count(n) != 1]
    negative = [n for n in names if n.startswith('test_v10_unhealthy_fixture_is_still_rejected[')]
    ok = (not errors and totals['tests'] > 0
          and totals['failures'] == totals['errors'] == totals['skipped'] == 0
          and set(files) == EXPECTED_FILES and not missing
          and len(negative) == 4 and len(set(negative)) == 4)
    print(json.dumps({'ok': ok, 'totals': totals, 'files': dict(files),
                      'junit_errors': errors, 'missing_or_duplicate_tests': missing,
                      'v10_negative_cases': negative,
                      'expected_count_hint_only': 157}, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
