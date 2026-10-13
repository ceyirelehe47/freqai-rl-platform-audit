# -*- coding: utf-8 -*-
"""R5-A 锁内重读完整核验任务头(FiniteRepair R5;reviewer BIND)。

反例源:_on_bind_record 已见头时只核 task_id/budget_face 即
return;_synced_op 重放不重建头验证事实——已打开对象的下一次
操作改小 single_caps/删 derived_totals/改派生组成/移除头、
追加同 task/total 但 single/derived 冲突的第二条头,均绕过
完整约束。R5:每次锁内重放从零重建并核完整任务约束;重复头
兼容政策 = 逐字段全等(幂等重发容忍,任何冲突拒绝)。

全部为记录型临时账本(RECORDING_ONLY),零真实资源;拒绝路径
断言无新的成功 reserve/draw/commit 事件落盘。
"""

from __future__ import annotations

import json

import pytest

from rl_posctl.budget import TaskLedger, open_task_ledger
from rl_posctl import versions as versions_mod

R3_TASK = versions_mod.POSCTL_R3_TASK_ID


def _mk(tmp_path, name="t.jsonl"):
    led = TaskLedger.create(tmp_path / name, R3_TASK)
    return led, tmp_path / name


def _header_of(path):
    lines = [ln for ln in path.read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    return json.loads(lines[0]), lines


def _rewrite_header(path, mutate):
    hdr, _ = _header_of(path)
    mutate(hdr)
    path.write_text(json.dumps(hdr, ensure_ascii=False) + "\n",
                    encoding="utf-8")


def _append_line(path, obj):
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, ensure_ascii=False) + "\n")


class TestInLockRereadRefusesHeaderDamage:
    """同一已打开对象:操作前头部被改/删 → 拒绝且零新事件。"""

    def test_live_single_caps_shrunk_refused_no_append(
            self, tmp_path):
        led, path = _mk(tmp_path)
        rid = led.reserve("base", ppo_steps=2, ppo_learn_attempts=1)
        led.commit(rid, "base", ppo_steps=2, ppo_learn_attempts=1)
        _rewrite_header(path, lambda h: h["single_caps"].update(
            ppo_steps=1))
        mutated = path.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError,
                           match="单次上限与代码不一致"):
            led.reserve("after", ppo_steps=2, ppo_learn_attempts=1)
        assert path.read_text(encoding="utf-8") == mutated

    def test_live_derived_totals_removed_refused_no_append(
            self, tmp_path):
        led, path = _mk(tmp_path)
        _rewrite_header(path, lambda h: h.pop("derived_totals"))
        mutated = path.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError, match="缺 derived_totals"):
            led.reserve("after", eval_steps=4)
        assert path.read_text(encoding="utf-8") == mutated

    def test_live_derived_composition_and_cap_refused(
            self, tmp_path):
        led, path = _mk(tmp_path)
        _rewrite_header(
            path, lambda h: h["derived_totals"][0].update(
                parts=["ppo_steps"], cap=10 ** 9))
        mutated = path.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError,
                           match="派生总项与代码不一致"):
            led.reserve("after", eval_steps=4)
        assert path.read_text(encoding="utf-8") == mutated

    def test_live_header_removed_refused_no_append(self, tmp_path):
        """整个头被移除:文件以 reserve 事件开头也不行。"""
        led, path = _mk(tmp_path)
        rid = led.reserve("base", eval_steps=2)
        led.commit(rid, "base", eval_steps=2)
        rest = [ln for ln in
                path.read_text(encoding="utf-8").splitlines()[1:]
                if ln.strip()]
        path.write_text("\n".join(rest) + "\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="锁内重放未见合法"):
            led.reserve("after", eval_steps=4)
        # 未新增任何成功事件(仍只有原 reserve+commit 两行)
        assert len([ln for ln in
                    path.read_text(encoding="utf-8").splitlines()
                    if ln.strip()]) == 2

    def test_restored_header_positive_recovers(self, tmp_path):
        """恢复合法夹具后正例成立(不是恒拒)。"""
        led, path = _mk(tmp_path)
        original = path.read_text(encoding="utf-8")
        _rewrite_header(path, lambda h: h["single_caps"].update(
            ppo_steps=1))
        with pytest.raises(RuntimeError):
            led.reserve("bad", ppo_steps=2, ppo_learn_attempts=1)
        path.write_text(original, encoding="utf-8")
        rid = led.reserve("ok", ppo_steps=2, ppo_learn_attempts=1)
        led.commit(rid, "ok", ppo_steps=2, ppo_learn_attempts=1)
        assert led.effective()["ppo_steps"] == 2


class TestConflictingSecondHeader:
    """合法第一头 + 冲突第二头:打开与锁内重放均拒绝。"""

    def test_second_single_conflict_refused_on_open_and_replay(
            self, tmp_path):
        led, path = _mk(tmp_path)
        hdr, _ = _header_of(path)
        bad = json.loads(json.dumps(hdr))
        bad["single_caps"]["ppo_steps"] = 1
        _append_line(path, bad)
        with pytest.raises(RuntimeError,
                           match="不一致 task_bind"):
            TaskLedger(path, R3_TASK)
        # 已打开对象(头追加前打开)的锁内重放同样拒绝
        with pytest.raises(RuntimeError,
                           match="不一致 task_bind"):
            led.reserve("replay", ppo_steps=2, ppo_learn_attempts=1)

    def test_second_derived_conflict_refused(self, tmp_path):
        led, path = _mk(tmp_path)
        hdr, _ = _header_of(path)
        bad = json.loads(json.dumps(hdr))
        bad["derived_totals"][0]["cap"] = 1
        _append_line(path, bad)
        with pytest.raises(RuntimeError,
                           match="不一致 task_bind"):
            open_task_ledger(path)
        with pytest.raises(RuntimeError,
                           match="不一致 task_bind"):
            led.reserve("replay", eval_steps=4)

    def test_identical_duplicate_header_tolerated(self, tmp_path):
        """兼容政策:与首头逐字段全等的重复头 = 幂等重发,可开可用。"""
        led, path = _mk(tmp_path)
        hdr, _ = _header_of(path)
        _append_line(path, hdr)
        led2 = open_task_ledger(path)
        rid = led2.reserve("dup_ok", eval_steps=4)
        led2.commit(rid, "dup_ok", eval_steps=4)
        assert led2.effective()["eval_steps"] == 4


class TestLegitimateFlowUnchanged:
    """合法路径/既有正确行为不因锁内重读受损。"""

    def test_long_lived_object_multi_op_and_reopen_consistent(
            self, tmp_path):
        led, path = _mk(tmp_path)
        rid = led.reserve("a", ppo_steps=2, ppo_learn_attempts=1)
        led.draw(rid, "a", ppo_steps=1)
        led.commit(rid, "a", ppo_steps=2, ppo_learn_attempts=1)
        rid2 = led.reserve("b", eval_steps=4)
        led.commit(rid2, "b", eval_steps=4)
        reopened = open_task_ledger(path)
        assert reopened.effective() == led.effective()
        assert reopened.snapshot()[
            "budget_face_matches_code"] is True

    def test_duplicate_settlement_still_once_only(self, tmp_path):
        led, path = _mk(tmp_path)
        rid = led.reserve("a", eval_steps=4)
        led.commit(rid, "a", eval_steps=4)
        with pytest.raises(RuntimeError):
            led.commit(rid, "again", eval_steps=4)
        assert led.effective()["eval_steps"] == 4

    def test_registry_caps_still_enforced_after_fix(self, tmp_path):
        """头部未动时单次上限照常生效(不是靠恒拒过负例)。"""
        led, _ = _mk(tmp_path)
        with pytest.raises(Exception, match="单次"):
            led.reserve("over", ppo_steps=65)
