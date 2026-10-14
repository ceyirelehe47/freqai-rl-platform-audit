# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R1 / F1:检查点生命周期与确认入口核验。

纯计数/伪模型口径(无 learn、无 env.step、无真实采样、无账本消费):
- CheckpointLifecycle 的"采集→更新→保存"精确次序(替身 saver);
- 阶段元数据存取/冷读(真实小模型,仅构造与保存,不训练);
- verify_final_checkpoint 对旧格式/阶段错误/身份错配/计数不符的
  拒绝(确认入口在任何资源消费之前)。
"""

from __future__ import annotations

import json

import pytest


# ---------------------------------------------------------------------------
# 替身 saver:记录 (stage, target, num_timesteps, optimizer_steps)
# ---------------------------------------------------------------------------
def _rec_saver(records):
    def saver(*, stage, path, target_step, num_timesteps,
              optimizer_steps):
        records.append({"stage": stage, "target": int(target_step),
                        "path": str(path),
                        "num_timesteps": int(num_timesteps),
                        "optimizer_steps": int(optimizer_steps)})
        return {"policy_digest": f"pdig-{stage}-{target_step}",
                "optimizer_digest": f"odig-{stage}-{target_step}"}
    return saver


class TestLifecycleOrder:
    """采集→更新→保存次序(F1 核心;多轮/中间/final/无更新/异常)。"""

    def _life(self, checkpoints, total, records):
        from rl_posctl.skill_p0.p0run import CheckpointLifecycle
        return CheckpointLifecycle(
            "unused", checkpoints, total, "run_t",
            saver=_rec_saver(records))

    def test_collect_never_saves(self):
        records = []
        life = self._life((0, 32768, 65536, 131072), 131072, records)
        life.record_collect(32768)
        life.record_collect(65536)
        assert records == [], "采集期(更新未发生)不得写盘"

    def test_multi_rollout_mid_post_update(self):
        """每档保存发生在对应 train() 返回之后,绑定已完成优化数。"""
        records = []
        life = self._life((0, 32768, 65536), 131072, records)
        # rollout 1..32 采集到 32768(31 个完整 rollout 已训练过?
        # 不——按调用次序驱动,只验证 lifecycle 本身)
        life.record_collect(32768)
        assert records == []
        life.after_train(32768, 1240)     # train(rollout 32) 返回
        assert len(records) == 1
        assert records[0]["stage"] == "mid"
        assert records[0]["target"] == 32768
        assert records[0]["optimizer_steps"] == 1240
        assert records[0]["num_timesteps"] == 32768
        life.record_collect(65536)
        life.after_train(65536, 2520)
        assert len(records) == 2
        assert records[1]["optimizer_steps"] == 2520

    def test_final_after_learn_unique_and_bound(self):
        records = []
        life = self._life((0, 32768, 131072), 131072, records)
        life.record_collect(32768)
        life.after_train(32768, 1240)
        # 131072 == total:登记越过,但由 finalize 落盘(learn 返回后)
        life.record_collect(131072)
        life.after_train(131072, 5080)
        assert len(records) == 1, "target==total 不得作为 mid 落盘"
        fin = life.finalize(131072, 5120)
        assert fin["stage"] == "final"
        assert fin["optimizer_steps"] == 5120
        assert fin["num_timesteps"] == 131072
        assert life.finalized
        with pytest.raises(RuntimeError, match="重复 finalize"):
            life.finalize(131072, 5120)

    def test_no_update_run_final_declares_zero(self):
        """无更新运行:final 仍可保存,optimizer_steps=0 如实声明。"""
        records = []
        life = self._life((0,), 128, records)
        life.record_collect(128)
        life.after_train(128, 0)
        fin = life.finalize(128, 0)
        assert fin["stage"] == "final"
        assert fin["optimizer_steps"] == 0

    def test_train_exception_leaves_no_final(self):
        """train 未正常返回 → 悬置 crossed 使 finalize 显式拒绝。"""
        records = []
        life = self._life((0, 64), 128, records)
        life.record_collect(128)
        with pytest.raises(RuntimeError, match="未 flush"):
            life.finalize(128, 1)
        assert all(r["stage"] != "final" for r in records)

    def test_mid_flush_only_after_train_return(self):
        """train 抛异常:after_train 不被调用,无任何 mid 档(次序)。"""
        records = []
        life = self._life((0, 64), 128, records)
        life.record_collect(64)
        # 模拟 train(rollout) 异常:调用方(包装器)不 flush
        assert records == []
        assert life._crossed == [64]

    def test_finalize_rejects_when_checkpoint_exists(self):
        """同名旧文件存在:真实 saver 路径拒绝覆盖(见真实存档测试)。"""
        from rl_posctl.skill_p0.p0run import CheckpointLifecycle
        # 替身不触盘;真实 create-only 拒绝在 TestStagedArchive 覆盖
        life = CheckpointLifecycle("x", (0,), 8, "r",
                                   saver=_rec_saver([]))
        life.finalize(8, 0)
        assert life.saved[0]["stage"] == "final"


class TestTrainFlushWiring:
    """wrap_train_flush:train 正常返回后才 flush;异常不 flush。"""

    def _wired(self, records):
        from rl_posctl.skill_p0.p0run import CheckpointLifecycle
        from psc_p0_train import wrap_train_flush   # runner 模块

        class _FakeModel:
            num_timesteps = 0

            def train(self):
                return "trained"

        life = CheckpointLifecycle(
            "x", (0, 4), 8, "r", saver=_rec_saver(records))
        m = _FakeModel()
        wrap_train_flush(m, life, {"n": 0})
        return m, life

    def test_flush_after_train_returns(self, monkeypatch):
        import sys
        from pathlib import Path
        monkeypatch.syspath_prepend(
            str(Path(__file__).resolve().parents[2] / "runner"))
        records = []
        m, life = self._wired(records)
        m.num_timesteps = 4
        assert m.train() == "trained"
        life.record_collect(4)      # 采集在下一次 rollout(已训练)
        m.num_timesteps = 8
        assert m.train() == "trained"
        # train 返回 → flush 发生在 train 之后(次序由 wrapper 保证)
        assert [r["stage"] for r in records] == ["mid"]


class TestStagedArchive:
    """真实阶段元数据存档(小模型;不训练、不采样、不步 env)。"""

    @pytest.fixture(scope="class")
    def model(self):
        import numpy as np
        import torch as th
        from gymnasium import spaces
        from rl_posctl.skill_p0.p0policy import P0ActorCriticPolicy

        class _M:                    # 仅承载 policy 与 save 所需字段
            num_timesteps = 0

        th.manual_seed(0)
        obs = spaces.Box(-np.inf, np.inf, (8,), np.float32)
        act = spaces.Box(np.array([0.0, -1.0]),
                         np.array([1.0, 1.0]), dtype=np.float32)
        m = _M()

        class _PpoLike:
            def __init__(self):
                self.policy = P0ActorCriticPolicy(
                    obs, act, lambda _: 3e-4, arm="B")
                self.num_timesteps = 0

            def save(self, path):
                import zipfile as zf
                # 极简 SB3 形态存档:data JSON 携带 header/stage,
                # policy/optimizer 张量文件(与 SB3 同键名)。
                import io
                import torch as _th
                data = {
                    "_psc_p0_header": getattr(self, "_psc_p0_header"),
                    "_psc_p0_stage": getattr(self, "_psc_p0_stage"),
                    "num_timesteps": self.num_timesteps}
                with zf.ZipFile(path, "w") as z:
                    z.writestr("data", json.dumps(data))
                    buf = io.BytesIO()
                    _th.save(self.policy.state_dict(), buf)
                    z.writestr("policy.pth", buf.getvalue())
                    buf2 = io.BytesIO()
                    _th.save(self.policy.optimizer.state_dict(),
                             buf2)
                    z.writestr("policy.optimizer.pth",
                               buf2.getvalue())

        real = _PpoLike()
        m.policy = real.policy
        m.save = real.save
        m._psc_p0_header = None
        # header 直接挂在 real(保存在 real 上)
        return real

    @staticmethod
    def _patch_header(monkeypatch, real):
        from rl_posctl.skill_p0 import p0policy as P
        monkeypatch.setattr(
            P, "save_p0_model", lambda model, path: model.save(
                str(path)))
        real._psc_p0_header = {
            k: f"v{i}" for i, k in enumerate(P.P0_HEADER_FIELDS)}
        real._psc_p0_header["code_digest"] = P.p0_code_digest()

    def test_initial_and_final_staged_roundtrip(self, model,
                                                tmp_path,
                                                monkeypatch):
        from rl_posctl.skill_p0 import p0policy as P
        self._patch_header(monkeypatch, model)
        m0 = P.save_p0_model_staged(
            model, tmp_path / "ck0.zip", stage="initial",
            target_step=0, optimizer_steps=0, run_name="r1")
        assert m0["stage"] == "initial"
        st = P.read_p0_stage(tmp_path / "ck0.zip")
        assert st["policy_digest"] == m0["policy_digest"]
        info = P.inspect_p0_archive(tmp_path / "ck0.zip")
        assert info["adam_steps"] == 0
        assert info["policy_digest"] == m0["policy_digest"]

    def test_same_name_conflict_rejected(self, model, tmp_path,
                                         monkeypatch):
        from rl_posctl.skill_p0 import p0policy as P
        self._patch_header(monkeypatch, model)
        P.save_p0_model_staged(model, tmp_path / "ck0.zip",
                               stage="initial", target_step=0,
                               optimizer_steps=0, run_name="r1")
        with pytest.raises(RuntimeError, match="拒绝覆盖"):
            P.save_p0_model_staged(
                model, tmp_path / "ck0.zip", stage="final",
                target_step=128, optimizer_steps=0, run_name="r1")

    def test_stage_enum_rejected(self, model, monkeypatch):
        from rl_posctl.skill_p0 import p0policy as P
        self._patch_header(monkeypatch, model)
        with pytest.raises(ValueError, match="未知 stage"):
            P.save_p0_model_staged(
                model, None, stage="pre_update", target_step=0,
                optimizer_steps=0, run_name="r1")


class TestVerifyFinalCheckpoint:
    """确认入口核验:资源前的拒绝面(正例 + 全部反例)。"""

    @pytest.fixture(scope="class")
    def archives(self, tmp_path_factory, request):
        import numpy as np
        import torch as th
        from gymnasium import spaces
        from rl_posctl.skill_p0 import p0policy as P
        from rl_posctl.skill_p0.p0policy import (
            P0ActorCriticPolicy)

        th.manual_seed(1)
        obs = spaces.Box(-np.inf, np.inf, (8,), np.float32)
        act = spaces.Box(np.array([0.0, -1.0]),
                         np.array([1.0, 1.0]), dtype=np.float32)

        class _PpoLike:
            def __init__(self):
                self.policy = P0ActorCriticPolicy(
                    obs, act, lambda _: 3e-4, arm="B")
                self.num_timesteps = 128

            def save(self, path):
                import io
                import zipfile as zf
                data = {
                    "_psc_p0_header": self._h,
                    "_psc_p0_stage": self._s,
                    "num_timesteps": self.num_timesteps}
                with zf.ZipFile(path, "w") as z:
                    z.writestr("data", json.dumps(data))
                    buf = io.BytesIO()
                    th.save(self.policy.state_dict(), buf)
                    z.writestr("policy.pth", buf.getvalue())
                    buf2 = io.BytesIO()
                    th.save(self.policy.optimizer.state_dict(),
                            buf2)
                    z.writestr("policy.optimizer.pth",
                               buf2.getvalue())

        real = _PpoLike()
        real._h = {k: f"x{i}" for i, k in
                   enumerate(P.P0_HEADER_FIELDS)}
        real._h.update({
            "code_digest": P.p0_code_digest(),
            "bank_ref": "b" * 64, "arm": "B"})
        real._s = None
        d = tmp_path_factory.mktemp("arch")

        import types

        def _save(stage, target, opt_steps):
            real._s = {
                "stage": stage, "target_step": target,
                "num_timesteps": 128, "optimizer_steps": opt_steps,
                "policy_digest": P.policy_digest(real),
                "optimizer_digest": P.optimizer_state_digest(real),
                "run_name": "engsmoke_B_270201_x",
                "code_digest": P.p0_code_digest(),
                "saved_utc": "2026-10-14T00:00:00Z"}
            p = d / f"ck_{stage}_{opt_steps}.zip"
            real.save(str(p))
            return p

        final_p = _save("final", 128, 0)
        mid_p = _save("mid", 64, 0)
        # 阶段声明 5 次更新而存档 Adam 状态为 0:
        # run_record 与声明一致时,由存档↔声明交叉核验拒绝
        lying_p = _save("final", 128, 5)
        return {"final": final_p, "mid": mid_p,
                "lying": lying_p,
                "digest": P.policy_digest(real), "dir": d}

    def _rr(self, **over):
        base = {"status": "OK", "actual_steps": 128,
                "optimizer_steps": 0, "run_name":
                "engsmoke_B_270201_x",
                "code_digest": None, "bank_ref": "b" * 64,
                "arm": "B"}
        base.update(over)
        return base

    def test_positive_final_accepted(self, archives, monkeypatch):
        from rl_posctl.skill_p0 import p0policy as P
        monkeypatch.setattr(
            P, "save_p0_model", lambda model, path: model.save(
                str(path)))
        rr = self._rr()
        rr["code_digest"] = archives["final"] and P.p0_code_digest()
        out = P.verify_final_checkpoint(
            archives["final"], rr)
        assert out["stage"]["stage"] == "final"
        assert out["adam_steps"] == 0

    def test_mid_stage_rejected(self, archives):
        from rl_posctl.skill_p0 import p0policy as P
        rr = self._rr(code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="pre-update"):
            P.verify_final_checkpoint(archives["mid"], rr)

    def test_run_invalid_rejected(self, archives):
        from rl_posctl.skill_p0 import p0policy as P
        rr = self._rr(status="RUN_INVALID",
                      code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="RUN_INVALID"):
            P.verify_final_checkpoint(archives["final"], rr)

    def test_optimizer_steps_mismatch_rejected(self, archives):
        """阶段声明 5 次更新而存档 Adam=0 → 保存时点与声明不符。"""
        from rl_posctl.skill_p0 import p0policy as P
        rr = self._rr(optimizer_steps=5,
                      code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="Adam"):
            P.verify_final_checkpoint(archives["lying"], rr)
        rr2 = self._rr(optimizer_steps=0,
                       code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="optimizer_steps"):
            P.verify_final_checkpoint(archives["lying"], rr2)

    def test_identity_mismatch_rejected(self, archives):
        from rl_posctl.skill_p0 import p0policy as P
        rr = self._rr(bank_ref="c" * 64,
                      code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="bank_ref"):
            P.verify_final_checkpoint(archives["final"], rr)
        rr = self._rr(arm="A", code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="arm"):
            P.verify_final_checkpoint(archives["final"], rr)

    def test_timesteps_mismatch_rejected(self, archives):
        from rl_posctl.skill_p0 import p0policy as P
        rr = self._rr(actual_steps=64,
                      code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="actual_steps"):
            P.verify_final_checkpoint(archives["final"], rr)

    def test_old_format_without_stage_rejected(self, archives):
        """旧格式(无 _psc_p0_stage,如历史 ck131072)在资源前拒绝。"""
        import json
        import shutil
        import zipfile
        from rl_posctl.skill_p0 import p0policy as P
        src = archives["final"]
        dst = archives["dir"] / "old_format.zip"
        with zipfile.ZipFile(src) as zin, \
                zipfile.ZipFile(dst, "w") as zout:
            for it in zin.infolist():
                if it.filename == "data":
                    data = json.loads(zin.read("data"))
                    data.pop("_psc_p0_stage")
                    zout.writestr("data", json.dumps(data))
                else:
                    zout.writestr(it, zin.read(it.filename))
        rr = self._rr(code_digest=P.p0_code_digest())
        with pytest.raises(RuntimeError, match="旧格式"):
            P.verify_final_checkpoint(dst, rr)
