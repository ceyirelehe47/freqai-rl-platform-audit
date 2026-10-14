# -*- coding: utf-8 -*-
"""PSC_P0_v1 FiniteRepair R2 / C1+C2:消费者边界(零真实资源)。

固定行/记录型叶口径(无 learn、无真实 env.step、无生成、无真实
采样、无科学重采样;bootstrap 仅 16 draws 固定数值小算例):
- C1 主实验槽位绑定:用途/arm/seed/几何/代码/输入/优化器证据在
  任何资源前核验;必需字段缺失即拒;工程 smoke 不得冒充 main;
  重复模型身份拒绝;期望来自冻结计划,不取自 record 自述;
- C2 期限/恒时间探针 raw 接线、配对身份显式对齐(不做位置匹配)、
  必需结果集合(5 基线×2 模式)、malformed 输入在预约/工作前拒绝;
- 真实 confirm.main 控制流:六记录型合法 main 正例到达明示生成
  哨兵;smoke 占六槽/缺 train bank/重复身份在生成前拒绝;
  全流程 raw/统计链与逐 episode 原件先于汇总;
- R1 ck0/ck128 只读复用:工程几何 128/2 自洽保持通过,main 槽位
  绑定拒绝(原件只读,不新增真实 smoke)。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from pathlib import Path

import pytest

from test_psc_p0_r1_resource_order import RecLedger

R1_ENGSMOKE_DIR = Path(os.environ.get(
    "PSC_P0_R1_ENGSMOKE_DIR",
    "/mnt/f/trading/acceptance/PSC_P0_R1_20261014/engsmoke/"
    "engsmoke_B_270201_1791953231"))
SLOTS = tuple((a, s) for a in ("A", "B")
              for s in (270201, 270202, 270203))


# ---------------------------------------------------------------------------
# 记录型合法 main 档构造(真实小策略张量 + 记录型 optimizer 状态;
# 无训练、无采样;几何/身份与冻结计划一致)
# ---------------------------------------------------------------------------
def _fake_archive(directory, *, arm, seed, bank_ref, torch_seed,
                  kind="main", total=131_072, opt_steps=5120,
                  n_steps=1024, reserved_ub=None, mids=(32_768, 65_536),
                  status="OK", run_name=None, record_over=None,
                  stage_over=None, header_over=None):
    """写一个记录型存档+配套 run_record,返回 (zip_path, record)。

    默认=合法完整 main(131072 步/5120 优化,含 initial+全部 mid
    +final manifest);kwargs 可构造各种反例形状。optimizer 状态为
    记录型(step 张量=opt_steps),摘要真实可复算。
    """
    import io
    import zipfile

    import numpy as np
    import torch as th
    from gymnasium import spaces

    from rl_posctl.skill_p0 import p0policy as P
    from rl_posctl.skill_p0.p0policy import P0ActorCriticPolicy
    from rl_posctl.skill_p0.p0spec import (
        C1_HORIZON, OPT_STEPS_PER_ROLLOUT, TASK_ID)

    th.manual_seed(torch_seed)
    obs = spaces.Box(-np.inf, np.inf, (8,), np.float32)
    act = spaces.Box(np.array([0.0, -1.0]), np.array([1.0, 1.0]),
                     dtype=np.float32)
    policy = P0ActorCriticPolicy(obs, act, lambda _: 3e-4, arm=arm)
    pol_sd = policy.state_dict()
    opt_sd = {"state": {0: {"step": th.tensor(float(opt_steps))}},
              "param_groups": [{"lr": 3e-4}]}
    pdig = hashlib.sha256("|".join(
        f"{k}:{P._tensor_digest(v)}"
        for k, v in sorted(pol_sd.items())).encode(
            "utf-8")).hexdigest()
    odig = P._optimizer_state_dict_digest(opt_sd)
    run_name = run_name or f"{arm}_{seed}"
    stage = {
        "stage": "final", "target_step": int(total),
        "num_timesteps": int(total),
        "optimizer_steps": int(opt_steps),
        "policy_digest": pdig, "optimizer_digest": odig,
        "run_name": run_name, "code_digest": P.p0_code_digest(),
        "saved_utc": "2026-10-14T00:00:00Z"}
    if stage_over:
        stage.update(stage_over)
    header = {k: f"h-{arm}-{seed}" for k in P.P0_HEADER_FIELDS}
    header.update({
        "arm": arm, "bank_ref": bank_ref,
        "code_digest": P.p0_code_digest(), "task_id": TASK_ID,
        "horizon": int(C1_HORIZON), "gamma": 1.0})
    if header_over:
        header.update(header_over)
    p = Path(directory) / f"ck{total}_{arm}_{seed}_{torch_seed}.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("data", json.dumps({
            "_psc_p0_header": header, "_psc_p0_stage": stage,
            "num_timesteps": int(total)}))
        buf = io.BytesIO()
        th.save(pol_sd, buf)
        z.writestr("policy.pth", buf.getvalue())
        buf2 = io.BytesIO()
        th.save(opt_sd, buf2)
        z.writestr("policy.optimizer.pth", buf2.getvalue())
    manifest = [{"stage": "initial", "target": 0,
                 "num_timesteps": 0, "optimizer_steps": 0}]
    for t in mids:
        manifest.append({
            "stage": "mid", "target": int(t),
            "num_timesteps": int(t),
            "optimizer_steps": (int(t) // n_steps)
            * OPT_STEPS_PER_ROLLOUT})
    manifest.append({"stage": "final", "target": int(total),
                     "num_timesteps": int(total),
                     "optimizer_steps": int(opt_steps)})
    record = {
        "status": status, "run_name": run_name, "arm": arm,
        "seed": seed, "kind": kind, "total_steps": int(total),
        "n_steps": int(n_steps), "actual_steps": int(total),
        "optimizer_steps": int(opt_steps),
        "reserved_ub": int(reserved_ub or total),
        "bank_ref": bank_ref, "code_digest": P.p0_code_digest(),
        "checkpoint_manifest": manifest, "n_rollouts": 0,
        "economic_failure": None}
    if record_over:
        record.update(record_over)
    return p, record


def _slot_tree(runs_root, *, legal=True, torch_seed_base=1,
               engsmoke=False, same_file=False):
    """建六槽位 main 树 + train bank 原件;期望输入身份 = train
    bank 实际字节 sha(独立于 record 自述)。
    返回 (train_bank, bank_ref, slots)。"""
    banks = runs_root / "banks" / "train"
    banks.mkdir(parents=True)
    train_bank = banks / "train_bank.json"
    train_bank.write_text('{"items": []}', encoding="utf-8")
    bank_ref = hashlib.sha256(
        train_bank.read_bytes()).hexdigest()
    slots = []
    if same_file:
        p, rec = _fake_archive(
            runs_root, arm="A", seed=270201, bank_ref=bank_ref,
            torch_seed=77, run_name="A_270201")
        for i, (arm, seed) in enumerate(SLOTS):
            rd = runs_root / "main" / f"{arm}_{seed}"
            rd.mkdir(parents=True)
            ck = rd / "ck131072.zip"
            ck.write_bytes(p.read_bytes())
            rr = dict(rec)
            rr.update({"run_name": f"{arm}_{seed}", "arm": arm,
                       "seed": seed})
            (rd / "run_record.json").write_text(
                json.dumps(rr), encoding="utf-8")
        return train_bank, bank_ref, slots
    for i, (arm, seed) in enumerate(SLOTS):
        rd = runs_root / "main" / f"{arm}_{seed}"
        rd.mkdir(parents=True)
        if engsmoke:
            p, rec = _fake_archive(
                rd, arm=arm, seed=seed, bank_ref=bank_ref,
                torch_seed=1000 + i, kind="engsmoke", total=128,
                opt_steps=2, n_steps=128, mids=(),
                run_name=f"engsmoke_{arm}_{seed}_1")
        else:
            p, rec = _fake_archive(
                rd, arm=arm, seed=seed, bank_ref=bank_ref,
                torch_seed=torch_seed_base + i)
        ck = rd / "ck131072.zip"
        ck.write_bytes(p.read_bytes())
        p.unlink()
        (rd / "run_record.json").write_text(
            json.dumps(rec), encoding="utf-8")
        slots.append((ck, rec))
    return train_bank, bank_ref, slots


def _load_confirm():
    root = Path(__file__).resolve().parents[2] / "runner"
    spec = importlib.util.spec_from_file_location(
        "psc_p0_confirm_r2t", root / "psc_p0_confirm.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _NoLog:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class TestSlotBindingVerifier:
    """C1:verify_final_checkpoint_for_slot 槽位绑定(正例+反例)。"""

    @pytest.fixture(scope="class")
    def legal(self, tmp_path_factory):
        d = tmp_path_factory.mktemp("slot")
        return _fake_archive(d, arm="B", seed=270201,
                             bank_ref="b" * 64, torch_seed=7)

    def _expected(self, bank_ref="b" * 64):
        from rl_posctl.skill_p0.p0policy import (
            expected_main_checkpoint)
        return expected_main_checkpoint("B", 270201, bank_ref=bank_ref)

    def test_legal_main_accepted(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        out = verify_final_checkpoint_for_slot(
            p, rec, self._expected())
        assert out["slot_bound"] is True
        assert out["stage"]["num_timesteps"] == 131072
        assert out["stage"]["optimizer_steps"] == 5120
        assert out["expected"]["run_name"] == "B_270201"

    def test_missing_fields_rejected_not_skipped(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, _ = legal
        with pytest.raises(RuntimeError, match="缺必需字段"):
            verify_final_checkpoint_for_slot(
                p, {"status": "OK"}, self._expected())

    def test_wrong_slot_run_name_rejected(self, legal):
        """同一份档放错槽位/重复占用:run_name 绑定拒绝
        (自洽层或槽位层均可,必须在资源前)。"""
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, run_name="B_270202")
        with pytest.raises(RuntimeError, match="run_name"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_short_geometry_rejected(self, tmp_path):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = _fake_archive(
            tmp_path, arm="B", seed=270201, bank_ref="b" * 64,
            torch_seed=9, total=128, opt_steps=2, n_steps=128,
            mids=())
        with pytest.raises(RuntimeError, match="actual_steps"):
            verify_final_checkpoint_for_slot(p, rec, self._expected())

    def test_total_declared_more_than_actual_rejected(self, legal):
        """total_steps=131072 而 actual=128(自洽层可能过的旧反例):
        槽位绑定按冻结计划拒绝。"""
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, total_steps=262144)
        with pytest.raises(RuntimeError, match="total_steps"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_zero_update_final_rejected(self, tmp_path):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = _fake_archive(
            tmp_path, arm="B", seed=270201, bank_ref="b" * 64,
            torch_seed=10, opt_steps=0)
        with pytest.raises(RuntimeError, match="optimizer_steps"):
            verify_final_checkpoint_for_slot(p, rec, self._expected())

    def test_fewer_steps_final_rejected(self, tmp_path):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = _fake_archive(
            tmp_path, arm="B", seed=270201, bank_ref="b" * 64,
            torch_seed=11, total=65_536, opt_steps=2560,
            mids=(32_768,))
        with pytest.raises(RuntimeError, match="num_timesteps"):
            verify_final_checkpoint_for_slot(p, rec, self._expected())

    def test_stale_code_rejected(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, code_digest="f" * 64)
        with pytest.raises(RuntimeError, match="code_digest"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_wrong_bank_ref_rejected(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, bank_ref="c" * 64)
        with pytest.raises(RuntimeError, match="bank_ref"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_pending_flush_mid_missing_rejected(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, checkpoint_manifest=[
            r for r in rec["checkpoint_manifest"]
            if r.get("target") != 65_536])
        with pytest.raises(RuntimeError, match="mid"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_lying_optimizer_digest_rejected(self, tmp_path):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint, verify_final_checkpoint_for_slot)
        p, rec = _fake_archive(
            tmp_path, arm="B", seed=270201, bank_ref="b" * 64,
            torch_seed=12, stage_over={"optimizer_digest": "0" * 64})
        with pytest.raises(RuntimeError, match="optimizer 摘要"):
            verify_final_checkpoint(p, rec)
        with pytest.raises(RuntimeError, match="optimizer 摘要"):
            verify_final_checkpoint_for_slot(p, rec, self._expected())

    def test_run_invalid_rejected(self, legal):
        from rl_posctl.skill_p0.p0policy import (
            verify_final_checkpoint_for_slot)
        p, rec = legal
        bad = dict(rec, status="RUN_INVALID")
        with pytest.raises(RuntimeError, match="RUN_INVALID"):
            verify_final_checkpoint_for_slot(p, bad, self._expected())

    def test_expected_rejects_unknown_slot(self):
        from rl_posctl.skill_p0.p0policy import (
            expected_main_checkpoint)
        with pytest.raises(ValueError, match="arm"):
            expected_main_checkpoint("C", 270201, bank_ref="b" * 64)
        with pytest.raises(ValueError, match="seed"):
            expected_main_checkpoint("B", 123456, bank_ref="b" * 64)
        with pytest.raises(ValueError, match="bank_ref"):
            expected_main_checkpoint("B", 270201, bank_ref="")


class TestR1SmokeReadonlyReuse:
    """R1 ck0/ck128 只读复用:工程几何保持;main 槽位拒绝。"""

    @pytest.fixture(scope="class")
    def smoke(self):
        ck0 = R1_ENGSMOKE_DIR / "ck0.zip"
        ck128 = R1_ENGSMOKE_DIR / "ck128.zip"
        rec_p = R1_ENGSMOKE_DIR / "run_record.json"
        if not (ck0.exists() and ck128.exists() and rec_p.exists()):
            pytest.skip(f"R1 engsmoke 原件不在场:{R1_ENGSMOKE_DIR}")
        return {"ck0": ck0, "ck128": ck128,
                "record": json.loads(rec_p.read_text(encoding="utf-8")),
                "sha": {n: hashlib.sha256(p.read_bytes()).hexdigest()
                        for n, p in (("ck0", ck0), ("ck128", ck128))}}

    def test_engineering_geometry_still_self_consistent(self, smoke):
        """正常工程 smoke 按自身 128/2 几何核验(R1 结论保持;
        R2 优化器摘要复算同样通过)。"""
        from rl_posctl.skill_p0.p0policy import (
            inspect_p0_archive, verify_final_checkpoint)
        i0 = inspect_p0_archive(smoke["ck0"])
        i128 = inspect_p0_archive(smoke["ck128"])
        assert i0["stage"]["stage"] == "initial"
        assert i0["adam_steps"] == 0
        assert i128["stage"]["stage"] == "final"
        assert i128["adam_steps"] == 2
        assert (i0["policy_digest"] != i128["policy_digest"]), (
            "final 权重必须不同于初始档")
        out = verify_final_checkpoint(smoke["ck128"], smoke["record"])
        assert out["adam_steps"] == 2

    def test_real_smoke_rejected_in_all_six_main_slots(self, smoke):
        """R1 反例复现:同一份真实 B engsmoke+record 放进六个 main
        槽位,槽位绑定必须在任何资源前拒绝(不达生成)。"""
        import shutil
        import tempfile
        from rl_posctl.skill_p0.p0policy import (
            expected_main_checkpoint, verify_final_checkpoint_for_slot)
        with tempfile.TemporaryDirectory() as td:
            for arm, seed in SLOTS:
                d = Path(td) / "main" / f"{arm}_{seed}"
                d.mkdir(parents=True)
                ck = d / "ck131072.zip"
                shutil.copyfile(smoke["ck128"], ck)
                (d / "run_record.json").write_text(
                    json.dumps(smoke["record"]), encoding="utf-8")
                exp = expected_main_checkpoint(
                    arm, seed, bank_ref=smoke["record"]["bank_ref"])
                with pytest.raises(RuntimeError) as ei:
                    verify_final_checkpoint_for_slot(
                        ck, smoke["record"], exp)
                msg = str(ei.value)
                assert "engsmoke" in msg or "run_name" in msg, (
                    f"{arm}_{seed} 必须因用途/槽位错配被拒:{msg[:200]}")


class TestConfirmEntryIntegration:
    """真实 confirm.main 控制流:生成哨兵前的接受/拒绝面。"""

    def _patch_common(self, mod, monkeypatch, runs_root, events):
        monkeypatch.setattr(mod, "RUNS_DIR", runs_root)
        monkeypatch.setattr(
            mod, "open_ledger",
            lambda *a, **k: events.append("ledger_open") or object())
        monkeypatch.setattr(
            mod, "make_sampler_meter", lambda *a, **k: (lambda n: None))
        monkeypatch.setattr(
            mod, "make_bootstrap_meter",
            lambda *a, **k: (lambda n: None))
        monkeypatch.setattr(mod, "RunLog", _NoLog)

    def _run_main(self, mod, monkeypatch, tmp_path):
        out = tmp_path / "confirm"
        argv = ["psc_p0_confirm.py", "--out", str(out)]
        monkeypatch.setattr(sys, "argv", argv)
        rc = None
        try:
            rc = mod.main()
        finally:
            monkeypatch.setattr(sys, "argv", ["psc_p0_confirm.py"])
        return rc, out

    def test_six_legal_main_reach_generation_sentinel(
            self, tmp_path, monkeypatch):
        mod = _load_confirm()
        runs_root = tmp_path / "runs"
        _slot_tree(runs_root)
        events = []

        class StopAtBank(Exception):
            pass

        def bank(*a, **k):
            events.append("BANK_GENERATION_REACHED")
            raise StopAtBank()

        self._patch_common(mod, monkeypatch, runs_root, events)
        monkeypatch.setattr(mod, "build_p0_bank", bank)
        with pytest.raises(StopAtBank):
            self._run_main(mod, monkeypatch, tmp_path)
        assert events == ["ledger_open", "BANK_GENERATION_REACHED"], (
            "合法六槽位必须在任何 bank 生成/评估资源前通过核验,"
            "到达生成哨兵(此处哨兵截停,零生成)")

    def test_six_engsmoke_rejected_before_ledger(
            self, tmp_path, monkeypatch):
        mod = _load_confirm()
        runs_root = tmp_path / "runs"
        _slot_tree(runs_root, engsmoke=True)
        events = []
        self._patch_common(mod, monkeypatch, runs_root, events)
        rc, out = self._run_main(mod, monkeypatch, tmp_path)
        assert rc == 2
        assert events == [], (
            "smoke 占六槽必须在打开账本/生成之前拒绝,零资源消费")
        rej = sorted(out.glob("*rejection*")) + sorted(
            out.rglob("*.json"))
        assert rej, "必须留下拒绝原件"
        blob = "\n".join(p.read_text(encoding="utf-8")
                         for p in rej[:3])
        assert "槽位绑定" in blob or "engsmoke" in blob

    def test_duplicate_model_identity_rejected_before_ledger(
            self, tmp_path, monkeypatch):
        """六个槽位为同一份文件(记录自述已按槽改写):槽位绑定之外
        的第二道防线——sha 重复占用在账本/生成前拒绝。"""
        mod = _load_confirm()
        runs_root = tmp_path / "runs"
        _slot_tree(runs_root, same_file=True)
        events = []
        self._patch_common(mod, monkeypatch, runs_root, events)
        # 用替身绕过档内 run_name 绑定,专测重复身份分支
        monkeypatch.setattr(
            mod, "verify_final_checkpoint_for_slot",
            lambda path, rec, exp: {
                "stage": {"stage": "final"}, "adam_steps": 5120,
                "policy_digest": "stub", "optimizer_digest": "stub",
                "sha256": hashlib.sha256(
                    Path(path).read_bytes()).hexdigest(),
                "slot_bound": True, "expected": {}})
        rc, out = self._run_main(mod, monkeypatch, tmp_path)
        assert rc == 2
        assert events == []
        blob = "\n".join(p.read_text(encoding="utf-8")
                         for p in out.rglob("*.json"))
        assert "重复模型身份" in blob

    def test_missing_train_bank_rejected(
            self, tmp_path, monkeypatch):
        mod = _load_confirm()
        runs_root = tmp_path / "runs"
        _slot_tree(runs_root)
        (runs_root / "banks" / "train" / "train_bank.json").unlink()
        events = []
        self._patch_common(mod, monkeypatch, runs_root, events)
        rc, out = self._run_main(mod, monkeypatch, tmp_path)
        assert rc == 2
        assert events == []
        blob = "\n".join(p.read_text(encoding="utf-8")
                         for p in out.rglob("*.json"))
        assert "train bank" in blob


def _bank_items():
    """固定行 bank 替身:2 pair × 2 variant,行数 4(价格 3 行)。"""
    out = []
    for pair in (0, 1):
        for var in (0, 1):
            out.append(([0.0, 1.0, 2.0], None,
                        {"pair_index": pair, "variant": var}))
    return out


class TestConfirmFullFlowRaw:
    """全流程组合正例:12 次 horizon 评估 + 恒时间探针 + 统计输入
    均通过同一落盘链;逐 episode 原件早于汇总,可复算。"""

    @pytest.fixture()
    def flow(self, tmp_path, monkeypatch):
        mod = _load_confirm()
        runs_root = tmp_path / "runs"
        out = tmp_path / "confirm"
        _slot_tree(runs_root)
        events = []
        monkeypatch.setattr(mod, "RUNS_DIR", runs_root)
        monkeypatch.setattr(mod, "RunLog", _NoLog)
        monkeypatch.setattr(mod, "BOOTSTRAP_DRAWS", 16)
        monkeypatch.setattr(
            mod, "build_p0_bank",
            lambda purpose, **kw: {"fixture": purpose})
        items = _bank_items()
        monkeypatch.setattr(
            mod, "load_p0_bank", lambda path: items)
        monkeypatch.setattr(
            mod, "P0EpisodeBankEnv", lambda *a, **k: None)

        class _FakeModel:
            def predict(self, obs, deterministic=True):
                import numpy as np
                return (np.zeros(2, dtype=np.float32), None)

        monkeypatch.setattr(
            mod, "load_p0_model", lambda *a, **k: _FakeModel())
        calls = []

        def action_fn(model, *, deterministic):
            calls.append(
                {"mode": "deterministic" if deterministic
                 else "sampled"})
            return lambda *x: None

        monkeypatch.setattr(mod, "model_action_fn", action_fn)
        profit = {"v": 0.02}

        def summarizer(infos):
            return {"n_steps": 2, "net_log_return": profit["v"],
                    "net_log_return_valid": True,
                    "economic_failure": False, "total_fees": 0.001}

        ledger = RecLedger(10 ** 6)

        import rl_posctl.skill_p0.p0eval as E

        def ev(items_, fn, **kw):
            calls.append({"tag": kw.get("tag"),
                          "raw": kw.get("raw_sink") is not None})
            profit["v"] = (
                0.01 if ":base:" in str(kw.get("tag")) else 0.02)
            return E.eval_on_bank(
                items_, fn, ledger=ledger, tag=kw.get("tag"),
                raw_sink=kw.get("raw_sink"),
                env_factory=lambda it: object(),
                runner=lambda env, f: [], summarizer=summarizer)

        monkeypatch.setattr(mod, "eval_on_bank", ev)
        monkeypatch.setattr(
            mod, "behavior_gate",
            lambda model, **k: {"pass": True, "n_conditions": 216})
        monkeypatch.setattr(
            mod, "baseline_fns",
            lambda: {b: (lambda *a: None) for b in (
                "flat", "const+1", "const-1", "const+0.5",
                "const-0.5")})
        monkeypatch.setattr(mod, "reference_policy", lambda spec: {})
        monkeypatch.setattr(
            mod, "reference_action_fn",
            lambda ref, spec: (lambda *a: None))
        monkeypatch.setattr(
            mod, "sign_action_fn",
            lambda: (lambda *a: None))
        probe_calls = []

        def probe(finals, items_h, ledger_, purpose,
                  raw_sink_factory=None):
            probe_calls.append(
                {"purpose": purpose,
                 "factory": raw_sink_factory is not None})
            if raw_sink_factory is not None:
                nm = sorted(finals)[0]
                raw_sink_factory(nm)({
                    "episode": 0, "model": nm,
                    "mode": "constant_time_template",
                    "bank_purpose": purpose, "pair_index": 0,
                    "variant": 0, "net_log_return": 0.01,
                    "n_steps": 2, "n_failure": 0})
            return {nm: [] for nm in sorted(finals)[:2]} if \
                raw_sink_factory else {}

        monkeypatch.setattr(
            mod, "constant_time_template_probe", probe)
        monkeypatch.setattr(
            mod, "make_sampler_meter", lambda *a, **k: (lambda n: None))
        bmeter = []
        monkeypatch.setattr(
            mod, "make_bootstrap_meter",
            lambda *a, **k: bmeter.append)
        monkeypatch.setattr(
            mod, "open_ledger", lambda *a, **k: ledger)
        monkeypatch.setattr(
            mod, "evidence_kib_settle",
            lambda *a, **k: {"kib": 0})
        return {"mod": mod, "out": out, "calls": calls,
                "probe_calls": probe_calls, "ledger": ledger,
                "bmeter": bmeter, "monkeypatch": monkeypatch,
                "items": items}

    def test_full_positive_all_raw_wired(self, flow, monkeypatch):
        mod = flow["mod"]
        argv = ["psc_p0_confirm.py", "--out", str(flow["out"])]
        monkeypatch.setattr(sys, "argv", argv)
        try:
            rc = mod.main()
        finally:
            monkeypatch.setattr(sys, "argv", ["psc_p0_confirm.py"])
        assert rc == 0
        raw = flow["out"] / "raw"
        names = sorted(p.name for p in raw.glob("*.jsonl"))
        model_raw = [n for n in names if n.startswith("model_")]
        base_raw = [n for n in names if n.startswith("baseline_")]
        boot_raw = [n for n in names if n.startswith("bootstrap_")]
        hz_raw = [n for n in names
                  if n.startswith(("hz32_", "hz96_"))]
        probe_raw = [n for n in names if n.startswith("hzprobe_")]
        assert len(model_raw) == 12, "6 模型 × 2 模式 raw"
        assert len(base_raw) == 7, "5 基线 + reference + sign_rule"
        assert len(boot_raw) == 20, "2 臂 × 5 基线 × 2 模式"
        assert len(hz_raw) == 12, "H=32/96 × 6 模型全接通 raw_sink"
        tag_calls = [c for c in flow["calls"] if "tag" in c]
        hz_evals = [c for c in tag_calls
                    if str(c["tag"]).startswith(("hz32:", "hz96:"))]
        assert len(hz_evals) == 12
        assert all(c["raw"] for c in tag_calls), (
            "全部实际 eval 调用必须携带 raw_sink(不得只加可选参数)")
        assert all(c["factory"] for c in flow["probe_calls"])
        report = json.loads(
            (flow["out"] / "confirm_report.json").read_text(
                encoding="utf-8"))
        assert report["layered_exit"][
            "c1_learning_evidence_established"] is True
        assert all(
            v["arm_gate_pass"] for v in report["arm_level"].values())

    def test_raw_recomputable_before_aggregation(self, flow,
                                                 monkeypatch):
        mod = flow["mod"]
        monkeypatch.setattr(sys, "argv", [
            "psc_p0_confirm.py", "--out", str(flow["out"])])
        try:
            mod.main()
        finally:
            monkeypatch.setattr(sys, "argv", ["psc_p0_confirm.py"])
        raw = flow["out"] / "raw"
        rows = [json.loads(line) for line in (
            raw / "model_B_270201_deterministic.jsonl").read_text(
            encoding="utf-8").splitlines()]
        assert len(rows) == 4
        for r in rows:
            for key in ("episode", "tag", "pair_index", "variant",
                        "steps", "summary", "net_log_return",
                        "reward_valid", "economic_failure"):
                assert key in r, f"raw 行缺身份/成本字段 {key}"
        mean = sum(r["net_log_return"] for r in rows) / len(rows)
        report = json.loads(
            (flow["out"] / "confirm_report.json").read_text(
                encoding="utf-8"))
        econ = report["per_seed"]["B_270201"]["economics"][
            "deterministic"]
        assert abs(econ["mean"] - mean) < 1e-12, (
            "汇总必须可从 raw 原件复算")
        boot_in = json.loads(
            (raw / "bootstrap_A_flat_deterministic.jsonl").read_text(
                encoding="utf-8").splitlines()[0])
        assert boot_in["kind"] == "bootstrap_input"
        assert boot_in["draws"] == 16
        assert boot_in["pair_values"] == pytest.approx([0.01, 0.01])

    def test_interrupt_keeps_written_raw(self, flow, monkeypatch):
        """中断:已写原件保留;聚合报告不产生;无重放补行。"""
        mod = flow["mod"]
        real_ev = mod.eval_on_bank
        state = {"n": 0}

        def ev(items_, fn, **kw):
            state["n"] += 1
            if state["n"] == 3:
                raise RuntimeError("评估中断反例")
            return real_ev(items_, fn, **kw)

        monkeypatch.setattr(mod, "eval_on_bank", ev)
        monkeypatch.setattr(sys, "argv", [
            "psc_p0_confirm.py", "--out", str(flow["out"])])
        with pytest.raises(RuntimeError, match="中断"):
            try:
                mod.main()
            finally:
                monkeypatch.setattr(sys, "argv", ["psc_p0_confirm.py"])
        raw = flow["out"] / "raw"
        kept = sorted(p.name for p in raw.glob("*.jsonl"))
        assert kept, "中断时已写 raw 原件必须保留"
        assert not (flow["out"] / "confirm_report.json").exists(), (
            "中断不得产出聚合报告")


class TestProbeRawIdentity:
    """真实 constant_time_template_probe:探针 raw 行身份 + 先约后用。"""

    def test_probe_rows_carry_identity(self, tmp_path, monkeypatch):
        import numpy as np

        import rl_posctl.evalreport as er
        import rl_posctl.skill_p0.p0eval as E
        mod = _load_confirm()

        class _Env:
            def __init__(self):
                self.n = 0

            def reset(self):
                return np.zeros(8, dtype=np.float32), {}

            def step(self, a):
                self.n += 1
                return (np.zeros(8, dtype=np.float32), 0.0,
                        self.n >= 2, False, {})

        class _Model:
            def predict(self, obs, deterministic=True):
                return (np.zeros(2, dtype=np.float32), None)

        rec_p = tmp_path / "run_record.json"
        rec_p.write_text(json.dumps(
            {"status": "OK", "bank_ref": "b" * 64}),
            encoding="utf-8")
        finals = {"A_270201": {"path": "", "run_record": str(rec_p)}}
        items = _bank_items()
        monkeypatch.setattr(mod, "make_env", lambda it: _Env())
        monkeypatch.setattr(
            mod, "P0EpisodeBankEnv", lambda *a, **k: _Env())
        monkeypatch.setattr(
            mod, "load_p0_model", lambda *a, **k: _Model())
        monkeypatch.setattr(
            er, "summarize",
            lambda infos: {"n_steps": 2, "net_log_return": 0.01,
                           "economic_failure": False,
                           "total_fees": 0.001,
                           "net_log_return_valid": True})
        ledger = RecLedger(100)
        files = {}

        def factory(name):
            p = tmp_path / f"hzprobe_{name}.jsonl"
            fh = p.open("x", encoding="utf-8")

            def sink(row):
                fh.write(json.dumps(row, ensure_ascii=False) + "\n")
                fh.flush()
            files[name] = (p, fh, sink)
            return sink

        rows = mod.constant_time_template_probe(
            finals, items, ledger, "hz32",
            raw_sink_factory=factory)
        for name, (p, fh, _s) in files.items():
            fh.close()
        assert set(files) == {"A_270201"}
        lines = [json.loads(x) for x in
                 files["A_270201"][0].read_text(
                     encoding="utf-8").splitlines()]
        assert len(lines) == 4
        for r in lines:
            assert r["model"] == "A_270201"
            assert r["mode"] == "constant_time_template"
            assert r["bank_purpose"] == "hz32"
            assert isinstance(r["pair_index"], int)
            assert "variant" in r and "summary" in r
            assert "total_fees" in r["summary"]
        kinds = [e[0] for e in ledger.events]
        assert kinds[0] == "reserve" and kinds[-1] == "commit", (
            "先约后用;实结一次")
        assert not [k for k in kinds if k == "abandon"]
        # 中断保留:第二次调用中途抛异常,已写行不消失
        ledger2 = RecLedger(100)

        def sink_boom(row):
            raise RuntimeError("探针写入中断反例")

        with pytest.raises(RuntimeError, match="写入中断"):
            mod.constant_time_template_probe(
                finals, items, ledger2, "hz96",
                raw_sink_factory=lambda nm: sink_boom)
        assert ledger2.events[-1][0] == "abandon", "异常保守保留预约"


class TestEvalMalformedBeforeWork:
    """C2:malformed 输入身份在预约/建环境/工作之前拒绝。"""

    def _run(self, items, cap=100):
        counter = {"env": 0, "work": 0}
        ledger = RecLedger(cap)
        from rl_posctl.skill_p0.p0eval import eval_on_bank

        def env_factory(it):
            counter["env"] += 1
            return object()

        def runner(env, fn):
            counter["work"] += 1
            return []

        def summarizer(infos):
            return {"n_steps": 1, "net_log_return": 0.0,
                    "net_log_return_valid": True,
                    "economic_failure": False}

        err = None
        try:
            eval_on_bank(items, lambda *a: None, ledger=ledger,
                         tag="t", env_factory=env_factory,
                         runner=runner, summarizer=summarizer)
        except ValueError as e:
            err = e
        return err, counter, ledger

    def test_missing_pair_index_rejected_before_any_work(self):
        bad = [([0, 1, 2], None, {"variant": 0})]
        err, counter, ledger = self._run(bad)
        assert err is not None and "pair_index" in str(err)
        assert counter == {"env": 0, "work": 0}
        assert ledger.events == [], "预约也不得发生"

    def test_missing_variant_rejected_before_any_work(self):
        bad = [([0, 1, 2], None, {"pair_index": 0})]
        err, counter, ledger = self._run(bad)
        assert err is not None and "variant" in str(err)
        assert counter == {"env": 0, "work": 0}
        assert ledger.events == []

    def test_string_pair_index_rejected(self):
        bad = [([0, 1, 2], None,
                {"pair_index": "0", "variant": 0})]
        err, counter, ledger = self._run(bad)
        assert err is not None
        assert counter == {"env": 0, "work": 0}
        assert ledger.events == []

    def test_non_tuple_item_rejected(self):
        bad = [([0, 1, 2], None)]
        err, counter, ledger = self._run(bad)
        assert err is not None and "结构非法" in str(err)
        assert ledger.events == []

    def test_valid_items_still_pass(self):
        ok, counter, ledger = self._run(_bank_items())
        assert ok is None
        assert counter["work"] == 4
        assert [e[0] for e in ledger.events] == ["reserve", "commit"]


class TestPairMatrixIdentityControls:
    """C2:四行固定夹具——身份/顺序/重复/缺端点/有效性/NaN。"""

    @staticmethod
    def _rows(values, *, pair=None, variant=None,
              failures=None, invalid=None, nan=None):
        out = []
        for i, v in enumerate(values):
            out.append({
                "episode": i,
                "pair_index": (i // 2 if pair is None else pair[i]),
                "variant": (i % 2 if variant is None else variant[i]),
                "net_log_return": (
                    float("nan") if (nan and i in nan) else v),
                "reward_valid": not (invalid and i in invalid),
                "economic_failure": bool(failures and i in failures)})
        return out

    def _base(self):
        return self._rows([0.10, 0.12, 0.08, 0.10])

    def test_identity_aligned_positive_matches_r1_math(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.20, 0.24, 0.18, 0.22])
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is True
        assert mat["pair_values"] == pytest.approx([0.11, 0.11])

    def test_reordered_rows_same_result(self):
        """行序重排但身份一致 → 显式按身份映射,结果不变。"""
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.18, 0.22, 0.20, 0.24],
                           pair=[1, 1, 0, 0], variant=[0, 1, 0, 1])
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is True
        assert mat["pair_values"] == pytest.approx([0.11, 0.11])

    def test_wrong_pair_index_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22],
                           pair=[999, 999, 1, 1])
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert "身份不一致" in mat["reason"]

    def test_wrong_variant_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22],
                           variant=["A", "B", "A", "B"])
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert "身份不一致" in mat["reason"]

    def test_duplicate_endpoint_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22],
                           pair=[0, 0, 0, 1], variant=[0, 0, 1, 1])
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert ("重复" in mat["reason"]
                or "端点数" in mat["reason"])

    def test_missing_endpoint_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        base = self._rows([0.1, 0.12, 0.08])
        model = self._rows([0.2, 0.24, 0.18])
        mat = pair_advantage_matrix({"m": model}, base)
        assert mat["valid"] is False
        assert "端点数" in mat["reason"]

    def test_economic_failure_flag_rejected_not_consumed(self):
        """economic_failure=True 即便数值有限也拒绝;分母保留。"""
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22],
                           failures={3: "margin"})
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert "episode 3" in mat["reason"]
        assert "economic_failure" in mat["reason"]

    def test_reward_valid_false_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22], invalid={2})
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert "reward_valid" in mat["reason"]

    def test_nan_and_none_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22], nan={1})
        mat = pair_advantage_matrix({"m": model}, self._base())
        assert mat["valid"] is False
        assert "非有限" in mat["reason"]
        model2 = self._rows([0.2, None, 0.18, 0.22])
        mat2 = pair_advantage_matrix({"m": model2}, self._base())
        assert mat2["valid"] is False

    def test_none_model_rows_rejected_required_seed(self):
        """缺必需模型行(种子缺失)在配对前拒绝,不宽松遍历。"""
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        model = self._rows([0.2, 0.24, 0.18, 0.22])
        mat = pair_advantage_matrix(
            {"A_270201": model, "A_270202": None,
             "A_270203": model}, self._base())
        assert mat["valid"] is False
        assert "缺必需模型行" in mat["reason"]

    def test_baseline_identity_duplicate_rejected(self):
        from rl_posctl.skill_p0.p0eval import pair_advantage_matrix
        base = self._rows([0.1, 0.12, 0.08, 0.1],
                          pair=[0, 0, 1, 1], variant=[0, 1, 0, 0])
        model = self._rows([0.2, 0.24, 0.18, 0.22])
        mat = pair_advantage_matrix({"m": model}, base)
        assert mat["valid"] is False
        assert "重复" in mat["reason"]


class TestBootstrapRequiredSet:
    """C2:必需结果集合(5 基线 × 2 模式;缺项=证据不足)。"""

    @staticmethod
    def _boot():
        return {b: {"deterministic": {"valid": True,
                                      "lower_positive": True},
                    "sampled": {"valid": True,
                                "lower_positive": True}}
                for b in ("flat", "const+1", "const-1",
                          "const+0.5", "const-0.5")}

    def test_full_set_passes(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        assert bootstrap_results_all_valid_positive(
            self._boot()) is True

    def test_missing_whole_baseline_fails(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        del boot["flat"]
        assert bootstrap_results_all_valid_positive(boot) is False

    def test_missing_whole_mode_fails(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        del boot["flat"]["sampled"]
        assert bootstrap_results_all_valid_positive(boot) is False

    def test_missing_required_key_fails(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        del boot["const+1"]["deterministic"]["valid"]
        assert bootstrap_results_all_valid_positive(boot) is False
        boot2 = self._boot()
        boot2["const-1"]["sampled"]["lower_positive"] = False
        assert bootstrap_results_all_valid_positive(boot2) is False

    def test_single_baseline_or_mode_insufficient(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        assert bootstrap_results_all_valid_positive(
            {"flat": boot["flat"]}) is False
        assert bootstrap_results_all_valid_positive(
            {"flat": {"deterministic":
                      boot["flat"]["deterministic"]}}) is False
        assert bootstrap_results_all_valid_positive({}) is False

    def test_extra_entries_fail_exact_set(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = self._boot()
        boot["unexpected"] = dict(boot["flat"])
        assert bootstrap_results_all_valid_positive(boot) is False
        boot2 = self._boot()
        boot2["flat"]["extra_mode"] = {
            "valid": True, "lower_positive": True}
        assert bootstrap_results_all_valid_positive(boot2) is False

    def test_custom_required_sets_honored(self):
        from rl_posctl.skill_p0.p0eval import (
            bootstrap_results_all_valid_positive)
        boot = {"b1": {"m1": {"valid": True,
                              "lower_positive": True}}}
        assert bootstrap_results_all_valid_positive(
            boot, required_baselines=("b1",),
            required_modes=("m1",)) is True
        assert bootstrap_results_all_valid_positive(
            boot, required_baselines=("b1", "b2"),
            required_modes=("m1",)) is False
