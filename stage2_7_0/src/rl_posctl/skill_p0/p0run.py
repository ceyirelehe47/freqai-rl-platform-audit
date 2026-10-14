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


class CheckpointLifecycle:
    """P0 训练检查点保存生命周期(R1/F1:采集→更新→保存次序)。

    旧缺陷:_on_step 在采集到门槛步数时立即写盘(该 rollout 的
    优化尚未发生)→ ck32768/65536/131072 实为 pre-update 状态;
    learn 返回后又因同名文件存在跳过真正最终保存。修复后的次序:

    - record_collect():采集期只登记越过的目标步(不写盘);
    - after_train():每次 train() **正常返回后**把已越过且
      target < total_steps 的目标保存为 mid(post-update,绑定
      当时真实 optimizer 步数);
    - finalize():learn 正常返回后唯一 final 保存(target=实际
      步数;同名已存在显式拒绝,绝不静默跳过/覆盖);
    - train 抛异常/经济失败 → 调用方不调 finalize,已有 mid
      原件保留(真实阶段),不伪造 final。

    saver 注入点供纯计数测试(假模型/假优化器)复用同一控制流;
    真实 saver = save_p0_model_staged(带权重/optimizer 摘要绑定)。
    """

    def __init__(self, out_dir, checkpoints, total_steps: int,
                 run_name: str, saver=None) -> None:
        self.out_dir = Path(out_dir)
        self.total_steps = int(total_steps)
        self.run_name = str(run_name)
        self._saver = saver
        self._pending = sorted(
            int(c) for c in checkpoints
            if 0 < int(c) < self.total_steps)
        self._crossed: list[int] = []
        self.saved: list[dict] = []
        self.finalized = False

    def _save(self, *, stage: str, target: int, num_timesteps: int,
              optimizer_steps: int) -> dict:
        path = self.out_dir / f"ck{int(target)}.zip"
        if self._saver is not None:
            rec = dict(self._saver(
                stage=stage, path=path, target_step=int(target),
                num_timesteps=int(num_timesteps),
                optimizer_steps=int(optimizer_steps)) or {})
        else:
            from rl_posctl.skill_p0.p0policy import (
                save_p0_model_staged)
            rec = dict(save_p0_model_staged(
                _LIFECYCLE_MODEL_HOLDER["model"], path,
                stage=stage, target_step=int(target),
                optimizer_steps=int(optimizer_steps),
                run_name=self.run_name))
        rec.update({"num_timesteps": int(num_timesteps),
                    "optimizer_steps": int(optimizer_steps),
                    "event": "checkpoint", "stage": stage,
                    "target": int(target), "ts": time.time()})
        self.saved.append(rec)
        return rec

    def record_collect(self, num_timesteps: int) -> None:
        """采集期(回调 _on_step):只登记,不写盘。"""
        while self._pending and int(num_timesteps) >= (
                self._pending[0]):
            self._crossed.append(self._pending.pop(0))

    def after_train(self, num_timesteps: int,
                    optimizer_steps: int) -> list[dict]:
        """train() 正常返回后:保存所有已越过目标的 post-update 档。"""
        out = []
        while self._crossed:
            target = self._crossed.pop(0)
            out.append(self._save(
                stage="mid", target=target,
                num_timesteps=num_timesteps,
                optimizer_steps=optimizer_steps))
        return out

    def finalize(self, num_timesteps: int,
                 optimizer_steps: int) -> dict:
        """learn 正常返回后的唯一 final 保存(存在即拒绝)。"""
        if self.finalized:
            raise RuntimeError("final 已保存,拒绝重复 finalize")
        if self._crossed:
            raise RuntimeError(
                f"仍有未 flush 的采集目标 {self._crossed}:"
                "final 保存前必须完成对应更新或显式放弃")
        rec = self._save(stage="final", target=num_timesteps,
                         num_timesteps=num_timesteps,
                         optimizer_steps=optimizer_steps)
        self.finalized = True
        return rec


# 真实 saver 需要活动 model 引用(测试替身不走此路径)。
_LIFECYCLE_MODEL_HOLDER: dict = {"model": None}


def bind_lifecycle_model(model) -> None:
    """登记 CheckpointLifecycle 默认 saver 使用的活动模型。"""
    _LIFECYCLE_MODEL_HOLDER["model"] = model


class P0LearnGate:
    """P0 训练门(镜像 tests conftest._LearnGate;P0 计量键 +
    optimizer.step 实计)。kind ∈ main/smoke/techretry/engsmoke。"""

    STEP_KEY = {"main": "ppo_steps_main", "smoke": "ppo_steps_smoke",
                "techretry": "ppo_steps_techretry",
                "engsmoke": "ppo_steps_smoke"}
    ATT_KEY = {"main": "ppo_learn_main_attempts",
               "smoke": "ppo_learn_smoke_attempts",
               "techretry": "ppo_learn_techretry_attempts",
               "engsmoke": "ppo_learn_smoke_attempts"}

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
