"""Author-side checks of patch generation/guards on synthetic repositories.
These are not execution of the user's full repository.
"""
import importlib.util
import subprocess
from pathlib import Path
import pytest

BUNDLE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('r17_applier', BUNDLE / 'apply_implementation.py')
applier = importlib.util.module_from_spec(spec)
spec.loader.exec_module(applier)


def synthetic_source():
    return ("from __future__ import annotations\nfrom pathlib import Path\n"
            "def untouched_business(x):\n    return x * 2\n\n"
            + applier.START +
            "class ReportTargetRejected(Exception):\n    pass\n\n"
            "class ReceiptWriteError(Exception):\n    pass\n\n"
            "def _resolve_target_strict(p):\n    return p\n\n"
            "def _assert_report_target_safe(p, roots):\n    return p\n\n"
            "def _atomic_write_receipt(p, payload, owned_id=None):\n    return (0, 0)"
            + applier.END + "\n    pass\n\n"
            "def untouched_reader():\n    return 'same'\n")


def test_transform_preserves_unrelated_source():
    before = synthetic_source()
    block = (BUNDLE / 'implementation/receipt_block.py').read_text()
    after = applier.transform(before, block)
    assert before.split(applier.START)[0] == after.split('# ----------------------------------------')[0]
    assert before[before.index(applier.END):] == after[after.index(applier.END):]
    compile(after, 'full_synthetic_reader.py', 'exec')


def test_duplicate_or_missing_anchors_refused():
    block = (BUNDLE / 'implementation/receipt_block.py').read_text()
    with pytest.raises(ValueError):
        applier.transform('print(1)', block)
    with pytest.raises(ValueError):
        applier.transform(synthetic_source() + applier.START, block)


def test_git_blob_function_matches_git(tmp_path):
    b = b'blob identity test\n'
    actual = subprocess.run(['git', 'hash-object', '--stdin'], input=b,
                            capture_output=True, check=True).stdout.decode().strip()
    assert applier.git_blob(b) == actual


def test_generated_multifile_patch_applies_atomically(tmp_path):
    repo = tmp_path / 'fixture_repo'
    repo.mkdir()
    subprocess.run(['git', '-C', str(repo), 'init', '-q'], check=True)
    before = synthetic_source()
    block = (BUNDLE / 'implementation/receipt_block.py').read_text()
    after = applier.transform(before, block)
    target = repo / applier.READER
    target.parent.mkdir(parents=True)
    target.write_text(before)
    tests = (BUNDLE / 'tests' / Path(applier.TEST).name).read_text()
    patch = (applier.diff_file(applier.READER, before, after)
             + applier.diff_file(applier.TEST, '', tests, added=True)).encode()
    checked = applier.run_git(repo, 'apply', '--check', '--whitespace=error', '-', data=patch)
    assert checked.returncode == 0, checked.stderr
    applied = applier.run_git(repo, 'apply', '--whitespace=error', '-', data=patch)
    assert applied.returncode == 0, applied.stderr
    assert target.read_text() == after
    assert (repo / applier.TEST).read_text() == tests
