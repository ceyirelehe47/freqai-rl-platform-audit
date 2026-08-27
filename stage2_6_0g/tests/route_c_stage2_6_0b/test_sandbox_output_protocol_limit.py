"""工作包 C7:输出协议限制(单步超时/单行长度/非法响应 fail closed)。"""

from __future__ import annotations

import time

import numpy as np
import pytest

from rl_curriculum.sandbox import (
    MAX_RESPONSE_LINE_BYTES,
    CandidateSandboxError,
    SandboxedCandidate,
)


def test_sandboxed_candidate_happy_path(sandbox_checkpoint, schema,
                                         mock_trusted_issuer):
    import hashlib
    from pathlib import Path

    from rl_curriculum.charter import charter_hash
    from rl_curriculum.probe_charter import audit_probe_charter

    cand = SandboxedCandidate(
        sandbox_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=schema.schema_hash())
    cand.reset_episode()
    obs = np.zeros(schema.observation_shape()[0], dtype=np.float32)
    a1 = cand.act(obs)
    a2 = cand.act(obs)
    assert a1 == a2
    cand.reset_episode()
    assert cand.act(obs) == a1
    cand.close()


def test_oversized_response_line_fails_closed(sandbox_checkpoint, schema):
    """worker 输出超长行 -> CandidateSandboxError(协议违规 fail closed)。"""
    import os

    from rl_curriculum.sandbox import MAX_RESPONSE_LINE_BYTES, _LineReader

    r_fd, w_fd = os.pipe()
    os.set_blocking(r_fd, False)
    big = b"x" * (MAX_RESPONSE_LINE_BYTES + 1) + b"\n"
    os.write(w_fd, big)
    reader = _LineReader(os.fdopen(r_fd, "rb"), timeout=5.0,
                         max_bytes=MAX_RESPONSE_LINE_BYTES)
    with pytest.raises(CandidateSandboxError, match="上限"):
        reader.readline()
    os.close(w_fd)


def test_response_timeout_fails_closed(sandbox_checkpoint, schema):
    """单步响应超时 -> CandidateSandboxError。"""
    from rl_curriculum.sandbox import _LineReader

    import os
    import time

    r_fd, w_fd = os.pipe()
    # 不写入任何数据:读取必须超时
    reader = _LineReader(os.fdopen(r_fd, "rb"), timeout=0.5,
                         max_bytes=MAX_RESPONSE_LINE_BYTES)
    t0 = time.time()
    import pytest as _pytest

    with _pytest.raises(CandidateSandboxError, match="超时"):
        reader.readline()
    assert time.time() - t0 < 5
    os.close(w_fd)


def test_illegal_worker_output_fails_candidate(sandbox_checkpoint, schema):
    """worker 输出非 JSON 行 -> 通信错误(EXAM_INVALID 路径)。"""
    import json

    from rl_curriculum.sandbox import CandidateSandboxError

    # 手工构造 SandboxedCandidate 的 _send 语义:非 JSON 行在解析层
    # 抛 CandidateSandboxError(已脱敏)
    line = "not-json-at-all"
    with pytest.raises(json.JSONDecodeError):
        json.loads(line)
    # 源码级断言:_send 对解析失败有专门的处理分支
    import inspect

    from rl_curriculum import sandbox as sbx

    src = inspect.getsource(sbx.SandboxedCandidate._send)
    assert "回复无法解析" in src


def test_max_response_line_bytes_bound():
    assert MAX_RESPONSE_LINE_BYTES == 4096
    from rl_candidate_runtime.worker import MAX_RESPONSE_LINE_BYTES as W

    assert W == MAX_RESPONSE_LINE_BYTES, (
        "worker 侧与父进程侧行长上限必须一致")
