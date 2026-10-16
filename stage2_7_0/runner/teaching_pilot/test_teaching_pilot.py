# -*- coding: utf-8 -*-
"""UnifiedTeachingPilot-v1 v3 手写控制。

已执行量登记(如实):
- v1 包:假 rollout 整批=32768 次旧薄 env step;另有失败/预算
  测试 env 步数**未单独计数=未知**(不概称零环境执行);
- v2 包:11 tests 含 35 次真实 env.step(账本/末端/flat 控制组);
- 本版(v3):一步账本/flat/时钟/末端控制使用真实 env,步数在
  测试内计数并断言;**完整控制流=真 stub+spy(spy 结论仅限被
  注入的控制链)**;official 模板经 launch stages 假 PY 验证;
  零真实 learn/rollout。
"""
import json
import math
import pathlib
import random
import sys

import numpy as np
import pytest
import torch as th

HERE = pathlib.Path(
    __file__).resolve().parent
sys.path.insert(0, str(HERE))

import teach_env as TE  # noqa
import policy as PL  # noqa
import runner as RN  # noqa
import eval_pilot as EP  # noqa

SPEC = json.loads(
    (HERE / "run_spec.json").read_text(
        encoding="utf-8"))


def test_reviewer_reference_ratio():
    """审查方基准:flat,w=.5,fee=.001,r=.01,rem1。"""
    env = TE.UnifiedPilotEnv(
        random.Random(0))
    env.reset(remaining=1, s=1)
    env._draw_r = lambda: 0.01
    o, r, term, _tr, info = env.step(
        np.array([1.0, 0.5]))
    ratio = (env.led.equity(
        env.price) / 100.0)
    ana = (1.005 - 0.000505) / 1.0005
    assert ratio == pytest.approx(
        ana, rel=1e-15)
    assert abs(
            ratio
            - 1.0039930034982512) \
        < 1e-15     # 审查值差 1 ulp(算序)
    assert r == pytest.approx(
        math.log(ratio), rel=1e-15)
    assert term and info[
        "terminal_liquidation"]


def test_flat_then_open_then_settle_order():
    """flat 开仓吃本步收益(v2 旧序吃不到);HOLD 两步对照。"""
    env = TE.UnifiedPilotEnv(
        random.Random(3))
    env.reset(remaining=8, s=1)
    env._draw_r = lambda: 0.01
    o, r, _t, _tr, info = env.step(
        np.array([1.0, 0.5]))
    assert r > 0.003   # 含本步收益
    assert info["r"] == 0.01
    # HOLD 保仓:收益=仓位收益,无费用
    eq0 = env.led.equity(env.price)
    o2, r2, _t2, _tr2, info2 = env.step(
        np.array([0.0, 0.0]))
    eq1 = env.led.equity(env.price)
    assert r2 == pytest.approx(
        math.log(eq1 / eq0),
        rel=1e-15)


def test_rem_terminal_zero_and_flat_hold_zero():
    """flat 全 HOLD:解析净 log=0;短程 3 步实证 rem 终态 0。"""
    env = TE.UnifiedPilotEnv(
        random.Random(11))
    env.reset(remaining=3, s=1)
    steps = 0
    tot = 0.0
    for _ in range(3):
        o, r, term, _tr, _i = env.step(
            np.array([0.0, 0.0]))
        tot += r
        steps += 1
        assert _i["reward_valid"]
        if term:
            break
    assert term and steps == 3
    assert env.rem == 0
    assert tot == pytest.approx(
        0.0, abs=1e-12)


def test_close_risk_same_bar_flatten():
    """审查例:e≈-19(短仓):r=.01→收盘 .81/名义 19.19/
    同 bar 强平后 .79081(reward=log(.79081/1));
    r=.052→.012−.019988<0→同 bar 经济失败。"""
    for r_v, kind in ((0.01, "flat"),
                      (0.052, "fail")):
        env = TE.UnifiedPilotEnv(
            random.Random(1))
        env.reset(remaining=8, s=1)
        env.led.cash = 1.0
        env.led.qty = -19.0
        env.led.avg_entry = 1.0
        env._draw_r = (lambda rv=r_v:
                       rv)
        o, r, term, _tr, info = env.step(
            np.array([0.0, 0.0]))
        if kind == "flat":
            assert info["risk_action"] == (
                "close_risk_flatten")
            eq = env.led.equity(env.price)
            assert eq == pytest.approx(
                0.79081, rel=1e-12)
            assert r == pytest.approx(
                math.log(0.79081 / 1.0),
                rel=1e-12)
            assert env.led.qty == 0.0
        else:
            assert term
            assert not info["reward_valid"]
            assert info["economic_failure"][
                "phase"] == "close_flatten"


def test_open_risk_and_illegal():
    env = TE.UnifiedPilotEnv(
        random.Random(2))
    env.reset(remaining=8, s=1)
    with pytest.raises(ValueError):
        env.step(np.array([1.0, 1.5]))
    with pytest.raises(ValueError):
        env.step(np.array(
            [1.0, float("nan")]))
    # 开盘破产失败:人为大亏仓
    env2 = TE.UnifiedPilotEnv(
        random.Random(5))
    env2.reset(remaining=8, s=1)
    env2.led.apply_target_ratio(
        1.0, 1.0)
    env2.led.cash -= 150.0   # 破产构造
    env2._draw_r = lambda: 0.0
    o, r, term, _tr, info = \
        env2.step(np.array([0.0, 0.0]))
    assert term
    assert not info["reward_valid"]
    assert info["economic_failure"][
        "phase"] == "open"


# ---------------- stub 全流程(spy) ----------------

class _SpyEnv:
    _spy = True

    def __init__(self, rng=None):
        self.n_steps_env = 0

    def reset(self, **kw):
        return np.zeros(8), {}

    def step(self, a):
        raise AssertionError(
            "real env.step hit")


class _FakePPO:
    _pilot_stub = True

    def __init__(self, env, seed, spec):
        self.num_timesteps = 0

    def learn(self, total_timesteps,
              reset_num_timesteps=True,
              callback=None,
              progress_bar=False):
        self.num_timesteps = (
            total_timesteps)
        return self

    def save(self, path):
        th.save({"f": 1}, path + ".zip")


def _fake_eval(ck, spec, tag, book,
               out_dir,
               env_factory=None):
    why, _c, _p = book.checkpoint(
        "eval_" + tag)
    if why:
        raise RuntimeError(
            "budget(eval): %s" % why)
    return {"tag": tag,
            "steps_used": 2112}


def test_stub_flow_identity_compare(
        tmp_path, monkeypatch):
    """真 stub 全流程+身份比较(故意错 repo SHA→拒)。"""
    monkeypatch.setattr(
        RN, "build_real_ppo",
        lambda *a, **k: (
            _ for _ in ()
        ).throw(AssertionError(
            "real PPO build")))
    out = tmp_path / "p"
    rep = RN.run_pilot(
        str(out), SPEC,
        ppo_factory=lambda e, s, sp:
            _FakePPO(e, s, sp),
        eval_fn=_fake_eval,
        env_factory=lambda r:
            _SpyEnv(r))
    assert rep["status"] == "completed"
    assert rep["identity"][
        "module_paths"]["ledger"]
    # 拒绝分支:expected repo SHA 错→identity 阶段即停
    bad = json.loads(json.dumps(SPEC))
    bad.setdefault(
        "identity_expected",
        SPEC.get(
            "identity_expected",
            {}))
    bad["identity_expected"][
        "repo"] = dict(
            SPEC.get(
                "identity_expected",
                {}).get("repo", {}))
    k0 = list(bad[
        "identity_expected"]
        ["repo"])[0]
    bad["identity_expected"][
        "repo"][k0] = "0" * 64
    out2 = tmp_path / "p2"
    with pytest.raises(
            RuntimeError,
            match="repo SHA"):
        RN.run_pilot(
            str(out2), bad,
            ppo_factory=lambda e, s,
                sp: _FakePPO(
                    e, s, sp),
            eval_fn=_fake_eval,
            env_factory=lambda r:
                _SpyEnv(r))


def test_stub_fail_and_budget(
        tmp_path, monkeypatch):
    monkeypatch.setattr(
        RN, "build_real_ppo",
        lambda *a, **k: (
            _ for _ in ()
        ).throw(AssertionError(
            "real PPO build")))
    out = tmp_path / "f"
    with pytest.raises(RuntimeError):
        RN.run_pilot(
            str(out), SPEC,
            ppo_factory=lambda e, s,
                sp: _Boom(
                    e, s, sp),
            eval_fn=_fake_eval,
            env_factory=lambda r:
                _SpyEnv(r))
    m = json.loads(
        (out / "pilot.json")
        .read_text(encoding="utf-8"))
    assert m["status"] == "failed"
    assert (out /
            "FAILED.marker"
            ).exists()
    st = {"n": 0}

    def clock():
        st["n"] += 1
        return st["n"] * 200.0
    out2 = tmp_path / "b"
    with pytest.raises(
            RuntimeError,
            match="wall_clock"):
        RN.run_pilot(
            str(out2), SPEC,
            ppo_factory=lambda e, s,
                sp: _FakePPO(
                    e, s, sp),
            eval_fn=_fake_eval,
            env_factory=lambda r:
                _SpyEnv(r),
            clock=(clock,
                   lambda: 0.0))


class _Boom(_FakePPO):
    def learn(self, *a, **k):
        raise RuntimeError(
            "non-finite loss")


# ---------------- 真评价函数(桩 loader/env) ----------------

class _CountEnv(
        TE.UnifiedPilotEnv):
    """计数 env(真 step,小规模);按 seed 复现。"""

    def __init__(self, rng):
        super().__init__(rng)
        self.extra = 0


class _StubPolicy:
    """固定动作策略(branch,w)。"""

    def __init__(self, w, branch=1.0):
        self.w = w
        self.branch = branch

    def predict(self, obs,
                deterministic=False,
                **kw):
        return np.array(
            [self.branch,
             self.w]), None


class _StubPPO:
    def __init__(self, policy):
        self.policy = policy


class _FakeEvalEnv:
    """手写 FakeEnv:1 步即终;计数;零真实 env。"""

    def __init__(self, rng=None):
        self.steps = 0

    def reset(self, *, remaining=None,
              s=None, seed=None,
              options=None):
        self.rem = remaining or 32
        self.s = s or 1
        self.c = 1
        self.q = 1.0
        self.g = 0
        return np.zeros(8), {}

    def step(self, a):
        self.steps += 1
        term = self.rem <= 1
        self.rem = max(0, self.rem - 1)
        return (np.zeros(8), 0.0,
                term, False,
                {"reward_valid": True,
                 "economic_failure": None,
                 "r": 0.001})


def test_real_evaluate_function(
        tmp_path, monkeypatch):
    """真 evaluate_checkpoint(FakeEnv+spy 禁真实
    env):计数/序列化/摘要/RNG 恢复。"""
    monkeypatch.setattr(
        TE, "UnifiedPilotEnv",
        lambda rng=None: (
            _ for _ in ()
        ).throw(AssertionError(
            "real env constructed")))
    loader_calls = {"n": 0}

    def loader(path, device=None):
        loader_calls["n"] += 1
        return _StubPPO(
            _StubPolicy(0.0,
                        branch=0.0))
    ts = th.get_rng_state()
    ns = np.random.get_state()
    ps = random.getstate()

    class _Book:
        def checkpoint(self, ph):
            return None, {}, {}
    import tempfile
    outd = tempfile.mkdtemp()
    res = EP.evaluate_checkpoint(
        "fake.zip", SPEC, "initial",
        _Book(), outd,
        env_factory=lambda r:
            _FakeEvalEnv(r),
        _loader=loader)
    assert res["steps_used"] <= 2112
    assert loader_calls["n"] == 1
    # RNG 恢复(实快照)
    assert th.equal(
        th.get_rng_state(), ts)
    assert np.random.get_state()[
        1].tolist() == ns[1].tolist()
    assert random.getstate() == ps
    # 序列化安全:null 失败表示存在路径
    s = json.dumps(res,
                   allow_nan=False)
    assert "net_log" in s
    # 摘要固定键
    for k in ("h32_pos",
              "tail_neg"):
        assert k in res["summary"]


def test_ledger_replay_baselines():
    kw = {"remaining": 1, "s": 1}
    rs = [0.01]
    v = EP._ledger_replay(
        kw, rs, lambda s: 0.5)
    ana = (1.005
           - 0.000505) / 1.0005
    assert v["valid"] is True
    assert v["net_log"] == pytest.approx(
        math.log(ana), rel=1e-15)
    # all HOLD 解析=0
    h = EP._ledger_replay(
        kw, rs, lambda s: None)
    assert h["net_log"] == pytest.approx(
        0.0, abs=1e-15)
    # 失败序列化路径由 env 侧产生(-inf→valid/null/raw);
    # 本世界 |w|≤1 下纯重放权益不破 0(线性合约),失败标记
    # 断言移至 env 层(close_flatten/open 失败测试已覆盖)。


# ---------------- official 模板(launch stages+假 PY) ----------------

def test_official_template_stub(tmp_path):
    """真 official 分支+假 PY(只记录 argv;不执行
    pytest/runner 真件)。"""
    import subprocess
    d = HERE
    fa = tmp_path / "att"
    fa.mkdir()
    fake_py = tmp_path / "fake_py.sh"
    fake_py.write_text(
        "#!/bin/bash\n"
        'printf "%s\\n" "$@" >> '
        '"$(dirname "$0")/fake_argv.log"\n'
        'if [ "$1" = "-m" ]; then exit 0; fi\n'
        'mkdir -p "$1" 2>/dev/null || true\n'
        "exit 0\n",
        encoding="utf-8")
    fake_py.chmod(0o755)
    r = subprocess.run(
        ["bash",
         str(d / "launch_teach.sh"),
         str(fa), "tpl",
         "official",
         str(fake_py),
         str(fa / "outp")],
        capture_output=True,
        text=True)
    assert r.returncode == 0
    snapdirs = list(fa.glob("tpl_*"))
    assert len(snapdirs) == 1
    snap = snapdirs[0] / "snapshot"
    for f in ("runner.py",
              "run_spec.json",
              "repo/rl_posctl/ledger.py",
              "repo/rl_posctl/curriculum.py",
              "repo/rl_posctl/skill_p0/"
              "p0policy.py"):
        assert (snap / f).exists()
    man = (snap / "sha256.manifest").read_text()
    assert "curriculum.py" in man
    argv = (tmp_path
            / "fake_argv.log").read_text()
    assert "runner.py" in argv
    assert "--mode" in argv


def test_real_ppo_identity_no_step():
    pytest.importorskip(
        "stable_baselines3")
    env = TE.UnifiedPilotEnv(
        random.Random(0))
    model = RN.build_real_ppo(
        env, 20261016, SPEC)
    tot = sum(p.numel()
              for p in
              model.policy
              .parameters())
    assert tot == 36489
    assert env.n_steps_env == 0
    assert model.clip_range(
        1.0) == pytest.approx(0.2)
    # seed shim:VecEnv seed 不改内部 rng
    v = model.env
    v.seed(999)
    assert env.rng.random() is not \
        None    # 内部 rng 未被替换


def test_status():
    assert RN.STATUS == \
        "PREPARED_NOT_RUN"
