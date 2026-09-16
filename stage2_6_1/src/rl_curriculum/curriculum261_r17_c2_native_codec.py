"""Lossless, bounded synthetic episode transport. No pickle or project imports.

This is an engineering input format, not a producer proof or authorization.
Native episode_content_hash is additionally checked by c2_native_inputs.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import stat
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

FORMAT = 'R17C2ExplicitSyntheticSamples-v1'
MAX_COMPRESSED = 256 * 1024 * 1024
MAX_JSON = 512 * 1024 * 1024
MAX_ROWS = 4096
MAX_COLUMNS = 64
DTYPES = frozenset(('bool', 'int8', 'int16', 'int32', 'int64',
                    'uint8', 'uint16', 'uint32', 'uint64', 'float32', 'float64'))


class SampleError(ValueError):
    pass


def need(ok: bool, message: str) -> None:
    if not ok:
        raise SampleError(message)


def exact(value: Any, keys, label: str) -> None:
    need(type(value) is dict and set(value) == set(keys), label + ': key set')


def integer(value: Any, lo: int, hi: int, label: str) -> int:
    need(type(value) is int and lo <= value <= hi, label + ': integer/range')
    return value


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=False, allow_nan=False).encode('utf-8')


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def parse_json(raw: bytes) -> Any:
    def pairs(items):
        out = {}
        for k, v in items:
            need(k not in out, 'duplicate JSON key: ' + k)
            out[k] = v
        return out

    def bad(value):
        raise SampleError('nonfinite JSON: ' + value)

    try:
        return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs,
                          parse_constant=bad)
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise SampleError('invalid JSON') from exc


def _name(value: Any) -> None:
    need(value is None or type(value) is str, 'index/column name must be text or null')


def _array(values: np.ndarray) -> dict:
    a = np.asarray(values)
    dtype = str(a.dtype)
    need(dtype in DTYPES, 'unsupported numeric dtype: ' + dtype)
    need(a.ndim == 1 and len(a) <= MAX_ROWS, 'array dimensions')
    if a.dtype.kind == 'f':
        need(bool(np.isfinite(a).all()), 'nonfinite array')
    # Canonical little-endian bytes preserve signed zero and full float precision.
    raw = np.ascontiguousarray(a, dtype=a.dtype.newbyteorder('<')).tobytes()
    return {'dtype': dtype, 'n': len(a), 'hex': raw.hex()}


def _unarray(doc: dict) -> np.ndarray:
    exact(doc, ('dtype', 'n', 'hex'), 'array')
    need(type(doc['dtype']) is str and doc['dtype'] in DTYPES, 'array dtype')
    n = integer(doc['n'], 0, MAX_ROWS, 'array length')
    dtype = np.dtype(doc['dtype']).newbyteorder('<')
    text = doc['hex']
    need(type(text) is str and len(text) == n * dtype.itemsize * 2
         and re.fullmatch('[0-9a-f]*', text) is not None, 'array bytes/length')
    a = np.frombuffer(bytes.fromhex(text), dtype=dtype).copy()
    if dtype.kind == 'b':
        need(set(bytes.fromhex(text)) <= {0, 1}, 'noncanonical boolean byte')
    if dtype.kind == 'f':
        need(bool(np.isfinite(a).all()), 'nonfinite array')
    return a.astype(np.dtype(doc['dtype']), copy=False)


_DATETIME_RE = re.compile(r'datetime64\[(ns|us|ms|s)(?:, UTC)?\]')
DATETIME_UNITS = ('ns', 'us', 'ms', 's')


def datetime_unit(dtype_text: str) -> str:
    """pandas 3 constructs datetime64[us] by default; preserve the native unit."""
    m = _DATETIME_RE.fullmatch(dtype_text)
    need(m is not None, 'datetime must use ns/us/ms/s and UTC or naive time')
    return m.group(1)


def encode_index(index: pd.Index) -> dict:
    _name(index.name)
    need(index.is_unique, 'duplicate index')
    if isinstance(index, pd.RangeIndex):
        return {'kind': 'range', 'name': index.name, 'start': index.start,
                'stop': index.stop, 'step': index.step}
    if isinstance(index, pd.DatetimeIndex):
        unit = datetime_unit(str(index.dtype))
        need(not index.hasnans, 'NaT index')
        need(index.freqstr is None or re.fullmatch(r'(?:[1-9][0-9]*)?(?:ns|us|ms|s|min|h|D)', index.freqstr) is not None,
             'unsupported datetime frequency')
        return {'kind': 'datetime', 'name': index.name,
                'tz': None if index.tz is None else 'UTC', 'unit': unit, 'freq': index.freqstr,
                'values': _array(index.asi8)}
    need(not isinstance(index, pd.MultiIndex), 'MultiIndex is not permitted')
    return {'kind': 'numeric', 'name': index.name, 'values': _array(index.to_numpy())}


def decode_index(doc: dict, n: int) -> pd.Index:
    need(type(doc) is dict and 'kind' in doc, 'index object')
    _name(doc.get('name'))
    if doc['kind'] == 'range':
        exact(doc, ('kind', 'name', 'start', 'stop', 'step'), 'range index')
        start = integer(doc['start'], -10**12, 10**12, 'index start')
        stop = integer(doc['stop'], -10**12, 10**12, 'index stop')
        step = integer(doc['step'], -MAX_ROWS, MAX_ROWS, 'index step')
        need(step != 0 and len(range(start, stop, step)) == n, 'index size')
        out = pd.RangeIndex(start, stop, step, name=doc['name'])
    elif doc['kind'] == 'datetime':
        exact(doc, ('kind', 'name', 'tz', 'unit', 'freq', 'values'), 'datetime index')
        need(doc['tz'] in (None, 'UTC'), 'index timezone')
        need(doc['unit'] in DATETIME_UNITS, 'datetime unit')
        freq = doc['freq']
        need(freq is None or (type(freq) is str and
             re.fullmatch(r'(?:[1-9][0-9]*)?(?:ns|us|ms|s|min|h|D)', freq) is not None),
             'unsupported datetime frequency')
        vals = _unarray(doc['values'])
        need(vals.dtype == np.dtype('int64'), 'datetime int64 required')
        out = pd.DatetimeIndex(pd.to_datetime(vals, unit=doc['unit'], utc=doc['tz'] == 'UTC'),
                               name=doc['name'], freq=freq)
        need(not out.hasnans and datetime_unit(str(out.dtype)) == doc['unit'],
             'datetime unit did not round-trip')
        need(out.freqstr == freq, 'datetime frequency did not round-trip')
    else:
        exact(doc, ('kind', 'name', 'values'), 'numeric index')
        need(doc['kind'] == 'numeric', 'unknown index kind')
        out = pd.Index(_unarray(doc['values']), name=doc['name'])
    need(len(out) == n and out.is_unique, 'index length/uniqueness')
    return out


def encode_frame(frame: pd.DataFrame) -> dict:
    need(type(frame) is pd.DataFrame, 'DataFrame required')
    n = integer(len(frame), 1, MAX_ROWS, 'frame rows')
    need(1 <= len(frame.columns) <= MAX_COLUMNS and frame.columns.is_unique,
         'frame columns')
    need(all(type(c) is str and c for c in frame.columns), 'column names')
    _name(frame.columns.name)
    data = []
    for col in frame.columns:
        s = frame[col]
        if _DATETIME_RE.fullmatch(str(s.dtype)) is not None:
            need(not s.isna().any(), 'NaT column')
            data.append({'kind': 'datetime', 'tz': 'UTC' if s.dt.tz else None,
                         'unit': datetime_unit(str(s.dtype)),
                         'values': _array(s.array.asi8)})
        else:
            data.append({'kind': 'numeric', 'values': _array(s.to_numpy())})
    return {'n_rows': n, 'columns': list(frame.columns),
            'columns_name': frame.columns.name,
            'index': encode_index(frame.index), 'data': data}


def decode_frame(doc: dict) -> pd.DataFrame:
    exact(doc, ('n_rows', 'columns', 'columns_name', 'index', 'data'), 'frame')
    n = integer(doc['n_rows'], 1, MAX_ROWS, 'frame rows')
    cols = doc['columns']
    need(type(cols) is list and 1 <= len(cols) <= MAX_COLUMNS
         and all(type(c) is str and c for c in cols)
         and len(set(cols)) == len(cols), 'frame column names')
    _name(doc['columns_name'])
    need(type(doc['data']) is list and len(doc['data']) == len(cols), 'column data')
    out = {}
    for col, data in zip(cols, doc['data']):
        need(type(data) is dict and 'kind' in data, 'column object')
        if data['kind'] == 'datetime':
            exact(data, ('kind', 'tz', 'unit', 'values'), 'datetime column')
            need(data['tz'] in (None, 'UTC'), 'column timezone')
            need(data['unit'] in DATETIME_UNITS, 'datetime column unit')
            vals = _unarray(data['values'])
            need(vals.dtype == np.dtype('int64'), 'datetime column int64')
            values = pd.to_datetime(vals, unit=data['unit'], utc=data['tz'] == 'UTC')
            need(not values.hasnans, 'NaT column')
            need(str(values.dtype) == 'datetime64[' + data['unit'] + (', UTC]' if data['tz'] == 'UTC' else ']'),
                 'datetime column unit did not round-trip')
        else:
            exact(data, ('kind', 'values'), 'numeric column')
            need(data['kind'] == 'numeric', 'unknown column kind')
            values = _unarray(data['values'])
        need(len(values) == n, 'column length')
        out[col] = values
    frame = pd.DataFrame(out, columns=cols)
    frame.index = decode_index(doc['index'], n)
    frame.columns.name = doc['columns_name']
    need(encode_frame(frame) == doc, 'frame round-trip mismatch')
    return frame


def regular_bytes(path: Path, *, limit: int = MAX_COMPRESSED) -> bytes:
    """No following symlinks in any path component; reject concurrent changes."""
    p = Path(path).absolute()
    need('..' not in p.parts, 'parent traversal')
    for part in (p, *p.parents):
        st = part.lstat()
        need(not stat.S_ISLNK(st.st_mode), 'symlink path component: ' + str(part))
    fd = os.open(p, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC)
    try:
        before = os.fstat(fd)
        need(stat.S_ISREG(before.st_mode) and before.st_size <= limit, 'regular bounded file required')
        with os.fdopen(fd, 'rb', closefd=False) as f:
            data = f.read(limit + 1)
        after = os.fstat(fd)
        live = p.lstat()
        identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
        need(identity(before) == identity(after) == identity(live)
             and len(data) == before.st_size, 'file changed while reading')
        return data
    finally:
        os.close(fd)


def write_new(path: Path, data: bytes) -> str:
    p = Path(path).absolute()
    need('..' not in p.parts, 'parent traversal')
    for parent in p.parents:
        need(not parent.is_symlink(), 'symlink parent')
    p.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(p, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC, 0o600)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as f:
            f.write(data)
            f.flush()
            os.fsync(fd)
    finally:
        os.close(fd)
    return hashlib.sha256(data).hexdigest()


def save_document(path: Path, doc: dict) -> str:
    raw = canonical(doc)
    need(len(raw) <= MAX_JSON, 'sample document too large')
    data = gzip.compress(raw, compresslevel=6, mtime=0)
    need(len(data) <= MAX_COMPRESSED, 'compressed document too large')
    return write_new(path, data)


def load_document(path: Path, expected_sha256: str) -> dict:
    need(type(expected_sha256) is str and re.fullmatch('[0-9a-f]{64}', expected_sha256) is not None,
         'external SHA-256 anchor required')
    raw = regular_bytes(path)
    need(hashlib.sha256(raw).hexdigest() == expected_sha256, 'input file digest mismatch')
    import io
    try:
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
            plain = stream.read(MAX_JSON + 1)
        need(len(plain) <= MAX_JSON, 'decompression size limit')
    except (OSError, EOFError) as exc:
        raise SampleError('invalid gzip document') from exc
    doc = parse_json(plain)
    need(type(doc) is dict, 'sample document mapping required')
    return doc
