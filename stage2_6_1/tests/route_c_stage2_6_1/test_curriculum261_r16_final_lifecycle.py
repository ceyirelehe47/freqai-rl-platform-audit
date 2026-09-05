# -*- coding: utf-8 -*-
"""R16 final 生命周期测试(§6.3 顺序/§6.4 异常分支;mock 领域核心)。

断言权威 journal 的事件序列——生命周期的每个阶段转换都留下
可重放的事实;异常只结束自己拥有的操作。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import rl_curriculum.curriculum261_r16_final as r16_final
from rl_curriculum.curriculum261_r16_execgov import (
    R16OwnershipError,
    journal_entries,
)


@pytest.fixture()
def state_root(tmp_path, monkeypatch):
    root = tmp_path / "r16_state"
    root.mkdir()
    monkeypatch.setenv("CURRICULUM261_R16_STATE_ROOT", str(root))
    monkeypatch.delenv("CURRICULUM261_R16_EXECUTOR_TOKEN", raising=False)
    return root


PLAN = {
    "iteration": "r16",
    "robustness_gate": {"pass": True},
    "parameter_pack": {"digest": "pack-1"},
    "final_sample_counts": {"c2_matched_blocks": 10},
    "vendor_pin": "x" * 40,
    "preprocessing_v2": {"contract_digest": "v2d"},
    "code_identity": {},
    "cue_semantic_contract": {},
}


@pytest.fixture()
def mocked_final(monkeypatch, state_root):
    """mock 全部前置检查与领域核心;记录调用顺序。"""
    calls = {"core": 0, "core_exception": None, "exposure_io": None}

    def fake_load():
        return dict(PLAN), "digest-1"

    monkeypatch.setattr(r16_final, "load_locked_plan_r16", fake_load)

    import rl_curriculum.curriculum261_r16_param_pack as pp

    monkeypatch.setattr(pp, "load_selected_pack",
                        lambda root: {"digest": "pack-1",
                                      "recall_floor": 0.95,
                                      "p_contract": 0.95})

    import rl_curriculum.curriculum261_r16_preflight as pf

    monkeypatch.setattr(
        pf, "verify_sealed_attestation",
        lambda out_dir: {"pass": True,
                         "attestation": {"plan_digest": "digest-1"}})
    monkeypatch.setattr(r16_final, "_static_identity_checks_r16",
                        lambda *a, **k: None)

    def fake_core(out_dir, plan, pack, **kwargs):
        calls["core"] += 1
        calls["last_kwargs"] = kwargs
        if calls["core_exception"]:
            raise calls["core_exception"]
        return {"verdict": "PASS", "checks": {}}

    monkeypatch.setattr(r16_final, "execute_final_core_r16", fake_core)
    return calls


def events():
    return [e["event"] for e in journal_entries()]


class TestHappyPath:
    def test_lifecycle_event_order(self, mocked_final, state_root,
                                   tmp_path):
        result = r16_final.run_final_qualification_r16(tmp_path / "out")
        assert result["verdict"] == "PASS"
        ev = events()
        # §6.3 顺序:acquire → exposure → grant → (core) → revoke →
        # terminal → release
        assert ev[0] == "session_acquired"
        i_exp = ev.index("exposure_started")
        i_grant = ev.index("grant_issued")
        i_del = ev.index("executor_delegated")
        i_rev = ev.index("grant_revoked")
        i_term = ev.index("qualification_terminal")
        i_rel = ev.index("session_released")
        assert (i_exp < i_grant < i_del < i_rev < i_term < i_rel)
        # core 收到 _r16 namespace
        kw = mocked_final["last_kwargs"]
        assert kw["final_namespace"] == "qualification_r16"
        assert kw["fit_namespace"] == "preprocess_fit_qualification_r16"
        assert kw["independent_namespace"] == (
            "c2_independent_qualification_r16")
        assert kw["semantic_namespace_override"] == (
            "cue_semantic_qualification_r16")
        assert kw["fresh_seed_final_namespace"] == "qualification_r16"

    def test_failed_verdict_terminal_failed(self, mocked_final,
                                            state_root, tmp_path):
        def fake_core(out_dir, plan, pack, **kwargs):
            return {"verdict": "FAIL", "checks": {}}

        monkeypatch_holder = TestHappyPath  # noqa: F841
        import rl_curriculum.curriculum261_r16_final as f

        orig = f.execute_final_core_r16
        f.execute_final_core_r16 = fake_core
        try:
            r16_final.run_final_qualification_r16(tmp_path / "out")
        finally:
            f.execute_final_core_r16 = orig
        term = [e for e in journal_entries()
                if e["event"] == "qualification_terminal"][0]
        assert term["status"] == "failed"


class TestExceptionBranches:
    def test_core_exception_crashes_and_releases(self, mocked_final,
                                                 state_root, tmp_path):
        mocked_final["core_exception"] = RuntimeError("core boom")
        with pytest.raises(RuntimeError, match="core boom"):
            r16_final.run_final_qualification_r16(tmp_path / "out")
        ev = events()
        assert "qualification_terminal" in ev
        term = [e for e in journal_entries()
                if e["event"] == "qualification_terminal"][0]
        assert term["status"] == "crashed"
        assert ev[-1] == "session_released"
        assert (tmp_path / "out"
                / "qualification_crash_traceback.log").is_file()

    def test_precheck_failure_no_exposure_no_session(
            self, mocked_final, state_root, tmp_path, monkeypatch):
        """前置检查失败:exposure 未发生、无会话事件(资格未消耗)。"""
        monkeypatch.setattr(
            r16_final, "load_locked_plan_r16",
            lambda: (_ for _ in ()).throw(RuntimeError("plan 未锁定")))
        with pytest.raises(RuntimeError, match="plan 未锁定"):
            r16_final.run_final_qualification_r16(tmp_path / "out")
        assert events() == []  # 零正式副作用

    def test_competing_request_zero_side_effects(
            self, mocked_final, state_root, tmp_path):
        """§6.2:A 持有会话时 B 的 qualify 请求:R16OwnershipError
        直接传播,journal 只有 A 的事件 + B 的 session_rejected。"""
        from rl_curriculum.curriculum261_r16_execgov import (
            R16FormalSession,
        )

        a = R16FormalSession.acquire(binding={"role": "A"})
        with pytest.raises(R16OwnershipError):
            r16_final.run_final_qualification_r16(tmp_path / "out")
        ev = events()
        assert "exposure_started" not in ev
        assert "iteration_aborted" not in ev
        assert "qualification_terminal" not in ev
        assert any(e == "session_rejected" for e in ev)
        assert a.owns()  # A 不受影响
        a.release()


class TestOneShotAcrossCalls:
    def test_second_run_rejected_after_terminal(self, mocked_final,
                                                state_root, tmp_path):
        r16_final.run_final_qualification_r16(tmp_path / "out")
        with pytest.raises(RuntimeError, match="已 exposure"):
            r16_final.run_final_qualification_r16(tmp_path / "out")
        # 恰好一次 exposure / 一次终态
        ev = events()
        assert ev.count("exposure_started") == 1
        assert ev.count("qualification_terminal") == 1


class TestCliQualifyCompetitionHandling:
    """cmd_qualify 的竞争区分(§6.2):R16OwnershipError 不写
    iteration aborted、不 dump failure evidence。"""

    def test_ownership_error_skips_aborted_write(
            self, state_root, tmp_path, monkeypatch):
        import rl_curriculum.curriculum261_r16_execgov as eg

        a = eg.R16FormalSession.acquire(binding={"role": "A"})
        dumped = []
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_generation_envelope."
            "dump_failure_evidence",
            lambda *a_, **k: dumped.append(a_))
        aborted_written = []
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r16_namespaces."
            "write_r16_iteration_aborted",
            lambda reason: aborted_written.append(reason))
        # 前置检查全部通过(mock),让请求走到 acquire 边界——
        # 六要素/plan/attestation 检查在会话获取之前(B 的早期
        # 只读检查通过后,acquire 才因 A 持锁被拒;§6.2/§6.3)。
        import rl_curriculum.curriculum261_r16_final as f16

        monkeypatch.setattr(f16, "load_locked_plan_r16",
                            lambda: (dict(PLAN), "digest-1"))
        monkeypatch.setattr(f16, "_static_identity_checks_r16",
                            lambda *a_, **k: None)
        import rl_curriculum.curriculum261_r16_param_pack as pp

        monkeypatch.setattr(pp, "load_selected_pack",
                            lambda root: {"digest": "pack-1",
                                          "recall_floor": 0.95,
                                          "p_contract": 0.95})
        import rl_curriculum.curriculum261_r16_preflight as pf

        monkeypatch.setattr(
            pf, "verify_sealed_attestation",
            lambda out_dir: {"pass": True,
                             "attestation": {"plan_digest": "digest-1"}})

        from rl_curriculum.curriculum261_r16_cli import cmd_qualify
        import argparse

        args = argparse.Namespace(out_dir=str(tmp_path / "out"),
                                  rehearsal=False)
        with pytest.raises(eg.R16OwnershipError):
            cmd_qualify(args)
        assert not dumped
        assert not aborted_written
        assert "iteration_aborted" not in events()
        assert "exposure_started" not in events()
        a.release()
