# -*- coding: utf-8 -*-
"""seed_extend 微测(零经济步:零 env.step/零 learn 真件;
stub replay/continue;真 gate 逻辑全走)。"""
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
       "seed_contrast_prep_20261016")
sys.path.insert(
    0, "/mnt/f/trading/"
       "teaching_pilot_prep_20261016")

import seed_extend as SX  # noqa
import seed_contrast as SC  # noqa
import runner as R5  # noqa

SPEC = json.loads(
    (HERE / "RUNSPEC_EXT.json")
    .read_text(encoding="utf-8"))


class _Env:
    def __init__(self):
        self.n_steps_env = 0
        self.rng = random.Random(0)


class _Opt:
    def state_dict(self):
        return {"param_groups": [1],
                "state": {}}

    param_groups = []

    def step(self, *a, **k):
        return None


class _P:
    def __init__(self):
        self._sd = {"k": th.zeros(1)}
        self._opt = _Opt()

    def set_training_mode(self, m):
        pass

    def state_dict(self):
        return dict(self._sd)

    @property
    def optimizer(self):
        return self._opt


class _Model:
    _pilot_stub = True

    def __init__(self):
        self.policy = _P()
        self.num_timesteps = 0
        self._n_updates = 0
        self.pilot_env = _Env()

    def learn(self, total_timesteps,
              reset_num_timesteps=True,
              callback=None, **k):
        if reset_num_timesteps:
            self.num_timesteps = total_timesteps
            self._n_updates = 320
            self.pilot_env.n_steps_env = total_timesteps
        else:
            self.num_timesteps = total_timesteps
            self._n_updates = 640
            self.pilot_env.n_steps_env = total_timesteps

    def save(self, p):
        th.save({}, p + ".zip")


def test_boundary_mismatch_stops(tmp_path):
    """权重不同 → 边界拒,零续训零评价。"""
    out = tmp_path / "m"
    m = _Model()
    sig_ref = SC.fresh_signature(m)

    def replay(model, total, r, led, bk):
        model.num_timesteps = 32768
        model._n_updates = 320
        model.pilot_env.n_steps_env = 32768
        model.policy._sd = {
            "k": th.ones(1)}   # 异权重
    cont = {"n": 0}

    def cont_learn(mm, t, r, led, bk):
        cont["n"] += 1
    with pytest.raises(RuntimeError,
                       match="boundary"):
        SX.run(
            str(out),
            loader=lambda p: _Model(),
            builder=lambda s, p: m,
            replay_learner=replay,
            continue_learner=cont_learn,
            clock=(lambda: 0.0,
                   lambda: 0.0),
            eval_runner=lambda *a:
                (_ for _ in ()).throw(
                    AssertionError(
                        "eval at/after "
                        "mismatch")),
            panel_fn=lambda mm: {
                "rows": [1] * 4},
            initial_sig_ref=sig_ref)
    assert cont["n"] == 0
    rep = json.loads(
        (out / "extend.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert (out / "FAILED.marker"
            ).exists()


def test_full_stub_flow_and_rng(
        tmp_path):
    """匹配→续训→末端评价 2112 桩+4 行+RNG 快照
    可恢复(逐位);总步账恰 67648。"""
    m = _Model()
    sig_ref = SC.fresh_signature(m)
    eval_calls = {"n": 0, "steps": 0}

    def replay(model, total, r, led,
               bk):
        model.num_timesteps = 32768
        model._n_updates = 320
        model.pilot_env.n_steps_env = \
            32768
        model._pilot_opt_count = {"n": 1280}
        led.add(32768, "replay_stub")

    def cont_learn(model, total, r,
                   led, bk):
        assert total == 32768   # 追加量语义
        model.num_timesteps += total   # SB3 累计
        model.pilot_env.n_steps_env = 65536
        model._n_updates = 640
        model._pilot_opt_count = {"n": 2560}
        led.add(32768, "continue_stub")   # 模拟 helper 计数

    def eval_runner(mm, tr, r, tag,
                    lg, bk):
        eval_calls["n"] += 1
        r[tag + "_episodes"] = [
            {"index": i}
            for i in range(128)]
        r["steps"][tag] = 2112
        for _ in range(2112):
            lg.add(1, tag)
        eval_calls["steps"] = 2112
        return 2112
    out = tmp_path / "f"
    rep = SX.run(
        str(out),
        loader=lambda p: _Model(),
        builder=lambda s, p: m,
        replay_learner=replay,
        continue_learner=cont_learn,
        clock=(lambda: 0.0,
               lambda: 0.0),
        eval_runner=eval_runner,
        panel_fn=lambda mm: {
            "rows": [1] * 4},
        initial_sig_ref=sig_ref)
    assert rep["status"] == "completed"
    assert eval_calls["n"] == 1   # 边界零评价
    assert rep["steps"] == {
        "replay": 32768,
        "continue": 32768,
        "final_eval": 2112}
    assert rep["total_real_env_steps"] == 67648
    assert rep["final_counts"] == {
        "env": 65536, "model": 65536,
        "n_updates": 640,
        "optimizer": 2560}
    # RNG 快照可恢复(逐位)
    snap = th.load(
        out / "boundary_rng.pt",
        weights_only=False)
    ts = th.get_rng_state()
    th.manual_seed(9)
    th.set_rng_state(snap["torch"])
    assert th.equal(
        th.get_rng_state(),
        snap["torch"])
    th.set_rng_state(ts)
    assert (out / "DONE.marker"
            ).exists()
    assert "B64_final_sha256" in rep


def test_spec_sha_gate(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        json.dumps(
            {**SPEC, "seeds": {
                **SPEC["seeds"],
                "torch_init": 1}}),
        encoding="utf-8")
    out = tmp_path / "g"
    with pytest.raises(RuntimeError,
                       match="RUNSPEC_EXT"):
        SX.run(str(out),
               spec_path=str(bad),
               loader=lambda p: None,
               builder=lambda s, p: None,
               replay_learner=lambda *a:
                   None,
               continue_learner=lambda
                   *a: None,
               clock=(lambda: 0.0,
                      lambda: 0.0))
    assert (out / "FAILED.marker"
            ).exists()


def test_counts_gate_on_stub(
        tmp_path):
    """_n_updates 非 320/640 → 计数门拒。"""
    m = _Model()

    def replay(model, *a):
        model.num_timesteps = 32768
        model._n_updates = 319   # 坏
        model.pilot_env.n_steps_env = 32768
    out = tmp_path / "c"
    with pytest.raises(RuntimeError):
        SX.run(
            str(out),
            loader=lambda p: _Model(),
            builder=lambda s, p: m,
            replay_learner=replay,
            continue_learner=lambda
                *a: None,
            clock=(lambda: 0.0,
                   lambda: 0.0),
            eval_runner=lambda *a: 0,
            panel_fn=lambda mm: {
                "rows": [1] * 4})


def test_status():
    assert SX.STATUS == "PREPARED_NOT_RUN"


class _AppendModel(_Model):
    """learn spy:记录调用;SB3 reset=False 追加量累计。"""

    def __init__(self):
        super().__init__()
        self.calls = []

    def learn(self, total_timesteps,
              reset_num_timesteps=True,
              callback=None, **k):
        self.calls.append(
            (total_timesteps,
             reset_num_timesteps))
        if reset_num_timesteps:
            self.num_timesteps = \
                total_timesteps
        else:
            self.num_timesteps += \
                total_timesteps
        return self


def test_real_continue_helper_append():
    """真实 _real_learn_continue:learn 恰收
    (32768, reset=False);追加量累计 65536。"""
    mm = _AppendModel()
    mm.num_timesteps = 32768
    mm.pilot_env.n_steps_env = 32768
    rep = {}
    led = SC.StepLedger(67648, rep)

    class _B:
        def checkpoint(self, ph):
            return None, {}, {}
    SX._real_learn_continue(
        mm, 32768, rep, led, _B())
    assert mm.calls == [
        (32768, False)]
    assert mm.num_timesteps == 65536


def test_rng_save_invariance_reported(
        tmp_path):
    """全流程桩:boundary_rng_invariance=True
    (run 内部四 RNG/_last_obs/env 身份前后核)。"""
    m = _Model()
    sig_ref = SC.fresh_signature(m)

    def replay(model, total, r, led, bk):
        model.num_timesteps = 32768
        model._n_updates = 320
        model.pilot_env.n_steps_env = 32768
        model._pilot_opt_count = {"n": 1280}
        led.add(32768, "replay_stub")

    def cont(model, total, r, led, bk):
        model.num_timesteps += total
        model.pilot_env.n_steps_env = 65536
        model._n_updates = 640
        model._pilot_opt_count = {"n": 2560}
        led.add(32768, "continue_stub")   # 模拟 helper 计数

    def ev(mm, tr, r, tag, lg, bk):
        r[tag + "_episodes"] = [
            {"index": i}
            for i in range(128)]
        r["steps"][tag] = 2112
        for _ in range(2112):
            lg.add(1, tag)
        return 2112
    out = tmp_path / "inv"
    rep = SX.run(
        str(out),
        loader=lambda p: _Model(),
        builder=lambda s, p: m,
        replay_learner=replay,
        continue_learner=cont,
        clock=(lambda: 0.0, lambda: 0.0),
        eval_runner=ev,
        panel_fn=lambda mm: {
            "rows": [1] * 4},
        initial_sig_ref=sig_ref)
    assert rep[
        "boundary_rng_invariance"] \
        is True
    assert rep["boundary"][
        "optimizer_success"] == 1280


def test_bad_optimizer_count_stops(
        tmp_path):
    """重放 optimizer_success≠1280 → 边界拒。"""
    m = _Model()
    sig_ref = SC.fresh_signature(m)

    def replay(model, total, r, led, bk):
        model.num_timesteps = 32768
        model._n_updates = 320
        model.pilot_env.n_steps_env = 32768
        model._pilot_opt_count = {"n": 999}
        led.add(32768, "replay_stub")
    out = tmp_path / "bo"
    with pytest.raises(RuntimeError,
                       match="optimizer"):
        SX.run(
            str(out),
            loader=lambda p: _Model(),
            builder=lambda s, p: m,
            replay_learner=replay,
            continue_learner=lambda
                *a: None,
            clock=(lambda: 0.0,
                   lambda: 0.0),
            eval_runner=lambda *a: 0,
            panel_fn=lambda mm: {
                "rows": [1] * 4},
            initial_sig_ref=sig_ref)
    rep = json.loads(
        (out / "extend.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"


def test_continue_interrupt_partial(
        tmp_path):
    """续段中断:首因固定+fail_train_counts
    (env/model/updates/opt)+partial 存档。"""
    m = _Model()
    sig_ref = SC.fresh_signature(m)

    def replay(model, total, r, led, bk):
        model.num_timesteps = 32768
        model._n_updates = 320
        model.pilot_env.n_steps_env = 32768
        model._pilot_opt_count = {"n": 1280}
        led.add(32768, "replay_stub")

    def cont(model, total, r, led, bk):
        model.pilot_env.n_steps_env = \
            40960
        model._n_updates = 380
        model._pilot_opt_count = {
            "n": 1520}
        led.add(40960 - 32768,
                "continue_stub")
        raise RuntimeError(
            "oom at 40k")
    out = tmp_path / "ci"
    with pytest.raises(RuntimeError,
                       match="oom at 40k"):
        SX.run(
            str(out),
            loader=lambda p: _Model(),
            builder=lambda s, p: m,
            replay_learner=replay,
            continue_learner=cont,
            clock=(lambda: 0.0,
                   lambda: 0.0),
            eval_runner=lambda *a: 0,
            panel_fn=lambda mm: {
                "rows": [1] * 4},
            initial_sig_ref=sig_ref)
    rep = json.loads(
        (out / "extend.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "oom at 40k" in rep[
        "train_fail_reason"]
    ftc = rep["fail_train_counts"]
    assert ftc["env"] == 40960
    assert ftc["model"] == 32768
    assert ftc["n_updates"] == 380
    assert ftc["optimizer"] == 1520
    assert (out /
            "partial_failure.zip"
            ).exists()


def test_sig_equal_json_forms():
    """正例:tuple vs JSON list 形态等价;负例:形/参数变。"""
    sig_a = {
        "param_hash": "h" * 64,
        "param_spec": [
            ("k", (1,), "torch.float32", 1)],
        "n_param_groups": 1,
        "optimizer_content_hash": "x" * 64,
        "optimizer_state_entries": 0,
        "num_timesteps": 0,
        "ppo_n_updates": 0}
    ref = json.loads(json.dumps(sig_a))
    assert SX.sig_equal_json(sig_a, ref)
    bad_shape = json.loads(json.dumps(sig_a))
    bad_shape["param_spec"][0] = [
        "k", [2], "torch.float32", 2]
    assert not SX.sig_equal_json(
        sig_a, bad_shape)
    bad_param = json.loads(json.dumps(sig_a))
    bad_param["param_hash"] = "0" * 64
    assert not SX.sig_equal_json(
        sig_a, bad_param)


class _ReplayModel(_Model):
    """learn 模拟 SB3:env 逐步计数可中断。"""

    def __init__(self, interrupt_at=None):
        super().__init__()
        self.calls = []
        self.interrupt_at = interrupt_at

    def learn(self, total_timesteps,
              reset_num_timesteps=True,
              callback=None, **k):
        self.calls.append(
            (total_timesteps,
             reset_num_timesteps))
        start = (0
                 if reset_num_timesteps
                 else self.num_timesteps)
        if callback is not None:
            callback.init_callback(self)
        step = 0
        while step < total_timesteps:
            step += 1
            self.pilot_env.n_steps_env = \
                start + step
            self.policy.optimizer.step()
            if callback is not None:
                callback.update_locals(
                    {"infos": [
                        {"reward_valid": True}]})
                if not callback.on_step():
                    raise RuntimeError(
                        "callback stop")
            if (self.interrupt_at
                    is not None
                    and start + step
                    == self.interrupt_at):
                raise RuntimeError(
                    "oom at %d"
                    % self.interrupt_at)
        self.num_timesteps = \
            start + total_timesteps
        self._n_updates = \
            10 * (self.num_timesteps
                  // 1024)
        return self


def test_real_replay_helper_success():
    """真实 _real_learn_replay+learn spy:
    计数恰 32768,无双计,counter 由 helper 同步。"""
    mm = _ReplayModel()
    rep = {}
    led = SC.StepLedger(67648, rep)

    class _B:
        def checkpoint(self, ph):
            return None, {}, {}
    SX._real_learn_replay(
        mm, 32768, rep, led, _B())
    assert mm.calls == [(32768, True)]
    assert mm.pilot_env.n_steps_env \
        == 32768
    assert led.total == 32768   # 单次计满
    assert mm._pilot_opt_count["n"] == 32768


def test_real_replay_helper_interrupt():
    """中断:原异常为主+counter 已 best-effort 同步
    +cleanup 异常另列(此处无)。"""
    mm = _ReplayModel(interrupt_at=20000)
    rep = {}
    led = SC.StepLedger(67648, rep)

    class _B:
        def checkpoint(self, ph):
            return None, {}, {}
    with pytest.raises(RuntimeError,
                       match="oom at 20000"):
        SX._real_learn_replay(
            mm, 32768, rep, led, _B())
    assert led.total == 20000   # 中断处实际同步
    assert "replay_sync_error" not in rep


def test_real_continue_helper_interrupt_no_double():
    """续段真实 helper 中断:无外层 counter,计数单次。"""
    mm = _ReplayModel()
    mm.num_timesteps = 32768
    mm.pilot_env.n_steps_env = 32768
    rep = {}
    led = SC.StepLedger(67648, rep)
    led.add(32768, "replay")

    class _B:
        def checkpoint(self, ph):
            return None, {}, {}

    class _InterruptModel(_ReplayModel):
        def learn(self, total_timesteps,
                  reset_num_timesteps=True,
                  callback=None, **k):
            self.calls.append(
                (total_timesteps,
                 reset_num_timesteps))
            if callback is not None:
                callback.init_callback(self)
            for i in range(8192):
                self.pilot_env.n_steps_env += 1
                if callback is not None:
                    callback.update_locals(
                        {"infos": [
                            {"reward_valid": True}]})
                    callback.on_step()
            raise RuntimeError("oom cont")
    mm2 = _InterruptModel()
    mm2.num_timesteps = 32768
    mm2.pilot_env.n_steps_env = 32768
    mm2._n_updates = 320
    with pytest.raises(RuntimeError,
                       match="oom cont"):
        SX._real_learn_continue(
            mm2, 32768, rep, led, _B())
    assert led.total == 32768 + 8192
    assert mm2.calls == [(32768, False)]


def test_np_eq_full_state():
    import numpy as _np
    a = _np.random.get_state()
    SX._np_eq(a, a)
    b = list(a)
    b = tuple(b)
    assert SX._np_eq(a, b)
    c = list(a)
    cl = list(c[1])
    cl[0] = cl[0] + 1
    c = (c[0], _np.array(cl),
         c[2], c[3], c[4])
    assert not SX._np_eq(a, c)
