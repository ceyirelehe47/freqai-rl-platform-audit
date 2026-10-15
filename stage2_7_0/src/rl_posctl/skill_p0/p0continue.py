# -*- coding: utf-8 -*-
"""P0 统一续训入口(批准版实施,route-c-p0-continuation 分支)。

复用已验收组件(p0run/p0policy/p0eval/p0banks/budget/experiments/
curriculum),不另造 harness;已验收模块零修改。

执行序(批准版 2026-10-15,顺序固定):
  1. 纯 plan 校验(结构/类型/白名单/自洽;零文件系统副作用)
  2. 源码/原件 SHA(checkpoint、bank;bank 列序显式核对)
  3. 加载模型(load_p0_model_archive,仅 arm;无 bank_ref)
  4. 实际步数/超参/schedule 预验证(learn 前;失败=零训练步、
     零 optimizer 调用、零评估)
  5. 独占登记预约(registry intent;flock 互斥,防重复)
  6. 环境+训练+最后更新后唯一 final 保存+对比评估+实结

要点:
- 追加步数与累计目标显式双字段:载入后
  loaded.num_timesteps + append_steps == cumulative_end 硬校验;
  learn(total_timesteps=append_steps, reset_num_timesteps=False)。
- 门逻辑复用已验收 v5 语义(attempts/successes/unknown 计数 +
  上限前置拒绝)。旧 P0LearnGate 不直接用于续训:其不接受
  reset 语义且计数键为 "n"(历史口径),与本入口的双字段口径
  不一致——故移植 v5 包裹器而非复用旧类。
- 首版仅 post-update 唯一 final 保存(无中间档);learn 正常
  返回后保存,异常/经济失败不伪造 final。
- 课程小写;首版仅 c1 可执行,其余课程仅登记(registry_only,
  不执行、不自动晋级);晋级门作用于**前序**课程(不要求目标
  课程自身已毕业)。
- 失败保证:intent 之前失败=零训练/零评估/零原件修改。注意
  "加载模型"阶段本身存在 import/内存/只读 IO,不是绝对零副作用;
  该阶段的失败同样零训练零评估零原件修改。
- 评估:冻结源+新两档,各 108 格分布 + 8 集×64 步确定性逐 step
  原始证据(合计 216 格/1024 predict/1024 step);in-sample 标签
  保留;不生成新 bank、不做 bootstrap。

本模块的 hooks 参数仅供纯假对象单测注入;缺省绑定全部为真实
实现(懒导入,保持模块导入轻量)。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rl_posctl.curriculum import VALID_COURSES
from rl_posctl.skill_p0.p0registry import (
    CurriculumStatus, Registry, RegistryError, plan_digest,
    sha256_file, utc_now)

#: 首版可执行课程(其余仅登记)
EXECUTABLE_COURSES = ("c1",)

#: 课程链:晋级门=前序课程全部 GRADUATED(人工批准)
_COURSE_CHAIN = ("c1", "c2", "c3",
                 "c4d0", "c4d1", "c4d2", "c4d3")

#: 固定恢复语义(唯一允许值)
RESUME_SEMANTICS = (
    "load+set_random_seed(new)+learn(reset_num_timesteps=False)")

#: 评估冻结口径(首版唯一评估模式)
EVAL_FROZEN = {"mode": "in_sample_contrast", "grids": 108,
               "episodes": 8, "steps_per_episode": 64,
               "deterministic": True}

#: 静态超参校验面(与 p0spec 冻结常数同名)
_HYPERPARAM_FIELDS = ("n_steps", "batch_size", "n_epochs",
                      "gamma", "gae_lambda", "vf_coef",
                      "ent_coef", "max_grad_norm")

FAIL = {
    "plan": 10, "prereq": 11, "sha": 12, "bank_order": 13,
    "load": 14, "steps": 15, "hyperparams": 16,
    "schedule": 17, "intent": 18, "train": 19, "save": 20,
    "eval": 21, "settle": 22,
}


class PlanError(ValueError):
    """plan 结构/自洽性错误(阶段 1)。"""


def validate_plan_pure(plan: dict) -> None:
    """阶段 1:纯结构校验,零文件系统副作用。"""
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
                "git_head_pinned"):
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


def prerequisites_of(course: str) -> tuple:
    """前序课程(不含自身);c1 无前序。"""
    idx = _COURSE_CHAIN.index(course)
    return _COURSE_CHAIN[:idx]


def check_prerequisites(plan: dict, status: CurriculumStatus,
                        arm: str) -> None:
    """晋级门:前序课程须 GRADUATED(不要求目标课程毕业)。"""
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
    return model, header


def _real_bank_feature_names(bank_path) -> list:
    """bank 列序,取自 bank JSON 首个 episode 的特征列。"""
    from rl_posctl.skill_p0.p0banks import load_p0_bank
    items = load_p0_bank(Path(bank_path))
    if not items:
        raise RuntimeError("bank empty")
    first = items[0]
    feats = first.get("feats") or first.get("features")
    if feats is None:
        raise RuntimeError(
            "bank item has no feats columns")
    if isinstance(feats, list):
        return [str(c) for c in feats]
    return [str(c) for c in feats.columns]


def _real_save_final(model, path, *, target_step,
                     optimizer_steps, run_name):
    from rl_posctl.skill_p0.p0policy import (
        save_p0_model_staged)
    return save_p0_model_staged(
        model, path, stage="final",
        target_step=int(target_step),
        optimizer_steps=int(optimizer_steps),
        run_name=str(run_name))


def wrap_optimizer_gate(optimizer, cap: int) -> dict:
    """v5 门语义:attempts/successes/unknown + 上限前置拒绝。

    旧 P0LearnGate 不适用于续训(不接受 reset 语义、计数键
    "n" 为历史口径),故移植已验收 v5 包裹器。
    """
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
    return {
        "load_model": _real_load_model,
        "bank_feature_names": _real_bank_feature_names,
        "save_final": _real_save_final,
    }


# ---- 主流程 -----------------------------------------------------
def run_continuation(plan_path, registry_root, *, hooks=None,
                     status=None, _env=None) -> int:
    """执行固定六阶段序;返回进程退出码(0=成功)。"""
    hooks = dict(_default_hooks(), **(hooks or {}))
    plan = json.loads(Path(plan_path).read_text(
        encoding="utf-8"))
    registry = Registry(registry_root)
    status = status or CurriculumStatus(registry_root)
    arm = plan["source"]["arm"]
    digest = plan_digest(plan)
    experiment_id = plan["experiment_id_hint"]

    # -- 1. 纯 plan 校验 ----------------------------------------
    try:
        validate_plan_pure(plan)
    except PlanError as exc:
        print(f"[stage1/plan] FAIL: {exc}", file=sys.stderr)
        return FAIL["plan"]

    course = plan["course"]["course"]
    registry_only = course not in EXECUTABLE_COURSES

    # -- 1b. 前序课程毕业门(登记前;不要求目标课程毕业) --------
    try:
        check_prerequisites(plan, status, arm)
    except RegistryError as exc:
        print(f"[stage1/prereq] FAIL: {exc}", file=sys.stderr)
        return FAIL["prereq"]

    # -- 1c. 仅登记课程(非 c1):前序门过后直接登记,不执行、
    #        不触碰原件 SHA/加载/训练(无自动晋级)。
    if registry_only:
        try:
            registry.register_intent(plan, mode="registry_only")
        except RegistryError as exc:
            print(f"[stage1/registry-only] FAIL: {exc}",
                  file=sys.stderr)
            return FAIL["intent"]
        print(f"[stage1] REGISTERED_ONLY course={course} "
              f"id={experiment_id} (not executable in this "
              f"version; no auto promotion)")
        return 0

    ck_path = Path(plan["source"]["checkpoint"])
    bank_path = Path(plan["course"]["bank_path"])
    if sha256_file(ck_path) != plan["source"][
            "checkpoint_sha256"]:
        print("[stage2/sha] FAIL: checkpoint sha mismatch",
              file=sys.stderr)
        return FAIL["sha"]
    if sha256_file(bank_path) != plan["course"]["bank_sha256"]:
        print("[stage2/sha] FAIL: bank sha mismatch",
              file=sys.stderr)
        return FAIL["sha"]
    try:
        bank_cols = hooks["bank_feature_names"](bank_path)
    except Exception as exc:  # bank 不可读=拒绝
        print(f"[stage2/bank] FAIL: {exc}", file=sys.stderr)
        return FAIL["bank_order"]
    if bank_cols != list(plan["course"]["feature_names"]):
        print("[stage2/bank_order] FAIL: %r != plan %r"
              % (bank_cols, plan["course"]["feature_names"]),
              file=sys.stderr)
        return FAIL["bank_order"]

    # -- 3. 加载模型(非绝对零副作用:import/内存/只读 IO) -----
    try:
        model, header = hooks["load_model"](plan)
    except Exception as exc:
        print(f"[stage3/load] FAIL: {exc}", file=sys.stderr)
        return FAIL["load"]

    # -- 4. 实际步数/超参/schedule(learn 前) -------------------
    base = int(getattr(model, "num_timesteps", 0))
    if base + plan["steps"]["append_steps"] != plan["steps"][
            "cumulative_end"]:
        print("[stage4/steps] FAIL: base %d + append %d != "
              "cumulative_end %d"
              % (base, plan["steps"]["append_steps"],
                 plan["steps"]["cumulative_end"]),
              file=sys.stderr)
        return FAIL["steps"]
    if int(getattr(model, "n_envs", 1)) != 1:
        print("[stage4/hyperparams] FAIL: n_envs != 1",
              file=sys.stderr)
        return FAIL["hyperparams"]
    hp_bad = {k: (v, getattr(model, k, None))
              for k, v in plan["hyperparams_frozen"].items()
              if getattr(model, k, None) != v}
    if hp_bad:
        print("[stage4/hyperparams] FAIL: %r" % hp_bad,
              file=sys.stderr)
        return FAIL["hyperparams"]

    n_steps = int(model.n_steps)
    append = plan["steps"]["append_steps"]
    target = plan["steps"]["cumulative_end"]
    sf = plan["schedules_frozen"]
    n_points = int(sf["n_points"])
    if append % n_steps != 0 or append // n_steps != n_points:
        print("[stage4/schedule] FAIL: append %d vs n_steps %d"
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
        print("[stage4/schedule] FAIL: drift clip %r lr %r"
              % (set(clip_pts), set(lr_pts)), file=sys.stderr)
        return FAIL["schedule"]

    # -- 5. 独占登记预约(flock;先于一切训练副作用) -----------
    try:
        registry.register_intent(plan, mode="executable")
    except RegistryError as exc:
        print(f"[stage5/intent] FAIL: {exc}", file=sys.stderr)
        return FAIL["intent"]

    # -- 6. 环境+训练+final 保存+评估+实结 ----------------------
    evidence_root = Path(plan["evidence"]["root"])
    try:
        from rl_posctl.budget import create_only_dir
        create_only_dir(evidence_root)
    except Exception as exc:
        registry.record_failed(experiment_id, digest, {
            "stage": "evidence_root",
            "reason": repr(exc), "optimizer": {
                "attempts": 0, "successes": 0,
                "unknown": False}})
        print(f"[stage6/evidence] FAIL: {exc}",
              file=sys.stderr)
        return FAIL["train"]

    counters = {"optimizer": {"attempts": 0, "successes": 0,
                              "unknown": False}}
    try:
        settle = _execute_training(
            plan, model, hooks, evidence_root, counters,
            registry, digest, experiment_id, bank_path)
        registry.record_settled(experiment_id, digest, settle)
        return 0
    except BaseException as exc:
        registry.record_failed(experiment_id, digest, {
            "stage": "train/eval",
            "reason": repr(exc),
            "optimizer": counters["optimizer"],
            "num_timesteps_end": int(getattr(
                model, "num_timesteps", -1))})
        print(f"[stage6] FAIL: {exc!r}", file=sys.stderr)
        return FAIL["train"]


def _execute_training(plan, model, hooks, evidence_root,
                      counters, registry, digest,
                      experiment_id, bank_path) -> dict:
    """训练+final 保存+对比评估;异常向上抛(由调用方实结)。

    首版仅 post-update 唯一 final:learn 正常返回后保存,
    无中间档;异常/经济失败不伪造 final。
    hooks 注入点(缺省=真实绑定):load_bank_items/make_env/
    envmod/make_stop/learn/save_final/load_model/eval_hooks。
    """
    append = plan["steps"]["append_steps"]
    target = plan["steps"]["cumulative_end"]
    base = int(model.num_timesteps)

    def _real_items(bank_path):
        from rl_posctl.skill_p0.p0banks import load_p0_bank
        return load_p0_bank(Path(bank_path))

    def _real_env(items):
        from rl_posctl.skill_p0.p0env import P0EpisodeBankEnv
        return P0EpisodeBankEnv(items)

    def _real_envmod():
        import rl_posctl.env as envmod
        return envmod

    def _real_stop():
        from rl_posctl.experiments import FailureAwareStop
        return FailureAwareStop()

    items = (hooks.get("load_bank_items") or _real_items)(
        bank_path)
    env = (hooks.get("make_env") or _real_env)(items)
    model.set_env(env)
    model.set_random_seed(plan["random_stream"]["new_seed"])
    envmod = (hooks.get("envmod") or _real_envmod)()
    envmod.ENV_STEP_LIMIT = int(
        envmod.ENV_STEP_COUNT) + append

    box = wrap_optimizer_gate(
        model.policy.optimizer,
        cap=plan["budget"]["optimizer_updates"])
    counters["optimizer"] = box
    stop = (hooks.get("make_stop") or _real_stop)()

    learn = hooks.get("learn")
    if learn is not None:
        learn(model, append, stop)
    else:
        model.learn(total_timesteps=append,
                    reset_num_timesteps=False,
                    callback=stop.cb)

    failure = getattr(stop, "failure", None)
    if failure is not None:
        raise RuntimeError(f"economic failure: {failure}")

    if int(model.num_timesteps) != target:
        raise RuntimeError(
            "timestep target miss: %r != %d"
            % (model.num_timesteps, target))

    ck_path = evidence_root / f"ck{target}.zip"
    meta = hooks["save_final"](
        model, ck_path, target_step=target,
        optimizer_steps=box["successes"],
        run_name=plan["source"]["run_name"] + "_cont")

    # 对比评估:冻结源(重新冷载同 SHA 原件)+ 新模型
    frozen_model, _hdr = hooks["load_model"](plan)
    eval_summary = run_contrast_eval(
        [("source_frozen", frozen_model), ("new", model)],
        bank_path=bank_path,
        feature_names=plan["course"]["feature_names"],
        out_dir=evidence_root / "eval",
        hooks=hooks.get("eval_hooks"))

    return {
        "train_steps_settled": int(model.num_timesteps) - base,
        "optimizer": {"attempts": box["attempts"],
                      "successes": box["successes"],
                      "unknown": box["unknown"]},
        "num_timesteps_end": int(model.num_timesteps),
        "new_checkpoint": str(ck_path),
        "new_checkpoint_sha256": sha256_file(ck_path),
        "final_stage_meta": meta,
        "eval": eval_summary,
        "evidence_root": str(evidence_root),
        "rc": 0,
        "utc": utc_now(),
    }


# ---- 对比评估引擎 -----------------------------------------------
def run_contrast_eval(tiers, *, bank_path, feature_names,
                      out_dir, hooks=None) -> dict:
    """两档对比评估:各 108 格分布 + 8 集×64 步逐 step 原始。

    冻结口径:in-sample(训练 bank 内)、确定性、合计 216 格/
    1024 predict/1024 step;不生成新 bank、不做 bootstrap。
    hooks 供纯假对象单测注入 {grid_obs, dist_probs,
    run_episodes};缺省为真实 p0eval 绑定。
    """
    hooks = hooks or {}
    grid_obs = hooks.get("grid_obs") or _real_grid_obs
    dist_probs = hooks.get("dist_probs") or _real_dist_probs
    run_episodes = hooks.get("run_episodes") or (
        _real_run_episodes)

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    obs = grid_obs(feature_names)
    if len(obs) != EVAL_FROZEN["grids"]:
        raise RuntimeError(
            "grid obs count %d != frozen %d"
            % (len(obs), EVAL_FROZEN["grids"]))

    total_predicts = 0
    total_steps = 0
    unknown_flags = []
    raw_path = out_dir / "raw_episodes.jsonl"
    with open(raw_path, "w", encoding="utf-8") as raw:
        for tier_name, tier_model in tiers:
            grid = dist_probs(tier_model, obs)
            (out_dir / f"grid_{tier_name}.json").write_text(
                json.dumps(grid, ensure_ascii=False, indent=1),
                encoding="utf-8")
            rows, counts = run_episodes(
                tier_model, tier_name, bank_path,
                feature_names)
            for row in rows:
                raw.write(json.dumps(
                    row, ensure_ascii=False) + "\n")
            total_predicts += counts["predicts_done"]
            total_steps += counts["steps_done"]
            unknown_flags.append(bool(
                counts.get("predict_unknown")))

    summary = {
        "tiers": [t[0] for t in tiers],
        "grid_observations": len(tiers) * len(obs),
        "predicts_done": total_predicts,
        "steps_done": total_steps,
        "raw_rows_flushed": total_predicts,
        "predict_attempt_unknown": any(unknown_flags),
        "note": "IN-SAMPLE evaluation on the training bank; "
                "training-fit contrast only — NOT unseen-data "
                "generalization, NOT convergence; no bootstrap",
        "utc": utc_now(),
    }
    return summary


def _real_grid_obs(feature_names):
    from rl_posctl.skill_p0.p0eval import behavior_grid_obs
    return behavior_grid_obs(feature_names=list(
        feature_names))


def _real_dist_probs(model, obs):
    import numpy as np
    from rl_posctl.skill_p0.p0eval import dist_probs
    return dist_probs(model, np.asarray(obs))


def _real_run_episodes(model, tier, bank_path,
                       feature_names):
    """8 集×64 步确定性逐 step(v5 已审口径移植)。"""
    import numpy as np
    from rl_posctl.skill_p0.p0banks import load_p0_bank
    from rl_posctl.skill_p0.p0eval import make_env

    items = load_p0_bank(Path(bank_path))[:EVAL_FROZEN[
        "episodes"]]
    cap_step = EVAL_FROZEN["episodes"] * EVAL_FROZEN[
        "steps_per_episode"]
    steps_done = 0
    predicts_done = 0
    predict_unknown = False
    rows = []
    for item in items:
        env = make_env(item)
        obs, _info = env.reset()
        for _t in range(EVAL_FROZEN["steps_per_episode"]):
            if steps_done + 1 > cap_step:
                raise RuntimeError("step cap exceeded")
            try:
                act, _ = model.predict(
                    np.asarray(obs)[None, :],
                    deterministic=True)
            except BaseException:
                predict_unknown = True
                raise
            predicts_done += 1
            obs, _r, _term, _trunc, _info = env.step(
                np.asarray(act[0]))
            steps_done += 1
            rows.append({
                "tier": tier, "predict_unknown": False,
                "predicts_done": predicts_done,
                "steps_done": steps_done})
    counts = {"predicts_done": predicts_done,
              "steps_done": steps_done,
              "predict_unknown": predict_unknown}
    for row in rows:
        row["predict_unknown"] = predict_unknown
    return rows, counts


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
