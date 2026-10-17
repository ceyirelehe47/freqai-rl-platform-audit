# -*- coding: utf-8 -*-
"""aux_keep v2 手写假控制(假对象走正式接线:
collect→train→tap,每轮 40 optimizer step)。"""
import inspect
import json
import pathlib
import random
import sys

import pytest
import numpy as np
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
for d in ("dir_preteach_prep_20261017", "seed_extend_prep_20261017",
          "seed_contrast_prep_20261016", "teaching_pilot_prep_20261016",
          "diag_panel_prep_20261016"):
    sys.path.insert(0, "/mnt/f/trading/" + d)

import aux_keep as AK  # noqa: E402
import dir_preteach as DP  # noqa: E402
import seed_contrast as SC  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common.callbacks import BaseCallback  # noqa: E402


class _FakeActionNet(th.nn.Module):
    def __init__(self):
        super().__init__()
        self.lin = th.nn.Linear(8, 8)
        th.manual_seed(3)
        for p_ in self.parameters():
            th.nn.init.normal_(p_, std=.05)

    def forward(self, x):
        return self.lin(x)


class _FakeDistBatch:
    def __init__(self, n):
        self._n = n

    def merged_atom_logp(self):
        return th.log(th.tensor([[.30, .40, .25]]).repeat(self._n, 1))

    def interior_log_mass(self):
        return th.log(th.full((self._n,), .05))

    @property
    def Z(self):
        return th.full((self._n,), .9)

    @property
    def alpha(self):
        return 1.0 + th.abs(th.zeros(self._n))

    @property
    def beta(self):
        return 1.0 + th.abs(th.zeros(self._n))

    @property
    def branch_logp(self):
        return th.log_softmax(th.zeros(self._n, 2), dim=-1)

    @property
    def mix_logp(self):
        return th.log_softmax(th.zeros(self._n, 4), dim=-1)


class _FakeView:
    def __init__(self, n):
        self._n = n
        self._b = _FakeDistBatch(n)

    @property
    def dist(self):
        return self._b

    def mode(self):
        return th.zeros(self._n, 2)

    @property
    def branch_logp(self):
        return self._b.branch_logp

    @property
    def mix_logp(self):
        return self._b.mix_logp

    @property
    def Z(self):
        return self._b.Z

    @property
    def alpha(self):
        return self._b.alpha

    @property
    def beta(self):
        return self._b.beta

    def merged_atom_logp(self):
        return self._b.merged_atom_logp()

    def interior_log_mass(self):
        return self._b.interior_log_mass()


class _FakeOpt:
    """step 推进伪参数版本(权重+ε)并记录
    梯度范数(证明正式 train 非零)。"""

    def __init__(self, pol):
        self._pol = pol
        self.steps = 0
        self.grad_norms = []
        self._live = list(
            pol.action_net.parameters())
        self._pg = [{"lr": 3e-4,
                     "params":
                         list(self.
                              _live)}]

    @property
    def param_groups(self):
        return self._pg

    def state_dict(self):
        # 仿 torch:state_dict 中 params 编码为索引
        groups = []
        for g in self._pg:
            gg = dict(g)
            gg["params"] = list(
                range(len(gg["params"])))
            groups.append(gg)
        return {"param_groups": groups,
                "state": self._pol._opt_state}

    def load_state_dict(self, sd):
        self._pol._opt_state = sd["state"]
        groups = []
        for g in sd["param_groups"]:
            gg = dict(g)
            # 索引解码回 live 参数
            gg["params"] = self._live
            groups.append(gg)
        self._pg = groups

    def zero_grad(self, *a, **k):
        return None

    def step(self, *a, **k):
        gn = 0.0
        with th.no_grad():
            for p_ in self._pg[0]["params"]:
                if p_.grad is not None:
                    gn += float(p_.grad.abs().sum())
                p_.add_(1e-3)
        self.grad_norms.append(gn)
        self.steps += 1


class _FakePolicy:
    def __init__(self):
        self.action_net = _FakeActionNet()
        self._opt_state = {}
        self.optimizer = _FakeOpt(self)
        self.training = True

    def extract_features(self, obs):
        return obs

    @property
    def mlp_extractor(self):
        class _M:
            def forward_actor(self, x):
                return x
        return _M()

    def named_parameters(self):
        for n_, p_ in self.action_net.named_parameters():
            yield ("actor." + n_, p_)
        yield ("value.v", th.zeros(1, requires_grad=True))

    def parameters(self):
        for _, p_ in self.named_parameters():
            yield p_

    def set_training_mode(self, m):
        self.training = m

    def state_dict(self):
        return {"k": self.action_net.lin.weight.detach().clone()}

    def predict(self, obs, deterministic=False, *args, **kw):
        return (np.array([[1.0, 0.0]]), None)

    def get_distribution(self, obs):
        self.action_net(obs)
        return _FakeView(len(obs))

    def evaluate_actions(self, obs, acts):
        raw = self.action_net(obs)
        log_prob = raw.mean(dim=1)
        values = th.zeros(len(obs), 1)
        return (values, log_prob, None)


class _FakeBuf:
    """1024 样本·batch 256→4 minibatch·×10 epochs=40 step/轮。"""

    def __init__(self):
        self.values = np.zeros(1024)
        self.returns = np.zeros(1024)

    _k = [0]

    def get(self, bs):
        for _ in range(4):
            k = self._k[0]
            self._k[0] += 1
            idx = th.arange(bs) + k
            yield type("RD", (), {
                "actions": th.zeros(bs, 1),
                "observations": th.randn(bs, 8),
                "advantages": th.sin(idx.float()) * 0.5,
                "old_values": th.zeros(bs),
                "returns": th.zeros(bs),
                "old_log_prob": th.zeros(bs)})()


class _FakeModel:
    """正式接线:collect(1024·on_step)→on_rollout_end
    →train()(tap→augmented·40 step)。"""

    _pilot_stub = True

    def __init__(self):
        self.policy = _FakePolicy()
        import types
        self.pilot_env = types.SimpleNamespace(
            n_steps_env=0, rng=random.Random(0),
            _terminated=False)
        self.num_timesteps = 0
        self._n_updates = 0
        self.rollout_buffer = _FakeBuf()
        self.n_epochs = 10
        self.batch_size = 256
        self.action_space = object()
        self.logger = type("L", (), {
            "name_to_value": {},
            "record": lambda *a, **k: None})()
        self.clip_range = lambda p: 0.2
        self.clip_range_vf = None
        self.normalize_advantage = True
        self.target_kl = None
        self.verbose = 0
        self.ent_coef = 0.0
        self.vf_coef = 0.5
        self.max_grad_norm = 0.5
        self._current_progress_remaining = 1.0
        self._update_learning_rate = lambda o: None
        self._save_calls = []
        self._inject = None

    def train(self):
        pass

    def learn(self, total_timesteps,
              reset_num_timesteps=True, callback=None, **k):
        if callback:
            callback.init_callback(self)
        env = self.pilot_env
        while env.n_steps_env < int(total_timesteps):
            for _ in range(1024):
                env.n_steps_env += 1
                loc = {"infos": [{"reward_valid": True}],
                       "rewards": [0.0]}
                if self._inject is not None:
                    self._inject(loc)
                callback.update_locals(loc)
                callback.on_step()
            self.num_timesteps = env.n_steps_env
            callback.on_rollout_end()
            self.train()
            self.logger.name_to_value["train/loss"] = \
                float(env.n_steps_env)
        return self

    def save(self, p, exclude=None):
        self._save_calls.append(
            {"path": p, "exclude": list(exclude or [])})
        th.save({}, p + ".zip")


def _sig_ref(m):
    import seed_extend as SXi
    return SXi._sig_json_norm(SC.fresh_signature(m))


TRACES = []
_per = 2112 // 128
_rem = 2112 - _per * 128
for i in range(128):
    n = _per + (1 if i < _rem else 0)
    TRACES.append({"remaining": 32 if i % 2 == 0 else 1,
                   "s0": 1 if i % 2 == 0 else -1,
                   "steps": [{"s": 1}] * n})


def _fake_eval(mm, tr, r, tag, lg, bk):
    r[tag + "_episodes"] = [
        {"index": i, "valid": True, "net_log": 0.0}
        for i in range(len(tr))]
    steps = sum(len(x["steps"]) for x in tr)
    r["steps"][tag] = steps
    for _ in range(steps):
        lg.add(1, tag)
    for t in tr:
        for _st in t["steps"]:
            mm.policy.predict(th.ones(1, 8))
    return steps


def _mk_run(tmp, m, **kw):
    # 生产 _real_ppo_run(guard 原样交 learn)
    d = dict(
        builder=lambda s, p: m,
        preteach=lambda mm, o, y, n, bk, r:
            [{"i": i} for i in range(n)],
        boundary_saver=lambda mm, od: {
            "path": "x", "sha256": "0" * 64,
            "params_digest": "1" * 64,
            "note": "新臂 post_aux 边界"},
        inner_eval=_fake_eval,
        clock=(lambda: 0.0, lambda: 0.0),
        initial_sig_ref=_sig_ref(m))
    d.update(kw)
    return AK.run(str(tmp), **d)


def test_verbatim():
    ours = AK.AUXKEEP_TRAIN_SRC
    theirs = AK._dedent8(inspect.getsource(PPO.train))
    assert AK.strip_insert(ours) == theirs


def test_tap_post_update_full_chain(tmp_path):
    m = _FakeModel()
    panels_batches = []

    def prun(mm, tag):
        assert mm.policy.training is False
        panels_batches.append(
            (tag,
             mm.policy.optimizer.steps))
        return {"rows": [0] * 8, "n_forwards": 1}
    rep = _mk_run(tmp_path / "a", m, panel_runner=prun)
    assert rep["status"] == "completed"
    assert m.policy.optimizer.steps == 1280
    assert m._auxkeep_n == 1280
    assert m._n_updates == 320
    assert len(panels_batches) == 6
    assert [p[0] for p in panels_batches[:2]] == \
        ["pre_aux", "post_aux"]
    taps = {p[0]: p[1] for p in panels_batches[2:]}
    assert taps["p8192"] == 320
    assert taps["p16384"] == 640
    assert taps["p24576"] == 960
    assert taps["p32768"] == 1280
    # 正式 train 全程非零梯度(生产链记录)
    assert m.policy.optimizer.grad_norms
    assert min(m.policy.optimizer.grad_norms) > 0
    assert set(rep["panels"]) >= {
        "panel_at_8192", "panel_at_16384",
        "panel_at_24576", "panel_at_32768"}
    assert len(rep["logger_rows"]) == 32
    assert rep["panels"]["param_hash_32768"] == \
        AK.params_digest(m)
    ex = [c for c in m._save_calls
          if c["path"].endswith("AK_final")]
    assert ex and ex[0]["exclude"] == ["train"]
    assert rep["total_real_env_steps"] == 34880
    assert len(rep["eval_actions"]["eval"]) == 2112
    assert (tmp_path / "a" / "DONE.marker").exists()


def test_guard_economic_failure(tmp_path):
    m = _FakeModel()

    def inj(loc):
        if m.pilot_env.n_steps_env == 5:
            loc["infos"][0]["economic_failure"] = "boom"
    m._inject = inj
    with pytest.raises(RuntimeError, match="economic"):
        _mk_run(tmp_path / "g", m)
    rep = json.loads((tmp_path / "g" / "auxkeep.json")
                     .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "economic" in rep["fail_reason"]


def test_guard_nonfinite_reward(tmp_path):
    m = _FakeModel()

    def inj(loc):
        if m.pilot_env.n_steps_env == 5:
            loc["rewards"] = [float("nan")]
    m._inject = inj
    with pytest.raises(RuntimeError, match="non-finite"):
        _mk_run(tmp_path / "nr", m)


def test_guard_invalid_reward_valid(tmp_path):
    m = _FakeModel()

    def inj(loc):
        if m.pilot_env.n_steps_env == 5:
            loc["infos"][0]["reward_valid"] = False
    m._inject = inj
    with pytest.raises(RuntimeError, match="reward_valid"):
        _mk_run(tmp_path / "rv", m)


def test_rollout_end_budget(tmp_path):
    class _Boom:
        def __init__(self):
            self.seen = []

        def checkpoint(self, ph):
            self.seen.append(ph)
            if ph == "rollout":
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SC.Book
    boom = _Boom()

    class _P:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc, p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    m = _FakeModel()
    orig = AK.SC.Book
    AK.SC.Book = _P
    try:
        with pytest.raises(RuntimeError,
                           match=r"budget\(rollout\)"):
            _mk_run(tmp_path / "rb", m)
    finally:
        AK.SC.Book = orig


def test_boundary_tamper_rejected(tmp_path):
    m = _FakeModel()
    info = AK.boundary_save(m, str(tmp_path / "b"))
    exp = {"params": AK._clone(m.policy.state_dict()),
           "optimizer": AK._clone(m.policy.optimizer.state_dict()),
           "state": DP._state_snapshot(m, m.pilot_env)}
    w0 = m.policy.action_net.lin.weight.detach().clone()
    with th.no_grad():
        m.policy.action_net.lin.weight[0, 0] += 1.0
    with pytest.raises(RuntimeError, match="params"):
        AK.boundary_verify(m, exp)
    with th.no_grad():
        m.policy.action_net.lin.weight.copy_(w0)
    m.policy.optimizer._pg[0]["lr"] = 1e-9
    with pytest.raises(RuntimeError, match="optimizer"):
        AK.boundary_verify(m, exp)
    m.policy.optimizer._pg[0]["lr"] = 3e-4
    st = np.random.get_state()
    np.random.seed(12345)
    with pytest.raises(RuntimeError, match="state"):
        AK.boundary_verify(m, exp)
    np.random.set_state(st)
    m._last_obs = th.zeros(9)
    with pytest.raises(RuntimeError, match="state"):
        AK.boundary_verify(m, exp)
    m._last_obs = None
    AK.boundary_verify(m, exp)
    assert info["payload_identity"]["sb3_version"] == "2.9.0"


def test_load_pollutes_live_rejected(tmp_path):
    m = _FakeModel()
    real_load = th.load

    def bad_load(*a, **k):
        np.random.seed(777)
        return real_load(*a, **k)
    orig = AK.th.load
    AK.th.load = bad_load
    try:
        with pytest.raises(RuntimeError, match="pollut"):
            AK.boundary_save(m, str(tmp_path / "pl"))
    finally:
        AK.th.load = orig


def test_partial_exclude_and_retention(tmp_path):
    class _Boom16384:
        def checkpoint(self, ph):
            if ph.startswith("tap_16384"):
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SC.Book
    boom = _Boom16384()

    class _P:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc, p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    m = _FakeModel()
    orig = AK.SC.Book
    AK.SC.Book = _P
    try:
        with pytest.raises(RuntimeError,
                           match=r"budget\(tap_16384\)"):
            _mk_run(tmp_path / "pr", m)
    finally:
        AK.SC.Book = orig
    rep = json.loads((tmp_path / "pr" / "auxkeep.json")
                     .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "tap_16384" in rep["fail_reason"]
    assert "panel_at_8192" in rep["panels"]
    assert "panel_at_16384" in rep["panels"]
    assert len(rep["logger_rows"]) >= 16
    assert rep["counts_sync"]["aux_attempted"] == 640
    ex = [c for c in m._save_calls
          if c["path"].endswith("partial_failure")]
    assert ex and ex[0]["exclude"] == ["train"]
    assert (tmp_path / "pr" / "partial_failure.zip").exists()
    assert (tmp_path / "pr" / "FAILED.marker").exists()


def test_ppo_and_aux_grads_nonzero():
    m = _FakeModel()
    _, obs, y, _ = DP.aux_inputs()
    loss_a, _ = DP.aux_objective_raw(
        DP.actor_raw8(m, obs), y)
    loss_a.backward()
    g1 = m.policy.action_net.lin.weight.grad
    assert g1 is not None and float(g1.abs().sum()) > 0
    m.policy.action_net.lin.weight.grad = None
    v, lp, ent = m.policy.evaluate_actions(
        th.ones(4, 8), th.zeros(4, 1))
    (-lp.mean()).backward()
    g2 = m.policy.action_net.lin.weight.grad
    assert g2 is not None and float(g2.abs().sum()) > 0
    m.policy.action_net.lin.weight.grad = None
    AK.install_auxkeep(
        m, obs, y,
        SC.Book(clock=(lambda: 0.0, lambda: 0.0)),
        {}, [], [],
        lambda mm, tag: {"rows": [0] * 8})
    m.policy.set_training_mode = lambda v: None
    before = m.policy.optimizer.steps
    m.train()
    assert m.policy.optimizer.steps - before == 40
    assert m._auxkeep_n == 40


def test_main_default_explicit(tmp_path, monkeypatch):
    calls = []

    def fake_run(out_dir, spec_path=None, **kw):
        calls.append((out_dir, spec_path))
        return {"status": "stub"}
    monkeypatch.setattr(AK, "run", fake_run)
    AK.main([str(tmp_path / "o1")])
    assert calls[-1][1] == str(
        pathlib.Path(AK._HERE) / "RUNSPEC_AUXKEEP.json")
    AK.main([str(tmp_path / "o2"), "--spec", "/tmp/x.json"])
    assert calls[-1][1] == "/tmp/x.json"
    with pytest.raises(SystemExit):
        AK.main([str(tmp_path / "o3"), "--mode", "debug"])
    assert len(calls) == 2


def _bad_eval(valid_val, with_net_log):
    def ev(mm, tr, r, tag, lg, bk):
        eps = []
        for i in range(len(tr)):
            e = {"index": i, "valid": valid_val}
            if with_net_log:
                e["net_log"] = 0.0
            eps.append(e)
        r[tag + "_episodes"] = eps
        steps = sum(len(x["steps"]) for x in tr)
        r["steps"][tag] = steps
        for _ in range(steps):
            lg.add(1, tag)
        for t in tr:
            for _st in t["steps"]:
                mm.policy.predict(th.ones(1, 8))
        return steps
    return ev


def test_strict_eval_negatives(tmp_path):
    m = _FakeModel()
    with pytest.raises(RuntimeError, match="net_log"):
        _mk_run(tmp_path / "nm", m,
                inner_eval=_bad_eval(True, False))
    m2 = _FakeModel()
    with pytest.raises(RuntimeError, match="valid"):
        _mk_run(tmp_path / "iv", m2,
                inner_eval=_bad_eval(1, True))


def test_status():
    assert AK.STATUS == "PREPARED_NOT_RUN"


def test_nan_aux_control(tmp_path):
    """假 aux 返回 NaN:FAILED/首错/attempted 与
    成功 optimizer 分计/JSON 可读/partial exclude/
    无额外 step。"""
    m = _FakeModel()
    real_aux = AK.DP.aux_objective_raw

    def nan_aux(raw, y):
        return (th.tensor(float("nan")),
                th.zeros(len(y)))
    AK.DP.aux_objective_raw = nan_aux
    try:
        with pytest.raises(
                RuntimeError,
                match="non-finite aux"):
            _mk_run(tmp_path / "na", m)
    finally:
        AK.DP.aux_objective_raw = real_aux
    rep = json.loads(
        (tmp_path / "na" / "auxkeep.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "failed"
    assert "non-finite aux" in rep[
        "fail_reason"]
    cs = rep["counts_sync"]
    assert cs["aux_attempted"] == 1
    assert cs["optimizer_success"] == 0
    assert cs["aux_invalid"]["i"] == 1
    assert m.policy.optimizer.steps == 0
    ex = [c for c in m._save_calls
          if c["path"].endswith(
              "partial_failure")]
    assert ex and ex[0]["exclude"] == \
        ["train"]
    assert (tmp_path / "na" /
            "FAILED.marker").exists()


def test_boundary_blob_tamper_via_production_load(
            tmp_path):
    """patch 生产 boundary_save 实际 th.load
    返回的 blob:RNG/source SHA 篡改均拒。"""
    m = _FakeModel()
    real_load = th.load

    def tamper_rng(*a, **k):
        blob = real_load(*a, **k)
        blob["state"]["torch"] = \
            blob["state"][
                "torch"] + 1
        return blob
    AK.th.load = tamper_rng
    try:
        with pytest.raises(
                RuntimeError,
                match="blob"):
            AK.boundary_save(
                m, str(tmp_path / "t1"))
    finally:
        AK.th.load = real_load

    def tamper_src(*a, **k):
        blob = real_load(*a, **k)
        blob["orig_train_sha256"] = \
            "x" * 64
        return blob
    AK.th.load = tamper_src
    try:
        with pytest.raises(
                RuntimeError,
                match="blob"):
            AK.boundary_save(
                m, str(tmp_path / "t2"))
    finally:
        AK.th.load = real_load


def test_boundary_live_tamper_via_production_load(
            tmp_path):
    """load 期改 live 参数/原地改 last_obs
    均拒。"""
    m = _FakeModel()
    real_load = th.load

    def live_param(*a, **k):
        with th.no_grad():
            m.policy.action_net.\
                lin.weight[0, 0] += 1.0
        return real_load(*a, **k)
    AK.th.load = live_param
    try:
        with pytest.raises(
                RuntimeError,
                match="live params"):
            AK.boundary_save(
                m, str(tmp_path / "l1"))
    finally:
        AK.th.load = real_load

    m2 = _FakeModel()
    m2._last_obs = th.zeros(4)
    real_load2 = th.load

    def live_obs(*a, **k):
        with th.no_grad():
            m2._last_obs[0] += 1.0
        return real_load2(*a, **k)
    AK.th.load = live_obs
    try:
        with pytest.raises(
                RuntimeError,
                match="polluted"):
            AK.boundary_save(
                m2,
                str(tmp_path / "l2"))
    finally:
        AK.th.load = real_load2
