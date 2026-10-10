# -*- coding: utf-8 -*-
"""Child: monkeypatch PIN constant then run real entry (issue-permit)."""
import runpy
import sys

pin, project, deploy, adir, head, tree = sys.argv[1:7]
sys.path.insert(0, project + "/src")
import rl_curriculum.curriculum261_qaf_provenance_guard as guard
guard.R17_PIN_EXPECTED_ROOT = pin
entry = project + "/stage2_6_1_runner/qprod_formal_authority.py"
sys.argv = [entry, "issue-permit", "--dir", adir, "--deploy-root", deploy,
            "--task-level", "level_a", "--attempt", "qaf_v3",
            "--repo", pin, "--project-dir", project,
            "--regression-evidence", "fr2-indep-probe",
            "--code-freeze-sha", head, "--plan-digest", tree]
try:
    runpy.run_path(entry, run_name="__main__")
    print("CHILD_RC=0")
except SystemExit as e:
    print("CHILD_RC=" + str(e.code))
