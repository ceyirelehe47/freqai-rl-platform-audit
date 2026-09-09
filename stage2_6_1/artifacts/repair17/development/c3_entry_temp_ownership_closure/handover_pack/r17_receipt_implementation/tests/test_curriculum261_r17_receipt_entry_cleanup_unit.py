"""R17 receipt entry/cleanup regressions.

Default: import the actual repository reader. For the author's standalone
implementation tests only, R17_RECEIPT_TEST_MODULE points to the exact inline
replacement block. This never substitutes the production cleanup branches.
"""
from __future__ import annotations

import errno
import importlib.util
import json
import os
from pathlib import Path
from datetime import datetime, timezone

import pytest


@pytest.fixture(scope='module')
def mod():
    override = os.environ.get('R17_RECEIPT_TEST_MODULE')
    root = Path(__file__).resolve().parents[2]
    candidates = ([Path(override)] if override else [
        root / 'runner' / 'r17_c3_engineering_slice.py',
        root / 'stage2_6_1_runner' / 'r17_c3_engineering_slice.py',
        root / 'stage2_6_1' / 'runner' / 'r17_c3_engineering_slice.py',
    ])
    path = next((p for p in candidates if p.is_file()), None)
    assert path is not None, f'Reader/implementation missing: {candidates}'
    spec = importlib.util.spec_from_file_location('r17_receipt_under_test', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def roots(tmp_path):
    source = tmp_path / 'source'
    source.mkdir()
    (source / 'recipe.json').write_text('{"keep": true}', encoding='utf-8')
    (source / 'child').mkdir()
    out = tmp_path / 'receipts'
    out.mkdir()
    other = tmp_path / 'elsewhere'
    other.mkdir()
    return source, out, other


def state(path):
    """Observe content/type/mtime/identity, deliberately not atime."""
    st = path.lstat()
    payload = (os.readlink(path) if path.is_symlink() else
               path.read_bytes() if path.is_file() else '<directory>')
    return (st.st_mode, st.st_dev, st.st_ino, st.st_mtime_ns, payload)


def tree(root):
    return {str(p.relative_to(root)): state(p)
            for p in [root, *sorted(root.rglob('*'))]}


@pytest.mark.parametrize('kind', [
    'json', 'empty', 'plain', 'directory', 'hardlink',
    'link_existing_same', 'link_existing_cross',
    'link_dangling_same', 'link_dangling_cross', 'link_chain', 'link_self',
])
def test_existing_terminal_entry_always_rejected(mod, roots, kind):
    source, out, other = roots
    target = out / 'result.json'
    if kind in ('json', 'empty', 'plain'):
        target.write_text({'json':'{}','empty':'','plain':'KEEP'}[kind])
    elif kind == 'directory':
        target.mkdir()
    elif kind == 'hardlink':
        os.link(source / 'recipe.json', target)
    elif kind == 'link_self':
        target.symlink_to('result.json')
    elif kind == 'link_chain':
        (other / 'middle').symlink_to('missing.json')
        target.symlink_to(other / 'middle')
    else:
        victim = (other if kind.endswith('cross') else out) / 'victim.json'
        if 'existing' in kind:
            victim.write_text('KEEP')
        target.symlink_to(victim)
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(target, [source])
    assert tree(source.parent) == before
    assert not (other / 'missing.json').exists()


def test_terminal_link_under_symlink_parent_relative(mod, roots, monkeypatch):
    source, out, other = roots
    (source.parent / 'out_alias').symlink_to(out)
    (out / 'r.json').symlink_to(other / 'missing.json')
    monkeypatch.chdir(source.parent)
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(Path('out_alias/r.json'), [source])
    assert tree(source.parent) == before


@pytest.mark.parametrize('suffix', ['recipe.json', 'new/deep/r.json'])
def test_symlink_dotdot_into_protected_source(mod, roots, suffix):
    source, out, other = roots
    (out / 'alias').symlink_to(source / 'child')
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(out / 'alias' / '..' / suffix, [source])
    assert tree(source.parent) == before


@pytest.mark.parametrize('tail', ['new.json', '../new.json', '../../new.json'])
def test_non_directory_ancestor_is_not_folded_away(mod, roots, tail):
    source, out, other = roots
    (out / 'file').write_text('NOT A DIRECTORY')
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected) as info:
        mod._assert_report_target_safe(out / 'file' / tail, [source])
    assert 'NotADirectory' in str(info.value) or 'ENOTDIR' in str(info.value)
    assert tree(source.parent) == before


@pytest.mark.parametrize('kind', ['loop', 'dangling', 'missing_dotdot'])
def test_bad_ancestor_not_treated_as_creatable(mod, roots, kind):
    source, out, other = roots
    if kind == 'loop':
        (out / 'a').symlink_to('b')
        (out / 'b').symlink_to('a')
        target = out / 'a' / 'r.json'
    elif kind == 'dangling':
        (out / 'a').symlink_to(other / 'absent')
        target = out / 'a' / 'r.json'
    else:
        target = out / 'missing' / '..' / 'r.json'
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(target, [source])
    assert tree(source.parent) == before


@pytest.mark.parametrize('code', [errno.EACCES, errno.EIO, errno.ELOOP,
                                  errno.ENOTDIR, errno.ENAMETOOLONG])
def test_realpath_errno_fail_closed(mod, roots, monkeypatch, code):
    source, out, other = roots
    before = tree(source.parent)
    real = mod.os.path.realpath
    def fault(path, *, strict=False):
        if str(path).startswith(str(out)):
            assert strict is True
            raise OSError(code, 'injected resolver failure', str(path))
        return real(path, strict=strict)
    with monkeypatch.context() as m:
        m.setattr(mod.os.path, 'realpath', fault)
        with pytest.raises(mod.ReportTargetRejected) as info:
            mod._assert_report_target_safe(out / 'new.json', [source])
        assert f'errno={code}' in str(info.value)
    assert tree(source.parent) == before


def test_lstat_access_failure_not_false_missing(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'new.json'
    real = mod.os.lstat
    def fault(path, *args, **kwargs):
        if Path(path) == target:
            raise PermissionError(errno.EACCES, 'lstat denied', str(path))
        return real(path, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'lstat', fault)
        with pytest.raises(mod.ReportTargetRejected):
            mod._assert_report_target_safe(target, [source])
    assert not target.exists()


@pytest.mark.parametrize('kind', ['absolute', 'relative', 'nested', 'parent_link',
                                  'prefix_sibling'])
def test_healthy_external_target_uses_confirmed_path(mod, roots, monkeypatch, kind):
    source, out, other = roots
    target = out / 'new.json'
    if kind == 'relative':
        monkeypatch.chdir(source.parent)
        target = Path('receipts/new.json')
    elif kind == 'nested':
        target = out / 'new' / 'deep' / 'r.json'
    elif kind == 'parent_link':
        (source.parent / 'alias').symlink_to(out)
        target = source.parent / 'alias' / 'new.json'
    elif kind == 'prefix_sibling':
        target = source.with_name('source-backup') / 'r.json'
    before = tree(source)
    confirmed = mod._assert_report_target_safe(target, [source])
    tid = mod._atomic_write_receipt(confirmed, {'PASS': True})
    assert confirmed.is_absolute()
    assert json.loads(confirmed.read_text()) == {'PASS': True}
    assert (confirmed.stat().st_dev, confirmed.stat().st_ino) == tid
    assert tree(source) == before


def test_external_input_and_extra_protect_root(mod, roots):
    source, out, other = roots
    original = other / 'p52.json'
    original.write_text('KEEP')
    for target, protections in [
        (original, [source, original]),
        (other / 'new.json', [source, other]),
    ]:
        before = tree(source.parent)
        with pytest.raises(mod.ReportTargetRejected):
            mod._assert_report_target_safe(target, protections)
        assert tree(source.parent) == before


def test_preexisting_fixed_tmp_link_is_preserved(mod, roots):
    source, out, other = roots
    target = out / 'r.json'
    fixed = out / 'r.json.tmp'
    fixed.symlink_to(source / 'recipe.json')
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(target, [source])
    assert tree(source.parent) == before


def test_second_invocation_cannot_own_first_receipt(mod, roots):
    source, out, other = roots
    target = mod._assert_report_target_safe(out / 'r.json', [source])
    mod._atomic_write_receipt(target, {'first': True})
    before = state(target)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(out / 'r.json', [source])
    assert state(target) == before
    next_path = mod._assert_report_target_safe(out / 'next.json', [source])
    mod._atomic_write_receipt(next_path, {'second': True})
    assert state(target) == before


class FixedClock:
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 9, 12, 0, 0, 123456, tzinfo=timezone.utc)


def fixed_temp(mod, target, monkeypatch):
    monkeypatch.setattr(mod, 'datetime', FixedClock)
    stamp = FixedClock.now().strftime('%Y%m%dT%H%M%S%f')
    return target.with_name(f'.{target.name}.{os.getpid()}.{stamp}.tmp')


@pytest.mark.parametrize('kind', ['regular', 'directory', 'dangling_link', 'live_link'])
def test_true_exclusive_create_collision_never_unlinks_foreign(mod, roots,
                                                              monkeypatch, kind):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    if kind == 'regular':
        tmp.write_text('PREEXISTING_FOREIGN_TEMP')
    elif kind == 'directory':
        tmp.mkdir()
    else:
        victim = other / 'missing.json'
        if kind == 'live_link':
            victim.write_text('KEEP TARGET')
        tmp.symlink_to(victim)
    before = tree(source.parent)
    with pytest.raises(mod.ReceiptWriteError) as info:
        mod._atomic_write_receipt(target, {'PASS': True})
    assert isinstance(info.value.primary_error, FileExistsError)
    assert tree(source.parent) == before
    assert not target.exists()


def test_os_open_failure_creates_no_cleanup_ownership(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    original = mod.os.open
    unlinked = []
    real_unlink = mod.os.unlink
    def fail_open(path, *args, **kwargs):
        if Path(path) == tmp:
            raise PermissionError(errno.EACCES, 'create denied', str(path))
        return original(path, *args, **kwargs)
    def watch_unlink(path, *args, **kwargs):
        unlinked.append(str(path))
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'open', fail_open)
        m.setattr(mod.os, 'unlink', watch_unlink)
        with pytest.raises(mod.ReceiptWriteError):
            mod._atomic_write_receipt(target, {'x': 1})
    assert unlinked == []
    assert not tmp.exists() and not target.exists()


def test_fdopen_failure_closes_owned_fd_and_removes_temp(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    observed = []
    def fail_wrap(fd, *args, **kwargs):
        observed.append(fd)
        raise OSError(errno.EIO, 'wrap failed')
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'fdopen', fail_wrap)
        with pytest.raises(mod.ReceiptWriteError) as info:
            mod._atomic_write_receipt(target, {'x': 1})
    assert 'wrap failed' in str(info.value)
    assert not tmp.exists() and not target.exists()
    with pytest.raises(OSError) as err:
        os.fstat(observed[0])
    assert err.value.errno == errno.EBADF


class FaultyStream:
    def __init__(self, stream, stages):
        self.stream, self.stages = stream, stages
    def write(self, text):
        if 'write' in self.stages:
            self.stream.write('{')
            raise OSError(errno.ENOSPC, 'write failed')
        return self.stream.write(text)
    def flush(self):
        if 'flush' in self.stages:
            raise OSError(errno.EIO, 'flush failed')
        return self.stream.flush()
    def fileno(self):
        return self.stream.fileno()
    def close(self):
        self.stream.close()
        if 'close' in self.stages:
            raise OSError(errno.EIO, 'close failed')


@pytest.mark.parametrize('stage', ['write', 'flush', 'fsync', 'close', 'encode'])
def test_after_creation_failure_cleans_own_temp(mod, roots, monkeypatch, stage):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    before_source = tree(source)
    real_fdopen = mod.os.fdopen
    with monkeypatch.context() as m:
        if stage in ('write', 'flush', 'close'):
            m.setattr(mod.os, 'fdopen', lambda *a, **kw:
                        FaultyStream(real_fdopen(*a, **kw), {stage}))
        if stage == 'fsync':
            def fail_sync(fd):
                raise OSError(errno.EIO, 'fsync failed')
            m.setattr(mod.os, 'fsync', fail_sync)
        with pytest.raises(mod.ReceiptWriteError):
            mod._atomic_write_receipt(target, {'bad': {1}} if stage == 'encode'
                                      else {'x': 1})
    assert not tmp.exists() and not target.exists()
    assert tree(source) == before_source


def test_write_and_close_errors_both_preserved(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    real_fdopen = mod.os.fdopen
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'fdopen', lambda *a, **kw:
                    FaultyStream(real_fdopen(*a, **kw), {'write', 'close'}))
        with pytest.raises(mod.ReceiptWriteError) as info:
            mod._atomic_write_receipt(target, {'x': 1})
    assert 'write failed' in str(info.value.primary_error)
    assert any('close failed' in str(e) for e in info.value.cleanup_errors)
    assert not tmp.exists() and not target.exists()


def test_final_name_collision_preserves_existing_and_cleans_temp(mod, roots,
                                                               monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    target.write_text('OLD')
    before = state(target)
    tmp = fixed_temp(mod, target, monkeypatch)
    with pytest.raises(mod.ReceiptWriteError) as info:
        mod._atomic_write_receipt(target, {'x': 1})
    assert isinstance(info.value.primary_error, FileExistsError)
    assert state(target) == before
    assert not tmp.exists()


def test_candidate_update_and_foreign_replacement(mod, roots):
    source, out, other = roots
    target = out / 'r.json'
    one = mod._atomic_write_receipt(target, {'v': 1})
    two = mod._atomic_write_receipt(target, {'v': 2}, owned_id=one)
    assert json.loads(target.read_text()) == {'v': 2}
    foreign = other / 'foreign.json'
    foreign.write_text('FOREIGN')
    os.replace(foreign, target)
    before = state(target)
    with pytest.raises(mod.ReceiptWriteError):
        mod._atomic_write_receipt(target, {'v': 3}, owned_id=two)
    assert state(target) == before
    assert not list(out.glob('*.tmp'))


def test_candidate_update_cannot_follow_a_terminal_link(mod, roots):
    source, out, other = roots
    owned = other / 'owned.json'
    oid = mod._atomic_write_receipt(owned, {'v': 1})
    link = out / 'r.json'
    link.symlink_to(owned)
    before_link, before_owned = state(link), state(owned)
    before_source = tree(source)
    with pytest.raises(mod.ReceiptWriteError):
        mod._atomic_write_receipt(link, {'v': 2}, owned_id=oid)
    # The low-level writer may create/clean its OWN temp, changing the
    # external output directory mtime. Input/link/target data cannot change.
    assert state(link) == before_link and state(owned) == before_owned
    assert tree(source) == before_source
    assert not list(out.glob('*.tmp'))


def test_initial_and_temp_cleanup_error_preserved(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    real_unlink = mod.os.unlink
    first = OSError(errno.EIO, 'FIRST fsync failure')
    def fail_sync(fd):
        raise first
    def fail_temp_unlink(path, *args, **kwargs):
        if Path(path) == tmp:
            raise PermissionError(errno.EACCES, 'SECOND cleanup failure')
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'fsync', fail_sync)
        m.setattr(mod.os, 'unlink', fail_temp_unlink)
        with pytest.raises(mod.ReceiptWriteError) as info:
            mod._atomic_write_receipt(target, {'x': 1})
    assert info.value.primary_error is first
    assert info.value.__cause__ is first
    assert any('SECOND' in str(e) for e in info.value.cleanup_errors)
    assert tmp.exists() and not target.exists()
    assert str(tmp) in str(info.value)
    tmp.unlink()  # test-only restoration, after observing product behavior


def test_cleanup_only_failure_withdraws_own_published_candidate(mod, roots,
                                                              monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    real_unlink = mod.os.unlink
    def fail_temp(path, *args, **kwargs):
        if Path(path) == tmp:
            raise OSError(errno.EIO, 'temp cleanup failed')
        return real_unlink(path, *args, **kwargs)
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'unlink', fail_temp)
        with pytest.raises(mod.ReceiptWriteError) as info:
            mod._atomic_write_receipt(target, {'readback_verdict': 'PASS'})
    assert info.value.primary_error is None
    assert info.value.cleanup_errors
    assert info.value.published_path is None
    assert not target.exists() and tmp.exists()
    tmp.unlink()


def test_cleanup_cannot_delete_replaced_temp(mod, roots, monkeypatch):
    source, out, other = roots
    target = out / 'r.json'
    tmp = fixed_temp(mod, target, monkeypatch)
    real_link = mod.os.link
    foreign = other / 'foreign.tmp'
    foreign.write_text('FOREIGN')
    fid = (foreign.stat().st_dev, foreign.stat().st_ino)
    def replace_temp_at_publication(src, dst, *args, **kwargs):
        # Deterministic I/O-boundary fault, not a racing background thread.
        result = real_link(src, dst, *args, **kwargs)
        os.replace(foreign, src)
        return result
    with monkeypatch.context() as m:
        m.setattr(mod.os, 'link', replace_temp_at_publication)
        with pytest.raises(mod.ReceiptWriteError):
            mod._atomic_write_receipt(target, {'x': 1})
    assert tmp.read_text() == 'FOREIGN'
    assert (tmp.stat().st_dev, tmp.stat().st_ino) == fid
    assert not target.exists()


def test_invalid_nul_rejected_before_writes(mod, roots):
    source, out, other = roots
    before = tree(source.parent)
    with pytest.raises(mod.ReportTargetRejected):
        mod._assert_report_target_safe(out / '\x00bad.json', [source])
    assert tree(source.parent) == before


def test_kernel_non_directory_precedes_library_folding(mod, roots, monkeypatch):
    source, out, other = roots
    (out / 'file').write_text('KEEP')
    raw_parent = out / 'file' / '..'
    real = mod.os.path.realpath
    def folding_library(path, *, strict=False):
        if Path(path) == raw_parent:
            return str(out)
        return real(path, strict=strict)
    with monkeypatch.context() as m:
        m.setattr(mod.os.path, 'realpath', folding_library)
        with pytest.raises(mod.ReportTargetRejected):
            mod._assert_report_target_safe(raw_parent / 'new.json', [source])
    assert not (out / 'new.json').exists()
