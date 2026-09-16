"""Transport tests; no producer/V2/evaluation dependency is substituted."""
import copy
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from rl_curriculum import curriculum261_r17_c2_native_codec as c


def frame():
    return pd.DataFrame({'date': pd.date_range('2026-01-01', periods=4, freq='15min', tz='UTC'),
                         'value': np.array([0., -0., np.nextafter(1., 2.), 1.25]),
                         'i': np.array([0,1,2,3], dtype=np.int64),
                         'b': np.array([True,False,True,False])})


@pytest.mark.parametrize('dtype', sorted(c.DTYPES))
def test_all_numeric_dtypes_roundtrip(dtype):
    f = pd.DataFrame({'v': np.array([0,1,0,1], dtype=dtype)})
    doc = c.encode_frame(f)
    pd.testing.assert_frame_equal(c.decode_frame(doc), f, check_exact=True)


@pytest.mark.parametrize('index', [pd.RangeIndex(4), pd.RangeIndex(9,1,-2),
    pd.Index([11,12,18,22], name='row'), pd.date_range('2024-01-01', periods=4),
    pd.date_range('2024-01-01', periods=4, tz='UTC')])
def test_index_and_signed_zero_are_lossless(index):
    f = frame()
    f.index = index
    f.columns.name = 'features'
    out = c.decode_frame(c.encode_frame(f))
    pd.testing.assert_frame_equal(out, f, check_exact=True)
    assert np.signbit(out.value.iloc[1])


@pytest.mark.parametrize('value', [np.nan, np.inf, -np.inf])
def test_nonfinite_array_rejected(value):
    f = frame()
    f.loc[1, 'value'] = value
    with pytest.raises(c.SampleError):
        c.encode_frame(f)


@pytest.mark.parametrize('raw', [b'{"a":1,"a":2}', b'{"a":NaN}', b'{"a":Infinity}', b'\xff', b'{'])
def test_strict_json(raw):
    with pytest.raises(c.SampleError):
        c.parse_json(raw)


@pytest.mark.parametrize('mutation', ['columns','extra','dtype','hex','n','index','timezone'])
def test_invalid_frame_shape_rejected(mutation):
    d = c.encode_frame(frame())
    if mutation == 'columns': d['columns'][1] = 'date'
    elif mutation == 'extra': d['extra'] = 1
    elif mutation == 'dtype': d['data'][1]['values']['dtype'] = 'object'
    elif mutation == 'hex': d['data'][1]['values']['hex'] += '00'
    elif mutation == 'n': d['n_rows'] = True
    elif mutation == 'index': d['index']['step'] = 0
    elif mutation == 'timezone': d['data'][0]['tz'] = 'arbitrary-constructor'
    with pytest.raises(c.SampleError):
        c.decode_frame(d)


def test_safe_document_and_external_anchor(tmp_path):
    doc = {'frame': c.encode_frame(frame()), 'synthetic': True}
    p = tmp_path/'sample.json.gz'
    sha = c.save_document(p, doc)
    assert c.load_document(p, sha) == doc
    with pytest.raises(c.SampleError):
        c.load_document(p, '0'*64)
    with pytest.raises(FileExistsError):
        c.save_document(p, doc)


def test_symlink_input_and_parent_rejected(tmp_path):
    real = tmp_path/'real'
    real.mkdir()
    p = real/'sample.gz'
    sha = c.save_document(p, {'x':1})
    (tmp_path/'link').symlink_to(real, target_is_directory=True)
    (tmp_path/'file').symlink_to(p)
    for bad in (tmp_path/'link/sample.gz', tmp_path/'file'):
        with pytest.raises(c.SampleError):
            c.load_document(bad, sha)
    with pytest.raises(c.SampleError):
        c.write_new(tmp_path/'link/new', b'x')


def test_parent_traversal_rejected(tmp_path):
    (tmp_path/'sub').mkdir()
    with pytest.raises(c.SampleError):
        c.write_new(tmp_path/'sub/../bad', b'x')


def test_decompression_bound(tmp_path, monkeypatch):
    p = tmp_path/'large.gz'
    data = gzip.compress(b'{"a":"' + b'x'*500 + b'"}', mtime=0)
    p.write_bytes(data)
    monkeypatch.setattr(c, 'MAX_JSON', 100)
    with pytest.raises(c.SampleError):
        c.load_document(p, hashlib.sha256(data).hexdigest())


def test_noncanonical_bool_byte():
    d = c.encode_frame(pd.DataFrame({'b': [True]}))
    d['data'][0]['values']['hex'] = '02'
    with pytest.raises(c.SampleError):
        c.decode_frame(d)


def test_no_object_dtype_or_duplicate_index():
    with pytest.raises(c.SampleError):
        c.encode_frame(pd.DataFrame({'x': ['arbitrary', 'objects']}))
    f = frame()
    f.index = [1,1,2,3]
    with pytest.raises(c.SampleError):
        c.encode_frame(f)
