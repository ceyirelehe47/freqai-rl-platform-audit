# -*- coding: utf-8 -*-
"""h1gate 手写假控制(走正式 CLI/实际调用链;
零真实模型/评价/训练之外的假对象)。"""
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
for d in ("dir_preteach_prep_20261017",
          "seed_extend_prep_20261017",
          "seed_contrast_prep_20261016",
          "teaching_pilot_prep_20261016",
          "diag_panel_prep_20261016"):
    sys.path.insert(
        0, "/mnt/f/trading/" + d)

import h1gate as H  # noqa: E402
import dir_preteach as DP  # noqa: E402
import seed_contrast as SC  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common. callbacks import BaseCallback  # noqa: E402


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
    """可微批分布面:branch_logp(n,2)/
    merged_atom_logp(n,3)——由 raw8 构造
    (merged 零原子=mix 零类,即本 fake 的
    mix_zero+mix_cont·b0 中 b0=0 特例;
    身份测试另行用显式数值)。"""

    def __init__(self, n, raw=None):
        self._n = n
        self._raw = raw

    def interior_log_mass(self):
        return th.log(
            th.full((self._n,), .05))

    def merged_atom_logp(self):
        mix = th.log_softmax(
            self._raw[:, 2:6], dim=-1)
        # mix 顺序 [-1,0,+1,cont]:
        # 零原子=mix_zero+mix_cont*b0
        # (b0=0 特例→mix[:,1])
        b0 = th.zeros(self._n)
        return th.stack(
            [mix[:, 0],
             th.log(
                 th.exp(mix[:, 1])
                 + th.exp(mix[:, 3]) * b0),
             mix[:, 2]], dim=1)

    @property
    def branch_logp(self):
        return th.log_softmax(
            self._raw[:, :2], dim=-1)

    @property
    def mix_logp(self):
        return th.log_softmax(
            self._raw[:, 2:6], dim=-1)

    @property
    def alpha(self):
        return th.nn.functional.softplus(
                self._raw[:, 6]) + 1

    @property
    def beta(self):
        return th.nn.functional.softplus(
                self._raw[:, 7]) + 1

    @property
    def Z(self):
        return th.ones(self._n)

    def mode(self):
        return th.zeros(self._n, 2)

    @property
    def dist(self):
        return self


class _FakeView:
    """仿 P0DistView:只 .dist/.arm(不透传)。"""

    def __init__(self, n, raw, arm="B"):
        self._n = n
        self.dist = _FakeDistBatch(n, raw)
        self.arm = arm

    def mode(self):
        return th.zeros(self._n, 2)


class _FakeOpt:
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
        groups = []
        for g in self._pg:
            gg = dict(g)
            gg["params"] = list(
                range(len(gg["params"])))
            groups.append(gg)
        return {"param_groups": groups,
                "state":
                    self._pol._opt_state}

    def load_state_dict(self, sd):
        self._pol._opt_state = sd["state"]
        groups = []
        for g in sd["param_groups"]:
            gg = dict(g)
            gg["params"] = self._live
            groups.append(gg)
        self._pg = groups

    def zero_grad(self, *a, **k):
        return None

    def step(self, *a, **k):
        gn = 0.0
        with th.no_grad():
            for p_ in self._pg[0][
                    "params"]:
                if p_.grad is not None:
                    gn += float(
                        p_.grad.abs()
                        .sum())
                p_.add_(1e-3)
        self.grad_norms.append(gn)
        self.steps += 1


class _FakePolicy:
    def __init__(self):
        self.action_net = _FakeActionNet()
        self._opt_state = {}
        self.optimizer = _FakeOpt(self)
        self.training = True
        self._gd_calls = []

    def extract_features(self, obs):
        return obs

    @property
    def mlp_extractor(self):
        pol = self

        class _M:
            def forward_actor(
                    self, x):
                return x
        return _M()

    def named_parameters(self):
        for n_, p_ in self.action_net.named_parameters():
            yield ("actor."
                   + n_, p_)
        yield ("value.v",
               th.zeros(
                   1,
                   requires_grad=
                       True))

    def parameters(self):
        for _, p_ in self.named_parameters():
            yield p_

    def set_training_mode(self, m):
        self.training = m

    def state_dict(self):
        return {
            "k": self.action_net.
            lin.weight.detach().
            clone()}

    def predict(self, obs,
                deterministic=False,
                *args, **kw):
        return (np.array(
            [[1.0, 0.0]]), None)

    def get_distribution(
            self, obs):
        raw = self.action_net(obs)
        self._gd_calls.append(
            obs.detach().clone())
        return _FakeView(
            len(obs), raw)

    def evaluate_actions(
            self, obs, acts):
        raw = self.action_net(obs)
        log_prob = raw.mean(dim=1)
        values = th.zeros(
            len(obs), 1)
        return (values,
                log_prob, None)


class _FakeBuf:
    _k = [0]

    def __init__(self):
        self.values = np.zeros(1024)
        self.returns = np.zeros(1024)

    def get(self, bs):
        for _ in range(4):
            k = self._k[0]
            self._k[0] += 1
            idx = th.arange(bs) + k
            yield type("RD", (), {
                "actions":
                    th.zeros(bs, 1),
                "observations":
                    th.randn(bs, 8),
                "advantages":
                    th.sin(idx.float())
                    * 0.5,
                "old_values":
                    th.zeros(bs),
                "returns":
                    th.zeros(bs),
                "old_log_prob":
                    th.zeros(bs)})()


class _FakeModel:
    _pilot_stub = True

    def __init__(self):
        self.policy = _FakePolicy()
        import types
        self.pilot_env = types.SimpleNamespace(
                n_steps_env=0,
                rng=random.Random(0),
                _terminated=False)
        self.num_timesteps = 0
        self._n_updates = 0
        self.rollout_buffer = _FakeBuf()
        self.n_epochs = 10
        self.batch_size = 256
        self.action_space = object()
        self.logger = type(
            "L", (), {
                "name_to_value": {},
                "record": lambda *a,
                **k: None})()
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
              reset_num_timesteps=True,
              callback=None, **k):
        if callback:
            callback.init_callback(self)
        env = self.pilot_env
        while env.n_steps_env < int(total_timesteps):
            for _ in range(1024):
                env.n_steps_env += 1
                loc = {
                    "infos": [
                        {"reward_valid":
                         True}],
                    "rewards": [0.0]}
                if self._inject is not None:
                    self._inject(loc)
                callback.update_locals(loc)
                callback.on_step()
            self.num_timesteps = env.n_steps_env
            callback.on_rollout_end()
            self.train()
            self.logger.name_to_value[
                    "train/loss"] = float(env.
                      n_steps_env)
        self._pilot_opt_count = {
            "n": self.policy.
            optimizer.steps}
        return self

    def save(self, p,
             exclude=None):
        self._save_calls.append(
            {"path": p,
             "exclude":
                 list(exclude
                      or [])})
        th.save({}, p + ".zip")


def _sig_ref(m):
    import seed_extend as SXi
    return SXi._sig_json_norm(
            SC.fresh_signature(m))


TR = []
_per = 2112 // 128
_rem = 2112 - _per * 128
for _i in range(128):
    _n = _per + (
        1 if _i < _rem else 0)
    TR.append({
        "remaining":
            32 if _i % 2 == 0
            else 1,
        "s0": 1 if _i % 2 == 0
        else -1,
        "steps":
            [{"s": 1}] * _n})


def _fake_eval(mm, tr, r, tag,
               lg, bk):
    r[tag + "_episodes"] = [
        {"index": i,
         "valid": True,
         "net_log": 0.0}
        for i in range(len(tr))]
    steps = sum(
        len(x["steps"])
        for x in tr)
    r["steps"][tag] = steps
    for _ in range(steps):
        lg.add(1, tag)
    for t in tr:
        for _st in t["steps"]:
            mm.policy.predict(
                th.ones(1, 8))
    return steps


def _mk_spec(tmp, tr):
    import hashlib
    spec = json.loads(
        pathlib.Path(
            H._HERE,
            "RUNSPEC_H1GATE.json")
        .read_text(
            encoding="utf-8"))
    canon = hashlib.sha256(
        json.dumps(
            tr, sort_keys=True,
            separators=(",", ":")
        ).encode()).hexdigest()
    spec["identity_expected"][
        "traces_canon_"
        "sha256"] = canon
    p = tmp / "spec.json"
    p.write_text(
        json.dumps(
            spec,
            ensure_ascii=False,
            indent=1) + "\n",
        encoding="utf-8")
    return str(p), hashlib.sha256(
            p.read_bytes()
        ).hexdigest()


_CUR_SPEC = [None]


def _mk_run(tmp, m, **kw):
    d = dict(
        builder=lambda s, p: m,
        preteach=lambda mm, o,
            y, n, bk, r: [
            {"i": i}
            for i in range(n)],
        boundary_saver=lambda
            mm, od: {
            "path": "x",
            "sha256":
                "0" * 64},
        boundary_comparer=lambda
            mm, pt: {
            "matched": False,
            "boundary":
                "post_aux_new",
            "reason":
                "prep stub"},
        inner_eval=_fake_eval,
        clock=(lambda: 0.0,
               lambda: 0.0),
        initial_sig_ref=
            _sig_ref(m))
    d.update(kw)
    d.setdefault("spec_path", _CUR_SPEC[0])
    d.setdefault("traces", TR)
    d.setdefault("panel_runner",
                 lambda mm, tag: {
                     "rows": [0] * 8,
                     "n_forwards": 1,
                     "obs_canon_sha256":
                         "0" * 64})
    return H.run(
        str(tmp), **d)


def _pin_digest(monkeypatch):
    monkeypatch.setattr(
        H, "params_digest",
        lambda policy:
        "44cb869039a5c550"
        "2804e575d4936cc5"
        "8ba4e47e2f71d6e4"
        "919b1928a3c78d2a")


def test_verbatim():
    assert H.strip_insert(
        H.H1G_TRAIN_SRC) == H._dedent8(
            inspect.getsource(
                PPO.train))


def test_gate_inputs_domain():
    """H1 域隔离:gate 两行 rem=1/s±/q=1,
    与方向 4 行(rem=32)零重叠。"""
    states, obs, sha = H.gate_inputs()
    assert states == [
        (1, 1, 1.0),
        (1, -1, 1.0)]
    _, obs_dir, _, dir_sha = DP.aux_inputs()
    assert obs.shape == (2, 8)
    assert obs_dir.shape == (4, 8)
    # rem 列(索引 6)gate=1/128,
    # dir=32/128——零重叠
    g_rems = obs[:, 6].tolist()
    d_rems = obs_dir[:, 6].tolist()
    assert g_rems == [
        1 / 128, 1 / 128]
    assert d_rems == [
        32 / 128] * 4
    assert sha == H.GATE_OBS_SHA256
    assert dir_sha == H.DIR_OBS_PIN


def test_merged_zero_atom_and_p_flat_identity():
    """显式数值:零原子= mix_zero+
    mix_cont·b0;p_flat=pH+
    (1−pH)·p0(log 域合成一致)。"""
    mix = th.log(th.tensor(
        [[.2, .3, .1, .4]]))
    b0 = 0.25  # 连续零单元
    zero = .3 + .4 * b0
    blp = th.log(th.tensor(
        [[.6, .4]]))
    atoms = th.log(th.stack(
        [th.tensor([.2]),
         th.tensor([zero]),
         th.tensor([.1])],
        dim=1))
    class _D:
        branch_logp = blp

        def merged_atom_logp(self):
            return atoms
    v = _FakeView(1, th.zeros(1, 8))
    v.dist = _D()
    lp = H.log_p_flat_rows(v)
    # arm 门:非 B 拒
    v2 = _FakeView(1, th.zeros(1, 8), arm="A")
    with pytest.raises(RuntimeError,
                       match="frozen B"):
        H.log_p_flat_rows(v2)
    pH = th.exp(blp[0, 0])
    p0 = zero
    expect = pH + (1 - pH) * p0
    got = float(
        th.exp(lp[0]))
    assert got == pytest.approx(
            float(expect),
            rel=1e-5)


def test_install_train_counts_and_grads():
    """正式 train:dir_n==gate_n==
    optimizer step;两项梯度
    非零;一次 backward 一步。"""
    m = _FakeModel()
    _, obs_dir, y, _ = DP.aux_inputs()
    _, obs_gate, _ = H.gate_inputs()
    H.install_h1gate(
        m, obs_dir, y,
        obs_gate,
        SC.Book(clock=(
            lambda: 0.0,
            lambda: 0.0)),
        {}, [], [],
        lambda mm, tag: {
            "rows": [0] * 8})
    m.rollout_buffer = _FakeBuf()
    m.policy.set_training_mode = lambda v: None
    before = m.policy.optimizer.steps
    m.train()
    assert m.policy.optimizer.steps - before == 40
    assert m._h1g_dir_n == 40
    assert m._h1g_gate_n == 40
    assert m.policy.optimizer.grad_norms
    assert min(m.policy.
               optimizer.
               grad_norms) > 0
    # gate 输入恰为两行
    # rem=1 obs(域隔离:
    # get_distribution
    # 收到的就是这个)
    gd_obs = m.policy._gd_calls
    assert all(
        o.shape == (2, 8)
        for o in gd_obs)
    assert all(
        float(o[0, 6]) ==
        1 / 128
        for o in gd_obs)


def test_full_fake_chain(
        tmp_path,
        monkeypatch):
    """生产 _real_ppo_run 驱动:
    六批面板/阈值计数/32 logger/
    数据双文件/DONE/34880。"""
    m = _FakeModel()
    panels_batches = []

    def prun(mm, tag):
        assert mm.policy.training is False
        panels_batches.append(
            (tag,
             mm.policy.
             optimizer.
             steps))
        return {"rows":
                    [0] * 8,
                "n_forwards": 1}
    sp, sh = _mk_spec(
        tmp_path, TR)
    orig_pin = H.RUNSPEC_SHA256
    H.RUNSPEC_SHA256 = sh
    _CUR_SPEC[0] = sp
    try:
        rep = _mk_run(
            tmp_path / "a", m,
            panel_runner=prun)
    finally:
        H.RUNSPEC_SHA256 = orig_pin
    assert rep[
        "status"] == "completed"
    assert m.policy.optimizer.steps == 1280
    assert m._h1g_dir_n == 1280
    assert m._h1g_gate_n == 1280
    assert len(
        panels_batches) == 6
    taps = {
        p[0]: p[1]
        for p in
        panels_batches[2:]}
    assert taps[
        "p8192"] == 320
    assert taps[
        "p16384"] == 640
    assert taps[
        "p24576"] == 960
    assert taps[
        "p32768"] == 1280
    assert len(rep[
        "logger_rows"]) == 32
    assert rep[
        "boundary_vs_"
        "auxkeep"][
        "boundary"] == "post_aux_new"
    assert rep[
        "total_real_"
        "env_steps"] == 34880
    assert len(rep[
        "eval_actions"]
        ["eval"]) == 2112
    assert (tmp_path /
            "a" /
            "DONE.marker").exists()
    assert (tmp_path /
            "a" /
            "eval_data.json").exists()
    assert (tmp_path /
            "a" /
            "eval_actions"
            ".json").exists()
    ex = [c for c in
          m._save_calls
          if c["path"].
          endswith(
              "H1G_final")]
    assert ex and ex[0][
        "exclude"] == ["train"]
    receipt = json.loads(
        (tmp_path / "a" /
         "h1gate.json")
        .read_text(
            encoding="utf-8"))
    assert receipt[
        "status"] == "completed"


def test_serialization_refused_keeps_data(
        tmp_path,
        monkeypatch):
    class _Weird:
        pass
    _pin_digest(monkeypatch)

    def ev_w(mm, tr, r,
             tag, lg, bk):
        _fake_eval(
            mm, tr, r,
            tag, lg, bk)
        r["weird"] = _Weird()
        return r["steps"][
            tag]
    m = _FakeModel()
    sp, sh = _mk_spec(
        tmp_path, TR)
    orig_pin = H.RUNSPEC_SHA256
    H.RUNSPEC_SHA256 = sh
    _CUR_SPEC[0] = sp
    try:
        with pytest.raises(
                RuntimeError,
                match=
                    "serialization"
                    " refused"):
            _mk_run(
                tmp_path / "s",
                m,
                inner_eval=ev_w)
    finally:
        H.RUNSPEC_SHA256 = orig_pin
    receipt = json.loads(
        (tmp_path / "s" /
         "h1gate.json")
        .read_text(
            encoding="utf-8"))
    assert receipt[
        "status"] == "serialization" "_refused"
    assert (tmp_path /
            "s" /
            "eval_data.json").exists()


def test_tap_budget_midfailure(tmp_path,
           monkeypatch):
    class _Boom:
        def checkpoint(
                self, ph):
            if ph == "tap_16384":
                return ("wall",
                        {"wall_s":
                         1e3},
                        {})
            return (None, {},
                    {})
    real = SC.Book
    boom = _Boom()

    class _P:
        def __init__(
                self, *a,
                **k):
            self._r = real(
                *a, **k)

        def checkpoint(
                self, ph):
            w, c, p2 = boom.checkpoint(
                    ph)
            rw, rc, rp = self._r.checkpoint(
                    ph)
            return (w or rw,
                    c if w
                    else rc,
                    p2 if w
                    else rp)

        def snapshot(
                self):
            return self._r.snapshot()
    _pin_digest(monkeypatch)
    m = _FakeModel()
    orig = H.SC.Book
    H.SC.Book = _P
    try:
        sp, sh = _mk_spec(
            tmp_path, TR)
        orig_pin = H.RUNSPEC_SHA256
        H.RUNSPEC_SHA256 = sh
        _CUR_SPEC[0] = sp
        try:
            with pytest.raises(
                        RuntimeError,
                        match=r"budget"
                              r"\(tap_"
                              r"16384\)"):
                _mk_run(
                    tmp_path /
                    "pr", m)
        finally:
            H.RUNSPEC_SHA256 = orig_pin
    finally:
        H.SC.Book = orig
    rep = json.loads(
        (tmp_path / "pr" /
         "h1gate.json")
        .read_text(
            encoding="utf-8"))
    assert rep[
        "status"] == "failed"
    assert rep[
        "counts_sync"][
        "gate_attempted"] == 640
    assert rep[
        "counts_sync"][
        "dir_attempted"] == 640
    ex = [c for c in
          m._save_calls
          if c["path"].
          endswith(
              "partial_"
              "failure")]
    assert ex and ex[0][
        "exclude"] == ["train"]
    assert (tmp_path /
            "pr" /
            "FAILED.marker").exists()
    assert "panel_at_" "8192" in rep[
            "panels"]


def test_boundary_compare_branches(
        tmp_path):
    m = _FakeModel()
    m.policy._opt_state = {}
    real_save = H.boundary_save
    info = real_save(
        m, str(tmp_path))
    # matched:现有档=当前快照
    res = H.boundary_compare(
        m, info["path"])
    assert res[
        "matched"] is True
    assert res[
        "boundary"] == "post_aux_matched"
    # mismatch:改 live 参数
    w0 = m.policy.action_net.lin.weight.detach().clone()
    with th.no_grad():
        m.policy.action_net.lin.weight[0, 0] += 1.0
    res2 = H.boundary_compare(
            m, info["path"])
    assert res2[
        "matched"] is False
    assert res2[
        "boundary"] == "post_aux_new"
    assert res2[
        "params_equal"] is False
    with th.no_grad():
        m.policy.action_net.lin.weight.copy_(w0)
    # 缺档→明确新边界
    res3 = H.boundary_compare(
            m,
            str(tmp_path /
                "absent.pt"))
    assert res3[
        "matched"] is False
    assert res3[
        "boundary"] == "post_aux_new"


def test_nonfinite_gate_stops_without_step(
        tmp_path):
    m = _FakeModel()
    _, obs_dir, y, _ = DP.aux_inputs()
    _, obs_gate, _ = H.gate_inputs()
    real_gd = m.policy.get_distribution

    def gd_nan(obs):
        view = real_gd(obs)
        return view
    H.install_h1gate(
        m, obs_dir, y,
        obs_gate,
        SC.Book(clock=(
            lambda: 0.0,
            lambda: 0.0)),
        {}, [], [],
        lambda mm, tag: {
            "rows": [0] * 8})
    # 注入:branch_logp 含
    # -inf→lp_flat 非有限
    orig_view = _FakeView

    class _NanView(
            orig_view):
        pass
    m.rollout_buffer = _FakeBuf()
    m.policy.set_training_mode = lambda v: None
    # 用 hook:直接让 gate
    # 观测产生 nan 参数路径
    with th.no_grad():
        m.policy.action_net.lin.weight[0, 0] = float("nan")
    with pytest.raises(
            RuntimeError,
            match=
                "non-finite"):
        m.train()
    assert m._h1g_dir_n == 1
    assert m._h1g_invalid[
        "term"] in (
            "dir", "gate")
    # 无额外 optimizer step
    assert m.policy.optimizer.steps == 0


def test_main_default_explicit(tmp_path,
         monkeypatch):
    calls = []

    def fake_run(
            out_dir,
            spec_path=None,
            **kw):
        calls.append(
            (out_dir,
             spec_path))
        return {"status":
                "stub"}
    monkeypatch.setattr(
        H, "run",
        fake_run)
    H.main([
        str(tmp_path /
            "o1")])
    assert calls[-1][1] == str(
            pathlib.Path(
                H._HERE)
            / "RUNSPEC_"
              "H1GATE"
              ".json")
    H.main([
        str(tmp_path /
            "o2"),
        "--spec",
        "/tmp/x.json"])
    assert calls[-1][1] == "/tmp/x.json"
    with pytest.raises(
            SystemExit):
        H.main([
            str(tmp_path /
                "o3"),
            "--mode",
            "debug"])
    assert len(calls) == 2


def test_strict_eval_missing_net_log(
        tmp_path,
        monkeypatch):
    _pin_digest(monkeypatch)

    def ev_missing(
            mm, tr, r,
            tag, lg, bk):
        r[tag
          + "_episodes"] = [
            {"index": i,
             "valid": True}
            for i in
            range(len(tr))]
        steps = sum(
            len(x["steps"])
            for x in tr)
        r["steps"][
            tag] = steps
        for _ in range(
                steps):
            lg.add(1, tag)
        for t in tr:
            for _st in t[
                    "steps"]:
                mm.policy.predict(
                        th.ones(
                            1, 8))
        return steps
    m = _FakeModel()
    sp, sh = _mk_spec(
        tmp_path, TR)
    orig_pin = H.RUNSPEC_SHA256
    H.RUNSPEC_SHA256 = sh
    _CUR_SPEC[0] = sp
    try:
        with pytest.raises(
                RuntimeError,
                match=
                    "net_log"):
            _mk_run(
                tmp_path /
                "nm", m,
                inner_eval=
                    ev_missing)
    finally:
        H.RUNSPEC_SHA256 = orig_pin


def test_status():
    assert H.STATUS == "PREPARED_NOT_RUN"


def test_dir_and_gate_grads_separate():
    """方向项、gate 项各自把梯度送到 actor。"""
    m = _FakeModel()
    _, obs_dir, y, _ = DP.aux_inputs()
    _, obs_gate, _ = H.gate_inputs()
    # 仅方向项
    loss_d, _ = DP.aux_objective_raw(
        DP.actor_raw8(m, obs_dir), y)
    loss_d.backward()
    g1 = m.policy.action_net.lin.weight.grad
    assert g1 is not None and float(g1.abs().sum()) > 0
    m.policy.action_net.lin.weight.grad = None
    # 仅 gate 项(含非零 b0 数值控制)
    raw = m.policy.action_net(obs_gate)
    # (非零 b0 语义由 identity 数值控制覆盖;
    # 梯度仅证可达,不经 b0。)
    view = _FakeView(2, raw)
    lp = H.log_p_flat_rows(view)
    assert float(th.exp(lp).min()) > 0
    (-lp.mean()).backward()
    g2 = m.policy.action_net.lin.weight.grad
    assert g2 is not None and float(g2.abs().sum()) > 0


def test_gate_only_nan_first_cause(tmp_path):
    """gate 单独 NaN:gate 首因·dir/gate 各
    attempted 1·optimizer 0。"""
    m = _FakeModel()
    _, obs_dir, y, _ = DP.aux_inputs()
    _, obs_gate, _ = H.gate_inputs()

    class _NanDist:
        def __init__(self):
            self.branch_logp = th.tensor(
                [[float("nan"), float("nan")],
                 [float("nan"), float("nan")]])

        def merged_atom_logp(self):
            return th.zeros(2, 3)
    real_gd = m.policy.get_distribution

    def gd_bad(obs):
        v = real_gd(obs)
        if obs.shape[0] == 2 and \
                float(obs[0, 6]) == 1 / 128:
            v.dist = _NanDist()
        return v
    m.policy.get_distribution = gd_bad
    H.install_h1gate(
        m, obs_dir, y, obs_gate,
        SC.Book(clock=(lambda: 0.0, lambda: 0.0)),
        {}, [], [],
        lambda mm, tag: {"rows": [0] * 8})
    m.rollout_buffer = _FakeBuf()
    m.policy.set_training_mode = lambda v: None
    with pytest.raises(RuntimeError,
                       match="non-finite gate"):
        m.train()
    assert m._h1g_dir_n == 1
    assert m._h1g_gate_n == 1
    assert m._h1g_invalid["term"] == "gate"
    assert m.policy.optimizer.steps == 0


def test_data_write_ser_refused(tmp_path, monkeypatch):
    """数据先写遇 SerializationError→最小 refused
    receipt+已落原件保留。"""
    class _W:
        pass
    _pin_digest(monkeypatch)

    def ev_w(mm, tr, r, tag, lg, bk):
        _fake_eval(mm, tr, r, tag, lg, bk)
        r["eval_episodes"][0]["weird"] = _W()
        return r["steps"][tag]
    m = _FakeModel()
    sp, sh = _mk_spec(tmp_path, TR)
    orig_pin = H.RUNSPEC_SHA256
    H.RUNSPEC_SHA256 = sh
    _CUR_SPEC[0] = sp
    try:
        with pytest.raises(RuntimeError,
                           match="serialization refused"):
            _mk_run(tmp_path / "dw", m,
                    inner_eval=ev_w)
    finally:
        H.RUNSPEC_SHA256 = orig_pin
    rep = json.loads(
        (tmp_path / "dw" / "h1gate.json")
        .read_text(encoding="utf-8"))
    assert rep["status"] == "serialization_refused"
    assert rep["diag"]["kind"] == "unknown-type"
    # 已落原件保留:actions 在 except 路落
    assert (tmp_path / "dw" /
            "eval_actions.json").exists()
    assert (tmp_path / "dw" /
            "FAILED.marker").exists()


def test_post_save_overlimit_receipt_fail(
        tmp_path, monkeypatch):
    """post_save 超限+receipt 覆写失败→无 DONE/
    FAILED 尽力/原预算异常保留。"""
    import seed_contrast as SCi
    _pin_digest(monkeypatch)

    class _Boom:
        def checkpoint(self, ph):
            if ph == "post_save":
                return ("wall", {"wall_s": 1e3}, {})
            return (None, {}, {})
    real = SCi.Book
    boom = _Boom()

    class _PB:
        def __init__(self, *a, **k):
            self._r = real(*a, **k)

        def checkpoint(self, ph):
            w, c, p2 = boom.checkpoint(ph)
            rw, rc, rp = self._r.checkpoint(ph)
            return (w or rw, c if w else rc,
                    p2 if w else rp)

        def snapshot(self):
            return self._r.snapshot()
    orig_book = H.SC.Book
    H.SC.Book = _PB
    real_aw = H.atomic_write_json
    st = {"receipt_writes": 0}

    def aw(obj, path):
        if path.endswith("h1gate.json"):
            st["receipt_writes"] += 1
            if st["receipt_writes"] > 1:
                raise OSError("disk gone")
        return real_aw(obj, path)
    monkeypatch.setattr(H, "atomic_write_json", aw)
    try:
        sp, sh = _mk_spec(tmp_path, TR)
        orig_pin = H.RUNSPEC_SHA256
        H.RUNSPEC_SHA256 = sh
        _CUR_SPEC[0] = sp
        try:
            with pytest.raises(
                    RuntimeError,
                    match=r"budget\(post_save\)"):
                _mk_run(tmp_path / "pf", _FakeModel())
        finally:
            H.RUNSPEC_SHA256 = orig_pin
    finally:
        H.SC.Book = orig_book
    assert not (tmp_path / "pf" / "DONE.marker").exists()
    assert (tmp_path / "pf" / "FAILED.marker").exists()


def test_boundary_semantic_env_id():
    """旧/新 env_id 不同而语义值相同→matched;
    一个值不同→new;比较零污染。"""
    m = _FakeModel()
    m.policy._opt_state = {}
    import tempfile, pathlib as P
    with tempfile.TemporaryDirectory() as td:
        info = H.boundary_save(m, td)
        # matched:同 payload 语义(env_id 同也匹配)
        res = H.boundary_compare(m, info["path"])
        assert res["matched"] is True
        # 模拟跨运行:改档内 env_id,语义不变
        blob = th.load(info["path"],
                       weights_only=False)
        blob["state"]["env_id"] = "other-run"
        p2 = P.Path(td) / "shifted.pt"
        th.save(blob, p2)
        res2 = H.boundary_compare(m, str(p2))
        assert res2["matched"] is True
        # 语义值不同(torch RNG)→new
        blob2 = th.load(info["path"],
                        weights_only=False)
        blob2["state"]["torch"] = \
            blob2["state"]["torch"] + 1
        p3 = P.Path(td) / "rng.pt"
        th.save(blob2, p3)
        res3 = H.boundary_compare(m, str(p3))
        assert res3["matched"] is False
        assert res3["boundary"] == "post_aux_new"
        assert res3["state_equal"] is False


def test_compare_load_pollution_rejected():
    """假 load 分别污染 live params/Adam→拒;
    正常 matched 对照。"""
    m = _FakeModel()
    m.policy._opt_state = {}
    import tempfile
    import pathlib as P
    with tempfile.TemporaryDirectory() as td:
        info = H.boundary_save(m, td)
        real_load = H.th.load

        def poll_params(*a, **k):
            blob = real_load(*a, **k)
            with th.no_grad():
                m.policy.action_net.lin.\
                    weight[0, 0] += 1.0
            return blob
        w0 = m.policy.action_net.lin.\
            weight.detach().clone()
        H.th.load = poll_params
        try:
            with pytest.raises(
                    RuntimeError,
                    match="polluted live "
                          "\\(params\\)"):
                H.boundary_compare(
                    m, info["path"])
        finally:
            H.th.load = real_load
        with th.no_grad():
            m.policy.action_net.lin.\
                weight.copy_(w0)

        def poll_adam(*a, **k):
            blob = real_load(*a, **k)
            m.policy.optimizer.\
                _pg[0]["lr"] = 1e-9
            return blob
        H.th.load = poll_adam
        try:
            with pytest.raises(
                    RuntimeError,
                    match="polluted live "
                          "\\(optimizer\\)"):
                H.boundary_compare(
                    m, info["path"])
        finally:
            H.th.load = real_load
        m.policy.optimizer._pg[0][
            "lr"] = 3e-4
        res = H.boundary_compare(
            m, info["path"])
        assert res["matched"] is True
