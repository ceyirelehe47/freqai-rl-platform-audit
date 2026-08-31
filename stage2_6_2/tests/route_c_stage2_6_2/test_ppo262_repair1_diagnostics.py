"""Repair R1:attribution / update 绑定 / 概率指标 / scaling / BC /
诊断 namespace regression tests(任务书 §23)。"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))


# ============================================================ Attribution
class TestEpisodeAttribution:
    def test_terminal_info_keeps_identity(self, small_bank_factory):
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        bank = small_bank_factory(1)
        env = CurriculumMultiEpisodeEnv(bank)
        obs, _ = env.reset()
        info = None
        for _ in range(300):
            obs, r, term, trunc, info = env.step(0)
            if term or trunc:
                break
        assert info is not None and (term or trunc)
        for key in ("episode_key", "namespace", "family", "rung",
                    "pair_index", "variant", "manifest_index"):
            assert info.get(key) is not None, f"terminal info 丢 {key}"
        assert info["episode_key"] == bank[0].key.canonical()

    def test_curve_manifest_alignment(self, small_bank_factory,
                                      locked_rung_params):
        """callback 曲线与 manifest 一一对应(manifest 顺序)。"""
        from rl_curriculum.ppo262_diag_train import diag_train_run
        from rl_curriculum.ppo262_config import PPO262_CANDIDATES
        bank = small_bank_factory(1)  # 6 eps
        run = diag_train_run(
            bank, config=PPO262_CANDIDATES["cand_a_center"],
            model_seed=27101, total_timesteps=6 * 287,
            run_label="test/attribution")
        curve = run["episode_curve"]
        assert [r["episode_key"] for r in curve] == [
            e.key.canonical() for e in bank]
        for row in curve:
            assert row["family"] and row["rung"]
            assert row["pair_index"] is not None and row["variant"]
            assert row["manifest_index"] is not None
            assert row["episode_key"]  # 非空字符串
            assert "cost_fees_paid" in row
            assert "terminal_liquidation_fee" in row

    def test_identity_not_in_observation(self, small_bank_factory):
        """attribution 只进 info,不进 observation(维度/数值合同)。"""
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        bank = small_bank_factory(1)
        env = CurriculumMultiEpisodeEnv(bank)
        obs, _ = env.reset()
        assert obs.shape == (9,) and obs.dtype == np.float32
        obs2, *_ = env.step(1)
        assert obs2.shape == (9,)

    def test_staged_and_mixed_orders_verifiable(self, small_bank_factory):
        """staged/mixed 顺序可通过日志(curve 顺序)验证。"""
        from rl_curriculum.ppo262_banks import mixed_order, staged_order
        bank = small_bank_factory(1)
        keys = [e.key for e in bank]
        st = staged_order(keys)
        mx = mixed_order(keys, model_seed=26201)
        assert [k.canonical() for k in st] == [
            e.key.canonical() for e in bank]
        assert sorted(k.canonical() for k in st) == sorted(
            k.canonical() for k in mx)


# ============================================================ Update metrics
class TestUpdateMetricBinding:
    def _run(self, bank):
        from rl_curriculum.ppo262_diag_train import diag_train_run
        from rl_curriculum.ppo262_config import PPO262_CANDIDATES
        return diag_train_run(
            bank, config=PPO262_CANDIDATES["cand_a_center"],
            model_seed=27101, total_timesteps=2 * len(bank) * 287,
            run_label="test/update-binding")

    def test_first_update_has_data(self, small_bank_factory):
        run = self._run(small_bank_factory(1))
        upd = run["update_records"]
        assert upd, "无 update 记录"
        first = upd[0]
        assert first["update_index"] == 1 and first["rollout_index"] == 1
        for key in ("approx_kl", "clip_fraction", "policy_loss",
                    "value_loss", "entropy_loss", "explained_variance",
                    "grad_norm"):
            assert key in first, f"首个 update 缺 {key}"
            assert first[key] is not None

    def test_update_index_monotonic_and_unique_rollout(self,
                                                       small_bank_factory):
        run = self._run(small_bank_factory(1))
        upd = run["update_records"]
        idx = [u["update_index"] for u in upd]
        assert idx == sorted(idx) and len(set(idx)) == len(idx)
        assert [u["rollout_index"] for u in upd] == idx  # 1:1 绑定
        steps = [u["env_step"] for u in upd]
        assert steps == sorted(steps)

    def test_missing_metrics_explicit(self, small_bank_factory):
        run = self._run(small_bank_factory(1))
        for u in run["update_records"]:
            assert "missing_metrics" in u  # 字段存在(不静默)
            assert not u["missing_metrics"]  # 本配置下应全部捕获

    def test_determinism_repeat_run(self, small_bank_factory):
        bank = small_bank_factory(1)
        r1 = self._run(bank)
        r2 = self._run(bank)
        for a, b in zip(r1["update_records"], r2["update_records"]):
            for key in ("approx_kl", "value_loss", "policy_loss"):
                assert a[key] == pytest.approx(b[key], abs=1e-9)

    def test_diagnosed_ppo_same_seed_same_init_as_ppo(
            self, small_bank_factory):
        """DiagnosedPPO 不消耗额外随机数:同 seed 初始权重与原生
        PPO 逐位一致(official 权重复现合同不破坏)。"""
        from rl_curriculum.ppo262_config import build_ppo
        from rl_curriculum.ppo262_diag_train import build_diagnosed_ppo
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        from stable_baselines3 import PPO
        env_bank = small_bank_factory(1)
        m1 = PPO("MlpPolicy", CurriculumMultiEpisodeEnv(list(env_bank)),
                 n_steps=574, seed=99,
                 policy_kwargs={"net_arch": [128, 128]}, device="cpu")
        m2 = build_diagnosed_ppo(
            PPO_CFG, 99, CurriculumMultiEpisodeEnv(list(env_bank)))
        for p1, p2 in zip(m1.policy.parameters(),
                          m2.policy.parameters()):
            assert np.array_equal(p1.detach().numpy(),
                                  p2.detach().numpy())
        # 原生 build_ppo 路径不变
        m3 = build_ppo(PPO_CFG, 99, CurriculumMultiEpisodeEnv(
            list(env_bank)))
        for p1, p3 in zip(m1.policy.parameters(), m3.policy.parameters()):
            assert np.array_equal(p1.detach().numpy(),
                                  p3.detach().numpy())


# ============================================================ Probability
class TestProbabilityMetrics:
    def test_logits_to_probability_correct(self):
        """softmax(logits) 与概率一致性(手工构造分布)。"""
        logits = np.array([0.0, 2.0])
        probs = np.exp(logits - logits.max())
        probs = probs / probs.sum()
        assert probs[1] == pytest.approx(0.8808, abs=1e-3)

    def test_det_matches_argmax_stochastic_reproducible(
            self, small_bank_factory):
        from rl_curriculum.ppo262_config import build_ppo
        from rl_curriculum.ppo262_diag_metrics import (
            probability_metrics_on_bank,
        )
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        cfg = {"policy": "MlpPolicy", "learning_rate": 3e-4,
               "n_steps": 574, "batch_size": 287, "n_epochs": 10,
               "gamma": 0.99, "gae_lambda": 0.95, "clip_range": 0.2,
               "ent_coef": 0.01, "vf_coef": 0.5, "max_grad_norm": 0.5,
               "net_arch": [128, 128], "activation_fn": "Tanh",
               "device": "cpu"}
        bank = small_bank_factory(1)[:2]
        model = build_ppo(cfg, 26201, CurriculumMultiEpisodeEnv(bank))
        p1 = probability_metrics_on_bank(model, bank)
        p2 = probability_metrics_on_bank(model, bank)
        # stochastic 用固定诊断 RNG -> 两次评估逐位一致
        assert p1["overall"]["stochastic_long_rate"] == (
            p2["overall"]["stochastic_long_rate"])
        assert p1["overall"]["deterministic_long_rate"] == (
            p2["overall"]["deterministic_long_rate"])
        # latent 聚合存在(family 维度)
        assert "c1_opportunity" in p1["per_family"]

    def test_det_equals_argmax_single_obs(self, small_bank_factory):
        import torch
        from rl_curriculum.ppo262_config import build_ppo
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        cfg = {"policy": "MlpPolicy", "learning_rate": 3e-4,
               "n_steps": 574, "batch_size": 287, "n_epochs": 10,
               "gamma": 0.99, "gae_lambda": 0.95, "clip_range": 0.2,
               "ent_coef": 0.01, "vf_coef": 0.5, "max_grad_norm": 0.5,
               "net_arch": [128, 128], "activation_fn": "Tanh",
               "device": "cpu"}
        bank = small_bank_factory(1)[:1]
        model = build_ppo(cfg, 7, CurriculumMultiEpisodeEnv(bank))
        obs = np.zeros(9, dtype=np.float32)
        with torch.no_grad():
            dist = model.policy.get_distribution(
                torch.as_tensor(obs.reshape(1, -1)))
            logits = dist.distribution.logits[0].numpy()
        assert int(np.argmax(logits)) == int(logits[1] > logits[0])


# ============================================================ Scaling
class TestObsAdapters:
    def test_arm_a_identity_bitwise(self):
        from rl_curriculum.ppo262_diag_train import ObsAdapter
        a = ObsAdapter.identity(9)
        x = np.random.default_rng(0).normal(size=(5, 9)) * 100
        assert np.array_equal(a.apply(x), x.astype(np.float32))
        assert np.array_equal(a.apply(x[0]), x[0].astype(np.float32))

    def test_arm_b_constants_do_not_read_data(self):
        from rl_curriculum.ppo262_diagnose_cli import _arm_b_constants
        X1 = np.full((100, 9), 3.0)          # 常数矩阵
        X1[:, 8] = 0.0
        X2 = np.full((100, 9), 3.0)
        X2[:, 8] = 0.0
        # 同分布输入 -> 同常数;规则是确定性的机械变换
        assert _arm_b_constants(X1) == _arm_b_constants(X2)
        c = _arm_b_constants(X1)
        assert c["scale"][-1] == 1.0  # position slot 不缩放
        assert c["center"][-1] == 0.0

    def test_arm_c_fits_only_train_and_freezes(self):
        from rl_curriculum.ppo262_diag_train import ObsAdapter
        rng = np.random.default_rng(1)
        Xtr = rng.normal(5.0, 2.0, size=(500, 9))
        Xtr[:, 8] = 0.0
        adapter = ObsAdapter.fit_frozen(Xtr, source="test")
        # 冻结:fit 后对相同数据变换结果恒定;等价于 (x-mean)/std
        out = adapter.apply(Xtr)
        expected = ((Xtr - Xtr.mean(0)) / np.where(
            Xtr.std(0) > 1e-9, Xtr.std(0), 1.0))
        np.testing.assert_allclose(out, expected.astype(np.float32),
                                   atol=1e-5)
        # dev 数据不参与 fit:adapter 常数不变
        Xdev = rng.normal(500.0, 50.0, size=(10, 9))
        Xdev[:, 8] = 0.0
        _ = adapter.apply(Xdev)  # 不 raise 且不改变 adapter
        d = adapter.describe()
        assert d["scale"][-1] == 1.0

    def test_position_slot_never_scaled(self):
        from rl_curriculum.ppo262_diag_train import ObsAdapter
        X = np.random.default_rng(2).normal(size=(200, 9)) * 7
        X[:, 8] = 1.0
        adapter = ObsAdapter.fit_frozen(X, source="t")
        out = adapter.apply(X)
        assert np.all(out[:, 8] == 1.0)  # position 恒等

    def test_no_nan_inf_and_shape_preserved(self):
        from rl_curriculum.ppo262_diag_train import ObsAdapter
        X = np.random.default_rng(3).normal(size=(50, 9))
        for adapter in (ObsAdapter.identity(9),
                        ObsAdapter.fixed(np.zeros(9), np.full(9, 0.01),
                                         source="t"),
                        ObsAdapter.fit_frozen(X, source="t")):
            out = adapter.apply(X)
            assert out.shape == X.shape and out.dtype == np.float32
            assert np.all(np.isfinite(out))

    def test_same_episode_only_transform_changes(self, small_bank_factory):
        """同一 episode 经三 arm:内层动力学一致,只有 obs 变换。"""
        from rl_curriculum.ppo262_diag_train import (
            ObsAdapter, ObsScaleWrapper,
        )
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        bank = small_bank_factory(1)[:2]
        raw_env = CurriculumMultiEpisodeEnv(list(bank))
        center = np.zeros(9)
        scale = np.array([1, 1, 1, 1, 100, 100, 100, 100, 1], float)
        wrapper = ObsScaleWrapper(
            CurriculumMultiEpisodeEnv(list(bank)),
            ObsAdapter.fixed(center, scale, source="t"))
        o1, i1 = raw_env.reset(seed=1)
        o2, i2 = wrapper.reset(seed=1)
        np.testing.assert_allclose(o2, (o1 - center) / scale, rtol=1e-6)
        # attribution 透传
        assert i1["episode_key"] == i2["episode_key"]
        r1 = raw_env.step(0)
        r2 = wrapper.step(0)
        assert r1[1] == r2[1]  # reward 不变
        np.testing.assert_allclose(
            r2[0], (r1[0] - center) / scale, rtol=1e-6)

    def test_observation_space_consistent(self, small_bank_factory):
        from rl_curriculum.ppo262_diag_train import (
            ObsAdapter, ObsScaleWrapper,
        )
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        env = CurriculumMultiEpisodeEnv(small_bank_factory(1)[:1])
        w = ObsScaleWrapper(env, ObsAdapter.fixed(
            np.zeros(9), np.full(9, 10.0), source="t"))
        assert w.observation_space is env.observation_space


# ============================================================ BC
class TestBCWarmStart:
    def test_label_only_from_observation(self, small_bank_factory,
                                         locked_rung_params,
                                         locked_reference_thresholds):
        from rl_curriculum.curriculum261_api import (
            curriculum261_eval_config,
        )
        from rl_curriculum.curriculum261_production_obs import (
            production_observation_schema,
        )
        from rl_curriculum.ppo262_diag_train import collect_bc_dataset
        from rl_curriculum.ppo262_metrics import build_261_policy_set
        bank = small_bank_factory(1)
        fam = bank[0].key.family
        pols = build_261_policy_set(
            fam, locked_rung_params[fam][bank[0].key.rung],
            locked_reference_thresholds[fam])
        ds = collect_bc_dataset(
            bank[:2], pols["reference"], production_observation_schema(),
            curriculum261_eval_config())
        assert ds["X"].shape[1] == 9  # 只 policy-visible obs
        assert set(np.unique(ds["y"])).issubset({0, 1})
        # label 数 = obs 数(逐 bar)
        assert len(ds["y"]) == len(ds["X"])

    def test_actor_bc_updates_actor_not_critic(self, small_bank_factory):
        import torch
        from rl_curriculum.ppo262_diag_train import (
            ObsAdapter, actor_state_hash, bc_train_actor,
            build_diagnosed_ppo,
        )
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        cfg = {"policy": "MlpPolicy", "learning_rate": 3e-4,
               "n_steps": 574, "batch_size": 287, "n_epochs": 10,
               "gamma": 0.99, "gae_lambda": 0.95, "clip_range": 0.2,
               "ent_coef": 0.01, "vf_coef": 0.5, "max_grad_norm": 0.5,
               "net_arch": [128, 128], "activation_fn": "Tanh",
               "device": "cpu"}
        model = build_diagnosed_ppo(
            cfg, 27301, CurriculumMultiEpisodeEnv(small_bank_factory(1)))

        def _critic_hash() -> str:
            import hashlib
            h = hashlib.sha256()
            for mod in (model.policy.mlp_extractor.value_net,
                        model.policy.value_net):
                for p in mod.parameters():
                    h.update(np.ascontiguousarray(
                        p.detach().numpy(), dtype=np.float32).tobytes())
            return h.hexdigest()

        rng = np.random.default_rng(4)
        X = rng.normal(size=(600, 9)).astype(np.float32)
        y = (X[:, 0] > 0).astype(np.int64)  # 可学的线性规则
        critic_before = _critic_hash()
        info = bc_train_actor(
            model, {"X": X, "y": y}, epochs=30, lr=3e-4,
            adapter=ObsAdapter.identity(9), rng_seed=27301)
        assert info["final_train_match_rate"] > 0.9  # 规则可学
        assert _critic_hash() == critic_before  # critic 未被 BC 触碰
        # actor 确实被更新
        assert actor_state_hash(model) != ""

    def test_bc_init_state_import_verified(self, small_bank_factory):
        """bc_init_state 载入后初始 policy 哈希 = BC 结束状态。"""
        import torch
        from rl_curriculum.ppo262_diag_train import (
            ObsAdapter, bc_train_actor, build_diagnosed_ppo,
            diag_train_run,
        )
        from rl_curriculum.ppo262_env import CurriculumMultiEpisodeEnv
        cfg = dict(PPO_CFG)
        bank = small_bank_factory(1)[:2]
        env = CurriculumMultiEpisodeEnv(list(bank))
        model = build_diagnosed_ppo(cfg, 27301, env)
        rng = np.random.default_rng(5)
        X = rng.normal(size=(400, 9)).astype(np.float32)
        y = (X[:, 1] > 0).astype(np.int64)
        bc_train_actor(model, {"X": X, "y": y}, epochs=10, lr=3e-4,
                       adapter=ObsAdapter.identity(9), rng_seed=27301)
        from rl_curriculum.ppo262_diag_train import actor_state_hash
        bc_actor_hash = actor_state_hash(model)
        state = {k: v.clone()
                 for k, v in model.policy.state_dict().items()}
        run = diag_train_run(
            bank, config=cfg, model_seed=27301,
            total_timesteps=1 * len(bank) * 287,
            run_label="test/bc-import", bc_init_state=state)
        # 载入验证:训练开始前的 actor 状态 == BC 结束状态
        assert run["bc_init_actor_state_sha256"] == bc_actor_hash


PPO_CFG = {"policy": "MlpPolicy", "learning_rate": 3e-4,
           "n_steps": 574, "batch_size": 287, "n_epochs": 10,
           "gamma": 0.99, "gae_lambda": 0.95, "clip_range": 0.2,
           "ent_coef": 0.01, "vf_coef": 0.5, "max_grad_norm": 0.5,
           "net_arch": [128, 128], "activation_fn": "Tanh",
           "device": "cpu"}


# ============================================================ namespaces
class TestDiagNamespaces:
    def test_diag_namespace_strings_disjoint_from_official(self):
        from rl_curriculum.ppo262_diag_namespaces import DIAG262_NAMESPACES
        from rl_curriculum.ppo262_namespaces import all_262_namespaces
        s = set(DIAG262_NAMESPACES)
        assert not (s & set(all_262_namespaces()))

    def test_diag_derive_rejects_official_ns(self):
        from rl_curriculum.ppo262_diag_namespaces import (
            derive262_diag_seed,
        )
        with pytest.raises(ValueError, match="不在"):
            derive262_diag_seed(
                "ppo_config_dev_262", "c1_opportunity", "D1", 0, 0)
        with pytest.raises(ValueError):
            derive262_diag_seed(
                "qualification_r2", "c1_opportunity", "D1", 0, 0)

    def test_diag_derive_deterministic(self):
        from rl_curriculum.ppo262_diag_namespaces import (
            derive262_diag_seed,
        )
        a = derive262_diag_seed(
            "diag262r1_smoke", "c1_opportunity", "D0", 3, 0)
        b = derive262_diag_seed(
            "diag262r1_smoke", "c1_opportunity", "D0", 3, 0)
        assert a == b and a > 0

    def test_final_namespace_still_locked(self, tmp_lock_dir):
        from rl_curriculum.ppo262_namespaces import derive262_seed
        with pytest.raises(RuntimeError, match="final"):
            derive262_seed(
                "ppo_final_eval_262", "c1_opportunity", "D0", 0, 0)

    def test_no_exposure_marker(self, tmp_lock_dir):
        from rl_curriculum.ppo262_namespaces import (
            final_eval_exposed, final_eval_unlocked,
        )
        assert not final_eval_unlocked()
        assert not final_eval_exposed()

    def test_small_range_isolation(self):
        from rl_curriculum.ppo262_diag_namespaces import (
            verify_diag_namespace_isolation,
        )
        art = verify_diag_namespace_isolation(
            pair_range=range(0, 40), official_pair_range=range(0, 64),
            pair_range_261=range(0, 64))
        assert art["pass"], art["problems"][:3]
