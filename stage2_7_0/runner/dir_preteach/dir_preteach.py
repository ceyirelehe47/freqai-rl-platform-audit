# -*- coding: utf-8 -*-
"""dir_preteach v2 — B 方向有限因果预教学执行器
(PREPARED_NOT_RUN;准备期零真实 forward/rollout/learn)。

v2(审查方 4704 五组):
1. 真实 policy 链:extract_features→mlp_extractor.
   forward_actor→action_net raw8;p=softmax(raw[:,2:6]),
   a/b=softplus(raw[:,6/7])+1;m=p⁺−p⁻+p_cont·(a−b)/(a+b);
   仅 actor 参数,branch 前 2 列不进方向 loss;
   损失=mean(relu(.05−y·m)²)(固定裕度 .05,教学候选
   非最优/非毕业门);
2. sig_equal_json 用 SX 已验版;删 rng_fresh(20261017);
   fresh build 后保存并核四 RNG/_last_obs/episode 标志/
   对象身份;辅助与面板零随机流;辅助后仅清空 PPO Adam
   (param_groups 不变核);先消费冻结 pilot run_spec 身份;
3. _panel8 真实实现:3×8=辅助前/后/PPO 后各一 batch
   (2 H32 q1+4 H32 q{.5,.25}+2 H1 q1,各 s±;实际 q 观测);
   评价旁读 2112 动作/128 段零额外 forward;硬核
   PPO 32768/320/1280·eval 2112/128·总 34880;
4. 每辅助更新前后同 book 预算检查;有限性+成功计数入
   partial;首次 final 超限立即 raise(failed≠DONE/rc0);
   保存失败不覆盖首因;资源覆盖全阶段;
5. launcher 补冻结 SX 复制/SHA+SEED_EXTEND_DIR=SNAP/sc。
"""
import argparse
import copy
import hashlib
import json
import math
import os
import random
import sys

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.environ.get(
    "SEED_EXTEND_DIR",
    "/mnt/f/trading/seed_extend_prep_20261017")
SC_DIR = os.environ.get(
    "SEED_CONTRAST_DIR",
    "/mnt/f/trading/seed_contrast_prep_20261016")
PILOT = os.environ.get(
    "SEED_CONTRAST_PILOT",
    "/mnt/f/trading/teaching_pilot_prep_20261016")
DIAG = os.environ.get(
    "SEED_CONTRAST_DIAG",
    "/mnt/f/trading/diag_panel_prep_20261016")
for _p in (_HERE, EXT_DIR, SC_DIR, PILOT, DIAG):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import seed_contrast as SC  # noqa: E402
import seed_extend as SX  # noqa: E402
import runner as R5  # noqa: E402

STATUS = "PREPARED_NOT_RUN"
RUNSPEC_SHA256 = "ebce9f61a7399fb666319e94c17e1dcbd33d60ede325689eacebb2e1afa1f885"
AUX_UPDATES = 256
AUX_LR = 3e-4
AUX_MARGIN = 0.05
EVAL_CAP_STEPS = 2112
TOTAL_CAP = 34880


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def actor_raw8(model, obs):
    """真实链:extract_features→forward_actor→action_net。"""
    policy = model.policy
    feats = policy.extract_features(
        obs)
    lat = policy.mlp_extractor.forward_actor(feats)
    raw = policy.action_net(lat)
    return raw


def rebal_cond_mean_raw(raw):
    """p=softmax(raw[2:6]);a/b=softplus(raw[6/7])+1;
    m=p⁺−p⁻+p_cont·(a−b)/(a+b)。仅 REBAL 条件均值,
    branch 列(raw[:2])不进方向损失。"""
    p = th.softmax(raw[:, 2:6], dim=-1)
    a = th.nn.functional.softplus(
        raw[:, 6]) + 1.0
    b = th.nn.functional.softplus(
        raw[:, 7]) + 1.0
    # mix 顺序: [-1, 0, +1, cont](与解码原子一致)
    return (p[:, 2] - p[:, 0]
            + p[:, 3] * (a - b) / (a + b))


def actor_params(policy):
    """仅 actor 侧参数(features 共享+actor MLP+action_net);
    value 参数不进辅助优化(按名过滤 value)。"""
    return [p_ for n_, p_ in
            policy.named_parameters()
            if "value" not in n_]


def aux_objective_raw(raw, y):
    """mean(relu(.05−y·m)²)——固定裕度教学候选;
    不监督 branch/不锁最优/非毕业门。"""
    m = rebal_cond_mean_raw(raw)
    viol = th.relu(
        AUX_MARGIN - y * m)
    return (viol ** 2).mean(), m


def preteach_actor(model, obs, y,
                   n_updates, book,
                   report):
    """纯监督固定批:恰 n_updates 次;每更新前后预算
    book 检查;零 env 步/零随机流(确定性输入)。"""
    opt = th.optim.Adam(
        actor_params(model.policy),
        lr=AUX_LR)
    hist = []
    succ = 0
    _aux_keep_live(report, hist)
    for i in range(int(n_updates)):
        why, _c, _p = book.checkpoint(
            "aux_u%d_pre" % i)
        if why:
            report.setdefault(
                "fail_reason",
                "budget(aux_u%d_pre):"
                " %s" % (i, why))
            raise RuntimeError(
                "budget(aux_u%d_pre):"
                " %s" % (i, why))
        opt.zero_grad()
        raw = actor_raw8(model, obs)
        loss, m = aux_objective_raw(
            raw, y)
        if not th.isfinite(loss):
            raise RuntimeError(
                "non-finite aux loss @%d"
                % i)
        loss.backward()
        grads_finite = all(
            th.isfinite(
                p_.grad).all()
            for grp in
            opt.param_groups
            for p_ in
            grp["params"]
            if p_.grad is not None)
        if not grads_finite:
            raise RuntimeError(
                "non-finite grad @%d"
                % i)
        opt.step()
        params_finite = all(
            th.isfinite(p_).all()
            for p_ in
            actor_params(
                model.policy))
        if not params_finite:
            raise RuntimeError(
                "non-finite params @%d"
                % i)
        succ += 1
        hist.append({
            "i": i,
            "loss": float(
                loss.detach()),
            "margin_min": float(
                (y * m).detach()
                .min()),
            "grads_finite":
                bool(grads_finite),
            "params_finite":
                bool(params_finite)})
        report["aux_success"] = succ
        _aux_keep_live(report, hist)
        why, _c, _p = book.checkpoint(
            "aux_u%d_post" % i)
        if why:
            report.setdefault(
                "fail_reason",
                "budget(aux_u%d_post)"
                ": %s" % (i, why))
            raise RuntimeError(
                "budget(aux_u%d_post)"
                ": %s" % (i, why))
    report["aux_history_tail"] = hist[-3:]
    report["aux_history_n"] = len(hist)
    return hist


def _aux_keep_live(report, hist):
    """中断路径兜底:保留 live hist(成功路径
    末尾同样调用,幂等)。"""
    report["aux_history_tail"] = hist[-3:]
    report["aux_history_n"] = len(hist)
    report["aux_live_hist_n"] = len(hist)
    return hist


def aux_inputs():
    """恰 4 合法 flat H32 输入(s±×q{1,.75})。"""
    states = [(32, 1, 1.0), (32, 1, 0.75),
              (32, -1, 1.0),
              (32, -1, 0.75)]

    def mk(rem, s, q):
        return [1.0, 0.0, float(q),
                float(s), 0.0,
                math.asinh(40.0) / 4.0,
                rem / 128.0,
                32.0 / 128.0]
    obs = th.tensor(
        [mk(*st) for st in states],
        dtype=th.float32)
    y = th.tensor(
        [float(np.sign(s * q))
         for _, s, q in states],
        dtype=th.float32)
    canon = hashlib.sha256(
        obs.detach().numpy()
        .astype("<f4").tobytes()
    ).hexdigest()
    return states, obs, y, canon


PANEL8_STATES = [
    (32, 1, 1.0), (32, -1, 1.0),
    (32, 1, 0.5), (32, -1, 0.5),
    (32, 1, 0.25), (32, -1, 0.25),
    (1, 1, 1.0), (1, -1, 1.0)]
AUX_OBS_SHA256 = "50aaa47e3b7baeededd67d6950b8aec1e070883e981acab45e6abfe157fcf79e"
PANEL8_OBS_SHA256 = ("717879654dba0f3b7"
                     "561e3ce3839002d9a2"
                     "0526acd7a6aed30074"
                     "8ebc74d8ce9")


def _obs_matrix(states):
    """固定输入 little-endian float32 C-order(实际 q)。"""

    def mk(rem, s, q):
        return [1.0, 0.0, float(q),
                float(s), 0.0,
                math.asinh(40.0) / 4.0,
                rem / 128.0,
                32.0 / 128.0]
    arr = np.array(
        [mk(*st) for st in states],
        dtype="<f4")
    return th.tensor(
        arr.astype(np.float32))


def _obs_sha(matrix):
    arr = matrix.detach() \
        .numpy().astype(
            "<f4")
    return hashlib.sha256(
        arr.tobytes(
            order="C")).hexdigest()


def panel8(model, tag):
    """全量 8 行:同一次 hook+get_distribution,复用
    diag._Subview/_row(实际 q 观测,非默认 q1);
    P_hold/有效 flat/P0 公开 mode/原子/I/Z/质量齐;
    恰 1 个 NN batch;eval+no_grad。"""
    import diag_panel as DPv2
    policy = model.policy
    policy.set_training_mode(False)
    obs = _obs_matrix(PANEL8_STATES)
    got = _obs_sha(obs)
    if got != PANEL8_OBS_SHA256:
        raise RuntimeError(
            "panel8 obs SHA %s"
            % got)
    captured = {}

    def hook(_m, _i, out):
        if "raw8" in captured:
            raise RuntimeError(
                "panel hook >1 batch")
        captured["raw8"] = out.\
            detach()
    h = policy.action_net.\
        register_forward_hook(
            hook)
    try:
        with th.no_grad():
            view = policy.\
                get_distribution(
                    obs)
            raw = captured.get(
                "raw8")
            if raw is None or raw.\
                    shape != (8, 8):
                raise RuntimeError(
                    "raw8 %r"
                    % (None if raw
                       is None
                       else raw.shape))
            rows = []
            for i, (rem, sv,
                    q) in enumerate(
                        PANEL8_STATES):
                row = DPv2._row(
                    tag, rem, sv,
                    DPv2._Subview(
                        view, i),
                    raw[i])
                # 实际 q 行(_row 默认 q1)
                row["q"] = float(q)
                row["obs"] = [
                    1.0, 0.0, float(q),
                    float(sv), 0.0,
                    math.asinh(40.0) / 4.0,
                    rem / 128.0,
                    32.0 / 128.0]
                rows.append(row)
    finally:
        h.remove()
    rep = {
        "tag": tag,
        "obs_canon_sha256":
            PANEL8_OBS_SHA256,
        "n_forwards": 1,
        "rows": rows}
    # 复用已验质量核(两组总和/域)
    DPv2._check_rows(rep)
    # 辅助目标 latent 均值读出保留
    with th.no_grad():
        m_ = rebal_cond_mean_raw(raw)
    for i in range(len(rows)):
        rows[i][
            "aux_cond_mean_w"] = \
            float(m_[i])
    return rep


def aux_inputs():
    """恰 4 合法 flat H32 输入+固定 SHA 门。"""
    states = [(32, 1, 1.0),
              (32, 1, 0.75),
              (32, -1, 1.0),
              (32, -1, 0.75)]
    obs = _obs_matrix(states)
    got = _obs_sha(obs)
    if got != AUX_OBS_SHA256:
        raise RuntimeError(
            "aux obs SHA %s"
            % got)
    y = th.tensor(
        [float(np.sign(s_ * q_))
         for _, s_, q_ in
         states],
        dtype=th.float32)
    return states, obs, y, got


def reset_ppo_adam(model):
    """仅清空 PPO Adam state;param_groups 不变核。"""
    sd = model.policy.optimizer .state_dict()
    groups_before = copy.deepcopy(
        sd["param_groups"])
    sd["state"] = {}
    model.policy.optimizer .load_state_dict(sd)
    got = model.policy.optimizer .state_dict()
    if len(got["state"]) != 0:
        raise RuntimeError(
            "Adam state not empty")
    if got["param_groups"] != groups_before:
        raise RuntimeError(
            "param_groups changed")
    return True


def _les_copy(model):
    """model._last_episode_starts 的 None 或
    array 副本(防原地变更漏检)。"""
    v = getattr(model,
                "_last_episode_starts",
                None)
    if v is None:
        return None
    arr = (v.detach().cpu().numpy()
           if hasattr(v, "detach")
           else np.asarray(v))
    return arr.copy()


def _state_snapshot(model, env):
    return {
        "torch": th.get_rng_state(),
        "numpy":
            np.random.get_state(),
        "python":
            random.getstate(),
        "env_rng":
            env.rng.getstate(),
        "env_id": id(env),
        "last_obs":
            getattr(model,
                    "_last_obs",
                    None),
        "ep_flag":
            getattr(env,
                    "_terminated",
                    None),
        "last_episode_starts":
            _les_copy(model)}


def _state_same(a, b):
    if not th.equal(
            a["torch"], b["torch"]):
        return False
    if not SX._np_eq(
            a["numpy"],
            b["numpy"]):
        return False
    if a["python"] != b["python"]:
        return False
    if a["env_rng"] != b["env_rng"]:
        return False
    if a["env_id"] != b["env_id"]:
        return False
    if a["last_obs"] is not b["last_obs"]:
        return False
    if a["ep_flag"] != b["ep_flag"]:
        return False
    la = a["last_episode_starts"]
    lb = b["last_episode_starts"]
    if (la is None) != (lb is None):
        return False
    if la is not None:
        if la.shape != lb.shape:
            return False
        if la.dtype != lb.dtype:
            return False
        if not np.array_equal(la, lb):
            return False
    return True


def run(out_dir, spec_path=None,
        loader=None, builder=None,
        learner=None, clock=None,
        traces=None,
        inner_eval=None,
        aux_runner=None,
        panel_runner=None,
        initial_sig_ref=None):
    spec_path = spec_path or os.path.join(
            _HERE,
            "RUNSPEC_DIR.json")
    if sha256_file(spec_path) != RUNSPEC_SHA256:
        raise RuntimeError(
            "RUNSPEC_DIR SHA")
    spec = json.load(open(
        spec_path,
        encoding="utf-8"))
    os.makedirs(out_dir,
                exist_ok=False)
    marker = os.path.join(
        out_dir,
        "RUNNING.marker")
    fd = os.open(
        marker,
        os.O_CREAT | os.O_EXCL
        | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(
        out_dir, "dirpt.json")
    report = {
        "status": "running",
        "course_gate":
            "not_frozen",
        "steps": {
            "aux_env": 0,
            "ppo": 0,
            "eval": 0},
        "phases": {}}
    book = SC.Book(
        limits={"wall_s": 900.0,
                "cpu_s": 600.0,
                "rss_gib": 1.0},
        clock=clock)
    ledger = SC.StepLedger(
        TOTAL_CAP, report)
    model = None
    try:
        exp = spec[
            "identity_expected"]
        cout = ("/mnt/f/"
                "trading/"
                "seed_contrast_"
                "a1_20261016"
                "_output")
        for name, fname, want in (
                ("B_final",
                 "B_final.zip",
                 exp[
                     "B_final_"
                     "sha256"]),
                ("traces",
                 "traces.json",
                 exp[
                     "traces_"
                     "canon_"
                     "sha256"]),
                ("contrast",
                 "contrast.json",
                 exp[
                     "contrast_"
                     "json_"
                     "sha256"])):
            got = sha256_file(
                os.path.join(
                    cout,
                    fname))
            if got != want:
                raise RuntimeError(
                    "%s SHA"
                    % name)
        # 冻结 pilot run_spec 先消费
        p_spec_path = os.path.join(
                PILOT,
                "run_spec.json")
        p_spec = json.load(
            open(p_spec_path,
                 encoding="utf-8"))
        if sha256_file(
                p_spec_path) != exp[
                    "pilot_run_"
                    "spec_sha256"]:
            raise RuntimeError(
                "pilot spec SHA")
        report["identity"] = R5.collect_identity(
                p_spec)
        eff_B = SC.build_effective_B(
                p_spec, 311002)
        report["only_change"] = SC.diff_against_a1(
                p_spec, eff_B)
        report["refs_ok"] = True
        why, _c, _p = book.checkpoint("refs")
        if why:
            raise RuntimeError(
                "budget(refs)")
        # ---- fresh build+RNG 快照 ----
        build = builder or SC._real_build_b
        th.manual_seed(20261016)
        np.random.seed(20261016
                       % (2 ** 31))
        random.seed(20261016)
        model = build(
            eff_B, eff_B)
        env = model.pilot_env
        sig0 = SC.fresh_signature(
            model)
        ref = initial_sig_ref or json.load(open(
                os.path.join(
                    cout,
                    "contrast."
                    "json"),
                encoding=
                    "utf-8"))[
                "initial_"
                "signature_"
                "B"]
        if not SX.sig_equal_json(
                    sig0, ref):
            raise RuntimeError(
                "initial sig")
        report[
            "initial_sig_"
            "equal_B"] = True
        snap0 = _state_snapshot(
            model, env)
        report[
            "state_after_build"] = "captured"
        # ---- 面板:辅助前 ----
        prun = panel_runner or panel8
        report[
            "panel_pre_aux"] = prun(model,
                 "pre_aux")
        if not _state_same(
                snap0,
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at"
                " pre panel")
        # ---- 预教学(零 env/零随机流) ----
        states, obs, y, canon = aux_inputs()
        report[
            "aux_obs_canon"] = canon
        arun = aux_runner or preteach_actor
        hist = arun(
            model, obs, y,
            AUX_UPDATES,
            book, report)
        report[
            "aux_updates"] = len(hist)
        if len(hist) != AUX_UPDATES:
            raise RuntimeError(
                "aux updates")
        report["steps"][
            "aux_env"] = 0
        _aux_keep_live(report, hist)
        if not _state_same(
                snap0,
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at"
                " aux")
        # ---- Adam 清空+核 ----
        reset_ppo_adam(model)
        # ---- 面板:辅助后 ----
        report[
            "panel_post_aux"] = prun(model,
                   "post_aux")
        snap1 = _state_snapshot(model, env)
        if not _state_same(snap0, snap1):
            raise RuntimeError(
                "state changed at post_aux panel")
        # ---- 主链 PPO ----
        learn = learner or _real_ppo_run
        learn(model, 32768,
              report, ledger,
              book)
        if env.n_steps_env != 32768:
            raise RuntimeError(
                "ppo env steps")
        if int(getattr(
                model, "num_timesteps",
                0)) != 32768:
            raise RuntimeError(
                "num_timesteps %d"
                % model.num_timesteps)
        report["steps"][
            "ppo"] = env.n_steps_env
        oc = getattr(
            model,
            "_pilot_opt_"
            "count", None)
        if not oc or oc["n"] != 1280:
            raise RuntimeError(
                "opt calls %r"
                % (oc and
                   oc["n"]))
        n_up = int(getattr(
            model,
            "_n_updates",
            0))
        if n_up != 320:
            raise RuntimeError(
                "_n_updates %d"
                % n_up)
        report[
            "ppo_counts"] = {
            "env": env.n_steps_env,
            "model": int(
                getattr(
                    model,
                    "num_"
                    "timesteps",
                    0)),
            "n_updates":
                n_up,
            "optimizer":
                int(oc["n"])}
        ck = os.path.join(
            out_dir,
            "DPT_final")
        model.save(ck)
        report[
            "DPT_final_"
            "sha256"] = sha256_file(
                ck + ".zip")
        # ---- 面板:PPO 后 ----
        report[
            "panel_post_ppo"] = prun(model,
                   "post_ppo")
        why, _c, _p = book.checkpoint(
                "post_ppo")
        if why:
            raise RuntimeError(
                "budget(post_"
                "ppo): %s"
                % why)
        # ---- 末评(旁读动作) ----
        tr_list = traces if traces is not None else json.load(open(
                os.path.join(
                    cout,
                    "traces."
                    "json"),
                encoding=
                    "utf-8"))
        canon_tr = hashlib.sha256(
                json.dumps(
                    tr_list,
                    sort_keys=True,
                    separators=(
                        ",", ":"))
                .encode()
            ).hexdigest()
        if canon_tr != exp[
                "traces_canon_"
                "sha256"]:
            raise RuntimeError(
                "trace canon")
        run_eval = inner_eval or SC._eval_on_traces
        actions = []

        orig_policy = model.policy

        class _Cap:
            def predict(
                    self,
                    *args, **kw):
                out = orig_policy.predict(
                        *args, **kw)
                arr = np.asarray(
                        out[0]).reshape(
                            -1)
                if arr.shape[0] != 2:
                    raise RuntimeError(
                        "predict dim %d"
                        % arr.shape[0])
                br, wv = (
                    float(arr[0]),
                    float(arr[1]))
                if not (
                        math.isfinite(br)
                        and math.isfinite(wv)):
                    raise RuntimeError(
                        "non-finite action")
                if br not in (0.0, 1.0):
                    raise RuntimeError(
                        "branch %r" % br)
                if not (-1.0 <= wv <= 1.0):
                    raise RuntimeError(
                        "w %r" % wv)
                actions.append([br, wv])
                return out
        model.policy = _Cap()
        try:
            n_ev = SC._with_action_rng(
                    spec[
                        "seeds"][
                        "eval_"
                        "action"],
                    lambda: run_eval(
                        model,
                        tr_list,
                        report,
                        "eval",
                        ledger,
                        book))
        finally:
            model.policy = orig_policy
            report.setdefault(
                'eval_actions', {})['eval'] = actions
        eps = report.get(
            "eval_episodes",
            [])
        if n_ev != EVAL_CAP_STEPS:
            raise RuntimeError(
                "eval steps %d"
                % n_ev)
        if len(eps) != 128:
            raise RuntimeError(
                "episodes %d"
                % len(eps))
        n_valid = sum(
            1 for e_ in eps
            if e_.get("valid"))
        if n_valid != 128:
            raise RuntimeError(
                "valid %d" % n_valid)
        for e_ in eps:
            nl_ = e_.get("net_log")
            if not math.isfinite(
                    float(nl_)):
                raise RuntimeError(
                    "non-finite net_log")
        # 动作契约:恰 2112·分段=锁 trace
        lens = [len(t["steps"])
                for t in tr_list]
        if len(actions) != \
                EVAL_CAP_STEPS:
            raise RuntimeError(
                "actions %d"
                % len(actions))
        if sum(lens) != len(actions):
            raise RuntimeError(
                "actions vs trace")
        i0 = 0
        for L in lens:
            seg = actions[i0:i0 + L]
            if len(seg) != L:
                raise RuntimeError(
                    "seg short")
            i0 += L
        report["steps"][
            "eval"] = n_ev
        model = None
        report[
            "total_real_"
            "env_steps"] = ledger.total
        if ledger.total != TOTAL_CAP:
            raise RuntimeError(
                "total %d"
                % ledger.total)
        # 首次 final 超限立即 raise
        why, cum, _p = book.checkpoint(
                "final")
        report["phases"] = book.snapshot()
        report[
            "budget_final"] = cum
        if why:
            report[
                "status"] = "failed"
            report.setdefault(
                    "fail_"
                    "reason",
                    "budget("
                    "final):"
                    " %s" % why)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=
                        False)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED"
                    ".marker"))
            raise RuntimeError(
                "budget(final)"
                ": %s" % why)
        report["status"] = "completed"
        with open(rp, "w",
                  encoding=
                      "utf-8") as f:
            json.dump(report,
                      f,
                      indent=1,
                      allow_nan=
                          False)
        why2, cum2, _p = book.checkpoint(
                "post_save")
        if why2:
            report[
                "status"] = "failed"
            report[
                "budget_post_"
                "save"] = cum2
            report.setdefault(
                    "fail_reason",
                    "budget("
                    "post_save)"
                    ": %s"
                    % why2)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=
                        False)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED"
                    ".marker"))
            raise RuntimeError(
                "budget(post_"
                "save): %s"
                % why2)
        os.replace(
            marker,
            os.path.join(
                out_dir,
                "DONE.marker"))
        return report
    except BaseException as exc:
        try:
            report[
                "status"] = "failed"
            report.setdefault(
                "fail_reason",
                repr(exc))
            report["phases"] = book.snapshot()
            if model is not None:
                try:
                    partial = os.path.join(
                            out_dir,
                            "partial"
                            "_failure")
                    model.save(
                        partial)
                    report[
                        "partial_"
                        "sha256"] = sha256_file(
                            partial
                            + ".zip")
                    report[
                        "partial_"
                        "forensics"
                        "_only"] = True
                except BaseException as se:
                    report[
                        "partial_"
                        "save_"
                        "error"] = repr(se)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") as f:
                json.dump(
                    report, f,
                    indent=1,
                    allow_nan=
                        False)
        except BaseException:
            pass
        try:
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED"
                    ".marker"))
        except BaseException:
            pass
        raise


def _real_ppo_run(model, total,
                  report, ledger,
                  book):
    env = model.pilot_env
    oc = {"n": 0}
    R5._wrap_optimizer(
        model.policy.optimizer,
        book, oc)
    model._pilot_opt_count = oc
    cbk = R5._make_guard_callback(
            book, env)
    counter = SC._EnvCounter(
        env, ledger)
    SC._attach_counter(
        cbk, counter)
    try:
        model.learn(
            total_timesteps=
                int(total),
            reset_num_timesteps=
                True,
            callback=cbk,
            progress_bar=False)
    except BaseException:
        try:
            counter.sync()
        except BaseException as ce:
            report.setdefault(
                "ppo_sync_error",
                repr(ce))
        raise
    counter.sync()


def main(argv=None):
    ap = argparse.ArgumentParser(
            description=
                "dir preteach")
    ap.add_argument(
        "out_dir")
    ap.add_argument(
        "--spec",
        default=os.path.join(
            _HERE, "RUNSPEC_DIR.json"))
    ap.add_argument(
        "--mode",
        choices=[
            "official"],
        default="official")
    a = ap.parse_args(
        argv)
    if a.mode != "official":
        raise SystemExit(
            "unknown mode")
    run(a.out_dir, a.spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main())
