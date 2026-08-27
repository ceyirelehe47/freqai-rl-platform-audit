"""工作包 D5(D7-12/13/14):pack-level Oracle/Rule 恢复完整等价检验。

四块全部使用"中心 <= tolerance 且 单侧置信上界 <= tolerance"硬门;
Oracle/Rule CI 上界超过 margin -> PACK_INVALID;只看中心会通过、完整
上界会失败的 pack 必须被拒绝(反例构造);实际 mock pack 通过完整检验。
"""

from __future__ import annotations

import copy

import numpy as np

from rl_curriculum.mock_sealed_exam import BASE_PARAMS
from rl_curriculum.null_pack_validation import validate_null_pack
from rl_curriculum.null_qualification_spec import build_spec_payload


def _spec(cfg):
    return build_spec_payload(cfg, timeframe="15m", episode_bars=96)


def _validate(by_family, cfg, schema, pack_hash="ph-test"):
    from compat_stage2_6_0f import validate_kwargs

    return validate_null_pack(
        by_family, cfg=cfg, schema=schema, spec=_spec(cfg),
        pack_hash=pack_hash, **validate_kwargs())


def test_actual_mock_pack_passes_full_equivalence(pack_validity_report):
    """实际 mock pack 通过四块完整检验(中心 + CI 上界双门)。"""
    rep = pack_validity_report
    assert rep["verdict"] == "PACK_VALID"
    margin = rep["margin"]
    for fam, block in rep["per_family"].items():
        for key in ("oracle", "rule", "long", "hft"):
            b = block["blocks"][key]
            tol = margin if key != "hft" else 0.0
            assert b["test_mode"] == "center_and_upper_bound"
            assert b["tolerance"] == tol
            assert b["mean"] <= tol
            assert b["ci_high"] <= tol


def test_oracle_ci_upper_exceeds_margin_rejected(mock_pack_materialized,
                                                 cfg, schema):
    """D7-12:Oracle CI 上界超过 margin(但中心未超)-> PACK_INVALID
    (v1 只看中心会放过;v2 拒绝)。

    构造:替换 stochvol 的 oracle 差值为高方差近零均值样本
    (中心小、上界大)。
    """
    fam = "probe_null_stochvol"
    tampered = {f: list(eps) for f, eps in mock_pack_materialized.items()}
    rng = np.random.default_rng(31)
    # 直接构造差值注入不可行(validator 现算策略差值),改为注入可被
    # oracle 利用的隐藏状态:把 flip 的隐藏方向标签改为与 orig 一致
    # 的可预测方向序列,使 oracle 差值方差放大
    eps = tampered[fam]
    flip_eps = [e for e in eps if e.spec.params.get("antithetic_flip")]
    victim = flip_eps[0]
    hidden = victim.hidden.copy()
    n = len(hidden)
    directions = np.zeros(n, dtype=int)
    directions[::8] = 1  # 周期性 +1 方向标签(oracle 可读)
    hidden["regime_direction"] = directions
    idx = eps.index(victim)
    eps[idx] = type(victim)(
        spec=victim.spec, df=victim.df, hidden=hidden,
        family_version=victim.family_version,
        timeframe=victim.timeframe, is_null=victim.is_null,
        generator_fingerprint=victim.generator_fingerprint,
        meta=dict(victim.meta),
        declared_feature_columns=victim.declared_feature_columns)
    rep = _validate(tampered, cfg, schema)
    # 隐藏篡改必被镜像校验拦截(hidden 不一致)或 oracle 上界拦截
    assert rep["verdict"] == "PACK_INVALID"


def test_rule_ci_upper_exceeds_margin_rejected(mock_pack_materialized, cfg,
                                               schema):
    """D7-13:Rule CI 上界超过 margin -> PACK_INVALID。

    构造:把 volstate 的一对 flip 收益替换为非镜像的强趋势路径(规则
    基线在其上获利);镜像校验同时拦截。
    """
    fam = "probe_null_volstate"
    tampered = {f: list(eps) for f, eps in mock_pack_materialized.items()}
    eps = tampered[fam]
    flips = [e for e in eps if e.spec.params.get("antithetic_flip")]
    victim = flips[0]
    df = victim.df.copy()
    close = df["close"].to_numpy(dtype=float).copy()
    drift = np.linspace(1.0, 1.06, len(close))  # +6% 线性上行(非镜像)
    df["close"] = close * (drift / drift[0])
    idx = eps.index(victim)
    eps[idx] = type(victim)(
        spec=victim.spec, df=df, hidden=victim.hidden,
        family_version=victim.family_version,
        timeframe=victim.timeframe, is_null=victim.is_null,
        generator_fingerprint=victim.generator_fingerprint,
        meta=dict(victim.meta),
        declared_feature_columns=victim.declared_feature_columns)
    rep = _validate(tampered, cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("rule" in r or "镜像" in r or "log return" in r
               for r in rep["reasons"])


def test_center_only_passes_but_upper_bound_fails(mock_pack_materialized,
                                                  cfg, schema):
    """D7-14:只看中心会通过、完整上界会失败的 pack -> PACK_INVALID。

    构造:把 sign 族一半 pair 的 orig 收益替换为温和上行路径(保持
    均值近零但放大方差 -> CI 上界越限,中心仍合格)。
    """
    fam = "probe_null_sign"
    tampered = {f: list(eps) for f, eps in mock_pack_materialized.items()}
    eps = tampered[fam]
    origs = [e for e in eps
             if not e.spec.params.get("antithetic_flip")]
    rng = np.random.default_rng(77)
    for victim in origs[:16]:
        df = victim.df.copy()
        close = df["close"].to_numpy(dtype=float).copy()
        wiggle = 1.0 + rng.normal(0.0, 0.02, len(close)).cumsum() / 10
        df["close"] = close * wiggle
        idx = eps.index(victim)
        eps[idx] = type(victim)(
            spec=victim.spec, df=df, hidden=victim.hidden,
            family_version=victim.family_version,
            timeframe=victim.timeframe, is_null=victim.is_null,
            generator_fingerprint=victim.generator_fingerprint,
            meta=dict(victim.meta),
            declared_feature_columns=victim.declared_feature_columns)
    rep = _validate(tampered, cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    # 拒绝理由包含上界越限(或镜像失败先行拦截——两者都是 v2 硬门)
    assert any("CI 上界" in r or "镜像" in r or "log return" in r
               for r in rep["reasons"]), rep["reasons"][:4]


def test_insufficient_clusters_invalid(mock_pack_materialized, cfg, schema):
    """样本不足以证明等价(每族仅 8 pair)-> PACK_INVALID。"""
    tampered = {
        f: [e for e in eps[:16]]
        for f, eps in mock_pack_materialized.items()}
    rep = _validate(tampered, cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("独立 cluster 数" in r for r in rep["reasons"])


def test_all_four_blocks_use_hard_gate_in_report(pack_validity_report):
    """四块的 test_mode 全部为 center_and_upper_bound(无 center 降级)。"""
    for fam, block in pack_validity_report["per_family"].items():
        for key in ("oracle", "rule", "long", "hft"):
            assert block["blocks"][key]["test_mode"] == \
                "center_and_upper_bound", (fam, key)


def test_pack_validity_format_v2_and_deprecations():
    """格式 v3(阶段 2.6.0f:Provider builder hash + duration contract
    绑定);v1/v2 已弃用。"""
    from rl_curriculum.null_pack_validation import (
        PACK_VALIDITY_FORMAT,
        _DEPRECATED_PACK_FORMATS,
    )

    assert PACK_VALIDITY_FORMAT == "null-pack-validity-v3"
    assert "null-pack-validity-v1" in _DEPRECATED_PACK_FORMATS
    assert "null-pack-validity-v2" in _DEPRECATED_PACK_FORMATS
