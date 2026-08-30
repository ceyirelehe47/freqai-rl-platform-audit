"""工作包 C4/E9:线程生命周期(真实生产路径)。

- 正式 profile 禁止一切线程(clone 全拒):Builder 创建线程 ->
  RuntimeError/OSERR(创建即拒绝);
- Builder 吞掉异常继续返回 pack:quiesce 外部实测任务数恰为 1
  (线程从未存在,静止证明成立);
- 线程在证据阶段存活不可达:clone 被拒后不存在可存活线程;
  锁/EDIC 绑定 thread_policy=threads_forbidden_clone_denied 与
  quiesce 任务数。
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.stage2_6_0i


def test_thread_creation_denied(run_attack):
    """E9:threading.Thread().start() -> clone EPERM -> 构建失败。"""
    outcome = run_attack(
        "    import threading\n"
        "    t = threading.Thread(target=lambda: None)\n"
        "    t.start()\n",
        label="thread-create", max_attempts=1)
    assert not isinstance(outcome, dict), "线程创建未被拒绝"
    name, msg = outcome
    assert name in ("BuilderRunnerError", "BuilderProvenanceError"), outcome


def test_thread_error_swallowed_still_quiescent(run_attack):
    """E9:Builder 捕获线程创建异常仍返回 pack —— 线程从未创建,
  quiesce 实测恰 1 任务,pack 可采信(无存活线程即无 E9 威胁)。"""
    run = run_attack(
        "    try:\n"
        "        t = threading.Thread(target=lambda: None)\n"
        "        t.start()\n"
        "    except (RuntimeError, OSError):\n"
        "        pass\n"
        "    notes = {'threads_denied': True}\n",
        label="thread-swallow", max_attempts=1,
        top_imports="import threading\n")
    assert isinstance(run, dict), run
    edic = run["deterministic_input_report"]
    assert edic["thread_policy"] == "threads_forbidden_clone_denied"
    assert edic["supervisor"]["thread_count"] == 1
    assert edic["probes"]["clone_thread_denied"]["result"] == "ERRNO1"
    lock = run["runtime_lock"]
    assert lock["thread_policy"] == "threads_forbidden_clone_denied"
    assert lock["thread_state"]["thread_count_at_quiesce"] == 1


def test_background_import_thread_impossible(run_attack):
    """E9 场景变体:试图以线程在返回后 import 新模块——线程创建
    本身被拒,构建以线程创建异常失败(不允许'返回后线程继续活动'
    的任何路径)。"""
    outcome = run_attack(
        "    import threading, json\n"
        "    def bg():\n"
        "        import hashlib\n"
        "        json.dumps({'x': 1})\n"
        "    t = threading.Thread(target=bg, daemon=True)\n"
        "    t.start()\n"
        "    t.join(timeout=0)\n",
        label="thread-bg-import", max_attempts=1)
    assert not isinstance(outcome, dict), outcome
