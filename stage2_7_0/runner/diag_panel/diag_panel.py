# -*- coding: utf-8 -*-
"""diag_panel v2 — 初末两档×4 对称 flat 观测解析分布面板
(PREPARED_NOT_RUN;准备期零真实权重读取/零真实 forward)。

v2(审查方 4133):
- _SampleDist 显式切片方法(merged_atom_logp/interior_log_mass),
  修 getattr 透传导致四题同取第 0 题;
- interior 拆分:beta_survival_Z=Beta 保留比例;
  interior_category_mass I=mix_cont×Z(内部类别质量);
  存条件三原子+I、P_H、P_R×(A−/A0/A+)、P_R×I;
  条件组 A−+A0+A++I≈1 与无条件组 P_H+P_R·Σ≈1 双校验
  (工程容差 1e-6,禁 renormalize 掩盖);
- 真实链:set_training_mode(False)+全读数 th.no_grad;
  hook 每档恰 1 次;观测 4×8 float32 little-endian C 序 128B
  独立 SHA 钉 effc181a…;solvency float32=1.095545768737793;
  raw/参数/概率有限+α/β 现有域(≥1 且有限);
  HOLD mode 必须 w=0;
- budget_final 先入报告再写成功 JSON;
- 派生均值/半差=8 行纯后处理,零新增前向。
"""
import argparse
import hashlib
import json
import math
import os
import resource
import sys
import time

import numpy as np
import torch as th

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _HERE)


def repo_src_path():
    env = os.environ.get("PILOT_REPO_SRC")
    if env and os.path.isdir(env):
        return env
    return os.path.abspath(os.path.join(
        _HERE, "..", "freqai-rl-audit",
        "stage2_7_0", "src"))


_REPO_SRC = repo_src_path()
for _p in (_REPO_SRC,
           os.path.join(_REPO_SRC, "rl_posctl",
                        "skill_p0")):
    if os.path.isdir(_p) and _p not in sys.path:
        sys.path.insert(0, _p)

STATUS = "PREPARED_NOT_RUN"
CONFIG_NAME = "CONFIG_diag.json"
CONFIG_SHA256 = "548290931755e28032f0ca45067c1d932a3f3029e189c573b1fd625eb301055c"
OBS_BYTES_SHA256 = ("effc181a119709d6a156d24dfbf9604fd"
                    "6080f817d870fd09cc9aee444122e9b")
SOLV_F32 = 1.095545768737793
SPEC_FILE = ("/mnt/f/trading/"
             "teaching_pilot_prep_20261016/"
             "run_spec.json")
CKPTS = {
    "initial": ("/mnt/f/trading/"
                "unified_teaching_pilot_a1_"
                "20261016_output/initial.zip"),
    "final": ("/mnt/f/trading/"
              "unified_teaching_pilot_a1_"
              "20261016_output/final.zip")}
REPO_IDENTITY = [
    "rl_posctl/skill_p0/unified_course.py",
    "rl_posctl/skill_p0/p0policy.py",
    "rl_posctl/skill_p0/p0spec.py",
    "rl_posctl/curriculum.py",
    "rl_posctl/ledger.py",
    "rl_posctl/env.py"]
BUDGET = {"wall_s": 60.0, "cpu_s": 30.0,
          "rss_gib": 1.0}
STATES = [(32, 1), (32, -1), (1, 1), (1, -1)]
TOL = 1e-6


def sha256_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for c in iter(lambda: f.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


def make_obs(rem, s):
    return [1.0, 0.0, 1.0, float(s),
            0.0, math.asinh(40.0) / 4.0,
            rem / 128.0, 32.0 / 128.0]


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
        rss = (resource.getrusage(
            resource.RUSAGE_SELF).ru_maxrss
               / (1024.0 * 1024.0))
        self.phases.setdefault(phase, {}).update(
            {"wall_s": wall, "cpu_s": cpu,
             "rss_gib": rss})
        why = None
        if wall > self.limits["wall_s"]:
            why = "wall_clock"
        elif cpu > self.limits["cpu_s"]:
            why = "cpu"
        elif rss > self.limits["rss_gib"]:
            why = "rss"
        return why, {"wall_s": wall, "cpu_s": cpu,
                     "rss_gib": rss}, dict(self.phases)

    def snapshot(self):
        return dict(self.phases)


def collect_identity(cfg):
    root = repo_src_path()
    repo = {rel: sha256_file(os.path.join(root, rel))
            for rel in REPO_IDENTITY}
    exp = cfg["pins"].get("repo", {})
    for k, v in exp.items():
        if repo.get(k) != v:
            raise RuntimeError("repo SHA mismatch %s" % k)
    return repo


def _row(tag, rem, s, view, raw8_row):
    """单行(样本 i):view=_Subview(分布,i);raw8_row=hook 同次。"""
    d = view.dist
    blp = float(d.branch_logp.flatten()[0])
    blp2 = float(d.branch_logp.flatten()[1])
    mlp = d.mix_logp[0].tolist()
    atoms = th.exp(d.merged_atom_logp())[0].tolist()
    I = float(th.exp(d.interior_log_mass())[0])
    beta_z = float(d.Z[0])
    p_h = math.exp(blp)
    p_r = math.exp(blp2)
    a_m, a0, a_p = atoms
    mode = view.mode()
    mode_v = [float(mode[0, 0]),
              float(mode[0, 1])]
    if mode_v[0] == 0.0 and mode_v[1] != 0.0:
        raise RuntimeError(
            "HOLD mode must carry w=0 (got %r)"
            % mode_v[1])
    alpha = float(d.alpha[0])
    beta = float(d.beta[0])
    for name, v in (("alpha", alpha),
                    ("beta", beta)):
        if not (math.isfinite(v) and v >= 1.0):
            raise RuntimeError(
                "%s outside domain %r" % (name, v))
    for v in [p_h, p_r, a_m, a0, a_p, I, beta_z]:
        if not math.isfinite(v):
            raise RuntimeError("non-finite prob")
    for v in raw8_row:
        if not math.isfinite(float(v)):
            raise RuntimeError("non-finite raw8")
    cond_sum = a_m + a0 + a_p + I
    uncond = p_h + p_r * (a_m + a0 + a_p + I)
    flat = p_h + p_r * a0
    return {
        "ckpt": tag, "rem": rem, "s": s,
        "obs": make_obs(rem, s),
        "raw8": [float(x) for x in raw8_row],
        "branch_logp": [blp, blp2],
        "branch_probs": [p_h, p_r],
        "mix_logp": mlp,
        "mix_probs": [math.exp(x) for x in mlp],
        "alpha": alpha, "beta": beta,
        "merged_atoms_conditional": {
            "A_minus": a_m, "A_zero": a0,
            "A_plus": a_p},
        "beta_survival_Z": beta_z,
        "interior_category_mass": I,
        "P_hold": p_h, "P_rebal": p_r,
        "P_R_minus": p_r * a_m,
        "P_R_zero": p_r * a0,
        "P_R_plus": p_r * a_p,
        "P_R_interior": p_r * I,
        "effective_flat": flat,
        "mode": mode_v,
        "checks": {
            "cond_atoms_plus_I": cond_sum,
            "uncond_total": uncond,
            "flat_identity_absdiff": abs(
                flat - (p_h + p_r * a0))}}


def _check_rows(report):
    """工程容差 1e-6;禁 renormalize。"""
    for r in report["rows"]:
        c = r["checks"]
        if abs(c["cond_atoms_plus_I"] - 1.0) > TOL:
            raise RuntimeError(
                "row %s rem%d s%+d cond sum %r"
                % (r["ckpt"], r["rem"], r["s"],
                   c["cond_atoms_plus_I"]))
        if abs(c["uncond_total"] - 1.0) > TOL:
            raise RuntimeError(
                "row %s rem%d s%+d uncond %r"
                % (r["ckpt"], r["rem"], r["s"],
                   c["uncond_total"]))
        if c["flat_identity_absdiff"] > 1e-15:
            raise RuntimeError("flat identity")


class _Subview:
    """单样本视图(样本 i);显式切片方法防
    getattr 透传 batch 方法取错行。"""

    def __init__(self, view, i):
        self._view = view
        self._i = i

    def mode(self):
        return self._view.mode()[self._i:self._i + 1]

    @property
    def dist(self):
        return _SampleDist(self._view.dist, self._i)


class _SampleDist:
    def __init__(self, dist, i):
        self._d = dist
        self._i = i

    def merged_atom_logp(self):
        return self._d.merged_atom_logp()[
            self._i:self._i + 1]

    def interior_log_mass(self):
        return self._d.interior_log_mass()[
            self._i:self._i + 1]

    def __getattr__(self, n):
        v = getattr(self._d, n)
        if isinstance(v, th.Tensor) and v.shape[0] > self._i:
            return v[self._i:self._i + 1]
        return v


def _diagnostics(rows):
    by = {(r["ckpt"], r["rem"], r["s"]): r for r in rows}
    out = {"per_rem": {},
           "note": ("形状指标 (α−β)/(α+β) 仅共同正偏/"
                    "方向敏感度诊断,非精确执行正概率"
                    "或最优仓位;派生量=8 行纯后处理")}
    for rem in (32, 1):
        blk = {}
        for s in (1, -1):
            ri = by[("initial", rem, s)]
            rf = by[("final", rem, s)]
            blk["s%+d" % s] = {
                "dP_hold": rf["P_hold"] - ri["P_hold"],
                "dP_R0": rf["P_R_zero"] - ri["P_R_zero"],
                "dP_eff_flat":
                    rf["effective_flat"]
                    - ri["effective_flat"],
                "atom_pos_minus_neg_final":
                    rf["merged_atoms_conditional"]["A_plus"]
                    - rf["merged_atoms_conditional"]["A_minus"],
                "atom_pos_minus_neg_init":
                    ri["merged_atoms_conditional"]["A_plus"]
                    - ri["merged_atoms_conditional"]["A_minus"],
                "shape_r_final": (rf["alpha"] - rf["beta"])
                / (rf["alpha"] + rf["beta"]),
                "shape_r_init": (ri["alpha"] - ri["beta"])
                / (ri["alpha"] + ri["beta"])}
        rfp = blk["s+1"]["shape_r_final"]
        rfn = blk["s-1"]["shape_r_final"]
        out["per_rem"][rem] = {
            **blk,
            "shape_symmetric_mean": 0.5 * (rfp + rfn),
            "shape_half_diff": 0.5 * (rfp - rfn)}
    return out


def run(out_dir, cfg_path=None, loader=None,
        clock=None, get_dist=None):
    os.makedirs(out_dir, exist_ok=False)
    marker = os.path.join(out_dir, "RUNNING.marker")
    fd = os.open(marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    os.close(fd)
    rp = os.path.join(out_dir, "diag_panel.json")
    report = {"status": "running",
              "course_gate": "not_frozen",
              "rows": [], "n_loads": 0,
              "n_forwards": 0, "n_hooks": 0}
    book = Book(clock=clock)
    try:
        cpath = cfg_path or os.path.join(_HERE, CONFIG_NAME)
        got_cfg = sha256_file(cpath)
        if got_cfg != CONFIG_SHA256:
            raise RuntimeError("CONFIG SHA mismatch: %s" % got_cfg)
        cfg = json.load(open(cpath, encoding="utf-8"))
        report["config_sha256"] = got_cfg
        report["identity"] = {"repo": collect_identity(cfg)}
        report["spec_sha256"] = sha256_file(SPEC_FILE)
        if report["spec_sha256"] != cfg["pins"]["spec_sha256"]:
            raise RuntimeError("spec SHA mismatch")
        ck_sha = {}
        for tag, path in CKPTS.items():
            ck_sha[tag] = sha256_file(path)
            if ck_sha[tag] != cfg["pins"]["ckpt_%s" % tag]:
                raise RuntimeError("ckpt %s SHA mismatch" % tag)
        report["ckpt_sha256"] = ck_sha
        # 观测字节身份(4×8 float32 little-endian C 序 128B)
        obs_np = np.array(
            [make_obs(r, s) for r, s in STATES],
            dtype="<f4", order="C")
        obs_bytes = obs_np.tobytes(order="C")
        obs_sha = hashlib.sha256(obs_bytes).hexdigest()
        if obs_sha != OBS_BYTES_SHA256:
            raise RuntimeError("obs bytes SHA %s" % obs_sha)
        if float(obs_np[0, 5]) != SOLV_F32:
            raise RuntimeError("solvency f32 %r" % obs_np[0, 5])
        report["obs_identity"] = {
            "shape": [4, 8], "dtype": "float32",
            "byteorder": "little", "order": "C",
            "nbytes": len(obs_bytes),
            "sha256": obs_sha,
            "solvency_f32": float(obs_np[0, 5])}
        why, _c, _p = book.checkpoint("identity")
        if why:
            raise RuntimeError("budget(identity): %s" % why)
        load = loader
        if load is None:
            from stable_baselines3 import PPO
            load = PPO.load
        gd = get_dist
        obs = th.from_numpy(obs_np.copy())
        for tag in ("initial", "final"):
            model = load(CKPTS[tag], device="cpu")
            report["n_loads"] += 1
            policy = model.policy
            policy.set_training_mode(False)
            captured = {}
            hooks_before = report["n_hooks"]

            def hook(mod, inp, out):
                report["n_hooks"] += 1
                captured["raw8"] = out.detach().cpu().numpy()
            h = policy.action_net.register_forward_hook(hook)
            try:
                with th.no_grad():
                    if gd is not None:
                        view = gd(policy, obs)
                    else:
                        view = policy.get_distribution(obs)
                    raw = captured.get("raw8")
                    if raw is None or raw.shape != (4, 8):
                        raise RuntimeError(
                            "hook raw8 shape %r"
                            % (None if raw is None else raw.shape))
                    for i, (r, s) in enumerate(STATES):
                        report["rows"].append(_row(
                            tag, r, s,
                            _Subview(view, i), raw[i]))
            finally:
                h.remove()
            report["n_forwards"] += 1
            if report["n_hooks"] - hooks_before != 1:
                raise RuntimeError(
                    "hooks per ckpt %d"
                    % (report["n_hooks"] - hooks_before))
            why, _c, _p = book.checkpoint("batch_" + tag)
            if why:
                raise RuntimeError("budget(batch_%s): %s"
                                   % (tag, why))
        if len(report["rows"]) != 8:
            raise RuntimeError("rows %d != 8" % len(report["rows"]))
        _check_rows(report)
        report["diagnostics"] = _diagnostics(report["rows"])
        why, cum, _p = book.checkpoint("pre_save")
        report["budget_final"] = cum
        report["status"] = "completed"
        with open(rp, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=1, allow_nan=False)
        why2, cum2, _p = book.checkpoint("post_save")
        if why2:
            report["status"] = "failed"
            report["budget_post_save"] = cum2
            report.setdefault("fail_reason",
                              "budget(post_save): %s" % why2)
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1, allow_nan=False)
            os.replace(marker, os.path.join(out_dir, "FAILED.marker"))
            raise RuntimeError("budget(post_save): %s" % why2)
        os.replace(marker, os.path.join(out_dir, "DONE.marker"))
        return report
    except BaseException as exc:
        try:
            report["status"] = "failed"
            report.setdefault("fail_reason", repr(exc))
            report["phases"] = book.snapshot()
            with open(rp, "w", encoding="utf-8") as f:
                json.dump(report, f, indent=1, allow_nan=False)
        except BaseException:
            pass
        try:
            os.replace(marker, os.path.join(out_dir, "FAILED.marker"))
        except BaseException:
            pass
        raise


def main(argv=None):
    ap = argparse.ArgumentParser(description="diag panel")
    ap.add_argument("out_dir")
    ap.add_argument("--config",
                    default=os.path.join(_HERE, CONFIG_NAME))
    a = ap.parse_args(argv)
    run(a.out_dir, cfg_path=a.config)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
