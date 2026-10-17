# -*- coding: utf-8 -*-
"""entropy_arm v2 — 有限单因素臂执行器(PREPARED_NOT_RUN)。

v2(审查方 4551 四组):
1. CLI 统一 --mode official;spec 后实际核 B64_final 与旧
   extend.json 引用 SHA(消费,不匹配即拒);
2. 评价捕获透传(原参数/keyword;SB3 第二位是 state);
   np.asarray(out[0]).reshape(-1) 核 2 有限数;原样返回,
   零新增 predict;动作分段=锁 trace episode 步长;finally
   恢复 policy(保中断前动作);
3. logger 旁读包 model.train(orig 后记录,finally 恢复/删除
   实例属性),每行标 timesteps/_n_updates/ent_coef;续段预期
   32 条≤64,末条含最终值;
4. ent 修改前硬核 from==0.001;真实 helper 语义 32768/False/
   原counter/失败sync;成功失败均保 ent_rows;ent_log 保存
   失败→整体非零失败(不以 SX DONE 称成功)。
"""
import argparse
import hashlib
import json
import math
import os
import sys

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
EXT_DIR = os.environ.get(
    "SEED_EXTEND_DIR",
    "/mnt/f/trading/seed_extend_prep_20261017")
for _p in (_HERE, EXT_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import seed_extend as SX  # noqa: E402
import seed_contrast as SC  # noqa: E402
import runner as R5  # noqa: E402

STATUS = "PREPARED_NOT_RUN"
RUNSPEC_SHA256 = "74766f658cc52f463391c1989bd47d90a6680a2b4f56005068e5513bd9816c8d"
ENT_FROM_EXPECT = 0.001
ENT_TO = 0.010
ENT_LOG_CAP = 64
ENT_KEYS = ("train/entropy_loss",
            "train/approx_kl",
            "train/clip_fraction")
B64_FINAL_SHA256 = "0cae31518d7caa63ae563c444e12b6963f1330d29aa694f0697d0f9272b8cdc9"
EXTEND_JSON_SHA256 = ("3badfb2cec17a7a4697e01f0"
                      "f944cca70f02e65d560a115"
                      "1504f6b90bd1a512b")


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


EXT_OUT_DIR = ("/mnt/f/trading/"
                "seed_extend_a1_"
                "20261017_output")


def verify_refs(spec):
    exp = spec["identity_expected"]
    cout = exp["contrast_out_dir"]
    for name, base, fname, want in (
            ("B64_final", EXT_OUT_DIR,
             "B64_final.zip",
             B64_FINAL_SHA256),
            ("extend.json",
             EXT_OUT_DIR,
             "extend.json",
             EXTEND_JSON_SHA256),
            ("B_final", cout,
             "B_final.zip",
             exp[
                 "B_final_sha256"]),
            ("traces", cout,
             "traces.json",
             exp[
                 "traces_canon_sha256"])):
        got = sha256_file(
            os.path.join(base,
                         fname))
        if got != want:
            raise RuntimeError(
                "%s SHA %s"
                % (name, got))
    return True


def set_ent_coef(model, value):
    old = float(model.ent_coef)
    if abs(old - ENT_FROM_EXPECT) > 1e-12:
        raise RuntimeError(
            "ent_coef from %r != %r"
            % (old, ENT_FROM_EXPECT))
    model.ent_coef = float(value)
    got = float(model.ent_coef)
    if got != float(value):
        raise RuntimeError(
            "ent_coef set %r" % got)
    return old, got


def _row_from_logger(n2v, model):
    row = {}
    for k in ENT_KEYS:
        v = n2v.get(k)
        if v is not None:
            row[k] = float(v)
    row["_timesteps"] = int(
        getattr(model, "num_timesteps", 0))
    row["_n_updates"] = int(
        getattr(model, "_n_updates", 0))
    row["_ent_coef"] = float(
        getattr(model, "ent_coef",
                float("nan")))
    return row


def wrap_train_recorder(model, ent_rows):
    """临时包 model.train:orig 返回后旁读 logger(≤64);
    finally 恢复原属性(原无实例属性则 del)。"""
    had_instance = "train" in model.__dict__
    orig = model.__dict__.get("train")

    def wrapped(*a, **k):
        if orig is not None:
            r = orig(*a, **k)
        else:
            r = type(model).train(
                model, *a, **k)
        lg = getattr(model, "logger",
                     None)
        n2v = getattr(
            lg, "name_to_value",
            None)
        if n2v is not None and \
                len(ent_rows) < ENT_LOG_CAP:
            ent_rows.append(
                _row_from_logger(
                    n2v, model))
        return r

    def restore():
        if had_instance:
            model.__dict__[
                "train"] = orig
        else:
            model.__dict__.pop(
                "train", None)
    model.train = wrapped
    return restore


def make_continue_learner(ent_rows):
    """真实续训 helper(SX 语义):唯一 counter/
    32768/False/失败 sync;ent 硬核+train 旁读。"""

    def cont(model, additional,
             report, ledger, book):
        old, new = set_ent_coef(
            model, ENT_TO)
        report["ent_coef_change"] = {
            "from": old, "to": new}
        env = model.pilot_env
        cbk = R5._make_guard_callback(
            book, env)
        counter = SC._EnvCounter(
            env, ledger)
        SC._attach_counter(
            cbk, counter)
        restore = wrap_train_recorder(
            model, ent_rows)
        try:
            model.learn(
                total_timesteps=int(
                    additional),
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
        finally:
            restore()   # train tap 已记正常末条
        counter.sync()
    return cont


def make_eval_capture(inner):
    """评价捕获:predict 原样透传(参数/keyword),
    记录 reshape(-1) 两有限数;finally 恢复;
    按锁 trace episode 步长分段。"""

    def wrapped(model, traces,
                report, tag,
                ledger, book):
        flat = []
        orig = model.policy

        class _Cap:
            def predict(self,
                        *args, **kw):
                out = orig.predict(
                    *args, **kw)
                arr = np.asarray(
                    out[0]).reshape(-1)
                if arr.shape[0] != 2:
                    raise RuntimeError(
                        "predict dim %d"
                        % arr.shape[0])
                for x in arr:
                    if not math.\
                            isfinite(\
                                float(x)):
                        raise RuntimeError(
                            "non-finite "
                            "action")
                br = float(arr[0])
                w = float(arr[1])
                if br not in (0.0, 1.0):
                    raise RuntimeError(
                        "branch %r" % br)
                if not (-1.0 <= w <= 1.0):
                    raise RuntimeError(
                        "w %r" % w)
                flat.append([br, w])
                return out
        model.policy = _Cap()
        try:
            n = inner(model, traces,
                      report, tag,
                      ledger, book)
        finally:
            report.setdefault(
                "eval_actions_partial",
                {})[tag] = list(flat)
            model.policy = orig
        # 分段:按 traces 步长
        lens = [len(t["steps"])
                for t in traces]
        segs = []
        i = 0
        for L in lens:
            segs.append(flat[i:i + L])
            i += L
        if i != len(flat):
            raise RuntimeError(
                "actions %d vs seg %d"
                % (len(flat), i))
        report.setdefault(
            "eval_actions",
            {})[tag] = segs
        valid_n = sum(
            1 for e in report.get(
                tag + "_episodes", [])
            if e.get("valid"))
        if valid_n == len(lens) and \
                n is not None:
            if len(flat) != n:
                raise RuntimeError(
                    "actions %d != steps"
                    " %d" % (len(flat),
                             n))
        return n
    return wrapped


def run(out_dir, spec_path=None,
        loader=None, builder=None,
        replay_learner=None,
        clock=None, traces=None,
        panel_fn=None,
        inner_eval=None,
        set_ent=None,
        initial_sig_ref=None,
        kw_cont=None):
    spec_path = spec_path or os.path.join(
            _HERE, "RUNSPEC_ENT.json")
    if sha256_file(spec_path) != RUNSPEC_SHA256:
        raise RuntimeError(
            "RUNSPEC_ENT SHA")
    spec = json.load(open(
        spec_path, encoding="utf-8"))
    verify_refs(spec)   # 引用门(消费)
    ent_rows = []
    if kw_cont is not None:
        def cont(model, add, r, l, b):
            st = set_ent or set_ent_coef
            old, new = st(
                model, ENT_TO)
            r["ent_coef_change"] = {
                "from": old,
                "to": new}
            restore = wrap_train_recorder(
                    model, ent_rows)
            try:
                return kw_cont(
                    model, add, r,
                    l, b)
            finally:
                restore()
    else:
        cont = make_continue_learner(
            ent_rows)
    inner = inner_eval or SC._eval_on_traces
    _sx_old = SX.RUNSPEC_SHA256
    SX.RUNSPEC_SHA256 = RUNSPEC_SHA256
    try:
        try:
            rep = SX.run(
                out_dir, spec_path,
                loader=loader,
                builder=builder,
                replay_learner=\
                    replay_learner,
                continue_learner=cont,
                clock=clock,
                traces=traces,
                eval_runner=make_eval_capture(
                        inner),
                panel_fn=panel_fn,
                initial_sig_ref=initial_sig_ref)
            sx_failed = False
        except BaseException:
            sx_failed = True
            raise
    finally:
        SX.RUNSPEC_SHA256 = _sx_old
        # 成功失败均保 ent_rows;日志保存失败仅作辅因,
        # 不覆盖 SX 首因(无 SX primary 时才成整体首因)
        log_save_err = None
        try:
            entp = os.path.join(out_dir, "ent_log.json")
            with open(entp, "w", encoding="utf-8") as f:
                json.dump({"rows": ent_rows,
                           "n": len(ent_rows),
                           "keys": list(ENT_KEYS),
                           "cap": ENT_LOG_CAP},
                          f, indent=1, allow_nan=False)
        except BaseException as se:
            log_save_err = se
            try:
                with open(os.path.join(
                        out_dir,
                        "ENTLOG_SAVE_ERROR.txt"),
                        "w", encoding="utf-8") as f:
                    f.write(repr(se))
            except BaseException:
                pass
        if not sx_failed:
            if log_save_err is not None:
                raise RuntimeError(
                    "ent_log save failed: %r"
                    % log_save_err)
            rep["ent_log_file_sha256"] = sha256_file(entp)
            rep["ent_log_n"] = len(ent_rows)
        elif log_save_err is not None:
            print("ENTLOG_SAVE_SECONDARY: %r"
                  % log_save_err, file=sys.stderr)
    return rep


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="entropy arm")
    ap.add_argument("out_dir")
    ap.add_argument(
        "--spec",
        default=os.path.join(
            _HERE,
            "RUNSPEC_ENT.json"))
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
