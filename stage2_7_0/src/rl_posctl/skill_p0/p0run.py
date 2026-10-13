# -*- coding: utf-8 -*-
"""PSC_P0_v1 runner 共享:账本入口、learn 门、计量器与 RunLog 辅助。"""

from __future__ import annotations

import json
import time
from pathlib import Path

from rl_posctl import env as _envmod
from rl_posctl.budget import TaskLedger, open_task_ledger
from rl_posctl.policy import rollout_upper_bound
from rl_posctl.skill_p0.p0spec import TASK_ID

ACCEPT_ROOT = Path("/mnt/f/trading/acceptance/PSC_P0_v1")
DEFAULT_LEDGER = ACCEPT_ROOT / "runs" / "psc_p0_v1_ledger.jsonl"
RUNS_DIR = ACCEPT_ROOT / "runs"


def open_ledger(path=None) -> TaskLedger:
    return open_task_ledger(Path(path) if path else DEFAULT_LEDGER)


def make_sampler_meter(ledger, tag: str):
    """dist_sample_actions 计量器(诊断采样;env 动作不在此计)。"""
    def meter(n: int) -> None:
        if n <= 0:
            return
        rid = ledger.reserve(f"sample:{tag}", dist_sample_actions=int(n))
        ledger.commit(rid, f"sample:{tag}", dist_sample_actions=int(n))
    return meter


def make_bootstrap_meter(ledger, tag: str):
    def meter(n: int) -> None:
        if n <= 0:
            return
        rid = ledger.reserve(f"bootstrap:{tag}",
                             bootstrap_draws=int(n))
        ledger.commit(rid, f"bootstrap:{tag}", bootstrap_draws=int(n))
    return meter


def _dir_kib(roots: list) -> int:
    total = 0
    for root in roots:
        p = Path(root)
        if not p.exists():
            continue
        for f in p.rglob("*"):
            if f.is_file():
                total += f.stat().st_size
    return (total + 1023) // 1024


def evidence_kib_settle(ledger, *, tag: str,
                        roots=None) -> dict:
    """evidence_kib 增量结算(runs/+evidence/ 树;只增不减)。"""
    roots = roots or [RUNS_DIR, ACCEPT_ROOT / "evidence"]
    now = _dir_kib(roots)
    snap = ledger.snapshot()
    recorded = int(snap["committed"].get("evidence_kib", 0)
                   + snap["outstanding"].get("evidence_kib", 0)
                   + snap.get("incident_backcharged", {}).get(
                       "evidence_kib", 0))
    delta = max(0, now - recorded)
    rec = {"tag": tag, "tree_kib": now, "recorded_kib": recorded,
           "delta_kib": delta}
    if delta > 0:
        rid = ledger.reserve(f"evidence:{tag}", evidence_kib=delta)
        ledger.commit(rid, f"evidence:{tag}", evidence_kib=delta)
    return rec


class P0LearnGate:
    """P0 训练门(镜像 tests conftest._LearnGate;P0 计量键 +
    optimizer.step 实计)。kind ∈ main/smoke/techretry。"""

    STEP_KEY = {"main": "ppo_steps_main", "smoke": "ppo_steps_smoke",
                "techretry": "ppo_steps_techretry"}
    ATT_KEY = {"main": "ppo_learn_main_attempts",
               "smoke": "ppo_learn_smoke_attempts",
               "techretry": "ppo_learn_techretry_attempts"}

    def __init__(self, ledger, kind: str = "main") -> None:
        if kind not in self.STEP_KEY:
            raise ValueError(f"未知 learn kind {kind!r}")
        self.ledger = ledger
        self.kind = kind

    def learn(self, model, total_timesteps: int,
              extra_callbacks=None, optimizer_box=None,
              opt_ub: int = 0):
        ub = rollout_upper_bound(model, int(total_timesteps))
        amounts = {self.STEP_KEY[self.kind]: int(ub),
                   self.ATT_KEY[self.kind]: 1}
        if opt_ub:
            amounts["ppo_optimizer_steps"] = int(opt_ub)
        rid = self.ledger.reserve(f"learn:{self.kind}", **amounts)
        tag = f"learn:{self.kind}"
        before = int(_envmod.ENV_STEP_COUNT)
        prev_limit = _envmod.ENV_STEP_LIMIT
        _envmod.ENV_STEP_LIMIT = (
            int(_envmod.ENV_STEP_COUNT)
            - int(_envmod.PPO_EXEMPT_STEPS))
        _envmod.grant_ppo_exempt(int(ub))

        from stable_baselines3.common.callbacks import BaseCallback

        class _GuardCb(BaseCallback):
            """回调守卫兜底(主防线=env.step 咽喉 check_step_budget)。"""

            def _on_step(self) -> bool:
                used = int(_envmod.ENV_STEP_COUNT) - before
                if used > int(ub):
                    from rl_posctl.budget import BudgetExceeded
                    raise BudgetExceeded(
                        "P0 learn 执行中超上界:实步 "
                        f"{used} > 预约上界 {ub}(截停,不事后扩约)")
                return True

        cbs = [_GuardCb()] + list(extra_callbacks or [])
        actual_raw = 0
        try:
            model.learn(total_timesteps=int(total_timesteps),
                        callback=cbs)
        except BaseException as exc:
            actual_raw = int(_envmod.ENV_STEP_COUNT) - before
            self.ledger.abandon(rid, tag, note=(
                "P0 learn 异常中断,保守保留余额;observed_steps="
                f"{actual_raw},reserved_ub={int(ub)},exc={exc!r}"))
            if actual_raw > int(ub):
                self.ledger.incident_backcharge(
                    "psc_p0_learn_overrun_observed",
                    note="P0 learn 异常路径已观察步数超预约上界;"
                         f"{actual_raw}>{int(ub)};实测保全,不扩约",
                    **{self.STEP_KEY[self.kind]:
                       int(actual_raw - ub)})
            raise
        finally:
            if actual_raw == 0:
                actual_raw = int(_envmod.ENV_STEP_COUNT) - before
            _envmod.grant_ppo_exempt(int(actual_raw) - int(ub))
            _envmod.ENV_STEP_LIMIT = prev_limit
        if actual_raw > int(ub):
            self.ledger.abandon(
                rid, tag, note=(
                    f"P0 learn 观察步数超预约上界({actual_raw}>"
                    f"{int(ub)});实测保全,不结清"))
            self.ledger.incident_backcharge(
                "psc_p0_learn_overrun_observed",
                note="P0 learn 观察步数超预约上界;实测保全",
                **{self.STEP_KEY[self.kind]:
                   int(actual_raw - ub)})
            from rl_posctl.budget import BudgetExceeded
            raise BudgetExceeded("P0 learn 实际步数超预约上界")
        actuals = {self.STEP_KEY[self.kind]: int(actual_raw),
                   self.ATT_KEY[self.kind]: 1}
        if opt_ub:
            actuals["ppo_optimizer_steps"] = int(
                optimizer_box["n"]) if optimizer_box else 0
        self.ledger.commit(rid, tag, **actuals)
        return {"actual_steps": int(actual_raw), "reserved_ub": int(ub),
                "optimizer_steps": (
                    int(optimizer_box["n"]) if optimizer_box else None),
                "ts": time.time()}


def write_json_create(path, obj) -> None:
    p = Path(path)
    if p.exists():
        raise RuntimeError(f"文件已存在,拒绝覆盖(create-only):{p}")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1),
                 encoding="utf-8")
