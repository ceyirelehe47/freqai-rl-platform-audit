"""工作包 A5:候选沙箱隔离与错误脱敏。
阶段 2.6.0b 更新:SubprocessCandidate/CandidateSubprocessError 已删除
(JSON-lines 子进程只是 API 隔离,不是安全边界),改用系统级沙箱
rl_curriculum.sandbox.SandboxedCandidate(unshare namespaces + Landlock
+ rlimits);reset_episode() 无参数;启动命令行使用中性 __CHECKPOINT__
占位符,不出现提交路径。"""

from __future__ import annotations

import inspect

import numpy as np
import pytest

from rl_curriculum.candidate_worker import scrub_environment
from rl_curriculum.charter import charter_hash
from rl_curriculum.probe_charter import (
    audit_probe_charter,
    probe_observation_schema,
)
from rl_curriculum.evaluator import run_observation_episode
from rl_curriculum.sandbox import (
    CandidateSandboxError,
    SandboxedCandidate,
)
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _launch(formal_checkpoint):
    return SandboxedCandidate(
        formal_checkpoint,
        expected_charter_hash=charter_hash(audit_probe_charter()),
        expected_observation_schema_hash=probe_observation_schema()
        .schema_hash(),
    )


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


def test_sandboxed_candidate_acts_on_observation_only(formal_checkpoint,
                                                      gen_a, cfg, schema):
    """沙箱候选:同一受限接口,只收 observation 数组。"""
    cand = _launch(formal_checkpoint)
    try:
        cand.reset_episode()  # 无 Episode 身份 token(工作包 B)
        obs = np.zeros(schema.observation_dim, dtype=np.float32)
        action = cand.act(obs)
        assert action in (0, 1)
        # 完整 Episode 走通(每步一次 JSON-lines 沙箱往返)
        ep = gen_a.generate(dict(TRAIN_PARAMS), seed=11, split="train",
                            timeframe="15m")
        result = run_observation_episode(cand, ep, cfg, schema)
        assert np.isfinite(result.net_return)
    finally:
        cand.close()


def test_sandboxed_candidate_error_is_redacted(formal_checkpoint, schema):
    """候选异常不携带 traceback/隐藏参数:只回脱敏标记。"""
    cand = _launch(formal_checkpoint)
    try:
        cand.reset_episode()
        with pytest.raises(CandidateSandboxError) as ei:
            cand.act(np.zeros(3, dtype=np.float32))  # 错误 shape -> 崩溃
        msg = str(ei.value)
        assert "candidate-error-redacted" in msg or "已脱敏" in msg
        for forbidden in ("Traceback", "hidden", "family", "seed",
                          "params", "split"):
            assert forbidden not in msg.lower().replace("脱敏", ""), msg
    finally:
        cand.close()


def test_sandbox_argv_has_no_hidden_paths(formal_checkpoint):
    """沙箱启动命令行只有中性 checkpoint 占位符与两个绑定哈希,
    无 pack/seed/family/split/hidden/manifest.json,也不含提交路径。"""
    cand = SandboxedCandidate(
        formal_checkpoint,
        expected_charter_hash="c-test",
        expected_observation_schema_hash="o-test",
    )
    try:
        argv = cand._proc.args
        joined = " ".join(argv)
        # 工作包 C:worker 命令行使用中性占位符,原始提交路径不进入 argv
        assert "__CHECKPOINT__" in joined
        assert str(formal_checkpoint) not in joined
        for forbidden in ("pack", "seed", "family", "split", "hidden",
                          "manifest.json"):
            assert forbidden not in joined.lower(), (forbidden, joined)
    finally:
        cand.close()


def test_sandbox_launch_env_is_fixed_allowlist():
    """沙箱进程环境是固定白名单(不继承 os.environ,考试信息变量无从进入)。"""
    from rl_curriculum import sandbox

    src = inspect.getsource(sandbox.launch_sandboxed)
    assert "os.environ" not in src
    # 环境清洗工具仍然删除命中泄漏模式的变量(沙箱启动器复用)
    leaky = {"EXAM_SEED": "99", "PACK_PATH": "/secret/pack.json",
             "PATH": "/usr/bin"}
    scrubbed = scrub_environment(leaky)
    assert "EXAM_SEED" not in scrubbed and "PACK_PATH" not in scrubbed
    assert scrubbed["PATH"] == "/usr/bin"
