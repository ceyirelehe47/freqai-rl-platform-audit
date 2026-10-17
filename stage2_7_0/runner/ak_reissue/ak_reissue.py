# -*- coding: utf-8 -*-
"""ak_reissue — a1 final 的独立新评价 receipt 准备件
(PREPARED_NOT_RUN;审查方 5163 冻结口径)。

- 冷载 AK_final.zip(显式 device=cpu),冷载后核参数
  digest==param_hash_32768(44cb8690…78d2a);
- 复用 SC._eval_on_traces+原 trace 顺序与账本;
  SC._with_action_rng(4243);恰 128 题/2112 步;
  零 learn/optimizer/零新锚点面板;
- **该 2112 为新增评价单列**,不称恢复原评价、
  不计入原 34880;
- 预算 180wall/60CPU/1GiB 全调用封顶;
- 序列化:numpy scalar 递归转原生;非有限/未知类型
  **明确拒绝**(诊断字段化→receipt status=serialization_
  refused,**不截断既有文件**);先完整序列化成功→
  同目录临时文件→os.replace 原子写;
- 仅新 receipt(独立文件),绝不覆盖原截断 JSON/
  FAILED.marker/模型;
- 状态依据真实结果(failed/serialization_refused/
  completed 三分)。
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
SC_DIR = os.environ.get(
    "SEED_CONTRAST_DIR",
    "/mnt/f/trading/"
    "seed_contrast_prep_20261016")
PILOT = os.environ.get(
    "SEED_CONTRAST_PILOT",
    "/mnt/f/trading/"
    "teaching_pilot_prep_20261016")
DIAG = os.environ.get(
    "SEED_CONTRAST_DIAG",
    "/mnt/f/trading/"
    "diag_panel_prep_20261016")
EXT_DIR = os.environ.get(
    "SEED_EXTEND_DIR",
    "/mnt/f/trading/"
    "seed_extend_prep_20261017")
for _p in (_HERE, SC_DIR, PILOT, DIAG, EXT_DIR):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

import seed_contrast as SC  # noqa: E402
import runner as R5  # noqa: E402
from stable_baselines3 import \
    PPO  # noqa: E402

STATUS = "PREPARED_NOT_RUN"
RUNSPEC_SHA256 = "48df0d1b24d328861f6f9dbdcd83104c0baacd54424840f84ee475dc6743c55b"
AK_FINAL_PIN = ("c743ba5d68f65addf9f6dad1fcdeb4e"
                "774edc4d3a6d885f79ba0b7cff1149d3a")
PILOT_SPEC_PIN = ("23ce189231b3359765d05af1df1d4403"
                  "d682ce598d17067e952b7d9595b82b47")
PARAM_HASH_PIN = ("44cb869039a5c5502804e575d4936c"
                  "c58ba4e47e2f71d6e4919b1928a3c78d2a")
EVAL_CAP_STEPS = 2112
N_EPISODES = 128
EVAL_ACTION_SEED = 4243
BUDGET = {"wall_s": 180.0,
          "cpu_s": 60.0,
          "rss_gib": 1.0}


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20),
                      b""):
            h.update(c)
    return h.hexdigest()


def params_digest(policy):
    """与 aux_keep.params_digest 同式(键序+tensor
    字节)——冷载后核 final 身份。"""
    h = hashlib.sha256()
    sd = policy.state_dict()
    for k in sorted(sd):
        t = sd[k]
        h.update(k.encode())
        h.update(np.asarray(
            t.detach().cpu().numpy()
            if hasattr(t, "detach")
            else t).tobytes())
    return h.hexdigest()


class SerializationError(Exception):
    """含已诊断字段,不截断既有文件。"""


def to_native(v, path="$"):
    """递归:numpy scalar→原生;非有限/未知类型
    明确拒绝(带诊断 path)。"""
    if v is None or isinstance(
            v, (bool, str)):
        return v
    if isinstance(v, (int,)):
        return int(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise SerializationError(
                {"path": path,
                 "kind":
                     "non-finite",
                 "value": repr(v)})
        return float(v)
    if isinstance(
            v, np.bool_):
        return bool(v)
    if isinstance(
            v, np.integer):
        return int(v)
    if isinstance(
            v, np.floating):
        f = float(v)
        if not math.isfinite(f):
            raise SerializationError(
                {"path": path,
                 "kind":
                     "non-finite",
                 "value": repr(v)})
        return f
    if isinstance(
            v, np.ndarray):
        return [to_native(
                    x,
                    path + "[]")
                for x in
                v.reshape(-1)[:]] \
            if v.ndim else \
            to_native(v.item(),
                      path)
    if isinstance(v, dict):
        return {str(k):
                to_native(
                    x,
                    path + "."
                    + str(k))
                for k, x in
                v.items()}
    if isinstance(v, (list,
                      tuple)):
        return [to_native(
                    x,
                    path + "[%d]"
                    % i)
                for i, x in
                enumerate(v)]
    raise SerializationError(
        {"path": path,
         "kind": "unknown-type",
         "type":
             type(v).
             __name__})


def atomic_write_json(obj, out_path):
    """先完整序列化成功(内存)→同目录临时文件
    →os.replace。序列化失败=零写入。"""
    obj = to_native(obj, path="$receipt")
    text = json.dumps(
        obj, ensure_ascii=False,
        indent=1,
        allow_nan=False)
    tmp = out_path + \
        ".tmp.%d" % os.getpid()
    d = os.path.dirname(
        out_path) or "."
    with open(tmp, "w",
              encoding="utf-8") \
            as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, out_path)


def _strip_objs():
    """custom_objects:反序列化前替换恢复的
    auxkeep 运行时属性为 None/[](避免恢复保存
    的 dir_preteach.panel8 等无关依赖)。"""
    return {
        "pilot_env": None,
        "_auxkeep_prun": None,
        "_auxkeep_book": None,
        "_auxkeep_obs": None,
        "_auxkeep_y": None,
        "_auxkeep_logger": [],
        "_auxkeep_panels": None,
        "_auxkeep_tail": None}


def cold_load(ckpt_zip):
    """显式 cpu 冷载;核文件 SHA+参数 digest;
    custom_objects 清 auxkeep 运行时属性。"""
    if sha256_file(ckpt_zip) != \
            AK_FINAL_PIN:
        raise RuntimeError(
            "AK_final SHA")
    model = PPO.load(
        ckpt_zip, device="cpu",
        custom_objects=
            _strip_objs())
    policy = model.policy
    policy.set_training_mode(False)
    dig = params_digest(policy)
    if dig != PARAM_HASH_PIN:
        raise RuntimeError(
            "param hash %s"
            % dig)
    return model, dig


def run(out_dir,
        spec_path=None,
        clock=None,
        traces=None,
        inner_eval=None,
        builder=None):
    spec_path = spec_path or \
        os.path.join(
            _HERE,
            "RUNSPEC_"
            "AKRE.json")
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
        "ak_reissue.json")
    actions = []
    book = SC.Book(
        limits=BUDGET,
        clock=clock)
    report = {
        "status": "running",
        "kind":
            "reissue_eval_only",
        "source_training_run_"
        "status": "failed",
        "note": ("新增评价单列;"
                 "非原评价恢复;"
                 "不计入原 34880"),
        "course_gate":
            "not_frozen",
        "steps": {"eval": 0},
        "phases": {}}
    model = None
    try:
        ROOT_ = "/mnt/f/trading"
        tr_path = os.path.join(
            ROOT_,
            "seed_contrast_a1_20261016"
            "_output",
            "traces.json")
        tr_list = traces \
            if traces is not None \
            else json.load(open(
                tr_path,
                encoding=
                    "utf-8"))
        canon = hashlib.\
            sha256(json.dumps(
                tr_list,
                sort_keys=True,
                separators=(",", ":")
            ).encode()
            ).hexdigest()
        if canon != spec["inputs"]["traces_canon_sha256"]:
            raise RuntimeError(
                "trace canon")
        ak = os.path.join(
            ROOT_,
            "auxkeep_a1_20261017"
            "_output",
            "AK_final.zip")
        pilot_spec_path = \
            os.path.join(
                PILOT,
                "run_spec.json")
        if sha256_file(
                pilot_spec_path) != \
                PILOT_SPEC_PIN:
            raise RuntimeError(
                "pilot spec SHA")
        p_spec = json.load(open(
            pilot_spec_path,
            encoding="utf-8"))
        report["identity"] = \
            R5.collect_identity(
                p_spec)
        load = builder or \
            cold_load
        model, dig = \
            load(ak)
        why_l, _cl, _pl = \
            book.checkpoint(
                "post_load")
        if why_l:
            raise RuntimeError(
                "budget(post_"
                "load): %s"
                % why_l)
        report[
            "ak_final_"
            "sha256"] = \
            AK_FINAL_PIN
        report[
            "param_hash"] \
            = dig
        ledger = SC.\
            StepLedger(
                EVAL_CAP_STEPS,
                report)
        run_eval = \
            inner_eval or \
            SC._eval_on_traces
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
                    EVAL_ACTION_SEED,
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
            report[
                "eval_"
                "actions"] = \
                actions
        eps = report.get(
            "eval_episodes",
            [])
        if n_ev != \
                EVAL_CAP_STEPS:
            raise RuntimeError(
                "eval steps %d"
                % n_ev)
        if len(eps) != \
                N_EPISODES:
            raise RuntimeError(
                "episodes %d"
                % len(eps))
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
        if n_valid != \
                N_EPISODES:
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
        # eval 后参数不变核
        # (释放前)
        dig2 = params_digest(
            model.policy)
        if dig2 != \
                PARAM_HASH_PIN:
            raise RuntimeError(
                "params changed "
                "after eval: %s"
                % dig2)
        # 原始数据先原子落盘
        # (两个独立文件;失败不丢)
        data = {
            "ak_final_sha256":
                AK_FINAL_PIN,
            "param_hash": dig,
            "traces_canon":
                canon,
            "action_seed":
                EVAL_ACTION_SEED,
            "n_episodes":
                len(eps),
            "n_actions":
                len(actions),
            "episodes":
                eps,
            "complete": True}
        atomic_write_json(
            data,
            os.path.join(
                out_dir,
                "eval_data"
                ".json"))
        atomic_write_json(
            actions,
            os.path.join(
                out_dir,
                "eval_actions"
                ".json"))
        model = None
        why, cum, _p = \
            book.checkpoint(
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
            try:
                atomic_write_json(
                        report,
                        rp)
            except BaseException:
                pass
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
        # 先完整序列化→
        # 原子写(仅新 receipt)
        try:
            atomic_write_json(report, rp)
        except SerializationError \
                as se:
            rep2 = {
                "status":
                    "serialization"
                    "_refused",
                "kind":
                    "reissue_"
                    "eval_only",
                "note":
                    report[
                        "note"],
                "diag":
                    se.args[0],
                "steps":
                    report[
                        "steps"],
                "course_gate":
                    "not_"
                    "frozen"}
            atomic_write_json(
                rep2, rp)
            os.replace(
                marker,
                os.path.join(
                    out_dir,
                    "FAILED"
                    ".marker"))
            raise RuntimeError(
                "serialization "
                "refused: %r"
                % (se.args[0],))
        # post_save 预算门:
        # 超限→failed/RUNNING
        # →FAILED/DONE 尚未
        # 创建;receipt 覆写
        # completed→failed
        why2, cum2, _p2 = \
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
            try:
                atomic_write_json(
                    report, rp)
            except BaseException \
                    as wre:
                report.setdefault(
                    "receipt_write_"
                    "error",
                    repr(wre))
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
        # DONE 仅在 post_save
        # 通过后最后创建
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
        io_errors = []
        # -- 路1:eval_data.json
        # (独立;缺失才写;
        # I/O 错不吞其余) --
        try:
            dp = os.path.join(
                out_dir,
                "eval_data.json")
            if actions and not \
                    os.path.exists(dp):
                atomic_write_json(
                    {"ak_final_sha256":
                     AK_FINAL_PIN,
                     "complete": False,
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
        # -- 路2:eval_actions
        # .json(独立检查/
        # 独立恢复) --
        try:
            ap_ = os.path.join(
                out_dir,
                "eval_actions"
                ".json")
            if actions and not \
                    os.path.exists(ap_):
                atomic_write_json(
                    actions, ap_)
        except BaseException \
                as e2:
            io_errors.append(
                "eval_actions:"
                + repr(e2))
        # -- 路3:receipt(仅
        # 当不存在或为 stale
        # completed 时写;
        # 已落 failed/
        # serialization_
        # refused 首因不覆盖)
        # --
        try:
            protect = False
            if os.path.exists(rp):
                try:
                    prev = json.load(
                        open(rp,
                             encoding=
                                 "utf-8"))
                    st = prev.get(
                        "status")
                    protect = st in (
                        "failed",
                        "serialization"
                        "_refused")
                except BaseException:
                    protect = False
            if not protect:
                report["status"] =                     "failed"
                report.setdefault(
                    "fail_reason",
                    repr(exc))
                report["phases"] = \
                    book.snapshot()
                if io_errors:
                    report[
                        "io_errors"] \
                        = io_errors
                atomic_write_json(
                    report, rp)
        except BaseException \
                as e3:
            io_errors.append(
                "receipt:"
                + repr(e3))
        # -- 路4:marker:
        # RUNNING/遗留 DONE
        # →FAILED(best-effort;
        # 磁盘不可写则保持
        # 失败态由 rc 表达) --
        try:
            failed_m = os.path.                join(out_dir,
                     "FAILED.marker")
            if not os.path.                    exists(
                        failed_m):
                if os.path.                        exists(
                            marker):
                    os.replace(
                        marker,
                        failed_m)
                else:
                    done_m = os.\
                        path.join(
                            out_dir,
                            "DONE"
                            ".marker")
                    if os.path.\
                            exists(
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
        raise


def main(argv=None):
    ap = argparse.\
        ArgumentParser(
            description=
                "ak reissue "
                "eval")
    ap.add_argument(
        "out_dir")
    ap.add_argument(
        "--spec",
        default=os.path.join(
            _HERE, "RUNSPEC_AKRE.json"))
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
