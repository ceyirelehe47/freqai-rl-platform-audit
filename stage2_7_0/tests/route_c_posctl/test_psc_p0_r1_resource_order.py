# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 / F2:新 P0 资源入口先校验+唯一预约。

纯计数口径(记录型账本/工作叶替身;零 env.step、零 learn、零真实
采样、零真实 bootstrap 重采样):保持真实控制流,只把账本与工作叶
换成记录器。另含 R1 预算面注册核验与调用点次序 AST 检查。
"""

from __future__ import annotations

import ast
from pathlib import Path

import numpy as np

import pytest

from rl_posctl.budget import BudgetExceeded


class RecLedger:
    """记录型账本替身:余额不足在 reserve 拒(动作未发生)。"""

    def __init__(self, available: int):
        self.available = int(available)
        self.events = []

    def reserve(self, tag, **amounts):
        ask = sum(int(v) for v in amounts.values())
        self.events.append(("reserve", tag, ask))
        if ask > self.available:
            raise BudgetExceeded(
                f"预约被拒[{tag}]: {ask}>{self.available}")
        self.available -= ask
        return f"rid-{len(self.events)}"

    def commit(self, rid, tag, **actuals):
        got = sum(int(v) for v in actuals.values())
        self.events.append(("commit", tag, got))

    def abandon(self, rid, tag, note=""):
        self.events.append(("abandon", tag, note))


def _items(n, rows=3):
    """固定行 bank 替身:prices 行数决定步数上界(rows-1)。"""
    out = []
    for i in range(n):
        out.append((list(range(rows)), None,
                    {"pair_index": i % 3, "variant": i // 3}))
    return out


def _fake_env_factory(counter):
    def f(item):
        counter["env_created"] += 1
        return object()
    return f


def _fake_runner(counter, fail_at=None):
    def run(env, fn):
        counter["work_units"] += 1
        if fail_at is not None and counter["work_units"] > fail_at:
            raise RuntimeError("工作叶中断反例")
        return []
    return run


def _fake_summarizer(steps):
    def s(infos):
        return {"n_steps": steps,
                "net_log_return": 0.01,
                "net_log_return_valid": True,
                "economic_failure": False}
    return s


class TestEvalOnBankOrder:
    """eval_on_bank:校验+唯一预约 → 执行 → 实结(F2 主反例)。"""

    def _call(self, ledger, items, fail_at=None, sink=None):
        from rl_posctl.skill_p0.p0eval import eval_on_bank
        counter = {"env_created": 0, "work_units": 0}
        rows = eval_on_bank(
            items, lambda env, row, ratio, sl: 0.0,
            ledger=ledger, tag="t",
            raw_sink=sink,
            env_factory=_fake_env_factory(counter),
            runner=_fake_runner(counter, fail_at=fail_at),
            summarizer=_fake_summarizer(steps=2))
        return rows, counter

    def test_zero_balance_denied_before_work(self):
        """额度 0:预约被拒,工作叶调用数为 0(旧版先执行 3 单元)。"""
        led = RecLedger(available=0)
        with pytest.raises(BudgetExceeded):
            self._call(led, _items(3))
        assert led.events[0][0] == "reserve"
        # 反例核心:工作叶从未被调用
        assert led.events == [("reserve", "eval:t", 6)]

    def test_insufficient_denied_before_work(self):
        led = RecLedger(available=2)
        with pytest.raises(BudgetExceeded):
            self._call(led, _items(3))
        assert all(e[0] == "reserve" for e in led.events)

    def test_exact_fit_single_reservation_settled_once(self):
        led = RecLedger(available=6)
        rows, counter = self._call(led, _items(3))
        assert counter["env_created"] == 3
        assert counter["work_units"] == 3
        reserves = [e for e in led.events if e[0] == "reserve"]
        commits = [e for e in led.events if e[0] == "commit"]
        assert len(reserves) == 1, "唯一预约"
        assert len(commits) == 1, "一次实结"
        assert commits[0][2] == 6   # 实际 = 3 eps × 2 steps
        assert len(rows) == 3

    def test_next_operation_denied_before_work(self):
        led = RecLedger(available=6)
        self._call(led, _items(3))
        with pytest.raises(BudgetExceeded):
            self._call(led, _items(3))       # 跨调用共账,余额 0
        assert led.events[-1][0] == "reserve"

    def test_failure_abandon_conservative(self):
        """中断:abandon 保留余额,已发生量不归零,异常如实上抛。"""
        led = RecLedger(available=6)
        with pytest.raises(RuntimeError, match="中断反例"):
            self._call(led, _items(3), fail_at=1)
        kinds = [e[0] for e in led.events]
        assert kinds == ["reserve", "abandon"]
        assert "observed_steps=2" in led.events[1][2]

    def test_input_validation_before_anything(self):
        from rl_posctl.skill_p0.p0eval import eval_on_bank
        led = RecLedger(available=100)
        with pytest.raises(ValueError, match="items 为空"):
            eval_on_bank([], lambda *a: 0.0, ledger=led, tag="t")
        with pytest.raises(TypeError, match="action_fn"):
            eval_on_bank(_items(1), None, ledger=led, tag="t")
        assert led.events == [], "校验失败不得产生任何预约"

    def test_no_ledger_no_reservation(self):
        rows, counter = self._call(None, _items(2))
        assert counter["work_units"] == 2 and len(rows) == 2


class TestSamplerAndBootstrapOrder:
    """分布采样/重采样:预约在样本生成之前。"""

    def test_paired_bootstrap_invalid_inputs_no_meter(self):
        from rl_posctl.skill_p0.p0eval import paired_bootstrap
        meter_calls = []
        for bad in ([], [0.1], [0.1, float("nan")], [0.1, None],
                    "ab"):
            out = paired_bootstrap(
                bad, seed=1, draws=10,
                meter=lambda n: meter_calls.append(n),
                rng_factory=lambda s: (_ for _ in ()).throw(
                    AssertionError("无效输入不得到达采样")))
            assert out["valid"] is False
            assert out["reason"]
        assert meter_calls == [], "无效输入不得消耗采样额度"

    def test_paired_bootstrap_meter_before_rng(self):
        from rl_posctl.skill_p0.p0eval import paired_bootstrap
        events = []

        class _Rng:
            def __init__(self, seed):
                events.append("rng_create")

            def integers(self, *a, **k):
                events.append("integers")
                import numpy as np
                return np.zeros(k.get("size") or a[2],
                                dtype=int)

        raw_got = []

        def sink(row):
            raw_got.append(row)
            events.append("raw")

        out = paired_bootstrap(
            [0.5, 0.6, 0.55, 0.7], seed=7, draws=10,
            meter=lambda n: events.append("meter"),
            raw_sink=sink, rng_factory=_Rng)
        assert out["valid"] is True
        assert out["lower_positive"] is True
        # 次序:raw 输入落盘 → 预约 → 重采样矩阵
        assert events == ["raw", "rng_create", "integers"] or (
            events[0] == "raw" and "meter" in events[:3])
        assert events[0] == "raw"
        assert events.index("meter") < events.index("integers"), (
            "预约必须在重采样矩阵生成之前")
        assert raw_got[0]["kind"] == "bootstrap_input"
        assert raw_got[0]["draws"] == 10

    def test_behavior_gate_meter_before_sampling(self, monkeypatch):
        from rl_posctl.skill_p0 import p0eval as E
        events = []

        class _Dist:
            def sample(self):
                events.append("sample")
                return None

        class _Policy:
            def get_distribution(self, obs):
                events.append("get_distribution")
                return _Dist()

        class _Model:
            policy = _Policy()

        rows = [(1.0, 0, 0, 0, 0, [0.0] * 8),
                (-1.0, 0, 0, 0, 0, [0.0] * 8),
                (0.0, 0, 0, 0, 0, [0.0] * 8)]
        monkeypatch.setattr(E, "behavior_grid_obs",
                            lambda feature_names=None: rows)
        monkeypatch.setattr(
            E, "gate_probabilities",
            lambda model, obs: {
                "p_rebal_up": np.array([0.9, 0.0, 0.0]),
                "p_rebal_down": np.array([0.0, 0.9, 0.0]),
                "p_neutral_band": np.array([0.0, 0.0, 0.9])})
        E.behavior_gate(
            _Model(), meter=lambda n: events.append("meter"),
            sampled_check=2)
        assert events.count("sample") == 2
        assert events.index("meter") < events.index("sample"), (
            "预约必须在采样执行之前")

    def test_meter_denied_prevents_sampling(self, monkeypatch):
        from rl_posctl.skill_p0 import p0eval as E

        def denied_meter(n):
            raise BudgetExceeded(f"采样额度不足:{n}")

        class _Dist:
            def sample(self):
                raise AssertionError("额度拒绝后不得采样")

        class _Policy:
            def get_distribution(self, obs):
                return _Dist()

        rows = [(1.0, 0, 0, 0, 0, [0.0] * 8),
                (-1.0, 0, 0, 0, 0, [0.0] * 8),
                (0.0, 0, 0, 0, 0, [0.0] * 8)]
        monkeypatch.setattr(E, "behavior_grid_obs",
                            lambda feature_names=None: rows)
        monkeypatch.setattr(
            E, "gate_probabilities",
            lambda model, obs: {
                "p_rebal_up": np.array([0.9, 0.0, 0.0]),
                "p_rebal_down": np.array([0.0, 0.9, 0.0]),
                "p_neutral_band": np.array([0.0, 0.0, 0.9])})
        with pytest.raises(BudgetExceeded):
            E.behavior_gate(
                type("M", (), {"policy": _Policy()})(),
                meter=denied_meter, sampled_check=2)


class TestR1BudgetFace:
    """R1 有限修复面注册(纯读取;真实账本行为在 WSL 端到端)。"""

    def test_face_registered_with_zero_caps(self):
        from rl_posctl.budget import task_registry
        tid = "PSC_P0_v1_FiniteRepair_R1"
        reg = task_registry()
        assert tid in reg
        lim = reg[tid]["limits"]
        assert lim["ppo_steps_smoke"] == 128
        assert lim["ppo_steps_main"] == 0
        assert lim["ppo_steps_techretry"] == 0
        assert lim["ppo_learn_main_attempts"] == 0
        assert lim["ppo_learn_techretry_attempts"] == 0
        assert lim["ppo_learn_smoke_attempts"] == 1
        assert lim["ppo_optimizer_steps"] == 8
        assert lim["eval_steps"] == 128
        assert lim["dist_sample_actions"] == 1024
        for k in ("gen_calls", "episodes", "bc_fits", "bc_epochs",
                  "bc_minibatch_updates", "supervised_rows",
                  "bootstrap_draws"):
            assert lim[k] == 0, f"{k} 必须显式 0(fail closed)"
        der = {d[0]: d for d in reg[tid]["derived_totals"]}
        assert der["economic_total"][2] == 256
        assert set(der["economic_total"][1]) == {
            "ppo_steps_main", "ppo_steps_smoke",
            "ppo_steps_techretry", "eval_steps"}


class TestCallSiteOrderAst:
    """调用点次序 AST 检查(纯静态;真实调用链由 runner 结构保证)。"""

    ROOT = Path(__file__).resolve().parents[2]

    def _tree(self, rel):
        return ast.parse(
            (self.ROOT / rel).read_text(encoding="utf-8"))

    def test_repr_meters_precede_sampling(self):
        tree = self._tree("runner/psc_p0_repr.py")
        src = {n.name: n for n in tree.body
               if isinstance(n, ast.FunctionDef)}
        for fname in ("concentration_check",
                      "mc_logprob_entropy_checks"):
            calls = [(n.lineno, ast.unparse(n.func))
                     for n in ast.walk(src[fname])
                     if isinstance(n, ast.Call)]
            meters = [ln for ln, c in calls if c.endswith("meter")]
            samples = [ln for ln, c in calls
                       if c.endswith("sample")]
            assert meters and samples
            assert max(meters) < min(samples), (
                f"{fname}: meter({meters}) 必须先于 sample"
                f"({samples})")

    def test_bc_rows_reserve_precedes_build(self):
        tree = self._tree("runner/psc_p0_bc.py")
        calls = [(n.lineno, ast.unparse(n.func))
                 for n in ast.walk(tree)
                 if isinstance(n, ast.Call)]
        build_a = min(ln for ln, c in calls
                      if "build_bc_a_tables" in c)
        reserve_a = min(ln for ln, c in calls
                        if c.endswith("reserve")
                        and ln < build_a + 40)
        assert reserve_a < build_a, "监督行预约必须先于表构建"
        build_b = min(ln for ln, c in calls
                      if "build_bc_b_tables" in c)
        reserves = sorted(ln for ln, c in calls
                          if c.endswith("reserve"))
        between = [ln for ln in reserves
                   if reserve_a < ln < build_b]
        assert between, "bc_b 构建前也必须先预约"

    def test_confirm_verifies_before_ledger(self):
        tree = self._tree("runner/psc_p0_confirm.py")
        calls = [(n.lineno, ast.unparse(n.func))
                 for n in ast.walk(tree)
                 if isinstance(n, ast.Call)]
        verify = min(ln for ln, c in calls
                     if "verify_final_checkpoint" in c)
        open_ledger = min(ln for ln, c in calls
                          if c.endswith("open_ledger"))
        assert verify < open_ledger, (
            "确认入口核验必须在任何账本打开/资源消费之前")

class TestRunnerLoadability:
    """加载级防回归(P1 复验发现:psc_p0_confirm import 断裂)。"""

    RUNNERS = (
        "psc_p0_train", "psc_p0_confirm", "psc_p0_eval",
        "psc_p0_bc", "psc_p0_repr", "psc_p0_bgate_v2",
        "psc_p0_r1_ledger", "psc_p0_r1_prep", "psc_p0_r1_smoke",
        "psc_p0_r1_verify")
    NEED = {
        "psc_p0_confirm": (
            "RUNS_DIR", "open_ledger", "make_sampler_meter",
            "make_bootstrap_meter", "evidence_kib_settle",
            "load_p0_model", "p0_code_digest",
            "verify_final_checkpoint"),
    }

    def test_all_r1_runners_importable(self):
        import importlib.util
        root = (Path(__file__).resolve().parents[2] / "runner")
        for name in self.RUNNERS:
            spec = importlib.util.spec_from_file_location(
                name, root / f"{name}.py")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            for attr in self.NEED.get(name, ()):
                assert hasattr(mod, attr), (
                    f"{name} 缺 {attr}(import 断裂回归)")

