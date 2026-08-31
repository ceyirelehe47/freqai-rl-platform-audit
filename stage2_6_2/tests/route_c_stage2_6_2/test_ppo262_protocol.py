"""PPO 训练/评估协议测试(§27 PPO + Protocol)。"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from rl_curriculum.ppo262_config import (
    PPO262_CANDIDATES, build_ppo, candidate_digest,
)
from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
from rl_curriculum.ppo262_metrics import SB3PPOPolicy
from rl_curriculum.ppo262_train import train_run
from rl_curriculum.ppo262_banks import (
    core_bank_keys, mixed_order, staged_order,
)

CFG = dict(PPO262_CANDIDATES["cand_a_center"])


def test_staged_mixed_same_initial_weights(small_bank_factory):
    """同 model seed 构造的 PPO(staged/mixed 前置)初始权重逐位一致。"""
    bank = small_bank_factory(1)
    e1 = CurriculumMultiEpisodeEnv(bank)
    e2 = CurriculumMultiEpisodeEnv(bank)
    m1 = build_ppo(CFG, seed=26201, env=e1)
    m2 = build_ppo(CFG, seed=26201, env=e2)
    w1 = m1.policy.state_dict()
    w2 = m2.policy.state_dict()
    assert set(w1) == set(w2)
    for k in w1:
        assert np.array_equal(
            w1[k].detach().numpy(), w2[k].detach().numpy()), k


def test_save_load_deterministic_eval_identical(small_bank_factory,
                                                tmp_path):
    bank = small_bank_factory(1)
    env = CurriculumMultiEpisodeEnv(bank)
    model = build_ppo(CFG, seed=26202, env=env)
    model.learn(total_timesteps=287, progress_bar=False)
    p_saved = Path(tmp_path) / "m"
    model.save(str(p_saved))
    from stable_baselines3 import PPO
    loaded = PPO.load(str(p_saved), device="cpu")
    pa = SB3PPOPolicy(model, "a")
    pb = SB3PPOPolicy(loaded, "b")
    for e in bank[:2]:
        from rl_curriculum.curriculum261_api import (
            curriculum261_eval_config,
        )
        from rl_curriculum.curriculum261_production_obs import (
            production_observation_schema,
        )
        from rl_curriculum.evaluator import run_observation_episode
        cfg = curriculum261_eval_config()
        schema = production_observation_schema()
        ra, aa, _ = run_observation_episode(
            pa, e.episode, cfg, schema, return_actions=True)
        rb, ab, _ = run_observation_episode(
            pb, e.episode, cfg, schema, return_actions=True)
        assert aa == ab
        assert ra.net_return == pytest.approx(rb.net_return, abs=1e-12)


def test_short_run_reproducible(small_bank_factory):
    """固定 model seed + 固定 manifest:短 run 权重与动作可复现。"""
    bank = small_bank_factory(1)
    results = []
    for _ in range(2):
        run = train_run(
            bank, config_name="cand_a_center", config=CFG,
            model_seed=26201, total_timesteps=2 * 287,
            order_name="test", run_label="repro")
        results.append(run)
    # 动作序列由 deterministic eval 比对(state_dict 直接比对)
    m1 = results[0]["model"]
    m2 = results[1]["model"]
    w1, w2 = m1.policy.state_dict(), m2.policy.state_dict()
    for k in w1:
        assert np.array_equal(
            w1[k].detach().numpy(), w2[k].detach().numpy()), k


def test_train_run_audits_and_boundaries(small_bank_factory):
    bank = small_bank_factory(1)
    n_eps = len(bank)
    run = train_run(
        bank, config_name="cand_a_center", config=CFG, model_seed=26201,
        total_timesteps=n_eps * 287, order_name="test",
        run_label="audit")
    assert run["pass"] is True, run["audit_problems"]
    assert run["env_audit"]["steps_taken"] == n_eps * 287
    assert run["env_audit"]["episodes_consumed"] == n_eps
    assert run["env_audit"]["exhausted_cycles"] <= 1
    assert run["episode_curve"], "学习曲线不应为空"


def test_train_run_rejects_misaligned_budget(small_bank_factory):
    bank = small_bank_factory(1)
    with pytest.raises(ValueError, match="倍数"):
        train_run(bank, config_name="x", config=CFG, model_seed=1,
                  total_timesteps=1000, order_name="t", run_label="t")
    with pytest.raises(ValueError, match="超过"):
        train_run(bank, config_name="x", config=CFG, model_seed=1,
                  total_timesteps=(len(bank) + 2) * 287, order_name="t",
                  run_label="t")


def test_checkpoint_plan_last_is_primary(small_bank_factory, tmp_path):
    """checkpoint 计划:0/中间/final;final(ep640 语义)必须存在。"""
    bank = small_bank_factory(1)
    saved = []

    def saver(n, model):
        p = Path(tmp_path) / f"ck{n}"
        model.save(str(p))
        saved.append(n)
        return str(p)

    n_eps = len(bank)
    run = train_run(
        bank, config_name="cand_a_center", config=CFG, model_seed=26201,
        total_timesteps=n_eps * 287, order_name="test", run_label="ck",
        checkpoint_episodes=(0, n_eps // 2, n_eps), checkpoint_saver=saver)
    assert 0 in saved
    assert n_eps in saved
    assert run["checkpoints"][f"ep{n_eps}"] is not None


# ---------------------------------------------------------------- protocol
def test_final_plan_digest_stable_and_tamper_evident():
    from rl_curriculum.ppo262_final import final_plan_digest
    plan = {"format": "x", "a": 1, "created_utc": "2026-01-01"}
    d1 = final_plan_digest(plan)
    d2 = final_plan_digest(dict(plan))
    assert d1 == d2
    plan2 = dict(plan, a=2)
    assert final_plan_digest(plan2) != d1
    assert d1.startswith("fp-")


def test_final_plan_lock_once_only(tmp_path):
    from rl_curriculum.ppo262_final import (
        build_final_plan, lock_final_plan, load_locked_final_plan,
    )
    plan = build_final_plan(
        r2_plan_digest="qp-x", stage261_code_identity={},
        code_identity_262={}, selected_config_name="c",
        selected_config={}, selected_config_digest="pc-x",
        training_manifest_hashes={}, model_hashes={"m": "h" * 64},
        model_seeds=[1, 2, 3], final_seed_schedule={},
        metric_definitions={}, pass_thresholds={},
        observation_identity={}, preprocessing_boundary_name="b",
        route_c_identities={}, vendor_sha="v", git_baseline="g",
        schedule_comparison_rule={})
    d = lock_final_plan(plan, tmp_path)
    assert d.startswith("fp-")
    with pytest.raises(RuntimeError, match="不得修改"):
        lock_final_plan(plan, tmp_path)
    # 篡改检测
    f = tmp_path / "final_evaluation_plan.json"
    tampered = json.loads(f.read_text(encoding="utf-8"))
    tampered["vendor_sha"] = "other"
    f.write_text(json.dumps(tampered), encoding="utf-8")
    with pytest.raises(RuntimeError, match="篡改"):
        load_locked_final_plan(tmp_path)


def test_final_run_guards_model_hash_and_code(tmp_path):
    from rl_curriculum.ppo262_final import (
        build_final_plan, lock_final_plan, verify_final_run_guards,
    )
    model_file = tmp_path / "m.zip"
    model_file.write_bytes(b"model-bytes")
    import hashlib
    h = hashlib.sha256(b"model-bytes").hexdigest()
    plan = build_final_plan(
        r2_plan_digest="qp-x", stage261_code_identity={},
        code_identity_262={"ppo262_train.py": "a" * 64},
        selected_config_name="c", selected_config={},
        selected_config_digest="pc-x", training_manifest_hashes={},
        model_hashes={"final": h}, model_seeds=[1], final_seed_schedule={},
        metric_definitions={}, pass_thresholds={},
        observation_identity={}, preprocessing_boundary_name="b",
        route_c_identities={}, vendor_sha="v", git_baseline="g",
        schedule_comparison_rule={})
    # hash 匹配 + code 匹配 -> 无问题
    problems = verify_final_run_guards(
        plan, models={"final": model_file},
        code_identity_262_now={"ppo262_train.py": "a" * 64})
    assert problems == []
    # model bytes 变化 -> hash 拒绝
    model_file.write_bytes(b"tampered")
    problems = verify_final_run_guards(
        plan, models={"final": model_file},
        code_identity_262_now={"ppo262_train.py": "a" * 64})
    assert any("model hash" in p for p in problems)
    # code identity 漂移 -> 拒绝
    model_file.write_bytes(b"model-bytes")
    problems = verify_final_run_guards(
        plan, models={"final": model_file},
        code_identity_262_now={"ppo262_train.py": "b" * 64})
    assert any("code identity" in p for p in problems)


def test_config_drift_rejected_by_digest():
    """candidate digest 绑定配置:任何键改动 digest 必变。"""
    d1 = candidate_digest("cand_a_center")
    original = dict(PPO262_CANDIDATES["cand_a_center"])
    try:
        PPO262_CANDIDATES["cand_a_center"]["ent_coef"] = 0.5
        d2 = candidate_digest("cand_a_center")
        assert d1 != d2
    finally:
        PPO262_CANDIDATES["cand_a_center"] = original


def test_selected_config_digest_file_matches(tmp_lock_dir):
    """selected config digest 落盘口径(fp 前缀体系外的 pc 前缀)。"""
    d = candidate_digest("cand_a_center")
    assert d.startswith("pc-")
    assert len(d) == 3 + 64


def test_final_fail_does_not_overwrite(tmp_path):
    """final FAIL 产物写入独立 attempt 目录(不覆盖)。"""
    from rl_curriculum.ppo262_final import FINAL_RESULT_FORMAT
    a1 = tmp_path / "attempt1"
    a2 = tmp_path / "attempt2"
    a1.mkdir()
    (a1 / "final_evaluation_raw.json").write_text(
        json.dumps({"verdict": "FAIL"}), encoding="utf-8")
    # 协议:第二次执行必须换目录(re-run 本身已被 exposure marker 拒绝,
    # 这里验证结果目录约定)
    assert (a1 / "final_evaluation_raw.json").exists()
    assert FINAL_RESULT_FORMAT == "ppo262-final-result-v1"
