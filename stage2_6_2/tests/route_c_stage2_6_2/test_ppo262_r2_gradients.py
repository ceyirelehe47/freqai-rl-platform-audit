"""R2 真实 PPO surrogate 梯度测试(单 minibatch 等价 + 语义一致)。

覆盖任务书 §10/§20:
- gradient 来自实际 PPO surrogate objective(clipped);
- 与手工单 minibatch reference 数值一致;
- advantage normalization 语义一致;
- clip 语义一致(post <= pre);
- entropy 项一致;
- pre/post clipping norm 记录;
- update/minibatch identity 齐全。
"""

from __future__ import annotations

import pytest
import torch

from rl_curriculum.ppo262_banks import EpisodeKey, generate262_bank
from rl_curriculum.ppo262_config import PPO262_CANDIDATES
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_r2_namespaces import (
    DIAG262R2_SMOKE_NS, derive262r2_seed,
)
from rl_curriculum.ppo262_r2_train import (
    build_diagnosed_ppo2, r2_diag_train_run,
)


@pytest.fixture(scope="module")
def tiny_bank(locked_rung_params):
    keys = [EpisodeKey(DIAG262R2_SMOKE_NS, "c1_opportunity", "D0",
                       900200 + j, v)
            for j in range(2) for v in ("A", "B")]
    return generate262_bank(
        keys, locked_plan_rung_params=locked_rung_params,
        derive_seed_fn=derive262r2_seed)


@pytest.fixture(scope="module")
def grad_run(tiny_bank):
    """2 updates(4 eps × 2 cycles = 2288 steps)带首 minibatch 捕获。"""
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    run = r2_diag_train_run(
        tiny_bank, config=cfg, model_seed=28201,
        total_timesteps=2 * 4 * 287, run_label="test/grad")
    assert run["pass"], run["audit_problems"]
    return run, cfg


def test_first_minibatch_equivalence(grad_run, tiny_bank):
    run, cfg = grad_run
    model = run["model"]
    cap = model.diag2_first_minibatch
    assert cap is not None
    rec = next(r for r in model.diag2_minibatch_records
               if r["minibatch_index"] == cap["minibatch_index"])
    # 同 seed 重建(初始权重逐位一致)+ 载入捕获的 pre-update 权重
    env = CurriculumMultiEpisodeEnv(tiny_bank)
    manual = build_diagnosed_ppo2(cfg, 28201, env)
    manual.policy.load_state_dict(cap["policy_state_before"])
    policy = manual.policy
    obs = torch.as_tensor(cap["observations"])
    actions = torch.as_tensor(cap["actions"]).long().flatten()
    old_log_prob = torch.as_tensor(cap["old_log_prob"])
    returns = torch.as_tensor(cap["returns"])
    adv = torch.as_tensor(cap["advantages_raw"]).clone()
    if cap["normalize_advantage"] and len(adv) > 1:
        adv = (adv - adv.mean()) / (adv.std() + 1e-8)
    values, log_prob, entropy = policy.evaluate_actions(obs, actions)
    values = values.flatten()
    ratio = torch.exp(log_prob - old_log_prob)
    eps = cap["clip_range"]
    policy_loss = -torch.min(
        adv * ratio, adv * torch.clamp(ratio, 1 - eps, 1 + eps)).mean()
    value_loss = torch.nn.functional.mse_loss(returns, values)
    entropy_loss = -torch.mean(entropy)
    loss = (policy_loss + cap["ent_coef"] * entropy_loss
            + cap["vf_coef"] * value_loss)
    policy.set_training_mode(True)
    policy.optimizer.zero_grad()
    loss.backward()

    def _norm(params):
        gs = [p.grad for p in params if p.grad is not None]
        return float(torch.sqrt(sum((g.detach() ** 2).sum() for g in gs)))

    actor = (list(policy.mlp_extractor.policy_net.parameters())
             + list(policy.action_net.parameters()))
    critic = (list(policy.mlp_extractor.value_net.parameters())
              + list(policy.value_net.parameters()))
    assert float(policy_loss.item()) == pytest.approx(
        rec["policy_loss"], rel=1e-5, abs=1e-7)
    assert float(value_loss.item()) == pytest.approx(
        rec["value_loss"], rel=1e-5, abs=1e-7)
    assert float(entropy_loss.item()) == pytest.approx(
        rec["entropy_loss"], rel=1e-5, abs=1e-7)
    assert float(loss.item()) == pytest.approx(
        rec["total_loss"], rel=1e-5, abs=1e-7)
    assert _norm(actor) == pytest.approx(
        rec["actor_total_grad_norm"], rel=1e-4, abs=1e-7)
    assert _norm(critic) == pytest.approx(
        rec["critic_total_grad_norm"], rel=1e-4, abs=1e-7)
    fp = policy.mlp_extractor.policy_net[0]
    manual_cols = [float(x) for x in
                   fp.weight.grad.detach().abs().mean(dim=0)]
    assert manual_cols == pytest.approx(
        rec["policy_first_layer_per_input_abs_grad"], rel=1e-3,
        abs=1e-9)


def test_advantage_normalization_semantics(grad_run):
    run, _ = grad_run
    for rec in run["minibatch_records"]:
        if rec["n_samples"] > 1:
            assert rec["advantage_normalized"]["mean"] == pytest.approx(
                0.0, abs=1e-5)
            assert rec["advantage_normalized"]["std"] == pytest.approx(
                1.0, rel=1e-3)


def test_clip_semantics_and_norms_recorded(grad_run):
    run, _ = grad_run
    assert run["minibatch_records"]
    for rec in run["minibatch_records"]:
        assert rec["pre_clip_total_grad_norm"] is not None
        assert rec["post_clip_total_grad_norm"] is not None
        # 裁剪只会缩小(或不动)总范数;容差吸收 float 求和顺序噪声
        assert rec["post_clip_total_grad_norm"] <= (
            rec["pre_clip_total_grad_norm"] * (1 + 1e-6) + 1e-9)
        assert rec["actor_total_grad_norm"] > 0
        assert rec["critic_total_grad_norm"] > 0
        # entropy 项在 loss 中(总 loss = policy + ent*entropy + vf*value)
        expect = (rec["policy_loss"] + rec["ent_coef"]
                  * rec["entropy_loss"] + rec["vf_coef"]
                  * rec["value_loss"])
        assert expect == pytest.approx(rec["total_loss"], rel=1e-4)


def test_minibatch_identity_complete_and_monotonic(grad_run):
    run, _ = grad_run
    cfg = dict(PPO262_CANDIDATES["cand_a_center"])
    recs = run["minibatch_records"]
    ids = [r["minibatch_index"] for r in recs]
    assert ids == sorted(ids) and len(set(ids)) == len(ids)
    for r in recs:
        assert {"update_index", "minibatch_index", "epoch",
                "minibatch_of_update", "env_step"} <= set(r)
    n_updates = len(run["update_records"])
    assert n_updates == (run["total_timesteps"] // cfg["n_steps"])
    assert len(recs) == n_updates * cfg["n_epochs"] * (
        cfg["n_steps"] // cfg["batch_size"])
    # update_index 与 minibatch 绑定一致
    for r in recs:
        assert 1 <= r["update_index"] <= n_updates


def test_bc_gradient_probe_is_not_used():
    """R1 的 -log_prob(action) 行为模仿式探针不得再出现于 R2 训练路径。"""
    import inspect

    import rl_curriculum.ppo262_r2_train as mod
    src = inspect.getsource(mod)
    assert "clipped surrogate" in src
    # DiagnosedPPO2.train 复制了 SB3 语义的关键结构
    assert "th.clamp(" in src
    assert "1 - clip_range, 1 + clip_range" in src
    assert "clip_grad_norm_" in src
    # 不得存在行为模仿式梯度探针(R1 缺陷路径)
    assert "def gradient_probe" not in src
    assert "actor_loss = -dist.log_prob(act_t).mean()" not in src
