# -*- coding: utf-8 -*-
"""h1gate — H1 flat 门控教学臂(PREPARED_NOT_RUN;
按已入库 DESIGN_NOTE_H1FLATGATE_20261017.md v2)。

- 原 MDP/奖励/HOLD/REBAL 语义/P0 分布零修改;
- train=安装版 SB3 PPO.train 逐字副本+唯一插入块
  (锚 loss 行;方向 λ=1·四行 H32 输入+gate λ=1·两行
  flat rem=1 输入,同一总 loss,一次 backward/step,
  零额外 optimizer step);
- L_gate=−mean(log p_flat);p_flat=pH+(1−pH)·p0,
  复用冻结 branch_logp/merged_atom_logp(零原子=
  mix_zero+mix_cont·b0,由冻结分布给出,不重算);
- 256 方向预教学保留整段(4 行,不含 gate);
- post_aux 边界:确定性重建后与已有 auxkeep
  boundary_post_aux.pt 严格比较(参数/Adam/RNG/obs/
  flags)——匹配则标 matched,否则明确**新边界**,
  不伪称同起点;
- 六批面板+32 logger;34880 步;900wall/600CPU/1GiB;
- 原子 writer/独立数据文件/失败首因与标记机制沿用
  ak_reissue(np→原生转换杜绝 float32 事故);
- H1 指标与 H32 方向/实际开仓分列;不扫系数/seed;
- 准备期零真实 forward/rollout/learn。
"""
import argparse
import copy
import hashlib
import inspect
import json
import math
import os
import random
import sys
import types

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
DPT_DIR = os.environ.get(
    "DIR_PRETEACH_DIR",
    "/mnt/f/trading/dir_preteach_prep_20261017")
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
for _p in (_HERE, DPT_DIR, EXT_DIR, SC_DIR, PILOT, DIAG):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import dir_preteach as DP  # noqa: E402
import seed_contrast as SC  # noqa: E402
import seed_extend as SX  # noqa: E402
import runner as R5  # noqa: E402
from stable_baselines3 import PPO  # noqa: E402
from stable_baselines3.common. \
    callbacks import \
    BaseCallback  # noqa: E402

STATUS = "PREPARED_NOT_RUN"
RUNSPEC_SHA256 = "b9841d57213bcfe21454ce5ff3161919502f8bf5c6c36f2ae6fc7846b5bd28b8"
LAM_DIR = 1.0
LAM_GATE = 1.0
PRETEACH_UPDATES = 256
LOGGER_CAP = 32
EVAL_CAP_STEPS = 2112
N_EPISODES = 128
TOTAL_CAP = 34880
PANEL_STEPS = (8192, 16384, 24576, 32768)
# 阈值→(epoch,opt,dir_n,gate_n)
TAP_EXPECT = {8192: (80, 320, 320, 320),
              16384: (160, 640, 640, 640),
              24576: (240, 960, 960, 960),
              32768: (320, 1280, 1280, 1280)}
AUX_SRC_PIN = ("f985e90153ba2ef9ad40f50469f0fb84"
               "ccbed1fe4b35b1bff1f00916b35593f2")
GATE_OBS_SHA256 = "b9fc74f14e17c5698694060d3f312a9e103970284fffe0cbad8ff7bf9fe0768d"
EXISTING_BOUNDARY_PIN = (
    "4cf160e71f72f46ffa7702b0650c12cd"
    "74ff1fed5b036a9c9d3cbc634709d74c")
DIR_OBS_PIN = DP.AUX_OBS_SHA256
AUX_INSERT_MARK_BEGIN = "# H1GATE-BEGIN"
AUX_INSERT_MARK_END = "# H1GATE-END"

LOSS_ANCHOR = (
    "            loss = policy_loss + self.ent_coef * "
    "entropy_loss + self.vf_coef * value_loss\n")

_INSERT = '''            # H1GATE-BEGIN(唯一插入;其余逐字 SB3)
            aux_loss, aux_m = DP.aux_objective_raw(
                DP.actor_raw8(self, self._h1g_obs_dir),
                self._h1g_y)
            self._h1g_dir_n += 1
            if not (bool(th.isfinite(aux_loss))
                    and bool(th.isfinite(aux_m).all())):
                self._h1g_invalid = {
                    "i": self._h1g_dir_n,
                    "term": "dir",
                    "reason": "non-finite"}
                raise RuntimeError(
                    "non-finite dir aux @%d"
                    % self._h1g_dir_n)
            self._h1g_gate_n += 1
            gate_view = self.policy.get_distribution(
                self._h1g_obs_gate)
            lp_flat = log_p_flat_rows(
                gate_view)
            if not bool(th.isfinite(lp_flat).all()):
                self._h1g_invalid = {
                    "i": self._h1g_gate_n,
                    "term": "gate",
                    "reason": "non-finite"}
                raise RuntimeError(
                    "non-finite gate logp @%d"
                    % self._h1g_gate_n)
            gate_loss = -lp_flat.mean()
            self._h1g_tail.append({
                "i": self._h1g_gate_n,
                "p_flat_min": float(
                    th.exp(lp_flat).min().detach())})
            if len(self._h1g_tail) > 3:
                del self._h1g_tail[0]
            loss = loss + self._h1g_lam_dir * aux_loss \\
                + self._h1g_lam_gate * gate_loss
            # H1GATE-END
'''


def _dedent8(src):
    lines = src.splitlines(True)
    pad = len(lines[0]) - len(lines[0].lstrip())
    return "".join(l[pad:] if l.strip() else l
                   for l in lines)


def strip_insert(src):
    i = src.find(AUX_INSERT_MARK_BEGIN)
    j = src.find(AUX_INSERT_MARK_END)
    assert 0 < i < j
    i0 = src.rfind("\n", 0, i) + 1
    return src[:i0] + src[
        j + len(AUX_INSERT_MARK_END) + 1:]


def _build_train():
    src = _dedent8(inspect.getsource(PPO.train))
    assert src.count(LOSS_ANCHOR) == 1
    new_src = src.replace(LOSS_ANCHOR,
                          LOSS_ANCHOR + _INSERT)
    import gymnasium.spaces as _gsp
    import torch.nn.functional as _F
    from stable_baselines3.common. \
        utils import \
        explained_variance as _ev
    ns = {"DP": DP, "spaces": _gsp,
          "th": th, "np": np, "F": _F,
          "explained_variance": _ev,
          "log_p_flat_rows":
              log_p_flat_rows}
    exec(compile(new_src,
                 "<h1gate_train>", "exec"), ns)
    return ns["train"], new_src


ORIG_TRAIN_SRC = _dedent8(
    inspect.getsource(PPO.train))


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20),
                      b""):
            h.update(c)
    return h.hexdigest()


def gate_inputs():
    """两行合法 flat rem=1(s±,q=1,c=1,g=0,
    solv40;其余编码同 H32 锚点)+固定 SHA 门。"""
    states = [(1, 1, 1.0), (1, -1, 1.0)]

    def mk(rem, s, q):
        return [1.0, 0.0, float(q), float(s),
                0.0, math.asinh(40.0) / 4.0,
                rem / 128.0, 32.0 / 128.0]
    obs = th.tensor(
        [mk(*st) for st in states],
        dtype=th.float32)
    got = hashlib.sha256(
        obs.detach().numpy()
        .astype("<f4").tobytes()).hexdigest()
    if got != GATE_OBS_SHA256:
        raise RuntimeError(
            "gate obs SHA %s" % got)
    return states, obs, got


def log_p_flat_rows(view):
    """复用冻结分布面:P0DistView 只透传 .dist/.arm;
    arm 必须是冻结 B;log p_flat=logaddexp(logpH,
    logpREBAL+logA0);A0=底层 merged_atom_logp 冻结值
    (mix_zero+mix_cont·b0,不重算)。"""
    arm = getattr(view, "arm", None)
    if arm != "B":
        raise RuntimeError(
            "H1 gate requires frozen "
            "B distribution")
    d = view.dist
    blp = d.branch_logp
    atoms = d.merged_atom_logp()
    return th.logaddexp(
        blp[:, 0], blp[:, 1] + atoms[:, 1])


H1G_TRAIN, H1G_TRAIN_SRC = _build_train()


def params_digest(model):
    h = hashlib.sha256()
    sd = model.policy.state_dict()
    for k in sorted(sd):
        t = sd[k]
        h.update(k.encode())
        h.update(np.asarray(
            t.detach().cpu().numpy()
            if hasattr(t, "detach")
            else t).tobytes())
    return h.hexdigest()


class SerializationError(Exception):
    pass


def to_native(v, path="$"):
    if v is None or isinstance(v, (bool, str)):
        return v
    if isinstance(v, int):
        return int(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise SerializationError(
                {"path": path,
                 "kind": "non-finite",
                 "value": repr(v)})
        return float(v)
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        f = float(v)
        if not math.isfinite(f):
            raise SerializationError(
                {"path": path,
                 "kind": "non-finite",
                 "value": repr(v)})
        return f
    if isinstance(v, np.ndarray):
        if v.ndim:
            return [to_native(x, path + "[]")
                    for x in v.reshape(-1)]
        return to_native(v.item(), path)
    if isinstance(v, dict):
        return {str(k): to_native(
            x, path + "." + str(k))
            for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [to_native(
            x, path + "[%d]" % i)
            for i, x in enumerate(v)]
    raise SerializationError(
        {"path": path,
         "kind": "unknown-type",
         "type": type(v).__name__})


def atomic_write_json(obj, out_path):
    obj = to_native(obj, path="$receipt")
    text = json.dumps(obj, ensure_ascii=False,
                      indent=1, allow_nan=False)
    tmp = out_path + ".tmp.%d" % os.getpid()
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)


def _clone(obj):
    def rec(v):
        if th.is_tensor(v):
            return v.detach().clone()
        if isinstance(v, dict):
            return {k: rec(x)
                    for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(rec(x) for x in v)
        return copy.deepcopy(v)
    return rec(obj)


def _same_deep(a, b):
    if th.is_tensor(a) or th.is_tensor(b):
        if not (th.is_tensor(a)
                and th.is_tensor(b)):
            return False
        if a.dtype != b.dtype:
            return False
        if a.shape != b.shape:
            return False
        return bool(th.equal(a, b))
    if isinstance(a, dict) and \
            isinstance(b, dict):
        if set(a) != set(b):
            return False
        return all(_same_deep(a[k], b[k])
                   for k in a)
    if isinstance(a, (list, tuple)) and \
            isinstance(b, (list, tuple)):
        if type(a) is not type(b) or \
                len(a) != len(b):
            return False
        return all(_same_deep(x, y)
                   for x, y in zip(a, b))
    if isinstance(a, np.ndarray) or \
            isinstance(b, np.ndarray):
        if not (isinstance(a, np.ndarray)
                and isinstance(b, np.ndarray)):
            return False
        if a.dtype != b.dtype or \
                a.shape != b.shape:
            return False
        return bool(np.array_equal(a, b))
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a) and \
                math.isnan(b):
            return True
    return a == b


def semantic_boundary_state(state):
    """跨运行语义比较:仅剔除 env_id 过程
    地址;其余全值+shape+dtype 保留。"""
    value = _clone(state)
    if isinstance(value, dict):
        value.pop("env_id", None)
    return value


def boundary_save(model, out_dir):
    """新臂 post_aux 边界存档+回读核
    (live 全值保护,auxkeep 模式)。"""
    pre_live = DP._state_snapshot(
        model, model.pilot_env)
    pre_val = _clone(pre_live)
    payload = {
        "params": _clone(
            model.policy.state_dict()),
        "optimizer": _clone(
            model.policy.optimizer.
            state_dict()),
        "state": _clone(pre_live),
        "lam_dir": LAM_DIR,
        "lam_gate": LAM_GATE}
    os.makedirs(str(out_dir),
                exist_ok=True)
    path = os.path.join(
        out_dir, "boundary_h1gate.pt")
    th.save(payload, path)
    expected_payload = _clone(payload)
    blob = th.load(
        path, weights_only=False)
    post_live = DP._state_snapshot(
        model, model.pilot_env)
    if not DP._state_same(
            pre_live, post_live):
        raise RuntimeError(
            "load polluted live "
            "(identity)")
    if not _same_deep(
            pre_val, post_live):
        raise RuntimeError(
            "load polluted live "
            "(values)")
    if not _same_deep(
            blob, expected_payload):
        raise RuntimeError(
            "boundary blob mismatch")
    if not _same_deep(
            model.policy.state_dict(),
            expected_payload[
                "params"]):
        raise RuntimeError(
            "live params != expected")
    if not _same_deep(
            model.policy.optimizer.
            state_dict(),
            expected_payload[
                "optimizer"]):
        raise RuntimeError(
            "live optimizer != "
            "expected")
    return {"path": path,
            "sha256":
                sha256_file(path)}


def boundary_compare(model,
                     existing_pt):
    """与已有 auxkeep post_aux 边界严格比较:
    参数/Adam/RNG/obs/flags 全部一致才 matched;
    否则明确新边界。只读比较,零状态污染。"""
    if not os.path.exists(
            existing_pt):
        return {"matched": False,
                "boundary":
                    "post_aux_new",
                "reason":
                    "existing pt absent",
                "existing_sha256":
                    None}
    got = sha256_file(existing_pt)
    pre_live = DP._state_snapshot(
        model, model.pilot_env)
    pre_val = _clone(pre_live)
    # load 前克隆完整 live
    # params/optimizer(污染证)
    pre_params = _clone(
        model.policy.state_dict())
    pre_optimizer = _clone(
        model.policy.optimizer.
        state_dict())
    blob = th.load(
        existing_pt,
        weights_only=False)
    post_live = DP._state_snapshot(
        model, model.pilot_env)
    if not DP._state_same(
            pre_live, post_live):
        raise RuntimeError(
            "compare polluted live "
            "(identity)")
    if not _same_deep(
            pre_val, post_live):
        raise RuntimeError(
            "compare polluted live "
            "(values)")
    if not _same_deep(
            model.policy.state_dict(),
            pre_params):
        raise RuntimeError(
            "compare polluted live "
            "(params)")
    if not _same_deep(
            model.policy.optimizer.
            state_dict(),
            pre_optimizer):
        raise RuntimeError(
            "compare polluted live "
            "(optimizer)")
    ok_p = _same_deep(
        blob.get("params"),
        model.policy.state_dict())
    ok_o = _same_deep(
        blob.get("optimizer"),
        model.policy.optimizer.
        state_dict())
    ok_s = _same_deep(
        semantic_boundary_state(
            blob.get("state")),
        semantic_boundary_state(
            pre_live))
    matched = bool(ok_p and ok_o
                   and ok_s)
    return {"matched": matched,
            "boundary":
                "post_aux_matched"
                if matched
                else "post_aux_new",
            "existing_sha256": got,
            "params_equal": ok_p,
            "optimizer_equal": ok_o,
            "state_equal": ok_s}


def _panel_eval(model, prun, tag):
    pre_id = DP._state_snapshot(
        model, model.pilot_env)
    pre_val = _clone(pre_id)
    was = model.policy.training
    model.policy.set_training_mode(False)
    try:
        out = prun(model, tag)
    finally:
        model.policy.set_training_mode(was)
    post = DP._state_snapshot(
        model, model.pilot_env)
    if not DP._state_same(pre_id, post):
        raise RuntimeError(
            "panel state identity "
            "changed @%s" % tag)
    if not _same_deep(pre_val, post):
        raise RuntimeError(
            "panel state values "
            "changed @%s" % tag)
    return out


def install_h1gate(model, obs_dir, y,
                   obs_gate, book, report,
                   panels_out, logger_rows,
                   prun,
                   lam_dir=LAM_DIR,
                   lam_gate=LAM_GATE):
    """绑定 augmented train+post-update tap。"""
    if DP.sha256_file(os.path.join(
            DPT_DIR,
            "dir_preteach.py")) != \
            AUX_SRC_PIN:
        raise RuntimeError(
            "dir_preteach src pin")
    model._h1g_obs_dir = obs_dir
    model._h1g_y = y
    model._h1g_obs_gate = obs_gate
    model._h1g_lam_dir = float(lam_dir)
    model._h1g_lam_gate = \
        float(lam_gate)
    model._h1g_dir_n = 0
    model._h1g_gate_n = 0
    model._h1g_tail = []
    model._h1g_invalid = None
    model._h1g_panels = panels_out
    model._h1g_logger = logger_rows
    model._h1g_book = book
    model._h1g_prun = prun
    old_train = model.train
    aug = types.MethodType(
        H1G_TRAIN, model)

    def _tap_train():
        result = aug()
        _tap(model)
        return result
    model.train = _tap_train
    return {"old_train": old_train}


def _tap(model):
    book = model._h1g_book
    env = model.pilot_env
    n = env.n_steps_env
    if int(getattr(model,
                   "num_timesteps",
                   0)) != n:
        raise RuntimeError(
            "num_timesteps %d != env %d"
            % (int(getattr(model,
                           "num_timesteps",
                           0)), n))
    oc = getattr(model,
                 "_pilot_opt_count",
                 None)
    oc_n = int(oc["n"]) if oc else -1
    ep = int(getattr(model,
                     "_n_updates", 0))
    if n in TAP_EXPECT:
        e_w, o_w, d_w, g_w = \
            TAP_EXPECT[n]
        if (ep, oc_n,
                model._h1g_dir_n,
                model._h1g_gate_n) != \
                (e_w, o_w, d_w, g_w):
            raise RuntimeError(
                "tap counts @%d: %r"
                % (n, (ep, oc_n,
                       model._h1g_dir_n,
                       model.
                       _h1g_gate_n)))
        model._h1g_panels[
            "panel_at_%d" % n] = \
            _panel_eval(
                model, model._h1g_prun,
                "p%d" % n)
        if n == 32768:
            model._h1g_panels[
                "param_hash_32768"] = \
                params_digest(model)
    lg = getattr(model, "logger", None)
    n2v = getattr(lg,
                  "name_to_value",
                  None) or {}
    row = {"env_steps": n,
           "values": dict(n2v)}
    rows = model._h1g_logger
    rows.append(row)
    if len(rows) > LOGGER_CAP:
        del rows[0]
    why, _c, _p = book.checkpoint(
        "tap_%d" % n)
    if why:
        raise RuntimeError(
            "budget(tap_%d): %s"
            % (n, why))


def _sanitize(rows):
    out = []
    for r in rows:
        rr = dict(r)
        vals = rr.get("values", {})
        rr["values"] = {
            k: (float(v)
                if isinstance(
                    v, (int, float))
                and math.isfinite(
                    float(v))
                else None)
            for k, v in
            vals.items()}
        out.append(rr)
    return out


def _sync_counts(model, report):
    if model is None:
        return
    env = getattr(model,
                  "pilot_env", None)
    oc = getattr(model,
                 "_pilot_opt_count",
                 None)
    report["counts_sync"] = {
        "env": int(env.n_steps_env)
        if env else None,
        "model": int(getattr(
            model,
            "num_timesteps", 0)),
        "epoch": int(getattr(
            model, "_n_updates", 0)),
        "optimizer_success":
            int(oc["n"])
            if oc else None,
        "dir_attempted":
            int(getattr(model,
                        "_h1g_dir_n",
                        0)),
        "gate_attempted":
            int(getattr(model,
                        "_h1g_gate_n",
                        0)),
        "invalid":
            getattr(model,
                    "_h1g_invalid",
                    None),
        "gate_tail": _sanitize(
            list(getattr(
                model,
                "_h1g_tail", [])))}


def run(out_dir, spec_path=None,
        clock=None, traces=None,
        inner_eval=None,
        preteach=None,
        panel_runner=None,
        boundary_saver=None,
        boundary_comparer=None,
        builder=None,
        initial_sig_ref=None):
    spec_path = spec_path or \
        os.path.join(
            _HERE, "RUNSPEC_H1GATE.json")
    if sha256_file(
            spec_path) != \
            RUNSPEC_SHA256:
        raise RuntimeError(
            "RUNSPEC SHA")
    spec = json.load(open(
        spec_path, encoding="utf-8"))
    os.makedirs(out_dir,
                exist_ok=False)
    marker = os.path.join(
        out_dir, "RUNNING.marker")
    fd = os.open(
        marker,
        os.O_CREAT | os.O_EXCL
        | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(
        out_dir, "h1gate.json")
    report = {
        "status": "running",
        "course_gate": "not_frozen",
        "source_design": (
            "DESIGN_NOTE_"
            "H1FLATGATE_20261017"
            ".md(68efe51b…)"),
        "objective_changed": (
            "PPO+1.0*方向辅助(4 行 H32)"
            "+1.0*gate(2 行 flat rem1);"
            "剂量 4→6 行如实计数;"
            "不冒称原净 log 单目标"),
        "steps": {"aux_env": 0,
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
    panels_out = {}
    logger_rows = []
    actions = []
    report["panels"] = panels_out
    report["logger_rows"] = \
        logger_rows
    try:
        exp = spec[
            "identity_expected"]
        cout = ("/mnt/f/trading/"
                "seed_contrast_a1_"
                "20261016_output")
        a1out = ("/mnt/f/trading/"
                 "auxkeep_a1_20261017"
                 "_output")
        for name, path, want in (
                ("B_final",
                 cout + "/B_final.zip",
                 exp[
                     "B_final_sha256"]),
                ("contrast",
                 cout + "/contrast.json",
                 exp[
                     "contrast_json_"
                     "sha256"]),
                ("a2_dirpt",
                 "/mnt/f/trading/"
                 "dir_preteach_a2_"
                 "20261017_output/"
                 "dirpt.json",
                 exp[
                     "a2_dirpt_"
                     "sha256"]),
                ("existing_"
                 "boundary",
                 a1out +
                 "/boundary_post_"
                 "aux.pt",
                 EXISTING_BOUNDARY_PIN)):
            got = sha256_file(path)
            if got != want:
                raise RuntimeError(
                    "%s SHA" % name)
        p_spec_path = os.path.join(
            PILOT, "run_spec.json")
        p_spec = json.load(open(
            p_spec_path,
            encoding="utf-8"))
        if sha256_file(
                p_spec_path) != \
                exp[
                    "pilot_run_spec_"
                    "sha256"]:
            raise RuntimeError(
                "pilot spec SHA")
        report["identity"] = \
            R5.collect_identity(
                p_spec)
        eff_B = SC.\
            build_effective_B(
                p_spec, 311002)
        report["only_change"] = \
            SC.diff_against_a1(
                p_spec, eff_B)
        build = builder or SC._real_build_b
        th.manual_seed(20261016)
        np.random.seed(
            20261016 % (2 ** 31))
        random.seed(20261016)
        model = build(
            eff_B, eff_B)
        env = model.pilot_env
        sig0 = SC.fresh_signature(
            model)
        ref = initial_sig_ref or \
            json.load(open(
                os.path.join(
                    cout,
                    "contrast.json"),
                encoding="utf-8"))[
                "initial_signature_"
                "B"]
        if not SX.sig_equal_json(
                sig0, ref):
            raise RuntimeError(
                "initial sig")
        report[
            "initial_sig_"
            "equal_B"] = True
        snap0 = DP._state_snapshot(
            model, env)
        # ---- 输入身份门 ----
        _, obs_dir, y, dir_canon = \
            DP.aux_inputs()
        _, obs_gate, gate_canon = \
            gate_inputs()
        if dir_canon != DIR_OBS_PIN:
            raise RuntimeError(
                "dir obs SHA")
        report["dir_obs_canon"] = \
            dir_canon
        report["gate_obs_canon"] = \
            gate_canon
        prun = panel_runner or \
            DP.panel8
        report["panel_pre_aux"] = \
            _panel_eval(model, prun,
                        "pre_aux")
        if not DP._state_same(
                snap0, DP.
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at pre")
        # ---- 256 方向预教学
        #      (整段保留) ----
        pteach = preteach or \
            DP.preteach_actor
        hist = pteach(
            model, obs_dir, y,
            PRETEACH_UPDATES,
            book, report)
        if len(hist) != \
                PRETEACH_UPDATES:
            raise RuntimeError(
                "preteach n")
        report["preteach_"
               "updates"] = len(hist)
        # ---- Adam 重置+边界 ----
        DP.reset_ppo_adam(model)
        saver = boundary_saver or \
            boundary_save
        report["boundary"] = \
            saver(model, out_dir)
        cmp_fn = boundary_comparer \
            or boundary_compare
        report[
            "boundary_vs_"
            "auxkeep"] = cmp_fn(
                model,
                a1out +
                "/boundary_post_"
                "aux.pt")
        if not DP._state_same(
                snap0, DP.
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at "
                "boundary")
        report["panel_post_aux"] = \
            _panel_eval(model, prun,
                        "post_aux")
        # ---- 绑定+PPO ----
        install_h1gate(
            model, obs_dir, y,
            obs_gate, book, report,
            panels_out, logger_rows,
            prun)
        report["h1gate_"
               "installed"] = True
        _real_ppo_run(
            model, 32768, report,
            ledger, book)
        if env.n_steps_env != 32768:
            raise RuntimeError(
                "ppo env steps")
        report["steps"]["ppo"] = \
            env.n_steps_env
        if int(getattr(
                model,
                "num_timesteps",
                0)) != 32768:
            raise RuntimeError(
                "num_timesteps")
        oc = getattr(
            model,
            "_pilot_opt_count",
            None)
        if not oc or \
                oc["n"] != 1280:
            raise RuntimeError(
                "opt calls")
        if model._h1g_dir_n != 1280:
            raise RuntimeError(
                "dir n %d"
                % model._h1g_dir_n)
        if model._h1g_gate_n != 1280:
            raise RuntimeError(
                "gate n %d"
                % model._h1g_gate_n)
        h_final = params_digest(
            model)
        if panels_out.get(
                "param_hash_"
                "32768") != h_final:
            raise RuntimeError(
                "param hash @32768")
        _sync_counts(model, report)
        why, _c, _p = book.\
            checkpoint(
                "post_ppo")
        if why:
            raise RuntimeError(
                "budget(post_ppo)"
                ": %s" % why)
        ck = os.path.join(
            out_dir, "H1G_final")
        model.save(
            ck, exclude=["train"])
        report[
            "H1G_final_sha256"] = \
            sha256_file(
                ck + ".zip")
        # ---- 末评+动作 ----
        tr_list = traces \
            if traces is not None \
            else json.load(open(
                os.path.join(
                    cout,
                    "traces.json"),
                encoding="utf-8"))
        canon = hashlib.sha256(
            json.dumps(
                tr_list,
                sort_keys=True,
                separators=(",", ":")
            ).encode()).hexdigest()
        if canon != exp[
                "traces_canon_"
                "sha256"]:
            raise RuntimeError(
                "trace canon")
        run_eval = inner_eval or \
            SC._eval_on_traces
        orig_policy = \
            model.policy

        class _Cap:
            def predict(
                    self, *args,
                    **kw):
                out = orig_policy.\
                    predict(
                        *args, **kw)
                arr = np.asarray(
                        out[0]).\
                    reshape(-1)
                if arr.shape[0] != 2:
                    raise RuntimeError(
                        "predict dim")
                br, wv = (
                    float(arr[0]),
                    float(arr[1]))
                if not (
                        math.isfinite(
                            br)
                        and math.
                        isfinite(wv)):
                    raise RuntimeError(
                        "non-finite "
                        "action")
                if br not in \
                        (0.0, 1.0):
                    raise RuntimeError(
                        "branch")
                if not (-1.0 <= wv
                        <= 1.0):
                    raise RuntimeError(
                        "w")
                actions.append(
                    [br, wv])
                return out
        model.policy = _Cap()
        try:
            n_ev = SC.\
                _with_action_rng(
                    4243,
                    lambda: run_eval(
                        model, tr_list,
                        report, "eval",
                        ledger, book))
        finally:
            model.policy = \
                orig_policy
            report.setdefault(
                "eval_actions",
                {})["eval"] = actions
        eps = report.get(
            "eval_episodes", [])
        if n_ev != EVAL_CAP_STEPS:
            raise RuntimeError(
                "eval steps")
        if len(eps) != N_EPISODES:
            raise RuntimeError(
                "episodes")
        n_valid = 0
        for e_ in eps:
            if e_.get(
                    "valid") is \
                    not True:
                continue
            nl_ = e_.get(
                "net_log")
            if nl_ is None:
                raise RuntimeError(
                    "net_log missing")
            if not math.isfinite(
                    float(nl_)):
                raise RuntimeError(
                    "non-finite "
                    "net_log")
            n_valid += 1
        if n_valid != N_EPISODES:
            raise RuntimeError(
                "valid")
        if len(actions) != \
                EVAL_CAP_STEPS:
            raise RuntimeError(
                "actions n")
        lens = [len(t["steps"])
                for t in tr_list]
        if sum(lens) != \
                len(actions):
            raise RuntimeError(
                "actions vs trace")
        report["steps"][
            "eval"] = n_ev
        dig2 = params_digest(model)
        if dig2 != h_final:
            raise RuntimeError(
                "params changed "
                "after eval")
        # ---- 数据文件先落 ----
        atomic_write_json(
            {"boundary_sha256":
             report["boundary"]
             ["sha256"],
             "dir_obs_canon":
             dir_canon,
             "gate_obs_canon":
             gate_canon,
             "action_seed": 4243,
             "n_episodes":
             len(eps),
             "n_actions":
             len(actions),
             "episodes": eps,
             "complete": True},
            os.path.join(
                out_dir,
                "eval_data.json"))
        atomic_write_json(
            actions,
            os.path.join(
                out_dir,
                "eval_actions"
                ".json"))
        model = None
        report[
            "total_real_"
            "env_steps"] = \
            ledger.total
        if ledger.total != \
                TOTAL_CAP:
            raise RuntimeError(
                "total")
        why, cum, _p = book.\
            checkpoint("final")
        report["phases"] = \
            book.snapshot()
        report[
            "budget_final"] = cum
        if why:
            report["status"] = \
                "failed"
            report.setdefault(
                "fail_reason",
                "budget(final)"
                ": %s" % why)
            atomic_write_json(
                report, rp)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED.marker"))
            raise RuntimeError(
                "budget(final)"
                ": %s" % why)
        report["status"] = \
            "completed"
        try:
            atomic_write_json(
                report, rp)
        except SerializationError \
                as se:
            atomic_write_json(
                {"status":
                 "serialization_"
                 "refused",
                 "kind":
                 "h1gate",
                 "diag":
                 se.args[0]},
                rp)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED.marker"))
            raise RuntimeError(
                "serialization "
                "refused")
        # post_save 先于 DONE
        why2, cum2, _p2 = \
            book.checkpoint(
                "post_save")
        if why2:
            report["status"] = \
                "failed"
            report[
                "budget_post_"
                "save"] = cum2
            report.setdefault(
                "fail_reason",
                "budget(post_"
                "save): %s"
                % why2)
            try:
                atomic_write_json(
                    report, rp)
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
    except BaseException \
            as exc:
        is_ser = isinstance(
            exc, SerializationError)
        reraise = exc
        io_errors = []
        try:
            dp = os.path.join(
                out_dir,
                "eval_data.json")
            if actions and not \
                    os.path.exists(
                        dp):
                atomic_write_json(
                    {"complete":
                     False,
                     "fail_reason":
                     repr(exc),
                     "n_actions_"
                     "captured":
                     len(actions)},
                    dp)
        except BaseException \
                as e1:
            io_errors.append(
                "eval_data:"
                + repr(e1))
        try:
            ap_ = os.path.join(
                out_dir,
                "eval_actions"
                ".json")
            if actions and not \
                    os.path.exists(
                        ap_):
                atomic_write_json(
                    actions, ap_)
        except BaseException \
                as e2:
            io_errors.append(
                "eval_actions:"
                + repr(e2))
        if model is not None:
            try:
                partial = os.path.\
                    join(out_dir,
                         "partial_"
                         "failure")
                model.save(
                    partial,
                    exclude=["train"])
            except BaseException:
                pass
        try:
            protect = False
            if os.path.exists(
                    rp):
                try:
                    prev = json.load(
                        open(
                            rp,
                            encoding=
                                "utf-8"))
                    protect = \
                        prev.get(
                            "status"
                        ) in (
                            "failed",
                            "serialization"
                            "_refused")
                except BaseException:
                    protect = False
            if not protect:
                if is_ser:
                    atomic_write_json(
                        {"status":
                         "serialization"
                         "_refused",
                         "kind":
                         "h1gate",
                         "diag":
                         (exc.args[0]
                          if exc.args
                          else repr(
                              exc)),
                         "fail_reason":
                         repr(exc)},
                        rp)
                    reraise = RuntimeError(
                        "serialization "
                        "refused: %r"
                        % (exc.args[0]
                           if exc.args
                           else exc,))
                else:

                    report[
                        "status"] = \
                        "failed"
                    report.setdefault(
                        "fail_reason",
                        repr(exc))
                    _sync_counts(
                        model, report)
                    report[
                        "phases"] = \
                        book.snapshot()
                    if io_errors:
                        report[
                            "io_errors"] \
                            = io_errors
                    try:
                        atomic_write_json(
                            report, rp)
                    except \
                            SerializationError \
                            as se2:
                        atomic_write_json(
                            {"status":
                             "failed",
                             "kind":
                             "h1gate",
                             "fail_reason":
                             repr(exc),
                             "serialization"
                             "_diag":
                             (se2.args[0]
                              if se2.args
                              else repr(
                                  se2))},
                            rp)
        except BaseException \
                as e3:
            pass
        try:
            failed_m = os.path.\
                join(out_dir,
                     "FAILED.marker")
            if not os.path.exists(
                    failed_m):
                if os.path.exists(
                        marker):
                    os.replace(
                        marker,
                        failed_m)
                else:
                    done_m = os.path.\
                        path.join(
                            out_dir,
                            "DONE"
                            ".marker")
                    if os.path.exists(
                            done_m):
                        os.replace(
                            done_m,
                            failed_m)
                    else:
                        with open(
                                failed_m,
                                "w") \
                                as f2:
                            pass
        except BaseException:
            pass
        raise reraise


def _real_ppo_run(model, total,
                  report, ledger,
                  book):
    """guard 原样交 learn。"""
    env = model.pilot_env
    oc = {"n": 0}
    R5._wrap_optimizer(
        model.policy.optimizer,
        book, oc)
    model._pilot_opt_count = oc
    cbk = R5.\
        _make_guard_callback(
            book, env)
    counter = SC._EnvCounter(
        env, ledger)
    SC._attach_counter(
        cbk, counter)
    try:
        model.learn(
            total_timesteps=int(
                total),
            reset_num_timesteps=
                True,
            callback=cbk,
            progress_bar=False)
    except BaseException:
        try:
            counter.sync()
        except BaseException \
                as ce:
            report.setdefault(
                "ppo_sync_error",
                repr(ce))
        raise
    counter.sync()


def main(argv=None):
    ap = argparse.\
        ArgumentParser(
            description=
                "h1 flat gate arm")
    ap.add_argument("out_dir")
    ap.add_argument(
        "--spec",
        default=os.path.join(
            _HERE,
            "RUNSPEC_H1GATE"
            ".json"))
    ap.add_argument(
        "--mode",
        choices=["official"],
        default="official")
    a = ap.parse_args(argv)
    if a.mode != "official":
        raise SystemExit(
            "unknown mode")
    run(a.out_dir, a.spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
