# -*- coding: utf-8 -*-
"""R1-D 计量与唯一运行目录正反例(独立审查 §8)。

执行前预约(fail closed,动作不发生)、失败保守保留、跨进程一致
(锁内重读)、单次上限(SB3 取整事前控制)、create-only 目录、
同维不同语义存档拒绝(loader 侧,反序列化前)。
"""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import torch as th

from rl_posctl.budget import (
    BudgetExceeded, ReservationLedger, create_only_dir)
from rl_posctl.versions import POSCTL_R1_BUDGET


class TestReservationLedger:
    def test_reserve_commit_lifecycle(self, tmp_path):
        led = ReservationLedger(tmp_path / "b.jsonl")
        rid = led.reserve("t1", ppo_steps=100,
                          ppo_learn_attempts=1)
        assert led.effective()["ppo_steps"] == 100
        led.commit(rid, "t1", ppo_steps=96,
                   ppo_learn_attempts=1)
        assert led.committed["ppo_steps"] == 96
        assert led.effective()["ppo_steps"] == 96

    def test_over_limit_rejected_before_action(self, tmp_path):
        led = ReservationLedger(tmp_path / "b.jsonl",
                                limits={"ppo_steps": 1000})
        rid = led.reserve("t1", ppo_steps=800)
        with pytest.raises(BudgetExceeded, match="fail closed"):
            led.reserve("t2", ppo_steps=300)   # 800+300>1000
        assert led.effective()["ppo_steps"] == 800   # 未变
        led.release(rid, "t1")
        r2 = led.reserve("t2", ppo_steps=300)
        led.commit(r2, "t2", ppo_steps=300)

    def test_single_cap_rejected(self, tmp_path):
        led = ReservationLedger(tmp_path / "b.jsonl")
        cap = POSCTL_R1_BUDGET["ppo_steps_single"]
        with pytest.raises(BudgetExceeded, match="单次上限"):
            led.reserve("t", ppo_steps=cap + 1)

    def test_abandon_keeps_amount_conservative(self, tmp_path):
        led = ReservationLedger(tmp_path / "b.jsonl")
        rid = led.reserve("t1", ppo_steps=500,
                          ppo_learn_attempts=1)
        led.abandon(rid, "t1", note="中断")
        assert led.committed["ppo_steps"] == 500   # 不退额度
        assert led.committed["ppo_learn_attempts"] == 1

    def test_commit_over_reservation_rejected(self, tmp_path):
        led = ReservationLedger(tmp_path / "b.jsonl")
        rid = led.reserve("t1", ppo_steps=100)
        with pytest.raises(BudgetExceeded, match="超预约"):
            led.commit(rid, "t1", ppo_steps=101)

    def test_crash_reload_keeps_open_reservations(self, tmp_path):
        p = tmp_path / "b.jsonl"
        led = ReservationLedger(p)
        rid = led.reserve("t1", ppo_steps=400)
        # 模拟崩溃:新实例重读(未闭合预约继续占用)
        led2 = ReservationLedger(p)
        assert led2.effective()["ppo_steps"] == 400
        with pytest.raises(BudgetExceeded):
            led2.reserve("t2", ppo_steps=(
                POSCTL_R1_BUDGET["ppo_steps_total"] - 400 + 1))

    def test_two_processes_no_double_spend(self, tmp_path):
        """两个独立进程同时预约:锁内重读 ⇒ 第二个被拒(不超发)。"""
        p = tmp_path / "b.jsonl"
        led = ReservationLedger(
            p, limits={"ppo_steps": 1000})
        led.reserve("local", ppo_steps=400)
        code = (
            "import sys\n"
            "sys.path.insert(0,{src!r})\n"
            "from rl_posctl.budget import ReservationLedger\n"
            "led = ReservationLedger({p!r}, "
            "limits={{'ppo_steps': 1000}})\n"
            "try:\n"
            "    led.reserve('other', ppo_steps=700)\n"
            "    print('RESERVED')\n"
            "except Exception as e:\n"
            "    print('REJECTED')\n"
        ).format(src=_src_root(), p=str(p))
        script = tmp_path / "other.py"
        script.write_text(code, encoding="utf-8")
        r = subprocess.run([sys.executable, str(script)],
                           capture_output=True, text=True,
                           timeout=120,
                           env={"PYTHONPATH": _src_root()})
        out = r.stdout.strip().splitlines()[-1]
        # 本进程已占 400;另一进程 700 → 1100 > 1000,锁内重读后拒绝
        assert out == "REJECTED", r.stdout + r.stderr
        # 未超限路径:另一进程 500(400+500=900 ≤ 1000)成功
        code_ok = code.replace("ppo_steps=700", "ppo_steps=500")
        script.write_text(code_ok, encoding="utf-8")
        r2 = subprocess.run([sys.executable, str(script)],
                            capture_output=True, text=True,
                            timeout=120,
                            env={"PYTHONPATH": _src_root()})
        assert r2.stdout.strip().splitlines()[-1] == "RESERVED"


def _src_root():
    import rl_posctl
    return str(Path(rl_posctl.__file__).resolve().parent.parent)


class TestCreateOnlyDir:
    def test_create_and_conflict(self, tmp_path):
        d = create_only_dir(tmp_path / "run1")
        assert d.is_dir()
        with pytest.raises(RuntimeError, match="create-only"):
            create_only_dir(tmp_path / "run1")
        d2 = create_only_dir(tmp_path / "run2")   # 新名可用
        assert d2.is_dir()


class TestLoaderIdentityForged:
    def _tiny_env(self):
        from rl_posctl.env import HybridPositionEnv
        n = 8
        px = pd.Series(100.0 + np.arange(n) * 0.5)
        prices = pd.DataFrame({"open": px, "close": px})
        feats = pd.DataFrame(np.zeros((n, 2)),
                             columns=["f0", "f1"])
        return HybridPositionEnv(features=feats, prices=prices,
                                 fee=0.001, window_size=1)

    def test_forged_same_dim_different_semantics_rejected(
            self, tmp_path):
        """同 obs 维数、不同 observation_spec 的伪造 header:
       反序列化前拒绝(上轮探针:只查 policy_spec+obs_dim 时不拒)。"""
        import zipfile
        from rl_posctl.policy import (POSCTL_HEADER_KEY,
                                      load_posctl_model,
                                      make_posctl_ppo,
                                      save_posctl_model)
        env = self._tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8,
                                seed=0)
        path = tmp_path / "m.zip"
        save_posctl_model(model, path)
        # 篡改 header 的 observation_spec(保持 obs_dim 一致)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            blobs = {n: zf.read(n) for n in names}
        data = json.loads(blobs["data"].decode("utf-8"))
        data[POSCTL_HEADER_KEY]["observation_spec"] = "PosctlObs-v1"
        blobs["data"] = json.dumps(data).encode("utf-8")
        forged = tmp_path / "forged.zip"
        with zipfile.ZipFile(forged, "w") as zf:
            for n, b in blobs.items():
                zf.writestr(n, b)
        with pytest.raises(RuntimeError,
                           match="observation_spec"):
            load_posctl_model(forged, env)

    def test_v1_archive_rejected(self, tmp_path):
        """旧 v1 存档(真实上轮模型风格 header)按 policy_spec 拒绝。"""
        import zipfile
        from rl_posctl.policy import (POSCTL_HEADER_KEY,
                                      load_posctl_model,
                                      make_posctl_ppo,
                                      save_posctl_model)
        env = self._tiny_env()
        model = make_posctl_ppo(env, n_steps=8, batch_size=8,
                                seed=0)
        path = tmp_path / "m.zip"
        save_posctl_model(model, path)
        with zipfile.ZipFile(path) as zf:
            names = zf.namelist()
            blobs = {n: zf.read(n) for n in names}
        data = json.loads(blobs["data"].decode("utf-8"))
        h = data[POSCTL_HEADER_KEY]
        h["policy_spec"] = "HybridAtomBetaPolicy-v1"
        h.pop("account_features", None)
        h.pop("action_space_lo", None)
        h.pop("action_space_hi", None)
        blobs["data"] = json.dumps(data).encode("utf-8")
        forged = tmp_path / "v1.zip"
        with zipfile.ZipFile(forged, "w") as zf:
            for n, b in blobs.items():
                zf.writestr(n, b)
        with pytest.raises(RuntimeError, match="拒绝"):
            load_posctl_model(forged, env)
