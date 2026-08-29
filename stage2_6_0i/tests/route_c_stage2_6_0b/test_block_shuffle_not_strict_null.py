"""工作包 H1:block shuffle 不再是严格 Null(降级为诊断族)。"""

from __future__ import annotations

import numpy as np
import pytest

from rl_curriculum.counterfactual import (
    test_null_control,
)
from rl_curriculum.generators import (
    FORMAL_NULL_FAMILIES,
    PARTIAL_DEPENDENCY_TESTS,
    PROBE_ONLY_NULLS,
)


def test_block_shuffle_not_in_required_families():
    assert "probe_null_block" not in FORMAL_NULL_FAMILIES
    assert "probe_null_block" in PARTIAL_DEPENDENCY_TESTS
    assert "probe_null_control" in PROBE_ONLY_NULLS


def test_verdict_required_nulls_exclude_block_shuffle():
    from rl_curriculum.verdict_spec import probe_course_verdict_spec

    spec = probe_course_verdict_spec()
    assert "probe_null_block" not in spec.required_null_families
    assert set(spec.required_null_families) == set(FORMAL_NULL_FAMILIES)


def test_charter_formal_nulls_exclude_block_shuffle():
    from rl_curriculum.probe_charter import audit_probe_charter

    charter = audit_probe_charter()
    proto = charter.get("evaluation_protocol", charter)
    families = proto["formal_null_families"]
    assert "probe_null_block" not in families
    assert "probe_null_stochvol" in families


def test_block_shuffle_meta_documents_partial_classification():
    from rl_curriculum.generators import _NULL_META_DOC

    doc = _NULL_META_DOC["probe_null_block"]
    assert "partial_dependency_destruction" in doc["classification"]
    assert "不得作为正式 Null 硬门" in doc["limitations"]


@pytest.fixture(scope="module")
def block_episodes():
    """block shuffle Episode:短周期规则在其上可获利(方向关系残存)。"""
    from rl_curriculum.generators import ProbeNullBlockShuffleGenerator

    gen = ProbeNullBlockShuffleGenerator()
    params = {"episode_bars": 96, "null_block_size": 8}
    return [gen.generate(dict(params), s, split="null_control",
                         timeframe="15m") for s in (601, 602)]


def test_short_period_rule_profit_on_block_shuffle_not_cheating(
        block_episodes, schema, cfg):
    """短周期规则在 block shuffle 中获利不触发 Null 作弊:
    block 族不在 null_control 的 required 家族中;单独评估 block 族
    时其结论标记为诊断(probe_null_block is_null_family=False)。"""
    from rl_curriculum.policies import OneStepGreedyPolicy

    for ep in block_episodes:
        assert ep.is_null is False  # 降级:诊断族,不再标记为严格 Null
    r = test_null_control(
        OneStepGreedyPolicy(), {"probe_null_block": block_episodes},
        cfg, schema)
    # 该族不是 verdict 的 required family;结果只作诊断证据
    assert "probe_null_block" in r.extra["per_family"]


def test_block_shuffle_keeps_within_block_direction():
    """块内方向(漂移)关系保留(与完全无信号 Null 的机制差异):
    块均值的绝对值显著大于 iid 噪声下的期望(|mean_block| >> σ/√L)。"""
    from rl_curriculum.generators import (
        ProbeNullBlockShuffleGenerator,
    )

    gen = ProbeNullBlockShuffleGenerator()
    params = {"episode_bars": 96, "null_block_size": 16,
              "regimes": [[1, 25.0, 32], [1, 25.0, 32], [1, 25.0, 32]]}
    ep = gen.generate(dict(params), 77, timeframe="15m")
    rets = np.diff(np.log(ep.df["close"].to_numpy()))
    block = 16
    n_blocks = len(rets) // block
    block_means = np.abs(rets[:n_blocks * block].reshape(
        n_blocks, block).mean(axis=1))
    noise_scale = float(np.std(rets)) / np.sqrt(block)
    assert float(np.median(block_means)) > 1.5 * noise_scale, (
        f"块内方向关系意外消失: median|block_mean|="
        f"{np.median(block_means):.6f} vs noise={noise_scale:.6f}")
