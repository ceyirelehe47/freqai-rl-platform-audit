# -*- coding: utf-8 -*-
"""diag_panel v2 手写桩测(零真实权重/零真实 forward;
手写**不同** 4 行 branch/三原子/I;FakePolicy 检查
grad 关闭/eval 已设/hook 一次)。"""
import json
import math
import pathlib
import sys

import pytest
import torch as th

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import diag_panel as DP  # noqa

CFG_PATH = HERE / "CONFIG_diag.json"


def _patch_config_sha(monkeypatch, path=None):
    p = str(path or CFG_PATH)
    monkeypatch.setattr(DP, "CONFIG_SHA256",
                        DP.sha256_file(p))


def _fake_rows_params(i):
    """手写不同 4 行:branch/三原子/I 各异;Z 与 I 明显不同。"""
    return [
        # i=0 rem32 s+1:P_H=.55
        dict(branch=(.55, .45),
             atoms=(.20, .30, .25), interior=.25,
             alpha=2.0, beta=3.0),
        # i=1 rem32 s−1:P_H=.70
        dict(branch=(.70, .30),
             atoms=(.35, .10, .25), interior=.30,
             alpha=4.0, beta=1.5),
        # i=2 rem1 s+1:P_H=.40
        dict(branch=(.40, .60),
             atoms=(.10, .40, .20), interior=.30,
             alpha=1.2, beta=5.0),
        # i=3 rem1 s−1:P_H=.50
        dict(branch=(.50, .50),
             atoms=(.30, .15, .35), interior=.20,
             alpha=3.0, beta=3.0)][i]


class _FakeDist:
    """单样本固定分布(参数来自 _fake_rows_params)。"""

    def __init__(self, p):
        import math as m
        self.branch_logp = th.log(
            th.tensor([p["branch"]]))
        self.mix_logp = th.log(th.tensor(
            [[0.1, 0.2, 0.3, 0.4]]))
        self.alpha = th.tensor([p["alpha"]])
        self.beta = th.tensor([p["beta"]])
        a = p["atoms"]
        I = p["interior"]
        assert abs(sum(a) + I - 1.0) < 1e-12
        self._atoms = th.tensor([a])
        # Z 与 I 明显不同(Z=保留比例,I=mix_cont×Z)
        self._Z = 0.6
        self._logI = m.log(I)
        self._logZ = m.log(self._Z)

    def merged_atom_logp(self):
        return th.log(self._atoms)

    def interior_log_mass(self):
        return th.tensor([[self._logI]])

    @property
    def Z(self):
        return th.tensor([[self._Z]])


class _BatchDist:
    def __init__(self, dists):
        self._ds = dists

    def merged_atom_logp(self):
        return th.cat([d.merged_atom_logp()
                       for d in self._ds])

    def interior_log_mass(self):
        return th.cat([d.interior_log_mass()
                       for d in self._ds])

    @property
    def branch_logp(self):
        return th.cat([d.branch_logp
                       for d in self._ds])

    @property
    def mix_logp(self):
        return th.cat([d.mix_logp
                       for d in self._ds])

    @property
    def alpha(self):
        return th.cat([d.alpha for d in self._ds])

    @property
    def beta(self):
        return th.cat([d.beta for d in self._ds])

    @property
    def Z(self):
        return th.cat([d.Z for d in self._ds])


class _BatchView:
    def __init__(self, dists):
        self._dists = dists

    def mode(self):
        # 行 0/2:REBAL w=.25;行 1:HOLD w=0;行 3:REBAL w=-.5
        return th.tensor([[1.0, 0.25], [0.0, 0.0],
                          [1.0, 0.25], [1.0, -0.5]])

    @property
    def dist(self):
        return _BatchDist(self._dists)


class _FakePolicy:
    def __init__(self, counter):
        self._c = counter
        self.action_net = th.nn.Linear(8, 8)
        self.training = True
        self._net_calls = 0

    def set_training_mode(self, mode):
        self.training = bool(mode)

    def get_distribution(self, obs):
        self._c["forward"] += 1
        assert obs.shape == (4, 8)
        assert not th.is_grad_enabled(), "grad on"
        assert self.training is False, "eval not set"
        self.action_net(obs)      # 触发 hook
        self._net_calls += 1
        assert self._net_calls == 1, "hook>1"
        return _BatchView([
            _FakeDist(_fake_rows_params(i))
            for i in range(4)])


def _mk_model(counter):
    return type("M", (), {"policy": _FakePolicy(counter)})()


def test_two_loads_two_hooks_eight_rows(
        tmp_path, monkeypatch):
    _patch_config_sha(monkeypatch)
    loads = {"n": 0}
    fwd = {"forward": 0}

    def loader(path, device=None):
        loads["n"] += 1
        return _mk_model(fwd)
    out = tmp_path / "d"
    rep = DP.run(str(out), loader=loader,
                 get_dist=lambda pol, o:
                 pol.get_distribution(o))
    assert rep["n_loads"] == 2
    assert rep["n_forwards"] == 2
    assert rep["n_hooks"] == 2      # 每档恰 1
    assert fwd["forward"] == 2
    assert len(rep["rows"]) == 8
    assert (out / "DONE.marker").exists()
    oi = rep["obs_identity"]
    assert oi["sha256"] == DP.OBS_BYTES_SHA256
    assert oi["solvency_f32"] == 1.095545768737793
    # 逐行断言:行索引/条件与无条件总和/flat 分解/Z≠I
    by = {(r["ckpt"], r["rem"], r["s"]): r
          for r in rep["rows"]}
    for tag in ("initial", "final"):
        for i, (rem, s) in enumerate(DP.STATES):
            r = by[(tag, rem, s)]
            p = _fake_rows_params(i)
            assert r["P_hold"] == pytest.approx(
                p["branch"][0], rel=2e-6)
            assert r["merged_atoms_conditional"][
                "A_minus"] == pytest.approx(
                p["atoms"][0], rel=2e-6)
            assert r["interior_category_mass"] == \
                pytest.approx(p["interior"], rel=2e-6)
            assert r["beta_survival_Z"] == \
                pytest.approx(0.6, rel=2e-6)
            assert r["beta_survival_Z"] != \
                pytest.approx(
                    r["interior_category_mass"],
                    rel=1e-3)
            c = r["checks"]
            assert abs(c["cond_atoms_plus_I"] - 1) \
                <= 1e-6
            assert abs(c["uncond_total"] - 1) <= 1e-6
            assert r["effective_flat"] == \
                pytest.approx(
                    r["P_hold"]
                    + r["P_R_zero"], rel=1e-12)
            assert r["P_R_zero"] == pytest.approx(
                r["P_rebal"]
                * p["atoms"][1], rel=2e-6)
    # mode HOLD 行 w=0(行 1=s−1/rem32 fake)
    r1 = by[("initial", 32, -1)]
    assert r1["mode"][0] == 0.0
    assert r1["mode"][1] == 0.0


def test_identity_reject(tmp_path, monkeypatch):
    _patch_config_sha(monkeypatch)
    cfg = json.loads(CFG_PATH.read_text(encoding="utf-8"))
    cfg["pins"]["spec_sha256"] = "0" * 64
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(cfg), encoding="utf-8")
    _patch_config_sha(monkeypatch, bad)
    out = tmp_path / "d2"
    with pytest.raises(RuntimeError, match="spec SHA"):
        DP.run(str(out), cfg_path=str(bad))
    assert (out / "FAILED.marker").exists()


def test_obs_bytes_gate(tmp_path, monkeypatch):
    """观测字节身份门:篡改常量→拒(真实 run 同门)。"""
    _patch_config_sha(monkeypatch)
    monkeypatch.setattr(DP, "OBS_BYTES_SHA256",
                        "0" * 64)
    out = tmp_path / "d6"
    with pytest.raises(RuntimeError,
                       match="obs bytes SHA"):
        DP.run(str(out), loader=lambda p, device=None:
               _mk_model({"forward": 0}))
    assert (out / "FAILED.marker").exists()


def test_save_fail_first_cause(tmp_path, monkeypatch):
    _patch_config_sha(monkeypatch)
    real = json.dump

    def boom(*a, **k):
        raise OSError("disk gone")
    monkeypatch.setattr(json, "dump", boom)
    out = tmp_path / "d3"
    with pytest.raises(OSError):
        DP.run(str(out),
               loader=lambda p, device=None:
               _mk_model({"forward": 0}),
               get_dist=lambda pol, o:
               pol.get_distribution(o))
    assert (out / "FAILED.marker").exists()
    assert not (out / "DONE.marker").exists()


def test_budget_fail(tmp_path, monkeypatch):
    _patch_config_sha(monkeypatch)
    st = {"n": 0}

    def clock():
        st["n"] += 1
        if st["n"] > 5:
            return 100.0
        return 0.0
    out = tmp_path / "d4"
    with pytest.raises(RuntimeError, match="wall_clock"):
        DP.run(str(out),
               loader=lambda p, device=None:
               _mk_model({"forward": 0}),
               get_dist=lambda pol, o:
               pol.get_distribution(o),
               clock=(clock, lambda: 0.0))
    assert (out / "FAILED.marker").exists()


def test_spy_no_real_load(tmp_path, monkeypatch):
    _patch_config_sha(monkeypatch)
    import stable_baselines3 as sb3
    monkeypatch.setattr(
        sb3.PPO, "load",
        staticmethod(lambda *a, **k: (
            _ for _ in ()).throw(
            AssertionError("real PPO.load hit"))))
    out = tmp_path / "d5"
    rep = DP.run(str(out),
                 loader=lambda p, device=None:
                 _mk_model({"forward": 0}),
                 get_dist=lambda pol, o:
                 pol.get_distribution(o))
    assert rep["status"] == "completed"


def test_status():
    assert DP.STATUS == "PREPARED_NOT_RUN"
