# -*- coding: utf-8 -*-
"""R14 §八:exposure 终态后禁止重生成 final corpus(负测试)。

exposure marker 存在(terminal)后,任何试图使用 qualification_r14
或其 final subordinate namespace 重新生成语料的调用必须 fail closed。
"""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from rl_curriculum import curriculum261_api as api
from rl_curriculum.curriculum261_r14_namespaces import (
    CURRICULUM261_ITERATION_ID_R14,
    R14_EXPOSURE_LEDGER_NAME,
    R14_EXPOSURE_MARKER_NAME,
    qualification_r14_lock_dir,
    qualification_r14_terminal_exposed,
    write_qualification_r14_exposure,
)


@pytest.fixture()
def r14_lock(tmp_path, monkeypatch):
    lock = tmp_path / "lock"
    lock.mkdir()
    monkeypatch.setenv("CURRICULUM261_R14_LOCK_DIR", str(lock))
    return lock


@pytest.fixture()
def unlocked(monkeypatch):
    """六要素解锁视为满足(隔离 exposure 守卫的独立测试)。"""
    monkeypatch.setattr(
        "rl_curriculum.curriculum261_r14_namespaces"
        ".qualification_r14_unlocked",
        lambda: True)
    return True


QUALIFICATION_NAMESPACES = (
    "qualification_r14",
    "preprocess_fit_qualification_r14",
    "c2_independent_qualification_r14",
    "cue_semantic_qualification_r14",
)


class TestTerminalExposureBlocksGeneration:
    @pytest.mark.parametrize("namespace", QUALIFICATION_NAMESPACES)
    def test_terminal_marker_blocks_all_qualification_namespaces(
            self, r14_lock, unlocked, namespace):
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "failed")
        assert qualification_r14_terminal_exposed() is True
        with pytest.raises(api.GeneratorError,
                           match="终态暴露"):
            api.derive261_seed(namespace, "c3_cost", "D0", 0, 0)

    def test_completed_is_also_terminal(self, r14_lock, unlocked):
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "completed")
        with pytest.raises(api.GeneratorError, match="终态暴露"):
            api.derive261_seed("qualification_r14", "c1_opportunity",
                               "D1", 0, 0)

    def test_crashed_is_also_terminal(self, r14_lock, unlocked):
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "crashed")
        with pytest.raises(api.GeneratorError, match="终态暴露"):
            api.derive261_seed("qualification_r14", "c1_opportunity",
                               "D1", 0, 0)

    def test_running_window_does_not_block(self, r14_lock, unlocked):
        """running 是正式一次性执行窗口(write running -> corpus
        生成 -> terminal);不得被守卫误杀。"""
        write_qualification_r14_exposure("r14qp-test", "running")
        assert qualification_r14_terminal_exposed() is False
        seed = api.derive261_seed(
            "qualification_r14", "c1_opportunity", "D1", 0, 0)
        assert isinstance(seed, int)

    def test_marker_deleted_but_ledger_terminal_still_blocks(
            self, r14_lock, unlocked):
        """删除 marker 不得绕过:append-only ledger 的终态事件同样
        判定已暴露。"""
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "failed")
        marker = r14_lock / R14_EXPOSURE_MARKER_NAME
        assert marker.is_file()
        marker.unlink()
        assert qualification_r14_terminal_exposed() is True
        with pytest.raises(api.GeneratorError, match="终态暴露"):
            api.derive261_seed("qualification_r14", "c3_cost", "D2", 1,
                               0)

    def test_non_qualification_namespaces_unaffected(
            self, r14_lock, unlocked):
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "failed")
        # calibration/stress 等 namespace 不受 exposure 影响
        seed = api.derive261_seed(
            "stress_r14", "c3_cost", "D0", 0, 0)
        assert isinstance(seed, int)
        seed2 = api.derive261_seed(
            "calibration_r14", "c1_opportunity", "D1", 0, 0)
        assert isinstance(seed2, int)

    def test_locked_state_blocks_before_exposure_check(
            self, r14_lock, monkeypatch):
        """六要素未解锁时,qualification namespace 在 lock 检查处即被
        拒(exposure 检查顺序在其后;两者都是 fail closed)。"""
        monkeypatch.setattr(
            "rl_curriculum.curriculum261_r14_namespaces"
            ".qualification_r14_unlocked",
            lambda: False)
        with pytest.raises(api.GeneratorError, match="完整锁定"):
            api.derive261_seed("qualification_r14", "c3_cost", "D3", 0,
                               0)


class TestExposureErrorContract:
    def test_error_mentions_r15_and_no_regeneration(
            self, r14_lock, unlocked):
        write_qualification_r14_exposure("r14qp-test", "running")
        write_qualification_r14_exposure("r14qp-test", "failed")
        with pytest.raises(api.GeneratorError) as excinfo:
            api.derive261_seed("cue_semantic_qualification_r14",
                               "c2_context", "D1", 0, 0)
        msg = str(excinfo.value)
        assert "R15" in msg
        assert "不得再次生成" in msg
