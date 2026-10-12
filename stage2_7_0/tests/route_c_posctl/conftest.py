# -*- coding: utf-8 -*-
"""R2/R3 测试预算门禁(FiniteRepair R2→R3)。

- 任务共享账本路径 = 环境变量 POSCTL_R3_LEDGER(优先)或
  POSCTL_R2_LEDGER(由任务身份显式创建;未设置时消费资源的环境
  交互/生成测试**跳过**并显式说明——fail closed,不隐式免计、
  不自动开新账本)。账本按**头部 task_bind 的任务身份**打开
  (face 与代码注册表核对;R2/R3 面均可承载)。
- 全量套件的**整体预约与执行中硬限**由 runner/posctl_r2_suite.py
  在 pytest 前先做(先校验、预占任务共享额度,再设置
  env/curriculum 进程内上限);本 conftest 只提供:
  * r2_task_ledger 会话 fixture(打开绑定账本);
  * r2_learn 单测内 learn 的精确 PPO 计量(预约→执行→实结;登记
    会话注册表供套件 wrapper 区分 PPO 步与无梯度步,避免双计)。
    R3-01/F1-c:learn 前**事前**计算 rollout 向上取整上界
    (rollout_upper_bound)并按上界预约——上界超单次上限 = 预约
    拒绝,learn 根本不被调用;执行中回调对超上界的 rollout 截停;
    ppo 步按豁免记账,不挤占套件 eval 硬限。
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
    for var in ("POSCTL_R4_LEDGER", "POSCTL_R3_LEDGER",
                "POSCTL_R2_LEDGER"):
        p = os.environ.get(var, "").strip()
        if p:
            return Path(p)
    return None


def ppo_registry_path() -> Path | None:
    lp = _ledger_path()
    if lp is None:
        return None
    return lp.parent / "suite_ppo_registry.jsonl"


def _header_task_id(path: Path) -> str | None:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            s = line.strip()
            if not s:
                continue
            rec = json.loads(s)
            return rec.get("task_id") if rec.get(
                "event") == "task_bind" else None
    return None


class _LearnGate:
    """单测内真实 learn 的预算门(先预约后执行;实结+注册)。

    R3:预约量 = rollout 向上取整**事前**上界(不是用户请求步数);
    learn 的 env 步记 ppo 不记 eval,且按上界豁免进程内 eval 硬限;
    实结后豁免校正到实际步。

    R4-A3(B2):执行中防护从"每次 step 之后的 callback"升级到
    **env.step 咽喉点**——learn 进入时把进程内 ENV_STEP_LIMIT 设为
    进入时的 eval 用量(learn 步全部按 ppo 豁免计入),第 ub+1 步在
    经济转移之前被 check_step_budget 拒绝(旧:第三步已完成才在
    callback 发现;失败 abandon 只记 2 而豁免已到 3,丢失已观察
    工作)。异常路径:abandon 未划拨余额之外,若已观察步数超出
    预约上界(框架吞掉咽喉异常等罕见路径),超界部分按事故补记
    保全实测——不扩约追认、不把低于实测的数当保守余额。
    """

    def __init__(self, ledger) -> None:
        self.ledger = ledger
        self.session_ppo_steps = 0
        self.session_learn_attempts = 0

    def learn(self, model, total_timesteps: int, callback=None):
        """预约(上界)→learn(咽喉硬限)→实结;实耗 ≤ 预约。"""
        import rl_posctl.env as _envmod
        from rl_posctl.policy import rollout_upper_bound
        # F1-c 修复核心:几何上界在 learn 之前;无可信几何 → 拒学
        ub = rollout_upper_bound(model, int(total_timesteps))
        rid = self.ledger.reserve(
            "pytest_learn", ppo_learn_attempts=1,
            ppo_steps=int(ub))
        before = int(_envmod.ENV_STEP_COUNT)
        # R4-A3:learn 步只受 ppo 上界约束——先冻结 eval 基线用量,
        # 再授豁免(顺序关键:限额基于授豁免**前**的用量,否则算出
        # 负限额会把首步也拒掉);learn 步经豁免通过,第 ub+1 步在
        # env.step 咽喉被拒。
        prev_limit = _envmod.ENV_STEP_LIMIT
        _envmod.ENV_STEP_LIMIT = (
            int(_envmod.ENV_STEP_COUNT)
            - int(_envmod.PPO_EXEMPT_STEPS))
        _envmod.grant_ppo_exempt(int(ub))

        def _guard(local_vars, global_vars):
            # 回调守卫保留(不经过 env.step 的计数路径兜底);
            # 主防线是 env.step 咽喉的 check_step_budget。
            used = int(_envmod.ENV_STEP_COUNT) - before
            if used > int(ub):
                from rl_posctl.budget import BudgetExceeded
                raise BudgetExceeded(
                    "learn 执行中超上界:实步 "
                    f"{used} > 预约上界 {ub}(截停,不事后扩约)")
            if callback is not None:
                return bool(callback(local_vars, global_vars))
            # SB3 函数回调语义:False=中止训练;继续须显式 True
            return True

        actual_raw = 0
        try:
            model.learn(total_timesteps=int(total_timesteps),
                        callback=_guard)
        except BaseException as exc:
            actual_raw = int(_envmod.ENV_STEP_COUNT) - before
            self.ledger.abandon(
                rid, "pytest_learn",
                note=("learn 异常中断,保守保留余额;"
                      f"observed_steps={actual_raw},"
                      f"reserved_ub={int(ub)},exc={exc!r}"))
            if actual_raw > int(ub):
                # 已发生超出预约的实测工作:事故补记保全(只增不减;
                # 不是扩约授权,后续预约对超限 fail closed)
                self.ledger.incident_backcharge(
                    "pytest_learn_overrun_observed",
                    note=("learn 异常路径下已观察步数超预约上界"
                          f"({actual_raw}>{int(ub)});实测保全,"
                          "不扩约追认"),
                    ppo_steps=int(actual_raw - ub),
                    ppo_learn_attempts=0)
            raise
        finally:
            if actual_raw == 0:
                actual_raw = int(_envmod.ENV_STEP_COUNT) - before
            # 豁免校正到实际观察;恢复 learn 前的进程内限额
            _envmod.grant_ppo_exempt(int(actual_raw) - int(ub))
            _envmod.ENV_STEP_LIMIT = prev_limit
        if actual_raw > int(ub):
            # 吞掉守卫/咽喉异常的框架路径:已观察工作超预约——
            # 不结清(不得把超预约量写成成功结清),余额保守保留 +
            # 超界部分事故补记保全实测(不扩约追认)。
            self.ledger.abandon(
                rid, "pytest_learn",
                note=("learn 已观察步数超预约上界"
                      f"({actual_raw}>{int(ub)});实测保全,不结清"))
            self.ledger.incident_backcharge(
                "pytest_learn_overrun_observed",
                note=("learn 观察步数超预约上界"
                      f"({actual_raw}>{int(ub)});实测保全,"
                      "不扩约追认"),
                ppo_steps=int(actual_raw - ub),
                ppo_learn_attempts=0)
            from rl_posctl.budget import BudgetExceeded as _BE
            raise _BE(
                "learn 实际步数超预约上界:"
                f"{actual_raw} > {int(ub)}(实测已保全,不结清)")
        self.ledger.commit(
            rid, "pytest_learn", ppo_learn_attempts=1,
            ppo_steps=int(actual_raw))
        self.session_ppo_steps += int(actual_raw)
        self.session_learn_attempts += 1
        reg = ppo_registry_path()
        if reg is not None:
            with reg.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps({
                    "run_id": _RUN_ID, "ppo_steps": int(actual_raw),
                    "learn_attempts": 1,
                    "rollout_upper_bound": int(ub),
                    "ts": time.time()},
                    ensure_ascii=False) + "\n")
        return int(actual_raw)


@pytest.fixture(scope="session")
def r2_task_ledger():
    path = _ledger_path()
    if path is None or not path.exists():
        pytest.skip(
            "POSCTL_R3_LEDGER/POSCTL_R2_LEDGER 未设置或账本不存在:"
            "环境交互/生成测试必须经任务共享账本先预约后执行"
            "(fail closed);由 runner/posctl_r{2,3}_task_ledger.py "
            "--init 显式创建后重跑",
            allow_module_level=False)
    from rl_posctl.budget import TaskLedger
    tid = _header_task_id(path)
    if tid is None:
        pytest.skip(
            f"账本无 task_bind 首行(拒绝续用旧式账本):{path}")
    return TaskLedger(path, tid)


@pytest.fixture()
def r2_learn(r2_task_ledger):
    """真实 learn 的单测用门(消耗 ppo 预算,不隐式免计)。"""
    return _LearnGate(r2_task_ledger)
