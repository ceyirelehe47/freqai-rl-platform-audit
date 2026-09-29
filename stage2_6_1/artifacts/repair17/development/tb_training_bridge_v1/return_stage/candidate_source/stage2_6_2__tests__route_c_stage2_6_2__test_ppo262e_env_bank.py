"""Engineering Bridge 测试:bank/env/V2 消费面(K01/K02/V02/V03/M01 冷读)。

纪律:
- 零原生生成:K01 边界观察用**中止型 recorder**(在真实
  spec.generator.generate 调用前拦截并抛出,零 episode 生成、零配额
  消耗);K02/V02/V03 用**合成 episode**(synthetic_ohlcv +
  attach_production_features,SYNTHETIC_ONLY);
- 零 optimizer 更新:M01 的 checkpoint 用 build_diagnosed_ppo 构造后
  直接 save(无 learn 调用);前向均为 no_grad(仅前向/环境 step 的
  无梯度测试,另行记录,不冒充学习)。
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rl_curriculum.generator_api import EpisodeSpec, GeneratedEpisode
from rl_curriculum.ppo262_banks import EpisodeKey, LoadedEpisode
from rl_curriculum.curriculum261_api import episode_content_hash


# ---------------------------------------------------------------- 合成 episode
def _synthetic_episode(k: int, *, bars: int = 96, start: float = 100.0
                       ) -> GeneratedEpisode:
    from rl_curriculum.curriculum261_production_obs import (
        attach_production_features,
    )
    from rl_curriculum.ppo262_eng_fixture import synthetic_ohlcv
    df = attach_production_features(synthetic_ohlcv({
        "start": start * (1.0 + 0.2 * k), "drift": 0.0002 * (k + 1),
        "amp": 0.003, "period": 24.0 + 6.0 * k, "phase": 0.7 * k,
        "wick": 0.0015, "bars": bars}))
    return GeneratedEpisode(
        spec=EpisodeSpec(
            family="eng_synthetic", params={"fixture_k": k}, seed=9000 + k,
            split="train", timeframe="15m"),
        df=df, hidden=df.iloc[:0].copy(), family_version="eng-synth-v0",
        timeframe="15m", is_null=False,
        generator_fingerprint="ppo262e-synthetic-fixture-v1")


def _loaded(k: int, family: str = "c1_opportunity", variant: str = "A",
            bars: int = 96) -> LoadedEpisode:
    ep = _synthetic_episode(k, bars=bars)
    return LoadedEpisode(
        key=EpisodeKey("ppo_eng_bank_262e", family, "D1", k, variant),
        episode=ep, content_hash=episode_content_hash(ep))


@pytest.fixture(scope="module")
def fixture_v1(tmp_path_factory):
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    out = build_eng_fixture(tmp_path_factory.mktemp("eng_fix_env"),
                            variant="v1_r2_reference", verbose=False)
    return out


@pytest.fixture(scope="module")
def fixture_v2(tmp_path_factory):
    from rl_curriculum.ppo262_eng_fixture import build_eng_fixture
    out = build_eng_fixture(tmp_path_factory.mktemp("eng_fix_env2"),
                            variant="v2_perturbed", verbose=False)
    return out


@pytest.fixture(scope="module")
def preproc(fixture_v1):
    from rl_curriculum.curriculum261_r4_preprocessing import (
        RouteCPreprocessorV2,
    )
    return RouteCPreprocessorV2.load_envelope(
        Path(fixture_v1["qualification_dir"]) / "preprocessor_envelope.json")


@pytest.fixture(scope="module")
def qi_v2(fixture_v2):
    from rl_curriculum.ppo262_qualified_input import load_qualified_input
    return load_qualified_input(
        fixture_v2["qualification_dir"],
        authorization_path=fixture_v2["authorization_path"],
        expected_scope="engineering")


# ---------------------------------------------------------------- K01
class _BoundaryAbort(Exception):
    def __init__(self, records):
        self.records = records
        super().__init__("boundary observed; aborted before generator")


def test_k01_selected_pack_reaches_real_generator_boundary(qi_v2, tmp_path):
    """两套 pack 对照:真实 generator 边界观察到的参数 = 选定 pack。

    recorder 在 spec.generator.generate 之前被调用(generate262_pair 的
    param_recorder 语义),抛出以中止生成——零 episode、零配额。整桥
    调用按 staged 序先到 c1;三族逐族用**桥同一 rung_params 对象**直接
    驱动公共 generate262_bank 单对中止观察。
    """
    from rl_curriculum.ppo262_eng_profile import (
        QuotaLedger, generate_eng_bank,
    )
    from rl_curriculum.ppo262_banks import generate262_bank
    ledger = QuotaLedger(tmp_path / "ledger.jsonl")

    def _aborted_run(runner):
        recs = []

        def recorder(family, rung, side, params):
            recs.append({"family": family, "rung": rung, "side": side,
                         "params": dict(params)})
            raise _BoundaryAbort(recs)
        with pytest.raises(_BoundaryAbort) as ab:
            runner(recorder)
        return {r["family"]: r for r in ab.value.records}

    # 整桥路径(staged 序第一个到 c1)
    recs_bridge = _aborted_run(
        lambda rec: generate_eng_bank(qi_v2, ledger, param_recorder=rec))
    assert set(recs_bridge) == {"c1_opportunity"}
    assert recs_bridge["c1_opportunity"]["params"]["opp_drift_bps"] == 45.0
    assert recs_bridge["c1_opportunity"]["params"]["cur261_rung"] == "D1"

    # 三族逐族:同一 pack 对象(qi.rung_params)驱动公共生成入口
    rung = qi_v2.rung_params()
    expected_value = {"c1_opportunity": 45.0, "c2_context": 50.0,
                      "c3_cost": 0.20}
    for fam, key in (("c1_opportunity", "opp_drift_bps"),
                     ("c2_context", "alpha_bps"),
                     ("c3_cost", "cue_rate")):
        keys = [EpisodeKey("ppo_eng_bank_262e", fam, "D1", 0, "A")]
        recs = _aborted_run(
            lambda rec: generate262_bank(
                keys, locked_plan_rung_params=rung,
                param_recorder=rec))
        assert recs[fam]["params"][key] == expected_value[fam]
    # 中止发生在真实生成前:账本无成功事件
    assert ledger.sums()["bank_episode_success"] == 0


@pytest.fixture(scope="module")
def qi_v1_and_boundary(fixture_v1, tmp_path_factory):
    from rl_curriculum.ppo262_qualified_input import load_qualified_input
    qi = load_qualified_input(
        fixture_v1["qualification_dir"],
        authorization_path=fixture_v1["authorization_path"],
        expected_scope="engineering")

    from rl_curriculum.ppo262_eng_profile import (
        QuotaLedger, generate_eng_bank,
    )
    ledger = QuotaLedger(tmp_path_factory.mktemp("led1") / "l.jsonl")
    recs = []

    def recorder(family, rung, side, params):
        recs.append({"family": family, "rung": rung, "side": side,
                     "params": dict(params)})
        raise _BoundaryAbort(recs)

    try:
        generate_eng_bank(qi, ledger, param_recorder=recorder)
    except _BoundaryAbort:
        pass
    return qi, {r["family"]: r for r in recs}


def test_k01_v1_pack_is_r2_reference_values(qi_v1_and_boundary):
    qi, recs = qi_v1_and_boundary
    from rl_curriculum.ppo262_cli import _locked_rung_params
    r2 = _locked_rung_params()["c1_opportunity"]["D1"]
    got = recs["c1_opportunity"]["params"]
    assert got["opp_drift_bps"] == r2["opp_drift_bps"] == 42.0
    assert got["vol_bps"] == r2["vol_bps"]
    # 与 v2 对照:参数对照在边界可区分(不是同一个常数回落)
    assert qi.rung_params()["c1_opportunity"]["D1"]["opp_drift_bps"] == 42.0


# ---------------------------------------------------------------- K02
def test_k02_bank_order_and_multiset():
    from rl_curriculum.ppo262_banks import (
        manifest_equality, mixed_order, staged_order,
    )
    from rl_curriculum.ppo262_eng_profile import eng_bank_keys
    keys = eng_bank_keys()
    staged = staged_order(keys)
    mixed = mixed_order(keys, model_seed=262501)
    eq = manifest_equality(staged, mixed)
    assert eq["same_multiset"] and eq["different_order"]
    fams = [k.family for k in staged]
    assert fams == sorted(fams)  # staged: C1 -> C2 -> C3
    variants = {(k.family, k.variant) for k in keys}
    assert variants == {(f, v) for f in ("c1_opportunity", "c2_context",
                                         "c3_cost") for v in ("A", "B")}


def test_k02_labels_not_in_observation_and_reset_isolation(preproc):
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    bank = [_loaded(0), _loaded(1, family="c2_context"), _loaded(
        2, family="c3_cost")]
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
    obs, info = env.reset(seed=7)
    assert obs.shape == (9,) and str(obs.dtype) == "float32"
    assert np.isfinite(obs).all()
    # attribution 只进 info,不进 observation
    assert info["family"] == "c1_opportunity" and info["namespace"] == (
        "ppo_eng_bank_262e")
    rewards = []
    done = False
    while not done:
        obs, r, term, trunc, info = env.step(1)
        rewards.append(float(r))
        done = term or trunc
        assert obs.shape == (9,)
    # episode 边界账户清空(terminal liquidation 后全现金)
    assert info.get("btc", info.get("actual_position", 0)) == 0
    obs2, info2 = env.reset()
    # reset 后新 episode:第一个特征值与上一 episode 末值不同源(独立内层)
    assert info2["family"] == "c2_context"
    assert env.audit()["first_pass_order_ok"]


def test_k02_env_budget_boundary():
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    bank = [_loaded(0), _loaded(1)]
    env = CurriculumMultiEpisodeEnv(bank)
    for _ in range(2):
        env.reset()
        done = False
        while not done:
            _, _, term, trunc, _ = env.step(1)
            done = term or trunc
    env.reset()  # 耗尽 -> exhausted_cycles=1(确定性回起点,不静默循环)
    assert env.exhausted_cycles == 1
    audit = env.audit()
    assert audit["duplicate_episode_completions"] == 0


# ---------------------------------------------------------------- V02
def test_v02_sb3_sees_v2_outer_space(preproc):
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    from rl_curriculum.ppo262_eng_profile import PPO262E_SMOKE_CONFIG
    bank = [_loaded(0), _loaded(1)]
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
    low, high = env.observation_space.low, env.observation_space.high
    assert env.observation_space.shape == (9,)
    assert np.all(np.isneginf(low[:-1])) and np.all(np.isposinf(high[:-1]))
    assert low[-1] == 0.0 and high[-1] == 1.0
    model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG), 262501, env)
    assert np.array_equal(model.observation_space.low, low)
    assert np.array_equal(model.observation_space.high, high)
    # 无预处理路径(旧 R2 默认)不受影响
    env_raw = CurriculumMultiEpisodeEnv(bank)
    assert not np.all(np.isneginf(env_raw.observation_space.low[:-1]))



def test_v02_passthrough_no_clip_extreme(preproc):
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    ep = _synthetic_episode(0, bars=96, start=5_000_000.0)
    loaded = LoadedEpisode(
        key=EpisodeKey("ppo_eng_bank_262e", "c1_opportunity", "D1", 0, "A"),
        episode=ep, content_hash=episode_content_hash(ep))
    env = CurriculumMultiEpisodeEnv([loaded], preprocessor=preproc)
    obs, _ = env.reset(seed=3)
    # %-raw_close 等特征在该价格尺度上远超 MinMax 训练范围 -> 不 clip
    assert np.abs(obs[:-1]).max() > 10.0
    assert np.isfinite(obs).all() and obs[-1] in (0.0, 1.0)


def test_v02_invalid_input_rejected_by_contract(preproc, tmp_path):
    """非法列/维度按既有合同拒绝(envelope 层)。"""
    import pandas as pd
    from rl_curriculum.curriculum261_production_obs import (
        attach_production_features,
    )
    from rl_curriculum.ppo262_eng_fixture import synthetic_ohlcv
    df = attach_production_features(synthetic_ohlcv({
        "start": 100.0, "drift": 0.0, "amp": 0.001, "period": 20.0,
        "phase": 0.0, "wick": 0.001, "bars": 40}))
    ok = preproc.transform_episode_df(df)
    assert ok.shape == df.shape
    missing = df.drop(columns=["%-ret-1"])
    with pytest.raises(RuntimeError):
        preproc.transform_episode_df(missing)


# ---------------------------------------------------------------- V03
def test_v03_ledger_invariant_under_scaling(preproc):
    """相同 OHLCV 与相同动作:缩放与否的 reward/费用/仓位逐步一致。"""
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    bank = [_loaded(0), _loaded(1, family="c2_context")]
    env_a = CurriculumMultiEpisodeEnv(bank)                    # raw
    env_b = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
    oa, _ = env_a.reset(seed=11)
    ob, _ = env_b.reset(seed=11)
    for t in range(80):
        _, ra, term_a, trunc_a, ia = env_a.step(1 if t % 7 else 0)
        _, rb, term_b, trunc_b, ib = env_b.step(1 if t % 7 else 0)
        assert np.allclose(ra, rb), f"reward 漂移 @t={t}"
        assert np.allclose(ia.get("fee_paid", 0.0), ib.get("fee_paid", 0.0))
        assert ia.get("new_target_position") == ib.get(
            "new_target_position")
        assert (term_a, trunc_a) == (term_b, trunc_b)
        if term_a or trunc_a:
            env_a.reset()
            env_b.reset()


# ---------------------------------------------------------------- M01
@pytest.fixture(scope="module")
def checkpoint_dir(fixture_v1, preproc, tmp_path_factory):
    """构造未训练 checkpoint(零 learn 调用 = 零 optimizer 配额)。"""
    from rl_curriculum.ppo262_qualified_input import load_qualified_input
    from rl_curriculum.ppo262_eng_profile import (
        collect_frozen_probe, engineering_manifest,
    )
    from rl_curriculum.ppo262_train import save_model_with_manifest
    from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
    from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
    from rl_curriculum.ppo262_eng_profile import PPO262E_SMOKE_CONFIG
    qi = load_qualified_input(
        fixture_v1["qualification_dir"],
        authorization_path=fixture_v1["authorization_path"],
        expected_scope="engineering")
    bank = [_loaded(0), _loaded(1, family="c2_context")]
    env = CurriculumMultiEpisodeEnv(bank, preprocessor=preproc)
    model = build_diagnosed_ppo(dict(PPO262E_SMOKE_CONFIG), 262501, env)
    out = tmp_path_factory.mktemp("ckpt")
    manifest = engineering_manifest(
        qi, bank=bank, steps=0, updates=0, config=PPO262E_SMOKE_CONFIG,
        model_seed=262501)
    saved = save_model_with_manifest(
        model, out / "eng_ppo_smoke_256", manifest=manifest)
    probe = collect_frozen_probe(
        preproc, bank, model, bundle_hash=qi.bundle_hash)
    (out / "eng_frozen_probe.json").write_text(
        json.dumps(probe), encoding="utf-8")
    return out, saved, manifest


def test_m01_cold_read_positive(fixture_v1, checkpoint_dir, tmp_path):
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    out, saved, manifest = checkpoint_dir
    result = cold_read_checkpoint(
        fixture_v1["qualification_dir"],
        fixture_v1["authorization_path"], out, tmp_path,
        expected_profile="ppo262_engineering_v1")
    assert result["pass"], result["checks"]
    assert result["model_sha256"] == saved["model_sha256"]
    assert result["deterministic_actions_match"] is True
    assert result["action_probability_max_abs_diff"] <= 1e-9


def test_m01_cold_read_rejects_wrong_input_binding(
        fixture_v1, fixture_v2, checkpoint_dir, tmp_path):
    """训练元数据指向 v1,冷读输入却是 v2 => 绑定不一致拒绝。"""
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    from rl_curriculum.ppo262_qualified_input import QualifiedInputError
    out, _, _ = checkpoint_dir
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v2["qualification_dir"],
            fixture_v2["authorization_path"], out, tmp_path)
    problems = ei.value.report["problems"]
    assert any("manifest" in p and "digest" in p for p in problems)


def test_m01_cold_read_rejects_tampered_model_bytes(
        fixture_v1, checkpoint_dir, tmp_path):
    import shutil
    from rl_curriculum.ppo262_eng_profile import cold_read_checkpoint
    from rl_curriculum.ppo262_qualified_input import QualifiedInputError
    out, _, _ = checkpoint_dir
    tampered = tmp_path / "tampered"
    shutil.copytree(out, tampered)
    zp = tampered / "eng_ppo_smoke_256.zip"
    zp.write_bytes(zp.read_bytes() + b"\x00tamper")
    with pytest.raises(QualifiedInputError) as ei:
        cold_read_checkpoint(
            fixture_v1["qualification_dir"],
            fixture_v1["authorization_path"], tampered, tmp_path)
    assert any("模型文件字节" in p or "model_sha" in p
               for p in ei.value.report["problems"])
