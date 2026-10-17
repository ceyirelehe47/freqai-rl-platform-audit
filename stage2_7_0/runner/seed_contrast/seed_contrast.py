# -*- coding: utf-8 -*-
"""seed_contrast v2 — A/B 单因素对照执行器(PREPARED_NOT_RUN)。

v2(审查方 4273 五组):
1. 身份=复用 R5.collect_identity(旧 p_spec)核当前源码/module 路径
   +快照入报告;effective_B=旧实际训练配置深拷贝仅改
   seeds.train_env=311002,**真实输入树比较**(任何其他差异即拒);
2. 初态/RNG 顺序:A_eval(load final→eval→del)→load A_initial
   取签名(param_hash+空 Adam/param_groups/num_timesteps)→del→
   fresh manual_seed 构造 B→比签名→此后不再 load;评价动作 RNG=
   事前固定独立 seed(全局三 RNG 严格 snapshot/finally 恢复);
3. learn 接回 R5._make_guard_callback/_wrap_optimizer+实际 env
   计数;预算覆盖训练/评价 bar/最终保存;总步分段检查;
   CLI main+launch(inner 900s)复用;
4. 输出:128 trace 先存盘+SHA,A/B 引用同 SHA+episode 索引;
   同 trace 纯 ledger 基线(零新增 env 步);B 4 行复用
   diag_panel v2 行级合同(同次 raw8/hook/obsSHA/质量校验/
   HOLD mode w=0);A 面板引用 af2dd1c3…;
5. _peak_rss_gib 如实命名(ru_maxrss=峰值)。
"""
import argparse
import copy
import gc
import hashlib
import json
import math
import os
import random
import resource
import sys
import time

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
PILOT = os.environ.get(
    "SEED_CONTRAST_PILOT",
    "/mnt/f/trading/teaching_pilot_prep_20261016")
DIAG = os.environ.get(
    "SEED_CONTRAST_DIAG",
    "/mnt/f/trading/diag_panel_prep_20261016")
for _p in (_HERE, PILOT, DIAG):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

STATUS = "PREPARED_NOT_RUN"
A_FINAL = ("/mnt/f/trading/"
           "unified_teaching_pilot_a1_"
           "20261016_output/final.zip")
A_INITIAL = ("/mnt/f/trading/"
             "unified_teaching_pilot_a1_"
             "20261016_output/initial.zip")
A_PANEL_JSON_SHA = ("af2dd1c393d0230db664"
                    "a28404ef9027492a2aa1"
                    "a1ef5397dc38206fbca2"
                    "70b8")
BUDGET = {"wall_s": 900.0, "cpu_s": 600.0,
          "rss_gib": 1.0}
RUNSPEC_SHA256 = ("fe7ec68bbaa4dffc87b03de"
                  "f1c4510000def356dfa790f4"
                  "ec11d504745a546f6")
DIAG_PANEL_SHA256 = ("5ebd5fa6a39b6d9a56e0d"
                     "0500c27a60d3e82530e04"
                     "f7eda4d8b1edf6da1ddfd"
                     "2")
EVAL_CAP = 2112


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def _peak_rss_gib():
    """ru_maxrss=进程峰值(非释放后当前值),如实命名。"""
    return (resource.getrusage(
        resource.RUSAGE_SELF).ru_maxrss
            / (1024.0 * 1024.0))


def param_hash(policy):
    sd = policy.state_dict()
    h = hashlib.sha256()
    for k in sorted(sd):
        t = sd[k].detach().cpu().contiguous()
        h.update(k.encode())
        h.update(np.ascontiguousarray(
            t.numpy()).tobytes())
    return h.hexdigest()


def _param_spec(policy):
    """逐参数 key/shape/dtype/numel(全列)。"""
    sd = policy.state_dict()
    return sorted(
        (k, tuple(t.shape),
         str(t.dtype), t.numel())
        for k, t in sd.items())


def _opt_content_hash(optimizer):
    """Adam state/param_groups 完整内容规范化哈希。"""
    import runner as R5
    opt_sd = optimizer.state_dict()

    def norm(o):
        if isinstance(o, th.Tensor):
            t = o.detach().cpu().contiguous()
            return ("T", str(t.dtype),
                    tuple(t.shape),
                    hashlib.sha256(
                        np.ascontiguousarray(
                            t.numpy())
                        .tobytes())
                    .hexdigest())
        if isinstance(o, dict):
            return ("D", sorted(
                (k, norm(v))
                for k, v in o.items()))
        if isinstance(o, (list, tuple)):
            return ("L", [norm(x)
                          for x in o])
        return ("S", repr(o))
    return hashlib.sha256(repr(norm(
        opt_sd)).encode()).hexdigest()


def fresh_signature(model):
    """初态签名 v2:param_spec(键/形/dtype/长)+Adam 完整
    内容哈希+空 state 断言+num_timesteps/_n_updates=0。"""
    opt_sd = model.policy.optimizer.\
        state_dict()
    if len(opt_sd["state"]) != 0:
        raise RuntimeError(
            "initial Adam state not empty")
    return {
        "param_hash": param_hash(
            model.policy),
        "param_spec": _param_spec(
            model.policy),
        "n_param_groups": len(
            opt_sd["param_groups"]),
        "optimizer_content_hash":
            _opt_content_hash(
                model.policy.optimizer),
        "optimizer_state_entries":
            len(opt_sd["state"]),
        "num_timesteps": int(
            getattr(model,
                    "num_timesteps", 0)),
        "ppo_n_updates": int(
            getattr(model,
                    "_n_updates", 0))}


def tree_diff(a, b, path=""):
    """真实树差异列表(叶子路径级;根无点前缀)。"""
    out = []
    if type(a) is not type(b):
        out.append(path + " (type)")
        return out
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s%s (only-B)"
                           % (path + "." if path else "", k))
            elif k not in b:
                out.append("%s%s (only-A)"
                           % (path + "." if path else "", k))
            else:
                out += tree_diff(
                    a[k], b[k],
                    "%s.%s" % (path, k)
                    if path else k)
    elif isinstance(a, list):
        if len(a) != len(b):
            out.append(path + " (len)")
        else:
            for i, (x, y) in enumerate(
                    zip(a, b)):
                out += tree_diff(
                    x, y,
                    "%s[%d]" % (path, i))
    else:
        if a != b:
            out.append("%s: %r -> %r"
                       % (path, a, b))
    return out


def build_effective_B(old_spec, new_env_seed):
    b = copy.deepcopy(old_spec)
    b["seeds"]["train_env"] = int(new_env_seed)
    return b


def diff_against_a1(old_spec, eff_B):
    """真实比较:差异必须恰为 seeds.train_env 一叶。"""
    diffs = tree_diff(old_spec, eff_B)
    allowed = {"seeds.train_env"}
    bad = [d for d in diffs
           if d.split(":")[0].strip().lstrip(".")
           not in allowed]
    if bad or len(diffs) != 1:
        raise RuntimeError(
            "effective_B diffs not "
            "single train_env: %r" % diffs)
    return diffs


class Book:
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
        rss = _peak_rss_gib()
        self.phases.setdefault(
            phase, {}).update(
            {"wall_s": wall, "cpu_s": cpu,
             "peak_rss_gib": rss})
        why = None
        if wall > self.limits["wall_s"]:
            why = "wall_clock"
        elif cpu > self.limits["cpu_s"]:
            why = "cpu"
        elif rss > self.limits["rss_gib"]:
            why = "rss"
        return why, {"wall_s": wall,
                     "cpu_s": cpu,
                     "peak_rss_gib": rss}, dict(
            self.phases)

    def snapshot(self):
        return dict(self.phases)


class StepLedger:
    """总步分段账(非仅末尾检查)。"""

    def __init__(self, cap, report):
        self.cap = cap
        self.report = report
        self.total = 0

    def add(self, n, tag):
        self.total += n
        self.report[
            "total_real_env_steps"] = \
            self.total
        if self.total > self.cap:
            raise RuntimeError(
                "total env steps %d>%d at %s"
                % (self.total, self.cap,
                   tag))


class _EnvCounter:
    """增量同步:delta=now-seen→seen=now→ledger.add(delta)
    (幂等:重复 sync 第二次 delta=0 不双加)。"""

    def __init__(self, env, ledger):
        self._env = env
        self._ledger = ledger
        self._seen = int(
            getattr(env, "n_steps_env", 0))

    def sync(self):
        now = int(getattr(
            self._env, "n_steps_env", 0))
        delta = now - self._seen
        self._seen = now
        if delta > 0:
            self._ledger.add(
                delta, "train_env")


def _attach_counter(cbk, counter):
    """包 R5 原生 BaseCallback 实例:仅 _on_step 前同步计数,
    init/locals/rollout 生命周期全保留。"""
    old_step = cbk._on_step

    def counted_on_step():
        counter.sync()
        return old_step()
    cbk._on_step = counted_on_step


def _snapshot_rng():
    return (th.get_rng_state(),
            np.random.get_state(),
            random.getstate())


def _restore_rng(snap):
    th.set_rng_state(snap[0])
    np.random.set_state(snap[1])
    random.setstate(snap[2])


def _with_action_rng(seed, fn):
    """评价动作 RNG:事前固定 seed,严格 snapshot/finally。"""
    snap = _snapshot_rng()
    th.manual_seed(seed)
    np.random.seed(seed % (2 ** 31))
    random.seed(seed)
    try:
        return fn()
    finally:
        _restore_rng(snap)


def run(out_dir, spec_path, loader=None,
        builder=None, learner=None,
        clock=None, traces=None,
        eval_runner=None, panel_fn=None):
    import runner as R5
    import teach_env as TE
    import trace_lock as TL
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir, "RUNNING.marker")
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "contrast.json")
    report = {"status": "running",
              "course_gate": "not_frozen",
              "steps": {"A_eval": 0, "B_eval": 0,
                        "B_train": 0},
              "phases": {}}
    book = Book(clock=clock)
    ledger = None
    model_b = None
    try:
        spec = json.load(open(spec_path, encoding="utf-8"))
        report["spec_sha256"] = sha256_file(spec_path)
        if report["spec_sha256"] != RUNSPEC_SHA256:
            raise RuntimeError(
                "RUNSPEC SHA mismatch (expect "
                "%s)" % RUNSPEC_SHA256)
        p_spec_path = os.path.join(PILOT, "run_spec.json")
        p_spec = json.load(open(p_spec_path, encoding="utf-8"))
        # ---- 1. 身份(R5 复用)+唯一变因真实比较 ----
        report["identity"] = R5.collect_identity(p_spec)
        eff_B = build_effective_B(
            p_spec, spec["seeds"]["train_env_B"])
        report["only_change"] = diff_against_a1(
            p_spec, eff_B)
        # eff_B 控制执行;新 spec 同义字段必须与 eff_B 一致
        if spec["seeds"]["torch_init"] != \
                eff_B["seeds"]["torch_init"]:
            raise RuntimeError(
                "spec torch_init != eff_B")
        if spec["seeds"]["train_env_B"] != \
                eff_B["seeds"]["train_env"]:
            raise RuntimeError(
                "spec train_env_B != eff_B")
        if spec["arms"]["B"]["train_steps"] != \
                eff_B["ppo"]["total_teach_steps"]:
            raise RuntimeError(
                "spec train_steps != eff_B")
        report["eff_B_canon_sha256"] = hashlib.sha256(
            json.dumps(eff_B, sort_keys=True,
                       separators=(",", ":"))
            .encode()).hexdigest()
        exp = spec["identity_expected"]
        if sha256_file(A_FINAL) != exp["a1_final_sha256"]:
            raise RuntimeError("A final SHA")
        if sha256_file(A_INITIAL) != exp["a1_initial_sha256"]:
            raise RuntimeError("A initial SHA")
        if sha256_file(p_spec_path) != \
                exp["teaching_pilot_run_spec_sha256"]:
            raise RuntimeError("pilot run_spec SHA")
        # A 面板引用(不重跑)
        a_panel = ("/mnt/f/trading/"
                   "diag_panel_a1_20261016_output/"
                   "diag_panel.json")
        if sha256_file(a_panel) != A_PANEL_JSON_SHA:
            raise RuntimeError("A panel JSON SHA")
        report["A_panel_reference"] = {
            "path": a_panel,
            "sha256": A_PANEL_JSON_SHA}
        ledger = StepLedger(
            spec["budget"]["caps"]["total_real_env_steps"],
            report)
        why, _c, _p = book.checkpoint("identity")
        if why:
            raise RuntimeError("budget(identity): %s" % why)
        # ---- 4. 共同 trace 先存盘+SHA ----
        tr_list = traces if traces is not None \
            else TL.build_all(spec["seeds"]["trace_base"])
        tr_canon = json.dumps(
            tr_list, sort_keys=True,
            separators=(",", ":"))
        tr_sha = hashlib.sha256(
            tr_canon.encode()).hexdigest()
        tr_file = os.path.join(out_dir, "traces.json")
        with open(tr_file, "w", encoding="utf-8") as f:
            f.write(tr_canon)
        report["trace_file_sha256_raw"] = \
            sha256_file(tr_file)
        report["trace_canon_sha256"] = tr_sha
        report["trace_count"] = len(tr_list)
        why, _c, _p = book.checkpoint("trace_lock")
        if why:
            raise RuntimeError("budget(trace): %s" % why)
        load = loader or _real_load
        run_eval = eval_runner or _eval_on_traces
        panel = panel_fn or _panel4_v2
        # ---- A 评价(load final→eval→del) ----
        model_a = load(A_FINAL)
        st_a = _with_action_rng(
            spec["seeds"]["eval_action_A"],
            lambda: run_eval(
                model_a, tr_list, report,
                "A_eval", ledger, book))
        del model_a
        gc.collect()
        report.setdefault("release_log", []).append(
            {"after": "A_eval", "gc_done": True,
             "peak_rss_gib": _peak_rss_gib()})
        why, _c, _p = book.checkpoint("post_A_release")
        if why:
            raise RuntimeError("budget(post_A_release): %s" % why)
        # ---- A initial 签名→释放→fresh 构造 B ----
        a_init = load(A_INITIAL)
        sig_a = fresh_signature(a_init)
        del a_init
        gc.collect()
        report["initial_signature_A"] = sig_a
        build = builder or _real_build_b
        th.manual_seed(eff_B["seeds"]["torch_init"])
        model_b = build(eff_B, eff_B)
        sig_b = fresh_signature(model_b)
        report["initial_signature_B"] = sig_b
        if sig_b != sig_a:
            raise RuntimeError(
                "B initial signature != a1 "
                "initial: %r vs %r"
                % (sig_b, sig_a))
        ck_init = os.path.join(out_dir, "B_initial")
        model_b.save(ck_init)
        report["B_initial_sha256"] = \
            sha256_file(ck_init + ".zip")
        why, _c, _p = book.checkpoint("B_built")
        if why:
            raise RuntimeError("budget(B_built): %s" % why)
        # ---- B 训练(guard+wrap+实际 env 计数) ----
        opt_counter = {"n": 0}
        env_b = getattr(model_b, "pilot_env", None)
        R5._wrap_optimizer(
            model_b.policy.optimizer, book,
            opt_counter)
        learn = learner or _real_learn
        n_train = eff_B["ppo"]["total_teach_steps"]
        counter = None
        cbk = None
        if env_b is not None:
            cbk = R5._make_guard_callback(
                book, env_b)
            counter = _EnvCounter(
                env_b, ledger)
            _attach_counter(cbk, counter)
        try:
            learn(model_b, n_train, report,
                  callback=cbk)
        except BaseException:
            # 首因先固定,再同步(幂等 delta,不双加)
            report.setdefault(
                "train_fail_reason",
                repr(sys.exc_info()[1]))
            if counter is not None:
                counter.sync()
            raise
        if counter is not None:
            counter.sync()      # 成功收尾
        report["steps"]["B_train"] = int(
            getattr(model_b, "num_timesteps", 0))
        if env_b is not None:
            if env_b.n_steps_env != n_train:
                raise RuntimeError(
                    "env steps %d != %d"
                    % (env_b.n_steps_env,
                       n_train))
        rollouts = (n_train
                    // eff_B["ppo"]["n_steps"])
        exp_updates = (rollouts
                       * eff_B["ppo"]["epochs"])
        exp_opt = (exp_updates
                   * (eff_B["ppo"]["n_steps"]
                      // eff_B["ppo"]
                      ["batch_size"]))
        report["train_counts"] = {
            "env_steps": env_b.n_steps_env,
            "model_timesteps": int(
                getattr(model_b,
                        "num_timesteps", 0)),
            "ppo_n_updates": int(
                getattr(model_b,
                        "_n_updates", 0)),
            "optimizer_success":
                opt_counter["n"]}
        if env_b.n_steps_env != n_train:
            raise RuntimeError("env steps")
        if report["train_counts"][
                "model_timesteps"] != n_train:
            raise RuntimeError("model steps")
        if report["train_counts"][
                "ppo_n_updates"] != exp_updates:
            raise RuntimeError(
                "_n_updates %d != %d"
                % (report["train_counts"][
                       "ppo_n_updates"],
                   exp_updates))
        if opt_counter["n"] != exp_opt:
            raise RuntimeError(
                "optimizer calls %d != %d"
                % (opt_counter["n"],
                   exp_opt))
        report["optimizer_calls_success"] = \
            opt_counter["n"]
        ck_fin = os.path.join(out_dir, "B_final")
        model_b.save(ck_fin)
        report["B_final_sha256"] = \
            sha256_file(ck_fin + ".zip")
        why, _c, _p = book.checkpoint("post_learn_save")
        if why:
            raise RuntimeError(
                "budget(post_learn_save): %s" % why)
        # ---- B 评价+B 面板 ----
        st_b = _with_action_rng(
            spec["seeds"]["eval_action_B"],
            lambda: run_eval(
                model_b, tr_list, report,
                "B_eval", ledger, book))
        report["B_panel"] = panel(model_b)
        if len(report["B_panel"].get(
                "rows", [])) != 4:
            raise RuntimeError("panel rows")
        for _tag in ("A_eval", "B_eval"):
            eps = report.get(
                _tag + "_episodes", [])
            if len(eps) != 128:
                raise RuntimeError(
                    "%s episodes %d"
                    % (_tag, len(eps)))
            if report["steps"][_tag] \
                    > EVAL_CAP:
                raise RuntimeError(
                    "%s steps cap" % _tag)
        # ---- 同 trace 纯 ledger 基线(零新增 env 步) ----
        report["baselines"] = _trace_baselines(tr_list)
        model_b = None      # 不 del:晚异常仍可读局部
        gc.collect()
        report["release_log"].append(
            {"after": "B_done", "gc_done": True,
             "peak_rss_gib": _peak_rss_gib()})
        why, cum, _p = book.checkpoint("final")
        report["phases"] = book.snapshot()
        report["budget_final"] = cum
        report["status"] = ("completed"
                            if why is None
                            else "failed")
        if why:
            report.setdefault(
                "fail_reason",
                "budget(final): %s" % why)
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1,
                      allow_nan=False)
        why2, cum2, _p = book.checkpoint(
            "post_save")
        if why2:
            report["status"] = "failed"
            report["budget_post_save"] = cum2
            report.setdefault(
                "fail_reason",
                "budget(post_save): %s" % why2)
            with open(rp, "w",
                      encoding="utf-8") as f:
                json.dump(report, f, indent=1,
                          allow_nan=False)
            os.replace(marker, os.path.join(
                out_dir, "FAILED.marker"))
            raise RuntimeError(
                "budget(post_save): %s" % why2)
        os.replace(marker, os.path.join(
            out_dir, "DONE.marker"))
        return report
    except BaseException as exc:
        try:
            report["status"] = "failed"
            report.setdefault("fail_reason",
                              repr(exc))
            if "opt_counter" in locals() \
                    and opt_counter is not None:
                report[
                    "optimizer_calls_success"] = \
                    int(opt_counter["n"])
            if model_b is not None:
                report["steps"]["B_train"] = int(
                    getattr(model_b, "num_timesteps", 0))
                report["ppo_n_updates_fail"] = \
                    int(getattr(model_b,
                                "_n_updates", 0))
                _eb = getattr(model_b,
                              "pilot_env", None)
                if _eb is not None:
                    report[
                        "env_steps_at_fail"] = \
                        int(getattr(_eb,
                                    "n_steps_env",
                                    0))
            report["phases"] = book.snapshot()
            if model_b is not None:
                try:
                    partial = os.path.join(
                        out_dir, "partial_failure")
                    model_b.save(partial)
                    report["partial_checkpoint"] = \
                        partial + ".zip"
                    report["partial_sha256"] = \
                        sha256_file(partial + ".zip")
                    report["partial_forensics_only"] = True
                except BaseException as se:
                    report["partial_save_error"] = \
                        repr(se)
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


# ---------------- 真实件(执行期;准备期不触) ----------------

def _real_load(path):
    from stable_baselines3 import PPO
    return PPO.load(path, device="cpu")


def _real_build_b(spec, p_spec):
    import runner as R5
    import teach_env as TE
    env = TE.UnifiedPilotEnv(
        random.Random(
            spec["seeds"]["train_env"]))
    model = R5.build_real_ppo(
        env, spec["seeds"]["torch_init"],
        p_spec)
    model.pilot_env = env   # 计数/guard 锚
    return model


def _real_learn(model, total, report,
                callback=None):
    model.learn(total_timesteps=total,
                reset_num_timesteps=True,
                callback=callback,
                progress_bar=False)


def _eval_on_traces(model, traces, report,
                    tag, ledger, book):
    """锁定 trace 评价(stub 或真实 policy);bar 级预算。"""
    import teach_env as TE
    from rl_posctl.ledger import (
        TwoSidedLinearLedger)
    policy = model.policy
    try:
        policy.set_training_mode(False)
    except Exception:
        pass
    steps = 0
    episodes = []
    for idx, tr in enumerate(traces):
        led = TwoSidedLinearLedger()
        price = 1.0
        rem = tr["remaining"]
        total = 0.0
        failed = None
        for stt in tr["steps"]:
            obs = th.tensor([[
                stt["c"], stt["g"], stt["q"],
                stt["s"],
                _asinh(led.exposure_ratio(price)),
                _asinh(min(
                    led.solvency_ratio(price),
                    40.0)),
                rem / 128.0, 32.0 / 128.0]],
                dtype=th.float32)
            with th.no_grad():
                a = policy.predict(
                    obs, deterministic=False)[0]
            br, w = TE.UnifiedPilotEnv._decode(a)
            steps += 1
            ledger.add(1, tag)
            if steps > EVAL_CAP:
                raise RuntimeError(
                    "eval cap %s" % tag)
            open_p = price
            eq0 = led.equity(open_p)
            if eq0 <= 0.0:
                failed = "open<=0"
                total = float("-inf")
                break
            if (led.qty != 0.0
                    and eq0 < TE.MAINT
                    * abs(led.qty) * open_p):
                led.risk_flatten(open_p)
                if led.equity(open_p) <= 0.0:
                    failed = "flatten<=0"
                    total = float("-inf")
                    break
            if br == 0:
                led.hold(open_p)
            else:
                led.apply_target_ratio(w, open_p)
            if led.equity(open_p) <= 0.0:
                failed = "post_fee<=0"
                total = float("-inf")
                break
            r = stt["r"]
            close = open_p * (1.0 + r)
            if rem <= 1:
                led.liquidate(close)
                eqf = led.equity(close)
                if eqf <= 0.0:
                    failed = "terminal<=0"
                    total = float("-inf")
                else:
                    total += math.log(eqf / eq0)
                break
            eqc = led.equity(close)
            if eqc <= 0.0:
                failed = "close<=0"
                total = float("-inf")
                break
            if (led.qty != 0.0
                    and eqc < TE.MAINT
                    * abs(led.qty) * close):
                led.risk_flatten(close)
                if led.equity(close) <= 0.0:
                    failed = "close_flat<=0"
                    total = float("-inf")
                    break
            total += math.log(
                led.equity(close) / eq0)
            price = close
            rem -= 1
        if idx % 16 == 0:
            why, _c, _p = book.checkpoint(
                "eval_%s_ep%d" % (tag, idx))
            if why:
                raise RuntimeError(
                    "budget(eval %s ep%d): %s"
                    % (tag, idx, why))
        episodes.append({
            "index": idx,
            "remaining": tr["remaining"],
            "s0": tr["s0"],
            "valid": failed is None,
            "net_log": (None if failed
                        else total),
            "failed": failed})
    report["steps"][tag] = steps
    report[tag + "_episodes"] = episodes
    return steps


def _asinh(x):
    if not math.isfinite(x):
        x = math.copysign(1e9, x if x else 1)
    return math.asinh(x) / 4.0


def _panel4_v2(model):
    """B 4 锚点=diag_panel v2 行级合同复用。"""
    import diag_panel as DPv2
    policy = model.policy
    policy.set_training_mode(False)
    obs_np = np.array(
        [DPv2.make_obs(r, s)
         for r, s in DPv2.STATES],
        dtype="<f4", order="C")
    obs_sha = hashlib.sha256(
        obs_np.tobytes(order="C")).hexdigest()
    if obs_sha != DPv2.OBS_BYTES_SHA256:
        raise RuntimeError("obs SHA %s" % obs_sha)
    obs = th.from_numpy(obs_np.copy())
    captured = {}

    def hook(mod, inp, out):
        captured["raw8"] = (
            out.detach().cpu().numpy())
    h = policy.action_net.\
        register_forward_hook(hook)
    try:
        with th.no_grad():
            view = policy.get_distribution(obs)
            raw = captured.get("raw8")
            if raw is None or raw.shape != (4, 8):
                raise RuntimeError("hook raw8")
            rows = []
            for i, (r, s) in enumerate(
                    DPv2.STATES):
                rows.append(DPv2._row(
                    "B_final", r, s,
                    DPv2._Subview(view, i),
                    raw[i]))
    finally:
        h.remove()
    if len(rows) != 4:
        raise RuntimeError("panel rows %d" % len(rows))
    for row in rows:
        c = row["checks"]
        if abs(c["cond_atoms_plus_I"] - 1.0) > DPv2.TOL:
            raise RuntimeError("cond sum")
        if abs(c["uncond_total"] - 1.0) > DPv2.TOL:
            raise RuntimeError("uncond sum")
    return {"obs_sha256": obs_sha,
            "rows": rows}


def _trace_baselines(traces):
    """同 trace 纯 ledger 基线(零 env 步)。"""
    import teach_env as TE
    from rl_posctl.ledger import (
        TwoSidedLinearLedger)
    import eval_pilot as EP

    def replay(tr, act):
        led = TwoSidedLinearLedger()
        price = 1.0
        rem = tr["remaining"]
        total = 0.0
        for stt in tr["steps"]:
            open_p = price
            eq0 = led.equity(open_p)
            if eq0 <= 0.0:
                return {"valid": False,
                        "net_log": None,
                        "raw_marker": "-inf"}
            if (led.qty != 0.0
                    and eq0 < TE.MAINT
                    * abs(led.qty) * open_p):
                led.risk_flatten(open_p)
                if led.equity(open_p) <= 0.0:
                    return {"valid": False,
                            "net_log": None,
                            "raw_marker": "-inf"}
            w = act(stt)
            if w is None:
                led.hold(open_p)
            else:
                led.apply_target_ratio(w, open_p)
            if led.equity(open_p) <= 0.0:
                return {"valid": False,
                        "net_log": None,
                        "raw_marker": "-inf"}
            close = open_p * (1.0 + stt["r"])
            if rem <= 1:
                led.liquidate(close)
                eqf = led.equity(close)
                if eqf <= 0.0:
                    return {"valid": False,
                            "net_log": None,
                            "raw_marker": "-inf"}
                return {"valid": True,
                        "net_log": total
                        + math.log(eqf / eq0),
                        "raw_marker": None}
            eqc = led.equity(close)
            if eqc <= 0.0:
                return {"valid": False,
                        "net_log": None,
                        "raw_marker": "-inf"}
            if (led.qty != 0.0
                    and eqc < TE.MAINT
                    * abs(led.qty) * close):
                led.risk_flatten(close)
                if led.equity(close) <= 0.0:
                    return {"valid": False,
                            "net_log": None,
                            "raw_marker": "-inf"}
            total += math.log(
                led.equity(close) / eq0)
            price = close
            rem -= 1
        return {"valid": True,
                "net_log": total,
                "raw_marker": None}
    out = {"all_HOLD_analytic": 0.0}
    for name, fn in (
            ("const_long",
             lambda st: 1.0),
            ("const_short",
             lambda st: -1.0),
            ("signal_full",
             lambda st: float(np.sign(
                 st["s"] * st["c"]
                 * st["q"])))):
        out[name] = [
            {"index": i,
             **replay(tr, fn)}
            for i, tr in enumerate(traces)]
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="seed contrast")
    ap.add_argument("out_dir")
    ap.add_argument("--spec", required=True)
    ap.add_argument("--mode",
                    choices=["official"],
                    default="official")
    a = ap.parse_args(argv)
    if a.mode != "official":
        raise SystemExit("unknown mode")
    run(a.out_dir, a.spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
