"""工作包 L:多类 Null Control(结构不同 + 跨族一致 + 文档化)。"""

from __future__ import annotations

import numpy as np

from rl_curriculum.generators import (
    DEFAULT_GENERATOR_REGISTRY,
    FORMAL_NULL_FAMILIES,
)
from tests.route_c_stage2_6_0a.conftest import TRAIN_PARAMS


def _gen_ep(fam, seed, params=None):
    return DEFAULT_GENERATOR_REGISTRY[fam].generate(
        dict(params or TRAIN_PARAMS), seed=seed, split="null_control",
        timeframe="15m")


def test_three_formal_null_families_registered():
    assert FORMAL_NULL_FAMILIES == (
        "probe_null_sign", "probe_null_block", "probe_null_volstate")
    for fam in FORMAL_NULL_FAMILIES:
        gen = DEFAULT_GENERATOR_REGISTRY[fam]
        assert gen.is_null_family
        assert fam in DEFAULT_GENERATOR_REGISTRY


def test_families_structurally_distinct():
    """同源同种子下三个族的输出互不相同(构造真实不同)。"""
    outs = {}
    for fam in FORMAL_NULL_FAMILIES:
        ep = _gen_ep(fam, 123)
        r = np.diff(np.log(ep.df["close"].to_numpy()))
        outs[fam] = r
    fams = list(FORMAL_NULL_FAMILIES)
    for i in range(len(fams)):
        for j in range(i + 1, len(fams)):
            assert not np.allclose(outs[fams[i]], outs[fams[j]]), (
                fams[i], fams[j])


def test_each_family_documents_preserves_destroys():
    for fam in FORMAL_NULL_FAMILIES:
        ep = _gen_ep(fam, 124)
        doc = ep.meta["null_doc"]
        for key in ("preserves", "destroys", "distribution_difference",
                    "limitations"):
            assert doc.get(key), (fam, key)


def test_sign_null_keeps_abs_returns():
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    src = ProbeSegmentedDriftGenerator().generate(
        dict(TRAIN_PARAMS), seed=125, timeframe="15m")
    r_src = np.diff(np.log(src.df["close"].to_numpy()),
                    prepend=float(np.log(src.df["open"].iloc[0])))
    r_null = np.diff(np.log(_gen_ep("probe_null_sign", 125).df["close"]
                            .to_numpy()),
                     prepend=float(np.log(_gen_ep(
                         "probe_null_sign", 125).df["open"].iloc[0])))
    assert np.allclose(np.sort(np.abs(r_null)), np.sort(np.abs(r_src)),
                       atol=1e-12)


def test_volstate_null_keeps_abs_and_vol_slots():
    null = _gen_ep("probe_null_volstate", 126)
    r_null = np.diff(np.log(null.df["close"].to_numpy()),
                     prepend=float(np.log(null.df["open"].iloc[0])))
    # volstate 的 |r| 与源一致(|r| 保留,符号随机化)
    from rl_curriculum.generators import ProbeSegmentedDriftGenerator

    src = ProbeSegmentedDriftGenerator().generate(
        dict(TRAIN_PARAMS), seed=126, timeframe="15m")
    r_src = np.diff(np.log(src.df["close"].to_numpy()),
                    prepend=float(np.log(src.df["open"].iloc[0])))
    assert np.allclose(np.sort(np.abs(r_null)), np.sort(np.abs(r_src)),
                       atol=1e-12)


def test_null_generators_deterministic():
    for fam in FORMAL_NULL_FAMILIES:
        e1 = _gen_ep(fam, 127)
        e2 = _gen_ep(fam, 127)
        assert e1.df.equals(e2.df), fam


def test_cross_family_consistency_no_model_edge(cfg, schema):
    """正式 Null 结论:跨族一致——规则基线与 Oracle 均无稳定正超额。"""
    from rl_curriculum.counterfactual import test_null_control
    from rl_curriculum.policies import (
        OracleSegmentedDriftPolicy,
        RuleTrendPolicy,
    )

    by = {fam: [_gen_ep(fam, s) for s in (128, 129, 130, 131)]
          for fam in FORMAL_NULL_FAMILIES}
    for pol in (RuleTrendPolicy(), OracleSegmentedDriftPolicy()):
        r = test_null_control(pol, by, cfg, schema)
        assert r.pass_, (pol.name, r.reason)
        for fam, per in r.extra["per_family"].items():
            assert not per["stable_positive_excess"], (pol.name, fam)
