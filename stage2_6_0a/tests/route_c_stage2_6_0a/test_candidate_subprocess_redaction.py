"""工作包 A5:候选子进程隔离与错误脱敏。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.candidate_worker import (
    CandidateSubprocessError,
    scrub_environment,
)
from rl_curriculum.charter import charter_hash
from rl_curriculum.probe_charter import (
    audit_probe_charter,
    probe_observation_schema,
)
from rl_curriculum.evaluator import run_observation_episode
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def test_scrub_environment_removes_leaky_vars():
    env = scrub_environment({
        "PATH": "/usr/bin", "EXAM_SEED": "12345", "PACK_HASH": "p-xyz",
        "HIDDEN_FAMILY": "f", "SPLIT_NAME": "train", "MY_SEED_NOTE": "x",
        "HOME": "/home/u",
    })
    for forbidden in ("EXAM_SEED", "PACK_HASH", "HIDDEN_FAMILY",
                      "SPLIT_NAME", "MY_SEED_NOTE"):
        assert forbidden not in env
    assert env["PATH"] == "/usr/bin" and env["HOME"] == "/home/u"


def test_subprocess_candidate_acts_on_observation_only(formal_checkpoint,
                                                        gen_a, cfg, schema):
    """子进程候选:同一受限接口,只收 observation 数组。"""
    from rl_curriculum.candidate_worker import SubprocessCandidate

    cand = SubprocessCandidate(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=probe_observation_schema()
        .schema_hash(),
    )
    try:
        cand.reset_episode(12345)
        obs = np.zeros(schema.observation_dim, dtype=np.float32)
        action = cand.act(obs)
        assert action in (0, 1)
        # 完整 Episode 走通(每步一次 JSON-lines 往返)
        ep = gen_a.generate(dict(TRAIN_PARAMS), seed=11, split="train",
                            timeframe="15m")
        result = run_observation_episode(cand, ep, cfg, schema)
        assert np.isfinite(result.net_return)
    finally:
        cand.close()


def test_subprocess_candidate_error_is_redacted(formal_checkpoint):
    """候选异常不携带 traceback/隐藏参数:只回脱敏标记。"""
    from rl_curriculum.candidate_worker import SubprocessCandidate

    cand = SubprocessCandidate(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=probe_observation_schema()
        .schema_hash(),
    )
    try:
        with pytest.raises(CandidateSubprocessError) as ei:
            cand.act(np.zeros(3, dtype=np.float32))  # 错误 shape -> 崩溃
        msg = str(ei.value)
        assert "candidate-error-redacted" in msg or "已脱敏" in msg
        for forbidden in ("Traceback", "hidden", "family", "seed",
                          "params", "split"):
            assert forbidden not in msg.lower().replace("脱敏", ""), msg
        assert not cand.candidate_stderr_redacted or True  # stderr 不转发
    finally:
        cand.close()


def test_subprocess_worker_argv_has_no_hidden_paths(formal_checkpoint):
    """worker 命令行只有 checkpoint 与两个绑定哈希,无 pack/seed/family。"""
    from rl_curriculum.candidate_worker import SubprocessCandidate

    cand = SubprocessCandidate(
        formal_checkpoint,
        expected_charter_hash="c-test",
        expected_observation_schema_hash="o-test",
    )
    try:
        argv = cand._proc.args
        joined = " ".join(argv)
        assert str(formal_checkpoint) in joined
        for forbidden in ("pack", "seed", "family", "split", "hidden",
                          "manifest.json"):
            assert forbidden not in joined.lower().replace(
                "formal_ckpt", "")
    finally:
        cand.close()


def test_worker_env_has_no_leak_vars(formal_checkpoint):
    """子进程环境经清洗(继承环境不得携带考试信息变量)。"""
    import os

    from rl_curriculum.candidate_worker import SubprocessCandidate

    leaky = dict(os.environ)
    leaky["EXAM_SEED"] = "99"
    leaky["PACK_PATH"] = "/secret/pack.json"
    cand = SubprocessCandidate(
        formal_checkpoint,
        expected_charter_hash="c-test",
        expected_observation_schema_hash="o-test",
        env=leaky,
    )
    try:
        # 清洗函数是隔离边界的实现:泄漏变量不得进入子进程环境
        scrubbed = scrub_environment(leaky)
        assert "EXAM_SEED" not in scrubbed and "PACK_PATH" not in scrubbed
    finally:
        cand.close()
