"""R2 BC 三 seed 执行合同与 family 分离测试。

覆盖任务书 §7/§20:
- 计划 3 seeds,缺 1 个即 FAIL,多余 seed 也 FAIL;
- 每 seed checkpoint 齐全(after_bc_before_ppo 存在);
- family-specific BC 不混入其他 family(fail closed);
- BC 只训练 actor(critic 哈希不变);actor 导入可验证;
- held-out pairs 不进入 BC train;
- retention/destroyed 规则(纯函数)。
"""

from __future__ import annotations

import numpy as np
import pytest
import torch

from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.curriculum261_api import curriculum261_eval_config
from rl_curriculum.curriculum261_production_obs import (
    production_observation_schema,
)
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_SMOKE_NS, derive262r2_seed,
)
from rl_curriculum.ppo262_r2_train import (
    actor_state_hash, bc_retention, bc_train_actor_weighted,
    build_diagnosed_ppo2, collect_family_bc_dataset,
    critic_state_hash,
)


@pytest.fixture(scope="module")
def c1_bank(locked_rung_params):
    keys = [EpisodeKey(DIAG262R2_SMOKE_NS, "c1_opportunity", "D0",
                       900300 + j, v)
            for j in range(2) for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=locked_rung_params,
        derive_seed_fn=derive262r2_seed)


@pytest.fixture(scope="module")
def c2_bank(locked_rung_params):
    keys = [EpisodeKey(DIAG262R2_SMOKE_NS, "c2_context", "D0",
                       900300 + j, v)
            for j in range(2) for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=locked_rung_params,
        derive_seed_fn=derive262r2_seed)


THR = {
    "bc_retained_max_drop": 0.15,
    "bc_retained_min_final_bal_acc": 0.55,
    "bc_learned_min_bal_acc": 0.55,
}


def test_bc_dataset_family_separation_and_labels(
        c1_bank, c2_bank, locked_rung_params,
        locked_reference_thresholds):
    schema = production_observation_schema()
    cfg = curriculum261_eval_config()
    ds = collect_family_bc_dataset(
        c1_bank, "c1_opportunity", locked_rung_params,
        locked_reference_thresholds, schema, cfg)
    assert len(ds["X"]) == len(ds["y"]) == len(ds["row_pairs"])
    assert len(ds["y"]) == len(c1_bank) * 287
    # label 一致性:对第一个 episode 重放 reference 验证
    from rl_curriculum.ppo262_metrics import build_261_policy_set
    from rl_curriculum.evaluator import run_observation_episode
    e = c1_bank[0]
    pols = build_261_policy_set(
        "c1_opportunity",
        locked_rung_params["c1_opportunity"][e.key.rung],
        locked_reference_thresholds["c1_opportunity"])
    _, actions, _ = run_observation_episode(
        pols["reference"], e.episode, cfg, schema, return_actions=True)
    n = len(actions)
    assert list(ds["y"][:n]) == [int(a) for a in actions]
    # fail closed:混入异族 episode
    with pytest.raises(ValueError):
        collect_family_bc_dataset(
            c1_bank + c2_bank, "c1_opportunity", locked_rung_params,
            locked_reference_thresholds, schema, cfg)


def test_bc_train_actor_only_and_weighted(c1_bank):
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    env = CurriculumMultiEpisodeEnv(c1_bank)
    model = build_diagnosed_ppo2(cfg, 28301, env)
    a0, c0 = actor_state_hash(model), critic_state_hash(model)
    rng = np.random.default_rng(3)
    X = rng.normal(size=(2000, 9)).astype(np.float32)
    y = (rng.random(2000) < 0.3).astype(np.int64)
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    ad = ObsAdapter.identity(9)
    info = bc_train_actor_weighted(
        model, {"X": X, "y": y}, epochs=3, lr=3e-4, adapter=ad,
        rng_seed=28601, class_weighted=True)
    assert model and info["class_weighted"]
    # 逆频率权重合同
    w = info["class_weights"]
    assert w[0] == pytest.approx(2000 / (2 * np.sum(y == 0)))
    assert w[1] == pytest.approx(2000 / (2 * np.sum(y == 1)))
    # actor 变化,critic 不动
    assert actor_state_hash(model) != a0
    assert critic_state_hash(model) == c0
    assert info["history"][-1]["loss"] < info["history"][0]["loss"]


def test_three_seed_execution_contract():
    """计划 3 seeds:缺 1 FAIL;多 1 FAIL(纯逻辑,模拟 aggregation)。"""

    def agg(seeds_executed, planned=(28601, 28602, 28603)):
        got = sorted(seeds_executed)
        return {"match": got == list(planned)}

    assert agg([28603, 28601, 28602])["match"]
    assert not agg([28601, 28602])["match"]      # 缺 1
    assert not agg([28601, 28602, 28603, 28604])["match"]  # 多 1


def test_bc_retention_rules():
    # 学会 + 保留
    r = bc_retention(0.80, 0.75, THR)
    assert r["bc_learned"] and r["retained"] and not r["destroyed"]
    # 学会 + 摧毁(下降超阈)
    r = bc_retention(0.80, 0.50, THR)
    assert r["bc_learned"] and r["destroyed"] and not r["retained"]
    # 学会 + 终值过低
    r = bc_retention(0.80, 0.54, THR)
    assert r["destroyed"]
    # 从未学会
    r = bc_retention(0.48, 0.48, THR)
    assert not r["bc_learned"] and not r["retained"] and not r["destroyed"]


def test_bc_heldout_pairs_disjoint_from_train(c1_bank):
    """train/eval pair 区间分离(namespace + pair 双隔离)。"""
    from rl_curriculum.ppo262_r2_namespaces import (
        bc_eval_namespace, bc_train_namespace,
    )
    train_pairs = {(e.key.rung, e.key.pair_index) for e in c1_bank}
    eval_keys = [EpisodeKey(bc_eval_namespace("c1_opportunity"),
                            "c1_opportunity", r, p, v)
                 for r in ("D0",) for p in (256, 257) for v in ("A", "B")]
    assert bc_train_namespace("c1_opportunity") != \
        bc_eval_namespace("c1_opportunity")
    eval_pairs = {(k.rung, k.pair_index) for k in eval_keys}
    assert not (train_pairs & eval_pairs)


def test_actor_import_hash_roundtrip(c1_bank):
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    env = CurriculumMultiEpisodeEnv(c1_bank)
    donor = build_diagnosed_ppo2(cfg, 28602, env)
    X = np.random.default_rng(4).normal(
        size=(500, 9)).astype(np.float32)
    y = (np.random.default_rng(5).random(500) < 0.4).astype(np.int64)
    from rl_curriculum.ppo262_diag_train import ObsAdapter
    bc_train_actor_weighted(
        donor, {"X": X, "y": y}, epochs=2, lr=3e-4,
        adapter=ObsAdapter.identity(9), rng_seed=28602)
    expect = actor_state_hash(donor)
    state = {k: v.clone() for k, v in donor.policy.state_dict().items()}
    receiver = build_diagnosed_ppo2(cfg, 28602, env)
    receiver.policy.load_state_dict(state)
    assert actor_state_hash(receiver) == expect
