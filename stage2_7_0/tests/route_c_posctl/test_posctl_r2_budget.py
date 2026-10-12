# -*- coding: utf-8 -*-
"""R2-01 执行前任务共享预算:计量校验、任务绑定与 runner 顺序正反例。

原缺陷(独立审查 F1/probe):
- 课程/suite/BC 入口在工作完成后 reserve;课程名错误也晚于工作;
- 每 run 新建 QuotaLedger 使全任务生成额度失效(两 run 各 400
  episode 合计 800 > 512 均成功);
- commit(actual=−100)/incident(−50) 被接纳 ⇒ 释放已消耗额度。

本文件用**记录型叶替身**(计数器/计数 stub,零真实科研工作)验证
所有拒例的顺序:真实 main 必须在任何工作叶之前拒绝。
"""

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from rl_posctl.budget import (
    DERIVED_TOTALS, METRICS, TaskLedger, checked_amounts, r2_limits,
    r2_single_caps)
from rl_posctl import banks as banks_mod
from rl_posctl import versions as versions_mod

RUNNER_DIR = Path(__file__).resolve().parents[2] / "runner"
TASK_ID = versions_mod.POSCTL_R2_TASK_ID


def _load_runner(name):
    spec = importlib.util.spec_from_file_location(
        name, RUNNER_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _mk_ledger(tmp_path, name="t.jsonl"):
    led = TaskLedger.create(tmp_path / name, TASK_ID)
    return led, tmp_path / name


class TestAmountValidation:
    """非法计量(负/NaN/inf/非整数/bool/未知指标)一律拒绝。"""

    @pytest.mark.parametrize("bad", [
        -100, -1, float("nan"), float("inf"), -float("inf"), 2.5,
        1.0000001, True])
    def test_commit_rejects_bad_amounts(self, tmp_path, bad):
        led, _ = _mk_ledger(tmp_path)
        rid = led.reserve("t", eval_steps=10)
        with pytest.raises(ValueError):
            led.commit(rid, "t", eval_steps=bad)
        # 拒绝后预约仍占用(不结清)
        assert led.effective()["eval_steps"] == 10

    @pytest.mark.parametrize("bad", [-50, -1, float("nan"), 3.5, False])
    def test_incident_rejects_bad_amounts(self, tmp_path, bad):
        led, _ = _mk_ledger(tmp_path)
        with pytest.raises(ValueError):
            led.incident_backcharge("x", eval_steps=bad)
        assert led.effective()["eval_steps"] == 0   # 未入账

    def test_reserve_rejects_bad_amounts(self, tmp_path):
        led, _ = _mk_ledger(tmp_path)
        for bad in (-5, float("nan"), 2.5, True):
            with pytest.raises(ValueError):
                led.reserve("t", gen_calls=bad)
        with pytest.raises(ValueError, match="未知计量项"):
            led.reserve("t", not_a_metric=1)

    def test_negative_cannot_release_consumption(self, tmp_path):
        """负计量不得释放已消耗额度(reviewer 反例回归)。"""
        led, _ = _mk_ledger(tmp_path)
        rid = led.reserve("t", eval_steps=100)
        led.commit(rid, "t", eval_steps=100)
        assert led.effective()["eval_steps"] == 100
        rid2 = led.reserve("t2", eval_steps=50)
        with pytest.raises(ValueError):
            led.commit(rid2, "t2", eval_steps=-100)
        led.abandon(rid2, "t2")
        # 事故补记同样只能增加消费
        with pytest.raises(ValueError):
            led.incident_backcharge("x", eval_steps=-50)
        assert led.effective()["eval_steps"] >= 100


class TestTaskLedgerBinding:
    def test_create_only_refuses_existing(self, tmp_path):
        led, path = _mk_ledger(tmp_path)
        with pytest.raises(RuntimeError, match="create-only"):
            TaskLedger.create(path, TASK_ID)

    def test_unbound_ledger_refused(self, tmp_path):
        """无 task_bind 首行的旧式账本(R1 形态)拒绝打开——
        不自动改写/续用(R1 账本已耗尽超限的现场保护)。"""
        p = tmp_path / "old_style.jsonl"
        p.write_text(json.dumps(
            {"event": "commit", "rid": "a", "eval_steps": 76432})
            + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="task_bind"):
            TaskLedger(p, TASK_ID)

    def test_wrong_task_id_refused(self, tmp_path):
        _, path = _mk_ledger(tmp_path)
        with pytest.raises(RuntimeError, match="不匹配"):
            TaskLedger(path, "PosCtl_R_OTHER")

    def test_budget_face_maps_mechanically(self):
        """预算面 ↔ 账本限额一一对应(机械复算;无同名近似字段
        漏检查)。R2-05 的字段映射机械测试。"""
        lim = r2_limits()
        assert set(lim.keys()) == set(METRICS)
        b = versions_mod.POSCTL_R2_BUDGET
        assert lim["ppo_steps"] == b["ppo_steps_total"]
        assert lim["ppo_learn_attempts"] == b["ppo_learn_attempts"]
        assert lim["bc_fits"] == b["bc_fits"] == 0
        assert lim["eval_steps"] == b["eval_steps"]
        assert lim["gen_calls"] == b["gen_calls"]
        assert lim["episodes"] == b["episodes"]
        # R2 面与 R1 面分离(R1 耗尽不清零、R2 不挪用)
        assert b["eval_steps"] != versions_mod.POSCTL_R1_BUDGET[
            "eval_steps"]
        # 派生总项 = 分项之和(总项/分项同时可复算)
        for _name, parts, cap in DERIVED_TOTALS:
            assert cap == sum(lim[p] for p in parts)

    def test_budget_face_snapshot_matches_code(self, tmp_path):
        led, _ = _mk_ledger(tmp_path)
        snap = led.snapshot()
        assert snap["task_id"] == TASK_ID
        assert snap["budget_face_matches_code"] is True
        assert snap["derived_totals"]["synthetic_total"][
            "cap"] == versions_mod.POSCTL_R2_BUDGET["synthetic_total"]

    def test_derived_total_enforced(self, tmp_path):
        """synthetic_total(ppo+eval ≤ 33,792)在 reserve 机械复算
        (分项各自生效之外的总项检查)。"""
        led, _ = _mk_ledger(tmp_path)
        rid = led.reserve("a", eval_steps=32_768)
        led.commit(rid, "a", eval_steps=32_768)
        for _i in range(8):        # 单次上限 128 ⇒ 分 8 次约满
            rid2 = led.reserve("b", ppo_steps=128)
            led.commit(rid2, "b", ppo_steps=128)
        with pytest.raises(Exception, match="synthetic_total"):
            led.reserve("c", eval_steps=1)

    def test_bc_is_zero_on_r2_face(self, tmp_path):
        led, _ = _mk_ledger(tmp_path)
        with pytest.raises(Exception):
            led.reserve("bc", bc_fits=1)

    def test_two_runs_cumulative_shared(self, tmp_path):
        """两个 run(两个账本实例)共享同一文件:合计超限即拒。"""
        led1, path = _mk_ledger(tmp_path)
        rid = led1.reserve("run1", eval_steps=20_000)
        led1.commit(rid, "run1", eval_steps=20_000)
        led2 = TaskLedger(path, TASK_ID)      # 新实例 = 新"run"
        with pytest.raises(Exception, match="fail closed"):
            led2.reserve("run2", eval_steps=13_000)   # 合计 33k>? 分项
        rid2 = led2.reserve("run2", eval_steps=12_768)
        led2.commit(rid2, "run2", eval_steps=12_768)
        assert led2.effective()["eval_steps"] == 32_768

    def test_concurrent_processes_share_budget(self, tmp_path):
        _, path = _mk_ledger(tmp_path)
        led = TaskLedger(path, TASK_ID)
        rid = led.reserve("local", eval_steps=30_000)
        code = (
            "import sys\n"
            "sys.path.insert(0,{src!r})\n"
            "from rl_posctl.budget import TaskLedger\n"
            "led = TaskLedger({p!r}, {tid!r})\n"
            "try:\n"
            "    led.reserve('other', eval_steps=5_000)\n"
            "    print('RESERVED')\n"
            "except Exception:\n"
            "    print('REJECTED')\n"
        ).format(src=_src_root(), p=str(path), tid=TASK_ID)
        script = tmp_path / "other.py"
        script.write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True,
                           timeout=120,
                           env={**os.environ,
                                "PYTHONPATH": _src_root()})
        assert r.stdout.strip().splitlines()[-1] == "REJECTED", (
            r.stdout + r.stderr)
        led.release(rid, "local")   # 零工作退还;另一进程重试成功
        r2 = subprocess.run([sys.executable, str(script)],
                            capture_output=True, text=True,
                            timeout=120,
                            env={**os.environ,
                                 "PYTHONPATH": _src_root()})
        assert r2.stdout.strip().splitlines()[-1] == "RESERVED"


def _src_root():
    import rl_posctl
    return str(Path(rl_posctl.__file__).resolve().parent.parent)


class TestGenerationThroughTaskLedger:
    def test_unbound_quota_record_refused(self, tmp_path):
        """QuotaLedger 未绑定任务账本 ⇒ record 拒绝(R1 每-run
        独立配额缺陷的 fail-closed 修正;reviewer
        per_run_generation_limit 反例)。"""
        q = banks_mod.QuotaLedger(tmp_path / "q.jsonl")
        with pytest.raises(RuntimeError, match="任务账本"):
            q.record(gen_calls=1, episodes=1, bank="b", domain="eval")

    def test_generation_failure_still_counted(self, tmp_path):
        """生成失败(结构重试)仍计调用:先预约后生成 ⇒ 调用已
        入账;重试走新 record(不释放)。"""
        led, _ = _mk_ledger(tmp_path)
        q = banks_mod.QuotaLedger(tmp_path / "q.jsonl",
                                  task_ledger=led)
        q.record(gen_calls=1, episodes=1, bank="b", domain="eval")
        # 生成调用失败(模拟):额度已消耗,不退
        assert led.effective()["gen_calls"] == 1
        q.record(gen_calls=1, episodes=1, bank="b", domain="eval")
        assert led.effective()["gen_calls"] == 2

    def test_same_seed_rebuild_counted_in_runner_plan(self):
        """smoke 的生成上界机械包含冷读同 seed 重建
        (GEN_UB = bank + eval + cold rebuild;不偷偷免计)。"""
        mod = _load_runner("posctl_r2_smoke")
        assert mod.GEN_UB == (mod.BANK_EPS + mod.EVAL_EPS
                              + mod.COLD_REBUILDS)
        assert mod.COLD_REBUILDS >= 1


class TestEvalRunnerOrder:
    """真实 main 的先校验/先预约顺序(计数替身;零真实生成)。"""

    def _run_main(self, tmp_path, monkeypatch, argv):
        mod = _load_runner("posctl_r2_eval")
        calls = {"tier": 0, "gen": 0}

        def stub_tier(*a, **k):
            calls["tier"] += 1
            raise AssertionError("tier_validity 不得在拒绝路径执行")

        def stub_gen(*a, **k):
            calls["gen"] += 1
            raise AssertionError("generate_episode 不得在拒绝路径执行")
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

    def test_unknown_baseline_rejected_before_any_work(
            self, tmp_path, monkeypatch):
        """R1 反例回归:错 baseline 名在任何 tier/生成之前拒绝
        (旧:7 次工作叶后 KeyError、账本空)。"""
        led, path = _mk_ledger(tmp_path)
        rc, calls = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path),
             "--baseline", "always_retarget",      # 旧事故名
             "--baseline", "bad_name_xyz"])
        assert rc == 2
        assert calls["tier"] == 0 and calls["gen"] == 0
        rej = list((tmp_path / "out").glob("rejected_*/rejection.json"))
        assert len(rej) == 1
        rec = json.loads(rej[0].read_text(encoding="utf-8"))
        assert "bad_name_xyz" in rec["reason"]
        assert rec["budget_consumed"] is False
        # 无运行目录产生(旧事故产生到 replay 段才崩)
        assert not list((tmp_path / "out").glob("curriculum_eval_*"))
        assert led.effective()["eval_steps"] == 0

    def test_exhausted_budget_rejected_before_first_work_leaf(
            self, tmp_path, monkeypatch):
        """R1 反例回归:额度 0/耗尽 ⇒ 首工作叶之前拒绝(旧:9 次
        工作叶后 BudgetExceeded、账本空)。"""
        led, path = _mk_ledger(tmp_path)
        rid = led.reserve("fill", eval_steps=32_768)   # 耗尽 eval 面
        led.commit(rid, "fill", eval_steps=32_768)
        rc, calls = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(path), "--tier-episodes", "1",
             "--c123-episodes", "1", "--replay-episodes", "1"])
        assert rc == 2
        assert calls["tier"] == 0 and calls["gen"] == 0
        rej = json.loads(next(
            (tmp_path / "out").glob("rejected_*/rejection.json")
            ).read_text(encoding="utf-8"))
        assert "预约被拒" in rej["reason"]
        assert not list((tmp_path / "out").glob("curriculum_eval_*"))

    def test_missing_ledger_rejected(self, tmp_path, monkeypatch):
        rc, _ = self._run_main(
            tmp_path, monkeypatch,
            ["--out-root", str(tmp_path / "out"),
             "--ledger", str(tmp_path / "nope.jsonl")])
        assert rc == 2

    def test_midrun_exception_keeps_reservation_and_log(
            self, tmp_path, monkeypatch):
        """中途异常:预约保守保留(abandon),原字节日志(run_output
        .raw.txt)留痕,不静默扩约。"""
        led, path = _mk_ledger(tmp_path)
        mod = _load_runner("posctl_r2_eval")

        def boom(spec, **k):
            raise RuntimeError("midrun-boom")
        monkeypatch.setattr(mod, "error_report", boom)
        old_argv = sys.argv
        sys.argv = ["posctl_r2_eval.py",
                    "--out-root", str(tmp_path / "out"),
                    "--ledger", str(path),
                    "--tier-episodes", "1", "--c123-episodes", "1",
                    "--replay-episodes", "1"]
        try:
            with pytest.raises(RuntimeError, match="midrun-boom"):
                mod.main()
        finally:
            sys.argv = old_argv
        # 预约保守保留(不退):重开账本读持久化状态(runner 用
        # 自己的实例写盘,测试实例的内存快照是陈旧的)
        led = TaskLedger(path, TASK_ID)
        eff = led.effective()
        assert eff["eval_steps"] > 0
        assert eff["gen_calls"] > 0
        run_dirs = list((tmp_path / "out").glob("curriculum_eval_*"))
        assert len(run_dirs) == 1
        raw = (run_dirs[0] / "run_output.raw.txt").read_bytes()
        assert b"midrun-boom" in raw          # 原字节留痕
        meta = json.loads((run_dirs[0] / "run_meta.json")
                          .read_text(encoding="utf-8"))
        assert meta["exception"] == "RuntimeError('midrun-boom')"

    def test_parent_death_keeps_reservation(self, tmp_path):
        """父进程硬退出(无 abandon 机会):未闭合预约保守占用,
        重开后仍 fail closed(R1 崩溃漏账根因的回归)。"""
        _, path = _mk_ledger(tmp_path)
        driver = (
            "import importlib.util, os, sys\n"
            "spec = importlib.util.spec_from_file_location(\n"
            "    'r', {runner!r})\n"
            "mod = importlib.util.module_from_spec(spec)\n"
            "spec.loader.exec_module(mod)\n"
            "sys.argv = ['r', '--out-root', {out!r}, "
            "'--ledger', {led!r}, '--tier-episodes', '1',\n"
            "        '--c123-episodes', '1', '--replay-episodes', "
            "'1']\n"
            "import rl_posctl.curriculum as c\n"
            "orig = c.generate_episode\n"
            "def die(*a, **k):\n"
            "    os._exit(9)      # 模拟父进程硬死亡(首工作叶)\n"
            "c.generate_episode = die\n"
            "mod.tier_validity = lambda *a, **k: (\n"
            "    c.generate_episode(None, 0), dict())[1]\n"
            "mod.main()\n"
        ).format(runner=str(RUNNER_DIR / "posctl_r2_eval.py"),
                 out=str(tmp_path / "out2"), led=str(path))
        script = tmp_path / "driver.py"
        script.write_text(driver, encoding="utf-8")
        r = subprocess.run(
            [sys.executable, str(script)], capture_output=True,
            text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": _src_root(),
                 "PYTHONDONTWRITEBYTECODE": "1"})
        assert r.returncode == 9      # 硬死亡确认
        led = TaskLedger(path, TASK_ID)
        eff = led.effective()
        assert eff["eval_steps"] > 0 and eff["gen_calls"] > 0
        assert led.outstanding() != {k: 0 for k in METRICS}
        with pytest.raises(Exception):
            led.reserve("after_death", eval_steps=32_768,
                        gen_calls=2_048)


class TestSmokeRunnerOrder:
    def test_invalid_steps_rejected_prework(self, tmp_path, monkeypatch):
        """无效 steps(>128 单次上限)在零工作叶前拒绝(SB3 取整
        事前控制,不先跑再改口径)。"""
        led, path = _mk_ledger(tmp_path)
        mod = _load_runner("posctl_r2_smoke")
        import rl_posctl.experiments as _exp
        monkeypatch.setattr(
            _exp, "build_train_bank",
            lambda *a, **k: (_ for _ in ()).throw(
                AssertionError("bank 不得在拒绝路径生成")))
        old_argv = sys.argv
        sys.argv = ["posctl_r2_smoke.py",
                    "--out-root", str(tmp_path / "out"),
                    "--ledger", str(path), "--steps", "200"]
        try:
            rc = mod.main()
        finally:
            sys.argv = old_argv
        assert rc == 2
        assert not list((tmp_path / "out").glob("smoke_*"))
        assert led.effective()["ppo_steps"] == 0

    def test_legacy_r1_runner_refused(self, tmp_path):
        """R1 入口(末段入账/事后预约模式)默认拒绝,需显式确认。"""
        r = subprocess.run(
            [sys.executable, str(RUNNER_DIR
                                 / "posctl_suite_counted.py"),
             "--out", str(tmp_path / "x.xml"),
             "--ledger", str(tmp_path / "l.jsonl")],
            capture_output=True, text=True, timeout=120,
            env={**os.environ, "PYTHONPATH": _src_root()})
        assert "REFUSED" in r.stdout
        assert not (tmp_path / "x.xml").exists()
