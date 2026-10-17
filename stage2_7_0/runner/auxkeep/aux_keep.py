# -*- coding: utf-8 -*-
"""aux_keep v2 — 持续方向辅助保持臂(PREPARED_NOT_RUN;
按入库 DESIGN_NOTE_AUXKEEP_20261017.md 冻结设计)。

v2(审查方 5055 三组工程接线):
1. 面板时序=**post-update tap**:guard 原样交 learn
   (R5._make_guard_callback+SC._attach_counter,locals/
   on_rollout_end 生命周期保留);薄 tap 包在 augmented
   train **完整返回后**——8192/16384/24576/32768 各核
   epoch/optimizer/aux==80/320/320·160/640/640·240/960/
   960·320/1280/1280(每轮 train 后 40 step);每 train 后
   读一次现有 logger 成 32 行;四点各单批 8 行共六批;
   面板前后核四 RNG/last_obs 身份及值/starts/环境标志,
   finally 恢复 policy.training;32768 参数 hash 与最终
   保存前一致(不新增 final forward)。
2. 边界:reset_ppo_adam **先于**保存(此后不再重置);
   deepcopy 完整参数/完整 Adam/四 RNG/last_obs/starts/
   环境标志/λ=不可变 expected;回读逐项比较结构/dtype/
   shape/全部值(非仅 state 数与 torch RNG);load 后核
   live 未污染;输出参数与完整 optimizer/payload 身份+
   文件 SHA;**仅新臂 post_aux 边界**;AK_final 与
   partial_failure 的 model.save 均 exclude=['train'];
   payload 存 SB3 版本+原 PPO.train 与生成 train 原文/
   SHA(去插入块逐字一致);版本 2.9.0 不升级。
3. learn 前 panels/logger 绑 report;成功/异常收尾同步
   env/model/epoch/optimizer 成功与 aux attempted/tail
   (attempted 可大于成功,不伪填);末评严格 valid is
   True·net_log 缺失/None/非有限均失败(不默认 0)。
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
RUNSPEC_SHA256 = "55f21fc1cab59a58bfe469192276e3c6e1c4ec74c7ea9a5f3b1932a388f84859"
AUXKEEP_LAMBDA = 1.0
PRETEACH_UPDATES = 256
LOGGER_CAP = 32
EVAL_CAP_STEPS = 2112
TOTAL_CAP = 34880
PANEL_STEPS = (8192, 16384, 24576, 32768)
# 阈值→(epoch 轮,optimizer 成功,aux attempted)
TAP_EXPECT = {8192: (80, 320, 320),
              16384: (160, 640, 640),
              24576: (240, 960, 960),
              32768: (320, 1280, 1280)}
AUX_SRC_PIN = ("f985e90153ba2ef9ad40f50469f0fb84"
               "ccbed1fe4b35b1bff1f00916b35593f2")
AUX_INSERT_MARK_BEGIN = "# AUXKEEP-BEGIN"
AUX_INSERT_MARK_END = "# AUXKEEP-END"

LOSS_ANCHOR = (
    "            loss = policy_loss + self.ent_coef * "
    "entropy_loss + self.vf_coef * value_loss\n")

_INSERT = '''            # AUXKEEP-BEGIN(唯一插入;其余逐字 SB3)
            aux_loss, aux_m = DP.aux_objective_raw(
                DP.actor_raw8(self, self._auxkeep_obs),
                self._auxkeep_y)
            self._auxkeep_n += 1
            if not (bool(th.isfinite(aux_loss))
                    and bool(th.isfinite(aux_m).all())):
                self._auxkeep_invalid = {
                    "i": self._auxkeep_n,
                    "reason": ("non-finite aux "
                               "loss/m @%d"
                               % self._auxkeep_n)}
                raise RuntimeError(
                    "non-finite aux @%d"
                    % self._auxkeep_n)
            self._auxkeep_tail.append({
                "i": self._auxkeep_n,
                "loss": float(aux_loss.detach()),
                "margin_min": float(
                    (self._auxkeep_y * aux_m
                     ).detach().min())})
            if len(self._auxkeep_tail) > 3:
                del self._auxkeep_tail[0]
            loss = loss + self._auxkeep_lam * aux_loss
            # AUXKEEP-END
'''


def _dedent8(src):
    lines = src.splitlines(True)
    pad = len(lines[0]) - len(lines[0].lstrip())
    return "".join(l[pad:] if l.strip() else l
                   for l in lines)


def _build_train():
    """从安装版 SB3 PPO.train 逐字生成+唯一插入块。"""
    src = _dedent8(inspect.getsource(PPO.train))
    assert src.count(LOSS_ANCHOR) == 1, "anchor"
    new_src = src.replace(LOSS_ANCHOR,
                          LOSS_ANCHOR + _INSERT)
    import gymnasium.spaces as _gsp
    import torch.nn.functional as _F
    from stable_baselines3.common. \
        utils import \
        explained_variance as _ev
    ns = {"DP": DP, "spaces": _gsp,
          "th": th, "np": np, "F": _F,
          "explained_variance": _ev}
    exec(compile(new_src,
                 "<auxkeep_train>", "exec"), ns)
    return ns["train"], new_src


AUXKEEP_TRAIN, AUXKEEP_TRAIN_SRC = _build_train()
ORIG_TRAIN_SRC = _dedent8(
    inspect.getsource(PPO.train))


def strip_insert(src):
    """去插入块(标记行首到 END 行尾+换行)。"""
    i = src.find(AUX_INSERT_MARK_BEGIN)
    j = src.find(AUX_INSERT_MARK_END)
    assert 0 < i < j
    i0 = src.rfind("\n", 0, i) + 1
    return src[:i0] + src[
        j + len(AUX_INSERT_MARK_END) + 1:]


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20),
                      b""):
            h.update(c)
    return h.hexdigest()


def params_digest(model):
    """确定性参数 digest(键序+tensor 字节)。"""
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


def _clone(obj):
    """deepcopy 且 tensor→clone(不可变 expected)。"""
    def rec(v):
        if th.is_tensor(v):
            return v.detach().clone()
        if isinstance(v, dict):
            return {k: rec(x)
                    for k, x in v.items()}
        if isinstance(v, (list, tuple)):
            return type(v)(
                rec(x) for x in v)
        return copy.deepcopy(v)
    return rec(obj)


def _same_deep(a, b):
    """逐项比较结构/dtype/shape/全部值。"""
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
                and isinstance(b,
                               np.ndarray)):
            return False
        if a.dtype != b.dtype:
            return False
        if a.shape != b.shape:
            return False
        return bool(np.array_equal(a, b))
    # scalar:类型必须一致
    if type(a) is not type(b):
        return False
    if isinstance(a, float):
        if math.isnan(a) and \
                math.isnan(b):
            return True
    return a == b


def _canon(v):
    """optimizer 结构规范字节。"""
    if th.is_tensor(v):
        return v.detach().cpu().\
            numpy().tobytes()
    if isinstance(v, np.ndarray):
        return v.tobytes()
    if isinstance(v, dict):
        out = b""
        for k in sorted(v):
            out += str(k).encode()
            out += _canon(v[k])
        return out
    if isinstance(v, (list, tuple)):
        out = b""
        for x in v:
            out += _canon(x)
        return out
    return repr(v).encode()


def boundary_save(model, out_dir):
    """post_aux 边界(调用前 Adam 已重置):deepcopy
    expected→存档→回读逐项比较→live 未污染核。"""
    pre_live = DP._state_snapshot(
        model, model.pilot_env)
    pre_val = _clone(pre_live)
    expected = {
        "params": _clone(
            model.policy.state_dict()),
        "optimizer": _clone(
            model.policy.optimizer.
            state_dict()),
        "state": _clone(pre_live),
        "lam": AUXKEEP_LAMBDA}
    import stable_baselines3 as _sb3
    payload = dict(expected)
    payload["sb3_version"] = \
        _sb3.__version__
    payload["orig_train_src"] = \
        ORIG_TRAIN_SRC
    payload["gen_train_src"] = \
        AUXKEEP_TRAIN_SRC
    payload["orig_train_sha256"] = \
        hashlib.sha256(
            ORIG_TRAIN_SRC.encode()
        ).hexdigest()
    payload["gen_train_sha256"] = \
        hashlib.sha256(
            AUXKEEP_TRAIN_SRC.encode()
        ).hexdigest()
    # 去插入块逐字一致核(存档时再证)
    if strip_insert(
            AUXKEEP_TRAIN_SRC) != \
            ORIG_TRAIN_SRC:
        raise RuntimeError(
            "train not verbatim")
    if payload["sb3_version"] != \
            "2.9.0":
        raise RuntimeError(
            "sb3 version %s"
            % payload[
                "sb3_version"])
    os.makedirs(str(out_dir), exist_ok=True)
    path = os.path.join(
        out_dir,
        "boundary_post_aux.pt")
    th.save(payload, path)
    # expected=完整 payload 的
    # 独立克隆(值基线)
    expected_payload = \
        _clone(payload)
    # 实际 load 结果与完整
    # expected 逐值比较
    blob = th.load(
        path, weights_only=False)
    post_live = DP._state_snapshot(
        model, model.pilot_env)
    if not DP._state_same(
            pre_live, post_live):
        raise RuntimeError(
            "load polluted live "
            "state (identity)")
    if not _same_deep(
            pre_val, post_live):
        raise RuntimeError(
            "load polluted live "
            "state (values)")
    if not _same_deep(
            blob,
            expected_payload):
        raise RuntimeError(
            "boundary blob "
            "mismatch on reload")
    # live 参数/完整
    # optimizer vs expected
    if not _same_deep(
            model.policy.
            state_dict(),
            expected_payload[
                "params"]):
        raise RuntimeError(
            "live params != "
            "expected on reload")
    if not _same_deep(
            model.policy.
            optimizer.state_dict(),
            expected_payload[
                "optimizer"]):
        raise RuntimeError(
            "live optimizer != "
            "expected on reload")
    if not _same_deep(
            post_live,
            expected_payload[
                "state"]):
        raise RuntimeError(
            "live state != "
            "expected on reload")
    sd = model.policy.state_dict()
    pspec = {
        k: [list(v.shape),
            str(v.dtype)]
        for k, v in sd.items()}
    osd = model.policy.\
        optimizer.state_dict()
    oh = hashlib.sha256()
    for k in sorted(osd):
        v = osd[k]
        oh.update(
            str(k).encode())
        oh.update(_canon(v))
    info = {
        "path": path,
        "params_spec": pspec,
        "optimizer_content_sha256":
            oh.hexdigest(),
        "sha256":
            sha256_file(path),
        "params_digest":
            params_digest(model),
        "optimizer_state_n":
            len(blob["optimizer"]
                ["state"]),
        "payload_identity": {
            "sb3_version":
                payload[
                    "sb3_version"],
            "orig_train_sha256":
                payload[
                    "orig_train_"
                    "sha256"],
            "gen_train_sha256":
                payload[
                    "gen_train_"
                    "sha256"]},
        "note": ("新臂 post_aux 边界;"
                 "不冒称复原旧 a2")}
    return info


def boundary_verify(model,
                    expected):
    """live vs expected 全量核(测试注入篡改用)。
    结构/dtype/shape/全部值+RNG/obs/starts。"""
    if not _same_deep(
            model.policy.state_dict(),
            expected["params"]):
        raise RuntimeError(
            "live params != expected")
    if not _same_deep(
            model.policy.optimizer.
            state_dict(),
            expected["optimizer"]):
        raise RuntimeError(
            "live optimizer != "
            "expected")
    live = DP._state_snapshot(
        model, model.pilot_env)
    if not DP._state_same(
            live, expected["state"]):
        raise RuntimeError(
            "live state != expected")


def _panel_eval(model, prun, tag):
    """六批统一包裹:eval 模式+状态身份与独立值
    快照,finally 恢复 mode 并核无污染。"""
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


def install_auxkeep(model, obs, y,
                    book, report,
                    panels_out,
                    logger_rows,
                    prun,
                    lam=AUXKEEP_LAMBDA):
    """绑定 augmented train+post-update tap;
    固定 4 输入/计数;返回卸载句柄。"""
    if DP.sha256_file(os.path.join(
            DPT_DIR,
            "dir_preteach.py")) != \
            AUX_SRC_PIN:
        raise RuntimeError(
            "dir_preteach src pin")
    model._auxkeep_obs = obs
    model._auxkeep_y = y
    model._auxkeep_lam = float(lam)
    model._auxkeep_n = 0
    model._auxkeep_tail = []
    model._auxkeep_invalid = None
    model._auxkeep_prun = prun
    model._auxkeep_panels = panels_out
    model._auxkeep_logger = logger_rows
    model._auxkeep_book = book
    old_train = model.train
    aug = types.MethodType(
        AUXKEEP_TRAIN, model)

    def _tap_train():
        # augmented train 完整返回
        # (post-update 权重)
        result = aug()
        _tap(model)
        return result
    model.train = _tap_train
    return {"old_train": old_train}


def _tap(model):
    """每轮 train 后:num_timesteps 一致核+
    阈值核对+面板(单批·经 _panel_eval)+
    logger 行+状态核。"""
    book = model._auxkeep_book
    env = model.pilot_env
    n = env.n_steps_env
    if int(getattr(model,
                   "num_timesteps",
                   0)) != n:
        raise RuntimeError(
            "num_timesteps %d != "
            "env %d"
            % (int(getattr(
                      model,
                      "num_"
                      "timesteps",
                      0)), n))
    oc = getattr(model,
                 "_pilot_opt_count",
                 None)
    oc_n = int(oc["n"]) if oc else -1
    ep = int(getattr(model,
                     "_n_updates", 0))
    aux = model._auxkeep_n
    if n in TAP_EXPECT:
        e_w, o_w, a_w = \
            TAP_EXPECT[n]
        if (ep, oc_n, aux) != \
                (e_w, o_w, a_w):
            raise RuntimeError(
                "tap counts @%d: "
                "epoch=%d opt=%d "
                "aux=%d (want %d/"
                "%d/%d)"
                % (n, ep, oc_n, aux,
                   e_w, o_w, a_w))
        was = model.policy.training
        model.policy.\
            set_training_mode(False)
        try:
            model._auxkeep_panels[
                "panel_at_%d" % n] = \
                _panel_eval(
                    model,
                    model.
                    _auxkeep_prun,
                    "p%d" % n)
            if n == 32768:
                model._auxkeep_panels[
                    "param_hash_32768"] \
                    = params_digest(
                        model)
        finally:
            model.policy.\
                set_training_mode(
                    was)
    # logger 行(每 train 一行,≤32)
    lg = getattr(model,
                 "logger", None)
    n2v = getattr(lg,
                  "name_to_value",
                  None) or {}
    row = {"env_steps": n,
           "values": {
               k: (v if math.
                   isfinite(
                       float(v))
                   else str(v))
               for k, v in
               n2v.items()}}
    rows = model._auxkeep_logger
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
    """历史非有限诊断仅转 null/文字,
    保证 JSON 可写;不继续训练。"""
    out = []
    for r in rows:
        rr = dict(r)
        for k in ("loss",
                  "margin_min"):
            v = rr.get(k)
            if v is not None \
                    and not math.\
                    isfinite(v):
                rr[k] = None
        rr.setdefault(
            "note",
            "non-finite values "
            "nullified")
        out.append(rr)
    return out


def _sync_counts(model, report):
    """成功/异常收尾均同步实际计数
    (attempted 可大于成功)。"""
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
            model, "_n_updates",
            0)),
        "optimizer_success":
            int(oc["n"])
            if oc else None,
        "aux_attempted":
            int(getattr(
                model,
                "_auxkeep_n", 0)),
        "aux_invalid":
            getattr(model,
                    "_auxkeep_"
                    "invalid",
                    None),
        "aux_tail": _sanitize(
            list(getattr(
                model,
                "_auxkeep_tail",
                [])))}


def run(out_dir, spec_path=None,
        loader=None, builder=None,
        learner=None, clock=None,
        traces=None, inner_eval=None,
        preteach=None,
        panel_runner=None,
        boundary_saver=None,
        initial_sig_ref=None):
    spec_path = spec_path or \
        os.path.join(
            _HERE,
            "RUNSPEC_"
            "AUXKEEP.json")
    if sha256_file(
            spec_path) != \
            RUNSPEC_SHA256:
        raise RuntimeError(
            "RUNSPEC SHA")
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
        out_dir,
        "auxkeep.json")
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
        limits={
            "wall_s": 900.0,
            "cpu_s": 600.0,
            "rss_gib": 1.0},
        clock=clock)
    ledger = SC.StepLedger(
        TOTAL_CAP, report)
    model = None
    panels_out = {}
    logger_rows = []
    # learn 前绑定(成功/失败
    # 均随 report 落盘)
    report["panels"] = panels_out
    report["logger_rows"] = \
        logger_rows
    try:
        exp = spec[
            "identity_expected"]
        cout = ("/mnt/f/"
                "trading/"
                "seed_contrast_"
                "a1_20261016"
                "_output")
        a2out = ("/mnt/f/trading/"
                 "dir_preteach_a2_20261017_"
                 "output")
        for name, path, want in (
                ("B_final",
                 cout + "/B_final.zip",
                 exp[
                     "B_final_"
                     "sha256"]),
                ("traces",
                 cout + "/traces.json",
                 exp[
                     "traces_"
                     "canon_"
                     "sha256"]),
                ("contrast",
                 cout + "/contrast.json",
                 exp[
                     "contrast_"
                     "json_"
                     "sha256"]),
                ("a2_dirpt",
                 a2out + "/dirpt.json",
                 exp[
                     "a2_dirpt_"
                     "sha256"]),
                ("a2_DPT",
                 a2out + "/DPT_final.zip",
                 exp[
                     "a2_DPT_"
                     "final_"
                     "sha256"])):
            got = sha256_file(path)
            if got != want:
                raise RuntimeError(
                    "%s SHA" % name)
        p_spec_path = \
            os.path.join(
                PILOT,
                "run_spec.json")
        p_spec = json.load(
            open(p_spec_path,
                 encoding=
                     "utf-8"))
        if sha256_file(
                p_spec_path) != \
                exp[
                    "pilot_run_"
                    "spec_sha256"]:
            raise RuntimeError(
                "pilot spec SHA")
        report["identity"] = \
            R5.collect_identity(
                p_spec)
        eff_B = SC.\
            build_effective_B(
                p_spec, 311002)
        report[
            "only_change"] = \
            SC.diff_against_a1(
                p_spec, eff_B)
        build = builder or \
            SC._real_build_b
        th.manual_seed(20261016)
        np.random.seed(
            20261016 % (2 ** 31))
        random.seed(20261016)
        model = build(
            eff_B, eff_B)
        env = model.pilot_env
        sig0 = SC.fresh_signature(
            model)
        ref = initial_sig_ref \
            or json.load(open(
                os.path.join(
                    cout,
                    "contrast."
                    "json"),
                encoding=
                    "utf-8"))[
                "initial_"
                "signature_"
                "B"]
        if not SX.\
                sig_equal_json(
                    sig0, ref):
            raise RuntimeError(
                "initial sig")
        report[
            "initial_sig_"
            "equal_B"] = True
        snap0 = DP.\
            _state_snapshot(
                model, env)
        prun = panel_runner \
            or DP.panel8
        report[
            "panel_pre_aux"] = \
            _panel_eval(model, prun,
                        "pre_aux")
        if not DP._state_same(
                snap0, DP.
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at"
                " pre panel")
        # ---- 预教学 256 ----
        states, obs, y, \
            canon = DP.\
            aux_inputs()
        report[
            "aux_obs_canon"] \
            = canon
        pteach = preteach \
            or DP.\
            preteach_actor
        hist = pteach(
            model, obs, y,
            PRETEACH_UPDATES,
            book, report)
        report[
            "preteach_"
            "updates"] = \
            len(hist)
        if len(hist) != \
                PRETEACH_UPDATES:
            raise RuntimeError(
                "preteach n")
        # ---- Adam 重置
        #      (先于边界) ----
        DP.reset_ppo_adam(
            model)
        # ---- post_aux 边界 ----
        saver = boundary_saver \
            or boundary_save
        report[
            "boundary"] = \
            saver(model,
                  out_dir)
        if not DP._state_same(
                snap0, DP.
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at"
                " boundary")
        report[
            "panel_post_aux"] \
            = _panel_eval(model, prun,
                          "post_aux")
        if not DP._state_same(
                snap0, DP.
                _state_snapshot(
                    model, env)):
            raise RuntimeError(
                "RNG changed at"
                " post panel")
        # ---- auxkeep 绑定
        #      (augmented+tap) ----
        install_auxkeep(
            model, obs, y,
            book, report,
            panels_out,
            logger_rows,
            prun)
        report[
            "auxkeep_"
            "installed"] = True
        report[
            "objective_"
            "changed"] = (
            "PPO+%.1f*aux(同一"
            "总 loss);监督剂量"
            "同时改变(256 预教学"
            "+1280 持续);不冒称"
            "原净 log 单目标"
            % AUXKEEP_LAMBDA)
        # ---- PPO 32768
        #      (guard 原样
        #      交 learn) ----
        learn = learner or \
            _real_ppo_run
        learn(model, 32768,
              report, ledger,
              book)
        if env.n_steps_env != \
                32768:
            raise RuntimeError(
                "ppo env steps")
        report["steps"][
            "ppo"] = \
            env.n_steps_env
        if int(getattr(
                model,
                "num_timesteps",
                0)) != 32768:
            raise RuntimeError(
                "num_timesteps")
        oc = getattr(
            model,
            "_pilot_opt_"
            "count", None)
        if not oc or \
                oc["n"] != 1280:
            raise RuntimeError(
                "opt calls %r"
                % (oc and
                   oc["n"]))
        if model._auxkeep_n != \
                1280:
            raise RuntimeError(
                "aux n %d"
                % model.
                _auxkeep_n)
        # 32768 参数 hash
        # 与最终保存前一致
        h_final = \
            params_digest(model)
        if panels_out.get(
                "param_hash_"
                "32768") != \
                h_final:
            raise RuntimeError(
                "param hash "
                "@32768 != "
                "pre-save")
        _sync_counts(model,
                     report)
        report[
            "ppo_counts"] = {
            "env": env.n_steps_env,
            "model": 32768,
            "n_updates":
                int(getattr(
                    model,
                    "_n_updates",
                    0)),
            "optimizer":
                int(oc["n"]),
            "aux_minibatch":
                model.
                _auxkeep_n}
        report[
            "auxkeep_tail"] = \
            list(model.
                 _auxkeep_tail)
        why, _c, _p = book.\
            checkpoint(
                "post_ppo")
        if why:
            raise RuntimeError(
                "budget(post_"
                "ppo): %s"
                % why)
        # ---- 保存
        #      (exclude train) ----
        ck = os.path.join(
            out_dir,
            "AK_final")
        model.save(
            ck,
            exclude=["train"])
        report[
            "AK_final_"
            "sha256"] = \
            sha256_file(
                ck + ".zip")
        # ---- 末评+动作 ----
        tr_list = traces \
            if traces is not None \
            else json.load(
                open(os.path.
                     join(
                         cout,
                         "traces."
                         "json"),
                     encoding=
                         "utf-8"))
        canon_tr = \
            hashlib.sha256(
                json.dumps(
                    tr_list,
                    sort_keys=
                        True,
                    separators=(
                        ",", ":"))
                .encode()
            ).hexdigest()
        if canon_tr != exp[
                "traces_canon_"
                "sha256"]:
            raise RuntimeError(
                "trace canon")
        run_eval = \
            inner_eval or \
            SC._eval_on_traces
        actions = []
        orig_policy = \
            model.policy

        class _Cap:
            def predict(
                    self,
                    *args,
                    **kw):
                out = orig_policy.\
                    predict(
                        *args,
                        **kw)
                arr = np.asarray(
                        out[0]).\
                    reshape(-1)
                if arr.shape[0] \
                        != 2:
                    raise RuntimeError(
                        "predict dim")
                br, wv = (
                    float(arr[0]),
                    float(arr[1]))
                if not (
                        math.
                        isfinite(br)
                        and math.
                        isfinite(wv)):
                    raise RuntimeError(
                        "non-finite"
                        " action")
                if br not in \
                        (0.0, 1.0):
                    raise RuntimeError(
                        "branch")
                if not (-1.0
                        <= wv
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
            model.policy = \
                orig_policy
            report.setdefault(
                "eval_actions",
                {})["eval"] = \
                actions
        eps = report.get(
            "eval_episodes",
            [])
        if n_ev != \
                EVAL_CAP_STEPS:
            raise RuntimeError(
                "eval steps %d"
                % n_ev)
        if len(eps) != 128:
            raise RuntimeError(
                "episodes %d"
                % len(eps))
        # 严格 valid is True
        # +net_log 必在且有限
        n_valid = 0
        for e_ in eps:
            if e_.get(
                    "valid") is \
                    not True:
                continue
            nl_ = e_.get(
                "net_log",
                None)
            if nl_ is None:
                raise RuntimeError(
                    "net_log "
                    "missing")
            if not math.\
                    isfinite(
                        float(
                            nl_)):
                raise RuntimeError(
                    "non-finite"
                    " net_log")
            n_valid += 1
        if n_valid != 128:
            raise RuntimeError(
                "valid %d"
                % n_valid)
        lens = [len(
            t["steps"])
            for t in tr_list]
        if len(actions) != \
                EVAL_CAP_STEPS:
            raise RuntimeError(
                "actions %d"
                % len(actions))
        if sum(lens) != \
                len(actions):
            raise RuntimeError(
                "actions vs"
                " trace")
        report["steps"][
            "eval"] = n_ev
        model = None
        report[
            "total_real_"
            "env_steps"] = \
            ledger.total
        if ledger.total != \
                TOTAL_CAP:
            raise RuntimeError(
                "total %d"
                % ledger.total)
        why, cum, _p = book.\
            checkpoint(
                "final")
        report["phases"] = \
            book.snapshot()
        report[
            "budget_final"] \
            = cum
        if why:
            report[
                "status"] = \
                "failed"
            report.setdefault(
                "fail_reason",
                "budget(final)"
                ": %s" % why)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") \
                    as f:
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
        report["status"] = \
            "completed"
        with open(rp, "w",
                  encoding=
                      "utf-8") \
                as f:
            json.dump(report,
                      f,
                      indent=1,
                      allow_nan=
                          False)
        why2, cum2, _p = \
            book.checkpoint(
                "post_save")
        if why2:
            report[
                "status"] = \
                "failed"
            report[
                "budget_post_"
                "save"] = cum2
            report.setdefault(
                "fail_reason",
                "budget(post_"
                "save): %s"
                % why2)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") \
                    as f:
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
    except BaseException \
            as exc:
        try:
            report[
                "status"] = \
                "failed"
            # 首因保留
            report.setdefault(
                "fail_reason",
                repr(exc))
            _sync_counts(
                model, report)
            report["phases"] = \
                book.snapshot()
            if model is not None:
                try:
                    partial = \
                        os.path.\
                        join(
                            out_dir,
                            "partial"
                            "_failure")
                    model.save(
                        partial,
                        exclude=[
                            "train"])
                    report[
                        "partial_"
                        "sha256"] = \
                        sha256_file(
                            partial
                            + ".zip")
                    report[
                        "partial_"
                        "forensics"
                        "_only"] = \
                        True
                except BaseException \
                        as se:
                    report[
                        "partial_"
                        "save_"
                        "error"] = \
                        repr(se)
            with open(
                    rp, "w",
                    encoding=
                        "utf-8") \
                    as f:
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
    """guard 原样交 learn(SC._attach_counter
    仅包 _on_step;locals/on_rollout_end 保留)。"""
    env = model.pilot_env
    oc = {"n": 0}
    R5._wrap_optimizer(
        model.policy.optimizer,
        book, oc)
    model._pilot_opt_count \
        = oc
    cbk = R5.\
        _make_guard_callback(
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
                "aux keep arm")
    ap.add_argument(
        "out_dir")
    ap.add_argument(
        "--spec",
        default=os.path.join(
            _HERE, "RUNSPEC_AUXKEEP.json"))
    ap.add_argument(
        "--mode",
        choices=[
            "official"],
        default="official")
    a = ap.parse_args(
        argv)
    if a.mode != \
            "official":
        raise SystemExit(
            "unknown mode")
    run(a.out_dir, a.spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(
        main())
