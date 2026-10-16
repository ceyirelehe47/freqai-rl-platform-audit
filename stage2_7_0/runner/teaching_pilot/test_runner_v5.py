# -*- coding: utf-8 -*-
"""v5 两处合同小修的 stub 验收(仅三类;零真实 rollout/learn/
整套不重跑;FakeEnv.step 与真实 PPO 构造 spy 禁止)。"""
import json
import pathlib
import sys

import pytest
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import runner as RN  # noqa

SPEC = json.loads(
    (HERE / "run_spec.json").read_text(
        encoding="utf-8"))


class _FakeOptState(th.optim.Adam):
    """可定制 state_dict 的最小优化器(仅比较面)。"""

    def __init__(self, params, state=None,
                 lr=3e-4):
        super().__init__(params, lr=lr)
        if state is not None:
            self._custom = state

    def state_dict(self):
        if getattr(self, "_custom", None) \
                is not None:
            return self._custom
        return super().state_dict()


def test_A_optimizer_state_equal():
    t = th.arange(4, dtype=th.float32)
    sd_a = {"state": {0: {
        "step": th.tensor(3),
        "exp_avg": t.clone(),
        "exp_avg_sq": t.clone() * 2}},
        "param_groups": [{"lr": 3e-4,
                          "params": [0]}]}
    import copy
    sd_b = copy.deepcopy(sd_a)
    assert RN._optimizer_state_equal(
        sd_a, sd_b) is True
    # 同组数/step,exp_avg 不同 → False
    sd_c = copy.deepcopy(sd_a)
    sd_c["state"][0]["exp_avg"] = \
        t.clone() + 1.0
    assert RN._optimizer_state_equal(
        sd_a, sd_c) is False
    # exp_avg_sq 不同 → False
    sd_d = copy.deepcopy(sd_a)
    sd_d["state"][0]["exp_avg_sq"] = \
        t.clone() * 3
    assert RN._optimizer_state_equal(
        sd_a, sd_d) is False
    # lr 不同 → False
    sd_e = copy.deepcopy(sd_a)
    sd_e["param_groups"][0]["lr"] = 1e-3
    assert RN._optimizer_state_equal(
        sd_a, sd_e) is False
    # dtype/shape 不同 → False
    sd_f = copy.deepcopy(sd_a)
    sd_f["state"][0]["exp_avg"] = \
        t.double()
    assert RN._optimizer_state_equal(
        sd_a, sd_f) is False


class _FakeModelB:
    """B:纯赋值 env 步 17/model 17/_n_updates 3 再 raise。"""

    _pilot_stub = True

    def __init__(self, env, seed, spec):
        self.num_timesteps = 0
        self._n_updates = 0

    def learn(self, *a, **k):
        self.env_refs = None
        # 模拟 SB3 已推进计数后爆
        self.num_timesteps = 17
        self._n_updates = 3
        raise RuntimeError(
            "first cause boom")

    def save(self, path):
        th.save({"m": 1}, path + ".zip")


class _FakeEnvB:
    def __init__(self, rng=None):
        self.n_steps_env = 0
        self._bump = 0

    def reset(self, **kw):
        return None, {}

    def step(self, a):
        raise AssertionError(
            "FakeEnv.step hit")


def _fake_eval(ck, spec, tag, book,
               out_dir, env_factory=None):
    book.checkpoint("eval_" + tag)
    return {"tag": tag,
            "steps_used": 2112}


def test_B_partial_json_counters(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        RN, "build_real_ppo",
        lambda *a, **k: (
            _ for _ in ()
        ).throw(AssertionError(
            "real PPO build")))

    class _Env17(_FakeEnvB):
        def __init__(self, rng=None):
            super().__init__(rng)
            self.n_steps_env = 17

    out = tmp_path / "pb"
    with pytest.raises(RuntimeError,
                       match="first cause"):
        RN.run_pilot(
            str(out), SPEC,
            ppo_factory=lambda e, s, sp:
                _FakeModelB(e, s, sp),
            eval_fn=_fake_eval,
            env_factory=lambda r:
                _Env17(r))
    m = json.loads(
        (out / "pilot.json")
        .read_text(encoding="utf-8"))
    assert m["env_steps_train"] == 17
    assert m["learn_num_timesteps"] == 17
    assert m["ppo_n_updates_reported"] == 3
    assert "first cause" in m[
        "fail_reason"]
    assert (out /
            "FAILED.marker").exists()
    assert not (out /
                "DONE.marker").exists()
    assert (out /
            "partial_failure.zip"
            ).exists()
    assert m["partial_checkpoint"].endswith(
        "partial_failure.zip")
    assert m[
        "partial_forensics_only"] \
        is True


def test_C_partial_save_fail(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        RN, "build_real_ppo",
        lambda *a, **k: (
            _ for _ in ()
        ).throw(AssertionError(
            "real PPO build")))

    class _BadSave(_FakeModelB):
        def save(self, path):
            if "partial_failure" \
                    in path:
                raise OSError(
                    "disk dead")
            th.save({"m": 1},
                    path + ".zip")

    out = tmp_path / "pc"
    with pytest.raises(RuntimeError,
                       match="first cause"):
        RN.run_pilot(
            str(out), SPEC,
            ppo_factory=lambda e, s, sp:
                _BadSave(e, s, sp),
            eval_fn=_fake_eval,
            env_factory=lambda r:
                _FakeEnvB(r))
    m = json.loads(
        (out / "pilot.json")
        .read_text(encoding="utf-8"))
    assert "first cause" in m[
        "fail_reason"]
    assert "disk dead" in m.get(
        "partial_save_error", "")
    assert (out /
            "FAILED.marker").exists()
    assert not (out /
                "DONE.marker").exists()
