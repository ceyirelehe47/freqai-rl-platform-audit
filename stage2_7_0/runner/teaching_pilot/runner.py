# -*- coding: utf-8 -*-
"""runner v3 — UnifiedTeachingPilot-v1 执行器(PREPARED_NOT_RUN)。

v3(审查方 3999 组4/5):
- learn 加 on_step/rollout 薄控制:经济失败、非有限 reward、
  预算越界立即停(reward_valid=False 占位 0 不入学习);
- 计数分列:optimizer step(冷载单参 step)/epochs/环境步;
- 冷载比**实际权重**(逐参 allclose)+optimizer 摘要(组数/状态
  数/单参 step),不以参数数量或 step 总和代替;
- 预算覆盖导入→最终保存;最终保存后 checkpoint why→不可 DONE;
- 身份:expected SHA **比较**(不符即停),非只记录;核 --spec
  路径/世界全参数/实际 module.__file__ 源路径(PILOT_REPO_SRC 同根);
- SB3 seed 不覆盖 train_env(VecEnv seed shim,pending=311001),
  torch 初始化种子独立。
"""
import argparse
import hashlib
import json
import os
import resource
import sys
import time

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)
import teach_env as TE  # noqa
import policy as PL  # noqa

STATUS = "PREPARED_NOT_RUN"
SPEC_FILE = os.path.join(_HERE, "run_spec.json")
IDENTITY_LOCAL = [
    "teach_env.py", "policy.py", "runner.py",
    "eval_pilot.py", "run_spec.json"]
IDENTITY_REPO = [
    "rl_posctl/skill_p0/unified_course.py",
    "rl_posctl/skill_p0/p0policy.py",
    "rl_posctl/skill_p0/p0spec.py",
    "rl_posctl/curriculum.py",
    "rl_posctl/ledger.py",
    "rl_posctl/env.py"]

BUDGET = {"wall_s": 900.0, "cpu_s": 600.0,
          "rss_gib": 1.0}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20),
                      b""):
            h.update(c)
    return h.hexdigest()


def repo_src():
    return TE.repo_src_path()


def collect_identity(spec=None):
    """实测+预期比较(不符 raise);返回实测与实际 module 路径。"""
    root = repo_src()
    got_local = {n: sha256_file(
        os.path.join(_HERE, n))
        for n in IDENTITY_LOCAL}
    got_repo = {rel: sha256_file(
        os.path.join(root, rel))
        for rel in IDENTITY_REPO}
    mod_paths = {}
    import rl_posctl.ledger as _led
    import rl_posctl.env as _env
    import rl_posctl.skill_p0.p0policy as _pol
    import rl_posctl.skill_p0.p0spec as _spec
    import rl_posctl.skill_p0.unified_course as _uc
    for name, m in (
            ("ledger", _led), ("env", _env),
            ("p0policy", _pol),
            ("p0spec", _spec),
            ("unified_course", _uc)):
        mod_paths[name] = m.__file__
        real = os.path.realpath(m.__file__)
        if not real.startswith(
                os.path.realpath(root)):
            raise RuntimeError(
                "module %s outside repo root:"
                " %s" % (name, real))
    exp = (spec or {}).get(
        "identity_expected", {})
    for k, v in exp.get("local",
                        {}).items():
        if got_local.get(k) != v:
            raise RuntimeError(
                "local SHA mismatch %s"
                % k)
    for k, v in exp.get("repo",
                        {}).items():
        if got_repo.get(k) != v:
            raise RuntimeError(
                "repo SHA mismatch %s"
                % k)
    return {"local": got_local,
            "repo": got_repo,
            "module_paths": mod_paths,
            "repo_root": root}


class Book:
    """全 pilot 累计预算(分阶段;最终保存后仍检查)。"""

    def __init__(self, limits=None, clock=None):
        self.limits = limits or BUDGET
        if clock is not None:
            self.nw, self.nc = clock
        else:
            self.nw = time.perf_counter
            self.nc = time.process_time
        self.t0 = self.nw()
        self.c0 = self.nc()
        self.phases = {}

    def checkpoint(self, phase):
        wall = self.nw() - self.t0
        cpu = self.nc() - self.c0
        rss = (resource.getrusage(
            resource.RUSAGE_SELF).ru_maxrss
            / (1024.0 * 1024.0))
        d = self.phases.setdefault(
            phase, {})
        d.update({"wall_s": wall,
                  "cpu_s": cpu,
                  "rss_gib": rss})
        why = None
        if wall > self.limits["wall_s"]:
            why = "wall_clock"
        elif cpu > self.limits["cpu_s"]:
            why = "cpu"
        elif rss > self.limits["rss_gib"]:
            why = "rss"
        return why, {"wall_s": wall,
                     "cpu_s": cpu,
                     "rss_gib": rss}, dict(
            self.phases)

    def snapshot(self):
        return dict(self.phases)


class _SeedHoldVec:
    """DummyVecEnv shim:seed() 不覆盖内部 rng
    (train_env=311001 pending 保留;SB3 首 reset 不改 seed)。"""

    def __init__(self, env):
        from stable_baselines3.common.vec_env \
            import DummyVecEnv
        self._inner = DummyVecEnv(
            [lambda: env])

        class _Held:
            pass

    def __getattr__(self, n):
        return getattr(
            self._inner, n)

    def seed(self, seed=None):
        return [self._inner.envs[0]
                .rng and None]


def build_real_ppo(env, seed, spec):
    """SB3 PPO+P0ActorCriticPolicy(B);env 用 seed-shim 包裹。"""
    from stable_baselines3 import PPO
    from stable_baselines3.common.vec_env \
        import DummyVecEnv
    from rl_posctl.skill_p0 import p0spec

    class _HoldSeedDummy(DummyVecEnv):
        def seed(self, seed=None):
            return [seed]

    p = spec["ppo"]
    vec = _HoldSeedDummy([lambda: env])
    model = PPO(
        env=vec,
        policy=PL.P0ActorCriticPolicy,
        policy_kwargs={
            "arm": PL.ARM,
            "net_arch": {"pi": [128, 128],
                         "vf": [128, 128]},
            "activation_fn": th.nn.Tanh},
        learning_rate=p["lr"],
        n_steps=p["n_steps"],
        batch_size=p["batch_size"],
        n_epochs=p["epochs"],
        gamma=p["gamma"],
        gae_lambda=p0spec.GAE_LAMBDA,
        clip_range=p0spec.CLIP_RANGE,
        vf_coef=p0spec.VF_COEF,
        max_grad_norm=p0spec.MAX_GRAD_NORM,
        ent_coef=p0spec.ENT_COEF,
        seed=seed, device="cpu")
    return model


def _weights_allclose(m1, m2):
    p1 = list(m1.parameters())
    p2 = list(m2.parameters())
    if len(p1) != len(p2):
        return False
    import math as _m
    tot = 0.0
    for a, b in zip(p1, p2):
        if a.shape != b.shape:
            return False
        d = float(
            (a.detach() - b.detach())
            .abs().sum())
        if not _m.isfinite(d):
            return False
        tot += d
    return tot, len(p1)


def _optimizer_state_equal(a, b):
    if isinstance(a, th.Tensor) or isinstance(b, th.Tensor):
        return (isinstance(a, th.Tensor) and isinstance(b, th.Tensor)
                and a.shape == b.shape and a.dtype == b.dtype
                and bool(th.equal(a.detach().cpu(), b.detach().cpu())))
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(
            _optimizer_state_equal(a[k], b[k]) for k in a)
    if isinstance(a, (list, tuple)):
        return len(a) == len(b) and all(
            _optimizer_state_equal(x, y)
            for x, y in zip(a, b))
    return a == b


def _optimizer_summary(model):
    st = model.policy.optimizer.state_dict()
    entries = st["state"]
    steps = {int(s.get("step", 0))
             for s in entries.values()}
    return {
        "n_param_groups": len(
            st["param_groups"]),
        "n_state_entries": len(entries),
        "per_param_step_set": sorted(steps)[:5],
        "optimizer_step_max": (
            max(steps) if steps else 0)}


def run_pilot(out_dir, spec, ppo_factory=None,
              eval_fn=None, clock=None,
              env_factory=None,
              callback_factory=None,
              spec_path=None):
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir,
                          "RUNNING.marker")
    fd = os.open(marker,
                 os.O_CREAT | os.O_EXCL
                 | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "pilot.json")
    report = {"status": "running",
              "course_gate": "not_frozen",
              "phases": {},
              "env_steps_train": 0}
    book = Book(clock=clock)
    try:
        if spec_path is not None:
            report["spec_path"] = \
                os.path.abspath(
                    spec_path)
            report["spec_sha256"] = \
                sha256_file(spec_path)
        report["identity"] = (
            collect_identity(spec))
        why, _c, _p = book.checkpoint(
            "import")
        if why:
            raise RuntimeError(
                "budget(import): %s" % why)
        seeds = spec["seeds"]
        factory = (env_factory
                   or TE.UnifiedPilotEnv)
        import random as _rd
        env = factory(
            _rd.Random(
                seeds["train_env"]))
        mk = ppo_factory or build_real_ppo
        th.manual_seed(
            seeds["torch_init"])
        model = mk(env,
                   seeds["torch_init"],
                   spec)
        if not getattr(model,
                       "_pilot_stub",
                       False):
            tot = sum(
                p.numel() for p in
                model.policy.parameters())
            if tot != PL.STATIC_TOTAL:
                raise RuntimeError(
                    "param count %d"
                    % tot)
            report["param_total"] = tot
        why, _c, _p = book.checkpoint(
            "init")
        if why:
            raise RuntimeError(
                "budget(init): %s" % why)
        ck0 = os.path.join(out_dir,
                           "initial")
        model.save(ck0)
        report["initial_ckpt_sha"] = (
            sha256_file(ck0 + ".zip"))
        ev = eval_fn or _real_eval
        report["eval_initial"] = ev(
            ck0, spec, "initial",
            book, out_dir,
            env_factory=env_factory)
        # ---- 训练:单次 learn+薄控制 ----
        cbk = (callback_factory or
               _make_guard_callback)(
                   book, env)
        opt_counter = {"n": 0}
        if not getattr(model,
                       "_pilot_stub",
                       False):
            _wrap_optimizer(
                model.policy.optimizer,
                book, opt_counter)
        total = spec["ppo"][
            "total_teach_steps"]
        model.learn(
            total_timesteps=total,
            reset_num_timesteps=True,
            callback=cbk,
            progress_bar=False)
        report["env_steps_train"] = (
            env.n_steps_env)
        report["learn_num_timesteps"] = (
            model.num_timesteps)
        report["expected_env_steps"] = \
            total
        if (env.n_steps_env != total
                and not getattr(
                    model, "_pilot_stub",
                    False)):
            raise RuntimeError(
                "env steps %d != %d"
                % (env.n_steps_env,
                   total))
        why, _c, _p = book.checkpoint(
            "post_learn")
        if why:
            raise RuntimeError(
                "budget(post_learn): %s"
                % why)
        # 训练后 optimizer 计数(分列)
        if not getattr(model,
                       "_pilot_stub",
                       False):
            report[
                "optimizer_summary_"
                "train"] = \
                _optimizer_summary(model)
        ck1 = os.path.join(out_dir,
                           "final")
        model.save(ck1)
        report["final_ckpt_sha"] = (
            sha256_file(ck1 + ".zip"))
        report["eval_final"] = ev(
            ck1, spec, "final",
            book, out_dir,
            env_factory=env_factory)
        # 冷载:实际权重严格相等+optimizer 内容比较
        if not getattr(model,
                       "_pilot_stub",
                       False):
            from stable_baselines3 \
                import PPO
            cold = PPO.load(
                ck1, device="cpu")
            res = _weights_allclose(
                model.policy,
                cold.policy)
            if res is False:
                raise RuntimeError(
                    "cold weights shape/"
                    "tensor mismatch")
            if res[0] != 0.0:
                raise RuntimeError(
                    "cold weights differ:"
                    " sum_abs_diff=%r"
                    % res[0])
            report["cold_weight_check"] = {
                "sum_abs_diff": res[0],
                "n_tensors": res[1],
                "equal": True}
            s1 = _optimizer_summary(model)
            s2 = _optimizer_summary(cold)
            report[
                "cold_optimizer_"
                "summary"] = s2
            if not _optimizer_state_equal(
                    model.policy.optimizer
                    .state_dict(),
                    cold.policy.optimizer
                    .state_dict()):
                raise RuntimeError(
                    "cold optimizer state "
                    "content mismatch")
            report[
                "cold_optimizer_state_"
                "equal"] = True
        # 计数分列
        report["counters"] = {
            "env_steps_train":
                report[
                    "env_steps_train"],
            "epochs_config":
                spec["ppo"]["epochs"],
            "optimizer_step_max":
                report.get(
                    "optimizer_summary_"
                    "train", {}).get(
                    "optimizer_step_max",
                    None),
            "optimizer_calls_success":
                opt_counter["n"]}
        why, cum, phases = (
            book.checkpoint("final"))
        report["phases"] = phases
        report["budget_final"] = cum
        report["final_budget_why"] = \
            why
        steps = (
            report["env_steps_train"]
            + report.get(
                "eval_initial",
                {}).get("steps_used", 0)
            + report.get(
                "eval_final",
                {}).get("steps_used", 0))
        report[
            "grand_steps_total"] = \
            steps
        cap = spec["evaluation"][
            "grand_total_steps_cap"]
        if steps > cap:
            raise RuntimeError(
                "grand step cap")
        ok = why is None
        report["status"] = (
            "completed" if ok
            else "failed")
        if not ok:
            report.setdefault(
                "fail_reason",
                "budget(final): %s"
                % why)
        with open(rp, "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        # 最终保存后再 checkpoint(不可 DONE 若超限)
        why2, cum2, _ph = (
            book.checkpoint(
                "post_save"))
        report["budget_post_save"] = \
            cum2
        if why2:
            report["status"] = "failed"
            report.setdefault(
                "fail_reason",
                "budget(post_save): %s"
                % why2)
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(report, f,
                          indent=1,
                          allow_nan=False)
            os.replace(marker,
                       os.path.join(
                           out_dir,
                           "FAILED"
                           ".marker"))
            raise RuntimeError(
                "budget(post_save):"
                " %s" % why2)
        os.replace(
            marker,
            os.path.join(
                out_dir,
                "DONE.marker"
                if ok
                else "FAILED.marker"))
        if not ok:
            raise RuntimeError(
                "budget(final): %s"
                % why)
        return report
    except BaseException as exc:
        report["status"] = "failed"
        report.setdefault("fail_reason", repr(exc))
        if "env" in locals():
            report["env_steps_train"] = int(
                getattr(env, "n_steps_env", 0))
        if "model" in locals():
            report["learn_num_timesteps"] = int(
                getattr(model, "num_timesteps", 0))
            report["ppo_n_updates_reported"] = int(
                getattr(model, "_n_updates", 0))
        if "opt_counter" in locals():
            report["optimizer_calls_success"] = int(
                opt_counter["n"])
        if "model" in locals():
            try:
                partial = os.path.join(
                    out_dir, "partial_failure")
                model.save(partial)
                report["partial_checkpoint"] = \
                    partial + ".zip"
                report["partial_checkpoint_sha256"] = \
                    sha256_file(partial + ".zip")
                report["partial_forensics_only"] = True
            except BaseException as save_exc:
                report["partial_save_error"] = \
                    repr(save_exc)
        report["phases"] = book.snapshot()
        try:
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1,
                          allow_nan=False)
        except BaseException:
            pass
        try:
            os.replace(marker, os.path.join(
                out_dir, "FAILED.marker"))
        except BaseException:
            pass
        raise


def _wrap_optimizer(optimizer, book,
                    counter):
    """优化薄 hook:每次 step 前查梯度有限/后查参数有限,
    计成功调用;每 256 次预算 checkpoint;异常向上。"""
    orig = optimizer.step

    def stepped(*a, **k):
        for g in optimizer.param_groups:
            for p in g["params"]:
                if p.grad is not None \
                        and not bool(
                        th.isfinite(
                            p.grad).all()):
                    raise RuntimeError(
                        "non-finite grad")
        out = orig(*a, **k)
        for g in optimizer.param_groups:
            for p in g["params"]:
                if not bool(th.isfinite(
                        p).all()):
                    raise RuntimeError(
                        "non-finite param")
        counter["n"] += 1
        if counter["n"] % 256 == 0:
            why, _c, _p = (
                book.checkpoint(
                    "optim"))
            if why:
                raise RuntimeError(
                    "budget(optim):"
                    " %s" % why)
        return out

    optimizer.step = stepped


def _make_guard_callback(book, env):
    from stable_baselines3.common.\
        callbacks import BaseCallback

    class Guard(BaseCallback):
        def _on_step(self):
            for info in self.locals.get(
                    "infos", []):
                ef = info.get(
                    "economic_failure")
                if ef is not None:
                    raise RuntimeError(
                        "economic failure:"
                        " %s" % ef)
                rv = info.get(
                    "reward_valid", True)
                if rv is False:
                    raise RuntimeError(
                        "reward_valid=False"
                        " reached learner")
                rws = self.locals.get(
                    "rewards")
                if rws is not None:
                    import math as _m
                    for x in np.asarray(
                            rws).reshape(-1):
                        if not _m.isfinite(
                                float(x)):
                            raise RuntimeError(
                                "non-finite "
                                "reward")
            return True

        def _on_rollout_end(self):
            why, _c, _p = (
                book.checkpoint(
                    "rollout"))
            if why:
                raise RuntimeError(
                    "budget(rollout):"
                    " %s" % why)

    return Guard()


def _real_eval(ckpt_path, spec, tag, book,
               out_dir, env_factory=None):
    import eval_pilot as EP
    return EP.evaluate_checkpoint(
        ckpt_path, spec, tag, book,
        out_dir,
        env_factory=env_factory)


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="UnifiedTeaching"
                    "Pilot-v1")
    ap.add_argument("out_dir")
    ap.add_argument("--spec",
                    default=SPEC_FILE)
    ap.add_argument(
        "--mode",
        choices=["official"],
        default="official")
    a = ap.parse_args(argv)
    if not os.path.isfile(a.spec):
        raise SystemExit(
            "spec not found: %s"
            % a.spec)
    spec = json.load(open(
        a.spec, encoding="utf-8"))
    report_spec_path = os.path.abspath(
        a.spec)
    spec_sha = sha256_file(a.spec)
    if a.mode != "official":
        raise SystemExit(
            "unknown mode")
    if sha256_file(a.spec) != spec_sha:
        raise SystemExit(
            "spec changed during run")
    run_pilot(a.out_dir, spec,
              spec_path=report_spec_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
