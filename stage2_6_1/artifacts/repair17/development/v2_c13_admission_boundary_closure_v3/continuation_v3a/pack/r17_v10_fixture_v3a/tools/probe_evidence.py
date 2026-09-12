#!/usr/bin/env python3
"""Read-only healthy package verification + isolated copy mutations. No claim."""
from __future__ import annotations
import argparse
import copy
import json
from pathlib import Path
import shutil
import sys


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--runner',type=Path,required=True)
    ap.add_argument('--package',type=Path,required=True)
    ap.add_argument('--out',type=Path,required=True)
    args=ap.parse_args()
    sys.path.insert(0,str(args.runner.resolve(strict=True)))
    import r17_v2_c13_regression_evidence as rev
    from r17_v2_c13_admission_guard import tree_index
    original=args.package.resolve(strict=True)
    if args.out.exists():raise RuntimeError('output directory already exists')
    if args.out.absolute().is_relative_to(original):raise RuntimeError('output cannot be inside input')
    args.out.mkdir(parents=True)
    before=tree_index(original)
    def verify(root):return rev.verify_package(root,checks='full')
    control=verify(original)
    (args.out/'healthy.json').write_text(json.dumps(control,indent=2)+'\n')
    if not control['ok']:raise RuntimeError(f'healthy full verification failed: {control["errors"]}')
    recipes=[
        ('required_empty','required_role_set_mismatch'),
        ('required_duplicate','required_role_set_mismatch'),
        ('critical_empty','critical_policy_mismatch'),
        ('failure_under_zero_summary','junit_failures_nonzero'),
        ('collection_same_count_foreign','collected_membership_mismatch'),
        ('import_origin_missing','import_identity_mismatch'),
        ('supervisor_rc_missing','supervision_rc_mismatch'),
        ('nested_directory_symlink','non_regular_file'),
    ]
    results=[]
    for label,expected in recipes:
        case=args.out/label; case.mkdir()
        pkg=case/'package';shutil.copytree(original,pkg)
        def edit(rel,fn):
            p=pkg/rel;doc=json.loads(p.read_text());fn(doc)
            p.write_text(json.dumps(doc,indent=2)+'\n')
        if label=='required_empty':
            edit('required_files.json',lambda d:d.update(entries=[]))
        elif label=='required_duplicate':
            edit('required_files.json',lambda d:d['entries'].append(copy.deepcopy(d['entries'][0])))
        elif label=='critical_empty':
            edit('critical_tests.json',lambda d:d.update(critical_test_files=[]))
        elif label=='failure_under_zero_summary':
            import xml.etree.ElementTree as ET
            p=pkg/'junit.xml';doc=ET.fromstring(p.read_bytes())
            case_node=next(c for c in doc.iter('testcase') if not list(c))
            ET.SubElement(case_node,'failure',{'message':'isolated negative fixture'})
            p.write_bytes(ET.tostring(doc,encoding='utf-8',xml_declaration=True))
        elif label=='collection_same_count_foreign':
            p=pkg/'collected_tests.txt';lines=p.read_text().splitlines()
            i=next(i for i,s in enumerate(lines) if '::' in s)
            lines[i]=lines[i]+'__not_executed';p.write_text('\n'.join(lines)+'\n')
        elif label=='import_origin_missing':
            edit('import_identity.json',lambda d:next(iter(d['deploy'].values())).update(file='/nonexistent/import.py'))
        elif label=='supervisor_rc_missing':
            edit('supervision/run_record.json',lambda d:d['business'].pop('rc'))
        else:
            (pkg/'symlink_directory').symlink_to(pkg/'supervision',target_is_directory=True)
        # Resign only the outer manifest for semantic negatives, never original.
        if label!='nested_directory_symlink':
            ix={k:v for k,v in rev.package_content_index(pkg).items() if k!='manifest.json'}
            (pkg/'manifest.json').write_text(json.dumps({'format':rev.PACKAGE_FORMAT,'files':ix},indent=2)+'\n')
        verdict=verify(pkg)
        keys={k for k,_ in verdict['errors']}
        ok=not verdict['ok'] and expected in keys
        result={'case':label,'expected_error':expected,'rejected_at_expected_layer':ok,'verdict':verdict}
        (case/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        (case/'mutation.txt').write_text(label+'; isolated copy only; original untouched\n')
        results.append(result)
    unchanged=before==tree_index(original)
    summary={'healthy_full_pass':True,'original_bytes_unchanged':unchanged,
             'all_negative_cases_rejected':all(x['rejected_at_expected_layer'] for x in results),
             'cases':[{k:v for k,v in r.items() if k!='verdict'} for r in results]}
    (args.out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2))
    return 0 if unchanged and summary['all_negative_cases_rejected'] else 1

if __name__=='__main__':
    raise SystemExit(main())
