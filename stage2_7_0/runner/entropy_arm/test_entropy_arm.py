# -*- coding: utf-8 -*-
"""entropy_arm v2 微测(零经济步;真实 helper+手写
train/predict spy;不整段替换)。"""
import json
import math
import pathlib
import random
import sys

import pytest
import numpy as np
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(
    0, "/mnt/f/trading/"
       "seed_extend_prep_20261017")
sys.path.insert(
    0, "/mnt/f/trading/"
       "seed_contrast_prep_20261016")
sys.path.insert(
    0, "/mnt/f/trading/"
       "teaching_pilot_prep_20261016")

import entropy_arm as EA  # noqa
import seed_contrast as SC  # noqa


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
        self.calls = []

    def set_training_mode(self, m):
        pass

    def state_dict(self):
        return dict(self._sd)

    @property
    def optimizer(self):
        return self._opt

    def predict(self, obs,
                deterministic=False,
                *args, **kw):
        self.calls.append(
            (args, kw))
        return (np.array(
                    [[1.0, -0.2]]),
                None)


class _Logger:
    def __init__(self):
        self.name_to_value = {
            "train/entropy_loss": -0.021,
            "train/approx_kl": 0.003,
            "train/clip_fraction": 0.05}


class _Model:
    _pilot_stub = True

    def __init__(self):
        self.policy = _P()
        self.num_timesteps = 32768
        self._n_updates = 320
        self.pilot_env = _Env()
        self.ent_coef = 0.001
        self.logger = _Logger()
        self.train_calls = 0

    def train(self, mode=True):
        self.train_calls += 1
        self.logger.name_to_value[
            "train/entropy_loss"] = -0.021 - 0.001 * self.train_calls
        return self

    def save(self, p):
        th.save({}, p + ".zip")


def test_predict_passthrough_spy():
    """手写 (1,2) 输出+完整签名 spy:
    一对一调用/透传/两有限数记录。"""
    m = _Model()
    rows = []

    class _Inner:
        def __call__(self, mm, tr, r,
                     tag, lg, bk):
            out = mm.policy.predict(
                th.ones(1, 8),
                deterministic=False)
            return 0
    trs = [{"remaining": 1, "s0": 1,
            "steps": [{"s": 1}]}]
    rep = {}
    cap = EA.make_eval_capture(
        _Inner())
    n = cap(m, trs, rep,
            "final_eval", None, None)
    # deterministic 被命名参数捕获,
    # spy 落 args/kw 均空(透传成功)
    assert m.policy.calls == [((), {})]
    segs = rep["eval_actions"][
        "final_eval"]
    assert segs == [[[1.0, -0.2]]]
    assert isinstance(
        m.policy, _P)


def test_eval_capture_segments_and_steps():
    """分段=锁 trace 步长;全 valid 时
    动作数==实际步;finally 恢复。"""
    m = _Model()
    trs = [
        {"remaining": 3, "s0": 1,
         "steps": [{"s": 1},
                   {"s": 1},
                   {"s": 1}]},
        {"remaining": 2, "s0": -1,
         "steps": [{"s": -1},
                   {"s": -1}]}]

    class _Inner:
        def __call__(self, mm, tr,
                     r, tag, lg, bk):
            for e in tr:
                for _st in e["steps"]:
                    mm.policy.predict(
                        th.ones(1, 8))
            r[tag + "_episodes"] = [
                {"valid": True}
                for _ in tr]
            return 5
    rep = {}
    EA.make_eval_capture(
        _Inner())(m, trs, rep,
                  "T", None, None)
    segs = rep["eval_actions"]["T"]
    assert [len(x)
            for x in segs] == [3, 2]
    assert sum(len(x)
               for x in segs) == 5


def test_eval_capture_interrupt_keeps_actions():
    """中断仍恢复 policy 并保留已捕获动作。"""
    m = _Model()

    class _Inner:
        def __call__(self, mm, tr,
                     r, tag, lg, bk):
            mm.policy.predict(
                th.ones(1, 8))
            raise RuntimeError(
                "eval boom")
    rep = {}
    with pytest.raises(
            RuntimeError,
            match="eval boom"):
        EA.make_eval_capture(
            _Inner())(
                m, [{"steps":
                     [{"s": 1}] *
                     2}],
                rep, "T",
                None, None)
    assert isinstance(
        m.policy, _P)
    # 实际动作保留(partial)
    assert rep[
        "eval_actions_partial"][
        "T"] == [[1.0, -0.2]]


def test_train_recorder_rows_and_restore():
    """train spy 更新 logger→包后逐次记录+
    末条注记;finally 恢复(无实例属性则还原
    类方法)。"""
    m = _Model()
    rows = []
    restore = EA.wrap_train_recorder(
            m, rows)
    assert "train" in m.__dict__
    for _ in range(3):
        m.train()
    restore()
    assert "train" not in m.__dict__
    assert len(rows) == 3
    last = rows[-1]
    assert last["_ent_coef"] == pytest.approx(0.001)
    assert last["_timesteps"] == 32768
    assert last["_n_updates"] == 320
    # 恢复后 train 仍可用(类方法)
    m.train()
    assert m.train_calls == 4


def test_ent_from_gate():
    m = _Model()
    m.ent_coef = 0.02   # 非 0.001
    with pytest.raises(
            RuntimeError,
            match="ent_coef from"):
        EA.set_ent_coef(
            m, EA.ENT_TO)


def test_full_flow_with_kw_cont(
        tmp_path):
    """kw_cont 注入路径:ent 变更入报告+
    train 旁读 rows(真实 train spy)。"""
    m = _Model()
    sig = SC.fresh_signature(m)

    def replay(model, total, r,
               led, bk):
        model._n_updates = 320
        model.pilot_env.n_steps_env = 32768
        model._pilot_opt_count = {
            "n": 1280}
        led.add(32768,
                "replay_stub")

    def cont(model, add, r, led,
             bk):
        # 真实 SB3 语义近似:
        # learn→train×2→learn 完
        for _ in range(2):
            model.train()
        model.num_timesteps = 65536
        model.pilot_env.n_steps_env = 65536
        model._n_updates = 640
        model._pilot_opt_count = {
            "n": 2560}
        led.add(add,
                "continue_stub")

    def fake_eval(mm, tr, r, tag,
                  lg, bk):
        r[tag + "_episodes"] = [
            {"index": i,
             "valid": True}
            for i in
            range(len(tr))]
        steps = sum(
            len(t["steps"])
            for t in tr)
        r["steps"][tag] = steps
        for t in tr:
            for _st in t["steps"]:
                lg.add(1, tag)
        for t in tr:
            for _st in t["steps"]:
                mm.policy.predict(
                    th.ones(1, 8))
        return steps
    out = tmp_path / "e"
    rep = EA.run(
        str(out),
        loader=lambda p: _Model(),
        builder=lambda s, p: m,
        replay_learner=replay,
        clock=(lambda: 0.0,
               lambda: 0.0),
        inner_eval=fake_eval,
        panel_fn=lambda mm: {
            "rows": [1] * 4},
        initial_sig_ref=sig,
        kw_cont=cont)
    assert rep["ent_coef_change"] == {"from": 0.001,
            "to": 0.010}
    ent = json.loads(
        (out / "ent_log.json")
        .read_text(
            encoding="utf-8"))
    assert ent["n"] == 2
    assert ent["rows"][-1][
        "_ent_coef"] == pytest.approx(0.010)
    segs = rep["eval_actions"][
        "final_eval"]
    assert sum(len(x)
               for x in segs) == rep["steps"]["final_eval"]
    assert (out /
            "DONE.marker").exists()


def test_status():
    assert EA.STATUS == "PREPARED_NOT_RUN"


def test_illegal_branch_rejected():
    """.6 分支不能作为合法正例。"""
    m = _Model()
    m.policy = type(
        "X", (), {
            "predict":
                lambda self, o,
                **k: (
                    np.array(
                        [[0.6,
                          0.0]]),
                    None)})()
    rep = {}

    class _Inner:
        def __call__(self, mm,
                     tr, r, tag,
                     lg, bk):
            mm.policy.predict(
                th.ones(1, 8))
            return 0
    with pytest.raises(
            RuntimeError,
            match="branch"):
        EA.make_eval_capture(
            _Inner())(
                m,
                [{"steps":
                  [{"s": 1}]}],
                rep, "T",
                None, None)


def test_real_cont_learner_spy():
    """实际 make_continue_learner+手写
    learn/train spy:32 次假 1024 计数;
    32768/False/唯一 counter/32 行
    (首 33792/330·末 65536/640/.01)/
    RNG·train 属性恢复。"""
    import random as _rd
    import numpy as _np
    rows = []
    m = _Model()
    m.num_timesteps = 32768
    m.pilot_env.n_steps_env = 32768

    class _InnerModel(_Model):
        def __init__(self):
            super().__init__()
            self.calls = []

        def learn(self, total_timesteps,
                  reset_num_timesteps=True,
                  callback=None, **k):
            self.calls.append(
                (total_timesteps,
                 reset_num_timesteps))
            if callback is not None:
                callback.init_callback(self)
            for _r in range(32):
                # 假 rollout 1024 步
                for _s in range(1024):
                    self.pilot_env.\
                        n_steps_env += 1
                    if callback:
                        callback.\
                            update_locals(
                            {"infos": [
                             {"reward_valid":
                              True}]})
                        callback.on_step()
                # SB3: rollout 后 train
                self.num_timesteps = \
                    self.pilot_env.\
                    n_steps_env
                self._n_updates = \
                    10 * (self.num_timesteps
                          // 1024)
                self.train()
            return self
    mm = _InnerModel()
    mm.num_timesteps = 32768
    mm.pilot_env.n_steps_env = 32768
    rep = {}
    led = SC.StepLedger(
        67648, rep)

    class _Bk:
        def checkpoint(self, ph):
            return None, {}, {}
    ts = th.get_rng_state()
    ns = _np.random.get_state()
    ps = _rd.getstate()
    cont_fn = EA.make_continue_learner(rows)
    # 原生 Guard 需 init_callback 设置 model
    # ——真实链由 SB3 learn 调;spy 内手动 init
    import runner as R5
    _bk_env = mm.pilot_env
    pre_cbk = R5._make_guard_callback(_Bk(), _bk_env)
    pre_cbk.init_callback(mm)
    # 还原:正式调用会重建 callback;仅验证签名链
    cont_fn(mm, 32768, rep, led, _Bk())
    assert mm.calls == [
        (32768, False)]
    assert mm.pilot_env.n_steps_env \
        == 65536
    assert led.total == 32768   # 唯一 counter
    assert len(rows) == 32
    assert rows[0]["_timesteps"] \
        == 33792
    assert rows[0]["_n_updates"] \
        == 330
    last = rows[-1]
    assert last["_timesteps"] \
        == 65536
    assert last["_n_updates"] \
        == 640
    assert last["_ent_coef"] == \
        pytest.approx(0.010)
    # RNG/train 属性恢复
    assert th.equal(
        th.get_rng_state(), ts)
    assert _np.array_equal(
        _np.random.get_state()[1],
        ns[1])
    assert _rd.getstate() == ps
    assert "train" not in \
        mm.__dict__
    assert mm.ent_coef == \
        pytest.approx(0.010)


def test_entlog_save_secondary_not_primary(
        tmp_path, monkeypatch):
    """SX primary 在,日志保存失败仅辅因
    (stderr SECONDARY,primary 原样传)。"""
    m = _Model()
    sig = SC.fresh_signature(m)

    def replay(model, total, r,
               led, bk):
        model._n_updates = 320
        model.pilot_env.\
            n_steps_env = 32768
        model._pilot_opt_count = {
            "n": 1280}
        led.add(32768,
                "replay_stub")

    def cont(model, add, r, led,
             bk):
        raise RuntimeError(
            "SX primary boom")
    import seed_extend as SXi
    orig_run = SXi.run

    def boom_run(*a, **k):
        try:
            return orig_run(
                *a, **k)
        except BaseException:
            raise
    real_dump = json.dump

    def bad_dump(*a, **k):
        raise OSError("disk full")
    out = tmp_path / "p"
    import entropy_arm as EAm
    monkeypatch.setattr(
        json, "dump", bad_dump)
    with pytest.raises(
            RuntimeError,
            match="SX primary"):
        EAm.run(
            str(out),
            loader=lambda p:
                _Model(),
            builder=lambda s, p: m,
            replay_learner=replay,
            clock=(lambda: 0.0,
                   lambda: 0.0),
            inner_eval=lambda *a:
                0,
            panel_fn=lambda mm: {
                "rows": [1] * 4},
            initial_sig_ref=sig,
            kw_cont=cont)
    assert (out /
            "ENTLOG_SAVE_ERROR.txt"
            ).exists()
