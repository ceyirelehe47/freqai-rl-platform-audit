# -*- coding: utf-8 -*-
"""R3-01 预算面绑定/唯一计量/执行上限(FiniteRepair R3)。

全部用真实 TaskLedger/QuotaLedger 与真实 runner main 控制流;
昂贵生成/评估/learn 叶为记录型替身(monkeypatch 到 runner 模块
属性),不做真实科研工作。cap 执行中硬限用**真实咽喉点**
(env.step / generate_episode / QuotaLedger.draw)消费,不直接
拨计数器(stub 掉被测面不算修复验证)。
"""

from __future__ import annotations

import importlib.util
import json
import math
import os
import subprocess
import sys
from pathlib import Path

import pytest

import rl_posctl.curriculum as _currmod
import rl_posctl.env as _envmod
import rl_posctl.banks as banks_mod
from rl_posctl.budget import (
    BudgetExceeded, DERIVED_TOTALS_R3, METRICS, TaskLedger,
    open_task_ledger, r2_limits, r3_limits, task_registry)
from rl_posctl import versions as versions_mod

RUNNER_DIR = Path(__file__).resolve().parents[2] / "runner"
R2_TASK = versions_mod.POSCTL_R2_TASK_ID
R3_TASK = versions_mod.POSCTL_R3_TASK_ID


def _load_runner(name):
    spec = importlib.util.spec_from_file_location(
        name, RUNNER_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_ledger(tmp_path, name="t.jsonl", task=R2_TASK):
    led = TaskLedger.create(tmp_path / name, task)
    return led, tmp_path / name


def _reset_counters():
    _envmod.ENV_STEP_COUNT = 0
    _envmod.PPO_EXEMPT_STEPS = 0
    _envmod.ENV_STEP_LIMIT = None
    _currmod.GEN_CALL_COUNT = 0
    _currmod.GEN_CALL_LIMIT = None


@pytest.fixture(autouse=True)
def _clean_counters():
    # 测试内隔离(归零);结束后**累计回填**——套件 wrapper 依赖
    # 进程累计计数器结账,不得被清零(batchA1 负计量教训)。
    pre_env = int(_envmod.ENV_STEP_COUNT)
    pre_gen = int(_currmod.GEN_CALL_COUNT)
    _reset_counters()
    yield
    _envmod.ENV_STEP_COUNT = pre_env + int(_envmod.ENV_STEP_COUNT)
    _currmod.GEN_CALL_COUNT = pre_gen + int(
        _currmod.GEN_CALL_COUNT)
    _envmod.ENV_STEP_LIMIT = None
    _currmod.GEN_CALL_LIMIT = None


# =================================================================
# F1-a 预算面真正绑定
# =================================================================
class TestBudgetFaceBinding:
    def test_registry_maps_faces_mechanically(self):
        """任务注册表:任务身份 ↔ 面/单次上限/派生总项一一对应,
        R3 面 = SCOPE_AND_BUDGET 表数值(机械复算)。"""
        reg = task_registry()
        for tid, entry in reg.items():
            assert set(entry["limits"]) == set(METRICS)
            for _n, parts, cap in entry["derived_totals"]:
                assert cap == sum(entry["limits"][p]
                                  for p in parts)
        r3 = task_registry()[R3_TASK]
        b = versions_mod.POSCTL_R3_BUDGET
        assert r3["limits"]["ppo_steps"] == b["ppo_steps_total"]
        assert r3["limits"]["eval_steps"] == b["eval_steps"]
        assert r3["limits"]["gen_calls"] == b["gen_calls"]
        assert r3["limits"]["episodes"] == b["episodes"]
        assert r3["limits"]["ppo_learn_attempts"] == \
            b["ppo_learn_attempts"]
        assert r3["single_caps"]["ppo_steps"] == \
            b["ppo_steps_single"]
        assert DERIVED_TOTALS_R3[0][2] == b["synthetic_total"]
        assert b["ppo_steps_total"] + b["eval_steps"] == \
            b["synthetic_total"]

    def test_header_face_mismatch_refused_on_open(self, tmp_path):
        """reviewer F1-a 反例:头部 eval=0 的账本不得按代码缺省面
        (32768)重新打开续花——打开即拒绝(其余头部字段齐全,单验
        面不一致;缺字段场景见 R4 测试)。"""
        led, path = _mk_ledger(tmp_path)
        header_face = dict(led.limits, eval_steps=0)
        hdr = {"event": "task_bind", "task_id": led.task_id,
               "budget_face": header_face,
               "single_caps": dict(led.single_caps),
               "derived_totals": [
                   {"name": n, "parts": list(pp), "cap": c}
                   for n, pp, c in led._derived_spec]}
        p2 = tmp_path / "hdr0.jsonl"
        p2.write_text(json.dumps(hdr) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="预算面与代码不一致"):
            TaskLedger(p2, led.task_id)

    def test_divergent_limits_refused_on_open(self, tmp_path):
        led, path = _mk_ledger(tmp_path)
        with pytest.raises(RuntimeError, match="同任务异预算"):
            TaskLedger(path, led.task_id,
                       limits=dict(led.limits, episodes=5))

    def test_second_bind_row_with_other_face_refused(
            self, tmp_path):
        _, path = _mk_ledger(tmp_path)
        led2 = TaskLedger(path, R2_TASK)
        face = led2.limits
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "event": "task_bind", "task_id": R2_TASK,
                "budget_face": dict(face, eval_steps=1)}) + "\n")
        with pytest.raises(RuntimeError,
                           match="不一致 task_bind"):
            TaskLedger(path, R2_TASK)

    def test_matching_reopen_and_reserve_under_header(
            self, tmp_path):
        """正面:一致面重开可用;预约受头部面(而非别的面)约束。"""
        led, path = _mk_ledger(tmp_path)
        led2 = TaskLedger(path, led.task_id)
        assert led2.snapshot()["budget_face_matches_code"] is True
        rid = led2.reserve("ok", eval_steps=10)
        led2.commit(rid, "ok", eval_steps=3)
        assert led2.effective()["eval_steps"] == 3

    def test_unknown_task_identity_refused(self, tmp_path):
        with pytest.raises(RuntimeError, match="未知任务身份"):
            TaskLedger.create(tmp_path / "x.jsonl",
                              "PosCtl_NO_SUCH_TASK")

    def test_open_task_ledger_resolves_header_identity(
            self, tmp_path):
        """入口按头部任务身份打开(R3 账本不用 R2 硬编码)。"""
        led, path = _mk_ledger(tmp_path, task=R3_TASK)
        opened = open_task_ledger(path)
        assert opened.task_id == R3_TASK
        assert opened.limits == r3_limits()
        _, p2 = _mk_ledger(tmp_path, name="r2l.jsonl",
                           task=R2_TASK)
        opened2 = open_task_ledger(p2)
        assert opened2.task_id == R2_TASK
        assert opened2.limits == r2_limits()


# =================================================================
# F1-b 总预约与叶级不双计(draw 划拨)
# =================================================================
class TestDrawSingleCounting:
    def test_nine_gens_recorded_nine(self, tmp_path):
        """9 次叶调用准确记 9(旧:总预约+叶级各记一次=18)。"""
        led, path = _mk_ledger(tmp_path, task=R3_TASK)
        rid = led.reserve("t", gen_calls=9, episodes=9)
        quota = banks_mod.QuotaLedger(
            tmp_path / "q.jsonl", task_ledger=led, grant_rid=rid)
        for i in range(9):
            quota.record(gen_calls=1, bank="b", domain="eval")
            quota.record_episode(bank="b", domain="eval")
        led.commit(rid, "t", gen_calls=9, episodes=9)
        led2 = TaskLedger(path, R3_TASK)
        snap = led2.snapshot()
        assert snap["committed"]["gen_calls"] == 9
        assert snap["committed"]["episodes"] == 9
        assert snap["effective"]["gen_calls"] == 9

    def test_exact_room_nine_then_tenth_refused(self, tmp_path):
        """刚好 9 额度可合法完成 9;第 10 次在**动作前**拒绝
        (旧:剩 9 反而首叶被拒)。"""
        led, path = _mk_ledger(tmp_path, task=R3_TASK)
        rid0 = led.reserve("prior", gen_calls=64 - 9)
        led.commit(rid0, "prior", gen_calls=64 - 9)
        rid = led.reserve("t", gen_calls=9, episodes=9)
        quota = banks_mod.QuotaLedger(
            tmp_path / "q.jsonl", task_ledger=led, grant_rid=rid)
        for _ in range(9):
            quota.record(gen_calls=1, bank="b", domain="eval")
        with pytest.raises(BudgetExceeded, match="划拨超预约"):
            quota.record(gen_calls=1, bank="b", domain="eval")

    def test_commit_total_settles_without_double_count(
            self, tmp_path):
        led, _ = _mk_ledger(tmp_path, task=R3_TASK)
        rid = led.reserve("t", eval_steps=100, gen_calls=5)
        led.draw(rid, "leaf", eval_steps=30, gen_calls=3)
        led.commit(rid, "t", eval_steps=40, gen_calls=3)
        assert led.effective()["eval_steps"] == 40
        assert led.effective()["gen_calls"] == 3
        assert led.outstanding() == {k: 0 for k in METRICS}

    def test_abandon_keeps_only_remainder(self, tmp_path):
        """异常保留**未划拨余额**(未知实耗),已划拨实测已入账;
        两类分列,不混为一类。"""
        led, path = _mk_ledger(tmp_path, task=R3_TASK)
        rid = led.reserve("t", gen_calls=9)
        for _ in range(5):
            led.draw(rid, "leaf", gen_calls=1)
        led.abandon(rid, "t", note="midrun")
        led2 = TaskLedger(path, R3_TASK)
        snap = led2.snapshot()
        # 5 实测 + 4 保守余额;事件流可区分(draw 行 vs abandon 行)
        assert snap["committed"]["gen_calls"] == 9
        rows = [json.loads(l) for l in
                path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        kinds = [r["event"] for r in rows]
        assert kinds.count("draw") == 5
        ab = [r for r in rows if r["event"] == "abandon"][0]
        assert ab["amounts"]["gen_calls"] == 4

    def test_actual_below_drawn_rejected(self, tmp_path):
        led, _ = _mk_ledger(tmp_path)
        rid = led.reserve("t", eval_steps=10)
        led.draw(rid, "l", eval_steps=5)
        with pytest.raises(BudgetExceeded, match="不可回缩"):
            led.commit(rid, "t", eval_steps=3)

    def test_release_refused_after_draw(self, tmp_path):
        """已开始工作(有划拨)的预约不得 release 免计。"""
        led, _ = _mk_ledger(tmp_path)
        rid = led.reserve("t", eval_steps=10)
        led.draw(rid, "l", eval_steps=1)
        with pytest.raises(RuntimeError, match="已有划拨"):
            led.release(rid, "t")

    def test_cross_process_grant_draws_shared(self, tmp_path):
        """跨进程共用额度:另一进程同 grant 划拨,同文件一致。"""
        led, path = _mk_ledger(tmp_path, task=R3_TASK)
        rid = led.reserve("t", gen_calls=4)
        code = (
            "import sys\n"
            "sys.path.insert(0,{src!r})\n"
            "from rl_posctl.budget import TaskLedger\n"
            "led = TaskLedger({p!r}, {tid!r})\n"
            "led.draw({rid!r}, 'other', gen_calls=3)\n"
            "print('DREW')\n"
        ).format(
            src=str(Path(__file__).resolve().parents[2] / "src"),
            p=str(path), tid=R3_TASK, rid=rid)
        script = tmp_path / "other.py"
        script.write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True,
                           timeout=120,
                           env={**os.environ,
                                "PYTHONDONTWRITEBYTECODE": "1"})
        assert "DREW" in r.stdout, r.stdout + r.stderr
        led2 = TaskLedger(path, R3_TASK)
        rem = led2.reservation_remainder(rid)
        assert rem["gen_calls"] == 1
        with pytest.raises(BudgetExceeded):
            led2.draw(rid, "x", gen_calls=2)

    def test_generation_failure_counts_call_not_episode(
            self, tmp_path, monkeypatch):
        """失败生成:调用必计,episode 不冒充成功
        (generate_counted 真实路径;生成叶替换为抛错)。"""
        led, _ = _mk_ledger(tmp_path, task=R3_TASK)
        rid = led.reserve("t", gen_calls=2, episodes=2)
        quota = banks_mod.QuotaLedger(
            tmp_path / "q.jsonl", task_ledger=led, grant_rid=rid)

        def boom(spec, seed):
            raise RuntimeError("生成失败模拟")
        monkeypatch.setattr(banks_mod, "generate_episode", boom)
        with pytest.raises(RuntimeError, match="生成失败模拟"):
            banks_mod.generate_counted(
                None, 1, ledger=quota, bank="b", domain="train")
        snap = led.snapshot()
        assert snap["committed"]["gen_calls"] == 1
        assert snap["committed"]["episodes"] == 0
        rows = [json.loads(l) for l in
                (tmp_path / "q.jsonl").read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        assert all(not r.get("episode_success_settlement")
                   for r in rows)


# =================================================================
# F1-d 参数/输出在预约前拒绝(真实 eval main + 记录叶)
# =================================================================
class TestEvalRunnerPreflight:
    def _run_main(self, tmp_path, monkeypatch, argv):
        mod = _load_runner("posctl_r2_eval")
        calls = {"tier": 0, "gen": 0}

        def stub_tier(*a, **k):
            calls["tier"] += 1
            raise AssertionError(
                "tier_validity 不得在拒绝路径执行")

        def stub_gen(*a, **k):
            calls["gen"] += 1
            raise AssertionError(
                "generate_episode 不得在拒绝路径执行")
        monkeypatch.setattr(mod, "tier_validity", stub_tier)
        monkeypatch.setattr(mod, "error_report", stub_tier)
        monkeypatch.setattr(mod, "spec_for", lambda *a, **k: None)
        old_argv = sys.argv
        sys.argv = ["posctl_r2_eval.py"] + argv
        try:
            rc = mod.main()
        finally:
            sys.argv = old_argv
        return rc, calls

    def test_bad_refinements_rejected_zero_reservation(
            self, tmp_path, monkeypatch):
        """--err-refinements oops:语法错在**预约前**拒绝,零未闭合
        预约(旧:预约 1024 eval+9 gen+9 episodes 后才崩)。"""
        led, path = _mk_ledger(tmp_path)
        rc, calls = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path), "--tier-episodes", "1",
             "--c123-episodes", "1", "--replay-episodes", "1",
             "--err-refinements", "oops"])
        assert rc == 2
        assert calls["tier"] == 0 and calls["gen"] == 0
        led2 = TaskLedger(path, R2_TASK)
        assert led2.outstanding() == {k: 0 for k in METRICS}
        assert led2.effective()["eval_steps"] == 0

    @pytest.mark.parametrize("bad", [
        "321,64,40;321,64,40",              # 重复级别
        "321,64,40",                        # 单级
        "321,64,40;161,32,24",              # 倒退
        "0,16,12;81,16,12",                 # 非正整数
        "81,16;161,32,24",                  # 形状错
        "81,NaN,12;161,32,24",              # 非数值
    ])
    def test_degenerate_refinements_rejected_preflight(
            self, tmp_path, monkeypatch, bad):
        led, path = _mk_ledger(tmp_path)
        rc, _ = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path), "--err-refinements", bad])
        assert rc == 2
        led2 = TaskLedger(path, R2_TASK)
        assert led2.outstanding() == {k: 0 for k in METRICS}

    def test_output_dir_exists_rejected_preflight(
            self, tmp_path, monkeypatch):
        """输出目录在场先拒绝(不混写旧 run;预约前)。"""
        led, path = _mk_ledger(tmp_path)
        stamp = __import__("time").strftime(
            "curriculum_eval_%Y%m%dT%H%M%S")
        (tmp_path / "out" / stamp).mkdir(parents=True)
        rc, _ = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path)])
        assert rc == 2
        led2 = TaskLedger(path, R2_TASK)
        assert led2.outstanding() == {k: 0 for k in METRICS}


# =================================================================
# F1-c 执行中硬限(真实咽喉点;cap=1 第二叶不执行)
# =================================================================
def _tiny_env():
    """真实 HybridPositionEnv(合成价格/特征;不经生成器)。"""
    import numpy as np
    import pandas as pd
    from rl_posctl.env import HybridPositionEnv
    n = 40
    px = pd.Series(100.0 + np.arange(n) * 0.01)
    prices = pd.DataFrame({"open": px, "close": px})
    feats = pd.DataFrame(np.zeros((n, 2)), columns=["f0", "f1"])
    return HybridPositionEnv(
        features=feats, prices=prices, fee=0.001, window_size=1)


class TestInExecutionCaps:
    def test_env_step_cap1_second_leaf_not_executed(self):
        """cap=1:第一叶 1 步执行;第二叶 env.step 在经济转移前
        抛 BudgetExceeded(工作不发生,不是 commit 才发现)。"""
        _envmod.ENV_STEP_LIMIT = 1
        env = _tiny_env()
        obs, _ = env.reset()
        env.step([0, 0.0])                 # 叶 1:1 步,执行
        with pytest.raises(BudgetExceeded,
                           match="执行中硬限"):
            env.step([0, 0.0])             # 叶 2:不执行
        # 第一步确实发生(转移完成);第二步被拒(计数未增)
        assert _envmod.ENV_STEP_COUNT == 1

    def test_gen_call_cap_enforced_before_sampling(self):
        _currmod.GEN_CALL_LIMIT = 0         # 0 授权:首叶即拒
        spec = type("S", (), {})()         # 不会被用到(先拒)
        with pytest.raises(BudgetExceeded,
                           match="generate_episode"):
            _currmod.generate_episode(spec, 0)
        assert _currmod.GEN_CALL_COUNT == 0

    def test_ppo_exempt_keeps_learn_steps_off_eval_cap(self):
        """learn 步按豁免记账:cap=0 eval 时授权 learn 仍可走。"""
        _envmod.ENV_STEP_LIMIT = 0
        env = _tiny_env()
        env.reset()
        _envmod.grant_ppo_exempt(2)
        env.step([0, 0.0])
        env.step([0, 0.0])
        assert _envmod.ENV_STEP_COUNT == 2
        # 豁免校正为实际后,第 3 步(eval 分类)再被拒
        _envmod.grant_ppo_exempt(-2)
        with pytest.raises(BudgetExceeded):
            env.step([0, 0.0])


# =================================================================
# F1-c learn 门取整预检(记录型模型)
# =================================================================
class TestLearnGatePreflight:
    def _gate(self, tmp_path, task=R2_TASK):
        led, _ = _mk_ledger(tmp_path, task=task)
        spec = importlib.util.spec_from_file_location(
            "submitted_conftest",
            Path(__file__).resolve().parent / "conftest.py")
        ct = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(ct)
        return ct._LearnGate(led), led

    def test_roundup_over_single_cap_never_calls_learn(
            self, tmp_path):
        """reviewer F1-c 反例:n_steps=256 请求 16 → 上界 256>单次
        上限,预约拒绝,**learn 根本不被调用**(旧:先 learn 再在
        commit 拒 256>16)。"""
        gate, _ = self._gate(tmp_path, task=R3_TASK)  # 单次上限 64
        calls = []

        class RoundUpModel:
            n_steps = 256
            n_envs = 1

            def learn(self, total_timesteps, callback=None):
                calls.append(total_timesteps)
                _envmod.ENV_STEP_COUNT += 256
        with pytest.raises(BudgetExceeded):
            gate.learn(RoundUpModel(), 16)
        assert calls == []          # learn 未被调用

    def test_roundup_preflight_reserves_bound_not_request(
            self, tmp_path):
        """上界(取整后)入账,不是请求值;合法路径照常工作。"""
        gate, led = self._gate(tmp_path)
        calls = []

        class Model:
            n_steps = 8
            n_envs = 1

            def learn(self, total_timesteps, callback=None):
                calls.append(total_timesteps)
                for _ in range(12):
                    _envmod.ENV_STEP_COUNT += 1
                    callback({}, {})
        got = gate.learn(Model(), 12)
        assert calls == [12]
        assert got == 12
        snap = led.snapshot()
        assert snap["committed"]["ppo_steps"] == 12
        assert snap["committed"]["ppo_learn_attempts"] == 1

    def test_midlearn_overrun_stopped_by_guard(self, tmp_path):
        """执行中超上界的 rollout 被回调截停(fail closed)。"""
        gate, led = self._gate(tmp_path)

        class Liar:
            n_steps = 8
            n_envs = 1

            def learn(self, total_timesteps, callback=None):
                for _ in range(20):        # 超上界 16
                    _envmod.ENV_STEP_COUNT += 1
                    callback({}, {})
        with pytest.raises(BudgetExceeded, match="超上界"):
            gate.learn(Liar(), 16)
        # 异常路径:未划拨余额保守保留(abandon → committed)
        assert led.snapshot()["committed"][
            "ppo_steps"] == 16

    def test_model_without_geometry_refused(self, tmp_path):
        """无可信几何(无 n_steps)→ 拒学(fail closed)。"""
        gate, _ = self._gate(tmp_path)

        class Opaque:
            n_envs = 1

            def learn(self, *a, **k):
                raise AssertionError("不得被调用")
        with pytest.raises(ValueError, match="n_steps"):
            gate.learn(Opaque(), 16)


# =================================================================
# 套件 wrapper 预检(账本一致/参数解析)
# =================================================================
class TestSuitePreflight:
    def _run(self, tmp_path, monkeypatch, argv, ledger=None):
        mod = _load_runner("posctl_r2_suite")
        monkeypatch.setattr(
            mod.pytest, "main",
            lambda argv: (_ for _ in ()).throw(
                AssertionError("pytest 不得在拒绝路径执行")))
        old_argv = sys.argv
        sys.argv = ["posctl_r2_suite.py"] + argv
        try:
            rc = mod.main()
        finally:
            sys.argv = old_argv
        return rc

    def test_env_ledger_conflict_rejected_prework(
            self, tmp_path, monkeypatch):
        led, path = _mk_ledger(tmp_path)
        monkeypatch.setenv("POSCTL_R3_LEDGER",
                           str(tmp_path / "other.jsonl"))
        rc = self._run(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path),
             "--junit", str(tmp_path / "j.xml")])
        assert rc == 2
        led2 = TaskLedger(path, R2_TASK)
        assert led2.outstanding() == {k: 0 for k in METRICS}

    def test_bad_pytest_args_rejected_prework(
            self, tmp_path, monkeypatch):
        led, path = _mk_ledger(tmp_path)
        rc = self._run(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path),
             "--junit", str(tmp_path / "j.xml"),
             "--pytest-args", "'unbalanced"])
        assert rc == 2
        led2 = TaskLedger(path, R2_TASK)
        assert led2.outstanding() == {k: 0 for k in METRICS}

    def test_existing_junit_rejected_prework(
            self, tmp_path, monkeypatch):
        led, path = _mk_ledger(tmp_path)
        (tmp_path / "j.xml").write_text("old", encoding="utf-8")
        rc = self._run(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path),
             "--junit", str(tmp_path / "j.xml")])
        assert rc == 2
