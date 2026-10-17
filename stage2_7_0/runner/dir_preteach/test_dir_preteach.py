# -*- coding: utf-8 -*-
"""dir_preteach v2 手写假控制(零真实模型 forward/
rollout/learn;假 raw8/builder/learner/eval 走完整
正式 run 链)。"""
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

import dir_preteach as DP  # noqa: E402
import seed_contrast as SC  # noqa: E402


class _FakeActionNet(th.nn.Module):
    """可训 8→8(真梯度;raw8 布局合法)。"""

    def __init__(self):
        super().__init__()
        self.lin = th.nn.Linear(8, 8)
        th.manual_seed(3)
        for p_ in self.parameters():
            th.nn.init.normal_(p_, std=.05)

    def forward(self, x):
        return self.lin(x)


class _FakeMLP:
    def forward_actor(self, x):
        return x


class _FakeDist:
    """合法分布面(cond 原子+I 归一=1;行 i)。"""

    def __init__(self, i):
        import torch as _t
        g = _t.Generator().manual_seed(11 + i)
        self.branch_logp = _t.log(
            _t.softmax(_t.randn(1, 2, generator=g), dim=-1))
        self.mix_logp = _t.log(
            _t.softmax(_t.randn(1, 4, generator=g), dim=-1))
        self._raw6 = 0.1 + 0.05 * i
        self._raw7 = 0.1 + 0.05 * i
        # 原子 0.30/0.40/0.25 + I 0.05 = 1.00
        self._atoms = [0.30, 0.40, 0.25]

    def merged_atom_logp(self):
        return th.log(th.tensor(
            [self._atoms]))

    def interior_log_mass(self):
        return th.log(th.tensor([0.05]))

    @property
    def Z(self):
        return th.tensor([0.9])

    @property
    def alpha(self):
        return th.nn.functional.softplus(
            th.tensor([self._raw6])) + 1

    @property
    def beta(self):
        return th.nn.functional.softplus(
            th.tensor([self._raw7])) + 1


class _FakeView:
    def __init__(self, n):
        self._n = n

    @property
    def dist(self):
        return self  # _SampleDist 由 _Subview 再包;提供 batch dist 面

    def merged_atom_logp(self):
        return th.log(th.tensor(
            [[0.30, 0.40, 0.25]]).repeat(
                self._n, 1))

    def interior_log_mass(self):
        return th.log(th.full((self._n,), 0.05))

    @property
    def Z(self):
        return th.full((self._n,), 0.9)

    @property
    def alpha(self):
        return 1.0 + th.abs(th.zeros(self._n))

    @property
    def beta(self):
        return 1.0 + th.abs(th.zeros(self._n))

    @property
    def branch_logp(self):
        bl = th.log_softmax(th.zeros(self._n, 2), dim=-1)
        return bl

    @property
    def mix_logp(self):
        return th.log_softmax(th.zeros(self._n, 4), dim=-1)

    def __getitem__(self, i):
        return _FakeDistRow(int(i))

    def mode(self):
        # 逐行 mode:batch [n,2]
        out = th.zeros(self._n, 2)
        for i in range(self._n):
            d = _FakeDist(i)
            if float(d.branch_logp.flatten()[0]) > \
                    float(d.branch_logp.flatten()[1]):
                out[i] = th.tensor([0.0, 0.0])
            else:
                out[i] = th.tensor([0.0, 0.0])
        return out


class _FakeDistRow:
    def __init__(self, i):
        self._i = i

    def __getattr__(self, n):
        return getattr(_FakeDist(self._i), n)


class _FakePolicy:
    def __init__(self):
        self.action_net = _FakeActionNet()
        self.mlp_extractor = _FakeMLP()
        self._opt_state = {}
        self._pg = [{
            "lr": 3e-4}]

    def extract_features(self, obs):
        return obs

    def state_dict(self):
        return {"k": th.zeros(1)}

    def set_training_mode(self, m):
        pass

    def predict(self, obs, deterministic=False, *args, **kw):
        return (np.array([[1.0, 0.0]]), None)

    def get_distribution(self, obs):
        # 走真实 action_net 前向(触发 hook)
        self.action_net(obs)
        return _FakeView(len(obs))

    def _hook_probe(self):
        return True

    def named_parameters(self):
        for n_, p_ in self.action_net.named_parameters():
            yield ("actor." + n_,
                   p_)
        yield ("value.v",
               th.zeros(1,
                        requires_grad=
                        True))

    class _Opt:
        pass

    @property
    def optimizer(self):
        pol = self

        class _O:
            def state_dict(self):
                return {
                    "param_groups":
                        [dict(g)
                         for g in
                         pol._pg],
                    "state":
                        pol._opt_state}

            def load_state_dict(
                    self, sd):
                pol._opt_state = sd["state"]
                pol._pg = sd[
                        "param_"
                        "groups"]
        return _O()


class _FakeModel:
    _pilot_stub = True

    def __init__(self):
        self.policy = _FakePolicy()
        import types
        self.pilot_env = types.SimpleNamespace(
                n_steps_env=0,
                rng=random.
                Random(0))
        self.num_timesteps = 0
        self._n_updates = 0

    def learn(self,
              total_timesteps,
              reset_num_timesteps=
                  True,
              callback=None,
              **k):
        if callback:
            callback.init_callback(
                    self)
        for _ in range(
                int(
                    total_timesteps)):
            self.pilot_env.n_steps_env += 1
            if callback:
                callback.update_locals(
                        {"infos":
                         [{"reward_valid":
                           True}]})
                callback.on_step()
        self.num_timesteps = total_timesteps
        self._n_updates = 320
        return self

    def save(self, p):
        th.save({},
                p + ".zip")


def _sig_ref(m):
    import seed_extend as SXi
    return SXi._sig_json_norm(
            SC.fresh_signature(
                m))


def test_real_chain_raw8_and_loss():
    """真实公式链:假 raw8 前向、损失=
    mean(relu(.05−y·m)²);branch 列不进。"""
    m = _FakeModel()
    _, obs, y, _ = DP.aux_inputs()
    raw = DP.actor_raw8(
        m, obs)
    assert raw.shape == (4, 8)
    loss, mm = DP.aux_objective_raw(
            raw, y)
    p = th.softmax(
        raw[:, 2:6],
        dim=-1)
    a = th.nn.functional.softplus(
            raw[:, 6]) + 1
    b = th.nn.functional.softplus(
            raw[:, 7]) + 1
    ref_m = (p[:, 2]
             - p[:, 0]
             + p[:, 3]
             * (a - b)
             / (a + b))
    assert th.allclose(
        mm, ref_m)
    ref = (th.relu(
        .05 - y
        * ref_m)
        ** 2).mean()
    assert loss.item() == pytest.approx(
            ref.item(),
            rel=1e-6)


def test_preteach_actor_learns_margin():
    """真梯度 256 更新:margin_min 上移(假网络
    可学);成功计数同步。"""
    m = _FakeModel()
    _, obs, y, _ = DP.aux_inputs()
    rep = {}
    hist = DP.preteach_actor(
            m, obs, y,
            256,
            SC.Book(
                clock=(
                    lambda:
                    0.0,
                    lambda:
                    0.0)),
            rep)
    assert len(hist) == 256
    assert rep[
        "aux_success"] == 256
    assert hist[-1][
        "margin_min"] > hist[0][
            "margin_min"]


def test_panel8_rows_quality():
    """全量行(diag._row 复用):字段齐实际 q;
    恰 1 batch;panel SHA 门。"""
    m = _FakeModel()
    out = DP.panel8(m, "t")
    assert len(out["rows"]) == 8
    qs = [r["q"] for r in out["rows"]]
    assert qs == [1.0, 1.0, 0.5, 0.5, 0.25, 0.25, 1.0, 1.0]
    rems = sorted({r["rem"] for r in out["rows"]})
    assert rems == [1, 32]
    for r in out["rows"]:
        for k in ("P_hold", "effective_flat", "mode",
                  "merged_atoms_conditional",
                  "interior_category_mass",
                  "beta_survival_Z", "mix_probs", "raw8"):
            assert k in r, k
        assert 0.0 <= r["P_hold"] <= 1.0
        assert 0.0 <= r["effective_flat"] <= 1.0
    assert out["n_forwards"] == 1
    assert out["obs_canon_sha256"] == DP.PANEL8_OBS_SHA256


def test_aux_inputs_sha():
    _, obs, y, canon = DP.aux_inputs()
    assert canon == DP.AUX_OBS_SHA256
    assert obs.shape == (4, 8)


def test_full_run_fake_chain(
        tmp_path):
    """完整正式链(假对象):3 面板/梯度 aux/
    Adam 清空/32768/320/1280/eval 2112/
    128/总 34880/DONE。"""
    import runner as R5

    class _Bk:
        def checkpoint(
                self, ph):
            return None, {}, {}

    def fake_eval(
            mm, tr, r, tag,
            lg, bk):
        import torch as _th
        r[tag
          + "_episodes"] = [{"index":
                i,
                "valid":
                True,
                "net_log":
                0.0}
               for i in
               range(128)]
        steps = sum(
            len(t[
                "steps"])
            for t in tr)
        r["steps"][
            tag] = steps
        for _ in range(
                steps):
            lg.add(1,
                   tag)
        for t in tr:
            for _st in t["steps"]:
                mm.policy.predict(_th.ones(1, 8))
        return steps
    m = _FakeModel()
    oc = {"n": 0}

    class _Wrap:
        def __init__(
                self):
            self.n = 0

        def step(self,
                 *a,
                 **k):
            self.n += 1
            oc["n"] = self.n
    m.policy.action_net.lin._orig_fwd = m.policy.action_net.lin.forward

    def _wrap_step(
            *a, **k):
        oc["n"] += 1
        return None
    # 直接注入 opt 计数:learn 后由 run 读 _pilot_opt_count
    # (假 learn 不 wrap;借 _real_ppo_run? 不——learner 注入)
    def fake_learner(
            mm, total, r,
            led, bk):
        mm.learn(
            total,
            reset_num_timesteps=
                True,
            callback=None)
        mm.pilot_env.n_steps_env = total
        mm._pilot_opt_count = {
                "n": 1280}
        led.add(total,
                "ppo_stub")
    out = tmp_path / "full"
    rep = DP.run(
        str(out),
        loader=lambda
            p: _FakeModel(),
        builder=lambda
            s, p: m,
        learner=fake_learner,
        inner_eval=fake_eval,
        clock=(lambda:
               0.0,
               lambda:
               0.0),
        initial_sig_ref=_sig_ref(m))
    assert rep[
        "status"] == "completed"
    assert rep[
        "aux_updates"] == 256
    assert rep[
        "ppo_counts"] == {"env": 32768,
         "model": 32768,
         "n_updates":
             320,
         "optimizer":
             1280}
    assert rep[
        "steps"] == {"aux_env": 0,
         "ppo": 32768,
         "eval": 2112}
    assert rep[
        "total_real_"
        "env_steps"] == 34880
    for k in ("panel_pre_aux",
              "panel_post_aux",
              "panel_post_ppo"):
        assert len(
            rep[k][
                "rows"]) == 8
    assert (out /
            "DONE.marker").exists()
    assert rep[
        "eval_actions"][
        "eval"]


def test_first_final_overlimit_fails(tmp_path):
    """phase==final 真触发:手写 Boom Book 让 final
    超限(fail-closed FAILED 无 DONE,不等二次 clock)。"""
    import seed_contrast as SCi
    import dir_preteach as DPe

    class _Boom:
        def __init__(self):
            self.seen = []

        def checkpoint(self, ph):
            self.seen.append(ph)
            if ph == "final":
                return ("wall", {"wall_s": 1000.0}, {})
            return (None, {}, {})

    boom = _Boom()
    real_book = SCi.Book

    class _Patched:
        def __init__(self, *a, **k):
            self._real = real_book(*a, **k)

        def checkpoint(self, ph):
            why, cum, p2 = boom.checkpoint(ph)
            rwhy, rcum, rp = self._real.checkpoint(ph)
            return (why or rwhy,
                    cum if why else rcum,
                    p2 if why else rp)

        def snapshot(self):
            return self._real.snapshot()

    m = _FakeModel()

    def fake_learner(mm, total, r, led, bk):
        mm.learn(total, callback=None)
        mm.pilot_env.n_steps_env = total
        mm._pilot_opt_count = {"n": 1280}
        led.add(total, "ppo_stub")

    out = tmp_path / "fail"
    orig = DPe.SC.Book
    DPe.SC.Book = _Patched
    try:
        with pytest.raises(RuntimeError,
                           match="budget"):
            DPe.run(
                str(out),
                loader=lambda p: _FakeModel(),
                builder=lambda s, p: m,
                learner=fake_learner,
                initial_sig_ref=_sig_ref(m),
                inner_eval=lambda mm, tr, r, tag,
                    lg, bk: (
                    r.__setitem__(
                        tag + "_episodes",
                        [{"index": i2, "valid": True,
                          "net_log": 0.0}
                         for i2 in range(len(tr))]),
                    r["steps"].__setitem__(
                        tag, sum(len(x["steps"]) for x in tr)),
                    [lg.add(1, tag)
                     for t in tr for _st in t["steps"]],
                    [mm.policy.predict(th.ones(1, 8))
                     for t in tr for _st in t["steps"]],
                    sum(len(x["steps"]) for x in tr))[-1])
    finally:
        DPe.SC.Book = orig
    rep = json.loads(
        (out / "dirpt.json").read_text(
            encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "final" in rep["fail_reason"]
    assert boom.seen[-1] == "final"
    assert not (out / "DONE.marker").exists()
    assert (out / "FAILED.marker").exists()


def test_manifest_sx_pinned():
    txt = pathlib.Path(
            "/mnt/f/"
            "trading/"
            "dir_preteach_"
            "prep_20261017/"
            "launch_dpt.sh").read_text(
            encoding=
                "utf-8")
    assert "SX frozen SHA" in txt
    assert ("8ef6d554"
            in txt)
    assert ("$SNAP/sc"
            in txt)


def test_status():
    assert DP.STATUS == "PREPARED_NOT_RUN"


def test_illegal_mass_rejected():
    """非法分布(cond 和 1.25)被 _check_rows 拒。"""
    import diag_panel as DPv2
    rep = {"rows": [{
        "ckpt": "t", "rem": 32, "s": 1,
        "checks": {
            "cond_atoms_plus_I": 1.25,
            "uncond_total": 1.0,
            "flat_identity_absdiff":
                0.0}}]}
    with pytest.raises(RuntimeError,
                       match="cond sum"):
        DPv2._check_rows(rep)


def test_preteach_records_finite_flags():
    """真核落盘:grads/params_finite 逐更新真值。"""
    m = _FakeModel()
    _, obs, y, _ = DP.aux_inputs()
    rep = {}
    hist = DP.preteach_actor(
        m, obs, y, 8,
        SC.Book(clock=(
            lambda: 0.0,
            lambda: 0.0)), rep)
    assert len(hist) == 8
    for h_ in hist:
        assert h_["grads_finite"] is True
        assert h_["params_finite"] is True
    assert rep["aux_live_hist_n"] == 8




def test_predict_dim3_rejected_in_run(tmp_path):
    """run 捕获层:predict 3 维 → eval 阶段拒。"""
    m = _FakeModel()

    def _p3(obs, deterministic=False, *a, **k):
        return (np.zeros((1, 3)), None)
    m.policy.predict = _p3

    def bad_eval(mm, tr, r, tag, lg, bk):
        r[tag + "_episodes"] = [
            {"index": i2, "valid": True,
             "net_log": 0.0}
            for i2 in range(len(tr))]
        steps = sum(len(x["steps"]) for x in tr)
        r["steps"][tag] = steps
        for _ in range(steps):
            lg.add(1, tag)

        for t_ in tr:
            for _st in t_["steps"]:
                mm.policy.predict(th.ones(1, 8))
        return steps

    def fake_learner(mm, total, r, led, bk):
        mm.learn(total, callback=None)
        mm.pilot_env.n_steps_env = total
        mm._pilot_opt_count = {"n": 1280}
        led.add(total, "ppo_stub")
    out = tmp_path / "d3"
    with pytest.raises(RuntimeError,
                       match="predict dim"):
        DP.run(
            str(out),
            loader=lambda p: _FakeModel(),
            builder=lambda s, p: m,
            learner=fake_learner,
            inner_eval=bad_eval,
            clock=(lambda: 0.0, lambda: 0.0),
            initial_sig_ref=_sig_ref(m))
    rep = json.loads(
        (out / "dirpt.json").read_text(
            encoding="utf-8"))
    assert rep["status"] == "failed"


def test_nan_grad_fails_before_step():
    """NaN 梯度在 optimizer.step 前失败;
    step 调用 0 次。"""
    m = _FakeModel()

    class _Boom(th.nn.Module):
        def __init__(self):
            super().__init__()
            self.lin = th.nn.Linear(8, 8)
            th.manual_seed(5)
            for p_ in self.parameters():
                th.nn.init.normal_(p_, std=.05)
            # 反向产生 NaN 的钩子:权重 inf
            with th.no_grad():
                self.lin.weight.fill_(
                    float("inf"))

        def forward(self, x):
            return self.lin(x)
    m.policy.action_net = _Boom()
    steps = {"n": 0}
    orig_step = th.optim.Adam.step

    def counting_step(self, *a, **k):
        steps["n"] += 1
        return orig_step(self, *a, **k)
    th.optim.Adam.step = counting_step
    try:
        _, obs, y, _ = DP.aux_inputs()
        rep = {}
        with pytest.raises(RuntimeError,
                           match="non-finite"):
            DP.preteach_actor(
                m, obs, y, 4,
                SC.Book(clock=(
                    lambda: 0.0,
                    lambda: 0.0)),
                rep)
    finally:
        th.optim.Adam.step = orig_step
    assert steps["n"] == 0


def test_aux_interrupt_keeps_tail_n2():
    """2 次成功后 pre 预算失败:partial
    tail/n 仍为 2(live hist 不丢)。"""
    m = _FakeModel()

    class _Boom:
        def __init__(self):
            self.calls = 0

        def checkpoint(self, ph):
            self.calls += 1
            if self.calls > 4:  # 2 次
                return ("wall",
                        {"wall_s":
                         1000.0}, {})
            return (None, {}, {})
    _, obs, y, _ = DP.aux_inputs()
    rep = {}
    with pytest.raises(RuntimeError,
                       match="budget"):
        DP.preteach_actor(
            m, obs, y, 256, _Boom(),
            rep)
    assert rep[
        "aux_history_n"] == 2
    assert len(rep[
        "aux_history_tail"]) == 2
    assert rep[
        "aux_live_hist_n"] == 2


def test_episode_array_mutation_rejected(
        tmp_path):
    """episode 数组原地变化 → 状态核拒。"""
    m = _FakeModel()
    orig_snap = DP._les_copy(m)
    m._last_episode_starts = \
        th.zeros(1, 4)
    snap_a = DP._state_snapshot(
        m, m.pilot_env)
    # 原地翻转
    m._last_episode_starts[0, 0] = 1.0
    snap_b = DP._state_snapshot(
        m, m.pilot_env)
    assert not DP._state_same(
        snap_a, snap_b)


def test_main_argparse_default_and_explicit(
        tmp_path, monkeypatch):
    """main/argparse:默认 spec=HERE/RUNSPEC_DIR.json
    与显式 --spec 均构造正确;不调 run 内模型/环境/
    训练(fake run 注入)。"""
    calls = []

    def fake_run(out_dir, spec_path=None, **kw):
        calls.append((out_dir, spec_path))
        return {"status": "stub"}
    monkeypatch.setattr(
        DP, "run", fake_run)
    # 默认路径
    DP.main([str(tmp_path / "o1")])
    assert calls[-1][1] == str(
        pathlib.Path(
            DP._HERE)
        / "RUNSPEC_DIR.json")
    # 显式路径
    DP.main([str(tmp_path / "o2"),
             "--spec",
             "/tmp/x.json"])
    assert calls[-1][1] == "/tmp/x.json"
    # mode 拒绝非 official
    with pytest.raises(SystemExit):
        DP.main([str(tmp_path / "o3"),
                 "--mode", "debug"])
    assert len(calls) == 2
