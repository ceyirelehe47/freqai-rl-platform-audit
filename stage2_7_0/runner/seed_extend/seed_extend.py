# -*- coding: utf-8 -*-
"""seed_extend — 同路径预算延长执行器(PREPARED_NOT_RUN)。

最小改动:复用 seed_contrast v4(SC)与 pilot v5(R5)已验件,
仅新增本文件。B_final 未保存 RNG → 不能 load 冒充续训;本件
在**同一进程**内:同初态重放 32768 → 边界相等门(权重+完整
Adam+计数 vs 已验 B_final 冷载)→ 保存完整 RNG → 原进程
env/优化器/RNG 继续 learn(32768, reset_num_timesteps=False,追加量)
→ 末端旧共同 trace 评价 2112+4 锚点。总 ≤67648。
"""
import argparse
import gc
import hashlib
import json
import os
import random
import resource
import sys
import time

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
SC_DIR = os.environ.get(
    "SEED_CONTRAST_DIR",
    "/mnt/f/trading/seed_contrast_prep_20261016")
PILOT = os.environ.get(
    "SEED_CONTRAST_PILOT",
    "/mnt/f/trading/teaching_pilot_prep_20261016")
DIAG = os.environ.get(
    "SEED_CONTRAST_DIAG",
    "/mnt/f/trading/diag_panel_prep_20261016")
for _p in (_HERE, SC_DIR, PILOT, DIAG):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import seed_contrast as SC  # noqa: E402
import runner as R5  # noqa: E402

STATUS = "PREPARED_NOT_RUN"
RUNSPEC_SHA256 = "d21e8d991347f372de07d293520313e86e68d33155348ca5c25354036d72a92b"
SC_FROZEN_SHA256 = ("803c9a64b683b7fe87a9c10"
                    "87ee651716e1dc6e924860"
                    "b41c9b07acb42a7271")
SPEC_FILE = os.path.join(_HERE, "RUNSPEC_EXT.json")
BUDGET = {"wall_s": 900.0, "cpu_s": 600.0,
          "rss_gib": 1.0}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _pure_opt_copy(opt_state):
    """Adam 纯数据副本(Tensor clone;无引用共享)。"""
    import copy as _c

    def cp(o):
        if isinstance(o, th.Tensor):
            return o.detach().cpu().clone()
        if isinstance(o, dict):
            return {k: cp(v) for k, v in o.items()}
        if isinstance(o, list):
            return [cp(x) for x in o]
        if isinstance(o, tuple):
            return tuple(cp(x) for x in o)
        return _c.deepcopy(o)
    return cp(opt_state)


def _np_eq(a, b):
    import numpy as _np
    if a[0] != b[0] or len(a) != len(b):
        return False
    if not _np.array_equal(a[1], b[1]):
        return False
    for i in range(2, len(a)):
        if a[i] != b[i]:
            return False
    return True


def _sig_json_norm(obj):
    """tuple→list 递归(JSON 形态)。"""
    if isinstance(obj, (tuple, list)):
        return [_sig_json_norm(x)
                for x in obj]
    if isinstance(obj, dict):
        return {k: _sig_json_norm(v)
                for k, v in obj.items()}
    return obj


def sig_equal_json(a, b):
    """JSON 形态比较(参数/形状/dtype/Adam 全信息保留)。"""
    return _sig_json_norm(a) == _sig_json_norm(b)


def _vec_state_same(a, b):
    """VecEnv/_last_episode_starts 内容比较
    (None/同对象/tensor 逐位/ndarray 逐位)。"""
    if a is None or b is None:
        return a is b
    if a is b:
        return True
    try:
        import numpy as _np
        aa = (a.detach().cpu().numpy()
              if hasattr(a, "detach")
              else _np.asarray(a))
        bb = (b.detach().cpu().numpy()
              if hasattr(b, "detach")
              else _np.asarray(b))
        return _np.array_equal(aa, bb)
    except Exception:
        return False


def rng_snapshot():
    return {
        "torch": th.get_rng_state(),
        "numpy": np.random.get_state(),
        "python": random.getstate()}


def boundary_signature(model):
    return {
        "param_hash": SC.param_hash(
            model.policy),
        "optimizer_equal": True,  # 由调用方用 R5 比较
        "num_timesteps": int(
            getattr(model,
                    "num_timesteps", 0)),
        "ppo_n_updates": int(
            getattr(model,
                    "_n_updates", 0))}


def run(out_dir, spec_path=None,
        loader=None, builder=None,
        replay_learner=None,
        continue_learner=None,
        clock=None, traces=None,
        eval_runner=None,
        panel_fn=None,
        initial_sig_ref=None):
    spec_path = spec_path or SPEC_FILE
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir, "RUNNING.marker")
    fd = os.open(marker,
                 os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "extend.json")
    report = {"status": "running",
              "course_gate": "not_frozen",
              "steps": {"replay": 0,
                        "continue": 0,
                        "final_eval": 0},
              "phases": {}}
    book = SC.Book(limits=BUDGET, clock=clock)
    ledger = SC.StepLedger(67648, report)
    model = None
    eval_calls = {"n": 0}
    try:
        spec = json.load(open(spec_path,
                              encoding="utf-8"))
        spec_sha = sha256_file(spec_path)
        if spec_sha != RUNSPEC_SHA256:
            raise RuntimeError(
                "RUNSPEC_EXT SHA %s" % spec_sha)
        report["spec_sha256"] = spec_sha
        exp = spec["identity_expected"]
        cout = exp["contrast_out_dir"]
        b_final = os.path.join(cout,
                               "B_final.zip")
        tr_file = os.path.join(cout,
                               "traces.json")
        cj = os.path.join(cout,
                          "contrast.json")
        for path, want, name in (
                (b_final,
                 exp["B_final_sha256"],
                 "B_final"),
                (tr_file,
                 exp["traces_canon_sha256"],
                 "traces"),
                (cj,
                 exp["contrast_json_sha256"],
                 "contrast.json"),
                (os.path.join(
                    PILOT, "run_spec.json"),
                 exp[
                     "pilot_run_spec_sha256"],
                 "pilot run_spec")):
            got = sha256_file(path)
            if got != want:
                raise RuntimeError(
                    "%s SHA %s" % (name, got))
        report["identity_refs_ok"] = True
        load = loader or SC._real_load
        # ---- B_final 冷读提取(先于 fresh build/manual_seed) ----
        cold = load(b_final)
        try:
            cold.policy.set_training_mode(False)
        except Exception:
            pass
        cold_data = {
            "param_hash": SC.param_hash(cold.policy),
            "param_spec": SC._param_spec(cold.policy),
            "adam_state": _pure_opt_copy(
                cold.policy.optimizer.state_dict()),
            "num_timesteps": int(
                getattr(cold, "num_timesteps", 0)),
            "ppo_n_updates": int(
                getattr(cold, "_n_updates", 0))}
        del cold
        gc.collect()
        report["cold_read_before_build"] = True
        # ---- 阶段1:同初态重放 32768 ----
        build = builder or SC._real_build_b
        p_spec = json.load(open(
            os.path.join(PILOT,
                         "run_spec.json"),
            encoding="utf-8"))
        report["identity"] = \
            R5.collect_identity(p_spec)
        eff_B = SC.build_effective_B(
            p_spec, 311002)
        diffs = SC.diff_against_a1(
            p_spec, eff_B)
        report["only_change"] = diffs
        th.manual_seed(
            eff_B["seeds"]["torch_init"])
        model = build(eff_B, eff_B)
        sig0 = SC.fresh_signature(model)
        ref = initial_sig_ref
        if ref is None:
            ref = json.load(open(
                cj, encoding="utf-8"))[
                "initial_signature_B"]
        if not sig_equal_json(sig0, ref):
            # 引用比较:初态签名应与 a1 B 一致
            raise RuntimeError(
                "initial signature != a1 B")
        why, _c, _p = book.checkpoint(
            "built")
        if why:
            raise RuntimeError(
                "budget(built): %s" % why)
        replay_learn = (
            replay_learner
            or _real_learn_replay)
        replay_learn(model, 32768,
                     report, ledger, book)
        env = getattr(model, "pilot_env",
                      None)
        if env is None or env.n_steps_env != 32768:
            raise RuntimeError(
                "replay env steps")
        report["steps"]["replay"] = env.n_steps_env
        # ---- 边界相等门(纯数据比较;零评价/零随机流) ----
        bs = boundary_signature(model)
        if bs["param_hash"] != cold_data["param_hash"]:
            raise RuntimeError(
                "boundary weights mismatch")
        if SC._param_spec(model.policy) != cold_data["param_spec"]:
            raise RuntimeError(
                "boundary param_spec mismatch")
        if not R5._optimizer_state_equal(
                model.policy.optimizer.state_dict(),
                cold_data["adam_state"]):
            raise RuntimeError(
                "boundary Adam mismatch")
        if (bs["num_timesteps"] != 32768
                or bs["ppo_n_updates"] != 320):
            raise RuntimeError(
                "boundary counts %r" % bs)
        opt_count = getattr(model, "_pilot_opt_count", None)
        if not opt_count or opt_count["n"] != 1280:
            raise RuntimeError(
                "replay optimizer calls %r"
                % (opt_count and opt_count["n"]))
        if eval_calls["n"] != 0:
            raise RuntimeError(
                "eval consumed at boundary")
        report["boundary"] = {
            "param_hash": bs["param_hash"],
            "num_timesteps": bs["num_timesteps"],
            "ppo_n_updates": bs["ppo_n_updates"],
            "optimizer_success": 1280,
            "eval_calls": 0}
        # 保存完整 RNG(保存前后四 RNG/内部态不变)
        env_id = id(env)
        model_env_ref = getattr(model, "env", None)
        last_obs = getattr(model, "_last_obs", None)
        ves_before = getattr(
            model_env_ref,
            "_last_episode_starts", None)
        les_before = getattr(
            model, "_last_episode_starts", None)
        ep_flag = getattr(env, "_terminated", None)
        before = rng_snapshot()
        before_env = env.rng.getstate()
        snap = rng_snapshot()
        snap["env_rng"] = env.rng.getstate()
        rpath = os.path.join(out_dir, "boundary_rng.pt")
        th.save(snap, rpath)
        after = rng_snapshot()
        ok_inv = (
            th.equal(after["torch"], before["torch"])
            and _np_eq(after["numpy"], before["numpy"])
            and after["python"] == before["python"]
            and env.rng.getstate() == before_env
            and id(env) == env_id
            and getattr(model, "_last_obs", None) is last_obs
            and getattr(env, "_terminated", None) is ep_flag
            and (getattr(model, "env", None)
                 is model_env_ref)
            and _vec_state_same(
                getattr(getattr(
                    model, "env", None),
                    "_last_episode_starts", None),
                ves_before)
            and _vec_state_same(
                getattr(model,
                        "_last_episode_starts",
                        None), les_before))
        report["boundary_rng_invariance"] = bool(ok_inv)
        if not ok_inv:
            raise RuntimeError(
                "RNG/state changed during boundary save")
        report["boundary_rng_sha256"] = sha256_file(rpath)
        why, _c, _p = book.checkpoint(
            "boundary")
        if why:
            raise RuntimeError(
                "budget(boundary): %s"
                % why)
        # ---- 阶段2:原进程续训至 65536 ----
        # 续段:唯一 counter 在真实 helper 内(成功/失败
        # 都同步该实例);run 不再外层同步(防双计)
        cont_learn = (
            continue_learner
            or _real_learn_continue)
        try:
            cont_learn(model, 32768, report,
                       ledger, book)
        except BaseException as exc:
            # 首因先固定;计数已由 helper 内同步
            report.setdefault(
                "train_fail_reason", repr(exc))
            _eb = getattr(model, "pilot_env", None)
            _oc = getattr(model, "_pilot_opt_count", None)
            report["fail_train_counts"] = {
                "env": int(getattr(
                    _eb, "n_steps_env", 0)),
                "model": int(getattr(
                    model, "num_timesteps", 0)),
                "n_updates": int(getattr(
                    model, "_n_updates", 0)),
                "optimizer": int(_oc["n"])
                if _oc else None}
            report["steps"]["continue"] = int(
                getattr(_eb, "n_steps_env", 0)) - \
                report["steps"]["replay"]
            raise
        if env.n_steps_env != 65536:
            raise RuntimeError(
                "extend env steps %d"
                % env.n_steps_env)
        report["steps"]["continue"] = env.n_steps_env - 32768
        ck = os.path.join(out_dir,
                          "B64_final")
        model.save(ck)
        report["B64_final_sha256"] = sha256_file(ck + ".zip")
        opt_count = getattr(model,
                            "_pilot_opt_count",
                            None)
        report["final_counts"] = {
            "env": env.n_steps_env,
            "model": int(
                getattr(model,
                        "num_timesteps", 0)),
            "n_updates": int(
                getattr(model,
                        "_n_updates", 0)),
            "optimizer":
                int(opt_count["n"])
            if opt_count else None}
        fc = report["final_counts"]
        if (fc["model"] != 65536
                or fc["n_updates"] != 640):
            raise RuntimeError(
                "final counts %r" % fc)
        if fc["optimizer"] != 2560:
            raise RuntimeError(
                "final optimizer calls %r"
                % fc["optimizer"])
        why, _c, _p = book.checkpoint(
            "post_train")
        if why:
            raise RuntimeError(
                "budget(post_train): %s"
                % why)
        # ---- 末端:旧 trace 评价+4 锚点 ----
        tr_list = traces if traces is not None else json.load(
                open(tr_file,
                     encoding="utf-8"))
        canon = hashlib.sha256(
            json.dumps(tr_list,
                       sort_keys=True,
                       separators=(
                           ",", ":"))
            .encode()).hexdigest()
        if canon != exp[
                "traces_canon_sha256"]:
            raise RuntimeError(
                "trace canon SHA")
        run_eval = eval_runner or SC._eval_on_traces

        def counted_eval(m, t, r, tag,
                         lg, bk):
            eval_calls["n"] += 1
            return run_eval(
                m, t, r, tag, lg, bk)
        SC._with_action_rng(
            spec["seeds"][
                "final_eval_action"],
            lambda: counted_eval(
                model, tr_list, report,
                "final_eval", ledger,
                book))
        report["final_eval_episodes"] = report.get(
                "final_eval_episodes", [])
        panel = panel_fn or SC._panel4_v2
        report["B64_panel"] = panel(model)
        if len(report["B64_panel"].get(
                "rows", [])) != 4:
            raise RuntimeError(
                "panel rows")
        eps = report.get(
            "final_eval_episodes", [])
        if len(eps) != 128:
            raise RuntimeError(
                "final eval episodes %d"
                % len(eps))
        if report["steps"]["final_eval"] > 2112:
            raise RuntimeError(
                "final eval steps cap")
        if ledger.total != 67648:
            raise RuntimeError(
                "total env steps %d"
                % ledger.total)
        model = None
        gc.collect()
        report["release_log"] = [
            {"after": "B64_done",
             "peak_rss_gib":
                 SC._peak_rss_gib()}]
        report[
            "total_real_env_steps"] = ledger.total
        why, cum, _p = book.checkpoint(
            "final")
        report["phases"] = \
            book.snapshot()
        report["budget_final"] = cum
        report["status"] = (
            "completed"
            if why is None
            else "failed")
        if why:
            report.setdefault(
                "fail_reason",
                "budget(final): %s" % why)
        with open(rp, "w",
                  encoding="utf-8") as f:
            json.dump(report, f,
                      indent=1,
                      allow_nan=False)
        why2, cum2, _p = book.checkpoint(
            "post_save")
        if why2:
            report["status"] = "failed"
            report[
                "budget_post_save"] = cum2
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
                "budget(post_save)"
                ": %s" % why2)
        os.replace(marker, os.path.join(
            out_dir, "DONE.marker"))
        return report
    except BaseException as exc:
        try:
            report["status"] = "failed"
            report.setdefault(
                "fail_reason", repr(exc))
            if model is not None:
                _eb = getattr(
                    model, "pilot_env",
                    None)
                if _eb is not None:
                    report[
                        "env_steps_at_fail"] \
                        = int(
                            getattr(
                                _eb,
                                "n_steps"
                                "_env",
                                0))
                try:
                    partial = os.path.join(
                        out_dir,
                        "partial_failure")
                    model.save(partial)
                    report[
                        "partial_sha256"] \
                        = sha256_file(
                            partial + ".zip")
                    report[
                        "partial_forensics"
                        "_only"] = True
                except BaseException as se:
                    report[
                        "partial_save_error"] \
                        = repr(se)
            report["phases"] = \
                book.snapshot()
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(report, f,
                          indent=1,
                          allow_nan=False)
        except BaseException:
            pass
        try:
            os.replace(marker,
                       os.path.join(
                           out_dir,
                           "FAILED"
                           ".marker"))
        except BaseException:
            pass
        raise


# ---------- 真实件(执行期) ----------

def _real_learn_replay(model, total,
                       report, ledger,
                       book):
    """重放 helper:唯一 counter 实例;成功/失败均同步;
    清理异常另列,原异常为主。"""
    env = model.pilot_env
    opt_counter = {"n": 0}
    R5._wrap_optimizer(
        model.policy.optimizer,
        book, opt_counter)
    model._pilot_opt_count = opt_counter
    cbk = R5._make_guard_callback(book, env)
    counter = SC._EnvCounter(env, ledger)
    SC._attach_counter(cbk, counter)
    try:
        model.learn(
            total_timesteps=total,
            reset_num_timesteps=True,
            callback=cbk,
            progress_bar=False)
    except BaseException:
        try:
            counter.sync()
        except BaseException as ce:
            report.setdefault(
                "replay_sync_error", repr(ce))
        raise
    counter.sync()


def _real_learn_continue(model, additional,
                         report, ledger,
                         book):
    """追加量语义:SB3 reset=False 时 total_timesteps
    =追加量(当前 32768+追加 32768=65536)。唯一 counter;
    成功/失败均同步;清理异常另列。"""
    env = model.pilot_env
    cbk = R5._make_guard_callback(book, env)
    counter = SC._EnvCounter(env, ledger)
    SC._attach_counter(cbk, counter)
    try:
        model.learn(
            total_timesteps=int(additional),
            reset_num_timesteps=False,
            callback=cbk,
            progress_bar=False)
    except BaseException:
        try:
            counter.sync()
        except BaseException as ce:
            report.setdefault(
                "continue_sync_error",
                repr(ce))
        raise
    counter.sync()


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="seed extend")
    ap.add_argument("out_dir")
    ap.add_argument("--spec",
                    default=SPEC_FILE)
    ap.add_argument(
        "--mode",
        choices=["official"],
        default="official")
    a = ap.parse_args(argv)
    run(a.out_dir, a.spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
