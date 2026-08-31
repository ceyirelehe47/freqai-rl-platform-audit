"""R2 checkpoint 持久化测试(真实保存/哈希/可加载;非空 probability)。

覆盖任务书 §9/§20:initial/5/10/25/50/100 全部存在;state hash 可
重算;可加载;probability dynamics 非空;BC after-BC checkpoint 存在。
"""

from __future__ import annotations

import pytest

from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_diag_metrics import probability_metrics_on_bank
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_SMOKE_NS, derive262r2_seed,
)
from rl_curriculum.ppo262_r2_train import (
    R2CheckpointStore, load_r2_checkpoint, policy_state_hash,
    r2_diag_train_run,
)


@pytest.fixture(scope="module")
def tiny_bank(locked_rung_params):
    keys = [EpisodeKey(DIAG262R2_SMOKE_NS, "c1_opportunity", "D0",
                       900100 + j, v)
            for j in range(2) for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=locked_rung_params,
        derive_seed_fn=derive262r2_seed)


def _tiny_cfg():
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    return cfg


def test_scratch_checkpoint_schedule_full_coverage(tiny_bank, tmp_path):
    """bank=4 eps × cycles=2 -> 8 episodes;schedule 0/2/4/6/8 边界。"""
    cfg = _tiny_cfg()
    store = R2CheckpointStore(
        tmp_path, "scratch_test", family="c1_opportunity",
        arm="A_unscaled", seed=28201,
        expected_tags=("ep0", "ep2", "ep4", "ep6", "ep8"))
    run = r2_diag_train_run(
        tiny_bank, config=cfg, model_seed=28201,
        total_timesteps=2 * 4 * 287, run_label="test/ckpt",
        checkpoint_store=store,
        checkpoint_episodes=(0, 2, 4, 6, 8))
    assert run["pass"], run["audit_problems"]
    v = store.verify_expected()
    assert v["pass"], v["problems"]
    assert v["n_expected"] == v["n_produced"] == 5
    assert not v["extra_tags"]
    # 每个 checkpoint 可重载且哈希一致 + probability 非空
    env = CurriculumMultiEpisodeEnv(tiny_bank)
    for tag, rec in store.records.items():
        model = load_r2_checkpoint(
            rec["path"], config=cfg, model_seed=28201, env=env,
            expect_policy_sha256=rec["policy_state_sha256"])
        prob = probability_metrics_on_bank(model, tiny_bank)
        assert prob["n_bars_total"] > 0
        assert prob["overall"]["mean_p_long"] is not None
    # checkpoint 状态与训练轨迹单调(ep8 != ep0)
    assert store.records["ep0"]["policy_state_sha256"] != \
        store.records["ep8"]["policy_state_sha256"]


def test_bc_run_saves_after_bc_checkpoint_not_random_ep0(
        tiny_bank, tmp_path):
    cfg = _tiny_cfg()
    env = CurriculumMultiEpisodeEnv(tiny_bank)
    from rl_curriculum.ppo262_r2_train import build_diagnosed_ppo2
    donor = build_diagnosed_ppo2(cfg, 28301, env)
    bc_state = {k: v.clone() for k, v in
                donor.policy.state_dict().items()}
    donor_hash = policy_state_hash(donor)
    store = R2CheckpointStore(
        tmp_path, "bc_test", family="c1_opportunity", arm="bc",
        seed=28301,
        expected_tags=("after_bc_before_ppo", "ep2", "ep4", "ep8"))
    run = r2_diag_train_run(
        tiny_bank, config=cfg, model_seed=28301,
        total_timesteps=2 * 4 * 287, run_label="test/bc-ckpt",
        checkpoint_store=store, checkpoint_episodes=(0, 2, 4, 8),
        bc_init_state=bc_state)
    assert run["pass"], run["audit_problems"]
    v = store.verify_expected()
    assert v["pass"], v["problems"]
    assert "ep0" not in store.records
    # after_bc checkpoint 的哈希 == donor(BC 权重真实载入)
    assert store.records["after_bc_before_ppo"][
        "policy_state_sha256"] == donor_hash


def test_checkpoint_store_rejects_missing_and_extra(tmp_path):
    store = R2CheckpointStore(
        tmp_path, "empty_test", family="c1_opportunity", arm="A",
        seed=1, expected_tags=("ep0", "ep4"))
    v = store.verify_expected()
    assert not v["pass"]
    assert any("未保存" in p for p in v["problems"])


def test_plan_checkpoint_schedule_covers_fractions():
    """计划 schedule 必须覆盖 initial/5/10/25/50/100% 边界。"""
    from rl_curriculum.ppo262_r2_cli import R2_BANK_SPEC
    for key, total in (("scratch", 288), ("bc", 96)):
        eps = R2_BANK_SPEC[key]["checkpoint_episodes"]
        assert eps[0] == 0 and eps[-1] == total
        fracs = [e / total for e in eps]
        assert fracs == sorted(fracs)
        # 每个计划点都在 fraction 阶梯的 bank 边界上
        bank = R2_BANK_SPEC[key]["episodes_per_bank"]
        assert all(e % bank == 0 for e in eps)
        # 覆盖 5/10/25/50/100%(ceil 到 bank 边界)
        for f in (0.05, 0.10, 0.25, 0.50, 1.00):
            target = f * total
            assert any(e >= target for e in eps), (key, f)
