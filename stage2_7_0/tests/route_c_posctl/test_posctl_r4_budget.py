# -*- coding: utf-8 -*-
"""R4-A 预算完整合同 + learn 边界(FiniteRepair R4)。

B1:commit 必结键完整性(遗漏已授权/已划拨指标=不完整结清拒,
不出现负 delta 冲回;完整结清准确去重);头部 single_caps/
derived_totals 缺失或错值开账即拒。
B2:learn 门咽喉阻断(第 ub+1 步在 env.step 经济转移前拒绝,
不是执行后 callback 才发现);异常路径不失去已观察工作
(abandon 余额+超界事故补记);取整预检持续有效。
场景与 portable_probes/probe_budget.py、probe_learn_boundary.py
同款;记录型叶/真实 env 咽喉,零真实训练、零生成。
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

import rl_posctl.env as _envmod
from rl_posctl.budget import (
    BudgetExceeded, TaskLedger, open_task_ledger)
from rl_posctl import versions as versions_mod

R3_TASK = versions_mod.POSCTL_R3_TASK_ID
TESTS_DIR = Path(__file__).resolve().parent


def _mk(tmp_path, name="t.jsonl", task=R3_TASK):
    led = TaskLedger.create(tmp_path / name, task)
    return led, tmp_path / name


def _reset():
    _envmod.ENV_STEP_COUNT = 0
    _envmod.PPO_EXEMPT_STEPS = 0
    _envmod.ENV_STEP_LIMIT = None


@pytest.fixture(autouse=True)
def _counters():
    pre = int(_envmod.ENV_STEP_COUNT)
    _reset()
    yield
    _envmod.ENV_STEP_COUNT = pre + int(_envmod.ENV_STEP_COUNT)
    _envmod.ENV_STEP_LIMIT = None


def _load_conftest():
    spec = importlib.util.spec_from_file_location(
        "r4_conftest_under_test", TESTS_DIR / "conftest.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _tiny_env():
    import numpy as np
    import pandas as pd
    from rl_posctl.env import HybridPositionEnv
    n = 10
    px = pd.Series(np.full(n, 100.0))
    return HybridPositionEnv(
        features=pd.DataFrame(np.zeros((n, 1)), columns=["f0"]),
        prices=pd.DataFrame({"open": px, "close": px}),
        fee=0.0, window_size=1)


# =================================================================
# B1-a commit 必结键完整性
# =================================================================
class TestCommitCompleteness:
    def test_omitted_gen_key_refused_no_negative_writeback(
            self, tmp_path):
        """probe omit_gen 反例:reserve(gen9,eval1)→draw(gen9)→
        commit(eval_steps=0) 不得结清——旧实现落盘 delta.gen=-9
        并使重开账本 gen 归 0(冲回已划拨消费)。"""
        led, path = _mk(tmp_path)
        rid = led.reserve("recording_only",
                          gen_calls=9, eval_steps=1)
        led.draw(rid, "recording_only", gen_calls=9)
        assert led.effective()["gen_calls"] == 9
        with pytest.raises(BudgetExceeded, match="不完整结清"):
            led.commit(rid, "done", eval_steps=0)
        led2 = TaskLedger(path, R3_TASK)
        assert led2.effective()["gen_calls"] == 9
        last = json.loads(path.read_text(
            encoding="utf-8").splitlines()[-1])
        assert last["event"] != "commit"

    def test_empty_actuals_refused(self, tmp_path):
        """probe omit_all 反例:commit() 空参同样拒绝。"""
        led, _ = _mk(tmp_path)
        rid = led.reserve("r", gen_calls=9, eval_steps=1)
        led.draw(rid, "r", gen_calls=9)
        with pytest.raises(BudgetExceeded, match="不完整结清"):
            led.commit(rid, "done")

    def test_complete_settlement_keeps_nine(self, tmp_path):
        """probe complete 正例:显式全键(gen9,eval0)结清;
        gen 保持 9 不双计、不冲回;未用 eval 余额正常释放。"""
        led, path = _mk(tmp_path)
        rid = led.reserve("recording_only",
                          gen_calls=9, eval_steps=1)
        led.draw(rid, "recording_only", gen_calls=9)
        led.commit(rid, "done", gen_calls=9, eval_steps=0)
        led2 = TaskLedger(path, R3_TASK)
        eff = led2.effective()
        assert eff["gen_calls"] == 9
        assert eff["eval_steps"] == 0     # 未用余额随结清释放
        assert led2.outstanding() == {k: 0 for k in led2.limits}
        last = json.loads(path.read_text(
            encoding="utf-8").splitlines()[-1])
        assert last["amounts"]["gen_calls"] == 0   # 无负 delta
        assert last["actual_total"]["gen_calls"] == 9

    def test_mixed_and_all_metrics_required(self, tmp_path):
        """必结键域=全部指标(authorized>0 或 drawn>0);
        漏任一即拒;显式 0 合法。"""
        led, _ = _mk(tmp_path)
        rid = led.reserve("r", eval_steps=5, episodes=3,
                          gen_calls=2)
        led.draw(rid, "r", eval_steps=5, episodes=1)
        with pytest.raises(BudgetExceeded, match="episodes"):
            led.commit(rid, "d", eval_steps=5, gen_calls=0)
        led.commit(rid, "d", eval_steps=5, episodes=3,
                   gen_calls=0)
        eff = led.effective()
        assert eff["eval_steps"] == 5 and eff["episodes"] == 3
        assert eff["gen_calls"] == 0

    def test_duplicate_settlement_refused(self, tmp_path):
        """并发/重复结清同一预约:第二次拒(未知/已闭合)。"""
        led, _ = _mk(tmp_path)
        rid = led.reserve("r", eval_steps=5)
        led.commit(rid, "d", eval_steps=5)
        with pytest.raises(RuntimeError, match="已闭合"):
            led.commit(rid, "d2", eval_steps=5)

    def test_reopen_replay_no_negative_deltas(self, tmp_path):
        """重开重放:完整结清链无负 amounts;abandon 只保留余额。"""
        led, path = _mk(tmp_path)
        r1 = led.reserve("a", gen_calls=4)
        led.draw(r1, "a", gen_calls=3)
        led.commit(r1, "a", gen_calls=3)
        r2 = led.reserve("b", gen_calls=5)
        led.draw(r2, "b", gen_calls=2)
        led.abandon(r2, "b", note="midrun")
        led2 = TaskLedger(path, R3_TASK)
        assert led2.effective()["gen_calls"] == 8
        # = r1 实测 3 + r2 实测 2(draw 即入账)+ r2 未划拨余额 3
        rows = [json.loads(l) for l in
                path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        for r in rows:
            if r["event"] in ("commit", "abandon"):
                assert all(v >= 0
                           for v in r["amounts"].values()), r


# =================================================================
# B1-b 头部约束完整核验
# =================================================================
class TestHeaderCompleteness:
    def _full_header(self, led):
        return {"event": "task_bind", "task_id": led.task_id,
                "budget_face": dict(led.limits),
                "single_caps": dict(led.single_caps),
                "derived_totals": [
                    {"name": n, "parts": list(pp), "cap": c}
                    for n, pp, c in led._derived_spec]}

    def test_single_caps_shrunk_refused(self, tmp_path):
        """probe single_cap 反例:头部 single_caps.ppo_steps 改 1
        后仍不得打开并预约 2。"""
        led, _ = _mk(tmp_path)
        hdr = self._full_header(led)
        hdr["single_caps"]["ppo_steps"] = 1
        p = tmp_path / "sc.jsonl"
        p.write_text(json.dumps(hdr) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError,
                           match="单次上限与代码不一致"):
            open_task_ledger(p)

    def test_single_caps_missing_refused(self, tmp_path):
        led, _ = _mk(tmp_path)
        hdr = self._full_header(led)
        hdr.pop("single_caps")
        p = tmp_path / "scm.jsonl"
        p.write_text(json.dumps(hdr) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="缺 single_caps"):
            open_task_ledger(p)

    def test_derived_totals_missing_refused(self, tmp_path):
        """probe derived_missing 反例:删 derived_totals 仍可开
        并预约的漏洞闭合。"""
        led, _ = _mk(tmp_path)
        hdr = self._full_header(led)
        hdr.pop("derived_totals")
        p = tmp_path / "dm.jsonl"
        p.write_text(json.dumps(hdr) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError,
                           match="缺 derived_totals"):
            open_task_ledger(p)

    def test_derived_totals_wrong_value_refused(self, tmp_path):
        led, _ = _mk(tmp_path)
        hdr = self._full_header(led)
        hdr["derived_totals"][0]["cap"] = 10 ** 9
        p = tmp_path / "dw.jsonl"
        p.write_text(json.dumps(hdr) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError,
                           match="派生总项与代码不一致"):
            open_task_ledger(p)

    def test_complete_header_opens_and_enforces_caps(self,
                                                     tmp_path):
        """正例:完整头打开可用;单次上限照常生效(R3 面 64)。"""
        led, path = _mk(tmp_path)
        led2 = open_task_ledger(path)
        rid = led2.reserve("ok", ppo_steps=2,
                           ppo_learn_attempts=1)
        led2.commit(rid, "ok", ppo_steps=2,
                    ppo_learn_attempts=1)
        with pytest.raises(BudgetExceeded, match="单次"):
            led2.reserve("over", ppo_steps=65)


# =================================================================
# B2 learn 门咽喉阻断与异常记账
# =================================================================
class TestLearnBoundary:
    def _gate(self, tmp_path):
        ct = _load_conftest()
        led, _ = _mk(tmp_path, name="gate.jsonl")
        return ct._LearnGate(led), led

    def test_overrun_third_step_not_executed(self, tmp_path):
        """probe overrun 反例:上界 2、模型尝试 3 步——第 3 步在
        env.step 经济转移**之前**拒绝(economic_steps=2,不是 3);
        abandon 保留余额 2;豁免校正到实际 2(旧:3 步已发生、
        abandon 只记 2、豁免 3)。"""
        gate, led = self._gate(tmp_path)
        env = _tiny_env()
        env.reset()

        class ToyModel:
            n_steps = 2
            n_envs = 1
            called = False

            def learn(self, total_timesteps, callback):
                self.called = True
                for _ in range(3):
                    env.step((0, 0.0))
                    callback({}, {})
                return self
        mod = ToyModel()
        with pytest.raises(BudgetExceeded):
            gate.learn(mod, 2)
        assert mod.called is True
        assert len(env.step_records) == 2      # 第 3 步未执行
        assert _envmod.ENV_STEP_COUNT == 2
        assert led.effective()["ppo_steps"] == 2   # 余额保留
        assert _envmod.PPO_EXEMPT_STEPS == 2   # 校正到实际观察

    def test_roundup_preflight_still_blocks_learn(self, tmp_path):
        """probe roundup 正例保持:n_steps=256、请求 2 → 预约前
        拒,learn 根本不被调用。"""
        gate, _ = self._gate(tmp_path)

        class Big:
            n_steps = 256
            n_envs = 1
            called = False

            def learn(self, *a, **k):
                self.called = True
        mod = Big()
        with pytest.raises(BudgetExceeded, match="单次"):
            gate.learn(mod, 2)
        assert mod.called is False

    def test_legitimate_two_steps_settled(self, tmp_path):
        """probe legitimate 正例:上界 2、2 步——正常结清 2。"""
        gate, led = self._gate(tmp_path)
        env = _tiny_env()
        env.reset()

        class ToyModel:
            n_steps = 2
            n_envs = 1

            def learn(self, total_timesteps, callback):
                for _ in range(2):
                    env.step((0, 0.0))
                    callback({}, {})
                return self
        got = gate.learn(ToyModel(), 2)
        assert got == 2
        snap = led.snapshot()
        assert snap["committed"]["ppo_steps"] == 2
        assert snap["committed"]["ppo_learn_attempts"] == 1
        assert snap["outstanding"]["ppo_steps"] == 0

    def test_eval_budget_not_borrowed_by_learn(self, tmp_path):
        """无梯度余额不能被 learn 越界借用:learn 步全部按 ppo
        豁免;learn 结束后限额恢复原值,其后的 eval 步回到 eval
        限额约束(咽喉拒绝,不执行)。"""
        gate, _ = self._gate(tmp_path)
        _envmod.ENV_STEP_LIMIT = 10     # 套件设置的 eval 限额
        env = _tiny_env()
        env.reset()

        class ToyModel:
            n_steps = 2
            n_envs = 1

            def learn(self, total_timesteps, callback):
                for _ in range(2):
                    env.step((0, 0.0))
                    callback({}, {})
                return self
        gate.learn(ToyModel(), 2)
        assert _envmod.ENV_STEP_LIMIT == 10   # 恢复,不污染套件
        # learn 后:EXEMPT 已校正到实际 2 → eval 用量 0;
        # 限额收紧到 0,下一 eval 步在咽喉被拒(不执行)
        _envmod.ENV_STEP_LIMIT = 0
        with pytest.raises(BudgetExceeded, match="执行中硬限"):
            env.step((0, 0.0))

    def test_swallowed_overrun_keeps_observed_work(self,
                                                   tmp_path):
        """异常路径不失去已观察工作:框架吞掉守卫异常并继续
        抬计数时(不经过 env.step 的罕见路径),commit 拒绝
        超预约量;abandon 余额之外,超界部分按事故补记保全
        实测(不扩约追认,不把低于实测的数当保守余额)。"""
        gate, led = self._gate(tmp_path)

        class Liar:
            n_steps = 2
            n_envs = 1

            def learn(self, total_timesteps, callback):
                for _ in range(5):
                    _envmod.ENV_STEP_COUNT += 1
                    try:
                        callback({}, {})
                    except BudgetExceeded:
                        continue        # 框架吞掉异常继续跑
                return self
        with pytest.raises(BudgetExceeded):
            gate.learn(Liar(), 2)
        snap = led.snapshot()
        assert snap["committed"]["ppo_steps"] == 2      # 余额
        assert snap["incident_backcharged"]["ppo_steps"] == 3
        assert led.effective()["ppo_steps"] == 5        # 观察 5
