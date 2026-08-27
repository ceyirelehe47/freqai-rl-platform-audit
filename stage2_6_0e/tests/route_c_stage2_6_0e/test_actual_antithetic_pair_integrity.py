"""工作包 D(D1-D4/D7):actual pack antithetic pair 完整性测试。

每 seed 恰好 (orig, flip) 各一;参数仅 flip 可不同;物化路径逐位镜像
(收益相反数/累计 drift 抵消/volume/hidden/时间戳);nuisance 槽位因
flip 不变;实际 pack 的每一对都被验证;各类负例全部 PACK_INVALID。
"""

from __future__ import annotations

import copy

import numpy as np
import pytest

from rl_curriculum.mock_sealed_exam import BASE_PARAMS
from rl_curriculum.null_pack_validation import (
    MIRROR_TOLERANCES,
    validate_null_pack,
)
from rl_curriculum.null_qualification_spec import (
    build_spec_payload,
    null_qualification_spec_hash,
)

FAMS = ("probe_null_sign", "probe_null_volstate", "probe_null_stochvol")


def _spec(cfg):
    return build_spec_payload(cfg, timeframe="15m", episode_bars=96)


def _validate(by_family, cfg, schema, pack_hash="ph-test"):
    return validate_null_pack(
        by_family, cfg=cfg, schema=schema, spec=_spec(cfg),
        pack_hash=pack_hash)


def _pair_of(by_family, family=FAMS[0], index=0):
    eps = by_family[family]
    orig = [e for e in eps
            if not e.spec.params.get("antithetic_flip")][index]
    flip = [e for e in eps
            if e.spec.params.get("antithetic_flip")][index]
    return orig, flip


def test_actual_pack_every_pair_verified(pack_validity_report):
    """D7-11:实际 pack 每一对均验证(每族 32 pair,全部镜像通过)。"""
    rep = pack_validity_report
    assert rep["verdict"] == "PACK_VALID"
    for fam, block in rep["per_family"].items():
        pairs = block["pairs"]
        assert pairs["n_pairs_expected"] == 32
        assert pairs["n_pairs_verified"] == 32
        assert pairs["n_pairs_mirror_ok"] == 32
        assert pairs["every_pair_verified"] is True
        assert len(block["pair_details"]) == 32
        assert all(d["mirror_ok"] for d in block["pair_details"])


def test_exact_one_original_one_flip_per_seed(mock_pack_materialized, cfg,
                                              schema):
    """D7-1:每 seed 恰好一个 original + 一个 flip(实际 pack 结构)。"""
    for fam, eps in mock_pack_materialized.items():
        by_seed = {}
        for ep in eps:
            by_seed.setdefault(ep.spec.seed, []).append(
                bool(ep.spec.params.get("antithetic_flip")))
        assert by_seed and all(
            flags == [False, True] or flags == [True, False]
            for flags in by_seed.values())
        assert len(by_seed) == 32


def _tamper_and_validate(by_family, family, seed, eps_modifier, cfg, schema):
    """构造篡改后的 by_family 并验证。"""
    tampered = {f: list(eps) for f, eps in by_family.items()}
    eps_modifier(tampered[family])
    return _validate(tampered, cfg, schema)


def test_extra_flip_rejected(mock_pack_materialized, cfg, schema):
    """D7-2:同 seed 多一个 flip(1 orig + 2 flip)-> PACK_INVALID
    (旧 set(flags) 检查发现不了;v2 按 Episode 数 + 计数拒绝)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    fam = FAMS[0]
    orig, flip = _pair_of(mock_pack_materialized, fam)

    def add_extra_flip(eps):
        eps.append(R[fam].generate(
            dict(flip.spec.params), flip.spec.seed,
            split=flip.spec.split, timeframe=flip.spec.timeframe))

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, add_extra_flip,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("!= 2" in r or "恰好一个" in r
               for r in rep["reasons"]), rep["reasons"]


def test_extra_original_rejected(mock_pack_materialized, cfg, schema):
    """D7-3:多一个 original(两个 original + 一个 flip)-> PACK_INVALID。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    fam = FAMS[0]
    orig, _ = _pair_of(mock_pack_materialized, fam)

    def add_extra_orig(eps):
        eps.append(R[fam].generate(
            dict(orig.spec.params), orig.spec.seed, split=orig.spec.split,
            timeframe=orig.spec.timeframe))

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, orig.spec.seed, add_extra_orig,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("两个 original" in r or "!= 2" in r
               for r in rep["reasons"]), rep["reasons"]


def test_missing_flip_rejected(mock_pack_materialized, cfg, schema):
    """D1:缺 flip(只有 original)-> PACK_INVALID。"""
    fam = FAMS[0]
    _, flip = _pair_of(mock_pack_materialized, fam)

    def drop_flip(eps):
        eps.remove(flip)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, drop_flip, cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("不完整" in r or "!= 2" in r for r in rep["reasons"])


def test_duplicate_spec_rejected(mock_pack_materialized, cfg, schema):
    """D1:重复 spec(同一 canonical 条目两次)被拒绝。"""
    fam = FAMS[0]
    orig, flip = _pair_of(mock_pack_materialized, fam)

    def duplicate(eps):
        eps.append(flip)  # 同一对象重复(重复路径/重复 spec)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, duplicate,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("重复" in r or "!= 2" in r for r in rep["reasons"])


def test_pair_params_mismatch_rejected(mock_pack_materialized, cfg, schema):
    """D7-4/D2:pair 参数除 flip 外不一致 -> PACK_INVALID。"""
    fam = FAMS[0]
    orig, flip = _pair_of(mock_pack_materialized, fam)

    def break_params(eps):
        idx = eps.index(flip)
        bad = copy.deepcopy(flip.spec.params)
        bad["drift_bps_range"] = [25.0, 35.0]  # 除 flip 外的参数不同
        from rl_curriculum.generator_api import EpisodeSpec

        eps[idx] = type(flip)(
            spec=EpisodeSpec(fam, bad, flip.spec.seed, "null_control",
                             "15m"),
            df=flip.df, hidden=flip.hidden,
            family_version=flip.family_version,
            timeframe=flip.timeframe, is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_params,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("params" in r and "不一致" in r for r in rep["reasons"])


def test_timeframe_mismatch_rejected(mock_pack_materialized, cfg, schema):
    """D7-5:pair timeframe 不一致 -> PACK_INVALID。"""
    from rl_curriculum.generator_api import EpisodeSpec

    fam = FAMS[0]
    orig, flip = _pair_of(mock_pack_materialized, fam)

    def break_tf(eps):
        idx = eps.index(flip)
        eps[idx] = type(flip)(
            spec=EpisodeSpec(fam, dict(flip.spec.params), flip.spec.seed,
                             "null_control", "1h"),
            df=flip.df, hidden=flip.hidden,
            family_version=flip.family_version, timeframe="1h",
            is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_tf, cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("timeframe" in r for r in rep["reasons"])


def test_duration_mismatch_rejected(mock_pack_materialized, cfg, schema):
    """D7-6:pair resolved duration 不一致 -> PACK_INVALID。"""
    from rl_curriculum.generator_api import EpisodeSpec

    fam = FAMS[0]
    orig, flip = _pair_of(mock_pack_materialized, fam)

    def break_duration(eps):
        idx = eps.index(flip)
        bad = dict(flip.spec.params)
        bad["episode_bars"] = 48  # resolved duration 与 orig 不同
        eps[idx] = type(flip)(
            spec=EpisodeSpec(fam, bad, flip.spec.seed, "null_control",
                             "15m"),
            df=flip.df, hidden=flip.hidden,
            family_version=flip.family_version, timeframe="15m",
            is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_duration,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("duration" in r or "params" in r for r in rep["reasons"])


def test_path_not_bitwise_mirror_rejected(mock_pack_materialized, cfg,
                                          schema):
    """D7-7:路径并非逐位镜像(篡改 flip 收益一步)-> PACK_INVALID。"""
    fam = FAMS[0]
    _, flip = _pair_of(mock_pack_materialized, fam)

    def break_mirror(eps):
        idx = eps.index(flip)
        df = flip.df.copy()
        close = df["close"].to_numpy(dtype=float).copy()
        close[40] = close[40] * 1.0005  # 一步价格被改动
        df["close"] = close
        eps[idx] = type(flip)(
            spec=flip.spec, df=df, hidden=flip.hidden,
            family_version=flip.family_version,
            timeframe=flip.timeframe, is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_mirror,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("log return" in r or "drift" in r for r in rep["reasons"])


def test_hidden_state_mismatch_rejected(mock_pack_materialized, cfg,
                                        schema):
    """D7-8:hidden volatility/regime 状态不一致 -> PACK_INVALID。"""
    fam = FAMS[0]
    _, flip = _pair_of(mock_pack_materialized, fam)

    def break_hidden(eps):
        idx = eps.index(flip)
        hidden = flip.hidden.copy()
        col = hidden.columns[0]
        vals = hidden[col].to_numpy().copy()
        vals[10] = vals[10] + 1.0
        hidden[col] = vals
        eps[idx] = type(flip)(
            spec=flip.spec, df=flip.df, hidden=hidden,
            family_version=flip.family_version,
            timeframe=flip.timeframe, is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_hidden,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("隐藏" in r for r in rep["reasons"])


def test_volume_mismatch_rejected(mock_pack_materialized, cfg, schema):
    """D7-9:volume 不一致 -> PACK_INVALID。"""
    fam = FAMS[0]
    _, flip = _pair_of(mock_pack_materialized, fam)

    def break_volume(eps):
        idx = eps.index(flip)
        df = flip.df.copy()
        vol = df["volume"].to_numpy(dtype=float).copy()
        vol[5] += 1.0
        df["volume"] = vol
        eps[idx] = type(flip)(
            spec=flip.spec, df=df, hidden=flip.hidden,
            family_version=flip.family_version,
            timeframe=flip.timeframe, is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_volume,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("volume" in r for r in rep["reasons"])


def test_nuisance_changed_by_flip_rejected(mock_pack_materialized, cfg,
                                           schema):
    """D7-10:nuisance 因 flip 而变化(伪造不对称 nuisance)-> PACK_INVALID。"""
    fam = FAMS[0]
    _, flip = _pair_of(mock_pack_materialized, fam)

    def break_nuisance(eps):
        idx = eps.index(flip)
        df = flip.df.copy()
        vals = df["nuisance_0"].to_numpy(dtype=float).copy()
        vals[3] += 0.123
        df["nuisance_0"] = vals
        eps[idx] = type(flip)(
            spec=flip.spec, df=df, hidden=flip.hidden,
            family_version=flip.family_version,
            timeframe=flip.timeframe, is_null=flip.is_null,
            generator_fingerprint=flip.generator_fingerprint,
            meta=dict(flip.meta),
            declared_feature_columns=flip.declared_feature_columns)

    rep = _tamper_and_validate(
        mock_pack_materialized, fam, flip.spec.seed, break_nuisance,
        cfg, schema)
    assert rep["verdict"] == "PACK_INVALID"
    assert any("nuisance" in r for r in rep["reasons"])


def test_generator_side_nuisance_symmetry():
    """D4(生成器侧):antithetic_flip 不改变 nuisance 派生——
    orig/flip 的 nuisance 槽位逐位一致(非 mock 物化路径的直接证据)。"""
    from rl_curriculum.generators import DEFAULT_GENERATOR_REGISTRY as R

    for fam in FAMS:
        base = dict(BASE_PARAMS)
        flip_params = dict(BASE_PARAMS)
        flip_params["antithetic_flip"] = True
        ep_o = R[fam].generate(base, 777001, split="null_control",
                               timeframe="15m")
        ep_f = R[fam].generate(flip_params, 777001, split="null_control",
                               timeframe="15m")
        for slot in ("nuisance_0", "nuisance_1", "nuisance_2"):
            assert np.array_equal(
                ep_o.df[slot].to_numpy(dtype=float),
                ep_f.df[slot].to_numpy(dtype=float)), (fam, slot)
        # volume/hidden 一致;收益镜像
        assert np.array_equal(
            ep_o.df["volume"].to_numpy(dtype=float),
            ep_f.df["volume"].to_numpy(dtype=float))
        assert ep_o.hidden.equals(ep_f.hidden)
        lr_o = np.diff(np.log(ep_o.df["close"].to_numpy(dtype=float)))
        lr_f = np.diff(np.log(ep_f.df["close"].to_numpy(dtype=float)))
        assert float(np.max(np.abs(lr_o + lr_f))) <= \
            MIRROR_TOLERANCES["step_log_return_antisymmetry"]


def test_nuisance_slots_bitwise_equal_in_actual_pack(
        mock_pack_materialized):
    """D4:实际 pack 内所有 pair 的 nuisance 槽位逐位一致(pair side
    不可经 observation 区分)。"""
    for fam, eps in mock_pack_materialized.items():
        by_seed = {}
        for ep in eps:
            by_seed.setdefault(ep.spec.seed, []).append(ep)
        for seed, pair in by_seed.items():
            a, b = pair
            for slot in ("nuisance_0", "nuisance_1", "nuisance_2"):
                assert np.array_equal(
                    a.df[slot].to_numpy(dtype=float),
                    b.df[slot].to_numpy(dtype=float)), (fam, seed, slot)


def test_pair_identity_not_in_observation(mock_pack_materialized):
    """D4:flip/pair id/base seed 不进入 observation(白名单隔离)。"""
    for fam, eps in mock_pack_materialized.items():
        for ep in eps:
            cols = ep.observation_columns()
            assert "antithetic_flip" not in cols
            assert not any("seed" in c or "pair" in c or "flip" in c
                           for c in cols)
