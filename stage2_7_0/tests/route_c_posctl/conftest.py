# -*- coding: utf-8 -*-
"""R2 测试预算门禁(FiniteRepair R2 / FINDINGS R2-01)。

- 任务共享账本路径 = 环境变量 POSCTL_R2_LEDGER(由 R2 任务身份显式
  创建;未设置时消费资源的环境交互/生成测试**跳过**并显式说明——
  fail closed,不隐式免计、不自动开新账本)。
- 全量套件的**整体预约**由 runner/posctl_r2_suite.py 在 pytest 前
  先做(先校验和预占任务共享额度,再执行);本 conftest 只提供:
  * r2_task_ledger 会话 fixture(打开绑定账本);
  * r2_learn 单测内 learn 的精确 PPO 计量(预约→执行→实结;登记
    会话注册表供套件 wrapper 区分 PPO 步与无梯度步,避免双计)。
- 纯数学/账本对拍测试不消费 env.step/generate,不需要本 fixture。
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import pytest

_RUN_ID = time.strftime("%Y%m%dT%H%M%S") + "_" + uuid.uuid4().hex[:8]


def _ledger_path() -> Path | None:
    p = os.environ.get("POSCTL_R2_LEDGER", "").strip()
    return Path(p) if p else None


def ppo_registry_path() -> Path | None:
    lp = _ledger_path()
    if lp is None:
        return None
    return lp.parent / "suite_ppo_registry.jsonl"


class _LearnGate:
    """单测内真实 learn 的预算门(先预约后执行;实结+注册)。"""

    def __init__(self, ledger) -> None:
        self.ledger = ledger
        self.session_ppo_steps = 0
        self.session_learn_attempts = 0

    def learn(self, model, total_timesteps: int, callback=None):
        """预约→learn→实结;learn 的 env 步记 ppo 不记 eval。"""
        import rl_posctl.env as _envmod
        rid = self.ledger.reserve(
            "pytest_learn", ppo_learn_attempts=1,
            ppo_steps=int(total_timesteps))
        before = int(_envmod.ENV_STEP_COUNT)
        try:
            model.learn(total_timesteps=int(total_timesteps),
                        callback=callback)
        except BaseException:
            self.ledger.abandon(
                rid, "pytest_learn",
                note="learn 异常中断,保守保留预约")
            raise
        actual = int(_envmod.ENV_STEP_COUNT) - before
        self.ledger.commit(
            rid, "pytest_learn", ppo_learn_attempts=1,
            ppo_steps=actual)
        self.session_ppo_steps += actual
        self.session_learn_attempts += 1
        reg = ppo_registry_path()
        if reg is not None:
            with reg.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "run_id": _RUN_ID, "ppo_steps": actual,
                    "learn_attempts": 1,
                    "ts": time.time()},
                    ensure_ascii=False) + "\n")
        return actual


@pytest.fixture(scope="session")
def r2_task_ledger():
    path = _ledger_path()
    if path is None or not path.exists():
        pytest.skip(
            "POSCTL_R2_LEDGER 未设置或账本不存在:R2 环境交互/生成"
            "测试必须经任务共享账本先预约后执行(fail closed);由 "
            "runner/posctl_r2_task_ledger.py --init 显式创建后重跑",
            allow_module_level=False)
    from rl_posctl.budget import TaskLedger
    return TaskLedger(path, "PosCtl_R2_20261012")


@pytest.fixture()
def r2_learn(r2_task_ledger):
    """真实 learn 的单测用门(消耗 ppo 预算,不隐式免计)。"""
    return _LearnGate(r2_task_ledger)
