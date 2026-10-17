# -*- coding: utf-8 -*-
"""seed_contrast v4 微测(旧 v1/v2/v3 保留不重跑)。

登记(v3 已发生:**2 次 TL 一 bar 生成+9 个真 ledger bar+两批
随机未训练 Linear 读出**——后者是未训练随机权重的 forward,
不得误称"训练权重前向";不重跑旧批,后续手写注入)。
本件:原生 callback 包裹计数/真实 _real_build_b 接线 spy/
RUNSPEC SHA 门/post_save 顺序。零 learn/零 env.step。
"""
import json
import pathlib
import random
import sys

import pytest
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(
    0, "/mnt/f/trading/"
       "teaching_pilot_prep_20261016")

import seed_contrast as SC  # noqa
import runner as R5  # noqa
import teach_env as TE  # noqa

SPEC = json.loads(
    (HERE / "RUNSPEC_SEED.json")
    .read_text(encoding="utf-8"))


class _FakeEnvCB:
    def __init__(self):
        self.n_steps_env = 0


class _FakeModel:
    def __init__(self):
        self.policy = None
        self.num_timesteps = 0


class _Book:
    def checkpoint(self, ph):
        return None, {}, {}


def test_native_callback_wrap_counting():
    """原生 BaseCallback+包裹:生命周期方法在;计数幂等;
    经济失败仍拒;cap 只记实际增量;首因不被覆盖。"""
    env = _FakeEnvCB()
    rep = {}
    led = SC.StepLedger(3, rep)   # cap=3
    cbk = R5._make_guard_callback(
        _Book(), env)
    counter = SC._EnvCounter(env, led)
    SC._attach_counter(cbk, counter)
    # 生命周期保留
    for meth in ("on_training_start",
                 "on_rollout_start",
                 "on_step",
                 "on_rollout_end",
                 "on_training_end",
                 "update_locals",
                 "init_callback"):
        assert hasattr(cbk, meth), meth
    cbk.model = _FakeModel()
    # 2→4:只记 2(非 4/6)
    env.n_steps_env = 2
    cbk.update_locals(
        {"infos": [{"reward_valid": True}]})
    assert cbk.on_step() is True
    assert led.total == 2      # 实际 2(cap3 内)
    # 2→4 超 cap:sync 先记实际 2(total=4)再抛(单次,非 6)
    env.n_steps_env = 4
    cbk.update_locals(
        {"infos": [{"reward_valid": True}]})
    with pytest.raises(RuntimeError):
        cbk.on_step()
    assert led.total == 4      # 只记实际增量,不双加
    # 经济失败仍拒(R5 guard 语义)
    env2 = _FakeEnvCB()
    led2 = SC.StepLedger(100, {})
    cbk2 = R5._make_guard_callback(
        _Book(), env2)
    c2 = SC._EnvCounter(env2, led2)
    SC._attach_counter(cbk2, c2)
    cbk2.model = _FakeModel()
    cbk2.update_locals({"infos": [{
        "economic_failure":
            {"phase": "open"}}]})
    with pytest.raises(RuntimeError,
                       match="economic"):
        cbk2.on_step()
    # 失败路径:首因固定后同步,二次 sync 幂等不加
    led3 = SC.StepLedger(1000, {})
    env3 = _FakeEnvCB()
    env3.n_steps_env = 10
    c3 = SC._EnvCounter(env3, led3)
    c3.sync()      # 基线=10,delta0
    assert led3.total == 0
    env3.n_steps_env = 15
    c3.sync()
    c3.sync()      # 重复同步幂等
    assert led3.total == 5   # 只记增量


def test_real_build_b_wiring_spy(monkeypatch):
    """手写 TE/runner spy 调**真实** _real_build_b:
    env seed=eff_B['seeds']['train_env'](311002)。"""
    got = {}

    class _SpyEnv:
        def __init__(self, rng):
            got["env_rng_seed"] = \
                rng.getrandbits(32)

    class _M:
        pass

    def spy_build(env, seed, p_spec):
        got["torch_init"] = seed
        got["env_type"] = type(env).__name__
        return _M()

    monkeypatch.setattr(
        TE, "UnifiedPilotEnv", _SpyEnv)
    monkeypatch.setattr(
        R5, "build_real_ppo", spy_build)
    eff = json.loads(json.dumps(
        json.load(open(
            "/mnt/f/trading/"
            "teaching_pilot_prep_20261016/"
            "run_spec.json",
            encoding="utf-8"))))
    eff["seeds"]["train_env"] = 311002
    out = SC._real_build_b(eff, eff)
    assert type(out).__name__ == "_M"
    assert type(out.pilot_env).__name__ \
        == "_SpyEnv"
    assert got["torch_init"] == 20261016
    assert got["env_type"] == "_SpyEnv"
    # SpyEnv 收到的 rng=Random(311002)
    r = random.Random(311002)
    assert got["env_rng_seed"] == \
        r.getrandbits(32)


def test_runspec_sha_gate(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {**SPEC,
             "seeds": {
                 **SPEC["seeds"],
                 "train_env_B":
                     311003}}),
        encoding="utf-8")
    out = tmp_path / "g"
    with pytest.raises(RuntimeError,
                       match="RUNSPEC SHA"):
        SC.run(
            str(out), str(bad),
            loader=lambda p: None,
            builder=lambda s, p: None,
            learner=lambda m, t, r,
                callback=None: None,
            clock=(lambda: 0.0,
                   lambda: 0.0))
    assert (out / "FAILED.marker"
            ).exists()


def test_diag_pin_constant():
    import hashlib
    p = pathlib.Path(
        "/mnt/f/trading/"
        "diag_panel_prep_20261016/"
        "diag_panel.py")
    if p.exists():
        got = hashlib.sha256(
            p.read_bytes()).hexdigest()
        assert got == SC.DIAG_PANEL_SHA256


def test_status():
    assert SC.STATUS == "PREPARED_NOT_RUN"
