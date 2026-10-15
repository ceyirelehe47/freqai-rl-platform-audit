# -*- coding: utf-8 -*-
"""P0 统一续训入口(rev2,审阅 NO-GO 修正版,2026-10-15)。

直接复用已验收 v5 语义(不简化替代):真实 bank tuple、真实六元组
grid、真实 numpy 分布分量、v5 保存前断言、v5 逐 step 评估面。

执行序(固定;纯 plan 校验先于任何目录副作用):
  1. 纯 plan 结构校验(零副作用;畸形输入不创建任何目录)
  2. 冻结预算核对(train_steps==append;optimizer==rollout 几何;
     超参对照 p0spec 冻结常数——plan 不能自己声明自己过;
     PPO_EXEMPT_STEPS==0)
  3. 前序课程毕业门;非 c1 课程仅登记(不触原件不加载)
  4. 原件 SHA(checkpoint/bank)+ bank 列序(item[1].columns)
     + 源码 vs 来源候选 commit(blob 全等;入口自身 commit 分开
     记录)+ 实际 git HEAD
  5. 载入存档(仅 arm)+ header 核验(observation_spec/obs 维度/
     bank_ref 关联/base seed 可核则核)+ 实际步数/超参/32 点
     schedule 预验证(learn 前;失败=零训练步零优化器调用)
  6. registry intent(此后才可能有训练副作用)
  7. 训练(v5 optimizer 门)→ v5 保存前断言(零更新绝不 final)
     → 唯一 final 保存 → 前后摘要 → 原件复核
  8. 评估(独立预约 ENV_STEP_LIMIT;不沿用训练限额不豁免)
  9. settled 实结(失败→failed 实结,终态)

hooks 参数仅供纯假对象单测注入;缺省全部真实绑定(懒导入)。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from rl_posctl.curriculum import VALID_COURSES
from rl_posctl.skill_p0.p0registry import (
    CurriculumStatus, Registry, RegistryError, plan_digest,
    sha256_file, utc_now)

#: 首版可执行课程(其余仅登记)
EXECUTABLE_COURSES = ("c1",)

_COURSE_CHAIN = ("c1", "c2", "c3",
                 "c4d0", "c4d1", "c4d2", "c4d3")

RESUME_SEMANTICS = (
    "load+set_random_seed(new)+learn(reset_num_timesteps=False)")

#: v5 评估冻结口径(整段移植自已验收 eval_contrast.py)
EVAL_FROZEN = {"mode": "in_sample_contrast", "grids": 108,
               "episodes": 16, "steps": 1024,
               "predicts": 1024, "deterministic": True}
EP_CAP = 64
TOTAL_STEP_CAP = 1024
TOTAL_PREDICT_CAP = 1024
PAIRS = (0, 1, 2, 3)
VARIANTS = (0, 1)
OBS_SPEC = "PosctlObsP0Time-v1"
OBS_DIM = 8
FEE = 0.001
WINDOW_SIZE = 1

#: 源码核验面(全部 vs 来源候选 commit blob)
SOURCE_MODULES = (
    "src/rl_posctl/env.py",
    "src/rl_posctl/budget.py",
    "src/rl_posctl/experiments.py",
    "src/rl_posctl/curriculum.py",
    "src/rl_posctl/skill_p0/p0policy.py",
    "src/rl_posctl/skill_p0/p0banks.py",
    "src/rl_posctl/skill_p0/p0env.py",
    "src/rl_posctl/skill_p0/p0eval.py",
    "src/rl_posctl/skill_p0/p0spec.py",
    "src/rl_posctl/skill_p0/p0run.py",
)

_HYPERPARAM_FIELDS = ("n_steps", "batch_size", "n_epochs",
                      "gamma", "gae_lambda", "vf_coef",
                      "ent_coef", "max_grad_norm")

FAIL = {
    "plan": 10, "frozen_budget": 11, "prereq": 12, "sha": 13,
    "bank_order": 14, "sources": 15, "load": 16, "steps": 17,
    "hyperparams": 18, "schedule": 19, "intent": 20,
    "train": 21, "eval": 22, "settle": 23,
}


class PlanError(ValueError):
    """plan 结构/自洽性错误(阶段 1,零副作用)。"""


def validate_plan_pure(plan: dict) -> None:
    """阶段 1:纯结构校验。零文件系统副作用。"""
    if not isinstance(plan, dict):
        raise PlanError("plan must be a JSON object")
    for key in ("experiment_id_hint", "source", "steps",
                "random_stream", "course", "budget",
                "eval_scope", "evidence", "hyperparams_frozen",
                "schedules_frozen"):
        if key not in plan:
            raise PlanError(f"missing top key {key!r}")

    src = plan["source"]
    for key in ("checkpoint", "checkpoint_sha256", "run_name",
                "arm", "base_model_seed_in_zip",
                "git_head_pinned", "repo"):
        if key not in src:
            raise PlanError(f"missing source.{key}")
    if not (isinstance(src["checkpoint_sha256"], str)
            and len(src["checkpoint_sha256"]) == 64):
        raise PlanError("source.checkpoint_sha256 not sha256")
    if not isinstance(src["base_model_seed_in_zip"], int):
        raise PlanError("source.base_model_seed_in_zip not int")

    steps = plan["steps"]
    if not (isinstance(steps.get("append_steps"), int)
            and steps["append_steps"] > 0):
        raise PlanError("steps.append_steps must be int>0")
    if not (isinstance(steps.get("cumulative_end"), int)
            and steps["cumulative_end"]
            > steps["append_steps"]):
        raise PlanError(
            "steps.cumulative_end must be int > append_steps")

    rs = plan["random_stream"]
    if not isinstance(rs.get("new_seed"), int):
        raise PlanError("random_stream.new_seed must be int")
    if rs.get("resume_semantics") != RESUME_SEMANTICS:
        raise PlanError(
            "random_stream.resume_semantics must equal the "
            "fixed continuation literal")

    course = plan["course"]
    name = course.get("course")
    if name not in VALID_COURSES:
        raise PlanError(f"unknown course {name!r}")
    if name != name.lower():
        raise PlanError(
            f"course must be lowercase, got {name!r}")
    for key in ("bank_path", "bank_sha256", "feature_names"):
        if key not in course:
            raise PlanError(f"missing course.{key}")
    fn = course["feature_names"]
    if (not isinstance(fn, list) or not fn
            or len(set(fn)) != len(fn)
            or not all(isinstance(x, str) for x in fn)):
        raise PlanError("course.feature_names must be a "
                        "non-empty unique str list")

    budget = plan["budget"]
    for key in ("train_steps", "optimizer_updates"):
        if not (isinstance(budget.get(key), int)
                and budget[key] > 0):
            raise PlanError(f"budget.{key} must be int>0")

    ev = plan["eval_scope"]
    for key, want in EVAL_FROZEN.items():
        if ev.get(key) != want:
            raise PlanError(
                f"eval_scope.{key} must equal frozen "
                f"{want!r} (got {ev.get(key)!r})")

    if not isinstance(plan["evidence"].get("root"), str):
        raise PlanError("evidence.root must be str")

    hp = plan["hyperparams_frozen"]
    if not isinstance(hp, dict) or set(hp) != set(
            _HYPERPARAM_FIELDS):
        raise PlanError(
            "hyperparams_frozen keys must equal "
            f"{_HYPERPARAM_FIELDS}")

    sf = plan["schedules_frozen"]
    if not (isinstance(sf, dict)
            and {"clip_range", "learning_rate",
                 "n_points"} <= set(sf)):
        raise PlanError(
            "schedules_frozen needs clip_range/learning_rate/"
            "n_points")


def check_frozen_budget(plan: dict, spec) -> None:
    """阶段 2:预算/超参对照冻结 p0spec(plan 不能自证)。"""
    append = plan["steps"]["append_steps"]
    n_steps = int(spec.N_STEPS)
    if plan["budget"]["train_steps"] != append:
        raise PlanError(
            "budget.train_steps %r != append_steps %r"
            % (plan["budget"]["train_steps"], append))
    if append % n_steps != 0:
        raise PlanError(
            "append %d not a multiple of N_STEPS %d"
            % (append, n_steps))
    want_opt = (append // n_steps) * int(
        spec.OPT_STEPS_PER_ROLLOUT)
    if plan["budget"]["optimizer_updates"] != want_opt:
        raise PlanError(
            "budget.optimizer_updates %r != rollout geometry "
            "%d ((%d/%d)*%d)"
            % (plan["budget"]["optimizer_updates"], want_opt,
               append, n_steps,
               int(spec.OPT_STEPS_PER_ROLLOUT)))
    frozen_hp = {
        "n_steps": int(spec.N_STEPS),
        "batch_size": int(spec.BATCH_SIZE),
        "n_epochs": int(spec.N_EPOCHS),
        "gamma": float(spec.GAMMA),
        "gae_lambda": float(spec.GAE_LAMBDA),
        "vf_coef": float(spec.VF_COEF),
        "ent_coef": float(spec.ENT_COEF),
        "max_grad_norm": float(spec.MAX_GRAD_NORM),
    }
    for k, v in frozen_hp.items():
        if plan["hyperparams_frozen"].get(k) != v:
            raise PlanError(
                "hyperparams_frozen.%s %r != p0spec frozen %r"
                % (k, plan["hyperparams_frozen"].get(k), v))
    if float(plan["schedules_frozen"]["learning_rate"]) != float(
            spec.LEARNING_RATE):
        raise PlanError("schedules_frozen.learning_rate != "
                        "p0spec LEARNING_RATE")
    if float(plan["schedules_frozen"]["clip_range"]) != float(
            spec.CLIP_RANGE):
        raise PlanError("schedules_frozen.clip_range != "
                        "p0spec CLIP_RANGE")
    if int(plan["schedules_frozen"]["n_points"]) != (
            append // n_steps):
        raise PlanError(
            "schedules_frozen.n_points != append/N_STEPS")


def prerequisites_of(course: str) -> tuple:
    idx = _COURSE_CHAIN.index(course)
    return _COURSE_CHAIN[:idx]


def check_prerequisites(plan: dict, status: CurriculumStatus,
                        arm: str) -> None:
    for pre in prerequisites_of(plan["course"]["course"]):
        if not status.graduated(arm, pre):
            raise RegistryError(
                f"prerequisite {pre!r} not GRADUATED for arm "
                f"{arm!r}; no auto promotion")


# ---- 真实绑定(懒导入;测试用 hooks 覆盖) ------------------------
def _real_load_model(plan):
    from rl_posctl.skill_p0.p0policy import (
        load_p0_model_archive)
    model, header = load_p0_model_archive(
        Path(plan["source"]["checkpoint"]),
        arm=plan["source"]["arm"])
    model.policy.set_training_mode(False)
    return model, header


def _real_bank_items(bank_path):
    from rl_posctl.skill_p0.p0banks import load_p0_bank
    return load_p0_bank(Path(bank_path))


def _real_verify_sources(plan) -> dict:
    """源码 vs 来源候选 commit blob 全等(Windows git.exe)。"""
    repo = plan["source"]["repo"]
    candidate = plan["source"]["git_head_pinned"]
    exe = shutil.which("git.exe") or shutil.which("git")
    if not exe:
        raise RuntimeError("git executable missing")
    out = {}
    for rel in SOURCE_MODULES:
        rel_repo = ("stage2_7_0/" + rel)
        lt = subprocess.run(
            [exe, "-C", repo, "ls-tree", candidate, "--",
             rel_repo], capture_output=True, text=True,
            timeout=120)
        if lt.returncode != 0:
            raise RuntimeError(
                "ls-tree rc=%d for %s" % (
                    lt.returncode, rel_repo))
        blob = (lt.stdout.split("\t")[0].split()[2]
                if len(lt.stdout.split()) >= 3 else None)
        ho = subprocess.run(
            [exe, "-C", repo, "hash-object", rel_repo],
            capture_output=True, text=True, timeout=120)
        if ho.returncode != 0:
            raise RuntimeError(
                "hash-object rc=%d for %s" % (
                    ho.returncode, rel_repo))
        ok = (blob is not None
              and ho.stdout.strip() == blob)
        out[rel] = {"candidate_blob": blob,
                    "worktree_sha": ho.stdout.strip(),
                    "match": ok}
        if not ok:
            raise RuntimeError(
                "source drifted vs candidate: %s" % rel)
    return out


def _real_git_head(plan) -> str:
    repo = plan["source"]["repo"]
    exe = shutil.which("git.exe") or shutil.which("git")
    r = subprocess.run(
        [exe, "-C", repo, "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError("rev-parse rc=%d" % r.returncode)
    return r.stdout.strip()


def _real_envmod():
    import rl_posctl.env as envmod
    return envmod


def _real_make_env(features, prices):
    from rl_posctl.skill_p0.p0env import P0FiniteTimeEnv
    return P0FiniteTimeEnv(
        features=features, prices=prices, fee=FEE,
        window_size=WINDOW_SIZE, funding_schedule={})


def _real_save_final(model, path, *, target_step,
                     optimizer_steps, run_name):
    from rl_posctl.skill_p0.p0policy import (
        save_p0_model_staged)
    return save_p0_model_staged(
        model, path, stage="final",
        target_step=int(target_step),
        optimizer_steps=int(optimizer_steps),
        run_name=str(run_name))


def _real_digests(model):
    from rl_posctl.skill_p0.p0policy import (
        policy_digest, optimizer_state_digest)
    return {"policy": policy_digest(model),
            "optimizer": optimizer_state_digest(model)}


def wrap_optimizer_gate(optimizer, cap: int) -> dict:
    """v5 门语义(已验收):attempts/successes/unknown + 上限
    前置拒绝。旧 P0LearnGate 不适用于续训(reset 语义/计数键
    "n" 历史口径),不使用。"""
    box = {"attempts": 0, "successes": 0, "unknown": False}
    orig = optimizer.step

    def _gated_step(*a, **k):
        if box["attempts"] + 1 > cap:
            from rl_posctl.budget import BudgetExceeded
            raise BudgetExceeded(
                "optimizer.step cap: attempt %d > %d"
                % (box["attempts"] + 1, cap))
        box["attempts"] += 1
        failed = False
        try:
            return orig(*a, **k)
        except BaseException:
            failed = True
            box["unknown"] = True
            raise
        finally:
            if not failed:
                box["successes"] += 1

    optimizer.step = _gated_step
    return box


def _default_hooks() -> dict:
    import rl_posctl.skill_p0.p0spec as spec
    return {
        "spec": spec,
        "load_model": _real_load_model,
        "bank_items": _real_bank_items,
        "verify_sources": _real_verify_sources,
        "git_head": _real_git_head,
        "envmod": _real_envmod,
        "make_env": _real_make_env,
        "save_final": _real_save_final,
        "digests": _real_digests,
        "eval": {},
    }


# ---- 主流程 -----------------------------------------------------
def run_continuation(plan_path, registry_root, *, hooks=None,
                     status=None) -> int:
    """执行固定九阶段序;返回进程退出码(0=成功)。"""
    plan = json.loads(Path(plan_path).read_text(
        encoding="utf-8"))
    hooks = dict(_default_hooks(), **(hooks or {}))
    arm = plan["source"]["arm"]

    # -- 1. 纯 plan 校验(先于 Registry 创建/任何目录副作用) --
    try:
        validate_plan_pure(plan)
    except PlanError as exc:
        print(f"[stage1/plan] FAIL: {exc}", file=sys.stderr)
        return FAIL["plan"]

    # -- 2. 冻结预算/超参核对(对照 p0spec;不采信 plan 自声明) --
    try:
        check_frozen_budget(plan, hooks["spec"])
    except PlanError as exc:
        print(f"[stage2/frozen] FAIL: {exc}", file=sys.stderr)
        return FAIL["frozen_budget"]

    course = plan["course"]["course"]
    registry_only = course not in EXECUTABLE_COURSES
    status = status or CurriculumStatus(registry_root)

    # -- 3. 前序毕业门;非 c1 仅登记 -----------------------------
    try:
        check_prerequisites(plan, status, arm)
    except RegistryError as exc:
        print(f"[stage3/prereq] FAIL: {exc}", file=sys.stderr)
        return FAIL["prereq"]
    if registry_only:
        registry = Registry(registry_root)
        try:
            registry.register_intent(plan,
                                     mode="registry_only")
        except RegistryError as exc:
            print(f"[stage3/registry-only] FAIL: {exc}",
                  file=sys.stderr)
            return FAIL["intent"]
        print(f"[stage3] REGISTERED_ONLY course={course} "
              f"(not executable; no auto promotion)")
        return 0

    # -- 4. 原件 SHA + bank 列序 + 源码/HEAD ------------------
    ck_path = Path(plan["source"]["checkpoint"])
    bank_path = Path(plan["course"]["bank_path"])
    if sha256_file(ck_path) != plan["source"][
            "checkpoint_sha256"]:
        print("[stage4/sha] FAIL: checkpoint sha mismatch",
              file=sys.stderr)
        return FAIL["sha"]
    if sha256_file(bank_path) != plan["course"]["bank_sha256"]:
        print("[stage4/sha] FAIL: bank sha mismatch",
              file=sys.stderr)
        return FAIL["sha"]
    try:
        items = hooks["bank_items"](bank_path)
    except Exception as exc:
        print(f"[stage4/bank] FAIL: {exc}", file=sys.stderr)
        return FAIL["bank_order"]
    if not items:
        print("[stage4/bank] FAIL: empty bank", file=sys.stderr)
        return FAIL["bank_order"]
    bank_cols = [str(c) for c in items[0][1].columns]
    if bank_cols != list(plan["course"]["feature_names"]):
        print("[stage4/bank_order] FAIL: bank columns %r != "
              "plan %r" % (bank_cols,
                           plan["course"]["feature_names"]),
              file=sys.stderr)
        return FAIL["bank_order"]
    try:
        sources_check = hooks["verify_sources"](plan)
        head_actual = hooks["git_head"](plan)
    except Exception as exc:
        print(f"[stage4/sources] FAIL: {exc}", file=sys.stderr)
        return FAIL["sources"]

    # -- 5. 载入 + header 核验 + 步数/超参/schedule ----------
    try:
        model, header = hooks["load_model"](plan)
    except Exception as exc:
        print(f"[stage5/load] FAIL: {exc}", file=sys.stderr)
        return FAIL["load"]
    obs_shape = tuple(
        getattr(model.observation_space, "shape", ()) or ())
    if obs_shape != (OBS_DIM,):
        print("[stage5/header] FAIL: obs shape %r != (%d,)"
              % (obs_shape, OBS_DIM), file=sys.stderr)
        return FAIL["load"]
    if header.get("observation_spec") != OBS_SPEC:
        print("[stage5/header] FAIL: observation_spec %r != %r"
              % (header.get("observation_spec"), OBS_SPEC),
              file=sys.stderr)
        return FAIL["load"]
    if str(header.get("bank_ref")) != str(
            plan["course"]["bank_sha256"]):
        print("[stage5/header] FAIL: header bank_ref %r != "
              "plan bank sha (association broken)"
              % header.get("bank_ref"), file=sys.stderr)
        return FAIL["load"]
    if int(getattr(model, "num_timesteps", 0)) + plan["steps"][
            "append_steps"] != plan["steps"][
                "cumulative_end"]:
        print("[stage5/steps] FAIL: base %r + append %d != "
              "cumulative_end %d"
              % (getattr(model, "num_timesteps", 0),
                 plan["steps"]["append_steps"],
                 plan["steps"]["cumulative_end"]),
              file=sys.stderr)
        return FAIL["steps"]
    if int(getattr(model, "n_envs", 1)) != 1:
        print("[stage5/hyperparams] FAIL: n_envs != 1",
              file=sys.stderr)
        return FAIL["hyperparams"]
    hp_bad = {k: (v, getattr(model, k, None))
              for k, v in plan["hyperparams_frozen"].items()
              if getattr(model, k, None) != v}
    if hp_bad:
        print("[stage5/hyperparams] FAIL: %r" % hp_bad,
              file=sys.stderr)
        return FAIL["hyperparams"]

    spec = hooks["spec"]
    n_steps = int(spec.N_STEPS)
    append = plan["steps"]["append_steps"]
    target = plan["steps"]["cumulative_end"]
    base = int(model.num_timesteps)
    sf = plan["schedules_frozen"]
    n_points = int(sf["n_points"])
    if append % n_steps != 0 or append // n_steps != n_points:
        print("[stage5/schedule] FAIL: append %d vs n_steps %d"
              " does not give %d points"
              % (append, n_steps, n_points), file=sys.stderr)
        return FAIL["schedule"]
    clip_pts, lr_pts = [], []
    for k in range(1, n_points + 1):
        pr = 1.0 - float(base + n_steps * k) / float(target)
        clip_pts.append(float(model.clip_range(pr)))
        lr_pts.append(float(model.lr_schedule(pr)))
    if not (all(c == sf["clip_range"] for c in clip_pts)
            and all(l == sf["learning_rate"] for l in lr_pts)):
        print("[stage5/schedule] FAIL: drift clip %r lr %r"
              % (set(clip_pts), set(lr_pts)), file=sys.stderr)
        return FAIL["schedule"]

    # -- 6. registry intent(第一个可能有训练副作用的点) ------
    registry = Registry(registry_root)
    digest = plan_digest(plan)
    experiment_id = plan["experiment_id_hint"]
    base_seed_hdr = header.get("seed")
    try:
        registry.register_intent(
            plan, mode="executable", extra={
                "source_candidate": plan["source"][
                    "git_head_pinned"],
                "entry_head_actual": head_actual,
                "sources_vs_candidate": sources_check,
                "header": {
                    "observation_spec": header.get(
                        "observation_spec"),
                    "bank_ref": header.get("bank_ref"),
                    "hyperparams_digest": header.get(
                        "hyperparams_digest"),
                    "seed_in_header": base_seed_hdr,
                },
                "base_seed_check": (
                    "match" if base_seed_hdr == plan["source"][
                        "base_model_seed_in_zip"]
                    else "unverifiable_no_seed_field"
                    if base_seed_hdr is None else
                    "MISMATCH")})
    except RegistryError as exc:
        print(f"[stage6/intent] FAIL: {exc}", file=sys.stderr)
        return FAIL["intent"]

    # -- 7/8/9. 训练+保存+评估+实结 ---------------------------
    evidence_root = Path(plan["evidence"]["root"])
    counters = {"optimizer": {"attempts": 0, "successes": 0,
                              "unknown": False}}
    try:
        from rl_posctl.budget import create_only_dir
        create_only_dir(evidence_root)
    except Exception as exc:
        registry.record_failed(experiment_id, digest, {
            "stage": "evidence_root", "reason": repr(exc),
            "optimizer": counters["optimizer"]})
        print(f"[stage7/evidence] FAIL: {exc}", file=sys.stderr)
        return FAIL["train"]
    try:
        settle = _execute_training(
            plan, model, hooks, evidence_root, counters,
            items, bank_path, base_seed_hdr)
        registry.record_settled(experiment_id, digest, settle)
        return 0
    except BaseException as exc:
        registry.record_failed(experiment_id, digest, {
            "stage": "train/eval", "reason": repr(exc),
            "optimizer": counters["optimizer"],
            "num_timesteps_end": int(getattr(
                model, "num_timesteps", -1))})
        print(f"[stage7] FAIL: {exc!r}", file=sys.stderr)
        return FAIL["train"]


def _execute_training(plan, model, hooks, evidence_root,
                      counters, items, bank_path,
                      base_seed_hdr) -> dict:
    """训练(v5 断言)+ 唯一 final + 前后摘要 + 原件复核 +
    独立预约评估。异常上抛由调用方实结。"""
    spec = hooks["spec"]
    n_steps = int(spec.N_STEPS)
    append = plan["steps"]["append_steps"]
    target = plan["steps"]["cumulative_end"]
    base = int(model.num_timesteps)
    cap_opt = plan["budget"]["optimizer_updates"]

    from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv
    envmod = hooks["envmod"]()
    if int(getattr(envmod, "PPO_EXEMPT_STEPS", 1)) != 0:
        raise RuntimeError(
            "PPO_EXEMPT_STEPS != 0 at start: %r"
            % getattr(envmod, "PPO_EXEMPT_STEPS"))
    train_env_count_base = int(envmod.ENV_STEP_COUNT)
    # 训练预约:throat 硬限(基线+append)
    envmod.ENV_STEP_LIMIT = train_env_count_base + append

    env = (hooks.get("make_train_env") or P0EpisodeBankEnv)(
        items)
    model.set_env(env)
    model.set_random_seed(plan["random_stream"]["new_seed"])

    digests_start = hooks["digests"](model)

    (evidence_root / "budget_ledger.json").write_text(
        json.dumps({
            "faces": {
                "train_steps": {"reserved": append,
                                "settled": None},
                "optimizer_updates": {"reserved": cap_opt,
                                      "settled": None},
                "eval_env_steps": {"reserved": TOTAL_STEP_CAP,
                                   "settled": None}},
            "utc": utc_now()}, ensure_ascii=False, indent=1),
        encoding="utf-8")

    box = wrap_optimizer_gate(
        model.policy.optimizer, cap=cap_opt)
    counters["optimizer"] = box
    from rl_posctl.experiments import FailureAwareStop
    stop = FailureAwareStop()

    learn = hooks.get("learn")
    if learn is not None:
        learn(model, append, stop)
    else:
        model.learn(total_timesteps=append,
                    reset_num_timesteps=False,
                    callback=stop.cb)

    # -- v5 保存前断言(零更新绝不 final) --------------------
    learned = int(model.num_timesteps) - base
    if int(model.num_timesteps) != target:
        raise RuntimeError(
            "timestep target miss: %r != %d"
            % (model.num_timesteps, target))
    if stop.failure is not None:
        raise RuntimeError(
            "economic failure: %r" % (stop.failure,))
    if learned != append or append != (
            append // n_steps) * n_steps:
        raise RuntimeError("collected %r != append" % learned)
    if box["successes"] == 0:
        raise RuntimeError(
            "zero optimizer updates: refusing final save")
    if (box["successes"] != cap_opt or box["unknown"]
            or box["attempts"] != cap_opt):
        raise RuntimeError(
            "optimizer gate counts %r != cap %d"
            % (box, cap_opt))

    digests_end = hooks["digests"](model)
    ck_path = evidence_root / f"ck{target}.zip"
    meta = hooks["save_final"](
        model, ck_path, target_step=target,
        optimizer_steps=box["successes"],
        run_name=plan["source"]["run_name"] + "_cont")
    train_env_steps = int(envmod.ENV_STEP_COUNT) - (
        train_env_count_base)

    # 原件复核(训练后)
    ck_after = sha256_file(Path(plan["source"]["checkpoint"]))
    bank_after = sha256_file(Path(plan["course"]["bank_path"]))
    if ck_after != plan["source"]["checkpoint_sha256"]:
        raise RuntimeError("originals changed during run: ck")
    if bank_after != plan["course"]["bank_sha256"]:
        raise RuntimeError("originals changed during run: bank")

    # -- 评估:独立预约,不沿用训练限额、不豁免 -------------
    if int(getattr(envmod, "PPO_EXEMPT_STEPS", 1)) != 0:
        raise RuntimeError("PPO_EXEMPT_STEPS drifted != 0")
    eval_env_count_base = int(envmod.ENV_STEP_COUNT)
    envmod.ENV_STEP_LIMIT = eval_env_count_base + (
        TOTAL_STEP_CAP)

    eval_summary = run_contrast_eval(
        [("source_frozen",
          hooks["load_model"](plan)[0]),
         ("new", model)],
        items=items,
        feature_names=plan["course"]["feature_names"],
        out_dir=evidence_root / "eval",
        hooks=hooks.get("eval") or {})

    eval_env_steps = int(envmod.ENV_STEP_COUNT) - (
        eval_env_count_base)

    ledger = {
        "faces": {
            "train_steps": {"reserved": append,
                            "settled": learned},
            "optimizer_updates": {"reserved": cap_opt,
                                  "settled": box["successes"]},
            "eval_env_steps": {"reserved": TOTAL_STEP_CAP,
                               "settled": eval_env_steps}},
        "train_env_throat_delta": train_env_steps,
        "utc": utc_now()}
    (evidence_root / "budget_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=1),
        encoding="utf-8")

    return {
        "train_steps_settled": learned,
        "optimizer": {"attempts": box["attempts"],
                      "successes": box["successes"],
                      "unknown": box["unknown"]},
        "num_timesteps_end": int(model.num_timesteps),
        "digests_start": digests_start,
        "digests_end": digests_end,
        "new_checkpoint": str(ck_path),
        "new_checkpoint_sha256": sha256_file(ck_path),
        "final_stage_meta": meta,
        "originals_unchanged": True,
        "base_seed_in_header": base_seed_hdr,
        "train_env_throat_delta": train_env_steps,
        "eval": eval_summary,
        "evidence_root": str(evidence_root),
        "rc": 0,
    }


# ---- v5 对比评估引擎(整段移植自已验收 eval_contrast.py) ----------
def run_contrast_eval(tiers, *, items, feature_names,
                      out_dir, hooks=None) -> dict:
    """两档 × (108 格分布 + 8 集固定 pair0-3×variant 逐 step)。

    v5 冻结面:16 集/1024 step/1024 predict/216 格;逐 step 立即
    flush;economic_failure 写行后立即失败;term/trunc 唯一终端行;
    异常路径 partial/unknown 如实计数;不生成新 bank;无 bootstrap。
    """
    import numpy as np
    from rl_posctl.skill_p0.p0eval import (
        behavior_grid_obs, dist_probs as real_dist_probs,
        incbeta)
    from rl_posctl.skill_p0.p0spec import (
        BEHAVIOR_W_MIN, BEHAVIOR_W_NEUTRAL)

    grid_rows_fn = hooks.get("grid_rows") or (
        lambda fn: behavior_grid_obs(feature_names=list(fn)))
    dist_fn = hooks.get("dist_probs") or real_dist_probs
    make_env = hooks.get("make_env") or _real_make_env

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    sel = []
    for p in PAIRS:
        for v in VARIANTS:
            sel.append(next(
                it for it in items
                if it[2]["pair_index"] == p
                and it[2]["variant"] == v))
    if len(sel) != len(PAIRS) * len(VARIANTS):
        raise RuntimeError("selection != 8")
    canon = [str(c) for c in sel[0][1].columns]
    if canon != list(feature_names):
        raise RuntimeError(
            "bank column order %r != plan %r" % (
                canon, list(feature_names)))
    for it in sel:
        if [str(c) for c in it[1].columns] != canon:
            raise RuntimeError(
                "episode feature order != canonical")

    steps_done = 0
    predicts_done = 0
    grids_done = 0
    grids_unknown = False
    predict_unknown = False
    rows_flushed = 0
    episodes_done = 0
    raw_fh = (out_dir / "raw_episodes.jsonl").open(
        "x", encoding="utf-8")
    terminal_rows = []
    grid_all = []
    try:
        for tag, model in tiers:
            rows = grid_rows_fn(canon)
            if len(rows) != EVAL_FROZEN["grids"]:
                raise RuntimeError(
                    "grid rows %d" % len(rows))
            try:
                d = dist_fn(model, np.stack(
                    [r[5] for r in rows]))
            except BaseException:
                grids_unknown = True
                raise
            grids_done += 1  # 成功后才计数
            a_, b_ = d["alpha"], d["beta"]
            m = d["m"]
            up_c = (1.0 + BEHAVIOR_W_MIN) / 2.0
            dn_c = (1.0 - BEHAVIOR_W_MIN) / 2.0
            i_up = np.array([incbeta(a_[k], b_[k], up_c)
                             for k in range(len(rows))])
            i_dn = np.array([incbeta(a_[k], b_[k], dn_c)
                             for k in range(len(rows))])
            i_nh = np.array([incbeta(
                a_[k], b_[k],
                (1 + BEHAVIOR_W_NEUTRAL) / 2)
                for k in range(len(rows))])
            i_nl = np.array([incbeta(
                a_[k], b_[k],
                (1 - BEHAVIOR_W_NEUTRAL) / 2)
                for k in range(len(rows))])
            model_rows = []
            for k, r in enumerate(rows):
                p_r = float(d["p_rebal"][k])
                p_h = float(d["p_hold"][k])
                p_neu_r = p_r * (
                    float(m[k][1]) + float(m[k][3]) * (
                        float(d["b0"][k])
                        + (i_nh[k] - i_nl[k])))
                model_rows.append({
                    "model": tag, "s": r[0], "c": r[1],
                    "q": r[2], "g": r[3],
                    "remaining": r[4],
                    "obs": [float(x) for x in r[5]],
                    "p_hold": p_h, "p_rebal": p_r,
                    "alpha": float(a_[k]),
                    "beta": float(b_[k]),
                    "mix": [float(x) for x in m[k]],
                    "b0": float(d["b0"][k]),
                    "p_rebal_up": p_r * (
                        float(m[k][2]) + float(m[k][3])
                        * (1.0 - i_up[k])),
                    "p_rebal_down": p_r * (
                        float(m[k][0])
                        + float(m[k][3]) * i_dn[k]),
                    "p_rebal_neutral": p_neu_r,
                    "p_neutral_band": p_h + p_neu_r})
            grid_all.extend(model_rows)
            (out_dir / f"grid_{tag}.json").write_text(
                json.dumps(model_rows, ensure_ascii=False,
                           indent=1), encoding="utf-8")

            for it in sel:
                env = make_env(it[1], it[0])
                obs, _info = env.reset()
                ep_steps = 0
                ep_act_vol = 0.0
                term_row = None
                while True:
                    t = env._current_tick
                    row = env._feature_row(t)
                    fees0 = float(env.ledger.fees_total)
                    eq0 = env.ledger.equity(
                        float(env._close[t]))
                    ratio0 = (env.ledger.exposure_ratio(
                        float(env._close[t]))
                        if eq0 > 0 else 0.0)
                    if predicts_done + 1 > (
                            TOTAL_PREDICT_CAP):
                        raise RuntimeError(
                            "predict cap exceeded")
                    try:
                        act, _ = model.predict(
                            np.asarray(obs)[None, :],
                            deterministic=True)
                    except BaseException:
                        predict_unknown = True
                        raise
                    predicts_done += 1
                    if steps_done + 1 > TOTAL_STEP_CAP:
                        raise RuntimeError(
                            "step cap exceeded")
                    if ep_steps + 1 > EP_CAP:
                        raise RuntimeError(
                            "episode cap exceeded")
                    try:
                        obs, r_, term, trunc, info = env.step(
                            np.asarray(act[0]))
                    except BaseException:
                        raise RuntimeError(
                            "env.step failed "
                            "(consumption unknown)")
                    steps_done += 1
                    ep_steps += 1
                    ep_act_vol += abs(float(
                        info.get("signed_qty") or 0.0))
                    raw_fh.write(json.dumps({
                        "model": tag,
                        "pair_index": it[2]["pair_index"],
                        "variant": it[2]["variant"],
                        "step": int(t),
                        "s": float(row.get("s")),
                        "feature_names": canon,
                        "branch": info.get("action_branch"),
                        "w": info.get("action_w"),
                        "exposure_before": float(ratio0),
                        "exposure_after": info.get(
                            "account_state", {}).get(
                                "exposure_ratio"),
                        "strategy_action_volume": abs(float(
                            info.get("signed_qty") or 0.0)),
                        "fee_increment_all_fills": float(
                            env.ledger.fees_total) - fees0,
                        "risk_action": info.get("risk_action"),
                        "terminal_liquidation": info.get(
                            "terminal_liquidation"),
                        "terminated": bool(term),
                        "truncated": bool(trunc),
                        "equity_end": info.get("equity_end"),
                        "economic_failure": info.get(
                            "economic_failure") is not None,
                    }, ensure_ascii=False) + "\n")
                    raw_fh.flush()
                    rows_flushed += 1
                    if info.get("economic_failure") is not None:
                        raise RuntimeError(
                            "economic failure in eval episode "
                            "(model %s pair %s v%s step %d)"
                            % (tag, it[2]["pair_index"],
                               it[2]["variant"], t))
                    if term or trunc:
                        term_row = {
                            "model": tag,
                            "pair_index": it[2][
                                "pair_index"],
                            "variant": it[2]["variant"],
                            "equity_end": info.get(
                                "equity_end"),
                            "fees_total": float(
                                env.ledger.fees_total),
                            "action_volume_total": ep_act_vol,
                            "liquidation": bool(info.get(
                                "terminal_liquidation"))}
                        break
                if ep_steps != EP_CAP or term_row is None:
                    raise RuntimeError(
                        "episode did not run exactly %d steps "
                        "with a unique terminal row: %d"
                        % (EP_CAP, ep_steps))
                terminal_rows.append(term_row)
                episodes_done += 1
    finally:
        raw_fh.close()

    if not (episodes_done == EVAL_FROZEN["episodes"]
            and steps_done == EVAL_FROZEN["steps"]
            and predicts_done == EVAL_FROZEN["predicts"]
            and grids_done == len(tiers)
            and len(grid_all) == 2 * EVAL_FROZEN["grids"]
            and not grids_unknown):
        raise RuntimeError(
            "face totals mismatch: eps=%d steps=%d preds=%d "
            "grids=%d cells=%d unknown=%r"
            % (episodes_done, steps_done, predicts_done,
               grids_done, len(grid_all), grids_unknown))

    summ = {}
    for tag_, _m in tiers:
        neu = [g["p_neutral_band"] for g in grid_all
               if g["model"] == tag_ and g["s"] == 0.0]
        lng = [g["p_rebal_up"] for g in grid_all
               if g["model"] == tag_ and g["s"] == 1.0]
        sh = [g["p_rebal_down"] for g in grid_all
              if g["model"] == tag_ and g["s"] == -1.0]
        trs = [t for t in terminal_rows
               if t["model"] == tag_]
        summ[tag_] = {
            "neutral_min": min(neu),
            "neutral_mean": sum(neu) / len(neu),
            "long_min": min(lng), "short_min": min(sh),
            "episodes": {
                "n_episodes": len(trs),
                "mean_episode_end_equity": sum(
                    t["equity_end"] for t in trs) / len(trs),
                "mean_episode_fees": sum(
                    t["fees_total"] for t in trs) / len(trs),
                "total_fees": sum(
                    t["fees_total"] for t in trs),
                "mean_action_volume": sum(
                    t["action_volume_total"]
                    for t in trs) / len(trs)}}

    return {
        "tiers": [t[0] for t in tiers],
        "episodes_done": episodes_done,
        "steps_done": steps_done,
        "predicts_done": predicts_done,
        "grid_batches_done": grids_done,
        "grid_cells_total": len(grid_all),
        "rows_flushed": rows_flushed,
        "grid_attempt_unknown": grids_unknown,
        "predict_attempt_unknown": predict_unknown,
        "per_model": summ,
        "note": "IN-SAMPLE evaluation on the training bank; "
                "training-fit contrast only — NOT unseen-data "
                "generalization, NOT convergence; no bootstrap",
        "utc": utc_now(),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="p0continue",
        description="P0 统一续训入口(plan.json 驱动)")
    ap.add_argument("plan", help="续训计划 JSON 路径")
    ap.add_argument("--registry-root", required=True,
                    help="登记根目录(repo 与 acceptance 之外)")
    args = ap.parse_args(argv)
    return run_continuation(
        args.plan, args.registry_root)


if __name__ == "__main__":
    sys.exit(main())
